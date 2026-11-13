"""Java / Appium triage (009 mobil-masaüstü, Ş6): kanıt okuma, kurallar ve kural 3'ün sayfa
kaynağı karşılığı (gerçek Postgres + artefakt fikstürleri)."""

from __future__ import annotations

import json
import sys
import types
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tp_core.features.triage import classify_run
from tp_core.features.triage import java as jv
from tp_core.features.triage.rules import Girdi, siniflandir
from tp_core.models import Failure, Run, Script, TestResult
from tp_core.models.triage_feature import FailureEk

from .conftest import SHA, FakeToolchain

pytestmark = pytest.mark.usefixtures("triage_env")

SINIF = "com.antreklabs.bayi.uretilen.TPD1C3_0a1b2c3dTest"
KIMLIKLER = "src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java"
JAVA_SEMBOLLER: dict[str, Any] = {
    "schema_version": 1,
    "sha": SHA,
    "lang": "java",
    "page_objects": [
        {
            "class": "KatalogEkrani",
            "file": "src/test/java/com/antreklabs/bayi/ekranlar/KatalogEkrani.java",
            "methods": [],
            "locators": {
                "Katalog.SEPETE_EKLE": {
                    "testId": "add-to-cart",
                    "role": "",
                    "name": "",
                    "intent": "Ürün kartında sepete ekleme butonu.",
                    "prefix": False,
                    "file": KIMLIKLER,
                    "line": 52,
                },
                "Katalog.URUN_KARTI_ONEK": {
                    "testId": "product-card-",
                    "role": "",
                    "name": "",
                    "intent": "Tek bir ürünün kartı.",
                    "prefix": True,
                    "file": KIMLIKLER,
                    "line": 46,
                },
                "Katalog.ADET_ONEK": {
                    "testId": "qty-input-",
                    "role": "",
                    "name": "",
                    "intent": "Adet alanı.",
                    "prefix": True,
                    "file": KIMLIKLER,
                    "line": 50,
                },
                "Menu.SEPET": {
                    "testId": "nav-cart",
                    "role": "",
                    "name": "",
                    "intent": "Sepet bağlantısı.",
                    "prefix": False,
                    "file": KIMLIKLER,
                    "line": 18,
                },
            },
        }
    ],
    "errors": [],
}

ANDROID_KIRIK = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy index="0" rotation="0">
  <android.widget.FrameLayout resource-id="android:id/content">
    <android.view.ViewGroup resource-id="nav-cart" content-desc="Sepet"/>
    <android.view.ViewGroup resource-id="product-card-P-001">
      <android.widget.EditText resource-id="qty-input-P-001" text="1"/>
      <android.widget.Button resource-id="cart-add" text="Sepete ekle"/>
    </android.view.ViewGroup>
    <android.view.ViewGroup resource-id="product-card-P-002">
      <android.widget.Button resource-id="cart-add" text="Sepete ekle"/>
    </android.view.ViewGroup>
    <android.widget.TextView resource-id="promo-banner" text="Kampanya"/>
  </android.widget.FrameLayout>
</hierarchy>"""
IOS = """<?xml version="1.0" encoding="UTF-8"?>
<AppiumAUT><XCUIElementTypeApplication name="Bayi" label="Bayi">
  <XCUIElementTypeOther name="product-card-P-001" label="P-001">
    <XCUIElementTypeButton name="cart-add" label="Sepete ekle"/>
    <XCUIElementTypeStaticText name="P-001" label="P-001"/>
  </XCUIElementTypeOther>
</XCUIElementTypeApplication></AppiumAUT>"""
WINDOWS = """<?xml version="1.0" encoding="utf-16"?>
<Window AutomationId="AnaPencere" Name="Bayi">
<Button AutomationId="cart-add" Name="Sepete ekle"/></Window>"""

TIMEOUT_MSG = (
    "org.openqa.selenium.TimeoutException: Expected condition failed: öğe tıklanabilir olmadı: "
    "kimlik 'product-card-P-001' içinde 'add-to-cart' (tried for 10 second(s) with 250 "
    "milliseconds interval)"
)
ASSERT_MSG = (
    "java.lang.AssertionError: cart-total metni: beklenen <150,00 TL>, görülen <175,00 TL> "
    "(10000 ms)"
)


# ----------------------------------------------------------------------------- saf


def test_kimlik_dugumleri_platformlar() -> None:
    a = jv.kimlik_dugumleri(ANDROID_KIRIK, "android")
    kimlikler = [d.kimlik for d in a]
    assert "content" not in kimlikler  # android:id/… sistem kimliği atlanır
    assert kimlikler.count("cart-add") == 2
    ilk = next(d for d in a if d.kimlik == "cart-add")
    assert ilk.kapsayicilar == ("product-card-P-001",) and ilk.metin == "Sepete ekle"
    i = [d.kimlik for d in jv.kimlik_dugumleri(IOS, "ios")]
    # iOS: name == label ise kimlik sayılmaz (P-001); Application adı da öyle.
    assert i == ["product-card-P-001", "cart-add"]
    w = [d.kimlik for d in jv.kimlik_dugumleri(WINDOWS.replace("utf-16", "utf-8"), "windows")]
    assert w == ["AnaPencere", "cart-add"]


def test_kimlik_dugumleri_dtd_ve_varlik_reddedilir() -> None:
    xxe = (
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        '<r resource-id="&x;"/>'
    )
    with pytest.raises(jv.SayfaKaynagiHatasi):
        jv.kimlik_dugumleri(xxe, "android")
    with pytest.raises(jv.SayfaKaynagiHatasi):
        jv.kimlik_dugumleri("<r><a></r>", "android")
    derin = "<a>" * (jv.MAX_DERINLIK + 5) + "</a>" * (jv.MAX_DERINLIK + 5)
    with pytest.raises(jv.SayfaKaynagiHatasi):
        jv.kimlik_dugumleri(derin, "android")


def test_kimlik_zinciri() -> None:
    assert jv.kimlik_zinciri(TIMEOUT_MSG) == ("add-to-cart", "product-card-P-001", False)
    assert jv.kimlik_zinciri("öğe görünmedi: kimlik 'cart-total'") == ("cart-total", None, False)
    assert jv.kimlik_zinciri("kimlik 'a' ya da 'b'")[2] is True
    assert jv.kimlik_zinciri(None, "yok") == (None, None, False)


def test_aday_kimlik_tek_aday_ve_reddedilenler() -> None:
    sabit, onek = jv.bilinen_kimlikler(JAVA_SEMBOLLER)
    d = jv.kimlik_dugumleri(ANDROID_KIRIK, "android")
    s = jv.aday_kimlik(d, "add-to-cart", "product-card-P-001", sabit, onek)
    assert s.yeni == "cart-add" and s.neden is None
    # Kapsamsız: promo-banner tanımsız ama ortak sözcüğü yok; cart-add tek benzer aday.
    assert jv.aday_kimlik(d, "add-to-cart", None, sabit, onek).yeni == "cart-add"
    # Eski kimlik ekrandaysa kırılma değil.
    s2 = jv.aday_kimlik(d, "nav-cart", None, sabit, onek)
    assert s2.yeni is None and s2.eski_ekranda
    # Kapsayıcı yoksa aday aranmaz.
    s3 = jv.aday_kimlik(d, "add-to-cart", "product-card-P-999", sabit, onek)
    assert s3.yeni is None and s3.kapsam_bulundu is False
    # İki benzer aday → öneri yok.
    iki = ANDROID_KIRIK.replace("promo-banner", "cart-adder")
    s4 = jv.aday_kimlik(jv.kimlik_dugumleri(iki, "android"), "add-to-cart", None, sabit, onek)
    assert s4.yeni is None and "tek aday yok" in (s4.neden or "")


def test_java_mi_ve_kanit_dizini_adi() -> None:
    assert jv.java_mi(None, SINIF) and jv.java_mi("android", "x")
    # 011: `web` kısa devresi kalktı — Java mı sorusu dile/dosyaya bakar (web + Playwright for
    # Java). Dil `ts` diyorsa Java değildir; dil/dosya yoksa web'de istisna metni Java demez.
    assert jv.java_mi("web", SINIF) and jv.java_mi("web", None, dil="java")
    assert not jv.java_mi("web", SINIF, dil="ts")
    assert not jv.java_mi("web", None, "java.lang.AssertionError: x")
    assert not jv.java_mi(None, "tests/cart.spec.ts", "Error: expect(locator)")
    assert jv.java_mi(None, None, "org.openqa.selenium.TimeoutException: x")
    assert jv.kanit_dizini_adi(SINIF, "senaryo") == "TPD1C3_0a1b2c3dTest.senaryo"
    ad = jv.kanit_dizini_adi("../x/Kotu Ad.java", "m/../")
    assert ad is not None and "/" not in ad and ad.startswith("Kotu_Ad.")


# ---------------------------------------------------------------------------- kurallar


def test_kurallar_java_assertion_product_defect() -> None:
    g = Girdi(
        test_adi="senaryo",
        dosya=SINIF,
        platform="android",
        mesaj=ASSERT_MSG,
        beklenen="150,00 TL",
        gerceklesen="175,00 TL",
        sayfa_kaynagi=ANDROID_KIRIK,
        sayfa_kaynagi_rel="target/kanit/x/sayfa-kaynagi.xml",
    )
    assert g.tur() == "assertion"
    karar, _ek, _neden = siniflandir(g)
    assert karar is not None and karar.sinif == "product_defect"
    kodlar = [s["kod"] for s in karar.sinyaller]
    assert {"assertion_farki", "eleman_bulundu", "sayfa_yapisi_beklenen"} <= set(kodlar)
    assert karar.sinyaller[0]["kaynak"] == "Java/Appium hata mesajı"


def test_kurallar_java_oge_yok_product_defect_degil() -> None:
    g = Girdi(
        test_adi="senaryo",
        dosya=SINIF,
        platform="ios",
        mesaj="java.lang.AssertionError: x: beklenen <1>, görülen <(öğe yok)> (10000 ms)",
        beklenen="1",
        gerceklesen="(öğe yok)",
    )
    karar, _ek, _neden = siniflandir(g)
    assert karar is None


def test_kurallar_java_turleri() -> None:
    def tur(m: str) -> str:
        return Girdi(test_adi="t", dosya=SINIF, mesaj=m).tur()

    assert tur(TIMEOUT_MSG) == "locator_timeout"
    assert tur("org.openqa.selenium.NoSuchElementException: no such element") == (
        "locator_not_found"
    )
    assert tur("org.openqa.selenium.StaleElementReferenceException: x") == "other"
    assert tur("org.openqa.selenium.SessionNotCreatedException: x") == "navigation"
    assert tur("java.lang.AssertionError: POST /test/reset başarısız: 401") == "test_data"
    karar, _, _ = siniflandir(
        Girdi(test_adi="t", dosya=SINIF, mesaj="SessionNotCreatedException: Could not start")
    )
    assert karar is not None and karar.sinif == "environment"


# ------------------------------------------------------------------------- uçtan uca


def _bugs_modulu(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = types.ModuleType("tp_core.features.bugs")
    mod.create_draft_from_failure = lambda session, failure_id: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tp_core.features.bugs", mod)


def _java_kosusu(
    engine: Engine,
    kok: Path,
    mesaj: str,
    *,
    sayfa_kaynagi: str | None = ANDROID_KIRIK,
    platform_ortam: bool = True,
    script_platform: str | None = None,
) -> uuid.UUID:
    rid = uuid.uuid4()
    dizin = f"runs/ci-{rid.hex[:12]}"
    yerel = kok / dizin
    kanit = yerel / "target" / "kanit" / "TPD1C3_0a1b2c3dTest.senaryo"
    kanit.mkdir(parents=True)
    if sayfa_kaynagi is not None:
        (kanit / "sayfa-kaynagi.xml").write_text(sayfa_kaynagi, encoding="utf-8")
    (kanit / "ekran.png").write_bytes(b"\x89PNG")
    saglik = {"ok": True}
    giris = {
        "title": "senaryo",
        "file": SINIF,
        "status": "unexpected",
        "attempt_results": [{"retry": 0, "status": "failed"}],
        "failure": {"message": mesaj, "type": None},
    }
    (yerel / "run.json").write_text(
        json.dumps(
            {"run_id": dizin.split("/")[1], "sha": SHA, "status": "failed", "saglik": saglik,
             "tests": [giris], "failures": [giris], "lang": "java"},
            ensure_ascii=False,
        )
    )  # fmt: skip
    sid = None
    if script_platform:
        sid = uuid.uuid4()
        with Session(engine) as s, s.begin():
            s.add(
                Script(
                    id=sid,
                    dosya_yolu="e2e-app/src/test/java/x/TPD1C3_0a1b2c3dTest.java",
                    platform=script_platform,
                )
            )
    with Session(engine) as s, s.begin():
        s.add(
            Run(
                id=rid,
                script_id=sid,
                commit=SHA,
                kaynak="local",
                tetik="push",
                sonuc="failed",
                ortam={"saglik": saglik, **({"platform": "android"} if platform_ortam else {})},
                artefaktlar={"dizin": dizin},
            )
        )
        s.flush()
        s.add(
            TestResult(
                run_id=rid,
                test_adi="senaryo",
                dosya=SINIF,
                sonuc="failed",
                commit=SHA,
                tetik="push",
                kaynak="local",
                hata_mesaji=mesaj,
            )
        )
    return rid


def _tek(engine: Engine, rid: uuid.UUID) -> tuple[Failure, FailureEk]:
    with Session(engine) as s:
        f, ek = s.execute(
            select(Failure, FailureEk)
            .join(FailureEk, FailureEk.failure_id == Failure.id)
            .where(Failure.run_id == rid)
        ).one()
        return f, ek


def test_uctan_uca_java_locator_kirilmasi_oneri(
    engine: Engine, artefakt_kok: Path, toolchain: FakeToolchain
) -> None:
    toolchain.java_semboller = JAVA_SEMBOLLER
    rid = _java_kosusu(engine, artefakt_kok, TIMEOUT_MSG)
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert (f.sinif, f.alt_tur, f.karar_kaynagi) == ("test_maintenance", "locator", "rule")
    assert f.oneri_turu == "locator_fix"
    o = ek.oneri
    assert (o["locator_key"], o["old_testid"], o["new_testid"]) == (
        "Katalog.SEPETE_EKLE",
        "add-to-cart",
        "cart-add",
    )
    assert o["platform"] == "android" and o["kaynak"] == "sayfa_kaynagi"
    assert o["dosya"] == KIMLIKLER and o["scope_test_id"] == "product-card-P-001"
    assert ("symbols", SHA, "android") in toolchain.cagrilar
    kodlar = [s["kod"] for s in f.eslesen_sinyaller]
    assert kodlar[0] == "locator_0_eleman" and kodlar[-1] == "test_id_farkli"
    assert "eski_kimlik_ekranda_yok" in kodlar
    turler = {lk["tur"] for lk in ek.kanit_linkleri}
    assert {"screenshot", "page_source"} <= turler


def test_uctan_uca_java_platform_scriptten(
    engine: Engine, artefakt_kok: Path, toolchain: FakeToolchain
) -> None:
    toolchain.java_semboller = JAVA_SEMBOLLER
    rid = _java_kosusu(
        engine, artefakt_kok, TIMEOUT_MSG, platform_ortam=False, script_platform="android"
    )
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert f.sinif == "test_maintenance" and ek.oneri["platform"] == "android"


def test_uctan_uca_java_sayfa_kaynagi_yoksa_oneri_yok_llm_replay_miss(
    engine: Engine,
    artefakt_kok: Path,
    toolchain: FakeToolchain,
    triage_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tp_core.audit import PgCallRecorder
    from tp_core.gateway import GatewaySettings, build_gateway

    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TP_REPLAY_STRICT", raising=False)
    triage_env["gateway"] = lambda engine: build_gateway(
        PgCallRecorder(engine), engine=engine, settings=GatewaySettings()
    )
    toolchain.java_semboller = JAVA_SEMBOLLER
    rid = _java_kosusu(engine, artefakt_kok, TIMEOUT_MSG, sayfa_kaynagi=None)
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert (f.sinif, f.oneri_turu) == ("unknown", "none")
    assert ek.oneri is None and "sayfa kaynağı" in (ek.oneri_yok_nedeni or "")


def test_uctan_uca_java_assertion_product_defect(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bugs_modulu(monkeypatch)
    rid = _java_kosusu(engine, artefakt_kok, ASSERT_MSG)
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert f.sinif == "product_defect" and f.karar_kaynagi == "rule"
    assert (ek.kanit["beklenen"], ek.kanit["gerceklesen"]) == ("150,00 TL", "175,00 TL")
    assert "sayfa_yapisi_beklenen" in [s["kod"] for s in f.eslesen_sinyaller]
