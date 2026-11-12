"""011 test mimarı 3. tur: bekletme (holdout) seti (#2), bağlayıcı ham geçiş alt sınırı ve ilk
denemenin maskesiz puanlanması (#7), "sepet okunamadı" ayrı kategorisi (#3), prompt kuralları
(#2 risk temelli P1, #3 sepet yazımı, #10 AC parantez kuralı) ve içerik hash'i kapısı."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.gateway import build_eval_sets as bes
from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.gateway.eval_agents import SEPET_OKUNAMADI
from tp_core.gateway.eval_live import BundleRun, _finish_run
from tp_core.gateway.eval_set import (
    HOLDOUT,
    CaseResult,
    alt_kume_ozeti,
    alt_kume_satirlari,
    check_output,
    kural_yeniden_isteme_olcumleri,
    load_set,
    uretim_dagilimi,
    write_report,
)
from tp_core.gateway.evaluation import ICERIK_KAYNAKLARI, evaluation_status, icerik_hash

TODAY = dt.date(2026, 11, 13)

# --------------------------------------------------------------- bekletme seti: yapı


def _ham_set() -> dict[str, Any]:
    return json.loads((RULES / "evaluation" / "case-generation.json").read_text(encoding="utf-8"))


def test_bekletme_bolumu_ayri_ve_load_set_ile_ayni_kosuda() -> None:
    ham = _ham_set()
    bekletme = ham["holdout_cases"]
    assert len(bekletme) == 4 and all(c["alt_kume"] == HOLDOUT for c in bekletme)
    # Ayar bölümü (`cases`) bekletme vakası taşımaz; yükleyici ikisini birleştirir.
    assert not any(c.get("alt_kume") for c in ham["cases"])
    data = load_set(RULES, "case-generation")
    assert [c["id"] for c in data["cases"]] == [c["id"] for c in ham["cases"] + bekletme]
    assert data["runs"] == 3


# Bekletme beklentileri yalnız genel kural denetimleridir: vaka-özel anahtar sözcük / konu /
# metin beklentisi (ezber) yoktur.
GENEL_BEKLENTILER = {
    "ac_coverage",
    "ready_ac_coverage",
    "min_cases",
    "max_cases",
    "not_contains_any",
    "techniques_include",
    "source_grounded",
    "max_p1_orani",
}


def test_bekletme_beklentileri_genel_kural_denetimleri() -> None:
    for case in _ham_set()["holdout_cases"]:
        exp = case["expect"]
        assert set(exp) == GENEL_BEKLENTILER, case["id"]
        assert exp["source_grounded"] is True and exp["max_p1_orani"] == 0.6
        assert exp["not_contains_any"] == bes.FABRICATION_COMMON
        assert exp["ac_coverage"] == exp["ready_ac_coverage"]
        assert exp["min_cases"] == len(exp["ac_coverage"]) and exp["max_cases"] == 15


def test_bekletme_story_leri_ayar_story_leriyle_ve_golden_larla_ortusmez() -> None:
    ham = _ham_set()
    ayar_metni = "\n".join(m["content"] for c in ham["cases"] for m in c["messages"])
    for case in ham["holdout_cases"]:
        icerik = case["messages"][0]["content"]
        assert 'source="testdata:bekletme"' in icerik and "testdata:demo-app" not in icerik
        assert icerik.endswith("Test seviyesi: SYSTEM")
        # Ayar vakalarının ürünleri, kullanıcıları ve mesajları bekletme girdisinde yok.
        for ayar_izi in ("P-001", "bayi1", "750,00", "Hesabınız kilitlendi", "Ürün bulunamadı"):
            assert ayar_izi not in icerik, (case["id"], ayar_izi)
        # Bekletme AC'leri ayar girdisinde geçmez.
        for ac in re.findall(r"^AC\d+: (.+)$", icerik, re.MULTILINE):
            assert ac not in ayar_metni
        # Elle hazırlanmış golden çıktı bekletmeyi ayara çevirirdi: yoktur.
        ad = case["replay_key"]["name"]
        assert not list((RULES / "replay").glob(f"*/golden/**/{ad}.json")), ad


def test_bekletme_set_surumu_ve_kayit_durumu() -> None:
    """Bekletme ayrı paket değildir: prompt dosyası yok, `evaluations.yaml` kaydı yok; kapı
    `case-generation` kaydıyla kapanır (aynı koşu)."""
    assert not (RULES / "prompts" / "case-generation-holdout.md").exists()
    assert not (RULES / "evaluation" / "case-generation-holdout.json").exists()
    assert "holdout" not in (RULES / "evaluations.yaml").read_text(encoding="utf-8")


# --------------------------------------------------------------- rapor: alt kümeler


def _veri(**ek: Any) -> dict[str, Any]:
    return {
        "bundle": "case-generation",
        "purpose": "case_generation",
        "version": 3,
        "runs": 1,
        "cases": [
            {"id": "a", "messages": [], "expect": {}},
            {"id": "h", "alt_kume": HOLDOUT, "messages": [], "expect": {}},
        ],
        **ek,
    }


def test_rapor_bekletmeyi_ayri_satirda_tasir(tmp_path: Path) -> None:
    sonuc = [CaseResult("a", True, [], {"cases": []}), CaseResult("h", False, ["x"], None)]
    ozet = alt_kume_ozeti(_veri(), sonuc)
    assert ozet == {
        "ayar": {"vaka": 1, "gecen": 1, "toplam": 1, "kalan": []},
        "holdout": {"vaka": 1, "gecen": 0, "toplam": 1, "kalan": ["h"]},
    }
    assert alt_kume_satirlari(ozet) == [
        "alt küme ayar: 1/1 geçti",
        "alt küme holdout: 0/1 geçti (kalan: h)",
    ]
    path = write_report(tmp_path, _veri(), sonuc, model="m", provider="p", mode="live", today=TODAY)
    rapor = json.loads(path.read_text(encoding="utf-8"))
    assert rapor["alt_kumeler"]["holdout"]["kalan"] == ["h"]
    # Tek alt kümeli sette alan yok.
    tek = {**_veri(), "cases": _veri()["cases"][:1]}
    assert alt_kume_ozeti(tek, sonuc[:1]) == {}


def _satir(vaka: str, deneme: int, cikti: Any, *, kural: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "eval_vaka": vaka,
        "amac": "case_generation",
        "mod": "live",
        "deneme": deneme,
        "sema_gecerli": True,
        "cikti": cikti,
        "maliyet": 0.1,
        "sure_ms": 1000,
        "ek": {"kural_hatalari": list(kural)} if kural else {},
    }


def test_ham_gecis_alt_kume_basina_ve_maskesiz_puanlanir() -> None:
    """1. deneme son çıktıysa puanlama maskesiz son çıktıyla yapılır (satırdaki maskeli `cikti`
    yer tutucu taşır ve `contains` beklentisini düşürürdü)."""
    veri = _veri()
    mesaj = "Kullanıcı adı veya parola hatalı"
    veri["cases"][0]["expect"] = {"contains": [mesaj]}
    maskesiz = load_golden("case_generation", "TPD-4")["output"]
    maskeli = json.loads(json.dumps(maskesiz, ensure_ascii=False).replace(mesaj, "<METIN_1>"))
    assert check_output("case_generation", veri["cases"][0]["expect"], maskesiz) == []
    assert check_output("case_generation", veri["cases"][0]["expect"], maskeli) != []
    rows = [_satir("a", 1, maskeli), _satir("h", 1, {"cases": []}, kural=("C1: covers: x",))]
    rows.append(_satir("h", 2, {"cases": []}))
    sonuc = [CaseResult("a", True, [], maskesiz), CaseResult("h", True, [], {"cases": []})]
    o = kural_yeniden_isteme_olcumleri(veri, sonuc, rows, "case_generation")
    assert o["ilk_deneme_gecis"] == 1 and o["ilk_deneme_maskeli_puanlama"] == 0
    assert o["alt_kumeler"] == {
        "ayar": {"vaka": 1, "ilk_deneme_gecis": 1, "ilk_deneme_gecis_orani": 1.0},
        "holdout": {"vaka": 1, "ilk_deneme_gecis": 0, "ilk_deneme_gecis_orani": 0.0},
    }
    # Son çıktı yoksa (geçit hatası) maskeli satıra düşülür ve sayılır.
    o2 = kural_yeniden_isteme_olcumleri(
        veri, [CaseResult("a", False, ["x"], None)], rows[:1], "case_generation"
    )
    assert o2["ilk_deneme_maskeli_puanlama"] == 1 and o2["ilk_deneme_gecis"] == 0


# --------------------------------------------------------------- bağlayıcı ham geçiş alt sınırı


def test_case_generation_setinde_ham_gecis_alt_siniri_baglayici() -> None:
    data = load_set(RULES, "case-generation")
    assert data["ham_gecis_alt_siniri"] == 0.6
    o = kural_yeniden_isteme_olcumleri(data, [], [], "case_generation")
    (esik,) = o["esikler"]
    assert esik["ad"] == "ham_gecis_alt_siniri" and esik["bagliyici"] is True
    assert esik["esik"] == 0.6


def _bitir(tmp_path: Path, veri: dict[str, Any], rows: list[dict[str, Any]]) -> BundleRun:
    run = BundleRun("case-generation", purpose="case_generation")
    run.results = [CaseResult("a", True, [], {"cases": []}), CaseResult("h", True, [], None)]
    run.rows = rows
    gw = SimpleNamespace(
        models=SimpleNamespace(purpose=lambda _p: SimpleNamespace(model="m")),
        provider_name="fake",
    )
    _finish_run(
        run,
        tmp_path,
        veri,
        gw,  # type: ignore[arg-type]
        "live",
        TODAY,
        5.0,
        "gönderilmedi",
        1,
        None,
        SimpleNamespace(path=tmp_path / "defter.jsonl"),  # type: ignore[arg-type]
        [],
        False,
    )
    return run


@pytest.mark.parametrize(("sinir", "gecer"), [(0.6, False), (None, True)])
def test_alt_sinir_gecilmezse_tum_vakalar_gecse_de_set_gecmez(
    tmp_path: Path, sinir: float | None, gecer: bool
) -> None:
    """Her vaka (kural yeniden istemesiyle) geçti, ama ilk denemelerin ikisi de kural ihlalli:
    ham oran 0 < 0,6 → bağlayıcı eşikle set geçmez; eşik tanımsızsa yalnız bilgi."""
    veri = _veri(**({"ham_gecis_alt_siniri": sinir} if sinir is not None else {}))
    rows = [
        _satir("a", 1, {"cases": []}, kural=("C1: covers: x",)),
        _satir("a", 2, {"cases": []}),
        _satir("h", 1, {"cases": []}, kural=("C1: covers: x",)),
        _satir("h", 2, {"cases": []}),
    ]
    run = _bitir(tmp_path, veri, rows)
    assert run.olcum is not None and run.olcum["ilk_deneme_gecis_orani"] == 0.0
    assert run.passed is gecer
    rapor = json.loads(run.report.read_text(encoding="utf-8"))  # type: ignore[union-attr]
    assert rapor["olcumler"]["esikler"][0]["bagliyici"] is (sinir is not None)
    assert rapor["alt_kumeler"]["holdout"]["toplam"] == 1


# --------------------------------------------------------------- sepet okunamadı (#3)


def test_sepet_okunamadi_uydurmadan_ayri_listelenir() -> None:
    sonuc = [
        CaseResult("a#k1", False, [f"C2: {SEPET_OKUNAMADI}: tutar '125,00 TL' doğrulanamadı"], {}),
        CaseResult(
            "a#k2", False, ["C1: kaynakta olmayan tutar '501,00 TL' (case'te sepet yok)"], {}
        ),
    ]
    d = uretim_dagilimi(sonuc)
    assert d["sepet_okunamadi"] == ["a#k1"] and d["uydurma"] == ["a#k2"]
    assert d["toplam"]["sepet_okunamadi"] == 1


# --------------------------------------------------------------- prompt kuralları


def _prompt(ad: str) -> str:
    return re.sub(r"\s+", " ", (RULES / "prompts" / f"{ad}.md").read_text(encoding="utf-8"))


AC_PARANTEZ = (
    "When a number in parentheses in an acceptance criterion and another wording of the same "
    "rule disagree (for example `(en fazla 8 kişi)` beside `8 kişiden az gruplar`), do not "
    "choose one reading: write both readings into the item definition and record an open "
    "question for the PO."
)


def test_ac_parantez_kurali_iki_promptta_ayni_cumle() -> None:
    """#10: parantez sınırı belirlemez; çelişkide iki okuma + açık soru (ISTQB: soru sor)."""
    for ad in ("case-generation", "design-model"):
        metin = _prompt(ad)
        assert AC_PARANTEZ in metin, ad
        assert "defines the boundary" not in metin, ad


def test_oncelik_risk_temelli_kota_yok() -> None:
    metin = _prompt("case-generation")
    assert "at most half" not in metin and "normally at most" not in metin
    assert "`P1` is not the default" in metin
    assert "names which of these four it guards" in metin
    assert "unlikely or has a workaround" in metin


def test_sepet_yazimi_urun_kodu_carpi_adet_zorunlu() -> None:
    metin = _prompt("case-generation")
    assert "`<product code> × <quantity>`" in metin
    assert "never a product name without its code and never the quantity first" in metin
    # Örnek kodlar test verisi kod biçimindedir (denetleyici bu biçimi okur) ve eval'de geçmez.
    assert "`KX-12 × 3; KX-40 × 1`" in metin


# --------------------------------------------------------------- içerik hash'i kapısı


@pytest.mark.parametrize("paket", ["case-generation", "design-model"])
def test_uretim_promptlari_icerik_hashiyle_kapilanir(paket: str) -> None:
    """Örnekler sürüm yükseltmeden yeniden yazıldı: hash'siz eski `evaluated` kaydı
    `icerik_degisti` olur (kapı kapanır, yeniden canlı koşu gerekir)."""
    assert paket in ICERIK_KAYNAKLARI and icerik_hash(RULES, paket)
    st = evaluation_status(RULES, paket)
    kayitli = (st.detail or {}).get("icerik_hash")
    if kayitli != icerik_hash(RULES, paket):
        assert st.status == "icerik_degisti" and not st.mergeable
