"""test-runner: koşu yönetimi (sahte Playwright), kırılmanın her durumda geri alınması, sıra."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runner import run as runner
from runner.app import app
from tests.conftest import Forge, make_fake_node

REPORT_PASSED = {
    "suites": [
        {
            "title": "cart.spec.ts",
            "file": "cart.spec.ts",
            "specs": [
                {
                    "title": "6 al 1 bedava",
                    "file": "cart.spec.ts",
                    "line": 5,
                    "tags": ["@kampanya"],
                    "tests": [
                        {
                            "projectName": "chromium",
                            "status": "expected",
                            "results": [{"status": "passed", "duration": 120, "retry": 0}],
                        }
                    ],
                }
            ],
        }
    ],
    "errors": [],
    "stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0, "duration": 150.5},
}


def fake_playwright(
    tmp_path: Path, *, report: dict[str, Any] | None, exit_code: int = 0, sleep_s: float = 0
) -> Path:
    """`node <cli> test ...` yerine: argv/ortamı kaydeder, raporu yazar, çıkış kodu döner."""
    return make_fake_node(
        tmp_path,
        f"""
        cwd = pathlib.Path.cwd()
        (cwd / "results").mkdir(exist_ok=True)
        (cwd / "results" / "argv.json").write_text(json.dumps({{
            "argv": sys.argv[1:],
            "env": {{k: os.environ.get(k) for k in (
                "BASE_URL", "DEMO_API_URL", "DEMOAPP_TEST_TOKEN", "BREAK_CAMPAIGN", "CI",
                "TP_RUN_ID", "ANTHROPIC_API_KEY", "TP_FAULT")}},
            "node_modules_link": os.path.islink("node_modules"),
        }}))
        time.sleep({sleep_s})
        report = {json.dumps(report)!r}
        if report != "null":
            (cwd / "results" / "results.json").write_text(report)
            (cwd / "results" / "junit.xml").write_text("<testsuites/>")
        sys.exit({exit_code})
        """,
    )


class DemoApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.gets: list[str] = []
        self.status = 200
        self.get_status: dict[str, int] = {}  # yol → durum (varsayılan 200)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.gets.append(self.path)
                self.send_response(outer.get_status.get(self.path, 200))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                outer.calls.append(
                    {
                        "path": self.path,
                        "token": self.headers.get("X-Demoapp-Test-Token"),
                        "body": json.loads(self.rfile.read(length) or b"{}"),
                    }
                )
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def demo_api(env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[DemoApi]:
    """Sahte demo uygulaması: hem web (`BASE_URL/`) hem API (`/health`, `/test/break`)."""
    api = DemoApi()
    monkeypatch.setenv("DEMO_API_URL", api.url)
    monkeypatch.setenv("BASE_URL", f"{api.url}/web")
    monkeypatch.setenv("TP_HEALTH_TIMEOUT_S", "2")
    yield api
    api.server.shutdown()


@pytest.fixture
def client(env: Path, demo_api: DemoApi) -> TestClient:
    return TestClient(app)


def _run(client: TestClient, **body: Any) -> Any:
    return client.post("/run", json={"run_id": "r1", **body})


def test_passed_run_layout_env_and_argv(
    client: TestClient,
    forge: Forge,
    env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sızmamalı")
    resp = _run(
        client,
        sha=forge.main[:12],
        grep="kampanya",
        repeat_each=3,
        retries=1,
        test_files=["tests/cart.spec.ts"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "passed"
    assert data["sha"] == forge.main
    assert data["stats"] == {
        "expected": 1,
        "unexpected": 0,
        "flaky": 0,
        "skipped": 0,
        "duration_ms": 150,
    }
    assert data["tests"][0]["title"] == "6 al 1 bedava"
    run_dir = env / "runs" / "r1"
    assert data["artifacts_dir"] == str(run_dir)
    assert data["junit"] == str(run_dir / "src" / "e2e" / "results" / "junit.xml")
    assert Path(data["junit"]).is_file() and Path(data["json"]).is_file()
    # Koşan kodun kopyası kanıt olarak kalır; imaj bağımlılık bağlantısı kaldırılır.
    assert (run_dir / "src" / "e2e" / "pages" / "catalog" / "locators.ts").is_file()
    assert not (run_dir / "src" / "e2e" / "node_modules").exists()
    assert json.loads((run_dir / "run.json").read_text())["status"] == "passed"
    rec = json.loads((run_dir / "src" / "e2e" / "results" / "argv.json").read_text())
    assert rec["node_modules_link"] is True
    assert rec["argv"][1:] == [
        "test",
        "--project=chromium",
        "--repeat-each=3",
        "--retries=1",
        "--grep=kampanya",
        "tests/cart.spec.ts",
    ]
    assert rec["env"] == {
        "BASE_URL": f"{demo_api.url}/web",
        "DEMO_API_URL": demo_api.url,
        "DEMOAPP_TEST_TOKEN": "test-belirteci",
        "BREAK_CAMPAIGN": "",
        "CI": "1",
        "TP_RUN_ID": "r1",
        "ANTHROPIC_API_KEY": None,
        "TP_FAULT": "",
    }
    assert data["break_campaign"] is False and data["fault"] is None
    assert demo_api.calls == []  # kırılma istenmedi → /test/break çağrılmaz
    # Koşu öncesi sağlık kontrolü raporda (Faz 4 triyaj kuralı 1'in deterministik sinyali).
    assert demo_api.gets == ["/web/", "/health"]
    saglik = data["saglik"]
    assert saglik["ok"] is True and saglik["hata"] is None
    assert saglik["web"]["status"] == 200 and saglik["api"]["status"] == 200
    assert isinstance(saglik["web"]["ms"], int) and isinstance(saglik["api"]["ms"], int)
    assert json.loads((run_dir / "run.json").read_text())["saglik"] == saglik


def test_failed_run_and_break_restored(
    client: TestClient,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
) -> None:
    failed = json.loads(json.dumps(REPORT_PASSED))
    failed["stats"].update(expected=0, unexpected=1)
    t = failed["suites"][0]["specs"][0]["tests"][0]
    t["status"] = "unexpected"
    t["results"] = [
        {
            "status": "failed",
            "duration": 5,
            "error": {"message": "\x1b[31mexpect(x).toHaveText\x1b[0m"},
        }
    ]
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=failed, exit_code=1)))
    resp = _run(client, sha=forge.main, env={"BREAK_CAMPAIGN": "1"})
    data = resp.json()
    assert data["status"] == "failed"
    assert data["tests"][0]["error"] == "expect(x).toHaveText"
    rec = json.loads(Path(data["json"]).with_name("argv.json").read_text())
    assert rec["env"]["BREAK_CAMPAIGN"] == "1"
    assert data["break_restore"]["ok"] is True
    assert [(c["path"], c["token"], c["body"]) for c in demo_api.calls] == [
        ("/test/break", "test-belirteci", {"kullanici_adi": "bayi1", "kampanya": False}),
        ("/test/break", "test-belirteci", {"kullanici_adi": "bayi2", "kampanya": False}),
    ]


def test_timeout_kills_and_still_restores_break(
    client: TestClient,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=None, sleep_s=30)))
    monkeypatch.setenv("TP_RUN_TIMEOUT_S", "1")
    data = _run(client, sha=forge.main, break_campaign=True).json()
    assert data["status"] == "error"
    assert "süre sınırını" in data["error"]
    assert data["exit_code"] is None
    assert len(demo_api.calls) == 2


def test_break_restore_failure_makes_run_error(
    client: TestClient,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
) -> None:
    demo_api.status = 500
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    data = _run(client, sha=forge.main, break_campaign=True).json()
    assert data["status"] == "error"
    assert "geri alınamadı" in data["error"]


def test_committed_fake_report_is_ignored(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = forge.commit(
        "tp/case-sahte",
        {"e2e/results/results.json": json.dumps(REPORT_PASSED)},
    )
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=None, exit_code=1)))
    data = _run(client, sha=head).json()
    assert data["status"] == "error"
    assert data["error"] == "Playwright JSON raporu üretilmedi"


def test_no_tests_ran_is_error(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = {"suites": [], "errors": [], "stats": {"expected": 0, "unexpected": 0}}
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=empty, exit_code=1)))
    data = _run(client, sha=forge.main, grep="eşleşmeyen").json()
    assert data["status"] == "error"
    assert "Hiç test koşmadı" in data["error"]


def test_run_id_is_immutable(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    assert _run(client, sha=forge.main).status_code == 200
    second = _run(client, sha=forge.main)
    assert second.status_code == 409
    assert "zaten kullanılmış" in second.json()["detail"]


def test_unknown_commit_404(client: TestClient) -> None:
    resp = _run(client, sha="f" * 40)
    assert resp.status_code == 404
    assert "bulunamadı" in resp.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"sha": "--upload-pack=x"},
        {"sha": "main", "run_id": "../../etc"},
        {"sha": "main", "test_files": ["../x.spec.ts"]},
        {"sha": "main", "env": {"NODE_OPTIONS": "--require=/tmp/x.js"}},
        {"sha": "main", "env": {"BREAK_CAMPAIGN": "evet"}},
        {"sha": "main", "fault": "Kampanya-Yok"},
        {"sha": "main", "fault": "x" * 41},
        {"sha": "main", "fault": "a_b\n"},
        {"sha": "main", "fault": 7},
        {"sha": "main", "env": {"TP_FAULT": "a b"}},
        {"sha": "main", "fault": "min_siparis_500", "env": {"TP_FAULT": "min_siparis_1000"}},
        {"sha": "main", "repeat_each": 0},
        {"sha": "main", "retries": 9},
        {"sha": "main", "workers": 3},
        {"sha": "main", "bilinmeyen": 1},
    ],
)
def test_invalid_bodies_422_turkish(client: TestClient, body: dict[str, Any]) -> None:
    resp = client.post("/run", json={"run_id": "r1", **body})
    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("Geçersiz istek")


def test_break_requires_token(
    client: TestClient, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", "")
    resp = _run(client, sha=forge.main, break_campaign=True)
    assert resp.status_code == 422
    assert "DEMOAPP_TEST_TOKEN" in resp.json()["detail"]


# ------------------------------------------------------------------ ekilmiş hata (012 §4.6)


@pytest.mark.parametrize(
    "istek",
    [
        {"fault": "min_siparis_500"},
        {"env": {"TP_FAULT": "min_siparis_500"}},
        {"fault": "min_siparis_500", "env": {"TP_FAULT": "min_siparis_500"}},
    ],
)
def test_fault_run_passes_env_reports_and_restores(
    client: TestClient,
    forge: Forge,
    env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
    istek: dict[str, Any],
) -> None:
    """`fault` (ya da eş anlamlısı env.TP_FAULT) test sürecine TP_FAULT olarak geçer, raporda
    `break_campaign`'in yanında durur ve koşu sonunda her bayi için geri alınır."""
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    resp = _run(client, sha=forge.main, **istek)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "passed"
    assert (data["fault"], data["break_campaign"]) == ("min_siparis_500", False)
    rec = json.loads(Path(data["json"]).with_name("argv.json").read_text())
    assert (rec["env"]["TP_FAULT"], rec["env"]["BREAK_CAMPAIGN"]) == ("min_siparis_500", "")
    assert data["break_restore"] == {"ok": True, "bayiler": {"bayi1": "ok", "bayi2": "ok"}}
    assert [(c["path"], c["token"], c["body"]) for c in demo_api.calls] == [
        ("/test/break", "test-belirteci", {"kullanici_adi": "bayi1", "kampanya": False}),
        ("/test/break", "test-belirteci", {"kullanici_adi": "bayi2", "kampanya": False}),
    ]
    kayit = json.loads((env / "runs" / "r1" / "run.json").read_text())
    assert (kayit["fault"], kayit["break_campaign"]) == ("min_siparis_500", False)


def test_fault_with_break_campaign_passes_both(
    client: TestClient,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
) -> None:
    """İkisi birlikte verilebilir; hangisinin uygulanacağına fixture karar verir (TP_FAULT)."""
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    data = _run(client, sha=forge.main, fault="fiyat_p004_31", break_campaign=True).json()
    assert (data["fault"], data["break_campaign"]) == ("fiyat_p004_31", True)
    rec = json.loads(Path(data["json"]).with_name("argv.json").read_text())
    assert (rec["env"]["TP_FAULT"], rec["env"]["BREAK_CAMPAIGN"]) == ("fiyat_p004_31", "1")
    assert len(demo_api.calls) == 2  # tek geri alma turu


def test_empty_fault_is_no_fault(
    client: TestClient,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    data = _run(client, sha=forge.main, fault="", env={"TP_FAULT": ""}).json()
    assert data["fault"] is None and data["break_restore"] is None
    assert demo_api.calls == []


def test_fault_requires_token(
    client: TestClient, forge: Forge, monkeypatch: pytest.MonkeyPatch, demo_api: DemoApi
) -> None:
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", "")
    resp = _run(client, sha=forge.main, fault="kampanya_esik_7")
    assert resp.status_code == 422
    assert "DEMOAPP_TEST_TOKEN" in resp.json()["detail"]
    assert "Ekilmiş hata koşusu" in resp.json()["detail"]
    assert demo_api.calls == [] and demo_api.gets == []


def test_fault_restored_after_timeout_and_restore_failure_is_error(
    client: TestClient,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=None, sleep_s=30)))
    monkeypatch.setenv("TP_RUN_TIMEOUT_S", "1")
    data = _run(client, sha=forge.main, fault="kampanya_esik_7").json()
    assert data["status"] == "error" and "süre sınırını" in data["error"]
    assert len(demo_api.calls) == 2  # süre aşımında da her bayi için geri alındı

    demo_api.status = 500
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    data = client.post(
        "/run", json={"run_id": "r2", "sha": forge.main, "fault": "kampanya_esik_7"}
    ).json()
    assert data["status"] == "error"
    assert data["error"] == "Ekilmiş hata geri alınamadı."
    assert data["break_restore"]["ok"] is False


def test_fault_not_restored_when_app_unhealthy(
    client: TestClient,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
) -> None:
    demo_api.get_status["/health"] = 503
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    data = _run(client, sha=forge.main, fault="kampanya_esik_7").json()
    assert data["status"] == "error" and data["fault"] == "kampanya_esik_7"
    # Playwright hiç koşmadı: hata uygulanmadı, geri alma da yok.
    assert demo_api.calls == [] and data["break_restore"] is None


def test_runs_are_serialized(
    client: TestClient, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_RUN_QUEUE_WAIT_S", "0.2")
    assert runner.RUN_LOCK.acquire(timeout=1)
    try:
        resp = _run(client, sha=forge.main)
    finally:
        runner.RUN_LOCK.release()
    assert resp.status_code == 409
    assert "sürüyor" in resp.json()["detail"]


@pytest.mark.parametrize(
    ("bozuk", "beklenen"),
    [("/health", "api"), ("/web/", "web")],
)
def test_unhealthy_app_skips_playwright(
    client: TestClient,
    forge: Forge,
    env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,
    bozuk: str,
    beklenen: str,
) -> None:
    """Demo uygulaması sağlıksızsa Playwright başlatılmaz; koşu `error` + `saglik.ok=false`."""
    demo_api.get_status[bozuk] = 503
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    resp = _run(client, sha=forge.main, break_campaign=True)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "error"
    assert data["error"].startswith("Demo uygulaması sağlık kontrolü başarısız")
    assert data["exit_code"] is None and data["tests"] == []
    saglik = data["saglik"]
    assert saglik["ok"] is False
    assert saglik[beklenen]["status"] == 503 and saglik[beklenen]["hata"] == "HTTP 503"
    assert saglik["hata"] == data["error"]
    # Playwright hiç koşmadı: e2e kopyası/argv kaydı yok, kırılma uygulanmadığı için geri alma yok.
    run_dir = env / "runs" / "r1"
    assert not (run_dir / "src").exists()
    assert not (run_dir / "runner.log").exists()
    assert demo_api.calls == [] and data["break_restore"] is None
    assert json.loads((run_dir / "run.json").read_text())["saglik"]["ok"] is False


def test_unreachable_app_is_error(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ağ hatası (bağlantı reddi) da sağlık başarısızlığıdır: status None, hata türü kaydedilir."""
    monkeypatch.setenv("BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("DEMO_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    data = _run(client, sha=forge.main).json()
    assert data["status"] == "error"
    assert data["saglik"]["ok"] is False
    assert data["saglik"]["web"]["status"] is None and data["saglik"]["web"]["hata"]
    assert data["saglik"]["api"]["status"] is None and data["saglik"]["api"]["hata"]
    assert "sağlık kontrolü başarısız" in data["error"]


def test_playwright_env_passes_only_testveri_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """K19: `TP_TESTVERI_<AD>` test sürecine geçer; benzer ama desene uymayan adlar geçmez."""
    from types import SimpleNamespace

    for k, v in {
        "TP_TESTVERI_DEMO_PAROLA": "gizli",
        "TP_TESTVERI_X1": "a",
        "TP_TESTVERI_": "bos-ad",
        "TP_TESTVERI_kucuk": "b",
        "TP_TESTVERI_" + "A" * 65: "uzun",
        "XTP_TESTVERI_A": "onek",
        "ANTHROPIC_API_KEY": "anahtar",
    }.items():
        monkeypatch.setenv(k, v)
    cfg = SimpleNamespace(base_url="http://b", demo_api_url="http://a", demoapp_test_token="t")
    env = runner.playwright_env(cfg, runner.RunRequest(sha="a" * 40, run_id="r1"))  # type: ignore[arg-type]
    secrets = {k: v for k, v in env.items() if "TESTVERI" in k}
    assert secrets == {"TP_TESTVERI_DEMO_PAROLA": "gizli", "TP_TESTVERI_X1": "a"}
    assert "ANTHROPIC_API_KEY" not in env
    assert runner.TESTVERI_ENV_RE.fullmatch("TP_TESTVERI_" + "A" * 64)
