"""java (TestNG; web Playwright for Java, uygulama Appium) worker eklentisi: `worker/java.py` ve
`check._run_java_steps` sarmalayıcısı (davranış değişmez)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _Java:
    ad = "java"
    platformlar: tuple[str, ...] = ("web", "android", "ios", "windows")
    hat = "tam"

    @property
    def steps(self) -> tuple[str, ...]:
        from worker import java as javayol

        return javayol.STEPS

    def validate_test_file(self, yol: str) -> str:
        from worker import java as javayol

        return javayol.validate_java_test_file(yol)

    def symbols(self, cfg: Any, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
        from worker import app

        return app.extract_symbols(cfg, full_sha, repo, "java", platform)

    def guard(
        self, cfg: Any, repo: Path, base: str, head: str, mode: str, platform: str
    ) -> dict[str, Any]:
        from toolchain_common import gitforge
        from worker import java as javayol

        kok = javayol.java_kok(cfg, platform)
        with gitforge.checkout(repo, head, kok.root, cfg.git_timeout_s) as root:
            return javayol.guard_report(cfg, repo, base, head, mode, root, kok)

    def run_static(
        self, cfg: Any, req: Any, head: Any, base: str | None, runner_client: Any,
        steps: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:  # fmt: skip
        from worker import check

        return check._run_java_steps(cfg, req, head, base, runner_client, steps)


EKLENTI = _Java()
