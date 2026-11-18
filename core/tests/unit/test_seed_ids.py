import uuid

import pytest

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
        "sunucu": "admin",
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
        "po": "Cengizhan Gunaydin · Ürün Sahibi (PO)",
        "muhendis": "Gokhan Sipahi · Otomasyon Mühendisi",
        "testci": "Fatih Arslan · Test Uzmanı",
        "sunucu": "Sistem Yöneticisi",
        "denetci": "Denetçi",
        "gelistirici": "Geliştirici",
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
        display_name("muhendis", "engineer", configured_names("muhendis=")) == "Otomasyon Mühendisi"
    )


def test_seed_main_proje_kapsamli_tohumlari_baglamda_kosar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`python -m tp_core.seed` CLI'ında proje bağlamı yoktur; katalog ve otomasyon tohumları
    proje kapsamlıdır (`mevcut_pid`) ve varsayılan projenin bağlamında koşmalıdır."""
    from tp_core import seed as modul
    from tp_core.home_config import durum as home_durum
    from tp_core.proje.baglam import mevcut_pid, varsayilan_pid

    gorulen: list[str] = []
    monkeypatch.setattr(home_durum, "cli_yukle", lambda *_a, **_k: None)
    monkeypatch.setattr(modul, "seed", lambda: 0)
    monkeypatch.setattr(modul, "seed_test_verisi", lambda: gorulen.append(mevcut_pid()) or 0)
    monkeypatch.setattr(modul, "seed_otomasyon_demo", lambda: gorulen.append(mevcut_pid()) or {})
    modul.main()
    assert gorulen == [varsayilan_pid(), varsayilan_pid()]
