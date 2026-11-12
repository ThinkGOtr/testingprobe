"""Demo-B ön kontrolü: defect adayı anı yalnızca F2 'Kod hatalı' yolunda vardır; kontrol bunu
Demo-B'den önce söyler (tek yanlış tık sessizce kanıtı silmesin)."""

from __future__ import annotations

import json

from tests.unit.gateway.demo_sources import load_golden
from tp_core.gateway.demo_check import HINT, evaluate, main

MAIN = load_golden("case_generation", "TPD-1")["output"]["cases"]
SCENARIO = load_golden("case_generation", "f2-kod-hatasi/TPD-1")["output"]["cases"]


def _numbered(cases):
    return list(enumerate(cases, start=1))


def test_code_defect_path_has_the_six_no_free_defect_candidate() -> None:
    r = evaluate("TPD-1", _numbered(SCENARIO))
    assert r.ok
    assert [(c.sira_no, c.golden) for c in r.defect_candidates] == [(3, "f2-kod-hatasi/TPD-1-C3")]
    assert r.defect_candidates[0].title.startswith("6 adet kampanyalı üründe bedava ürün verilmez")
    # C1–C10 REPLAY (MISS yok); C11–C15 (011 K17 sınır case'leri) doğrulama kaydı yok → dürüst
    # REPLAY-MISS, kontrolün sonucunu değiştirmez (karar defect adayına göre).
    assert all(c.golden for c in r.cases if c.sira_no <= 10)
    assert [c.sira_no for c in r.cases if not c.golden] == [11, 12, 13, 14, 15]
    assert "TAMAM" in r.report()


def test_default_fix_doc_path_fails_with_the_presenter_hint() -> None:
    r = evaluate("TPD-1", _numbered(MAIN))
    assert not r.ok and r.defect_candidates == []
    assert all(c.golden for c in r.cases if c.sira_no <= 10)
    report = r.report()
    assert "HATA" in report and HINT in report and "Kod hatalı" in report


def test_edited_boundary_case_is_not_counted() -> None:
    cases = json.loads(json.dumps(SCENARIO))
    cases[2]["expected_result"] += " (düzenlendi)"
    r = evaluate("TPD-1", _numbered(cases))
    assert not r.ok
    assert next(c for c in r.cases if c.sira_no == 3).golden is None


def test_no_approved_cases_fails(monkeypatch, capsys) -> None:
    import tp_core.gateway.demo_check as dc

    monkeypatch.setattr(dc, "approved_cases", lambda story: [])
    assert main(["--story", "TPD-1"]) == 1
    assert "0 onaylı case" in capsys.readouterr().out
    monkeypatch.setattr(dc, "approved_cases", lambda story: _numbered(SCENARIO))
    assert main(["--story", "TPD-1"]) == 0


def test_decision_reads_the_structured_field_not_the_evidence_text(tmp_path) -> None:
    """Kanıt metnindeki '· beklenen:' notu tek başına defect adayı yapmaz; yapılandırılmış
    `defect_adayi` beyanı (eşlemedeki bir adımı göstermeli) yapar."""
    import shutil

    from tp_core.gateway.config import find_rules_dir

    rules = tmp_path / "rules"
    shutil.copytree(find_rules_dir(), rules)
    path = rules / "replay" / "verify_and_map" / "golden" / "f2-kod-hatasi" / "TPD-1-C3.json"
    golden = json.loads(path.read_text(encoding="utf-8"))
    assert golden["defect_adayi"]["step_id"] == "S4"
    assert "kayıttaki not" in golden["output"]["step_mapping"][-1]["evidence_ref"]

    without = {k: v for k, v in golden.items() if k != "defect_adayi"}
    path.write_text(json.dumps(without, ensure_ascii=False), encoding="utf-8")
    assert not evaluate("TPD-1", _numbered(SCENARIO), rules).ok  # metin notu yetmez

    dangling = {**golden, "defect_adayi": {**golden["defect_adayi"], "step_id": "S9"}}
    path.write_text(json.dumps(dangling, ensure_ascii=False), encoding="utf-8")
    assert not evaluate("TPD-1", _numbered(SCENARIO), rules).ok  # eşlemede olmayan adım

    path.write_text(json.dumps(golden, ensure_ascii=False), encoding="utf-8")
    assert evaluate("TPD-1", _numbered(SCENARIO), rules).ok
