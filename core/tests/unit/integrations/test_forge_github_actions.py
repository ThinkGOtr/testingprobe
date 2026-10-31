"""GitHubForge — GitHub Actions uçları (ci-runs alımı): httpx MockTransport ile sahte GitHub.

Kimlik bilgisi yokken GitHub modunun aynı kod yolunu doğrular: dispatch, koşu bulma, job ve
artefakt listesi, artefakt indirme (yönlendirme kimliksiz), güvenli zip açma, ayrıntılı kontroller.
"""

from __future__ import annotations

import io
import json
import stat
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from tp_core.integrations.forge import (
    ForgeError,
    ForgeNotFoundError,
    ForgeValidationError,
)
from tp_core.integrations.forge_github import (
    ARTIFACT_SAUCE,
    ARTIFACT_TEST_LOCAL,
    CI_META_FILE,
    GitHubForge,
    TokenAuth,
    WorkflowRun,
    safe_extract_zip,
)

REPO = "acme/testingprobe"
R = f"/repos/{REPO}"
SHA = "a" * 40
DEPLOY_SHA = "d" * 40
BLOB_HOST = "productionresultssa1.blob.core.windows.net"

Handler = Callable[[httpx.Request], httpx.Response | dict[str, Any] | list[Any]]


class FakeGitHub:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str, str], Handler] = {}
        self.calls: list[httpx.Request] = []

    def on(
        self,
        method: str,
        path: str,
        handler: Handler | dict[str, Any] | list[Any],
        host: str = "api.github.com",
    ) -> None:
        self.routes[(host, method, path)] = (
            handler if callable(handler) else (lambda _r, h=handler: h)
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        handler = self.routes.get((request.url.host, request.method, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"message": "Not Found"})
        result = handler(request)
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    def last(self, method: str, path: str) -> httpx.Request:
        for req in reversed(self.calls):
            if req.method == method and req.url.path == path:
                return req
        raise AssertionError(f"çağrı yok: {method} {path}")


@pytest.fixture
def gh() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def forge(gh: FakeGitHub) -> GitHubForge:
    return GitHubForge(REPO, TokenAuth("tok-123"), transport=httpx.MockTransport(gh))


def no_content(_r: httpx.Request) -> httpx.Response:
    return httpx.Response(204)


def run_json(run_id: int, title: str, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": run_id,
        "name": "ci",
        "display_title": title,
        "event": "repository_dispatch",
        "status": "completed",
        "conclusion": "failure",
        "head_sha": SHA,
        "head_branch": "main",
        "run_number": run_id % 1000,
        "run_attempt": 1,
        "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
        "created_at": f"2026-10-31T10:00:{run_id % 60:02d}Z",
        "updated_at": "2026-10-31T10:05:00Z",
        "path": ".github/workflows/ci.yml",
    }
    data.update(extra)
    return data


def make_zip(files: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


# ------------------------------------------------------------------ tetik


def test_dispatch_deploy_istek_kimligi_ve_ref(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("POST", f"{R}/dispatches", no_content)
    forge.dispatch_deploy("ist-42", ref="tp/case-1")
    req = gh.last("POST", f"{R}/dispatches")
    assert json.loads(req.content) == {
        "event_type": "deploy",
        "client_payload": {"istek_id": "ist-42", "ref": "tp/case-1"},
    }
    assert req.headers["Authorization"] == "Bearer tok-123"
    forge.dispatch_deploy("ist-43")
    assert json.loads(gh.last("POST", f"{R}/dispatches").content)["client_payload"] == {
        "istek_id": "ist-43"
    }


@pytest.mark.parametrize(
    "call",
    [
        lambda f: f.dispatch_deploy("kötü id"),
        lambda f: f.dispatch_deploy("x" * 65),
        lambda f: f.dispatch_deploy("ok", ref="../main"),
        lambda f: f.repository_dispatch("de ploy", {}),
        lambda f: f.repository_dispatch("deploy", {f"k{i}": i for i in range(11)}),
        lambda f: f.repository_dispatch("deploy", {"x": object()}),
        lambda f: f.repository_dispatch("deploy", {"istek_id": "a b"}),
    ],
)
def test_dispatch_dogrulama(forge: GitHubForge, gh: FakeGitHub, call: Any) -> None:
    with pytest.raises(ForgeValidationError):
        call(forge)
    assert not gh.calls


def test_dispatch_yetki_hatasi(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on(
        "POST",
        f"{R}/dispatches",
        lambda _r: httpx.Response(403, json={"message": "Resource not accessible by integration"}),
    )
    with pytest.raises(ForgeError, match="403"):
        forge.dispatch_deploy("ist-1")


def test_workflow_dispatch(forge: GitHubForge, gh: FakeGitHub) -> None:
    path = f"{R}/actions/workflows/ci.yml/dispatches"
    gh.on("POST", path, no_content)
    assert (
        forge.workflow_dispatch("ci.yml", "main", {"tetik": "nightly", "istek_id": "g-1"}) is None
    )
    assert json.loads(gh.last("POST", path).content) == {
        "ref": "main",
        "inputs": {"tetik": "nightly", "istek_id": "g-1"},
    }
    # Yeni API: koşu kimliği yanıtta dönerse kullanılır.
    bv = f"{R}/actions/workflows/break-verify.yml/dispatches"
    gh.on("POST", bv, {"workflow_run_id": 987, "run_url": "u", "html_url": "h"})
    assert forge.workflow_dispatch("break-verify.yml", "tp/case-1", {"grep": "kampanya"}) == 987
    with pytest.raises(ForgeValidationError):
        forge.workflow_dispatch("../x.yml")
    with pytest.raises(ForgeValidationError):
        forge.workflow_dispatch("ci.yml", "main", {"bad key": "x"})
    with pytest.raises(ForgeValidationError):
        forge.workflow_dispatch("ci.yml", "main", {"istek_id": "a;b"})
    with pytest.raises(ForgeValidationError):
        forge.workflow_dispatch("ci.yml", "main", {"tetik": 1})  # type: ignore[dict-item]


# ------------------------------------------------------------------ koşular


def test_list_workflow_runs_sha_ile(forge: GitHubForge, gh: FakeGitHub) -> None:
    path = f"{R}/actions/workflows/ci.yml/runs"
    gh.on(
        "GET",
        path,
        {
            "total_count": 2,
            "workflow_runs": [
                run_json(11, "Kampanya testleri", event="pull_request", conclusion="success"),
                run_json(12, "Kampanya testleri", event="push", status="in_progress",
                         conclusion=None),
            ],
        },
    )  # fmt: skip
    runs = forge.list_workflow_runs(head_sha=SHA, event="push", per_page=500)
    params = gh.last("GET", path).url.params
    assert params["head_sha"] == SHA
    assert params["event"] == "push"
    assert params["per_page"] == "100"
    assert [r.id for r in runs] == [12, 11]  # en yeni önce
    assert runs[0].completed is False and runs[1].completed is True
    assert runs[1].html_url == f"https://github.com/{REPO}/actions/runs/11"
    with pytest.raises(ForgeValidationError):
        forge.list_workflow_runs(head_sha="main")
    with pytest.raises(ForgeValidationError):
        forge.list_workflow_runs(event="issues")
    with pytest.raises(ForgeValidationError):
        forge.list_workflow_runs(created="1; drop")


def test_find_dispatched_run_kosu_adindan(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on(
        "GET",
        f"{R}/actions/workflows/ci.yml/runs",
        {
            "workflow_runs": [
                run_json(20, "ci deploy [ist-41]"),
                run_json(21, "ci deploy [ist-42]", status="queued", conclusion=None),
                run_json(22, "ci deploy [elle]"),
                run_json(23, "Fix [ist-42] in title", event="pull_request"),
            ]
        },
    )
    run = forge.find_dispatched_run("ist-42", event="repository_dispatch")
    assert run is not None
    # 23'ün başlığı da [ist-42] ile bitmiyor ("in title") → yalnızca 21 eşleşir
    assert run.id == 21 and run.status == "queued"
    assert gh.calls[-1].url.params["event"] == "repository_dispatch"
    assert forge.find_dispatched_run("ist-99") is None
    assert WorkflowRun.from_api(run_json(1, "ci deploy [elle]")).istek_id is None
    assert WorkflowRun.from_api(run_json(1, "ci nightly [g-1]")).istek_id == "g-1"


def test_get_run_ve_jobs(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/actions/runs/55", run_json(55, "ci deploy [x]", conclusion="success"))
    gh.on(
        "GET",
        f"{R}/actions/runs/55/jobs",
        {
            "jobs": [
                {"id": 1, "run_id": 55, "name": "test-local", "status": "completed",
                 "conclusion": "failure", "html_url": "https://github.com/j/1"},
                {"id": 2, "run_id": 55, "name": "sauce", "status": "completed",
                 "conclusion": "skipped"},
            ]
        },
    )  # fmt: skip
    run = forge.get_workflow_run(55)
    assert run.conclusion == "success" and run.istek_id == "x"
    jobs = forge.list_run_jobs(55)
    assert [(j.name, j.conclusion) for j in jobs] == [
        ("test-local", "failure"),
        ("sauce", "skipped"),
    ]
    assert gh.last("GET", f"{R}/actions/runs/55/jobs").url.params["filter"] == "latest"
    with pytest.raises(ForgeValidationError):
        forge.get_workflow_run(0)
    with pytest.raises(ForgeNotFoundError):
        forge.get_workflow_run(56)


# ------------------------------------------------------------------ artefaktlar


def artifact_json(aid: int, name: str, **extra: Any) -> dict[str, Any]:
    data = {
        "id": aid,
        "name": name,
        "size_in_bytes": 1234,
        "expired": False,
        "created_at": f"2026-10-31T10:0{aid % 10}:00Z",
        "expires_at": "2026-11-14T10:00:00Z",
        "digest": "sha256:" + "0" * 64,
        "workflow_run": {"id": 55, "head_sha": SHA},
    }
    data.update(extra)
    return data


def test_list_run_artifacts(forge: GitHubForge, gh: FakeGitHub) -> None:
    path = f"{R}/actions/runs/55/artifacts"
    gh.on(
        "GET",
        path,
        {"artifacts": [artifact_json(1, ARTIFACT_TEST_LOCAL), artifact_json(2, ARTIFACT_SAUCE)]},
    )
    arts = forge.list_run_artifacts(55)
    assert [(a.id, a.name, a.run_id, a.head_sha) for a in arts] == [
        (1, "test-local-results", 55, SHA),
        (2, "sauce-results", 55, SHA),
    ]
    # ad süzgeci sunucuya gider; sunucu süzmese de yalnızca eşleşen döner
    only = forge.list_run_artifacts(55, ARTIFACT_SAUCE)
    assert gh.last("GET", path).url.params["name"] == "sauce-results"
    assert [a.id for a in only] == [2]
    with pytest.raises(ForgeValidationError):
        forge.list_run_artifacts(55, "../x")


def test_download_artifact_yonlendirme_kimliksiz(forge: GitHubForge, gh: FakeGitHub) -> None:
    payload = make_zip({"ci-meta.json": b"{}"})
    gh.on(
        "GET",
        f"{R}/actions/artifacts/7/zip",
        lambda _r: httpx.Response(302, headers={"location": f"https://{BLOB_HOST}/a/7.zip?sig=x"}),
    )
    gh.on("GET", "/a/7.zip", lambda _r: httpx.Response(200, content=payload), host=BLOB_HOST)
    assert forge.download_artifact(7) == payload
    api_req, blob_req = gh.calls[-2], gh.calls[-1]
    assert api_req.headers["Authorization"] == "Bearer tok-123"
    assert blob_req.url.host == BLOB_HOST
    assert "Authorization" not in blob_req.headers  # token blob deposuna sızmaz


def test_download_artifact_sinirlar(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/actions/artifacts/8/zip", lambda _r: httpx.Response(410))
    with pytest.raises(ForgeNotFoundError, match="süresi dolmuş"):
        forge.download_artifact(8)
    gh.on(
        "GET",
        f"{R}/actions/artifacts/9/zip",
        lambda _r: httpx.Response(302, headers={"location": "http://evil.example/x.zip"}),
    )
    with pytest.raises(ForgeError, match="güvensiz yönlendirme"):
        forge.download_artifact(9)
    gh.on(
        "GET",
        f"{R}/actions/artifacts/10/zip",
        lambda _r: httpx.Response(302, headers={"location": f"https://{BLOB_HOST}/big.zip"}),
    )
    gh.on("GET", "/big.zip", lambda _r: httpx.Response(200, content=b"x" * 2048), host=BLOB_HOST)
    with pytest.raises(ForgeValidationError, match="boyut"):
        forge.download_artifact(10, max_bytes=1024)
    gh.on("GET", "/gone.zip", lambda _r: httpx.Response(403), host=BLOB_HOST)
    gh.on(
        "GET",
        f"{R}/actions/artifacts/11/zip",
        lambda _r: httpx.Response(302, headers={"location": f"https://{BLOB_HOST}/gone.zip"}),
    )
    with pytest.raises(ForgeError):
        forge.download_artifact(11)


def test_download_run_artifact_acilir(forge: GitHubForge, gh: FakeGitHub, tmp_path: Path) -> None:
    meta = {"schema_version": 1, "kaynak": "github", "sha": DEPLOY_SHA, "durum": "failed"}
    payload = make_zip(
        {
            CI_META_FILE: json.dumps(meta).encode(),
            "junit.xml": b"<testsuites/>",
            "results.json": b"{}",
            "allure-results/x-result.json": b"{}",
            "playwright-report/index.html": b"<html/>",
        }
    )
    gh.on(
        "GET",
        f"{R}/actions/runs/55/artifacts",
        {
            "artifacts": [
                artifact_json(3, ARTIFACT_TEST_LOCAL, expired=True),
                artifact_json(4, ARTIFACT_TEST_LOCAL),
            ]
        },
    )
    gh.on("GET", f"{R}/actions/artifacts/4/zip", lambda _r: httpx.Response(200, content=payload))
    dest = tmp_path / "out"
    art = forge.download_run_artifact(55, ARTIFACT_TEST_LOCAL, dest)
    assert art is not None and art.id == 4
    assert json.loads((dest / CI_META_FILE).read_text())["sha"] == DEPLOY_SHA
    assert (dest / "playwright-report/index.html").exists()
    # dolu hedefe ikinci kez açılmaz
    with pytest.raises(ForgeValidationError, match="boş değil"):
        forge.download_run_artifact(55, ARTIFACT_TEST_LOCAL, dest)
    # artefakt yok (ör. Sauce job'u koşmadı) → None
    gh.on("GET", f"{R}/actions/runs/56/artifacts", {"artifacts": []})
    assert forge.download_run_artifact(56, ARTIFACT_SAUCE, tmp_path / "s") is None


def test_download_run_artifact_kotu_zip_temizlenir(
    forge: GitHubForge, gh: FakeGitHub, tmp_path: Path
) -> None:
    gh.on("GET", f"{R}/actions/runs/57/artifacts", {"artifacts": [artifact_json(5, "x")]})
    bad = make_zip({"ok.txt": b"1", "../../kacis.txt": b"2"})
    gh.on("GET", f"{R}/actions/artifacts/5/zip", lambda _r: httpx.Response(200, content=bad))
    dest = tmp_path / "bad"
    with pytest.raises(ForgeValidationError, match="güvensiz yol"):
        forge.download_run_artifact(57, "x", dest)
    assert not dest.exists()
    assert not (tmp_path / "kacis.txt").exists()


@pytest.mark.parametrize(
    ("files", "symlink", "match"),
    [
        ({"/etc/x": b"1"}, None, "güvensiz yol"),
        ({"a/../../x": b"1"}, None, "güvensiz yol"),
        ({"C:/x": b"1"}, None, "güvensiz yol"),
        ({"a\\..\\x": b"1"}, None, "geçersiz yol"),
        ({"ok": b"1"}, "link", "sembolik bağ"),
    ],
)
def test_safe_extract_zip_reddeder(
    tmp_path: Path, files: dict[str, bytes], symlink: str | None, match: str
) -> None:
    with pytest.raises(ForgeValidationError, match=match):
        safe_extract_zip(make_zip(files, symlink=symlink), tmp_path / "d")


def test_safe_extract_zip_sinirlar(tmp_path: Path) -> None:
    bomb = make_zip({"z.bin": b"\0" * (2 * 1024 * 1024)})
    with pytest.raises(ForgeValidationError, match="açılmış boyutu"):
        safe_extract_zip(bomb, tmp_path / "a", max_total=1024 * 1024)
    many = make_zip({f"f{i}": b"" for i in range(5)})
    with pytest.raises(ForgeValidationError, match="çok fazla"):
        safe_extract_zip(many, tmp_path / "b", max_files=4)
    with pytest.raises(ForgeValidationError, match="zip değil"):
        safe_extract_zip(b"not a zip", tmp_path / "c")
    ok = safe_extract_zip(make_zip({"a/b.txt": b"1", "c.txt": b"2"}), tmp_path / "d")
    assert ok == ["a/b.txt", "c.txt"]


# ------------------------------------------------------------------ kontroller


def test_check_runs_ayrintili(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on(
        "GET",
        f"{R}/commits/{SHA}/check-runs",
        {
            "check_runs": [
                {
                    "id": 101,
                    "name": "test-local",
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": f"https://github.com/{REPO}/runs/101",
                    "details_url": f"https://github.com/{REPO}/actions/runs/555/job/101",
                    "started_at": "2026-10-31T10:00:00Z",
                    "completed_at": "2026-10-31T10:02:00Z",
                    "app": {"slug": "github-actions"},
                    "output": {"title": "1 failed", "summary": "Kampanya"},
                },
                {
                    "id": 102,
                    "name": "harici",
                    "status": "in_progress",
                    "conclusion": None,
                    "details_url": "https://ci.example.com/x",
                    "started_at": "2026-10-31T10:01:00Z",
                },
            ]
        },
    )
    runs = forge.check_runs(SHA)
    first, second = runs
    assert (first.id, first.workflow_run_id, first.job_id, first.app_slug) == (
        101,
        555,
        101,
        "github-actions",
    )
    assert first.check.conclusion == "failure" and first.output_summary == "Kampanya"
    assert second.workflow_run_id is None and second.check.status == "in_progress"
    # port biçimi değişmedi
    assert [c.name for c in forge.checks(SHA)] == ["test-local", "harici"]


def test_repository_dispatch_ci_seridi_yuku(forge: GitHubForge, gh: FakeGitHub) -> None:
    """ci-runs şeridinin yükü (`tetik`, `tp_run_id`) geçer; `tp_run_id` koşu adına girer."""
    gh.on("POST", f"{R}/dispatches", no_content)
    rid = "3f2b8c1e-0d4a-4b7e-9a51-2c6f0e8d9b10"
    forge.repository_dispatch("deploy", {"tetik": "deploy", "tp_run_id": rid})
    assert json.loads(gh.last("POST", f"{R}/dispatches").content)["client_payload"] == {
        "tetik": "deploy",
        "tp_run_id": rid,
    }
    with pytest.raises(ForgeValidationError):
        forge.repository_dispatch("deploy", {"tp_run_id": "x y"})
    run = WorkflowRun.from_api(run_json(30, f"ci deploy [{rid}]"))
    assert run.istek_id == rid
