"""ast-guard CLI'ını forge'daki iki commit üzerinde çalıştırır (git-ref modu).

CLI ref'leri `git -C <bare repo>` ile okur; bu, iki checkout'u karşılaştırmakla aynı ağaçları
görür ve CI'daki kullanımla aynıdır. Depo başka uid'e ait olduğu için `safe.directory` ortamdan
verilir. Çıkış kodları: 0 geçti · 1 ihlal · 2 kullanım/çalışma hatası.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from toolchain_common import gitforge, proc
from toolchain_common.settings import Settings

MODES = ("repair", "pr")


class AstGuardError(RuntimeError):
    """ast-guard çalışamadı (çözülemeyen ref, süre aşımı, bozuk çıktı)."""


def run_ast_guard(
    cfg: Settings, base_sha: str, head_sha: str, mode: str, repo: Path | None = None
) -> dict[str, Any]:
    """`repo` iki commit'i de içeren depo (varsayılan yerel forge; GitHub modunda ayna)."""
    if mode not in MODES:
        raise ValueError(f"mod yalnızca {MODES} olabilir")
    res = proc.run(
        [
            cfg.node,
            str(cfg.ast_guard_cli),
            "--repo",
            str(repo or cfg.forge_path),
            "--base",
            base_sha,
            "--head",
            head_sha,
            "--root",
            cfg.e2e_root,
            "--mode",
            mode,
        ],
        env=gitforge.git_env(),
        timeout_s=cfg.ast_guard_timeout_s,
        keep_full_stdout=True,
    )
    if res.timed_out:
        raise AstGuardError(f"ast-guard süre sınırını aştı ({int(cfg.ast_guard_timeout_s)} sn)")
    try:
        report = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise AstGuardError(f"ast-guard çıktısı okunamadı: {res.stderr.strip()[:500]}") from exc
    if res.exit_code == 2 or not isinstance(report, dict) or "violations" not in report:
        msg = report.get("error") if isinstance(report, dict) else None
        raise AstGuardError(f"ast-guard çalışamadı: {msg or res.stderr.strip()[:500]}")
    if res.exit_code not in (0, 1) or bool(report.get("ok")) != (res.exit_code == 0):
        raise AstGuardError(f"ast-guard beklenmeyen çıkış kodu {res.exit_code}")
    return report
