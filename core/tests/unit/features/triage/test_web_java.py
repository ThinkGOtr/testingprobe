"""Web + Java (Playwright for Java + TestNG; 011 üretim dili §2.8) triage: dil/rapora bakan "Java
mı" sorusu, Playwright for Java hata kalıpları, web yöntemiyle kanıt (trace.zip / sayfa.html) ve
kimlik ↔ sabit eşlemesi `Kimlikler.java` üzerinden (gerçek Postgres + artefakt fikstürleri)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tp_core.features.triage import classify_run
from tp_core.features.triage import java_web as jw
from tp_core.features.triage.rules import Girdi, siniflandir
from tp_core.features.triage.services import TriageToolchain
from tp_core.models import Failure, Run, TestResult
from tp_core.models.triage_feature import FailureEk

from .conftest import SHA, FakeToolchain, trace_zip
from .test_java import JAVA_SEMBOLLER, _bugs_modulu

pytestmark = pytest.mark.usefixtures("triage_env")

SINIF = "com.antreklabs.bayi.uretilen.TPD1Web3_0a1b2c3dTest"
DOSYA = "src/test/java/com/antreklabs/bayi/uretilen/TPD1Web3_0a1b2c3dTest.java"
KANIT_AD = "TPD1Web3_0a1b2c3dTest.senaryo"

PW_TIMEOUT = (
    "com.microsoft.playwright.TimeoutError: Error {\n"
    "  message='Timeout 10000ms exceeded.\n"
    "=========================== logs ===========================\n"
    'waiting for getByTestId("product-card-P-001").getByTestId("add-to-cart")\n'
    "============================================================'\n"
    "  name='TimeoutError'\n"
    "}"
)
PW_LOCATOR_CLICK = (
    "com.microsoft.playwright.PlaywrightException: Locator.click: Timeout 5000ms exceeded.\n"
    'Call log:\n  - waiting for getByTestId("nav-cart")'
)
OT4J = (
    "org.opentest4j.AssertionFailedError: cart-total metni ==> expected: <150,00 TL> but was: "
    "<175,00 TL>"
)
PW_ASSERT = (
    "org.opentest4j.AssertionFailedError: Locator expected to have text: 150,00 TL\n"
    'Received: 175,00 TL\nCall log:\n  - waiting for getByTestId("cart-total")'
)
PW_NET = (
    "com.microsoft.playwright.PlaywrightException: Page.navigate: net::ERR_CONNECTION_REFUSED "
    "at http://demo-app-web:8080/katalog"
)

DOM_KIRIK = """<!doctype html><html><body>
<nav><a data-testid="nav-cart">Sepet</a></nav>
<main>
  <article data-testid="product-card-P-001"><h3>Kola 330 ml</h3>
    <input data-testid="qty-input-P-001" value="1">
    <button data-testid="cart-add">Sepete ekle</button>
  </article>
  <article data-testid="product-card-P-002">
    <button data-testid="cart-add">Sepete ekle</button>
  </article>
  <div data-testid="promo-banner">Kampanya</div>
  <script>var x = "<div data-testid='kotu'>";</script>
</main></body></html>"""


# ----------------------------------------------------------------------------- saf


def test_playwright_java_kaliplari() -> None:
    assert jw.playwright_java_turu(PW_TIMEOUT) == "locator_timeout"
    assert jw.playwright_java_turu(PW_LOCATOR_CLICK) == "locator_timeout"
    assert jw.playwright_java_turu(OT4J) == "assertion"
    assert jw.playwright_java_turu(PW_ASSERT) == "assertion"
    assert jw.playwright_java_turu("java.lang.AssertionError: x beklenen <1>, görülen <2>") == (
        "assertion"
    )
    assert jw.playwright_java_turu(PW_NET) == "navigation"
    assert jw.playwright_java_turu("java.net.ConnectException: Connection refused") == (
        "navigation"
    )
    # Doğrulanan öğe hiç bulunamadı: değer farkı değil (0 eleman).
    bulunamadi = (
        "org.opentest4j.AssertionFailedError: Locator expected to be visible\n"
        "Received: <element(s) not found>"
    )
    assert jw.playwright_java_turu(bulunamadi) == "locator_not_found"
    assert (
        jw.playwright_java_turu(
            "com.microsoft.playwright.PlaywrightException: strict mode violation: 2 elements"
        )
        == "other"
    )
    assert jw.playwright_java_turu("NullPointerException") is None
    assert jw.beklenen_gorulen(OT4J) == ("150,00 TL", "175,00 TL")
    assert jw.beklenen_gorulen(PW_ASSERT) == ("150,00 TL", "175,00 TL")


def test_kirik_kimlik_cagri_gunlugunden_ve_ekran_bicimi() -> None:
    assert jw.kirik_kimlik(PW_TIMEOUT) == ("add-to-cart", "product-card-P-001", False)
    assert jw.kirik_kimlik(PW_LOCATOR_CLICK) == ("nav-cart", None, False)
    assert jw.kirik_kimlik("kimlik 'kart' içinde 'dugme'") == ("dugme", "kart", False)
    assert jw.kirik_kimlik("bir şey") == (None, None, False)


def test_dom_dugumleri_kapsayici_zinciri_ve_sinirlar() -> None:
    d = jw.dom_dugumleri(DOM_KIRIK)
    kimlikler = [x.kimlik for x in d]
    assert "kotu" not in kimlikler  # <script> içeriği öğe değildir
    assert kimlikler.count("cart-add") == 2
    ilk = next(x for x in d if x.kimlik == "cart-add")
    assert ilk.kapsayicilar == ("product-card-P-001",) and ilk.metin == "Sepete ekle"
    qty = next(x for x in d if x.kimlik == "qty-input-P-001")
    assert qty.kapsayicilar == ("product-card-P-001",)  # boş öğe (input) zinciri bozmaz
    with pytest.raises(jw.DomHatasi):
        jw.dom_dugumleri("<div>" * (jw.MAX_DERINLIK + 5))


def test_girdi_dil_java_web_kurallari() -> None:
    g = Girdi(test_adi="t", dosya=SINIF, mesaj=PW_TIMEOUT, platform="web", dil="java")
    assert g.java and g.web_java and g.tur() == "locator_timeout"
    assert g.kaynak_adi == "Playwright for Java hata mesajı"
    karar, ek, _ = siniflandir(g)
    assert karar is None and ek[0]["kod"] == "locator_0_eleman"
    net = Girdi(test_adi="t", dosya=SINIF, mesaj=PW_NET, platform="web", dil="java")
    karar, _, _ = siniflandir(net)
    assert karar is not None and karar.sinif == "environment"
    assert "Ağ / sayfa yükleme" in karar.sinyaller[0]["aciklama"]
    a = Girdi(test_adi="t", dosya=SINIF, mesaj=OT4J, platform="web", dil="java",
              beklenen="150,00 TL", gerceklesen="175,00 TL")  # fmt: skip
    karar, _, _ = siniflandir(a)
    assert karar is not None and karar.sinif == "product_defect"


def test_ts_web_ve_appium_davranisi_degismez() -> None:
    # Web + TS: Java istisna metni geçse de Playwright TS yolu.
    ts = Girdi(test_adi="t", dosya="tests/cart.spec.ts", platform="web", dil="ts",
               mesaj="Error: locator.click: Timeout 5000ms exceeded. java.lang.X")  # fmt: skip
    assert not ts.java and not ts.web_java and ts.tur() == "locator_timeout"
    eski = Girdi(test_adi="t", dosya="tests/cart.spec.ts", platform="web", mesaj="x")
    assert not eski.java and eski.kaynak_adi == "Playwright hata mesajı"
    # Appium Java: dil bilinse de uygulama platformu web + Java değildir.
    ap = Girdi(test_adi="t", dosya=SINIF, platform="android", dil="java",
               mesaj="org.openqa.selenium.TimeoutException: x")  # fmt: skip
    assert ap.java and not ap.web_java and ap.kaynak_adi == "Java/Appium hata mesajı"


def test_triage_toolchain_symbols_govdesi() -> None:
    import httpx

    govdeler: list[dict[str, Any]] = []

    def yanit(req: httpx.Request) -> httpx.Response:
        govdeler.append(json.loads(req.content))
        return httpx.Response(200, json={"page_objects": []})

    tc = TriageToolchain("http://tc", transport=httpx.MockTransport(yanit))
    tc.symbols(SHA)
    tc.symbols(SHA, platform="web")
    tc.symbols(SHA, platform="android")
    tc.symbols(SHA, platform="web", lang="java")
    assert govdeler == [
        {"sha": SHA},
        {"sha": SHA},
        {"sha": SHA, "platform": "android"},
        {"sha": SHA, "lang": "java", "platform": "web"},
    ]


# ----------------------------------------------------------------------------- uçtan uca


def _web_java_kosusu(
    engine: Engine,
    kok: Path,
    mesaj: str,
    *,
    dom: str | None = DOM_KIRIK,
    trace: bytes | None = None,
    dil_ortamda: bool = True,
) -> uuid.UUID:
    rid = uuid.uuid4()
    dizin = f"runs/ci-{rid.hex[:12]}"
    yerel = kok / dizin
    kanit = yerel / "src" / "e2e-java" / "target" / "kanit" / KANIT_AD
    kanit.mkdir(parents=True)
    if dom is not None:
        (kanit / "sayfa.html").write_text(dom, encoding="utf-8")
    if trace is not None:
        (kanit / "trace.zip").write_bytes(trace)
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
             "tests": [giris], "failures": [giris], "lang": "java", "platform": "web"},
            ensure_ascii=False,
        )
    )  # fmt: skip
    sid = None
    ortam: dict[str, Any] = {"saglik": saglik, "platform": "web"}
    if dil_ortamda:
        ortam["dil"] = "java"
    with Session(engine) as s, s.begin():
        s.add(Run(id=rid, script_id=sid, commit=SHA, kaynak="local", tetik="push",
                  sonuc="failed", ortam=ortam, artefaktlar={"dizin": dizin}))  # fmt: skip
        s.flush()
        s.add(TestResult(run_id=rid, test_adi="senaryo", dosya=SINIF, sonuc="failed",
                         commit=SHA, tetik="push", kaynak="local", hata_mesaji=mesaj))  # fmt: skip
    return rid


def _tek(engine: Engine, rid: uuid.UUID) -> tuple[Failure, FailureEk]:
    with Session(engine) as s:
        return s.execute(
            select(Failure, FailureEk)
            .join(FailureEk, FailureEk.failure_id == Failure.id)
            .where(Failure.run_id == rid)
        ).one()


def test_uctan_uca_web_java_locator_oneri_dom_ve_kimlikler(
    engine: Engine, artefakt_kok: Path, toolchain: FakeToolchain
) -> None:
    toolchain.java_semboller = JAVA_SEMBOLLER
    tr = trace_zip(
        "http://demo-app-web:8080/katalog",
        [("ARTICLE", "product-card-P-001", "Kola"), ("BUTTON", "cart-add", "Sepete ekle")],
    )
    rid = _web_java_kosusu(engine, artefakt_kok, PW_TIMEOUT, trace=tr)
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert (f.sinif, f.alt_tur, f.karar_kaynagi) == ("test_maintenance", "locator", "rule")
    o = ek.oneri
    assert (o["locator_key"], o["old_testid"], o["new_testid"]) == (
        "Katalog.SEPETE_EKLE", "add-to-cart", "cart-add",
    )  # fmt: skip
    assert (o["platform"], o["dil"], o["kaynak"]) == ("web", "java", "hata_ani_dom")
    assert o["dosya"].endswith("ekranlar/Kimlikler.java")
    assert o["scope_test_id"] == "product-card-P-001" and o["url_path"] == "/katalog"
    assert o["trace_dom"]["destekliyor"] is True
    # Sembol tablosu web + Java projesinden istenir; Appium sayfa kaynağı okunmaz.
    assert ("symbols", SHA, "web", "java") in toolchain.cagrilar
    assert not any(c[0] == "probe" for c in toolchain.cagrilar)
    kodlar = [s["kod"] for s in f.eslesen_sinyaller]
    assert kodlar[0] == "locator_0_eleman" and kodlar[-1] == "test_id_farkli"
    assert "trace_dom" in kodlar and "eski_kimlik_ekranda_yok" in kodlar
    turler = {lk["tur"] for lk in ek.kanit_linkleri}
    assert {"screenshot", "trace", "dom"} <= turler and "page_source" not in turler


def test_uctan_uca_web_java_dil_rapordan(
    engine: Engine, artefakt_kok: Path, toolchain: FakeToolchain
) -> None:
    """`run.ortam.dil` yoksa dil koşu raporundan (`run.json` `lang`) gelir."""
    toolchain.java_semboller = JAVA_SEMBOLLER
    rid = _web_java_kosusu(engine, artefakt_kok, PW_TIMEOUT, dil_ortamda=False)
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert f.sinif == "test_maintenance" and ek.oneri["dil"] == "java"


def test_uctan_uca_web_java_eski_kimlik_sayfada_ise_oneri_yok(
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
    dom = DOM_KIRIK.replace(
        'data-testid="cart-add">Sepete ekle</button>\n  </article>\n  <art',
        'data-testid="add-to-cart">Sepete ekle</button>\n  </article>\n  <art',
    )
    rid = _web_java_kosusu(engine, artefakt_kok, PW_TIMEOUT, dom=dom)
    classify_run(engine, rid)
    _f, ek = _tek(engine, rid)
    assert ek.oneri is None and "ekranda var" in (ek.oneri_yok_nedeni or "")


def test_uctan_uca_web_java_assertion_product_defect(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bugs_modulu(monkeypatch)
    rid = _web_java_kosusu(engine, artefakt_kok, OT4J)
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert f.sinif == "product_defect" and f.karar_kaynagi == "rule"
    assert (ek.kanit["beklenen"], ek.kanit["gerceklesen"]) == ("150,00 TL", "175,00 TL")
    kodlar = [s["kod"] for s in f.eslesen_sinyaller]
    assert "sayfa_yapisi_beklenen" in kodlar


def test_uctan_uca_web_java_ag_hatasi_ortam(engine: Engine, artefakt_kok: Path) -> None:
    rid = _web_java_kosusu(engine, artefakt_kok, PW_NET)
    classify_run(engine, rid)
    f, _ek = _tek(engine, rid)
    assert f.sinif == "environment" and f.karar_kaynagi == "rule"


def test_kanit_oku_runner_evidence_yollari(tmp_path: Path) -> None:
    """test-runner (Ş3) web + Java kanıtı: `failure.page_html_rel` / `evidence.page_html` ve
    `trace_rel` (TP_ARTIFACTS_PATH'e göre) öncelikli; kök dışı yol okunmaz."""
    kosu_rel = "runs/ci-x"
    kosu = tmp_path / kosu_rel
    d = kosu / "baska" / "yer"
    d.mkdir(parents=True)
    (d / "dom.html").write_text(DOM_KIRIK, encoding="utf-8")
    (d / "iz.zip").write_bytes(b"PK")
    failure = {
        "page_html_rel": f"{kosu_rel}/baska/yer/dom.html",
        "trace_rel": f"{kosu_rel}/baska/yer/iz.zip",
        "evidence": {"page_html": {"rel": f"{kosu_rel}/../disari.html"}},
    }
    k = jw.kanit_oku(kosu, kosu_rel, failure, SINIF, "senaryo")
    assert k.dom_rel == "baska/yer/dom.html" and k.sayfa_html and "cart-add" in k.sayfa_html
    assert k.trace_rel == "baska/yer/iz.zip"
    k2 = jw.kanit_oku(
        kosu,
        kosu_rel,
        {"evidence": {"page_html": {"rel": f"{kosu_rel}/baska/yer/dom.html"}}},
        SINIF,
        "senaryo",
    )
    assert k2.dom_rel == "baska/yer/dom.html"
