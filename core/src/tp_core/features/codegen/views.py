"""`/scripts` yanıtları (portal `Script` / `ScriptDetay` tipleri, review-portal/src/api/types.ts).

core-api forge'a erişmez (`tp_forge` yalnızca core-worker'da): PR bilgisi çekirdeğin
`pull_request` kaydından okunur. Check'ler LocalForge kipinde `TP_ARTIFACTS_PATH/checks/<sha>.json`
dosyasından (yerel CI sonucu, core-api'de salt okunur bağlı), GitHub kipinde core-worker PR
senkronunun (`service.sync_prs`) `pull_request.checks` kolonuna yazdığı kopyadan okunur. GitHub
kopyası yoksa ya da güncel head'e ait değilse (bayat) zorunlu check'ler `pending` sayılır.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from tp_core.config import get_settings
from tp_core.features.codegen.browser import AgentConfig, sayfa_adresi
from tp_core.features.codegen.ozet import ham_cikti, insan_ozeti
from tp_core.features.codegen.service import (
    AJAN_BAYILERI,
    adim5_butce_s,
    dal_engeli,
    merge_kabul_gerekceleri,
    screenshot_url,
)
from tp_core.integrations.forge import (
    GITHUB_REQUIRED_CHECKS,
    LOCAL_REQUIRED_CHECKS,
    REQUIRED_CHECKS_ENV,
    ForgeValidationError,
    parse_required_checks,
)
from tp_core.models import PullRequest, Script, ScriptTestCase, StepMapping
from tp_core.models.codegen_feature import ScriptAdim, ScriptCodegen, ScriptKontrol
from tp_core.workflow.service import content_hash_of

_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_EKRAN_RE = re.compile(r"^codegen/[0-9a-f-]{36}/step-\d{1,4}\.png$")


def required_checks() -> tuple[str, ...]:
    forge = get_settings().forge
    varsayilan = LOCAL_REQUIRED_CHECKS if forge == "local" else GITHUB_REQUIRED_CHECKS
    try:
        return parse_required_checks(os.environ.get(REQUIRED_CHECKS_ENV), varsayilan)
    except ForgeValidationError:
        return tuple(varsayilan)


def read_checks(sha: str | None) -> list[dict[str, Any]]:
    """`checks/<sha>.json` (LocalForge biçimi); yoksa/okunamazsa []."""
    if not sha or not _SHA_RE.match(sha):
        return []
    yol = Path(get_settings().checks_dir) / f"{sha}.json"
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return _gecerli_checkler(veri.get("checks", []) if isinstance(veri, dict) else veri)


def _gecerli_checkler(liste: Any) -> list[dict[str, Any]]:
    if not isinstance(liste, list):
        return []
    return [c for c in liste if isinstance(c, dict) and isinstance(c.get("name"), str)]


def github_checks(sha: str | None, kayit: PullRequest | None) -> list[dict[str, Any]] | None:
    """GitHub kipi: core-worker'ın `pull_request.checks` kopyası. Kopya yoksa ya da `checks_sha`
    istenen head değilse (dal güncellendi, senkron henüz koşmadı) None: durum bilinmiyor."""
    if not sha or kayit is None or kayit.checks is None or kayit.checks_sha != sha:
        return None
    return _gecerli_checkler(kayit.checks)


def script_pr_kaydi(sc: Script) -> PullRequest | None:
    """Script'in PR kaydı (script'in bağlı olduğu oturumdan); oturum yoksa None."""
    if sc.pr_no is None:
        return None
    s = object_session(sc)
    return s.get(PullRequest, sc.pr_no) if s is not None else None


def _check_durumu(c: dict[str, Any]) -> str:
    if c.get("status") != "completed":
        return "pending"
    return {"success": "passed", "skipped": "skipped"}.get(str(c.get("conclusion")), "failed")


def pr_checks(
    sha: str | None, kayit: PullRequest | None = None
) -> tuple[list[dict[str, Any]], str | None, list[str]]:
    """(portal check listesi, ci özeti, zorunlu check engelleri).

    LocalForge: `checks/<sha>.json`. GitHub: `kayit` (PR kaydı) üzerindeki worker kopyası; kopya
    yok/bayatsa zorunlu check'ler `pending` (asla `passed` değil)."""
    zorunlu = required_checks()
    if get_settings().forge == "github":
        ham = github_checks(sha, kayit)
        if ham is None:
            if not sha:
                return [], None, [f"Zorunlu kontrol '{ad}': yok" for ad in zorunlu]
            bekleyen = [
                {
                    "ad": ad,
                    "durum": "pending",
                    "zorunlu": True,
                    "url": None,
                    "aciklama": "GitHub check durumu henüz alınmadı (PR senkronu bekleniyor)",
                }
                for ad in zorunlu
            ]
            return bekleyen, "pending", [f"Zorunlu kontrol '{ad}': pending" for ad in zorunlu]
    else:
        ham = read_checks(sha)
    son: dict[str, dict[str, Any]] = {}
    for c in ham:
        son[c["name"]] = c
    liste = [
        {
            "ad": ad,
            "durum": _check_durumu(c),
            "zorunlu": ad in zorunlu,
            "url": c.get("url"),
            "aciklama": None,
        }
        for ad, c in son.items()
    ]
    engeller = []
    durumlar = []
    for ad in zorunlu:
        c = son.get(ad)
        d = _check_durumu(c) if c else "yok"
        durumlar.append(d)
        if d != "passed":
            engeller.append(f"Zorunlu kontrol '{ad}': {d}")
    if not son:
        ci = None
    elif all(d == "passed" for d in durumlar):
        ci = "passed"
    elif any(d == "failed" for d in durumlar):
        ci = "failed"
    else:
        ci = "pending"
    return liste, ci, engeller


def _pr(session: Session, sc: Script, cg: ScriptCodegen) -> dict[str, Any] | None:
    if sc.pr_no is None:
        return None
    kayit = session.get(PullRequest, sc.pr_no)
    checks, ci, _ = pr_checks(sc.head_sha, kayit)
    return {
        "number": sc.pr_no,
        "url": cg.pr_url,
        "baslik": kayit.baslik if kayit else (cg.baslik or ""),
        "branch": sc.branch or (kayit.branch if kayit else ""),
        "durum": kayit.durum if kayit else ("merged" if sc.durum == "merged" else "open"),
        "ci": ci,
        "icerik_hash": content_hash_of(sc),
        "head_sha": sc.head_sha,
        "checks": checks,
        "forge": get_settings().forge,
        # PR açıklaması (prbody: izlenebilirlik, eşleme, yerel kontrol, denetim zinciri başı).
        # LocalForge'un PR sayfası yoktur; portal bunu "PR açıklaması" olarak gösterir.
        "govde": kayit.govde if kayit else None,
        # Dal main'in gerisinde mi (başka PR merge edildi) ve güncelleme durumu.
        "dal": _dal(cg),
        # Merge bilgisi (portal "Birleştirildi — <kim> · merge commit <sha>"); açık PR'da null.
        "merge_sha": kayit.merge_sha if kayit else None,
        "merge_eden": kayit.merge_eden if kayit else None,
        "merge_zamani": (
            kayit.guncelleme.isoformat() if kayit and kayit.durum == "merged" else None
        ),
    }


def _dal(cg: ScriptCodegen) -> dict[str, Any]:
    d = cg.dal or {}
    return {
        "geride": bool(d.get("geride")),
        "guncelleme": d.get("guncelleme"),
        "neden": d.get("neden"),
        "onceki_head": d.get("onceki_head"),
    }


def _break_verify(sc: Script, cg: ScriptCodegen) -> dict[str, Any]:
    kd = sc.kirma_dogrulama or {}
    asamalar = kd.get("asamalar") or [
        {"ad": ad, "sonuc": "pending", "run_id": None, "zaman": None}
        for ad in ("baseline", "broken", "restored")
    ]
    return {"durum": cg.break_durum, "asamalar": asamalar, "neden": kd.get("neden")}


def serialize(session: Session, sc: Script, cg: ScriptCodegen) -> dict[str, Any]:
    case_ids = [
        str(r)
        for r in session.scalars(
            select(ScriptTestCase.test_case_id).where(ScriptTestCase.script_id == sc.id)
        )
    ]
    yk = cg.yerel_kontrol or {}
    return {
        "id": str(sc.id),
        "case_ids": case_ids,
        "requirement_id": str(cg.requirement_id) if cg.requirement_id else None,
        "requirement_key": cg.story_key,
        "case_ref": f"{cg.story_key or 'SERBEST'}-C{cg.sira_no}",
        "test_key": cg.test_key,
        "baslik": cg.baslik,
        "dosya_yolu": sc.dosya_yolu,
        "branch": sc.branch or "",
        "durum": sc.durum,
        # Faz 4: defect adayı script'in triage sonucu (portal "Triage sonucuna git").
        "failure_id": _triage_failure_id(session, sc),
        "pr": _pr(session, sc, cg),
        "pass_at_1": sc.pass_at_1,
        "zayif_test": sc.zayif_test,
        "break_verify": _break_verify(sc, cg),
        "yerel_sinif": None if yk.get("atlandi") else yk.get("sinif"),
        "mode": cg.uretim_modu,
        "engel": ({"tur": cg.engel_turu, "neden": cg.engel_nedeni} if cg.engel_turu else None),
        "olusturma": sc.olusturma.isoformat(),
        "hata": cg.engel_nedeni,
    }


def list_scripts(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Script, ScriptCodegen)
        .join(ScriptCodegen, ScriptCodegen.script_id == Script.id)
        .order_by(Script.olusturma.desc())
        .limit(200)
    ).all()
    return [serialize(session, sc, cg) for sc, cg in rows]


def _yerel_kontrol(cg: ScriptCodegen) -> dict[str, Any] | None:
    yk = cg.yerel_kontrol
    if not yk:
        return None
    adim = yk.get("adimlar") or {}
    run_status = yk.get("run_status")
    return {
        "tsc": adim.get("tsc"),
        "eslint": adim.get("eslint"),
        "ast_guard": adim.get("ast_guard"),
        "tekrar": int(yk.get("tekrar") or 3),
        "sonuc": run_status if run_status in ("passed", "failed", "error") else None,
        "sinif": None if yk.get("atlandi") else yk.get("sinif"),
        "aciklama": yk.get("aciklama"),
        "run_id": yk.get("run_id"),
        "duzeltme_turu": cg.duzeltme_turu,
        "basarisiz": [
            {
                "test_adi": h.get("test_adi") or "",
                "hata_mesaji": h.get("hata_mesaji"),
                "beklenen": h.get("beklenen"),
                "gerceklesen": h.get("gerceklesen"),
                # Hangi doğrulama (eşleme satırı) ve onaylı case'in hangi cümlesi; tekrar sayısı.
                "eslesme": h.get("eslesme"),
                "kaynak_metin": h.get("kaynak_metin"),
                "tekrar": int(h.get("tekrar") or 1),
            }
            for h in yk.get("basarisiz") or []
        ],
        "atlandi": bool(yk.get("atlandi")),
    }


def merge_engelleri(sc: Script, cg: ScriptCodegen) -> list[str]:
    """Açık PR'ın merge kapısı engelleri. PR yoksa ya da zaten merge edildiyse kapı yoktur: boş
    liste (portal "Merge kapısı" bloğunu göstermez; PR açılmayan defect adayında çelişkili
    "PR merge edilebilir durumda değil" satırı çıkmaz)."""
    engeller: list[str] = []
    if sc.pr_no is None or sc.durum == "merged":
        return engeller
    if sc.durum != "pr_open":
        engeller.append(f"PR merge edilebilir durumda değil (durum: {sc.durum})")
        return engeller
    if cg.break_durum == "running":
        engeller.append("Kırarak doğrulama sürüyor")
    dal = dal_engeli(cg)
    if dal:
        engeller.append(dal)
    _, _, check_engelleri = pr_checks(sc.head_sha, script_pr_kaydi(sc))
    engeller += check_engelleri
    return engeller


def gecikme_uyarisi(sc: Script, adimlar: Sequence[ScriptAdim]) -> str | None:
    """§8.4 adım 5 gecikme bütçesi (120 sn): doğrulama sürerken aşıldıysa REPLAY önerisi."""
    if sc.durum != "verifying" or not adimlar:
        return None
    from datetime import UTC, datetime

    gecen = (datetime.now(UTC) - min(a.zaman for a in adimlar)).total_seconds()
    butce = adim5_butce_s()
    if gecen <= butce:
        return None
    return (
        f"Doğrulama {int(gecen)} sn sürüyor (adım 5 bütçesi {butce} sn aşıldı) — sunum için "
        "REPLAY'e geçmeyi önerin (TP_MODEL_MODE=replay)."
    )


def uyarilar(sc: Script, cg: ScriptCodegen) -> list[str]:
    out: list[str] = []
    if cg.uretim_modu == "replay" and not cg.eslesme:
        out.append(
            "REPLAY kipi: eşleme kayıtlı golden'dan gelecek (hazırlanmış örnek çıktı; canlı model "
            "değil). Tarayıcı adımları çalışan uygulamada koşturuluyor."
        )
    elif cg.uretim_modu in ("replay", "replay_miss"):
        out.append(
            "Eşleme REPLAY kaydından geldi (hazırlanmış örnek çıktı; canlı model değil). Tarayıcı "
            "adımları yine de çalışan uygulamada koşturuldu."
        )
    if sc.durum == "pr_open" and cg.break_durum == "not_started":
        out.append("Kırarak doğrulama henüz yapılmadı (merge öncesi önerilir).")
    if cg.break_durum == "weak":
        out.append("Zayıf test: uygulama kırıldığında test yeşil kaldı.")
    return out


def _adim(sid: Any, a: ScriptAdim, gizli: set[str]) -> dict[str, Any]:
    """Ajan adımı: kısa insan özeti + "Ham çıktı". Eski kayıtlarda (`ham` boş, `ozet` ham araç
    çıktısıydı) özet okuma anında yeniden üretilir; ham metin temizlenip maskelenir."""
    if a.ham or not a.ozet:
        # Temizleme idempotenttir: okuma anında yeniden uygulanır (kural sonradan sıkılaştıysa
        # eski satırlar da temiz görünür; ör. kırpılmış `</untrusted …` parçası).
        aciklama, ham = a.ozet, ham_cikti(a.ham, gizli) if a.ham else a.ham
    else:  # şema öncesi kayıt: ozet = ham MCP çıktısı
        ham = ham_cikti(a.ozet, gizli)
        aciklama = insan_ozeti(
            a.arac, a.arguman or {}, izinli=a.izinli, ok=None, url=sayfa_adresi(ham)
        )
    return {
        "sira": a.sira,
        "tur": a.tur,
        "step_id": "",
        "arac": a.arac,
        "aciklama": aciklama,
        "ham_cikti": ham or None,
        "hata": bool(a.hata),
        "arguman": a.arguman,
        "po": None,
        "method": None,
        "args": [],
        "verified": a.izinli and not a.hata,
        "izinli": a.izinli,
        "ekran_goruntusu_url": screenshot_url(sid, a.sira) if a.ekran_goruntusu else None,
        "zaman": a.zaman.isoformat(),
    }


def _dogrulama_notu(m: StepMapping, ajan_bayileri: dict[str, str]) -> str | None:
    """Ajan bayisiyle doğrulanan giriş satırı: tablo bunu açıkça söyler (bayi1 ≠ bayi3)."""
    if m.beklenen or not m.dogrulandi:
        return None
    bayi = next((a for a in m.argumanlar or [] if isinstance(a, str) and a in ajan_bayileri), None)
    if bayi is None:
        return None
    return f"doğrulandı (ajan bayisi {ajan_bayileri[bayi]} ile; test {bayi} ile koşar)"


def detail(session: Session, sc: Script, cg: ScriptCodegen) -> dict[str, Any]:
    out = serialize(session, sc, cg)
    gizli = {AgentConfig.from_env().agent_password}
    ajan_bayileri = dict((cg.eslesme or {}).get(AJAN_BAYILERI) or {})
    adimlar = session.scalars(
        select(ScriptAdim).where(ScriptAdim.script_id == sc.id).order_by(ScriptAdim.sira)
    ).all()
    eslemeler = session.scalars(
        select(StepMapping).where(StepMapping.script_id == sc.id).order_by(StepMapping.adim_no)
    ).all()
    kontroller = session.scalars(
        select(ScriptKontrol).where(ScriptKontrol.script_id == sc.id).order_by(ScriptKontrol.zaman)
    ).all()
    out.update(
        kod=sc.icerik,
        adimlar=[_adim(sc.id, a, gizli) for a in adimlar],
        eslemeler=[
            {
                "adim_no": m.adim_no,
                "step_id": m.adim_kimligi,
                "po": m.po_sinifi,
                "method": m.po_metodu,
                "args": m.argumanlar,
                "beklenen": m.beklenen,
                "verified": m.dogrulandi,
                "kaynak_metin": m.kanit_ref if m.beklenen else None,
                "kanit_ref": None if m.beklenen else m.kanit_ref,
                "dogrulama_notu": _dogrulama_notu(m, ajan_bayileri),
            }
            for m in eslemeler
        ],
        yerel_kontrol=_yerel_kontrol(cg),
        merge_engelleri=merge_engelleri(sc, cg),
        # Kapı değil: merge isteğinde `onay_notu` (açık insan kabulü) zorunlu kılan uyarılar.
        merge_kabul_gerekli=merge_kabul_gerekceleri(sc, cg),
        dogrulama=cg.dogrulama,
        kontroller=[
            {
                "tur": k.tur,
                "sha": k.sha,
                "kirma": k.kirma,
                "run_id": k.run_id,
                "toolchain_run_id": (k.ozet or {}).get("toolchain_run_id"),
                "sonuc": k.sonuc,
                "sinif": k.sinif,
                "aciklama": (k.ozet or {}).get("aciklama"),
                "sure_ms": k.sure_ms,
                "zaman": k.zaman.isoformat(),
            }
            for k in kontroller
        ],
        uyarilar=[
            *([g] if (g := gecikme_uyarisi(sc, adimlar)) else []),
            *uyarilar(sc, cg),
        ],
        gecikme_butcesi_s=adim5_butce_s(),
        case_hash=cg.case_hash,
        symbols_sha=cg.symbols_sha,
        denetim_hash=cg.denetim_hash,
        bundle_hash=cg.bundle_hash,
    )
    return out


def get_pair(session: Session, sid: uuid.UUID) -> tuple[Script, ScriptCodegen] | None:
    sc = session.get(Script, sid)
    cg = session.get(ScriptCodegen, sid)
    if sc is None or cg is None:
        return None
    return sc, cg


def screenshot_path(session: Session, sid: uuid.UUID, sira: int) -> Path | None:
    """Ekran görüntüsünün diskteki yolu; kayıt yoksa ya da yol doğrulanamazsa None."""
    adim = session.scalars(
        select(ScriptAdim).where(ScriptAdim.script_id == sid, ScriptAdim.sira == sira)
    ).first()
    if adim is None or not adim.ekran_goruntusu:
        return None
    rel = adim.ekran_goruntusu
    if not _EKRAN_RE.match(rel) or rel.split("/")[1] != str(sid):
        return None
    kok = Path(get_settings().screenshot_root).resolve()
    try:
        yol = (kok / rel).resolve()
    except (OSError, RuntimeError):
        return None
    if kok not in yol.parents or not yol.is_file():
        return None
    return yol


def pr_response(session: Session, number: int, scripts: Sequence[Script]) -> dict[str, Any] | None:
    for sc in scripts:
        cg = session.get(ScriptCodegen, sc.id)
        if cg is not None:
            return _pr(session, sc, cg)
    return None


def _triage_failure_id(session: Session, sc: Script) -> str | None:
    """Script'e bağlı en yeni triage kaydı (`failure_ek.script_id`), yoksa `script.failure_id`."""
    from tp_core.models.triage_feature import FailureEk

    fid = session.scalars(
        select(FailureEk.failure_id)
        .where(FailureEk.script_id == sc.id)
        .order_by(FailureEk.olusturma.desc())
        .limit(1)
    ).first()
    if fid is None:
        fid = sc.failure_id
    return str(fid) if fid else None
