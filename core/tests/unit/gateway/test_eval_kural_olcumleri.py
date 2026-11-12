"""Eval raporunda ham model ölçümleri (inceleme tur 2, test mimarı #4): ilk deneme geçişi,
kural yeniden isteme oranı, düzelme, ek maliyet/süre, kural türü histogramı; `--no-output-check`
kipi geçidin kural yeniden istemesini kapatır."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from tp_core.gateway.eval_set import (
    CaseResult,
    kural_yeniden_isteme_olcumleri,
    run_case,
)

VERI: dict[str, Any] = {
    "purpose": "triage",
    "cases": [
        {"id": "a", "messages": [], "expect": {"class": "bug"}},
        {"id": "b", "messages": [], "expect": {"class": "bug"}},
    ],
}


def _satir(vaka, deneme, *, gecerli=True, kural=(), maliyet=0.1, sure=1000, cikti=None, **ek):
    return {
        "eval_vaka": vaka,
        "amac": "triage",
        "mod": "live",
        "deneme": deneme,
        "sema_gecerli": gecerli,
        "cikti": cikti if cikti is not None else {"class": "bug"},
        "maliyet": maliyet,
        "sure_ms": sure,
        "ek": {**({"kural_hatalari": list(kural)} if kural else {}), **ek},
    }


def test_olcumler_ilk_deneme_yeniden_isteme_ek_maliyet_histogram() -> None:
    rows = [
        # a: ilk deneme kural ihlalli → yeniden istendi → düzeldi
        _satir("a", 1, kural=["C1: open_question_refs: 'Q9' tanımsız", "C2: covers: x"]),
        _satir("a", 2, maliyet=0.2, sure=3000),
        # b: ilk denemede temiz
        _satir("b", 1),
    ]
    sonuclar = [CaseResult("a", True), CaseResult("b", True)]
    o = kural_yeniden_isteme_olcumleri(VERI, sonuclar, rows, "triage")
    assert o["ilk_deneme_gecis"] == 1 and o["ilk_deneme_gecis_orani"] == 0.5
    assert o["kural_yeniden_isteme_orani"] == 0.5 and o["sema_yeniden_isteme_orani"] == 0.0
    assert o["duzelme_orani"] == 1.0 and o["kalan_kural_ihlali"] == 0
    assert o["ek_maliyet_usd"] == 0.2 and o["ek_maliyet_orani"] == 0.5
    assert o["ek_sure_ms"]["p50"] == 3000
    assert o["kural_turu_histogrami"] == {"covers": 1, "open_question_refs": 1}
    (esik,) = o["esikler"]
    assert esik["gecti"] is False and esik["bagliyici"] is False  # varsayılan %70 yalnız bilgi


def test_kalan_ihlal_ve_secim_satiri_ve_baglayici_esik() -> None:
    rows = [
        _satir("a", 1, kural=["C1: x: y"]),
        _satir("a", 2, gecerli=False, cikti="bozuk"),
        _satir("a", 3, gecerli=False, cikti="bozuk"),
        _satir("a", 3, kural=["C1: x: y"], maliyet=0.0, secilen_deneme=1),
    ]
    veri = {**VERI, "cases": VERI["cases"][:1], "ham_gecis_alt_siniri": 0.0}
    o = kural_yeniden_isteme_olcumleri(veri, [CaseResult("a", False)], rows, "triage")
    assert o["kalan_kural_ihlali"] == 1 and o["duzelme_orani"] == 0.0
    assert o["esikler"][0]["bagliyici"] is True and o["esikler"][0]["gecti"] is True


def test_no_output_check_kipi_gecide_denetim_vermez() -> None:
    gorulen: list[dict[str, Any]] = []

    class Gecit:
        def call(self, *a: Any, **kw: Any) -> Any:
            gorulen.append(kw)
            return SimpleNamespace(output={"cases": []}, mode="live")

    veri = {"purpose": "case_generation", "bundle": "case-generation"}
    vaka = {"id": "x", "messages": [], "expect": {"ac_coverage": ["AC1"]}}
    run_case(Gecit(), veri, vaka, {}, output_check=True)
    run_case(Gecit(), veri, vaka, {}, output_check=False)
    assert "output_check" in gorulen[0] and "output_check" not in gorulen[1]
