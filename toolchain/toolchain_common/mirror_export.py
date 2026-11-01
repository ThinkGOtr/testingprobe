"""GitHub kipi: çalışan demo-app-web'in derleme girdisi forge aynasından (salt okuma).

    python -m toolchain_common.mirror_export archive --ref <tam sha> --path demo-app/web > web.tar
    python -m toolchain_common.mirror_export tree    --ref <tam sha> --path demo-app/web

`scripts/demo-web-sync.sh` GitHub kipinde (`TP_FORGE=github`) bunu toolchain-worker içinde
çalıştırır: core'un istediği commit (GitHub main) `repos.locate(fetch=True)` ile önce yerel
forge'da / aynada aranır, yoksa `TP_FORGE_REMOTE_URL`'den salt okunur belirteçle
(`TP_FORGE_REMOTE_TOKEN`, yalnızca http başlığında) aynaya çekilir. `archive` `<sha>:<path>`
ağacının tar'ını stdout'a yazar (kökte Dockerfile); `tree` aynı ağacın git kimliğini yazar
(`DEMO_APP_WEB_TREE` → `/build.json` `web_tree`). Yazma kimliği ve forge'a yazım yoktur.

Yalnızca tam (40 hex) commit sha'sı kabul edilir: istek core'un çözdüğü sha'dır; ad (main)
burada çözülmez (yarış: ad bu arada ilerleyebilir). Çıkış: 0 tamam · 2 kullanım/doğrulama ·
3 commit ya da dizin yok · 4 forge/ayna hatası.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence

from toolchain_common import gitforge, repos
from toolchain_common.settings import Settings, settings

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}\Z")
PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*\Z")


def _validate(sha: str, path: str) -> None:
    if not FULL_SHA_RE.match(sha or ""):
        raise ValueError(f"tam commit sha'sı gerekli (40 hex): {sha!r}")
    if not PATH_RE.match(path or "") or ".." in path.split("/") or len(path) > 200:
        raise ValueError(f"geçersiz depo içi yol: {path!r}")


def _archive(cfg: Settings, loc: repos.Located, path: str) -> bytes:
    if gitforge.tree_id(loc.repo, loc.sha, path, cfg.git_timeout_s) is None:
        raise gitforge.CommitNotFound(f"{loc.sha[:12]} commit'inde '{path}' dizini yok")
    try:
        out = subprocess.run(
            gitforge._git_argv(loc.repo, "archive", "--format=tar", f"{loc.sha}:{path}"),
            env=gitforge.git_env(),
            capture_output=True,
            timeout=cfg.git_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise gitforge.ForgeError("git archive süre aşımı") from exc
    if out.returncode != 0:
        msg = out.stderr.decode("utf-8", "replace").strip()
        raise gitforge.ForgeError(f"git archive başarısız ({loc.sha[:12]}:{path}): {msg[:300]}")
    return out.stdout


def main(argv: Sequence[str] | None = None, cfg: Settings | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m toolchain_common.mirror_export")
    p.add_argument("komut", choices=("archive", "tree"))
    p.add_argument("--ref", required=True, help="tam commit sha'sı")
    p.add_argument("--path", required=True, help="depo içi dizin (ör. demo-app/web)")
    a = p.parse_args(argv)
    cfg = cfg or settings()
    try:
        _validate(a.ref, a.path)
    except ValueError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    try:
        loc = repos.locate(cfg, a.ref, fetch=True)
        if a.komut == "tree":
            oid = gitforge.tree_id(loc.repo, loc.sha, a.path, cfg.git_timeout_s)
            if oid is None:
                raise gitforge.CommitNotFound(f"{loc.sha[:12]} commit'inde '{a.path}' yok")
            print(oid)
            return 0
        sys.stdout.buffer.write(_archive(cfg, loc, a.path))
        sys.stdout.buffer.flush()
        return 0
    except gitforge.CommitNotFound as exc:
        uzak = (
            "" if cfg.forge_remote_url else " (TP_FORGE_REMOTE_URL tanımlı değil: ayna çekilemez)"
        )
        print(f"HATA: {exc}{uzak}", file=sys.stderr)
        return 3
    except gitforge.ForgeError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
