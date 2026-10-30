"""Xray Cloud test yönetimi adaptörü (``TestManagementPort``).

Akış: ``POST /api/v2/authenticate`` (client id/secret → bearer token) → ``POST
/api/v2/import/test/bulk`` (adımlarla Manual Test) → ``GET .../{jobId}/status`` ile iş bitene
kadar bekleme → Jira REST ile story bağlantısı. Idempotency Jira'daki ``tp-<uuid>`` etiketiyle.
Yerelde aynı API'yi ``jira-sim`` (``/xray/api/v2``) sunar.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import httpx

from tp_core.integrations.jira import (
    JiraSettings,
    Sleep,
    get_jira_settings,
    send_with_retry,
)
from tp_core.integrations.testmgmt import (
    AI_LABEL,
    CaseContent,
    TestManagementError,
    case_description_text,
    find_by_label,
    link_to_story,
)
from tp_core.ports import JiraPort, PublishedCase

TERMINAL = {"successful", "failed", "partially_successful", "unsuccessful"}


class XrayError(TestManagementError):
    pass


class XrayClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        http: httpx.Client | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        sleep: Sleep = time.sleep,
        poll_interval_s: float = 1.0,
        poll_timeout_s: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http or httpx.Client()
        self._timeout = httpx.Timeout(timeout_s, connect=min(timeout_s, 5.0))
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s
        self._token: str | None = None

    def _send(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        json: Any = None,
        idempotent: bool | None = None,
    ) -> Any:
        what = f"Xray {method} {path}"
        for attempt in range(2):  # süresi dolmuş token için bir kez yeniden kimlik doğrula
            headers = {"Accept": "application/json"}
            if auth:
                headers["Authorization"] = f"Bearer {self.authenticate(force=attempt > 0)}"
            resp = send_with_retry(
                self._http,
                method,
                f"{self.base_url}/api/v2{path}",
                what=what,
                max_retries=self._max_retries,
                backoff_s=self._backoff_s,
                sleep=self._sleep,
                timeout=self._timeout,
                headers=headers,
                json=json,
                idempotent=idempotent,
            )
            if resp.status_code == 401 and auth and attempt == 0:
                continue
            if resp.status_code >= 400:
                raise XrayError(f"{what} → HTTP {resp.status_code}: {_error_text(resp)}")
            try:
                return resp.json()
            except ValueError as exc:
                raise XrayError(f"{what}: JSON olmayan yanıt") from exc
        raise XrayError(f"{what}: kimlik doğrulama başarısız")  # pragma: no cover

    def authenticate(self, force: bool = False) -> str:
        if self._token and not force:
            return self._token
        token = self._send(
            "POST",
            "/authenticate",
            auth=False,
            json={"client_id": self._client_id, "client_secret": self._client_secret},
            idempotent=True,  # token almak yan etkisizdir; 5xx'te güvenle tekrarlanır
        )
        if not isinstance(token, str) or not token:
            raise XrayError("Xray kimlik doğrulaması token döndürmedi")
        self._token = token
        return token

    def import_tests(self, tests: list[dict[str, Any]]) -> dict[str, Any]:
        """Toplu içe aktarımı başlatır ve iş bitene kadar bekler; ``result`` sözlüğünü döner."""
        job = self._send("POST", "/import/test/bulk", json=tests)
        job_id = job.get("jobId") if isinstance(job, dict) else None
        if not job_id:
            raise XrayError(f"Xray içe aktarımı iş kimliği döndürmedi: {job!r}")
        deadline = time.monotonic() + self._poll_timeout_s
        waited = 0.0
        while True:
            status = self._send("GET", f"/import/test/bulk/{job_id}/status")
            state = str(status.get("status") or "")
            if state in TERMINAL:
                result = status.get("result") or {}
                result["status"] = state
                return result
            if time.monotonic() > deadline or waited > self._poll_timeout_s:
                raise XrayError(f"Xray içe aktarımı zaman aşımı (iş {job_id}, durum {state})")
            self._sleep(self._poll_interval_s)
            waited += self._poll_interval_s


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    if isinstance(body, dict):
        return str(body.get("error") or body.get("errorMessages") or body)
    return str(body)


class XrayTestManagement:
    """Onaylı case'i Xray Cloud Manual Test'i olarak yayınlar (adımlar Xray adım alanında)."""

    name = "xray"

    def __init__(self, xray: XrayClient, jira: JiraPort, project: str) -> None:
        self.xray = xray
        self.jira = jira
        self.project = project

    def find_existing(self, case_id: UUID) -> str | None:
        return find_by_label(self.jira, self.project, case_id)

    def _payload(self, case: CaseContent, story_key: str) -> dict[str, Any]:
        return {
            "testtype": "Manual",
            "fields": {
                "project": {"key": self.project},
                "summary": case.title[:255],
                "description": case_description_text(case, story_key),
                "labels": [AI_LABEL, case.tp_label],
            },
            "steps": [
                {"action": s.action, "data": s.data or "", "result": s.expected or ""}
                for s in case.steps
            ],
        }

    def publish_case(self, case: Mapping[str, Any], story_key: str) -> PublishedCase:
        content = CaseContent.from_mapping(case)
        key = self.find_existing(content.case_id)
        if key is None:
            result = self.xray.import_tests([self._payload(content, story_key)])
            issues = result.get("issues") or []
            if result.get("status") != "successful" or not issues:
                raise XrayError(f"Xray içe aktarımı başarısız: {result.get('errors') or result}")
            key = str(issues[0]["key"])
        link_to_story(self.jira, key, story_key, None)
        url = getattr(self.jira, "issue_url", None)
        return PublishedCase(
            case_id=content.case_id, external_key=key, url=url(key) if url else None
        )


def get_xray_client(
    settings: JiraSettings | None = None, *, http: httpx.Client | None = None
) -> XrayClient:
    s = settings or get_jira_settings()
    cid = s.xray_client_id.get_secret_value() if s.xray_client_id else ""
    secret = s.xray_client_secret.get_secret_value() if s.xray_client_secret else ""
    if not (cid and secret):
        if not s.is_simulator:
            raise XrayError("XRAY_CLIENT_ID/XRAY_CLIENT_SECRET tanımlı değil")
        cid, secret = "sim", "sim"
    return XrayClient(s.xray_base_url, cid, secret, http=http)
