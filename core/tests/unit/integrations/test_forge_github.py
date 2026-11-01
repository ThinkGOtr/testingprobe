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
    ForgeStateError,
    ForgeValidationError,
    get_forge,
)
from tp_core.integrations.forge_github import (
    AppAuth,
    GitHubForge,
    TokenAuth,
    qualifying_approvals,
)
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


def test_pr_merge_info(forge: GitHubForge, gh: FakeGitHub) -> None:
    """GitHub arayüzünde merge edilen PR'ın merge commit'i ve merge eden (çekirdek senkronu)."""
    merged = pr_json(state="closed", merged_at="2026-01-01T00:00:00Z")
    merged.update(merged=True, merge_commit_sha="f" * 40, merged_by={"login": "engineer1"})
    gh.on("GET", f"{R}/pulls/7", merged)
    assert forge.pr_merge_info(7) == {
        "merge_commit_sha": "f" * 40,
        "merged_by": {"login": "engineer1"},
    }
    acik = pr_json(8)
    acik.update(merge_commit_sha="a" * 40)  # GitHub test merge commit'i: merge sayılmaz
    gh.on("GET", f"{R}/pulls/8", acik)
    assert forge.pr_merge_info(8) == {"merge_commit_sha": None, "merged_by": None}


def test_comment_pr(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("POST", f"{R}/issues/7/comments", {"id": 1})
    forge.comment_pr(7, "CI kırmızı")
    assert gh.body("POST", f"{R}/issues/7/comments") == {"body": "CI kırmızı"}


# ------------------------------------------- dal güncelleme / kapatma (LocalForge ile eşlik)

UPDATED = "d" * 40


def update_routes(
    gh: FakeGitHub, *, behind: int = 2, gecikme: int = 1, parents: list[str] | None = None
) -> list[float]:
    """PR #7 (head BRANCH_HEAD) main'in `behind` commit gerisinde; PUT 202 sonrası head
    `gecikme` okuma sonra UPDATED olur (GitHub update-branch asenkrondur)."""
    okuma = {"n": 0}

    def pr(_r: httpx.Request) -> dict[str, Any]:
        okuma["n"] += 1
        guncel = gh.count("PUT", f"{R}/pulls/7/update-branch") and okuma["n"] > 1 + gecikme
        return pr_json(7, head={"ref": "tp/fix", "sha": UPDATED if guncel else BRANCH_HEAD})

    gh.on("GET", f"{R}/pulls/7", pr)
    gh.on("GET", f"{R}/compare/main...{BRANCH_HEAD}", {"behind_by": behind, "ahead_by": 1})
    gh.on(
        "PUT",
        f"{R}/pulls/7/update-branch",
        lambda _r: httpx.Response(202, json={"message": "Updating pull request branch."}),
    )
    gh.on(
        "GET",
        f"{R}/commits/{UPDATED}",
        {"sha": UPDATED, "parents": [{"sha": s} for s in (parents or [BRANCH_HEAD, MAIN])]},
    )
    uykular: list[float] = []
    return uykular


def update_forge(gh: FakeGitHub, uykular: list[float], **kw: Any) -> GitHubForge:
    return GitHubForge(
        REPO, TokenAuth("tok-123"), transport=httpx.MockTransport(gh), sleep=uykular.append,
        poll_interval_s=0.5, **kw,
    )  # fmt: skip


def test_update_branch_main_ile_gunceller_ve_yeni_head_doner(gh: FakeGitHub) -> None:
    uykular = update_routes(gh)
    forge = update_forge(gh, uykular)
    assert callable(getattr(forge, "update_branch", None))  # codegen._dal_guncellenebilir
    assert forge.update_branch(7) == UPDATED
    assert gh.body("PUT", f"{R}/pulls/7/update-branch") == {"expected_head_sha": BRANCH_HEAD}
    assert uykular == [0.5]  # 202 sonrası yeni head beklendi
    put = next(r for r in gh.calls if r.method == "PUT")
    assert put.headers["Authorization"] == "Bearer tok-123"  # bot (App) kimliği


def test_update_branch_beklenen_head_ile(gh: FakeGitHub) -> None:
    uykular = update_routes(gh)
    forge = update_forge(gh, uykular)
    with pytest.raises(ForgeStateError, match="beklenenden farklı"):
        forge.update_branch(7, expected_head_sha="e" * 40)
    assert gh.count("PUT", f"{R}/pulls/7/update-branch") == 0
    with pytest.raises(ForgeValidationError):
        forge.update_branch(7, expected_head_sha="abc")
    assert forge.update_branch(7, expected_head_sha=BRANCH_HEAD) == UPDATED


def test_update_branch_dal_gunceldeyse_yazmaz(gh: FakeGitHub) -> None:
    uykular = update_routes(gh, behind=0)
    forge = update_forge(gh, uykular)
    assert forge.update_branch(7) == BRANCH_HEAD
    assert gh.count("PUT", f"{R}/pulls/7/update-branch") == 0


@pytest.mark.parametrize(
    ("mesaj", "hata"),
    [
        ("merge conflict between base and head", ForgeConflictError),
        ("expected head sha didn't match current head ref.", ForgeStateError),
    ],
)
def test_update_branch_github_422_eslemesi(
    gh: FakeGitHub, mesaj: str, hata: type[Exception]
) -> None:
    uykular = update_routes(gh)
    gh.on("PUT", f"{R}/pulls/7/update-branch",
          lambda _r: httpx.Response(422, json={"message": mesaj}))  # fmt: skip
    with pytest.raises(hata):
        update_forge(gh, uykular).update_branch(7)


def test_update_branch_yaris_no_new_commits_ayni_head(gh: FakeGitHub) -> None:
    uykular = update_routes(gh)
    gh.on("PUT", f"{R}/pulls/7/update-branch",
          lambda _r: httpx.Response(422, json={"message": "There are no new commits on the "
                                                          "base branch."}))  # fmt: skip
    assert update_forge(gh, uykular).update_branch(7) == BRANCH_HEAD


def test_update_branch_yabanci_yeni_head_kabul_edilmez(gh: FakeGitHub) -> None:
    uykular = update_routes(gh, parents=["e" * 40, MAIN])  # eski head ebeveyn değil
    with pytest.raises(ForgeStateError, match="başka biri"):
        update_forge(gh, uykular).update_branch(7)


def test_update_branch_yeni_head_gelmezse_zaman_asimi(gh: FakeGitHub) -> None:
    uykular = update_routes(gh, gecikme=10_000)
    with pytest.raises(ForgeError, match="görünmedi"):
        update_forge(gh, uykular, update_wait_s=0).update_branch(7)


def test_update_branch_kapali_pr_ve_gecersiz_girdi(gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/pulls/7", pr_json(7, state="closed"))
    forge = update_forge(gh, [])
    with pytest.raises(ForgeStateError, match="açık değil"):
        forge.update_branch(7)
    with pytest.raises(ForgeValidationError):
        forge.update_branch(0)
    with pytest.raises(ForgeValidationError):
        forge.update_branch(7, actor="kötü aktör;")


def test_close_pr(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/pulls/7", pr_json(7))
    gh.on("PATCH", f"{R}/pulls/7", pr_json(7, state="closed"))
    forge.close_pr(7)
    assert gh.body("PATCH", f"{R}/pulls/7") == {"state": "closed"}


@pytest.mark.parametrize("ek", [{"state": "closed"}, {"merged_at": "2026-10-31T10:00:00Z"}])
def test_close_pr_acik_degilse_reddeder(
    forge: GitHubForge, gh: FakeGitHub, ek: dict[str, Any]
) -> None:
    gh.on("GET", f"{R}/pulls/7", pr_json(7, **ek))
    with pytest.raises(ForgeStateError, match="açık değil"):
        forge.close_pr(7)
    assert gh.count("PATCH", f"{R}/pulls/7") == 0


def test_close_pr_yanit_kapali_degilse_hata(forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/pulls/7", pr_json(7))
    gh.on("PATCH", f"{R}/pulls/7", pr_json(7))
    with pytest.raises(ForgeError, match="kapatılamadı"):
        forge.close_pr(7)


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


def review(
    login: str, state: str = "APPROVED", commit: str = BRANCH_HEAD, **user: Any
) -> dict[str, Any]:
    return {"user": {"login": login, "type": "User", **user}, "state": state, "commit_id": commit}


def approved_routes(gh: FakeGitHub, *reviews: dict[str, Any]) -> None:
    """Ruleset'in istediği insan GitHub onayı (varsayılan: engineer1 head'i onayladı)."""
    gh.on("GET", f"{R}/pulls/7/reviews", list(reviews) or [review("engineer1")])
    gh.on("GET", "/user", {"login": "demo-admin-gh"})


@pytest.fixture
def merge_forge(gh: FakeGitHub) -> GitHubForge:
    gh.on("GET", f"{R}/pulls/7", pr_json())
    gh.on("PUT", f"{R}/pulls/7/merge", {"merged": True, "sha": NEW_COMMIT})
    approved_routes(gh)
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
    assert result.github_onaylayanlar == ["engineer1"]
    assert result.github_merge_eden == "demo-admin-gh"
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
    assert result.bypass_reason == (
        "'semgrep' durumu: failure (ruleset bypass; GitHub'da merge eden: demo-admin-gh)"
    )


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
    approved_routes(gh)
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


# ------------------------------------------------- GitHub review'u (ruleset: 1 insan onayı)


def test_onay_sayimi_kullanici_basina_son_karar() -> None:
    reviews = [
        review("ayse"),
        review("ayse", "COMMENTED"),  # yorum kararı değiştirmez
        review("mehmet"),
        review("mehmet", "CHANGES_REQUESTED"),  # sonra değişiklik istedi
        review("eski", commit="e" * 40),  # bayat commit (dismiss_stale_reviews_on_push)
        review("tp-bot[bot]", type="Bot"),
        review("tp-bot"),
        review("geri", "APPROVED"),
        review("geri", "DISMISSED"),
        {"user": None, "state": "APPROVED", "commit_id": BRANCH_HEAD},
    ]
    assert qualifying_approvals(reviews, BRANCH_HEAD) == ["ayse"]


@pytest.mark.parametrize(
    "reviews",
    [
        [],
        [review("engineer1", commit="e" * 40)],
        [review("tp-bot[bot]", type="Bot")],
        [review("engineer1", "CHANGES_REQUESTED")],
    ],
)
def test_github_onayi_yoksa_muhendis_merge_edemez(
    merge_forge: GitHubForge, gh: FakeGitHub, reviews: list[dict[str, Any]]
) -> None:
    """Bypass token'ı review gereksinimini sessizce atlatamaz: PUT gönderilmez."""
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    gh.on("GET", f"{R}/pulls/7/reviews", reviews)
    with pytest.raises(ForgeProtectionError, match="onaylı insan review'u yok") as exc:
        merge_forge.merge_pr_detailed(7, "engineer1", expected_head_sha=BRANCH_HEAD)
    assert "GitHub'da onaylayın" in str(exc.value)
    assert gh.count("PUT", f"{R}/pulls/7/merge") == 0


def test_github_onayi_yoksa_demo_admin_merge_eder_ve_bypass_kaydedilir(
    merge_forge: GitHubForge, gh: FakeGitHub
) -> None:
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    gh.on("GET", f"{R}/pulls/7/reviews", [])
    result = merge_forge.merge_pr_detailed(7, "demo-admin", expected_head_sha=BRANCH_HEAD)
    assert result.bypass is True
    assert result.bypass_reason == (
        f"GitHub'da head {BRANCH_HEAD[:12]} için onaylı insan review'u yok "
        "(ruleset bypass; GitHub'da merge eden: demo-admin-gh)"
    )
    assert result.github_onaylayanlar == []
    # sha-only port da aynı yoldan geçer
    assert merge_forge.merge_pr(7, "demo-admin") == NEW_COMMIT


def test_github_onayi_varsa_muhendis_merge_eder_bypass_degil(
    merge_forge: GitHubForge, gh: FakeGitHub
) -> None:
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    result = merge_forge.merge_pr_detailed(7, "engineer1", expected_head_sha=BRANCH_HEAD)
    assert result.bypass is False and result.bypass_reason is None
    assert result.github_onaylayanlar == ["engineer1"]
    reviews_req = next(r for r in gh.calls if r.url.path.endswith("/reviews"))
    assert reviews_req.headers["Authorization"] == "Bearer bot"
    user_req = next(r for r in gh.calls if r.url.path == "/user")
    assert user_req.headers["Authorization"] == "Bearer human"
    # Portal kimseye adına GitHub review'u göndermez.
    assert gh.count("POST", f"{R}/pulls/7/reviews") == 0


def test_mergeable_state_blocked_bypass_sayilir(merge_forge: GitHubForge, gh: FakeGitHub) -> None:
    """Kontroller ve onay var ama GitHub başka bir kural (ör. CODEOWNERS) nedeniyle engelliyor."""
    gh.on("GET", f"{R}/pulls/7", pr_json(mergeable_state="blocked"))
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    with pytest.raises(ForgeProtectionError, match="mergeable_state=blocked"):
        merge_forge.merge_pr_detailed(7, "engineer1", expected_head_sha=BRANCH_HEAD)
    assert gh.count("PUT", f"{R}/pulls/7/merge") == 0
    result = merge_forge.merge_pr_detailed(7, "demo-admin", expected_head_sha=BRANCH_HEAD)
    assert result.bypass is True
    assert "mergeable_state=blocked" in (result.bypass_reason or "")


def test_review_listesi_okunamazsa_merge_yapilmaz(merge_forge: GitHubForge, gh: FakeGitHub) -> None:
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    gh.on("GET", f"{R}/pulls/7/reviews", lambda _r: httpx.Response(403, json={"message": "x"}))
    with pytest.raises(ForgeError):
        merge_forge.merge_pr_detailed(7, "demo-admin", expected_head_sha=BRANCH_HEAD)
    assert gh.count("PUT", f"{R}/pulls/7/merge") == 0


def test_merge_token_kimligi_alinamazsa_bilinmiyor(
    merge_forge: GitHubForge, gh: FakeGitHub
) -> None:
    gh.on("GET", f"{R}/commits/{BRANCH_HEAD}/check-runs", ruleset_checks())
    gh.on("GET", f"{R}/pulls/7/reviews", [])
    gh.on("GET", "/user", lambda _r: httpx.Response(403, json={"message": "x"}))
    result = merge_forge.merge_pr_detailed(7, "demo-admin", expected_head_sha=BRANCH_HEAD)
    assert result.github_merge_eden is None
    assert "GitHub'da merge eden: bilinmiyor" in (result.bypass_reason or "")


def test_review_sayfalama(merge_forge: GitHubForge, gh: FakeGitHub) -> None:
    first = [review(f"u{i}", "COMMENTED") for i in range(100)]

    def pages(req: httpx.Request) -> list[dict[str, Any]]:
        return first if req.url.params["page"] == "1" else [review("son")]

    gh.on("GET", f"{R}/pulls/7/reviews", pages)
    assert len(merge_forge.pr_reviews(7)) == 101


def test_changed_paths_tek_compare_cagrisi(forge: GitHubForge, gh: FakeGitHub) -> None:
    a, b = "a" * 40, "b" * 40
    gh.on(
        "GET",
        f"{R}/compare/{a}...{b}",
        {"files": [{"filename": "x.ts"}, {"filename": "y/z.ts", "previous_filename": "y/old.ts"}]},
    )
    assert forge.changed_paths(a, b) == ["x.ts", "y/old.ts", "y/z.ts"]
    gh.on("GET", f"{R}/compare/{a}...{b}", {"files": [{"filename": f"f{i}"} for i in range(300)]})
    assert forge.changed_paths(a, b) is None  # GitHub listesi kesilmiş olabilir → tam karşılaştırma


def test_merge_base_compare_cagrisindan(forge: GitHubForge, gh: FakeGitHub) -> None:
    """Demo kırılma farkı doğrulaması ortak atayı compare `merge_base_commit`'ten alır."""
    b = "b" * 40
    gh.on("GET", f"{R}/compare/main...{b}", {"merge_base_commit": {"sha": "c" * 40}})
    assert forge.merge_base("main", b) == "c" * 40
    gh.on("GET", f"{R}/compare/main...{b}", {"merge_base_commit": None})
    with pytest.raises(ForgeError, match="ortak ata"):
        forge.merge_base("main", b)


def test_olmayan_dal_head_sha_bulunamadi_sayilir(forge: GitHubForge, gh: FakeGitHub) -> None:
    # GitHub var olmayan ref için 404 değil 422 "No commit found" döner (codegen dal seçimi).
    gh.on(
        "GET",
        f"{R}/commits/tp/case-yok",
        lambda _r: httpx.Response(422, json={"message": "No commit found for SHA: tp/case-yok"}),
    )
    gh.on("GET", f"{R}/commits/kotu", lambda _r: httpx.Response(422, json={"message": "Bad"}))
    with pytest.raises(ForgeNotFoundError):
        forge.head_sha("tp/case-yok")
    with pytest.raises(ForgeValidationError):
        forge.head_sha("kotu")
