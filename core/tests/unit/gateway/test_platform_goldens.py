"""011 F4: platform ekleri ve derinleştirme golden'ları, setleri ve denetleyicileri.

- Ek dosyaları ön bilgili (`kind: platform_ek`), her biri değerlendirme kaydı ve seti olan paket;
  set ev sahibi paketle (`case-generation`) çağrılır, içerik hash'i ev sahibini kapsar.
- Platform golden'ı yalnız platform girdisiyle eşleşir; platformsuz girdi ana golden'a düşer.
- Derinleştirme golden'ları mevcut setle kimlik çakışmaz; denetleyiciler bozulmuş çıktıyı yakalar.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.features.cases import deepen, secenekler
from tp_core.features.cases.schema import normalize_ozet, set_problems
from tp_core.gateway import Gateway, ReplayStore
from tp_core.gateway.bundle import parse_prompt_file
from tp_core.gateway.config import load_model_table
from tp_core.gateway.eval_agents import deepening_problems, platform_problems
from tp_core.gateway.eval_set import case_replay_key, check_output, load_set, run_set
from tp_core.gateway.evaluation import ICERIK_KAYNAKLARI, icerik_dosyalari, prompt_versions
from tp_core.gateway.testing import InMemoryCallRecorder

EKLER = [
    "platform-common",
    "platform-web",
    "platform-mobile",
    "platform-desktop",
    "platform-api",
    "platform-data",
]
DERIN = ["case-negative", "case-technique"]


def _gw(rules_dir: Path) -> Gateway:
    return Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(rules_dir / "replay"),
    )


def test_ek_dosyalari_on_bilgili_ve_kapida() -> None:
    versions = prompt_versions(RULES)
    for ek in EKLER:
        path = RULES / "prompts" / f"{ek}.md"
        meta, body = parse_prompt_file(path.read_text(encoding="utf-8"), path)
        assert meta == {"id": ek, "version": 1, "kind": "platform_ek", "host": "case-generation"}
        assert versions[ek] == 1 and body
        data = load_set(RULES, ek)
        assert data["call_bundle"] == "case-generation" and data["purpose"] == "case_generation"
        # İçerik hash'i ev sahibi prompt + şema + amaç ayarını kapsar (ev sahibi değişince bayat).
        assert {
            f"prompts/{ek}.md",
            "prompts/platform-common.md",
            "prompts/case-generation.md",
            "schemas/case_generation.schema.json",
        } <= set(icerik_dosyalari(RULES, ek))
        assert ICERIK_KAYNAKLARI[ek].model_amaclari == ("case_generation",)
    for paket in DERIN:
        assert load_set(RULES, paket)["purpose"] == "case_deepening"


def test_her_ek_bir_platforma_bagli() -> None:
    adlar = {secenekler.platform_eki(p) for p in secenekler.PLATFORMLAR}
    assert adlar | {secenekler.ORTAK_EK} == set(EKLER)
    for ek in EKLER:
        assert secenekler.ek_yukle(ek).etiket == f"{ek}@v1"


def test_derinlestirme_semasi_uretim_semasiyla_ayni_yapida() -> None:
    import json

    gen = json.loads((RULES / "schemas/case_generation.schema.json").read_text(encoding="utf-8"))
    der = json.loads((RULES / "schemas/case_deepening.schema.json").read_text(encoding="utf-8"))
    assert der["properties"]["cases"]["minItems"] == 0
    assert der["properties"]["cases"]["maxItems"] == deepen.MAX_YENI_CASE
    for s in (gen, der):
        for k in ("$id", "title"):
            s.pop(k)
        s["properties"]["cases"].pop("minItems")
        s["properties"]["cases"].pop("maxItems")
    assert gen == der


@pytest.mark.parametrize(
    ("bundle", "case_id"),
    [
        ("platform-web", "tpd-4-web"),
        ("platform-common", "tpd-4-web"),
        ("case-negative", "tpd-1-negatif"),
        ("case-technique", "tpd-4-ep"),
    ],
)
def test_golden_kendi_beklentisini_saglar(rules_dir: Path, bundle: str, case_id: str) -> None:
    data = load_set(rules_dir, bundle)
    (case,) = [c for c in data["cases"] if c["id"] == case_id]
    store = ReplayStore(rules_dir / "replay")
    record, mode, _ = store.lookup(
        str(data["purpose"]), "-", case_replay_key(data, case)["name"], case["messages"]
    )
    assert mode == "replay"
    assert check_output(str(data["purpose"]), case["expect"], record["output"]) == []


@pytest.mark.parametrize("bundle", ["platform-web", "case-negative", "case-technique"])
def test_replay_duman_kosusu(rules_dir: Path, bundle: str) -> None:
    data = load_set(rules_dir, bundle)
    results = run_set(_gw(rules_dir), rules_dir, data)
    golden_li = {"tpd-4-web", "tpd-1-negatif", "tpd-4-ep"}
    for r in results:
        if r.id in golden_li:
            assert r.mode == "replay" and r.ok, (r.id, r.failures, r.error)
        else:  # golden'ı olmayan vaka: dürüst REPLAY-MISS (çıktı yok)
            assert not r.ok and r.mode is None and "ReplayNoOutput" in r.failures, r


def test_platform_golden_yalniz_platform_girdisine_eslesir(rules_dir: Path) -> None:
    store = ReplayStore(rules_dir / "replay")
    web = next(c for c in load_set(rules_dir, "platform-web")["cases"])
    duz = next(
        c for c in load_set(rules_dir, "case-generation")["cases"] if c["id"] == "tpd-4-giris"
    )
    golden = load_golden("case_generation", "platform-web/TPD-4")
    assert store.golden_mismatches(golden, web["messages"]) == []
    assert store.golden_mismatches(golden, duz["messages"])  # seçenek bloğu yok
    # Platformsuz girdi ana golden'a düşer; senaryo dizini taranırken platform golden'ı dönmez.
    _, mode, path = store.lookup("case_generation", "-", "TPD-4", duz["messages"])
    assert mode == "replay" and path.parent.name == "golden"


def test_platform_golden_ozellikleri() -> None:
    out = load_golden("case_generation", "platform-web/TPD-4")["output"]
    assert out["config_matrix"]["parameters"] and set(out["config_matrix"]) == {
        "parameters",
        "constraints",
    }
    assert [o["standard_ref"] for o in out["observations"]] == ["WSTG-ATHN-03"]
    web = [c for c in out["cases"] if c["platform"] == "Web"]
    # Erişilebilirlik: benimsenen WCAG maddeleri; güvenlik (N5): WSTG yalnız etiket (beklenen
    # kaynaktan), saldırı metni yalnız işaretli test verisinde (011 K19: CL öğeleri).
    a11y = [c for c in web if "a11y" in c["tags"]]
    guv = [c for c in web if "security" in c["tags"]]
    assert len(a11y) == 2 and len(guv) == 1
    assert all(r.startswith("WCAG-") for c in a11y for r in c["standard_refs"])
    assert guv[0]["standard_refs"] == ["WSTG-INPV-05"]
    assert [t["is_attack_payload"] for t in guv[0]["test_data"]] == [False, True]
    assert all("CL" in c["technique"] for c in web)
    assert all(c["requires_real_device"] is False for c in out["cases"])
    # İlk iki case ana TPD-4 golden'ıyla birebir (platformdan bağımsız).
    ana = load_golden("case_generation", "TPD-4")["output"]["cases"]
    assert out["cases"][:2] == ana


@pytest.mark.parametrize(
    ("ad", "temel"), [("negatif/TPD-1", "TPD-1"), ("teknik-ep/TPD-4", "TPD-4")]
)
def test_derinlestirme_golden_mevcut_setle_cakismaz(ad: str, temel: str) -> None:
    yeni = normalize_ozet(load_golden("case_deepening", ad)["output"])
    ana = load_golden("case_generation", temel)
    mevcut = normalize_ozet(ana["output"])
    assert deepen.id_conflicts(yeni, mevcut) == []
    numaralar = deepen.next_numbers(deepen.existing_ids(mevcut, ana["output"]["cases"]))
    for o in yeni["coverage_items"]:
        m = deepen._KIMLIK_RE.match(o["id"])
        if o["id"] not in {x["id"] for x in mevcut["coverage_items"]} and m:
            assert int(m.group(2)) >= numaralar[m.group(1)], o["id"]
    cases = ana["output"]["cases"] + load_golden("case_deepening", ad)["output"]["cases"]
    birlesik = deepen.overlay(mevcut, yeni)
    assert set_problems(cases, birlesik, ana["input_match"]["acceptance_criteria"]) == []


def _neg() -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_set(RULES, "case-negative")
    case = next(c for c in data["cases"] if c["id"] == "tpd-1-negatif")
    return copy.deepcopy(load_golden("case_deepening", "negatif/TPD-1")["output"]), case["expect"]


def test_derinlestirme_denetleyicisi_bozuk_ciktiyi_yakalar() -> None:
    out, expect = _neg()
    assert deepening_problems(out, expect) == []
    # 1. mevcut case tekrar
    bozuk = copy.deepcopy(out)
    bozuk["cases"][0]["title"] = expect["existing_titles"][0]
    assert any("tekrar" in f for f in deepening_problems(bozuk, expect))
    # 2. kimlik çakışması
    bozuk = copy.deepcopy(out)
    bozuk["coverage_items"][0]["id"] = "EP-I1"
    bozuk["negative_coverage"][0]["item"] = "EP-I1"
    bozuk["cases"][0]["covers"] = ["EP-I1"]
    bozuk["cases"][0]["test_data"][1]["class"] = "EP-I1"
    assert any("kimlik çakışması" in f for f in deepening_problems(bozuk, expect))
    # 3. uydurma mesaj
    bozuk = copy.deepcopy(out)
    bozuk["cases"][0]["expected_result"] = (
        'Ürün eklenmez; "Adet en az 1 olmalı" hata mesajı gösterilir'
    )
    assert any("AÇIK NOKTA" in f for f in deepening_problems(bozuk, expect))
    # 4. saldırı verisi adımda tekrar
    bozuk = copy.deepcopy(out)
    bozuk["cases"][0]["test_data"].append(
        {
            "name": "saldırı",
            "value": "<script>alert(1)</script>",
            "class": None,
            "synthetic": True,
            "is_attack_payload": True,
        }
    )
    bozuk["cases"][0]["steps"][2]["data"] = "<script>alert(1)</script>"
    assert deepening_problems(bozuk, expect)
    # 5. N etiketi yok
    bozuk = copy.deepcopy(out)
    bozuk["cases"][0]["tags"] = ["AI-generated"]
    assert any("N-kategori" in f for f in deepening_problems(bozuk, expect))


def test_platform_denetleyicisi() -> None:
    out = copy.deepcopy(load_golden("case_generation", "platform-web/TPD-4")["output"])
    expect = {"platforms": ["Web"], "observation_thresholds": ["44×44"], "observations_min": 1}
    assert platform_problems(out, expect) == []
    out["cases"][2]["expected_result"] += "; dokunma hedefi en az 44×44 pt"
    out["cases"][3]["platform"] = "Mobil-iOS"
    out["config_matrix"]["rows"] = [["Chrome son 2", "1366x768"]]
    out["observations"] = []
    sorunlar = platform_problems(out, expect)
    assert any("44×44" in s for s in sorunlar)
    assert any("Mobil-iOS" in s for s in sorunlar)
    assert any("satır" in s for s in sorunlar)
    assert any("gözlem" in s for s in sorunlar)
