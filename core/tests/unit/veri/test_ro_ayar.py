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


# ------------------------------------------------- Home kipi: Home alanları > Deployment dizesi

DEPLOYMENT_URL = "postgresql+psycopg://demoapp_ro:dep-Gizli@postgres:5432/demoapp"


@pytest.fixture
def home_gorunumu(monkeypatch: pytest.MonkeyPatch) -> Any:
    """`proje.ayar` Home kaynağına bağlı (sahte görünüm); Deployment dizesi ve Home'un parolası
    süreç ortamında (compose → core-worker)."""
    from tp_core.proje import ayar as proje_ayar
    from tp_core.proje import proje_icinde, varsayilan_pid

    for k in BOS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEMOAPP_RO_DATABASE_URL", DEPLOYMENT_URL)
    gorunum: dict[str, str] = {}
    proje_ayar.kaynak_bagla(lambda pid: gorunum, lambda pid: "etag-" + str(sorted(gorunum)))
    get_requirements_settings.cache_clear()
    try:
        with proje_icinde(varsayilan_pid()):
            yield gorunum
    finally:
        proje_ayar._kaynak_coz()
        get_requirements_settings.cache_clear()


def test_home_ayri_alanlari_deployment_dizesinin_onune_gecer(
    home_gorunumu: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    home_gorunumu.update(
        TP_RO_DB_TYPE="postgresql",
        TP_RO_DB_HOST="home-db",
        TP_RO_DB_PORT_NO="5433",
        TP_RO_DB_NAME="musteri",
        TP_RO_DB_USER="home_ro",
    )
    monkeypatch.setenv("TP_RO_DB_PASSWORD", "Home-Gizli-7")  # sır: süreç ortamından
    db = services.demo_db()
    t = db.tanim
    assert t is not None and t.ham_url is None
    assert (t.host, t.port, t.veritabani, t.kullanici, t.parola) == (
        "home-db",
        5433,
        "musteri",
        "home_ro",
        "Home-Gizli-7",
    )
    assert testdata.demo_db_query() is not None


def test_home_alan_vermiyorsa_deployment_dizesi_yedek(home_gorunumu: dict[str, str]) -> None:
    home_gorunumu.update(JIRA_PROJECT="TPD")
    t = services.demo_db().tanim
    assert t is not None and t.host == "postgres" and t.kullanici == "demoapp_ro"


def test_home_bos_tur_dizeyi_ezmez(home_gorunumu: dict[str, str]) -> None:
    home_gorunumu.update(TP_RO_DB_TYPE="", TP_RO_DB_HOST="home-db")
    t = services.demo_db().tanim
    assert t is not None and t.host == "postgres"


def test_home_dizesi_de_verirse_dize_kazanir(home_gorunumu: dict[str, str]) -> None:
    home_gorunumu.update(
        DEMOAPP_RO_DATABASE_URL="postgresql://u:p@home-url-db/demo",
        TP_RO_DB_TYPE="mysql",
        TP_RO_DB_HOST="mysql1",
        TP_RO_DB_NAME="demo",
        TP_RO_DB_USER="ro",
    )
    t = services.demo_db().tanim
    assert t is not None and t.host == "home-url-db"


def test_env_kipinde_alanlar_dizeyi_ezmez(monkeypatch: pytest.MonkeyPatch) -> None:
    """env kipi (Home kaynağı yok): süreç ortamındaki ayrı alanlar Home sayılmaz; dize kazanır."""
    for k in BOS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEMOAPP_RO_DATABASE_URL", DEPLOYMENT_URL)
    monkeypatch.setenv("TP_RO_DB_TYPE", "mysql")
    monkeypatch.setenv("TP_RO_DB_HOST", "mysql1")
    get_requirements_settings.cache_clear()
    try:
        assert services.demo_db().tur == "postgresql"
    finally:
        get_requirements_settings.cache_clear()
