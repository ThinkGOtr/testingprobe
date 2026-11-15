"""CI şeridinin dış bağımlılık fabrikaları (testler `override` ile değiştirir; kod yolu aynı)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tp_core.config import get_settings
from tp_core.proje import istemciler
from tp_core.proje.ayar import ayar

_overrides: dict[str, Callable[..., Any]] = {}


def mode() -> str:
    """`local` (LocalForge + toolchain-worker) veya `github` (Actions + GitHub API)."""
    f = _overrides.get("mode")
    if f is not None:
        return str(f())
    return (ayar("TP_FORGE") or "local").strip().lower() or "local"


def forge() -> Any:
    f = _overrides.get("forge")
    if f is not None:
        return f()
    return istemciler.forge()


def toolchain() -> Any:
    f = _overrides.get("toolchain")
    if f is not None:
        return f()
    from tp_core.features.ci.clients import ToolchainClient

    return ToolchainClient(get_settings().toolchain_url, token=get_settings().toolchain_token)


def github() -> Any:
    f = _overrides.get("github")
    if f is not None:
        return f()
    if "forge" not in _overrides:
        istemci = istemciler.ci()
        if istemci is not None:
            return istemci
    from tp_core.features.ci.clients import GitHubCi

    return GitHubCi(forge())


def artifacts_root() -> Path:
    f = _overrides.get("artifacts_root")
    if f is not None:
        return Path(f())
    return Path(get_settings().artifacts_path)


def github_artifacts_root() -> Path:
    """GitHub koşu artefaktlarının yerel kopyası (`TP_GITHUB_ARTIFACTS_PATH`; yoksa artefakt
    kökü)."""
    f = _overrides.get("github_artifacts_root")
    if f is not None:
        return Path(f())
    yol = get_settings().github_artifacts_path
    return Path(yol) if yol else artifacts_root()


def checks_root() -> Path:
    """Merge kapısı dosyalarının dizini (`TP_CHECKS_PATH`; yoksa `<artifacts>/checks`)."""
    f = _overrides.get("checks_root")
    if f is not None:
        return Path(f())
    yol = get_settings().checks_path
    return Path(yol) if yol else artifacts_root() / "checks"


def now() -> datetime:
    f = _overrides.get("now")
    if f is not None:
        return f()
    return datetime.now(UTC)


@contextmanager
def override(**fabrikalar: Callable[..., Any]) -> Iterator[None]:
    eski = dict(_overrides)
    _overrides.update(fabrikalar)
    try:
        yield
    finally:
        _overrides.clear()
        _overrides.update(eski)
