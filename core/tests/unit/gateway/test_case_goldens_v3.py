"""case_generation golden'ları şema v3 (specs/011): ANALIZ §4.2 deterministik kuralları.

- Her case_generation golden'ı (ana + senaryo) §4.2 kurallarının hepsini sağlar. Kurallar üç ayrı
  uygulamaya sorulur: test tarafı (`case_v3_rules`), canlı değerlendirme
  (`eval_agents.generation_rule_problems`) ve üretim (`features.cases.schema`).
- Bozulmuş golden (kural başına bir ihlal) üçünde de yakalanır: uygulamalar aynı kuralı okur.
- Golden'ların v3 alanları yönergeyle (rules/prompts/case-generation.md) tutarlıdır: hazır olma
  durumu, öncelik, test verisi, temizlik, platform alanları.
- Yeni değerlendirme beklentileri (`coverage_problems`) ve rapor dağılımı.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.unit.gateway import case_v3_rules as v3
from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.features.cases import schema as case_schema
from tp_core.gateway.eval_agents import (
    coverage_problems,
    generation_stats,
)
from tp_core.gateway.eval_set import CaseResult, check_output, uretim_dagilimi, write_report

GOLDENS = ["TPD-1", "TPD-3", "TPD-4", "SERBEST", "f2-kod-hatasi/TPD-1"]
V2_FIELDS = (
    "title",
    "type",
    "risk",
    "acceptance_criteria_refs",
    "preconditions",
    "steps",
    "expected_result",
    "tags",
)


def _golden(name: str) -> dict[str, Any]:
    return load_golden("case_generation", name)


def _acs(name: str) -> list[str]:
    return list(_golden(name)["input_match"]["acceptance_criteria"])


def test_golden_list_is_complete() -> None:
    root = RULES / "replay" / "case_generation" / "golden"
    have = {str(p.relative_to(root).with_suffix("")) for p in root.rglob("*.json")}
    assert have == set(GOLDENS)


# ------------------------------------------------------------------ §4.2: üç uygulama


def _test_side(output: dict[str, Any], acs: list[str]) -> list[str]:
    return v3.output_problems(output, acs)


def _eval_side(output: dict[str, Any], acs: list[str]) -> list[str]:
    return coverage_problems(output, {"ac_coverage": v3.ac_refs(acs)})


def _production_side(output: dict[str, Any], acs: list[str]) -> list[str]:
    """Üretimdeki kurallar (T1): `consistency_problems` + `unknown_ac_refs` + `set_problems`."""
    ozet = v3.summary_of(output)
    problems: list[str] = []
    for n, case in enumerate(output["cases"], start=1):
        problems += [f"C{n}: {p}" for p in case_schema.consistency_problems(case, ozet)]
        problems += [f"C{n}: olmayan AC {r}" for r in case_schema.unknown_ac_refs(case, acs)]
    return problems + list(case_schema.set_problems(output["cases"], ozet, acs))


IMPLEMENTATIONS: dict[str, Callable[[dict[str, Any], list[str]], list[str]]] = {
    "test": _test_side,
    "eval": _eval_side,
    "uretim": _production_side,
}


@pytest.mark.parametrize("impl", sorted(IMPLEMENTATIONS))
@pytest.mark.parametrize("name", GOLDENS)
def test_every_case_generation_golden_satisfies_the_deterministic_rules(
    name: str, impl: str
) -> None:
    """Her case_generation golden'ı §4.2 kurallarını sağlar (üç uygulamada da ihlal yok)."""
    assert IMPLEMENTATIONS[impl](_golden(name)["output"], _acs(name)) == []


def test_production_validators_accept_the_goldens() -> None:
    """Üretimin şema doğrulaması (case + özet) golden'ları v3 olarak kabul eder; hiçbiri eski
    (v2) içerik sayılmaz ve hazır olma durumu golden'dakiyle aynı okunur."""
    for name in GOLDENS:
        out = _golden(name)["output"]
        assert case_schema.validate_summary(v3.summary_of(out), RULES) == [], name
        for case in out["cases"]:
            assert case_schema.validate_case(case, RULES) == [], (name, case["title"])
            assert not case_schema.is_legacy(case)
            assert case_schema.readiness_of(case) == case["readiness"]


def _set(path: list[Any], value: Any) -> Callable[[dict[str, Any]], None]:
    def apply(out: dict[str, Any]) -> None:
        node: Any = out
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return apply


def _append(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    return lambda out: out[key].append(value)


def _attack_payload_repeated(out: dict[str, Any]) -> None:
    # "Gazoz" adımın verisinde de geçiyor: saldırı verisi yalnız test_data'da durmalıydı.
    out["cases"][0]["test_data"][0]["is_attack_payload"] = True


def _drop_decision(out: dict[str, Any]) -> None:
    out["negative_coverage"].clear()


def _duplicate_decision(out: dict[str, Any]) -> None:
    out["negative_coverage"].append(dict(out["negative_coverage"][0]))


def _tested_without_case(out: dict[str, Any]) -> None:
    out["coverage_items"].append(
        {"id": "EP-I2", "ac_ref": "AC2", "definition": "Boş arama metni", "valid": False}
    )
    out["negative_coverage"].append({"item": "EP-I2", "decision": "tested", "rationale": "x"})


def _uncovered_without_reason(out: dict[str, Any]) -> None:
    out["coverage_items"].append(
        {"id": "EP-V9", "ac_ref": "AC1", "definition": "Kapsanmayan bölüm", "valid": True}
    )


def _uncovered_ac(out: dict[str, Any]) -> None:
    # AC2'nin tek case'i (C3) AC1'e bağlanır; AC2 hiçbir case'te ve `not_covered`'da değil.
    out["cases"][2]["acceptance_criteria_refs"] = ["AC1"]


# Taban: TPD-3 (C1–C3 ready, C4 assumption_dependent → A1, C5 blocked → Q1).
VIOLATIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "1-tanimsiz-kapsam-ogesi": _set(["cases", 0, "covers"], ["EP-V9"]),
    "2-teknik-onek-uyumsuz": _set(["cases", 0, "technique"], ["BVA"]),
    "3-tanimsiz-varsayim": _set(["cases", 3, "assumption_refs"], ["A9"]),
    "3-tanimsiz-soru": _set(["cases", 4, "open_question_refs"], ["Q9"]),
    "4-ready-atifli": _set(["cases", 0, "assumption_refs"], ["A1"]),
    "4-ready-beklenen-bos": _set(["cases", 0, "expected_result"], ""),
    "4-ready-adim-beklenen-bos": _set(["cases", 0, "steps", 0, "expected"], " "),
    "4-varsayim-atifsiz": _set(["cases", 3, "assumption_refs"], []),
    "4-varsayim-beklenen-bos": _set(["cases", 3, "expected_result"], ""),
    "4-blocked-sorusuz": _set(["cases", 4, "open_question_refs"], []),
    "4-blocked-beklenen-dolu": _set(["cases", 4, "expected_result"], "Ürün listelenir"),
    "5-sentetik-degil": _set(["cases", 1, "test_data", 0, "synthetic"], False),
    "6-saldiri-verisi-adimda": _attack_payload_repeated,
    "7-olmayan-ac": _set(["cases", 0, "acceptance_criteria_refs"], ["AC1", "AC7"]),
    "set-karar-yok": _drop_decision,
    "set-iki-karar": _duplicate_decision,
    "set-karar-tanimsiz-ogeye": _append(
        "negative_coverage", {"item": "EP-I7", "decision": "out_of_scope", "rationale": "x"}
    ),
    "set-tested-ama-case-yok": _tested_without_case,
    "set-kapsanmayan-gerekcesiz": _uncovered_without_reason,
    "set-ac-kapsanmiyor": _uncovered_ac,
}


@pytest.mark.parametrize("impl", sorted(IMPLEMENTATIONS))
@pytest.mark.parametrize("violation", sorted(VIOLATIONS))
def test_each_rule_violation_is_caught_by_every_implementation(violation: str, impl: str) -> None:
    """Kural başına bir ihlal: test yardımcısı, değerlendirme ve üretim kuralları aynı sonuca
    varır (golden temiz, bozulmuş golden ihlalli)."""
    out = copy.deepcopy(_golden("TPD-3")["output"])
    VIOLATIONS[violation](out)
    assert IMPLEMENTATIONS[impl](out, _acs("TPD-3")), violation


def test_blocked_case_may_leave_step_expectations_empty() -> None:
    """§4.2 kural 4: `blocked` case'te adım beklenenleri boş olabilir (TPD-3 C5)."""
    case = _golden("TPD-3")["output"]["cases"][4]
    assert case["readiness"] == "blocked" and case["expected_result"] == ""
    assert [s["expected"] for s in case["steps"]] == [""]


# ------------------------------------------------------------------ golden'lar ↔ yönerge


def test_readiness_distribution_of_the_goldens() -> None:
    """Hazır olmayan case'ler yalnız TPD-3'te ve SONDA (mevcut indeksler kaymaz); TPD-1 (prova:
    10 case onaylanır), TPD-4 (her case'in verify_and_map golden'ı var) ve SERBEST tümüyle hazır."""
    durumlar = {n: [c["readiness"] for c in _golden(n)["output"]["cases"]] for n in GOLDENS}
    assert durumlar["TPD-3"] == ["ready", "ready", "ready", "assumption_dependent", "blocked"]
    for name in ("TPD-1", "f2-kod-hatasi/TPD-1", "TPD-4", "SERBEST"):
        assert set(durumlar[name]) == {"ready"}, name
        out = _golden(name)["output"]
        assert out["open_questions"] == [] and out["assumptions"] == [], name
    tpd3 = _golden("TPD-3")["output"]
    assert [q["id"] for q in tpd3["open_questions"]] == ["Q1"]
    assert [a["id"] for a in tpd3["assumptions"]] == ["A1"]
    assert tpd3["cases"][3]["assumption_refs"] == ["A1"]
    assert tpd3["cases"][4]["open_question_refs"] == ["Q1"]
    # Yönerge: hiçbir case'in dayanmadığı soru / varsayım yazılmaz.
    assert "büyük/küçük harf" in tpd3["open_questions"][0]["question"]
    note = _golden("TPD-3")["note"]
    assert "assumption_dependent" in note and "blocked" in note


@pytest.mark.parametrize("name", GOLDENS)
def test_v3_fields_follow_the_prompt(name: str) -> None:
    out = _golden(name)["output"]
    # Platform bölümü yok: platform alanları ve üst düzey platform listeleri boş.
    assert out["observations"] == [] and out["automation_open_points"] == []
    assert out["config_matrix"] == {"parameters": [], "constraints": []}
    assert out["testability_gaps"] == []
    ids = [i["id"] for i in out["coverage_items"]]
    assert len(set(ids)) == len(ids)
    for case in out["cases"]:
        title = case["title"]
        assert list(case)[: len(V2_FIELDS)] == list(V2_FIELDS), (
            title
        )  # v2 alanları önde, sırası aynı
        assert case["platform"] is None and case["requires_real_device"] is False
        assert case["standard_refs"] == []
        assert case["test_level"] == "SYSTEM" and case["verification_point"] == "UI"
        # Öncelik: para, limit, sipariş onayı (risk high) → P1; gerekçe tek cümle.
        if case["risk"] == "high":
            assert case["priority"] == "P1", title
        gerekce = case["priority_rationale"]
        assert gerekce.endswith(".") and gerekce.count(". ") == 0, title
        assert "olasılık" in gerekce and "iş kritikliği" in gerekce, title
        # Test verisi adımlardaki somut verilerle aynı; sınıfı case'in kapsadığı bir öğe.
        metin = "\n".join([*case["preconditions"], *(s["data"] or "" for s in case["steps"])])
        assert case["test_data"], title
        for veri in case["test_data"]:
            assert veri["value"] in metin, (title, veri["name"])
            assert veri["synthetic"] is True and veri["is_attack_payload"] is False
            assert veri["class"] is None or veri["class"] in case["covers"], (title, veri["name"])
        # Bağımsızlık: sepeti değiştiren case temizlik adımı taşır.
        if any("Sepete ekle" in s["action"] for s in case["steps"]):
            assert case["teardown"], title


def test_negative_and_uncovered_decisions_are_explicit() -> None:
    """Her `valid: false` öğenin tek kararı var; kapsanmayan öğelerin gerekçesi yazılı. TPD-4'te
    kaynağın sessiz kaldığı bölüm (kayıtlı olmayan kullanıcı adı) `out_of_scope`tur; case yok."""
    for name in GOLDENS:
        out = _golden(name)["output"]
        invalid = [i["id"] for i in out["coverage_items"] if not i["valid"]]
        assert sorted(d["item"] for d in out["negative_coverage"]) == sorted(invalid), name
        covered = {c for case in out["cases"] for c in case["covers"]}
        tested = {d["item"] for d in out["negative_coverage"] if d["decision"] == "tested"}
        assert tested <= covered, name
        uncovered = {i["id"] for i in out["coverage_items"]} - covered
        out_of_scope = {
            d["item"] for d in out["negative_coverage"] if d["decision"] == "out_of_scope"
        }
        assert uncovered == {n["item"] for n in out["not_covered"]} | out_of_scope, name
    tpd4 = _golden("TPD-4")["output"]
    assert [d["decision"] for d in tpd4["negative_coverage"]] == ["tested", "out_of_scope"]
    blob = json.dumps(tpd4["cases"], ensure_ascii=False)
    assert "kayıtlı olmayan" not in blob.casefold()


def test_scenario_coverage_model_follows_its_own_document() -> None:
    """f2-kod-hatasi belgesinde bedava eşiği 6|7 adettir (ana belgede 5|6): sınır değer öğeleri
    ve AC2 case'lerinin kapsamı belgeye göre yazılır; case metni (v2 alanları) yalnız C3'te
    ayrışır."""
    base = _golden("TPD-1")["output"]
    variant = _golden("f2-kod-hatasi/TPD-1")["output"]

    def tanim(out: dict[str, Any], ident: str) -> str:
        return next(i["definition"] for i in out["coverage_items"] if i["id"] == ident)

    assert tanim(base, "BV-1").startswith("5 adet") and tanim(base, "BV-2").startswith("6 adet")
    assert tanim(variant, "BV-1").startswith("6 adet")
    assert tanim(variant, "BV-2").startswith("7 adet")
    adet = {2: 7, 3: 6, 4: 5, 10: 7}  # AC2 case'leri: sıra no → adet
    for out, kapsam in (
        (base, {2: ["EP-V3"], 3: ["BV-2"], 4: ["BV-1", "EP-V2"], 10: ["EP-V3"]}),
        (variant, {2: ["BV-2", "EP-V3"], 3: ["BV-1"], 4: ["EP-V2"], 10: ["BV-2", "EP-V3"]}),
    ):
        for n, covers in kapsam.items():
            case = out["cases"][n - 1]
            assert case["covers"] == covers, (n, case["covers"])
            assert f"P-001 × {adet[n]}" in [s["data"] for s in case["steps"]]
    for n, (a, b) in enumerate(zip(base["cases"], variant["cases"], strict=True), start=1):
        v2_farki = [k for k in V2_FIELDS if a[k] != b[k]]
        assert bool(v2_farki) == (n == 3), (n, v2_farki)
        fark = {k for k in a if a[k] != b[k]} - set(V2_FIELDS)
        assert fark <= ({"technique", "covers", "test_data"} if n in adet else set()), (n, fark)


# ------------------------------------------------------------------ değerlendirme beklentileri


def _ready_case(**over: Any) -> dict[str, Any]:
    case = copy.deepcopy(_golden("TPD-4")["output"]["cases"][1])
    case.update(over)
    return case


def _tpd4(*cases: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(_golden("TPD-4")["output"])
    out["cases"] = [*out["cases"], *cases]
    return out


def test_fabrication_markers_are_checked_in_ready_cases_only() -> None:
    expect = {"not_contains_any": ["429", "kilitlen", "zaman aşımı"]}
    assert coverage_problems(_tpd4(), expect) == []
    uydurma = _ready_case(
        title="Üç hatalı denemede hesap Kilitlenir",
        expected_result="HTTP 429 döner ve hesap kilitlenir",
    )
    failures = coverage_problems(_tpd4(uydurma), expect)
    assert "uydurma belirteci '429' hazır case'te: ['C3']" in failures
    assert "uydurma belirteci 'kilitlen' hazır case'te: ['C3']" in failures  # büyük/küçük duyarsız
    assert not [f for f in failures if "zaman aşımı" in f]
    # Tutarın parçası olan rakam belirteç sayılmaz.
    tutar = _ready_case(expected_result="Toplam 1.429,00 TL ve 429,50 TL gösterilir")
    assert coverage_problems(_tpd4(tutar), expect) == []
    # Hazır olmayan case bilinmeyeni adıyla anabilir (beklenen sonuç iddiası yoktur).
    out = _tpd4(
        _ready_case(
            title="Art arda hatalı girişte hesap kilitlenir mi (yanıt bekleniyor)",
            readiness="blocked",
            open_question_refs=["Q1"],
            expected_result="",
        )
    )
    out["open_questions"] = [{"id": "Q1", "question": "Hesap kilitlenir mi?", "owner": "PO"}]
    assert coverage_problems(out, expect) == []


def test_source_silence_must_not_become_a_ready_case() -> None:
    """Kaynağın sessiz olduğu konu: `ready` case yazılamaz; varsayıma bağlı / engelli yazılabilir
    ya da hiç yazılmaz (TPD-4 golden'ı: `out_of_scope`)."""
    expect = {
        "must_not_be_ready_about": [
            {"topic": "kayıtlı olmayan kullanıcı adıyla giriş", "keywords": ["Kayıtlı olmayan"]}
        ]
    }
    assert coverage_problems(_tpd4(), expect) == []
    baslik = "Kayıtlı olmayan kullanıcı adıyla girişte hata mesajı gösterilir"
    failures = coverage_problems(_tpd4(_ready_case(title=baslik)), expect)
    assert failures == [
        "kaynak 'kayıtlı olmayan kullanıcı adıyla giriş' konusunda sessiz; hazır (ready) case "
        "yazılamaz: ['C3']"
    ]
    out = _tpd4(_ready_case(title=baslik, readiness="assumption_dependent", assumption_refs=["A1"]))
    out["assumptions"] = [{"id": "A1", "statement": "Aynı mesaj gösterilir", "owner": "PO"}]
    assert coverage_problems(out, expect) == []


def test_ready_ac_coverage_and_case_limits() -> None:
    out = _tpd4()
    assert coverage_problems(out, {"ready_ac_coverage": ["AC1", "AC2"], "max_cases": 2}) == []
    assert coverage_problems(out, {"max_cases": 1}) == ["2 case, en çok 1"]
    # AC2'nin tek case'i engellenirse: kaynak açıkken hazır case kalmadı.
    out["cases"][1].update(readiness="blocked", open_question_refs=["Q1"], expected_result="")
    out["open_questions"] = [{"id": "Q1", "question": "?", "owner": ""}]
    assert coverage_problems(out, {"ready_ac_coverage": ["AC1", "AC2"]}) == [
        "AC2 için hazır (ready) case yok"
    ]


def test_deterministic_rules_always_apply_to_the_eval_output() -> None:
    """§4.2 kuralları beklenti anahtarı olmadan da uygulanır (çıktının tamamına)."""
    out = _tpd4()
    out["cases"][0]["covers"] = ["BV-9"]
    failures = check_output("case_generation", {}, out)
    assert "C1: tanımsız kapsam öğesi: ['BV-9']" in failures
    assert "C1: teknik EP için kapsam öğesi yok" in failures
    assert "EP-V1: kapsanmıyor ve gerekçesi yok" in failures


def test_set_expectations_name_the_known_silent_points() -> None:
    """Set: uydurma belirteçleri her story'de; sessiz nokta beklentisi TPD-3 ve TPD-4'te."""
    data = json.loads((RULES / "evaluation" / "case-generation.json").read_text(encoding="utf-8"))
    assert data["version"] == 3 and data["runs"] == 3
    by_id = {c["id"]: c for c in data["cases"]}
    for case in data["cases"]:
        expect = case["expect"]
        assert {"429", "timeout", "HTTP 4"} <= set(expect["not_contains_any"]), case["id"]
        assert expect["ready_ac_coverage"] == expect["ac_coverage"]
        assert expect["max_cases"] == 10
        assert case["messages"][0]["content"].endswith("Test seviyesi: SYSTEM")
    konular = {
        k: [t["topic"] for t in c["expect"].get("must_not_be_ready_about", [])]
        for k, c in by_id.items()
    }
    assert konular["tpd-3-arama"] == ["aramada büyük/küçük harf duyarlılığı"]
    assert konular["tpd-4-giris"] == ["kayıtlı olmayan kullanıcı adıyla giriş"]
    assert konular["tpd-1-son-hal"] == [] and konular["serbest-son-hal"] == []


# ------------------------------------------------------------------ rapor: dağılım


def test_generation_stats_of_the_goldens() -> None:
    stats = {n: generation_stats(_golden(n)["output"]) for n in GOLDENS}
    assert stats["TPD-3"]["readiness"] == {"assumption_dependent": 1, "blocked": 1, "ready": 3}
    assert stats["TPD-3"]["technique"] == {"EG": 2, "EP": 3}
    assert stats["TPD-1"]["readiness"] == {"ready": 10}
    assert stats["TPD-1"]["technique"] == {"BVA": 3, "EP": 8, "UC": 1}
    assert stats["f2-kod-hatasi/TPD-1"]["technique"] == {"BVA": 4, "EP": 8, "UC": 1}
    assert stats["TPD-4"]["technique"] == {"EP": 2}
    assert stats["SERBEST"]["technique"] == {"BVA": 1, "DT": 3, "EP": 1, "UC": 1}
    assert (stats["TPD-1"]["coverage_items"], stats["TPD-1"]["covered_items"]) == (18, 11)
    assert stats["TPD-3"]["open_questions"] == 1 and stats["TPD-3"]["assumptions"] == 1


def test_report_carries_readiness_and_technique_distribution(tmp_path: Path) -> None:
    """Eval raporu koşu başına ve toplamda readiness / teknik dağılımını ve uydurma ya da
    readiness beklentisine takılan koşuları taşır."""
    tpd3, tpd4 = _golden("TPD-3")["output"], _golden("TPD-4")["output"]
    results = [
        CaseResult("tpd-3-arama#k1", True, [], tpd3, "live"),
        CaseResult(
            "tpd-4-giris#k1", False, ["uydurma belirteci '429' hazır case'te: ['C2']"], tpd4
        ),
        CaseResult("tpd-4-giris#k2", False, ["AC2 için hazır (ready) case yok"], tpd4),
        CaseResult("tpd-4-giris#k3", False, ["SchemaValidationFailed"], None, error="x"),
    ]
    dagilim = uretim_dagilimi(results)
    assert dagilim["toplam"]["kosu"] == 3 and dagilim["toplam"]["case"] == 9
    assert dagilim["toplam"]["readiness"] == {"assumption_dependent": 1, "blocked": 1, "ready": 7}
    assert dagilim["toplam"]["technique"] == {"EG": 2, "EP": 7}
    assert dagilim["kosular"]["tpd-3-arama#k1"]["readiness"]["blocked"] == 1
    assert dagilim["uydurma"] == ["tpd-4-giris#k1"]
    assert dagilim["readiness_ihlali"] == ["tpd-4-giris#k2"]
    data = {"bundle": "case-generation", "purpose": "case_generation", "version": 3, "runs": 3}
    path = write_report(
        tmp_path, data, results, model="m", provider="p", mode="live", today=dt.date(2026, 11, 11)
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["dagilim"]["toplam"]["readiness"]["ready"] == 7
    # Başka amaçların raporuna dağılım eklenmez.
    other = write_report(
        tmp_path,
        {"bundle": "triage", "purpose": "triage", "version": 2},
        [CaseResult("a", True)],
        model="m",
        provider="p",
        mode="live",
        today=dt.date(2026, 11, 11),
    )
    assert "dagilim" not in json.loads(other.read_text(encoding="utf-8"))
