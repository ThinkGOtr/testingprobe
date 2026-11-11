"""LocalForge: `tp_forge` volume'ündeki bare git deposu üzerinde `ForgePort`.

- Git, `subprocess` ile ve kabuk olmadan çağrılır; her dal/yol/ref önce doğrulanır
  (`forge.validate_*`), `-` ile başlayan değerler ve `..` reddedilir. Pathspec'ler literal'dir.
- Commit'ler çalışma ağacı olmadan plumbing ile yazılır (geçici index → write-tree →
  commit-tree → update-ref CAS). Yazar: `tp-bot <bot@testingprobe.local>`.
- PR kayıtları deponun yanındaki `tp-prs.json` dosyasındadır; yazımlar `fcntl` kilidi altında,
  geçici dosya + `os.replace` ile atomiktir. Okumalar kilitsizdir (salt-okunur bağlamalar için).
- Dal koruması: `main`'e doğrudan commit yok; merge yalnızca `merge_pr` ile ve `local-ci`
  kontrolü başarılıysa yapılır. `demo-admin` bu şartı bypass edebilir; bypass PR kaydına ve
  `MergeResult`'a yazılır. Bot (`tp-bot`) merge edemez. Uygulama (Java + Appium) kontrolleri
  platform başınadır (`local-ci-android|ios|windows`, 009 §2.7): head için kaydedilmiş her biri
  de zorunludur; yalnızca `e2e-app/` değiştiren PR web `local-ci` yerine en az bir platform
  kontrolü ister (`forge.local_required_checks`). Web'de check adı dile göredir (011 K-T1):
  `e2e/` (TS) değiştiren PR `local-ci`, `e2e-java/` (Playwright for Java) değiştiren PR
  `local-ci-web-java` ister (yalnız `e2e-java/` değiştiren PR web `local-ci`'ı istemez). Liste
  `TP_REQUIRED_CHECKS` ile değişir.
- Güncel dal kuralı (GitHub "require branches to be up to date" / strict status checks): PR dalı
  `main`'in güncel head'ini içermiyorsa merge reddedilir — aksi halde hiçbir kontrolün koşmadığı
  bir birleşim ağacı `main`'e girerdi. Dal `update_branch` ile güncellenir (yeni head → PR CI'ı
  ve onay yeniden). `demo-admin` bypass'ı bu kuralı da aşar ve nedeni kayda yazılır.
  `TP_FORGE_REQUIRE_UP_TO_DATE=0` kuralı kapatır (varsayılan açık).
- `merge_pr(..., expected_head_sha=...)`: PR kilidi altında dal head'i onaylanan sha değilse
  `ForgeConflictError` (anayasa I: yalnızca onaylanan içerik merge edilir).
- Kontroller `TP_ARTIFACTS_PATH/checks/<sha>.json` dosyasından okunur (yerel CI runner'ı yazar).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from tp_core.integrations.forge import (
    BOT_ACTORS,
    BOT_EMAIL,
    BOT_NAME,
    BYPASS_ACTOR,
    LOCAL_REQUIRED_CHECKS,
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
    local_required_checks,
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

DEFAULT_FORGE_PATH = "/forge/demo-app.git"
DEFAULT_ARTIFACTS_PATH = "/artifacts"
PRS_FILE_NAME = "tp-prs.json"
REQUIRE_UP_TO_DATE_ENV = "TP_FORGE_REQUIRE_UP_TO_DATE"

_GIT_TIMEOUT_S = 60
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_SEARCH_RESULTS = 500
_MAX_TITLE_LEN = 256
_MAX_BODY_LEN = 65536


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _env_flag(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on", "evet"):
        return True
    if v in ("0", "false", "no", "off", "hayir", "hayır"):
        return False
    raise ForgeValidationError(f"{REQUIRE_UP_TO_DATE_ENV} geçersiz: {value!r} (1 | 0)")


class _PRStore:
    """`tp-prs.json`: {"next_number": int, "prs": [kayıt, ...]}."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")

    def load(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"next_number": 1, "prs": []}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ForgeError(f"PR kaydı bozuk: {self.path}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("prs"), list):
            raise ForgeError(f"PR kaydı beklenen biçimde değil: {self.path}")
        data.setdefault("next_number", 1 + max((p["number"] for p in data["prs"]), default=0))
        return data

    def _save(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".tp-prs.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            # core (10001) ve toolchain (1001) aynı dosyayı yazabilmeli.
            os.chmod(tmp, 0o666)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise

    @contextlib.contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        """Özel kilit altında oku-değiştir-yaz. Gövde hata verirse hiçbir şey yazılmaz."""
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            with contextlib.suppress(PermissionError):
                os.fchmod(fd, 0o666)
            fcntl.flock(fd, fcntl.LOCK_EX)
            data = self.load()
            yield data
            self._save(data)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


class LocalForge:
    """Bare git deposu + JSON PR kaydı. `ForgePort`'u uygular."""

    def __init__(
        self,
        repo_path: str | os.PathLike[str],
        artifacts_path: str | os.PathLike[str] | None = None,
        prs_path: str | os.PathLike[str] | None = None,
        *,
        git_binary: str = "git",
        required_checks: Sequence[str] = LOCAL_REQUIRED_CHECKS,
        require_up_to_date: bool = True,
        checks_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.path = Path(repo_path)
        self.artifacts_path = Path(artifacts_path) if artifacts_path else None
        # Kapı dizini: ayrı volume (`TP_CHECKS_PATH`, tp_checks) ya da `<artifacts>/checks`.
        self.checks_path = Path(checks_path) if checks_path else None
        self._prs = _PRStore(Path(prs_path) if prs_path else self.path.parent / PRS_FILE_NAME)
        self._git_binary = git_binary
        self.required_checks = validate_required_checks(required_checks)
        self.require_up_to_date = bool(require_up_to_date)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LocalForge:
        env = os.environ if env is None else env
        return cls(
            env.get("TP_FORGE_PATH") or DEFAULT_FORGE_PATH,
            env.get("TP_ARTIFACTS_PATH") or DEFAULT_ARTIFACTS_PATH,
            env.get("TP_FORGE_PRS_PATH") or None,
            # MIMARI-SOZLESME: `TP_REQUIRED_CHECKS` boş = `local-ci` (ör. platform kontrolünü her
            # PR'da zorunlu kılmak için `local-ci,local-ci-android`).
            required_checks=parse_required_checks(
                env.get(REQUIRED_CHECKS_ENV), LOCAL_REQUIRED_CHECKS
            ),
            require_up_to_date=_env_flag(env.get(REQUIRE_UP_TO_DATE_ENV), default=True),
            checks_path=env.get("TP_CHECKS_PATH") or None,
        )

    # ------------------------------------------------------------------ git çekirdeği

    def available(self) -> bool:
        return (self.path / "HEAD").is_file() and (self.path / "objects").is_dir()

    def _env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_LITERAL_PATHSPECS": "1",
            "GIT_AUTHOR_NAME": BOT_NAME,
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_NAME": BOT_NAME,
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
        }
        if extra:
            env.update(extra)
        return env

    def _git(
        self,
        *args: str,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
        ok: Sequence[int] = (0,),
    ) -> subprocess.CompletedProcess[bytes]:
        if not self.available():
            raise ForgeNotFoundError(
                f"forge deposu bulunamadı: {self.path} (scripts/forge-init.sh çalıştırın)"
            )
        cmd = [
            self._git_binary,
            # Depo başka uid'e ait olabilir (volume paylaşımı); yalnızca bu git-dir kullanılır.
            "-c",
            "safe.directory=*",
            "-c",
            "core.hooksPath=/dev/null",
            "--git-dir",
            str(self.path),
            *args,
        ]
        try:
            proc = subprocess.run(  # kabuk yok, argümanlar doğrulanmış
                cmd,
                input=stdin,
                capture_output=True,
                env=self._env(env),
                timeout=_GIT_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ForgeError(f"git zaman aşımı: {args[0]}") from exc
        if proc.returncode not in ok:
            msg = proc.stderr.decode("utf-8", "replace").strip()
            raise ForgeError(f"git {args[0]} başarısız ({proc.returncode}): {msg}")
        return proc

    def _out(self, *args: str, **kw: Any) -> str:
        return self._git(*args, **kw).stdout.decode("utf-8", "replace").strip()

    def _rev(self, spec: str) -> str | None:
        proc = self._git("rev-parse", "--verify", "--quiet", "--end-of-options", spec, ok=(0, 1))
        out = proc.stdout.decode().strip()
        return out if proc.returncode == 0 and out else None

    def _branch_head(self, branch: str) -> str | None:
        validate_branch(branch)
        return self._rev(f"refs/heads/{branch}^{{commit}}")

    def _resolve(self, ref: str) -> str:
        """Commit sha'sı. Sıra: tam sha → refs/heads/<ref> → refs/tags/<ref> (belirsizlik yok)."""
        validate_ref(ref)
        candidates = [ref] if is_sha(ref) else [f"refs/heads/{ref}", f"refs/tags/{ref}"]
        for cand in candidates:
            sha = self._rev(f"{cand}^{{commit}}")
            if sha:
                return sha
        raise ForgeNotFoundError(f"ref bulunamadı: {ref}")

    def _is_ancestor(self, ancestor: str, descendant: str) -> bool:
        proc = self._git("merge-base", "--is-ancestor", ancestor, descendant, ok=(0, 1))
        return proc.returncode == 0

    def _tree_entries(self, commit: str) -> dict[str, tuple[str, str]]:
        """path → (mode, type) — özyinelemeli, dizinler dahil (-t)."""
        raw = self._git("ls-tree", "-r", "-t", "-z", "--full-tree", commit).stdout
        entries: dict[str, tuple[str, str]] = {}
        for item in raw.split(b"\0"):
            if not item:
                continue
            meta, _, path = item.partition(b"\t")
            mode, typ, _sha = meta.decode().split(" ")
            entries[path.decode("utf-8", "surrogateescape")] = (mode, typ)
        return entries

    # ------------------------------------------------------------------ okuma

    def head_sha(self, ref: str = "main") -> str:
        return self._resolve(ref)

    def read_file(self, path: str, ref: str = "main") -> str:
        validate_path(path)
        sha = self._resolve(ref)
        spec = f"{sha}:{path}"
        typ = self._git("cat-file", "-t", spec, ok=(0, 1, 128))
        if typ.returncode != 0:
            raise ForgeNotFoundError(f"dosya bulunamadı: {path} @ {ref}")
        if typ.stdout.decode().strip() != "blob":
            raise ForgeNotFoundError(f"dosya değil: {path} @ {ref}")
        size = int(self._out("cat-file", "-s", spec))
        if size > _MAX_FILE_BYTES:
            raise ForgeError(f"dosya çok büyük ({size} bayt): {path}")
        return self._git("cat-file", "blob", spec).stdout.decode("utf-8", "replace")

    def changed_paths(self, base: str, head: str) -> list[str]:
        """`base`..`head` arasında değişen (eklenen/silinen/değişen) dosya yolları."""
        a, b = self._resolve(base), self._resolve(head)
        raw = self._git("diff", "--name-only", "-z", "--no-renames", a, b).stdout
        return sorted({n.decode("utf-8", "surrogateescape") for n in raw.split(b"\0") if n})

    def merge_base(self, a: str, b: str) -> str:
        """`a` ve `b`'nin ortak atası (üç noktalı fark tabanı); yoksa ForgeError."""
        ra, rb = self._resolve(a), self._resolve(b)
        proc = self._git("merge-base", ra, rb, ok=(0, 1))
        sha = proc.stdout.decode().strip()
        if proc.returncode != 0 or not is_sha(sha):
            raise ForgeError(f"ortak ata yok: {a} / {b}")
        return sha

    def list_files(self, prefix: str = "", ref: str = "main") -> list[str]:
        validate_prefix(prefix)
        sha = self._resolve(ref)
        raw = self._git("ls-tree", "-r", "-z", "--name-only", "--full-tree", sha).stdout
        names = [n.decode("utf-8", "surrogateescape") for n in raw.split(b"\0") if n]
        return sorted(n for n in names if n.startswith(prefix))

    def search_code(self, query: str, ref: str = "main") -> list[tuple[str, int, str]]:
        """Sabit metin araması (regex değil): [(yol, satır no, satır)], en çok 500 sonuç."""
        validate_query(query)
        sha = self._resolve(ref)
        proc = self._git(
            "grep",
            "-n",
            "-I",
            "-z",
            "--full-name",
            "--fixed-strings",
            "-e",
            query,
            sha,
            "--",
            ok=(0, 1),
        )
        if proc.returncode == 1:
            return []
        prefix = f"{sha}:".encode()
        results: list[tuple[str, int, str]] = []
        for line in proc.stdout.split(b"\n"):
            if not line:
                continue
            parts = line.split(b"\0", 2)
            if len(parts) != 3:
                continue
            name, lineno, text = parts
            name = name.removeprefix(prefix)
            path = name.decode("utf-8", "surrogateescape")
            results.append((path, int(lineno), text.decode("utf-8", "replace")))
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
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

        old = self._branch_head(branch)
        parent = old or self._resolve(base)
        entries = self._tree_entries(parent)
        for path in blobs:
            if entries.get(path, ("", ""))[1] == "tree":
                raise ForgeValidationError(f"yol bir dizin: {path}")
            parts = path.split("/")
            for i in range(1, len(parts)):
                anc = "/".join(parts[:i])
                if anc in entries and entries[anc][1] != "tree":
                    raise ForgeValidationError(f"üst yol bir dosya: {anc}")

        with tempfile.TemporaryDirectory(prefix="tp-forge-") as tmp:
            idx_env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            self._git("read-tree", parent, env=idx_env)
            info = bytearray()
            for path, data in blobs.items():
                blob = self._out("hash-object", "-w", "--stdin", stdin=data)
                mode = entries.get(path, ("100644", "blob"))[0]
                if mode not in ("100644", "100755"):
                    mode = "100644"
                info += f"{mode} {blob}\t{path}".encode() + b"\0"
            self._git("update-index", "-z", "--index-info", stdin=bytes(info), env=idx_env)
            tree = self._out("write-tree", env=idx_env)

        if tree == self._rev(f"{parent}^{{tree}}"):
            new = parent  # değişiklik yok: boş commit üretilmez
        else:
            new = self._out("commit-tree", tree, "-p", parent, "-F", "-", stdin=message.encode())
        if new != old:
            self._update_ref(branch, new, old, f"tp: commit_files {branch}")
        return new

    def _update_ref(self, branch: str, new: str, old: str | None, reason: str) -> None:
        expected = old if old else "0" * len(new)
        proc = self._git(
            "update-ref", "-m", reason, f"refs/heads/{branch}", new, expected, ok=(0, 1, 128)
        )
        if proc.returncode != 0:
            raise ForgeConflictError(f"'{branch}' eşzamanlı değişti; işlemi yeniden deneyin")

    # ------------------------------------------------------------------ PR

    def _record_to_pr(self, rec: Mapping[str, Any]) -> PullRequest:
        head = rec["head_sha"]
        if rec["state"] == "open":
            head = self._branch_head(rec["branch"]) or head
        return PullRequest(
            number=rec["number"],
            branch=rec["branch"],
            base=rec["base"],
            title=rec["title"],
            body=rec.get("body", ""),
            state=rec["state"],
            head_sha=head,
            url=None,
            labels=list(rec.get("labels", [])),
        )

    @staticmethod
    def _find(data: Mapping[str, Any], number: int) -> dict[str, Any]:
        for rec in data["prs"]:
            if rec["number"] == number:
                return rec
        raise ForgeNotFoundError(f"PR bulunamadı: #{number}")

    def find_open_pr(self, branch: str) -> PullRequest | None:
        validate_branch(branch)
        for rec in self._prs.load()["prs"]:
            if rec["branch"] == branch and rec["state"] == "open":
                return self._record_to_pr(rec)
        return None

    def list_prs(self, state: str | None = None) -> list[PullRequest]:
        recs = self._prs.load()["prs"]
        return [self._record_to_pr(r) for r in recs if state is None or r["state"] == state]

    def open_pr(
        self, branch: str, title: str, body: str, labels: Sequence[str] = ()
    ) -> PullRequest:
        """İdempotent: dal için açık PR varsa onu döndürür."""
        validate_branch(branch)
        if branch in PROTECTED_BRANCHES:
            raise ForgeValidationError("korunan daldan PR açılamaz")
        if not isinstance(title, str) or not title.strip() or len(title) > _MAX_TITLE_LEN:
            raise ForgeValidationError("PR başlığı boş veya çok uzun")
        if len(body) > _MAX_BODY_LEN:
            raise ForgeValidationError("PR açıklaması çok uzun")
        clean_labels = [validate_label(lbl) for lbl in labels]
        base = "main"
        head = self._branch_head(branch)
        if head is None:
            raise ForgeNotFoundError(f"dal bulunamadı: {branch}")
        base_head = self._branch_head(base)
        if base_head is None:
            raise ForgeNotFoundError(f"temel dal bulunamadı: {base}")
        with self._prs.transaction() as data:
            for rec in data["prs"]:
                if rec["branch"] == branch and rec["state"] == "open":
                    return self._record_to_pr(rec)
            if self._is_ancestor(head, base_head):
                raise ForgeStateError(f"'{branch}' dalında '{base}'e göre yeni commit yok")
            number = int(data["next_number"])
            data["next_number"] = number + 1
            now = _now()
            rec = {
                "number": number,
                "branch": branch,
                "base": base,
                "title": title,
                "body": body,
                "state": "open",
                "head_sha": head,
                "labels": list(dict.fromkeys(clean_labels)),
                "comments": [],
                "merged_sha": None,
                "merged_by": None,
                "merged_at": None,
                "bypass": False,
                "bypass_reason": None,
                "created_at": now,
                "updated_at": now,
            }
            data["prs"].append(rec)
        return self._record_to_pr(rec)

    def get_pr(self, number: int) -> PullRequest:
        return self._record_to_pr(self._find(self._prs.load(), number))

    def get_pr_record(self, number: int) -> dict[str, Any]:
        """Ham kayıt (yorumlar, merge ayrıntısı, bypass) — portal ve denetim için."""
        return dict(self._find(self._prs.load(), number))

    def comment_pr(self, number: int, body: str, *, author: str = BOT_NAME) -> None:
        validate_actor(author)
        if not isinstance(body, str) or not body.strip() or len(body) > _MAX_BODY_LEN:
            raise ForgeValidationError("yorum boş veya çok uzun")
        with self._prs.transaction() as data:
            rec = self._find(data, number)
            rec.setdefault("comments", []).append({"author": author, "body": body, "at": _now()})
            rec["updated_at"] = _now()

    def close_pr(self, number: int) -> None:
        with self._prs.transaction() as data:
            rec = self._find(data, number)
            if rec["state"] != "open":
                raise ForgeStateError(f"PR #{number} açık değil ({rec['state']})")
            rec["head_sha"] = self._branch_head(rec["branch"]) or rec["head_sha"]
            rec["state"] = "closed"
            rec["updated_at"] = _now()

    def merge_pr(self, number: int, actor: str, *, expected_head_sha: str | None = None) -> str:
        return self.merge_pr_detailed(number, actor, expected_head_sha=expected_head_sha).sha

    def merge_pr_detailed(
        self, number: int, actor: str, *, expected_head_sha: str | None = None
    ) -> MergeResult:
        """`expected_head_sha` verilirse yalnızca dal tam o commit'teyken merge eder."""
        validate_actor(actor)
        if expected_head_sha is not None and not is_sha(expected_head_sha):
            raise ForgeValidationError(f"geçersiz beklenen head sha: {expected_head_sha!r}")
        if actor in BOT_ACTORS:
            raise ForgeProtectionError("bot PR merge edemez; merge insan onayı gerektirir")
        with self._prs.transaction() as data:
            rec = self._find(data, number)
            if rec["state"] != "open":
                raise ForgeStateError(f"PR #{number} açık değil ({rec['state']})")
            head = self._branch_head(rec["branch"])
            if head is None:
                raise ForgeNotFoundError(f"PR dalı bulunamadı: {rec['branch']}")
            if expected_head_sha is not None and head != expected_head_sha:
                raise ForgeConflictError(
                    f"PR #{number} head'i onaylanandan farklı "
                    f"(beklenen {expected_head_sha[:12]}, güncel {head[:12]}); yeniden onay gerekli"
                )
            base_head = self._branch_head(rec["base"])
            if base_head is None:
                raise ForgeNotFoundError(f"temel dal bulunamadı: {rec['base']}")

            checks = self.checks(head)
            # Platform/dil başına kapı (009 §2.7, 011 K-T1): kayıtlı uygulama / web + Java
            # kontrolleri de zorunlu; e2e-java/ değiştiren PR local-ci-web-java ister.
            fark_tabani = self._merge_base(base_head, head)
            degisen = self.changed_paths(fark_tabani, head) if is_sha(fark_tabani) else []
            zorunlu, platform_eksik = local_required_checks(self.required_checks, checks, degisen)
            verdict = evaluate_required_checks(checks, zorunlu)
            ihlaller: list[str] = []
            nedenler = [r for r in (verdict.reason() if not verdict.passed else "",
                                    platform_eksik or "") if r]  # fmt: skip
            if nedenler:
                if actor != BYPASS_ACTOR:
                    raise ForgeProtectionError(
                        f"merge için zorunlu kontroller başarılı olmalı ({'; '.join(nedenler)})"
                    )
                ihlaller.extend(nedenler)
            # Güncel dal kuralı: kontroller yalnızca `head` üzerinde koştu; base ilerlemişse
            # merge ağacı (head + yeni base) hiç test edilmemiştir.
            if (
                self.require_up_to_date
                and not self._is_ancestor(base_head, head)
                and not self._is_ancestor(head, base_head)
            ):
                stale = (
                    f"PR dalı '{rec['base']}'e göre güncel değil "
                    f"(dal tabanı {self._merge_base(base_head, head)[:12]}, "
                    f"{rec['base']} {base_head[:12]})"
                )
                if actor != BYPASS_ACTOR:
                    raise ForgeProtectionError(
                        f"{stale}; önce dalı güncelleyin (update_branch) ve local-ci'yi "
                        "yeni head üzerinde yeniden koşturun"
                    )
                ihlaller.append(stale)
            bypass = bool(ihlaller)
            reason = f"{'; '.join(ihlaller)}; {BYPASS_ACTOR} kural bypass'ı" if bypass else None

            if self._is_ancestor(head, base_head):
                method, new = "already-merged", base_head
            elif self._is_ancestor(base_head, head):
                method, new = "fast-forward", head
            else:
                method = "merge-commit"
                new = self._merge_commit(rec, base_head, head, actor)
            if new != base_head:
                self._update_ref(rec["base"], new, base_head, f"tp: merge PR #{number} ({actor})")

            now = _now()
            rec.update(
                state="merged",
                head_sha=head,
                merged_sha=new,
                merged_by=actor,
                merged_at=now,
                merge_method=method,
                bypass=bypass,
                bypass_reason=reason,
                updated_at=now,
            )
        return MergeResult(
            number=number,
            sha=new,
            actor=actor,
            method=method,
            bypass=bypass,
            bypass_reason=reason,
            checks=checks,
        )

    def _merge_base(self, a: str, b: str) -> str:
        proc = self._git("merge-base", a, b, ok=(0, 1))
        return proc.stdout.decode().strip() or "?"

    def update_branch(
        self, number: int, actor: str = BOT_NAME, *, expected_head_sha: str | None = None
    ) -> str:
        """GitHub "Update branch": temel dalı PR dalına merge eder; yeni (veya aynı) head döner.

        Dal zaten güncelse hiçbir şey yazılmaz. Yeni head üzerinde PR CI'ı yeniden koşmalı ve
        (head sha'ya bağlı) insan onayı yenilenmelidir. Çakışmada `ForgeConflictError`.
        `expected_head_sha` verilirse PR kilidi altında dal head'i tam o commit değilse (dala
        yabancı commit girmişse) hiçbir şey yazılmaz, `ForgeStateError` (GitHub 422 eşdeğeri).
        """
        validate_actor(actor)
        if expected_head_sha is not None and not is_sha(expected_head_sha):
            raise ForgeValidationError(f"geçersiz beklenen head sha: {expected_head_sha!r}")
        with self._prs.transaction() as data:
            rec = self._find(data, number)
            if rec["state"] != "open":
                raise ForgeStateError(f"PR #{number} açık değil ({rec['state']})")
            head = self._branch_head(rec["branch"])
            if head is None:
                raise ForgeNotFoundError(f"PR dalı bulunamadı: {rec['branch']}")
            if expected_head_sha is not None and head != expected_head_sha:
                raise ForgeStateError(
                    f"PR #{number} dalı beklenen head'de değil "
                    f"(beklenen {expected_head_sha[:12]}, güncel {head[:12]})"
                    "; güncelleme reddedildi"
                )
            base_head = self._branch_head(rec["base"])
            if base_head is None:
                raise ForgeNotFoundError(f"temel dal bulunamadı: {rec['base']}")
            if self._is_ancestor(base_head, head):
                return head
            new = self._merge_tree_commit(
                number,
                base_head,
                head,
                actor,
                f"Merge {rec['base']} into {rec['branch']}\n\nPR #{number} dalı güncellendi.\n",
                parents=(head, base_head),
            )
            self._update_ref(rec["branch"], new, head, f"tp: update PR #{number} ({actor})")
            rec["head_sha"] = new
            rec["updated_at"] = _now()
        return new

    def _merge_commit(self, rec: Mapping[str, Any], base_head: str, head: str, actor: str) -> str:
        message = f"Merge PR #{rec['number']} from {rec['branch']}\n\n{rec['title']}\n"
        return self._merge_tree_commit(
            rec["number"], base_head, head, actor, message, parents=(base_head, head)
        )

    def _merge_tree_commit(
        self,
        number: int,
        base_head: str,
        head: str,
        actor: str,
        message: str,
        *,
        parents: tuple[str, str],
    ) -> str:
        proc = self._git(
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--no-messages",
            base_head,
            head,
            ok=(0, 1),
        )
        lines = proc.stdout.decode("utf-8", "replace").splitlines()
        if proc.returncode == 1:
            conflicted = sorted({ln for ln in lines[1:] if ln})
            raise ForgeConflictError(
                f"PR #{number} çakışıyor: {', '.join(conflicted) or 'bilinmeyen dosya'}"
            )
        tree = lines[0].strip()
        who = {
            "GIT_AUTHOR_NAME": actor,
            "GIT_AUTHOR_EMAIL": f"{actor}@testingprobe.local",
            "GIT_COMMITTER_NAME": actor,
            "GIT_COMMITTER_EMAIL": f"{actor}@testingprobe.local",
        }
        return self._out(
            "commit-tree", tree, "-p", parents[0], "-p", parents[1], "-F", "-",
            stdin=message.encode(), env=who,
        )  # fmt: skip

    # ------------------------------------------------------------------ demo yönetimi

    def tree_sha(self, ref: str = "main", path: str = "web") -> str | None:
        """`ref`'teki `path` dizininin git ağaç sha'sı (yoksa / dizin değilse None)."""
        sha = self._resolve(ref)
        validate_path(path)
        spec = f"{sha}:{path}"
        typ = self._git("cat-file", "-t", spec, ok=(0, 1, 128))
        if typ.returncode != 0 or typ.stdout.decode().strip() != "tree":
            return None
        return self._rev(spec)

    def archive(self, ref: str = "main", path: str = "") -> bytes:
        """`ref`'teki ağacın (veya `path` alt dizininin) tar arşivi; kök = `path`.

        Demo uygulamasının imajını forge `main` HEAD'inden derlemek için (çalışma ağacından değil).
        """
        sha = self._resolve(ref)
        treeish = sha
        if path:
            validate_path(path)
            typ = self._git("cat-file", "-t", f"{sha}:{path}", ok=(0, 1, 128))
            if typ.returncode != 0 or typ.stdout.decode().strip() != "tree":
                raise ForgeNotFoundError(f"dizin bulunamadı: {path} @ {ref}")
            treeish = f"{sha}:{path}"
        return self._git("archive", "--format=tar", treeish).stdout

    def reset_branch(self, branch: str, target: str, *, actor: str) -> tuple[str | None, str]:
        """Yönetici işlemi: dalı `target` commit'ine taşır (korunan dal dahil). Yalnızca
        `demo-admin`; açık PR kayıtlarına dokunmaz. (eski sha, yeni sha) döndürür.

        Demo sıfırlaması (`main` → `demo-baseline`) içindir; çağıran denetime yazar.
        """
        validate_actor(actor)
        if actor != BYPASS_ACTOR:
            raise ForgeProtectionError(f"dal sıfırlama yalnızca {BYPASS_ACTOR} ile yapılabilir")
        validate_branch(branch)
        new = self._resolve(target)
        with self._prs.transaction():  # merge'lerle yarışmasın
            old = self._branch_head(branch)
            if old != new:
                self._update_ref(branch, new, old, f"tp: reset {branch} → {target} ({actor})")
        return old, new

    # ------------------------------------------------------------------ kontroller

    def checks(self, sha: str) -> list[CheckRun]:
        """`<checks>/<sha>.json` (`TP_CHECKS_PATH`, yoksa `<artifacts>/checks`): CheckRun listesi
        veya {"checks": [...]}; yoksa []."""
        full = sha if is_sha(sha) else self._resolve(sha)
        if self.checks_path is not None:
            path = self.checks_path / f"{full}.json"
        elif self.artifacts_path is not None:
            path = self.artifacts_path / "checks" / f"{full}.json"
        else:
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        try:
            data: Any = json.loads(raw)
            if isinstance(data, dict):
                data = data.get("checks", [data] if "name" in data else [])
            if not isinstance(data, list):
                raise TypeError("liste bekleniyordu")
            return [CheckRun.model_validate(item) for item in data]
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ForgeError(f"kontrol dosyası okunamadı: {path}: {exc}") from exc
