"""009 mobil-masaüstü (Ş6): platform boyutu — Java şablonu, ajan aracı (app-mcp), kontroller, akış.

- `java` süzgeci ve `appium_testng.java.j2` golden'ı; üretilen dosya gerçek `java-araclar guard`
  (JavaParser izin listesi) ile denetlenir (jar yoksa atlanır: `toolchain/java-araclar/mvnw -q -B
  package -DskipTests`).
- `AgentApp`: izin listesi, ilk çağrı `app_launch`, platform kilidi, model dışı `app_screenshot`,
  `[password]` maskesi, ajan bayisi.
- Kimlik çapraz kontrolü (`app_generate_locator` ↔ Kimlikler testId).
- Uçtan uca REPLAY: `POST /code/generate {platform: android}` → `verify_and_map_app` golden'ı
  sahte app-mcp'de yeniden yürütülür → Java şablonu → `/check platform=android` → PR; aynı case'in
  web script'i etkilenmez.

Golden güncelleme: `TP_UPDATE_GOLDEN=1 uv run pytest tests/unit/features/codegen/test_platform.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.codegen.app_fakes import PNG, FakeAppSession
from tests.unit.features.codegen.conftest import (
    RULES,
    TOOLCHAIN,
    FakeToolchain,
    git,
    golden_cases,
)
from tp_core.audit import content_hash
from tp_core.config import get_settings
from tp_core.features.codegen import checks, render, service
from tp_core.features.codegen.browser import (
    AgentApp,
    AgentConfig,
    BrowserError,
    allowed_tools,
    mask_args_with,
)
from tp_core.features.codegen.checks import SymbolTable
from tp_core.features.codegen.render import RenderError, RenderInput
from tp_core.features.codegen.toolchain import ToolchainClient, clear_symbol_cache
from tp_core.gateway import ALLOWED_AGENT_TOOLS, FORBIDDEN_TOOLS
from tp_core.gateway.snapshot_refs import app_locator
from tp_core.models import AiCall, Script, StepMapping, session_scope
from tp_core.models.codegen_feature import ScriptAdim, ScriptCodegen

from .conftest import run_jobs

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
E2E_APP = REPO / "demo-app" / "e2e-app"
JAR = REPO / "toolchain" / "java-araclar" / "target" / "java-araclar.jar"
GOLDEN = HERE / "golden"
JAVA_SYMBOLS = json.loads((HERE / "symbols-java.json").read_text(encoding="utf-8"))
APP_GOLDEN = json.loads(
    (RULES / "replay/verify_and_map_app/golden/TPD-1-C2-android.json").read_text("utf-8")
)
CASE_ID = uuid.UUID("3f9b1c2e-0000-5000-8000-0000000000c2")
DEALERS = {
    "bayi1": {"password": "Demo123!", "name": "Merkez Bayi"},
    "bayi2": {"password": "Demo123!", "name": "Sahil Bayi"},
}


def _girdi(**over: Any) -> RenderInput:
    case = over.pop("case", golden_cases()[1])
    alanlar: dict[str, Any] = {
        "case_id": CASE_ID,
        "case": case,
        "sira_no": 2,
        "story_key": "TPD-1",
        "test_key": "TPD-12",
        "case_hash": content_hash(case),
        "mode": "replay",
        "bundle_hash": "b" * 64,
        "mapping": over.pop("mapping", APP_GOLDEN["output"]),
        "dealers": DEALERS,
        "e2e_root": "e2e-app",
    }
    alanlar.update(over)
    return RenderInput(**alanlar)


# ------------------------------------------------------------------------ java süzgeci


@pytest.mark.parametrize(
    ("deger", "beklenen"),
    [
        ("150,00 TL", '"150,00 TL"'),
        ('a"b\\c', '"a\\"b\\\\c"'),
        ("satır\nalt\tsekme\r", '"satır\\nalt\\tsekme\\r"'),
        ("Çğıöşü İ €", '"Çğıöşü İ €"'),  # ASCII dışı ham UTF-8 (\uXXXX kaçışı yok)
        ("\\u0022", '"\\\\u0022"'),  # metindeki ters bölü çiftlenir: kaçış oluşmaz
        (7, "7"),
        (-3, "-3"),
        (2**31 - 1, "2147483647"),
        (2**31, "2147483648L"),
        (-(2**63), "-9223372036854775808L"),
        (1.5, "1.5"),
        (1e20, "1e+20"),
        (True, "true"),
        (False, "false"),
    ],
)
def test_java_literal(deger: Any, beklenen: str) -> None:
    assert render.java_literal(deger) == beklenen


@pytest.mark.parametrize(
    "deger",
    ["\x00", "a\x1bb", "‮", "​", " ", "", float("nan"), float("inf"), 2**63,
     None, [1], {"a": 1}],
)  # fmt: skip
def test_java_literal_reddeder(deger: Any) -> None:
    with pytest.raises(RenderError):
        render.java_literal(deger)


def test_java_sinif_adi_ve_yol() -> None:
    assert render.java_class_name("TPD-1", "android", 3, CASE_ID) == "TPD1AndroidC3_3f9b1c2eTest"
    assert render.java_class_name(None, "ios", 1, CASE_ID) == "SerbestIosC1_3f9b1c2eTest"
    assert render.java_class_name("bozuk anahtar", "windows", 2, CASE_ID).startswith(
        "SerbestWindowsC2_"
    )
    assert render.java_repo_path("demo-app/e2e-app", "TPD-1", "android", 3, CASE_ID) == (
        "demo-app/e2e-app/src/test/java/com/antreklabs/bayi/uretilen/TPD1AndroidC3_3f9b1c2eTest.java"
    )
    # Aynı case'in platformları ayrı dosya (dal/PR merge'de çakışmaz).
    yollar = {render.java_repo_path("e2e-app", "TPD-1", p, 3, CASE_ID) for p in
              ("android", "ios", "windows")}  # fmt: skip
    assert len(yollar) == 3


def test_java_bayileri_bayiler_java_dan() -> None:
    kaynak = (E2E_APP / "src/test/java/com/antreklabs/bayi/altyapi/Bayiler.java").read_text("utf-8")
    assert render.parse_java_dealers(kaynak) == DEALERS


# ------------------------------------------------------------------------ Java şablonu


def test_java_golden_cikti() -> None:
    r = render.render_java_test(_girdi(), "android", RULES)
    hedef = GOLDEN / "TPD1AndroidC2_3f9b1c2eTest.java"
    if os.environ.get("TP_UPDATE_GOLDEN") == "1":
        hedef.write_text(r.content, encoding="utf-8")
    assert r.content == hedef.read_text(encoding="utf-8")
    assert r.repo_path == (
        "e2e-app/src/test/java/com/antreklabs/bayi/uretilen/TPD1AndroidC2_3f9b1c2eTest.java"
    )
    assert r.test_file == (
        "src/test/java/com/antreklabs/bayi/uretilen/TPD1AndroidC2_3f9b1c2eTest.java"
    )
    assert r.dealer == "bayi1"
    k = r.content
    # §2.8 biçimi: başlık gerçek değerlerle, üç izinli import, @Bayi, tek @Test, yalnız çağrılar.
    assert k.startswith("// AI-generated — AI Testing Probe (CasesToCode).")
    assert f"// Case: TPD-1 C2 ({CASE_ID}) · Story: TPD-1 · Jira Test: TPD-12" in k
    assert f"// Onaylı case hash: {content_hash(golden_cases()[1])}" in k
    assert "// Eşleme: verify_and_map_app · platform: android · mod: replay · bundle: " in k
    assert '@Bayi("bayi1")\npublic class TPD1AndroidC2_3f9b1c2eTest extends TestTabani {' in k
    assert (
        f'@Test(groups = {{"uretilen", "android", "tp-case-{CASE_ID}", "TPD-1"}}, '
        'description = "7 adet kampanyalı üründe 1 adet bedava verilir")'
    ) in k
    assert '    girisEkrani().girisYap("bayi1", "Demo123!");' in k
    assert '    katalogEkrani().sepeteEkle("P-001", 7);' in k
    assert '    sepetEkrani().dogrulaToplam("150,00 TL");' in k
    assert "\\u" not in k


def test_java_cikti_deterministik_ve_platforma_gore() -> None:
    a = render.render_java_test(_girdi(), "android", RULES)
    assert a == render.render_java_test(_girdi(), "android", RULES)
    b = render.render_java_test(_girdi(), "ios", RULES)
    assert b.repo_path != a.repo_path and '"ios"' in b.content and "platform: ios" in b.content


def test_java_sablonu_enjeksiyona_kapali() -> None:
    mapping = json.loads(json.dumps(APP_GOLDEN["output"]))
    mapping["expects"][-1]["args"] = ['"); Runtime.getRuntime().exec("x']
    k = render.render_java_test(_girdi(mapping=mapping), "android", RULES).content
    assert 'dogrulaToplam("\\"); Runtime.getRuntime().exec(\\"x");' in k
    case = dict(golden_cases()[1])
    case["title"] = 'baş"lık */ ‮'
    with pytest.raises(RenderError):
        render.render_java_test(_girdi(case=case), "android", RULES)
    kotu = json.loads(json.dumps(APP_GOLDEN["output"]))
    kotu["expects"][0]["method"] = "dogrula(); x"
    with pytest.raises(RenderError):
        render.render_java_test(_girdi(mapping=kotu), "android", RULES)


def _java_guard(dosya_adi: str, icerik: str, tmp_path: Path) -> dict[str, Any]:
    kok = tmp_path / "e2e-app"
    shutil.copytree(E2E_APP, kok, ignore=shutil.ignore_patterns("target", ".mvn"))
    hedef = kok / "src/test/java/com/antreklabs/bayi/uretilen" / dosya_adi
    hedef.write_text(icerik, encoding="utf-8")
    sonuc = subprocess.run(
        ["java", "-jar", str(JAR), "guard", "--root", str(kok), "--kimlikler", "--",
         str(hedef.relative_to(kok))],
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert sonuc.returncode in (0, 1), sonuc.stderr
    return json.loads(sonuc.stdout)


@pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None,
    reason="java-araclar.jar yok (toolchain/java-araclar/mvnw -q -B package -DskipTests)",
)
@pytest.mark.parametrize("platform", ["android", "ios", "windows"])
def test_uretilen_java_gercek_guard_dan_gecer(platform: str, tmp_path: Path) -> None:
    mapping = json.loads(json.dumps(APP_GOLDEN["output"]))
    # Kenar değerler: ASCII dışı, tırnak, ters bölü, satır sonu — hepsi geçerli literal olmalı.
    mapping["expects"].append(
        {"po": "SepetEkrani", "method": "dogrulaMinimumSiparisUyarisi",
         "args": ['Minimum "sipariş" tutarı: 750,00 TL\\yeni\nsatır — ğüşİ']}
    )  # fmt: skip
    r = render.render_java_test(_girdi(mapping=mapping), platform, RULES)
    rapor = _java_guard(Path(r.test_file).name, r.content, tmp_path)
    assert rapor["ok"], rapor["violations"]


@pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None, reason="java-araclar.jar yok"
)
def test_guard_bozuk_ciktiyi_yakalar(tmp_path: Path) -> None:
    """Kontrol: guard gerçekten koşuyor (şablon dışı içerik reddedilir)."""
    r = render.render_java_test(_girdi(), "android", RULES)
    bozuk = r.content.replace("girisEkrani().ac();", "girisEkrani().ac(); Thread.sleep(5);")
    rapor = _java_guard(Path(r.test_file).name, bozuk, tmp_path)
    assert not rapor["ok"]


# ------------------------------------------------------------------- tür kontrolü (Java)


@pytest.mark.parametrize(
    ("tip", "deger", "beklenen"),
    [
        ("String", "a", True),
        ("String", 1, False),
        ("int", 7, True),
        ("int", 2**31, False),
        ("int", 7.0, False),
        ("int", True, False),
        ("long", 2**40, True),
        ("long", 2**63, False),
        ("double", 7, True),
        ("double", 7.5, True),
        ("double", float("inf"), False),
        ("double", "7", False),
        ("boolean", True, True),
        ("boolean", 1, False),
        ("char", "a", None),
        ("string", "a", True),  # TS türleri değişmedi
        ("number", 7.5, True),
    ],
)
def test_tur_uyar_java(tip: str, deger: Any, beklenen: bool | None) -> None:
    assert checks._tur_uyar(tip, deger) is beklenen


def test_java_eslemesi_sembol_tablosundan_gecer() -> None:
    tablo = SymbolTable(JAVA_SYMBOLS)
    s = checks.check_mapping(
        APP_GOLDEN["output"], golden_cases()[1], tablo, fixtures=set(JAVA_SYMBOLS["fixtures"])
    )
    assert s.ok, s.ozet()
    kotu = json.loads(json.dumps(APP_GOLDEN["output"]))
    kotu["step_mapping"][2]["args"] = ["P-001", "7"]  # int parametreye metin
    s = checks.check_mapping(kotu, golden_cases()[1], tablo)
    assert not s.ok and "tür uyumsuz" in s.ozet()


# -------------------------------------------------------------------- AgentApp (app-mcp)


def test_gateway_izin_listesi_ve_yasak_arac() -> None:
    assert ALLOWED_AGENT_TOOLS["verify_and_map_app"] == frozenset(
        {"app_launch", "app_snapshot", "app_click", "app_type", "app_select_option",
         "app_wait_for", "app_generate_locator"}
    )  # fmt: skip
    assert "app_screenshot" in FORBIDDEN_TOOLS
    assert allowed_tools("verify_and_map_app") == ALLOWED_AGENT_TOOLS["verify_and_map_app"]


def _ajan(**kw: Any) -> tuple[AgentApp, FakeAppSession, dict[int, bytes]]:
    oturum = FakeAppSession(kw.pop("platform_oturum", "android"))
    ekranlar: dict[int, bytes] = {}

    def sink(n: int, png: bytes) -> str:
        ekranlar[n] = png
        return f"codegen/x/step-{n}.png"

    ajan = AgentApp(
        oturum,
        platform=kw.pop("platform", "android"),
        config=AgentConfig(),
        case_dealers=["bayi1", "bayi2"],
        screenshot_sink=sink,
        **kw,
    )
    return ajan, oturum, ekranlar


def test_agent_app_arac_listesi_ekran_goruntusu_vermez() -> None:
    ajan, _, _ = _ajan()
    adlar = {t.name for t in ajan.tool_specs()}
    assert adlar == ALLOWED_AGENT_TOOLS["verify_and_map_app"]
    assert "app_screenshot" not in adlar


def test_agent_app_ilk_cagri_app_launch_ve_platform_kilidi() -> None:
    ajan, oturum, _ = _ajan()
    with pytest.raises(BrowserError, match="app_launch"):
        ajan("app_snapshot", {})
    with pytest.raises(BrowserError, match="platform"):
        ajan("app_launch", {"platform": "ios"})
    with pytest.raises(BrowserError, match="izinli değil"):
        ajan("app_screenshot", {})
    assert not any(n != "app_screenshot" for n, _ in oturum.calls)
    sonuc = ajan("app_launch", {"platform": "android", "reset": True})
    assert '<untrusted kind="snapshot"' in sonuc and "login-username" in sonuc
    with pytest.raises(BrowserError):
        AgentApp(oturum, platform="web")


def test_agent_app_model_disi_canli_gorunum_ve_parola_maskesi() -> None:
    ajan, oturum, ekranlar = _ajan()
    ajan("app_launch", {"platform": "android"})
    ajan.pop_screenshot()
    # Parola alanı `element` açıklamasız da (snapshot'taki `[password]`) gizlenir.
    ajan("app_type", {"ref": "e6", "text": "bayi1"})
    sonuc = ajan("app_type", {"ref": "e8", "text": "Demo123!"})
    assert "Demo123!" not in sonuc
    yazilan = [a["text"] for n, a in oturum.calls if n == "app_type"]
    assert yazilan == ["bayi3", "Demo123!"]  # e2e bayisi → ajan bayisi; gerçek parola
    assert ajan.yerine_gecenler == {"bayi1": "bayi3"}
    assert mask_args_with({"ref": "e8", "text": "Demo123!"}, ajan.gizliler)["text"] == "***"
    # Her eylemden sonra görüntü model döngüsünün dışında alındı; sonuç metnine girmedi.
    assert ekranlar and all(v == PNG for v in ekranlar.values())
    assert sum(1 for n, _ in oturum.calls if n == "app_screenshot") == 3
    assert "PNG" not in sonuc


def test_agent_app_arac_hatasi_yapilandirilmis() -> None:
    ajan, _, _ = _ajan()
    ajan("app_launch", {"platform": "android"})
    with pytest.raises(Exception, match="son snapshot"):
        ajan("app_click", {"ref": "e99"})
    sonuc = ajan.pop_sonuc()
    assert sonuc is not None and not sonuc.ok


# ---------------------------------------------------------------- kimlik çapraz kontrolü


def _loc(kimlik: str | None, platform: str = "android") -> str:
    strat = "id" if platform == "android" else "accessibilityId"
    return "### Locator\n" + json.dumps({"platform": platform, "strategy": strat, "id": kimlik})


def test_app_locator_ayristirma() -> None:
    assert app_locator(_loc("login-submit")) == ("id", "login-submit")
    assert app_locator(_loc(None, "ios")) == ("accessibilityId", None)
    assert app_locator("### Locator\n{bozuk") is None and app_locator(None) is None


def test_app_kimlik_capraz_kontrolu() -> None:
    from tp_core.features.codegen.browser import LocatorHedefi

    tablo = SymbolTable(JAVA_SYMBOLS)
    hedef = LocatorHedefi("e2", True, "textbox", "Kullanıcı adı", None, "login-username")
    iyi = [
        (1, 'textbox "Kullanıcı adı" (Giris.KULLANICI_ADI)', _loc("login-username"), hedef),
        (2, 'P-001 kartında textbox "Adet" (Katalog.ADET_ONEK)', _loc("qty-input-P-001"), None),
        (3, "bilinmeyen ipucu", _loc("cart-total"), None),
    ]
    assert service.app_locator_capraz_kontrol(iyi, tablo, canli=True) == []
    kotu = [
        (1, 'button "Giriş yap" (Giris.GIRIS_YAP)', _loc("login-username"), None),
        (2, 'P-001 kartında textbox "Adet" (Katalog.ADET_ONEK)', _loc("qty-input-P-002"), None),
        (3, "x", _loc(None), None),
        (4, "x", _loc("uydurma-kimlik"), None),
        (5, 'textbox "Kullanıcı adı"', _loc("login-password"), hedef),
        (6, "x", "### Locator\nREPLAY sapması: …", None),
    ]
    uyusmaz = dict(service.app_locator_capraz_kontrol(kotu, tablo, canli=True))
    assert set(uyusmaz) == {1, 2, 3, 4, 5, 6}, uyusmaz
    assert "login-submit" in uyusmaz[1] and "Kimlikler'de yok" in uyusmaz[4]


# ------------------------------------------------------------------ uçtan uca (REPLAY)


@pytest.fixture(scope="session")
def demo_bare_app(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """LocalForge düzeni: `e2e/` + `e2e-app/` (Java test projesi) kökte."""
    kok = tmp_path_factory.mktemp("forge-app-src")
    work = kok / "work"
    shutil.copytree(
        REPO / "demo-app" / "e2e", work / "e2e",
        ignore=shutil.ignore_patterns("node_modules", "results", "*.spec.ts.tmp"),
    )  # fmt: skip
    for f in (work / "e2e" / "tests" / "generated").glob("*.spec.ts"):
        f.unlink()
    shutil.copytree(E2E_APP, work / "e2e-app", ignore=shutil.ignore_patterns("target"))
    git("init", "-q", "-b", "main", str(work))
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "demo-app e2e + e2e-app", cwd=work)
    bare = kok / "demo-app.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("push", "-q", str(bare), "main", cwd=work)
    return bare


def java_gecti(n: int = 3) -> dict[str, Any]:
    return {
        "conclusion": "success",
        "summary": "Yerel CI geçti (Java)",
        "lang": "java",
        "platform": "android",
        "app": {"ok": True},
        "deps": {"ok": True},
        "guard": {"ok": True},
        "compile": {"ok": True},
        "run": {
            "run_id": f"run-{uuid.uuid4().hex[:6]}",
            "status": "passed",
            "saglik": {"ok": True},
            "tests": [{"title": "senaryo", "status": "expected", "error": None}] * n,
        },
        "duration_ms": 4321,
    }


class AppToolchain(FakeToolchain):
    """`/symbols` `platform` ile Java tablosunu, `/check` `platform` ile Java raporunu verir."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path == "/symbols" and body.get("platform"):
            self.istekler.append((request.url.path, body))
            return httpx.Response(200, json={"sha": body["sha"], **JAVA_SYMBOLS})
        if request.url.path == "/check" and body.get("platform") and not self.kontroller:
            self.kontroller.append(java_gecti())
        return super().handler(request)


@pytest.fixture
def app_codegen(
    engine: Engine,
    demo_bare_app: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ci_cagrilari: list[dict[str, Any]],
) -> Any:
    from tp_core.audit import PgCallRecorder
    from tp_core.gateway import build_gateway
    from tp_core.gateway.config import GatewaySettings
    from tp_core.integrations.forge_local import LocalForge

    bare = tmp_path / "forge" / "demo-app.git"
    shutil.copytree(demo_bare_app, bare)
    artifacts = tmp_path / "artifacts"
    (artifacts / "checks").mkdir(parents=True)
    monkeypatch.setenv("TP_ARTIFACTS_PATH", str(artifacts))
    monkeypatch.setenv("TP_FORGE", "local")
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.setenv("TP_AGENT_DEALER", "bayi3")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TP_REPLAY_STRICT", raising=False)
    monkeypatch.delenv("TP_RULES_DIR", raising=False)
    monkeypatch.delenv("TP_FORGE_APP_ROOT", raising=False)
    get_settings.cache_clear()
    clear_symbol_cache()
    gw = build_gateway(PgCallRecorder(engine), settings=GatewaySettings(), engine=engine)
    tc = AppToolchain(artifacts)
    uygulama_oturumlari: list[FakeAppSession] = []

    def app() -> FakeAppSession:
        s = FakeAppSession("android")
        uygulama_oturumlari.append(s)
        return s

    from tests.unit.features.codegen.test_browser import FakeSession

    forge = LocalForge(bare, artifacts)
    service.set_factories(
        gateway=lambda _e: gw,
        browser=FakeSession,
        app=app,
        toolchain=lambda: ToolchainClient(TOOLCHAIN, transport=httpx.MockTransport(tc.handler)),
        forge=lambda: forge,
    )

    class Ortam:
        pass

    o = Ortam()
    o.toolchain, o.forge, o.artifacts, o.oturumlar, o.ci = (
        tc, forge, artifacts, uygulama_oturumlari, ci_cagrilari
    )  # fmt: skip
    yield o
    service.reset_factories()
    clear_symbol_cache()
    get_settings.cache_clear()


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    from .conftest import login

    u = make_user("engineer")
    login(api, u)
    return u


def _uret(api: TestClient, cid: uuid.UUID, platform: str | None) -> dict[str, Any]:
    govde: dict[str, Any] = {"case_ids": [str(cid)]}
    if platform is not None:
        govde["platform"] = platform
    r = api.post("/code/generate", json=govde)
    assert r.status_code == 202, r.text
    return r.json()


def test_android_case_den_java_pr_a(
    api: TestClient,
    db: Any,
    engine: Engine,
    app_codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
) -> None:
    cid = hazir["cases"][2]
    dinle = psycopg.connect(
        db.app_url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    )
    dinle.execute("LISTEN tp_events")
    yanit = _uret(api, cid, "android")
    assert yanit["durum"] == "started" and yanit["platform"] == "android"
    assert yanit["sonuclar"][0]["platform"] == "android"
    sid = yanit["script_ids"][0]
    run_jobs(engine)
    with session_scope() as s:
        sc, cg = s.get(Script, uuid.UUID(sid)), s.get(ScriptCodegen, uuid.UUID(sid))
        assert sc.durum == "pr_open", cg.engel_nedeni
        assert sc.platform == "android" and sc.pass_at_1 is True and cg.uretim_modu == "replay"
        branch = f"tp/case-android-{cid}"
        assert sc.branch == branch
        assert sc.dosya_yolu.startswith(
            "e2e-app/src/test/java/com/antreklabs/bayi/uretilen/TPD1AndroidC2_"
        )
        kod = sc.icerik
        call = s.get(AiCall, uuid.UUID(cg.ai_call_ids[0]))
        assert call.amac == "verify_and_map_app" and call.mod == "replay"
        adimlar = s.scalars(select(ScriptAdim).where(ScriptAdim.script_id == sc.id)).all()
        assert len(adimlar) == len(APP_GOLDEN["steps"]) and all(a.izinli for a in adimlar)
        assert all(a.ekran_goruntusu for a in adimlar)
        parola = next(a for a in adimlar if a.arguman.get("element") == 'textbox "Parola"')
        assert parola.arguman["text"] == "***"
        maps = s.scalars(
            select(StepMapping).where(StepMapping.script_id == sc.id).order_by(StepMapping.adim_no)
        ).all()
        assert [m.po_sinifi for m in maps][:2] == ["GirisEkrani", "GirisEkrani"]
        pr_no, head = sc.pr_no, sc.head_sha
    assert app_codegen.forge.read_file(sc.dosya_yolu, ref=branch) == kod
    assert kod.startswith("// AI-generated") and '@Bayi("bayi1")' in kod
    assert 'sepetEkrani().dogrulaBedavaAdet("P-001", 1);' in kod
    pr = app_codegen.forge.find_open_pr(branch)
    assert pr is not None and pr.number == pr_no
    assert "platform:android" in pr.labels and "· android]" in pr.title
    assert "Model Java yazmadı" in pr.body and "| Platform | android |" in pr.body

    # toolchain: Java sembol tablosu + Java yerel kontrolü (e2e-app köküne göre dosya).
    symbols = [b for p, b in app_codegen.toolchain.istekler if p == "/symbols"]
    assert symbols == [{"sha": app_codegen.forge.head_sha("main"), "platform": "android"}]
    (istek,) = app_codegen.toolchain.checks()
    assert istek["platform"] == "android" and istek["sha"] == head
    assert istek["test_files"] == [sc.dosya_yolu.removeprefix("e2e-app/")]

    # Ajan: app-mcp oturumu, ajan bayisi, model dışı görüntü, oturum kapandı.
    (oturum,) = app_codegen.oturumlar
    assert oturum.closed and oturum.calls[0][0] == "app_launch"
    yazilan = [a.get("text") for n, a in oturum.calls if n == "app_type"]
    assert "bayi3" in yazilan and "bayi1" not in yazilan
    assert any(n == "app_screenshot" for n, _ in oturum.calls)

    # SSE: adım ve PR olayları platformu taşır.
    olaylar = [json.loads(n.payload) for n in dinle.notifies(timeout=0.5, stop_after=500)]
    dinle.close()
    from tp_core.events.bus import parse_payload  # noqa: F401  (biçim aynı)

    adim = next(e for e in olaylar if e.get("event") == "agent.step")
    assert adim["data"]["platform"] == "android"
    acilan = next(e for e in olaylar if e.get("event") == "pr.opened")
    assert acilan["data"]["platform"] == "android"

    # API: liste/detay platformu döner.
    liste = api.get("/scripts").json()
    assert liste[0]["id"] == sid and liste[0]["platform"] == "android"
    assert api.get(f"/scripts/{sid}").json()["platform"] == "android"

    # Aynı case web'de bağımsız üretilir: android PR'ı kapanmaz, dal/dosya çakışmaz.
    web = _uret(api, cid, None)
    assert web["platform"] == "web" and web["durum"] == "started"
    with session_scope() as s:
        web_sc = s.get(Script, uuid.UUID(web["script_ids"][0]))
        assert web_sc.platform == "web" and web_sc.branch == f"tp/case-{cid}"
        assert s.get(Script, uuid.UUID(sid)).durum == "pr_open"
    run_jobs(engine)
    with session_scope() as s:
        web_sc = s.get(Script, uuid.UUID(web["script_ids"][0]))
        assert web_sc.durum == "pr_open" and web_sc.dosya_yolu.endswith(".spec.ts")
        assert s.get(Script, uuid.UUID(sid)).durum == "pr_open"
    web_check = app_codegen.toolchain.checks()[-1]
    assert "platform" not in web_check and web_check["test_files"][0].endswith(".spec.ts")
    tekrar = _uret(api, cid, "android")
    assert tekrar["durum"] == "none" and tekrar["sonuclar"][0]["durum"] == "pr_acik"

    # Kırarak doğrula: platform ve Java dosyası aynen geçer.
    onceki = len(app_codegen.toolchain.checks())
    r = api.post(f"/scripts/{sid}/break-verify")
    assert r.status_code == 202, r.text
    app_codegen.toolchain.kontroller += [java_gecti(1), java_gecti(1)]
    kirik = java_gecti(1)
    kirik.update(conclusion="failure")
    kirik["run"] = {**kirik["run"], "status": "failed", "tests": [{
        "title": "senaryo", "status": "unexpected",
        "error": "java.lang.AssertionError: bedava adet: beklenen <1>, görülen <0> (10000 ms)",
        "failure": {"type": "assertion"},
    }]}  # fmt: skip
    app_codegen.toolchain.kirik.append(kirik)
    run_jobs(engine)
    bv = app_codegen.toolchain.checks()[onceki:]
    assert len(bv) == 3 and all(b["platform"] == "android" for b in bv)
    assert all(b["test_files"] == [sc.dosya_yolu.removeprefix("e2e-app/")] for b in bv)
    assert bv[1]["env"] == {"BREAK_CAMPAIGN": "1"}
    with session_scope() as s:
        assert s.get(ScriptCodegen, uuid.UUID(sid)).break_durum == "passed"


def test_platform_api_dogrulamasi(
    api: TestClient, engine: Engine, app_codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    r = api.post("/code/generate", json={"case_ids": [str(hazir["cases"][2])], "platform": "tv"})
    assert r.status_code == 422


def test_platform_kolonu_ve_kisit(engine: Engine) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from tp_core.models import Base

    with engine.connect() as conn:
        farklar = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    assert [f for f in farklar if "platform" in repr(f)] == []
    with engine.begin() as conn:
        varsayilan = conn.execute(
            text("INSERT INTO script (dosya_yolu) VALUES ('e2e/x.spec.ts') RETURNING platform")
        ).scalar_one()
        assert varsayilan == "web"
    with pytest.raises(Exception, match="script_platform_ck"), engine.begin() as conn:
        conn.execute(text("INSERT INTO script (dosya_yolu, platform) VALUES ('x', 'tv')"))


def test_start_generation_gecersiz_platform(engine: Engine) -> None:
    with session_scope() as s, pytest.raises(service.CodegenRejected, match="platform"):
        service.start_generation(s, [uuid.uuid4()], muhendis_principal(), "tv")


def muhendis_principal() -> Any:
    from tp_core.workflow.service import Principal

    return Principal(uuid.uuid4(), "m", "engineer")


# ------------------------------------------------------------- inceleme bulguları (Ş6)


def test_java_yorumu_unicode_kacisi_ve_gorunmez_karakter_tasimaz(tmp_path: Path) -> None:
    case = json.loads(json.dumps(golden_cases()[1]))
    case["steps"][0]["action"] = "C:\\users\\u0041 klasörü \ufeffgizli\u00ad tire"
    k = render.render_java_test(_girdi(case=case), "android", RULES)
    assert "\\u" not in k.content and "\ufeff" not in k.content and "\u00ad" not in k.content
    assert "// S1 — C:/users/u0041 klasörü gizli tire" in k.content
    if JAR.is_file() and shutil.which("java"):
        rapor = _java_guard(Path(k.test_file).name, k.content, tmp_path)
        assert rapor["ok"], rapor["violations"]


def test_web_hata_siniflari_java_kaliplarindan_etkilenmez() -> None:
    from tp_core.features.codegen.classify import test_error_kind

    msg = "Error: page.click: Connection refused\njava.lang.AssertionError: x"
    assert test_error_kind("AssertionError [ERR_ASSERTION]: 1 == 2") == "bilinmiyor"
    assert test_error_kind(msg) != "ortam"
    java = "java.lang.AssertionError: a: beklenen <1>, görülen <0> (10 ms)"
    assert test_error_kind(java, java=True) == "assertion"


def test_snapshot_adi_kimlik_isaretini_sahteleyemez() -> None:
    from tp_core.features.codegen.browser import locator_hedefi

    satir = '- button "Tıkla [id=login-submit] [password]" [id=gercek-kimlik] [ref=e5]: [id=x]'
    h = locator_hedefi([satir], "e5")
    assert h.kimlik == "gercek-kimlik" and h.parola is False


def test_gateway_parolayi_element_aciklamasi_olmadan_da_siler() -> None:
    from tp_core.gateway.core import executor_secrets

    ajan, _, _ = _ajan()
    ajan("app_launch", {"platform": "android"})
    ajan("app_type", {"ref": "e8", "text": "GizliParola9"})
    assert "GizliParola9" in executor_secrets(ajan)
    assert executor_secrets(object()) == frozenset()


def test_basarisiz_app_launch_kilidi_acmaz() -> None:
    oturum = FakeAppSession("android", hata=lambda n: n == "app_launch")
    ajan = AgentApp(oturum, platform="android", config=AgentConfig())
    with pytest.raises(Exception):  # noqa: B017 — MCP hata sonucu
        ajan("app_launch", {"platform": "android"})
    with pytest.raises(BrowserError, match="app_launch"):
        ajan("app_snapshot", {})


GIZLI_ORTAM = {"Demo123!": "TP_TESTVERI_DEMO_PAROLA"}


def test_java_gizli_test_verisi_ortamdan_okunur() -> None:
    """013 K19: bilinen gizli değer argümanı `System.getenv("<SIR>")`; metinde düz değer yok."""
    case = json.loads(json.dumps(golden_cases()[1]))
    case["title"] = f"{case.get('title')} (Demo123!)"
    r = render.render_java_test(_girdi(case=case, gizli_ortam=GIZLI_ORTAM), "android", RULES)
    assert '    girisEkrani().girisYap("bayi1", System.getenv("TP_TESTVERI_DEMO_PAROLA"));' in (
        r.content
    )
    assert "Demo123!" not in r.content and "•••" in r.content
    # Gizli değer yoksa çıktı golden'la aynı kalır (şablon değişmedi).
    assert (
        render.render_java_test(_girdi(), "android", RULES).content
        == render.render_java_test(_girdi(gizli_ortam={}), "android", RULES).content
    )


@pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None, reason="java-araclar.jar yok"
)
def test_java_gizli_test_verisi_gercek_guard_dan_gecer(tmp_path: Path) -> None:
    r = render.render_java_test(_girdi(gizli_ortam=GIZLI_ORTAM), "android", RULES)
    assert "System.getenv(" in r.content
    rapor = _java_guard(Path(r.test_file).name, r.content, tmp_path)
    assert rapor["ok"], rapor["violations"]
