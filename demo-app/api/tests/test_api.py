from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from demoapp_api import db
from demoapp_api.main import app
from demoapp_api.models import Ayar, Bayi

from .conftest import TEST_HEADERS, giris


# ------------------------------------------------------------------ health
def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "service": "demo-app-api",
        "status": "ok",
        "version": "0.2.0",
        "checks": {"db": "ok"},
    }


def test_health_degraded(client, monkeypatch):
    monkeypatch.setattr(db, "check_db", lambda: "error: connection refused")
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


def test_check_db_without_url_reports_error(monkeypatch):
    monkeypatch.delenv("DEMOAPP_DATABASE_URL", raising=False)
    db.clear_caches()
    assert db.check_db().startswith("error: ")


def test_uygulama_db_yokken_de_acilir(monkeypatch):
    monkeypatch.setenv("DEMOAPP_DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:1/yok")
    db.clear_caches()
    with TestClient(app) as c:
        assert c.get("/health").status_code == 503


# ------------------------------------------------------------------ auth
def test_giris_basarili_cerez_ve_me(client):
    resp = giris(client)
    assert resp.status_code == 200
    assert resp.json() == {"kullanici_adi": "bayi1", "ad": "Merkez Bayi"}
    cookie = resp.headers["set-cookie"]
    assert "bayi_oturum=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert client.get("/auth/me").json()["ad"] == "Merkez Bayi"


def test_giris_hatali_parola_ve_bilinmeyen_kullanici(client):
    for kullanici, parola in [("bayi1", "yanlis"), ("yok", "Demo123!")]:
        resp = giris(client, kullanici, parola)
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Kullanıcı adı veya parola hatalı"}


def test_oturumsuz_uclar_401(client):
    for method, path in [
        ("get", "/products"),
        ("get", "/cart"),
        ("post", "/orders"),
        ("get", "/orders"),
        ("get", "/auth/me"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path
    client.cookies.set("bayi_oturum", "uydurma")
    assert client.get("/cart").status_code == 401


def test_oturum_yoklamasi_oturumsuzken_200_null(client):
    """Sayfa açılışı yoklaması hata durum kodu dönmemeli (tarayıcı konsol hatası üretmesin)."""
    resp = client.get("/auth/session")
    assert resp.status_code == 200
    assert resp.json() == {"oturum": None}
    client.cookies.set("bayi_oturum", "uydurma")
    resp = client.get("/auth/session")
    assert resp.status_code == 200
    assert resp.json() == {"oturum": None}


def test_oturum_yoklamasi_oturumluyken_bayiyi_dondurur(bayi1):
    resp = bayi1.get("/auth/session")
    assert resp.status_code == 200
    assert resp.json() == {"oturum": bayi1.get("/auth/me").json()}
    assert bayi1.post("/auth/logout").status_code == 204
    assert bayi1.get("/auth/session").json() == {"oturum": None}


def test_cikis_oturumu_gecersiz_kilar(bayi1):
    token = bayi1.cookies.get("bayi_oturum")
    assert bayi1.post("/auth/logout").status_code == 204
    bayi1.cookies.set("bayi_oturum", token)
    assert bayi1.get("/auth/me").status_code == 401


# ------------------------------------------------------------------ katalog
def test_urunler_demo_verisiyle_ayni(bayi1):
    assert bayi1.get("/products").json() == [
        {"kod": "P-001", "ad": "Portakal Gazozu 1L", "fiyat": "25.00", "kampanya": "6 al 1 bedava"},
        {"kod": "P-002", "ad": "Limonata 330ml", "fiyat": "15.00", "kampanya": None},
        {"kod": "P-003", "ad": "Maden Suyu 200ml", "fiyat": "8.00", "kampanya": None},
        {"kod": "P-004", "ad": "Şeftalili Soğuk Çay 1L", "fiyat": "30.00", "kampanya": None},
    ]


# ------------------------------------------------------------------ sepet
def test_bos_sepet(bayi1):
    cart = bayi1.get("/cart").json()
    assert cart["satirlar"] == []
    assert cart["adet_toplam"] == 0
    assert cart["onaylanabilir"] is False
    assert cart["uyarilar"] == []
    assert cart["min_siparis_tutari"] == "750.00"


def test_sepete_ekleme_adetleri_toplar(bayi1):
    bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 3})
    cart = bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 4}).json()
    assert cart["adet_toplam"] == 7
    (line,) = cart["satirlar"]
    assert line["adet"] == 7
    assert line["bedava_adet"] == 1
    assert line["ucretli_adet"] == 6
    assert line["kampanya"] == "6 al 1 bedava"
    assert (cart["ara_toplam"], cart["indirim"], cart["toplam"]) == ("175.00", "25.00", "150.00")
    # Kampanyalı siparişte minimum tutar aranmaz.
    assert cart["min_siparis_saglandi"] is False
    assert cart["onaylanabilir"] is True
    assert cart["uyarilar"] == []


def test_kampanyasiz_sepette_min_tutar_uyarisi(bayi1):
    cart = bayi1.post("/cart/lines", json={"urun_kod": "P-002", "adet": 10}).json()
    assert cart["toplam"] == "150.00"
    assert cart["onaylanabilir"] is False
    assert cart["uyarilar"] == [{"kod": "min_siparis", "mesaj": "Minimum sipariş tutarı 750,00 TL"}]
    # Sepete kampanyalı ürün eklenince sipariş kampanyalı olur; minimum tutar aranmaz.
    cart = bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 1}).json()
    assert cart["onaylanabilir"] is True
    assert cart["uyarilar"] == []


def test_satirlar_katalog_sirasinda(bayi1):
    bayi1.post("/cart/lines", json={"urun_kod": "P-004", "adet": 1})
    cart = bayi1.post("/cart/lines", json={"urun_kod": "P-002", "adet": 1}).json()
    assert [x["urun_kod"] for x in cart["satirlar"]] == ["P-002", "P-004"]


def test_break_campaign_api(bayi1, monkeypatch):
    monkeypatch.setenv("BREAK_CAMPAIGN", "1")
    cart = bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 7}).json()
    assert cart["satirlar"][0]["bedava_adet"] == 0
    assert cart["indirim"] == "0.00"
    assert cart["toplam"] == "175.00"


def test_min_siparis_ayar_tablosundan_okunur(bayi1):
    with db.session_scope() as s:
        s.get(Ayar, "min_siparis_tutari").deger = "100.00"
    cart = bayi1.post("/cart/lines", json={"urun_kod": "P-002", "adet": 7}).json()
    assert cart["min_siparis_tutari"] == "100.00"
    assert cart["onaylanabilir"] is True


def test_gecersiz_sepet_istekleri(bayi1):
    assert bayi1.post("/cart/lines", json={"urun_kod": "P-999", "adet": 1}).status_code == 404
    assert bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 0}).status_code == 422
    assert bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 1000}).status_code == 422
    bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 999})
    assert bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 1}).status_code == 422
    assert bayi1.delete("/cart/lines/P-002").status_code == 404


def test_satir_guncelle_ve_sil(bayi1):
    bayi1.post("/cart/lines", json={"urun_kod": "P-002", "adet": 2})
    cart = bayi1.put("/cart/lines/P-002", json={"adet": 12}).json()
    assert cart["satirlar"][0]["adet"] == 12
    assert cart["satirlar"][0]["bedava_adet"] == 0  # kampanyasız ürün
    cart = bayi1.put("/cart/lines/P-002", json={"adet": 0}).json()
    assert cart["satirlar"] == []
    bayi1.post("/cart/lines", json={"urun_kod": "P-003", "adet": 1})
    assert bayi1.delete("/cart/lines/P-003").json()["satirlar"] == []
    bayi1.post("/cart/lines", json={"urun_kod": "P-003", "adet": 1})
    assert bayi1.delete("/cart").json()["adet_toplam"] == 0


def test_sepetler_bayiye_ozel(client):
    giris(client, "bayi1")
    client.post("/cart/lines", json={"urun_kod": "P-001", "adet": 2})
    client.cookies.clear()
    giris(client, "bayi2")
    assert client.get("/cart").json()["satirlar"] == []


# ------------------------------------------------------------------ sipariş
def test_min_altinda_siparis_reddedilir(bayi1):
    assert bayi1.post("/orders").json() == {"detail": "Sepetiniz boş"}
    bayi1.post("/cart/lines", json={"urun_kod": "P-002", "adet": 10})
    resp = bayi1.post("/orders")
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Minimum sipariş tutarı 750,00 TL"}
    assert bayi1.get("/orders").json() == []


def test_kampanyali_siparis_min_altinda_onaylanir(bayi1):
    bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 7})
    resp = bayi1.post("/orders")
    assert resp.status_code == 201
    assert resp.json()["toplam"] == "150.00"


def test_siparis_onayi_ve_gecmis(bayi1):
    bayi1.post("/cart/lines", json={"urun_kod": "P-004", "adet": 30})
    bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 7})
    resp = bayi1.post("/orders")
    assert resp.status_code == 201
    order = resp.json()
    assert order["numara"].startswith("SP-")
    assert (order["ara_toplam"], order["indirim"], order["toplam"]) == (
        "1075.00",
        "25.00",
        "1050.00",
    )
    assert order["adet_toplam"] == 37
    assert {x["urun_kod"]: x["bedava_adet"] for x in order["satirlar"]} == {
        "P-001": 1,
        "P-004": 0,
    }
    assert bayi1.get("/cart").json()["satirlar"] == []
    history = bayi1.get("/orders").json()
    assert [o["numara"] for o in history] == [order["numara"]]
    assert bayi1.get(f"/orders/{order['numara']}").json()["toplam"] == "1050.00"


def test_sepet_yalnizca_min_siparis_uyarisi_uretir(bayi1):
    bayi1.post("/cart/lines", json={"urun_kod": "P-004", "adet": 100})
    cart = bayi1.get("/cart").json()
    assert cart["toplam"] == "3000.00"
    assert cart["uyarilar"] == []
    assert bayi1.post("/orders").status_code == 201


def test_baska_bayinin_siparisi_gorunmez(client):
    giris(client, "bayi1")
    client.post("/cart/lines", json={"urun_kod": "P-004", "adet": 30})
    numara = client.post("/orders").json()["numara"]
    client.cookies.clear()
    giris(client, "bayi2")
    assert client.get(f"/orders/{numara}").status_code == 404
    assert client.get("/orders").json() == []


# ------------------------------------------------------------------ test/reset + tohum
def test_reset_yalnizca_test_modunda(client, monkeypatch):
    monkeypatch.delenv("DEMOAPP_TEST_MODE")
    assert client.post("/test/reset", headers=TEST_HEADERS).status_code == 404


def test_reset_token_tanimsizsa_kapali(client, monkeypatch):
    # compose'daki paylaşılan demo örneği: test modu açık ama token yok → uç yok sayılır.
    monkeypatch.delenv("DEMOAPP_TEST_TOKEN")
    assert client.post("/test/reset").status_code == 404
    assert client.post("/test/reset", headers=TEST_HEADERS).status_code == 404


def test_reset_tokensiz_ya_da_yanlis_tokenla_reddedilir(bayi1):
    bayi1.post("/cart/lines", json={"urun_kod": "P-002", "adet": 1})
    assert bayi1.post("/test/reset").status_code == 403
    assert bayi1.post("/test/reset", json={"kullanici_adi": "bayi1"}).status_code == 403
    yanlis = {"X-Demoapp-Test-Token": "yanlis"}
    assert bayi1.post("/test/reset", headers=yanlis).status_code == 403
    # Hiçbir şey silinmedi: oturum ve sepet yerinde.
    assert bayi1.get("/auth/me").status_code == 200
    assert len(bayi1.get("/cart").json()["satirlar"]) == 1


def test_reset_bayi_kapsamli(client):
    giris(client, "bayi2")
    client.post("/cart/lines", json={"urun_kod": "P-002", "adet": 1})
    client.cookies.clear()
    giris(client, "bayi1")
    client.post("/cart/lines", json={"urun_kod": "P-001", "adet": 1})
    resp = client.post("/test/reset", json={"kullanici_adi": "bayi1"}, headers=TEST_HEADERS)
    assert resp.json() == {"status": "ok", "kapsam": "bayi1"}
    assert client.get("/cart").json()["satirlar"] == []  # oturum korunur
    client.cookies.clear()
    giris(client, "bayi2")
    assert len(client.get("/cart").json()["satirlar"]) == 1
    assert (
        client.post("/test/reset", json={"kullanici_adi": "yok"}, headers=TEST_HEADERS).status_code
        == 404
    )


def test_tam_reset_tohumu_geri_yukler_ve_oturumlari_siler(bayi1):
    with db.session_scope() as s:
        s.get(Ayar, "min_siparis_tutari").deger = "1.00"
        s.add(Ayar(anahtar="fazla", deger="x"))
    assert bayi1.post("/test/reset", headers=TEST_HEADERS).json() == {
        "status": "ok",
        "kapsam": "tumu",
    }
    with db.session_scope() as s:
        assert s.get(Ayar, "min_siparis_tutari").deger == "750.00"
        assert s.get(Ayar, "fazla") is None
    assert bayi1.get("/auth/me").status_code == 401


def test_tohum_idempotent_ve_belgedeki_veri():
    db.init_db()
    db.init_db()
    with db.session_scope() as s:
        bayiler = {b.kullanici_adi: b for b in s.scalars(select(Bayi))}
    assert set(bayiler) == {"bayi1", "bayi2", "bayi3"}
    assert bayiler["bayi1"].ad == "Merkez Bayi"
    assert bayiler["bayi1"].kredi_limiti == Decimal("2000.00")
    assert bayiler["bayi2"].kredi_limiti == Decimal("500.00")
    assert bayiler["bayi3"].ad == "Doğrulama Bayi"
    assert bayiler["bayi3"].kredi_limiti == Decimal("2000.00")


def test_dogrulama_bayisi_giris_yapar_ve_bayi_kapsaminda_sifirlanir(client):
    """bayi3 (doğrulama ajanı) diğer bayilerden bağımsız sıfırlanır; tam sıfırlama onu kurar."""
    resp = giris(client, "bayi3")
    assert resp.status_code == 200
    assert resp.json() == {"kullanici_adi": "bayi3", "ad": "Doğrulama Bayi"}
    client.post("/cart/lines", json={"urun_kod": "P-001", "adet": 7})
    client.cookies.clear()
    giris(client, "bayi1")
    client.post("/cart/lines", json={"urun_kod": "P-002", "adet": 1})
    resp = client.post("/test/reset", json={"kullanici_adi": "bayi3"}, headers=TEST_HEADERS)
    assert resp.json() == {"status": "ok", "kapsam": "bayi3"}
    assert len(client.get("/cart").json()["satirlar"]) == 1  # bayi1'in sepeti yerinde
    client.cookies.clear()
    giris(client, "bayi3")
    assert client.get("/cart").json()["satirlar"] == []
    assert client.post("/auth/logout").status_code == 204
    with db.session_scope() as s:
        s.delete(s.scalar(select(Bayi).where(Bayi.kullanici_adi == "bayi3")))
    assert client.post("/test/reset", headers=TEST_HEADERS).json()["kapsam"] == "tumu"
    assert giris(client, "bayi3").status_code == 200


def test_grant_readonly_sqlite_atlar():
    with db.get_engine().begin() as conn:
        assert db.grant_readonly(conn) is False


# ------------------------------------------------------------------ test/break (bayi kapsamlı)
def _kir(c: TestClient, kullanici: str, kampanya: bool, headers=TEST_HEADERS):
    return c.post(
        "/test/break", json={"kullanici_adi": kullanici, "kampanya": kampanya}, headers=headers
    )


def _yedi_p001(c: TestClient) -> dict:
    c.delete("/cart")
    return c.post("/cart/lines", json={"urun_kod": "P-001", "adet": 7}).json()


def test_break_bayi_kapsamli_ac_kapa(client):
    giris(client, "bayi1")
    assert _yedi_p001(client)["indirim"] == "25.00"

    assert _kir(client, "bayi1", True).json() == {
        "kullanici_adi": "bayi1",
        "kampanya": True,
        "hata": "kampanya_bedava_yok",
    }
    bozuk = client.get("/cart").json()
    assert bozuk["satirlar"][0]["bedava_adet"] == 0
    assert (bozuk["indirim"], bozuk["toplam"]) == ("0.00", "175.00")

    # Diğer bayi etkilenmez (paylaşılan demo örneği ve MCP doğrulaması bozulmaz).
    client.cookies.clear()
    giris(client, "bayi2")
    assert _yedi_p001(client)["indirim"] == "25.00"

    client.cookies.clear()
    giris(client, "bayi1")
    assert _kir(client, "bayi1", False).json()["kampanya"] is False
    assert client.get("/cart").json()["indirim"] == "25.00"
    # Kapatma idempotent.
    assert _kir(client, "bayi1", False).status_code == 200


def test_break_siparise_de_yansir(bayi1):
    _kir(bayi1, "bayi1", True)
    bayi1.post("/cart/lines", json={"urun_kod": "P-001", "adet": 6})
    siparis = bayi1.post("/orders").json()
    assert (siparis["indirim"], siparis["toplam"]) == ("0.00", "150.00")
    assert siparis["satirlar"][0]["bedava_adet"] == 0


def test_break_reset_ile_kalkar(bayi1):
    _kir(bayi1, "bayi1", True)
    bayi1.post("/test/reset", json={"kullanici_adi": "bayi1"}, headers=TEST_HEADERS)
    assert _yedi_p001(bayi1)["indirim"] == "25.00"
    _kir(bayi1, "bayi1", True)
    bayi1.post("/test/reset", headers=TEST_HEADERS)  # tam reset oturumu da siler
    giris(bayi1)
    assert _yedi_p001(bayi1)["indirim"] == "25.00"


def test_break_yetki_ve_dogrulama(bayi1, monkeypatch):
    assert _kir(bayi1, "bayi1", True, headers={}).status_code == 403
    assert _kir(bayi1, "bayi1", True, headers={"X-Demoapp-Test-Token": "yanlis"}).status_code == 403
    assert _kir(bayi1, "yok", True).status_code == 404
    assert (
        bayi1.post("/test/break", json={"kullanici_adi": "bayi1"}, headers=TEST_HEADERS).status_code
        == 422
    )
    assert _yedi_p001(bayi1)["indirim"] == "25.00"  # reddedilen istekler hiçbir şey bozmadı
    monkeypatch.delenv("DEMOAPP_TEST_TOKEN")
    assert _kir(bayi1, "bayi1", True).status_code == 404


def test_break_test_modu_kapaninca_etkisiz(bayi1, monkeypatch):
    _kir(bayi1, "bayi1", True)
    monkeypatch.delenv("DEMOAPP_TEST_MODE")
    assert _yedi_p001(bayi1)["indirim"] == "25.00"


def test_oturum_kaydi_yanittan_once_commit_edilir() -> None:
    """Giriş yanıtı (çerez) tarayıcıya ulaştığında oturum satırı commit edilmiş olmalı.

    Varsayılan (`scope="request"`) yield bağımlılığı commit'i yanıt gönderildikten SONRA yapar;
    tarayıcı hemen ardından /cart isterse yük altında 401 alır (e2e'de gözlendi: giriş 200 →
    5 ms sonra /cart 401 → uygulama giriş sayfasına döner).
    """
    from demoapp_api import main

    dep = main.SessionDep.__metadata__[0]
    assert dep.dependency is main.db.get_session
    assert dep.scope == "function"
