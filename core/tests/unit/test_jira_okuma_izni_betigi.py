"""scripts/jira-okuma-izni.py — security-check 8'in Jira okuma hesabı izin adımı (R14)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

from tp_core.integrations.jira import JiraSettings

BETIK = Path(__file__).resolve().parents[3] / "scripts" / "jira-okuma-izni.py"
GERCEK = "https://ornek.atlassian.net"


@pytest.fixture(scope="module")
def betik():
    spec = importlib.util.spec_from_file_location("jira_okuma_izni", BETIK)
    assert spec and spec.loader
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _ayar(base: str = GERCEK, eposta: str | None = "okuma@ornek.test", token: str | None = None):
    # Sahte token çalışma anında birleştirilir (gerçek biçimli sabit depoya girmesin).
    token = token if token is not None else "ATAT" + "T3x" + "F" * 20
    return JiraSettings(JIRA_BASE_URL=base, JIRA_READ_EMAIL=eposta, JIRA_READ_TOKEN=token)


def _izinler(**deger: bool) -> dict:
    return {"permissions": {ad: {"key": ad, "havePermission": v} for ad, v in deger.items()}}


def _transport(govde: dict | None = None, durum: int = 200, istekler: list | None = None):
    def isle(istek: httpx.Request) -> httpx.Response:
        if istekler is not None:
            istekler.append(istek)
        return httpx.Response(durum, json=govde if govde is not None else {})

    return httpx.MockTransport(isle)


def test_simulatorde_atlanir_ve_istek_atilmaz(betik):
    istekler: list = []
    sonuc = betik.denetle(_ayar(base="http://jira-sim:8090"), _transport(istekler=istekler))
    assert sonuc == ("ATLA", "simulator")
    assert istekler == []


def test_yazma_izni_yoksa_tamam_ve_istek_bicimi(betik):
    istekler: list = []
    govde = _izinler(ADD_COMMENTS=False, CREATE_ISSUES=False, EDIT_ISSUES=False)
    assert betik.denetle(_ayar(), _transport(govde, istekler=istekler)) == ("TAMAM", "")
    (istek,) = istekler
    assert istek.method == "GET"
    assert istek.url.path == "/rest/api/3/mypermissions"
    assert istek.url.params["permissions"] == "ADD_COMMENTS,CREATE_ISSUES,EDIT_ISSUES"
    # Proje bağlamı yok: Jira "herhangi bir projede" izni döndürür (en sıkı yorum).
    assert "projectKey" not in istek.url.params
    assert istek.headers["authorization"].startswith("Basic ")


def test_yazma_izni_varsa_yalniz_izin_adlari_doner(betik):
    govde = _izinler(ADD_COMMENTS=True, CREATE_ISSUES=False, EDIT_ISSUES=True)
    assert betik.denetle(_ayar(), _transport(govde)) == ("YAZMA", "ADD_COMMENTS,EDIT_ISSUES")


@pytest.mark.parametrize(
    ("govde", "durum", "beklenen"),
    [
        ({}, 401, ("HATA", "http_401")),
        ({}, 503, ("HATA", "http_503")),
        ({"permissions": []}, 200, ("HATA", "gecersiz_yanit")),
        (
            _izinler(ADD_COMMENTS=False, CREATE_ISSUES=False),
            200,
            ("HATA", "izin_yanitta_yok:EDIT_ISSUES"),
        ),
    ],
)
def test_dogrulanamayan_yanit_hata_sayilir(betik, govde, durum, beklenen):
    assert betik.denetle(_ayar(), _transport(govde, durum)) == beklenen


def test_okuma_kimligi_yoksa_hata(betik):
    assert betik.denetle(_ayar(eposta=None), _transport({})) == ("HATA", "okuma_kimligi_yok")
    assert betik.denetle(_ayar(token=""), _transport({})) == ("HATA", "okuma_kimligi_yok")


def test_ag_hatasi_yalniz_sinif_adi(betik):
    def patla(istek: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("baglanti reddedildi " + str(istek.url))

    assert betik.denetle(_ayar(), httpx.MockTransport(patla)) == ("HATA", "ConnectError")


def test_main_cikti_tek_satir_ve_cikis_kodu(betik, monkeypatch, capsys):
    monkeypatch.setattr(betik, "denetle", lambda: ("YAZMA", "ADD_COMMENTS"))
    assert betik.main() == 1
    assert capsys.readouterr().out == "YAZMA ADD_COMMENTS\n"

    monkeypatch.setattr(betik, "denetle", lambda: ("TAMAM", ""))
    assert betik.main() == 0
    assert capsys.readouterr().out == "TAMAM\n"
