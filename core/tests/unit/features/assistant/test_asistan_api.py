"""Asistan HTTP uçları (AI-ASISTAN-PLANI §9, §13 "API (5 role parametrize)").

Gerçek Postgres; worker yok — kalp atışı ve iş/mesaj durumları test içinde SQL ile kurulur. Model
çağrısı yok (core-api zaten model bilmez).
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.conftest import PAROLA, Db
from tp_core.api.main import create_app
from tp_core.features.assistant import api as asistan_api
from tp_core.features.assistant import budget
from tp_core.workflow.service import Principal

ROLLER = ("analyst", "po", "engineer", "tester", "presenter")
REPO = Path(__file__).resolve().parents[5]


# ------------------------------------------------------------------ fikstürler ve yardımcılar


@pytest.fixture
def client(db: Db) -> Iterator[TestClient]:
    from tp_core.auth.login import THROTTLE

    THROTTLE._kayit.clear()
    with TestClient(create_app()) as c:
        yield c
    THROTTLE._kayit.clear()


def giris(c: TestClient, u: Principal) -> None:
    c.cookies.clear()
    r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 200, r.text


def kalp_atisi(
    engine: Engine,
    *,
    yas_s: int = 0,
    mod: str = "off",
    model_hazir: bool = False,
    maskeleme: bool = False,
    musteri_verisi: bool = False,
) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO asistan_durum (id, mod, model_hazir, maskeleme, musteri_verisi, "
                "paket_commit, kalp_atisi) VALUES (1, :mod, :mh, :mk, :mv, 'abc123', "
                "now() - make_interval(secs => :y)) ON CONFLICT (id) DO UPDATE SET "
                "mod = EXCLUDED.mod, model_hazir = EXCLUDED.model_hazir, "
                "maskeleme = EXCLUDED.maskeleme, musteri_verisi = EXCLUDED.musteri_verisi, "
                "kalp_atisi = EXCLUDED.kalp_atisi"
            ),
            {"mod": mod, "mh": model_hazir, "mk": maskeleme, "mv": musteri_verisi, "y": yas_s},
        )


@pytest.fixture
def canli(engine: Engine) -> None:
    kalp_atisi(engine)


def sohbet_ac(c: TestClient) -> str:
    r = c.post("/assistant/conversations", json={"baslik": None})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def sor(c: TestClient, sohbet: str, **govde: Any) -> httpx.Response:
    govde.setdefault("soru", "Bu buton neden gri?")
    return c.post(f"/assistant/conversations/{sohbet}/messages", json=govde)


def mesaj_bitir(engine: Engine, mesaj_id: str, *, durum: str = "done", amac: str | None) -> None:
    """Worker'ın yaptığını taklit eder: mesajı bitirir, işini kapatır."""
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE asistan_mesaj SET durum = :d, amac = :a, kaynak = 'model', "
                "tamamlanma = now() WHERE id = :m"
            ),
            {"d": durum, "a": amac, "m": mesaj_id},
        )
        c.execute(
            text(
                "UPDATE job SET durum = 'done', bitis = now() WHERE id = "
                "(SELECT job_id FROM asistan_mesaj WHERE id = :m)"
            ),
            {"m": mesaj_id},
        )


def tek(engine: Engine, sql: str, **p: Any) -> Any:
    with engine.connect() as c:
        return c.execute(text(sql), p).scalar_one()


def soru_sor_ve_bitir(
    c: TestClient, engine: Engine, sohbet: str, amac: str | None = "assistant"
) -> str:
    r = sor(c, sohbet)
    assert r.status_code == 202, r.text
    mid = r.json()["mesaj_id"]
    mesaj_bitir(engine, mid, amac=amac)
    return mid


def ai_call_ekle(
    engine: Engine,
    *,
    maliyet: str,
    kullanici_id: uuid.UUID | None = None,
    amac: str = "assistant",
    call_id: uuid.UUID | None = None,
    parent: uuid.UUID | None = None,
) -> uuid.UUID:
    cid = call_id or uuid.uuid4()
    ek = {"kanal": "asistan", "kullanici_id": str(kullanici_id)} if kullanici_id else None
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO ai_call (id, parent_call_id, amac, saglayici, model, mod, "
                "maliyet, ek) "
                "VALUES (:id, :p, :a, 'anthropic', 'claude-haiku-5-5', 'live', :m, "
                "CAST(:ek AS jsonb))"
            ),
            {"id": cid, "p": parent, "a": amac, "m": Decimal(maliyet), "ek": json.dumps(ek)},
        )
    return cid


# ------------------------------------------------------------------ durum


def test_status_kalp_atisi_yoksa_worker_yok(client: TestClient, make_user) -> None:
    giris(client, make_user("analyst"))
    d = client.get("/assistant/status").json()
    assert d["etkin"] is False and d["neden"] == "worker_yok"
    assert d["mod"] == "off" and d["kalan_soru"] == budget.SAATLIK_SORU


def test_status_alanlari_ve_eski_kalp_atisi(client: TestClient, make_user, engine) -> None:
    giris(client, make_user("tester"))
    kalp_atisi(engine, mod="live", model_hazir=True)
    d = client.get("/assistant/status").json()
    assert d["etkin"] is True and d["neden"] is None
    assert d["mod"] == "live" and d["model_hazir"] is True
    assert d["paket_commit"] == "abc123"
    assert d["varsayilan_model"] == "claude-haiku-5-5"
    assert d["degerlendirme"]["paket"] == "assistant"
    assert "hata" not in d["degerlendirme"]
    kalp_atisi(engine, yas_s=121, mod="live", model_hazir=True)
    d = client.get("/assistant/status").json()
    assert d["etkin"] is False and d["neden"] == "worker_yok" and d["model_hazir"] is False


def test_status_musteri_verisi_maskeleme_kapali(client: TestClient, make_user, engine) -> None:
    giris(client, make_user("po"))
    kalp_atisi(engine, musteri_verisi=True, maskeleme=False)
    assert client.get("/assistant/status").json()["neden"] == "maskeleme_kapali"
    kalp_atisi(engine, musteri_verisi=True, maskeleme=True)
    assert client.get("/assistant/status").json()["etkin"] is True


def test_post_kalp_atisi_yok_503(client: TestClient, make_user) -> None:
    giris(client, make_user("engineer"))
    s = sohbet_ac(client)
    r = sor(client, s)
    assert r.status_code == 503
    assert r.json() == {
        "detail": asistan_api.KAPALI_METINLERI["worker_yok"],
        "kod": "asistan_kapali",
        "neden": "worker_yok",
    }


def test_post_maskeleme_kapali_503(client: TestClient, make_user, engine) -> None:
    giris(client, make_user("engineer"))
    kalp_atisi(engine, musteri_verisi=True, maskeleme=False)
    r = sor(client, sohbet_ac(client))
    assert r.status_code == 503 and r.json()["neden"] == "maskeleme_kapali"


# ------------------------------------------------------------------ sohbetler ve soru (5 rol)


@pytest.mark.parametrize("rol", ROLLER)
def test_soru_akisi_ve_is_yuku(rol: str, client: TestClient, make_user, engine, canli) -> None:
    u = make_user(rol)
    giris(client, u)
    s = sohbet_ac(client)
    r = sor(client, s, baglam={"rota": f"/gereksinimler/{uuid.uuid4()}/caseler", "rol": "po"})
    assert r.status_code == 202, r.text
    mid = r.json()["mesaj_id"]

    mesajlar = client.get(f"/assistant/conversations/{s}/messages").json()
    assert [(m["sira"], m["rol"], m["durum"]) for m in mesajlar] == [
        (1, "user", "done"),
        (2, "assistant", "pending"),
    ]
    assert mesajlar[1]["id"] == mid and mesajlar[0]["icerik"] == "Bu buton neden gri?"
    assert "job_id" not in mesajlar[1] and "ai_call_id" not in mesajlar[1]

    with engine.connect() as c:
        yuk, tur, key, md = c.execute(
            text(
                "SELECT yuk, tur, idempotency_key, max_deneme FROM job WHERE id = "
                "(SELECT job_id FROM asistan_mesaj WHERE id = :m)"
            ),
            {"m": mid},
        ).one()
        baglam = c.execute(
            text("SELECT baglam FROM asistan_mesaj WHERE id = :m"), {"m": mid}
        ).scalar_one()
    assert tur == "assistant.answer" and key == f"assistant.answer:{mid}" and md == 1
    assert yuk == {"mesaj_id": mid, "kullanici_id": str(u.id), "tetik": "kullanici"}
    # Rol oturumdan: bağlamdaki `rol` atılır; rota kalıba indirgenir, ekran adı kural dosyasından.
    assert baglam == {"rota_kalibi": "/gereksinimler/:id/caseler", "ekran": "Case inceleme"}

    assert client.get(f"/assistant/messages/{mid}").json()["durum"] == "pending"
    liste = client.get("/assistant/conversations").json()
    assert liste[0]["id"] == s and liste[0]["baslik"] == "Bu buton neden gri?"


@pytest.mark.parametrize("rol", ROLLER)
def test_sahiplik_her_uc_404(rol: str, client: TestClient, make_user, engine, canli) -> None:
    sahip, diger = make_user(rol), make_user(rol)
    giris(client, sahip)
    s = sohbet_ac(client)
    ust = soru_sor_ve_bitir(client, engine, s)

    giris(client, diger)
    benim = sohbet_ac(client)
    kontroller = [
        client.get(f"/assistant/conversations/{s}/messages"),
        sor(client, s),
        client.delete(f"/assistant/conversations/{s}"),
        client.get(f"/assistant/messages/{ust}"),
        client.post(f"/assistant/messages/{ust}/cancel"),
        client.post(f"/assistant/messages/{ust}/feedback", json={"deger": 1}),
        sor(client, benim, ust_mesaj_id=ust),
    ]
    for r in kontroller:
        assert r.status_code == 404, r.text
        assert r.json()["kod"] == "bulunamadi"
    assert all(x["id"] != s for x in client.get("/assistant/conversations").json())


def test_silinmis_sohbet_404(client: TestClient, make_user, engine, canli) -> None:
    giris(client, make_user("analyst"))
    s = sohbet_ac(client)
    mid = soru_sor_ve_bitir(client, engine, s)
    assert client.delete(f"/assistant/conversations/{s}").status_code == 204
    assert client.get(f"/assistant/conversations/{s}/messages").status_code == 404
    assert sor(client, s).status_code == 404
    assert client.get(f"/assistant/messages/{mid}").status_code == 404
    assert client.delete(f"/assistant/conversations/{s}").status_code == 404
    assert client.get("/assistant/conversations").json() == []
    assert tek(engine, "SELECT silindi FROM asistan_sohbet WHERE id = :s", s=s) is True


def test_sohbet_silinince_acik_cevaplar_iptal(client: TestClient, make_user, engine, canli) -> None:
    """Silinen sohbetin bekleyen cevabı iptal edilir, işi kuyruktan düşer: kullanıcı başka
    sohbette hemen soru sorabilir. Koşan cevap da iptal olur (geçit sonraki turda durur)."""
    giris(client, make_user("tester"))
    s = sohbet_ac(client)
    mid = sor(client, s).json()["mesaj_id"]
    assert client.delete(f"/assistant/conversations/{s}").status_code == 204
    assert tek(engine, "SELECT durum FROM asistan_mesaj WHERE id = :m", m=mid) == "iptal"
    durum = tek(
        engine,
        "SELECT j.durum FROM job j JOIN asistan_mesaj m ON m.job_id = j.id WHERE m.id = :m",
        m=mid,
    )
    assert durum == "cancelled"
    olay = (
        tek(
            engine,
            "SELECT count(*) FROM outbox WHERE tur = 'assistant.answered' "
            "AND veri->>'mesaj_id' = :m AND veri->>'durum' = 'iptal'",
            m=mid,
        )
        if _outbox_var(engine)
        else 1
    )
    assert olay == 1
    s2 = sohbet_ac(client)
    mid2 = sor(client, s2).json()["mesaj_id"]  # 409 bekleyen_var değil
    with engine.begin() as c:  # worker işi aldı
        c.execute(text("UPDATE asistan_mesaj SET durum = 'running' WHERE id = :m"), {"m": mid2})
    assert client.delete(f"/assistant/conversations/{s2}").status_code == 204
    assert tek(engine, "SELECT durum FROM asistan_mesaj WHERE id = :m", m=mid2) == "iptal"


def _outbox_var(engine: Engine) -> bool:
    return bool(tek(engine, "SELECT to_regclass('public.outbox') IS NOT NULL"))


def test_sohbet_olusturma_hiz_siniri(client: TestClient, make_user) -> None:
    giris(client, make_user("analyst"))
    for i in range(30):
        assert client.post("/assistant/conversations", json={}).status_code == 201, i
    r = client.post("/assistant/conversations", json={})
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"
    giris(client, make_user("analyst"))  # kullanıcı başı kova
    assert client.post("/assistant/conversations", json={}).status_code == 201


def test_ortak_conftest_canli_anahtari_siler() -> None:
    import os

    assert "ANTHROPIC_API_KEY" not in os.environ


# ------------------------------------------------------------------ doğrulama


def test_boyut_ve_bos_soru_422(client: TestClient, make_user, canli) -> None:
    giris(client, make_user("tester"))
    s = sohbet_ac(client)
    assert sor(client, s, soru="a" * 2001).status_code == 422
    assert sor(client, s, soru="a" * 2000).status_code == 202
    s2 = sohbet_ac(client)
    r = sor(client, s2, soru="ne?", baglam={"ekran": "x", "secili_eleman": {"ipucu": "y" * 301}})
    assert r.status_code == 422  # ipucu sınırı
    buyuk = {"ekran": "E", "son_hata": {"detail": "ç" * 600, "gorunen_metin": "ğ" * 600}}
    r = sor(client, s2, soru="ne?", baglam=buyuk)
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_istek"
    assert sor(client, s2, soru="   ").json()["kod"] == "gecersiz_istek"
    assert sor(client, s2, baglam={"bilinmeyen": 1}).status_code == 422


def test_sirli_soru_ve_baglam_422_deger_yanitta_yok(client: TestClient, make_user, canli) -> None:
    giris(client, make_user("engineer"))
    s = sohbet_ac(client)
    sahte = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
    r = sor(client, s, soru=f"token bu mu {sahte}?")
    assert r.status_code == 422 and r.json()["kod"] == "sir_icerik"
    assert sahte not in r.text
    r = sor(client, s, soru="bu ne?", baglam={"secili_eleman": {"ad": f"x {sahte}"}})
    assert r.status_code == 422 and r.json()["kod"] == "sir_icerik"
    assert sahte not in r.text
    assert tek(engine_of(client), "SELECT count(*) FROM asistan_mesaj") == 0


def engine_of(_c: TestClient) -> Engine:
    from tp_core import db as tp_db

    return tp_db.get_engine()


def test_calisma_ani_sir_degeri_de_yakalanir(
    client: TestClient, make_user, canli, monkeypatch
) -> None:
    deger = "calisma-ani-" + uuid.uuid4().hex
    monkeypatch.setenv("JIRA_READ_TOKEN", deger)
    giris(client, make_user("analyst"))
    r = sor(client, sohbet_ac(client), soru=f"şu değer ne: {deger}")
    assert r.status_code == 422 and r.json()["kod"] == "sir_icerik" and deger not in r.text


def test_feedback_dogrulama(client: TestClient, make_user, engine, canli) -> None:
    giris(client, make_user("presenter"))
    s = sohbet_ac(client)
    mid = soru_sor_ve_bitir(client, engine, s)
    assert client.post(f"/assistant/messages/{mid}/feedback", json={"deger": 0}).status_code == 422
    r = client.post(f"/assistant/messages/{mid}/feedback", json={"deger": -1})
    assert r.status_code == 200 and r.json()["geri_bildirim"] == -1
    assert client.get(f"/assistant/messages/{mid}").json()["geri_bildirim"] == -1
    soru_id = client.get(f"/assistant/conversations/{s}/messages").json()[0]["id"]
    assert (
        client.post(f"/assistant/messages/{soru_id}/feedback", json={"deger": 1}).status_code == 422
    )


def test_origin_evil_403_ve_bearer_401(client: TestClient, make_user, canli) -> None:
    u = make_user("analyst")
    giris(client, u)
    s = sohbet_ac(client)
    r = client.post("/assistant/conversations", headers={"Origin": "http://evil"})
    assert r.status_code == 403 and r.json()["kod"] == "kaynak_reddi"

    ham = "tp" + "t_" + uuid.uuid4().hex  # yalnız çerez kabul edilir; bearer biçimi önemsiz
    m = str(uuid.uuid4())
    uclar = [
        ("GET", "/assistant/status"),
        ("GET", "/assistant/conversations"),
        ("POST", "/assistant/conversations"),
        ("DELETE", f"/assistant/conversations/{s}"),
        ("GET", f"/assistant/conversations/{s}/messages"),
        ("POST", f"/assistant/conversations/{s}/messages"),
        ("GET", f"/assistant/messages/{m}"),
        ("POST", f"/assistant/messages/{m}/cancel"),
        ("POST", f"/assistant/messages/{m}/feedback"),
        ("GET", "/assistant/suggestions"),
        ("POST", "/assistant/suggestions/gereksinim-po-bekliyor/feedback"),
    ]
    assert len(uclar) == 11
    client.cookies.clear()
    for yontem, yol in uclar:
        r = client.request(yontem, yol, headers={"Authorization": f"Bearer {ham}"}, json={})
        assert r.status_code == 401, (yontem, yol, r.status_code)
        assert r.json()["kod"] == "yetkisiz"


# ------------------------------------------------------------------ "Daha ayrıntılı incele"


@pytest.mark.parametrize("rol", ROLLER)
def test_ust_mesaj_kurallari(rol: str, client: TestClient, make_user, engine, canli) -> None:
    giris(client, make_user(rol))
    s = sohbet_ac(client)
    ust = soru_sor_ve_bitir(client, engine, s)
    soru_mesaji = client.get(f"/assistant/conversations/{s}/messages").json()[0]["id"]

    # rol='user' → 422
    r = sor(client, s, ust_mesaj_id=soru_mesaji)
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_istek"
    # başka sohbetteki üst → 404
    baska = sohbet_ac(client)
    assert sor(client, baska, ust_mesaj_id=ust).status_code == 404

    # istemcinin sorusu yok sayılır; soru ve amaç üstten türetilir
    r = sor(client, s, ust_mesaj_id=ust, soru="BAŞKA SORU")
    assert r.status_code == 202, r.text
    cocuk = client.get(f"/assistant/messages/{r.json()['mesaj_id']}").json()
    assert cocuk["ust_mesaj_id"] == ust and cocuk["amac"] == "assistant_deep"
    assert cocuk["icerik"] == "Bu buton neden gri?" and cocuk["tetik"] == "kullanici"
    assert len(client.get(f"/assistant/conversations/{s}/messages").json()) == 3

    # durum≠done (çocuk pending) ve amac='assistant_deep' → 422
    r = sor(client, s, ust_mesaj_id=cocuk["id"])
    assert r.status_code == 422
    mesaj_bitir(engine, cocuk["id"], amac="assistant_deep")
    r = sor(client, s, ust_mesaj_id=cocuk["id"])
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_istek"
    # ikinci kez → 409 zaten_derin
    r = sor(client, s, ust_mesaj_id=ust)
    assert r.status_code == 409 and r.json()["kod"] == "zaten_derin"


def test_oneri_kipindeki_cevabin_derini_kipi_devralir(
    client: TestClient, make_user, engine, canli
) -> None:
    giris(client, make_user("tester"))
    s = sohbet_ac(client)
    r = client.post(f"/assistant/conversations/{s}/messages", json={"kip": "oneri"})
    ust = r.json()["mesaj_id"]
    mesaj_bitir(engine, ust, amac="assistant")
    r = sor(client, s, ust_mesaj_id=ust)
    assert r.status_code == 202, r.text
    cocuk = client.get(f"/assistant/messages/{r.json()['mesaj_id']}").json()
    assert cocuk["kip"] == "oneri" and cocuk["icerik"] == "Bu ekranda başka ne yapabilirim?"


def test_amac_null_ust_kabul_ve_assistant_amaci(
    client: TestClient, make_user, engine, canli
) -> None:
    giris(client, make_user("analyst"))
    s = sohbet_ac(client)
    ust = soru_sor_ve_bitir(client, engine, s, amac=None)  # sözlük/şablon cevabı
    r = sor(client, s, ust_mesaj_id=ust)
    assert r.status_code == 202, r.text
    assert client.get(f"/assistant/messages/{r.json()['mesaj_id']}").json()["amac"] == "assistant"


def test_zaten_derin_tekil_kisittan_eslenir(
    client: TestClient, make_user, engine, canli, monkeypatch
) -> None:
    """Ön kontrolü atlatan yarışta da `unique(ust_mesaj_id)` → 409 `zaten_derin`."""
    u = make_user("engineer")
    giris(client, u)
    s = sohbet_ac(client)
    ust = soru_sor_ve_bitir(client, engine, s)
    with engine.begin() as c:  # otomatik çocuk (iş yok → sayaç boş)
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, ust_mesaj_id, "
                "durum, amac, tetik) VALUES (:s, :k, 3, 'assistant', :u, 'done', "
                "'assistant_deep', 'otomatik')"
            ),
            {"s": s, "k": u.id, "u": ust},
        )
    gercek = asistan_api.text

    def kontrolsuz(sql: str, *a: Any, **k: Any):
        if sql.startswith("SELECT 1 FROM asistan_mesaj WHERE ust_mesaj_id"):
            return gercek("SELECT 1 WHERE false AND :u IS NULL")
        return gercek(sql, *a, **k)

    monkeypatch.setattr(asistan_api, "text", kontrolsuz)
    r = sor(client, s, ust_mesaj_id=ust)
    assert r.status_code == 409 and r.json()["kod"] == "zaten_derin"


# ------------------------------------------------------------------ sayaçlar


def test_kullanici_basi_tek_bekleyen(client: TestClient, make_user, engine, canli) -> None:
    giris(client, make_user("tester"))
    s = sohbet_ac(client)
    assert sor(client, s).status_code == 202
    r = sor(client, s)
    assert r.status_code == 409 and r.json()["kod"] == "bekleyen_var"
    assert "kapanıyor" not in r.json()["detail"]
    # başka sohbetten de aynı
    assert sor(client, sohbet_ac(client)).json()["kod"] == "bekleyen_var"


def test_iptal_edilip_suren_is_sayimda_kalir(client: TestClient, make_user, engine, canli) -> None:
    giris(client, make_user("analyst"))
    s = sohbet_ac(client)
    mid = sor(client, s).json()["mesaj_id"]
    with engine.begin() as c:  # worker işi aldı
        c.execute(text("UPDATE asistan_mesaj SET durum = 'running' WHERE id = :m"), {"m": mid})
        c.execute(
            text(
                "UPDATE job SET durum = 'running' WHERE id = "
                "(SELECT job_id FROM asistan_mesaj WHERE id = :m)"
            ),
            {"m": mid},
        )
    r = client.post(f"/assistant/messages/{mid}/cancel")
    assert r.status_code == 200 and r.json()["durum"] == "iptal"
    # kısmi tekil indeks boşaldı ama iş sürüyor → yine 409; metin "kapanıyor" der
    r = sor(client, s)
    assert r.status_code == 409 and r.json()["kod"] == "bekleyen_var"
    assert "kapanıyor" in r.json()["detail"]
    with engine.begin() as c:
        c.execute(text("UPDATE job SET durum = 'done' WHERE durum = 'running'"))
    assert sor(client, s).status_code == 202


def test_pending_iptal_isi_kuyruktan_dusurur(client: TestClient, make_user, engine, canli) -> None:
    giris(client, make_user("po"))
    s = sohbet_ac(client)
    mid = sor(client, s).json()["mesaj_id"]
    assert client.post(f"/assistant/messages/{mid}/cancel").json()["durum"] == "iptal"
    durum = tek(
        engine,
        "SELECT j.durum FROM job j JOIN asistan_mesaj m ON m.job_id = j.id WHERE m.id = :m",
        m=mid,
    )
    assert durum == "cancelled"
    # idempotent; bitmiş mesaj iptal edilemez
    assert client.post(f"/assistant/messages/{mid}/cancel").status_code == 200
    mid2 = sor(client, s).json()["mesaj_id"]
    mesaj_bitir(engine, mid2, amac="assistant")
    r = client.post(f"/assistant/messages/{mid2}/cancel")
    assert r.status_code == 409 and r.json()["kod"] == "cakisma"


def test_global_sinir_6_sonra_mesgul(client: TestClient, make_user, engine, canli) -> None:
    assert budget.global_sinir() == 6
    for i in range(6):
        giris(client, make_user("tester", ad=f"g{i}_{uuid.uuid4().hex[:4]}"))
        assert sor(client, sohbet_ac(client)).status_code == 202
    giris(client, make_user("tester"))
    r = sor(client, sohbet_ac(client))
    assert r.status_code == 429 and r.json()["kod"] == "mesgul"


def test_global_sinir_paralel_ortamdan(client: TestClient, make_user, canli, monkeypatch) -> None:
    monkeypatch.setenv("TP_WORKER_ASISTAN_PARALEL", "1")
    for _ in range(2):
        giris(client, make_user("engineer"))
        assert sor(client, sohbet_ac(client)).status_code == 202
    giris(client, make_user("engineer"))
    assert sor(client, sohbet_ac(client)).json()["kod"] == "mesgul"


def test_saatlik_sinir_iptal_ve_hata_dahil_derin_iki(
    client: TestClient, make_user, engine, canli
) -> None:
    u = make_user("presenter")
    giris(client, u)
    s = sohbet_ac(client)
    ust = soru_sor_ve_bitir(client, engine, s)  # 1
    with engine.begin() as c:  # 27 geçmiş mesaj: iptal, hata ve otomatik çocuk karışık
        for i in range(27):
            c.execute(
                text(
                    "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, durum) "
                    "VALUES (:s, :k, :n, 'assistant', :d)"
                ),
                {"s": s, "k": u.id, "n": 100 + i, "d": "iptal" if i % 2 else "error"},
            )
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, durum, "
                "ust_mesaj_id, amac, tetik) VALUES (:s, :k, 200, 'assistant', 'done', :u, "
                "'assistant_deep', 'otomatik')"
            ),
            {"s": s, "k": u.id, "u": ust},
        )
    assert client.get("/assistant/status").json()["kalan_soru"] == 2  # otomatik sayılmaz
    # derin ama üstün otomatik çocuğu var → ayrı bir üst gerekir; 2 hakla derin (2) sığar
    ust2 = soru_sor_ve_bitir(client, engine, s)  # 29
    r = sor(client, s, ust_mesaj_id=ust2)
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"  # 29 + 2 > 30
    mid = sor(client, s).json()["mesaj_id"]  # 30
    mesaj_bitir(engine, mid, amac="assistant")
    r = sor(client, s)
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"
    assert client.get("/assistant/status").json()["kalan_soru"] == 0


# ------------------------------------------------------------------ bütçe


def test_butce_tam_sinirda_402(client: TestClient, make_user, engine, canli) -> None:
    u = make_user("analyst")
    giris(client, u)
    s = sohbet_ac(client)
    ai_call_ekle(engine, maliyet="0.999999", kullanici_id=u.id)
    assert sor(client, s).status_code == 202
    s2 = sohbet_ac(client)
    with engine.begin() as c:
        c.execute(text("UPDATE job SET durum = 'done'"))
    ai_call_ekle(engine, maliyet="0.000001", kullanici_id=u.id)  # tam $1.00
    r = sor(client, s2)
    assert r.status_code == 402 and r.json()["kod"] == "butce_asildi"
    assert r.json()["detail"] == budget.BUTCE_METINLERI["kullanici"]


def test_asistan_gunluk_ve_kok_soru_butcesi(client: TestClient, make_user, engine, canli) -> None:
    u = make_user("engineer")
    giris(client, u)
    s = sohbet_ac(client)
    ust = soru_sor_ve_bitir(client, engine, s)
    kok_call = ai_call_ekle(engine, maliyet="0.30", kullanici_id=u.id)
    ai_call_ekle(engine, maliyet="0.20", kullanici_id=u.id, parent=kok_call)  # tur
    with engine.begin() as c:
        c.execute(
            text("UPDATE asistan_mesaj SET ai_call_id = :c WHERE id = :m"),
            {"c": kok_call, "m": ust},
        )
    r = sor(client, s, ust_mesaj_id=ust)
    assert r.status_code == 402 and r.json()["detail"] == budget.BUTCE_METINLERI["soru"]
    # başka soru serbest; ama asistan günlük tavanı (başka kullanıcının harcamasıyla) dolunca 402
    assert sor(client, sohbet_ac(client)).status_code == 202
    with engine.begin() as c:
        c.execute(text("UPDATE job SET durum = 'done'"))
    ai_call_ekle(engine, maliyet="9.50", amac="assistant_deep")
    r = sor(client, sohbet_ac(client))
    assert r.status_code == 402 and r.json()["detail"] == budget.BUTCE_METINLERI["asistan"]


# ------------------------------------------------------------------ öneri bağlamı


def test_oneri_kural_id_gecersiz_409_gecerli_sohbete_yazilir(
    client: TestClient, make_user, engine, canli, monkeypatch
) -> None:
    cagrilar: list[tuple[str, Any]] = []

    def sahte(_session, kullanici, kural_id, baglam) -> bool:
        cagrilar.append((kural_id, baglam))
        return kural_id == "gereksinim-po-bekliyor"

    monkeypatch.setattr(asistan_api, "oneri_gecerli_mi", sahte)
    giris(client, make_user("analyst"))
    s = sohbet_ac(client)
    r = sor(client, s, oneri_kural_id="eski-kural")
    assert r.status_code == 409 and r.json()["kod"] == "oneri_gecersiz"
    r = sor(
        client,
        s,
        soru="Bu öneriyi neden yapmalıyım?",
        oneri_kural_id="gereksinim-po-bekliyor",
        baglam={"rota_kalibi": "/gereksinimler/:id", "oneri": {"baslik": "SAHTE"}},
    )
    assert r.status_code == 202, r.text
    assert tek(engine, "SELECT oneri_kural_id FROM asistan_sohbet WHERE id = :s", s=s) == (
        "gereksinim-po-bekliyor"
    )
    baglam = tek(engine, "SELECT baglam FROM asistan_mesaj WHERE id = :m", m=r.json()["mesaj_id"])
    # istemcinin `oneri` metni atılır; sunucu yalnız kural kimliğini yazar
    assert baglam["oneri"] == {"kural_id": "gereksinim-po-bekliyor"}
    assert cagrilar[-1][1]["rota_kalibi"] == "/gereksinimler/:id"
    assert sor(client, s, oneri_kural_id="Gecersiz Biçim").status_code == 422


def test_oneri_kapaliysa_kural_id_gecersiz(client, make_user, canli, monkeypatch) -> None:
    monkeypatch.setattr(asistan_api, "oneri_gecerli_mi", lambda *a: True)
    monkeypatch.setenv("TP_ASISTAN_ONERI", "0")
    giris(client, make_user("po"))
    r = sor(client, sohbet_ac(client), oneri_kural_id="gereksinim-po-bekliyor")
    assert r.status_code == 409 and r.json()["kod"] == "oneri_gecersiz"


@pytest.mark.parametrize("deger", ["0", "false", "off"])
def test_oneri_kapaliysa_oneri_kipi_reddedilir(
    client, make_user, engine, canli, monkeypatch, deger
) -> None:
    """Geri alma bayrağı "Başka ne yapabilirim?" kipini de kapatır (§9); düz soru etkilenmez.
    Bayrak okumaları tek kaynaktan (`oneri.oneri_etkin`): "0" dışındaki kapalı değerler de."""
    giris(client, make_user("tester"))
    s = sohbet_ac(client)
    monkeypatch.setenv("TP_ASISTAN_ONERI", deger)
    r = client.post(f"/assistant/conversations/{s}/messages", json={"kip": "oneri"})
    assert r.status_code == 409 and r.json()["kod"] == "oneri_gecersiz"
    assert tek(engine, "SELECT count(*) FROM asistan_mesaj WHERE sohbet_id = :s", s=s) == 0
    assert sor(client, s).status_code == 202


def test_oneri_kapaliysa_oneri_kipi_cevabinin_derini_reddedilir(
    client, make_user, engine, canli, monkeypatch
) -> None:
    giris(client, make_user("tester"))
    s = sohbet_ac(client)
    mid = client.post(f"/assistant/conversations/{s}/messages", json={"kip": "oneri"}).json()[
        "mesaj_id"
    ]
    mesaj_bitir(engine, mid, amac="assistant")
    monkeypatch.setenv("TP_ASISTAN_ONERI", "0")
    r = sor(client, s, ust_mesaj_id=mid)
    assert r.status_code == 409 and r.json()["kod"] == "oneri_gecersiz"


def test_kip_oneri_bos_soru_sabit_metin(client: TestClient, make_user, engine, canli) -> None:
    giris(client, make_user("tester"))
    s = sohbet_ac(client)
    r = client.post(f"/assistant/conversations/{s}/messages", json={"kip": "oneri"})
    assert r.status_code == 202, r.text
    m = client.get(f"/assistant/messages/{r.json()['mesaj_id']}").json()
    assert m["kip"] == "oneri" and m["icerik"] == "Bu ekranda başka ne yapabilirim?"


# ------------------------------------------------------------------ eşzamanlılık (gerçek sunucu)


def _giris_istemcisi(sunucu: str, u: Principal) -> httpx.Client:
    c = httpx.Client(base_url=sunucu, timeout=20)
    r = c.post("/auth/login", json={"kullanici_adi": u.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 200, r.text
    return c


def _ayni_anda(isler: list) -> list[httpx.Response]:
    engel = threading.Barrier(len(isler))
    sonuc: list[httpx.Response | None] = [None] * len(isler)

    def kos(i: int) -> None:
        engel.wait()
        sonuc[i] = isler[i]()

    tlar = [threading.Thread(target=kos, args=(i,)) for i in range(len(isler))]
    for t in tlar:
        t.start()
    for t in tlar:
        t.join(30)
    assert all(r is not None for r in sonuc)
    return sonuc  # type: ignore[return-value]


def test_eszamanli_iki_post_biri_202_biri_409(sunucu: str, make_user, engine) -> None:
    from tp_core.auth.login import THROTTLE

    THROTTLE._kayit.clear()
    kalp_atisi(engine)
    u = make_user("analyst")
    c1, c2 = _giris_istemcisi(sunucu, u), _giris_istemcisi(sunucu, u)
    try:
        s1 = c1.post("/assistant/conversations", json={}).json()["id"]
        s2 = c2.post("/assistant/conversations", json={}).json()["id"]
        yanitlar = _ayni_anda(
            [
                lambda: c1.post(f"/assistant/conversations/{s1}/messages", json={"soru": "a"}),
                lambda: c2.post(f"/assistant/conversations/{s2}/messages", json={"soru": "b"}),
            ]
        )
    finally:
        c1.close()
        c2.close()
    kodlar = sorted(r.status_code for r in yanitlar)
    assert kodlar == [202, 409], [r.text for r in yanitlar]
    assert next(r for r in yanitlar if r.status_code == 409).json()["kod"] == "bekleyen_var"
    assert tek(engine, "SELECT count(*) FROM job WHERE tur = 'assistant.answer'") == 1


def test_eszamanli_global_7_kullanici_biri_mesgul(sunucu: str, make_user, engine) -> None:
    from tp_core.auth.login import THROTTLE

    THROTTLE._kayit.clear()
    kalp_atisi(engine)
    istemciler = []
    sohbetler = []
    for _ in range(7):
        c = _giris_istemcisi(sunucu, make_user("tester"))
        istemciler.append(c)
        sohbetler.append(c.post("/assistant/conversations", json={}).json()["id"])
    try:
        yanitlar = _ayni_anda(
            [
                (
                    lambda c=c, s=s: c.post(
                        f"/assistant/conversations/{s}/messages", json={"soru": "x"}
                    )
                )
                for c, s in zip(istemciler, sohbetler, strict=True)
            ]
        )
    finally:
        for c in istemciler:
            c.close()
    kodlar = sorted(r.status_code for r in yanitlar)
    assert kodlar == [202] * 6 + [429], [r.text for r in yanitlar]
    assert next(r for r in yanitlar if r.status_code == 429).json()["kod"] == "mesgul"


# ------------------------------------------------------------------ ortam (İlke II)


def _compose() -> dict[str, Any]:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))


def _ortam(servis: dict[str, Any]) -> dict[str, Any]:
    env = servis.get("environment") or {}
    return dict(env) if isinstance(env, dict) else {}


def test_core_api_ortaminda_model_anahtari_ve_kipi_yok() -> None:
    if not (REPO / "docker-compose.yml").is_file():
        pytest.skip("docker-compose.yml yok (imaj içi koşu)")
    servisler = _compose()["services"]
    api_env = _ortam(servisler["core-api"])
    for yasak in ("ANTHROPIC_API_KEY", "TP_ASISTAN_MODEL_MODE", "GITHUB_ACTIONS_READ_TOKEN"):
        assert yasak not in api_env, yasak
    worker_env = _ortam(servisler["core-worker"])
    for ad in (
        "ANTHROPIC_API_KEY",
        "TP_ASISTAN_MODEL_MODE",
        "TP_ASISTAN_OTOMATIK_DERIN",
        "TP_ASISTAN_MUSTERI_VERISI",
        "TP_ASISTAN_VERI_ROLLERI",
        "TP_WORKER_ASISTAN_SERIT",
        "TP_WORKER_ASISTAN_PARALEL",
        "TP_ASISTAN_ONERI",
        "TP_ASISTAN_SAKLAMA_GUN",
    ):
        assert ad in worker_env, ad
    assert worker_env["TP_ASISTAN_MODEL_MODE"] == "${TP_ASISTAN_MODEL_MODE:-off}"
    # core-api de paylaşılan (gizli olmayan) ayarları alır: global sayaç paralellikten türer.
    for ad in ("TP_WORKER_ASISTAN_PARALEL", "TP_ASISTAN_ONERI", "JIRA_CREATE_URL"):
        assert ad in api_env, ad


def test_env_example_asistan_satirlari_degersiz() -> None:
    yol = REPO / ".env.example"
    if not yol.is_file():
        pytest.skip(".env.example yok")
    satirlar = {
        s.split("=", 1)[0]: s.split("=", 1)[1]
        for s in yol.read_text(encoding="utf-8").splitlines()
        if s and not s.startswith("#") and "=" in s
    }
    for ad in (
        "TP_ASISTAN_MODEL_MODE",
        "TP_ASISTAN_ONERI",
        "TP_ASISTAN_OTOMATIK_DERIN",
        "TP_ASISTAN_MUSTERI_VERISI",
        "TP_ASISTAN_VERI_ROLLERI",
        "TP_ASISTAN_SAKLAMA_GUN",
        "TP_WORKER_ASISTAN_SERIT",
        "TP_WORKER_ASISTAN_PARALEL",
        "JIRA_CREATE_URL",
        "GITHUB_ACTIONS_READ_TOKEN",
    ):
        assert satirlar.get(ad) == "", ad
