"""specs/011 ANALIZ §4.2 deterministik kurallarının bağımsız (test tarafı) uygulaması.

Golden'lar bu yardımcıyla denetlenir; aynı kurallar üretimde `tp_core.features.cases.schema`
(`consistency_problems`, `set_problems`) ve canlı değerlendirmede
`tp_core.features.cases.kural_aynasi.generation_rule_problems` (`eval_agents` aracılığıyla)
olarak ayrıca yazılıdır. Üçü ayrı
uygulamadır: `test_goldens.py` golden'ları ve bozulmuş golden'ları üçüne birden sorar; biri
kuralı farklı okursa orada görünür.

Burada yalnız standart kütüphane kullanılır (tp_core içe aktarılmaz).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

PREFIX = {
    "EP": "EP-",
    "BVA": "BV-",
    "DT": "DT-",
    "ST": "ST-",
    "PW": "PW-",
    "UC": "UC-",
    "EG": "EG-",
    "CL": "CL-",
}
OPEN_POINT = re.compile(r"a[çc][ıiİI]k\s+nokta", re.IGNORECASE)
SUMMARY_KEYS = (
    "open_questions",
    "assumptions",
    "coverage_items",
    "negative_coverage",
    "not_covered",
    "observations",
    "automation_open_points",
    "config_matrix",
    "testability_gaps",
)


def summary_of(output: Mapping[str, Any]) -> dict[str, Any]:
    """Üretim çıktısının üst düzey listeleri (`case_uretim.ozet`)."""
    return {k: output[k] for k in SUMMARY_KEYS if k in output}


def _ids(summary: Mapping[str, Any], key: str) -> set[str]:
    return {str(x["id"]) for x in summary.get(key) or []}


def _filled(value: Any) -> bool:
    return bool(str(value or "").strip())


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _other_fields(case: Mapping[str, Any]) -> list[str]:
    """Saldırı verisinin geçmemesi gereken alanlar: başlık, ön koşul, adım, beklenen, temizlik."""
    out = [case.get("title"), case.get("expected_result")]
    out += list(case.get("preconditions") or [])
    out += list(case.get("teardown") or [])
    for step in case.get("steps") or []:
        out += [step.get("action"), step.get("data"), step.get("expected")]
    return [_norm(x) for x in out if _filled(x)]


def _occurs(value: str, field: str) -> bool:
    """Kısa veri (< 4 karakter, ör. `'`) yalnız boşlukla ayrılmış tek başına geçtiğinde sayılır."""
    if len(value) >= 4:
        return value in field
    return any(token == value for token in field.split(" "))


def case_problems(case: Mapping[str, Any], summary: Mapping[str, Any]) -> list[str]:
    """§4.2 kural 1–6 (case düzeyi)."""
    problems: list[str] = []
    covers = [str(c) for c in case.get("covers") or []]
    techniques = [str(t) for t in case.get("technique") or []]
    a_refs = [str(r) for r in case.get("assumption_refs") or []]
    q_refs = [str(r) for r in case.get("open_question_refs") or []]
    # 1
    unknown = [c for c in covers if c not in _ids(summary, "coverage_items")]
    if unknown:
        problems.append(f"kural 1: tanımsız kapsam öğesi {unknown}")
    # 2
    for technique in techniques:
        if not any(c.startswith(PREFIX[technique]) for c in covers):
            problems.append(f"kural 2: {technique} için '{PREFIX[technique]}' öğesi yok")
    prefixes = {PREFIX[t] for t in techniques if t in PREFIX}
    orphans = [c for c in covers if not any(c.startswith(p) for p in prefixes)]
    if orphans:
        problems.append(f"kural 2: tekniği olmayan öğe: {orphans}")
    # 3
    if [r for r in a_refs if r not in _ids(summary, "assumptions")]:
        problems.append("kural 3: tanımsız varsayım atıfı")
    if [r for r in q_refs if r not in _ids(summary, "open_questions")]:
        problems.append("kural 3: tanımsız açık soru atıfı")
    # 4
    readiness = case.get("readiness")
    expected = _filled(case.get("expected_result"))
    steps_filled = all(_filled(s.get("expected")) for s in case.get("steps") or [])
    if readiness == "ready":
        if a_refs or q_refs:
            problems.append("kural 4: ready case atıf taşıyor")
        if not (expected and steps_filled):
            problems.append("kural 4: ready case'te beklenen boş")
    elif readiness == "assumption_dependent":
        if not a_refs:
            problems.append("kural 4: assumption_dependent case'te varsayım atıfı yok")
        if not (expected and steps_filled):
            problems.append("kural 4: assumption_dependent case'te beklenen boş")
    elif readiness == "blocked":
        if not q_refs:
            problems.append("kural 4: blocked case'te açık soru atıfı yok")
        if expected:
            problems.append("kural 4: blocked case'te expected_result dolu")
    else:
        problems.append(f"kural 4: readiness {readiness!r}")
    # 4 (ek): "AÇIK NOKTA" yalnız varsayım/soru atıflı, hazır olmayan case'te
    fields = _other_fields(case)
    if any(OPEN_POINT.search(f) for f in fields):
        if readiness == "ready":
            problems.append("kural 4: ready case 'AÇIK NOKTA' içeriyor")
        elif not (a_refs or q_refs):
            problems.append("kural 4: 'AÇIK NOKTA' atıfsız")
    # 5, 6
    for data in case.get("test_data") or []:
        if data.get("synthetic") is not True:
            problems.append(f"kural 5: sentetik olmayan veri {data.get('name')!r}")
        value = _norm(data.get("value"))
        if (
            data.get("is_attack_payload") is True
            and value
            and any(_occurs(value, f) for f in fields)
        ):
            problems.append(f"kural 6: saldırı verisi başka alanda {data.get('name')!r}")
    return problems


def ac_refs(acceptance_criteria: Sequence[str]) -> list[str]:
    return [a.split(":", 1)[0].strip() for a in acceptance_criteria]


def set_problems(
    cases: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    acceptance_criteria: Sequence[str],
) -> list[str]:
    """§4.2 kural 7 (AC atıfı gereksinimde var) + set düzeyi kurallar."""
    problems: list[str] = []
    acs = ac_refs(acceptance_criteria)
    for n, case in enumerate(cases, start=1):
        extra = [r for r in case.get("acceptance_criteria_refs") or [] if r not in acs]
        if extra:
            problems.append(f"kural 7: C{n} gereksinimde olmayan AC {extra}")
    items = list(summary.get("coverage_items") or [])
    covered = {str(c) for case in cases for c in case.get("covers") or []}
    decisions = Counter(str(d["item"]) for d in summary.get("negative_coverage") or [])
    decision_of = {str(d["item"]): d for d in summary.get("negative_coverage") or []}
    reasoned = {
        str(n["item"]) for n in summary.get("not_covered") or [] if _filled(n.get("reason"))
    }
    known = {str(i["id"]) for i in items}
    for item in sorted(set(decisions) - known):
        problems.append(f"set: tanımsız öğeye negatif kapsam kararı {item}")
    invalid_partitions = {
        str(i["id"]) for i in items if i["valid"] is False and str(i["id"]).startswith("EP-I")
    }
    for n, case in enumerate(cases, start=1):
        if len([c for c in case.get("covers") or [] if c in invalid_partitions]) > 1:
            problems.append(f"set: C{n} birden çok geçersiz bölüm kapsıyor")
    for item in items:
        ident = str(item["id"])
        if item["valid"] is False and decisions.get(ident, 0) != 1:
            problems.append(f"set: {ident} için {decisions.get(ident, 0)} negatif kapsam kararı")
        decision = decision_of.get(ident, {})
        if ident in covered:
            if decision.get("decision") == "out_of_scope":
                problems.append(f"set: {ident} out_of_scope ama kapsanıyor")
            continue
        if decision.get("decision") in ("tested", "covered_by"):
            problems.append(f"set: {ident} kararı {decision['decision']} ama case yok")
        elif not (
            ident in reasoned
            or (decision.get("decision") == "out_of_scope" and _filled(decision.get("rationale")))
        ):
            problems.append(f"set: {ident} kapsanmıyor, gerekçesi yok")
    used = {str(r) for case in cases for r in case.get("acceptance_criteria_refs") or []}
    for ac in acs:
        if ac not in used and ac not in reasoned:
            problems.append(f"set: {ac} kapsanmıyor, gerekçesi yok")
    problems += question_problems(cases, summary)
    return problems


def question_problems(cases: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]) -> list[str]:
    """Açık soru bağı (011 K16): `not_covered.question_ref` tanımlı bir soru; her soru en az bir
    yerde anılır — case atfı, `not_covered.question_ref`, negatif kapsam kararının gerekçesi ya
    da kapsam öğesinin tanımı (yetim soru yok)."""
    problems: list[str] = []
    questions = [str(q["id"]) for q in summary.get("open_questions") or []]
    refs = {
        str(n["question_ref"])
        for n in summary.get("not_covered") or []
        if n.get("question_ref") is not None
    }
    for ref in sorted(refs - set(questions)):
        problems.append(f"set: not_covered.question_ref tanımsız soru {ref}")
    refs |= {str(r) for case in cases for r in case.get("open_question_refs") or []}
    texts = [str(d.get("rationale") or "") for d in summary.get("negative_coverage") or []]
    texts += [str(i.get("definition") or "") for i in summary.get("coverage_items") or []]
    for q in questions:
        mentioned = any(re.search(rf"(?<![A-Za-z0-9]){q}(?![0-9])", t) for t in texts)
        if q not in refs and not mentioned:
            problems.append(f"set: {q} yetim açık soru")
    return problems


def output_problems(output: Mapping[str, Any], acceptance_criteria: Sequence[str]) -> list[str]:
    """Bir üretim çıktısının (golden `output`) §4.2 ihlalleri; boş = kurallara uygun."""
    summary = summary_of(output)
    cases = list(output.get("cases") or [])
    problems = [
        f"C{n}: {p}" for n, case in enumerate(cases, start=1) for p in case_problems(case, summary)
    ]
    return problems + set_problems(cases, summary, acceptance_criteria)
