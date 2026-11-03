"""Siteler arası istek sahteciliği (CSRF) savunması: tarayıcı kaynaklı güvensiz istekleri süzer.

Bütün yerel servisler 127.0.0.1'de koşar; portlar siteyi ayırmaz. Demo uygulaması (8081),
jira-sim arayüzü ya da makinedeki başka bir geliştirme sunucusu portal ile *aynı sitedir* ve
`SameSite=Lax` çerez onların POST'larında da gönderilir. Bu yüzden POST/PUT/PATCH/DELETE için:

1. `Sec-Fetch-Site` başlığı varsa (tarayıcı koyar, sayfa betiği değiştiremez) yalnızca
   `same-origin` veya `none` (kullanıcının kendisi yazdı/yer imi) kabul edilir.
2. Yoksa `Origin` başlığı varsa `TP_ALLOWED_ORIGINS` listesinde olmalıdır (`null` dahil
   listede olmayan her değer reddedilir).
3. İkisi de yoksa istek tarayıcıdan gelmiyordur (curl, MCP/IDE bearer istemcisi, servisler
   arası çağrı): tarayıcılar güvensiz yöntemlerde her zaman en az `Origin` gönderir, dolayısıyla
   bu yol bir CSRF saldırısına açılmaz.

Reddedilen istek 403 `{"detail": "...", "kod": "kaynak_reddi"}` alır ve uygulamaya hiç
ulaşmaz. Kural çerez olsun olmasın uygulanır (giriş CSRF'ine karşı da).
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

GUVENSIZ = frozenset({"POST", "PUT", "PATCH", "DELETE"})
GUVENLI_FETCH_SITE = frozenset({"same-origin", "none"})
RED_MESAJI = "İstek başka bir kaynaktan geldi; işlem reddedildi"
# Ara katman uygulamanın hata işleyicilerinden önce yanıt verir; kodu burada yazılır (errors.py).
RED_KODU = "kaynak_reddi"


def parse_origins(deger: str) -> frozenset[str]:
    return frozenset(o.strip().rstrip("/").lower() for o in deger.split(",") if o.strip())


def istek_kabul_mu(
    method: str, sec_fetch_site: str | None, origin: str | None, izinli: frozenset[str]
) -> bool:
    if method.upper() not in GUVENSIZ:
        return True
    if sec_fetch_site is not None:
        return sec_fetch_site.strip().lower() in GUVENLI_FETCH_SITE
    if origin is not None:
        return origin.strip().rstrip("/").lower() in izinli
    return True


class OriginGuard:
    """Saf ASGI ara katmanı (SSE gibi akış yanıtlarını tamponlamaz)."""

    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.izinli = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        basliklar: dict[str, str] = {}
        for ad, deger in scope.get("headers", []):
            anahtar = ad.decode("latin-1").lower()
            if anahtar in ("sec-fetch-site", "origin"):
                basliklar[anahtar] = deger.decode("latin-1")
        if istek_kabul_mu(
            scope.get("method", "GET"),
            basliklar.get("sec-fetch-site"),
            basliklar.get("origin"),
            self.izinli,
        ):
            await self.app(scope, receive, send)
            return
        govde = json.dumps({"detail": RED_MESAJI, "kod": RED_KODU}, ensure_ascii=False).encode(
            "utf-8"
        )
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(govde)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": govde})
