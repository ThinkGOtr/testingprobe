"""java test-runner eklentisi: `runner/java_run.py` sarmalayıcısı (davranış değişmez)."""

from __future__ import annotations

from typing import Any


class _Java:
    ad = "java"

    def validate_test_file(self, yol: str) -> str:
        from worker.java import validate_java_test_file

        return validate_java_test_file(yol)

    def execute_locked(self, cfg: Any, req: Any, loc: Any, http: Any) -> dict[str, Any]:
        from runner import java_run

        return java_run.execute_locked(cfg, req, loc, http)


EKLENTI = _Java()
