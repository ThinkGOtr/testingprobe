"""Kontrol Kulesi: her sayı DB satırlarından; kırma koşuları hariç; baz değer uydurulmaz."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA, login, run_jobs
from tp_core.audit import record_ai_call
from tp_core.features.ci import enqueue_ci
from tp_core.features.control_tower import service as ct
from tp_core.models import PullRequest, Run, Script, ScriptTestCase, StepMapping, TestResult
from tp_core.models.codegen_feature import ScriptCodegen, ScriptKontrol
from tp_core.models.guard import allow_state_write

pytestmark = pytest.mark.usefixtures("ci_env")

KPI = (
    "gecme_orani",
    "flaky",
    "karne",
    "kabul_orani",
    "script_ilk_review",
    "hazirlik_suresi",
    "manuel_baz",
    "maliyet",
    "a11y",
    "son_kosular",
)


def _run_ekle(
    s: Session,
    tetik: str,
    sonuc: str,
    zaman: datetime,
    testler: list[tuple[str, str, uuid.UUID | None]],
    **ortam,
) -> uuid.UUID:
    run = Run(
        id=uuid.uuid4(),
        commit=SHA,
        kaynak="local",
        tetik=tetik,
        sonuc=sonuc,
        ortam=ortam,
        artefaktlar={},
    )
    s.add(run)
    s.flush()
    s.execute(update(Run).where(Run.id == run.id).values(olusturma=zaman))
    for ad, durum, case in testler:
        s.add(
            TestResult(
                run_id=run.id,
                test_case_id=case,
                test_adi=ad,
                dosya="generated/tpd-1-kampanya.spec.ts",
                sonuc=durum,
                sure_ms=10,
                retry=0,
                commit=SHA,
                tetik=tetik,
                kaynak="local",
                olusturma=zaman,
            )
        )
    s.flush()
    return run.id


@pytest.fixture
def senaryo(engine: Engine, make_requirement_case, monkeypatch: pytest.MonkeyPatch):
    # Faz 4 triage kancası kırmızı A koşusunu sınıflandırır (kural dışı zaman aşımı → LLM yedeği,
    # ek ai_call satırları); bu senaryo yalnızca CI/AI katkısı sayılarını sabit girdilerle ölçer.
    import tp_core.features.triage as triage

    monkeypatch.setattr(triage, "on_run_finished", lambda session, run: None)
    c1 = make_requirement_case(title="7 adet Portakal Gazozu → 1 adet bedava")
    c2 = make_requirement_case(title="6 adet → bedava yok")
    c3 = make_requirement_case(title="Minimum sipariş tutarı 750,00 TL uyarısı")
    make_requirement_case(title="taslak", durum="draft")
    make_requirement_case(jira_key="TPD-4", title="giriş", durum="published", ai=False)
    with Session(engine) as s, s.begin(), allow_state_write():
        merged = Script(
            id=uuid.uuid4(),
            dosya_yolu="e2e/tests/generated/tpd-1-kampanya.spec.ts",
            durum="merged",
            head_sha=SHA,
            pass_at_1=True,
            insan_review_sonucu="kabul",
            onarim_sonrasi_sonuc="passed",
        )
        acik = Script(
            id=uuid.uuid4(),
            dosya_yolu="e2e/tests/generated/diger.spec.ts",
            durum="pr_open",
            pass_at_1=False,
            insan_review_sonucu="degisiklik",
        )
        s.add_all([merged, acik])
        s.flush()
        s.add_all(
            [
                ScriptTestCase(script_id=merged.id, test_case_id=c1),
                ScriptTestCase(script_id=merged.id, test_case_id=c2),
                ScriptTestCase(script_id=acik.id, test_case_id=c3),
            ]
        )
        s.flush()
    # A: gerçek yerel CI (sahte toolchain + rapor fikstürleri): PR, kırmızı.
    with Session(engine) as s, s.begin():
        a = enqueue_ci(s, SHA, "pr", 1)
    run_jobs(engine)
    simdi = datetime.now(UTC)
    with Session(engine) as s, s.begin():
        s.execute(update(Run).where(Run.id == a).values(olusturma=simdi - timedelta(hours=2)))
        # B: kırarak doğrulama — bilerek kırmızı; hiçbir KPI'ye girmez.
        b = _run_ekle(
            s,
            "break_verify",
            "failed",
            simdi - timedelta(hours=1),
            [("TPD-1 › 7 adet Portakal Gazozu → 1 adet bedava", "failed", c1)],
            break_campaign=True,
        )
        # C: aynı commit'te push, yeşil (6 adet testi aynı commit'te önce kaldı → flaky).
        c = _run_ekle(
            s,
            "push",
            "passed",
            simdi - timedelta(minutes=30),
            [
                ("TPD-1 › 6 adet → bedava yok", "passed", c2),
                ("TPD-1 › 7 adet Portakal Gazozu → 1 adet bedava", "passed", c1),
            ],
        )
        record_ai_call(
            s.connection(),
            {"amac": "case_generation", "saglayici": "anthropic", "model": "m", "mod": "live",
             "maliyet": Decimal("0.5"), "sure_ms": 4000},
        )  # fmt: skip
        record_ai_call(
            s.connection(),
            {"amac": "verify_and_map", "saglayici": "replay", "model": "m", "mod": "replay",
             "maliyet": Decimal("0.25")},
        )  # fmt: skip
    return {"a": a, "b": b, "c": c, "cases": (c1, c2, c3)}


def test_kontrol_kulesi_sayilari_satirlardan(engine: Engine, senaryo) -> None:
    with Session(engine) as s:
        k = ct.control_tower(s, artefakt=True)
    # Son koşular: yalnızca CI tetikleri (kırma koşusu yok).
    assert [r["id"] for r in k["son_kosular"]] == [str(senaryo["c"]), str(senaryo["a"])]
    # Geçme oranı: A failed + C passed (B hariç).
    g = k["gecme_orani"]
    assert (g["oran"], g["toplam"], g["gecen"]) == (0.5, 2, 1)
    # B (break_verify) CI tetiği değildir: pencereye de girmez.
    assert g["haric_kirma"] == 0
    assert g["metin"] == "Son 2 CI koşusundan 1'i geçti (pencere: son 20)"
    assert g["test"]["toplam"] == 10 and g["test"]["gecen"] == 7
    assert k["gecme_hedefi"] is None
    assert sum(x["kosu"] for x in k["gunluk_gecme"]) == 2
    # Flaky: retry ile geçen + aynı commit'te değişen; kırma koşusu "7 adet"i flaky yapmaz.
    f = {x["test_adi"]: x for x in k["flaky"]}
    assert f["TPD-1 › Sepete ekle sepet sayacını artırır"]["neden"] == "retry"
    assert f["TPD-1 › 6 adet → bedava yok"]["neden"] == "same_commit"
    assert "TPD-1 › 7 adet Portakal Gazozu → 1 adet bedava" not in f
    # Karne
    kr = {x["story_key"]: x for x in k["karne"]}
    tpd1 = kr["TPD-1"]
    assert (tpd1["case_sayisi"], tpd1["otomasyon_sayisi"], tpd1["otomasyon_kapsami"]) == (
        3,
        2,
        0.6667,
    )
    assert tpd1["case_durumlari"] == {"approved": 3, "draft": 1}
    assert (tpd1["son_sonuc"], tpd1["son_kosu_id"]) == ("passed", str(senaryo["c"]))
    assert tpd1["pr_son_kosu_id"] == str(senaryo["a"]) and tpd1["acik_defect_adayi"] == 0
    assert kr["TPD-4"]["son_sonuc"] == "none" and kr["TPD-4"]["otomasyon_kapsami"] == 0.0
    # Adım eşlemesi yokken alan ölçülmedi: uydurulmaz.
    assert tpd1["alan"] is None and tpd1["alanlar"] == [] and k["alan_karnesi"] == []
    assert "alan_karnesi" in k["kaynaklar"]
    # a11y: A koşusunun axe ekleri
    assert k["a11y"]["ihlal"] == 5 and k["a11y"]["kritik"] == 1
    assert k["a11y"]["kosu_id"] == str(senaryo["a"])
    assert {x["yol"] for x in k["a11y"]["sayfalar"]} == {"katalog", "sepet"}
    # AI katkısı
    ai = k["ai_katkisi"]
    assert ai["maliyet_usd_toplam"] == 0.75 and ai["cagri_sayisi"] == 2 and ai["replay_cagri"] == 1
    assert ai["amaclar"]["case_generation"] == {"cagri": 1, "maliyet_usd": 0.5}
    # İlk review: merged + kabul + aynı commit'te push CI'ı geçti → 1/1; PR'ı açık olan bekliyor.
    assert (ai["pass_at_1"], ai["script_ilk_review"], ai["duzeltme_sonrasi"]) == (0.5, 1.0, 1.0)
    assert (ai["script_review_sayisi"], ai["script_review_bekleyen"]) == (1, 1)
    assert any("n=1" in u and "Script ilk review" in u for u in k["uyarilar"])
    assert ai["manuel_baz_ms"] is None and ai["baz_deger_olculmedi"] is True
    assert any("baz değer ölçülmedi" in u for u in k["uyarilar"])
    assert all(x["kazanc_orani"] is None for x in k["hazirlik"])
    # Her KPI'nin kaynağı yazılı.
    assert set(KPI) <= set(k["kaynaklar"])


def test_manuel_baz_verilirse_kullanilir(
    engine: Engine, senaryo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "3600")
    with Session(engine) as s:
        k = ct.control_tower(s, artefakt=True)
    # Story'ye özel ölçüm yok: ortam değeri ölçüm sayılmaz, sayı olarak gösterilmez.
    assert k["ai_katkisi"]["manuel_baz_ms"] is None
    assert k["ai_katkisi"]["baz_deger_olculmedi"] is True
    assert ct.BAZ_YOK in k["uyarilar"]
    assert k["ai_katkisi"]["manuel_baz_varsayilan_ms"] == 3_600_000
    assert {x["manuel_baz_kaynagi"] for x in k["hazirlik"]} == {"varsayilan"}
    assert all(x["manuel_baz_ms"] is None for x in k["hazirlik"])
    assert {x["manuel_baz"]["varsayilan_ms"] for x in k["hazirlik"]} == {3_600_000}
    assert any("varsayılan (TP_MANUAL_BASELINE_S) ölçüm sayılmadı" in u for u in k["uyarilar"])


def test_bos_veritabaninda_uydurma_yok(engine: Engine) -> None:
    with Session(engine) as s:
        k = ct.control_tower(s, artefakt=True)
    assert k["son_kosular"] == [] and k["flaky"] == [] and k["karne"] == []
    assert k["gecme_orani"]["oran"] is None and k["a11y"] is None
    assert k["ai_katkisi"]["kabul_orani"] is None and k["ai_katkisi"]["pass_at_1"] is None
    assert any("Henüz CI koşusu yok" in u for u in k["uyarilar"])


def test_api_herkes_okur(api: TestClient, make_user, senaryo) -> None:
    assert api.get("/control-tower").status_code == 401
    login(api, make_user("po"))
    r = api.get("/control-tower")
    assert r.status_code == 200
    assert r.json()["gecme_orani"]["toplam"] == 2


# ------------------------------------------------------------------- script KPI'ları (§12)

SHA_B = "b" * 40
SHA_C = "c" * 40


def _script(
    s: Session,
    case_id: uuid.UUID,
    durum: str,
    *,
    case_hash: str = "h",
    pass_at_1: bool | None = None,
    engel: str | None = None,
    review: str | None = None,
    head_sha: str | None = None,
    pr_no: int | None = None,
    ilk_sinif: str | None = None,
    zaman: datetime | None = None,
    dil: str = "ts",
) -> uuid.UUID:
    sc = Script(
        id=uuid.uuid4(),
        dosya_yolu=f"e2e/tests/generated/{uuid.uuid4().hex[:6]}.spec.ts",
        durum=durum,
        dil=dil,
        pass_at_1=pass_at_1,
        insan_review_sonucu=review,
        head_sha=head_sha,
        pr_no=pr_no,
    )
    s.add(sc)
    s.flush()
    if zaman is not None:
        s.execute(update(Script).where(Script.id == sc.id).values(olusturma=zaman))
    s.add_all(
        [
            ScriptTestCase(script_id=sc.id, test_case_id=case_id),
            ScriptCodegen(
                script_id=sc.id,
                test_case_id=case_id,
                case_hash=case_hash,
                sira_no=1,
                engel_turu=engel,
            ),
        ]
    )
    if ilk_sinif is not None:
        s.add(
            ScriptKontrol(
                script_id=sc.id,
                tur="local_check",
                sha=head_sha or SHA,
                sonuc="success" if ilk_sinif == "gecti" else "failure",
                sinif=ilk_sinif,
            )
        )
    s.flush()
    return sc.id


def test_script_kpilari_karisik_sonuclar(engine: Engine, make_requirement_case) -> None:
    """Yalnızca 'kabul' yazılsa bile oran %100'e kilitlenmez; yeniden üretim tek sayılır."""
    c = [make_requirement_case(title=f"case {i}") for i in range(7)]
    t0 = datetime.now(UTC) - timedelta(hours=5)
    with Session(engine) as s, s.begin(), allow_state_write():
        # U1: merged + kabul + PR head'inde CI geçti → pay.
        _script(s, c[0], "merged", pass_at_1=True, review="kabul", head_sha=SHA_B, pr_no=11,
                ilk_sinif="gecti")  # fmt: skip
        # U2: locator → iki kez üretildi, ikisi de insana düştü (aynı onaylı hash) → payda, 1 birim.
        _script(s, c[1], "closed", pass_at_1=False, engel="locator", ilk_sinif="locator",
                zaman=t0)  # fmt: skip
        _script(s, c[1], "blocked", pass_at_1=False, engel="locator", ilk_sinif="locator")
        # U3: defect adayı, aynı hash ile yeniden üretildi → ayrı sayılır, pass@1'e girmez.
        _script(s, c[2], "closed", pass_at_1=False, engel="defect_candidate",
                ilk_sinif="defect_adayi", zaman=t0)  # fmt: skip
        _script(s, c[2], "blocked", pass_at_1=False, engel="defect_candidate",
                ilk_sinif="defect_adayi")  # fmt: skip
        # U4: PR açık, review bekliyor → paydaya girmez.
        _script(s, c[3], "pr_open", pass_at_1=True, ilk_sinif="gecti", head_sha=SHA_C)
        # U5: merged + kabul ama merge commit'indeki CI'da kaldı → payda, pay değil.
        _script(s, c[4], "merged", pass_at_1=True, review="kabul", head_sha=SHA_C, pr_no=12,
                ilk_sinif="gecti")  # fmt: skip
        # U6: ortam hatası → ayrı sayılır.
        _script(s, c[5], "blocked", engel="environment", ilk_sinif="ortam")
        # U7: case onaydan sonra değişti → yeni hash yeni birim; eskisi PR'dan kapatıldı → payda.
        _script(s, c[6], "closed", pass_at_1=True, case_hash="eski", ilk_sinif="gecti",
                zaman=t0)  # fmt: skip
        s.add(PullRequest(number=12, branch="tp/x", baslik="x", head_sha=SHA_C,
                          merge_sha="d" * 40, acan="engineer", durum="merged"))  # fmt: skip
        simdi = datetime.now(UTC)
        r = _run_ekle(s, "pr", "passed", simdi - timedelta(hours=2), [("U1", "passed", c[0])])
        s.execute(update(Run).where(Run.id == r).values(commit=SHA_B))
        r = _run_ekle(s, "push", "failed", simdi - timedelta(hours=1), [("U5", "failed", c[4])])
        s.execute(update(Run).where(Run.id == r).values(commit="d" * 40))
        s.execute(update(TestResult).where(TestResult.run_id == r).values(commit="d" * 40))
        # Kırma koşusunda (merge commit'inde) geçmesi kanıt sayılmaz.
        kr = _run_ekle(s, "break_verify", "passed", simdi, [("U5", "passed", c[4])],
                       break_campaign=True)  # fmt: skip
        s.execute(update(Run).where(Run.id == kr).values(commit="d" * 40))
        s.execute(update(TestResult).where(TestResult.run_id == kr).values(commit="d" * 40))
    with Session(engine) as s:
        so = ct.script_olculeri(s)
        k = ct.control_tower(s, artefakt=True)
    # Payda: U1, U2, U5, U7 = 4; pay: U1.
    assert (so["script_ilk_review"], so["script_review_sayisi"]) == (0.25, 4)
    assert so["script_ilk_review_kabul"] == 1
    assert (so["script_review_bekleyen"], so["script_ortam_hatasi"]) == (1, 1)
    assert so["script_defect_adayi"] == 1
    assert (so["script_birim_sayisi"], so["script_uretim_sayisi"]) == (7, 9)
    # pass@1: birimin ilk script'i; U1 ✓, U2 ✗, U4 ✓, U5 ✓, U7 ✓ (U3 defect adayı, U6 None).
    assert (so["pass_at_1"], so["pass_at_1_sayisi"], so["pass_at_1_defect_adayi"]) == (0.8, 5, 1)
    ai = k["ai_katkisi"]
    assert ai["script_ilk_review"] == 0.25 and ai["pass_at_1"] == 0.8
    assert any("defect adayı" in u for u in k["uyarilar"])
    assert {x["acik_defect_adayi"] for x in k["karne"] if x["story_key"] == "TPD-1"} == {1}


def test_degisiklik_istenen_birim_sonradan_kabul_ilk_review_sayilmaz(
    engine: Engine, make_requirement_case
) -> None:
    """Birimin önceki script'inde değişiklik istendiyse yeniden üretilip kabul edilen birim
    ilk review başarısı değildir."""
    c = make_requirement_case(title="7 adet → 1 bedava")
    t0 = datetime.now(UTC) - timedelta(hours=3)
    with Session(engine) as s, s.begin(), allow_state_write():
        _script(s, c, "closed", pass_at_1=True, review="degisiklik_istendi",
                engel="human_rejected", ilk_sinif="gecti", zaman=t0)  # fmt: skip
        _script(s, c, "merged", pass_at_1=True, review="kabul", head_sha=SHA_B, pr_no=21,
                ilk_sinif="gecti")  # fmt: skip
        r = _run_ekle(s, "pr", "passed", datetime.now(UTC), [("U", "passed", c)])
        s.execute(update(Run).where(Run.id == r).values(commit=SHA_B))
    with Session(engine) as s:
        so = ct.script_olculeri(s)
    assert (so["script_review_sayisi"], so["script_ilk_review_kabul"]) == (1, 0)
    assert so["script_ilk_review"] == 0.0


def test_yeniden_uretim_pass_at_1_dusurmez(engine: Engine, make_requirement_case) -> None:
    c = make_requirement_case(title="6 adet → bedava yok")
    t0 = datetime.now(UTC) - timedelta(hours=3)
    with Session(engine) as s, s.begin(), allow_state_write():
        _script(s, c, "merged", pass_at_1=True, review="kabul", head_sha=SHA_B, zaman=t0)
    with Session(engine) as s:
        once = ct.script_olculeri(s)
    with Session(engine) as s, s.begin(), allow_state_write():
        for i in range(3):  # demo tekrarları: aynı onaylı hash
            _script(s, c, "failed", pass_at_1=False, zaman=t0 + timedelta(minutes=i + 1))
    with Session(engine) as s:
        sonra = ct.script_olculeri(s)
    assert (once["pass_at_1"], once["pass_at_1_sayisi"]) == (1.0, 1)
    assert (sonra["pass_at_1"], sonra["pass_at_1_sayisi"]) == (1.0, 1)


def test_karne_son_sonuc_main_kosularindan(engine: Engine, senaryo) -> None:
    c1 = senaryo["cases"][0]
    with Session(engine) as s, s.begin():
        # Merge edilmemiş dalın PR koşusu sonra kırmızı: main yeşil kalır, PR ayrı gösterilir.
        d = _run_ekle(s, "pr", "failed", datetime.now(UTC), [("PR", "failed", c1)])
    with Session(engine) as s:
        tpd1 = {x["story_key"]: x for x in ct.karne(s)}["TPD-1"]
    assert (tpd1["son_sonuc"], tpd1["son_kosu_id"]) == ("passed", str(senaryo["c"]))
    assert (tpd1["pr_son_sonuc"], tpd1["pr_son_kosu_id"]) == ("failed", str(d))


def test_betik_onayi_review_suresi_olculmedi(
    engine: Engine, make_requirement_case, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.cases import service as cases

    make_requirement_case()
    make_requirement_case(jira_key="TPD-2")
    olcu = {
        "TPD-1": {"uretilen": 3, "kabul": 3, "ai_sure_ms": 0, "review_sure_ms": 36,
                  "ai_cagri_modlari": {"replay": 1}},
        "TPD-2": {"uretilen": 2, "kabul": 1, "ai_sure_ms": 4000, "review_sure_ms": 90_000,
                  "ai_cagri_modlari": {"live": 1}},
    }  # fmt: skip

    def sahte(session: Session, rid: uuid.UUID) -> dict:
        from tp_core.models import Requirement

        key = session.get(Requirement, rid).jira_key
        return {"jira_key": key, **olcu[key]}

    monkeypatch.setattr(cases, "requirement_metrics", sahte)
    with Session(engine) as s:
        k = ct.control_tower(s, artefakt=True)
    h = {x["story_key"]: x for x in k["hazirlik"]}
    assert h["TPD-1"]["review_sure_ms"] is None and h["TPD-1"]["review_olculmedi"] is True
    assert h["TPD-1"]["ai_sure_ms"] is None and h["TPD-1"]["toplam_ms"] is None
    assert (h["TPD-2"]["review_sure_ms"], h["TPD-2"]["toplam_ms"]) == (90_000, 94_000)
    ai = k["ai_katkisi"]
    assert (ai["ort_review_sure_ms"], ai["ort_ai_sure_ms"]) == (90_000, 4000)
    assert (ai["review_sure_olculen_story"], ai["ai_sure_olculen_story"]) == (1, 1)
    assert any("insan review süresi ölçülmedi" in u for u in k["uyarilar"])
    # n=5 küçük örneklem eşiğinde değil: kabul oranı için uyarı yok.
    assert not any("Case kabul oranı yalnızca" in u for u in k["uyarilar"])


def test_karne_uygulama_alani_page_objectlerden(engine: Engine, senaryo) -> None:
    """§8.11: karne story VE uygulama alanı bazında; alan = adım eşlemesinin page object'i."""
    c1, c2, c3 = senaryo["cases"]
    with Session(engine) as s, s.begin():
        for case, po, no in (
            (c1, "CatalogPage", 1),
            (c1, "CartPage", 2),
            (c2, "CartPage", 1),
            (c3, "OrderPage", 1),
            (c3, "CheckoutWizardPage", 2),
        ):
            s.add(
                StepMapping(
                    test_case_id=case, adim_no=no, po_sinifi=po, po_metodu="m", dogrulandi=True
                )
            )
    with Session(engine) as s:
        k = ct.control_tower(s, artefakt=True)
    tpd1 = {x["story_key"]: x for x in k["karne"]}["TPD-1"]
    assert tpd1["alanlar"] == ["CheckoutWizard", "Katalog", "Sepet", "Sipariş"]
    assert tpd1["alan"] == "CheckoutWizard, Katalog, Sepet, Sipariş"
    alan = {x["alan"]: x for x in k["alan_karnesi"]}
    assert set(alan) == {"CheckoutWizard", "Katalog", "Sepet", "Sipariş"}
    sepet = alan["Sepet"]
    assert (sepet["case_sayisi"], sepet["otomasyon_sayisi"], sepet["story_sayisi"]) == (2, 2, 1)
    assert sepet["otomasyon_kapsami"] == 1.0
    # Sepet case'lerinin main'deki son koşusu C (yeşil); kırma koşusu B sayılmaz.
    assert (sepet["son_sonuc"], sepet["son_kosu_id"]) == ("passed", str(senaryo["c"]))
    siparis = alan["Sipariş"]
    assert (siparis["case_sayisi"], siparis["otomasyon_sayisi"], siparis["son_sonuc"]) == (
        1,
        0,
        "none",
    )


def test_eksik_metot_ve_replay_miss_review_paydasina_girmez(
    engine: Engine, make_requirement_case
) -> None:
    """Demo yolu: C1/C2/C10 merge + kabul; C7 (F4 kredi limiti, code_defect) page object'te eksik
    metot → blocked, PR/insan review'u yok. İlk review başarısı 3/3 olmalı (3/4 değil)."""
    c = [make_requirement_case(title=f"case {i}") for i in range(5)]
    simdi = datetime.now(UTC)
    with Session(engine) as s, s.begin(), allow_state_write():
        for i, sha in enumerate((SHA_B, "e" * 40, "f" * 40)):
            _script(s, c[i], "merged", pass_at_1=True, review="kabul", head_sha=sha,
                    pr_no=30 + i, ilk_sinif="gecti")  # fmt: skip
            r = _run_ekle(s, "pr", "passed", simdi - timedelta(minutes=10 - i),
                          [(f"C{i}", "passed", c[i])])  # fmt: skip
            s.execute(update(Run).where(Run.id == r).values(commit=sha))
        # C7: eksik metot → blocked (kontrol koşmadı, pass@1 ölçülmedi).
        _script(s, c[3], "blocked", engel="missing_method")
        # REPLAY-MISS: kayıtlı doğrulama yok → insan review'u yok.
        _script(s, c[4], "failed", engel="replay_miss")
    with Session(engine) as s:
        so = ct.script_olculeri(s)
    assert (so["script_ilk_review"], so["script_review_sayisi"]) == (1.0, 3)
    assert so["script_ilk_review_kabul"] == 3
    assert (so["script_eksik_metot"], so["script_replay_miss"]) == (1, 1)
    assert (so["script_ortam_hatasi"], so["script_defect_adayi"]) == (0, 0)
    assert (so["pass_at_1"], so["pass_at_1_sayisi"]) == (1.0, 3)


def test_dogrulanmamis_script_review_paydasina_girmez(
    engine: Engine, make_requirement_case
) -> None:
    """MİM-Y2: `unverified` (C# / Python) script PR'a ve insan review'una girmez; ilk review
    başarısının paydasına katılmaz, `script_dogrulanmamis`'ta ayrı sayılır. Eski (yenisi gelince
    kapanmış) doğrulanmamış kayıt da paydaya girmez; aynı case'in merge edilmiş TS testi birimini
    korur (doğrulanmamış üretim onu gizlemez)."""
    c = [make_requirement_case(title=f"case {i}") for i in range(3)]
    with Session(engine) as s, s.begin(), allow_state_write():
        _script(s, c[0], "merged", pass_at_1=True, review="kabul", head_sha=SHA_B, pr_no=40,
                ilk_sinif="gecti")  # fmt: skip
        r = _run_ekle(s, "pr", "passed", datetime.now(UTC) - timedelta(minutes=5),
                      [("C0", "passed", c[0])])  # fmt: skip
        s.execute(update(Run).where(Run.id == r).values(commit=SHA_B))
        # Aynı case + (aynı hash) için sonradan C# üretimi: TS birimini gizlemez.
        _script(s, c[0], "unverified", dil="csharp")
        _script(s, c[1], "unverified", dil="python")
        _script(s, c[2], "closed", dil="csharp")  # eski doğrulanmamış, yenisi gelince kapandı
    with Session(engine) as s:
        so = ct.script_olculeri(s)
        k = ct.control_tower(s, artefakt=True)
    assert so["script_dogrulanmamis"] == 2
    assert (so["script_ilk_review"], so["script_review_sayisi"]) == (1.0, 1)
    assert (so["pass_at_1"], so["pass_at_1_sayisi"]) == (1.0, 1)
    # Tur 2 (MİM-L3): üretim sayısı da tam hat üretimleridir; doğrulanmamış dildeki kayıtlar
    # (unverified + kapanmış eski) yalnız `script_dogrulanmamis`'ta görünür.
    assert so["script_birim_sayisi"] == 1 and so["script_uretim_sayisi"] == 1
    # API yanıtı (`GET /control-tower` `ai_katkisi`) alanı taşır.
    assert k["ai_katkisi"]["script_dogrulanmamis"] == 2


def test_demo_kirma_commiti_gecme_oranina_girmez(engine: Engine) -> None:
    """`make demo-break` locator kırmasının main commit'indeki push koşusu bilerek kırmızıdır."""
    from tp_core.audit import append_audit
    from tp_core.integrations.forge_demo import AUDIT_BREAK

    kirik = "d" * 40
    simdi = datetime.now(UTC)
    with Session(engine) as s, s.begin(), allow_state_write():
        for i in range(12):
            _run_ekle(s, "push", "passed", simdi - timedelta(minutes=30 + i), [])
        r = _run_ekle(s, "push", "failed", simdi - timedelta(minutes=5), [])
        s.execute(update(Run).where(Run.id == r).values(commit=kirik))
        _run_ekle(s, "nightly", "failed", simdi - timedelta(minutes=6), [], break_campaign=True)
    with Session(engine) as s:
        g = ct.gecme_orani(s, 20)
    # Kırma kaydı yokken locator kırması koşusu sayılır; BREAK_CAMPAIGN koşusu zaten hariç.
    assert (g["toplam"], g["gecen"], g["haric_kirma"]) == (13, 12, 1)
    assert g["metin"] == (
        "Son 13 CI koşusundan 12'si geçti (pencere: son 20; 1 kasıtlı kırma koşusu hariç)"
    )
    with engine.begin() as c:
        append_audit(c, "demo-admin", AUDIT_BREAK, "pr:7", {"main_sonra": kirik})
        append_audit(c, "demo-admin", AUDIT_BREAK, "pr:8", {"main_sonra": None})
    with Session(engine) as s:
        g = ct.gecme_orani(s, 20)
        gunluk = ct.gunluk_gecme(s, 14)
    assert (g["oran"], g["toplam"], g["gecen"], g["haric_kirma"]) == (1.0, 12, 12, 2)
    assert g["metin"] == (
        "Son 12 CI koşusundan 12'si geçti (pencere: son 20; 2 kasıtlı kırma koşusu hariç)"
    )
    assert sum(x["kosu"] for x in gunluk) == 12


def test_iyelik_ekleri() -> None:
    assert ct._iyelik(1) == "i" and ct._iyelik(3) == "ü" and ct._iyelik(6) == "sı"
    assert ct._iyelik(10) == "u" and ct._iyelik(0) == "ı" and ct._iyelik(12) == "si"


def test_karne_acik_bug_farkli_jira_anahtari_kirma_taslagi_haric(
    engine: Engine, make_requirement_case
) -> None:
    """C3 bulgusu + F2 hatası aynı TPD-5'e bağlı, F4 yeni TPD-18, kırma koşusu taslağı bekliyor:
    açık bug 2 (farklı anahtar), bekleyen taslak 0 (kırma taslağı sayılmaz)."""
    from tp_core.models import BugDraft, ConsistencyFinding, Failure, Requirement
    from tp_core.models.bugs_feature import BugDraftEk

    c1 = make_requirement_case(title="7 adet Portakal Gazozu → 1 adet bedava")
    simdi = datetime.now(UTC)
    with Session(engine) as s, s.begin(), allow_state_write():
        req_id = s.scalars(select(Requirement.id).where(Requirement.jira_key == "TPD-1")).one()
        bulgu = ConsistencyFinding(
            requirement_id=req_id, tur="doc_vs_code", doc_ref="C3", severity="blocking"
        )
        s.add(bulgu)
        s.flush()

        def _hata(tetik: str, **ortam) -> uuid.UUID:
            rid = _run_ekle(s, tetik, "failed", simdi, [(f"t-{tetik}", "failed", c1)], **ortam)
            tr = s.scalars(select(TestResult.id).where(TestResult.run_id == rid)).one()
            f = Failure(
                run_id=rid, test_result_id=tr, test_adi="t", hata_imzasi="x",
                sinif="product_defect",
            )  # fmt: skip
            s.add(f)
            s.flush()
            return f.id

        f2, f4 = _hata("push"), _hata("nightly")
        kirma = _hata("break_verify", break_campaign=True)

        def _taslak(durum: str, karar: str | None, key: str | None, **bag) -> BugDraft:
            d = BugDraft(
                icerik={}, icerik_hash=uuid.uuid4().hex, durum=durum, karar=karar,
                link_key=key if karar == "link" else None, jira_key=key, **bag,
            )  # fmt: skip
            s.add(d)
            return d

        _taslak("published", "link", "TPD-5", finding_id=bulgu.id)
        _taslak("published", "link", "TPD-5", failure_id=f2)
        _taslak("published", "new", "TPD-18", failure_id=f4)
        _taslak("draft", None, None, failure_id=kirma)
        _taslak("dismissed", None, None, failure_id=f4)
        silinen = _taslak("published", "new", "TPD-19", failure_id=f4)
        s.flush()
        s.add(BugDraftEk(bug_draft_id=silinen.id, kaynak="failure",
                         yayin={"jira_silindi": {"key": "TPD-19"}}))  # fmt: skip

    with Session(engine) as s:
        tpd1 = {x["story_key"]: x for x in ct.karne(s)}["TPD-1"]
    assert (tpd1["acik_bug"], tpd1["bug_taslagi"]) == (2, 0)

    # Kırma olmayan koşudan gelen bekleyen taslak ayrı sayılır, açık bug'ı değiştirmez.
    with Session(engine) as s, s.begin(), allow_state_write():
        s.add(BugDraft(icerik={}, icerik_hash="h", durum="approved", karar="new", failure_id=f2))
        s.flush()
    with Session(engine) as s:
        tpd1 = {x["story_key"]: x for x in ct.karne(s)}["TPD-1"]
    assert (tpd1["acik_bug"], tpd1["bug_taslagi"]) == (2, 1)
