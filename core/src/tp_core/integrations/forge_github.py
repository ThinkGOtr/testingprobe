"""GitHubForge: GitHub REST v3 üzerinde `ForgePort` (httpx).

Kimlik (öncelik sırasıyla):
1. GitHub App: `GH_APP_ID` + `GH_APP_PRIVATE_KEY` (PEM, `\\n` kaçışlı olabilir) veya
   `GH_APP_PRIVATE_KEY_PATH`; isteğe bağlı `GH_APP_INSTALLATION_ID` (yoksa depodan bulunur).
   RS256 JWT → kurulum token'ı; token süresi dolmadan 60 sn önce yenilenir (önbellekli).
2. `GITHUB_TOKEN`, yoksa `GITHUB_READ_TOKEN` (yalnızca okuma).

Depo: `GITHUB_REPO` (`sahip/ad`); API: `GITHUB_API_URL` (varsayılan https://api.github.com).

Merge: anayasa gereği bot PR merge etmez. `merge_pr` yalnızca insan hesabının token'ı
(`GITHUB_MERGE_TOKEN`, ör. demo-admin) tanımlıysa çalışır; aksi halde reddedilir ve merge
GitHub arayüzünden yapılır. Dal koruması ve bypass GitHub ruleset'inde uygulanır.
Zorunlu kontroller `TP_REQUIRED_CHECKS` (varsayılan `test-local,ast-guard,semgrep` =
`scripts/github-ruleset.sh` CHECKS); hepsi başarılı değilse yalnızca `BYPASS_ACTOR` (demo-admin)
merge edebilir ve sonuç bypass sayılır; diğer aktörler PUT gönderilmeden reddedilir (LocalForge
ile aynı kural; merge token'ının ruleset bypass yetkisine güvenilmez).
`merge_pr(..., expected_head_sha=...)` onaylanan head'i GitHub'a `sha` olarak iletir; dal onaydan
sonra ilerlediyse GitHub 409 döner → `ForgeConflictError` (anayasa I: onaylanan içerik).

Kod araması GitHub arama API'siyle aday dosyaları bulur (yalnızca bu depo; arama dizini
varsayılan dalı kapsar), satırlar ise istenen ref'teki dosya içeriğinden sabit metinle çıkarılır.
"""

from __future__ import annotations

import base64
import os
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx
import jwt

from tp_core.integrations.forge import (
    BOT_ACTORS,
    BYPASS_ACTOR,
    GITHUB_REQUIRED_CHECKS,
    PROTECTED_BRANCHES,
    REQUIRED_CHECKS_ENV,
    ForgeConflictError,
    ForgeError,
    ForgeNotFoundError,
    ForgeProtectionError,
    ForgeValidationError,
    MergeResult,
    evaluate_required_checks,
    is_sha,
    parse_required_checks,
    validate_actor,
    validate_branch,
    validate_files,
    validate_label,
    validate_message,
    validate_path,
    validate_prefix,
    validate_query,
    validate_ref,
    validate_required_checks,
)
from tp_core.ports import CheckRun, PullRequest

DEFAULT_API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
_MAX_SEARCH_CANDIDATES = 20
_MAX_SEARCH_RESULTS = 500

_CONCLUSIONS = {
    "success": "success",
    "failure": "failure",
    "cancelled": "cancelled",
    "skipped": "skipped",
    "neutral": "skipped",
    "stale": "cancelled",
    "timed_out": "failure",
    "action_required": "failure",
    "startup_failure": "failure",
}
_STATUSES = {"queued": "queued", "in_progress": "in_progress", "completed": "completed"}


class GitHubAuth(Protocol):
    def token(self, client: httpx.Client) -> str: ...
    def invalidate(self) -> None: ...


class TokenAuth:
    """Sabit kişisel/ince ayarlı token."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ForgeValidationError("GitHub token boş")
        self._token = token

    def token(self, client: httpx.Client) -> str:
        return self._token

    def invalidate(self) -> None:
        pass


class AppAuth:
    """GitHub App: JWT ile kurulum token'ı alır ve önbellekler."""

    def __init__(
        self,
        app_id: str,
        private_key: str,
        repo: str,
        installation_id: str | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not app_id or not private_key:
            raise ForgeValidationError("GitHub App kimliği eksik")
        self.app_id = str(app_id)
        self.private_key = private_key
        self.repo = repo
        self.installation_id = installation_id
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: tuple[str, float] | None = None  # (token, bitiş epoch)

    def app_jwt(self) -> str:
        now = int(self._clock())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def token(self, client: httpx.Client) -> str:
        with self._lock:
            if self._cached and self._cached[1] - 60 > self._clock():
                return self._cached[0]
            headers = {"Authorization": f"Bearer {self.app_jwt()}"}
            if not self.installation_id:
                resp = client.get(f"/repos/{self.repo}/installation", headers=headers)
                _raise_for(resp, "App kurulumu")
                self.installation_id = str(resp.json()["id"])
            resp = client.post(
                f"/app/installations/{self.installation_id}/access_tokens", headers=headers
            )
            _raise_for(resp, "kurulum token'ı")
            body = resp.json()
            expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00")).timestamp()
            self._cached = (body["token"], expires)
            return body["token"]

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None


def _raise_for(resp: httpx.Response, what: str) -> None:
    if resp.is_success:
        return
    try:
        detail = resp.json().get("message", "")
    except ValueError:
        detail = resp.text[:200]
    msg = f"GitHub {what}: HTTP {resp.status_code} {detail}".strip()
    code = resp.status_code
    if code == 404:
        raise ForgeNotFoundError(msg)
    if code == 409:
        raise ForgeConflictError(msg)
    if code in (403, 405):
        raise ForgeProtectionError(msg)
    if code == 422:
        raise ForgeValidationError(msg)
    raise ForgeError(msg)


def _q(value: str) -> str:
    return quote(value, safe="/")


class GitHubForge:
    """GitHub REST ile `ForgePort`."""

    def __init__(
        self,
        repo: str,
        auth: GitHubAuth,
        *,
        api_url: str = DEFAULT_API_URL,
        merge_auth: GitHubAuth | None = None,
        required_checks: Sequence[str] = GITHUB_REQUIRED_CHECKS,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not _REPO_RE.match(repo or ""):
            raise ForgeValidationError(f"geçersiz GITHUB_REPO: {repo!r} (sahip/ad)")
        self.repo = repo
        self.owner = repo.split("/", 1)[0]
        self._auth = auth
        self._merge_auth = merge_auth
        self.required_checks = validate_required_checks(required_checks)
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            transport=transport,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "testing-probe",
            },
        )

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, *, transport: httpx.BaseTransport | None = None
    ) -> GitHubForge:
        env = os.environ if env is None else env
        repo = (env.get("GITHUB_REPO") or "").strip()
        if not repo:
            raise ForgeValidationError("TP_FORGE=github için GITHUB_REPO gerekli")
        auth: GitHubAuth
        app_id = (env.get("GH_APP_ID") or "").strip()
        key = env.get("GH_APP_PRIVATE_KEY") or ""
        key_path = env.get("GH_APP_PRIVATE_KEY_PATH") or ""
        if app_id and (key or key_path):
            pem = key.replace("\\n", "\n") if key else Path(key_path).read_text(encoding="utf-8")
            auth = AppAuth(app_id, pem, repo, env.get("GH_APP_INSTALLATION_ID") or None)
        elif env.get("GITHUB_TOKEN"):
            auth = TokenAuth(env["GITHUB_TOKEN"])
        elif env.get("GITHUB_READ_TOKEN"):
            auth = TokenAuth(env["GITHUB_READ_TOKEN"])
        else:
            raise ForgeValidationError(
                "GitHub kimliği yok: GH_APP_ID + GH_APP_PRIVATE_KEY(_PATH) veya GITHUB_TOKEN"
            )
        merge_token = env.get("GITHUB_MERGE_TOKEN") or ""
        return cls(
            repo,
            auth,
            api_url=env.get("GITHUB_API_URL") or DEFAULT_API_URL,
            merge_auth=TokenAuth(merge_token) if merge_token else None,
            required_checks=parse_required_checks(
                env.get(REQUIRED_CHECKS_ENV), GITHUB_REQUIRED_CHECKS
            ),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ HTTP

    def _request(
        self,
        method: str,
        path: str,
        what: str,
        *,
        auth: GitHubAuth | None = None,
        **kw: Any,
    ) -> httpx.Response:
        auth = auth or self._auth
        extra = kw.pop("headers", {})
        for attempt in range(2):
            headers = {**extra, "Authorization": f"Bearer {auth.token(self._client)}"}
            resp = self._client.request(method, path, headers=headers, **kw)
            if resp.status_code == 401 and attempt == 0:
                auth.invalidate()  # süresi dolmuş kurulum token'ı → bir kez yenile
                continue
            _raise_for(resp, what)
            return resp
        raise ForgeError(f"GitHub {what}: kimlik doğrulanamadı")  # pragma: no cover

    def _get(self, path: str, what: str, **kw: Any) -> Any:
        return self._request("GET", path, what, **kw).json()

    def _post(self, path: str, what: str, body: Any, **kw: Any) -> Any:
        return self._request("POST", path, what, json=body, **kw).json()

    @property
    def _r(self) -> str:
        return f"/repos/{self.repo}"

    # ------------------------------------------------------------------ okuma

    def head_sha(self, ref: str = "main") -> str:
        validate_ref(ref)
        return self._get(f"{self._r}/commits/{_q(ref)}", f"ref {ref}")["sha"]

    def read_file(self, path: str, ref: str = "main") -> str:
        validate_path(path)
        validate_ref(ref)
        data = self._get(f"{self._r}/contents/{_q(path)}", f"dosya {path}", params={"ref": ref})
        if not isinstance(data, dict) or data.get("type") != "file":
            raise ForgeNotFoundError(f"dosya değil: {path} @ {ref}")
        if data.get("encoding") == "base64" and data.get("content") is not None:
            raw = base64.b64decode(data["content"])
        else:  # >1 MB: içerik boş gelir, blob API'den alınır
            blob = self._get(f"{self._r}/git/blobs/{data['sha']}", f"blob {path}")
            raw = base64.b64decode(blob["content"])
        return raw.decode("utf-8", "replace")

    def _tree(self, ref: str) -> list[dict[str, Any]]:
        sha = ref if is_sha(ref) else self.head_sha(ref)
        commit = self._get(f"{self._r}/git/commits/{sha}", "commit")
        tree = self._get(
            f"{self._r}/git/trees/{commit['tree']['sha']}", "ağaç", params={"recursive": "1"}
        )
        if tree.get("truncated"):
            raise ForgeError("GitHub ağaç listesi kesildi (depo çok büyük)")
        return list(tree.get("tree", []))

    def list_files(self, prefix: str = "", ref: str = "main") -> list[str]:
        validate_prefix(prefix)
        validate_ref(ref)
        blobs = (e["path"] for e in self._tree(ref) if e["type"] == "blob")
        return sorted(p for p in blobs if p.startswith(prefix))

    def search_code(self, query: str, ref: str = "main") -> list[tuple[str, int, str]]:
        validate_query(query)
        validate_ref(ref)
        term = f'"{query}"' if '"' not in query else query.replace('"', " ")
        data = self._get(
            "/search/code",
            "kod araması",
            params={"q": f"{term} repo:{self.repo}", "per_page": _MAX_SEARCH_CANDIDATES},
        )
        paths = sorted({item["path"] for item in data.get("items", [])})
        results: list[tuple[str, int, str]] = []
        for path in paths:
            try:
                text = self.read_file(path, ref)
            except ForgeNotFoundError:
                continue  # dosya bu ref'te yok
            for no, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    results.append((path, no, line))
                    if len(results) >= _MAX_SEARCH_RESULTS:
                        return results
        return results

    # ------------------------------------------------------------------ yazma

    def commit_files(
        self, branch: str, files: Mapping[str, str], message: str, base: str = "main"
    ) -> str:
        validate_branch(branch)
        if branch in PROTECTED_BRANCHES:
            raise ForgeProtectionError(f"'{branch}' korunan dal: doğrudan commit yok, PR açın")
        blobs = validate_files(files)
        validate_message(message)
        validate_ref(base)

        try:
            ref = self._get(f"{self._r}/git/ref/heads/{_q(branch)}", f"dal {branch}")
            old: str | None = ref["object"]["sha"]
        except ForgeNotFoundError:
            old = None
        parent = old or self.head_sha(base)
        parent_commit = self._get(f"{self._r}/git/commits/{parent}", "commit")
        parent_tree = parent_commit["tree"]["sha"]
        modes = {e["path"]: e["mode"] for e in self._tree(parent) if e["type"] == "blob"}

        entries = [
            {
                "path": path,
                "mode": "100755" if modes.get(path) == "100755" else "100644",
                "type": "blob",
                "content": data.decode("utf-8"),
            }
            for path, data in blobs.items()
        ]
        tree = self._post(
            f"{self._r}/git/trees", "ağaç oluşturma", {"base_tree": parent_tree, "tree": entries}
        )
        if tree["sha"] == parent_tree:
            new = parent
        else:
            commit = self._post(
                f"{self._r}/git/commits",
                "commit oluşturma",
                {"message": message, "tree": tree["sha"], "parents": [parent]},
            )
            new = commit["sha"]
        if old is None:
            self._post(
                f"{self._r}/git/refs", "dal oluşturma", {"ref": f"refs/heads/{branch}", "sha": new}
            )
        elif new != old:
            try:
                self._request(
                    "PATCH",
                    f"{self._r}/git/refs/heads/{_q(branch)}",
                    "dal güncelleme",
                    json={"sha": new, "force": False},
                )
            except ForgeValidationError as exc:  # fast-forward değil: dal eşzamanlı değişti
                raise ForgeConflictError(f"'{branch}' eşzamanlı değişti: {exc}") from exc
        return new

    # ------------------------------------------------------------------ PR

    @staticmethod
    def _pr(data: Mapping[str, Any]) -> PullRequest:
        if data.get("merged_at") or data.get("merged"):
            state = "merged"
        else:
            state = "open" if data.get("state") == "open" else "closed"
        return PullRequest(
            number=data["number"],
            branch=data["head"]["ref"],
            base=data["base"]["ref"],
            title=data.get("title") or "",
            body=data.get("body") or "",
            state=state,
            head_sha=data["head"]["sha"],
            url=data.get("html_url"),
            labels=[lbl["name"] for lbl in data.get("labels", [])],
        )

    def find_open_pr(self, branch: str) -> PullRequest | None:
        validate_branch(branch)
        items = self._get(
            f"{self._r}/pulls",
            "PR listesi",
            params={"state": "open", "head": f"{self.owner}:{branch}", "per_page": 10},
        )
        for item in items:
            if item["head"]["ref"] == branch:
                return self._pr(item)
        return None

    def open_pr(
        self, branch: str, title: str, body: str, labels: Sequence[str] = ()
    ) -> PullRequest:
        validate_branch(branch)
        if branch in PROTECTED_BRANCHES:
            raise ForgeValidationError("korunan daldan PR açılamaz")
        if not isinstance(title, str) or not title.strip() or len(title) > 256:
            raise ForgeValidationError("PR başlığı boş veya çok uzun")
        clean = list(dict.fromkeys(validate_label(lbl) for lbl in labels))
        existing = self.find_open_pr(branch)
        if existing:
            return existing
        data = self._post(
            f"{self._r}/pulls",
            "PR açma",
            {"title": title, "head": branch, "base": "main", "body": body},
        )
        pr = self._pr(data)
        if clean:
            self._post(f"{self._r}/issues/{pr.number}/labels", "etiket", {"labels": clean})
            pr = pr.model_copy(update={"labels": list(dict.fromkeys([*pr.labels, *clean]))})
        return pr

    def get_pr(self, number: int) -> PullRequest:
        return self._pr(self._get(f"{self._r}/pulls/{int(number)}", f"PR #{number}"))

    def merge_pr(self, number: int, actor: str, *, expected_head_sha: str | None = None) -> str:
        return self.merge_pr_detailed(number, actor, expected_head_sha=expected_head_sha).sha

    def merge_pr_detailed(
        self, number: int, actor: str, *, expected_head_sha: str | None = None
    ) -> MergeResult:
        """PR'ı insan token'ıyla merge eder.

        `expected_head_sha` verilirse (onaylanan head) GitHub'a `sha` olarak gönderilir: dal
        bu sha'da değilse GitHub 409 döner ve merge yapılmaz. Verilmezse PR'ın o anki head'i
        kullanılır (yalnızca onay bağlamı olmayan çağrılar için; iş akışları sha'yı vermelidir).
        """
        validate_actor(actor)
        if expected_head_sha is not None and not is_sha(expected_head_sha):
            raise ForgeValidationError(f"geçersiz beklenen head sha: {expected_head_sha!r}")
        if actor in BOT_ACTORS:
            raise ForgeProtectionError("bot PR merge edemez; merge insan onayı gerektirir")
        if self._merge_auth is None:
            raise ForgeProtectionError(
                "GitHub modunda merge GitHub arayüzünden insan tarafından yapılır "
                "(GITHUB_MERGE_TOKEN tanımlı değil)"
            )
        pr = self.get_pr(number)
        if pr.state != "open":
            raise ForgeConflictError(f"PR #{number} açık değil ({pr.state})")
        head = expected_head_sha or pr.head_sha
        if head != pr.head_sha:
            raise ForgeConflictError(
                f"PR #{number} head'i onaylanandan farklı "
                f"(beklenen {head[:12]}, güncel {pr.head_sha[:12]}); yeniden onay gerekli"
            )
        checks = self.checks(head)
        verdict = evaluate_required_checks(checks, self.required_checks)
        # Merge token'ı (ör. demo-admin) ruleset bypass yetkisine sahip olabilir; kontroller
        # kırmızıyken yalnızca BYPASS_ACTOR merge edebilir (LocalForge ile aynı kural).
        if not verdict.passed and actor != BYPASS_ACTOR:
            raise ForgeProtectionError(
                f"merge için zorunlu kontroller başarılı olmalı ({verdict.reason()})"
            )
        resp = self._request(
            "PUT",
            f"{self._r}/pulls/{int(number)}/merge",
            f"PR #{number} merge",
            auth=self._merge_auth,
            json={"merge_method": "merge", "sha": head},
        ).json()
        if not resp.get("merged"):
            raise ForgeConflictError(f"PR #{number} merge edilemedi: {resp.get('message', '')}")
        return MergeResult(
            number=number,
            sha=resp["sha"],
            actor=actor,
            method="merge-commit",
            bypass=not verdict.passed,
            bypass_reason=None if verdict.passed else f"{verdict.reason()} (ruleset bypass)",
            checks=checks,
        )

    def comment_pr(self, number: int, body: str) -> None:
        if not isinstance(body, str) or not body.strip():
            raise ForgeValidationError("yorum boş olamaz")
        self._post(f"{self._r}/issues/{int(number)}/comments", "PR yorumu", {"body": body})

    def checks(self, sha: str) -> list[CheckRun]:
        validate_ref(sha)
        data = self._get(
            f"{self._r}/commits/{_q(sha)}/check-runs",
            "kontroller",
            params={"per_page": 100, "filter": "latest"},
        )
        runs: list[CheckRun] = []
        # Sıra: eskiden yeniye (started_at); aynı adlı koşularda son girdi en günceldir.
        items = sorted(
            data.get("check_runs", []),
            key=lambda it: it.get("started_at") or it.get("completed_at") or "",
        )
        for item in items:
            status = _STATUSES.get(item.get("status", ""), "queued")
            conclusion = None
            if status == "completed":
                conclusion = _CONCLUSIONS.get(item.get("conclusion") or "", "failure")
            runs.append(
                CheckRun(
                    name=item["name"],
                    status=status,  # type: ignore[arg-type]
                    conclusion=conclusion,  # type: ignore[arg-type]
                    url=item.get("html_url"),
                )
            )
        return runs
