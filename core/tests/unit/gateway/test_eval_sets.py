"""Constitution X değerlendirme setleri (`rules/evaluation/*.json`) ve koşturucusu
(`tp_core.gateway.eval_set`): set kanonik kurucuların bugünkü çıktısıdır, beklentiler golden
çıktılarıyla tutarlıdır, koşturucu yalnızca canlı ve tamamen geçen koşuyu `evaluated` yazar."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.gateway import build_eval_sets as bes
from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.gateway import Gateway, ReplayStore
from tp_core.gateway.config import load_model_table
from tp_core.gateway.eval_set import (
    EVAL_DIR,
    check_output,
    load_set,
    mark_evaluated,
    run_set,
    write_report,
)
from tp_core.gateway.evaluation import evaluation_status
from tp_core.gateway.testing import FakeProvider, InMemoryCallRecorder, text_response

BUILT = bes.build_sets()


@pytest.mark.parametrize("bundle", sorted(BUILT))
def test_stored_eval_set_is_what_the_builders_produce(bundle: str) -> None:
    """Kurucu/kaynak değişince set bayatlar: `python -m tests.unit.gateway.build_eval_sets`."""
    stored = (RULES / EVAL_DIR / f"{bundle}.json").read_text(encoding="utf-8")
    assert stored == bes.dump(BUILT[bundle]), f"{bundle} seti bayat; yeniden üretin"
    assert load_set(RULES, bundle)["version"] == BUILT[bundle]["version"]


def test_triage_set_covers_the_required_llm_paths() -> None:
    cases = {c["id"]: c for c in BUILT["triage"]["cases"]}
    assert cases["zaman-asimi-kuralsiz"]["expect"]["class"] == "unknown"
    assert "environment" in cases["saglikli-agsiz-eleman-gorunmedi"]["expect"]["class_not"]
    assert cases["saglik-bilinmiyor-baglanti-reddedildi"]["expect"]["class"] == "environment"
    assert cases["test-verisi-eksik-bayi"]["expect"]["class"] == "test_data"
    text = {k: c["messages"][0]["content"] for k, c in cases.items()}
    assert "Sağlık kontrolü: başarılı" in text["saglikli-agsiz-eleman-gorunmedi"]
    assert "Sağlık kontrolü: bilinmiyor" in text["saglik-bilinmiyor-baglanti-reddedildi"]
    # Üretimin kural sinyali metni (triage.service.kural_sinyalleri), elle yazılmış benzeri değil.
    assert "kural 2 (flaky): 2 denemenin hepsi kırmızı" in text["zaman-asimi-kuralsiz"]


def test_llm_path_cases_do_not_match_the_deterministic_rules() -> None:
    """Set yalnızca kuralların SINIFLAMADIĞI girdileri içerir (XI): ağ hatası/fixture kalıbına uyan
    mesaj modele hiç gitmez."""
    from tp_core.features.triage import rules

    for case in BUILT["triage"]["cases"]:
        content = case["messages"][0]["content"]
        line = next(x for x in content.splitlines() if x.startswith("Hata: "))
        assert not rules._AG_RE.search(line), case["id"]
        assert not rules._VERI_RE.search(line), case["id"]


def _golden_for(bundle: str, case_id: str) -> dict[str, Any] | None:
    names = {
        ("triage", "zaman-asimi-kuralsiz"): ("triage", "HATA"),
        ("bug-draft", "c3-6-adet"): ("bug_draft", "HATA"),
        ("bug-draft", "kirma-7-adet"): ("bug_draft", "kirma-kampanya/HATA"),
        ("bug-draft", "f2-kampanya-bulgusu"): ("bug_draft", "f2-kampanya/HATA"),
        ("bug-draft", "f4-kredi-limiti-bulgusu"): ("bug_draft", "f4-kredi-limiti/HATA"),
    }
    ref = names.get((bundle, case_id))
    return load_golden(*ref)["output"] if ref else None


def _gateway(rules_dir: Path, mode: str, script: list[Any] | None = None) -> Gateway:
    return Gateway(
        provider=FakeProvider(script or []) if mode != "replay" else None,
        recorder=InMemoryCallRecorder(),
        mode=mode,
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(rules_dir / "replay"),
    )


@pytest.mark.parametrize("bundle", sorted(BUILT))
def test_replay_goldens_pass_their_own_eval_cases(rules_dir: Path, bundle: str) -> None:
    """Beklentiler golden çıktılarıyla çelişmez: REPLAY duman koşusunda golden'ı olan her vaka
    geçer (REPLAY koşusu `evaluated` sayılmaz; aşağıda)."""
    data = load_set(rules_dir, bundle)
    results = run_set(_gateway(rules_dir, "replay"), rules_dir, data)
    backed = 0
    for r in results:
        if bundle == "dup-rank" or _golden_for(bundle, r.id) is not None:
            backed += 1
            assert r.mode == "replay" and r.ok, (r.id, r.failures, r.error)
        else:
            # Golden'sız vaka REPLAY'de dürüstçe iskalar (nötr unknown): canlı model gerekir.
            assert r.mode == "replay_miss", r.id
    assert backed


def test_check_output_flags_wrong_answers() -> None:
    assert check_output("triage", {"class": "unknown"}, {"class": "product_defect"})
    assert check_output("triage", {"class_not": ["environment"]}, {"class": "environment"})
    assert not check_output("triage", {"class_in": ["flaky", "unknown"]}, {"class": "flaky"})
    bad_actual = {"actual": "bedava 1; toplam 125,00 TL", "story_key": "TPD-1"}
    assert check_output("bug_draft", {"not_contains": {"actual": ["TL"]}}, bad_actual)
    assert check_output("bug_draft", {"contains": {"steps": ["bayi2"]}}, {"steps": ["bayi1"]})
    dup = {
        "candidates": [
            {"key": "TPD-5", "rank": 1, "likelihood": "high", "rationale": "Aynı belirti"},
            {"key": "TPD-5", "rank": 2, "likelihood": "low", "rationale": "x"},
        ],
        "recommendation": "link",
        "link_key": "TPD-5",
    }
    problems = check_output("dup_rank", {"candidate_keys": ["TPD-5", "TPD-6"]}, dup)
    assert any("birden çok" in p for p in problems) and any("TPD-6" in p for p in problems)


def _status(rules_dir: Path, bundle: str) -> str:
    return evaluation_status(rules_dir, bundle).status


def test_live_run_that_passes_is_recorded_as_evaluated(rules_dir: Path) -> None:
    data = load_set(rules_dir, "bug-draft")
    script = []
    for case in data["cases"]:
        out = _golden_for("bug-draft", case["id"])
        assert out is not None
        script.append(text_response(out))
    gw = _gateway(rules_dir, "live", script)
    results = run_set(gw, rules_dir, data)
    assert all(r.ok and r.mode == "live" for r in results), [(r.id, r.failures) for r in results]
    today = dt.date(2026, 11, 2)
    report = write_report(
        rules_dir, data, results, model="m", provider=gw.provider_name, mode="live", today=today
    )
    assert report.name == "bug-draft-v2-2026-11-02.json"
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] == len(data["cases"])
    header = (rules_dir / "evaluations.yaml").read_text(encoding="utf-8").split("version:")[0]
    assert _status(rules_dir, "bug-draft") == "pending"
    mark_evaluated(
        rules_dir,
        "bug-draft",
        2,
        model="m",
        provider="fake",
        results=str(report.relative_to(rules_dir)),
        today=today,
    )
    st = evaluation_status(rules_dir, "bug-draft")
    assert st.status == "evaluated" and st.detail["results"].startswith("evaluation/results/")
    text = (rules_dir / "evaluations.yaml").read_text(encoding="utf-8")
    assert text.startswith(header)  # açıklama yorumu korunur
    others = yaml.safe_load(text)["bundles"]
    assert others["triage"]["status"] == "pending" and others["dup-rank"]["status"] == "pending"


def test_wrong_live_answer_fails_the_case(rules_dir: Path) -> None:
    data = load_set(rules_dir, "triage")
    wrong = {"class": "environment", "sub_type": None, "rationale": "x", "signals": ["x"]}
    gw = _gateway(rules_dir, "live", [text_response(wrong)] * len(data["cases"]))
    results = {r.id: r for r in run_set(gw, rules_dir, data)}
    assert not results["saglikli-agsiz-eleman-gorunmedi"].ok
    assert not results["zaman-asimi-kuralsiz"].ok
    assert results["saglik-bilinmiyor-baglanti-reddedildi"].ok


def test_cli_refuses_replay_and_never_marks_a_replay_smoke_run(
    rules_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tp_core.gateway import eval_set

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.setenv("TP_RULES_DIR", str(rules_dir))
    assert eval_set.main(["--bundle", "dup-rank", "--update-status"]) == 2
    assert eval_set.main(["--bundle", "dup-rank", "--allow-replay", "--update-status"]) == 0
    assert _status(rules_dir, "dup-rank") == "pending"
    reports = list((rules_dir / EVAL_DIR / "results").glob("dup-rank-v2-*-replay-duman.json"))
    assert len(reports) == 1
    assert "GEÇTİ" in capsys.readouterr().out
