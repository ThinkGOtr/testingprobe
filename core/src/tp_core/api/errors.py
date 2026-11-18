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
- Path parametresi doğrulama hatası (ör. UUID beklenen `/failures/{id}`'ye `1`) → 404
  `bulunamadi`: biçimi geçersiz kimlikle kayıt zaten olamaz; gövde/sorgu doğrulaması 422 kalır.
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


# ------------------------------------------------------------- çok proje (TP-COK-PROJE-PLANI §6)

PROJE_DEGISTI = "proje_degisti"
PROJE_ROLU_YOK = "proje_rolu_yok"
PROJE_AYARI_EKSIK = "proje_ayari_eksik"
PROJE_YOK = "proje_yok"


def proje_degisti() -> KodluHata:
    """409: isteğin `X-TP-Proje` başlığı oturumun seçili projesinden farklı (başka sekmede proje
    değişti). GET dahil; portal `/auth/me`'yi yeniden okuyup sayfayı yeni projede yükler."""
    return KodluHata(
        409, PROJE_DEGISTI, "Proje başka bir sekmede değiştirildi; sayfayı yeniden yükleyin"
    )


def proje_rolu_yok() -> KodluHata:
    """403: seçili projede (ya da istenen projede) kişinin TP rolü yok."""
    return KodluHata(403, PROJE_ROLU_YOK, "Seçili projede rolünüz yok; başka bir proje seçin")


def proje_yok() -> KodluHata:
    """404: proje kullanıcının projeleri arasında değil (ya da bu kurulumda etkin değil)."""
    return KodluHata(404, PROJE_YOK, "Proje bulunamadı")


class ProjeAyariEksik(WorkflowError):
    """409: projenin bu işlem için gereken ayarı tanımlı değil (ör. RO veritabanı, kod üretimi
    paket adları; TP-COK-PROJE-PLANI §4.5). Özellik servisleri `raise ProjeAyariEksik(...)`."""

    status_code = 409
    kod = PROJE_AYARI_EKSIK


class OrtamAyariYok(ProjeAyariEksik):
    """409: seçilen test ortamının etkin config'i Home'dan çözülemedi (koşu proje değerlerine —
    başka ortamın adresine — düşmesin; `proje.ortam.gorunum`)."""


CANLI_ENGEL = "canli_ortam"


class CanliOrtamEngeli(KodluHata):
    """409: Canlı (`prod`) ortamda veriyi değiştiren işlem kapalı (`proje.ortam.canli_engelle`).

    Gövde: `{detail, kod: "cakisma", engel: "canli_ortam", islem, ortam: {eid, ad, tur, canli}}`
    (genel `cakisma` kodu: asistan hata sözlüğü kapsar; ayrım `engel` alanındadır)."""

    def __init__(self, islem: str, ortam: Mapping[str, Any]) -> None:
        ad = ortam.get("ad") or ortam.get("eid")
        super().__init__(
            409,
            "cakisma",
            f"Canlı ortamda ({ad}) veriyi değiştiren işlemler kapalı: {islem}. Koşular yalnız "
            "okuma amaçlıdır; bu işlem için Canlı olmayan bir ortamı varsayılan yapın.",
            ek={"engel": CANLI_ENGEL, "islem": islem, "ortam": dict(ortam)},
        )
        self.islem = islem
        self.ortam = dict(ortam)

    def __str__(self) -> str:
        return str(self.detail)


def _hizmet_durumu_mu(exc: KodluHata) -> bool:
    return exc.status_code == 503 and exc.kod in HIZMET_DURUMU_KODLARI


def _dogrulama_metni(exc: RequestValidationError) -> str:
    parcalar = []
    for hata in exc.errors()[:5]:
        yer = ".".join(str(p) for p in hata.get("loc", ()) if p not in ("body", "query", "path"))
        parcalar.append(f"{yer}: {hata.get('msg', 'geçersiz')}" if yer else hata.get("msg", ""))
    return "Geçersiz istek — " + "; ".join(parcalar)


BULUNAMADI_METNI = "Kayıt bulunamadı"


def _path_hatasi_mi(exc: RequestValidationError) -> bool:
    """Hatalardan biri path parametresindeyse (geçersiz biçimli kimlik) kayıt bulunamaz."""
    return any((hata.get("loc") or ("",))[0] == "path" for hata in exc.errors())


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _dogrulama(_r: Request, exc: RequestValidationError) -> JSONResponse:
        if _path_hatasi_mi(exc):
            return JSONResponse({"detail": BULUNAMADI_METNI, "kod": "bulunamadi"}, status_code=404)
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
