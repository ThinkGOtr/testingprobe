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
Ruleset (`scripts/github-ruleset.sh`) merge için şunları ister; portal merge'ü PUT'tan önce aynı
kuralları kendisi değerlendirir, çünkü tek merge token'ı ruleset bypass aktörüne (demo-admin)
ait olabilir ve GitHub bu durumda eksikleri SESSİZCE atlar:
- zorunlu kontroller `TP_REQUIRED_CHECKS` (varsayılan `test-local,ast-guard,semgrep` =
  ruleset CHECKS) head commit'inde başarılı;
- head commit'ini (`dismiss_stale_reviews_on_push`) onaylayan en az bir insan GitHub review'u
  (kullanıcı başına son karar `APPROVED`; bot hesapları sayılmaz);
- GitHub'ın PR için bildirdiği `mergeable_state` `blocked` değil (ör. CODEOWNERS onayı eksik).
Biri eksikse yalnızca `BYPASS_ACTOR` (demo-admin) merge edebilir ve sonuç bypass sayılır
(`MergeResult.bypass=True`, `bypass_reason` eksikleri ve GitHub'da merge eden token sahibini
yazar); diğer aktörler PUT gönderilmeden reddedilir: önce PR GitHub'da insan tarafından
onaylanmalı (Approve) ya da merge GitHub arayüzünden yapılmalıdır. Portal kullanıcısı adına
GitHub review'u gönderilmez (kişi başı token yok; başkası adına onay sahtecilik olur).
Ayrıntı `GitHubMergeResult` alanlarında: `github_onaylayanlar`, `github_merge_eden`.
`merge_pr(..., expected_head_sha=...)` onaylanan head'i GitHub'a `sha` olarak iletir; dal onaydan
sonra ilerlediyse GitHub 409 döner → `ForgeConflictError` (anayasa I: onaylanan içerik).

Dal güncelleme / kapatma (LocalForge ile aynı sözleşme; kod üretimi aynı yolu kullanır):
- `update_branch(n, actor)`: GitHub "Update branch" (`PUT pulls/{n}/update-branch`,
  `expected_head_sha` = core'un bildiği head). Dal zaten güncelse (compare `behind_by == 0`)
  hiçbir şey yazılmaz ve aynı head döner. GitHub isteği asenkron işler (202); yeni head
  `GET pulls/{n}`'den beklenir ve yeni merge commit'inin ebeveynlerinde eski head olmalıdır
  (başkasının push'u core'un head'i sayılmaz). Çakışma → `ForgeConflictError`; head bu arada
  ilerlediyse → `ForgeStateError`. Böylece main ilerleyince diğer açık bot PR'larının yeni
  head'i core'dan gelir: PR CI, insan onayı ve kırarak doğrulama yeni head'de yenilenir ve
  sonraki merge "yabancı head" sayılmaz.
- `close_pr(n)`: `PATCH pulls/{n} state=closed` (insan reddi / yerine geçilen PR).
- İkisi de bot kimliğiyle yapılır: GitHub App izinleri `Pull requests: write` ve
  `Contents: write` (update-branch dala merge commit'i yazar).

Kod araması GitHub arama API'siyle aday dosyaları bulur (yalnızca bu depo; arama dizini
varsayılan dalı kapsar), satırlar ise istenen ref'teki dosya içeriğinden sabit metinle çıkarılır.

**GitHub Actions (ci-runs alımı; `ForgePort` dışında, yalnızca GitHub modu):**
- tetik: `repository_dispatch` / `dispatch_deploy` (ci.yml `deploy`; `client_payload {ref,
  istek_id}`), `workflow_dispatch` (ci.yml gece/elle). break-verify.yml için genel API yeterlidir
  ama çekirdek onu TETİKLEMEZ: kod üretimindeki "kırarak doğrula" her iki modda da
  toolchain-worker `/check` yolunu kullanır (GitHub modunda `TP_FORGE_REMOTE_URL` aynası gerekir);
  break-verify.yml yalnızca elle kanıt içindir (`.github/CI.md`);
- koşular: `list_workflow_runs(head_sha=…)`, `find_dispatched_run(istek_id)` (koşu adındaki
  `[<istek_id>]`), `get_workflow_run`, `list_run_jobs`;
- artefaktlar: `list_run_artifacts`, `download_artifact` (302 yönlendirmesi Authorization
  başlığı OLMADAN izlenir; boyut sınırlı), `safe_extract_zip` (zip-slip / sembolik bağ / boyut
  bombası reddi), `download_run_artifact(run_id, ad, hedef)`;
- kontroller: `check_runs(sha)` (ayrıntılı; `details_url`'den koşu ve job kimliği).
Artefakt düzeni (`.github/CI.md` "Artefakt sözleşmesi"): `test-local-results` (kökte
`ci-meta.json`, `junit.xml`, `results.json`, `allure-results/`, `playwright-report/`),
`sauce-results` (kökte `sauce.json`), `break-verify-results` (kökte `break-verify.json`).
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import stat
import threading
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx
import jwt
from pydantic import Field

from tp_core.integrations.forge import (
    BOT_ACTORS,
    BOT_NAME,
    BYPASS_ACTOR,
    GITHUB_REQUIRED_CHECKS,
    PROTECTED_BRANCHES,
    REQUIRED_CHECKS_ENV,
    ForgeConflictError,
    ForgeError,
    ForgeNotFoundError,
    ForgeProtectionError,
    ForgeStateError,
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

# --------------------------------------------------------------- GitHub Actions sabitleri
CI_WORKFLOW = "ci.yml"
# Yalnızca elle tetiklenen kanıt workflow'u; çekirdek dispatch ETMEZ (bkz. modül belgesi).
BREAK_VERIFY_WORKFLOW = "break-verify.yml"
DEPLOY_EVENT = "deploy"
# ci.yml / break-verify.yml artefakt adları (.github/CI.md "Artefakt sözleşmesi")
ARTIFACT_TEST_LOCAL = "test-local-results"
ARTIFACT_SAUCE = "sauce-results"
ARTIFACT_PLAYWRIGHT_REPORT = "playwright-report"
ARTIFACT_BREAK_VERIFY = "break-verify-results"
# Artefakt kök dosyaları
CI_META_FILE = "ci-meta.json"
SAUCE_FILE = "sauce.json"
BREAK_VERIFY_FILE = "break-verify.json"

ISTEK_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_DISPLAY_ISTEK_RE = re.compile(r"\[([A-Za-z0-9._-]{1,64})\]\s*$")
_WORKFLOW_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.ya?ml$")
_EVENT_TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_INPUT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,99}$")
_DETAILS_RE = re.compile(r"/actions/runs/(\d+)(?:/job/(\d+))?")
_RUN_EVENTS = frozenset(
    {"pull_request", "push", "schedule", "repository_dispatch", "workflow_dispatch"}
)
_REDIRECTS = (301, 302, 303, 307, 308)
MAX_ARTIFACT_BYTES = 200 * 1024 * 1024  # indirilen zip
MAX_EXTRACT_BYTES = 500 * 1024 * 1024  # açılmış toplam
MAX_EXTRACT_FILES = 20_000


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


# --------------------------------------------------------------- GitHub Actions modelleri


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def validate_istek_id(value: str) -> str:
    if not isinstance(value, str) or not ISTEK_ID_RE.match(value):
        raise ForgeValidationError(f"geçersiz istek_id: {value!r} ([A-Za-z0-9._-], ≤64)")
    return value


def _validate_workflow(workflow: str | int) -> str:
    if isinstance(workflow, int) and not isinstance(workflow, bool) and workflow > 0:
        return str(workflow)
    if isinstance(workflow, str) and _WORKFLOW_RE.match(workflow):
        return workflow
    raise ForgeValidationError(f"geçersiz workflow: {workflow!r} (ör. ci.yml)")


def _positive(value: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ForgeValidationError(f"geçersiz {what}: {value!r}")
    return value


@dataclass(frozen=True)
class WorkflowRun:
    """GitHub Actions workflow koşusu (yalnızca alımın kullandığı alanlar)."""

    id: int
    name: str
    display_title: str
    event: str
    status: str  # queued | in_progress | completed | waiting | requested | pending
    conclusion: str | None  # success | failure | cancelled | skipped | timed_out | …
    head_sha: str
    head_branch: str | None
    run_number: int
    run_attempt: int
    html_url: str | None
    created_at: str | None
    updated_at: str | None
    path: str | None  # .github/workflows/ci.yml

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def istek_id(self) -> str | None:
        """Koşu adının sonundaki `[<istek_id>]` (ci.yml `run-name`); yoksa None."""
        m = _DISPLAY_ISTEK_RE.search(self.display_title or "")
        return m.group(1) if m and m.group(1) != "elle" else None

    @classmethod
    def from_api(cls, d: Mapping[str, Any]) -> WorkflowRun:
        return cls(
            id=_int(d.get("id")),
            name=str(d.get("name") or ""),
            display_title=str(d.get("display_title") or ""),
            event=str(d.get("event") or ""),
            status=str(d.get("status") or ""),
            conclusion=_str(d.get("conclusion")),
            head_sha=str(d.get("head_sha") or ""),
            head_branch=_str(d.get("head_branch")),
            run_number=_int(d.get("run_number")),
            run_attempt=_int(d.get("run_attempt")) or 1,
            html_url=_str(d.get("html_url")),
            created_at=_str(d.get("created_at")),
            updated_at=_str(d.get("updated_at")),
            path=_str(d.get("path")),
        )


@dataclass(frozen=True)
class WorkflowJob:
    id: int
    run_id: int
    name: str
    status: str
    conclusion: str | None
    html_url: str | None
    started_at: str | None
    completed_at: str | None

    @classmethod
    def from_api(cls, d: Mapping[str, Any]) -> WorkflowJob:
        return cls(
            id=_int(d.get("id")),
            run_id=_int(d.get("run_id")),
            name=str(d.get("name") or ""),
            status=str(d.get("status") or ""),
            conclusion=_str(d.get("conclusion")),
            html_url=_str(d.get("html_url")),
            started_at=_str(d.get("started_at")),
            completed_at=_str(d.get("completed_at")),
        )


@dataclass(frozen=True)
class WorkflowArtifact:
    id: int
    name: str
    size_in_bytes: int
    expired: bool
    run_id: int | None
    head_sha: str | None
    created_at: str | None
    expires_at: str | None
    digest: str | None  # "sha256:…" (upload-artifact v4+)

    @classmethod
    def from_api(cls, d: Mapping[str, Any]) -> WorkflowArtifact:
        run = d.get("workflow_run") if isinstance(d.get("workflow_run"), Mapping) else {}
        return cls(
            id=_int(d.get("id")),
            name=str(d.get("name") or ""),
            size_in_bytes=_int(d.get("size_in_bytes")),
            expired=bool(d.get("expired")),
            run_id=_int(run.get("id")) or None,
            head_sha=_str(run.get("head_sha")),
            created_at=_str(d.get("created_at")),
            expires_at=_str(d.get("expires_at")),
            digest=_str(d.get("digest")),
        )


@dataclass(frozen=True)
class GitHubCheckRun:
    """Ayrıntılı kontrol (check run). `check` = `ForgePort.checks()` ile aynı eşlenmiş biçim."""

    id: int
    name: str
    status: str
    conclusion: str | None  # GitHub'ın ham sonucu
    check: CheckRun
    html_url: str | None
    details_url: str | None
    started_at: str | None
    completed_at: str | None
    app_slug: str | None  # github-actions | …
    workflow_run_id: int | None  # details_url'den (Actions kontrolleri)
    job_id: int | None
    output_title: str | None
    output_summary: str | None


def _map_check(item: Mapping[str, Any]) -> CheckRun:
    status = _STATUSES.get(item.get("status", ""), "queued")
    conclusion = None
    if status == "completed":
        conclusion = _CONCLUSIONS.get(item.get("conclusion") or "", "failure")
    return CheckRun(
        name=item["name"],
        status=status,  # type: ignore[arg-type]
        conclusion=conclusion,  # type: ignore[arg-type]
        url=item.get("html_url"),
    )


def safe_extract_zip(
    data: bytes,
    dest: Path,
    *,
    max_total: int = MAX_EXTRACT_BYTES,
    max_files: int = MAX_EXTRACT_FILES,
) -> list[str]:
    """Artefakt zip'ini `dest` altına güvenle açar; açılan göreli yolları döner.

    Artefakt CI'da koşan test kodunun çıktısıdır (güvenilmeyen veri): mutlak yol, `..`, sürücü
    harfi, ters bölü ve sembolik bağ girdisi reddedilir; dosya sayısı ve açılmış toplam boyut
    (beyan edilen değil, gerçekten okunan bayt) sınırlıdır. İhlalde `ForgeValidationError`;
    `dest` yarım yazılmış olabilir, çağıran onu atmalıdır (`download_run_artifact` siler).
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ForgeValidationError(f"artefakt zip değil: {exc}") from exc
    root = dest.resolve()
    written: list[str] = []
    total = 0
    with zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise ForgeValidationError(f"artefaktta çok fazla dosya ({len(infos)} > {max_files})")
        for info in infos:
            name = info.filename
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ForgeValidationError(f"artefaktta sembolik bağ: {name!r}")
            if "\\" in name or "\x00" in name:
                raise ForgeValidationError(f"artefaktta geçersiz yol: {name!r}")
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or (pure.parts and ":" in pure.parts[0]):
                raise ForgeValidationError(f"artefaktta güvensiz yol: {name!r}")
            target = (root / pure).resolve()
            if target != root and root not in target.parents:
                raise ForgeValidationError(f"artefaktta güvensiz yol: {name!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_total:
                        raise ForgeValidationError(
                            f"artefakt açılmış boyutu sınırı aşıyor (> {max_total} bayt)"
                        )
                    out.write(chunk)
            written.append(pure.as_posix())
    return sorted(written)


class GitHubMergeResult(MergeResult):
    """`MergeResult` + GitHub'a özgü denetim ayrıntısı."""

    github_onaylayanlar: list[str] = Field(default_factory=list)
    """Head commit'ini onaylayan insan GitHub hesapları (kullanıcı başına son karar)."""
    github_merge_eden: str | None = None
    """GitHub'da merge'ü yapan token'ın sahibi (`GET /user`; bilinmiyorsa None)."""


def _is_bot_login(user: Mapping[str, Any]) -> bool:
    login = str(user.get("login") or "")
    return user.get("type") == "Bot" or login.endswith("[bot]") or login in BOT_ACTORS


def qualifying_approvals(reviews: Sequence[Mapping[str, Any]], head_sha: str) -> list[str]:
    """Head commit'ini onaylayan insan review'ları (GitHub kuralı: kullanıcı başına son karar).

    `COMMENTED`/`PENDING` kararı değiştirmez; `DISMISSED`/`CHANGES_REQUESTED` onayı geri alır.
    Ruleset `dismiss_stale_reviews_on_push` istediği için yalnızca `commit_id == head_sha` olan
    onay sayılır. Bot hesapları sayılmaz.
    """
    latest: dict[str, tuple[str, str]] = {}
    for rv in reviews:
        user = rv.get("user")
        if not isinstance(user, Mapping) or _is_bot_login(user) or not user.get("login"):
            continue
        state = str(rv.get("state") or "").upper()
        if state in ("COMMENTED", "PENDING", ""):
            continue
        latest[str(user["login"])] = (state, str(rv.get("commit_id") or ""))
    return sorted(
        login for login, (state, commit) in latest.items()
        if state == "APPROVED" and commit == head_sha
    )  # fmt: skip


class GitHubForge:
    """GitHub REST ile `ForgePort`."""

    # Kod araması yalnızca varsayılan dalın (gecikmeli) dizinini tarar: başka ref'teki ya da yeni
    # merge edilmiş içerik bulunamayabilir. Deterministik okuma gereken yerler (demo testid
    # durumu) aramaya değil ağaç listesine dayanır (`integrations.forge_demo`).
    code_search_is_indexed = True
    # Depo düzeni: GitHub kipinde test edilen uygulama `demo-app/` altındadır (ci.yml `APP_ROOT`,
    # CODEOWNERS `/demo-app/...`). `TP_FORGE_APP_ROOT` ortam değişkeni bunu ezer (codegen ile aynı).
    default_app_root = "demo-app"

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
        update_wait_s: float = 60.0,
        poll_interval_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not _REPO_RE.match(repo or ""):
            raise ForgeValidationError(f"geçersiz GITHUB_REPO: {repo!r} (sahip/ad)")
        self.repo = repo
        self.owner = repo.split("/", 1)[0]
        self._auth = auth
        self._merge_auth = merge_auth
        self._merge_login: str | None = None
        self.required_checks = validate_required_checks(required_checks)
        self._update_wait_s = max(0.0, float(update_wait_s))
        self._poll_interval_s = max(0.01, float(poll_interval_s))
        self._sleep = sleep
        self._api_url = api_url
        self._transport = transport
        self._timeout = timeout
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

    def human_forge(self) -> GitHubForge:
        """Aynı depo, İNSAN kimliğiyle (`GITHUB_MERGE_TOKEN`, ör. demo-admin üyesi mühendis).

        Yalnızca demo kırılması/sıfırlaması gibi insanın kendi adına yaptığı, ruleset bypass'ı
        gerektiren işlemler içindir: dal, commit, PR ve merge bu kimlikle yapılır; bot (App)
        kimliği kullanılmaz (anayasa: bot merge etmez, bypass yalnızca demo-admin'de). Merge
        token'ı yoksa `ForgeProtectionError`.
        """
        if self._merge_auth is None:
            raise ForgeProtectionError(
                "İnsan kimliği yok: GITHUB_MERGE_TOKEN (demo-admin takımındaki mühendisin "
                "token'ı) tanımlı değil; demo kırılması/sıfırlaması bot kimliğiyle yapılmaz"
            )
        return GitHubForge(
            self.repo,
            self._merge_auth,
            api_url=self._api_url,
            merge_auth=self._merge_auth,
            required_checks=self.required_checks,
            transport=self._transport,
            timeout=self._timeout,
            update_wait_s=self._update_wait_s,
            poll_interval_s=self._poll_interval_s,
            sleep=self._sleep,
        )

    @property
    def has_merge_identity(self) -> bool:
        return self._merge_auth is not None

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

    def request(self, method: str, path: str, what: str, **kw: Any) -> httpx.Response:
        """Kimlikli GitHub isteği (App/token, 401'de bir kez yenileme); Actions uçları için."""
        return self._request(method, path, what, **kw)

    def _get(self, path: str, what: str, **kw: Any) -> Any:
        return self._request("GET", path, what, **kw).json()

    def _post(self, path: str, what: str, body: Any, **kw: Any) -> Any:
        return self._request("POST", path, what, json=body, **kw).json()

    def _post_no_content(self, path: str, what: str, body: Any) -> Any:
        """204 bekleyen POST (dispatch uçları); gövde varsa JSON olarak döner."""
        resp = self._request("POST", path, what, json=body)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

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

    def changed_paths(self, base: str, head: str) -> list[str] | None:
        """`base`...`head` karşılaştırmasında değişen yollar (tek REST çağrısı).

        GitHub compare en fazla 300 dosya döndürür; liste kesilmiş olabilirse None (çağıran tam
        ağaç karşılaştırmasına düşer)."""
        validate_ref(base)
        validate_ref(head)
        cmp = self._get(f"{self._r}/compare/{_q(base)}...{_q(head)}", f"{base}...{head} farkı")
        files = cmp.get("files") if isinstance(cmp, dict) else None
        if not isinstance(files, list) or len(files) >= 300:
            return None
        yollar: set[str] = set()
        for f in files:
            if not isinstance(f, dict) or not isinstance(f.get("filename"), str):
                return None
            yollar.add(f["filename"])
            if isinstance(f.get("previous_filename"), str):  # yeniden adlandırma: eski yol silindi
                yollar.add(f["previous_filename"])
        return sorted(yollar)

    def merge_base(self, a: str, b: str) -> str:
        """`a`...`b` karşılaştırmasının ortak atası (compare `merge_base_commit`)."""
        validate_ref(a)
        validate_ref(b)
        cmp = self._get(f"{self._r}/compare/{_q(a)}...{_q(b)}", f"{a}...{b} ortak atası")
        base = cmp.get("merge_base_commit") if isinstance(cmp, dict) else None
        sha = base.get("sha") if isinstance(base, dict) else None
        if not isinstance(sha, str) or not is_sha(sha):
            raise ForgeError(f"GitHub {a}...{b}: ortak ata okunamadı")
        return sha

    def _tree(self, ref: str) -> list[dict[str, Any]]:
        sha = ref if is_sha(ref) else self.head_sha(ref)
        commit = self._get(f"{self._r}/git/commits/{sha}", "commit")
        tree = self._get(
            f"{self._r}/git/trees/{commit['tree']['sha']}", "ağaç", params={"recursive": "1"}
        )
        if tree.get("truncated"):
            raise ForgeError("GitHub ağaç listesi kesildi (depo çok büyük)")
        return list(tree.get("tree", []))

    def tree_sha(self, ref: str = "main", path: str = "") -> str | None:
        """`ref`'teki `path` dizininin git ağaç sha'sı (boş yol = kök); yoksa / dizin değilse None.

        Ağaç kimliği içerikten türetilir: yerel forge, GitHub ve toolchain aynasında aynı içerik
        aynı sha'yı verir (çalışan demo-app-web'in `/build.json` `web_tree` karşılaştırması)."""
        validate_ref(ref)
        sha = ref if is_sha(ref) else self.head_sha(ref)
        commit = self._get(f"{self._r}/git/commits/{sha}", "commit")
        root = commit["tree"]["sha"]
        if not path:
            return str(root)
        validate_path(path)
        for e in self._tree(sha):
            if e.get("path") == path:
                return str(e["sha"]) if e.get("type") == "tree" and e.get("sha") else None
        return None

    def commit_tree(self, branch: str, tree: str, message: str, parent: str) -> str:
        """`parent` üstüne ağacı tam olarak `tree` olan tek commit yazar ve `branch`'i ona taşır.

        Demo sıfırlaması (GitHub): main'in üstüne demo-baseline ağacını geri getiren commit
        (geçmiş silinmez, force-push yok). Dal yoksa oluşturulur; varsa yalnızca fast-forward
        ile güncellenir. Korunan dala yazılmaz."""
        validate_branch(branch)
        if branch in PROTECTED_BRANCHES:
            raise ForgeProtectionError(f"'{branch}' korunan dal: doğrudan commit yok, PR açın")
        validate_message(message)
        if not is_sha(tree) or not is_sha(parent):
            raise ForgeValidationError("commit_tree: ağaç ve ebeveyn tam sha olmalı")
        try:
            ref = self._get(f"{self._r}/git/ref/heads/{_q(branch)}", f"dal {branch}")
            old: str | None = ref["object"]["sha"]
        except ForgeNotFoundError:
            old = None
        if old is not None:
            mevcut = self._get(f"{self._r}/git/commits/{old}", "commit")
            ebeveynler = [p.get("sha") for p in mevcut.get("parents") or []]
            if mevcut["tree"]["sha"] == tree and ebeveynler == [parent]:
                return str(old)  # aynı commit zaten dalda: idempotent
        commit = self._post(
            f"{self._r}/git/commits",
            "commit oluşturma",
            {"message": message, "tree": tree, "parents": [parent]},
        )
        new = str(commit["sha"])
        if old is None:
            self._post(
                f"{self._r}/git/refs", "dal oluşturma", {"ref": f"refs/heads/{branch}", "sha": new}
            )
        else:
            try:
                self._request(
                    "PATCH",
                    f"{self._r}/git/refs/heads/{_q(branch)}",
                    "dal güncelleme",
                    json={"sha": new, "force": False},
                )
            except ForgeValidationError as exc:
                raise ForgeConflictError(f"'{branch}' eşzamanlı değişti: {exc}") from exc
        return new

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

    def list_prs(self, state: str | None = None) -> list[PullRequest]:
        """PR listesi (LocalForge ile aynı sözleşme; `state`: open | closed | None = hepsi).

        Demo sıfırlaması açık `tp/*` ve `demo/*` PR'larını kapatmak için kullanır; en çok 10 sayfa
        (1000 PR). `merged` PR'lar GitHub'da `closed` listesindedir ve `merged` döner."""
        if state not in (None, "open", "closed", "merged"):
            raise ForgeValidationError(f"geçersiz PR durumu: {state!r}")
        api_state = "open" if state == "open" else ("all" if state is None else "closed")
        out: list[PullRequest] = []
        for page in range(1, 11):
            items = self._get(
                f"{self._r}/pulls",
                "PR listesi",
                params={"state": api_state, "per_page": 100, "page": page},
            )
            if not isinstance(items, list):
                raise ForgeError("GitHub PR listesi: beklenmeyen yanıt")
            out.extend(self._pr(i) for i in items if isinstance(i, dict))
            if len(items) < 100:
                break
        if state in ("closed", "merged"):
            out = [p for p in out if p.state == state]
        return out

    def get_pr(self, number: int) -> PullRequest:
        return self._pr(self._get(f"{self._r}/pulls/{int(number)}", f"PR #{number}"))

    def pr_merge_info(self, number: int) -> dict[str, Any]:
        """GitHub arayüzünde yapılan merge'ün ayrıntısı: `{merge_commit_sha, merged_by:{login}}`.

        Merge edilmemiş PR'da iki alan da None'dır. Yalnızca okuma (Pull requests: read).
        """
        data = self._get(f"{self._r}/pulls/{int(number)}", f"PR #{number}")
        merged = bool(data.get("merged")) or bool(data.get("merged_at"))
        sha = data.get("merge_commit_sha") if merged else None
        kim = data.get("merged_by") if merged and isinstance(data.get("merged_by"), dict) else None
        return {
            "merge_commit_sha": str(sha) if sha else None,
            "merged_by": {"login": str(kim.get("login"))} if kim and kim.get("login") else None,
        }

    def merge_pr(self, number: int, actor: str, *, expected_head_sha: str | None = None) -> str:
        return self.merge_pr_detailed(number, actor, expected_head_sha=expected_head_sha).sha

    def merge_pr_detailed(
        self, number: int, actor: str, *, expected_head_sha: str | None = None
    ) -> GitHubMergeResult:
        """PR'ı insan token'ıyla merge eder.

        `expected_head_sha` verilirse (onaylanan head) GitHub'a `sha` olarak gönderilir: dal
        bu sha'da değilse GitHub 409 döner ve merge yapılmaz. Verilmezse PR'ın o anki head'i
        kullanılır (yalnızca onay bağlamı olmayan çağrılar için; iş akışları sha'yı vermelidir).

        Ruleset koşulları (kontroller, insan GitHub review'u, mergeable_state) PUT'tan önce
        burada değerlendirilir; eksik varsa yalnızca BYPASS_ACTOR merge edebilir ve sonuç
        bypass olarak işaretlenir (modül belgesi).
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
        raw = self._get(f"{self._r}/pulls/{int(number)}", f"PR #{number}")
        pr = self._pr(raw)
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
        approvers = qualifying_approvals(self.pr_reviews(number), head)
        eksikler: list[str] = []
        if not verdict.passed:
            eksikler.append(verdict.reason())
        if not approvers:
            eksikler.append(f"GitHub'da head {head[:12]} için onaylı insan review'u yok")
        if str(raw.get("mergeable_state") or "") == "blocked" and verdict.passed and approvers:
            eksikler.append("GitHub kuralları merge'ü engelliyor (mergeable_state=blocked)")
        if eksikler and actor != BYPASS_ACTOR:
            raise ForgeProtectionError(
                "GitHub ruleset koşulları sağlanmadı: "
                + "; ".join(eksikler)
                + ". PR'ı GitHub'da onaylayın (Approve) veya merge'ü GitHub arayüzünden yapın; "
                "portal başkası adına GitHub review'u göndermez ve bypass yalnızca "
                f"{BYPASS_ACTOR} hesabındadır"
            )
        merged_by = self.merge_token_login()
        resp = self._request(
            "PUT",
            f"{self._r}/pulls/{int(number)}/merge",
            f"PR #{number} merge",
            auth=self._merge_auth,
            json={"merge_method": "merge", "sha": head},
        ).json()
        if not resp.get("merged"):
            raise ForgeConflictError(f"PR #{number} merge edilemedi: {resp.get('message', '')}")
        reason = None
        if eksikler:
            reason = (
                "; ".join(eksikler)
                + f" (ruleset bypass; GitHub'da merge eden: {merged_by or 'bilinmiyor'})"
            )
        return GitHubMergeResult(
            number=number,
            sha=resp["sha"],
            actor=actor,
            method="merge-commit",
            bypass=bool(eksikler),
            bypass_reason=reason,
            checks=checks,
            github_onaylayanlar=approvers,
            github_merge_eden=merged_by,
        )

    def pr_reviews(self, number: int) -> list[dict[str, Any]]:
        """PR review'ları (kronolojik; en çok 100 sayfa başına, tüm sayfalar)."""
        out: list[dict[str, Any]] = []
        for page in range(1, 11):
            items = self._get(
                f"{self._r}/pulls/{int(number)}/reviews",
                f"PR #{number} review listesi",
                params={"per_page": 100, "page": page},
            )
            if not isinstance(items, list):
                raise ForgeError(f"GitHub PR #{number} review listesi: beklenmeyen yanıt")
            out.extend(i for i in items if isinstance(i, dict))
            if len(items) < 100:
                break
        return out

    def merge_token_login(self) -> str | None:
        """Merge token'ının GitHub hesabı (denetim için; alınamazsa None, önbellekli)."""
        if self._merge_auth is None:
            return None
        if self._merge_login is None:
            try:
                data = self._get("/user", "merge token kimliği", auth=self._merge_auth)
            except ForgeError:
                return None
            login = data.get("login") if isinstance(data, dict) else None
            self._merge_login = str(login) if login else None
        return self._merge_login

    def comment_pr(self, number: int, body: str) -> None:
        if not isinstance(body, str) or not body.strip():
            raise ForgeValidationError("yorum boş olamaz")
        self._post(f"{self._r}/issues/{int(number)}/comments", "PR yorumu", {"body": body})

    def close_pr(self, number: int) -> None:
        """PR'ı kapatır (merge etmeden). Açık değilse `ForgeStateError` (LocalForge ile aynı)."""
        number = _positive(number, "PR numarası")
        pr = self.get_pr(number)
        if pr.state != "open":
            raise ForgeStateError(f"PR #{number} açık değil ({pr.state})")
        data = self._request(
            "PATCH", f"{self._r}/pulls/{number}", f"PR #{number} kapatma", json={"state": "closed"}
        ).json()
        if not isinstance(data, dict) or data.get("state") != "closed":
            raise ForgeError(f"GitHub PR #{number} kapatılamadı (yanıt durumu beklenmedik)")

    def update_branch(
        self, number: int, actor: str = BOT_NAME, *, expected_head_sha: str | None = None
    ) -> str:
        """GitHub "Update branch": temel dalı PR dalına merge eder; yeni (veya aynı) head döner.

        LocalForge.update_branch ile aynı sözleşme (modül belgesi). `actor` doğrulanır ve hata
        iletilerinde kullanılır; GitHub'da işlemi yapan hesap bot (App) kimliğidir.
        `expected_head_sha` verilirse dal tam o commit'te değilse hiçbir şey yazılmaz
        (`ForgeStateError`) ve GitHub'a da beklenen head olarak o gönderilir.
        """
        validate_actor(actor)
        number = _positive(number, "PR numarası")
        if expected_head_sha is not None and not is_sha(expected_head_sha):
            raise ForgeValidationError(f"geçersiz beklenen head sha: {expected_head_sha!r}")
        raw = self._get(f"{self._r}/pulls/{number}", f"PR #{number}")
        pr = self._pr(raw)
        if pr.state != "open":
            raise ForgeStateError(f"PR #{number} açık değil ({pr.state})")
        head = validate_ref(pr.head_sha)
        if expected_head_sha is not None and head != expected_head_sha:
            raise ForgeStateError(
                f"PR #{number} head'i beklenenden farklı (beklenen {expected_head_sha[:12]}, "
                f"güncel {head[:12]}); dal güncellenmedi"
            )
        base = validate_ref(pr.base)
        cmp = self._get(
            f"{self._r}/compare/{_q(base)}...{_q(head)}", f"PR #{number} dal karşılaştırma"
        )
        if not isinstance(cmp, dict) or not isinstance(cmp.get("behind_by"), int):
            raise ForgeError(f"GitHub PR #{number} dal karşılaştırma: beklenmeyen yanıt")
        if cmp["behind_by"] == 0:
            return head  # dal zaten güncel: hiçbir şey yazılmaz
        try:
            self._request(
                "PUT",
                f"{self._r}/pulls/{number}/update-branch",
                f"PR #{number} dal güncelleme",
                json={"expected_head_sha": head},
            )
        except ForgeValidationError as exc:  # GitHub bu uçta nedenleri 422 ile döner
            mesaj = str(exc).lower()
            if "conflict" in mesaj:
                raise ForgeConflictError(str(exc)) from exc
            if "expected" in mesaj and "sha" in mesaj:
                raise ForgeStateError(
                    f"PR #{number} dalı güncelleme sırasında ilerledi ({actor}): {exc}"
                ) from exc
            if "no new commits" in mesaj:
                return head
            raise
        return self._wait_new_head(number, head)

    def _wait_new_head(self, number: int, old: str) -> str:
        """202 sonrası yeni head'i bekler; yeni commit eski head'in üstüne kurulmuş olmalıdır."""
        deadline = time.monotonic() + self._update_wait_s
        while True:
            pr = self._pr(self._get(f"{self._r}/pulls/{number}", f"PR #{number}"))
            if pr.state != "open":
                raise ForgeStateError(f"PR #{number} güncelleme sırasında kapandı ({pr.state})")
            if pr.head_sha != old:
                commit = self._get(
                    f"{self._r}/commits/{_q(pr.head_sha)}", f"PR #{number} yeni head commit'i"
                )
                parents = [
                    p.get("sha")
                    for p in (commit.get("parents") if isinstance(commit, dict) else None) or []
                    if isinstance(p, dict)
                ]
                if old not in parents:
                    raise ForgeStateError(
                        f"PR #{number} dalında beklenmeyen head {pr.head_sha[:12]} "
                        f"(eski head {old[:12]} ebeveyn değil); dal başka biri tarafından değişti"
                    )
                return pr.head_sha
            if time.monotonic() >= deadline:
                raise ForgeError(
                    f"GitHub PR #{number} dal güncellemesini kabul etti ama yeni head "
                    f"{self._update_wait_s:.0f} sn içinde görünmedi; daha sonra yeniden deneyin"
                )
            self._sleep(self._poll_interval_s)

    def _check_items(self, sha: str) -> list[dict[str, Any]]:
        validate_ref(sha)
        data = self._get(
            f"{self._r}/commits/{_q(sha)}/check-runs",
            "kontroller",
            params={"per_page": 100, "filter": "latest"},
        )
        # Sıra: eskiden yeniye (started_at); aynı adlı koşularda son girdi en günceldir.
        return sorted(
            (it for it in data.get("check_runs", []) if isinstance(it, dict) and it.get("name")),
            key=lambda it: it.get("started_at") or it.get("completed_at") or "",
        )

    def checks(self, sha: str) -> list[CheckRun]:
        return [_map_check(item) for item in self._check_items(sha)]

    def check_runs(self, sha: str) -> list[GitHubCheckRun]:
        """Ayrıntılı kontroller (eskiden yeniye). Actions kontrollerinde `details_url`
        `…/actions/runs/<run_id>/job/<job_id>` biçimindedir; koşu/job kimliği buradan çıkarılır."""
        out: list[GitHubCheckRun] = []
        for item in self._check_items(sha):
            details = _str(item.get("details_url"))
            m = _DETAILS_RE.search(urlsplit(details).path) if details else None
            app = item.get("app") if isinstance(item.get("app"), Mapping) else {}
            output = item.get("output") if isinstance(item.get("output"), Mapping) else {}
            out.append(
                GitHubCheckRun(
                    id=_int(item.get("id")),
                    name=str(item["name"]),
                    status=str(item.get("status") or ""),
                    conclusion=_str(item.get("conclusion")),
                    check=_map_check(item),
                    html_url=_str(item.get("html_url")),
                    details_url=details,
                    started_at=_str(item.get("started_at")),
                    completed_at=_str(item.get("completed_at")),
                    app_slug=_str(app.get("slug")),
                    workflow_run_id=int(m.group(1)) if m else None,
                    job_id=int(m.group(2)) if m and m.group(2) else None,
                    output_title=_str(output.get("title")),
                    output_summary=_str(output.get("summary")),
                )
            )
        return out

    # ------------------------------------------------------------------ Actions: tetik

    def repository_dispatch(
        self, event_type: str = DEPLOY_EVENT, client_payload: Mapping[str, Any] | None = None
    ) -> None:
        """`POST /repos/{repo}/dispatches` (ci.yml `repository_dispatch: types: [deploy]`).

        GitHub koşu kimliği döndürmez; koşu `find_dispatched_run(istek_id)` ile bulunur.
        Yetki: token'da `contents: write` (App: Contents read & write)."""
        if not isinstance(event_type, str) or not _EVENT_TYPE_RE.match(event_type):
            raise ForgeValidationError(f"geçersiz event_type: {event_type!r}")
        payload = dict(client_payload or {})
        if len(payload) > 10:  # GitHub sınırı: en çok 10 üst düzey anahtar
            raise ForgeValidationError("client_payload en çok 10 üst düzey anahtar taşıyabilir")
        for key in ("istek_id", "tp_run_id"):  # ci.yml koşu adına girer: biçim sabit
            if key in payload:
                validate_istek_id(payload[key])
        if "ref" in payload:
            validate_ref(payload["ref"])
        try:
            encoded = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ForgeValidationError(f"client_payload JSON değil: {exc}") from exc
        if len(encoded.encode()) > 64 * 1024:
            raise ForgeValidationError("client_payload çok büyük (> 64 KB)")
        self._post_no_content(
            f"{self._r}/dispatches",
            f"repository_dispatch {event_type}",
            {"event_type": event_type, "client_payload": payload},
        )

    def dispatch_deploy(self, istek_id: str, ref: str | None = None) -> None:
        """Deploy tetiği (portal `POST /ci/trigger {tetik: deploy}` GitHub modunda).

        ci.yml koşu adı `ci deploy [<istek_id>]` olur; `ref` verilirse o dal/sha test edilir."""
        payload: dict[str, Any] = {"istek_id": validate_istek_id(istek_id)}
        if ref is not None:
            payload["ref"] = validate_ref(ref)
        self.repository_dispatch(DEPLOY_EVENT, payload)

    def workflow_dispatch(
        self,
        workflow: str | int = CI_WORKFLOW,
        ref: str = "main",
        inputs: Mapping[str, str] | None = None,
    ) -> int | None:
        """`POST /actions/workflows/{workflow}/dispatches`.

        ci.yml girdileri: `tetik` (manual|nightly|deploy), `istek_id`; break-verify.yml: `grep`,
        `istek_id`. GitHub koşu kimliği dönerse (yeni API yanıtı `workflow_run_id`) o döner,
        aksi halde None → `find_dispatched_run`. Yetki: `actions: write`."""
        wf = _validate_workflow(workflow)
        validate_ref(ref)
        clean: dict[str, str] = {}
        for key, value in (inputs or {}).items():
            if not isinstance(key, str) or not _INPUT_KEY_RE.match(key):
                raise ForgeValidationError(f"geçersiz workflow girdisi: {key!r}")
            if not isinstance(value, str) or len(value) > 1000:
                raise ForgeValidationError(f"geçersiz workflow girdi değeri: {key}")
            clean[key] = value
        if len(clean) > 25:  # GitHub sınırı
            raise ForgeValidationError("workflow_dispatch en çok 25 girdi alır")
        if clean.get("istek_id"):
            validate_istek_id(clean["istek_id"])
        body = self._post_no_content(
            f"{self._r}/actions/workflows/{_q(wf)}/dispatches",
            f"workflow_dispatch {wf}",
            {"ref": ref, "inputs": clean},
        )
        if isinstance(body, Mapping):
            run_id = _int(body.get("workflow_run_id") or body.get("id"))
            return run_id or None
        return None

    # ------------------------------------------------------------------ Actions: okuma

    def list_workflow_runs(
        self,
        workflow: str | int = CI_WORKFLOW,
        *,
        head_sha: str | None = None,
        event: str | None = None,
        branch: str | None = None,
        created: str | None = None,
        per_page: int = 30,
    ) -> list[WorkflowRun]:
        """Bir workflow'un koşuları (en yeni önce). `head_sha` ile commit'e göre süzülür.

        Not: `repository_dispatch` / `schedule` koşularının `head_sha`'sı varsayılan dalın ucudur;
        deploy'da test edilen commit artefakttaki `ci-meta.json` → `sha`'dadır."""
        wf = _validate_workflow(workflow)
        params: dict[str, Any] = {"per_page": max(1, min(int(per_page), 100))}
        if head_sha is not None:
            if not is_sha(head_sha):
                raise ForgeValidationError(f"geçersiz head_sha: {head_sha!r}")
            params["head_sha"] = head_sha
        if event is not None:
            if event not in _RUN_EVENTS:
                raise ForgeValidationError(f"geçersiz olay: {event!r}")
            params["event"] = event
        if branch is not None:
            params["branch"] = validate_branch(branch)
        if created is not None:
            if not re.match(r"^[<>=.0-9TZ:+-]{4,60}$", created):
                raise ForgeValidationError(f"geçersiz created süzgeci: {created!r}")
            params["created"] = created
        data = self._get(
            f"{self._r}/actions/workflows/{_q(wf)}/runs", f"workflow koşuları {wf}", params=params
        )
        runs = [
            WorkflowRun.from_api(d) for d in data.get("workflow_runs", []) if isinstance(d, dict)
        ]
        return sorted(runs, key=lambda r: (r.created_at or "", r.id), reverse=True)

    def find_dispatched_run(
        self,
        istek_id: str,
        workflow: str | int = CI_WORKFLOW,
        *,
        event: str | None = None,
        per_page: int = 50,
    ) -> WorkflowRun | None:
        """Çekirdeğin tetiklediği koşuyu koşu adındaki `[<istek_id>]` ile bulur (en yenisi).

        Dispatch'ten hemen sonra koşu henüz listelenmemiş olabilir → None; çağıran bekleyip
        yeniden dener."""
        validate_istek_id(istek_id)
        for run in self.list_workflow_runs(workflow, event=event, per_page=per_page):
            if run.istek_id == istek_id:
                return run
        return None

    def get_workflow_run(self, run_id: int) -> WorkflowRun:
        rid = _positive(run_id, "koşu kimliği")
        return WorkflowRun.from_api(self._get(f"{self._r}/actions/runs/{rid}", f"koşu {rid}"))

    def list_run_jobs(self, run_id: int) -> list[WorkflowJob]:
        """Koşunun son denemesindeki job'lar (test-local, ast-guard, semgrep, sauce, …)."""
        rid = _positive(run_id, "koşu kimliği")
        data = self._get(
            f"{self._r}/actions/runs/{rid}/jobs",
            f"koşu {rid} job'ları",
            params={"filter": "latest", "per_page": 100},
        )
        return [WorkflowJob.from_api(d) for d in data.get("jobs", []) if isinstance(d, dict)]

    def list_run_artifacts(self, run_id: int, name: str | None = None) -> list[WorkflowArtifact]:
        rid = _positive(run_id, "koşu kimliği")
        params: dict[str, Any] = {"per_page": 100}
        if name is not None:
            if not isinstance(name, str) or not _EVENT_TYPE_RE.match(name):
                raise ForgeValidationError(f"geçersiz artefakt adı: {name!r}")
            params["name"] = name
        data = self._get(
            f"{self._r}/actions/runs/{rid}/artifacts", f"koşu {rid} artefaktları", params=params
        )
        arts = [
            WorkflowArtifact.from_api(d) for d in data.get("artifacts", []) if isinstance(d, dict)
        ]
        return [a for a in arts if name is None or a.name == name]

    def download_artifact(self, artifact_id: int, *, max_bytes: int = MAX_ARTIFACT_BYTES) -> bytes:
        """Artefakt zip'ini indirir (`GET /actions/artifacts/{id}/zip`).

        GitHub kısa ömürlü imzalı bir adrese yönlendirir: yönlendirme yalnızca https'e ve
        Authorization başlığı GÖNDERİLMEDEN izlenir (token blob deposuna sızmaz). Süresi dolmuş
        artefakt (410) → `ForgeNotFoundError`. `max_bytes` aşılırsa `ForgeValidationError`."""
        aid = _positive(artifact_id, "artefakt kimliği")
        path = f"{self._r}/actions/artifacts/{aid}/zip"
        what = f"artefakt {aid}"
        resp: httpx.Response | None = None
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self._auth.token(self._client)}"}
            resp = self._client.get(path, headers=headers, follow_redirects=False)
            if resp.status_code == 401 and attempt == 0:
                self._auth.invalidate()
                continue
            break
        assert resp is not None
        if resp.status_code == 410:
            raise ForgeNotFoundError(f"GitHub {what}: süresi dolmuş (410)")
        if resp.status_code in _REDIRECTS:
            location = resp.headers.get("location") or ""
            if urlsplit(location).scheme != "https":
                raise ForgeError(f"GitHub {what}: güvensiz yönlendirme {location[:80]!r}")
            return self._fetch_limited(location, what, max_bytes, auth=False)
        _raise_for(resp, what)
        if len(resp.content) > max_bytes:
            raise ForgeValidationError(f"{what} boyut sınırını aşıyor (> {max_bytes} bayt)")
        return resp.content

    def _fetch_limited(self, url: str, what: str, max_bytes: int, *, auth: bool) -> bytes:
        headers: dict[str, str] = {"Accept": "*/*"}
        if auth:  # pragma: no cover - şimdilik yalnızca kimliksiz yönlendirme
            headers["Authorization"] = f"Bearer {self._auth.token(self._client)}"
        buf = bytearray()
        # İmzalı adres GitHub dışı bir konaktır: istemcinin varsayılan başlıkları (Accept,
        # API sürümü, User-Agent) zararsızdır; Authorization varsayılan başlıklarda YOKTUR.
        with self._client.stream("GET", url, headers=headers, follow_redirects=False) as resp:
            if not resp.is_success:
                resp.read()
                _raise_for(resp, what)
            declared = _int(resp.headers.get("content-length"))
            if declared > max_bytes:
                raise ForgeValidationError(f"{what} boyut sınırını aşıyor ({declared} bayt)")
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise ForgeValidationError(f"{what} boyut sınırını aşıyor (> {max_bytes} bayt)")
        return bytes(buf)

    def download_run_artifact(
        self,
        run_id: int,
        name: str,
        dest: Path,
        *,
        max_bytes: int = MAX_ARTIFACT_BYTES,
        max_extract: int = MAX_EXTRACT_BYTES,
    ) -> WorkflowArtifact | None:
        """Koşunun `name` adlı (süresi dolmamış, en yeni) artefaktını `dest` altına açar.

        Artefakt yoksa None (ör. Sauce job'u koşmadı, test-local no-op). `dest` boş/yok olmalı."""
        arts = [a for a in self.list_run_artifacts(run_id, name) if not a.expired]
        if not arts:
            return None
        art = max(arts, key=lambda a: (a.created_at or "", a.id))
        if art.size_in_bytes > max_bytes:
            raise ForgeValidationError(
                f"artefakt {art.name} boyut sınırını aşıyor ({art.size_in_bytes} bayt)"
            )
        if dest.exists() and any(dest.iterdir()):
            raise ForgeValidationError(f"hedef dizin boş değil: {dest}")
        data = self.download_artifact(art.id, max_bytes=max_bytes)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            safe_extract_zip(data, dest, max_total=max_extract)
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)  # yarım açılmış güvenilmeyen içerik kalmaz
            raise
        return art
