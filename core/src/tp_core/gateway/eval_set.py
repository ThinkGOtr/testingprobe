"""Prompt paketlerinin değerlendirme seti ve canlı koşturucusu (constitution X).

`rules/evaluations.yaml` bir paketin durumunu (`pending` / `evaluated` / `waived`) tutar; bu modül
`evaluated` durumunun dayandığı **seti** ve onu koşturan aracı sağlar:

- Set: `rules/evaluation/<paket>.json` — `{"bundle", "purpose", "version", "cases": [...]}`.
  Her vaka kanonik girdi kurucularıyla (`tp_core.gateway.defects`) kurulmuş model mesajlarını
  (`messages`) ve beklentiyi (`expect`) taşır. Setler elle değil, test yardımcılarından üretilir
  (`core/tests/unit/gateway/build_eval_sets.py`); `test_eval_sets` kurucular değişince setin
  bayatladığını yakalar.
- Beklentiler (deterministik, model çıktısına bakar):
  - triage: `class` (tam), `class_in`, `class_not`, `sub_type`;
  - bug_draft: `contains` / `not_contains` ({alan: [metin, …]}; alan `steps` ise adımların
    birleşimi), `story_key`;
  - dup_rank: `candidate_keys` (aramadaki küme; `dup_rank_problems` ile değişmezler), `top`,
    `recommendation`, `link_key`;
  - requirement_review: `verdict`, `question_types`, `ac_refs_within`, `ac_refs_any`,
    `max_questions`;
  - case_generation: `ac_coverage` (AC1..ACn hepsi bir case'te, fazlası yok), `min_cases`,
    `contains` / `not_contains` (case'lerin birleşik metni); set `runs` kez koşar (§12: 5 story ×
    3 koşu);
  - consistency_check (ajan): `doc_refs_include`, `acs`, `min_blocking`/`max_blocking`; kanıt
    araç ortamında üretimin `EvidenceVerifier`'ıyla yeniden doğrulanır (`eval_agents`);
  - verify_and_map (ajan): `steps`, `methods` (sembol tablosu), `expects_include`,
    `no_missing_methods`, `all_verified`.
- Vaka düzeyi `replay_key` setinkini geçersiz kılar (story başına golden kökü).
- Koşturucu: geçit **canlı** (`live`/`record`) olmalıdır; REPLAY'de koşu yalnızca duman testi
  sayılır (`--allow-replay`) ve durum kaydını asla `evaluated` yapmaz. Sonuç raporu
  `rules/evaluation/results/<paket>-v<sürüm>-<tarih>.json`'a yazılır; `--update-status` ile tüm
  vakalar geçtiyse `rules/evaluations.yaml` kaydı `evaluated` olur
  (`evaluation: {date, model, provider, results}`). Geçmeyen vaka varsa kayıt değişmez.

    cd core && ANTHROPIC_API_KEY=… uv run python -m tp_core.gateway.eval_set --bundle triage \\
        --update-status
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tp_core.gateway.bundle import load_schema
from tp_core.gateway.defects import dup_rank_problems
from tp_core.gateway.errors import GatewayConfigError, GatewayError
from tp_core.gateway.eval_agents import (
    ToolEnv,
    coverage_problems,
    findings_problems,
    mapping_problems,
    review_problems,
)
from tp_core.gateway.evaluation import EVALUATIONS_FILE, prompt_versions
from tp_core.ports import ModelMessage

EVAL_DIR = "evaluation"
RESULTS_DIR = "results"
LIVE_MODES = ("live", "record")


@dataclass
class CaseResult:
    id: str
    ok: bool
    failures: list[str] = field(default_factory=list)
    output: Any = None
    mode: str | None = None
    error: str | None = None


def set_path(rules_dir: Path, bundle: str) -> Path:
    return rules_dir / EVAL_DIR / f"{bundle}.json"


def load_set(rules_dir: Path, bundle: str) -> dict[str, Any]:
    path = set_path(rules_dir, bundle)
    if not path.is_file():
        raise GatewayConfigError(f"değerlendirme seti yok: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("bundle") != bundle or not data.get("cases"):
        raise GatewayConfigError(f"{path}: geçersiz değerlendirme seti")
    ids = [c.get("id") for c in data["cases"]]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        raise GatewayConfigError(f"{path}: vaka kimlikleri benzersiz ve dolu olmalı")
    return data


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return "" if value is None else str(value)


def check_output(purpose: str, expect: Mapping[str, Any], output: Any) -> list[str]:
    """Beklentiye aykırılıklar (boş = geçti). Türkçe, kısa."""
    out = output if isinstance(output, Mapping) else {}
    failures: list[str] = []
    if purpose == "triage":
        cls, sub = out.get("class"), out.get("sub_type")
        if "class" in expect and cls != expect["class"]:
            failures.append(f"sınıf {cls!r}, beklenen {expect['class']!r}")
        if "class_in" in expect and cls not in expect["class_in"]:
            failures.append(f"sınıf {cls!r} şunlardan biri değil: {expect['class_in']}")
        if cls in (expect.get("class_not") or []):
            failures.append(f"sınıf {cls!r} olmamalı")
        if "sub_type" in expect and sub != expect["sub_type"]:
            failures.append(f"alt tür {sub!r}, beklenen {expect['sub_type']!r}")
    elif purpose == "bug_draft":
        for name, needles in (expect.get("contains") or {}).items():
            have = _text(out.get(name))
            failures += [f"{name} '{n}' içermiyor" for n in needles if n not in have]
        for name, needles in (expect.get("not_contains") or {}).items():
            have = _text(out.get(name))
            failures += [f"{name} '{n}' içermemeli" for n in needles if n in have]
        if "story_key" in expect and out.get("story_key") != expect["story_key"]:
            failures.append(f"story_key {out.get('story_key')!r}, beklenen {expect['story_key']!r}")
    elif purpose == "dup_rank":
        keys = list(expect.get("candidate_keys") or [])
        failures += dup_rank_problems(out, [{"key": k} for k in keys])
        ranked = sorted(
            (c for c in out.get("candidates") or [] if isinstance(c, Mapping)),
            key=lambda c: c.get("rank") or 0,
        )
        top = ranked[0].get("key") if ranked else None
        if "top" in expect and top != expect["top"]:
            failures.append(f"ilk aday {top!r}, beklenen {expect['top']!r}")
        for name in ("recommendation", "link_key"):
            if name in expect and out.get(name) != expect[name]:
                failures.append(f"{name} {out.get(name)!r}, beklenen {expect[name]!r}")
    elif purpose == "requirement_review":
        failures += review_problems(out, expect)
    elif purpose == "case_generation":
        failures += coverage_problems(out, expect)
    elif purpose == "consistency_check":
        failures += findings_problems(out, expect)
    elif purpose == "verify_and_map":
        failures += mapping_problems(out, expect)
    else:
        raise GatewayConfigError(f"değerlendirme beklentisi tanımlı değil: {purpose}")
    return failures


def case_replay_key(data: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    """Vakanın golden kökü: vaka düzeyi `replay_key` setinkini geçersiz kılar (story başına)."""
    return dict(case.get("replay_key") or data.get("replay_key") or {})


def runs_of(data: Mapping[str, Any]) -> int:
    """Setin vaka başına koşu sayısı (`runs`, varsayılan 1; §12 case üretimi 5 story × 3 koşu)."""
    runs = int(data.get("runs") or 1)
    if runs < 1:
        raise GatewayConfigError(f"{data.get('bundle')}: 'runs' en az 1 olmalı")
    return runs


def run_id(case: Mapping[str, Any], run: int, runs: int) -> str:
    return str(case["id"]) if runs == 1 else f"{case['id']}#k{run}"


def case_messages(case: Mapping[str, Any]) -> list[ModelMessage]:
    return [ModelMessage(**m) for m in case["messages"]]


def run_case(
    gw: Any,
    data: Mapping[str, Any],
    case: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    env: ToolEnv | None = None,
    case_id: str | None = None,
) -> CaseResult:
    """Tek vakayı geçitten geçirir (vakanın golden kökü: `case_replay_key`). Geçit hatası vakayı
    düşürür, koşuyu değil (`eval_live` vaka başına bütçe denetimi için bunu tek tek çağırır).

    Ajan setleri (`agent`) üretimdeki araç ortamıyla (`env`) koşar; ortam yoksa vaka çağrılmaz."""
    purpose, bundle = str(data["purpose"]), str(data["bundle"])
    cid = case_id or str(case["id"])
    expect = case.get("expect") or {}
    agent = data.get("agent")
    try:
        if agent:
            if env is None:
                return CaseResult(cid, False, ["araç ortamı yok"], error="ajan araç ortamı yok")
            res = gw.run_agent(
                purpose,
                bundle,
                case_messages(case),
                env.tools,
                env.execute,
                dict(schema),
                replay_key=case_replay_key(data, case),
                max_turns=int(agent.get("max_turns") or 15),
            )
        else:
            res = gw.call(
                purpose,
                bundle,
                case_messages(case),
                dict(schema),
                replay_key=case_replay_key(data, case),
            )
    except GatewayError as exc:
        return CaseResult(cid, False, [type(exc).__name__], error=str(exc)[:500])
    failures = check_output(purpose, expect, res.output)
    if agent and env is not None:
        failures += env.check(res.output, expect)
    return CaseResult(cid, not failures, failures, res.output, res.mode)


def run_set(
    gw: Any, rules_dir: Path, data: Mapping[str, Any], *, env: ToolEnv | None = None
) -> list[CaseResult]:
    """Setin her vakasını (`runs` kez) geçitten geçirir."""
    schema = load_schema(rules_dir, str(data["purpose"]))
    runs = runs_of(data)
    return [
        run_case(gw, data, case, schema, env=env, case_id=run_id(case, k, runs))
        for case in data["cases"]
        for k in range(1, runs + 1)
    ]


def write_report(
    rules_dir: Path,
    data: Mapping[str, Any],
    results: Sequence[CaseResult],
    *,
    model: str,
    provider: str,
    mode: str,
    today: dt.date | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """`extra`: rapora eklenen ek alanlar (ör. `eval_live`: maliyet, bütçe, tamamlanma)."""
    today = today or dt.date.today()
    folder = rules_dir / EVAL_DIR / RESULTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    suffix = "" if mode in LIVE_MODES else "-replay-duman"
    path = folder / f"{data['bundle']}-v{data['version']}-{today.isoformat()}{suffix}.json"
    report = {
        "bundle": data["bundle"],
        "version": data["version"],
        "date": today.isoformat(),
        "model": model,
        "provider": provider,
        "mode": mode,
        "passed": sum(r.ok for r in results),
        "total": len(results),
        "runs": runs_of(data),
        "cases": [r.__dict__ for r in results],
        **dict(extra or {}),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def mark_evaluated(
    rules_dir: Path,
    bundle: str,
    version: int,
    *,
    model: str,
    provider: str,
    results: str,
    today: dt.date | None = None,
    passed: int | None = None,
    total: int | None = None,
    guardrails_version: int | None = None,
    calls: str | None = None,
) -> None:
    """`rules/evaluations.yaml` kaydını `evaluated` yapar (baştaki açıklama yorumu korunur).

    Eski `note` ("canlı değerlendirme yapılmadı" gibi) bayatlar: yerine üretilmiş bir satır yazılır
    ki kayıt kendisiyle çelişmesin. `guardrails_version`: koşu sırasında ortak `_guardrails`
    paketinin sürümü (`guardrails` geçişli kapsamı bunu okur). `calls`: çağrı kaydı (JSONL) yolu."""
    when = (today or dt.date.today()).isoformat()
    evaluation: dict[str, Any] = {
        "date": when,
        "model": model,
        "provider": provider,
        "results": results,
    }
    if guardrails_version is not None:
        evaluation["guardrails_version"] = guardrails_version
    if calls:
        evaluation["calls"] = calls
    score = f", {passed}/{total} vaka geçti" if passed is not None and total is not None else ""
    note = f"Canlı değerlendirme {when}, {model} ({provider}){score}: {results}"
    _write_entry(rules_dir, bundle, version, evaluation, note)


def _write_entry(
    rules_dir: Path, bundle: str, version: int, evaluation: dict[str, Any], note: str
) -> None:
    path = rules_dir / EVALUATIONS_FILE
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    header = "".join(_leading_comments(lines))
    data = yaml.safe_load(text) or {}
    entry = data.setdefault("bundles", {}).setdefault(bundle, {})
    entry.pop("waiver", None)
    entry.update({"version": version, "status": "evaluated", "note": note})
    entry["evaluation"] = evaluation
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    path.write_text(header + body, encoding="utf-8")


GUARDRAILS = "guardrails"


def guardrails_coverage(rules_dir: Path) -> tuple[bool, list[str]]:
    """Ortak `_guardrails` paketi kendi başına çağrılmaz; her prompt'a eklenir. Geçişli kapsam:
    guardrails'i içeren HER paket güncel sürümüyle `evaluated` ve kaydı aynı guardrails sürümünü
    taşıyorsa guardrails de değerlendirilmiştir. Dönen liste: eksik paketler (neden)."""
    from tp_core.gateway.evaluation import load_evaluations

    versions = prompt_versions(rules_dir)
    guard_v = versions.get(GUARDRAILS)
    records = load_evaluations(rules_dir)
    missing: list[str] = []
    for name, version in versions.items():
        if name == GUARDRAILS:
            continue
        rec = records.get(name) or {}
        ev = rec.get("evaluation") or {}
        if rec.get("status") != "evaluated" or rec.get("version") != version:
            missing.append(f"{name}@v{version} (canlı değerlendirilmedi)")
        elif ev.get("guardrails_version") != guard_v:
            missing.append(f"{name}@v{version} (guardrails v{guard_v} ile değil)")
    return not missing, missing


def mark_guardrails_if_covered(
    rules_dir: Path, *, model: str, provider: str, today: dt.date | None = None
) -> bool:
    """Geçişli kapsam tamamsa `guardrails` kaydını `evaluated` yapar (aksi hâlde dokunmaz)."""
    covered, _ = guardrails_coverage(rules_dir)
    if not covered:
        return False
    from tp_core.gateway.evaluation import load_evaluations

    versions = prompt_versions(rules_dir)
    records = load_evaluations(rules_dir)
    others = sorted(n for n in versions if n != GUARDRAILS)
    reports = ", ".join(str(records[n]["evaluation"]["results"]) for n in others)
    when = (today or dt.date.today()).isoformat()
    _write_entry(
        rules_dir,
        GUARDRAILS,
        versions[GUARDRAILS],
        {
            "date": when,
            "model": model,
            "provider": provider,
            "results": "geçişli: " + reports,
            "kapsam": "transitive",
        },
        f"Canlı değerlendirme {when} (geçişli): guardrails v{versions[GUARDRAILS]}'i içeren tüm "
        f"paketler ({', '.join(others)}) bu sürümle canlı değerlendirildi.",
    )
    return True


def _leading_comments(lines: Sequence[str]) -> list[str]:
    out = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            out.append(line)
        else:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    from tp_core.gateway.config import GatewaySettings, find_rules_dir, resolve_mode
    from tp_core.gateway.factory import build_gateway
    from tp_core.gateway.testing import InMemoryCallRecorder

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", required=True, help="prompt paketi (ör. triage, dup-rank)")
    parser.add_argument("--rules-dir", type=Path, default=None)
    parser.add_argument("--update-status", action="store_true")
    parser.add_argument(
        "--allow-replay", action="store_true", help="anahtarsız duman koşusu (durum yazılmaz)"
    )
    args = parser.parse_args(argv)
    settings = GatewaySettings()
    rules_dir = args.rules_dir or find_rules_dir(settings.rules_dir)
    mode = resolve_mode(settings)
    if mode not in LIVE_MODES and not args.allow_replay:
        print(
            "HATA: değerlendirme canlı model ister (ANTHROPIC_API_KEY, TP_MODEL_MODE=live).",
            file=sys.stderr,
        )
        return 2
    data = load_set(rules_dir, args.bundle)
    version = prompt_versions(rules_dir).get(args.bundle)
    if version != data["version"]:
        print(f"HATA: set v{data['version']}, prompt v{version}; seti yenileyin", file=sys.stderr)
        return 2
    gw = build_gateway(InMemoryCallRecorder(), settings=settings)
    model = gw.models.purpose(str(data["purpose"])).model
    results = run_set(gw, rules_dir, data)
    report = write_report(
        rules_dir, data, results, model=model, provider=gw.provider_name, mode=mode
    )
    for r in results:
        print(f"{'GEÇTİ' if r.ok else 'KALDI'}\t{r.id}\t{'; '.join(r.failures)}")
    passed = all(r.ok for r in results)
    print(f"{sum(r.ok for r in results)}/{len(results)} → {report}")
    if args.update_status and passed and mode in LIVE_MODES:
        mark_evaluated(
            rules_dir,
            args.bundle,
            int(data["version"]),
            model=model,
            provider=gw.provider_name,
            results=str(report.relative_to(rules_dir)),
        )
        print(f"{EVALUATIONS_FILE}: {args.bundle}@v{data['version']} evaluated")
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
