"""Rol anmaları: `TP_JIRA_MENTIONS_<ROL>` listesindeki herkes anılır; boş liste → eski
`JIRA_HESAP_<ROL>`; ürünün bot/okuma/yazma hesapları asla anılmaz; yineleme yok."""

from __future__ import annotations

from typing import Any

import pytest

from tp_core.home_config.durum import CALISMA_ANINDA
from tp_core.integrations import jira_notify
from tp_core.integrations.jira import MENTION_ROLLERI, JiraSettings, KisiEtiketleyici
from tp_core.integrations.jira_adf import bot_header
from tp_core.proje.ayar import PROJE_ANAHTARLARI

A = "712020:00000000-0000-4000-8000-0000000000a1"
B = "712020:00000000-0000-4000-8000-0000000000b2"
C = "712020:00000000-0000-4000-8000-0000000000c3"
ESKI = "712020:00000000-0000-4000-8000-0000000000e4"
BOT = "712020:00000000-0000-4000-8000-0000000000f5"

YENI_ANAHTARLAR = [f"TP_JIRA_MENTIONS_{r.upper()}" for r in MENTION_ROLLERI]


@pytest.fixture(autouse=True)
def _temiz_ortam(monkeypatch: pytest.MonkeyPatch) -> None:
    for ad in [
        *YENI_ANAHTARLAR,
        "JIRA_HESAP_ANALIST",
        "JIRA_HESAP_PO",
        "JIRA_HESAP_MUHENDIS",
        "JIRA_HESAP_TESTCI",
        "TP_JIRA_BOT_ACCOUNT_IDS",
        "JIRA_WRITE_EMAIL",
        "JIRA_READ_EMAIL",
    ]:
        monkeypatch.delenv(ad, raising=False)


def _mention_ids(header: dict[str, Any]) -> list[str]:
    return [n["attrs"]["id"] for n in header["content"] if n["type"] == "mention"]


def test_anahtarlar_home_config_listelerinde() -> None:
    assert set(YENI_ANAHTARLAR) <= CALISMA_ANINDA
    assert set(YENI_ANAHTARLAR) <= PROJE_ANAHTARLARI
    assert {"analyst", "po", "engineer", "tester", "developer", "admin", "auditor"} <= set(
        MENTION_ROLLERI
    )


def test_rolun_tum_kisileri_ayri_ayri_ve_tekil_anilir() -> None:
    s = JiraSettings(
        jira_mentions_engineer=f"{B}, {C}",
        jira_mentions_tester=f"{A},{B},{A}",
    )
    ids = jira_notify.role_mentions(jira_notify.BUG, s)  # mühendis + test uzmanı
    assert ids == [B, C, A]
    h = bot_header(ids)
    assert _mention_ids(h) == [B, C, A]  # her kişi ayrı mention düğümü
    assert all(n["type"] in ("text", "mention") for n in h["content"])


def test_liste_eski_tek_degerden_once_gelir() -> None:
    s = JiraSettings(jira_mentions_po=f"{A},{B}", jira_hesap_po=ESKI)
    assert jira_notify.role_mentions(("po",), s) == [A, B]


def test_bos_liste_eski_tek_degerli_enve_duser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_HESAP_TESTCI", ESKI)
    monkeypatch.setenv("TP_JIRA_MENTIONS_TESTER", "")
    assert jira_notify.role_mentions(jira_notify.YAYIN, JiraSettings()) == [ESKI]
    # İkisi de boş → anma yok.
    monkeypatch.delenv("JIRA_HESAP_TESTCI")
    assert jira_notify.role_mentions(jira_notify.YAYIN, JiraSettings()) == []


def test_yeni_env_adlari_okunur(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_JIRA_MENTIONS_ANALYST", f"{A},{C}")
    monkeypatch.setenv("TP_JIRA_MENTIONS_PO", B)
    assert jira_notify.role_mentions(jira_notify.PO_SORU, JiraSettings()) == [B, A, C]


def test_bot_okuma_yazma_hesaplari_haric() -> None:
    s = JiraSettings(
        jira_bot_account_ids=BOT,
        jira_mentions_po=f"{BOT},{A}",
        jira_hesap_testci=BOT,  # eski tek değer de bot ise anılmaz
    )
    assert s.role_accounts("po") == [A]
    assert jira_notify.role_mentions(("po", "testci"), s) == [A]
    # Büyük/küçük harf farkı hariç tutmayı atlatmaz.
    s2 = JiraSettings(jira_bot_account_ids=BOT.upper(), jira_mentions_tester=BOT)
    assert s2.role_accounts("tester") == []


def test_gecersiz_kimlikler_atlanir_ve_liste_bicimleri() -> None:
    s = JiraSettings(jira_mentions_tester=f"kişi@ornek.com, ,{A}")
    assert s.role_accounts("testci") == [A]
    liste = JiraSettings.model_validate({"TP_JIRA_MENTIONS_TESTER": [A, B]})
    assert liste.role_accounts("tester") == [A, B]
    json_metin = JiraSettings.model_validate({"TP_JIRA_MENTIONS_TESTER": f'["{B}","{A}"]'})
    assert json_metin.role_accounts("tester") == [B, A]


def test_portal_rol_kodlari_ve_bilinmeyen_rol() -> None:
    s = JiraSettings(jira_mentions_developer=f"{A},{B}")
    assert jira_notify.role_mentions(("developer", "yok"), s) == [A, B]
    assert s.role_accounts("yok") == []


def test_post_comment_herkesi_anar(monkeypatch: pytest.MonkeyPatch) -> None:
    s = JiraSettings(jira_mentions_engineer=f"{A},{B}", jira_mentions_tester=f"{B},{C}")
    monkeypatch.setattr("tp_core.integrations.jira.get_jira_settings", lambda: s)
    cagrilar: list[tuple[str, str, list[str]]] = []

    class Sahte:
        def add_comment(self, key: str, body: str, *, mentions: Any = ()) -> str:
            cagrilar.append((key, body, list(mentions)))
            return "c1"

    assert jira_notify.post_comment(Sahte(), "TPD-1", "metin", jira_notify.BUG) == "c1"
    assert cagrilar == [("TPD-1", "metin", [A, B, C])]


def test_okuyucu_etiketleyici_liste_uyelerini_role_cevirir() -> None:
    s = JiraSettings(jira_mentions_tester=f"{A},{B}")
    e = KisiEtiketleyici.ayarlardan(s)
    assert e.etiket([B]) == "tester"
    assert e.etiket([A]) == "tester"
