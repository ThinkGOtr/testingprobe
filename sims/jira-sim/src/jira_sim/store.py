"""Simülatör durumu: tek JSON belge, kilitli erişim, atomik dosya yazımı."""

from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jira_sim.adf import adf_to_text
from jira_sim.seed import PROJECT, STATUSES, USERS, initial_state


def now_jira() -> str:
    """Jira Cloud zaman biçimi: ``2026-10-30T12:34:56.789+0000``."""
    t = datetime.now(UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}+0000"


class Store:
    def __init__(self, path: str | os.PathLike[str] | None) -> None:
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        self.state: dict[str, Any] = {}
        self.faults: list[dict[str, Any]] = []
        self.xray_tokens: set[str] = set()
        self._load()

    # ----------------------------------------------------------------- kalıcılık
    def _load(self) -> None:
        with self.lock:
            if self.path and self.path.exists():
                with self.path.open(encoding="utf-8") as fh:
                    self.state = json.load(fh)
            else:
                self.state = initial_state()
                self.save()

    def save(self) -> None:
        """Atomik yazım: aynı dizinde geçici dosya → fsync → os.replace."""
        if not self.path:
            return
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".jira-", suffix=".json", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self.state, fh, ensure_ascii=False, indent=1)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp)
                raise

    def reset(self) -> None:
        with self.lock:
            self.state = initial_state()
            self.faults.clear()
            self.xray_tokens.clear()
            self.save()

    @contextlib.contextmanager
    def tx(self) -> Iterator[dict[str, Any]]:
        """Yazma işlemi: hata olursa durum geri alınır, başarıda diske yazılır."""
        with self.lock:
            snapshot = copy.deepcopy(self.state)
            try:
                yield self.state
            except BaseException:
                self.state = snapshot
                raise
            self.save()

    # ------------------------------------------------------------------ yardımcılar
    def next_id(self) -> str:
        with self.lock:
            self.state["next_id"] += 1
            return str(self.state["next_id"])

    def next_key(self, project: str) -> str:
        with self.lock:
            n = self.state["next_issue_number"]
            self.state["next_issue_number"] = n + 1
            return f"{project}-{n}"

    def issue(self, key: str) -> dict[str, Any] | None:
        issues = self.state["issues"]
        if key in issues:
            return issues[key]
        for it in issues.values():  # sayısal id ile erişim
            if it["id"] == key:
                return it
        return None

    def search_doc(self, it: dict[str, Any]) -> dict[str, Any]:
        desc = adf_to_text(it.get("description"))
        comments = " ".join(adf_to_text(c["body"]) for c in it.get("comments", []))
        status = STATUSES.get(it["status"], STATUSES["To Do"])
        reporter = USERS.get(it.get("reporter") or "", {})
        return {
            "_issue": it,
            "project": [it["project"], PROJECT["name"]],
            "key": [it["key"], it["id"]],
            "labels": list(it.get("labels", [])),
            "summary": it["summary"],
            "description": desc,
            "text": f"{it['summary']}\n{desc}\n{comments}",
            "status": [it["status"]],
            "statuscategory": [status["name"], status["key"]],
            "issuetype": [it["issuetype"]],
            "reporter": [it.get("reporter") or "", reporter.get("accountId", "")],
            "created": it["created"],
            "updated": it["updated"],
        }
