"""Asistan güvenlik olayı ve 10 dk dondurma (specs/013 §6.1–6.2; K4, K11).

Gerçek Postgres ve gerçek API ucu; worker yok (mesajlar SQL ile bitirilir).
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.assistant import test_asistan_api as _api
from tp_core.audit import verify_chain
from tp_core.features.assistant import budget, olay

client = _api.client
giris = _api.giris
kalp_atisi = _api.kalp_atisi
sohbet_ac = _api.sohbet_ac
sor = _api.sor
mesaj_bitir = _api.mesaj_bitir
tek = _api.tek

SAHTE = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"


@pytest.fixture
def canli(engine: Engine) -> None:
    kalp_atisi(engine)


def _sir_dene(c: TestClient, sohbet: str, n: int) -> None:
    for _ in range(n):
        r = sor(c, sohbet, soru=f"token bu mu {SAHTE}?")
        assert r.status_code == 422 and r.json()["kod"] == "sir_icerik", r.text


def _olaylar(engine: Engine, kullanici_id: uuid.UUID) -> list[dict]:
    with engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT tur, ciddi, ayrinti, mesaj_id FROM asistan_guvenlik_olay "
                    "WHERE kullanici_id = :k ORDER BY zaman, tur"
                ),
                {"k": kullanici_id},
            ).mappings()
        ]


def _supheli(engine: Engine) -> int:
    return tek(engine, "SELECT count(*) FROM audit_event WHERE eylem = 'asistan.supheli'")


# ------------------------------------------------------------------ API


def test_uc_ardisik_sir_dondurur_ve_kalan_s_doner(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    u = make_user("analyst")
    giris(client, u)
    s = sohbet_ac(client)
    _sir_dene(client, s, budget.DONDURMA_ESIK)

    olaylar = _olaylar(engine, u.id)
    assert [o["tur"] for o in olaylar] == ["sir_icerik"] * 3
    assert all(o["ciddi"] and o["mesaj_id"] is None for o in olaylar)
    assert all(set(o["ayrinti"]) == {"desen"} for o in olaylar)
    assert SAHTE not in json.dumps(olaylar, default=str)

    # Dördüncü POST temiz soru olsa da 429 `donduruldu`.
    r = sor(client, s, soru="Bu buton neden gri?")
    assert r.status_code == 429, r.text
    govde = r.json()
    assert govde["kod"] == "donduruldu"
    assert 0 < govde["kalan_s"] <= budget.DONDURMA_SURE_S
    assert r.headers["Retry-After"] == str(govde["kalan_s"])
    assert "dk" in govde["detail"]
    assert tek(engine, "SELECT count(*) FROM asistan_mesaj") == 0

    # Dondurma başlangıcında bir kez `donduruldu` olayı + denetim satırı (ayrıntıda yalnız sayı).
    assert [o["tur"] for o in _olaylar(engine, u.id)][-1] == "donduruldu"
    assert _supheli(engine) == 1
    with engine.connect() as c:
        aktor, nesne, ozet = c.execute(
            text("SELECT aktor, nesne, ozet FROM audit_event WHERE eylem = 'asistan.supheli'")
        ).one()
        assert verify_chain(c).ok
    assert aktor == u.kullanici_adi and nesne == f"app_user:{u.id}"
    assert set(ozet) == {"ardisik_ciddi", "sure_s"} and ozet["ardisik_ciddi"] == 3

    # Donmuş kullanıcının sır denemesi 429 alır; sayaç büyümez, yeni olay/denetim yazılmaz.
    r = sor(client, s, soru=f"yine {SAHTE}")
    assert r.status_code == 429 and r.json()["kod"] == "donduruldu"
    assert SAHTE not in r.text
    r = sor(client, s, soru="başka soru")
    assert r.status_code == 429
    tur_say = [o["tur"] for o in _olaylar(engine, u.id)]
    assert tur_say.count("sir_icerik") == 3 and tur_say.count("donduruldu") == 1
    assert _supheli(engine) == 1


def test_dondurma_derin_istegi_de_reddeder(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    u = make_user("tester")
    giris(client, u)
    s = sohbet_ac(client)
    r = sor(client, s)
    assert r.status_code == 202
    mid = r.json()["mesaj_id"]
    mesaj_bitir(engine, mid, amac="assistant")
    _sir_dene(client, s, 3)
    r = sor(client, s, ust_mesaj_id=mid)
    assert r.status_code == 429 and r.json()["kod"] == "donduruldu"


def test_kabul_edilen_soru_sayaci_sifirlar(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    u = make_user("engineer")
    giris(client, u)
    s = sohbet_ac(client)
    _sir_dene(client, s, 2)
    r = sor(client, s)
    assert r.status_code == 202, r.text
    mesaj_bitir(engine, r.json()["mesaj_id"], amac="assistant")
    _sir_dene(client, s, 2)
    with engine.connect() as c:
        assert olay.ardisik_ciddi(c, u.id)[0] == 2
    r = sor(client, s)
    assert r.status_code == 202, r.text
    assert _supheli(engine) == 0


def test_on_dakikadan_eski_ucuncu_olay_dondurmaz(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    u = make_user("po")
    giris(client, u)
    s = sohbet_ac(client)
    _sir_dene(client, s, 3)
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE asistan_guvenlik_olay SET zaman = zaman - make_interval(secs => :s) "
                "WHERE kullanici_id = :k"
            ),
            {"s": budget.DONDURMA_SURE_S + 60, "k": u.id},
        )
    r = sor(client, s)
    assert r.status_code == 202, r.text
    assert _supheli(engine) == 0
    assert "donduruldu" not in [o["tur"] for o in _olaylar(engine, u.id)]


def test_dondurma_kullanici_bazli(client: TestClient, make_user, engine: Engine, canli) -> None:
    a, b = make_user("analyst"), make_user("analyst")
    giris(client, a)
    _sir_dene(client, sohbet_ac(client), 3)
    giris(client, b)
    r = sor(client, sohbet_ac(client))
    assert r.status_code == 202, r.text


def test_baslikta_sir_olay_yazmaz(client: TestClient, make_user, engine: Engine, canli) -> None:
    """K11: yalnız sorudaki sır sayılır; sohbet başlığı 422'si sayaca girmez."""
    u = make_user("analyst")
    giris(client, u)
    r = client.post("/assistant/conversations", json={"baslik": f"x {SAHTE}"})
    assert r.status_code == 422 and r.json()["kod"] == "sir_icerik"
    assert _olaylar(engine, u.id) == []


# ------------------------------------------------------------------ olay.py birimleri


def test_olay_yaz_ciddi_turden_turetilir_ve_ayrinti_denetlenir(engine: Engine, make_user) -> None:
    u = make_user("analyst")
    with engine.begin() as c:
        for tur in ("sir_icerik", "kanarya", "istem_sizintisi", "kisisel_veri", "sinyal"):
            olay.olay_yaz(c, u.id, tur)
        olay.olay_yaz(c, u.id, "sinyal", ayrinti={"sinyaller": ["uretim_verisi_talebi"]})
    ciddi = {o["tur"]: o["ciddi"] for o in _olaylar(engine, u.id)}
    assert ciddi == {
        "sir_icerik": True,
        "kanarya": True,
        "istem_sizintisi": True,
        "kisisel_veri": False,
        "sinyal": False,
    }
    with engine.begin() as c:
        with pytest.raises(ValueError):
            olay.olay_yaz(c, u.id, "uydurma")
        with pytest.raises(ValueError):
            olay.olay_yaz(c, u.id, "sir_icerik", ayrinti={"deger": "x"})
        with pytest.raises(ValueError):
            olay.olay_yaz(c, u.id, "sir_icerik", ayrinti={"desen": f"token bu {SAHTE} mu"})
        with pytest.raises(ValueError):
            olay.olay_yaz(c, u.id, "sinyal", ayrinti={"sinyaller": ["a b c"]})


def test_ciddi_olmayan_olay_sayilmaz_ve_kalan_hesabi(engine: Engine, make_user) -> None:
    u = make_user("analyst")
    with engine.begin() as c:
        for _ in range(5):
            olay.olay_yaz(c, u.id, "kisisel_veri")
            olay.olay_yaz(c, u.id, "sinyal")
    with engine.connect() as c:
        simdi = c.execute(text("SELECT now()")).scalar_one()
        assert olay.ardisik_ciddi(c, u.id) == (0, None)
        assert olay.dondurma_kalan_s(c, u.id, simdi) is None
    with engine.begin() as c:
        for _ in range(3):
            olay.olay_yaz(c, u.id, "kanarya")
    with engine.connect() as c:
        sayi, son = olay.ardisik_ciddi(c, u.id)
        assert sayi == 3 and son is not None
        assert olay.dondurma_kalan_s(c, u.id, son) == budget.DONDURMA_SURE_S
        assert olay.dondurma_kalan_s(c, u.id, son + timedelta(seconds=599.5)) == 1
        assert olay.dondurma_kalan_s(c, u.id, son + timedelta(seconds=600)) is None
