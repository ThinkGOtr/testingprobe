"""JUnit XML + Playwright JSON ayrıştırma (DB'siz): retry, flaky, atlanan, hata, a11y."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.features.ci.helpers import FIXTURES, kosu_yaz
from tp_core.features.ci.parse import (
    KosuDizini,
    RaporHatasi,
    parse_files,
    parse_junit,
    parse_reports,
    sayilar,
)

GEN = "generated/tpd-1-kampanya.spec.ts"


def _ayristir(tmp_path: Path):
    rep = kosu_yaz(tmp_path, "ci-x-1", sha="a" * 40)
    yerel = tmp_path / "runs" / "ci-x-1"
    sonuc = yerel / "src" / "e2e" / "results"
    return parse_files(
        sonuc / "junit.xml",
        sonuc / "results.json",
        KosuDizini(rep["run"]["artifacts_dir"], yerel),
    )


def test_junit_ve_json_birlesir_durumlar_dogru(tmp_path: Path) -> None:
    ayr = _ayristir(tmp_path)
    t = {x.test_adi: x for x in ayr.testler}
    assert ayr.raporlar == {"junit": True, "json": True}
    # Demo-B: bugünkü kodda 7 adet → 1 bedava geçer; 6 adet sınırı assertion ile kalır.
    assert t["TPD-1 › 7 adet Portakal Gazozu → 1 adet bedava"].sonuc == "passed"
    alti = t["TPD-1 › 6 adet → bedava yok"]
    assert alti.sonuc == "failed"
    assert alti.retry == 1
    assert alti.dosya == GEN
    assert "\x1b" not in (alti.hata_mesaji or "")
    assert 'Expected: "0"' in (alti.hata_mesaji or "")
    assert t["TPD-1 › Minimum sipariş tutarı 750,00 TL uyarısı"].sonuc == "passed"
    flaky = t["TPD-1 › Sepete ekle sepet sayacını artırır"]
    assert (flaky.sonuc, flaky.retry, flaky.sure_ms) == ("flaky", 1, 6600)
    assert [d["sonuc"] for d in flaky.denemeler] == ["failed", "passed"]
    assert t["Sipariş › geçmiş listelenir"].sonuc == "skipped"
    assert t["Sipariş › onay numarası"].sonuc == "timedout"
    # Yalnızca JUnit'te olan test de yazılır (retry bilgisi yok).
    yalniz = t["Sipariş › yalnızca JUnit'te olan test"]
    assert (yalniz.sonuc, yalniz.retry, yalniz.kaynak_rapor) == ("passed", 0, "junit")
    assert sayilar(ayr.testler) == {
        "toplam": 9,
        "gecen": 4,
        "basarisiz": 3,
        "flaky": 1,
        "atlanan": 1,
    }


def test_a11y_ekleri_govdeden_ve_dosyadan_okunur(tmp_path: Path) -> None:
    ayr = _ayristir(tmp_path)
    t = {x.test_adi: x for x in ayr.testler}
    katalog = t["Erişilebilirlik @a11y › katalog sayfası"]
    assert (katalog.a11y_ihlal, katalog.a11y_kritik) == (2, 0)
    assert katalog.a11y[0]["etki"] == {"serious": 2, "moderate": 1}
    sepet = t["Erişilebilirlik @a11y › sepet sayfası (uyarı ve satırlarla)"]
    assert (sepet.a11y_ihlal, sepet.a11y_kritik) == (3, 1)
    assert sepet.a11y[0]["kurallar"][0]["id"] == "button-name"


def test_ek_yollari_goreli_ve_kosu_dizini_disindakiler_atilir(tmp_path: Path) -> None:
    ayr = _ayristir(tmp_path)
    t = {x.test_adi: x for x in ayr.testler}
    ekler = t["TPD-1 › 6 adet → bedava yok"].ekler
    assert [e["yol"] for e in ekler] == [
        "src/e2e/results/artifacts/kampanya-6/test-failed-1.png",
        "src/e2e/results/artifacts/kampanya-6/trace.zip",
    ]
    sepet = t["Erişilebilirlik @a11y › sepet sayfası (uyarı ve satırlarla)"]
    assert all("passwd" not in e["yol"] and ".." not in e["yol"] for e in sepet.ekler)
    assert [e["ad"] for e in sepet.ekler] == ["axe-sepet.json"]


def test_yalniz_junit_uyari_verir_retry_sifir() -> None:
    ayr = parse_reports((FIXTURES / "junit.xml").read_bytes(), None)
    assert ayr.raporlar == {"junit": True, "json": False}
    assert any("results.json" in u for u in ayr.uyarilar)
    t = {x.test_adi: x for x in ayr.testler}
    assert t["TPD-1 › 6 adet → bedava yok"].sonuc == "failed"
    assert t["Sipariş › onay numarası"].sonuc == "failed"  # JUnit <error>
    assert t["Sipariş › geçmiş listelenir"].sonuc == "skipped"
    assert all(x.retry == 0 for x in ayr.testler)


def test_yalniz_json_junit_eksik_uyarisi() -> None:
    ham = (FIXTURES / "results.json").read_bytes()
    ayr = parse_reports(None, ham)
    assert any("junit.xml" in u for u in ayr.uyarilar)
    assert len(ayr.testler) == 8


def test_dtd_ve_bozuk_xml_reddedilir() -> None:
    bomba = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuites>&a;</testsuites>'
    with pytest.raises(RaporHatasi):
        parse_junit(bomba)
    with pytest.raises(RaporHatasi):
        parse_junit(b"<testsuites><testcase")
    ayr = parse_reports(b"<bozuk", None)
    assert ayr.testler == []
    assert any("ayrıştırılamadı" in u for u in ayr.uyarilar)


def test_json_rapor_bozuksa_junit_ile_devam() -> None:
    ayr = parse_reports((FIXTURES / "junit.xml").read_bytes(), b"{bozuk")
    assert len(ayr.testler) == 9
    assert ayr.raporlar["json"] is False


def test_rapor_duzeyi_hatalar_uyariya_girer() -> None:
    ham = json.dumps({"suites": [], "errors": [{"message": "config hatası"}], "stats": {}})
    ayr = parse_reports(None, ham.encode())
    assert any("config hatası" in u for u in ayr.uyarilar)


TEKRARLI_JUNIT = """<testsuites><testsuite name="a.spec.ts">
<testcase classname="a.spec.ts" name="S › t" time="1"/>
<testcase classname="a.spec.ts" name="S › t" time="2"><failure message="beklenen 7"/></testcase>
<testcase classname="a.spec.ts" name="S › t" time="1"/>
<testcase classname="a.spec.ts" name="S › u" time="1"/>
<testcase classname="a.spec.ts" name="S › u" time="1"/>
</testsuite></testsuites>""".encode()


def test_yalniz_junit_tekrarlanan_testte_kalan_kaybolmaz() -> None:
    """JSON yokken aynı adlı tekrarlar tek satıra toplanır; bir tekrarın kalması korunur."""
    ayr = parse_reports(TEKRARLI_JUNIT, None)
    t = {x.test_adi: x for x in ayr.testler}
    assert len(ayr.testler) == 2
    assert (t["S › t"].sonuc, t["S › t"].retry, t["S › t"].hata_mesaji) == (
        "failed",
        2,
        "beklenen 7",
    )
    assert [d["sonuc"] for d in t["S › t"].denemeler] == ["passed", "failed", "passed"]
    assert t["S › t"].sure_ms == 4000
    assert (t["S › u"].sonuc, t["S › u"].retry) == ("passed", 1)
    assert sayilar(ayr.testler)["basarisiz"] == 1


def test_json_varken_junit_yalniz_json_anahtarlarina_gore_elenir() -> None:
    jsn = json.dumps(
        {
            "suites": [
                {
                    "title": "a.spec.ts",
                    "file": "a.spec.ts",
                    "suites": [
                        {
                            "title": "S",
                            "specs": [
                                {
                                    "title": "u",
                                    "tests": [
                                        {"status": "expected", "results": [{"status": "passed"}]}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    ).encode()
    ayr = parse_reports(TEKRARLI_JUNIT, jsn)
    t = {x.test_adi: x for x in ayr.testler}
    assert len(ayr.testler) == 2
    # JSON'daki "S › u" JSON'dan gelir; JUnit tekrarları ona karşı elenir.
    assert (t["S › u"].kaynak_rapor, t["S › u"].retry) == ("json", 0)
    # JSON'da olmayan "S › t" JUnit'ten gelir ve kalan tekrar korunur.
    assert t["S › t"].sonuc == "failed" and t["S › t"].kaynak_rapor == "junit"


def test_utf16_dtd_varlik_reddedilir() -> None:
    """Bayt araması UTF-16'da DTD'yi görmez; expat ön taraması belgenin kodlamasıyla yakalar."""
    belge = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE t [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<testsuites><testcase name="&b;" classname="c"/></testsuites>'
    ).encode("utf-16")
    assert b"<!doctype" not in belge.lower()
    with pytest.raises(RaporHatasi, match="DTD"):
        parse_junit(belge)
    ayr = parse_reports(belge, None)
    assert ayr.testler == [] and any("DTD" in u for u in ayr.uyarilar)
    # DTD'siz UTF-16 belge kabul edilir.
    temiz = '<testsuites><testcase name="x" classname="c"/></testsuites>'.encode("utf-16")
    assert [t.test_adi for t in parse_junit(temiz)] == ["x"]


_JUNIT_GOVDE = (
    '<testsuites><testsuite name="s"><testcase name="t" classname="a.spec.ts" time="0.1"/>'
    "</testsuite></testsuites>"
)
_JSON_BIR_TEST = json.dumps(
    {
        "suites": [
            {
                "title": "a.spec.ts",
                "file": "a.spec.ts",
                "specs": [{"title": "t", "tests": [{"status": "expected", "results": []}]}],
            }
        ]
    }
).encode()


@pytest.mark.parametrize(
    "xml",
    [
        # Bildirilen çok baytlı kodlama, BOM yok → expat ValueError.
        ('<?xml version="1.0" encoding="utf-16-le"?>' + _JUNIT_GOVDE).encode("utf-16-le"),
        # Bilinmeyen kodlama → expat LookupError.
        ('<?xml version="1.0" encoding="x-bogus"?>' + _JUNIT_GOVDE).encode(),
    ],
    ids=["utf16le-bomsuz", "bilinmeyen-kodlama"],
)
def test_desteklenmeyen_junit_kodlamasi_uyari_json_islenir(xml: bytes) -> None:
    with pytest.raises(RaporHatasi):
        parse_junit(xml)
    ayr = parse_reports(xml, _JSON_BIR_TEST)
    assert ayr.raporlar == {"junit": False, "json": True}
    assert [t.sonuc for t in ayr.testler] == ["passed"]
    assert any("kodlama" in u or "ayrıştırılamadı" in u for u in ayr.uyarilar)


def test_beklenmeyen_ayristirici_hatasi_rapor_kaybettirmez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tp_core.features.ci import parse as p

    def _patla(_: bytes) -> list:
        raise LookupError("beklenmedik")

    monkeypatch.setattr(p, "parse_junit", _patla)
    ayr = p.parse_reports(b"<x/>", _JSON_BIR_TEST)
    assert ayr.raporlar == {"junit": False, "json": True}
    assert any("beklenmedik" in u for u in ayr.uyarilar)


def _kosu_dizini(tmp_path: Path) -> tuple[Path, Path]:
    yerel = tmp_path / "runs" / "ci-x-9"
    sonuc = yerel / "src" / "e2e" / "results"
    sonuc.mkdir(parents=True)
    return yerel, sonuc


def test_sembolik_bag_rapor_izlenmez(tmp_path: Path) -> None:
    yerel, sonuc = _kosu_dizini(tmp_path)
    gizli = tmp_path / "gizli.txt"
    gizli.write_text("SECRET=1")
    (sonuc / "junit.xml").symlink_to(gizli)
    (sonuc / "results.json").write_bytes(_JSON_BIR_TEST)
    ayr = parse_files(sonuc / "junit.xml", sonuc / "results.json", KosuDizini(str(yerel), yerel))
    assert ayr.raporlar == {"junit": False, "json": True}
    assert any("sembolik bağ" in u for u in ayr.uyarilar)
    assert not any("SECRET" in u for u in ayr.uyarilar)


def test_dev_zero_bagi_bloklamaz(tmp_path: Path) -> None:
    yerel, sonuc = _kosu_dizini(tmp_path)
    (sonuc / "results.json").symlink_to("/dev/zero")
    (sonuc / "junit.xml").write_text(_JUNIT_GOVDE)
    ayr = parse_files(sonuc / "junit.xml", sonuc / "results.json", KosuDizini(str(yerel), yerel))
    assert ayr.raporlar == {"junit": True, "json": False}
    assert any("results.json" in u and "sembolik bağ" in u for u in ayr.uyarilar)


def test_ara_dizin_bagi_kosu_dizini_disina_cikamaz(tmp_path: Path) -> None:
    yerel = tmp_path / "runs" / "ci-x-9"
    (yerel / "src" / "e2e").mkdir(parents=True)
    dis = tmp_path / "dis"
    dis.mkdir()
    (dis / "junit.xml").write_text(_JUNIT_GOVDE)
    (yerel / "src" / "e2e" / "results").symlink_to(dis, target_is_directory=True)
    sonuc = yerel / "src" / "e2e" / "results"
    ayr = parse_files(sonuc / "junit.xml", None, KosuDizini(str(yerel), yerel))
    assert ayr.raporlar["junit"] is False
    assert any("koşu dizininin dışında" in u for u in ayr.uyarilar)


def test_fifo_ve_aygit_reddedilir(tmp_path: Path) -> None:
    import os

    from tp_core.features.ci.parse import _oku

    yerel, sonuc = _kosu_dizini(tmp_path)
    fifo = sonuc / "junit.xml"
    os.mkfifo(fifo)
    with pytest.raises(RaporHatasi, match="normal dosya değil"):
        _oku(fifo, yerel)
    with pytest.raises(RaporHatasi, match="normal dosya değil"):
        _oku(Path("/dev/zero"))


def test_boyut_siniri_st_size_yerine_okunan_bayta_bakar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.ci import parse as p

    yerel, sonuc = _kosu_dizini(tmp_path)
    (sonuc / "results.json").write_bytes(b"x" * 64)
    monkeypatch.setattr(p, "MAX_RAPOR_BAYT", 16)
    with pytest.raises(RaporHatasi, match="çok büyük"):
        p._oku(sonuc / "results.json", yerel)
    assert p._oku(sonuc / "yok.json", yerel) is None


def test_deneme_ayrintisi_adimlar_stack_cikti_sinirli() -> None:
    """Portal ayrıntı paneli: hata + stack + konum, adım ağacı (sınırlı), stdout/stderr (base64)."""
    import base64

    from tp_core.features.ci import parse

    derin = {"title": "d0", "duration": 1}
    for i in range(1, 8):
        derin = {"title": f"d{i}", "duration": 1, "steps": [derin]}
    sonuc = {
        "retry": 1,
        "status": "failed",
        "duration": 50,
        "errors": [{"message": "\x1b[31mboom\x1b[0m", "stack": "S" * 20_000}],
        "steps": [{"title": f"a{i}", "duration": i} for i in range(400)] + [derin],
        "stdout": [{"text": "x" * 10_000}],
        "stderr": [{"buffer": base64.b64encode("uyarı\n".encode()).decode()}],
    }
    d = parse._deneme_ozeti(sonuc)
    assert d["hata"]["mesaj"] == "boom"  # ANSI temizlenir
    assert len(d["hata"]["stack"]) <= parse.MAX_STACK + 1
    assert len(d["adimlar"]) == parse.MAX_ADIM  # toplam adım sınırı
    assert len(d["stdout"]) <= parse.MAX_CIKTI + 1
    assert d["stderr"] == "uyarı\n"
    # Derinlik sınırı: ağaç MAX_ADIM_DERINLIK'te kesilir.
    d2 = parse._deneme_ozeti({"status": "passed", "steps": [derin]})
    n, a = 0, d2["adimlar"][0]
    while "adimlar" in a:
        n, a = n + 1, a["adimlar"][0]
    assert n == parse.MAX_ADIM_DERINLIK - 1
    assert "hata" not in d2  # geçen denemede hata alanı yok
