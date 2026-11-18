"""014 test dilleri: toolchain dil eklentileri (specs/014-test-dilleri/plan.md §3).

Kayıt (ts + java worker'da, java runner'da), `lang` doğrulaması, sahte eklentiyle /symbols,
/check doğrulaması ve dağıtımı, runner dağıtımı, check adı genellemesi, kök çözümü ve
`ProjeBlogu.dil_kokleri` doğrulaması.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from runner import app as runner_app
from runner import diller as rdiller
from runner import run as runner
from toolchain_common.proje import ProjeBlogu
from worker import app as worker_app
from worker import check as checks
from worker import diller


class SahteDil:
    ad = "python"
    platformlar = ("web", "android", "ios", "windows")
    steps = ("app", "deps", "guard", "compile", "run")
    hat = "tam"

    def __init__(self) -> None:
        self.cagrilar: list[tuple[str, Any]] = []

    def validate_test_file(self, yol: str) -> str:
        if not (yol.startswith("tests/") and yol.endswith(".py")):
            raise ValueError("python test dosyası tests/**.py olmalı")
        return yol

    def symbols(self, cfg: Any, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
        self.cagrilar.append(("symbols", platform))
        return {"page_objects": [{"name": "LoginPage", "methods": []}]}

    def guard(self, cfg: Any, repo: Path, base: str, head: str, mode: str, platform: str) -> dict:
        self.cagrilar.append(("guard", mode))
        return {"ok": True, "violations": []}

    def run_static(self, cfg, req, head, base, runner_client, steps):  # type: ignore[no-untyped-def]
        self.cagrilar.append(("run_static", req.lang, req.platform))
        for ad in self.steps[:-1]:
            steps[ad] = {"ok": True}
        steps["run"] = {"ok": True, "status": "passed", "tests": []}
        return steps


class SahteRunner:
    ad = "python"

    def __init__(self) -> None:
        self.cagrilar: list[Any] = []

    def validate_test_file(self, yol: str) -> str:
        return SahteDil().validate_test_file(yol)

    def execute_locked(self, cfg, req, loc, http):  # type: ignore[no-untyped-def]
        self.cagrilar.append((req.lang, req.platform))
        return {"status": "passed", "lang": req.lang}


@pytest.fixture
def sahte(monkeypatch: pytest.MonkeyPatch) -> SahteDil:
    e = SahteDil()
    monkeypatch.setattr(diller, "_KAYIT", {**diller.kayit(), "python": e})
    return e


@pytest.fixture
def sahte_runner(monkeypatch: pytest.MonkeyPatch) -> SahteRunner:
    e = SahteRunner()
    monkeypatch.setattr(rdiller, "_KAYIT", {**rdiller.kayit(), "python": e})
    return e


# ------------------------------------------------------------------------------- kayıt


def test_kayit_ts_java_worker_java_runner_hatasiz() -> None:
    assert {"ts", "java"} <= set(diller.adlar())
    assert diller.hatalar() == {}
    assert isinstance(diller.eklenti("ts"), diller.WorkerDili)
    assert isinstance(diller.eklenti("java"), diller.WorkerDili)
    assert "java" in rdiller.kayit() and rdiller.hatalar() == {}
    assert rdiller.adlar()[0] == "ts"
    assert isinstance(rdiller.eklenti("java"), rdiller.RunnerDili)


def test_ts_java_eklentileri_bugunku_adimlari_verir() -> None:
    from worker import java as javayol

    assert diller.eklenti("ts").steps == checks.STEPS  # type: ignore[union-attr]
    assert diller.eklenti("java").steps == javayol.STEPS  # type: ignore[union-attr]
    yol = "src/test/java/com/antreklabs/bayi/uretilen/TPD1WebC2_3f9b1c2eTest.java"
    assert diller.eklenti("java").validate_test_file(yol) == yol  # type: ignore[union-attr]
    assert rdiller.eklenti("java").validate_test_file(yol) == yol  # type: ignore[union-attr]


def test_resolve_lang_bilinmeyen_dil_ve_platform_uyumsuzlugu() -> None:
    assert diller.resolve_lang(None, None) == "ts"
    assert diller.resolve_lang(None, "android") == "java"
    with pytest.raises(ValueError, match="lang yalnızca"):
        diller.resolve_lang("cobol", None)
    with pytest.raises(ValueError, match="uyuşmuyor"):
        diller.resolve_lang("ts", "android")  # javayol iletisi korunur


def test_resolve_lang_eklenti_platformlari(sahte: SahteDil, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert diller.resolve_lang("python", "ios") == "python"
    assert diller.resolve_platform("python", None) == "web"
    monkeypatch.setattr(sahte, "platformlar", ("web",))
    with pytest.raises(ValueError, match="uyuşmuyor"):
        diller.resolve_lang("python", "android")


# ---------------------------------------------------------------------------- check adı


def test_check_name_genel(sahte: SahteDil) -> None:
    assert checks.check_name("ts", None) == "local-ci"
    assert checks.check_name("java", None) == "local-ci-web-java"
    assert checks.check_name("java", "ios") == "local-ci-ios"
    assert checks.check_name("python", None) == "local-ci-web-python"
    assert checks.check_name("python", "android") == "local-ci-android-python"
    req = checks.CheckRequest(sha="a" * 40, lang="python", platform="windows")
    assert req.check_name == "local-ci-windows-python"
    assert req.step_names == SahteDil.steps


# ----------------------------------------------------------------------------- kök çözümü


def test_kok_cozum_sirasi(monkeypatch: pytest.MonkeyPatch) -> None:
    ad = "TP_E2E_APP_PYTHON_ROOT"
    monkeypatch.delenv(ad, raising=False)
    monkeypatch.delenv(f"{ad}_ANDROID", raising=False)
    cfg = SimpleNamespace(dil_kokleri=None)
    assert diller.kok(cfg, ad, "e2e-app-python", "android") == "e2e-app-python"  # type: ignore[arg-type]
    monkeypatch.setenv(ad, "demo-app/e2e-app-python")
    assert diller.kok(cfg, ad, "x", "android") == "demo-app/e2e-app-python"  # type: ignore[arg-type]
    monkeypatch.setenv(f"{ad}_ANDROID", "android-tests")
    assert diller.kok(cfg, ad, "x", "android") == "android-tests"  # type: ignore[arg-type]
    assert diller.kok(cfg, ad, "x", "web") == "demo-app/e2e-app-python"  # type: ignore[arg-type]
    cfg = SimpleNamespace(dil_kokleri={ad: "blok-taban"})
    assert diller.kok(cfg, ad, "x", "android") == "blok-taban"  # type: ignore[arg-type]
    cfg = SimpleNamespace(dil_kokleri={ad: "blok-taban", f"{ad}_ANDROID": "blok-android"})
    assert diller.kok(cfg, ad, "x", "android") == "blok-android"  # type: ignore[arg-type]
    assert diller.kok(cfg, ad, "x", "ios") == "blok-taban"  # type: ignore[arg-type]


def test_proje_blogu_dil_kokleri_dogrulamasi() -> None:
    b = ProjeBlogu(pid="p1", dil_kokleri={"TP_E2E_PYTHON_ROOT": " demo-app/e2e-python "})
    assert b.dil_kokleri == {"TP_E2E_PYTHON_ROOT": "demo-app/e2e-python"}
    assert ProjeBlogu(pid="p1", dil_kokleri={"TP_ANDROID_KOTLIN_ROOT_ANDROID": "app/src/x"})
    for kotu in (
        {"TP_E2E_PYTHON_ROOT": "/mutlak"},
        {"TP_E2E_PYTHON_ROOT": "../kacis"},
        {"BASE_URL": "x"},
        {"TP_E2E_PYTHON_ROOT_LINUX": "x"},
    ):
        with pytest.raises(ValidationError):
            ProjeBlogu(pid="p1", dil_kokleri=kotu)


def test_settings_proje_blogundan_dil_kokleri() -> None:
    from toolchain_common.settings import settings

    cfg = settings(ProjeBlogu(pid="p1", dil_kokleri={"TP_E2E_PYTHON_ROOT": "py"}))
    assert dict(cfg.dil_kokleri or {}) == {"TP_E2E_PYTHON_ROOT": "py"}


# ------------------------------------------------------------------------ worker uçları


@pytest.fixture
def client(env: Path) -> TestClient:
    worker_app._SYMBOL_CACHE.clear()
    return TestClient(worker_app.app)


def test_symbols_eklentiye_dagitilir_ve_onbellekli(
    client: TestClient, forge: Any, sahte: SahteDil
) -> None:
    for _ in range(2):
        r = client.post("/symbols", json={"sha": forge.main, "lang": "python", "platform": "ios"})
        assert r.status_code == 200, r.text
        tablo = r.json()
        assert tablo["sha"] == forge.main and tablo["lang"] == "python"
        assert tablo["platform"] == "ios" and tablo["page_objects"][0]["name"] == "LoginPage"
    assert sahte.cagrilar == [("symbols", "ios")]  # ikinci çağrı önbellekten


def test_bilinmeyen_lang_422(client: TestClient, forge: Any) -> None:
    r = client.post("/symbols", json={"sha": forge.main, "lang": "cobol"})
    assert r.status_code == 422


def test_ast_guard_eklentiye_dagitilir(client: TestClient, forge: Any, sahte: SahteDil) -> None:
    r = client.post(
        "/ast-guard",
        json={"base_sha": forge.main, "head_sha": forge.main, "lang": "python", "mode": "pr"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and sahte.cagrilar == [("guard", "pr")]


def test_check_govdesi_eklenti_test_dosyasi_ve_grep(sahte: SahteDil) -> None:
    body = worker_app.CheckBody(sha="main", lang="python", test_files=["tests/test_a.py"] * 2)
    assert body.test_files == ["tests/test_a.py"] and body.dil == "python"
    with pytest.raises(ValidationError, match="tests"):
        worker_app.CheckBody(sha="main", lang="python", test_files=["e2e/x.spec.ts"])
    with pytest.raises(ValidationError, match="grep"):
        worker_app.CheckBody(sha="main", lang="python", grep="login")


def test_check_execute_eklenti_run_static(sahte: SahteDil, env: Path, tmp_path: Path) -> None:
    from toolchain_common.settings import settings

    cfg = settings()
    req = checks.CheckRequest(sha="a" * 40, lang="python", platform="web", record_check=False)
    head = SimpleNamespace(sha="a" * 40, kaynak="yerel", repo=tmp_path)
    rapor = checks._execute_locked(cfg, req, head, None, None)  # type: ignore[arg-type]
    assert sahte.cagrilar == [("run_static", "python", "web")]
    assert rapor["ok"] is True and rapor["lang"] == "python"
    assert rapor["check_name"] == "local-ci-web-python"
    assert "Yerel CI (python) geçti" in rapor["summary"]


# ------------------------------------------------------------------------------- runner


def test_runner_lang_kayittan_dogrulanir(sahte_runner: SahteRunner) -> None:
    ok = runner_app.RunBody(sha="main", run_id="r1", lang="python", test_files=["tests/test_a.py"])
    assert ok.to_request().platform == "web"
    with pytest.raises(ValidationError, match="lang yalnızca"):
        runner_app.RunBody(sha="main", run_id="r1", lang="cobol")
    with pytest.raises(ValidationError, match="grep"):
        runner_app.RunBody(sha="main", run_id="r1", lang="python", grep="x")
    with pytest.raises(ValidationError):
        runner_app.RunBody(sha="main", run_id="r1", lang="python", test_files=["x.spec.ts"])


def test_runner_execute_locked_eklentiye_dagitir(sahte_runner: SahteRunner) -> None:
    req = runner.RunRequest(sha="a" * 40, run_id="r1", lang="python", platform="android")
    out = runner._execute_locked(None, req, None, None)  # type: ignore[arg-type]
    assert out == {"status": "passed", "lang": "python"}
    assert sahte_runner.cagrilar == [("python", "android")]
    with pytest.raises(runner.RunRejected, match="Bilinmeyen dil"):
        kotu = runner.RunRequest(sha="a", run_id="r", lang="cobol")
        runner._execute_locked(None, kotu, None, None)  # type: ignore[arg-type]
