"""İstemci adresi: yalnızca güvenilen ters proxy'den gelen X-Forwarded-For'a güvenilir.

Portal (review-portal nginx) `X-Forwarded-For $proxy_add_x_forwarded_for` gönderir: tarayıcının
yolladığı XFF'nin sonuna kendi gördüğü eşi ekler. Bu yüzden yalnızca EN SAĞDAKİ öğe güvenilirdir
(sol taraf istemcinin kendi yazdığı, sahte olabilecek değerdir). `X-Real-IP` nginx tarafından
yazılmadığı için (istemci serbestçe gönderebilir) kullanılmaz.

Bağlantı güvenilen bir proxy'den gelmiyorsa (ör. yayınlanmış 127.0.0.1:8000 portu) başlıklar yok
sayılır ve TCP eşi kullanılır. Güvenilen adlar DNS'te çözülür (konteyner yeniden oluşunca IP
değişebildiği için sonuç `COZUM_TTL_S` saniye önbelleklenir).
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import time

from fastapi import Request

from tp_core.config import get_settings

COZUM_TTL_S = 30.0

_onbellek: dict[str, tuple[float, frozenset[str]]] = {}
_kilit = threading.Lock()


def _coz(ad: str) -> frozenset[str]:
    simdi = time.monotonic()
    with _kilit:
        kayit = _onbellek.get(ad)
        if kayit is not None and simdi - kayit[0] < COZUM_TTL_S:
            return kayit[1]
    try:
        adresler = frozenset(str(a[4][0]) for a in socket.getaddrinfo(ad, None))
    except (OSError, UnicodeError):
        adresler = frozenset()
    with _kilit:
        _onbellek[ad] = (simdi, adresler)
    return adresler


def _guvenilir(es_adres: str, liste: str) -> bool:
    try:
        ip = ipaddress.ip_address(es_adres)
    except ValueError:
        ip = None
    for girdi in (p.strip() for p in liste.split(",")):
        if not girdi:
            continue
        if girdi == es_adres:
            return True
        if ip is not None:
            try:
                if ip in ipaddress.ip_network(girdi, strict=False):
                    return True
                continue
            except ValueError:
                pass
            if es_adres in _coz(girdi):
                return True
    return False


def client_address(request: Request) -> str:
    """İsteğin gerçek istemci adresi (denetim `istemci` alanı ve giriş deneme sınırı için)."""
    es = request.client.host if request.client else "?"
    if not _guvenilir(es, get_settings().trusted_proxies):
        return es
    xff = request.headers.get("x-forwarded-for", "")
    ogeler = [p.strip() for p in xff.split(",") if p.strip()]
    if not ogeler:
        return es
    try:
        return str(ipaddress.ip_address(ogeler[-1]))
    except ValueError:
        return es
