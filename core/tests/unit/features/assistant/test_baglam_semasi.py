"""Ekran bağlamı doğrulaması ve rota indirgeme (AI-ASISTAN-PLANI §5.5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tp_core.features.assistant.schemas import SoruGonder, baglam_dogrula, rota_indirge


def test_rota_indirge() -> None:
    assert rota_indirge("/gereksinimler/0f3c-1/caseler") == (
        "/gereksinimler/:id/caseler",
        "Case inceleme",
    )
    assert rota_indirge("/gereksinimler/:id") == ("/gereksinimler/:id", "Gereksinim detay")
    assert rota_indirge("/kosular?x=1#y") == ("/kosular", "Koşular")
    assert rota_indirge("/yok/boyle") is None
    assert rota_indirge("https://evil.example/kosular") is None
    assert rota_indirge(None) is None


def test_baglam_rol_ve_oneri_atilir_bilinmeyen_reddedilir() -> None:
    b = baglam_dogrula(
        {
            "rol": "po",
            "oneri": {"baslik": "x"},
            "rota_kalibi": "/kod/12",
            "ekran": "istemci adı",
            "secili_eleman": {"ad": "Kırarak doğrula", "rol": "button", "devre_disi": True},
        }
    )
    assert b == {
        "rota_kalibi": "/kod/:id",
        "ekran": "Script detay",
        "secili_eleman": {"ad": "Kırarak doğrula", "rol": "button", "devre_disi": True},
    }
    with pytest.raises(ValueError):
        baglam_dogrula({"varlik": {"tur": "requirement", "fazla": 1}})
    with pytest.raises(ValueError):
        baglam_dogrula(["liste"])
    assert baglam_dogrula({"rota": "/bilinmeyen"}) is None
    assert baglam_dogrula(None) is None


def test_baglam_2kb_siniri() -> None:
    sinirda = {"ekran": "e" * 100, "son_hata": {"detail": "d" * 600, "gorunen_metin": "g" * 600}}
    assert baglam_dogrula(sinirda) is not None
    with pytest.raises(ValidationError):
        SoruGonder.model_validate(
            {"soru": "x", "baglam": {"son_hata": {"detail": "ş" * 600, "gorunen_metin": "ğ" * 600}}}
        )


def test_soru_govdesi() -> None:
    g = SoruGonder.model_validate({"soru": "  merhaba  ", "bilinmeyen": 1})
    assert g.soru == "merhaba" and g.kip == "soru" and g.ust_mesaj_id is None
    with pytest.raises(ValidationError):
        SoruGonder.model_validate({"soru": "a" * 2001})
    with pytest.raises(ValidationError):
        SoruGonder.model_validate({"kip": "eylem"})
    with pytest.raises(ValidationError):
        SoruGonder.model_validate({"oneri_kural_id": "Büyük Harf"})
