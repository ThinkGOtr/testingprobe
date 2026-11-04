"""Demo-A/Demo-B prompt'larının değerlendirme setleri (requirement-review, case-generation,
consistency-check, verify-and-map), ajan araç ortamı, çağrı defteri (constitution VIII),
`guardrails` geçişli kapsamı ve `--update-status` kaydının kendisiyle çelişmemesi.

Hiçbir test gerçek API'ye ya da canlı yığına gitmez (FakeProvider, sahte araç ortamı).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.gateway import ALLOWED_AGENT_TOOLS, Gateway, ReplayStore
from tp_core.gateway.config import GatewaySettings, load_model_table
from tp_core.gateway.core import FINAL_TOOL
from tp_core.gateway.eval_agents import ToolEnv, ToolEnvUnavailable
from tp_core.gateway.eval_live import (
    CallLedger,
    default_ledger_path,
    main,
    plan_bundles,
    run_live,
)
from tp_core.gateway.eval_set import (
    GUARDRAILS,
    case_messages,
    case_replay_key,
    check_output,
    guardrails_coverage,
    load_set,
    mark_evaluated,
    mark_guardrails_if_covered,
    run_set,
)
from tp_core.gateway.evaluation import (
    EVALUATIONS_FILE,
    evaluation_status,
    evaluation_statuses,
    icerik_hash,
    prompt_versions,
)
from tp_core.gateway.testing import (
    FakeProvider,
    InMemoryCallRecorder,
    text_response,
    tool_response,
)
from tp_core.ports import ToolSpec

KEY = "sk-ant-api03-TESTKEYabcdefghijklmnop"
TODAY = dt.date(2026, 11, 2)
CORE_SETS = ("requirement-review", "case-generation", "consistency-check", "verify-and-map")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, rules_dir: Path) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "TP_EVAL_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TP_RULES_DIR", str(rules_dir))


def _golden_output(rules_dir: Path, data: dict[str, Any], case: dict[str, Any]) -> Any:
    store = ReplayStore(rules_dir / "replay")
    msgs = [m.model_dump(mode="json") for m in case_messages(case)]
    record, mode, _ = store.lookup(
        str(data["purpose"]), "-", case_replay_key(data, case)["name"], msgs
    )
    assert mode == "replay", case["id"]  # girdi beyanı eşleşti (REPLAY-MISS değil)
    return record["output"]


# ------------------------------------------------------------------ setlerin içeriği


def test_every_prompt_bundle_except_guardrails_has_an_eval_set() -> None:
    versions = prompt_versions(RULES)
    have = {p.stem for p in (RULES / "evaluation").glob("*.json")}
    assert have == set(versions) - {GUARDRAILS}
    for bundle in CORE_SETS:
        assert load_set(RULES, bundle)["version"] == versions[bundle]


def test_case_generation_set_is_five_stories_times_three_runs() -> None:
    """TEKNİK-TASARIM §12: 5 story × 3 koşu; girdi üretimin kurucusuyla (test verisi dahil)."""
    data = load_set(RULES, "case-generation")
    assert data["runs"] == 3 and len(data["cases"]) == 5
    keys = {c["replay_key"]["name"] for c in data["cases"]}
    assert keys == {"TPD-1", "TPD-3", "TPD-4", "SERBEST"}
    for case in data["cases"]:
        content = case["messages"][0]["content"]
        assert 'source="testdata:demo-app"' in content and "bayi1 / Demo123!" in content
        golden = load_golden("case_generation", case["replay_key"]["name"])
        refs = [a.split(":")[0] for a in golden["input_match"]["acceptance_criteria"]]
        if case["id"] != "tpd-1-f2-kod-hatasi":
            assert case["expect"]["ac_coverage"] == refs
        assert case["expect"]["min_cases"] == len(case["expect"]["ac_coverage"])


def test_agent_sets_declare_their_tool_environment() -> None:
    assert load_set(RULES, "consistency-check")["agent"]["tool_env"] == "consistency"
    assert load_set(RULES, "verify-and-map")["agent"]["tool_env"] == "browser"


@pytest.mark.parametrize("bundle", CORE_SETS)
def test_golden_outputs_meet_their_own_expectations(rules_dir: Path, bundle: str) -> None:
    """Beklentiler golden çıktılarıyla çelişmez (golden elle hazırlandı; canlı model aynı çıtayı
    geçmeli). Girdi beyanı eşleşir: set girdisi demo'nun gerçek girdisidir."""
    data = load_set(rules_dir, bundle)
    for case in data["cases"]:
        out = _golden_output(rules_dir, data, case)
        assert check_output(str(data["purpose"]), case["expect"], out) == [], case["id"]


@pytest.mark.parametrize("bundle", ["requirement-review", "case-generation"])
def test_replay_smoke_of_single_call_sets(rules_dir: Path, bundle: str) -> None:
    gw = Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(rules_dir / "replay"),
    )
    data = load_set(rules_dir, bundle)
    results = run_set(gw, rules_dir, data)
    assert len(results) == len(data["cases"]) * int(data.get("runs") or 1)
    for r in results:
        assert r.mode == "replay" and r.ok, (r.id, r.failures, r.error)
    if bundle == "case-generation":
        assert {r.id for r in results} >= {"tpd-4-giris#k1", "tpd-4-giris#k3"}


def test_agent_set_without_tool_env_never_passes(rules_dir: Path) -> None:
    gw = Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
    )
    results = run_set(gw, rules_dir, load_set(rules_dir, "consistency-check"))
    assert results and not any(r.ok for r in results)
    assert all(r.failures == ["araç ortamı yok"] for r in results)


# ------------------------------------------------------------------ beklenti denetimleri


def test_case_generation_check_flags_uncovered_and_invented_acs() -> None:
    expect = {"ac_coverage": ["AC1", "AC2"], "min_cases": 2, "not_contains": ["500 TL"]}
    one = {"cases": [{"acceptance_criteria_refs": ["AC1", "AC9"], "title": "500 TL"}]}
    failures = check_output("case_generation", expect, one)
    assert "AC2 hiçbir case'te yok" in failures
    assert "belgede olmayan AC: ['AC9']" in failures
    assert "1 case, en az 2" in failures and "'500 TL' geçmemeli" in failures


def test_requirement_review_check() -> None:
    expect = {"verdict": "needs_po", "ac_refs_within": ["AC1"], "question_types": ["missing_ac"]}
    out = {"verdict": "ready", "questions": [{"type": "ambiguity", "ac_ref": "AC7"}]}
    failures = check_output("requirement_review", expect, out)
    assert len(failures) == 3


def test_consistency_check_flags_missing_doc_ref_and_unknown_ac() -> None:
    expect = {"acs": ["AC1: a", "AC2: b"], "doc_refs_include": ["AC2"], "max_blocking": 0}
    out = {
        "findings": [
            {"id": "F1", "doc_ref": "AC1 ↔ AC5", "severity": "blocking", "type": "doc_vs_code"}
        ]
    }
    failures = check_output("consistency_check", expect, out)
    assert "AC2 için bulgu yok" in failures
    assert "belgede olmayan yer: ['AC5']" in failures
    assert "1 engelleyici bulgu, en çok 0" in failures
    assert "kanıtsız bulgu: ['F1']" in failures


def test_verify_and_map_check() -> None:
    expect = {
        "steps": ["S1", "S2"],
        "methods": ["LoginPage.goto"],
        "expects_include": ["LoginPage.expectLoggedIn"],
        "no_missing_methods": True,
        "all_verified": True,
    }
    out = {
        "step_mapping": [
            {"step_id": "S1", "po": "LoginPage", "method": "uydurma", "verified": False}
        ],
        "expects": [],
        "missing_methods": [],
    }
    failures = check_output("verify_and_map", expect, out)
    assert "adım S2 eşlenmedi" in failures
    assert "sembol tablosunda olmayan metot: LoginPage.uydurma" in failures
    assert "beklenen assertion yok: LoginPage.expectLoggedIn" in failures
    assert "doğrulanmamış adım: ['S1']" in failures


# ------------------------------------------------------------------ ajan canlı koşusu (sahte)


def _consistency_env(check_fails: bool = False, calls: list[str] | None = None) -> ToolEnv:
    names = sorted(ALLOWED_AGENT_TOOLS["consistency_check"])

    def execute(name: str, args: dict[str, Any]) -> str:
        (calls if calls is not None else []).append(name)
        return f"{name} sonucu"

    return ToolEnv(
        "consistency",
        [ToolSpec(name=n, description=n, input_schema={"type": "object"}) for n in names],
        execute,
        check=lambda output, expect: ["F9: kanıt doğrulanamadı"] if check_fails else [],
    )


def _consistency_script(rules_dir: Path) -> list[Any]:
    data = load_set(rules_dir, "consistency-check")
    script: list[Any] = []
    for case in data["cases"]:
        golden = _golden_output(rules_dir, data, case)
        script += [
            tool_response(("search_code", {"query": "min_aranir"})),
            tool_response((FINAL_TOOL, golden)),
        ]
    return script


def _run(rules_dir: Path, fake: FakeProvider, bundle: str, **kw: Any) -> tuple[int, str]:
    lines: list[str] = []
    code = run_live(
        GatewaySettings(),
        rules_dir,
        plan_bundles(rules_dir, [bundle]),
        kw.pop("budget", 50.0),
        provider_factory=lambda s: fake,
        out=lines.append,
        today=TODAY,
        **kw,
    )
    return code, "\n".join(lines)


def test_agent_set_runs_tools_through_env_and_marks_evaluated(rules_dir: Path) -> None:
    calls: list[str] = []
    fake = FakeProvider(_consistency_script(rules_dir))
    code, out = _run(
        rules_dir,
        fake,
        "consistency-check",
        update_status=True,
        envs={"consistency": lambda: _consistency_env(calls=calls)},
    )
    assert code == 0, out
    assert calls == ["search_code"] * 3  # araçlar ortamda yürüdü (sahte sonuç uydurulmadı)
    st = evaluation_status(rules_dir, "consistency-check")
    assert st.status == "evaluated"
    assert st.detail["calls"] == "evaluation/results/consistency-check-v4-2026-11-02.calls.jsonl"


def test_unverifiable_evidence_fails_the_agent_case(rules_dir: Path) -> None:
    fake = FakeProvider(_consistency_script(rules_dir))
    code, out = _run(
        rules_dir,
        fake,
        "consistency-check",
        update_status=True,
        envs={"consistency": lambda: _consistency_env(check_fails=True)},
    )
    assert code == 1 and "kanıt doğrulanamadı" in out
    assert evaluation_status(rules_dir, "consistency-check").status == "pending"


def test_unavailable_tool_env_skips_bundle_and_keeps_pending(rules_dir: Path) -> None:
    def down() -> ToolEnv:
        raise ToolEnvUnavailable("Playwright MCP oturumu kurulamadı")

    fake = FakeProvider([])  # çağrılırsa AssertionError
    code, out = _run(rules_dir, fake, "verify-and-map", update_status=True, envs={"browser": down})
    assert code == 1 and not fake.requests
    assert "ATLANDI — araç ortamı yok: Playwright MCP" in out
    assert evaluation_status(rules_dir, "verify-and-map").status == "pending"


# ------------------------------------------------------------------ çağrı defteri (VIII)


def _review_script(rules_dir: Path) -> list[Any]:
    data = load_set(rules_dir, "requirement-review")
    return [text_response(_golden_output(rules_dir, data, c)) for c in data["cases"]]


def test_live_calls_are_written_to_hash_chained_ledger_and_calls_file(
    rules_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    ledger = CallLedger(tmp_path / "ai_call.jsonl", [KEY])
    fake = FakeProvider(_review_script(rules_dir))
    code, out = _run(rules_dir, fake, "requirement-review", ledger=ledger, update_status=True)
    assert code == 0, out
    lines = [json.loads(x) for x in ledger.path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 5 and {x["tur"] for x in lines} == {"eval-live"}
    row = lines[0]["ai_call"]
    assert row["amac"] == "requirement_review" and row["bundle_hash"] and row["maskeli_girdi"]
    assert row["cikti"]["verdict"] and row["maliyet"] > 0 and row["mod"] == "live"
    assert CallLedger.verify(ledger.path) == []
    calls = rules_dir / "evaluation" / "results" / "requirement-review-v3-2026-11-02.calls.jsonl"
    assert len(calls.read_text(encoding="utf-8").splitlines()) == 5
    report = json.loads(calls.with_name(calls.name.replace(".calls.jsonl", ".json")).read_text())
    assert report["cagri_sayisi"] == 5 and report["guardrails_version"] == 1
    assert KEY not in ledger.path.read_text(encoding="utf-8")


def test_ledger_detects_tampering(tmp_path: Path) -> None:
    ledger = CallLedger(tmp_path / "l.jsonl")
    ledger.append("ping", [{"amac": "ping", "maliyet": 0.1}, {"amac": "ping", "maliyet": 0.2}])
    ledger.append("ping", [{"amac": "ping", "maliyet": 0.3}])
    assert CallLedger.verify(ledger.path) == []
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["ai_call"]["maliyet"] = 0.0  # özet alanına dokunmadan içerik değişti
    lines[1] = json.dumps(tampered, ensure_ascii=False, sort_keys=True)
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert CallLedger.verify(ledger.path) == ["satır 2: içerik özeti uyuşmuyor"]
    ledger.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert "satır 2: önceki özet uyuşmuyor" in CallLedger.verify(ledger.path)


def test_ping_is_logged_to_ledger_without_secrets(
    rules_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    path = tmp_path / "ai_call.jsonl"
    ok = FakeProvider([text_response("OK", input_tokens=12, output_tokens=1)])
    assert main(["--ping", "--ledger", str(path)], provider_factory=lambda s: ok) == 0
    err = FakeProvider([RuntimeError(f"reddedildi {KEY}")])
    assert main(["--ping", "--ledger", str(path)], provider_factory=lambda s: err) == 1
    entries = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [e["tur"] for e in entries] == ["ping", "ping"]
    assert entries[0]["ai_call"]["cikti"] == "OK" and entries[0]["ai_call"]["maliyet"] > 0
    assert entries[1]["ai_call"]["hata"].startswith("HATA: RuntimeError")
    assert KEY not in path.read_text(encoding="utf-8")
    assert CallLedger.verify(path) == []


def test_default_ledger_is_under_gitignored_exports(rules_dir: Path) -> None:
    path = default_ledger_path(rules_dir)
    assert path == rules_dir.resolve().parent / "exports" / "eval-live" / "ai_call.jsonl"


# ------------------------------------------------------------------ durum kaydı


def test_mark_evaluated_replaces_stale_note_and_header_has_no_dated_status(
    rules_dir: Path,
) -> None:
    text = (rules_dir / EVALUATIONS_FILE).read_text(encoding="utf-8")
    assert "Bugünkü durum" not in text  # başlık tarihli durum taşımaz (kayıtla çelişmesin)
    mark_evaluated(
        rules_dir,
        "triage",
        2,
        model="claude-haiku-5-5",
        provider="anthropic",
        results="evaluation/results/triage-v2-2026-11-02.json",
        today=TODAY,
        passed=4,
        total=4,
        guardrails_version=1,
    )
    entry = yaml.safe_load((rules_dir / EVALUATIONS_FILE).read_text(encoding="utf-8"))["bundles"][
        "triage"
    ]
    assert entry["status"] == "evaluated"
    assert "yapılmadı" not in entry["note"] and "bekliyor" not in entry["note"]
    assert entry["note"].startswith("Canlı değerlendirme 2026-11-02, claude-haiku-5-5")
    assert "4/4 vaka geçti" in entry["note"]
    assert entry["evaluation"]["guardrails_version"] == 1
    head = (rules_dir / EVALUATIONS_FILE).read_text(encoding="utf-8").split("version: 1")[0]
    assert "Birleştirme kapısı" in head and "geçişli" in head  # açıklama başlığı korunur
    evaluation_statuses(rules_dir)  # hâlâ geçerli kayıt


def _mark_all(rules_dir: Path, guard: int) -> None:
    for bundle, version in prompt_versions(rules_dir).items():
        if bundle == GUARDRAILS:
            continue
        mark_evaluated(
            rules_dir,
            bundle,
            version,
            model="m",
            provider="anthropic",
            results=f"evaluation/results/{bundle}.json",
            today=TODAY,
            guardrails_version=guard,
            icerik_hash=icerik_hash(rules_dir, bundle),
        )


def test_guardrails_is_evaluated_transitively_only_when_every_bundle_passed(
    rules_dir: Path,
) -> None:
    covered, missing = guardrails_coverage(rules_dir)
    # guardrails dışındaki her paket (asistan dahil) canlı değerlendirilmeden kapsam yok.
    assert not covered and len(missing) == len(prompt_versions(rules_dir)) - 1
    assert not mark_guardrails_if_covered(rules_dir, model="m", provider="anthropic")
    _mark_all(rules_dir, guard=99)  # başka guardrails sürümüyle: sayılmaz
    covered, missing = guardrails_coverage(rules_dir)
    assert not covered and all("guardrails v1 ile değil" in m for m in missing)
    _mark_all(rules_dir, guard=1)
    assert mark_guardrails_if_covered(rules_dir, model="m", provider="anthropic", today=TODAY)
    st = evaluation_status(rules_dir, GUARDRAILS)
    assert st.status == "evaluated" and st.detail["kapsam"] == "transitive"
    assert all(s.mergeable for s in evaluation_statuses(rules_dir).values())


def test_update_status_run_reports_guardrails_pending_until_all_bundles_pass(
    rules_dir: Path,
) -> None:
    code, out = _run(
        rules_dir,
        FakeProvider(_review_script(rules_dir)),
        "requirement-review",
        update_status=True,
    )
    assert code == 0
    assert "guardrails: canlı değerlendirme bekliyor (geçişli kapsam eksik" in out
    assert evaluation_status(rules_dir, GUARDRAILS).status == "pending"
