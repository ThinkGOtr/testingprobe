"""Müşteri CI kurulum PR'ını açan uç (014; Ş5 `musteri_ci.kurulum`).

`POST /code/ci-setup` `{platform, dil, onizle?, parametreler{…}}` (`code.ci_setup`):

1. API (core-api) parametreleri doğrular (`musteri_ci.parametre_hatalari`; biçim dışı → 422) ve
   `codegen.kurulum_pr` işini kuyruğa alır. GitHub App kurulum token'ı yalnız core-worker'da
   alınabildiğinden forge'a API'den dokunulmaz (`codegen.dil_algila` ile aynı devir).
2. Worker platformun güncel deposunun forge'unu (GitHub App kurulumu) kurar; taban dal forge'un
   `base_branch`'i (`TP_FORGE_CHECK_REF`, yoksa platformun kontrol dalı). Depo dosya listesinden
   plan çıkarır (`kurulum_plani` + dil iskeleti) ve `kurulum_pr_ac` ile PR'ı açar.
3. İdempotent: kurulum dalında (`tp/kurulum-<platform>-<dil>`) açık PR varsa yeni commit atılmaz,
   var olan PR döner (`durum: mevcut`). Aynı istek aynı dakikada ikinci kez gelirse aynı işi bekler.

`onizle: true` forge'a yazmaz; planı (eklenecek dosyalar, eksikler, elle adımlar) ve açık kurulum
PR'ını döner. Denetim: `musteri_ci.kurulum_pr_acildi` (yeni PR), `musteri_ci.kurulum_pr_mevcut`
(açık PR döndü), `musteri_ci.kurulum_pr_basarisiz` (forge/plan hatası). Onaylayan = isteği yapan
kullanıcı (PR gövdesine "Onaylayan" satırı yazılır).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tp_core.audit import append_audit
from tp_core.features.codegen import depo as depolar
from tp_core.features.codegen import platform as platformlar
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue
from tp_core.workflow.service import Principal

log = logging.getLogger(__name__)

KURULUM_PR_JOB = "codegen.kurulum_pr"
KURULUM_PR_DILIM_S = 60  # aynı istek bu dilimde tek iş (çift tıklama aynı işi bekler)
KURULUM_PR_BEKLEME_S = 20.0  # portal nginx /api/ zaman aşımı 30 sn
KURULUM_PR_ZAMAN_ASIMI_S = 180
SURUYOR = "Kurulum PR'ı hazırlanıyor; birkaç saniye sonra ekranı yenileyin."

# Kullanıcının verebileceği parametreler (platform/dil gövdenin üst düzeyindedir).
_ORTAK = ("varsayilan_dal", "uygulama_koku", "hazirlik_betigi", "node_surumu", "izlenen_kok")
_ANDROID = ("gradle_modulu", "test_paketi", "emulator_api")
_IOS = ("xcode_proje", "sema", "ui_test_hedefi", "runs_on", "simulator", "yapilandirma")
PARAMETRE_ADLARI: frozenset[str] = frozenset((*_ORTAK, *_ANDROID, *_IOS))


class KurulumIstekHatasi(ValueError):
    """İstek doğrulanamadı (422). `hatalar`: alan hataları (Türkçe)."""

    def __init__(self, mesaj: str, hatalar: list[str] | None = None) -> None:
        super().__init__(mesaj)
        self.hatalar = list(hatalar or [mesaj])


def _mci() -> Any:
    from tp_core.features import musteri_ci

    return musteri_ci


def _parametre_hatalari(p: Any) -> list[str]:
    from tp_core.features.musteri_ci.kurulum import parametre_hatalari

    return parametre_hatalari(p)


def taban_dal(platform: str, forge: Any | None = None) -> str:
    """PR'ın hedefi: forge'un `base_branch`'i (GitHub: `TP_FORGE_CHECK_REF`), yoksa platformun
    kontrol dalı (`TP_FORGE_CHECK_REF[_<P>]`, varsayılan `main`)."""
    b = getattr(forge, "base_branch", None) if forge is not None else None
    return str(b).strip() if isinstance(b, str) and b.strip() else depolar.kontrol_ref(platform)


def parametreler(platform: str, dil: str, girdi: Mapping[str, Any] | None) -> Any:
    """Gövde parametrelerinden `KurulumParametreleri` (boş değerler varsayılanı korur; diğer
    platformun alanları yok sayılır). Bilinmeyen alan ya da geçersiz değer `KurulumIstekHatasi`."""
    mci = _mci()
    if not platformlar.musteri_ci_mi(platform, dil):
        raise KurulumIstekHatasi(
            f"{platform}/{dil} müşteri CI hattında değil: kurulum PR'ı yalnız Android Kotlin ve "
            "iOS Swift için açılır"
        )
    girdi = dict(girdi or {})
    bilinmeyen = sorted(set(girdi) - PARAMETRE_ADLARI)
    if bilinmeyen:
        raise KurulumIstekHatasi(f"bilinmeyen kurulum parametresi: {', '.join(bilinmeyen)}")
    gecerli = set(_ORTAK) | set(_ANDROID if platform == "android" else _IOS)
    kw: dict[str, Any] = {}
    for ad, deger in girdi.items():
        if ad not in gecerli or deger is None:
            continue
        if isinstance(deger, str):
            deger = deger.strip()
            if not deger:
                continue
        kw[ad] = deger
    if "emulator_api" in kw:
        try:
            kw["emulator_api"] = int(kw["emulator_api"])
        except (TypeError, ValueError):
            raise KurulumIstekHatasi(
                f"emülatör API düzeyi sayı olmalı: {kw['emulator_api']!r}"
            ) from None
    kw.setdefault("varsayilan_dal", depolar.kontrol_ref(platform))
    p = mci.KurulumParametreleri(platform=platform, dil=dil, **kw)
    hatalar = _parametre_hatalari(p)
    if hatalar:
        raise KurulumIstekHatasi("kurulum parametreleri geçersiz: " + "; ".join(hatalar), hatalar)
    return p


def _param_json(p: Any) -> dict[str, Any]:
    return {f.name: getattr(p, f.name) for f in fields(p)}


def istek(
    session: Session,
    user: Principal,
    platform: str,
    dil: str,
    girdi: Mapping[str, Any] | None,
    *,
    onizle: bool = False,
) -> uuid.UUID:
    """Doğrular ve `codegen.kurulum_pr` işini kuyruğa alır (forge'a dokunmaz). Aynı kullanıcı +
    parametre + kip için `KURULUM_PR_DILIM_S` diliminde tek iş."""
    p = parametreler(platform, dil, girdi)
    yuk = {
        "platform": platform,
        "dil": dil,
        "parametreler": _param_json(p),
        "actor": user.kullanici_adi,
        "onizle": bool(onizle),
    }
    ozet = hashlib.sha256(json.dumps(yuk, sort_keys=True).encode()).hexdigest()[:16]
    dilim = int(time.time() // KURULUM_PR_DILIM_S)
    return enqueue(
        session.connection(),
        KURULUM_PR_JOB,
        yuk,
        idempotency_key=f"{KURULUM_PR_JOB}:{platform}:{dil}:{ozet}:{dilim}",
        max_deneme=1,
        zaman_asimi_s=KURULUM_PR_ZAMAN_ASIMI_S,
    )


def _plan(forge: Any, p: Any, taban: str) -> Any:
    from tp_core.features.codegen.service import _rules_dir
    from tp_core.features.musteri_ci.dil_kancalari import varsayilan_iskelet

    mci = _mci()
    sha = forge.head_sha(taban)
    dosyalar = forge.list_files(ref=sha)

    def oku(yol: str) -> str | None:
        return forge.read_file(yol, ref=sha)

    return mci.kurulum_plani(p, dosyalar, iskelet=varsayilan_iskelet(p, _rules_dir()), oku=oku)


def _plan_ozeti(plan: Any) -> dict[str, Any]:
    return {
        "dal": plan.dal,
        "baslik": plan.baslik,
        "hazir": plan.hazir,
        "dosyalar": sorted(plan.dosyalar),
        "eksikler": [e.aciklama for e in plan.eksikler],
        "elle_adimlar": list(plan.elle_adimlar),
    }


def _pr_json(pr: Any) -> dict[str, Any] | None:
    if pr is None:
        return None
    return {
        "number": pr.number,
        "url": getattr(pr, "url", None),
        "state": getattr(pr, "state", "open"),
        "title": getattr(pr, "title", None),
    }


def calistir(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    """`codegen.kurulum_pr` (core-worker): plan + (onizle değilse) PR. Hata `PermanentJobError`
    (iş düşer; API 409 döner) ve denetime yazılır."""
    from tp_core.features.codegen.service import _forge
    from tp_core.integrations.forge import ForgeError

    mci = _mci()
    yuk = dict(ctx.yuk or {})
    platform, dil = str(yuk.get("platform") or ""), str(yuk.get("dil") or "")
    actor = str(yuk.get("actor") or "")
    onizle = bool(yuk.get("onizle"))
    try:
        p = parametreler(platform, dil, {
            k: v for k, v in dict(yuk.get("parametreler") or {}).items() if k in PARAMETRE_ADLARI
        })  # fmt: skip
    except KurulumIstekHatasi as exc:
        raise PermanentJobError(str(exc)) from exc
    nesne = f"kurulum:{platform}/{dil}"
    try:
        forge = _forge(platform)
        taban = taban_dal(platform, forge)
        plan = _plan(forge, p, taban)
        if onizle:
            mevcut = forge.find_open_pr(plan.dal)
            return {
                "durum": "onizleme",
                "taban": taban,
                **_plan_ozeti(plan),
                "pr": _pr_json(mevcut),
                "kurulum": mci.portal_kurulum(plan, mevcut),
            }
        sonuc = mci.kurulum_pr_ac(forge, plan, onaylayan=actor, base=taban)
    except (ForgeError, mci.MusteriCiHatasi) as exc:
        mesaj = " ".join(str(exc).split())[:300] or type(exc).__name__
        if not onizle:
            with engine.begin() as conn:
                append_audit(
                    conn,
                    actor or "system",
                    "musteri_ci.kurulum_pr_basarisiz",
                    nesne,
                    {"platform": platform, "dil": dil, "hata": mesaj, "tur": type(exc).__name__},
                )
        raise PermanentJobError(f"Kurulum PR'ı açılamadı: {mesaj}") from exc
    if sonuc["durum"] in ("acildi", "mevcut"):
        with engine.begin() as conn:
            append_audit(
                conn,
                actor,
                f"musteri_ci.kurulum_pr_{sonuc['durum']}",
                nesne,
                {
                    "platform": platform,
                    "dil": dil,
                    "pr": sonuc["pr_no"],
                    "dal": sonuc["dal"],
                    "taban": taban,
                    "sha": sonuc["sha"],
                    "dosyalar": sonuc["dosyalar"],
                    "parametreler": _param_json(p),
                },
            )
    kurulum = mci.portal_kurulum(plan, sonuc if sonuc["durum"] != "gereksiz" else None)
    return {
        **{k: v for k, v in sonuc.items() if k != "onaylayan"},
        "taban": taban,
        "baslik": plan.baslik,
        "eksikler": [e.aciklama for e in plan.eksikler],
        "hazir": plan.hazir,
        "kurulum": kurulum,
    }


def mevcut_pr(forge: Any, platform: str, dil: str) -> Any:
    """Çiftin açık kurulum PR'ı (yoksa ya da okunamazsa None). Önizlemenin idempotent gösterimi
    için (`/code/languages` `kurulum`)."""
    mci = _mci()
    try:
        return forge.find_open_pr(f"{mci.KURULUM_DAL_ONEKI}-{platform}-{dil}")
    except Exception:
        log.warning("kurulum PR'ı aranamadı: %s/%s", platform, dil, exc_info=True)
        return None


__all__ = [
    "KURULUM_PR_JOB",
    "KurulumIstekHatasi",
    "calistir",
    "istek",
    "mevcut_pr",
    "parametreler",
    "taban_dal",
]
