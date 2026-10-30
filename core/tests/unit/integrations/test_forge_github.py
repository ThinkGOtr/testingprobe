"""GitHubForge: httpx MockTransport ile sahte GitHub REST."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tp_core.integrations.forge import (
    ForgeConflictError,
    ForgeError,
    ForgeNotFoundError,
    ForgeProtectionError,
    ForgeValidationError,
    get_forge,
)
from tp_core.integrations.forge_github import AppAuth, GitHubForge, TokenAuth
from tp_core.ports import ForgePort

REPO = "acme/demo-app"
R = f"/repos/{REPO}"
MAIN = "a" * 40
MAIN_TREE = "t" * 40
NEW_TREE = "n" * 40
NEW_COMMIT = "c" * 40
BRANCH_HEAD = "b" * 40

Handler = Callable[[httpx.Request], httpx.Response | dict[str, Any] | list[Any]]


class FakeGitHub:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Handler] = {}
        self.calls: list[httpx.Request] = []

    def on(self, method: str, path: str, handler: Handler | dict[str, Any] | list[Any]) -> None:
        self.routes[(method, path)] = handler if callable(handler) else (lambda _r, h=handler: h)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        handler = self.routes.get((request.method, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"message": "Not Found"})
        result = handler(request)
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(201 if request.method == "POST" else 200, json=result)

    def body(self, method: str, path: str) -> Any:
        for req in reversed(self.calls):
            if req.method == method and req.url.path == path:
                return json.loads(req.content)
        raise AssertionError(f"çağrı yok: {method} {path}")

    def count(self, method: str, path: str) -> int:
        return sum(1 for r in self.calls if r.method == method and r.url.path == path)


def pr_json(number: int = 7, branch: str = "tp/fix", **extra: Any) -> dict[str, Any]:
    data = {
        "number": number,
        "state": "open",
        "title": "Locator onarımı",
        "body": "gövde",
        "head": {"ref": branch, "sha": BRANCH_HEAD},
        "base": {"ref": "main", "sha": MAIN},
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "labels": [],
        "merged_at": None,
    }
    data.update(extra)
    return data


@pytest.fixture
def gh() -> FakeGitHub:
    fake = FakeGitHub()
    fake.on("GET", f"{R}/commits/main", {"sha": MAIN})
    fake.on("GET", f"{R}/git/commits/{MAIN}", {"sha": MAIN, "tree": {"sha": MAIN_TREE}})
    fake.on(
        "GET",
        f"{R}/git/trees/{MAIN_TREE}",
        {
            "truncated": False,
            "tree": [
                {"path": "README.md", "type": "blob", "mode": "100644"},
                {"path": "ci", "type": "tree", "mode": "040000"},
                {"path": "ci/run.sh", "type": "blob", "mode": "100755"},
                {"path": "e2e/pages/login/locators.ts", "type": "blob", "mode": "100644"},
            ],
        },
    )
    return fake


@pytest.fixture
def forge(gh: FakeGitHub) -> GitHubForge:
    return GitHubForge(REPO, TokenAuth("tok-123"), transport=httpx.MockTransport(gh))


def content(text: str) -> dict[str, Any]:
    return {
        "type": "file",
        "encoding": "base64",
        "sha": "f" * 40,
        "content": base64.b64encode(text.encode()).decode(),
    }


# ----------------------------------------------------------------------- okuma


def test_protocol_ve_kimlik_basliklari(forge: GitHubForge, gh: FakeGitHub) -> None:
    assert isinstance(forge, ForgePort)
    assert forge.head_sha() == MAIN
    req = gh.calls[-1]
    assert req.headers["Authorization"] == "Bearer tok-123"
    assert req.headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_read_file(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/contents/e2e/pages/login/locators.ts", content("export const x = 1;\n"))
    assert forge.read_file("e2e/pages/login/locators.ts", "tp/fix") == "export const x = 1;\n"
    assert gh.calls[-1].url.params["ref"] == "tp/fix"
    gh.on("GET", f"{R}/contents/e2e", [{"type": "dir"}])
    with pytest.raises(ForgeNotFoundError):
        forge.read_file("e2e")
    with pytest.raises(ForgeNotFoundError):
        forge.read_file("yok.txt")
    with pytest.raises(ForgeValidationError):
        forge.read_file("../secret")


def test_read_file_buyuk_dosya_blob_api(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/contents/big.txt", {"type": "file", "encoding": "none", "sha": "f" * 40})
    gh.on("GET", f"{R}/git/blobs/{'f' * 40}", {"content": base64.b64encode(b"buyuk").decode()})
    assert forge.read_file("big.txt") == "buyuk"


def test_list_files(forge: GitHubForge, gh: FakeGitHub) -> None:
    assert forge.list_files() == ["README.md", "ci/run.sh", "e2e/pages/login/locators.ts"]
    assert forge.list_files("e2e/") == ["e2e/pages/login/locators.ts"]
    gh.on("GET", f"{R}/git/trees/{MAIN_TREE}", {"truncated": True, "tree": []})
    with pytest.raises(ForgeError, match="kesildi"):
        forge.list_files()


def test_search_code_depo_ile_sinirli(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on(
        "GET",
        "/search/code",
        {"items": [{"path": "web/src/Catalog.tsx"}, {"path": "web/src/Gone.tsx"}]},
    )
    gh.on(
        "GET",
        f"{R}/contents/web/src/Catalog.tsx",
        content('a\n<button data-testid="add-to-cart">\nb\n'),
    )
    hits = forge.search_code("add-to-cart", "tp/x")
    assert hits == [("web/src/Catalog.tsx", 2, '<button data-testid="add-to-cart">')]
    search = next(r for r in gh.calls if r.url.path == "/search/code")
    assert search.url.params["q"] == f'"add-to-cart" repo:{REPO}'


# ---------------------------------------------------------------------- commit


def _commit_routes(gh: FakeGitHub) -> None:
    gh.on("POST", f"{R}/git/trees", {"sha": NEW_TREE})
    gh.on("POST", f"{R}/git/commits", {"sha": NEW_COMMIT})
    gh.on("POST", f"{R}/git/refs", {"ref": "refs/heads/tp/fix"})


def test_commit_yeni_dal(forge: GitHubForge, gh: FakeGitHub) -> None:
    _commit_routes(gh)
    sha = forge.commit_files(
        "tp/fix", {"ci/run.sh": "#!/bin/sh\n", "e2e/a.ts": "x"}, "fix: locator"
    )
    assert sha == NEW_COMMIT
    tree = gh.body("POST", f"{R}/git/trees")
    assert tree["base_tree"] == MAIN_TREE
    modes = {e["path"]: e["mode"] for e in tree["tree"]}
    assert modes == {"ci/run.sh": "100755", "e2e/a.ts": "100644"}
    assert gh.body("POST", f"{R}/git/commits") == {
        "message": "fix: locator",
        "tree": NEW_TREE,
        "parents": [MAIN],
    }
    assert gh.body("POST", f"{R}/git/refs") == {"ref": "refs/heads/tp/fix", "sha": NEW_COMMIT}


def test_commit_var_olan_dal_fast_forward(forge: GitHubForge, gh: FakeGitHub) -> None:
    _commit_routes(gh)
    gh.on("GET", f"{R}/git/ref/heads/tp/fix", {"object": {"sha": MAIN}})
    gh.on("PATCH", f"{R}/git/refs/heads/tp/fix", {"object": {"sha": NEW_COMMIT}})
    assert forge.commit_files("tp/fix", {"a.txt": "1"}, "m") == NEW_COMMIT
    assert gh.body("PATCH", f"{R}/git/refs/heads/tp/fix") == {"sha": NEW_COMMIT, "force": False}
    assert gh.count("POST", f"{R}/git/refs") == 0


def test_commit_eszamanli_degisiklik(forge: GitHubForge, gh: FakeGitHub) -> None:
    _commit_routes(gh)
    gh.on("GET", f"{R}/git/ref/heads/tp/fix", {"object": {"sha": MAIN}})
    gh.on(
        "PATCH",
        f"{R}/git/refs/heads/tp/fix",
        lambda _r: httpx.Response(422, json={"message": "Update is not a fast forward"}),
    )
    with pytest.raises(ForgeConflictError):
        forge.commit_files("tp/fix", {"a.txt": "1"}, "m")


def test_commit_degisiklik_yok(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("POST", f"{R}/git/trees", {"sha": MAIN_TREE})
    gh.on("GET", f"{R}/git/ref/heads/tp/fix", {"object": {"sha": MAIN}})
    assert forge.commit_files("tp/fix", {"README.md": "x"}, "m") == MAIN
    assert gh.count("POST", f"{R}/git/commits") == 0


def test_commit_main_ve_gecersiz(forge: GitHubForge, gh: FakeGitHub) -> None:
    with pytest.raises(ForgeProtectionError):
        forge.commit_files("main", {"a": "x"}, "m")
    with pytest.raises(ForgeValidationError):
        forge.commit_files("--force", {"a": "x"}, "m")
    with pytest.raises(ForgeValidationError):
        forge.commit_files("tp/x", {"/etc/passwd": "x"}, "m")
    assert gh.calls == []


# ---------------------------------------------------------------------- PR


def test_open_pr_idempotent(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/pulls", [pr_json()])
    pr = forge.open_pr("tp/fix", "Locator onarımı", "gövde")
    assert pr.number == 7
    assert gh.calls[-1].url.params["head"] == "acme:tp/fix"
    assert gh.count("POST", f"{R}/pulls") == 0


def test_open_pr_yeni_etiketli(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/pulls", [])
    gh.on("POST", f"{R}/pulls", pr_json())
    gh.on("POST", f"{R}/issues/7/labels", [{"name": "tp-repair"}])
    pr = forge.open_pr("tp/fix", "Locator onarımı", "gövde", labels=["tp-repair"])
    assert pr.labels == ["tp-repair"]
    assert pr.url == f"https://github.com/{REPO}/pull/7"
    assert gh.body("POST", f"{R}/pulls") == {
        "title": "Locator onarımı",
        "head": "tp/fix",
        "base": "main",
        "body": "gövde",
    }
    assert gh.body("POST", f"{R}/issues/7/labels") == {"labels": ["tp-repair"]}


def test_get_pr_durumlari(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/pulls/7", pr_json(state="closed", merged_at="2026-01-01T00:00:00Z"))
    assert forge.get_pr(7).state == "merged"
    gh.on("GET", f"{R}/pulls/8", pr_json(8, state="closed"))
    assert forge.get_pr(8).state == "closed"


def test_comment_pr(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("POST", f"{R}/issues/7/comments", {"id": 1})
    forge.comment_pr(7, "CI kırmızı")
    assert gh.body("POST", f"{R}/issues/7/comments") == {"body": "CI kırmızı"}


def test_merge_bot_ve_token_yoksa_reddedilir(forge: GitHubForge, gh: FakeGitHub) -> None:
    with pytest.raises(ForgeProtectionError, match="bot"):
        forge.merge_pr(7, "tp-bot")
    with pytest.raises(ForgeProtectionError, match="GitHub arayüzünden"):
        forge.merge_pr(7, "ali")
    assert gh.count("PUT", f"{R}/pulls/7/merge") == 0


def ruleset_checks(**overrides: str) -> dict[str, Any]:
    """`.github/workflows/ci.yml` iş adları (= scripts/github-ruleset.sh CHECKS)."""
    names = {"test-local": "success", "ast-guard": "success", "semgrep": "success", **overrides}
    return {
        "check_runs": [
            {"name": n, "status": "completed", "conclusion": c} for n, c in names.items()
        ]
    }


@pytest.fixture
def merge_forge(gh: FakeGitHub) -> GitHubForge:
    gh.on("GET", f"{R}/pulls/7", pr_json())
    gh.on("PUT", f"{R}/pulls/7/merge", {"merged": True, "sha": NEW_COMMIT})
    return GitHubForge(
        REPO, TokenAuth("bot"), merge_auth=TokenAuth("human"), transport=httpx.MockTransport(gh)
    )


def test_merge_insan_tokeni_ile(merge_forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    result = merge_forge.merge_pr_detailed(7, "demo-admin")
    assert result.sha == NEW_COMMIT
    # Gerçek CI kontrolleri (test-local, ast-guard, semgrep) yeşil → bypass DEĞİL.
    assert result.bypass is False
    assert result.bypass_reason is None
    put = next(r for r in gh.calls if r.method == "PUT")
    assert put.headers["Authorization"] == "Bearer human"
    assert json.loads(put.content) == {"merge_method": "merge", "sha": BRANCH_HEAD}
    checks_req = next(r for r in gh.calls if r.url.path.endswith("/check-runs"))
    assert checks_req.url.params["filter"] == "latest"


def test_merge_local_ci_adi_github_kontrolu_sayilmaz(
    merge_forge: GitHubForge, gh: FakeGitHub
) -> None:
    gh.on(
        "GET",
        f"{R}/commits/{BRANCH_HEAD}/check-runs",
        {"check_runs": [{"name": "local-ci", "status": "completed", "conclusion": "success"}]},
    )
    result = merge_forge.merge_pr_detailed(7, "demo-admin")
    assert result.bypass is True
    assert "'test-local' durumu: yok" in (result.bypass_reason or "")


def test_merge_bir_kontrol_kirmiziysa_bypass(merge_forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks(semgrep="failure"))
    result = merge_forge.merge_pr_detailed(7, "demo-admin")
    assert result.bypass is True
    assert result.bypass_reason == "'semgrep' durumu: failure (ruleset bypass)"


@pytest.mark.parametrize(
    "runs",
    [
        ruleset_checks(semgrep="failure"),
        ruleset_checks(**{"test-local": "in_progress"}),
        {"check_runs": []},
    ],
)
def test_merge_kirmizi_kontrolde_bypass_aktoru_disindakiler_reddedilir(
    merge_forge: GitHubForge, gh: FakeGitHub, runs: dict[str, Any]
) -> None:
    """Merge token'ı ruleset bypass yetkili olsa da insan onaylayan kırmızı CI'ı merge edemez."""
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", runs)
    with pytest.raises(ForgeProtectionError, match="zorunlu kontroller"):
        merge_forge.merge_pr_detailed(7, "engineer1", expected_head_sha=BRANCH_HEAD)
    with pytest.raises(ForgeProtectionError, match="zorunlu kontroller"):
        merge_forge.merge_pr(7, "ali")
    assert gh.count("PUT", f"{R}/pulls/7/merge") == 0


def test_merge_ayni_adli_kontrollerde_en_gunceli_gecerli(
    merge_forge: GitHubForge, gh: FakeGitHub
) -> None:
    runs = ruleset_checks()["check_runs"]
    runs[0] |= {"started_at": "2026-01-01T10:00:00Z"}
    # API sırası garanti değil: daha yeni (başarısız) yeniden koşu listede önce gelse de geçerli.
    runs.insert(
        0,
        {"name": "test-local", "status": "completed", "conclusion": "failure",
         "started_at": "2026-01-01T11:00:00Z"},
    )  # fmt: skip
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", {"check_runs": runs})
    result = merge_forge.merge_pr_detailed(7, "demo-admin")
    assert result.bypass is True
    assert "'test-local' durumu: failure" in (result.bypass_reason or "")


def test_merge_kontrol_listesi_ortamdan(gh: FakeGitHub) -> None:
    forge = GitHubForge.from_env(
        {
            "GITHUB_REPO": REPO,
            "GITHUB_TOKEN": "bot",
            "GITHUB_MERGE_TOKEN": "human",
            "TP_REQUIRED_CHECKS": " test-local , e2e ,",
        },
        transport=httpx.MockTransport(gh),
    )
    assert forge.required_checks == ("test-local", "e2e")
    default = GitHubForge.from_env(
        {"GITHUB_REPO": REPO, "GITHUB_TOKEN": "bot"}, transport=httpx.MockTransport(gh)
    )
    assert default.required_checks == ("test-local", "ast-guard", "semgrep")
    with pytest.raises(ForgeValidationError):
        GitHubForge(REPO, TokenAuth("bot"), required_checks=())
    with pytest.raises(ForgeValidationError):
        GitHubForge(REPO, TokenAuth("bot"), required_checks=["ok", "kötü\nad"])


def test_merge_onaylanan_head_sha_gonderilir(merge_forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    assert merge_forge.merge_pr(7, "ali", expected_head_sha=BRANCH_HEAD) == NEW_COMMIT
    assert gh.body("PUT", f"{R}/pulls/7/merge")["sha"] == BRANCH_HEAD


def test_merge_head_onaydan_sonra_ilerlediyse_reddedilir(
    merge_forge: GitHubForge, gh: FakeGitHub
) -> None:
    approved = "d" * 40  # onaylanan sha; PR head'i şimdi BRANCH_HEAD
    with pytest.raises(ForgeConflictError, match="onaylanandan farklı"):
        merge_forge.merge_pr(7, "ali", expected_head_sha=approved)
    assert gh.count("PUT", f"{R}/pulls/7/merge") == 0
    with pytest.raises(ForgeValidationError):
        merge_forge.merge_pr(7, "ali", expected_head_sha="main")


def test_merge_github_409_catisma(merge_forge: GitHubForge, gh: FakeGitHub) -> None:
    """PR okunduktan sonra push geldi: GitHub sha uyuşmazlığında 409 döner."""
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    gh.on(
        "PUT",
        f"{R}/pulls/7/merge",
        lambda _r: httpx.Response(409, json={"message": "Head branch was modified."}),
    )
    with pytest.raises(ForgeConflictError, match="409"):
        merge_forge.merge_pr(7, "ali", expected_head_sha=BRANCH_HEAD)


def test_merge_ruleset_reddi(gh: FakeGitHub) -> None:
    forge = GitHubForge(
        REPO, TokenAuth("bot"), merge_auth=TokenAuth("human"), transport=httpx.MockTransport(gh)
    )
    gh.on("GET", f"{R}/pulls/7", pr_json())
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", {"check_runs": []})
    gh.on(
        "PUT",
        f"{R}/pulls/7/merge",
        lambda _r: httpx.Response(405, json={"message": "Required status check is expected"}),
    )
    # Kırmızı kontrolde yalnızca bypass aktörü PUT'a ulaşır; GitHub yine de reddedebilir.
    with pytest.raises(ForgeProtectionError, match="405"):
        forge.merge_pr(7, "demo-admin")
    assert gh.count("PUT", f"{R}/pulls/7/merge") == 1


def test_checks_eslemesi(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on(
        "GET",
        f"{R}/commits/{MAIN}/check-runs",
        {
            "check_runs": [
                {"name": "local-ci", "status": "completed", "conclusion": "success",
                 "html_url": "https://x/1"},
                {"name": "lint", "status": "completed", "conclusion": "neutral"},
                {"name": "e2e", "status": "completed", "conclusion": "timed_out"},
                {"name": "sauce", "status": "waiting", "conclusion": None},
            ]
        },
    )  # fmt: skip
    runs = forge.checks(MAIN)
    assert [(c.name, c.status, c.conclusion) for c in runs] == [
        ("local-ci", "completed", "success"),
        ("lint", "completed", "skipped"),
        ("e2e", "completed", "failure"),
        ("sauce", "queued", None),
    ]
    assert runs[0].url == "https://x/1"


# ---------------------------------------------------------------- App kimliği


@pytest.fixture(scope="module")
def rsa_pem() -> tuple[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def test_app_auth_jwt_kurulum_ve_onbellek(gh: FakeGitHub, rsa_pem: tuple[str, Any]) -> None:
    pem, public = rsa_pem
    now = [1_800_000_000.0 - 3600]  # token bitişinden 1 saat önce
    jwts: list[str] = []

    def installation(req: httpx.Request) -> dict[str, Any]:
        jwts.append(req.headers["Authorization"].removeprefix("Bearer "))
        return {"id": 42}

    tokens = iter(["inst-1", "inst-2"])
    gh.on("GET", f"{R}/installation", installation)
    gh.on(
        "POST",
        "/app/installations/42/access_tokens",
        lambda _r: {"token": next(tokens), "expires_at": "2027-01-15T08:00:00Z"},
    )
    auth = AppAuth("12345", pem, REPO, clock=lambda: now[0])
    forge = GitHubForge(REPO, auth, transport=httpx.MockTransport(gh))
    forge.head_sha()
    forge.head_sha()
    claims = jwt.decode(
        jwts[0],
        public,
        algorithms=["RS256"],
        options={"verify_iat": False, "verify_exp": False},  # sahte saat
    )
    assert claims["iss"] == "12345"
    assert claims["exp"] - claims["iat"] <= 600
    assert gh.count("POST", "/app/installations/42/access_tokens") == 1
    assert gh.calls[-1].headers["Authorization"] == "Bearer inst-1"
    # 2027-01-15T08:00:00Z = 1_800_000_000; bitişten 60 sn önce yenilenir
    now[0] = 1_800_000_000.0 - 30
    forge.head_sha()
    assert gh.count("POST", "/app/installations/42/access_tokens") == 2
    assert gh.calls[-1].headers["Authorization"] == "Bearer inst-2"
    assert gh.count("GET", f"{R}/installation") == 1  # kurulum id'si önbellekte


def test_401_bir_kez_yeniler(gh: FakeGitHub, rsa_pem: tuple[str, Any]) -> None:
    pem, _ = rsa_pem
    tokens = iter(["eski", "yeni"])
    gh.on(
        "POST",
        "/app/installations/9/access_tokens",
        lambda _r: {"token": next(tokens), "expires_at": "2099-01-01T00:00:00Z"},
    )
    gh.on(
        "GET",
        f"{R}/commits/main",
        lambda r: (
            httpx.Response(401, json={"message": "Bad credentials"})
            if r.headers["Authorization"] == "Bearer eski"
            else {"sha": MAIN}
        ),
    )
    forge = GitHubForge(REPO, AppAuth("1", pem, REPO, "9"), transport=httpx.MockTransport(gh))
    assert forge.head_sha() == MAIN


def test_from_env(rsa_pem: tuple[str, Any]) -> None:
    pem, _ = rsa_pem
    f = GitHubForge.from_env({"GITHUB_REPO": REPO, "GITHUB_TOKEN": "t"})
    assert isinstance(f._auth, TokenAuth)
    f = GitHubForge.from_env(
        {"GITHUB_REPO": REPO, "GH_APP_ID": "1", "GH_APP_PRIVATE_KEY": pem.replace("\n", "\\n")}
    )
    assert isinstance(f._auth, AppAuth)
    assert f._auth.private_key == pem
    assert isinstance(
        get_forge({"TP_FORGE": "github", "GITHUB_REPO": REPO, "GITHUB_READ_TOKEN": "r"}),
        GitHubForge,
    )
    with pytest.raises(ForgeValidationError, match="kimliği yok"):
        GitHubForge.from_env({"GITHUB_REPO": REPO})
    with pytest.raises(ForgeValidationError):
        GitHubForge.from_env({"GITHUB_TOKEN": "t"})
    with pytest.raises(ForgeValidationError):
        GitHubForge.from_env({"GITHUB_REPO": "../x", "GITHUB_TOKEN": "t"})
