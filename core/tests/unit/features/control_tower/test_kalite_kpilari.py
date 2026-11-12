"""Kontrol Kulesi'nin 012 anahtarları (§4.7, §13.2): `beklenti_dogrulugu`, `onayli_uyumsuz` ve
`hata_yakalama`.

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
from tp_core.features.hata_kosusu import katalog
from tp_core.features.oracle import metrik
from tp_core.models import HataKosusu, HataKosusuAdim

pytestmark = pytest.mark.usefixtures("ci_env")

BOS_BEKLENTI = {
    "oran": None,
    "uyumlu": 0,
    "uyumsuz": 0,
    "kismen": 0,
    "kontrol_edilemedi": 0,
    "kapsam_disi": 0,
    "istisna": 0,
    "kontrolsuz_onay": 0,
    "n_case": 0,
    "n_story": 0,
    "tablolu_story": 0,
    "toplam_story": 0,
    "kapsam_orani": None,
    "golden_kaynakli": 0,
    "tekrar": 0,
}
BEKLENTI_ALANLARI = set(BOS_BEKLENTI)


def test_bos_veritabaninda_olculmedi(engine: Engine) -> None:
    with Session(engine) as s:
        k = ct.control_tower(s)
    assert k["beklenti_dogrulugu"] == BOS_BEKLENTI
    assert k["onayli_uyumsuz"] == []
    assert k["hata_yakalama"] is None
    assert k["kaynaklar"]["onayli_uyumsuz"] == ct.ONAYLI_UYUMSUZ_KAYNAGI
    assert k["kaynaklar"]["beklenti_dogrulugu"] == metrik.KAYNAK
    assert k["kaynaklar"]["hata_yakalama"] == ct.HATA_YAKALAMA_KOSU_YOK


def test_beklenti_kaynagi_degerden_kaynaklara_tasinir(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def sahte(session: Session, requirement_id=None) -> dict:
        assert requirement_id is None  # Kule tüm story'leri sayar
        return {**BOS_BEKLENTI, "oran": 0.75, "uyumlu": 3, "kaynak": "ölçüm kaynağı"}

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
    for sira, (asama, sonuc, kod, kiran) in enumerate(adimlar, start=1):
        s.add(
            HataKosusuAdim(
                kosu_id=kosu.id,
                platform="web",
                hata_kodu=kod,
                asama=asama,
                sonuc=sonuc,
                sira=sira,
                kiran_testler=kiran,
            )
        )
    s.flush()
    return kosu


def test_hata_yakalama_son_tam_katalog_kosusundan(engine: Engine) -> None:
    """Tam katalog koşusu (R4 §13.2 şekli): ilk hata AI testiyle, ikincisi yalnız el yazısıyla
    yakalanır, biri geçersiz, kalanlar kaçar. Kısmi ve süren koşu ölçünün yerini almaz."""
    kodlar = katalog.kodlar()
    assert "kampanya_tek_bedava" in kodlar and "kampanya_esik_7" not in kodlar
    ai = [{"test": "tests/generated/c2.spec.ts", "kaynak": "ai"}]
    el = [{"test": "tests/cart.spec.ts", "kaynak": "el"}]
    hata_adimlari = []
    for i, kod in enumerate(kodlar):
        if i == 0:
            hata_adimlari.append(("hata", "yakalandi", kod, ai))
        elif i == 1:
            hata_adimlari.append(("hata", "yakalandi", kod, el))
        elif i == 2:
            hata_adimlari.append(("hata", "gecersiz", kod, []))
        else:
            hata_adimlari.append(("hata", "kacti", kod, []))
    with Session(engine) as s:
        tamam = _kosu(
            s,
            "done",
            datetime(2026, 11, 12, 9, 30, tzinfo=UTC),
            [("temel", "yesil", None, []), *hata_adimlari, ("kapanis", "yesil", None, [])],
        )
        # Daha yeni ama kısmi koşu (tek hata) ve süren koşu ölçüye girmez.
        _kosu(
            s,
            "done",
            datetime(2026, 11, 12, 10, 0, tzinfo=UTC),
            [("temel", "yesil", None, []), ("hata", "yakalandi", kodlar[0], ai)],
        )
        _kosu(s, "running", None, [("temel", "bekliyor", None, [])])
        s.commit()
        k = ct.control_tower(s)
    hy = k["hata_yakalama"]
    assert "kaynak" not in hy
    assert hy["son_kosu"]["id"] == str(tamam.id) and hy["son_kosu"]["durum"] == "done"
    n = len(kodlar)
    gecerli = n - 1
    assert (hy["yakalanan"], hy["kacan"], hy["gecersiz"]) == (1, gecerli - 1, 1)
    assert hy["oran"] == round(1 / gecerli, 4)
    assert (hy["el_yazisi"]["yakalanan"], hy["el_yazisi"]["kacan"]) == (1, gecerli - 1)
    assert hy["kapsam"]["tam_katalog"] is True and hy["kapsam"]["katalog"] == n
    assert hy["kapsam"]["kosulan_hata"] == n and hy["kapsam"]["gecerli_adim"] == gecerli
    assert hy["platformlar"][0]["platform"] == "web"
    # `kacanlar`: hiçbir testin yakalamadığı (kacti) hatalar; `ai_kacanlar`: AI testlerinin
    # kaçırdığı (el yazısı yakalamış olabilir) hatalar.
    kacan_kodlar = [x["hata_kodu"] for x in hy["kacanlar"]]
    ai_kacan_kodlar = [x["hata_kodu"] for x in hy["ai_kacanlar"]]
    assert kacan_kodlar == kodlar[3:]
    assert ai_kacan_kodlar == [kodlar[1], *kodlar[3:]]
    assert "yakalanan 1" in k["kaynaklar"]["hata_yakalama"]


def test_api_iki_anahtari_ve_kaynaklari_tasir(api: TestClient, make_user, engine: Engine) -> None:
    login(api, make_user("tester"))
    k = api.get("/control-tower").json()
    assert set(k["beklenti_dogrulugu"]) == BEKLENTI_ALANLARI
    assert k["hata_yakalama"] is None
    assert k["onayli_uyumsuz"] == []
    assert {"beklenti_dogrulugu", "onayli_uyumsuz", "hata_yakalama"} <= set(k["kaynaklar"])
