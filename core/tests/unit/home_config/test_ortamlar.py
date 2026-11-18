"""Test ortamları (Home proje ortamları; 0048): liste ve varsayılan, ortam düzeyi etkin config
(ayrı ETag/önbellek), `proje.ayar` ortam kaplaması, A1 kaldırma, çözülemeyen ortam (fail-closed),
Canlı engeli ve toolchain bloğu. Veritabanı gerektirmez."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit.home_config.sahte_home import HOME, REF, SM_PROJESI, SahteHome, ornek_yanit
from tp_core.api.errors import CanliOrtamEngeli, OrtamAyariYok
from tp_core.features.ci.projeler import toolchain_projesi
from tp_core.home_config import baglanti, durum
from tp_core.proje import ayar, ortam, proje_icinde

A = "aaaabbbbcccc"
E1 = "e1e1e1e1e1e1"  # Staging (varsayılan)
E2 = "e2e2e2e2e2e2"  # Canlı
E3 = "e3e3e3e3e3e3"  # Home'da kaydı olmayan (silinmiş) ortam

ORTAMLAR = [
    {"eid": E2, "name": "Canlı", "type": "prod", "is_default": False},
    {"eid": E1, "name": "Staging", "type": "staging", "is_default": True},
    {"eid": "bozuk", "name": "x", "type": "test"},
    {"eid": E3, "name": "Eski", "type": "test", "is_default": False},
]


def _ortam_yaniti(eid: str, ad: str, tur: str, env: dict[str, Any], sirlar: dict[str, str]) -> dict:
    return ornek_yanit(
        environment={"eid": eid, "name": ad, "type": tur, "is_default": eid == E1},
        environments=ORTAMLAR,
        env={"JIRA_PROJECT": "TPD", **env},
        env_secrets=sirlar,
        etag=f"{eid}-v1",
    )


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[SahteHome]:
    sahte = SahteHome()
    sahte.yanit = ornek_yanit(
        env={"JIRA_PROJECT": "TPD", "BASE_URL": "https://proje.example.test"},
        environments=ORTAMLAR,
    )
    sahte.ortamlar[(A, E1)] = _ortam_yaniti(
        E1, "Staging", "staging",
        {"BASE_URL": "https://staging.example.test", "TP_PROBE_USER": "stg-kullanici"},
        {"TP_PROBE_PASSWORD": REF},
    )  # fmt: skip
    # Canlı: adres ortamdan, parola Home'da yok → A1 yerel kuralı parolayı kaldırır.
    sahte.ortamlar[(A, E2)] = _ortam_yaniti(
        E2, "Canlı", "prod", {"BASE_URL": "https://canli.example.test"}, {}
    )
    for k in [*durum.CALISMA_ANINDA, "TP_BAGLANTI_TOKENI", "TP_HOME_PROJECTS"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "home")
    monkeypatch.setenv("TP_HOME_PROJECT", A)
    monkeypatch.setenv("AIPROBE_HOME_RUN_URL", HOME)
    monkeypatch.setenv("SECRETS_PROJECT", SM_PROJESI)
    monkeypatch.setenv("TP_CONFIG_LKG_PATH", str(tmp_path / "lkg.json"))
    monkeypatch.setenv("TP_DATABASE_URL", "postgresql+psycopg://x@127.0.0.1:1/x")
    monkeypatch.setenv("BASE_URL", "http://demo-app-web:8080")
    monkeypatch.setenv("TP_PROBE_PASSWORD", "deployment-parolasi")
    durum.reset()
    baglanti.configure(None)
    durum.configure(
        http=sahte, id_token=lambda aud: f"id:{aud}", temizle=lambda: None,
        projeler=lambda: [], kaydet=lambda p, k: None, denetim=lambda e, o: None,
    )  # fmt: skip
    durum.baslat("core-api")
    try:
        yield sahte
    finally:
        durum.durdur()
        durum.reset()
        baglanti.configure(None)
        ayar._ust_temizle()


def test_ortam_listesi_ve_varsayilan(home: SahteHome) -> None:
    with proje_icinde(A):
        liste = ortam.ortamlar()
        assert [o.ad for o in liste] == ["Canlı", "Eski", "Staging"]  # bozuk kimlik atlanır
        v = ortam.varsayilan_ortam()
        assert v is not None and v.eid == E1 and not v.canli
        assert ortam.sec(None) == v
        assert ortam.sec(E2).canli
        with pytest.raises(ortam.OrtamBulunamadi):
            ortam.sec("ffffffffffff")


def test_ortam_kaplamasi_yalniz_baglamda(home: SahteHome) -> None:
    with proje_icinde(A):
        assert ayar.ayar("BASE_URL") == "https://proje.example.test"
        stg = ortam.ortam_bul(E1)
        with ortam.ortam_icinde(stg):
            assert ayar.ayar("BASE_URL") == "https://staging.example.test"
            assert ayar.ayar("TP_PROBE_USER") == "stg-kullanici"
            assert ayar.sir("TP_PROBE_PASSWORD") == "gizli-deger"  # Secret Manager'dan
            assert ayar.ayar("JIRA_PROJECT") == "TPD"
            surum_ortamli = ayar.surum()
        assert ayar.ayar("BASE_URL") == "https://proje.example.test"
        assert E1 in surum_ortamli and E1 not in ayar.surum()
    # Ortam değerleri süreç ortamına yazılmaz.
    assert os.environ["BASE_URL"] == "http://demo-app-web:8080"
    assert "gizli-deger" not in os.environ.values()


def test_ortam_configi_onbellekli_ayri_etag(home: SahteHome) -> None:
    with proje_icinde(A), ortam.ortam_icinde(ortam.ortam_bul(E1)):
        for _ in range(3):
            ayar.ayar("BASE_URL")
    ortam_istekleri = [u for _m, u, _h, _b in home.istekler if "environment=" in u]
    assert len(ortam_istekleri) == 1 and f"environment={E1}" in ortam_istekleri[0]


def test_hedefi_ortamdan_gelen_parola_kaldirilir(home: SahteHome) -> None:
    with proje_icinde(A), ortam.ortam_icinde(ortam.ortam_bul(E2)):
        assert ayar.ayar("BASE_URL") == "https://canli.example.test"
        # Deployment parolası Canlı adresine gönderilmez (A1).
        assert ayar.sir("TP_PROBE_PASSWORD") is None


def test_cozulemeyen_ortam_proje_degerine_dusmez(home: SahteHome) -> None:
    with proje_icinde(A), ortam.ortam_icinde(ortam.ortam_bul(E3)), pytest.raises(OrtamAyariYok):
        ayar.ayar("BASE_URL")


def test_canli_engeli(home: SahteHome) -> None:
    with proje_icinde(A):
        ortam.canli_engelle("demo sıfırlama")  # varsayılan Staging: serbest
        canli = ortam.ortam_bul(E2)
        with pytest.raises(CanliOrtamEngeli) as exc:
            ortam.canli_engelle("demo sıfırlama", canli)
        assert exc.value.status_code == 409
        assert exc.value.ek["engel"] == "canli_ortam"
        assert exc.value.ek["ortam"]["eid"] == E2
        assert "Canlı ortamda" in str(exc.value)
        with ortam.ortam_icinde(canli), pytest.raises(CanliOrtamEngeli):
            ortam.canli_engelle("kırarak doğrulama")


def test_toolchain_blogu_ortam_baglaminda(home: SahteHome) -> None:
    with proje_icinde(A):
        assert "proje" not in toolchain_projesi({"sha": "x"})  # ortamsız varsayılan proje
        with ortam.ortam_icinde(ortam.ortam_bul(E1)):
            blok = toolchain_projesi({"sha": "x"})["proje"]
        assert blok["ortam"] == {"eid": E1, "ad": "Staging", "tur": "staging"}
        assert blok["base_url"] == "https://staging.example.test"
        assert blok["probe_password"] == "gizli-deger"
        with ortam.ortam_icinde(ortam.ortam_bul(E2)):
            canli = toolchain_projesi({"sha": "x"})["proje"]
        assert canli["ortam"]["tur"] == "prod"
        assert canli["probe_password"] == ""  # env parolasına düşmesin


def test_env_kipinde_ortam_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIG_SOURCE", "env")
    durum.reset()
    with proje_icinde("varsayilan"):
        assert ortam.ortamlar() == []
        assert ortam.varsayilan_ortam() is None
        assert ortam.islem_ortami() is None
        ortam.canli_engelle("demo sıfırlama")
