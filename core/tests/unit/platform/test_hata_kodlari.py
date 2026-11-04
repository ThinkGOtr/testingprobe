"""Hata `kod` sözleşmesi (MIMARI-SOZLESME §5): genel eşleme, KodluHata, WorkflowError.kod,
5xx'te `ic_hata`, başlıkların korunması ve CSRF `kaynak_reddi`. Veritabanı gerektirmez."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tp_core.api import errors
from tp_core.api.csrf import OriginGuard
from tp_core.api.errors import KodluHata, genel_kod
from tp_core.workflow.budget import BudgetExceeded, BudgetStatus
from tp_core.workflow.service import (
    ApprovalNotAllowed,
    GateClosed,
    InvalidDecision,
    OnayHashUyusmuyor,
    WorkflowError,
)

GIZLI = "iç-ayrıntı: /srv/tp/gizli.py satır 42"


class _Govde(BaseModel):
    sayi: int


class _BulunamadiOzel(WorkflowError):
    """Özellik dosyalarındaki gibi kodsuz alt sınıf: durum kodundan genel kod alır."""

    status_code = 404


class _Kopuk(WorkflowError):
    status_code = 503
    kod = "jira_kopuk"


def _uygulama() -> FastAPI:
    app = FastAPI()
    errors.install(app)

    @app.get("/http/{status}")
    def http(status: int) -> None:
        raise HTTPException(status, f"durum {status}")

    @app.get("/yetkisiz")
    def yetkisiz() -> None:
        raise HTTPException(401, "Oturum açmanız gerekiyor", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/kodlu")
    def kodlu() -> None:
        raise KodluHata(429, "hiz_siniri", "Saatlik soru sınırına ulaştınız", {"Retry-After": "60"})

    @app.get("/kodlu-5xx")
    def kodlu_5xx() -> None:
        raise KodluHata(502, "model_hatasi", "Model sağlayıcısına ulaşılamadı")

    @app.get("/asistan-kapali")
    def asistan_kapali() -> None:
        raise KodluHata(503, "asistan_kapali", "Asistan şu an kullanılamıyor", neden="worker_yok")

    @app.get("/asistan-kapali-502")
    def asistan_kapali_502() -> None:
        raise KodluHata(502, "asistan_kapali", "Yanlış durum kodu")

    @app.get("/kodlu-503")
    def kodlu_503() -> None:
        raise KodluHata(503, "model_hatasi", "Geçici", neden="sizmamali")

    @app.get("/akis/{tur}")
    def akis(tur: str) -> None:
        sinif: type[WorkflowError] = {
            "temel": WorkflowError,
            "kapi": GateClosed,
            "hash": OnayHashUyusmuyor,
            "yetki": ApprovalNotAllowed,
            "karar": InvalidDecision,
            "ozel404": _BulunamadiOzel,
            "kopuk": _Kopuk,
        }[tur]
        raise sinif(f"{tur} mesajı")

    @app.get("/butce")
    def butce() -> None:
        raise BudgetExceeded(
            BudgetStatus(
                daily_spent=Decimal("5"),
                daily_limit=Decimal("1"),
                workflow_spent=None,
                workflow_limit=Decimal("1"),
                reason="Günlük bütçe aşıldı",
            )
        )

    @app.get("/patla")
    def patla() -> None:
        raise RuntimeError(GIZLI)

    @app.post("/dogrula")
    def dogrula(govde: _Govde) -> int:
        return govde.sayi

    @app.post("/yaz")
    def yaz() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_uygulama(), raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("status", "kod"),
    [
        (400, "gecersiz_istek"),
        (401, "yetkisiz"),
        (403, "yasak"),
        (404, "bulunamadi"),
        (409, "cakisma"),
        (418, "istek_hatasi"),
        (429, "hiz_siniri"),
        (500, "ic_hata"),
        (502, "ic_hata"),
        (503, "ic_hata"),
    ],
)
def test_http_hatasi_genel_kod(client: TestClient, status: int, kod: str) -> None:
    r = client.get(f"/http/{status}")
    assert r.status_code == status
    assert r.json() == {"detail": f"durum {status}", "kod": kod}


def test_genel_kod_5xx_daima_ic_hata() -> None:
    assert {genel_kod(s) for s in range(500, 600)} == {"ic_hata"}


def test_starlette_rota_ve_yontem_hatalari_kodlu(client: TestClient) -> None:
    r = client.get("/boyle-bir-uc-yok")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found", "kod": "bulunamadi"}
    r = client.get("/yaz")
    assert r.status_code == 405 and r.json()["kod"] == "yontem_desteklenmiyor"
    assert "POST" in r.headers["allow"]  # Starlette'in Allow başlığı korunur


def test_401_www_authenticate_korunur(client: TestClient) -> None:
    r = client.get("/yetkisiz")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json() == {"detail": "Oturum açmanız gerekiyor", "kod": "yetkisiz"}


def test_kodlu_hata_kendi_kodunu_ve_basliklarini_tasir(client: TestClient) -> None:
    r = client.get("/kodlu")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "60"
    assert r.json() == {"detail": "Saatlik soru sınırına ulaştınız", "kod": "hiz_siniri"}


def test_kodlu_hata_5xx_ic_hata(client: TestClient) -> None:
    r = client.get("/kodlu-5xx")
    assert r.status_code == 502
    assert r.json()["kod"] == "ic_hata"


def test_asistan_kapali_503_kodu_ve_nedeni_korunur(client: TestClient) -> None:
    # MIMARI-SOZLESME §5: 5xx'teki tek istisna bilinçli hizmet durumu `asistan_kapali`.
    r = client.get("/asistan-kapali")
    assert r.status_code == 503
    assert r.json() == {
        "detail": "Asistan şu an kullanılamıyor",
        "kod": "asistan_kapali",
        "neden": "worker_yok",
    }


@pytest.mark.parametrize("yol", ["/asistan-kapali-502", "/kodlu-503"])
def test_hizmet_durumu_istisnasi_dar(client: TestClient, yol: str) -> None:
    # İstisna yalnız 503 + izinli kod; diğer 5xx'ler `ic_hata`, `neden` yazılmaz.
    govde = client.get(yol).json()
    assert govde["kod"] == "ic_hata"
    assert "neden" not in govde


@pytest.mark.parametrize(
    ("tur", "status", "kod"),
    [
        ("temel", 409, "cakisma"),
        ("kapi", 409, "kapi_kapali"),
        ("hash", 409, "onay_hash_uyusmuyor"),
        ("yetki", 403, "onay_yetkisi_yok"),
        ("karar", 422, "gecersiz_karar"),
        ("ozel404", 404, "bulunamadi"),
        ("kopuk", 503, "ic_hata"),
    ],
)
def test_is_akisi_hatasi_sinif_kodu(client: TestClient, tur: str, status: int, kod: str) -> None:
    r = client.get(f"/akis/{tur}")
    assert r.status_code == status
    assert r.json() == {"detail": f"{tur} mesajı", "kod": kod}


def test_onay_hash_uyusmazligi_kapi_kapali_alt_sinifi() -> None:
    # Mevcut `except GateClosed` yakalayıcıları (MCP, servisler) değişmeden çalışır.
    assert issubclass(OnayHashUyusmuyor, GateClosed)
    assert OnayHashUyusmuyor.status_code == 409


def test_butce_hatasi_kodlu(client: TestClient) -> None:
    r = client.get("/butce")
    govde = r.json()
    assert r.status_code == 402
    assert govde["kod"] == "butce_asildi" and "budget" in govde and govde["detail"]


def test_dogrulama_hatasi_kodlu(client: TestClient) -> None:
    r = client.post("/dogrula", json={"sayi": "bir"})
    assert r.status_code == 422
    assert r.json()["kod"] == "gecersiz_istek"
    assert r.json()["detail"].startswith("Geçersiz istek")


def test_beklenmeyen_istisna_ic_hata_ve_metin_sizmaz(client: TestClient) -> None:
    r = client.get("/patla")
    assert r.status_code == 500
    assert r.json() == {"detail": "Sunucu hatası", "kod": "ic_hata"}
    assert GIZLI not in r.text and "RuntimeError" not in r.text


def test_csrf_reddi_kaynak_reddi_kodu() -> None:
    app = _uygulama()
    korunan = OriginGuard(app, frozenset({"http://127.0.0.1:3000"}))
    with TestClient(korunan) as c:
        r = c.post("/yaz", headers={"Origin": "http://127.0.0.1:8081"})
        assert r.status_code == 403
        assert r.json() == {
            "detail": "İstek başka bir kaynaktan geldi; işlem reddedildi",
            "kod": "kaynak_reddi",
        }
        assert c.post("/yaz", headers={"Origin": "http://127.0.0.1:3000"}).json() == {"ok": True}
