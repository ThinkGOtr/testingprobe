"""Çoklu DB yapılandırma anahtarları: proje ayarı, Home config sınıfları, sır, geriye uyum."""

from __future__ import annotations

from typing import Any

import pytest

from tp_core.features.cases import testdata
from tp_core.features.requirements import services
from tp_core.features.requirements.datatools import DataToolError
from tp_core.features.requirements.settings import get_requirements_settings
from tp_core.gateway.factory import SECRET_ENV_VARS, known_secret_values
from tp_core.home_config import durum
from tp_core.home_config import yukleyici as y
from tp_core.proje.ayar import PROJE_ANAHTARLARI

ANAHTARLAR = (
    "TP_RO_DB_TYPE",
    "TP_RO_DB_HOST",
    "TP_RO_DB_PORT_NO",
    "TP_RO_DB_NAME",
    "TP_RO_DB_USER",
    "TP_RO_DB_PASSWORD",
)
BOS: dict[str, None] = {k: None for k in (*ANAHTARLAR, "DEMOAPP_RO_DATABASE_URL")}


@pytest.fixture
def ayarla(proje_ayar: Any) -> Any:
    def _ayarla(**degerler: str | None) -> None:
        proje_ayar(**{**BOS, **degerler})
        get_requirements_settings.cache_clear()

    yield _ayarla
    get_requirements_settings.cache_clear()


def test_anahtarlar_proje_ayari_ve_home_tarafindan_yazilabilir() -> None:
    assert set(ANAHTARLAR) <= PROJE_ANAHTARLARI
    for k in ANAHTARLAR:
        assert y.gecerli_anahtar(k), k
    # `_PORT` soneki korunur: Home port alanını `TP_RO_DB_PORT_NO` adıyla yazar.
    assert y.korunan_mi("TP_RO_DB_PORT") and not y.korunan_mi("TP_RO_DB_PORT_NO")


def test_parola_sir_calisma_aninda_degil() -> None:
    assert "TP_RO_DB_PASSWORD" not in durum.CALISMA_ANINDA
    assert set(ANAHTARLAR) - {"TP_RO_DB_PASSWORD"} <= durum.CALISMA_ANINDA
    assert "TP_RO_DB_PASSWORD" in SECRET_ENV_VARS
    assert "Gizli-Parola-42" in known_secret_values({"TP_RO_DB_PASSWORD": "Gizli-Parola-42"})


def test_sunucu_home_dan_degisirse_yerel_parola_dusurulur() -> None:
    """A1: hedef (sunucu) Home'dan, parola Deployment'tan → parola kullanılmaz."""
    dus = y.bagli_sir_kaldirma({"TP_RO_DB_HOST": "saldirgan.example"}, set(), {})
    assert "TP_RO_DB_PASSWORD" in dus
    ayni = y.bagli_sir_kaldirma({"TP_RO_DB_HOST": "db"}, set(), {"TP_RO_DB_HOST": "db"})
    assert "TP_RO_DB_PASSWORD" not in ayni
    ikisi = y.bagli_sir_kaldirma({"TP_RO_DB_HOST": "x"}, {"TP_RO_DB_PASSWORD"}, {})
    assert "TP_RO_DB_PASSWORD" not in ikisi


def test_geriye_uyum_yalniz_url(ayarla: Any) -> None:
    ayarla(DEMOAPP_RO_DATABASE_URL="postgresql+psycopg://demoapp_ro:p@db:5432/demo")
    db = services.demo_db()
    assert db.tur == "postgresql" and db.lehce == "postgres"
    assert db.tanim is not None and db.tanim.ham_url == "postgresql://demoapp_ro:p@db:5432/demo"
    assert testdata.demo_db_query() is not None


def test_url_ayri_alanlarin_onune_gecer(ayarla: Any) -> None:
    ayarla(
        DEMOAPP_RO_DATABASE_URL="postgresql://u:p@db/demo",
        TP_RO_DB_TYPE="mysql",
        TP_RO_DB_HOST="mysql1",
        TP_RO_DB_NAME="demo",
        TP_RO_DB_USER="ro",
    )
    assert services.demo_db().tur == "postgresql"


def test_ayri_alanlar(ayarla: Any) -> None:
    ayarla(
        TP_RO_DB_TYPE="oracle",
        TP_RO_DB_HOST="ora1",
        TP_RO_DB_PORT_NO="1522",
        TP_RO_DB_NAME="FREEPDB1",
        TP_RO_DB_USER="ro",
        TP_RO_DB_PASSWORD="Ora-Gizli-9",
    )
    ayar = get_requirements_settings()
    assert "Ora-Gizli-9" not in repr(ayar) and "Ora-Gizli-9" not in str(ayar.model_dump())
    db = services.demo_db()
    t = db.tanim
    assert t is not None
    assert (t.tur, t.host, t.port, t.veritabani, t.kullanici, t.parola) == (
        "oracle",
        "ora1",
        1522,
        "FREEPDB1",
        "ro",
        "Ora-Gizli-9",
    )
    assert db.lehce == "oracle"


def test_hicbiri_yoksa_yapilandirilmamis(ayarla: Any) -> None:
    ayarla()
    assert testdata.demo_db_query() is None
    with pytest.raises(DataToolError, match="yapılandırılmamış"):
        services.demo_db().schema()


def test_eksik_ayri_alan_yapilandirma_hatasi(ayarla: Any) -> None:
    ayarla(TP_RO_DB_TYPE="mysql", TP_RO_DB_HOST="h", TP_RO_DB_PASSWORD="x-Gizli")
    with pytest.raises(DataToolError, match="TP_RO_DB_NAME") as ei:
        services.demo_db().query("SELECT kod FROM urun")
    assert "x-Gizli" not in str(ei.value)
