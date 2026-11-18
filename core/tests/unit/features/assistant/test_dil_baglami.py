"""Ekran testi 2 TP-5: Kod üretimi ekranından sorulan soruda dil seçeneklerinin durumu (neden + açma
yolu) modelin ekran bağlamına sunucuda eklenir; prompt değişmez."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tp_core.features.assistant import flow
from tp_core.features.codegen import service as codegen


def _mesaj(rol: str) -> flow.Mesaj:
    return flow.Mesaj(
        id=uuid.uuid4(), sohbet_id=uuid.uuid4(), kullanici_id=uuid.uuid4(), kullanici_adi="k",
        rol=rol, sira=1, icerik="Kotlin neden seçilemiyor?", baglam=None, kip="soru",
        tetik="kullanici", amac=None, ust_mesaj_id=None, job_id=None, oneri_kural_id=None,
    )  # fmt: skip


OZET: list[dict[str, Any]] = [
    {
        "platform": "android",
        "secenekler": [
            {"dil": "kotlin", "kullanilabilir": False, "engel": "liste",
             "neden": codegen.liste_engeli_metni("android", "kotlin"),
             "acma_yolu": codegen.dil_listesi_yolu("android")},
        ],
    }
]  # fmt: skip


@pytest.fixture
def ozet(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    cagri: list[int] = []

    def sahte() -> list[dict[str, Any]]:
        cagri.append(1)
        return OZET

    monkeypatch.setattr(codegen, "dil_durumu_ozeti", sahte)
    return cagri


def test_kod_ekraninda_dil_durumu_eklenir(ozet: list[int]) -> None:
    ekran = {"rota_kalibi": "/kod", "ekran": "Kod (scriptler)"}
    for rol in ("engineer", "admin"):
        out = flow._dil_durumu_ekle(ekran, _mesaj(rol))
        assert out is not None and out["dil_secenekleri"] == OZET
        assert "Platform ayarları › Android › Test dilleri" in str(out)
    assert "dil_secenekleri" not in ekran  # girdi değişmez


def test_baska_ekran_ya_da_yetkisiz_rolde_eklenmez(ozet: list[int]) -> None:
    assert flow._dil_durumu_ekle({"rota_kalibi": "/kosular"}, _mesaj("engineer")) == {
        "rota_kalibi": "/kosular"
    }
    assert flow._dil_durumu_ekle({"rota_kalibi": "/kod"}, _mesaj("tester")) == {
        "rota_kalibi": "/kod"
    }
    assert flow._dil_durumu_ekle(None, _mesaj("engineer")) is None
    assert ozet == []  # forge okunmadı


def test_ozet_hatasi_cevabi_dusurmez(monkeypatch: pytest.MonkeyPatch) -> None:
    def bozuk() -> list[dict[str, Any]]:
        raise RuntimeError("forge")

    monkeypatch.setattr(codegen, "dil_durumu_ozeti", bozuk)
    assert flow._dil_durumu_ekle({"rota_kalibi": "/kod"}, _mesaj("engineer")) == {
        "rota_kalibi": "/kod"
    }
