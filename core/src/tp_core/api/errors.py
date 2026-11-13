"""Hata biçimi sözleşmesi: her hata ``{"detail": "<Türkçe metin>", "kod": "<sabit kod>"}``
(MIMARI-SOZLESME §5).

`kod` makinece okunur, sabit bir sözlükten gelir (asistanın hata sözlüğü ve portal bunu eşler);
`detail` insan içindir ve önceki gibi korunur. Kural: `kod` hiçbir zaman istisna adından ya da
`str(exc)`'ten türetilmez; 5xx yanıtlarda daima `ic_hata`'dır (iç ayrıntı sızmaz). Tek istisna
bilinçli hizmet durumudur: `KodluHata(503, "asistan_kapali", ..., neden=...)` kodunu ve `neden`
alanını korur (HIZMET_DURUMU_KODLARI).

- `HTTPException` / Starlette hataları (404 rota, 405 yöntem dahil) → durum kodundan genel kod;
  `KodluHata` ise kendi kodunu taşır. Başlıklar (ör. 401 `WWW-Authenticate`) korunur.
- `WorkflowError` ailesi → sınıfın `kod` alanı; tanımsızsa durum kodundan genel kod.
- Beklenmeyen istisna → 500 `{"detail": "Sunucu hatası", "kod": "ic_hata"}`; metni yazılmaz.
- CSRF reddi ara katmanda üretilir; kodunu `api/csrf.py` kendisi yazar (`kaynak_reddi`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from tp_core.workflow.budget import BudgetExceeded
from tp_core.workflow.service import WorkflowError

IC_HATA = "ic_hata"
SUNUCU_HATASI_METNI = "Sunucu hatası"

# 5xx'te korunan tek kod ailesi: bilinçli hizmet durumu (iç hata değil). Yalnız `KodluHata` ile
# ve yalnız 503'te geçerlidir; WorkflowError ve diğer 5xx'ler yine `ic_hata` olur.
# `kimlik_servisi_yok`: AI Probe kimlik servisine (aiprobe-home) ulaşılamıyor (§8.14).
HIZMET_DURUMU_KODLARI = frozenset({"asistan_kapali", "kimlik_servisi_yok"})

# Durum kodu → genel kod. Listede olmayan 4xx'ler `istek_hatasi`, her 5xx `ic_hata` alır.
GENEL_KODLAR: Mapping[int, str] = {
    400: "gecersiz_istek",
    401: "yetkisiz",
    403: "yasak",
    404: "bulunamadi",
    405: "yontem_desteklenmiyor",
    409: "cakisma",
    410: "bulunamadi",
    413: "govde_cok_buyuk",
    415: "gecersiz_istek",
    422: "gecersiz_istek",
    429: "hiz_siniri",
}


def genel_kod(status: int) -> str:
    """Durum kodundan sabit genel `kod` (5xx → `ic_hata`)."""
    if status >= 500:
        return IC_HATA
    return GENEL_KODLAR.get(status, "istek_hatasi")


def _kod_sec(status: int, ozel: str | None) -> str:
    # 5xx'te sınıfın özel kodu bile yazılmaz: iç hata türü dışarıya sızmaz.
    if status >= 500:
        return IC_HATA
    return ozel or genel_kod(status)


class KodluHata(StarletteHTTPException):
    """Seçili hatalar için sabit `kod` taşıyan HTTP hatası (ör. asistan uçları).

    `raise KodluHata(429, "hiz_siniri", "Saatlik soru sınırına ulaştınız")`
    `raise KodluHata(503, "asistan_kapali", "Asistan şu an kapalı", neden="worker_yok")`
    `neden` gövdeye yalnız korunan hizmet durumu kodlarında yazılır.
    `ek`: 4xx gövdesine eklenen makinece okunur alanlar (ör. 429 `donduruldu` → `kalan_s`);
    `detail`/`kod` ezilemez, 5xx'te yazılmaz.
    """

    def __init__(
        self,
        status_code: int,
        kod: str,
        detail: str,
        headers: Mapping[str, str] | None = None,
        *,
        neden: str | None = None,
        ek: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=dict(headers or {}))
        self.kod = kod
        self.neden = neden
        self.ek = {k: v for k, v in (ek or {}).items() if k not in ("detail", "kod")}


def _hizmet_durumu_mu(exc: KodluHata) -> bool:
    return exc.status_code == 503 and exc.kod in HIZMET_DURUMU_KODLARI


def _dogrulama_metni(exc: RequestValidationError) -> str:
    parcalar = []
    for hata in exc.errors()[:5]:
        yer = ".".join(str(p) for p in hata.get("loc", ()) if p not in ("body", "query", "path"))
        parcalar.append(f"{yer}: {hata.get('msg', 'geçersiz')}" if yer else hata.get("msg", ""))
    return "Geçersiz istek — " + "; ".join(parcalar)


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _dogrulama(_r: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": _dogrulama_metni(exc), "kod": "gecersiz_istek"}, status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_r: Request, exc: StarletteHTTPException) -> Response:
        headers = getattr(exc, "headers", None)
        if not is_body_allowed_for_status_code(exc.status_code):
            return Response(status_code=exc.status_code, headers=headers)
        if isinstance(exc, KodluHata) and _hizmet_durumu_mu(exc):
            hizmet: dict[str, Any] = {"detail": exc.detail, "kod": exc.kod}
            if exc.neden:
                hizmet["neden"] = exc.neden
            return JSONResponse(hizmet, status_code=exc.status_code, headers=headers)
        kod = _kod_sec(exc.status_code, getattr(exc, "kod", None))
        govde: dict[str, Any] = {"detail": exc.detail, "kod": kod}
        if isinstance(exc, KodluHata) and exc.ek and exc.status_code < 500:
            govde.update(exc.ek)
        return JSONResponse(govde, status_code=exc.status_code, headers=headers)

    @app.exception_handler(WorkflowError)
    async def _akis(_r: Request, exc: WorkflowError) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc), "kod": _kod_sec(exc.status_code, exc.kod)},
            status_code=exc.status_code,
        )

    @app.exception_handler(BudgetExceeded)
    async def _butce(_r: Request, exc: BudgetExceeded) -> JSONResponse:
        return JSONResponse(
            {
                "detail": str(exc),
                "kod": _kod_sec(exc.status_code, "butce_asildi"),
                "budget": exc.status.as_dict(),
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _beklenmeyen(_r: Request, _exc: Exception) -> JSONResponse:
        # Starlette bu işleyiciyi ServerErrorMiddleware'de çağırır ve istisnayı yine günlüğe/
        # yukarı iletir; yanıta yalnız sabit metin gider (istisna adı/`str(exc)` asla).
        return JSONResponse({"detail": SUNUCU_HATASI_METNI, "kod": IC_HATA}, status_code=500)
