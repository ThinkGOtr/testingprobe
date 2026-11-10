"""`X-TP-Kimlik` yanıt başlığı: portal kimlik kipini ek istek atmadan öğrenir (§8.14).

`TP_AUTH_MODE=aiprobe|both` iken her HTTP yanıtına (401 dahil) eklenir:
``X-TP-Kimlik: kip=aiprobe; home=https://home.aiprobe.antreklabs.com; urun=testing-probe``.
Portal 401'de AI Probe girişine yönlendirmeyi, `<aiprobe-switcher>`'ı ve çıkış yönlendirmesini
buna göre açar. `local` kipte başlık **hiç yoktur** (yanıtlar bugünküyle aynı).

Saf ASGI ara katmanı (BaseHTTPMiddleware değil): SSE akışını tamponlamaz.
"""

from __future__ import annotations

import re

from pydantic import ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tp_core.config import get_settings

BASLIK = "X-TP-Kimlik"
_ORIGIN = re.compile(r"^(https://[a-z0-9.-]+(:\d+)?|http://(localhost|127\.0\.0\.1)(:\d+)?)$")
_URUN = re.compile(r"^[a-z0-9-]{1,64}$")


def baslik_degeri() -> str | None:
    try:
        ayar = get_settings()
    except ValidationError:
        # Yapılandırma eksik (ör. yalnız /health'i sınayan test): başlık yok, istek kendi hatasını
        # verir.
        return None
    if ayar.auth_mode == "local":
        return None
    parcalar = [f"kip={ayar.auth_mode}"]
    home = ayar.aiprobe_id_origin.strip().rstrip("/").lower()
    if _ORIGIN.match(home):
        parcalar.append(f"home={home}")
    if _URUN.match(ayar.aiprobe_product_id):
        parcalar.append(f"urun={ayar.aiprobe_product_id}")
    return "; ".join(parcalar)


class KimlikKipiBasligi:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        deger = baslik_degeri()
        if deger is None:
            await self.app(scope, receive, send)
            return
        eklenecek = (BASLIK.lower().encode("latin-1"), deger.encode("latin-1"))

        async def gonder(mesaj: Message) -> None:
            if mesaj["type"] == "http.response.start":
                mesaj["headers"] = [*mesaj.get("headers", []), eklenecek]
            await send(mesaj)

        await self.app(scope, receive, gonder)
