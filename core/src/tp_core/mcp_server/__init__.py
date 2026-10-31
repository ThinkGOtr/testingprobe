"""IDE (Claude Code / Copilot) kanalının MCP sunucusu (TEKNIK-TASARIM §8.3, §5; Constitution IX).

core-api içinde `/mcp` yolunda **streamable HTTP** (durumsuz, JSON yanıt) MCP uç noktası. Araçlar:

- `submit_draft_cases(requirement_key, cases[])` — `submit` kapsamı: şemalı taslakları `draft`
  (kanal `ide`) olarak portala düşürür; Jira'ya yazmaz.
- `publish_test_cases(case_ids[])` — `publish` kapsamı: portalla AYNI sunucu yolu (worker'daki
  `publish.cases` işi); yalnızca portalda insan onaylı ve onaylanan hash'i güncel case'ler
  yayınlanır.

Kimlik: `Authorization: Bearer tpt_…` (portalın verdiği 8 saatlik, kullanıcıya özel, kapsamlı
token; `tp_core.auth.tokens`). Oturum çerezi kullanılmaz (çerez-CSRF yüzeyi yok); tarayıcı
kaynaklı istekleri `OriginGuard` ayrıca reddeder. Yalnızca localhost: `Host` başlığı
127.0.0.1/localhost/[::1] olmalı (DNS rebinding koruması da açık) ve vekil (portal nginx,
`X-Forwarded-For`) üzerinden gelen istek reddedilir; compose portu yalnızca 127.0.0.1'e açar.

Her araç çağrısı `tool_call` tablosuna (kanal `ide`, çağıran kullanıcı, argüman ve sonuç özeti,
izin) yazılır; yayında onaylayanlar argüman özetinde ayrıca durur (çağıran ≠ onaylayan).
"""

from tp_core.mcp_server.server import (
    MCP_METHODS,
    MCP_PATH,
    TOOL_NAMES,
    McpEndpoint,
    build_server,
    mcp_asgi_app,
)

__all__ = ["MCP_METHODS", "MCP_PATH", "TOOL_NAMES", "McpEndpoint", "build_server", "mcp_asgi_app"]
