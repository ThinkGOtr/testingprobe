import uuid

from tp_core.seed import GORUNEN_ADLAR, KULLANICILAR, NAMESPACE_TP, tp_uuid


def test_uuid_deterministik() -> None:
    assert tp_uuid("user", "analist") == tp_uuid("user", "analist")
    assert tp_uuid("user", "analist") == uuid.uuid5(NAMESPACE_TP, "user:analist")
    assert tp_uuid("user", "analist").version == 5


def test_namespace_sabit() -> None:
    # Değişirse tüm seed kimlikleri değişir; bilinçli olmadıkça dokunmayın.
    assert str(NAMESPACE_TP) == "6f1d2c3a-8b4e-5f60-9a7b-1c2d3e4f5a6b"


def test_seed_kullanicilari() -> None:
    assert dict(KULLANICILAR) == {
        "analist": "analyst",
        "muhendis": "engineer",
        "yonetici": "admin",
        "po": "po",
        "testci": "tester",
        "denetci": "auditor",
        "gelistirici": "developer",
        "izleyici": "viewer",
    }
    # Rol başına bir hesap (specs/012-rol-yetki §3).
    from tp_core.auth.yetki import ROLLER

    assert {rol for _, rol in KULLANICILAR} == ROLLER
    assert len({tp_uuid("user", ad) for ad, _ in KULLANICILAR}) == 8


def test_seed_gorunen_adlari() -> None:
    from tp_core.auth.display import configured_names, display_name, parse_names

    assert set(GORUNEN_ADLAR) == {ad for ad, _ in KULLANICILAR}
    adlar = configured_names("")
    beklenen = {
        "analist": "Cengizhan Gunaydin · Analist",
        "po": "Cengizhan Gunaydin · PO",
        "muhendis": "Gokhan Sipahi · Automation Engineer",
        "testci": "Fatih Arslan · Testçi",
        "yonetici": "Sistem Yöneticisi",
        "denetci": "Denetçi",
        "gelistirici": "Developer",
        "izleyici": "Görüntüleyici",
    }
    assert {ad: display_name(ad, rol, adlar) for ad, rol in KULLANICILAR} == beklenen
    # Geçersiz kılma: boş ad → yalnızca rol; bozuk parça atlanır; büyük/küçük harf duyarsız.
    assert parse_names("Analist=Ayşe Yılmaz, sunucu=Gokhan Sipahi,bozuk,=x") == {
        "analist": "Ayşe Yılmaz",
        "sunucu": "Gokhan Sipahi",
    }
    assert configured_names("muhendis=")["muhendis"] == ""
    assert (
        display_name("muhendis", "engineer", configured_names("muhendis=")) == "Automation Engineer"
    )
