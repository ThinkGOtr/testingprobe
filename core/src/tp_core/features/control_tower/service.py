"""Kontrol Kulesi (TEKNIK-TASARIM §8.11, §12; adım 11). AI yok; her sayı DB satırlarından türer.

Her KPI'nin yanında `kaynaklar[<kpi>]` hangi tablo/filtre/pencereden geldiğini söyler. Ölçülmeyen
değer uydurulmaz: manuel baz değer (`TP_MANUAL_BASELINE_S`) yoksa `manuel_baz_ms=null` +
`baz_deger_olculmedi=true` + uyarı; geçme hedefi tanımlı değilse `gecme_hedefi=null`.

Kırma koşuları (tetik `break_verify` ya da `ortam.break_campaign=true`) bilerek kırmızıdır; geçme
oranına, flaky'ye, karneye ve a11y'ye girmez.
"""

from __future__ import annotations

import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.orm import Session

from tp_core.config import get_settings
from tp_core.features.ci import service as ci
from tp_core.features.ci import services as ci_services
from tp_core.models import (
    AiCall,
    BugDraft,
    ConsistencyFinding,
    Failure,
    PullRequest,
    Requirement,
    Run,
    Script,
    ScriptTestCase,
    StepMapping,
    TestCase,
    TestResult,
)
from tp_core.models.ci_feature import TestResultEk
from tp_core.models.codegen_feature import ScriptCodegen, ScriptKontrol

CI_TETIKLER = ("pr", "push", "nightly", "deploy", "manual")
# main üzerinde koşan tetikler: story karnesinin "son sonuç"u yalnızca bunlardan gelir (PR
# koşuları merge edilmemiş dalları ölçer; ayrı `pr_son_sonuc` olarak gösterilir).
MAIN_TETIKLER = ("push", "nightly", "deploy", "manual")
GUNCEL_CASE = ("approved", "published")
SCRIPT_KABUL = frozenset({"kabul", "accepted", "approved_unchanged", "degisiklik_istenmedi"})
SCRIPT_HEDEFI = 0.60
KABUL_HEDEFI = 0.70
GECTI = ("passed", "flaky")
# Birimin herhangi bir script'inde bu insan kararı varsa birim "ilk review'da kabul" sayılmaz:
# yeniden üretilip sonra kabul edilen birim ilk review başarısı değildir.
SCRIPT_ILK_REVIEW_BOZAR = frozenset({"degisiklik_istendi", "reddedildi", "kabul_yabanci_head"})
KALDI = ("failed", "timedout")
BAZ_YOK = "Manuel baz değer ölçülmedi (TP_MANUAL_BASELINE_S boş): kazanç oranı gösterilmez."
# Script birimi = (case, onaylı case hash'i): aynı onaylı içerikten yeniden üretimler tek birimdir.
AKTIF_SCRIPT = frozenset({"pending", "verifying", "checking"})
# Bu eşiğin altındaki örneklemle verilen oranların yanında uyarı yazılır (n küçük).
KUCUK_ORNEKLEM = 5


def _n(ad: str, varsayilan: int) -> int:
    try:
        return max(int((os.environ.get(ad) or "").strip() or varsayilan), 1)
    except ValueError:
        return varsayilan


def _kirma_degil() -> Any:
    return and_(
        Run.tetik != "break_verify",
        or_(
            Run.ortam["break_campaign"].astext.is_(None),
            Run.ortam["break_campaign"].astext != "true",
        ),
    )


def _oran(pay: int, payda: int) -> float | None:
    return round(pay / payda, 4) if payda else None


# ------------------------------------------------------------------------------ koşular


def son_kosular(session: Session, n: int) -> list[dict[str, Any]]:
    runs = session.scalars(
        select(Run).where(Run.tetik.in_(CI_TETIKLER)).order_by(Run.olusturma.desc()).limit(n)
    ).all()
    return ci.serialize_runs(session, list(runs))


def gecme_orani(session: Session, n: int) -> dict[str, Any]:
    runs = session.execute(
        select(Run.id, Run.sonuc)
        .where(Run.tetik.in_(CI_TETIKLER), Run.sonuc.in_(ci.BITMIS), _kirma_degil())
        .order_by(Run.olusturma.desc())
        .limit(n)
    ).all()
    gecen = sum(1 for _, s in runs if s == "passed")
    ids = [r for r, _ in runs]
    test_gecen = test_toplam = 0
    if ids:
        for sonuc, adet in session.execute(
            select(TestResult.sonuc, func.count())
            .where(TestResult.run_id.in_(ids), TestResult.sonuc != "skipped")
            .group_by(TestResult.sonuc)
        ):
            test_toplam += int(adet)
            if sonuc in GECTI:
                test_gecen += int(adet)
    return {
        "oran": _oran(gecen, len(runs)),
        "toplam": len(runs),
        "gecen": gecen,
        "donem_gun": None,
        "son_n": n,
        "test": {
            "oran": _oran(test_gecen, test_toplam),
            "toplam": test_toplam,
            "gecen": test_gecen,
        },
    }


def gunluk_gecme(session: Session, gun: int) -> list[dict[str, Any]]:
    tz = ci._istanbul()
    simdi = ci_services.now()
    bas = simdi - timedelta(days=gun)
    gunler: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for sonuc, zaman in session.execute(
        select(Run.sonuc, Run.olusturma).where(
            Run.tetik.in_(CI_TETIKLER),
            Run.sonuc.in_(ci.BITMIS),
            Run.olusturma >= bas,
            _kirma_degil(),
        )
    ):
        g = zaman.astimezone(tz).date().isoformat()
        gunler[g][1] += 1
        if sonuc == "passed":
            gunler[g][0] += 1
    return [
        {"tarih": g, "oran": round(p / t, 4), "kosu": t, "gecen": p}
        for g, (p, t) in sorted(gunler.items())
    ]


def flaky(session: Session, gun: int) -> list[dict[str, Any]]:
    bas = ci_services.now() - timedelta(days=gun)
    temel = (
        select(TestResult)
        .join(Run, Run.id == TestResult.run_id)
        .where(TestResult.olusturma >= bas, _kirma_degil())
    ).subquery()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    # (a) yeniden denemeyle geçen (Playwright `flaky`)
    for dosya, ad, adet, son in session.execute(
        select(temel.c.dosya, temel.c.test_adi, func.count(), func.max(temel.c.olusturma))
        .where(temel.c.sonuc == "flaky")
        .group_by(temel.c.dosya, temel.c.test_adi)
    ):
        out[(dosya or "", ad)] = {
            "test_adi": ad,
            "dosya": dosya,
            "neden": "retry",
            "sayi": int(adet),
            "son_gorulme": son.isoformat() if son else None,
        }
    # (b) aynı commit'te farklı sonuç (geçti ↔ kaldı)
    sinif = func.bool_or(temel.c.sonuc.in_(GECTI)).label("gecti")
    kaldi = func.bool_or(temel.c.sonuc.in_(KALDI)).label("kaldi")
    alt = (
        select(
            temel.c.dosya,
            temel.c.test_adi,
            temel.c.commit,
            sinif,
            kaldi,
            func.max(temel.c.olusturma).label("son"),
        )
        .where(temel.c.commit.is_not(None), temel.c.sonuc != "skipped")
        .group_by(temel.c.dosya, temel.c.test_adi, temel.c.commit)
    ).subquery()
    for dosya, ad, adet, son in session.execute(
        select(alt.c.dosya, alt.c.test_adi, func.count(), func.max(alt.c.son))
        .where(alt.c.gecti, alt.c.kaldi)
        .group_by(alt.c.dosya, alt.c.test_adi)
    ):
        anahtar = (dosya or "", ad)
        if anahtar in out:
            out[anahtar]["neden"] = "same_commit"
            out[anahtar]["ayni_commit_sayisi"] = int(adet)
            continue
        out[anahtar] = {
            "test_adi": ad,
            "dosya": dosya,
            "neden": "same_commit",
            "sayi": int(adet),
            "son_gorulme": son.isoformat() if son else None,
        }
    return sorted(out.values(), key=lambda x: (-x["sayi"], x["test_adi"]))


# ------------------------------------------------------------------------------ karne

# Uygulama alanı = case adımlarının eşlendiği page object sınıfı (`step_mapping.po_sinifi`,
# §8.4). Bilinen demo sınıfları Türkçe adla; diğerleri sınıf adından.
ALAN_ADI = {
    "CartPage": "Sepet",
    "CatalogPage": "Katalog",
    "LoginPage": "Giriş",
    "OrderPage": "Sipariş",
}


def alan_adi(po_sinifi: str) -> str:
    if po_sinifi in ALAN_ADI:
        return ALAN_ADI[po_sinifi]
    ad = po_sinifi[:-4] if po_sinifi.endswith("Page") and len(po_sinifi) > 4 else po_sinifi
    return ad or po_sinifi


def _case_alanlari(session: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    """Case → uygulama alanları (adım eşlemelerinin page object sınıfları, tüm script'ler)."""
    if not case_ids:
        return {}
    out: dict[uuid.UUID, set[str]] = defaultdict(set)
    for cid, po in session.execute(
        select(StepMapping.test_case_id, StepMapping.po_sinifi)
        .where(StepMapping.test_case_id.in_(case_ids))
        .distinct()
    ):
        if po and str(po) != "None":
            out[cid].add(alan_adi(str(po)))
    return out


def alan_karnesi(session: Session) -> list[dict[str, Any]]:
    """Uygulama alanı bazında karne (§8.11): alanın case'leri, otomasyonu, main son sonucu."""
    guncel = list(session.scalars(select(TestCase.id).where(TestCase.durum.in_(GUNCEL_CASE))))
    alanlar: dict[str, set[uuid.UUID]] = defaultdict(set)
    for cid, ads in _case_alanlari(session, guncel).items():
        for ad in ads:
            alanlar[ad].add(cid)
    if not alanlar:
        return []
    otomatik = set(
        session.scalars(
            select(ScriptTestCase.test_case_id)
            .join(Script, Script.id == ScriptTestCase.script_id)
            .where(
                ScriptTestCase.test_case_id.in_(guncel),
                Script.tur == "test",
                Script.durum == "merged",
            )
        )
    )
    story = dict(
        session.execute(
            select(TestCase.id, TestCase.requirement_id).where(TestCase.id.in_(guncel))
        ).all()
    )
    out = []
    for ad, cids in sorted(alanlar.items()):
        liste = sorted(cids)
        out.append(
            {
                "alan": ad,
                "story_sayisi": len({story[c] for c in liste if c in story}),
                "case_sayisi": len(liste),
                "otomasyon_sayisi": len(cids & otomatik),
                "otomasyon_kapsami": _oran(len(cids & otomatik), len(liste)),
                **_son_sonuc(session, liste),
                "acik_defect_adayi": _acik_defect_adayi(session, liste),
            }
        )
    return out


def karne(session: Session) -> list[dict[str, Any]]:
    reqs = session.scalars(
        select(Requirement)
        .where(
            Requirement.id.in_(
                select(TestCase.requirement_id).where(TestCase.durum != "superseded")
            )
        )
        .order_by(Requirement.jira_key.nulls_last(), Requirement.olusturma)
    ).all()
    out = []
    for req in reqs:
        cases = session.execute(
            select(TestCase.id, TestCase.durum).where(
                TestCase.requirement_id == req.id, TestCase.durum != "superseded"
            )
        ).all()
        durumlar: dict[str, int] = defaultdict(int)
        for _, d in cases:
            durumlar[d] += 1
        guncel = [cid for cid, d in cases if d in GUNCEL_CASE]
        otomatik: set[uuid.UUID] = set()
        if guncel:
            otomatik = set(
                session.scalars(
                    select(ScriptTestCase.test_case_id)
                    .join(Script, Script.id == ScriptTestCase.script_id)
                    .where(
                        ScriptTestCase.test_case_id.in_(guncel),
                        Script.tur == "test",
                        Script.durum == "merged",
                    )
                )
            )
        alan_seti = sorted(set().union(*_case_alanlari(session, guncel).values()))
        out.append(
            {
                "requirement_id": str(req.id),
                "story_key": req.jira_key or f"serbest:{str(req.id)[:8]}",
                "baslik": req.baslik,
                # Story'nin dokunduğu uygulama alanları; adım eşlemesi yoksa ölçülmedi (None).
                "alan": ", ".join(alan_seti) or None,
                "alanlar": alan_seti,
                "case_sayisi": len(guncel),
                "case_durumlari": dict(durumlar),
                "otomasyon_sayisi": len(otomatik),
                "otomasyon_kapsami": _oran(len(otomatik), len(guncel)),
                **_son_sonuc(session, guncel),
                **_son_sonuc(session, guncel, tetikler=("pr",), onek="pr_"),
                "acik_bug": _acik_bug(session, req.id),
                "acik_defect_adayi": _acik_defect_adayi(session, guncel),
            }
        )
    return out


def _son_sonuc(
    session: Session,
    case_ids: list[uuid.UUID],
    *,
    tetikler: tuple[str, ...] = MAIN_TETIKLER,
    onek: str = "",
) -> dict[str, Any]:
    """Case'lere bağlı test_result'ların en son kırma olmayan, bitmiş koşusu (`tetikler`)."""
    yok = {f"{onek}son_sonuc": "none", f"{onek}son_kosu_id": None}
    if not case_ids:
        return yok
    son = session.execute(
        select(Run.id, Run.olusturma)
        .join(TestResult, TestResult.run_id == Run.id)
        .where(
            TestResult.test_case_id.in_(case_ids),
            Run.tetik.in_(tetikler),
            _kirma_degil(),
            Run.sonuc.in_(ci.BITMIS),
        )
        .order_by(Run.olusturma.desc())
        .limit(1)
    ).first()
    if son is None:
        return yok
    sonuclar = set(
        session.scalars(
            select(TestResult.sonuc).where(
                TestResult.run_id == son[0], TestResult.test_case_id.in_(case_ids)
            )
        )
    )
    durum = "failed" if sonuclar & set(KALDI) else ("passed" if sonuclar & set(GECTI) else "none")
    return {f"{onek}son_sonuc": durum, f"{onek}son_kosu_id": str(son[0])}


def _acik_defect_adayi(session: Session, case_ids: list[uuid.UUID]) -> int:
    """Güncel case'lerden en son script'i defect adayı (blocked) olanların sayısı."""
    if not case_ids:
        return 0
    adet = 0
    for cid in case_ids:
        son = session.execute(
            select(Script.durum, ScriptCodegen.engel_turu)
            .join(ScriptCodegen, ScriptCodegen.script_id == Script.id)
            .where(ScriptCodegen.test_case_id == cid, Script.tur == "test")
            .order_by(Script.olusturma.desc(), Script.id.desc())
            .limit(1)
        ).first()
        if son is not None and son[0] == "blocked" and son[1] == "defect_candidate":
            adet += 1
    return adet


def _acik_bug(session: Session, req_id: uuid.UUID) -> int:
    bulgu = select(ConsistencyFinding.id).where(ConsistencyFinding.requirement_id == req_id)
    hata = (
        select(Failure.id)
        .join(TestResult, TestResult.id == Failure.test_result_id)
        .join(TestCase, TestCase.id == TestResult.test_case_id)
        .where(TestCase.requirement_id == req_id)
    )
    return int(
        session.scalar(
            select(func.count()).where(
                BugDraft.durum != "dismissed",
                or_(BugDraft.finding_id.in_(bulgu), BugDraft.failure_id.in_(hata)),
            )
        )
        or 0
    )


# ------------------------------------------------------------------------------ AI katkısı


def _review_tabani_ms() -> int:
    """Bunun altındaki review süresi insan review'u sayılmaz (betik/API onayı): ölçülmedi."""
    try:
        return max(int((os.environ.get("TP_CT_REVIEW_MIN_S") or "").strip() or 5), 0) * 1000
    except ValueError:
        return 5000


def _ci_gecti(session: Session, sc: Any, case_id: uuid.UUID | None) -> bool:
    """Script'in PR head'inde ya da merge commit'inde kırma olmayan CI'da geçtiği kanıtlı mı?

    Case'e bağlı test_result varsa test düzeyinde (geçen var, kalan yok); yoksa koşu düzeyinde
    (`run.sonuc = passed`).
    """
    shalar = {x for x in (sc.head_sha,) if x}
    if sc.pr_no is not None:
        merge_sha = session.scalar(
            select(PullRequest.merge_sha).where(PullRequest.number == sc.pr_no)
        )
        if merge_sha:
            shalar.add(merge_sha)
    if not shalar:
        return False
    kosu = (
        select(Run.id)
        .where(Run.commit.in_(shalar), Run.sonuc.in_(ci.BITMIS), _kirma_degil())
        .where(Run.tetik.in_(CI_TETIKLER))
    )
    if case_id is not None:
        sonuclar = set(
            session.scalars(
                select(TestResult.sonuc).where(
                    TestResult.run_id.in_(kosu), TestResult.test_case_id == case_id
                )
            )
        )
        if sonuclar - {"skipped"}:
            return bool(sonuclar & set(GECTI)) and not (sonuclar & set(KALDI))
    return bool(
        session.scalar(
            select(func.count()).select_from(kosu.where(Run.sonuc == "passed").subquery())
        )
    )


def script_olculeri(session: Session) -> dict[str, Any]:
    """§12 script ölçüleri; birim = (case, onaylı case hash'i), yeniden üretimler tek sayılır.

    - **İlk review başarısı:** pay = birimin son script'i merge edildi + insan "değişiklik
      istenmeden" kabul etti + PR head'inde ya da merge commit'inde CI geçti. Payda = sonuçlanmış
      birimler (son script merged / closed / blocked / failed). Hâlâ üretimde ya da PR'ı review
      bekleyen birimler paydaya girmez (`script_review_bekleyen`); ortam hatası (`environment`),
      defect adayı (doğru test, uygulama hatası), page object'te eksik metot (`missing_method`:
      PR yok, insan review'u yok — ör. F4 code_defect) ve REPLAY-MISS (`replay_miss`: kayıtlı
      doğrulama yok) ayrı sayılır, paydaya girmez.
    - **pass@1:** her birimin İLK script'inin ilk yerel kontrolü; ilk kontrol `defect_adayi` ise
      (test doğru, uygulama yanlış) paydaya girmez, `pass_at_1_defect_adayi`'da ayrı raporlanır.
    - **Düzeltme sonrası:** birimin ilk script'inde locator düzeltme turu koştuysa onun sonucu.
    """
    satirlar = session.execute(
        select(
            Script,
            ScriptCodegen.test_case_id,
            ScriptCodegen.case_hash,
            ScriptCodegen.engel_turu,
        )
        .outerjoin(ScriptCodegen, ScriptCodegen.script_id == Script.id)
        .where(Script.tur == "test")
        .order_by(Script.olusturma, Script.id)
    ).all()
    birimler: dict[tuple[str, ...], list[tuple[Any, uuid.UUID | None, str | None]]] = {}
    for sc, case_id, case_hash, engel in satirlar:
        if case_id is None:
            case_id = session.scalar(
                select(ScriptTestCase.test_case_id).where(ScriptTestCase.script_id == sc.id)
            )
        anahtar = (str(case_id), str(case_hash)) if case_hash else ("script", str(sc.id))
        birimler.setdefault(anahtar, []).append((sc, case_id, engel))
    ilk_ids = [b[0][0].id for b in birimler.values()]
    ilk_sinif: dict[uuid.UUID, str | None] = {}
    if ilk_ids:
        for sid, sinif in session.execute(
            select(ScriptKontrol.script_id, ScriptKontrol.sinif)
            .where(
                ScriptKontrol.script_id.in_(ilk_ids),
                ScriptKontrol.tur == "local_check",
                ScriptKontrol.kirma.is_(False),
            )
            .order_by(ScriptKontrol.zaman)
        ):
            ilk_sinif.setdefault(sid, sinif)

    p1_pay = p1_payda = p1_defect = 0
    ds_pay = ds_payda = 0
    rv_pay = rv_payda = bekleyen = ortam = defect = eksik_metot = replay_miss = 0
    for liste in birimler.values():
        ilk, _, ilk_engel = liste[0]
        if ilk.pass_at_1 is not None:
            if ilk_sinif.get(ilk.id) == "defect_adayi" or (
                ilk_engel == "defect_candidate" and not ilk.pass_at_1
            ):
                p1_defect += 1
            else:
                p1_payda += 1
                p1_pay += int(bool(ilk.pass_at_1))
        if ilk.onarim_sonrasi_sonuc is not None:
            ds_payda += 1
            ds_pay += int(ilk.onarim_sonrasi_sonuc == "passed")
        son, case_id, son_engel = liste[-1]
        if son.durum in AKTIF_SCRIPT or son.durum == "pr_open":
            bekleyen += 1
            continue
        if son.durum in ("blocked", "failed", "closed") and son_engel == "environment":
            ortam += 1
            continue
        if son.durum == "blocked" and son_engel == "defect_candidate":
            defect += 1
            continue
        # Script insana hiç ulaşmadı (PR yok, review yok): review başarısının paydası değildir.
        if son.durum in ("blocked", "failed", "closed") and son_engel == "missing_method":
            eksik_metot += 1
            continue
        if son.durum in ("blocked", "failed", "closed") and son_engel == "replay_miss":
            replay_miss += 1
            continue
        rv_payda += 1
        if any(s.insan_review_sonucu in SCRIPT_ILK_REVIEW_BOZAR for s, _, _ in liste):
            continue
        if (
            son.durum == "merged"
            and son.insan_review_sonucu in SCRIPT_KABUL
            and _ci_gecti(session, son, case_id)
        ):
            rv_pay += 1
    return {
        "script_ilk_review": _oran(rv_pay, rv_payda),
        "script_review_sayisi": rv_payda,
        "script_ilk_review_kabul": rv_pay,
        "script_review_bekleyen": bekleyen,
        "script_ortam_hatasi": ortam,
        "script_defect_adayi": defect,
        "script_eksik_metot": eksik_metot,
        "script_replay_miss": replay_miss,
        "script_birim_sayisi": len(birimler),
        "script_uretim_sayisi": len(satirlar),
        "pass_at_1": _oran(p1_pay, p1_payda),
        "pass_at_1_sayisi": p1_payda,
        "pass_at_1_defect_adayi": p1_defect,
        "duzeltme_sonrasi": _oran(ds_pay, ds_payda),
        "duzeltme_sonrasi_sayisi": ds_payda,
    }


def ai_katkisi(session: Session) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    from tp_core.features.cases import service as cases

    uyarilar: list[str] = []
    req_ids = session.scalars(
        select(TestCase.requirement_id)
        .where(TestCase.ai_generated.is_(True), TestCase.durum != "superseded")
        .distinct()
    ).all()
    uretilen = kabul = 0
    ai_sureleri: list[int] = []
    review_sureleri: list[int] = []
    hazirlik: list[dict[str, Any]] = []
    baz = cases.manual_baseline_ms()
    taban = _review_tabani_ms()
    review_olculmedi = ai_olculmedi = 0
    for rid in req_ids:
        m = cases.requirement_metrics(session, rid)
        uretilen += int(m.get("uretilen") or 0)
        kabul += int(m.get("kabul") or 0)
        if m.get("uretilen"):
            modlar = m.get("ai_cagri_modlari") or {}
            # REPLAY'de model süresi ölçülmez: 0 ms "ölçüm" değildir.
            ai: int | None = int(m.get("ai_sure_ms") or 0)
            if not ai and modlar and all(str(k).startswith("replay") for k in modlar):
                ai = None
                ai_olculmedi += 1
            # Taban altı review süresi (betik/API onayı) insan review süresi değildir.
            rv: int | None = m.get("review_sure_ms")
            if rv is None or int(rv) < taban:
                rv = None
                review_olculmedi += 1
            else:
                rv = int(rv)
            if ai is not None:
                ai_sureleri.append(ai)
            if rv is not None:
                review_sureleri.append(rv)
            toplam = ai + rv if ai is not None and rv is not None else None
            hazirlik.append(
                {
                    "requirement_id": str(rid),
                    "story_key": m.get("jira_key"),
                    "ai_sure_ms": ai,
                    "review_sure_ms": rv,
                    "ai_olculmedi": ai is None,
                    "review_olculmedi": rv is None,
                    "toplam_ms": toplam,
                    "manuel_baz_ms": baz,
                    "kazanc_orani": round(1 - toplam / baz, 4) if baz and toplam else None,
                    "ai_cagri_modlari": modlar,
                }
            )
    so = script_olculeri(session)
    toplam_maliyet, cagri, replay = session.execute(
        select(
            func.coalesce(func.sum(AiCall.maliyet), 0),
            func.count(),
            func.count().filter(AiCall.mod.in_(("replay", "replay_miss"))),
        )
    ).one()
    tz = ci._istanbul()
    gun_basi = datetime.combine(ci_services.now().astimezone(tz).date(), datetime.min.time(), tz)
    bugun = session.scalar(
        select(func.coalesce(func.sum(AiCall.maliyet), 0)).where(AiCall.olusturma >= gun_basi)
    )
    amaclar = {
        amac: {"cagri": int(n), "maliyet_usd": round(float(c), 6)}
        for amac, n, c in session.execute(
            select(AiCall.amac, func.count(), func.coalesce(func.sum(AiCall.maliyet), 0)).group_by(
                AiCall.amac
            )
        )
    }
    if baz is None:
        uyarilar.append(BAZ_YOK)
    if review_olculmedi:
        uyarilar.append(
            f"{review_olculmedi} story'de review süresi {taban // 1000} sn altında ya da yok "
            "(betik/API onayı): insan review süresi ölçülmedi, ortalamaya girmedi."
        )
    for ad, oran, n in (
        ("Case kabul oranı", _oran(kabul, uretilen), uretilen),
        ("Script ilk review başarısı", so["script_ilk_review"], so["script_review_sayisi"]),
        ("pass@1", so["pass_at_1"], so["pass_at_1_sayisi"]),
    ):
        if oran is not None and n < KUCUK_ORNEKLEM:
            uyarilar.append(f"{ad} yalnızca n={n} örnekten: küçük örneklem, kesin değil.")
    if so["pass_at_1_defect_adayi"]:
        uyarilar.append(
            f"pass@1 paydası dışında {so['pass_at_1_defect_adayi']} defect adayı: test doğru, "
            "uygulama beklenenden farklı (AI hatası sayılmaz; insan triage'ı bekler)."
        )
    if cagri and replay == cagri:
        uyarilar.append(
            "Tüm AI çağrıları REPLAY: AI süresi ölçülmez, maliyet 0'dır (canlı model yok)."
        )
    katki = {
        "kabul_orani": _oran(kabul, uretilen),
        "kabul_hedefi": KABUL_HEDEFI,
        "uretilen_case": uretilen,
        "kabul_edilen_case": kabul,
        "script_hedefi": SCRIPT_HEDEFI,
        **so,
        "ort_ai_sure_ms": round(sum(ai_sureleri) / len(ai_sureleri)) if ai_sureleri else None,
        "ort_review_sure_ms": round(sum(review_sureleri) / len(review_sureleri))
        if review_sureleri
        else None,
        "ai_sure_olculen_story": len(ai_sureleri),
        "review_sure_olculen_story": len(review_sureleri),
        "review_sure_taban_ms": taban,
        "manuel_baz_ms": baz,
        "baz_deger_olculmedi": baz is None,
        "maliyet_usd_toplam": round(float(toplam_maliyet), 6),
        "maliyet_usd_bugun": round(float(bugun or 0), 6),
        "gunluk_butce_usd": get_settings().daily_budget_usd,
        "cagri_sayisi": int(cagri),
        "replay_cagri": int(replay),
        "amaclar": amaclar,
    }
    return katki, hazirlik, uyarilar


# ------------------------------------------------------------------------------ a11y


def a11y(session: Session) -> dict[str, Any] | None:
    son = session.execute(
        select(Run.id, Run.olusturma)
        .join(TestResult, TestResult.run_id == Run.id)
        .join(TestResultEk, TestResultEk.test_result_id == TestResult.id)
        .where(func.jsonb_array_length(TestResultEk.a11y) > 0, not_(Run.tetik == "break_verify"))
        .order_by(Run.olusturma.desc())
        .limit(1)
    ).first()
    if son is None:
        return None
    sayfalar: dict[str, dict[str, Any]] = {}
    for (liste,) in session.execute(
        select(TestResultEk.a11y)
        .join(TestResult, TestResult.id == TestResultEk.test_result_id)
        .where(TestResult.run_id == son[0])
    ):
        for s in liste or []:
            if not isinstance(s, dict):
                continue
            ad = str(s.get("sayfa") or "?")
            kayit = sayfalar.setdefault(
                ad, {"yol": ad, "url": s.get("url"), "ihlal": 0, "kritik": 0}
            )
            kayit["ihlal"] += int(s.get("ihlal") or 0)
            kayit["kritik"] += int((s.get("etki") or {}).get("critical") or 0)
    liste = sorted(sayfalar.values(), key=lambda x: x["yol"])
    return {
        "ihlal": sum(x["ihlal"] for x in liste),
        "kritik": sum(x["kritik"] for x in liste),
        "son_tarama": son[1].isoformat(),
        "kosu_id": str(son[0]),
        "sayfalar": liste,
    }


# ------------------------------------------------------------------------------ toplam


def control_tower(session: Session) -> dict[str, Any]:
    n = _n("TP_CT_SON_KOSU", 20)
    gun = _n("TP_CT_FLAKY_GUN", 30)
    trend = _n("TP_CT_TREND_GUN", 14)
    katki, hazirlik, uyarilar = ai_katkisi(session)
    kosular = son_kosular(session, n)
    if not kosular:
        uyarilar.append("Henüz CI koşusu yok: geçme oranı, flaky ve son sonuçlar boş.")
    a = a11y(session)
    return {
        "son_kosular": kosular,
        "gecme_orani": gecme_orani(session, n),
        # Proje bir geçme hedefi tanımlamadı (§12'de yok); uydurulmaz.
        "gecme_hedefi": None,
        "gunluk_gecme": gunluk_gecme(session, trend),
        "flaky": flaky(session, gun),
        "karne": karne(session),
        "alan_karnesi": alan_karnesi(session),
        "ai_katkisi": katki,
        "hazirlik": hazirlik,
        "a11y": a,
        "kaynaklar": {
            "son_kosular": f"run tablosu, son {n} CI koşusu (tetik pr/push/nightly/deploy/manual)",
            "gecme_orani": (
                f"run.sonuc, son {n} tamamlanmış CI koşusu (passed / passed+failed+error); kırma "
                "koşuları (break_verify, BREAK_CAMPAIGN) hariç. Test oranı: aynı koşuların "
                "test_result satırları (passed+flaky / atlanmayanlar)"
            ),
            "flaky": (
                f"test_result (JUnit XML + Playwright JSON), son {gun} gün, kırma koşuları hariç: "
                "sonuc='flaky' (yeniden denemeyle geçti) ya da aynı commit'te hem geçen hem kalan"
            ),
            "karne": (
                "test_case (approved/published) · script_test_case + script (tur=test, "
                "durum=merged) = otomatik · son sonuç: case'e bağlı test_result'ların main "
                "üzerindeki (push/nightly/deploy/manual) en son kırma olmayan koşusu; PR koşusu "
                "ayrı (pr_son_sonuc) · açık defect adayı: son script'i blocked + defect_candidate "
                "· açık bug: bug_draft (dismissed hariç; Jira durumu okunmaz) · alan: case "
                "adımlarının step_mapping.po_sinifi'ndan (page object → uygulama "
                "alanı); eşleme yoksa alan ölçülmedi (—)"
            ),
            "alan_karnesi": (
                "uygulama alanı = step_mapping.po_sinifi (CartPage→Sepet, "
                "CatalogPage→Katalog, LoginPage→Giriş, OrderPage→Sipariş); alanın güncel "
                "case'leri, merged script'leri ve case'lere bağlı test_result'ların main "
                "üzerindeki en son kırma olmayan koşusu. Adım eşlemesi olmayan case'ler alana "
                "girmez"
            ),
            "kabul_orani": (
                "review (ilk insan kararı: approve ya da küçük düzeltmeli edit) / üretilen AI "
                "case'i — /requirements/{id}/case-metrics ile aynı hesap, tüm story'ler"
            ),
            "script_ilk_review": (
                "birim = (case, onaylı case hash'i) — yeniden üretimler tek sayılır. Pay: son "
                "script merged + script.insan_review_sonucu değişiklik istenmeden kabul + PR "
                "head'inde/merge commit'inde kırma olmayan CI geçti. Payda: sonuçlanmış birimler "
                "(merged/closed/blocked/failed); review bekleyen, ortam hatası (environment), "
                "defect adayı, page object'te eksik metot (missing_method: PR/insan review'u yok) "
                "ve replay_miss ayrı sayılır, paydaya girmez (ölçülmedi). Birimdeki herhangi bir "
                "script'te değişiklik istendiyse, reddedildiyse ya da yabancı head merge edildiyse"
                " birim kabul sayılmaz. pass@1 = birimin ilk script'inin script.pass_at_1'i: ilk "
                "turda modele atfedilen eşleme engeli (unsourced_value / unknown_method / "
                "unverified_step) ve kararsız (kararsiz) kontrol geçmedi sayılır; missing_method, "
                "environment ve replay_miss ölçülmedi kalır (paydada değil); ilk yerel kontrol "
                "defect_adayi ise paydada değil; düzeltme sonrası = script.onarim_sonrasi_sonuc"
            ),
            "hazirlik_suresi": (
                "story başına ai_call.sure_ms (case üretimi; tümü REPLAY ise ölçülmedi) + review "
                "süresi (karar aralıklarının birleşimi; TP_CT_REVIEW_MIN_S=5 sn altı betik/API "
                "onayı sayılır, ölçülmedi); ortalama yalnızca ölçülen story'ler üzerinden"
            ),
            "manuel_baz": "TP_MANUAL_BASELINE_S (F0 ölçümü); boşsa ölçülmedi, değer uydurulmaz",
            "maliyet": "ai_call.maliyet toplamı (tüm amaçlar); bugün: Europe/Istanbul gün başından",
            "a11y": (
                "test_result_ek.a11y: Playwright JSON raporundaki axe-<sayfa>.json ekleri, "
                "a11y verisi olan en son kırma olmayan koşu"
            ),
        },
        "uyarilar": uyarilar,
        "pencere": {"son_n": n, "flaky_gun": gun, "trend_gun": trend},
        "uretim": ci_services.now().isoformat(),
    }
