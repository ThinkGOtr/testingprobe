"""Kod üretimi (Demo-B, TEKNIK-TASARIM §8.4) golden'ları: sürüklenme, Demo-B hikâyesi, REPLAY yolu.

1. **Sürüklenme (golden-drift):** her verify_and_map golden'ının (ana + senaryo) eşlediği
   `po.method` güncel page object kaynağında doğru arity/türle vardır (regex ayrıştırıcı ve —
   node varsa — toolchain'in gerçek ts-morph sembol çıkarıcısı `POST /symbols` ile aynı tablo);
   her `expects` argümanı, golden'ın bağlı olduğu case_generation golden'ındaki onaylı case
   metninde (normalize edilerek) geçer; `browser_generate_locator` sonuçları locators.ts'teki
   testId'leri gösterir; ajan tarayıcısı doğrulama bayisiyle girer.
2. **Demo-B hikâyesi** (`f2-kod-hatasi` senaryosu: analist F2'de code_defect seçer, AC2
   özgün kalır):
   "7 adet → 1 bedava" bugünkü kodda yeşil, BREAK_CAMPAIGN'da kırmızı; "6 adet → bedava yok"
   bugünkü kodda assertion'da kırmızı (defect adayı; eksik metot değil); 750,00 TL minimum uyarısı,
   sepet sayacı ve sipariş onayı yeşil. Değerlendirme demo-app'in saf fiyat fonksiyonlarıyla yapılır
   (yerel kontrolün sonucunu öngörür; gerçek koşu test-runner'dadır).
3. **REPLAY yolu:** jira-sim → doküman düzeltmesi (F1/F3 fix_doc, F2 code_defect) → 2. tur → case
   üretimi → her case için `run_agent("verify_and_map")` sıkı kipte REPLAY-MISS'siz koşar; kayıtlı
   yörünge sırasıyla yeniden yürütülür ve `on_step` ile akar.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.unit.gateway.demo_sources import (
    DEMO_APP,
    PAGES,
    REPO,
    RULES,
    arg_matches,
    cart,
    demo_module,
    golden_ref,
    goldens,
    load_golden,
    normalize_value,
    normalized_text_values,
    page_object_methods,
    scenario_goldens,
    seed_setting,
    story_acs,
)
from tests.unit.gateway.test_replay_matching import (  # noqa: F401 (jira fikstürü)
    VERIFY_TOOLS,
    _cases,
    _check,
    _gateway,
    _story_messages,
    jira,
)
from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    MATCHED,
    VERIFY_AGENT_DEALER,
    VERIFY_BASE_URL,
    Gateway,
    ReplayMiss,
    ReplayStore,
    approved_case_text,
    golden_name,
    input_mismatches,
    load_schema,
)
from tp_core.gateway.config import load_model_table
from tp_core.gateway.promote import _golden_index
from tp_core.gateway.snapshot_refs import Hedef, locate_ref, snapshot_lines
from tp_core.gateway.testing import InMemoryCallRecorder
from tp_core.ports import AgentStep, ModelMessage

SCENARIO = "f2-kod-hatasi"
VERIFY = [*goldens("verify_and_map"), *scenario_goldens("verify_and_map")]
# Demo-A/B senaryo golden'ları (f2-kod-hatasi). Faz 4 amaçlarının (triage, bug_draft, dup_rank)
# senaryo dizinleri hata türüne göredir; test_defect_goldens.py denetler.
DEFECT_PURPOSES = ("triage", "bug_draft", "dup_rank")
# 011 F4 senaryo golden'ları (`platform-*/`, `negatif/`, `teknik-*/`) kod üretimine bağlı değildir;
# test_platform_goldens.py denetler.
SCENARIOS = [
    g for g in scenario_goldens() if g[0] not in DEFECT_PURPOSES and g[1].parent.name == SCENARIO
]
METHODS = page_object_methods()
E2E_DEALERS = ("bayi1", "bayi2")
SYMBOLS_CLI = REPO / "toolchain" / "symbols" / "dist" / "src" / "cli.js"


def _ids(items: list[tuple[str, Path, Any]]) -> list[str]:
    return [f"{p}/{golden_ref(path)}" for p, path, _ in items]


def _case_of(golden: dict[str, Any]) -> dict[str, Any]:
    """Golden'ın bağlı olduğu onaylı case (ana ya da senaryo case_generation golden'ı)."""
    case = golden["case"]
    source = case.get("case_golden") or case["jira_key"]
    return load_golden("case_generation", source)["output"]["cases"][case["sira_no"] - 1]


def _expected_text(case: dict[str, Any]) -> str:
    return " ".join([*(s["expected"] for s in case["steps"]), case["expected_result"]])


# ------------------------------------------------------------------ 0. senaryo golden'ları


@pytest.mark.parametrize(("purpose", "path", "golden"), SCENARIOS, ids=_ids(SCENARIOS))
def test_scenario_goldens_are_declared_and_valid(purpose: str, path: Path, golden: dict) -> None:
    assert golden["purpose"] == purpose
    assert golden["golden"] == golden_ref(path)
    assert path.parent.name == SCENARIO
    # Senaryo golden'ı yalnızca girdi beyanıyla döner; beyansız olamaz.
    assert isinstance(golden.get("input_match"), dict) and golden["input_match"]
    assert "Elle hazırlandı" in golden["note"] or "elle hazırlandı" in golden["note"]
    errors = list(Draft202012Validator(load_schema(RULES, purpose)).iter_errors(golden["output"]))
    assert not errors, [e.message for e in errors]


def test_scenario_document_is_the_code_defect_decision() -> None:
    """f2-kod-hatasi belgesi: AC2 jira-sim seed'indeki özgün metin, diğerleri ana 2. turla aynı."""
    base = load_golden("consistency_check", "TPD-1-r2")["input_match"]["acceptance_criteria"]
    original = story_acs("TPD-1")
    for purpose, name in (("consistency_check", "TPD-1-r2"), ("case_generation", "TPD-1")):
        acs = load_golden(purpose, f"{SCENARIO}/{name}")["input_match"]["acceptance_criteria"]
        assert acs[1] == original["AC2"], purpose
        assert acs[:1] + acs[2:] == base[:1] + base[2:], purpose


def test_scenario_round_two_findings_inherit_round_one_code_defects() -> None:
    """2. turda yeniden raporlanan farklar 1. turun code_defect bulgularıyla aynıdır (tür, AC,
    kanıt): gereksinim akışı `previous_decision` ile bunları stale yapar → son hal."""
    r1 = {f["id"]: f for f in load_golden("consistency_check", "TPD-1")["output"]["findings"]}
    r2 = load_golden("consistency_check", f"{SCENARIO}/TPD-1-r2")["output"]["findings"]
    key = lambda f: (f["type"], f["doc_ref"], json.dumps(f["evidence"], sort_keys=True))  # noqa: E731
    assert {key(f) for f in r2} <= {key(r1["F2"]), key(r1["F4"])} | {
        key(f) for f in load_golden("consistency_check", "TPD-1-r2")["output"]["findings"]
    }
    assert key(r1["F2"]) in {key(f) for f in r2}


# Onaylı case metnini (`approved_case_text`, verify_and_map girdi beyanı) oluşturan v2 alanları.
CASE_TEXT_FIELDS = (
    "title",
    "type",
    "risk",
    "acceptance_criteria_refs",
    "preconditions",
    "steps",
    "expected_result",
    "tags",
)
# AC2'nin case'leri (7 / 6 / 5 / 7 adet): senaryo belgesinde bedava eşiği 6|7, ana belgede 5|6.
AC2_CASES = (2, 3, 4, 10)


def test_scenario_cases_differ_from_the_main_golden_only_in_the_ac2_boundary() -> None:
    """Case metni (v2 alanları) yalnız C3'te ayrışır: verify_and_map ana golden'ları diğer
    case'lerle eşleşir. Şema v3 kapsam alanları (`technique`, `covers`, `test_data.class`) belgenin
    eşiğine göre yazıldığından AC2 case'lerinde farklı olabilir; başka hiçbir alan ayrışmaz."""
    base = load_golden("case_generation", "TPD-1")["output"]["cases"]
    variant = load_golden("case_generation", f"{SCENARIO}/TPD-1")["output"]["cases"]
    assert len(base) == len(variant)
    pairs = list(enumerate(zip(base, variant, strict=True), 1))
    text_differs = [n for n, (a, b) in pairs if any(a[k] != b[k] for k in CASE_TEXT_FIELDS)]
    assert text_differs == [3]
    for n, (a, b) in pairs:
        other = {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)} - set(CASE_TEXT_FIELDS)
        allowed = {"technique", "covers", "test_data"} if n in AC2_CASES else set()
        assert other <= allowed, (n, sorted(other))
    c3 = variant[2]
    assert c3["type"] == "boundary" and c3["acceptance_criteria_refs"] == ["AC2"]
    assert "bedava adet 0" in _expected_text(c3)
    # Story kuralı (6 öde + 1 bedava = adet // 7) 6 adette bedava vermez; case bunu söyler.
    assert 6 // 7 == 0


# ------------------------------------------------------------------ 1. sürüklenme


def _real_symbol_table() -> dict[str, Any]:
    node = shutil.which("node")
    if not node or not SYMBOLS_CLI.is_file():
        pytest.skip("node veya toolchain/symbols/dist yok (npm run build)")
    out = subprocess.run(
        [node, str(SYMBOLS_CLI), "--root", str(DEMO_APP / "e2e")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_regex_parser_agrees_with_the_real_symbol_extractor() -> None:
    """Golden testlerinin page object ayrıştırıcısı toolchain'in `/symbols` tablosuyla aynı:
    sınıf, metot, parametre türleri, action/expect türü."""
    table = _real_symbol_table()
    assert table["errors"] == []
    real = {
        (po["class"], m["name"]): (tuple(p["type"] for p in m["params"]), m["kind"])
        for po in table["page_objects"]
        for m in po["methods"]
    }
    ours = {k: (m.param_types, "expect" if m.is_expect else "action") for k, m in METHODS.items()}
    assert ours == real


def _locator_test_ids() -> set[str]:
    ids: set[str] = set()
    for path in PAGES.glob("**/locators.ts"):
        ids |= set(re.findall(r'testId:\s*"([^"]+)"', path.read_text(encoding="utf-8")))
    return ids


LOCATOR_IDS = _locator_test_ids()


def _known_test_id(test_id: str) -> bool:
    return test_id in LOCATOR_IDS or any(
        p.endswith("-") and test_id.startswith(p) and len(test_id) > len(p) for p in LOCATOR_IDS
    )


@pytest.mark.parametrize(("purpose", "path", "golden"), VERIFY, ids=_ids(VERIFY))
def test_verify_golden_maps_to_current_page_objects(purpose: str, path: Path, golden: dict) -> None:
    case = _case_of(golden)
    assert golden["case"]["title"] == case["title"]
    out = golden["output"]
    for m in out["step_mapping"]:
        meth = METHODS.get((m["po"], m["method"]))
        assert meth is not None, f"{m['po']}.{m['method']} page object kaynağında yok"
        assert not meth.is_expect
        assert len(m["args"]) == len(meth.param_types), m
        assert all(arg_matches(a, t) for a, t in zip(m["args"], meth.param_types, strict=True))
        if m["method"] == "login":
            # Eşleme argümanı case verisidir (tarayıcıdaki doğrulama bayisi değil).
            step = next(s for s in case["steps"] if s["id"] == m["step_id"])
            assert " / ".join(m["args"]) == step["data"]
    text = _expected_text(case)
    values = normalized_text_values(text)
    for e in out["expects"]:
        meth = METHODS.get((e["po"], e["method"]))
        assert meth is not None and meth.is_expect, e
        assert len(e["args"]) == len(meth.param_types), e
        for arg in e["args"]:
            is_money = isinstance(arg, str) and re.fullmatch(r"-?[\d.]+,\d{2}\s*TL", arg)
            if isinstance(arg, str) and not is_money:
                assert arg in text, f"{arg!r} onaylı case metninde yok"
            else:
                assert normalize_value(arg) in values, f"{arg!r} onaylı case metninde yok"


def _locators_by_role_name() -> dict[tuple[str, str], set[str]]:
    """locators.ts: (rol, ad) → testId'ler (sembol tablosunun modele verdiği rol/ad)."""
    out: dict[tuple[str, str], set[str]] = {}
    rx = re.compile(r'testId:\s*"([^"]+)",\s*role:\s*"([^"]+)",\s*name:\s*"([^"]*)"')
    for path in PAGES.glob("**/locators.ts"):
        for test_id, role, name in rx.findall(path.read_text(encoding="utf-8")):
            out.setdefault((role, name), set()).add(test_id)
    return out


LOCATORS_BY_ROLE = _locators_by_role_name()
_SNAPSHOT_ITEM = re.compile(r'^(?P<role>[a-z]+)(?: "(?P<name>[^"]*)")?.*\[ref=(?P<ref>e\d+)\]')


def _assert_locators_verified_from_snapshot_refs(steps: list[dict[str, Any]]) -> None:
    """§8.4 adım 2 / Constitution V: eleman SON snapshot'ta rol/adla bulunur, generate_locator o
    snapshot ref'iyle çağrılır ve sayfanın verdiği testId, aynı rol/ada sahip page object
    locator'ının testId'sidir (seçiciyi geri yankılamak doğrulama değildir).

    Prompt v3 kuralı: eylemde (click/type) kullanılan HER testId, ilk kullanımından önce bir
    generate_locator sonucunda görülmüş olmalıdır. Ref alan her adım yapılandırılmış `hedef`
    (rol/ad/kapsam) taşır ve hedef, kayıttaki snapshot'ta tam o ref'e çözülür (REPLAY ref'i aynı
    hedeften canlı snapshot'ta yeniden çözer; kayıttaki ref oturuma özgüdür)."""
    last_snapshot: dict[str, tuple[str, str]] = {}
    last_lines: list[str] = []
    acted: set[str] = set()
    verified_ids: set[str] = set()
    verified = 0
    for s in steps:
        if s["tool"] == "browser_snapshot":
            last_snapshot = {}
            last_lines = snapshot_lines(snapshot_from_summary(s["result_summary"])) or []
            for item in s["result_summary"].split(" | "):
                m = _SNAPSHOT_ITEM.match(item)
                if m:
                    last_snapshot[m["ref"]] = (m["role"], m["name"] or "")
        elif s["tool"] in ("browser_click", "browser_type"):
            ids = set(re.findall(r'data-testid="([^"]+)"', s["args"]["target"]))
            missing = ids - verified_ids
            assert not missing, f"{sorted(missing)} ilk kullanımdan önce doğrulanmamış"
            acted |= ids
        elif s["tool"] == "browser_generate_locator":
            ref = s["args"]["target"]
            assert re.fullmatch(r"e\d+", ref), f"generate_locator snapshot ref'i almalı: {ref!r}"
            assert ref in last_snapshot, f"{ref} son snapshot'ta yok"
            hedef = Hedef.from_raw(s.get("hedef"))
            assert hedef is not None, f"{ref}: yapılandırılmış hedef (rol/ad/kapsam) yok"
            assert locate_ref(last_lines, hedef) == ref, (hedef, ref)
            role, name = last_snapshot[ref]
            assert (role, name.startswith(hedef.ad)) == (hedef.rol, True), (hedef, role, name)
            got = re.findall(r"getByTestId\('([^']+)'\)", s["result_summary"])
            assert got, s["result_summary"]
            # Rol/ad → locator: ad, locator adıyla başlar (bağlantı adı sayacı da içerir).
            candidates = {
                tid
                for (r, n), ids in LOCATORS_BY_ROLE.items()
                if r == role and (n == name or (n and name.startswith(n + " ")))
                for tid in ids
            }
            assert any(
                got[-1] == c or (c.endswith("-") and got[-1].startswith(c)) for c in candidates
            ), (role, name, got, candidates)
            assert all(_known_test_id(i) for i in got), got
            assert got[-1] not in acted, f"{got[-1]} doğrulanmadan önce kullanılmış"
            verified_ids.update(got)
            verified += 1
    assert verified >= 1, "hiç locator doğrulanmamış"


@pytest.mark.parametrize(("purpose", "path", "golden"), VERIFY, ids=_ids(VERIFY))
def test_recorded_trajectory_is_realistic(purpose: str, path: Path, golden: dict) -> None:
    steps = golden["steps"]
    assert 0 < len(steps) <= 25
    tools = [s["tool"] for s in steps]
    assert set(tools) <= ALLOWED_AGENT_TOOLS["verify_and_map"]
    assert "browser_snapshot" in tools
    for s in steps:
        blob = json.dumps(s, ensure_ascii=False)
        assert "127.0.0.1" not in blob and "localhost" not in blob, "yerel kayıt kökü kalmış"
        if s["tool"] == "browser_navigate":
            assert s["args"]["url"].startswith(VERIFY_BASE_URL + "/")
        if s["tool"] in ("browser_click", "browser_type"):
            ids = re.findall(r'data-testid="([^"]+)"', s["args"]["target"])
            assert ids and all(_known_test_id(i) for i in ids), s["args"]["target"]
    _assert_locators_verified_from_snapshot_refs(steps)
    # Ajan tarayıcısı doğrulama bayisiyle girer; e2e bayileri tarayıcıya yazılmaz.
    typed_users = [
        s["args"]["text"] for s in steps if "login-username" in s["args"].get("target", "")
    ]
    assert typed_users == [VERIFY_AGENT_DEALER]
    # Sayfa değiştiren her eylemden sonra, sonraki etkileşimden önce snapshot alınır.
    url, pending = None, False
    for s in steps:
        if s["tool"] == "browser_snapshot":
            pending = False
            continue
        if pending and s["tool"] in ("browser_click", "browser_type", "browser_navigate"):
            pytest.fail(f"yeni sayfada snapshot alınmadan {s['tool']}")
        m = re.search(r"· URL (\S+)$", s["result_summary"])
        if m and m.group(1) != url:
            url, pending = m.group(1), True
    assert not pending, "son sayfa snapshot'sız"


@pytest.mark.parametrize(("purpose", "path", "golden"), VERIFY, ids=_ids(VERIFY))
def test_observed_mismatch_is_written_to_evidence(purpose: str, path: Path, golden: dict) -> None:
    """Sayfada gözlenen değer case'ten farklıysa (defect adayı) sepet adımının evidence_ref'i
    "beklenen:" notunu taşır; fark yoksa taşımaz. Beklenti hiçbir zaman sayfaya uydurulmaz."""
    failing = _failing_expects(golden, break_campaign=False)
    cart_steps = [
        m for m in golden["output"]["step_mapping"] if m["method"] == "openCart" and m["verified"]
    ]
    for m in cart_steps:
        assert ("beklenen:" in m["evidence_ref"]) == bool(failing), (m["evidence_ref"], failing)
        # Kayıt anındaki değerler REPLAY'de yeniden ölçülmez: metin bunu açıkça etiketler.
        assert "kayıttaki not — gözlenen:" in m["evidence_ref"], m["evidence_ref"]
    # Defect adayı kararı (demo_check) yapılandırılmış alandan okunur; metinle tutarlıdır.
    beyan = golden.get("defect_adayi")
    assert bool(beyan) == bool(failing), (beyan, failing)
    if beyan:
        assert beyan["step_id"] in {m["step_id"] for m in cart_steps}
        assert f"· beklenen: {beyan['beklenen']}" in next(
            m["evidence_ref"] for m in cart_steps if m["step_id"] == beyan["step_id"]
        )


# ------------------------------------------------------------------ 2. Demo-B hikâyesi


def _adds(golden: dict[str, Any]) -> list[tuple[str, int]]:
    return [
        (m["args"][0], m["args"][1])
        for m in golden["output"]["step_mapping"]
        if m["method"] == "addToCart"
    ]


def _failing_expects(golden: dict[str, Any], *, break_campaign: bool) -> list[str]:
    """Yerel kontrolde kırmızı olacak assertion'lar (demo-app saf fiyat fonksiyonlarıyla)."""
    import os

    lines = _adds(golden)
    if not lines:
        return []
    old = os.environ.get("BREAK_CAMPAIGN")
    os.environ["BREAK_CAMPAIGN"] = "1" if break_campaign else ""
    try:
        result = cart(lines)
    finally:
        if old is None:
            os.environ.pop("BREAK_CAMPAIGN", None)
        else:
            os.environ["BREAK_CAMPAIGN"] = old
    tl = demo_module("money").format_tl
    by_code = {s.urun_kod: s for s in result.satirlar}
    warns = [u.mesaj for u in result.uyarilar]
    failing = []
    for e in golden["output"]["expects"]:
        name, args = e["method"], e["args"]
        actual: Any
        if name == "expectLineQuantity":
            actual, want = by_code[args[0]].adet, args[1]
        elif name == "expectFreeQuantity":
            actual, want = by_code[args[0]].bedava_adet, args[1]
        elif name == "expectSubtotal":
            actual, want = tl(result.ara_toplam), args[0]
        elif name == "expectDiscount":
            actual, want = tl(result.indirim), args[0]
        elif name in ("expectTotal", "expectConfirmedTotal"):
            actual, want = tl(result.toplam), args[0]
        elif name == "expectCartCount":
            actual, want = result.adet_toplam, args[0]
        elif name == "expectMinOrderWarning":
            actual, want = args[0] in warns, True
        elif name == "expectNoMinOrderWarning":
            actual, want = not warns, True
        elif name == "expectCheckoutDisabled":
            actual, want = not result.onaylanabilir, True
        elif name == "expectCheckoutEnabled":
            actual, want = result.onaylanabilir, True
        else:
            continue  # sepet dışı (onay alanı, sipariş geçmişi, giriş)
        if actual != want:
            failing.append(f"{name}({args}) ≠ {actual}")
    return failing


def _scenario_verify_golden(n: int, case: dict[str, Any]) -> dict[str, Any]:
    """Geçidin bulacağı golden: önce ana ad, sonra senaryo (girdi beyanıyla)."""
    msg = _verify_messages(case, n)
    for name in (golden_name("TPD-1", case_no=n), f"{SCENARIO}/TPD-1-C{n}"):
        path = RULES / "replay" / "verify_and_map" / "golden" / f"{name}.json"
        if path.is_file():
            golden = json.loads(path.read_text(encoding="utf-8"))
            if not input_mismatches(golden["input_match"], msg):
                return golden
    raise AssertionError(f"C{n} için eşleşen verify_and_map golden'ı yok")


SCENARIO_CASES = load_golden("case_generation", f"{SCENARIO}/TPD-1")["output"]["cases"]
SNAP = "browser_snapshot"
GEN = "browser_generate_locator"


def _scenario_verify_golden_or_none(case: dict[str, Any], n: int) -> dict[str, Any] | None:
    """Case'in REPLAY'de döneceği verify golden'ı (ana ya da senaryo; yoksa None)."""
    msg = _verify_messages(case, n)
    for name in (golden_name("TPD-1", case_no=n), f"{SCENARIO}/TPD-1-C{n}"):
        path = RULES / "replay" / "verify_and_map" / "golden" / f"{name}.json"
        if path.is_file():
            golden = json.loads(path.read_text(encoding="utf-8"))
            if not input_mismatches(golden["input_match"], msg):
                return golden
    return None


def _by_title(prefix: str) -> tuple[int, dict[str, Any], dict[str, Any]]:
    for n, case in enumerate(SCENARIO_CASES, start=1):
        if case["title"].startswith(prefix):
            return n, case, _scenario_verify_golden(n, case)
    raise AssertionError(prefix)


def test_demo_b_seven_free_one_is_green_today_and_red_under_break_campaign() -> None:
    n, _case, golden = _by_title("7 adet kampanyalı üründe 1 adet bedava")
    assert golden["golden"] == golden_name("TPD-1", case_no=n)  # ana golden eşleşir
    assert _failing_expects(golden, break_campaign=False) == []
    broken = _failing_expects(golden, break_campaign=True)
    assert any(f.startswith("expectFreeQuantity") for f in broken), broken


def test_demo_b_six_no_free_is_a_defect_candidate_not_a_missing_method() -> None:
    n, _case, golden = _by_title("6 adet kampanyalı üründe bedava ürün verilmez")
    assert golden["golden"] == f"{SCENARIO}/TPD-1-C{n}"
    out = golden["output"]
    # Eşleme tam ve doğrulanmış: kod üretimi durmaz, test yazılır.
    assert out["missing_methods"] == []
    assert all(m["verified"] for m in out["step_mapping"])
    # Beklenti case'ten (0 bedava), bugünkü kod 1 verir → yerel kontrolde assertion kırmızı.
    assert {"po": "CartPage", "method": "expectFreeQuantity", "args": ["P-001", 0]} in out[
        "expects"
    ]
    failing = _failing_expects(golden, break_campaign=False)
    assert any(f.startswith("expectFreeQuantity") for f in failing), failing
    assert demo_module("campaign").bedava_adet(6) == 1  # dikilen hata: adet // 6


def test_demo_b_other_cases_are_green_on_todays_code() -> None:
    min_msg = demo_module("pricing").min_siparis_mesaji(Decimal(seed_setting("min_siparis_tutari")))
    for prefix, must in (
        ("Kampanyasız siparişte minimum tutarın altında", ("expectMinOrderWarning", [min_msg])),
        ("Sepete ekle ile ürün sepete eklenir", ("expectCartCount", [1])),
        ("Onaylanan siparişin numarası gösterilir", ("expectConfirmation", [])),
    ):
        _, _, golden = _by_title(prefix)
        assert _failing_expects(golden, break_campaign=False) == [], prefix
        pairs = [(e["method"], e["args"]) for e in golden["output"]["expects"]]
        assert must in pairs, (prefix, pairs)
    assert min_msg == "Minimum sipariş tutarı 750,00 TL"


def test_fix_doc_alternative_has_no_assertion_defect_candidate() -> None:
    """Alternatif F2 `fix_doc` yolunda (`golden/*.json`; demo'nun ana yolu `f2-kod-hatasi`)
    kampanya case'leri bugünkü kodda yeşildir; tek kod hatası AC4'tür ve eksik metot olarak durur
    (assertion'a varmaz)."""
    cases = load_golden("case_generation", "TPD-1")["output"]["cases"]
    for n in range(1, len(cases) + 1):
        golden = load_golden("verify_and_map", golden_name("TPD-1", case_no=n))
        assert _failing_expects(golden, break_campaign=False) == [], cases[n - 1]["title"]


# ------------------------------------------------------------------ 3. REPLAY yolu (geçit)


SYMBOLS = {
    "schema_version": 1,
    "sha": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    "root": "/tmp/a",
    "page_objects": [
        {
            "class": "CartPage",
            "file": "pages/cart/cart.page.ts",
            "doc": "",
            "methods": [
                {
                    "name": "expectTotal",
                    "params": [{"name": "amount", "type": "string"}],
                    "returns": "Promise<void>",
                    "kind": "expect",
                    "async": True,
                    "doc": "",
                    "line": 7,
                }
            ],
            "locators": {
                "total": {"testId": "cart-total", "role": "definition", "name": "Genel toplam"}
            },
        }
    ],
    "locator_files": [],
    "errors": [],
}


def _verify_messages(
    case: dict[str, Any],
    n: int,
    *,
    jira_key: str = "TPD-1",
    symbols: dict[str, Any] | None = None,
    feedback: str | None = None,
) -> list[ModelMessage]:
    """ÜRETİMİN girdi kurucusu (`features.codegen.service.mapping_messages`): testler ikinci bir
    biçim kurmaz; anahtar kararlılığı ve golden beyanı gerçek girdiyle denenir."""
    from tp_core.features.codegen.checks import SymbolTable
    from tp_core.features.codegen.service import case_ref, mapping_messages

    return mapping_messages(
        case,
        case_ref(jira_key, n),
        SymbolTable(symbols or SYMBOLS),
        agent_dealer=VERIFY_AGENT_DEALER,
        demo_web_url=VERIFY_BASE_URL,
        feedback=feedback,
    )


def snapshot_from_summary(summary: str) -> str:
    """Kayıttaki snapshot özetinden (`a | b | …`) MCP 1.64 biçiminde düz snapshot (REPLAY ref'i
    canlı snapshot'tan çözdüğü için sahte tarayıcı da snapshot döndürmelidir)."""
    items = [p for p in summary.split(" | ") if not p.startswith("URL ")]
    body = "\n".join(f"- {p}" for p in items)
    return f"### Page\n### Snapshot\n```yaml\n{body}\n```"


def _run_verify(gw: Gateway, rules_dir: Path, case: dict[str, Any], n: int):
    calls: list[tuple[str, dict[str, Any]]] = []
    streamed: list[AgentStep] = []
    golden = _scenario_verify_golden_or_none(case, n)
    recorded = {
        tool: iter(
            [s["result_summary"] for s in (golden or {}).get("steps", []) if s["tool"] == tool]
        )
        for tool in (SNAP, GEN)
    }

    def execute(name: str, args: dict[str, Any]) -> str:
        calls.append((name, args))
        if name == SNAP:
            return snapshot_from_summary(next(recorded[SNAP], ""))
        if name == GEN:  # sayfa kayıttaki locator'ı verir (sapma yok)
            return next(recorded[GEN], "")
        return f"{name} tamam"

    result = gw.run_agent(
        "verify_and_map",
        "verify-and-map",
        _verify_messages(case, n),
        VERIFY_TOOLS,
        execute,
        load_schema(rules_dir, "verify_and_map"),
        replay_key={"name": golden_name("TPD-1", case_no=n), "jira_key": "TPD-1"},
        on_step=streamed.append,
    )
    return result, calls, streamed


def test_code_defect_scenario_replays_end_to_end_in_strict_mode(rules_dir, jira) -> None:  # noqa: F811
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=True)
    issue = jira.get_issue("TPD-1")
    first = _check(gw, rules_dir, "TPD-1", _story_messages(issue), 1)
    by_id = {f["id"]: f for f in first.output["findings"]}
    # Analist: F1 ve F3 fix_doc, F2 (kampanya) ve F4 (kredi limiti) code_defect.
    acs = {a.split(":", 1)[0]: a for a in issue.acceptance_criteria}
    for fid in ("F1", "F3"):
        text = by_id[fid]["suggested_doc_text"]
        acs[text.split(":", 1)[0]] = text
    jira.update_description(
        "TPD-1", issue.description, [acs[k] for k in sorted(acs, key=lambda r: int(r[2:]))]
    )
    issue = jira.get_issue("TPD-1")
    second = _check(gw, rules_dir, "TPD-1", _story_messages(issue), 2)
    assert second.mode == "replay"
    assert recorder.ai_calls[-1]["ek"]["replay_kaynagi"] == (
        f"consistency_check/golden/{SCENARIO}/TPD-1-r2.json"
    )
    cases = _cases(gw, rules_dir, "TPD-1", _story_messages(issue))
    assert cases.mode == "replay"
    assert recorder.ai_calls[-1]["ek"]["replay_kaynagi"] == (
        f"case_generation/golden/{SCENARIO}/TPD-1.json"
    )
    for n, case in enumerate(cases.output["cases"], start=1):
        result, calls, streamed = _run_verify(gw, rules_dir, case, n)
        row = recorder.ai_calls[-1]
        assert result.mode == "replay" and row["mod"] == "replay", case["title"]
        assert row["ek"]["replay_kokeni"] == MATCHED
        used = row["ek"]["replay_kaynagi"]
        expected = (
            f"verify_and_map/golden/{SCENARIO}/TPD-1-C{n}.json"
            if n == 3
            else f"verify_and_map/golden/TPD-1-C{n}.json"
        )
        assert used == expected, (n, used)
        golden = json.loads((rules_dir / "replay" / used).read_text(encoding="utf-8"))
        # Yörünge deterministik: kayıtlı araç çağrıları aynı sırayla yeniden yürütülür ve akar.
        recorded = [(s["tool"], s["args"]) for s in golden["steps"]]
        assert calls == recorded
        assert [(s.tool, s.args) for s in streamed] == recorded
        assert [s.result_summary for s in streamed if s.tool not in (SNAP, GEN)] == [
            f"{t} tamam" for t, _ in recorded if t not in (SNAP, GEN)
        ]
        gens = [s.result_summary for s in streamed if s.tool == GEN]
        assert gens == [s["result_summary"] for s in golden["steps"] if s["tool"] == GEN]
        assert result.output == golden["output"]


def test_main_path_cases_never_pick_the_scenario_goldens(rules_dir) -> None:
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=True)
    cases = load_golden("case_generation", "TPD-1")["output"]["cases"]
    for n, case in enumerate(cases, start=1):
        result, _, _ = _run_verify(gw, rules_dir, case, n)
        assert result.output == load_golden("verify_and_map", f"TPD-1-C{n}")["output"]


def test_round_one_document_does_not_match_the_scenario_cases(rules_dir, jira) -> None:  # noqa: F811
    """Düzeltilmemiş (özgün) TPD-1'de case üretimi senaryo golden'ına da düşmez (AC3 farklı)."""
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=True)
    with pytest.raises(ReplayMiss):
        _cases(gw, rules_dir, "TPD-1", _story_messages(jira.get_issue("TPD-1")))


def test_changed_scenario_case_is_an_honest_replay_miss(rules_dir) -> None:
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=True)
    case = json.loads(json.dumps(SCENARIO_CASES[2]))
    case["steps"][3]["expected"] = case["steps"][3]["expected"].replace("bedava adet 0", "bedava 0")
    with pytest.raises(ReplayMiss):
        _run_verify(gw, rules_dir, case, 3)


# ------------------------------------------------------------------ girdi yardımcıları


@pytest.mark.parametrize(("purpose", "path", "golden"), VERIFY, ids=_ids(VERIFY))
def test_production_case_block_satisfies_the_golden_declaration(
    purpose: str, path: Path, golden: dict
) -> None:
    """Golden beyanı: yalnızca kendi `case:<KEY>-C<n>` bloğu ve onaylı case'in TAM metni."""
    case = _case_of(golden)
    key, n = golden["case"]["jira_key"], golden["case"]["sira_no"]
    spec = golden["input_match"]
    assert spec["sources"] == [f"case:{key}-C{n}"]
    assert spec["case_text"] == approved_case_text(case)
    assert set(spec) == {"sources", "case_text"}
    assert input_mismatches(spec, _verify_messages(case, n, jira_key=key)) == []
    # Başka bir case numarası (aynı içerik) kendi bloğu değildir.
    assert input_mismatches(spec, _verify_messages(case, n + 20, jira_key=key))


@pytest.mark.parametrize(
    "edit",
    [
        "append_expected",
        "append_step_expected",
        "add_step",
        "change_data",
        "add_precondition",
    ],
)
def test_any_edit_to_the_approved_case_is_an_honest_replay_miss(rules_dir, edit: str) -> None:
    """`contains` yalnızca varlık denetlerdi: beklenen metne eklenen yeni bir beklenti eski
    eşlemeyi REPLAY olarak döndürürdü. Tam case metni beyanıyla her düzenleme REPLAY-MISS'tir."""
    case = json.loads(json.dumps(load_golden("case_generation", "TPD-1")["output"]["cases"][1]))
    if edit == "append_expected":
        case["expected_result"] += " ve sipariş onay butonu pasif olur"
    elif edit == "append_step_expected":
        case["steps"][3]["expected"] += " ve sipariş onay butonu pasif olur"
    elif edit == "add_step":
        case["steps"].append(
            {"id": "S5", "action": "Siparişi onayla", "data": None, "expected": "Onaylanır"}
        )
    elif edit == "change_data":
        case["steps"][2]["data"] = "P-001 × 8"
    else:
        case["preconditions"].append("Bayinin kredi limiti dolu")
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=True)
    with pytest.raises(ReplayMiss):
        _run_verify(gw, rules_dir, case, 2)
    golden = load_golden("verify_and_map", "TPD-1-C2")
    assert input_mismatches(golden["input_match"], _verify_messages(case, 2)) == [
        "onaylı case metni golden'ın beyan ettiğinden farklı"
    ]


def test_case_declaration_ignores_symbol_table_and_feedback_blocks() -> None:
    """Eşleşme yalnızca case bloğuna bakar: sembol tablosu/geri bildirimdeki metin karışmaz,
    case metni oralarda geçse bile case bloğu farklıysa REPLAY-MISS kalır."""
    case = load_golden("case_generation", "TPD-1")["output"]["cases"][1]
    golden = load_golden("verify_and_map", "TPD-1-C2")
    feedback = "locator hatası: " + approved_case_text(case)
    assert (
        input_mismatches(golden["input_match"], _verify_messages(case, 2, feedback=feedback)) == []
    )
    edited = {**case, "title": case["title"] + " (düzenlendi)"}
    assert input_mismatches(golden["input_match"], _verify_messages(edited, 2, feedback=feedback))


@pytest.mark.parametrize(
    "shas",
    [
        ("a1b2c3d4e5f60718293a4b5c6d7e8f9012345678", "9f8e7d6c5b4a30291817161514131211100f0e0d"),
        # Tamamı rakam 12'lik önek (~%0.35 commit): kısa sha kuralı harf ister; sembol bloğu
        # kaynağı yine normalize edilmeli.
        ("123456789012ab34cd56ef7890abcdef12345678", "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"),
        ("abcdefabcdef1234567890abcdef1234567890ab", "123456789012ab34cd56ef7890abcdef12345678"),
    ],
)
def test_main_sha_and_checkout_root_do_not_change_the_replay_key(rules_dir, shas) -> None:
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=True)
    case = SCENARIO_CASES[0]
    schema = load_schema(rules_dir, "verify_and_map")
    keys = set()
    for sha, root in zip(shas, ("/tmp/a", "/var/folders/xyz/checkout-91/e2e"), strict=True):
        symbols = {**SYMBOLS, "sha": sha, "root": root}
        messages = _verify_messages(case, 1, symbols=symbols)
        assert f'source="symbols:{sha[:12]}"' in messages[0].content
        keys.add(
            gw.replay_key_for_agent(
                "verify_and_map",
                "verify-and-map",
                messages,
                VERIFY_TOOLS,
                schema,
                replay_key={"name": "TPD-1-C1", "jira_key": "TPD-1"},
            ).key
        )
    assert len(keys) == 1


def test_symbol_table_content_still_changes_the_replay_key(rules_dir) -> None:
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=True)
    case = SCENARIO_CASES[0]
    schema = load_schema(rules_dir, "verify_and_map")
    other = json.loads(json.dumps(SYMBOLS))
    other["page_objects"][0]["methods"][0]["name"] = "expectGrandTotal"
    keys = {
        gw.replay_key_for_agent(
            "verify_and_map",
            "verify-and-map",
            _verify_messages(case, 1, symbols=symbols),
            VERIFY_TOOLS,
            schema,
            replay_key={"name": "TPD-1-C1", "jira_key": "TPD-1"},
        ).key
        for symbols in (SYMBOLS, other)
    }
    assert len(keys) == 2


def test_agent_dealer_constant_matches_seed_and_e2e_fixtures() -> None:
    seed = (DEMO_APP / "api" / "src" / "demoapp_api" / "seed.py").read_text(encoding="utf-8")
    assert f'"kullanici_adi": "{VERIFY_AGENT_DEALER}"' in seed
    fixtures = (DEMO_APP / "e2e" / "tests" / "fixtures.ts").read_text(encoding="utf-8")
    assert f'AGENT_DEALER = "{VERIFY_AGENT_DEALER}"' in fixtures
    assert VERIFY_AGENT_DEALER not in E2E_DEALERS


# ------------------------------------------------------------------ senaryo araması (birim)


def _store(
    tmp_path: Path, files: dict[str, dict[str, Any]], *, strict: bool = False
) -> ReplayStore:
    for rel, data in files.items():
        p = tmp_path / "verify_and_map" / "golden" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ReplayStore(tmp_path, strict=strict)


def _g(name: str, needle: str | None, out: str) -> dict[str, Any]:
    g: dict[str, Any] = {"kind": "agent", "golden": name, "output": {"o": out}}
    if needle is not None:
        g["input_match"] = {"contains": [needle]}
    return g


MSG = [{"role": "user", "content": "case: 6 adet bedava yok"}]


def test_scenario_golden_is_used_only_when_its_declaration_matches(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        {
            "X-C3.json": _g("X-C3", "1 adet bedava", "ana"),
            "b-senaryo/X-C3.json": _g("b-senaryo/X-C3", "bedava yok", "senaryo"),
            "a-beyansiz/X-C3.json": _g("a-beyansiz/X-C3", None, "beyansiz"),
        },
    )
    record, mode, path = store.lookup("verify_and_map", "k", "X-C3", MSG)
    assert (mode, record["output"], record["golden"]) == (
        "replay",
        {"o": "senaryo"},
        "b-senaryo/X-C3",
    )
    assert record["provenance"] == MATCHED and path.parent.name == "b-senaryo"
    # Uymayan girdi: senaryo golden'ı asla dönmez; ana golden'ın iskalaması (beyanlı, yedeksiz).
    record, mode, _ = store.lookup(
        "verify_and_map", "k", "X-C3", [{"role": "user", "content": "?"}]
    )
    assert mode == "replay_miss" and record["output"] == {"o": "ana"}
    strict = ReplayStore(tmp_path, strict=True)
    with pytest.raises(ReplayMiss):
        strict.lookup("verify_and_map", "k", "X-C3", [{"role": "user", "content": "?"}])


def test_scenario_round_goldens_are_found_from_the_first_round_name(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        {
            "S.json": _g("S", "özgün", "1. tur"),
            "S-r2.json": _g("S-r2", "düzeltilmiş", "2. tur"),
            "sen/S-r2.json": _g("sen/S-r2", "bedava yok", "senaryo 2. tur"),
        },
    )
    record, mode, _ = store.lookup("verify_and_map", "k", "S", MSG)
    assert (mode, record["golden"]) == ("replay", "sen/S-r2")
    record, mode, _ = store.lookup("verify_and_map", "k", "S-r2", MSG)
    assert (mode, record["golden"]) == ("replay", "sen/S-r2")
    # Senaryo adıyla doğrudan istenirse yalnızca o dosya; senaryolar iç içe geçmez.
    assert store._scenario_candidates("verify_and_map", "sen/S-r2") == []


def test_scenario_golden_names_are_validated(tmp_path: Path) -> None:
    from tp_core.gateway import GatewayConfigError

    store = ReplayStore(tmp_path)
    assert store.golden_path("p", "sen/TPD-1-C3").name == "TPD-1-C3.json"
    for bad in ("../x", "a/b/c", "sen/../x", "/abs", "sen/"):
        with pytest.raises(GatewayConfigError):
            store.golden_path("p", bad)


def test_promotion_index_names_scenario_goldens_by_relative_path(rules_dir) -> None:
    store = ReplayStore(rules_dir / "replay")
    names = {n for entries in _golden_index(store, "verify_and_map").values() for n, _ in entries}
    assert f"{SCENARIO}/TPD-1-C3" in names and "TPD-1-C3" in names
    stale_check = {
        "provenance": "golden_promoted",
        "golden": f"{SCENARIO}/TPD-1-C3",
        "golden_sha256": "0" * 64,
    }
    assert store.is_stale("verify_and_map", stale_check)  # özet farklı → bayat (ad çözülür)


def test_models_table_still_lists_verify_and_map(rules_dir) -> None:
    assert "verify_and_map" in load_model_table(rules_dir).purposes
    assert Path(REPO / "rules" / "prompts" / "verify-and-map.md").is_file()


def test_unevaluated_prompt_bundle_is_marked_pending_live_evaluation() -> None:
    """Constitution X: canlı modelle değerlendirilmemiş prompt paketi (golden'ları elle; kayıt
    üst verisi `recording` yok) rules/README.md'de 'canlı değerlendirme bekliyor' işaretlidir."""
    readme = (RULES / "README.md").read_text(encoding="utf-8")
    prompt = (RULES / "prompts" / "verify-and-map.md").read_text(encoding="utf-8")
    version = re.search(r"^version:\s*(\d+)", prompt, re.MULTILINE)
    assert version
    live = [g for _, _, g in VERIFY if g.get("recording")]
    row = re.search(r"^\| `verify-and-map`.*\| v(\d+) \| (.+) \|$", readme, re.MULTILINE)
    assert row, "rules/README.md canlı değerlendirme tablosunda verify-and-map satırı yok"
    assert row.group(1) == version.group(1)
    if not live:
        assert "canlı değerlendirme bekliyor" in row.group(2)
