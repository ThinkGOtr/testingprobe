"""Rapor üreticisi: tablo, sayılar, çıkış kodu, bütçe, sır maskeleme, dosyalar."""

from __future__ import annotations

import json

from tp_rehearsal import report
from tp_rehearsal.env import Sirlar
from tp_rehearsal.runner import ATLANDI, FAIL, PASS, UYARI, AdimSonucu, Kontrol


def _adim(no: str, durum: str, sure: float = 1.0, butce: float = 10.0, **kw) -> AdimSonucu:
    return AdimSonucu(no, f"Adım {no}", "analist", "2", durum, sure, butce, **kw)


def _ozet(adimlar, toplam: float = 60.0, kip: str = "prova", **kw) -> report.ProvaOzeti:
    return report.ProvaOzeti(
        kip=kip,
        baslangic="2026-11-01T09:00:00+03:00",
        bitis="2026-11-01T09:01:00+03:00",
        toplam_s=toplam,
        toplam_butce_s=1500,
        model_modu="replay",
        replay_strict="1",
        adimlar=adimlar,
        **kw,
    )


def test_tum_pass_basarili_ve_cikis_sifir():
    oz = _ozet([_adim("A1", PASS), _adim("A2", UYARI)])
    assert oz.basarili
    assert oz.cikis_kodu() == 0
    assert oz.sayilar() == {PASS: 1, FAIL: 0, ATLANDI: 0, UYARI: 1}


def test_fail_ya_da_atlandi_cikis_bir():
    assert _ozet([_adim("A1", PASS), _adim("A2", FAIL)]).cikis_kodu() == 1
    assert _ozet([_adim("A1", PASS), _adim("A2", ATLANDI)]).cikis_kodu() == 1
    assert _ozet([]).cikis_kodu() == 1, "boş prova başarılı sayılmaz"


def test_toplam_butce_asimi_provada_fail_denetimde_degil():
    assert not _ozet([_adim("A1", PASS)], toplam=1501).basarili
    assert _ozet([_adim("A1", PASS)], toplam=1501, kip="denetim").basarili


def test_markdown_tablo_satirlari_ve_replay_etiketi():
    oz = _ozet(
        [
            _adim("A1", PASS, 2.5, 30),
            _adim("A2", FAIL, 75, 60, hata="zaman aşımı: x | y"),
            _adim("A3", ATLANDI, 0, 30, hata="önceki adım başarısız"),
        ],
        notlar=["not bir"],
    )
    md = report.markdown(oz)
    assert md.startswith("# Demo provası — BAŞARISIZ")
    assert "REPLAY (kayıtlı/hazırlanmış çıktı — canlı model değil)" in md
    assert "| A1 | Adım A1 | analist | 2 | ✅ PASS | 2.5 sn | 30.0 sn |  |" in md
    # Bütçe aşımı işareti ve tablo için kaçışlanmış dikey çizgi
    assert (
        "| A2 | Adım A2 | analist | 2 | ❌ FAIL | 1 dk 15 sn ⏱ | 1 dk 00 sn | "
        "zaman aşımı: x \\| y |" in md
    )
    assert "| A3 | Adım A3 | analist | 2 | ⏭ ATLANDI | — |" in md
    assert "## Başarısız adımlar" in md and "### A2 Adım A2" in md
    assert "- not bir" in md


def test_markdown_uyari_notu_ve_kanit():
    a = _adim(
        "P0", UYARI, kontroller=[Kontrol("strict", UYARI, "TP_REPLAY_STRICT='0'")], kanit={"k": 1}
    )
    md = report.markdown(_ozet([a]))
    assert "strict: TP_REPLAY_STRICT='0'" in md
    assert '"k": 1' in md


def test_live_kip_etiketi_degistirilmez():
    oz = _ozet([_adim("A1", PASS)])
    oz.model_modu = "live"
    assert "**live**" in report.markdown(oz)


def test_json_rapor_alanlari():
    oz = _ozet([_adim("A1", PASS, 12, 10)])
    j = report.json_rapor(oz)
    assert j["basarili"] is True and j["cikis_kodu"] == 0
    assert j["adimlar"][0]["butce_asildi"] is True
    assert j["sayilar"][PASS] == 1
    json.dumps(j)  # serileştirilebilir


def test_yaz_dosyalari_uretir_ve_sirlari_maskeler(tmp_path):
    sir = "cok-gizli-parola-123"
    sirlar = Sirlar.ortamdan({"SEED_USER_PASSWORD": sir})
    a = _adim("A1", FAIL, hata=f"giriş başarısız: {sir}", kanit={"govde": sir})
    dizin = report.yaz(_ozet([a]), tmp_path / "r", sirlar.maskele, f"log {sir}", f"rol\t{sir}")
    for ad in ("rapor.md", "rapor.json", "komutlar.log", "api-cagrilari.tsv"):
        metin = (dizin / ad).read_text(encoding="utf-8")
        assert sir not in metin, ad
        assert "***" in metin, ad
    assert json.loads((dizin / "rapor.json").read_text(encoding="utf-8"))["cikis_kodu"] == 1


def test_konsol_tablosu_ozet_satiri():
    t = report.konsol_tablosu(_ozet([_adim("A1", PASS), _adim("A2", FAIL)]))
    assert t.splitlines()[0].startswith("#")
    assert "1 PASS · 1 FAIL" in t and t.endswith("BAŞARISIZ")


def test_sure_bicimi():
    assert report._sure(5) == "5.0 sn"
    assert report._sure(125) == "2 dk 05 sn"
    assert report._sure(-1) == "0.0 sn"
