"""Asistanın dar Jira okuyucusu (AI-ASISTAN-PLANI §5.6): yalnız GET, ≤ 2 yorum isteği, kişi verisi
ayıklama, kısıtlı yorum filtresi, süre sınırlı yeniden deneme."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tp_core.integrations import jira as J
from tp_core.integrations.jira_adf import BOT_PREFIX, mention, text_to_adf

BASE = "http://jira-sim:8090"
PO_EMAIL = "po@sim.local"
ANALIST_ID = "712020:analist-1"


def _kisi(email: str | None, account: str, ad: str) -> dict[str, Any]:
    out: dict[str, Any] = {"accountId": account, "displayName": ad}
    if email:
        out["emailAddress"] = email
    return out


def _yorum(i: int, yazar: dict[str, Any], govde: Any, **ek: Any) -> dict[str, Any]:
    return {
        "id": str(i),
        "author": yazar,
        "body": govde,
        "created": f"2026-11-0{1 + i % 2}T10:00:00.000+0000",
        "jsdPublic": True,
        **ek,
    }


class SahteJira:
    """`MockTransport` işleyicisi: issue + yorumlar (`startAt`/`maxResults`), istek kaydı."""

    def __init__(self, yorumlar: list[dict[str, Any]], aciklama: Any = None) -> None:
        self.yorumlar = yorumlar
        self.aciklama = aciklama or text_to_adf("Açıklama")
        self.istekler: list[httpx.Request] = []
        self.yanit_kodu: dict[str, list[tuple[int, dict[str, str]]]] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.istekler.append(req)
        yol = req.url.path
        kuyruk = self.yanit_kodu.get(yol)
        if kuyruk:
            kod, basliklar = kuyruk.pop(0)
            return httpx.Response(kod, json={"errorMessages": ["x"]}, headers=basliklar)
        if yol.endswith("/comment"):
            bas = int(req.url.params.get("startAt", 0))
            n = int(req.url.params.get("maxResults", 5000))
            return httpx.Response(
                200,
                json={
                    "startAt": bas,
                    "maxResults": n,
                    "total": len(self.yorumlar),
                    "comments": self.yorumlar[bas : bas + n],
                },
            )
        if yol.startswith("/rest/api/3/issue/"):
            return httpx.Response(
                200,
                json={
                    "key": "TPD-3",
                    "fields": {
                        "summary": "Sepet",
                        "description": self.aciklama,
                        "labels": ["tp"],
                        "status": {"name": "To Do"},
                        "issuetype": {"name": "Story"},
                        "reporter": _kisi("rapor@ornek.com", "acc-r", "Rapor Eden"),
                        "updated": "2026-11-02T10:00:00.000+0000",
                    },
                },
            )
        return httpx.Response(404, json={"errorMessages": ["yok"]})


def _okuyucu(
    sahte: SahteJira,
    *,
    toplam: float = 12.0,
    uyku: list[float] | None = None,
    saat: list[float] | None = None,
    takma: dict[str, str] | None = None,
) -> J.JiraOkuyucu:
    ayar = J.JiraSettings(
        JIRA_BASE_URL=BASE,
        JIRA_HESAP_ANALIST=ANALIST_ID,
    )
    zaman = saat if saat is not None else [0.0]
    return J.get_jira_okuma(
        8.0,
        toplam,
        settings=ayar,
        transport=httpx.MockTransport(sahte),
        takma_adlar=takma,
        sleep=(uyku.append if uyku is not None else lambda _s: None),
        saat=lambda: zaman[0],
    )


def test_okuyucuda_yazma_yontemi_yok() -> None:
    ok = _okuyucu(SahteJira([]))
    for ad in (
        "add_comment",
        "add_comment_adf",
        "add_labels",
        "remove_labels",
        "create_issue",
        "edit_issue",
        "update_description",
        "link_issues",
        "transition",
        "delete_issue",
        "delete_comment",
        "search",
        "get_comments",
        "raw_fields",
        "myself",
    ):
        assert not hasattr(ok, ad), ad


@pytest.mark.parametrize("yontem", ["POST", "PUT", "DELETE", "PATCH"])
def test_get_disi_istek_transportta_reddedilir(yontem: str) -> None:
    sahte = SahteJira([])
    ok = _okuyucu(sahte)
    with pytest.raises(J.JiraYalnizOkuma):
        ok._http.request(yontem, f"{BASE}/rest/api/3/issue/TPD-3/comment", json={})
    assert sahte.istekler == []  # ağa hiç çıkmadı


def test_okuma_kimligi_kullanilir_yazma_kimligi_okunmaz() -> None:
    sahte = SahteJira([])
    ayar = J.JiraSettings(
        JIRA_BASE_URL="https://ornek.atlassian.net",
        JIRA_READ_EMAIL="okuma@ornek.com",
        JIRA_READ_TOKEN="okuma-" + "belirteci",
        JIRA_WRITE_EMAIL="yazma@ornek.com",
        JIRA_WRITE_TOKEN="yazma-" + "belirteci",
    )
    ok = J.get_jira_okuma(8, 12, settings=ayar, transport=httpx.MockTransport(sahte))
    ok.get_issue("TPD-3")
    yetki = sahte.istekler[0].headers["Authorization"]
    assert yetki == httpx.BasicAuth("okuma@ornek.com", "okuma-belirteci")._auth_header
    assert ok.issue_url("TPD-3") == "https://ornek.atlassian.net/browse/TPD-3"


def test_simulatorde_sim_okuma_kullanicisi() -> None:
    sahte = SahteJira([])
    _okuyucu(sahte).get_issue("TPD-3")
    beklenen = httpx.BasicAuth(*J.SIM_READ)._auth_header
    assert sahte.istekler[0].headers["Authorization"] == beklenen


def test_son_yorumlar_101_yorumda_iki_istekle_son_n() -> None:
    kisi = _kisi(None, "acc-x", "X")
    sahte = SahteJira([_yorum(i, kisi, text_to_adf(f"yorum {i}")) for i in range(105)])
    sayfa = _okuyucu(sahte).son_yorumlar("TPD-3", 5)
    assert len(sahte.istekler) == 2
    assert sahte.istekler[0].url.params["maxResults"] == "1"
    assert sahte.istekler[1].url.params["startAt"] == "100"
    assert sahte.istekler[1].url.params["maxResults"] == "5"
    assert sayfa.toplam == 105
    assert [y.metin for y in sayfa.yorumlar] == [f"yorum {i}" for i in range(100, 105)]


def test_son_yorumlar_tek_ya_da_sifir_yorumda_tek_istek() -> None:
    sahte = SahteJira([])
    assert _okuyucu(sahte).son_yorumlar("TPD-3", 5).toplam == 0
    assert len(sahte.istekler) == 1
    sahte = SahteJira([_yorum(1, _kisi(None, "a", "A"), text_to_adf("tek"))])
    sayfa = _okuyucu(sahte).son_yorumlar("TPD-3", 5)
    assert len(sahte.istekler) == 1 and [y.metin for y in sayfa.yorumlar] == ["tek"]


def test_kisitli_yorumlar_elenir_ve_sayilir() -> None:
    k = _kisi(None, "a", "A")
    sahte = SahteJira(
        [
            _yorum(1, k, text_to_adf("açık")),
            _yorum(2, k, text_to_adf("rol kısıtlı GIZLI"), visibility={"type": "role"}),
            _yorum(3, k, text_to_adf("iç not GIZLI"), jsdPublic=False),
        ]
    )
    sayfa = _okuyucu(sahte).son_yorumlar("TPD-3", 5)
    assert [y.metin for y in sayfa.yorumlar] == ["açık"]
    assert sayfa.kisitli == 2


def test_yazar_etiketleri_ve_mentionlar_kisi_verisi_tasimaz() -> None:
    yabanci = _kisi("ayse.yilmaz@ornek.com", "acc-ayse", "Ayşe Yılmaz")
    baska = _kisi(None, "acc-mehmet", "Mehmet Demir")
    analist = _kisi(None, ANALIST_ID, "Analist Kişi")
    po = _kisi(PO_EMAIL, "acc-po", "Pelin PO")
    bot_govde = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": BOT_PREFIX}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Case üretildi"}]},
        ],
    }
    mentionli = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Bak "},
                    {"type": "mention", "attrs": {"id": "acc-mehmet", "text": "@Mehmet Demir"}},
                    {"type": "text", "text": " ve "},
                    {"type": "mention", "attrs": {"id": ANALIST_ID, "text": "@Analist Kişi"}},
                ],
            }
        ],
    }
    sahte = SahteJira(
        [
            _yorum(1, yabanci, text_to_adf("ilk")),
            _yorum(2, baska, mentionli),
            _yorum(3, analist, text_to_adf("analist yazdı")),
            _yorum(4, po, text_to_adf("onaylıyorum")),
            _yorum(5, _kisi("writer@sim.local", "acc-bot", "Bot"), bot_govde),
            _yorum(6, yabanci, text_to_adf("yine ben")),
        ]
    )
    sayfa = _okuyucu(sahte).son_yorumlar("TPD-3", 10)
    yazarlar = [y.yazar for y in sayfa.yorumlar]
    assert yazarlar == ["Kişi-1", "Kişi-2", "analyst", "PO", J.BOT_ETIKETI, "Kişi-1"]
    assert sayfa.yorumlar[1].metin == "Bak @Kişi-2 ve @analyst"
    assert sayfa.yorumlar[4].metin == "Case üretildi"  # bot imi satırı atılır
    hepsi = repr(sayfa)
    for sizinti in ("Ayşe", "ayse.yilmaz", "acc-ayse", "Mehmet", "acc-mehmet", ANALIST_ID, "Pelin"):
        assert sizinti not in hepsi


def test_takma_adlar_mesaj_boyunca_paylasilir() -> None:
    takma: dict[str, str] = {}
    k1 = _kisi(None, "acc-1", "Bir")
    k2 = _kisi(None, "acc-2", "İki")
    _okuyucu(SahteJira([_yorum(1, k1, text_to_adf("a"))]), takma=takma).son_yorumlar("TPD-3", 5)
    sayfa = _okuyucu(
        SahteJira([_yorum(1, k2, text_to_adf("b")), _yorum(2, k1, text_to_adf("c"))]),
        takma=takma,
    ).son_yorumlar("TPD-3", 5)
    assert [y.yazar for y in sayfa.yorumlar] == ["Kişi-2", "Kişi-1"]


def test_aciklamadaki_mention_ve_raporlayan_modele_gitmez() -> None:
    aciklama = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Sahibi "}, mention("acc-gizli")],
            }
        ],
    }
    aciklama["content"][0]["content"][1]["attrs"]["text"] = "@Gizli Ad"
    issue = _okuyucu(SahteJira([], aciklama=aciklama)).get_issue("TPD-3")
    assert issue.description == "Sahibi @Kişi-1"
    assert "rapor" not in repr(issue) and "Rapor" not in repr(issue)
    assert (issue.summary, issue.status, issue.issue_type, issue.labels) == (
        "Sepet",
        "To Do",
        "Story",
        ["tp"],
    )


def test_retry_after_kalan_sureden_uzunsa_beklenmez() -> None:
    sahte = SahteJira([])
    sahte.yanit_kodu["/rest/api/3/issue/TPD-3"] = [(429, {"Retry-After": "30"})]
    uyku: list[float] = []
    ok = _okuyucu(sahte, toplam=12.0, uyku=uyku)
    with pytest.raises(J.JiraSureAsimi):
        ok.get_issue("TPD-3")
    assert uyku == [] and len(sahte.istekler) == 1


def test_kisa_retry_after_bir_kez_yeniden_denenir() -> None:
    sahte = SahteJira([])
    sahte.yanit_kodu["/rest/api/3/issue/TPD-3"] = [(503, {"Retry-After": "1"})] * 3
    uyku: list[float] = []
    with pytest.raises(J.JiraUnavailable):
        _okuyucu(sahte, uyku=uyku).get_issue("TPD-3")
    assert uyku == [1.0]
    assert len(sahte.istekler) == 2  # max_retries=1


def test_sure_dolunca_istek_atilmaz() -> None:
    sahte = SahteJira([])
    saat = [0.0]
    ok = _okuyucu(sahte, toplam=12.0, saat=saat)
    saat[0] = 12.0
    with pytest.raises(J.JiraSureAsimi):
        ok.get_issue("TPD-3")
    assert sahte.istekler == []


def test_istek_zaman_asimi_kalan_sureyle_sinirli() -> None:
    sahte = SahteJira([])
    saat = [0.0]
    ok = _okuyucu(sahte, toplam=12.0, saat=saat)
    saat[0] = 9.0
    ok.get_issue("TPD-3")
    zaman_asimi = sahte.istekler[0].extensions["timeout"]
    assert zaman_asimi["read"] == pytest.approx(3.0)


@pytest.mark.parametrize("kod,sinif", [(401, J.JiraAuthError), (403, J.JiraPermissionError)])
def test_erisim_hatalari_siniflanir(kod: int, sinif: type[Exception]) -> None:
    sahte = SahteJira([])
    sahte.yanit_kodu["/rest/api/3/issue/TPD-3"] = [(kod, {})]
    with pytest.raises(sinif):
        _okuyucu(sahte).get_issue("TPD-3")
