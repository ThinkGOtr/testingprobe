"""Test verisi yalıtımı ve "kırarak doğrula" kancaları (web: tests/fixtures.ts `isolationMode`,
`dealerBreak`, `testApi`, `clearCartViaPublicApi`; uygulama: altyapi/TestVerisi.java).

- Sıfırlama (varsayılan): her testten önce yalnızca o bayinin sepeti, siparişleri ve demo
  kırılması `POST /test/reset` ile silinir; `X-Demoapp-Test-Token` ister.
- Yalnızca sepet (`TP_E2E_NO_RESET=1`, token yok): bayinin sepeti herkese açık API ile
  (giriş + `DELETE /cart`) boşaltılır.
- `BREAK_CAMPAIGN=1`: bayi kapsamlı `POST /test/break {kampanya: true}`, test sonunda geri alınır.
- `TP_FAULT=<kod>`: aynı uçla bayi kapsamlı ekilmiş hata (`{hata: kod}`); `BREAK_CAMPAIGN=1` ile
  birlikteyse geçerli olan budur.

HTTP yalnız stdlib `urllib` iledir: Playwright `request` fikstürü izlenir (trace) ve token başlığı
trace.zip'e düşerdi (fixtures.ts notu). Token günlüğe, rapora ya da kanıta yazılmaz.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TOKEN_BASLIGI = "X-Demoapp-Test-Token"
HATA_KODU = re.compile(r"^[a-z0-9_]{1,40}$")
ZAMAN_ASIMI_S = 10.0


class KurulumHatasi(RuntimeError):
    """Veri hazırlığı (`/test/*`, giriş, sepet boşaltma, token) başarısız: kırmızı SAYILMAZ."""


@dataclass(frozen=True)
class Kirilma:
    """Bayi kapsamlı kırılma: `on` testten önce, `off` testten sonra `/test/break` gövdesi."""

    on: dict[str, Any]
    off: dict[str, Any]


def kirilma(ortam: Mapping[str, str] = os.environ) -> Kirilma | None:
    """TP_FAULT (ekilmiş hata) varsa o, yoksa BREAK_CAMPAIGN=1 (kampanya), hiçbiri yoksa None."""
    kod = ortam.get("TP_FAULT") or ""
    if kod:
        if not HATA_KODU.match(kod):
            raise KurulumHatasi(f"TP_FAULT geçersiz: '{kod}' (beklenen biçim: {HATA_KODU.pattern})")
        return Kirilma({"hata": kod}, {"hata": None})
    if ortam.get("BREAK_CAMPAIGN") == "1":
        return Kirilma({"kampanya": True}, {"kampanya": False})
    return None


def kip(ortam: Mapping[str, str] = os.environ) -> str:
    """`sifirlama` | `yalniz_sepet`; geçersiz birleşimlerde açıklayıcı hata."""
    if ortam.get("DEMOAPP_TEST_TOKEN"):
        return "sifirlama"
    if ortam.get("TP_FAULT"):
        raise KurulumHatasi(
            "TP_FAULT için DEMOAPP_TEST_TOKEN gerekir (ekilmiş hata POST /test/break ile bayi "
            "kapsamında açılır)."
        )
    if ortam.get("BREAK_CAMPAIGN") == "1":
        raise KurulumHatasi(
            "BREAK_CAMPAIGN=1 için DEMOAPP_TEST_TOKEN gerekir (kırılma POST /test/break ile bayi "
            "kapsamında açılır)."
        )
    if ortam.get("TP_E2E_NO_RESET") == "1":
        return "yalniz_sepet"
    raise KurulumHatasi(
        "DEMOAPP_TEST_TOKEN tanımlı değil; test verisi sıfırlanamaz. Ya token ile DEMO_API_URL "
        "verin (ör. http://127.0.0.1:18000) ya da yalnızca sepet yalıtımı için TP_E2E_NO_RESET=1 "
        "verin."
    )


def api_koku(base_url: str | None, ortam: Mapping[str, str] = os.environ) -> str:
    """Demo API kökü: `DEMO_API_URL` (ya da `API_URL`), yoksa web vekili `<BASE_URL>/api`."""
    kok = ortam.get("DEMO_API_URL") or ortam.get("API_URL")
    if kok:
        return kok.rstrip("/")
    if not base_url:
        raise KurulumHatasi("/test uçları için BASE_URL ya da DEMO_API_URL gerekir")
    return base_url.rstrip("/") + "/api"


class TestVerisi:
    """Bir testin veri hazırlığı istemcisi (çerezli: yalnız-sepet kipinde giriş oturumu)."""

    __test__ = False  # pytest bunu test sınıfı sanmasın

    def __init__(self, api: str, token: str | None) -> None:
        self._api = api
        self._token = token
        self._acici = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _istek(self, yontem: str, yol: str, govde: object | None, ne: str, *, token: bool) -> bytes:
        basliklar = {"Content-Type": "application/json"}
        if token:
            if not self._token:
                raise KurulumHatasi(f"{ne} için DEMOAPP_TEST_TOKEN gerekir")
            basliklar[TOKEN_BASLIGI] = self._token
        veri = None if govde is None else json.dumps(govde).encode("utf-8")
        istek = urllib.request.Request(
            f"{self._api}{yol}", data=veri, headers=basliklar, method=yontem
        )
        try:
            with self._acici.open(istek, timeout=ZAMAN_ASIMI_S) as yanit:
                return yanit.read()
        except urllib.error.HTTPError as exc:
            ipucu = (
                " (uç kapalı: API'de DEMOAPP_TEST_MODE=1 + DEMOAPP_TEST_TOKEN yok ya da web vekili "
                "/api/test/ yolunu açmıyor; DEMO_API_URL verin)"
                if exc.code == 404 and token
                else ""
            )
            raise KurulumHatasi(f"{ne} başarısız: {exc.code}{ipucu}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise KurulumHatasi(f"{ne}: demo API'ye ulaşılamadı ({type(exc).__name__})") from None

    def sifirla(self, kullanici_adi: str) -> None:
        self._istek("POST", "/test/reset", {"kullanici_adi": kullanici_adi}, "POST /test/reset",
                    token=True)  # fmt: skip

    def kir(self, kirilma: Kirilma, kullanici_adi: str, acik: bool) -> None:
        govde = {"kullanici_adi": kullanici_adi, **(kirilma.on if acik else kirilma.off)}
        self._istek("POST", "/test/break", govde, "POST /test/break", token=True)

    def sepeti_bosalt(self, kullanici_adi: str, parola: str) -> None:
        """Token olmadan: bayinin sepetini herkese açık API ile boşaltır ve oturumu kapatır."""
        self._istek("POST", "/auth/login", {"kullanici_adi": kullanici_adi, "parola": parola},
                    "sepet temizliği için giriş", token=False)  # fmt: skip
        yanit = self._istek("DELETE", "/cart", None, "sepet boşaltma", token=False)
        try:
            satirlar = json.loads(yanit or b"{}").get("satirlar")
        except ValueError:
            satirlar = None
        if satirlar != []:
            raise KurulumHatasi("sepet boşaltılamadı: yanıtta satırlar kaldı")
        self._istek("POST", "/auth/logout", None, "çıkış", token=False)

    def giris(self, kullanici_adi: str, parola: str) -> None:
        """API ile giriş (yalnız bu istemcinin çerezinde; tarayıcı oturumu için kullanılmaz)."""
        self._istek("POST", "/auth/login", {"kullanici_adi": kullanici_adi, "parola": parola},
                    "API ile giriş", token=False)  # fmt: skip
