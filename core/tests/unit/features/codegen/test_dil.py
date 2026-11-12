"""011 üretim dili (Ş1 core-akış): `platform.py` yardımcıları, dil algılama, toolchain istemcisi,
Java tablosuyla web locator çapraz kontrolü, şema (0021) ve `GET /code/languages` /
`POST /code/generate` `dil` alanı.

Uçtan uca akışlar (web + Java PR'ı, doğrulanmamış dil) `test_dil_akis.py`'dedir.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.codegen.conftest import TOOLCHAIN
from tp_core.features.codegen import dil_algila, service
from tp_core.features.codegen import platform as p
from tp_core.features.codegen import render as render_modulu
from tp_core.features.codegen.browser import LocatorHedefi
from tp_core.features.codegen.checks import SymbolTable
from tp_core.features.codegen.render import RenderError, render_dil
from tp_core.features.codegen.toolchain import ToolchainClient, ToolchainError, clear_symbol_cache
from tp_core.workflow.states import MACHINES

HERE = Path(__file__).resolve().parent
TS_SYMBOLS = json.loads((HERE / "symbols.json").read_text(encoding="utf-8"))

# ------------------------------------------------------------------ platform.py


def test_dil_sabitleri() -> None:
    assert p.DILLER == ("ts", "java", "csharp", "python")
    assert p.TAM_HAT_DILLERI == ("ts", "java")
    assert p.DOGRULANMAMIS_DILLER == ("csharp", "python")
    assert set(p.DIL_ETIKETI) == set(p.DILLER)


@pytest.mark.parametrize(
    ("platform", "dil", "beklenen"),
    [
        ("web", "ts", True),
        ("web", "java", True),
        ("web", "csharp", True),
        ("web", "python", True),
        (None, "python", True),
        ("android", "java", True),
        ("ios", "java", True),
        ("windows", "java", True),
        ("android", "ts", False),
        ("ios", "csharp", False),
        ("windows", "python", False),
        ("web", "go", False),
        ("tv", "java", False),
        ("web", None, False),
    ],
)
def test_gecerli_cift(platform: str | None, dil: str | None, beklenen: bool) -> None:
    assert p.gecerli_cift(platform, dil) is beklenen


def test_varsayilan_ve_dil_uyumu() -> None:
    assert p.varsayilan_dil("web") == p.varsayilan_dil(None) == "ts"
    assert all(p.varsayilan_dil(x) == "java" for x in p.UYGULAMA_PLATFORMLARI)
    # Eski imza aynen çalışır (toolchain `lang`); dil verilirse o kazanır.
    assert p.dil("web") == "ts" and p.dil("android") == "java"
    assert p.dil("web", "java") == "java" and p.dil("web", "bilinmez") == "ts"
    assert p.platform_dilleri("android") == ("java",)
    assert p.platform_dilleri("web") == p.DILLER


def test_java_mi_ve_tam_hat_mi_platformdan_bagimsiz() -> None:
    assert p.java_mi("java") and not p.java_mi("ts") and not p.java_mi(None)
    assert p.tam_hat_mi("ts") and p.tam_hat_mi("java")
    assert not p.tam_hat_mi("csharp") and not p.tam_hat_mi("python")
    assert p.dogrulanmamis_mi("python") and not p.dogrulanmamis_mi("java")
    # Araç/ortam sorusu platformdadır: web + Java yine web'dir.
    assert not p.uygulama_mi("web")


def test_gecerli_dil_turkce_hata() -> None:
    assert p.gecerli_dil("web", None) == "ts" and p.gecerli_dil("ios", "") == "java"
    assert p.gecerli_dil("web", " Python ") == "python"
    with pytest.raises(ValueError, match="dil yalnızca"):
        p.gecerli_dil("web", "go")
    with pytest.raises(ValueError, match="android platformunda TypeScript ile kod üretilemez"):
        p.gecerli_dil("android", "ts")


def test_cati_ve_check_adi() -> None:
    assert p.cati("web", "java") == "Playwright for Java + TestNG"
    assert p.cati("web", "csharp") == "Playwright .NET + NUnit"
    assert p.cati("web", "python") == "pytest-playwright"
    assert p.cati("android", "java") == "Appium + TestNG"
    # K-T1: web + ts `local-ci`, web + Java `local-ci-web-java`, uygulama `local-ci-<platform>`.
    assert p.check_adi("web") == p.check_adi("web", "ts") == "local-ci"
    assert p.check_adi("web", "java") == "local-ci-web-java"
    assert p.check_adi("web", "csharp") == "local-ci"
    assert p.check_adi("ios") == p.check_adi("ios", "java") == "local-ci-ios"


def test_java_test_kalibi_tek_kaynak() -> None:
    """K-T7: `*Test.java | *Testi.java | *Tests.java | *IT.java`; `birim/`, `uretilen/` hariç;
    Kotlin `*Test.kt` yalnız istenirse (algılama sinyali)."""
    kok = "e2e-java/src/test/java/com/x"
    for ad in ("SepetTest.java", "SepetTesti.java", "SepetTests.java", "SepetIT.java"):
        assert p.java_test_dosyasi_mi(f"{kok}/testler/{ad}"), ad
    assert not p.java_test_dosyasi_mi(f"{kok}/ekranlar/Sepet.java")
    assert not p.java_test_dosyasi_mi(f"{kok}/birim/KimliklerTest.java")
    assert not p.java_test_dosyasi_mi(f"{kok}/uretilen/TPD1WebC1_0a1b2c3dTest.java")
    assert p.java_test_dosyasi_mi(f"{kok}/uretilen/TPD1WebC1_0a1b2c3dTest.java", haric=("birim",))
    assert not p.java_test_dosyasi_mi("src/test/kotlin/SepetTest.kt")
    assert p.java_test_dosyasi_mi("src/test/kotlin/SepetTest.kt", kotlin=True)


def test_durum_makinesi_unverified() -> None:
    m = MACHINES["script"]
    assert "unverified" in m.states
    assert m.allowed("verifying", "unverified")
    assert m.allowed("unverified", "pending") and m.allowed("unverified", "closed")
    assert not m.allowed("unverified", "merged") and not m.allowed("unverified", "pr_open")
    assert not m.allowed("checking", "unverified")
    assert ("unverified", "merged") not in m.gates


# ------------------------------------------------------------------ dil algılama


class SahteForge:
    def __init__(self, dosyalar: dict[str, str], *, hata: Exception | None = None) -> None:
        self.dosyalar = dosyalar
        self.hata = hata
        self.listeleme = 0

    def head_sha(self, ref: str = "main") -> str:
        if self.hata:
            raise self.hata
        return "a" * 40

    def list_files(self, prefix: str = "", ref: str = "main") -> list[str]:
        self.listeleme += 1
        return sorted(y for y in self.dosyalar if y.startswith(prefix))

    def read_file(self, path: str, ref: str = "main") -> str:
        return self.dosyalar[path]


@pytest.fixture(autouse=True)
def _temiz_onbellek() -> Any:
    dil_algila.onbellegi_temizle()
    yield
    dil_algila.onbellegi_temizle()


def _depo(**ek: str) -> dict[str, str]:
    return {
        "e2e/package.json": "{}",
        "e2e/tests/a.spec.ts": "",
        "e2e/tests/alt/b.spec.ts": "",
        "e2e/tests/generated/tpd-1-c1.spec.ts": "",  # üretilen sayılmaz
        "e2e/tests/fixtures.ts": "",
        **ek,
    }


def test_algila_ts_uretilenleri_saymaz() -> None:
    a = dil_algila.algila(SahteForge(_depo()), "main", "web", uygulama_koku="")
    assert (a.dil, a.kaynak) == ("ts", "algilandi")
    assert a.sayilar == {"ts": 2, "java": 0, "csharp": 0, "python": 0}
    assert a.projeler == {"ts": True, "java": False}


def test_algila_java_cogunlukta_ve_uretilen_birim_haric() -> None:
    kok = "e2e-java/src/test/java/com/antreklabs/bayi"
    depo = _depo(
        **{
            "e2e-java/pom.xml": "<project/>",
            f"{kok}/testler/SepetTest.java": "",
            f"{kok}/testler/GirisTest.java": "",
            f"{kok}/testler/SiparisTest.java": "",
            f"{kok}/uretilen/TPD1WebC1_0a1b2c3dTest.java": "",
            f"{kok}/birim/KimliklerTest.java": "",
            f"{kok}/ekranlar/GirisEkrani.java": "",
        }
    )
    a = dil_algila.algila(SahteForge(depo), "main", "web", uygulama_koku="")
    assert a.dil == "java" and a.sayilar["java"] == 3 and a.projeler["java"]


def test_algila_esitlikte_oncelik_ts() -> None:
    kok = "e2e-java/src/test/java/x"
    depo = _depo(**{f"{kok}/ATest.java": "", f"{kok}/BTest.java": "", "e2e-java/pom.xml": ""})
    a = dil_algila.algila(SahteForge(depo), "main", "web", uygulama_koku="")
    assert a.sayilar["ts"] == a.sayilar["java"] == 2 and a.dil == "ts"


def test_algila_python_yalniz_playwright_projesi() -> None:
    depo = {
        # Uygulamanın kendi birim testleri: Playwright projesi değil → sayılmaz.
        "api/pyproject.toml": "[project]\ndependencies = ['fastapi']\n",
        "api/tests/test_api.py": "",
        "api/tests/test_db.py": "",
        "api/tests/test_x.py": "",
        "e2e-py/pyproject.toml": "dependencies = ['pytest-playwright']\n",
        "e2e-py/tests/test_sepet.py": "",
        "e2e-py/tests/siparis_test.py": "",
        "e2e-py/tests/yardimci.py": "",
    }
    a = dil_algila.algila(SahteForge(depo), "main", "web", uygulama_koku="")
    assert a.sayilar["python"] == 2 and a.dil == "python"


def test_algila_csharp_csproj_ister() -> None:
    depo = {
        "E2E/E2E.csproj": '<PackageReference Include="Microsoft.Playwright.NUnit" />',
        "E2E/SepetTests.cs": "",
        "E2E/GirisTest.cs": "",
        "Diger/Hesap.csproj": "<Project/>",  # Playwright'sız proje
        "Diger/HesapTests.cs": "",
        "Baska/YalnizTests.cs": "",  # csproj altında değil
    }
    a = dil_algila.algila(SahteForge(depo), "main", "web", uygulama_koku="")
    assert a.sayilar["csharp"] == 2 and a.dil == "csharp"


def test_algila_uygulama_koku_ve_uygulama_platformu() -> None:
    depo = {
        f"demo-app/{k}": v
        for k, v in _depo(
            **{
                "e2e-app/pom.xml": "",
                "e2e-app/src/test/java/a/testler/AkisTest.java": "",
            }
        ).items()
    }
    depo["baska/e2e/tests/z.spec.ts"] = ""  # uygulama kökü dışında
    f = SahteForge(depo)
    web = dil_algila.algila(f, "main", "web", uygulama_koku="demo-app")
    assert web.sayilar["ts"] == 2 and web.dil == "ts"
    app = dil_algila.algila(f, "main", "android", uygulama_koku="demo-app")
    assert app.sayilar == {"java": 1} and app.dil == "java" and app.kaynak == "algilandi"
    assert app.projeler == {"java": True}


def test_algila_bos_depo_ve_forge_hatasi_varsayilan() -> None:
    a = dil_algila.algila(SahteForge({}), "main", "web", uygulama_koku="")
    assert (a.dil, a.kaynak) == ("ts", "varsayilan")
    f = SahteForge({}, hata=RuntimeError("forge yok"))
    b = dil_algila.algila(f, "main", "ios", uygulama_koku="")
    assert (b.dil, b.kaynak, b.projeler) == ("java", "varsayilan", {})


def test_algila_sha_ile_onbelleklenir() -> None:
    f = SahteForge(_depo())
    dil_algila.algila(f, "main", "web", uygulama_koku="")
    dil_algila.algila(f, "a" * 40, "web", uygulama_koku="")
    assert f.listeleme == 1
    dil_algila.algila(f, "main", "android", uygulama_koku="")
    assert f.listeleme == 2  # platform anahtardadır


# ------------------------------------------------------------------ toolchain istemcisi


def _istemci(istekler: list[tuple[str, dict[str, Any]]], lang: str | None = None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        govde = json.loads(request.content or b"{}")
        istekler.append((request.url.path, govde))
        if request.url.path == "/symbols":
            tablo = {"sha": govde["sha"], "page_objects": []}
            if lang or govde.get("lang") or govde.get("platform"):
                tablo["lang"] = lang or "java"
            return httpx.Response(200, json=tablo)
        return httpx.Response(200, json={"conclusion": "success"})

    return ToolchainClient(TOOLCHAIN, transport=httpx.MockTransport(handler))


def test_toolchain_symbols_govdeleri_ve_onbellek() -> None:
    clear_symbol_cache()
    istekler: list[tuple[str, dict[str, Any]]] = []
    c = _istemci(istekler)
    sha = "b" * 40
    c.symbols(sha)
    c.symbols(sha, platform="android")
    c.symbols(sha, platform="web", lang="java")
    c.symbols(sha, lang="java")  # platform yok → web
    c.symbols(sha, platform="ios")  # uygulama tablosu platformlar arası ortak
    c.symbols(sha, platform="web", lang="ts")  # web + ts önbellekte
    assert [b for _, b in istekler] == [
        {"sha": sha},
        {"sha": sha, "platform": "android"},
        {"sha": sha, "lang": "java", "platform": "web"},
    ]
    clear_symbol_cache()


def test_toolchain_dogrulanmamis_dil_gitmez() -> None:
    istekler: list[tuple[str, dict[str, Any]]] = []
    c = _istemci(istekler)
    for dil in ("csharp", "python"):
        with pytest.raises(ToolchainError, match="yalnızca ts"):
            c.symbols("c" * 40, lang=dil)
        with pytest.raises(ToolchainError, match="yalnızca ts"):
            c.check("c" * 40, ["x"], lang=dil)
    with pytest.raises(ToolchainError, match="geçersiz platform/dil"):
        c.symbols("c" * 40, platform="android", lang="ts")
    assert istekler == []


def test_toolchain_ts_tablosu_bekleniyorsa_java_reddedilir() -> None:
    clear_symbol_cache()
    c = _istemci([], lang="java")
    with pytest.raises(ToolchainError, match="TS sembol tablosu"):
        c.symbols("d" * 40, platform="web", lang="ts")
    clear_symbol_cache()


def test_toolchain_check_govdeleri() -> None:
    istekler: list[tuple[str, dict[str, Any]]] = []
    c = _istemci(istekler)
    c.check("e" * 40, ["tests/generated/a.spec.ts"])
    c.check("e" * 40, ["tests/generated/a.spec.ts"], platform="web")
    c.check("e" * 40, ["src/test/java/X.java"], platform="android")
    c.check("e" * 40, ["src/test/java/Y.java"], platform="web", lang="java")
    govdeler = [b for _, b in istekler]
    assert "lang" not in govdeler[0] and "platform" not in govdeler[0]
    assert "lang" not in govdeler[1] and "platform" not in govdeler[1]
    assert (govdeler[2]["lang"], govdeler[2]["platform"]) == ("java", "android")
    assert (govdeler[3]["lang"], govdeler[3]["platform"]) == ("java", "web")
    assert govdeler[3]["repeat_each"] == 3


def test_service_toolchain_hedefi_ve_kokler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_FORGE_APP_ROOT", "demo-app")
    assert service.toolchain_hedefi("web", "ts") == {}
    assert service.toolchain_hedefi("web", None) == {}
    assert service.toolchain_hedefi("android", "java") == {"platform": "android"}
    assert service.toolchain_hedefi("web", "java") == {"lang": "java", "platform": "web"}
    assert service.e2e_java_root() == "demo-app/e2e-java"
    assert service.bayiler_path("web").startswith("demo-app/e2e-java/src/test/java/")
    assert service.bayiler_path().startswith("demo-app/e2e-app/")
    yol = "demo-app/e2e-java/src/test/java/com/antreklabs/bayi/uretilen/TPD1WebC2_0a1b2c3dTest.java"
    assert service.e2e_goreli(yol, "web", "java") == yol.removeprefix("demo-app/e2e-java/")
    assert service.e2e_goreli("demo-app/e2e/tests/generated/a.spec.ts", "web") == (
        "tests/generated/a.spec.ts"
    )
    cid = uuid.UUID("0a1b2c3d-0000-0000-0000-000000000000")
    assert service.baslangic_dosya_yolu("java", "web", "TPD-1", 2, cid) == yol
    # K-T6: doğrulanmamış başlangıç yolu render'ın yol kuralıdır (uygulama kökü altında).
    for dil, kok in (("csharp", "demo-app/e2e-csharp"), ("python", "demo-app/e2e-python")):
        yol_d = service.baslangic_dosya_yolu(dil, "web", "TPD-1", 2, cid)
        assert yol_d == render_modulu.dogrulanmamis_repo_path(dil, "TPD-1", 2, cid, kok)
        assert yol_d.startswith(kok + "/tests/")
    assert service.proje_dosyasi("java") == "demo-app/e2e-java/pom.xml"
    assert service.proje_dosyasi("ts") == "demo-app/e2e/package.json"
    # Tekrar sayısı ve dal adı araç/ortam sorusudur: dile bakmaz.
    assert service.tekrar_sayisi("web") == 3
    assert service.branch_for(cid, "web") == f"tp/case-{cid}"


# ------------------------------------------------------------- render giriş noktası


def test_render_dil_gecersiz_cift() -> None:
    # Geçerli çiftlerin render'ı Ş2'nin `test_render_dil.py`'sinde; burada yalnız çift kuralı.
    with pytest.raises(RenderError, match="yalnızca java"):
        render_dil(None, dil="ts", platform="android", rules=Path("."))  # type: ignore[arg-type]


# --------------------------------------------- web + Java: testId'ye dayalı çapraz kontrol


def java_web_tablosu() -> dict[str, Any]:
    """§2.5 page object eşitliği: TS tablosuyla aynı sınıf/metot/parametre adları, Java türleri ve
    Kimlikler biçimli locator'lar (yalnız testId/prefix; rol/ad boş, `within` yok)."""
    tur = {"string": "String", "number": "int", "boolean": "boolean"}
    pos = []
    for po in TS_SYMBOLS["page_objects"]:
        pos.append(
            {
                "class": po["class"],
                "file": f"src/test/java/com/antreklabs/bayi/ekranlar/{po['class']}.java",
                "doc": po.get("doc"),
                "methods": [
                    {
                        **m,
                        "name": p.java_metot_adi(m["name"]),
                        "async": False,
                        "returns": "void",
                        "params": [
                            {**prm, "type": tur.get(prm["type"], prm["type"])}
                            for prm in m.get("params") or []
                        ],
                    }
                    for m in po.get("methods") or []
                ],
                "locators": {
                    _kimlik_anahtari(k): {
                        "testId": v["testId"],
                        "role": "",
                        "name": "",
                        "intent": v.get("intent"),
                        "prefix": bool(v.get("prefix")),
                    }
                    for k, v in (po.get("locators") or {}).items()
                },
            }
        )
    return {
        "schema_version": 1,
        "root": "src/test/java",
        "page_objects": pos,
        "locator_files": [],
        "errors": [],
        "lang": "java",
        "fixtures": [p_["class"][:1].lower() + p_["class"][1:] for p_ in pos],
    }


def _kimlik_anahtari(k: str) -> str:
    sinif, _, ad = k.partition(".")
    import re

    return f"{sinif[:1].upper()}{sinif[1:]}." + re.sub(r"(?<!^)([A-Z])", r"_\1", ad).upper()


def test_java_web_tablosu_ts_ile_ayni_imzalar() -> None:
    ts, java = SymbolTable(TS_SYMBOLS), SymbolTable(java_web_tablosu())
    assert set(ts.classes) == set(java.classes)
    assert java.method("LoginPage", "login") is not None
    # Tek ad istisnası: `goto` Java'da ayrılmış sözcük → `goTo`.
    assert java.method("LoginPage", "goTo") is not None
    assert java.method("LoginPage", "goto") is None
    assert {v["testId"] for v in ts.locators().values()} == {
        v["testId"] for v in java.locators().values()
    }
    assert all(v["role"] == "" and "within" not in v for v in java.locators().values())


def test_java_metot_adi_eslemesi() -> None:
    assert p.JAVA_AD_ESLEME == {"goto": "goTo"}
    assert p.java_metot_adi("goto") == "goTo" and p.java_metot_adi("login") == "login"
    girdi = {
        "step_mapping": [{"po": "LoginPage", "method": "goto", "args": []}, "bozuk"],
        "expects": [{"po": "CartPage", "method": "expectTotal", "args": ["1"]}],
        "missing_methods": [{"step_id": "S9", "method": "goto"}],
    }
    cikti = p.java_eslemesi(girdi)
    assert cikti["step_mapping"][0]["method"] == "goTo" and cikti["step_mapping"][1] == "bozuk"
    assert cikti["expects"][0]["method"] == "expectTotal"
    assert cikti["missing_methods"] == girdi["missing_methods"]  # yalnız eşleme alanları
    assert girdi["step_mapping"][0]["method"] == "goto"  # girdi değişmez
    assert p.java_eslemesi(None) is None


def _kayit(n: int, element: str, cikti: str, hedef: LocatorHedefi | None = None) -> tuple:
    return (n, element, cikti, hedef)


def test_testid_capraz_kontrol_kabul_eder() -> None:
    tablo = SymbolTable(java_web_tablosu())
    kayitlar = [
        _kayit(1, 'textbox "Kullanıcı adı" (login.username)', "getByTestId('login-username')"),
        _kayit(
            2,
            'button "Sepete ekle" P-001',
            "getByTestId('product-card-P-001').getByTestId('add-to-cart')",
        ),
        _kayit(3, "adet (Katalog.X)", "getByTestId('qty-input-P-001')"),
    ]
    assert service.locator_capraz_kontrol_testid(kayitlar, tablo) == []
    # TS kontrolü bu tabloyla (rol/ad yok) canlı kipte eşleyemez: yeni yol bu yüzden var.
    canli = [
        _kayit(1, "x", "getByTestId('login-username')", LocatorHedefi("e1", True, "textbox", "Ad"))
    ]
    assert service.locator_capraz_kontrol(canli, tablo, canli=True) != []
    assert service.locator_capraz_kontrol_testid(canli, tablo, canli=True) == []


def test_testid_capraz_kontrol_reddeder() -> None:
    tablo = SymbolTable(java_web_tablosu())
    anahtar = next(k for k, v in tablo.locators().items() if v["testId"] == "login-submit")
    kayitlar = [
        _kayit(1, "x", "getByTestId('olmayan-kimlik')"),
        _kayit(2, "x", "getByRole('button', { name: 'Giriş yap' })"),
        _kayit(3, "kart P-002", "getByTestId('product-card-P-001').getByTestId('add-to-cart')"),
        _kayit(4, f'button "Giriş yap" ({anahtar})', "getByTestId('login-username')"),
        _kayit(5, "x", "getByTestId('login-submit')\nREPLAY sapması: kayıtta 'a', canlıda 'b'"),
        _kayit(6, "x", "getByTestId('login-submit')", LocatorHedefi("css=.btn", False)),
    ]
    sonuc = dict(service.locator_capraz_kontrol_testid(kayitlar, tablo, canli=True))
    assert set(sonuc) == {1, 2, 3, 4, 5, 6}
    assert "Kimlikler'de yok" in sonuc[1]
    assert "testId'li locator dönmedi" in sonuc[2]
    assert "product-card-P-002" in sonuc[3]
    assert "login-submit" in sonuc[4]
    assert "REPLAY sapması" in sonuc[5]
    assert "snapshot ref" in sonuc[6]


# ------------------------------------------------------------------ şema (0021)


def test_dil_kolonlari_model_ile_ayni(engine: Engine) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from tp_core.models import Base

    with engine.connect() as conn:
        farklar = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    ilgili = [f for f in farklar if any(k in repr(f) for k in ("dil", "kaynak_kod", "durum"))]
    assert ilgili == []
    with engine.begin() as conn:
        satir = conn.execute(
            text("INSERT INTO script (dosya_yolu) VALUES ('x') RETURNING dil, dil_kaynagi")
        ).one()
        assert tuple(satir) == ("ts", "varsayilan")
        conn.execute(text("INSERT INTO script (dosya_yolu, durum) VALUES ('y', 'unverified')"))
    for sql, kisit in [
        ("INSERT INTO script (dosya_yolu, dil) VALUES ('x', 'go')", "script_dil_ck"),
        (
            "INSERT INTO script (dosya_yolu, dil_kaynagi) VALUES ('x', 'tahmin')",
            "script_dil_kaynagi_ck",
        ),
        ("INSERT INTO script (dosya_yolu, durum) VALUES ('x', 'yok')", "script_durum_ck"),
    ]:
        with pytest.raises(Exception, match=kisit), engine.begin() as conn:
            conn.execute(text(sql))


def test_model_varsayilan_dili_platformdan(engine: Engine) -> None:
    from tp_core.models import Script, session_scope

    with session_scope() as s:
        web, app = Script(dosya_yolu="a"), Script(dosya_yolu="b", platform="ios")
        secilen = Script(dosya_yolu="c", platform="web", dil="python", dil_kaynagi="secildi")
        s.add_all([web, app, secilen])
        s.flush()
        assert (web.dil, app.dil, secilen.dil) == ("ts", "java", "python")


def test_0021_backfill_ve_geri_alma(db: Any) -> None:
    from sqlalchemy import create_engine

    from tests.unit.conftest import run_alembic

    run_alembic(db.owner_url, "0020", "downgrade")
    e = create_engine(db.owner_url)
    try:
        with e.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO script (dosya_yolu, platform) VALUES "
                    "('w', 'web'), ('a', 'android'), ('i', 'windows')"
                )
            )
        run_alembic(db.owner_url, "head")
        with e.begin() as conn:
            dil = dict(conn.execute(text("SELECT dosya_yolu, dil FROM script")).all())
            kaynak = set(conn.execute(text("SELECT dil_kaynagi FROM script")).scalars())
            conn.execute(text("UPDATE script SET durum = 'unverified' WHERE dosya_yolu = 'w'"))
        assert dil == {"w": "ts", "a": "java", "i": "java"} and kaynak == {"varsayilan"}
        run_alembic(db.owner_url, "0020", "downgrade")
        with e.begin() as conn:
            assert (
                conn.execute(text("SELECT durum FROM script WHERE dosya_yolu = 'w'")).scalar_one()
                == "closed"
            )
        run_alembic(db.owner_url, "head")
    finally:
        e.dispose()


# ------------------------------------------------------------------ API


def test_code_languages_ve_generate_dil_dogrulamasi(
    api: TestClient, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    r = api.get("/code/languages")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["platform"] == "web" and d["algilanan"] == "ts" and d["kaynak"] == "algilandi"
    assert d["sayilar"]["ts"] >= 8 and d["sayilar"]["java"] == 0
    secenek = {x["dil"]: x for x in d["secenekler"]}
    assert list(secenek) == ["ts", "java", "csharp", "python"]
    assert secenek["ts"] == {
        "dil": "ts", "etiket": "TypeScript", "cati": "Playwright Test", "hat": "tam",
        "kullanilabilir": True, "neden": None,
    }  # fmt: skip
    # Forge'da e2e-java yok: Java web seçilemez, neden Türkçe.
    assert secenek["java"]["kullanilabilir"] is False
    assert secenek["java"]["neden"] == "Depoda Java web test projesi (e2e-java/pom.xml) yok"
    assert secenek["csharp"]["hat"] == "dogrulanmamis" and secenek["csharp"]["kullanilabilir"]

    app = api.get("/code/languages", params={"platform": "android"}).json()
    assert [x["dil"] for x in app["secenekler"]] == ["java"]
    assert app["secenekler"][0]["cati"] == "Appium + TestNG"
    assert api.get("/code/languages", params={"platform": "tv"}).status_code == 422

    cid = str(hazir["cases"][2])
    for govde, parca in [
        ({"case_ids": [cid], "platform": "android", "dil": "ts"}, "android platformunda"),
        ({"case_ids": [cid], "dil": "java"}, "e2e-java/pom.xml"),
    ]:
        r = api.post("/code/generate", json=govde)
        assert r.status_code == 422, r.text
        assert parca in r.text
    assert api.post("/code/generate", json={"case_ids": [cid], "dil": "go"}).status_code == 422


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    from .conftest import login

    u = make_user("engineer")
    login(api, u)
    return u


# ------------------------------------------- dil algılama uç durumları (inceleme turu 1, K-T7)


class SayanForge(SahteForge):
    """Okunan dosyaları sayan sahte forge (okuma bütçesi testleri)."""

    def __init__(self, dosyalar: dict[str, str], **kw: Any) -> None:
        super().__init__(dosyalar, **kw)
        self.okunan: list[str] = []

    def read_file(self, path: str, ref: str = "main") -> str:
        self.okunan.append(path)
        return super().read_file(path, ref)


def _algila(depo: dict[str, str], platform: str = "web") -> dil_algila.Algilama:
    return dil_algila.algila(SahteForge(depo), "main", platform, uygulama_koku="")


PW_POM = (
    "<project><dependencies><dependency><groupId>com.microsoft.playwright</groupId>"
    "<artifactId>playwright</artifactId></dependency></dependencies></project>"
)
PW_JAVA = "import com.microsoft.playwright.Page;\nclass X {}\n"
PW_KT = "import com.microsoft.playwright.Page\nclass X\n"


def test_algila_kokte_standart_maven_ve_tum_java_kaliplari() -> None:
    """QA-Y1: kökte Maven (`src/test/java`) + `*Test`, `*Tests`, `*IT`, `*Testi`; Kotlin sinyali."""
    depo = {
        "pom.xml": PW_POM,
        "src/test/java/com/x/SepetTest.java": PW_JAVA,
        "src/test/java/com/x/GirisTests.java": PW_JAVA,
        "src/test/java/com/x/SiparisIT.java": PW_JAVA,
        "src/test/java/com/x/KatalogTesti.java": PW_JAVA,
        "src/test/kotlin/com/x/OdemeTest.kt": PW_KT,
        "src/test/java/com/x/birim/HesapTest.java": PW_JAVA,  # birim testi sayılmaz
        "src/main/java/com/x/Sepet.java": "",
        "e2e/tests/a.spec.ts": "",
    }
    a = _algila(depo)
    assert a.sayilar["java"] == 5 and a.dil == "java" and a.kaynak == "algilandi"
    # Proje dosyası Playwright'a başvurmuyorsa (ör. backend birim testleri) sayılmaz.
    depo["pom.xml"] = "<artifactId>junit</artifactId>"
    dil_algila.onbellegi_temizle()
    assert _algila(depo).sayilar["java"] == 0


def test_algila_gradle_kotlin_projesi() -> None:
    depo = {
        "ui-tests/build.gradle.kts": 'testImplementation("com.microsoft.playwright:playwright")',
        "ui-tests/src/test/kotlin/SepetTest.kt": PW_KT,
        "ui-tests/src/test/kotlin/GirisTest.kt": PW_KT,
    }
    assert _algila(depo).sayilar["java"] == 2


def test_algila_e2e_java_her_kalip_ve_e2e_app_web_sayimina_girmez() -> None:
    kok = "e2e-java/src/test/java/com/antreklabs/bayi"
    depo = {
        "e2e-java/pom.xml": "<project/>",  # bilinen proje: işaret aranmaz
        f"{kok}/testler/SepetTests.java": "",
        f"{kok}/testler/GirisIT.java": "",
        f"{kok}/uretilen/TPD1WebC1_0a1b2c3dTest.java": "",
        "e2e-app/pom.xml": PW_POM,
        "e2e-app/src/test/java/com/antreklabs/bayi/testler/SepetTesti.java": "",
    }
    a = _algila(depo)
    assert a.sayilar["java"] == 2 and a.sayilar["csharp"] == a.sayilar["python"] == 0


def test_algila_android_e2e_app_testi_kalibi() -> None:
    """MİM-O3: e2e-app el testleri `*Testi.java` → android algılaması 0 değil."""
    kok = "e2e-app/src/test/java/com/antreklabs/bayi"
    depo = {
        "e2e-app/pom.xml": "",
        f"{kok}/testler/SepetTesti.java": "",
        f"{kok}/testler/GirisTesti.java": "",
        f"{kok}/birim/KimliklerTest.java": "",
        f"{kok}/uretilen/TPD1AndroidC2_3f9b1c2eTest.java": "",
    }
    a = _algila(depo, "android")
    assert a.sayilar == {"java": 2} and a.kaynak == "algilandi"


def test_algila_dotnet_monorepo_okuma_butcesi_test_dizini_once() -> None:
    """QA-Y1: 25 projeli .NET monorepo + `tests/E2E/E2E.csproj`: bütçe src/* projelerine
    harcanmaz (yalnız altında test dosyası olan proje okunur, test adlı dizin önce); Python'un
    bütçesi ayrıdır."""
    depo: dict[str, str] = {}
    for i in range(25):
        depo[f"src/Modul{i:02d}/Modul{i:02d}.csproj"] = "<Project/>"
        depo[f"src/Modul{i:02d}/Servis.cs"] = ""
    for i in range(3):  # birim test projeleri (Playwright'sız): sayılmaz
        depo[f"src/Modul{i:02d}.Tests/Modul{i:02d}.Tests.csproj"] = "<Project/>"
        depo[f"src/Modul{i:02d}.Tests/ServisTests.cs"] = ""
    depo["tests/E2E/E2E.csproj"] = '<PackageReference Include="Microsoft.Playwright.NUnit" />'
    depo.update({f"tests/E2E/Akis{i}Tests.cs": "" for i in range(4)})
    depo["ui/pyproject.toml"] = "dependencies = ['pytest-playwright']"
    depo["ui/tests/test_sepet.py"] = ""
    f = SayanForge(depo)
    a = dil_algila.algila(f, "main", "web", uygulama_koku="")
    assert a.sayilar["csharp"] == 4 and a.dil == "csharp"
    assert a.sayilar["python"] == 1
    assert "tests/E2E/E2E.csproj" in f.okunan
    # Altında test dosyası olmayan 25 src/* projesi hiç okunmaz.
    assert not any(y.startswith("src/Modul") and ".Tests" not in y for y in f.okunan)


def test_algila_butce_dil_basina() -> None:
    depo: dict[str, str] = {}
    for i in range(dil_algila.MAX_ISARET_OKUMA + 5):
        depo[f"t{i:02d}/T{i:02d}.csproj"] = "<Project/>"
        depo[f"t{i:02d}/BirTests.cs"] = ""
    depo["e2e-py/pyproject.toml"] = "pytest-playwright"
    depo["e2e-py/tests/test_a.py"] = ""
    f = SayanForge(depo)
    a = dil_algila.algila(f, "main", "web", uygulama_koku="")
    assert sum(y.endswith(".csproj") for y in f.okunan) == dil_algila.MAX_ISARET_OKUMA
    assert a.sayilar["python"] == 1  # C# bütçeyi tüketti; Python'un kendi bütçesi var


def test_algila_kok_pyproject_zayif_isaret() -> None:
    """QA-O1: kökte `pytest-playwright` dev bağımlılığı + 30 api birim testi + 1 TS spec → ts."""
    depo = {
        "pyproject.toml": "[dependency-groups]\ndev = ['pytest-playwright']\n",
        "e2e/package.json": "{}",
        "e2e/tests/a.spec.ts": "",
        **{f"api/tests/test_unit{i}.py": "def test_x():\n    assert 1\n" for i in range(30)},
    }
    a = _algila(depo)
    assert a.sayilar["python"] == 0 and a.dil == "ts"
    # Test dosyasının kendisi Playwright kullanıyorsa sayılır.
    depo["ui/test_sepet.py"] = "from playwright.sync_api import Page\ndef test_s(page: Page): ...\n"
    dil_algila.onbellegi_temizle()
    assert _algila(depo).sayilar["python"] == 1
    # Kökteki conftest.py Playwright fikstürü tanımlıyorsa güçlü işarettir.
    depo["conftest.py"] = "import pytest\nfrom playwright.sync_api import Page\n"
    dil_algila.onbellegi_temizle()
    assert _algila(depo).sayilar["python"] == 31


def test_algila_spring_boot_kok_pom_birim_testleri_sayilmaz() -> None:
    """QA-Y1 tur 2 (a): kök pom'da (test kapsamlı) Playwright bağımlılığı + 200 servis birim testi
    + 30 TS spec → Java seçilmez (birim testleri Playwright içe aktarmaz); okuma bütçe içinde."""
    depo: dict[str, str] = {
        "pom.xml": PW_POM.replace(
            "</dependencies>",
            "<dependency><groupId>org.springframework.boot</groupId></dependency></dependencies>",
        ),
        "e2e/package.json": "{}",
        **{f"e2e/tests/s{i}.spec.ts": "" for i in range(30)},
    }
    for i in range(200):
        paket = f"src/test/java/com/sirket/servis/m{i % 8}"
        depo[f"{paket}/Servis{i}Test.java"] = "import org.junit.jupiter.api.Test;\nclass S {}\n"
    f = SayanForge(depo)
    a = dil_algila.algila(f, "main", "web", uygulama_koku="")
    assert a.sayilar["java"] == 0 and a.dil == "ts" and a.sayilar["ts"] == 30
    assert len(f.okunan) <= dil_algila.MAX_ISARET_OKUMA


def test_algila_ust_pom_yalniz_surum_ozelligi_modul_isaretlemez() -> None:
    """QA-Y1 tur 2 (b): üst pom'da yalnız `<playwright.version>` (ve sürüm yönetimi); `order-svc`
    80 birim testi + `ui-tests` 5 Playwright testi → yalnız ui-tests sayılır."""
    depo: dict[str, str] = {
        "pom.xml": (
            "<project><properties><playwright.version>1.49.0</playwright.version></properties>"
            "<dependencyManagement><dependencies><dependency>"
            "<groupId>com.microsoft.playwright</groupId><artifactId>playwright</artifactId>"
            "<version>${playwright.version}</version></dependency></dependencies>"
            "</dependencyManagement><modules><module>order-svc</module>"
            "<module>ui-tests</module></modules></project>"
        ),
        "order-svc/pom.xml": "<project><dependencies><dependency><groupId>org.junit"
        "</groupId></dependency></dependencies></project>",
        "ui-tests/pom.xml": PW_POM,
    }
    for i in range(80):
        depo[f"order-svc/src/test/java/com/x/order/Siparis{i}Test.java"] = "import org.junit.*;\n"
    for i in range(5):
        depo[f"ui-tests/src/test/java/com/x/ui/Akis{i}Test.java"] = PW_JAVA
    # Soyut taban sınıf (QA-Y7): adla ve (dizinde okunan dosyada) `abstract class` ile sayılmaz.
    depo["ui-tests/src/test/java/com/x/ui/BaseUiTest.java"] = PW_JAVA
    depo["ui-tests/src/test/java/com/x/ui/AbstractAkisTest.java"] = PW_JAVA
    depo["ui-tests/src/test/java/com/x/ortak/OrtakTest.java"] = (
        "import com.microsoft.playwright.Page;\npublic abstract class OrtakTest {}\n"
    )
    a = _algila(depo)
    assert a.sayilar["java"] == 5 and a.dil == "java"


def test_algila_soyut_taban_siniflar_sayilmaz() -> None:
    """QA-Y7: e2e-java'da ve C#'ta taban sınıf adları test sayılmaz."""
    kok = "e2e-java/src/test/java/com/antreklabs/bayi/testler"
    depo = {
        "e2e-java/pom.xml": "",
        f"{kok}/SepetTest.java": "",
        f"{kok}/BaseTest.java": "",
        f"{kok}/AbstractWebTest.java": "",
        f"{kok}/WebBaseTest.java": "",
        f"{kok}/BasketTest.java": "",  # `Base` ön eki değil
        f"{kok}/DatabaseTest.java": "",
        "E2E/E2E.csproj": "Microsoft.Playwright",
        "E2E/SepetTests.cs": "",
        "E2E/BaseTests.cs": "",
        "E2E/PageTestBase.cs": "",
    }
    a = _algila(depo)
    assert (a.sayilar["java"], a.sayilar["csharp"]) == (3, 1)


def test_algila_python_page_int_parametresi_isaret_degil() -> None:
    """QA-Y2 tur 2 (c): kökte `pytest-playwright`, `api/tests/test_list*.py` içinde
    `def fetch(page: int = 1)` + 10 TS spec → TS; yalnız `playwright` içe aktarımı ya da
    `page: Page` sayılır."""
    depo: dict[str, str] = {
        "pyproject.toml": "[dependency-groups]\ndev = ['pytest-playwright']\n",
        "e2e/package.json": "{}",
        **{f"e2e/tests/s{i}.spec.ts": "" for i in range(10)},
        **{
            f"api/tests/test_list{i}.py": (
                "# playwright gerekmez\ndef fetch(page: int = 1):\n    return page\n"
            )
            for i in range(15)
        },
    }
    a = _algila(depo)
    assert a.sayilar["python"] == 0 and a.dil == "ts"
    depo["ui/test_a.py"] = "import playwright.sync_api as pw\n"
    depo["ui/test_b.py"] = "def test_b(page: Page) -> None: ...\n"
    depo["ui/test_c.py"] = "def test_c(page: 'sync_api.Page') -> None: ...\n"  # işaret değil
    dil_algila.onbellegi_temizle()
    assert _algila(depo).sayilar["python"] == 2


def test_algila_izlenmeyen_dizinler() -> None:
    depo = {
        "E2E/E2E.csproj": "Microsoft.Playwright",
        "E2E/SepetTests.cs": "",
        "E2E/bin/Debug/KopyaTests.cs": "",
        "node_modules/x/pyproject.toml": "playwright",
        "node_modules/x/test_y.py": "",
    }
    a = _algila(depo)
    assert (a.sayilar["csharp"], a.sayilar["python"]) == (1, 0)


class DepoluForge(SahteForge):
    """`repo` kimliği taşıyan sahte forge (GitHubForge gibi; önbellek anahtarı)."""

    repo = "org/depo"

    def __init__(self, dosyalar: dict[str, str], **kw: Any) -> None:
        super().__init__(dosyalar, **kw)
        self.head_cagri = 0

    def head_sha(self, ref: str = "main") -> str:
        self.head_cagri += 1
        return super().head_sha(ref)


def test_head_sha_60_sn_onbellek_ve_hata_onbellegi(monkeypatch: pytest.MonkeyPatch) -> None:
    """GÜV-D2: dal → sha 60 sn önbellekli (forge her istekte okunmaz); başarısız algılama kısa
    süre önbellekli; sonuç `hata` taşır."""
    saat = {"t": 1000.0}
    monkeypatch.setattr(dil_algila, "_simdi", lambda: saat["t"])
    f = DepoluForge(_depo())
    for _ in range(3):
        dil_algila.algila(DepoluForge(_depo()), "main", "web", uygulama_koku="")
    f = DepoluForge(_depo())
    dil_algila.algila(f, "main", "web", uygulama_koku="")
    assert f.head_cagri == 0  # yeni nesne, aynı depo: önbellekten
    saat["t"] += dil_algila.HEAD_TTL_S + 1
    dil_algila.algila(f, "main", "web", uygulama_koku="")
    assert f.head_cagri == 1

    dil_algila.onbellegi_temizle()
    bozuk = DepoluForge({}, hata=RuntimeError("hız sınırı"))
    a = dil_algila.algila(bozuk, "main", "web", uygulama_koku="")
    assert a.kaynak == "varsayilan" and a.hata and a.projeler == {}
    dil_algila.algila(bozuk, "main", "web", uygulama_koku="")
    assert bozuk.head_cagri == 1  # hata önbellekte
    saat["t"] += dil_algila.HATA_TTL_S + 1
    dil_algila.algila(bozuk, "main", "web", uygulama_koku="")
    assert bozuk.head_cagri == 2


# --------------------------------------------- K-T3 / MİM-L7: dil seçenekleri, GitHub kipi


def _github_kipi(monkeypatch: pytest.MonkeyPatch, web_dilleri: str | None) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(forge="github"))
    if web_dilleri is None:
        monkeypatch.delenv("TP_WEB_DILLERI", raising=False)
    else:
        monkeypatch.setenv("TP_WEB_DILLERI", web_dilleri)
    monkeypatch.setenv("TP_FORGE_APP_ROOT", "demo-app")


def _projeli_algilama() -> dil_algila.Algilama:
    return dil_algila.Algilama(
        "java", "algilandi", {"ts": 1, "java": 5, "csharp": 0, "python": 0},
        {"ts": True, "java": True},
    )  # fmt: skip


def test_github_kipinde_java_tp_web_dillerine_bagli(monkeypatch: pytest.MonkeyPatch) -> None:
    _github_kipi(monkeypatch, None)
    monkeypatch.setattr(service, "_algila", lambda _p: _projeli_algilama())
    d = service.dil_secenekleri("web")
    java = next(x for x in d["secenekler"] if x["dil"] == "java")
    assert java["kullanilabilir"] is False and "TP_WEB_DILLERI" in java["neden"]
    # Algılanan dil üretilemiyorsa öneri varsayılana düşer.
    assert (d["algilanan"], d["kaynak"]) == ("ts", "varsayilan")
    with pytest.raises(service.GecersizDil, match="TP_WEB_DILLERI") as exc:
        service.dil_coz("web", "java")
    assert exc.value.status_code == 422
    assert service.dil_coz("web", None) == ("ts", "varsayilan")

    _github_kipi(monkeypatch, "ts,java")
    d = service.dil_secenekleri("web")
    assert next(x for x in d["secenekler"] if x["dil"] == "java")["kullanilabilir"] is True
    assert service.dil_coz("web", "java") == ("java", "secildi")

    _github_kipi(monkeypatch, "go")
    with pytest.raises(service.GecersizDil, match="Yapılandırma hatası"):
        service.dil_coz("web", "java")
    # Uygulama platformu ve doğrulanmamış diller TP_WEB_DILLERI'ne bağlı değildir.
    assert service.dil_coz("web", "csharp") == ("csharp", "secildi")


def test_depo_okunamazsa_secenekler_bilinmiyor(monkeypatch: pytest.MonkeyPatch) -> None:
    """MİM-L7: forge kurulamaz/okunamazsa seçenekler engellenmez ama neden dürüstçe yazılır."""

    def kurulamaz() -> Any:
        raise RuntimeError("GITHUB_READ_TOKEN yok")

    from types import SimpleNamespace

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(forge="local"))
    monkeypatch.setattr(service, "_forge", kurulamaz)
    d = service.dil_secenekleri("web")
    assert d["kaynak"] == "varsayilan" and "Dil algılanamadı" in d["neden"]
    assert all(x["kullanilabilir"] for x in d["secenekler"])
    assert all(x["neden"] == service.DEPO_OKUNAMADI for x in d["secenekler"])


def test_ajan_tablo_dili_k_t5(monkeypatch: pytest.MonkeyPatch) -> None:
    """K-T5: web + Java tablosunda canlı ajana repoda TS projesi varsa TS tablosu; REPLAY'de ve
    TS projesi yokken denetim tablosu; uygulama ve TS yolu değişmez."""
    f = SahteForge({**_depo(), "e2e-java/pom.xml": ""})
    monkeypatch.setattr(service, "beklenen_uretim_modu", lambda: "live")
    monkeypatch.setenv("TP_FORGE_APP_ROOT", "")
    sha = "a" * 40
    assert service._ajan_tablo_dili(f, sha, "web", "java") == "ts"
    assert service._ajan_tablo_dili(f, sha, "web", "ts") == "ts"
    assert service._ajan_tablo_dili(f, sha, "android", "java") == "java"
    yalniz_java = SahteForge({"e2e-java/pom.xml": ""})
    dil_algila.onbellegi_temizle()
    assert service._ajan_tablo_dili(yalniz_java, "b" * 40, "web", "java") == "java"
    monkeypatch.setattr(service, "beklenen_uretim_modu", lambda: "replay")
    assert service._ajan_tablo_dili(f, sha, "web", "java") == "java"


def test_code_languages_yalniz_engineer_ve_presenter(
    api: TestClient, codegen: Any, make_user: Any
) -> None:
    """K-T8 / GÜV-D2: `GET /code/languages` forge okur; yalnız engineer | presenter."""
    from .conftest import login

    for rol, beklenen in (("analyst", 403), ("po", 403), ("presenter", 200), ("engineer", 200)):
        login(api, make_user(rol))
        assert api.get("/code/languages").status_code == beklenen, rol


# ---------------------------------------------------- dil çakışması ve görünüm (birim)


def test_dil_cakismasi_yalniz_tam_hat_ve_baska_dilde_merged() -> None:
    from types import SimpleNamespace

    ts_merged = (SimpleNamespace(durum="merged", dil="ts"), None)
    java_acik = (SimpleNamespace(durum="pr_open", dil="java"), None)
    neden = service.dil_cakismasi([ts_merged], "web", "java")
    assert neden == (
        "Bu case'in web testi TypeScript ile merge edildi; dil değiştirmek için önce mevcut "
        "testi kaldırın: mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin"
    )  # K-T12: çıkış yolu mesajda
    assert service.dil_cakismasi([ts_merged], "web", "ts") is None
    assert service.dil_cakismasi([ts_merged], "web", "csharp") is None
    assert service.dil_cakismasi([java_acik], "web", "ts") is None


def test_views_web_java_kendi_checkini_bekler_ve_adim_listesi_tek_kaynak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MİM-L1 / K-T1: portal kapısı script'in check adını `platform.check_adi`'dan alır (web +
    Java → `local-ci-web-java` kaydı yoksa "queued" olarak kapıya verilir)."""
    from tp_core.features.codegen import classify, views

    goren: dict[str, list[str]] = {}

    def kapi(conf: Any, kosular: Any, degisen: Any, *_: Any) -> tuple[tuple[str, ...], None]:
        goren[str(len(goren))] = [k.name for k in kosular]
        return tuple(conf), None

    monkeypatch.setattr(views, "local_required_checks", kapi)
    monkeypatch.setattr(views, "required_checks", lambda: ("local-ci",))
    views.yerel_zorunlu_checkler([], ["e2e-java/x/YTest.java"], "web", "java")
    views.yerel_zorunlu_checkler([], ["e2e/tests/a.spec.ts"], "web", "ts")
    views.yerel_zorunlu_checkler([], ["e2e-app/x/YTest.java"], "android", None)
    assert goren == {"0": ["local-ci-web-java"], "1": [], "2": ["local-ci-android"]}
    assert views.KONTROL_ADIMLARI is classify.GORUNEN_ADIMLAR
    assert views.KONTROL_ADIMLARI["java"] == classify.JAVA_ADIMLARI
    assert views.KONTROL_ADIMLARI["ts"] == ("tsc", "eslint", "ast_guard")


def test_enum_kumeleri_platform_modulu_ile_ayni() -> None:
    """MİM-L1: veri modeli CHECK kümeleri (`models.enums`) `platform.py` tek kaynağıyla aynı."""
    from tp_core.models import enums

    assert frozenset(p.PLATFORMLAR) == enums.PLATFORM
    assert frozenset(p.DILLER) == enums.DIL
