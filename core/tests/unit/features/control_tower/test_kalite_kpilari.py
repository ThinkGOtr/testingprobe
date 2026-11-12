"""Kontrol Kulesi'nin 012 anahtarları (§4.7): `beklenti_dogrulugu` ve `hata_yakalama`.

Kule kuralı: KPI değeri kaynak metni taşımaz, kaynak `kaynaklar[<kpi>]`'dadır. Ölçülmeyen değer
uydurulmaz (`oran: null`, koşu yoksa `hata_yakalama: null`). Gerçek sayıların uçtan uca akışı
`tests/unit/features/kalite_e2e/` içindedir.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import login
from tp_core.features.control_tower import service as ct
from tp_core.features.oracle import metrik
from tp_core.models import HataKosusu, HataKosusuAdim

pytestmark = pytest.mark.usefixtures("ci_env")

BEKLENTI_ALANLARI = {
    "oran",
    "uyumlu",
    "uyumsuz",
    "kapsam_disi",
    "kontrol_edilemedi",
    "istisna",
    "kapsam_orani",
}


def test_bos_veritabaninda_olculmedi(engine: Engine) -> None:
    with Session(engine) as s:
        k = ct.control_tower(s)
    assert k["beklenti_dogrulugu"] == {
        "oran": None,
        "uyumlu": 0,
        "uyumsuz": 0,
        "kapsam_disi": 0,
        "kontrol_edilemedi": 0,
        "istisna": 0,
        "kapsam_orani": None,
    }
    assert k["hata_yakalama"] is None
    assert k["kaynaklar"]["beklenti_dogrulugu"] == metrik.KAYNAK
    assert k["kaynaklar"]["hata_yakalama"] == ct.HATA_YAKALAMA_KOSU_YOK


def test_beklenti_kaynagi_degerden_kaynaklara_tasinir(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def sahte(session: Session, requirement_id=None) -> dict:
        assert requirement_id is None  # Kule tüm story'leri sayar
        return {
            "oran": 0.75,
            "uyumlu": 3,
            "uyumsuz": 1,
            "kapsam_disi": 2,
            "kontrol_edilemedi": 1,
            "istisna": 1,
            "kapsam_orani": 0.7143,
            "kaynak": "ölçüm kaynağı",
        }

    monkeypatch.setattr(metrik, "beklenti_dogrulugu", sahte)
    with Session(engine) as s:
        k = ct.control_tower(s)
    assert set(k["beklenti_dogrulugu"]) == BEKLENTI_ALANLARI
    assert k["beklenti_dogrulugu"]["oran"] == 0.75
    assert k["kaynaklar"]["beklenti_dogrulugu"] == "ölçüm kaynağı"


def _kosu(s: Session, durum: str, bitis: datetime | None, adimlar: list[tuple]) -> HataKosusu:
    kosu = HataKosusu(durum=durum, platformlar=["web"], hatalar=[], bitis=bitis)
    s.add(kosu)
    s.flush()
    for sira, (asama, sonuc, kod) in enumerate(adimlar, start=1):
        s.add(
            HataKosusuAdim(
                kosu_id=kosu.id, platform="web", hata_kodu=kod, asama=asama, sonuc=sonuc, sira=sira
            )
        )
    s.flush()
    return kosu


def test_hata_yakalama_son_tamamlanan_kosudan(engine: Engine) -> None:
    with Session(engine) as s:
        tamam = _kosu(
            s,
            "done",
            datetime(2026, 11, 12, 9, 30, tzinfo=UTC),
            [
                ("temel", "yesil", None),
                ("hata", "yakalandi", "kampanya_esik_7"),
                ("hata", "kacti", "min_siparis_500"),
                ("hata", "gecersiz", "fiyat_p004_31"),
                ("kapanis", "yesil", None),
            ],
        )
        _kosu(s, "running", None, [("temel", "bekliyor", None)])  # süren koşu yerini almaz
        s.commit()
        k = ct.control_tower(s)
    hy = k["hata_yakalama"]
    assert "kaynak" not in hy
    assert hy["son_kosu"]["id"] == str(tamam.id) and hy["son_kosu"]["durum"] == "done"
    assert (hy["oran"], hy["yakalanan"], hy["kacan"], hy["gecersiz"]) == (0.5, 1, 1, 1)
    assert hy["platformlar"] == [
        {"platform": "web", "oran": 0.5, "yakalanan": 1, "kacan": 1, "gecersiz": 1}
    ]
    assert [x["hata_kodu"] for x in hy["kacanlar"]] == ["min_siparis_500"]
    kaynak = k["kaynaklar"]["hata_yakalama"]
    assert "yakalanan 1, kaçan 1, geçersiz 1" in kaynak and "%50" in kaynak


def test_api_iki_anahtari_ve_kaynaklari_tasir(api: TestClient, make_user, engine: Engine) -> None:
    login(api, make_user("tester"))
    k = api.get("/control-tower").json()
    assert set(k["beklenti_dogrulugu"]) == BEKLENTI_ALANLARI
    assert k["hata_yakalama"] is None
    assert {"beklenti_dogrulugu", "hata_yakalama"} <= set(k["kaynaklar"])
