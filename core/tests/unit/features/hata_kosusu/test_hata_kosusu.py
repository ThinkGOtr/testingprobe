"""Ekilmiş hata koşusu (012 §4.6, §4.7, §13 K9/K12; kabul senaryoları 11–14): sahte toolchain +
Postgres. Gerçek rapor yolu için `fixtures/` altındaki Playwright `results.json` ve Surefire XML
toolchain'in kendi ayrıştırıcısından (`toolchain/runner`) geçirilip core'un ingest/sınıflama
yolundan koşturulur."""

from __future__ import annotations

import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA, FakeToolchain, kosu_yaz, login, run_jobs
from tp_core.features.control_tower import service as kule
from tp_core.features.hata_kosusu import jobs as hk_jobs
from tp_core.features.hata_kosusu import katalog as kat
from tp_core.features.hata_kosusu import service
from tp_core.features.hata_kosusu.hatalar import HataKosusuSuruyor
from tp_core.features.triage import jobs as _triage_jobs  # noqa: F401  (iş kaydı)
from tp_core.models import BugDraft, Failure, HataKosusu, HataKosusuAdim, Run, TestResult
from tp_core.models.triage_feature import TriageKosu
from tp_core.workflow import jobs as jobq
from tp_core.workflow.service import Principal, WorkflowError

pytestmark = pytest.mark.usefixtures("ci_env")

DOKUZ = {
    "kampanya_bedava_yok",
    "kampanya_tek_bedava",
    "kampanya_cift_indirim",
    "min_siparis_haric",
    "min_siparis_muafiyet_yok",
    "min_siparis_500",
    "min_siparis_1000",
    "fiyat_p004_31",
    "kampanya_urunu_p002",
}
ASSERTION_HATASI = (
    'Error: expect(locator).toHaveText(expected) failed\n\nExpected: "1"\nReceived: "0"\n'
)
FIX = Path(__file__).parent / "fixtures"
TOOLCHAIN = Path(__file__).resolve().parents[5] / "toolchain"
AI_TEST = "tests/generated/tpd-1-c11-1a2b3c4d.spec.ts"
JAVA_AI_TEST = "src/test/java/com/antreklabs/bayi/uretilen/TPD1AndroidC11_1a2b3c4dTest.java"


def uretilen_kaydet(
    engine: Engine,
    dosya: str = AI_TEST,
    platform: str = "web",
    *,
    case_durum: str = "approved",
    hash_eslesir: bool = True,
) -> None:
    """`dosya`'yı (e2e / e2e-app köküne göre) onaylı bir case'in onaylı içeriğinden üretilmiş test
    olarak kaydeder (gereksinim + case + script + script_codegen; Y7)."""
    from tp_core.features.codegen.service import e2e_app_root, e2e_root
    from tp_core.models import Requirement, Script, TestCase
    from tp_core.models.codegen_feature import ScriptCodegen
    from tp_core.models.guard import allow_state_write

    kok = e2e_root() if platform == "web" else e2e_app_root()
    with allow_state_write(), Session(engine) as s, s.begin():
        req = Requirement(
            kaynak="jira",
            jira_key=f"TPD-{uuid.uuid4().hex[:6]}",
            baslik="b",
            kaynak_hash="h",
            durum="cases_ready",
        )
        s.add(req)
        s.flush()
        h = uuid.uuid4().hex
        tc = TestCase(
            id=uuid.uuid4(),
            requirement_id=req.id,
            sira_no=1,
            icerik={"title": "t"},
            icerik_hash=h,
            onaylanan_hash=h if case_durum in ("approved", "published") else None,
            durum=case_durum,
        )
        sc = Script(id=uuid.uuid4(), dosya_yolu=f"{kok}/{dosya}", platform=platform)
        s.add_all([tc, sc])
        s.flush()
        s.add(
            ScriptCodegen(
                script_id=sc.id,
                test_case_id=tc.id,
                case_hash=h if hash_eslesir else "eski" + h,
                sira_no=1,
            )
        )


# ------------------------------------------------------------------ sahte toolchain raporu


def _test(ad: str, durum: str = "expected", **ek: Any) -> dict[str, Any]:
    return {"title": ad, "file": ek.pop("file", "cart.spec.ts"), "status": durum, **ek}


def _assertion(ad: str, **ek: Any) -> dict[str, Any]:
    return _test(
        ad,
        "unexpected",
        error=ASSERTION_HATASI,
        failure={"type": "assertion", "expected": "1", "received": "0"},
        **ek,
    )


def _locator(ad: str, **ek: Any) -> dict[str, Any]:
    return _test(
        ad,
        "unexpected",
        error="locator.click: Timeout 5000ms exceeded.",
        failure={"type": "locator_timeout"},
        **ek,
    )


def rapor(
    kok: Path, body: dict[str, Any], sonuc: str, testler: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """`sonuc`: yesil | assertion | locator | saglik | appium_yok | derleme | testler (verilen
    `testler` listesi; kırmızı varsa koşu kırmızı)."""
    platform = body.get("platform") or "web"
    if sonuc == "testler":
        assert testler is not None
        yesil = all(t["status"] in ("expected", "passed", "skipped") for t in testler)
    else:
        yesil = sonuc == "yesil"
    ortam_hatasi = sonuc in ("saglik", "appium_yok")
    r = kosu_yaz(
        kok,
        body["run_id"],
        sha=body["sha"],
        durum="passed" if yesil else ("error" if ortam_hatasi else "failed"),
        conclusion="success" if yesil else "failure",
        saglik_ok=not ortam_hatasi,
    )
    if testler is None:
        testler = [
            _test("TPD-1 › 6 adet → 1 bedava"),
            _test("TPD-1 › minimum sipariş 750 dahil"),
        ]
        if sonuc == "assertion":
            testler[0] = _assertion("TPD-1 › 6 adet → 1 bedava")
        elif sonuc == "locator":
            testler[1] = _locator("TPD-1 › minimum sipariş 750 dahil")
        elif ortam_hatasi:
            testler = []
        elif sonuc == "derleme":
            r["tsc"] = {"ok": False, "error": "TS2304"}
            r["run"]["status"] = "skipped"
            testler = []
    r["run"]["tests"] = testler
    if platform != "web":
        r["lang"] = "java"
        r["platform"] = platform
        for ad in ("tsc", "eslint", "ast_guard"):
            r.pop(ad, None)
        r.update(
            app={"ok": True},
            deps={"ok": True},
            guard={"ok": True, "mode": "pr"},
            compile={"ok": True},
        )
        if sonuc == "appium_yok":
            r["run"]["saglik"] = {
                "ok": False,
                "api": {"url": "http://demo-api:8000/health", "hata": None},
                "appium": {"url": "http://appium:4723", "hata": "bağlantı reddedildi"},
                "hata": "Uygulama test ortamı sağlık kontrolü başarısız — appium",
            }
            r["run"]["error"] = r["run"]["saglik"]["hata"]
    return r


Plan = Callable[[str, str | None], Any]


def kur(
    toolchain: FakeToolchain,
    plan: Plan,
    kanca: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """`plan(platform, fault)` → rapor türü, `ulasilamaz` (bağlantı hatası) ya da test listesi."""

    def yanit(body: dict[str, Any]) -> httpx.Response:
        if kanca is not None:
            kanca(body)
        tur = plan(body.get("platform") or "web", body.get("fault"))
        if tur == "ulasilamaz":
            raise httpx.ConnectError("bağlantı reddedildi")
        if isinstance(tur, list):
            return httpx.Response(200, json=rapor(toolchain.kok, body, "testler", tur))
        if callable(tur):
            return httpx.Response(200, json=tur(toolchain.kok, body))
        return httpx.Response(200, json=rapor(toolchain.kok, body, tur))

    toolchain.yanit = yanit


def baslat(engine: Engine, user: Principal, platformlar=("web",), hatalar=None) -> uuid.UUID:
    with Session(engine) as s, s.begin():
        return uuid.UUID(service.baslat(s, list(platformlar), hatalar, user)["id"])


def detay(engine: Engine, kid: uuid.UUID) -> dict[str, Any]:
    with Session(engine) as s, s.begin():
        d = service.detay(s, kid)
    assert d is not None
    return d


def adim(d: dict[str, Any], platform: str, asama: str, kod: str | None = None) -> dict[str, Any]:
    return next(
        a
        for a in d["adimlar"]
        if a["platform"] == platform and a["asama"] == asama and a["hata_kodu"] == kod
    )


def isler(engine: Engine, kid: uuid.UUID) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text(
                    "SELECT idempotency_key, durum, deneme, max_deneme, zaman_asimi_s FROM job "
                    "WHERE idempotency_key LIKE :k ORDER BY olusturma, id"
                ),
                {"k": f"{service.JOB}:{kid}:%"},
            ).all()
        )


def _denetim_detayi(engine: Engine, kid: uuid.UUID, eylem: str) -> str:
    """Koşunun `eylem` denetim kayıtlarındaki `detay` metinleri (birleşik)."""
    with engine.connect() as c:
        ozetler = c.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = :e AND nesne = :n ORDER BY id"),
            {"e": eylem, "n": f"hata_kosusu:{kid}"},
        ).scalars()
        return " | ".join(str((o or {}).get("detay") or "") for o in ozetler)


def kosu_durumu(engine: Engine, kid: uuid.UUID) -> str:
    with engine.connect() as c:
        return c.execute(
            text("SELECT durum FROM hata_kosusu WHERE id = :i"), {"i": kid}
        ).scalar_one()


def adim_isleri(engine: Engine) -> list[Any]:
    return run_jobs(engine, limit=60)


@pytest.fixture
def muhendis(make_user) -> Principal:
    return make_user("engineer")


# ------------------------------------------------------------------ gerçek rapor yolu


@pytest.fixture
def tc_runner() -> Any:
    """toolchain'in rapor ayrıştırıcıları (`runner.results`, `runner.surefire`); stdlib'dir."""
    if not (TOOLCHAIN / "runner" / "results.py").exists():
        pytest.skip("toolchain kaynağı yok")
    if str(TOOLCHAIN) not in sys.path:
        sys.path.insert(0, str(TOOLCHAIN))
    from runner import results, surefire

    return results, surefire


def pw_raporu(tc: Any, ad: str) -> Callable[[Path, dict[str, Any]], dict[str, Any]]:
    """Gerçek Playwright `results.json` (fixtures/pw-<ad>.json) → toolchain `/check` yanıtı: dosya
    koşu dizinine yazılır, testler toolchain'in `results.summarize`'ıyla çıkarılır."""
    results, _ = tc

    def yap(kok: Path, body: dict[str, Any]) -> dict[str, Any]:
        ham = (FIX / f"pw-{ad}.json").read_bytes()
        ozet_dosya = kok / "gecici" / f"{body['run_id']}.json"
        ozet_dosya.parent.mkdir(parents=True, exist_ok=True)
        ozet_dosya.write_bytes(ham)
        testler = results.summarize(ozet_dosya, ozet_dosya.parent)["tests"]
        kirmizi = any(t["status"] not in ("expected", "flaky", "skipped") for t in testler)
        r = kosu_yaz(
            kok,
            body["run_id"],
            sha=body["sha"],
            results=ham,
            junit=b"",
            durum="failed" if kirmizi else "passed",
            conclusion="failure" if kirmizi else "success",
        )
        r["run"]["tests"] = testler
        return r

    return yap


def surefire_raporu(tc: Any, ad: str) -> Callable[[Path, dict[str, Any]], dict[str, Any]]:
    """Gerçek Surefire XML (fixtures/surefire-<ad>/TEST-*.xml) → toolchain Java `/check` yanıtı:
    testler toolchain'in `surefire.summarize`'ıyla çıkarılır, core'un okuduğu birleşik
    `junit.xml` `surefire.write_junit`'le yazılır."""
    _, surefire = tc

    def yap(kok: Path, body: dict[str, Any]) -> dict[str, Any]:
        tekrar = surefire.Repeat(0, FIX / f"surefire-{ad}", kok / "yok")
        testler = surefire.summarize([tekrar], project=body.get("platform") or "android")["tests"]
        junit = kok / "gecici" / f"{body['run_id']}.xml"
        junit.parent.mkdir(parents=True, exist_ok=True)
        surefire.write_junit([tekrar], junit)
        kirmizi = any(t["status"] == "unexpected" for t in testler)
        r = kosu_yaz(
            kok,
            body["run_id"],
            sha=body["sha"],
            results=b"",
            junit=junit.read_bytes(),
            durum="failed" if kirmizi else "passed",
            conclusion="failure" if kirmizi else "success",
        )
        r["run"]["tests"] = testler
        r["run"]["json"] = r["run"]["json_path"] = None
        for a in ("tsc", "eslint", "ast_guard"):
            r.pop(a, None)
        r.update(
            lang="java",
            platform=body.get("platform"),
            app={"ok": True},
            deps={"ok": True},
            guard={"ok": True, "mode": "pr"},
            compile={"ok": True},
        )
        return r

    return yap


def test_gercek_playwright_raporu_k12_sayimi(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain, tc_runner: Any
) -> None:
    """Temelde 1 kırmızı (assertion) test; hatalı koşuda üretilen test assertion ile, el yazısı
    iki test `toBeVisible` zaman aşımı (öğe yok) ve `locator.click` zaman aşımıyla kırmızı."""
    planlar = {
        None: pw_raporu(tc_runner, "temel"),
        "kampanya_tek_bedava": pw_raporu(tc_runner, "hata"),
        "min_siparis_500": pw_raporu(tc_runner, "hata-yalniz-locator"),
    }
    kur(toolchain, lambda p, f: planlar[f])
    uretilen_kaydet(engine)
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava", "min_siparis_500"])
    adim_isleri(engine)
    d = detay(engine, kid)
    assert d["durum"] == "done", d["uyarilar"]
    temel = adim(d, "web", "temel")
    # Temelde kırmızı test koşuyu geçersiz kılmaz; listelenir.
    assert temel["sonuc"] == "kirmizi"
    assert temel["kiran_testler"] == [
        {"test": "Sepet (el yazısı) › bilinen kırmızı: kredi limiti uyarısı", "kaynak": "el"}
    ]
    yak = adim(d, "web", "hata", "kampanya_tek_bedava")
    assert yak["sonuc"] == "yakalandi"
    # Yalnız assertion kırmızısı kanıttır; kaynağı üretilen test (tests/generated/).
    assert yak["kiran_testler"] == [
        {"test": "TPD-1-C11 (üretilen) › 14 adette 2 bedava", "kaynak": "ai"}
    ]
    assert yak["temelde_kirmizi"] == ["Sepet (el yazısı) › bilinen kırmızı: kredi limiti uyarısı"]
    assert "Assertion dışı kırmızı 2 test" in yak["neden"]
    assert "minimum uyarısı görünür" in yak["neden"] and "sipariş onaylanır" in yak["neden"]
    loc = adim(d, "web", "hata", "min_siparis_500")
    assert loc["sonuc"] == "gecersiz" and "assertion" in loc["neden"]
    assert {k["test"] for k in loc["kiran_testler"]} == {
        "Sepet (el yazısı) › minimum uyarısı görünür",
        "Sepet (el yazısı) › sipariş onaylanır",
    }
    assert loc["temelde_kirmizi"] == temel_adlari(temel)
    kapanis = adim(d, "web", "kapanis")
    # Kapanışta yalnız temelde kırmızı test kırmızı: yeşil sayılır.
    assert kapanis["sonuc"] == "yesil" and kapanis["temelde_kirmizi"] == temel_adlari(temel)
    oz = d["ozet"]
    assert (oz["oran"], oz["yakalanan"], oz["kacan"], oz["gecersiz"]) == (1.0, 1, 0, 1)
    # El yazısı suite bu hatayı assertion ile yakalamadı (kırmızıları locator/zaman aşımı).
    assert oz["el_yazisi"] == {"oran": 0.0, "yakalanan": 0, "kacan": 1}
    web = oz["platformlar"][0]
    # Envanter yalnız temelde yeşil testlerden (N3): 4 el yazısı testin biri temelde kırmızı.
    assert (web["uretilen_test"], web["el_test"]) == (1, 3)
    assert oz["kapsam"]["kosulan_hata"] == 2 and oz["kapsam"]["tam_katalog"] is False
    with Session(engine) as s:
        run = s.get(Run, uuid.UUID(yak["run_id"]))
        assert run.sonuc == "failed" and run.tetik == "break_verify"
        # ingest_check_report gerçek results.json'u işledi: 5 test satırı.
        n = s.scalar(select(func.count()).where(TestResult.run_id == run.id))
        assert n == 5
    for b in toolchain.istekler:
        assert b["record_check"] is False


def temel_adlari(temel: dict[str, Any]) -> list[str]:
    return [k["test"] for k in temel["kiran_testler"]]


def test_gercek_surefire_raporu_android(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain, tc_runner: Any
) -> None:
    """Java: üretilen test (`…/bayi/uretilen/`) AssertionError (`Bekle.dogrula`), el yazısı
    `TimeoutException` (tıklanabilir olmadı / görünmedi), temelde kırmızı AssertionError."""
    planlar = {
        None: surefire_raporu(tc_runner, "temel"),
        "kampanya_tek_bedava": surefire_raporu(tc_runner, "hata"),
    }
    kur(toolchain, lambda p, f: planlar[f])
    uretilen_kaydet(engine, JAVA_AI_TEST, "android")
    kid = baslat(engine, muhendis, ["android"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    d = detay(engine, kid)
    assert d["durum"] == "done", d["uyarilar"]
    assert (
        toolchain.istekler[0]["lang"] == "java" and toolchain.istekler[0]["platform"] == "android"
    )
    assert adim(d, "android", "temel")["sonuc"] == "kirmizi"
    yak = adim(d, "android", "hata", "kampanya_tek_bedava")
    assert yak["sonuc"] == "yakalandi"
    assert yak["kiran_testler"] == [
        {"test": "TPD1AndroidC11_1a2b3c4dTest › ondortAdetteIkiBedava", "kaynak": "ai"}
    ]
    assert yak["temelde_kirmizi"] == ["SepetTesti › krediLimitiUyarisi"]
    assert "SiparisTesti › siparisOnaylanir" in yak["neden"]
    assert "SepetTesti › minimumUyarisiGorunur" in yak["neden"]
    oz = d["ozet"]
    assert (oz["oran"], oz["yakalanan"], oz["kacan"]) == (1.0, 1, 0)
    assert oz["el_yazisi"] == {"oran": 0.0, "yakalanan": 0, "kacan": 1}
    with Session(engine) as s:
        run = s.get(Run, uuid.UUID(yak["run_id"]))
        assert run.ortam["platform"] == "android" and run.sonuc == "failed"
        assert s.scalar(select(func.count()).where(TestResult.run_id == run.id)) == 4


# ------------------------------------------------------------------ katalog


def test_katalog_dokuz_kod_ve_k9_alanlari() -> None:
    kat.onbellegi_temizle()
    hatalar = kat.katalog()
    assert {h["kod"] for h in hatalar} == DOKUZ and len(hatalar) == 9
    assert "kampanya_esik_7" not in {h["kod"] for h in hatalar}
    assert all(h["tur"] in ("kod", "veri") and h["ad"] and h["aciklama"] for h in hatalar)
    veri = {h["kod"] for h in hatalar if h["tur"] == "veri"}
    assert veri == {"min_siparis_500", "min_siparis_1000", "fiyat_p004_31", "kampanya_urunu_p002"}
    for h in hatalar:
        assert set(h) == {
            "kod",
            "ad",
            "tur",
            "aciklama",
            "yakalayan_kural",
            "ac_refs",
            "tablo",
            "ayirt_edici",
        }
        ae = h["ayirt_edici"]
        assert set(ae) == {"girdi", "dogru", "hatali"} and ae["dogru"] != ae["hatali"]
    k = {h["kod"]: h for h in hatalar}
    tek = k["kampanya_tek_bedava"]
    assert (tek["ac_refs"], tek["tablo"]) == (["AC2"], "T1")
    assert tek["ayirt_edici"]["girdi"]["adet"] == 14
    # u2 N6: 12 adette story (T1, adet // 7) de 1 der; ayrılan adet 14'tür ve açıklamada öndedir.
    assert tek["aciklama"].startswith("Ayırt edici girdi 14 adet: doğru 2 bedava, hatalı 1.")
    assert "14 adette (7'nin 2 katı) ayrılır" in tek["aciklama"]
    assert all("12 adet" not in h["aciklama"] for h in hatalar)
    assert tek["ayirt_edici"]["dogru"]["bedava_adet"] == 2
    assert tek["ayirt_edici"]["hatali"]["bedava_adet"] == 1
    assert k["min_siparis_haric"]["tablo"] == "T2" and k["fiyat_p004_31"]["tablo"] is None
    assert "eski değer" in k["min_siparis_500"]["aciklama"]
    # Ayırt edici kampanya girdileri story (`adet // 7`) ve uygulama (`adet // 6`) kurallarının
    # aynı doğru sonucu verdiği adetlerdendir.
    for kod in ("kampanya_bedava_yok", "kampanya_tek_bedava", "kampanya_urunu_p002"):
        ae = k[kod]["ayirt_edici"]
        adet = ae["girdi"]["adet"]
        assert adet // 7 == adet // 6 == ae["dogru"]["bedava_adet"]


def test_katalog_dogrulama_hatalari() -> None:
    ham = yaml.safe_load(kat.katalog_yolu().read_text(encoding="utf-8"))
    assert len(kat.dogrula(ham)) == 9
    ilk = ham["hatalar"][0]
    with pytest.raises(kat.KatalogHatasi, match="iki kez"):
        kat.dogrula({**ham, "hatalar": [*ham["hatalar"], ilk]})
    with pytest.raises(kat.KatalogHatasi, match="geçersiz hata kodu"):
        kat.dogrula({**ham, "hatalar": [{**ilk, "kod": "Kötü-Kod"}]})
    with pytest.raises(kat.KatalogHatasi, match="tür"):
        kat.dogrula({**ham, "hatalar": [{**ilk, "tur": "baska"}]})
    with pytest.raises(kat.KatalogHatasi, match="eksik alan"):
        kat.dogrula({**ham, "hatalar": [{"kod": "x"}]})
    with pytest.raises(kat.KatalogHatasi, match="sürüm"):
        kat.dogrula({**ham, "version": 2})
    eksik = {a: v for a, v in ilk.items() if a != "ayirt_edici"}
    with pytest.raises(kat.KatalogHatasi, match="eksik alan: ayirt_edici"):
        kat.dogrula({**ham, "hatalar": [eksik]})
    with pytest.raises(kat.KatalogHatasi, match="ac_refs"):
        kat.dogrula({**ham, "hatalar": [{**ilk, "ac_refs": ["ac 2"]}]})
    with pytest.raises(kat.KatalogHatasi, match="tablo"):
        kat.dogrula({**ham, "hatalar": [{**ilk, "tablo": "tablo1"}]})
    ayni = {"girdi": {"adet": 7}, "dogru": {"bedava_adet": 1}, "hatali": {"bedava_adet": 1}}
    with pytest.raises(kat.KatalogHatasi, match="ayırt etmiyor"):
        kat.dogrula({**ham, "hatalar": [{**ilk, "ayirt_edici": ayni}]})


def test_istek_dogrulama(engine: Engine, muhendis: Principal) -> None:
    with Session(engine) as s, s.begin():
        with pytest.raises(service.GecersizIstek, match="Bilinmeyen platform") as e:
            service.baslat(s, ["web", "linux"], None, muhendis)
        assert e.value.kod == "gecersiz_istek" and e.value.status_code == 422
        with pytest.raises(service.GecersizIstek, match="Katalogda olmayan"):
            service.baslat(s, ["web"], ["yok_boyle"], muhendis)
        with pytest.raises(service.GecersizIstek, match="En az bir platform"):
            service.baslat(s, [], None, muhendis)
    # Platformlar sabit sırada (web önce), hatalar katalog sırasında; tekrarlar düşer.
    assert service.platformlari_dogrula(["ios", "web", "ios"]) == ["web", "ios"]
    assert service.hatalari_dogrula(["min_siparis_500", "kampanya_tek_bedava"]) == [
        "kampanya_tek_bedava",
        "min_siparis_500",
    ]


# ------------------------------------------------------------------ başlatma


def test_baslatma_adimlari_ve_ilk_isi_yazar(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis, ["android", "web"], ["kampanya_tek_bedava", "min_siparis_500"])
    d = detay(engine, kid)
    assert d["durum"] == "queued" and d["platformlar"] == ["web", "android"]
    assert d["ozet"] is None and d["baslatan"] == muhendis.kullanici_adi
    assert d["iptal_istendi"] is False
    sira = [(a["sira"], a["platform"], a["asama"], a["hata_kodu"]) for a in d["adimlar"]]
    assert sira == [
        (0, "web", "temel", None),
        (1, "web", "hata", "kampanya_tek_bedava"),
        (2, "web", "hata", "min_siparis_500"),
        (3, "web", "kapanis", None),
        (4, "android", "temel", None),
        (5, "android", "hata", "kampanya_tek_bedava"),
        (6, "android", "hata", "min_siparis_500"),
        (7, "android", "kapanis", None),
    ]
    assert all(a["sonuc"] == "bekliyor" and a["run_id"] is None for a in d["adimlar"])
    assert all(a["temelde_kirmizi"] == [] for a in d["adimlar"])
    # Yalnız ilk adımın işi kuyrukta; süre sınırı adım başına.
    (is_,) = isler(engine, kid)
    assert is_.idempotency_key == service.is_anahtari(kid, 0)
    assert is_.durum == "queued" and is_.max_deneme == service.ADIM_DENEME == 2
    assert is_.zaman_asimi_s == service.adim_zaman_asimi_s() > 3000
    with engine.connect() as c:
        tarama = c.execute(
            text("SELECT durum, run_after > now() FROM job WHERE tur = :t"),
            {"t": service.JOB_TARAMA},
        ).all()
    assert [tuple(t) for t in tarama] == [("queued", True)]
    from tp_core.workflow.jobs import REGISTRY, serit_turleri, uzun_turler

    assert "hata_kosusu.calistir" in uzun_turler() and REGISTRY["hata_kosusu.calistir"]
    assert service.JOB_TARAMA in serit_turleri("genel")


def test_suren_kosu_varken_ikincisi_409(engine: Engine, muhendis: Principal) -> None:
    baslat(engine, muhendis)
    with Session(engine) as s, s.begin(), pytest.raises(HataKosusuSuruyor):
        service.baslat(s, ["web"], None, muhendis)


def test_eszamanli_iki_baslatma_biri_202_biri_409(engine: Engine, muhendis: Principal) -> None:
    """İki oturum aynı anda başlatır: ikincisi birincinin kilidini bekler, commit sonrası 409."""
    sonuc: dict[str, Any] = {}
    a = Session(engine)
    a.begin()
    service.baslat(a, ["web"], None, muhendis)

    def ikinci() -> None:
        with Session(engine) as b, b.begin():
            try:
                sonuc["b"] = service.baslat(b, ["web"], None, muhendis)
            except HataKosusuSuruyor as exc:
                sonuc["b_hata"] = exc

    t = threading.Thread(target=ikinci)
    t.start()
    time.sleep(0.5)
    assert t.is_alive()  # advisory lock'ta bekliyor
    a.commit()
    a.close()
    t.join(10)
    assert "b" not in sonuc and isinstance(sonuc.get("b_hata"), HataKosusuSuruyor)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM hata_kosusu")).scalar_one() == 1


# ------------------------------------------------------------------ iş: senaryolar


def test_web_mutlu_yol_adim_basina_is_senaryo_11(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "assertion" if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava", "min_siparis_500"])
    adim_isleri(engine)
    # Her adım tam suite, CI gövdesiyle; retries=0, repeat_each=1, record_check=false.
    assert len(toolchain.istekler) == 4
    for b in toolchain.istekler:
        assert b["sha"] == SHA and b["test_files"] == []
        assert (b["retries"], b["repeat_each"], b["ast_guard_mode"]) == (0, 1, "pr")
        assert b["record_check"] is False
        assert "lang" not in b and "platform" not in b
    assert [b.get("fault") for b in toolchain.istekler] == [
        None,
        "kampanya_tek_bedava",
        "min_siparis_500",
        None,
    ]
    # Adım başına bir iş: devam işleri sırayla kuyruğa alındı.
    assert [(r.idempotency_key, r.durum) for r in isler(engine, kid)] == [
        (service.is_anahtari(kid, i), "done") for i in range(4)
    ]
    d = detay(engine, kid)
    assert d["durum"] == "done" and d["commit"] == SHA and d["bitis"] and d["baslama"]
    assert [a["sonuc"] for a in d["adimlar"]] == ["yesil", "yakalandi", "yakalandi", "yesil"]
    yak = adim(d, "web", "hata", "kampanya_tek_bedava")
    assert yak["kiran_testler"] == [{"test": "TPD-1 › 6 adet → 1 bedava", "kaynak": "el"}]
    assert yak["hata_adi"] == "Kampanyada en çok 1 bedava" and yak["sure_ms"] is not None
    oz = d["ozet"]
    # Suite'te üretilen test yok: ana (AI) oran ölçülmez; el yazısı suite ayrı.
    assert oz["oran"] is None and oz["yakalanan"] == 0 and oz["kacanlar"] == []
    assert oz["el_yazisi"] == {"oran": 1.0, "yakalanan": 2, "kacan": 0}
    assert oz["tum_testler"] == {"oran": 1.0, "yakalanan": 2, "kacan": 0}
    assert "_ic" not in oz and d["uyarilar"] == []
    with Session(engine) as s:
        for a in d["adimlar"]:
            run = s.get(Run, uuid.UUID(a["run_id"]))
            assert run.tetik == "break_verify" and run.kaynak == "local"
            assert run.ortam["hata_kosusu_id"] == str(kid)
            assert run.ortam["hata_kodu"] == a["hata_kodu"]
            assert run.ortam["platform"] == "web" and run.ortam["break_campaign"] is False
            assert run.sonuc == ("passed" if a["asama"] != "hata" else "failed")
            assert run.artefaktlar["dizin"].startswith("runs/hk-")
        from tp_core.features.ci.service import run_detail

        rd = run_detail(s, uuid.UUID(yak["run_id"]))
        assert rd["hata_kodu"] == "kampanya_tek_bedava" and rd["hata_kosusu_id"] == str(kid)


def test_uzun_serit_adimlar_arasinda_serbest_kalir(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    """Adım koşarken kuyruğa giren başka bir uzun iş, koşunun sonraki adımından önce koşar
    (tek iş tüm koşuyu şeritte tutmaz)."""
    diger: dict[str, uuid.UUID] = {}

    def kanca(body: dict[str, Any]) -> None:
        if "fault" not in body and "id" not in diger:
            with engine.begin() as c:
                diger["id"] = jobq.enqueue(c, "noop", {})

    kur(toolchain, lambda p, f: "yesil", kanca)
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    jobq.process_one(engine, "w", turler=[service.JOB])  # temel; sırada noop + devam işi
    assert jobq.process_one(engine, "w", turler=[service.JOB, "noop"]) is not None
    with engine.connect() as c:
        noop = c.execute(text("SELECT durum FROM job WHERE id = :i"), {"i": diger["id"]})
        assert noop.scalar_one() == "done"
    assert [r.durum for r in isler(engine, kid)] == ["done", "queued"]
    adim_isleri(engine)
    assert kosu_durumu(engine, kid) == "done"


def test_temel_ortam_hatasi_platform_gecersiz(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "saglik")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava", "min_siparis_500"])
    adim_isleri(engine)
    assert len(toolchain.istekler) == 1  # yalnız temel koşu
    d = detay(engine, kid)
    assert d["durum"] == "done"
    assert adim(d, "web", "temel")["sonuc"] == "gecersiz"
    for a in d["adimlar"][1:]:
        assert a["sonuc"] == "gecersiz" and a["neden"].startswith("temel koşu yeşil değil")
        assert a["run_id"] is None
    assert d["ozet"]["oran"] is None and d["ozet"]["gecersiz"] == 2


def test_temelde_kirmizi_test_haric_tutulur_platform_surer(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kirmizi = _assertion("bilinen kırmızı")
    temel = [_test("a"), kirmizi]
    hatali = [_assertion("a"), kirmizi]
    yalniz_bilinen = [_test("a"), kirmizi]
    planlar: dict[str | None, Any] = {
        None: temel,
        "kampanya_tek_bedava": hatali,
        "min_siparis_500": yalniz_bilinen,
    }
    kur(toolchain, lambda p, f: planlar[f])
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava", "min_siparis_500"])
    adim_isleri(engine)
    d = detay(engine, kid)
    assert len(toolchain.istekler) == 4
    assert adim(d, "web", "temel")["sonuc"] == "kirmizi"
    yak = adim(d, "web", "hata", "kampanya_tek_bedava")
    assert yak["sonuc"] == "yakalandi"
    assert yak["kiran_testler"] == [{"test": "a", "kaynak": "el"}]
    assert yak["temelde_kirmizi"] == ["bilinen kırmızı"]
    kac = adim(d, "web", "hata", "min_siparis_500")
    # Yalnız temelde zaten kırmızı test kırmızı: hata yakalanmadı.
    assert kac["sonuc"] == "kacti" and kac["temelde_kirmizi"] == ["bilinen kırmızı"]
    assert "Temelde zaten kırmızı 1 test sayılmadı" in kac["neden"]
    assert adim(d, "web", "kapanis")["sonuc"] == "yesil"
    assert d["ozet"]["el_yazisi"] == {"oran": 0.5, "yakalanan": 1, "kacan": 1}


def test_ai_el_ayrimi(engine: Engine, muhendis: Principal, toolchain: FakeToolchain) -> None:
    """Üretilen (`tests/generated/`) ve el yazısı testler ayrı oranlanır; ana oran AI."""
    ai = {"file": AI_TEST}
    temel = [_test("üretilen", **ai), _test("el")]
    planlar: dict[str | None, Any] = {
        None: temel,
        # Yalnız el yazısı test yakalar → AI kaçırdı.
        "kampanya_tek_bedava": [_test("üretilen", **ai), _assertion("el")],
        # Yalnız üretilen test yakalar.
        "min_siparis_500": [_assertion("üretilen", **ai), _test("el")],
        # İkisi de.
        "min_siparis_1000": [_assertion("üretilen", **ai), _assertion("el")],
    }
    kur(toolchain, lambda p, f: planlar[f])
    uretilen_kaydet(engine)
    kid = baslat(
        engine, muhendis, ["web"], ["kampanya_tek_bedava", "min_siparis_500", "min_siparis_1000"]
    )
    adim_isleri(engine)
    d = detay(engine, kid)
    assert adim(d, "web", "hata", "min_siparis_1000")["kiran_testler"] == [
        {"test": "üretilen", "kaynak": "ai"},
        {"test": "el", "kaynak": "el"},
    ]
    oz = d["ozet"]
    assert (oz["oran"], oz["yakalanan"], oz["kacan"]) == (round(2 / 3, 4), 2, 1)
    assert oz["el_yazisi"] == {"oran": round(2 / 3, 4), "yakalanan": 2, "kacan": 1}
    assert oz["tum_testler"] == {"oran": 1.0, "yakalanan": 3, "kacan": 0}
    # Her hata en az bir testle yakalandı: `kacanlar` boş; AI testleri birini kaçırdı.
    assert oz["kacanlar"] == []
    assert oz["ai_kacanlar"] == [
        {"hata_kodu": "kampanya_tek_bedava", "ad": "Kampanyada en çok 1 bedava", "platform": "web"}
    ]
    web = oz["platformlar"][0]
    assert (web["uretilen_test"], web["el_test"]) == (1, 1)


def test_yakalandi_kacti_gecersiz_senaryo_12(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    sonuclar = {
        "kampanya_tek_bedava": "assertion",
        "min_siparis_500": "yesil",
        "fiyat_p004_31": "saglik",
        "min_siparis_1000": "locator",
        "kampanya_cift_indirim": "ulasilamaz",
        "min_siparis_haric": "derleme",
    }
    kur(toolchain, lambda p, f: sonuclar[f] if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], list(sonuclar))
    adim_isleri(engine)
    d = detay(engine, kid)
    s = {a["hata_kodu"]: a for a in d["adimlar"] if a["asama"] == "hata"}
    assert s["kampanya_tek_bedava"]["sonuc"] == "yakalandi"
    assert s["min_siparis_500"]["sonuc"] == "kacti"
    assert "yakalanmadı" in s["min_siparis_500"]["neden"]
    assert s["fiyat_p004_31"]["sonuc"] == "gecersiz"
    assert "sağlık kontrolü" in s["fiyat_p004_31"]["neden"]
    # Assertion olmayan kırmızı hata yakalama kanıtı sayılmaz.
    assert s["min_siparis_1000"]["sonuc"] == "gecersiz"
    assert "assertion" in s["min_siparis_1000"]["neden"]
    assert s["min_siparis_1000"]["kiran_testler"] == [
        {"test": "TPD-1 › minimum sipariş 750 dahil", "kaynak": "el"}
    ]
    assert s["kampanya_cift_indirim"]["sonuc"] == "gecersiz"
    assert "Toolchain'e ulaşılamadı" in s["kampanya_cift_indirim"]["neden"]
    with Session(engine) as ses:
        run = ses.get(Run, uuid.UUID(s["kampanya_cift_indirim"]["run_id"]))
        assert run.sonuc == "error" and "ulaşılamadı" in run.artefaktlar["hata"]
    assert s["min_siparis_haric"]["sonuc"] == "gecersiz"
    assert "Derleme" in s["min_siparis_haric"]["neden"]
    oz = d["ozet"]
    assert oz["gecersiz"] == 4
    assert oz["el_yazisi"] == {"oran": 0.5, "yakalanan": 1, "kacan": 1}


def test_cok_platform_sirali_ve_cihaz_kapali_senaryo_13(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    def plan(p: str, f: str | None) -> str:
        if p == "android":
            return "appium_yok"
        if p == "ios":
            return "ulasilamaz"
        return "assertion" if f else "yesil"

    kur(toolchain, plan)
    kid = baslat(engine, muhendis, ["ios", "android", "web"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    # Sıra: web (3 adım) → android (temel) → ios (temel); uygulama gövdesi CI ile aynı.
    sira = [(b.get("platform") or "web", b.get("fault")) for b in toolchain.istekler]
    assert sira == [
        ("web", None),
        ("web", "kampanya_tek_bedava"),
        ("web", None),
        ("android", None),
        ("ios", None),
    ]
    assert toolchain.istekler[3]["lang"] == "java"
    d = detay(engine, kid)
    assert d["durum"] == "done"
    temel = adim(d, "android", "temel")
    assert temel["sonuc"] == "gecersiz" and "Cihaz/Appium erişilemiyor" in temel["neden"]
    for a in d["adimlar"]:
        if a["platform"] in ("android", "ios") and a["asama"] != "temel":
            assert a["sonuc"] == "gecersiz" and a["neden"].startswith("temel koşu yeşil değil")
    assert "Cihaz/Appium" in adim(d, "android", "hata", "kampanya_tek_bedava")["neden"]
    oz = d["ozet"]
    assert oz["el_yazisi"]["oran"] == 1.0 and oz["gecersiz"] == 2
    pl = {p["platform"]: p for p in oz["platformlar"]}
    assert pl["web"]["el_yazisi"]["oran"] == 1.0 and pl["android"]["el_yazisi"]["oran"] is None
    assert [p["platform"] for p in oz["platformlar"]] == ["web", "android", "ios"]
    with Session(engine) as s:
        run = s.get(Run, uuid.UUID(temel["run_id"]))
        assert run.ortam["platform"] == "android" and run.sonuc == "error"


def test_kapanis_kirmizi_platformda_kredi_vermez(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    sayac = {"n": 0}

    def plan(p: str, f: str | None) -> str:
        sayac["n"] += 1
        if f:
            return "assertion"
        return "yesil" if sayac["n"] == 1 else "locator"

    kur(toolchain, plan)
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    d = detay(engine, kid)
    assert d["durum"] == "done"
    assert adim(d, "web", "kapanis")["sonuc"] == "kirmizi"
    yak = adim(d, "web", "hata", "kampanya_tek_bedava")
    assert yak["sonuc"] == "gecersiz" and "önceki sonuç: yakalandi" in yak["neden"]
    assert yak["kiran_testler"]  # kanıt silinmez
    assert len(d["uyarilar"]) == 1 and "kapanış koşusu yeşil değil" in d["uyarilar"][0]
    oz = d["ozet"]
    assert oz["el_yazisi"] == {"oran": None, "yakalanan": 0, "kacan": 0} and oz["gecersiz"] == 1


def test_olaylar_her_adimdan_sonra(
    engine: Engine,
    muhendis: Principal,
    toolchain: FakeToolchain,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    olaylar: list[tuple[str, dict[str, Any]]] = []
    gercek = service.publish_tx

    def yakala(conn: Any, ad: str, veri: dict[str, Any]) -> None:
        olaylar.append((ad, dict(veri)))
        gercek(conn, ad, veri)

    monkeypatch.setattr(service, "publish_tx", yakala)
    kur(toolchain, lambda p, f: "assertion" if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    hk = [v for ad, v in olaylar if ad == "hata_kosusu.ilerleme"]
    assert all(set(v) == {"id", "durum", "platform", "hata_kodu", "asama", "sonuc"} for v in hk)
    assert all(v["id"] == str(kid) for v in hk)
    biten = [(v["asama"], v["hata_kodu"], v["sonuc"]) for v in hk if v["sonuc"] is not None]
    assert biten == [
        ("temel", None, "yesil"),
        ("hata", "kampanya_tek_bedava", "yakalandi"),
        ("kapanis", None, "yesil"),
    ]
    assert hk[0]["durum"] == "queued" and hk[-1]["durum"] == "done"
    assert [v["durum"] for v in hk].count("running") >= 6  # başlangıç + adım başına 2


# ------------------------------------------------------------------ iptal


def test_kuyruktaki_kosu_hemen_iptal(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis)
    with Session(engine) as s, s.begin():
        assert service.iptal(s, kid, muhendis) == {
            "id": str(kid),
            "durum": "cancelled",
            "iptal_istendi": False,
        }
    assert [r.durum for r in isler(engine, kid)] == ["cancelled"]
    d = detay(engine, kid)
    assert d["durum"] == "cancelled" and d["bitis"] and "iptal" in d["uyarilar"][0]
    with Session(engine) as s, s.begin(), pytest.raises(WorkflowError):
        service.iptal(s, kid, muhendis)
    # İptal edilen koşu yenisini engellemez.
    baslat(engine, muhendis)


def test_temel_kosarken_iptal(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kimlik: dict[str, Any] = {}

    def kanca(body: dict[str, Any]) -> None:
        if "fault" not in body and "yanit" not in kimlik:
            with Session(engine) as s, s.begin():
                kimlik["yanit"] = service.iptal(s, kimlik["id"], muhendis)
            # Koşan adım sürerken koşu `running` kalır; GET bunu gösterir.
            d = detay(engine, kimlik["id"])
            kimlik["arada"] = (d["durum"], d["iptal_istendi"], d["bitis"])

    kur(toolchain, lambda p, f: "yesil", kanca)
    kimlik["id"] = kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    assert kimlik["yanit"] == {"id": str(kid), "durum": "running", "iptal_istendi": True}
    assert kimlik["arada"] == ("running", True, None)
    assert len(toolchain.istekler) == 1
    d = detay(engine, kid)
    assert d["durum"] == "cancelled" and d["bitis"] and d["iptal_istendi"] is True
    assert [a["sonuc"] for a in d["adimlar"]] == ["yesil", "bekliyor", "bekliyor"]
    assert d["ozet"]["bekleyen"] == 1
    assert [r.durum for r in isler(engine, kid)] == ["done"]  # devam işi açılmadı


def test_son_hata_adiminda_iptal(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kimlik: dict[str, uuid.UUID] = {}

    def kanca(body: dict[str, Any]) -> None:
        if body.get("fault") == "min_siparis_500":
            with Session(engine) as s, s.begin():
                assert service.iptal(s, kimlik["id"], muhendis)["durum"] == "running"

    kur(toolchain, lambda p, f: "assertion" if f else "yesil", kanca)
    kimlik["id"] = kid = baslat(
        engine, muhendis, ["web", "android"], ["kampanya_tek_bedava", "min_siparis_500"]
    )
    adim_isleri(engine)
    # Koşmakta olan son hata adımı biter, kapanış ve sonraki platform koşmaz.
    assert [b.get("fault") for b in toolchain.istekler] == [
        None,
        "kampanya_tek_bedava",
        "min_siparis_500",
    ]
    d = detay(engine, kid)
    assert d["durum"] == "cancelled" and d["bitis"]
    assert [a["sonuc"] for a in d["adimlar"]][:4] == ["yesil", "yakalandi", "yakalandi", "bekliyor"]
    assert d["ozet"]["el_yazisi"]["yakalanan"] == 2 and d["ozet"]["bekleyen"] == 2


def test_adimlar_arasinda_iptal_hemen_kapanir(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    jobq.process_one(engine, "w", turler=[service.JOB])  # temel; devam işi kuyrukta
    assert kosu_durumu(engine, kid) == "running"
    with Session(engine) as s, s.begin():
        assert service.iptal(s, kid, muhendis)["durum"] == "cancelled"
    assert [r.durum for r in isler(engine, kid)] == ["done", "cancelled"]
    adim_isleri(engine)
    assert len(toolchain.istekler) == 1 and kosu_durumu(engine, kid) == "cancelled"


# ------------------------------------------------------------------ çöküş, kurtarma, bitmiş durum


def test_adimlar_arasinda_cokus_sonrasi_kaldigi_yerden_surer(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "assertion" if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    jobq.process_one(engine, "w", turler=[service.JOB])  # temel
    # Worker hata adımının işini sahiplendi ve öldü (adım yazılmadı).
    with engine.begin() as c:
        alinan = jobq.claim(c, "olu-makine:1:abc", [service.JOB])
        assert alinan is not None and alinan.deneme == 1
    with engine.begin() as c:
        assert jobq.release_orphans(c, host="olu-makine") == 1
    adim_isleri(engine)
    d = detay(engine, kid)
    assert d["durum"] == "done"
    assert [a["sonuc"] for a in d["adimlar"]] == ["yesil", "yakalandi", "yesil"]
    assert [b.get("fault") for b in toolchain.istekler] == [None, "kampanya_tek_bedava", None]
    hata_isi = isler(engine, kid)[1]
    assert hata_isi.durum == "done" and hata_isi.deneme == 2


def test_deneme_hakki_biten_kosu_tarama_ile_kapanir_get_salt_okunur(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    jobq.process_one(engine, "w", turler=[service.JOB])  # temel
    for _ in range(2):  # iki kez öldü: deneme hakkı bitti
        with engine.begin() as c:
            assert jobq.claim(c, "olu-makine:1:abc", [service.JOB]) is not None
        with engine.begin() as c:
            jobq.release_orphans(c, host="olu-makine")
    assert isler(engine, kid)[1].durum == "failed"
    # GET uçları durumu değiştirmez.
    assert detay(engine, kid)["durum"] == "running"
    with Session(engine) as s, s.begin():
        assert service.liste(s)[0]["durum"] == "running"
    assert kosu_durumu(engine, kid) == "running"
    # Periyodik tarama kapatır.
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET run_after = now() WHERE tur = :t"), {"t": service.JOB_TARAMA}
        )
    sonuc = jobq.process_one(engine, "w", turler=[service.JOB_TARAMA])
    assert sonuc is not None
    d = detay(engine, kid)
    assert d["durum"] == "failed" and d["bitis"]
    assert d["uyarilar"][-1] == f"{service.YARIM_KALDI}."
    # Ham iş hatası görünmez; yalnız denetimde (güvenlik-12).
    assert "worker yeniden başladı" not in " ".join(d["uyarilar"])
    assert "worker yeniden başladı" in _denetim_detayi(engine, kid, "hata_kosusu.finished")
    assert d["ozet"]["kapsam"]["kosulan_hata"] == 0
    # Süren koşu kalmadı: tarama kendini yeniden planlamaz.
    with engine.connect() as c:
        bekleyen = c.execute(
            text("SELECT count(*) FROM job WHERE tur = :t AND durum = 'queued'"),
            {"t": service.JOB_TARAMA},
        ).scalar_one()
    assert bekleyen == 0


def test_cokus_sonrasi_worker_acilisi_kurtarir(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis)
    with engine.begin() as c:
        c.execute(text("UPDATE hata_kosusu SET durum = 'running' WHERE id = :i"), {"i": kid})
        c.execute(
            text(
                "UPDATE job SET durum = 'failed', son_hata = 'zaman aşımı (900 sn)' "
                "WHERE idempotency_key = :k"
            ),
            {"k": service.is_anahtari(kid)},
        )
    with engine.begin() as c:
        hk_jobs.on_worker_start(c)
    with Session(engine) as s:
        kosu = s.get(HataKosusu, kid)
        assert kosu.durum == "failed" and kosu.bitis is not None
        assert kosu.uyarilar[-1] == f"{service.YARIM_KALDI}."
    assert "zaman aşımı (900 sn)" in _denetim_detayi(engine, kid, "hata_kosusu.finished")


def test_iptal_istenip_kesilen_kosu_acilista_cancelled(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis)
    with engine.begin() as c:
        alinan = jobq.claim(c, "olu-makine:1:abc", [service.JOB])
        assert alinan is not None
    with Session(engine) as s, s.begin():
        assert service.iptal(s, kid, muhendis)["iptal_istendi"] is True
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET durum = 'failed' WHERE idempotency_key = :k"),
            {"k": service.is_anahtari(kid)},
        )
        hk_jobs.on_worker_start(c)
    d = detay(engine, kid)
    assert d["durum"] == "cancelled" and d["bitis"] and d["ozet"] is not None


def test_takili_kosu_yeni_baslatmayi_engellemez(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis)
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET durum = 'failed' WHERE idempotency_key = :k"),
            {"k": service.is_anahtari(kid)},
        )
    yeni = baslat(engine, muhendis)
    assert yeni != kid and detay(engine, kid)["durum"] == "failed"


def test_bitmis_kosu_adim_sonucuyla_ezilmez(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    """Adım koşarken koşu bitmiş duruma alınırsa (ör. elle/tarama) iş durumu ezmez, adımı
    yazmaz ve devam işi açmaz."""
    kimlik: dict[str, uuid.UUID] = {}

    def kanca(body: dict[str, Any]) -> None:
        if body.get("fault"):
            with engine.begin() as c:
                c.execute(
                    text("UPDATE hata_kosusu SET durum = 'failed', bitis = now() WHERE id = :i"),
                    {"i": kimlik["id"]},
                )

    kur(toolchain, lambda p, f: "assertion" if f else "yesil", kanca)
    kimlik["id"] = kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    d = detay(engine, kid)
    assert d["durum"] == "failed"
    assert [a["sonuc"] for a in d["adimlar"]] == ["yesil", "bekliyor", "bekliyor"]
    assert [r.durum for r in isler(engine, kid)] == ["done", "done"]


def test_eski_kimlik_haritasi_bitmis_durumu_ezmez(engine: Engine, muhendis: Principal) -> None:
    """Oturum koşuyu `running` iken yükledi; başka işlem `done` yaptı. Kilitli yeniden okuma
    (`populate_existing`) olmadan `kurtar` eski kopyayla `failed` yazardı."""
    kid = baslat(engine, muhendis)
    with engine.begin() as c:
        c.execute(text("UPDATE hata_kosusu SET durum = 'running' WHERE id = :i"), {"i": kid})
    with Session(engine) as s, s.begin():
        eski = s.get(HataKosusu, kid)
        assert eski is not None and eski.durum == "running"
        with engine.begin() as c:
            c.execute(
                text("UPDATE hata_kosusu SET durum = 'done', bitis = now() WHERE id = :i"),
                {"i": kid},
            )
            c.execute(
                text("UPDATE job SET durum = 'failed' WHERE idempotency_key = :k"),
                {"k": service.is_anahtari(kid)},
            )
        assert service.kurtar_hepsi(s) == 0
        with pytest.raises(WorkflowError):
            service.iptal(s, kid, muhendis)
    assert kosu_durumu(engine, kid) == "done"


# ------------------------------------------------------------------ KPI ve triage


def test_kpi_ve_triage_disinda_bug_taslagi_yok_senaryo_14(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "assertion" if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava", "kampanya_bedava_yok"])
    adim_isleri(engine)
    with Session(engine) as s:
        runs = s.scalars(select(Run).where(Run.ortam["hata_kosusu_id"].astext == str(kid))).all()
        assert len(runs) == 4
        kirmizi = [r for r in runs if r.sonuc == "failed"]
        assert len(kirmizi) == 2
        sayilan = s.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.id.in_([r.id for r in runs]), kule._kirma_degil())
        )
        assert sayilan == 0
        g = kule.gecme_orani(s, 20)
        assert g["toplam"] == 0 and g["oran"] is None
        for r in kirmizi:
            tk = s.get(TriageKosu, r.id)
            assert tk is not None and tk.durum == "skipped"
            assert "ekilmiş hata koşusu" in tk.neden
        assert s.scalar(select(func.count()).select_from(Failure)) == 0
        assert s.scalar(select(func.count()).select_from(BugDraft)) == 0


def test_triage_uygunlugu_hata_kosusu_kosusunu_atlar(engine: Engine) -> None:
    from tp_core.features.triage.service import uygunluk

    run = Run(
        id=uuid.uuid4(),
        tetik="break_verify",
        kaynak="local",
        sonuc="failed",
        ortam={"hata_kosusu_id": str(uuid.uuid4()), "hata_kodu": "kampanya_tek_bedava"},
    )
    with Session(engine) as s:
        u = uygunluk(s, run)
    assert u.uygun is False and u.kirma is True


# ------------------------------------------------------------------ özet ve Kule


def _adim(
    platform: str, asama: str, sonuc: str, kod: str | None = None, kiran: list | None = None
) -> HataKosusuAdim:
    return HataKosusuAdim(
        platform=platform,
        asama=asama,
        sonuc=sonuc,
        hata_kodu=kod,
        sira=0,
        kiran_testler=kiran or [],
    )


def test_ozet_hesabi() -> None:
    ai = [{"test": "u", "kaynak": "ai"}]
    el = [{"test": "e", "kaynak": "el"}]
    adimlar = [
        _adim("web", "temel", "yesil"),
        _adim("web", "hata", "yakalandi", "kampanya_tek_bedava", ai),
        _adim("web", "hata", "yakalandi", "min_siparis_500", el),
        _adim("web", "hata", "kacti", "fiyat_p004_31"),
        _adim("web", "hata", "gecersiz", "min_siparis_1000"),
        _adim("web", "kapanis", "yesil"),
        _adim("ios", "temel", "gecersiz"),
        _adim("ios", "hata", "gecersiz", "kampanya_tek_bedava"),
        _adim("ios", "kapanis", "gecersiz"),
    ]
    ic = {"temel": {"web": {"ai": 3, "el": 10}, "ios": {"ai": 0, "el": 0}}}
    oz = service.ozet_hesapla(adimlar, ["web", "ios"], ic)
    assert (oz["oran"], oz["yakalanan"], oz["kacan"]) == (round(1 / 3, 4), 1, 2)
    assert oz["el_yazisi"] == {"oran": round(1 / 3, 4), "yakalanan": 1, "kacan": 2}
    assert oz["tum_testler"] == {"oran": round(2 / 3, 4), "yakalanan": 2, "kacan": 1}
    assert (oz["gecersiz"], oz["bekleyen"]) == (2, 0)
    assert oz["kapsam"] == {
        "kosulan_hata": 4,
        "katalog": 9,
        "platformlar": ["web", "ios"],
        "tam_katalog": False,
        "gecerli_adim": 3,
        "esik": 0.5,
        "yeterli": False,
        "not": "Geçerli hata adımı kataloğun %50'inin altında (web 3/9; ios 0/9); oran ölçü "
        "sayılmaz.",
    }
    web, ios = oz["platformlar"]
    assert web["oran"] == round(1 / 3, 4) and web["gecersiz"] == 1
    assert (web["temel"], web["kapanis"], web["uretilen_test"], web["el_test"]) == (
        "yesil",
        "yesil",
        3,
        10,
    )
    assert ios["oran"] is None and ios["el_yazisi"]["oran"] is None and ios["gecersiz"] == 1
    assert [k["hata_kodu"] for k in oz["kacanlar"]] == ["fiyat_p004_31"]
    assert [k["hata_kodu"] for k in oz["ai_kacanlar"]] == ["min_siparis_500", "fiyat_p004_31"]
    assert service.ozet_hesapla([], ["web"])["oran"] is None


def test_hata_yakalama_ozeti_kule_sekli_ve_kapsam(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    with Session(engine) as s:
        assert service.hata_yakalama_ozeti(s) is None
    ai = {"file": AI_TEST}

    def plan(p: str, f: str | None) -> list[dict[str, Any]]:
        if f is None or f == "min_siparis_500":
            return [_test("üretilen", **ai), _test("el")]
        return [_assertion("üretilen", **ai), _test("el")]

    kur(toolchain, plan)
    uretilen_kaydet(engine)
    tam = baslat(engine, muhendis, ["web"])  # tüm katalog
    adim_isleri(engine)
    with Session(engine) as s:
        hy = service.hata_yakalama_ozeti(s)
    assert hy is not None and hy["son_kosu"]["id"] == str(tam)
    # Kısmi (tam katalog olmayan) yeni koşu ölçünün yerini almaz.
    baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    # Geçerli adımı olmayan tam koşu da almaz.
    kur(toolchain, lambda p, f: "saglik")
    baslat(engine, muhendis, ["web"])
    adim_isleri(engine)
    # Süren koşu da almaz.
    baslat(engine, muhendis)
    with Session(engine) as s:
        hy = service.hata_yakalama_ozeti(s)
    assert hy is not None
    assert set(hy) == {
        "son_kosu",
        "oran",
        "yakalanan",
        "kacan",
        "gecersiz",
        "el_yazisi",
        "tum_testler",
        "kapsam",
        "platformlar",
        "kacanlar",
        "ai_kacanlar",
        "kaynak",
    }
    assert hy["son_kosu"]["id"] == str(tam) and hy["son_kosu"]["durum"] == "done"
    assert (hy["oran"], hy["yakalanan"], hy["kacan"], hy["gecersiz"]) == (round(8 / 9, 4), 8, 1, 0)
    assert hy["el_yazisi"] == {"oran": 0.0, "yakalanan": 0, "kacan": 9}
    assert hy["kapsam"]["tam_katalog"] is True and hy["kapsam"]["kosulan_hata"] == 9
    assert hy["platformlar"] == [
        {
            "platform": "web",
            "oran": round(8 / 9, 4),
            "yakalanan": 8,
            "kacan": 1,
            "gecersiz": 0,
            "el_yazisi": {"oran": 0.0, "yakalanan": 0, "kacan": 9},
        }
    ]
    assert (
        hy["kacanlar"]
        == hy["ai_kacanlar"]
        == [{"hata_kodu": "min_siparis_500", "ad": "Minimum sipariş tutarı 500", "platform": "web"}]
    )
    assert "yakalanan 8, kaçan 1" in hy["kaynak"] and "9/9 hata" in hy["kaynak"]


# ------------------------------------------------------------------ API ve roller


def test_api_roller_ve_sekiller(api: TestClient, make_user, engine: Engine) -> None:
    login(api, make_user("analyst"))
    r = api.post("/fault-runs", json={"platformlar": ["web"]})
    assert r.status_code == 403
    assert api.get("/fault-runs/catalog").status_code == 200
    login(api, make_user("presenter"))
    r = api.post("/fault-runs", json={"platformlar": ["web"], "hatalar": ["kampanya_tek_bedava"]})
    assert r.status_code == 202, r.text
    govde = r.json()
    assert set(govde) == {"id", "durum"} and govde["durum"] == "queued"
    r2 = api.post("/fault-runs", json={"platformlar": ["web"]})
    assert r2.status_code == 409 and r2.json()["kod"] == "hata_kosusu_suruyor"
    liste = api.get("/fault-runs", params={"limit": 5}).json()
    assert [k["id"] for k in liste] == [govde["id"]]
    assert set(liste[0]) == {
        "id",
        "durum",
        "iptal_istendi",
        "platformlar",
        "hatalar",
        "commit",
        "baslatan_id",
        "baslatan",
        "ozet",
        "uyarilar",
        "baslama",
        "bitis",
        "olusturma",
    }
    d = api.get(f"/fault-runs/{govde['id']}").json()
    assert len(d["adimlar"]) == 3
    assert set(d["adimlar"][0]) == {
        "id",
        "platform",
        "hata_kodu",
        "hata_adi",
        "asama",
        "run_id",
        "sonuc",
        "kiran_testler",
        "temelde_kirmizi",
        "neden",
        "sure_ms",
        "sira",
    }
    assert api.get(f"/fault-runs/{uuid.uuid4()}").status_code == 404
    kat_ = api.get("/fault-runs/catalog").json()
    assert len(kat_) == 9 and set(kat_[0]) == {
        "kod",
        "ad",
        "tur",
        "aciklama",
        "yakalayan_kural",
        "ac_refs",
        "tablo",
        "ayirt_edici",
    }
    login(api, make_user("engineer"))
    r = api.post(f"/fault-runs/{govde['id']}/cancel")
    assert r.status_code == 200 and r.json() == {
        "id": govde["id"],
        "durum": "cancelled",
        "iptal_istendi": False,
    }
    assert api.post(f"/fault-runs/{govde['id']}/cancel").status_code == 409
    r = api.post("/fault-runs", json={"platformlar": ["web"], "hatalar": ["yok"]})
    assert r.status_code == 422 and "Katalogda olmayan" in r.json()["detail"]
    assert r.json()["kod"] == "gecersiz_istek"
    r = api.post("/fault-runs", json={"platformlar": ["linux"]})
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_istek"
    r = api.post("/fault-runs", json={"platformlar": ["web"], "hatalar": ["Kötü"]})
    assert r.status_code == 422
    r = api.post("/fault-runs", json={"platformlar": ["web"]})
    assert r.status_code == 202
    login(api, make_user("po"))
    assert api.post(f"/fault-runs/{r.json()['id']}/cancel").status_code == 403


def test_codegen_toolchain_istemcisi_fault_alani() -> None:
    import json

    from tp_core.features.codegen.toolchain import ToolchainClient

    govdeler: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        govdeler.append(json.loads(request.content))
        return httpx.Response(200, json={"conclusion": "success"})

    c = ToolchainClient("http://tc", transport=httpx.MockTransport(handler))
    c.check(SHA, [], repeat_each=1)
    c.check(SHA, [], repeat_each=1, fault="kampanya_tek_bedava", platform="android")
    c.close()
    # Verilmezse gövdeye yazılmaz: eski toolchain'lerle istek baytları aynı kalır.
    assert "fault" not in govdeler[0]
    assert govdeler[1]["fault"] == "kampanya_tek_bedava" and govdeler[1]["lang"] == "java"


def test_ortam_nedeni_appium_adresi_ve_ham_metin_nedende_yok() -> None:
    """Güvenlik-12: `neden` kategorize Türkçe metindir; Appium adresi ve ham hata yalnız
    ayrıntıdadır (denetime gider)."""
    sinif = type("S", (), {"sinif": "ortam", "hata": "x", "aciklama": "x"})()

    def rapor(appium: dict[str, Any]) -> dict[str, Any]:
        return {"run": {"saglik": {"ok": False, "appium": appium}}}

    neden, detay = service.ortam_nedeni(
        rapor({"url": None, "hata": "APPIUM_URL_WINDOWS yapılandırılmamış"}), sinif
    )
    assert neden == "Cihaz/Appium erişilemiyor: adres yapılandırılmamış."
    assert detay is not None and "APPIUM_URL_WINDOWS" in detay
    neden, detay = service.ortam_nedeni(
        rapor({"url": "http://appium-gw:4723/status", "hata": "ConnectError"}), sinif
    )
    assert neden == "Cihaz/Appium erişilemiyor."
    assert detay == "http://appium-gw:4723/status: ConnectError"
    neden, detay = service.ortam_nedeni(
        {"run": {"status": "error", "error": "Traceback … /opt/runner/x.py"}}, sinif
    )
    assert neden == "Test koşucusu hata verdi." and "Traceback" in (detay or "")
    yok = service.siniflandir("hata", None, "ConnectError: http://toolchain:9000/check")
    assert yok.neden == "Toolchain'e ulaşılamadı ya da istek reddedildi."
    assert "toolchain:9000" in (yok.detay or "")


def test_appium_adresi_adim_nedeninde_degil_denetimde(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "appium_yok")
    kid = baslat(engine, muhendis, ["android"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    d = detay(engine, kid)
    metin = " ".join(str(a["neden"] or "") for a in d["adimlar"]) + " ".join(d["uyarilar"])
    assert "appium:4723" not in metin and "bağlantı reddedildi" not in metin
    assert "Cihaz/Appium erişilemiyor" in adim(d, "android", "temel")["neden"]
    ayrinti = _denetim_detayi(engine, kid, "hata_kosusu.adim_detayi")
    assert "http://appium:4723: bağlantı reddedildi" in ayrinti


def test_test_kaynagi_codegen_kaydiyla(engine: Engine) -> None:
    """Y7: `ai` yalnız onaylı case'in onaylı hash'inden üretilmiş testin dosyası; yol adı taklit
    edilemez, failure konumu bakılmaz; codegen kaydı yoksa her test `el`."""
    with Session(engine) as s:
        assert service.uretilen_dosyalar(s, "web") == frozenset()
    # Kayıt yokken `tests/generated/` altındaki dosya da `el`.
    assert service.test_kaynagi({"file": "generated/tpd-1-c3-1a2b3c4d.spec.ts"}) == "el"
    uretilen_kaydet(engine)
    uretilen_kaydet(engine, JAVA_AI_TEST, "android")
    uretilen_kaydet(engine, "tests/generated/onaysiz.spec.ts", case_durum="draft")
    uretilen_kaydet(engine, "tests/generated/eski-hash.spec.ts", hash_eslesir=False)
    with Session(engine) as s:
        web = service.uretilen_dosyalar(s, "web")
        android = service.uretilen_dosyalar(s, "android")
        assert service.uretilen_dosyalar(s, "ios") == frozenset()
    # Playwright `testDir`'e göre yol ve toolchain `test_files` yolu.
    assert service.test_kaynagi({"file": "generated/tpd-1-c11-1a2b3c4d.spec.ts"}, web) == "ai"
    assert service.test_kaynagi({"file": AI_TEST}, web) == "ai"
    assert service.test_kaynagi({"file": JAVA_AI_TEST}, android) == "ai"
    # Platform ayrı: web kaydı android'de ai değil.
    assert service.test_kaynagi({"file": JAVA_AI_TEST}, web) == "el"
    # Taklit: `generated/` altındaki kayıtsız, onaysız ya da eski hash'li dosya `el`.
    for sahte in (
        "generated/sahte.spec.ts",
        "tests/generated/onaysiz.spec.ts",
        "tests/generated/eski-hash.spec.ts",
        "x/tests/generated/tpd-1-c11-1a2b3c4d.spec.ts",
    ):
        assert service.test_kaynagi({"file": sahte}, web) == "el", sahte
    # Yalnız testin kendi dosyası: failure konumu üretilen dosyayı gösterse de `el`.
    konumlu = {
        "file": "cart.spec.ts",
        "failure": {"location": {"file": AI_TEST}, "test_location": {"file": AI_TEST}},
    }
    assert service.test_kaynagi(konumlu, web) == "el"
    assert service.kiran_listesi(["eski"]) == [{"test": "eski", "kaynak": "el"}]


def test_temelde_yesil_uyelik_sarti_y8(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    """Y8: temelde atlanan ya da başlığı değişen test hatalı koşuda assertion ile kırmızı olsa da
    yakalama kanıtı değildir (`kacti` + not); temelde yeşil test kanıttır."""
    temel = [_test("a"), _test("atlanan", "skipped")]
    planlar: dict[str | None, Any] = {
        None: temel,
        "kampanya_tek_bedava": [_test("a"), _assertion("atlanan")],
        "min_siparis_500": [_test("a"), _assertion("yeni başlık")],
        "min_siparis_1000": [_assertion("a"), _assertion("atlanan")],
    }
    kur(toolchain, lambda p, f: planlar[f])
    kid = baslat(
        engine, muhendis, ["web"], ["kampanya_tek_bedava", "min_siparis_500", "min_siparis_1000"]
    )
    adim_isleri(engine)
    d = detay(engine, kid)
    atlanan = adim(d, "web", "hata", "kampanya_tek_bedava")
    assert atlanan["sonuc"] == "kacti" and atlanan["kiran_testler"] == []
    assert "yeşil görülmeyen 1 kırmızı test kanıt sayılmadı: atlanan" in atlanan["neden"]
    yeni = adim(d, "web", "hata", "min_siparis_500")
    assert yeni["sonuc"] == "kacti" and "yeni başlık" in yeni["neden"]
    yak = adim(d, "web", "hata", "min_siparis_1000")
    assert yak["sonuc"] == "yakalandi" and yak["kiran_testler"] == [{"test": "a", "kaynak": "el"}]
    with Session(engine) as s:
        ic = service._ic(s.get(HataKosusu, kid))
    assert ic["temel"]["web"]["yesil"] == ["cart.spec.ts::a"]
    assert (ic["temel"]["web"]["ai"], ic["temel"]["web"]["el"]) == (0, 1)


def test_temel_kirmizi_siniri_asilirsa_platform_gecersiz(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "MAX_TEMEL_KIRMIZI", 2)
    temel = [_test("a"), _assertion("k1"), _assertion("k2"), _assertion("k3")]
    kur(toolchain, lambda p, f: temel)
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    d = detay(engine, kid)
    t = adim(d, "web", "temel")
    assert t["sonuc"] == "gecersiz" and "Temelde 3 test kırmızı (sınır 2)" in t["neden"]
    assert adim(d, "web", "hata", "kampanya_tek_bedava")["sonuc"] == "gecersiz"
    assert len(toolchain.istekler) == 1


def test_uretilenlerin_hepsi_temelde_kirmiziysa_ai_olculmedi_n3(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    """t2 N3: üretilen testlerin hepsi temelde kırmızı → AI oranı %0 değil `null` (ölçülmedi)."""
    uretilen_kaydet(engine)
    ai = {"file": AI_TEST}
    temel = [_assertion("üretilen", **ai), _test("el")]
    kur(
        toolchain,
        lambda p, f: temel if f is None else [_assertion("üretilen", **ai), _assertion("el")],
    )
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    adim_isleri(engine)
    oz = detay(engine, kid)["ozet"]
    web = oz["platformlar"][0]
    assert (web["uretilen_test"], web["el_test"]) == (0, 1)
    assert oz["oran"] is None and web["oran"] is None
    # AI ölçülmeyen platformda `ai_kacanlar`'a yazılmaz; el yazısı yakaladı: `kacanlar` boş.
    assert oz["kacanlar"] == [] and oz["ai_kacanlar"] == []
    assert oz["el_yazisi"] == {"oran": 1.0, "yakalanan": 1, "kacan": 0}


def test_kule_gecerli_adim_esigi_y10(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Y10: tam katalog koşusunda geçerli hata adımı kataloğun %50'sinin altındaysa Kule oranları
    null ve `kapsam.not` nedeni söyler; eşik ayarlanabilir."""
    uretilen_kaydet(engine)
    ai = {"file": AI_TEST}
    gecerli = {"kampanya_tek_bedava", "min_siparis_500", "min_siparis_1000", "fiyat_p004_31"}

    def plan(p: str, f: str | None) -> Any:
        if f is None:
            return [_test("üretilen", **ai), _test("el")]
        if f in gecerli:
            return [_assertion("üretilen", **ai), _test("el")]
        return "saglik"

    kur(toolchain, plan)
    baslat(engine, muhendis, ["web"])
    adim_isleri(engine)
    with Session(engine) as s:
        hy = service.hata_yakalama_ozeti(s)
    assert hy is not None
    assert (hy["oran"], hy["yakalanan"], hy["kacan"], hy["gecersiz"]) == (None, 4, 0, 5)
    assert hy["el_yazisi"]["oran"] is None and hy["tum_testler"]["oran"] is None
    assert hy["platformlar"][0]["oran"] is None
    k = hy["kapsam"]
    assert (k["yeterli"], k["esik"], k["gecerli_adim"]) == (False, 0.5, 4)
    assert k["not"] and "web 4/9" in k["not"] and k["not"] in hy["kaynak"]
    monkeypatch.setenv(service.GECERLI_ESIK_ENV, "0.4")
    with Session(engine) as s:
        hy = service.hata_yakalama_ozeti(s)
    assert hy is not None and hy["oran"] == 1.0 and hy["kapsam"]["yeterli"] is True
    assert hy["kapsam"]["not"] is None


class _Ctx:
    def __init__(self, kid: uuid.UUID, deneme: int, max_deneme: int = 2) -> None:
        self.yuk = {"kosu_id": str(kid)}
        self.deneme = deneme
        self.max_deneme = max_deneme

    @property
    def son_deneme(self) -> bool:
        return self.deneme >= self.max_deneme


def _db_hatasi() -> Exception:
    from sqlalchemy.exc import OperationalError

    return OperationalError("SELECT 1", {}, Exception("server closed the connection"))


def test_gecici_db_hatasi_yeniden_denenir_son_denemede_failed_n4(
    engine: Engine, muhendis: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    """t2 N4: DB/taşıma hatası yeniden fırlatılır (iş yeniden denenir, adım `bekliyor`); koşu
    yalnız son denemede `failed` kapanır, ham metin denetimde."""
    from tp_core.workflow.jobs import PermanentJobError

    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])

    def patlat(_kid: uuid.UUID, **_k: Any) -> dict[str, Any]:
        raise _db_hatasi()

    monkeypatch.setattr(service, "_adim_isle", patlat)
    with pytest.raises(Exception) as ilk:
        service.calistir(_Ctx(kid, 1))  # type: ignore[arg-type]
    assert not isinstance(ilk.value, PermanentJobError)
    assert kosu_durumu(engine, kid) == "queued"
    assert {a["sonuc"] for a in detay(engine, kid)["adimlar"]} == {"bekliyor"}
    with pytest.raises(PermanentJobError):
        service.calistir(_Ctx(kid, 2))  # type: ignore[arg-type]
    d = detay(engine, kid)
    assert d["durum"] == "failed"
    assert "veritabanı/ağ hatası" in d["uyarilar"][-1]
    assert "server closed" not in " ".join(d["uyarilar"])
    assert "server closed the connection" in _denetim_detayi(engine, kid, "hata_kosusu.finished")


def test_gecici_db_hatasi_is_kuyrugunda_retry(
    engine: Engine, muhendis: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gerçek kuyruk yolu: ilk denemedeki DB hatası işi `retry` yapar, koşu süren kalır."""
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])

    def patlat(_kid: uuid.UUID, **_k: Any) -> dict[str, Any]:
        raise _db_hatasi()

    monkeypatch.setattr(service, "_adim_isle", patlat)
    jobq.process_one(engine, "w", turler=[service.JOB])
    assert isler(engine, kid)[0].durum == "retry"
    assert kosu_durumu(engine, kid) == "queued"


def test_iptal_istenmisken_beklenmeyen_hata_cancelled_y15(
    engine: Engine, muhendis: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.workflow.jobs import PermanentJobError

    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    with Session(engine) as s, s.begin():
        kosu = service._kilitle(s, kid)
        assert kosu is not None
        ic = service._ic(kosu)
        ic["iptal_istendi"] = True
        service._ic_yaz(kosu, ic)

    def patlat(_kid: uuid.UUID, **_k: Any) -> dict[str, Any]:
        raise RuntimeError("beklenmeyen")

    monkeypatch.setattr(service, "_adim_isle", patlat)
    with pytest.raises(PermanentJobError):
        service.calistir(_Ctx(kid, 1))  # type: ignore[arg-type]
    assert kosu_durumu(engine, kid) == "cancelled"


def test_commit_kilit_disinda_cozulur_n12(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain, fake_forge: Any
) -> None:
    """t2 N12: `head_sha` (ağ çağrısı) koşu satırı kilitliyken çağrılmaz: o sırada başka bir
    bağlantı satırı NOWAIT ile kilitleyebilir (iptal beklemez)."""
    kur(toolchain, lambda p, f: "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    gorulen: list[bool] = []
    asil = type(fake_forge).head_sha

    def head_sha(self: Any, ref: str = "main") -> str:
        with engine.begin() as c:
            c.execute(
                text("SELECT id FROM hata_kosusu WHERE id = :i FOR UPDATE NOWAIT"), {"i": kid}
            )
            gorulen.append(True)
        return asil(self, ref)

    type(fake_forge).head_sha = head_sha  # type: ignore[method-assign]
    try:
        jobq.process_one(engine, "w", turler=[service.JOB])
    finally:
        type(fake_forge).head_sha = asil  # type: ignore[method-assign]
    assert gorulen == [True]
    assert kosu_durumu(engine, kid) == "running"


def test_commit_cozulemezse_failed_ham_metin_denetimde(
    engine: Engine, muhendis: Principal, fake_forge: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bozuk(ref: str = "main") -> str:
        raise ValueError("token=gizli forge yanıtı")

    monkeypatch.setattr(fake_forge, "head_sha", bozuk)
    kid = baslat(engine, muhendis, ["web"], ["kampanya_tek_bedava"])
    jobq.process_one(engine, "w", turler=[service.JOB])
    d = detay(engine, kid)
    assert d["durum"] == "failed"
    assert d["uyarilar"][-1] == "Koşulacak commit çözülemedi (main)."
    assert "gizli" in _denetim_detayi(engine, kid, "hata_kosusu.finished")


def test_is_anahtarlari_tum_adimlari_kapsar(engine: Engine, muhendis: Principal) -> None:
    """t2 N10: adım işleri `LIKE` yerine tam anahtar listesiyle (tekil indeks) okunur."""
    from sqlalchemy import event

    kid = baslat(engine, muhendis, ["web", "android"], ["kampanya_tek_bedava"])
    sorgular: list[str] = []

    def say(_c: Any, _cur: Any, stmt: str, *_a: Any) -> None:
        sorgular.append(stmt)

    with Session(engine) as s:
        assert service.is_anahtarlari(s, kid) == [service.is_anahtari(kid, i) for i in range(6)]
        event.listen(engine, "before_cursor_execute", say)
        try:
            assert [r.durum for r in service._isler(s, kid)] == ["queued"]
        finally:
            event.remove(engine, "before_cursor_execute", say)
    job_sorgulari = [q for q in sorgular if "FROM job" in q]
    assert job_sorgulari and not any("LIKE" in q.upper() for q in job_sorgulari)
    assert all("idempotency_key = ANY" in q for q in job_sorgulari)
