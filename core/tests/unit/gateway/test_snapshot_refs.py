"""REPLAY'de snapshot ref'leri oturumdan bağımsız çözülür (gateway.snapshot_refs).

Playwright MCP ref'leri aynı yörüngede bile koşudan koşuya kayar (`browser_navigate`'in örtük
snapshot'ı bazen fazladan bir ref harcar: `button "Giriş yap" [ref=e20]` ↔ `[ref=e21]`). Golden
adımı elemanı rol/ad/kapsam ile taşır; replay ref'i CANLI son snapshot'tan çözer. Fikstür
(fixtures/playwright_mcp_outputs.json) Playwright MCP 1.64.1'in gerçek çıktısıdır.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tp_core.gateway import load_schema
from tp_core.gateway.core import REPLAY_DRIFT, REPLAY_UNRESOLVED
from tp_core.gateway.snapshot_refs import (
    Hedef,
    clean_line,
    is_inline_snapshot,
    locate_ref,
    ref_arg,
    snapshot_lines,
    strip_mcp_file_links,
)
from tp_core.ports import ModelMessage, ToolSpec

MCP = json.loads((Path(__file__).parent / "fixtures" / "playwright_mcp_outputs.json").read_text())
LOGIN = snapshot_lines(MCP["browser_snapshot_login"]) or []
CATALOG = snapshot_lines(MCP["browser_snapshot_catalog"]) or []


def _shift(text: str, by: int) -> str:
    """Aynı sayfanın ref'leri `by` kaymış hali (canlı yığında gözlenen +1 kayma)."""
    import re

    return re.sub(r"\[ref=e(\d+)\]", lambda m: f"[ref=e{int(m.group(1)) + by}]", text)


# ------------------------------------------------------------------ çözüm


def test_fixture_is_real_mcp_output() -> None:
    assert is_inline_snapshot(MCP["browser_snapshot_login"])
    assert not is_inline_snapshot(MCP["browser_navigate"])  # dosya bağlantısı ≠ snapshot
    assert not is_inline_snapshot(MCP["browser_click"])
    assert LOGIN and CATALOG


@pytest.mark.parametrize(
    ("lines", "hedef", "ref"),
    [
        (LOGIN, Hedef("button", "Giriş yap"), "e20"),
        (LOGIN, Hedef("textbox", "Kullanıcı adı"), "e16"),
        (LOGIN, Hedef("textbox", "Parola"), "e19"),
        # Bağlantı adı sayacı içerir ("Sepet 0 ürün"): ad önekiyle eşleşir.
        (CATALOG, Hedef("link", "Sepet"), "e33"),
        (CATALOG, Hedef("link", "Siparişlerim"), "e36"),
        # Aynı rol/ad her kartta tekrarlanır: kapsam kartı belirler (ilk kart P-001 değil).
        (CATALOG, Hedef("button", "Sepete ekle", "paragraph: P-002"), "e70"),
        (CATALOG, Hedef("spinbutton", "Adet", "paragraph: P-004"), "e95"),
        (CATALOG, Hedef("button", "Sepete ekle"), "e57"),
    ],
)
def test_locate_ref_by_role_name_and_scope(lines: list[str], hedef: Hedef, ref: str) -> None:
    assert locate_ref(lines, hedef) == ref


def test_scope_does_not_leak_into_the_next_card() -> None:
    # P-002 kartında "Kampanya" paragrafı yok; arama kart bitince durur (P-003'e taşmaz).
    lines = [x for x in CATALOG if 'button "Sepete ekle" [ref=e70]' not in x]
    assert locate_ref(lines, Hedef("button", "Sepete ekle", "paragraph: P-002")) is None
    assert locate_ref(CATALOG, Hedef("button", "Sepete ekle", "paragraph: P-999")) is None


def test_name_must_match_exactly_or_as_word_prefix() -> None:
    assert locate_ref(LOGIN, Hedef("button", "Giriş ya")) is None  # sözcük ortası öneki değil
    assert locate_ref(LOGIN, Hedef("button", "Giriş")) == "e20"  # sözcük öneki
    assert locate_ref(CATALOG, Hedef("link", "Sep")) is None
    lines = ["- alert [ref=e140]: Minimum sipariş tutarı 750,00 TL"]
    assert locate_ref(lines, Hedef("alert")) == "e140"  # adsız rol
    assert locate_ref(['- alert "x" [ref=e1]'], Hedef("alert")) is None


def test_shifted_page_resolves_to_the_shifted_ref() -> None:
    shifted = snapshot_lines(_shift(MCP["browser_snapshot_login"], 1)) or []
    assert locate_ref(shifted, Hedef("button", "Giriş yap")) == "e21"


def test_helpers() -> None:
    assert clean_line("    - paragraph [ref=e63]: P-002") == "paragraph: P-002"
    assert ref_arg({"element": "x", "target": "e21"}) == "target"
    assert ref_arg({"target": '[data-testid="x"]'}) is None
    assert ref_arg({"ref": "e3"}) == "ref"
    assert Hedef.from_raw({"rol": "button", "ad": "x"}) == Hedef("button", "x")
    assert Hedef.from_raw({"ad": "x"}) is None
    assert Hedef.from_raw(None) is None


def test_strip_mcp_file_links_keeps_content() -> None:
    out = strip_mcp_file_links(MCP["browser_navigate"])
    assert "page.goto(" in out and "Page URL:" in out
    assert "/tmp/playwright-mcp" not in out and "### Snapshot" not in out
    assert "### Events" not in out
    snap = MCP["browser_snapshot_login"]
    assert strip_mcp_file_links(snap) == snap  # satır içi snapshot'a dokunulmaz


# ------------------------------------------------------------------ REPLAY yürütmesi


TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in ("browser_navigate", "browser_snapshot", "browser_generate_locator", "browser_click")
]
OUTPUT = {
    "step_mapping": [
        {
            "step_id": "S1",
            "po": "LoginPage",
            "method": "login",
            "args": ["bayi1", "Demo123!"],
            "verified": True,
            "evidence_ref": "x",
        }
    ],
    "expects": [],
    "missing_methods": [],
}


def _golden(rules_dir: Path, steps: list[dict[str, Any]]) -> None:
    golden_dir = rules_dir / "replay" / "verify_and_map" / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    (golden_dir / "TPD-4-case-1.json").write_text(
        json.dumps({"kind": "agent", "output": OUTPUT, "steps": steps}), encoding="utf-8"
    )


RECORDED = [
    {
        "tool": "browser_navigate",
        "args": {"url": "http://demo-app-web:8080/giris"},
        "result_summary": "· URL /giris",
        "allowed": True,
    },
    {"tool": "browser_snapshot", "args": {}, "result_summary": "URL /giris", "allowed": True},
    {
        "tool": "browser_generate_locator",
        "args": {"element": 'button "Giriş yap" (login.submit)', "target": "e21"},
        "hedef": {"rol": "button", "ad": "Giriş yap"},
        "result_summary": "getByTestId('login-submit')",
        "allowed": True,
    },
]


class LivePage:
    """Canlı MCP gibi: snapshot ref'leri `shift` kadar kaymış; generate_locator ref'i sayfada
    arar (yoksa MCP'nin gerçek hatası)."""

    def __init__(self, shift: int) -> None:
        self.shift = shift
        self.calls: list[tuple[str, dict]] = []
        self.snapshot = _shift(MCP["browser_snapshot_login"], shift)

    def __call__(self, name: str, args: dict) -> str:
        self.calls.append((name, dict(args)))
        if name == "browser_navigate":
            return MCP["browser_navigate"]
        if name == "browser_snapshot":
            return self.snapshot
        ref = args["target"]
        if f"[ref={ref}]" not in self.snapshot:
            raise RuntimeError(MCP["browser_generate_locator_missing_ref"].replace("e9999", ref))
        line = next(x for x in self.snapshot.splitlines() if f"[ref={ref}]" in x)
        tid = {"button": "login-submit", "textbox": "login-username"}[line.split()[1]]
        return f"### Result\ngetByTestId('{tid}')"


def _run(gw, rules_dir: Path, browser) -> Any:
    return gw.run_agent(
        "verify_and_map",
        "verify-and-map",
        [ModelMessage(role="user", content="case")],
        TOOLS,
        browser,
        load_schema(rules_dir, "verify_and_map"),
        replay_key={"name": "TPD-4-case-1", "jira_key": "TPD-4"},
    )


@pytest.mark.parametrize("shift", [-1, 0, 1, 2])
def test_replay_resolves_recorded_ref_against_the_live_snapshot(
    make_gateway, rules_dir, recorder, shift: int
) -> None:
    """Kayıt e21'de; canlı sayfa hangi kaymayla gelirse gelsin doğru eleman doğrulanır."""
    _golden(rules_dir, RECORDED)
    browser = LivePage(shift)
    gw, _ = make_gateway(mode="replay")
    result = _run(gw, rules_dir, browser)
    live_ref = f"e{20 + shift}"
    assert browser.calls[-1] == (
        "browser_generate_locator",
        {"element": 'button "Giriş yap" (login.submit)', "target": live_ref},
    )
    step = result.steps[-1]
    assert step.args["target"] == live_ref  # adım/denetim gerçekten gönderilen ref'i taşır
    assert "getByTestId('login-submit')" in step.result_summary
    assert REPLAY_DRIFT not in step.result_summary
    assert recorder.tool_calls[-1]["arguman_ozeti"]["target"] == live_ref
    # Eylem sonucu MCP dosya bağlantılarını taşımaz.
    assert "/tmp/playwright-mcp" not in result.steps[0].result_summary


def test_replay_does_not_send_an_unresolvable_ref(make_gateway, rules_dir) -> None:
    steps = [dict(s) for s in RECORDED]
    steps[2] = {**steps[2], "hedef": {"rol": "button", "ad": "Çıkış yap"}}
    _golden(rules_dir, steps)
    browser = LivePage(1)
    gw, _ = make_gateway(mode="replay")
    result = _run(gw, rules_dir, browser)
    assert [c[0] for c in browser.calls] == ["browser_navigate", "browser_snapshot"]
    # Hata olarak akar (kod üretimi "Araç hatası" önekini başarısız adım sayar → insana).
    assert result.steps[-1].result_summary.startswith(REPLAY_UNRESOLVED)
    assert result.steps[-1].allowed is True


def test_replay_without_a_prior_live_snapshot_is_unresolved(make_gateway, rules_dir) -> None:
    _golden(rules_dir, [RECORDED[0], RECORDED[2]])
    browser = LivePage(0)
    gw, _ = make_gateway(mode="replay")
    result = _run(gw, rules_dir, browser)
    assert [c[0] for c in browser.calls] == ["browser_navigate"]
    assert result.steps[-1].result_summary.startswith(REPLAY_UNRESOLVED)


def test_legacy_step_without_target_spec_sends_the_recorded_ref(make_gateway, rules_dir) -> None:
    steps = [dict(s) for s in RECORDED]
    steps[2] = {k: v for k, v in steps[2].items() if k != "hedef"}
    _golden(rules_dir, steps)
    browser = LivePage(1)  # e21 = kaymış sayfada da "Giriş yap"
    gw, _ = make_gateway(mode="replay")
    _run(gw, rules_dir, browser)
    assert browser.calls[-1][1]["target"] == "e21"


def test_replay_flags_a_locator_that_differs_from_the_recording(make_gateway, rules_dir) -> None:
    """Hedefsiz eski kayıt + kaymış sayfa: e21 başka elemana denk gelirse sapma işaretlenir."""
    steps = [dict(s) for s in RECORDED]
    steps[2] = {k: v for k, v in steps[2].items() if k != "hedef"}
    steps[2]["args"] = {**steps[2]["args"], "target": "e16"}
    _golden(rules_dir, steps)
    browser = LivePage(0)  # canlı sayfada e16 = textbox "Kullanıcı adı"
    gw, _ = make_gateway(mode="replay")
    result = _run(gw, rules_dir, browser)
    summary = result.steps[-1].result_summary
    assert summary.startswith(REPLAY_DRIFT)
    assert "getByTestId('login-submit')" in summary and "getByTestId('login-username')" in summary
