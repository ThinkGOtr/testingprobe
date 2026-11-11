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
    # Check adı platformundur, dile bakmaz.
    assert p.check_adi("web") == "local-ci"
    assert p.check_adi("ios") == "local-ci-ios"


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
    assert service.baslangic_dosya_yolu("csharp", "web", "TPD-1", 2, cid).startswith(
        "demo-app/e2e-csharp/"
    )
    assert service.baslangic_dosya_yolu("python", "web", "TPD-1", 2, cid).endswith(".py")
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
