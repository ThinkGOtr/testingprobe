"""rules/replay golden kayıtlarının bağlayıcı kaynaklarla tutarlılığı (golden-drift CI job'u).

Saf veri: tp_core / anthropic / mcp içe aktarılmaz (anayasa II).

- Her amaç için en az bir golden var (anahtarsız demo uçtan uca koşar, MIMARI-SOZLESME §1).
- Her golden kendi şemasına uyar.
- Kod/veri kanıtları demo-app kaynağıyla birebir eşleşir (§8.2b adım 4'ün deterministik doğrulaması
  replay demosunda da geçsin; demo-app/** değişikliği satırları kaydırırsa burada kırmızı olur).
- verify_and_map golden'ları gerçek page object sembollerine, §8.4 araç izin listesine ve case'in
  beklenen metnine bağlıdır.
- TPD-1 case golden'ının beklenen değerleri demo-app fiyat fonksiyonlarıyla aynıdır.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from drift_sources import (
    DEMO_APP,
    RULES,
    arg_matches,
    cart,
    demo_module,
    golden_name,
    goldens,
    load_golden,
    load_schema,
    model_purposes,
    normalize_value,
    normalized_text_values,
    page_object_methods,
    seed_setting,
)

ALL_GOLDENS = list(goldens())
VERIFY_ALLOWLIST = {
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_select_option",
    "browser_wait_for",
    "browser_generate_locator",
}
DEMO_ORIGIN = "http://demo-app-web:8080"


def _ids(items: list[tuple[str, Path, Any]]) -> list[str]:
    return [f"{p}/{path.stem}" for p, path, _ in items]


def test_every_model_purpose_has_a_golden() -> None:
    purposes = model_purposes()
    # Yalnız senaryo golden'ı olan amaç da sayılır (case_deepening: `negatif/`, `teknik-*/`;
    # tür/teknik golden adındadır, ana golden'ı tasarım gereği yoktur — core testiyle aynı kural).
    senaryo = {p.parent.parent.parent.name for p in (RULES / "replay").glob("*/golden/*/*.json")}
    have = {p for p, _, _ in ALL_GOLDENS} | senaryo
    assert purposes <= have, f"golden'ı olmayan amaç(lar): {sorted(purposes - have)}"


@pytest.mark.parametrize(("purpose", "path", "golden"), ALL_GOLDENS, ids=_ids(ALL_GOLDENS))
def test_golden_matches_schema_and_name(purpose: str, path: Path, golden: dict) -> None:
    assert golden["purpose"] == purpose
    assert golden["golden"] == path.stem
    assert golden["kind"] in ("call", "agent")
    errors = sorted(
        Draft202012Validator(load_schema(purpose)).iter_errors(golden["output"]),
        key=str,
    )
    assert not errors, [e.message for e in errors]
    for step in golden.get("steps", []):
        # `hedef` (isteğe bağlı): ref alan adımın yapılandırılmış hedefi; REPLAY ref'i canlı
        # snapshot'tan bununla çözer (tp_core.gateway.snapshot_refs.Hedef).
        assert (
            {"tool", "args", "result_summary", "allowed"}
            <= set(step)
            <= {"tool", "args", "result_summary", "allowed", "hedef"}
        )
        if "hedef" in step:
            h = step["hedef"]
            assert isinstance(h, dict) and isinstance(h.get("rol"), str) and h["rol"], step
            assert set(h) <= {"rol", "ad", "kapsam"}, h


# ------------------------------------------------------------------ kanıt sürüklenmesi


def _evidence() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for purpose, path, golden in ALL_GOLDENS:
        for finding in (
            golden["output"].get("findings", []) if purpose == "consistency_check" else []
        ):
            for ev in finding["evidence"]:
                out.append((f"{path.stem}:{finding['id']}:{ev['kind']}", ev))
    return out


EVIDENCE = _evidence()


def test_consistency_goldens_have_evidence() -> None:
    kinds = {ev["kind"] for _, ev in EVIDENCE}
    assert kinds == {"code", "data"}


@pytest.mark.parametrize(("label", "ev"), EVIDENCE, ids=[label for label, _ in EVIDENCE])
def test_golden_evidence_matches_demo_app_source(label: str, ev: dict[str, Any]) -> None:
    if ev["kind"] == "code":
        assert ev["repo"] == "demo-app"
        lines = (DEMO_APP / ev["path"]).read_text(encoding="utf-8").splitlines()
        assert ev["line"] <= len(lines), f"{ev['path']} {len(lines)} satır"
        actual = lines[ev["line"] - 1]
        assert ev["snippet"] in actual, (
            f"{ev['path']}:{ev['line']} kaydı: {ev['snippet']!r}, kaynakta: {actual.strip()!r}"
        )
    else:
        m = re.fullmatch(r"(\w+)=(.+)", ev["result_digest"])
        assert m, ev["result_digest"]
        assert f"'{m.group(1)}'" in ev["query"]
        assert seed_setting(m.group(1)) == m.group(2)


def test_drift_check_catches_a_shifted_line(tmp_path: Path) -> None:
    """Kontrolün kendisi: satır kayarsa eşleşme bozulur (yanlış pozitif vermez)."""
    ev = next(ev for _, ev in EVIDENCE if ev["kind"] == "code")
    lines = (DEMO_APP / ev["path"]).read_text(encoding="utf-8").splitlines()
    shifted = ["# yeni satır", *lines]
    assert ev["snippet"] in lines[ev["line"] - 1]
    assert ev["snippet"] not in shifted[ev["line"] - 1]


# ------------------------------------------------------------------ verify_and_map


VERIFY = list(goldens("verify_and_map"))
METHODS = page_object_methods()


def _case(jira_key: str, sira_no: int) -> dict[str, Any]:
    return load_golden("case_generation", jira_key)["output"]["cases"][sira_no - 1]


# Doğrulama ajanı kaydı olan case'ler: TPD-1 C1–C10 ve TPD-4 C1–C2. TPD-1 C11–C15 (011 K17 sınır
# case'leri) sona eklendi; tarayıcı kaydı yok, kod üretimi onlarda dürüst REPLAY-MISS olur
# (demo/prova kod üretimi C1, C2, C3, C5 ile çalışır).
VERIFY_KAYITLI = {"TPD-1": 10, "TPD-4": 2}


def test_every_golden_case_has_a_verify_and_map_golden() -> None:
    names = {path.stem for _, path, _ in VERIFY}
    for jira, kayitli in VERIFY_KAYITLI.items():
        cases = load_golden("case_generation", jira)["output"]["cases"]
        assert len(cases) >= kayitli
        expected = {golden_name(jira, case_no=n) for n in range(1, kayitli + 1)}
        assert expected <= names, sorted(expected - names)


def test_page_object_parser_sees_real_symbols() -> None:
    assert METHODS[("CatalogPage", "addToCart")].param_types == ("string", "number")
    assert METHODS[("CartPage", "expectTotal")].param_types == ("string",)
    assert METHODS[("LoginPage", "login")].param_types == ("string", "string")


@pytest.mark.parametrize(("purpose", "path", "golden"), VERIFY, ids=_ids(VERIFY))
def test_verify_and_map_golden_is_grounded(purpose: str, path: Path, golden: dict) -> None:
    jira, sira = golden["case"]["jira_key"], golden["case"]["sira_no"]
    assert path.stem == golden_name(jira, case_no=sira)
    case = _case(jira, sira)
    assert golden["case"]["title"] == case["title"]
    out = golden["output"]

    # Recorded browser steps: only the §8.4 allowlist, only the demo origin, no screenshots.
    assert golden["steps"], "kayıtlı tarayıcı adımı yok"
    assert len(golden["steps"]) <= 25
    for step in golden["steps"]:
        assert step["tool"] in VERIFY_ALLOWLIST, step["tool"]
        assert step["allowed"] is True
        if step["tool"] == "browser_navigate":
            assert step["args"]["url"].startswith(DEMO_ORIGIN + "/")

    # Every case step is mapped or reported missing; ids exist.
    step_ids = {s["id"] for s in case["steps"]}
    mapped = {m["step_id"] for m in out["step_mapping"]}
    missing = {m["step_id"] for m in out["missing_methods"]}
    assert mapped | missing == step_ids
    assert (mapped | missing) <= step_ids

    # Methods exist with matching arity/types; actions in step_mapping, assertions in expects.
    for m in out["step_mapping"]:
        meth = METHODS.get((m["po"], m["method"]))
        assert meth is not None, f"{m['po']}.{m['method']} sembol tablosunda yok"
        assert not meth.is_expect, f"{m['method']} bir eylem değil"
        assert len(m["args"]) == len(meth.param_types), m
        assert all(arg_matches(a, t) for a, t in zip(m["args"], meth.param_types, strict=True))
        if not m["verified"]:
            assert m["evidence_ref"] is None
            assert m["step_id"] in missing
    expected_text = " ".join([*(s["expected"] for s in case["steps"]), case["expected_result"]])
    values = normalized_text_values(expected_text)
    for e in out["expects"]:
        meth = METHODS.get((e["po"], e["method"]))
        assert meth is not None, f"{e['po']}.{e['method']} sembol tablosunda yok"
        assert meth.is_expect
        assert len(e["args"]) == len(meth.param_types), e
        assert all(arg_matches(a, t) for a, t in zip(e["args"], meth.param_types, strict=True))
        # §8.4: assertion values must come from the approved case's expected text.
        for arg in e["args"]:
            is_money = isinstance(arg, str) and re.fullmatch(r"-?[\d.]+,\d{2}\s*TL", arg)
            if isinstance(arg, str) and not is_money:
                assert arg in expected_text, f"{arg!r} case beklenen metninde yok"
            else:
                assert normalize_value(arg) in values, f"{arg!r} case beklenen metninde yok"


def test_known_defect_case_stops_at_missing_method() -> None:
    """AC4 (kredi limiti) kodda yok: eşleme uydurulmaz, mühendise 'eksik metot' olarak düşer."""
    cases = load_golden("case_generation", "TPD-1")["output"]["cases"]
    for n, case in enumerate(cases[: VERIFY_KAYITLI["TPD-1"]], start=1):
        golden = load_golden("verify_and_map", golden_name("TPD-1", case_no=n))
        flagged = "expected-code-defect" in case["tags"]
        assert bool(golden["output"]["missing_methods"]) == flagged, case["title"]


def test_campaign_scripts_catch_break_campaign(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adım 6 (kırarak doğrula): BREAK_CAMPAIGN=1 ile en az bir kampanya beklentisi bozulmalı."""
    caught = []
    cases = load_golden("case_generation", "TPD-1")["output"]["cases"]
    for n, case in enumerate(cases[: VERIFY_KAYITLI["TPD-1"]], 1):
        golden = load_golden("verify_and_map", golden_name("TPD-1", case_no=n))
        adds = [m["args"] for m in golden["output"]["step_mapping"] if m["method"] == "addToCart"]
        frees = [e for e in golden["output"]["expects"] if e["method"] == "expectFreeQuantity"]
        if not frees:
            continue
        lines = [(code, qty) for code, qty in adds]
        monkeypatch.setenv("BREAK_CAMPAIGN", "1")
        broken = {s.urun_kod: s.bedava_adet for s in cart(lines).satirlar}
        monkeypatch.delenv("BREAK_CAMPAIGN")
        ok = {s.urun_kod: s.bedava_adet for s in cart(lines).satirlar}
        for e in frees:
            code, qty = e["args"]
            assert ok[code] == qty, case["title"]  # temiz uygulamada yeşil
            if broken[code] != qty:
                caught.append(case["title"])
    assert len(caught) >= 2, caught


# ------------------------------------------------------------------ case golden ↔ demo-app


TPD1_CASES = load_golden("case_generation", "TPD-1")["output"]["cases"]


def _case_cart(case: dict[str, Any]) -> list[tuple[str, int]]:
    lines = []
    for step in case["steps"]:
        m = re.fullmatch(r"(P-\d{3}) × (\d+)", step["data"] or "")
        if m:
            lines.append((m.group(1), int(m.group(2))))
    return lines


def _money(text: str, label: str) -> list[str]:
    guard = r"(?<!ara )" if label == "toplam" else ""
    pattern = rf"(?<![A-Za-zçğıöşü]){guard}{label} ([\d.]+,\d{{2}} TL)"
    return re.findall(pattern, text, re.IGNORECASE)


@pytest.mark.parametrize("case", TPD1_CASES, ids=[c["title"] for c in TPD1_CASES])
def test_tpd1_case_expectations_match_demo_app(case: dict[str, Any]) -> None:
    money = demo_module("money")
    lines = _case_cart(case)
    if not lines:
        pytest.skip("sepet içermeyen case")
    result = cart(lines)
    text = " ".join([*(s["expected"] for s in case["steps"]), case["expected_result"]])
    # sepet sayacı
    for m in re.finditer(r"Sepet sayacı (\d+) olur", text):
        assert int(m.group(1)) == result.adet_toplam
    # bedava adet / tutarlar
    for m in re.finditer(r"(P-\d{3}) satırında adet (\d+), bedava adet (\d+)", text):
        line = next(s for s in result.satirlar if s.urun_kod == m.group(1))
        assert (line.adet, line.bedava_adet) == (int(m.group(2)), int(m.group(3)))
    for label, value in (
        ("ara toplam", result.ara_toplam),
        ("indirim", result.indirim),
        ("toplam", result.toplam),
    ):
        for stated in _money(text, label):
            assert stated == money.format_tl(value), (label, stated)
    # minimum sipariş uyarısı ve onay butonu
    warns = [u.mesaj for u in result.uyarilar]
    if "expected-code-defect" in case["tags"]:
        # Bilinen kod hatası: uygulama kredi limiti uyarısı üretmiyor (bug açık). Hata düzelirse
        # bu test kırmızı olur ve golden güncellenmelidir.
        assert "Kredi limiti aşıldı" in text
        assert not any("Kredi" in w for w in warns)
        assert result.onaylanabilir is True
        return
    stated_warning = re.search(r"Minimum sipariş tutarı [\d.]+,\d{2} TL", text)
    negated = re.search(r"minimum sipariş uyarısı (görünmez|gösterilmez)", text, re.IGNORECASE)
    if stated_warning:
        assert warns == [stated_warning.group(0)]
    elif negated:
        assert warns == []
    if "pasif" in text:
        assert result.onaylanabilir is False
    if re.search(r"aktif|onaylanabilir", text.replace("pasif", "")):
        assert result.onaylanabilir is True


def test_tpd1_cases_follow_fixed_document() -> None:
    """Case'ler düzeltilmiş dokümandan üretilir: eski (500 TL / 7'de 1) beklentiler kalmamalı."""
    blob = " ".join(str(c) for c in TPD1_CASES)
    assert '500,00 TL" uyarısı' not in blob and "Minimum sipariş tutarı 500" not in blob
    assert "6 adette bedava ürün verilmez" not in blob
    min_tl = demo_module("money").format_tl(seed_setting("min_siparis_tutari"))
    assert f"Minimum sipariş tutarı {min_tl}" in blob
