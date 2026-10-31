"""toolchain-worker kimlik doğrulaması: paylaşılan taşıyıcı belirteç (`TP_TOOLCHAIN_TOKEN`).

toolchain-worker hem core-net'te (core-api, core-worker, review-portal, jira-sim) hem runner-net'te
(test-runner) dinler. test-runner commit'ten gelen güvenilmeyen kodu (spec, page object, fixture,
playwright.config, globalSetup) koşturur; kimlik doğrulaması olmasaydı bu kod `/check`'e istek atıp
merge kapısını (`checks/<sha>.json`) başka bir PR'ın head'i için yazdırabilirdi. Belirteç yalnızca
core-api ve core-worker ortamına verilir; test-runner'a ASLA verilmez.

- `TP_TOOLCHAIN_TOKEN` dolu → `/health` dışındaki her uç `Authorization: Bearer <belirteç>` ister
  (sabit zamanlı karşılaştırma); yoksa/yanlışsa 401.
- Boş ve `TP_TOOLCHAIN_REQUIRE_TOKEN=1` → uçlar 503 (yanlış yapılandırma; açık kalmaz), `/health`
  `auth: error`.
- Boş ve zorunlu değil → uçlar açık (geriye uyum), `/health` `auth: ok (uyarı: …)` der.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from toolchain_common.settings import settings


def require_token(request: Request) -> None:
    """FastAPI bağımlılığı: `/health` dışındaki toolchain-worker uçları."""
    cfg = settings()
    expected = cfg.toolchain_token
    if not expected:
        if cfg.toolchain_require_token:
            raise HTTPException(
                503, "toolchain-worker belirteci yapılandırılmamış (TP_TOOLCHAIN_TOKEN boş)."
            )
        return
    header = request.headers.get("authorization", "")
    scheme, _, given = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        given.strip().encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            401,
            "Kimlik doğrulaması gerekli: toolchain-worker yalnızca core'dan "
            "(Authorization: Bearer TP_TOOLCHAIN_TOKEN) çağrılır.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def check_auth() -> str:
    """`/health`: uçlar belirteçle korunuyor mu."""
    cfg = settings()
    if cfg.toolchain_token:
        return "ok (belirteç zorunlu)"
    msg = "TP_TOOLCHAIN_TOKEN boş: uçlar kimlik doğrulamasız (test-runner /check çağırabilir)"
    return f"error: {msg}" if cfg.toolchain_require_token else f"ok (uyarı: {msg})"
