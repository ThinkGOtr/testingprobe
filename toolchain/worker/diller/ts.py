"""ts (Playwright Test) worker eklentisi: bugünkü TS yolunun sarmalayıcısı (davranış değişmez).

`worker/app.py` ve `worker/check.py` ts için kendi yollarını doğrudan çağırır; bu eklenti kayıt
(`lang` doğrulaması) ve protokol eşitliği içindir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _Ts:
    ad = "ts"
    platformlar: tuple[str, ...] = ("web",)
    hat = "tam"

    @property
    def steps(self) -> tuple[str, ...]:
        from worker import check

        return check.STEPS

    def validate_test_file(self, yol: str) -> str:
        from toolchain_common.validation import validate_test_files

        return validate_test_files([yol])[0]

    def symbols(self, cfg: Any, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
        from worker import app

        return app.extract_symbols(cfg, full_sha, repo, "ts", platform)

    def guard(
        self, cfg: Any, repo: Path, base: str, head: str, mode: str, platform: str
    ) -> dict[str, Any]:
        from worker.astguard import run_ast_guard

        return run_ast_guard(cfg, base, head, mode, repo)

    def run_static(
        self, cfg: Any, req: Any, head: Any, base: str | None, runner_client: Any,
        steps: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:  # fmt: skip
        from worker import check

        return check._run_steps(cfg, req, head, base, runner_client, steps)


EKLENTI = _Ts()
