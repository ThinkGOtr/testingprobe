"""Commit'in hangi depoda olduğu: yerel forge (LocalForge) ya da GitHub aynası.

GitHub modunda (`TP_FORGE=github`) core sha'ları GitHub'dan alır; bu sha'lar yerel bare forge'da
yoktur. toolchain-worker, `TP_FORGE_REMOTE_URL` verilmişse eksik commit'i salt okunur olarak
`TP_FORGE_MIRROR_PATH` aynasına çeker (yalnızca `git fetch`; yazma kimliği yok). test-runner aynı
aynayı salt okunur bağlar ve yalnızca okur (internetsiz). Böylece `/symbols → /check → /run`
yerel ve GitHub modunda aynı kod yolundan geçer.

Çözüm kuralı:
- Tam/kısa hex sha: önce yerel forge, sonra ayna; ikisinde de yoksa (ve uzak depo varsa) çekilir.
  Sha içerik kimliğidir: hangi depoda bulunursa bulunsun aynı commit'tir.
- Ref adı (`main`, `tp/case-…`): uzak depo yapılandırılmışsa ad her seferinde uzaktan tazelenir ve
  aynada çözülür (yerel forge'daki eski `main` GitHub modunda yanıltıcı olurdu); yoksa aynası
  olan (ayna varsa önce ayna) depoda çözülür.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from toolchain_common import gitforge
from toolchain_common.settings import Settings
from toolchain_common.validation import SHA_RE, validate_ref

FULL_SHA_LEN = 40
_FETCH_LOCK = threading.Lock()


@dataclass(frozen=True)
class Located:
    repo: Path
    sha: str
    kaynak: str  # "forge" | "ayna"


def _mirror_ready(cfg: Settings) -> bool:
    return (cfg.forge_mirror_path / "HEAD").is_file()


def _try(repo: Path, ref: str, cfg: Settings) -> str | None:
    if not (repo / "HEAD").is_file():
        return None
    try:
        return gitforge.resolve_commit(repo, ref, cfg.git_timeout_s)
    except gitforge.CommitNotFound:
        return None


def _fetch(cfg: Settings, ref: str) -> None:
    """Uzak depodan `ref`'i (ve `main`'i: merge-base/ast-guard tabanı) aynaya çeker."""
    gitforge.init_mirror(cfg.forge_mirror_path, cfg.git_timeout_s)
    base = ["+refs/heads/main:refs/heads/main"]
    if SHA_RE.match(ref) and len(ref) == FULL_SHA_LEN:
        wanted = [f"+{ref}:refs/tp/{ref}"]
    elif SHA_RE.match(ref):
        wanted = []  # kısa sha uzaktan doğrudan istenemez: dallar + PR başları çekilir
    else:
        wanted = [f"+refs/heads/{ref}:refs/heads/{ref}"]
    url, token, timeout = cfg.forge_remote_url, cfg.forge_remote_token, cfg.fetch_timeout_s
    with _FETCH_LOCK:
        if wanted and gitforge.fetch(cfg.forge_mirror_path, url, base + wanted, token, timeout):
            return
        # Sunucu sha ile istemeye izin vermiyorsa (ya da kısa sha): tüm dallar + PR başları.
        gitforge.fetch(
            cfg.forge_mirror_path,
            url,
            ["+refs/heads/*:refs/heads/*", "+refs/pull/*/head:refs/pull/*/head"],
            token,
            timeout,
        )


def locate(cfg: Settings, ref: str, *, fetch: bool = False, prefer: Path | None = None) -> Located:
    """`ref`'i forge ya da aynada tam sha'ya çözer; `fetch` ise eksikte uzaktan çeker.

    `prefer` verilirse önce o depoda aranır (ör. PR tabanı, head ile aynı depoda).
    Bulunamazsa `gitforge.CommitNotFound`; forge okunamazsa `gitforge.ForgeError`.
    """
    validate_ref(ref)
    forge, mirror = cfg.forge_path, cfg.forge_mirror_path
    remote = bool(cfg.forge_remote_url) and fetch
    is_sha = bool(SHA_RE.match(ref))

    if not is_sha and remote:
        _fetch(cfg, ref)
        sha = _try(mirror, ref, cfg)
        if sha:
            return Located(mirror, sha, "ayna")
        raise gitforge.CommitNotFound(f"commit bulunamadı: {ref} (uzak depoda da yok)")

    order = [forge, mirror] if is_sha else [mirror, forge]
    if prefer is not None and prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)
    for repo in order:
        if repo == mirror and not _mirror_ready(cfg):
            continue
        sha = _try(repo, ref, cfg)
        if sha:
            return Located(repo, sha, "ayna" if repo == mirror else "forge")
    if remote:
        _fetch(cfg, ref)
        sha = _try(mirror, ref, cfg)
        if sha:
            return Located(mirror, sha, "ayna")
    if not (forge / "HEAD").is_file() and not _mirror_ready(cfg):
        raise gitforge.ForgeError(f"forge deposu bulunamadı: {forge} (make forge-init)")
    raise gitforge.CommitNotFound(f"commit bulunamadı: {ref}")
