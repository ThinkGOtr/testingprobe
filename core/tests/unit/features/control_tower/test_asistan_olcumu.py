"""Kontrol Kulesi asistan ölçüleri (AI-ASISTAN-PLANI §6.4 son madde, §17.7): `assistant*`
amaçları ayrı maliyet grubu; kural başına "Neden? Sor" ve Faydalı/Gizle/Yaptım sayıları, kişi
bazlı değil. Gerçek Postgres."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import login
from tp_core.features.assistant import oneri
from tp_core.features.control_tower import asistan
from tp_core.features.control_tower import service as ct


def _ai_call(engine: Engine, amac: str, maliyet: str, *, gun_once: int = 0) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO ai_call (id, amac, saglayici, model, mod, maliyet, olusturma) VALUES "
                "(:id, :a, 'anthropic', 'm', 'live', :m, now() - make_interval(days => :g))"
            ),
            {"id": uuid.uuid4(), "a": amac, "m": Decimal(maliyet), "g": gun_once},
        )


def _sohbet(engine: Engine, kullanici_id: uuid.UUID) -> uuid.UUID:
    sid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO asistan_sohbet (id, kullanici_id) VALUES (:i, :k)"),
            {"i": sid, "k": kullanici_id},
        )
    return sid


def _mesaj(
    engine: Engine,
    sohbet: uuid.UUID,
    kullanici_id: uuid.UUID,
    sira: int,
    *,
    rol: str = "user",
    baglam: dict[str, Any] | None = None,
) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, baglam, durum) "
                "VALUES (:i, :s, :k, :n, :r, CAST(:b AS jsonb), 'done')"
            ),
            {
                "i": uuid.uuid4(),
                "s": sohbet,
                "k": kullanici_id,
                "n": sira,
                "r": rol,
                "b": json.dumps(baglam) if baglam is not None else None,
            },
        )


def _geri_bildirim(engine: Engine, kullanici_id: uuid.UUID, kural_id: str, deger: int) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO asistan_oneri_geri_bildirim (id, kullanici_id, kural_id, deger) "
                "VALUES (:i, :k, :r, :d)"
            ),
            {"i": uuid.uuid4(), "k": kullanici_id, "r": kural_id, "d": deger},
        )


@pytest.fixture
def kurallar() -> list[str]:
    ids = [k.id for k in oneri.kural_seti().kurallar]
    assert len(ids) >= 2
    return ids


@pytest.fixture
def olcum_verisi(engine: Engine, make_user, kurallar: list[str]) -> dict[str, Any]:
    k1, k2 = kurallar[0], kurallar[1]
    u, v = make_user("analyst"), make_user("po")
    su, sv = _sohbet(engine, u.id), _sohbet(engine, v.id)
    # "Neden? Sor": kullanıcı sorusu öneri bağlamlı; cevap (rol=assistant) aynı bağlamı taşır ama
    # sayılmaz; öneri bağlamsız soru sayılmaz.
    _mesaj(engine, su, u.id, 1, baglam={"oneri": {"kural_id": k1}})
    _mesaj(engine, su, u.id, 2, rol="assistant", baglam={"oneri": {"kural_id": k1}})
    _mesaj(engine, sv, v.id, 1, baglam={"oneri": {"kural_id": k1}, "rota": "/x"})
    _mesaj(engine, sv, v.id, 3, baglam={"rota": "/x"})
    _mesaj(engine, sv, v.id, 5, baglam={"oneri": {"kural_id": "kaldirilmis-kural"}})
    for kid, deger, kim in ((k1, 1, u), (k1, 1, v), (k1, -1, u), (k2, 2, v), (k2, -1, v)):
        _geri_bildirim(engine, kim.id, kid, deger)
    _ai_call(engine, "assistant", "0.01")
    _ai_call(engine, "assistant_deep", "0.09")
    _ai_call(engine, "assistant_deep", "0.10", gun_once=3)
    _ai_call(engine, "case_generation", "0.50")
    return {"k1": k1, "k2": k2, "kullanicilar": (u, v)}


def test_maliyet_assistant_amaclari_ayri_grup(engine: Engine, olcum_verisi) -> None:
    with Session(engine) as s:
        k = ct.control_tower(s)
    ai = k["ai_katkisi"]
    g = ai["amac_gruplari"]
    assert g["asistan"]["amaclar"] == ["assistant", "assistant_deep"]
    assert g["asistan"]["cagri"] == 3 and g["asistan"]["maliyet_usd"] == 0.2
    # Bugün: 3 gün önceki derin çağrı hariç.
    assert g["asistan"]["maliyet_usd_bugun"] == 0.1
    assert g["diger"] == {
        "cagri": 1,
        "maliyet_usd": 0.5,
        "maliyet_usd_bugun": 0.5,
        "amaclar": ["case_generation"],
    }
    # Gruplar toplamı bozmaz: genel toplam ve amaç kırılımı aynen kalır.
    assert ai["maliyet_usd_toplam"] == 0.7 and ai["cagri_sayisi"] == 4
    assert ai["amaclar"]["assistant_deep"] == {"cagri": 2, "maliyet_usd": 0.19}
    assert k["asistan"]["maliyet"] == g
    assert "assistant*" in k["kaynaklar"]["maliyet"] and "asistan" in k["kaynaklar"]


def test_oneriler_kural_basina_sayilar(engine: Engine, olcum_verisi, kurallar) -> None:
    with Session(engine) as s:
        k = ct.control_tower(s)
    o = k["asistan"]
    satir = {x["kural_id"]: x for x in o["oneriler"]}
    k1, k2 = olcum_verisi["k1"], olcum_verisi["k2"]
    assert {a: satir[k1][a] for a in asistan.SAYAC_ALANLARI} == {
        "neden_sor": 2,
        "faydali": 2,
        "gizle": 1,
        "yaptim": 0,
    }
    assert {a: satir[k2][a] for a in asistan.SAYAC_ALANLARI} == {
        "neden_sor": 0,
        "faydali": 0,
        "gizle": 1,
        "yaptim": 1,
    }
    # Yüklü her kural görünür (sıfır sayılılar dahil); başlık yer tutucusuz, ekran dolu.
    assert set(kurallar) <= set(satir)
    assert all(satir[i]["kural_setinde"] and satir[i]["ekran"] for i in kurallar)
    assert all("{" not in (satir[i]["baslik"] or "") for i in kurallar)
    # Kural dosyasından kalkmış ama kaydı olan kimlik ayrıca listelenir.
    assert satir["kaldirilmis-kural"]["kural_setinde"] is False
    assert satir["kaldirilmis-kural"]["neden_sor"] == 1
    # En çok etkileşim önce.
    assert o["oneriler"][0]["kural_id"] == k1
    assert o["oneri_toplam"] == {"neden_sor": 3, "faydali": 2, "gizle": 2, "yaptim": 1}
    assert o["saklama_gun"] == 90


def test_kisi_bazli_veri_yok(engine: Engine, olcum_verisi) -> None:
    with Session(engine) as s:
        k = ct.control_tower(s)
    metin = json.dumps(k["asistan"], ensure_ascii=False)
    for u in olcum_verisi["kullanicilar"]:
        assert str(u.id) not in metin and u.kullanici_adi not in metin
    alanlar = {a for x in k["asistan"]["oneriler"] for a in x}
    assert alanlar == {"kural_id", "baslik", "ekran", "kural_setinde", *asistan.SAYAC_ALANLARI}


def test_bos_veritabaninda_sifir(engine: Engine, kurallar) -> None:
    with Session(engine) as s:
        k = ct.control_tower(s)
    o = k["asistan"]
    assert o["oneri_toplam"] == dict.fromkeys(asistan.SAYAC_ALANLARI, 0)
    assert [x["kural_id"] for x in o["oneriler"]] == kurallar
    assert o["maliyet"]["asistan"] == {
        "cagri": 0,
        "maliyet_usd": 0.0,
        "maliyet_usd_bugun": 0.0,
        "amaclar": [],
    }


def test_bozuk_kural_seti_karti_dusurmez(
    engine: Engine, olcum_verisi, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bozuk() -> Any:
        raise oneri.KuralHatasi("bozuk")

    monkeypatch.setattr(oneri, "kural_seti", bozuk)
    with Session(engine) as s:
        satirlar = asistan.oneri_olcumu(s)
    assert {x["kural_id"] for x in satirlar} == {
        olcum_verisi["k1"],
        olcum_verisi["k2"],
        "kaldirilmis-kural",
    }
    assert all(x["kural_setinde"] is False for x in satirlar)


def test_saklama_gunu_ortamdan(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_ASISTAN_SAKLAMA_GUN", "30")
    with Session(engine) as s:
        assert ct.control_tower(s)["asistan"]["saklama_gun"] == 30


def test_api_asistan_bolumu(api: TestClient, make_user, olcum_verisi) -> None:
    login(api, make_user("tester"))
    r = api.get("/control-tower")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asistan"]["oneri_toplam"]["neden_sor"] == 3
    assert body["ai_katkisi"]["amac_gruplari"]["asistan"]["cagri"] == 3
