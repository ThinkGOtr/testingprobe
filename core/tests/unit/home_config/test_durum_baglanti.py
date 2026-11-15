"""Config R1 — çalışan süreç: yenileme ve çalışma anı / yeniden başlatma ayrımı, CONFIG_SOURCE=env
geri uyumu, özellik kapısı, bağlantı erişim token'ı (sahte Home), Jira OAuth ve GitHub App
istemcileri, OAuth kipinde PO / bot kimliği kuralı."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.unit.home_config.sahte_home import HOME, SahteHome, ornek_yanit
from tp_core.home_config import baglanti, durum, kapi

JIRA_TABANI = "https://api.atlassian.com/ex/jira/11111111-2222-3333-4444-555555555555"
SAHIP = "712020:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PO = "712020:11111111-2222-3333-4444-555555555555"


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[SahteHome]:
    sahte = SahteHome()
    for k in [*durum.CALISMA_ANINDA, "TP_BAGLANTI_TOKENI", "JIRA_BASE_URL"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "home")
    monkeypatch.setenv("TP_HOME_PROJECT", "aaaabbbbcccc")
    monkeypatch.setenv("AIPROBE_HOME_RUN_URL", HOME)
    monkeypatch.setenv("TP_CONFIG_LKG_PATH", str(tmp_path / "lkg.json"))
    monkeypatch.setenv("JIRA_PROJECT", "ESKI")
    temizlenen: list[int] = []
    durum.reset()
    baglanti.configure(None)
    durum.configure(http=sahte, id_token=lambda aud: f"id:{aud}",
                    temizle=lambda: temizlenen.append(1))  # fmt: skip
    sahte.temizlenen = temizlenen  # type: ignore[attr-defined]
    yield sahte
    durum.reset()
    baglanti.configure(None)


# ------------------------------------------------------------------ CONFIG_SOURCE=env geri uyumu


def test_env_kipinde_hicbir_sey_degismez(monkeypatch: pytest.MonkeyPatch) -> None:
    durum.reset()
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    cagri: list[object] = []
    durum.configure(http=lambda *a: cagri.append(a))  # type: ignore[arg-type,return-value]
    durum.baslat("core-api")
    assert cagri == []
    assert durum.ozellikler() is None and durum.ozellik_acik("ios")
    assert durum.baglanti_kipi("jira") == "token" and durum.org_proje() is None
    kapi.platform_gerekli("windows")
    kapi.ai_agent_gerekli()
    assert durum.ozet()["kaynak"] == "env"
    durum.reset()


# ------------------------------------------------------------------ yenileme + uygulama


def test_calisma_aninda_ve_yeniden_baslatmada(
    home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = durum.yenile("core-api")
    assert d.kaynak == "home"
    assert os.environ["TP_DENETIM_KAPISI"] == "on" and os.environ["TP_CT_SON_KOSU"] == "25"
    # JIRA_PROJECT çalışma anı anahtarı değil: süreçte değişmez, bekleyen listesine düşer.
    assert os.environ["JIRA_PROJECT"] == "ESKI" and "JIRA_PROJECT" in d.bekleyen
    assert home.temizlenen  # type: ignore[attr-defined]
    # Home değeri değiştirir ve sır referansını döndürür; ETag yeni.
    home.yanit = ornek_yanit(
        etag="v2",
        env={"TP_DENETIM_KAPISI": "off", "JIRA_PROJECT": "ESKI"},
        env_secrets={"JIRA_READ_TOKEN": home.yanit["env_secrets"]["JIRA_READ_TOKEN"].replace(
            "latest", "2")},
    )  # fmt: skip
    d = durum.yenile("core-api")
    assert os.environ["TP_DENETIM_KAPISI"] == "off"
    # TP_CT_SON_KOSU Home'dan çekildi: açılış değerine (yoktu) döner.
    assert "TP_CT_SON_KOSU" not in os.environ
    assert d.bekleyen == ["JIRA_READ_TOKEN"]
    assert durum.ozet()["bekleyen"] == ["JIRA_READ_TOKEN"]


def test_304_tekrar_uygulamaz(home: SahteHome) -> None:
    durum.yenile()
    n = len(home.temizlenen)  # type: ignore[attr-defined]
    durum.yenile()
    assert home.istekler[-1][2].get("If-None-Match") == "v1"
    assert len(home.temizlenen) == n  # type: ignore[attr-defined]


def test_home_kapali_lkg_yoksa_env(home: SahteHome) -> None:
    home.kapali = True
    d = durum.yenile()
    assert d.kaynak == "env" and durum.ozellikler() is None and durum.ozellik_acik("ios")


def test_home_kapali_lkg_ile(home: SahteHome) -> None:
    durum.yenile()
    durum.reset()
    durum.configure(http=SahteHome(kapali=True), id_token=lambda a: "x", temizle=lambda: None)
    d = durum.yenile()
    assert d.kaynak == "lkg" and durum.ozellikler() == {
        "web": True, "android": True, "ios": False, "windows": True, "ai_agent": False,
    }  # fmt: skip


def test_arka_plan_yenileyici(home: SahteHome, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_CONFIG_YENILEME_S", "10")
    monkeypatch.setattr(
        durum, "_dongu", lambda servis, aralik: durum._DUR.wait(0.01) or durum.yenile(servis)
    )
    durum.baslat("core-worker")
    time.sleep(0.05)
    assert home.sayi("/v1/config/effective") >= 2
    durum.durdur()


# ------------------------------------------------------------------ özellik kapısı


def test_ozellik_kapisi(home: SahteHome) -> None:
    durum.yenile()
    kapi.platform_gerekli("web")
    kapi.platform_gerekli("android")
    with pytest.raises(kapi.OzellikKapali) as e:
        kapi.platform_gerekli("ios")
    assert e.value.status_code == 409 and e.value.kod == "ozellik_kapali"
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as h:
        kapi.ai_agent_gerekli()
    assert h.value.status_code == 404


def test_hata_kosusu_ve_codegen_kapisi(home: SahteHome) -> None:
    durum.yenile()
    from tp_core.features.codegen import service as cg
    from tp_core.features.hata_kosusu import service as hk

    assert hk.platformlari_dogrula(["android", "web"]) == ["web", "android"]
    with pytest.raises(kapi.OzellikKapali):
        hk.platformlari_dogrula(["web", "ios"])
    with pytest.raises(cg.PlatformKapali) as e:
        cg._platform_acik_mi("ios")
    assert isinstance(e.value, cg.CodegenRejected) and e.value.kod == "ozellik_kapali"


def test_agent_probe_router_kapisi() -> None:
    from tp_core.features.agent_probe import api

    assert any(d.dependency is kapi.ai_agent_gerekli for d in api.router.dependencies)


# ------------------------------------------------------------------ bağlantı erişim token'ı


def _erisim(home: SahteHome) -> None:
    home.yanit = ornek_yanit(
        connections={
            "jira": {"mode": "oauth", "public": {"site_url": "https://ornek.atlassian.net",
                                                 "cloud_id": "c", "account_id": SAHIP}},
            "github": {"mode": "app", "public": {"installation_id": "1"}},
        }
    )  # fmt: skip
    home.erisim = {
        "jira": {"mode": "oauth", "access_token": "jira-tok", "expires_at": time.time() + 3600,
                 "base_url": JIRA_TABANI},
        "github": {"mode": "app", "access_token": "gh-tok",
                   "expires_at": "2099-01-01T00:00:00Z", "base_url": None},
    }  # fmt: skip


def test_token_yalniz_yetkili_surecte(home: SahteHome) -> None:
    _erisim(home)
    durum.yenile()
    with pytest.raises(baglanti.BaglantiHatasi, match="core-worker"):
        baglanti.token_al("jira")
    assert home.sayi("/v1/connections/access-token") == 0


def test_token_onbellek_ve_yenileme(home: SahteHome, monkeypatch: pytest.MonkeyPatch) -> None:
    _erisim(home)
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    durum.yenile()
    t1 = baglanti.token_al("jira")
    t2 = baglanti.token_al("jira")
    assert t1 is t2 and t1.access_token == "jira-tok" and "jira-tok" not in repr(t1)
    assert home.sayi("/v1/connections/access-token") == 1
    _m, _u, bas, govde = home.istekler[-1]
    assert bas["Authorization"] == f"Bearer id:{HOME}"
    assert govde is not None and b'"type": "jira"' in govde and b"aaaabbbbcccc" in govde
    # Bitişe YENILEME_PAYI_S'den az kala yenilenir.
    home.erisim["jira"]["expires_at"] = time.time() + 30
    baglanti.gecersiz_kil("jira")
    baglanti.token_al("jira")
    baglanti.token_al("jira")
    assert home.sayi("/v1/connections/access-token") == 3


def test_token_kipinde_409(home: SahteHome, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    home.erisim_durum = 409
    durum.yenile()
    with pytest.raises(baglanti.TokenKipinde):
        baglanti.token_al("github")


def test_jira_base_url_disari_token_gitmez(
    home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    _erisim(home)
    home.erisim["jira"]["base_url"] = "https://saldirgan.example"
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    durum.yenile()
    with pytest.raises(baglanti.BaglantiHatasi, match=r"api\.atlassian\.com"):
        baglanti.token_al("jira")


# ---------------------------------------------------------- Jira OAuth istemcisi + PO kuralı


def _jira_sunucusu(gorulen: list[httpx.Request], changelog: list[dict]) -> httpx.MockTransport:
    def h(req: httpx.Request) -> httpx.Response:
        gorulen.append(req)
        if req.url.path.endswith("/myself"):
            return httpx.Response(200, json={"accountId": SAHIP})
        if "/changelog" in req.url.path:
            return httpx.Response(200, json={"values": changelog, "isLast": True})
        return httpx.Response(200, json={})

    return httpx.MockTransport(h)


def _etiket(kim: str) -> dict:
    return {
        "id": kim[-3:], "created": "2026-11-15T10:00:00.000+0000",
        "author": {"accountId": kim},
        "items": [{"field": "labels", "fromString": "", "toString": "tp-po-approved"}],
    }  # fmt: skip


def test_jira_oauth_istemcisi_ve_po_kurali(
    home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.integrations import jira

    _erisim(home)
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    monkeypatch.setenv("TP_TEST_TEK_HESAP", "1")  # OAuth'ta görev ayrılığını kapatamaz
    monkeypatch.setenv("JIRA_PO_ACCOUNT_IDS", f"{PO},{SAHIP}")
    jira.get_jira_settings.cache_clear()
    durum.yenile()
    gorulen: list[httpx.Request] = []
    istemci = jira.get_jira(http=httpx.Client(transport=_jira_sunucusu(
        gorulen, [_etiket(SAHIP), _etiket(PO)])))  # fmt: skip
    assert istemci.oauth and istemci.base_url == JIRA_TABANI
    assert istemci.browse_url == "https://ornek.atlassian.net"
    s = jira.get_jira_settings()
    # Bağlantı sahibi PO listesinden düşer ve bot sayılır.
    assert SAHIP not in s.po_accounts and PO in s.po_accounts
    assert SAHIP.lower() in s.bot_kimlikleri
    onaylar = istemci.po_approvals("TPD-1", s.po_accounts | {SAHIP})
    # Sahip listeye zorla eklense de (bot dışlaması) yalnız PO'nun etiketi onay sayılır.
    assert len(onaylar) == 1 and PO in {onaylar[0].author, *onaylar[0].author_ids}
    assert all(r.headers["Authorization"] == "Bearer jira-tok" for r in gorulen)
    assert all(str(r.url).startswith(JIRA_TABANI) for r in gorulen)
    jira.get_jira_settings.cache_clear()


def test_jira_oauth_core_apide_kullanilamaz(home: SahteHome) -> None:
    from tp_core.integrations import jira

    _erisim(home)
    durum.yenile()
    with pytest.raises(jira.JiraConfigError, match="OAuth"):
        jira.get_jira()


def test_jira_oauth_401_bir_kez_yeniler(home: SahteHome, monkeypatch: pytest.MonkeyPatch) -> None:
    _erisim(home)
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    durum.yenile()
    sayac = {"n": 0}

    def h(req: httpx.Request) -> httpx.Response:
        sayac["n"] += 1
        return httpx.Response(401 if sayac["n"] == 1 else 200, json={})

    with httpx.Client(transport=httpx.MockTransport(h), auth=baglanti.HomeJiraAuth()) as c:
        assert c.get(JIRA_TABANI + "/rest/api/3/myself").status_code == 200
    assert home.sayi("/v1/connections/access-token") == 2


def test_jira_token_kipi_bugunku_gibi(monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.integrations import jira

    durum.reset()
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    s = jira.JiraSettings(JIRA_BASE_URL="http://jira-sim:8090")  # type: ignore[call-arg]
    istemci = jira.get_jira(s)
    assert not istemci.oauth and isinstance(istemci._read_auth, httpx.BasicAuth)


# ------------------------------------------------------------------ GitHub App (forge)


def test_github_app_kipi(home: SahteHome, monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.integrations.forge import ForgeValidationError
    from tp_core.integrations.forge_github import GitHubForge, TokenAuth

    _erisim(home)
    durum.yenile()
    env = {"GITHUB_REPO": "org/repo", "GITHUB_TOKEN": "pat-yok-sayilir"}
    with pytest.raises(ForgeValidationError, match="core-worker"):
        GitHubForge.from_env(env)
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    gorulen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        gorulen.append(req)
        return httpx.Response(200, json={"sha": "a" * 40})

    forge = GitHubForge.from_env(env, transport=httpx.MockTransport(h))
    assert isinstance(forge._auth, baglanti.HomeGitHubAuth)
    forge.head_sha("main")
    assert gorulen[-1].headers["Authorization"] == "Bearer gh-tok"
    # token kipinde bugünkü yol (env PAT).
    durum.reset()
    monkeypatch.delenv("CONFIG_SOURCE")
    assert isinstance(GitHubForge.from_env(env)._auth, TokenAuth)


# --------------------------------------------------------- A1: çalışma anında hedef–sır bağı


def test_calisma_aninda_bagli_sirlar_silinir_ve_geri_gelir(
    home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_MERGE_TOKEN", "insan-tokeni")
    monkeypatch.setenv("TP_FORGE_REMOTE_TOKEN", "ayna")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    durum.yenile("core-worker")
    assert os.environ["GITHUB_MERGE_TOKEN"] == "insan-tokeni"
    # Home hedefi çalışırken değiştirir (yeniden başlatmada uygulanacak) ve env_unset gönderir:
    # bağlı sırlar beklemeden süreçten silinir.
    home.yanit = ornek_yanit(
        etag="v2",
        env={"GITHUB_API_URL": "https://kotu.example.test"},
        env_unset=["TP_FORGE_REMOTE_TOKEN"],
    )
    n = len(home.temizlenen)  # type: ignore[attr-defined]
    durum.yenile("core-worker")
    assert "GITHUB_MERGE_TOKEN" not in os.environ  # yerel kural
    assert "TP_FORGE_REMOTE_TOKEN" not in os.environ  # Home env_unset
    assert durum.ozet()["kaldirilan"] == [
        "GITHUB_ACTIONS_READ_TOKEN", "GITHUB_MERGE_TOKEN", "GITHUB_READ_TOKEN", "GITHUB_TOKEN",
        "TP_FORGE_REMOTE_TOKEN",
    ]  # fmt: skip
    assert len(home.temizlenen) > n  # type: ignore[attr-defined]
    # Home hedefi geri çeker: silinen değerler geri konur.
    home.yanit = ornek_yanit(etag="v3")
    durum.yenile("core-worker")
    assert os.environ["GITHUB_MERGE_TOKEN"] == "insan-tokeni"
    assert os.environ["TP_FORGE_REMOTE_TOKEN"] == "ayna"
    assert durum.ozet()["kaldirilan"] == []
