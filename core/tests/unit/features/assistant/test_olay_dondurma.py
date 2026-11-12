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

from tests.unit.conftest import Db
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
    dk = -(-govde["kalan_s"] // 60)
    assert govde["detail"] == (
        "Art arda engellenen istekler nedeniyle asistan geçici olarak durduruldu. "
        f"Yaklaşık {dk} dk sonra yeniden sorabilirsiniz; sorunuz kutuda duruyor."
    )
    assert tek(engine, "SELECT count(*) FROM asistan_mesaj") == 0

    # Dondurma başlangıcında bir kez `donduruldu` olayı + denetim satırı (ayrıntıda yalnız sayı).
    assert [o["tur"] for o in _olaylar(engine, u.id)][-1] == "donduruldu"
    assert _supheli(engine) == 1
    with engine.connect() as c:
        aktor, nesne, ozet = c.execute(
            text("SELECT aktor, nesne, ozet FROM audit_event WHERE eylem = 'asistan.supheli'")
        ).one()
        assert verify_chain(c).ok
    # Denetim aktörü takma ad (kullanıcı adı değil; PRV5).
    assert aktor == f"app_user:{u.id}" and nesne == f"app_user:{u.id}"
    assert u.kullanici_adi not in json.dumps([aktor, nesne, ozet])
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


def test_sizintili_cevaplar_sayaci_sifirlamaz_ve_dondurur(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    """K11: kanarya/istem sızıntısıyla biten soru temiz kabul değildir; üç ardışık sızıntı
    (aralarındaki kabul edilen sorulara rağmen) dondurur. Temiz biten soru yine sıfırlar."""
    u = make_user("analyst")
    giris(client, u)
    s = sohbet_ac(client)
    for _ in range(3):
        r = sor(client, s)
        assert r.status_code == 202, r.text
        mid = r.json()["mesaj_id"]
        mesaj_bitir(engine, mid, amac="assistant")
        with engine.begin() as c:
            soru = olay.soru_kimligi(c, uuid.UUID(mid))
            olay.olay_yaz(c, u.id, "istem_sizintisi", mesaj_id=soru)
    with engine.connect() as c:
        assert olay.ardisik_ciddi(c, u.id)[0] == 3
    r = sor(client, s)
    assert r.status_code == 429 and r.json()["kod"] == "donduruldu", r.text

    v = make_user("analyst")
    giris(client, v)
    s2 = sohbet_ac(client)
    r = sor(client, s2)
    mid = r.json()["mesaj_id"]
    mesaj_bitir(engine, mid, amac="assistant")
    with engine.begin() as c:
        olay.olay_yaz(c, v.id, "kanarya", mesaj_id=olay.soru_kimligi(c, uuid.UUID(mid)))
    r = sor(client, s2)  # temiz biten soru
    mesaj_bitir(engine, r.json()["mesaj_id"], amac="assistant")
    with engine.connect() as c:
        assert olay.ardisik_ciddi(c, v.id)[0] == 0


def _derin_cocuk(engine: Engine, ust: str) -> str:
    """Üst cevaba "Daha ayrıntılı" çocuğu (sohbetin sonuna; API'nin eklediği biçimde)."""
    cocuk = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, ust_mesaj_id, "
                "icerik, durum, amac, kip, tetik) SELECT :id, sohbet_id, kullanici_id, "
                "(SELECT max(sira) + 1 FROM asistan_mesaj x WHERE x.sohbet_id = a.sohbet_id), "
                "'assistant', a.id, a.icerik, 'done', 'assistant_deep', 'soru', 'kullanici' "
                "FROM asistan_mesaj a WHERE a.id = :u"
            ),
            {"id": cocuk, "u": ust},
        )
    return str(cocuk)


def test_soru_kimligi_zincirin_kok_sorusu(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    u = make_user("analyst")
    giris(client, u)
    s = sohbet_ac(client)
    cevaplar = []
    for _ in range(2):
        r = sor(client, s)
        assert r.status_code == 202, r.text
        cevaplar.append(r.json()["mesaj_id"])
        mesaj_bitir(engine, cevaplar[-1], amac="assistant")
    cocuk = _derin_cocuk(engine, cevaplar[0])
    torun = _derin_cocuk(engine, cocuk)
    with engine.connect() as c:
        sorular = [olay.soru_kimligi(c, uuid.UUID(m)) for m in cevaplar]
        assert len(set(sorular)) == 2
        for m in (cocuk, torun):
            assert olay.soru_kimligi(c, uuid.UUID(m)) == sorular[0]
        assert olay.soru_kimligi(c, sorular[1]) == sorular[1]  # kullanıcı mesajı kendisi
        assert olay.soru_kimligi(c, uuid.uuid4()) is None


def test_derin_cocuk_sizintisi_kok_soruyu_kirli_sayar(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    """SEC11: S1, C1, S2, C2, D(C1) — D'nin sızıntısı S1'e bağlı (soru kimliği) ve sayılır. S1'in
    ilk cevabı temiz olduğundan S1 sıfırlama noktası olarak kalır (BE2-1); S2'nin ilk cevabı
    sızınca S2 sıfırlamaz ve sayılar birikir."""
    u = make_user("analyst")
    giris(client, u)
    s = sohbet_ac(client)
    cevaplar = []
    for _ in range(2):
        r = sor(client, s)
        cevaplar.append(r.json()["mesaj_id"])
        mesaj_bitir(engine, cevaplar[-1], amac="assistant")
    d = _derin_cocuk(engine, cevaplar[0])
    with engine.begin() as c:
        s1 = olay.soru_kimligi(c, uuid.UUID(d))
        olay.olay_yaz(c, u.id, "kanarya", mesaj_id=s1, ayrinti={"cevap": d})
    with engine.connect() as c:
        assert olay.ardisik_ciddi(c, u.id)[0] == 1
    # S2'nin ilk cevabına sızıntı: S2 sıfırlama noktası değil, sayım 2 (D + S2).
    with engine.begin() as c:
        s2 = olay.soru_kimligi(c, uuid.UUID(cevaplar[1]))
        olay.olay_yaz(c, u.id, "kanarya", mesaj_id=s2)
    with engine.connect() as c:
        assert olay.ardisik_ciddi(c, u.id)[0] == 2
    r = sor(client, s)  # temiz kabul edilen soru sayacı sıfırlar
    assert r.status_code == 202
    with engine.connect() as c:
        assert olay.ardisik_ciddi(c, u.id)[0] == 0


def test_derin_cevap_sizintisi_onceki_sifirlamayi_geri_almaz(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    """BE2-1 (K11 = ardışık ciddi olay): sır×2 → temiz Q1 (sıfırlar) → Q1'in "Daha ayrıntılı"
    cevabı sızdırır. Derin sızıntı yeni bir ciddi olaydır (1) ama Q1'in temizliğini geri almaz:
    eski iki sır olayı yeniden sayılıp dondurmaz. Karşı örnek: sızıntı Q1'in İLK cevabındaysa
    Q1 sıfırlamaz ve 3 olay dondurur."""
    for ilk_cevapta in (False, True):
        u = make_user("analyst")
        giris(client, u)
        s = sohbet_ac(client)
        _sir_dene(client, s, 2)
        r = sor(client, s)
        assert r.status_code == 202, r.text
        c1 = r.json()["mesaj_id"]
        mesaj_bitir(engine, c1, amac="assistant")
        with engine.connect() as c:
            assert olay.ardisik_ciddi(c, u.id)[0] == 0
        sizan = c1 if ilk_cevapta else _derin_cocuk(engine, c1)
        with engine.begin() as c:
            q1 = olay.soru_kimligi(c, uuid.UUID(sizan))
            olay.olay_yaz(c, u.id, "kanarya", mesaj_id=q1, ayrinti={"cevap": sizan})
        with engine.connect() as c:
            assert olay.ardisik_ciddi(c, u.id)[0] == (3 if ilk_cevapta else 1)
        r = sor(client, s)
        if ilk_cevapta:
            assert r.status_code == 429 and r.json()["kod"] == "donduruldu", r.text
        else:
            assert r.status_code == 202, r.text
            assert _supheli(engine) == 0


def test_ayni_sorudaki_tekrarlanan_iz_sizintisi_bir_kez_sayilir(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    """SEC2-Y4: aynı sorunun ilk ve derin cevaplarındaki `istem_sizintisi` olayları tek ciddi olay
    sayılır; kanarya her olayda ayrı sayılır."""
    u = make_user("analyst")
    giris(client, u)
    s = sohbet_ac(client)
    r = sor(client, s)
    c1 = r.json()["mesaj_id"]
    mesaj_bitir(engine, c1, amac="assistant")
    d1 = _derin_cocuk(engine, c1)
    d2 = _derin_cocuk(engine, d1)
    with engine.begin() as c:
        q = olay.soru_kimligi(c, uuid.UUID(c1))
        for cevap in (c1, d1, d2):
            olay.olay_yaz(c, u.id, "istem_sizintisi", mesaj_id=q, ayrinti={"cevap": cevap})
    with engine.connect() as c:
        assert olay.ardisik_ciddi(c, u.id)[0] == 1
    assert sor(client, s).status_code != 429
    with engine.begin() as c:
        for cevap in (d1, d2):
            olay.olay_yaz(c, u.id, "kanarya", mesaj_id=q, ayrinti={"cevap": cevap})
    with engine.connect() as c:
        # Yeni soru (yukarıdaki POST) temiz: sıfırlama noktası o; sonraki iki kanarya sayılır.
        assert olay.ardisik_ciddi(c, u.id)[0] == 2
    # Soru kimliksiz iz olayları (mesaj_id NULL) birleştirilmez.
    with engine.begin() as c:
        olay.olay_yaz(c, u.id, "istem_sizintisi")
        olay.olay_yaz(c, u.id, "istem_sizintisi")
    with engine.connect() as c:
        assert olay.ardisik_ciddi(c, u.id)[0] == 4


def test_kisisel_veri_reddi_olay_yazar_sayaca_girmez(
    client: TestClient, make_user, engine: Engine, canli
) -> None:
    u = make_user("tester")
    giris(client, u)
    s = sohbet_ac(client)
    for _ in range(budget.DONDURMA_ESIK + 1):
        r = sor(client, s, soru="Müşterinin kartı 5105 1051 0510 5100, ödeme neden düştü?")
        assert r.status_code == 422 and r.json()["kod"] == "kisisel_veri", r.text
    assert r.json()["detail"] == (
        "Soru ya da eklenen ekran bilgisi bir kart numarası içeriyor. Numarayı silin ya da "
        "maskeleyin (ör. 5105 **** **** 5100) ve yeniden gönderin."
    )
    olaylar = _olaylar(engine, u.id)
    assert [o["tur"] for o in olaylar] == ["kisisel_veri"] * (budget.DONDURMA_ESIK + 1)
    assert all(not o["ciddi"] and o["ayrinti"] == {"alan": ["soru"]} for o in olaylar)
    assert "5105" not in json.dumps(olaylar, default=str)
    assert sor(client, s).status_code == 202


def test_ret_yolunda_olay_yazim_hatasi_500_donmez(
    client: TestClient,
    make_user,
    engine: Engine,
    canli,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """BE6: olay yazımı düşse de 422/429 aynen döner; kayda yalnız sınıf adı."""
    u = make_user("analyst")
    giris(client, u)
    s = sohbet_ac(client)

    def bozuk(*_a: object, **_k: object) -> None:
        raise RuntimeError(f"bağlantı koptu {SAHTE}")

    monkeypatch.setattr(olay, "olay_yaz", bozuk)
    with caplog.at_level("WARNING"):
        r = sor(client, s, soru=f"token bu mu {SAHTE}?")
        assert r.status_code == 422 and r.json()["kod"] == "sir_icerik", r.text
        r = sor(client, s, soru="kart 5105105105105100 neden reddedildi?")
        assert r.status_code == 422 and r.json()["kod"] == "kisisel_veri", r.text
    assert "RuntimeError" in caplog.text and SAHTE not in caplog.text
    monkeypatch.undo()

    _sir_dene(client, s, budget.DONDURMA_ESIK)
    monkeypatch.setattr(olay, "dondurma_baslat", bozuk)
    r = sor(client, s)
    assert r.status_code == 429 and r.json()["kod"] == "donduruldu", r.text


def test_on_dakikadan_eski_ucuncu_olay_dondurmaz(
    client: TestClient, make_user, engine: Engine, db: Db, canli
) -> None:
    u = make_user("po")
    giris(client, u)
    s = sohbet_ac(client)
    _sir_dene(client, s, 3)
    # Olay satırı tp_app için değiştirilemez (UPDATE yetkisi yok); zaman sahiple geri alınır.
    sahip = db.engine("tp_owner")
    with sahip.begin() as c:
        c.execute(
            text(
                "UPDATE asistan_guvenlik_olay SET zaman = zaman - make_interval(secs => :s) "
                "WHERE kullanici_id = :k"
            ),
            {"s": budget.DONDURMA_SURE_S + 60, "k": u.id},
        )
    sahip.dispose()
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
