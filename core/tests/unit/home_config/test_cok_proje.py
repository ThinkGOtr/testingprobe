"""Çok proje config (TP-COK-PROJE-PLANI §3): proje başına etkin config, LKG ve sırlar; süreç
ortamına yazılmaması; `proje.ayar` bağlantısı ve sürüm; reddedilen proje (fail-closed + denetim);
keşif; proje başına özellik kapısı ve bağlantı token'ı; `Settings`/`GatewaySettings` proje alanları.
Veritabanı gerektirmez (kurulu proje listesi, kayıt ve denetim enjekte edilir)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit.home_config.sahte_home import HOME, SM_PROJESI, SahteHome, ornek_yanit
from tp_core.home_config import baglanti, durum
from tp_core.proje import ProjeBaglamiYok, ayar, proje_icinde

A = "aaaabbbbcccc"  # TP_HOME_PROJECT
B = "ddddeeeeffff"
B_REF = f"projects/{SM_PROJESI}/secrets/aiprobe-o0123456789ab--pr-ddddeeeeffff--jira/versions/1"


def _b_yaniti(**ek: Any) -> dict[str, Any]:
    v = ornek_yanit(
        project={"pid": B, "code": "mob", "name": "Mobil", "features": {"android": True},
                 "products": ["tp"]},
        env={"JIRA_PROJECT": "MOB", "TP_DENETIM_KAPISI": "off"},
        env_secrets={"JIRA_READ_TOKEN": B_REF},
        connections={"jira": {"mode": "oauth", "public": {"account_id": "x"}}},
        etag="b1",
    )  # fmt: skip
    v.update(ek)
    return v


@pytest.fixture
def ortam(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, Any]]:
    sahte = SahteHome()
    sahte.projeler[B] = _b_yaniti()
    sahte.sirlar[B_REF] = "b-gizli"
    for k in [*durum.CALISMA_ANINDA, "TP_BAGLANTI_TOKENI", "JIRA_READ_TOKEN"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "home")
    monkeypatch.setenv("TP_HOME_PROJECT", A)
    monkeypatch.setenv("TP_HOME_PROJECTS", B)
    monkeypatch.setenv("AIPROBE_HOME_RUN_URL", HOME)
    monkeypatch.setenv("SECRETS_PROJECT", SM_PROJESI)
    monkeypatch.setenv("TP_CONFIG_LKG_PATH", str(tmp_path / "lkg.json"))
    monkeypatch.setenv("JIRA_PROJECT", "BAYI")
    monkeypatch.setenv("TP_DATABASE_URL", "postgresql+psycopg://x@127.0.0.1:1/x")
    monkeypatch.setenv("JIRA_READ_TOKEN", "bayi-env-sirri")
    kayit: list[tuple[str, str]] = []
    denetim: list[tuple[str, dict[str, Any]]] = []
    kurulu: list[str] = []
    durum.reset()
    baglanti.configure(None)
    durum.configure(
        http=sahte, id_token=lambda aud: f"id:{aud}", temizle=lambda: None,
        projeler=lambda: list(kurulu), kaydet=lambda p, k: kayit.append((p, k)),
        denetim=lambda e, o: denetim.append((e, o)),
    )  # fmt: skip
    yield {"home": sahte, "kayit": kayit, "denetim": denetim, "kurulu": kurulu, "tmp": tmp_path}
    durum.reset()
    baglanti.configure(None)
    ayar._ust_temizle()


def test_ek_proje_kendi_configi_sirlar_bellekte(ortam: dict[str, Any]) -> None:
    durum.baslat("core-api")
    try:
        assert ("aaaabbbbcccc", "env") in ortam["kayit"] and (B, "env") in ortam["kayit"]
        # Varsayılan proje: Home değeri, sır süreç ortamından.
        assert ayar.ayar("JIRA_PROJECT", pid=A) == "TPD"
        assert ayar.sir("JIRA_READ_TOKEN", pid=A) == "bayi-env-sirri"
        # B: kendi değeri ve Secret Manager'dan çözülen sırrı; süreç ortamına yazılmaz.
        assert ayar.ayar("JIRA_PROJECT", pid=B) == "MOB"
        assert ayar.sir("JIRA_READ_TOKEN", pid=B) == "b-gizli"
        assert os.environ["JIRA_READ_TOKEN"] == "bayi-env-sirri"
        assert "b-gizli" not in os.environ.values()
        assert os.environ.get("TP_DENETIM_KAPISI") == "on"  # varsayılan projenin değeri
        # B'de tanımsız T/A/P adı env'e (Bayi'ye) düşmez.
        assert ayar.ayar("TP_PO_JIRA_USERS", pid=B) is None
        # Bağlam: bağlamsız okuma hata; bağlamda o projenin değeri.
        with pytest.raises(ProjeBaglamiYok):
            ayar.ayar("JIRA_PROJECT")
        with proje_icinde(B):
            assert ayar.ayar("JIRA_PROJECT") == "MOB"
            assert durum.ozellik_acik("android") and not durum.ozellik_acik("web")
            assert durum.baglanti_kipi("jira") == "oauth"
        with proje_icinde(A):
            assert durum.ozellik_acik("web") and durum.baglanti_kipi("jira") == "token"
        # Ek projenin LKG'si ayrı dosyada (sır değeri değil, referans).
        lkg = Path(str(ortam["tmp"] / "lkg") + f"-{B}.json")
        assert lkg.is_file() and "b-gizli" not in lkg.read_text()
        assert durum.ozet()["projeler"][B]["etag"] == "b1"
    finally:
        durum.durdur()


def test_surum_degisince_onbellek_kirilir(ortam: dict[str, Any]) -> None:
    durum.ayar_kaynagini_bagla()
    durum.yenile("core-api")
    s1 = ayar.surum(B)
    durum.yenile("core-api")
    assert ayar.surum(B) == s1  # 304
    ortam["home"].projeler[B] = _b_yaniti(etag="b2", env={"JIRA_PROJECT": "MOB2"})
    durum.yenile("core-api")
    assert ayar.surum(B) != s1 and ayar.ayar("JIRA_PROJECT", pid=B) == "MOB2"
    from tp_core.config import get_settings

    with proje_icinde(B):
        assert get_settings().jira_project == "MOB2"
    with proje_icinde(A):
        assert get_settings().jira_project == "TPD"


def test_reddedilen_proje_kapali_ve_denetlenir(ortam: dict[str, Any]) -> None:
    durum.ayar_kaynagini_bagla()
    durum.yenile("core-api")
    assert ayar.ayar("JIRA_PROJECT", pid=B) == "MOB"
    ortam["home"].proje_durum[B] = 403
    durum.yenile("core-api")
    assert ayar.ayar("JIRA_PROJECT", pid=B) is None and ayar.sir("JIRA_READ_TOKEN", pid=B) is None
    assert durum.ozellikler(B) == {o: False for o in ("web", "android", "ios", "windows",
                                                      "ai_agent")}  # fmt: skip
    # Varsayılan proje etkilenmez.
    assert ayar.ayar("JIRA_PROJECT", pid=A) == "TPD" and durum.ozellik_acik("web", A)
    durum.yenile("core-api")
    olaylar = [e for e, _o in ortam["denetim"] if e == "config.proje_reddedildi"]
    assert olaylar == ["config.proje_reddedildi"]  # geçişte bir kez
    assert ortam["denetim"][0][1]["pid"] == B


def test_yuklenmemis_ek_proje_kapali(ortam: dict[str, Any]) -> None:
    ortam["home"].proje_durum["eeee00001111"] = 404
    kapali = {o: False for o in ("web", "android", "ios", "windows", "ai_agent")}
    assert durum.ozellikler("eeee00001111") == kapali
    assert durum.ayar_cozucu("eeee00001111") is None


def test_kesif(ortam: dict[str, Any]) -> None:
    yeni = "ffff00002222"
    ortam["home"].projeler[yeni] = _b_yaniti(project={"pid": yeni, "name": "Yeni"}, etag="y")
    assert durum.kesfet(yeni) is True and (yeni, "kesif") in ortam["kayit"]
    ortam["home"].proje_durum["9999aaaabbbb"] = 403
    assert durum.kesfet("9999aaaabbbb") is False
    sayi = ortam["home"].sayi("/v1/config/effective")
    assert durum.kesfet("9999aaaabbbb") is False  # negatif önbellek
    assert ortam["home"].sayi("/v1/config/effective") == sayi
    assert durum.kesfet("../kotu") is False


def test_env_kipinde_coklu_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    durum.reset()
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    assert durum.kesfet(B) is False and durum.ayar_cozucu(B) is None
    assert durum.ozellikler(B) is None and durum.ayar_surumu(B) == "env"


def test_baglanti_tokeni_proje_basina(
    ortam: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    h = ortam["home"]
    h.erisim = {"github": {"mode": "app", "access_token": "ghs", "expires_at": 9e12}}
    baglanti.token_al("github")
    with proje_icinde(B):
        baglanti.token_al("github")
        baglanti.token_al("github")  # önbellek
    baglanti.token_al("github", B)
    assert h.erisim_projeleri == [A, B]
    istek = [json.loads(g or b"{}") for _m, u, _h, g in h.istekler if "access-token" in u]
    assert [i["project"] for i in istek] == [A, B]


def test_gateway_ayari_proje_basina(ortam: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.gateway.config import GatewaySettings

    monkeypatch.setenv("TP_PII_MASKING", "0")
    ortam["home"].projeler[B] = _b_yaniti(env={"TP_PII_MASKING": "1"})
    durum.ayar_kaynagini_bagla()
    durum.yenile("core-api")
    with proje_icinde(B):
        assert GatewaySettings().pii_masking is True
    with proje_icinde(A):
        assert GatewaySettings().pii_masking is False
    assert GatewaySettings().pii_masking is False  # bağlamsız: env
