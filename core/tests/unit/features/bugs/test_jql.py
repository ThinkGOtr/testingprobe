"""Mükerrer araması JQL'inin güvenliği (kaçış, ayrılmış sözcükler, enjeksiyon) — saf birim."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tp_core.features.bugs import jql

REPO = Path(__file__).resolve().parents[5]
SIM_SRC = REPO / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim import jql as sim_jql  # noqa: E402


def test_quote_kacis() -> None:
    assert jql.quote('a"b') == '"a\\"b"'
    assert jql.quote("a\\b") == '"a\\\\b"'
    assert jql.quote('x\\" OR project = "Y') == '"x\\\\\\" OR project = \\"Y"'
    # Kontrol karakterleri (satır sonu dahil) atılır.
    assert jql.quote("a\nb\x00c") == '"abc"'


def test_proje_anahtari_dogrulanir() -> None:
    assert jql.check_project("TPD") == "TPD"
    for kotu in ("tpd", 'TPD" OR 1=1', "TPD OR project = X", "", "1TPD"):
        with pytest.raises(ValueError):
            jql.duplicate_search_jql(kotu, ["kampanya"])


def test_terimler_yalnizca_kelime() -> None:
    terimler = jql.key_terms(
        [
            'Kampanya") OR project = "XYZ',
            "indirim* AND sepette~ NOT hesaplanıyor",
            "6 adet; bedava? (1) {2} [3] ^ \\ / : +-&|!",
            "AND OR NOT TO and or not order by",
        ]
    )
    beklenen = ["kampanya", "project", "xyz", "indirim", "sepette", "hesaplanıyor", "bedava"]
    assert terimler == beklenen
    for t in terimler:
        assert t.isalnum()
        assert t not in jql.JQL_AYRILMIS


def test_terim_siniri_ve_tekrarsiz() -> None:
    metin = " ".join(f"kelime{i}" for i in range(30)) + " kelime1 kelime2"
    terimler = jql.key_terms([metin])
    assert len(terimler) == jql.MAX_TERIM
    assert len(set(terimler)) == len(terimler)


def test_ayrilmis_ve_durak_sozcukleri_atilir() -> None:
    assert jql.key_terms(["select from where and or not empty null order"]) == []
    assert jql.key_terms(["ve ile için beklenen gerçekleşen test"]) == []


def test_sorgu_bicimi() -> None:
    q = jql.duplicate_search_jql("TPD", ["Kampanya", "indirim"])
    assert q == (
        'project = "TPD" AND issuetype = "Bug" AND statusCategory != "Done" AND '
        '(text ~ "kampanya" OR text ~ "indirim") ORDER BY updated DESC'
    )
    assert jql.duplicate_search_jql("TPD", ["ve", "AND", "1"]) is None


def test_enjeksiyon_ayristiricida_tek_ifade_kalir() -> None:
    """Saldırgan metin sorgunun yapısını değiştiremez: jira-sim ayrıştırıcısıyla da geçerli."""
    zararli = 'x" OR project != "TPD" OR text ~ "y'
    q = jql.duplicate_search_jql("TPD", jql.key_terms([zararli, "kampanya"]))
    assert q is not None
    parsed = sim_jql.parse(q)
    # Proje kısıtı her zaman uygulanır: başka projedeki kayıt eşleşmez.
    baska = {
        "project": ["XYZ"],
        "issuetype": ["Bug"],
        "statuscategory": ["To Do", "new"],
        "text": "kampanya",
        "key": ["XYZ-1"],
    }
    assert not parsed.predicate(baska)
    ayni = {**baska, "project": ["TPD"], "key": ["TPD-9"]}
    assert parsed.predicate(ayni)
    kapali = {**ayni, "statuscategory": ["Done", "done"]}
    assert not parsed.predicate(kapali)


def test_etiket_sorgusu() -> None:
    assert jql.label_jql("TPD", "tp-1") == 'project = "TPD" AND labels = "tp-1"'
    assert '\\"' in jql.label_jql("TPD", 'tp-"x')


def test_issue_key() -> None:
    assert jql.is_issue_key("TPD-5")
    for kotu in ("tpd-5", "TPD-", "TPD-5 OR", None, 5, "TPD-5\n"):
        assert not jql.is_issue_key(kotu)


def test_ortusme_puani() -> None:
    terimler = ["kampanyalı", "bedava", "sipariş"]
    assert jql.overlap_score(terimler, "Kampanya indirimi; 6 adet alımda bedava ürün") == 2
    assert jql.overlap_score(terimler, "Giriş sayfası") == 0


def test_alan_genel_terimleri_atilir() -> None:
    """ac4, bayi*, sipariş* her kayıtta geçer: aday yapmaz (alakasız TPD-6 ile eşleşmesin)."""
    ac4 = (
        'AC4: Sipariş tutarı bayinin kredi limitini aşarsa "Kredi limiti aşıldı" uyarısı '
        "gösterilir ve sipariş onaylanamaz."
    )
    terimler = jql.key_terms([ac4, "Bayi siparişi"])
    assert "ac4" not in terimler
    assert not any(t.startswith(("bayi", "sipariş")) for t in terimler)
    assert "kredi" in terimler and "limitini" in terimler
