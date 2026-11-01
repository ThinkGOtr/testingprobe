"""Faz 4 demo hikâyesinin model girdileri (triage / bug_draft / dup_rank golden'larının girdisi).

Bu modül şeritlerin (triage, bugs) üreteceği girdinin örneğidir ve golden `input_match`
beyanlarının sınandığı TEK yerdir: hata kayıtları toolchain `/check` / test-runner `failures`
biçimindedir (toolchain/README.md "Failure inputs"), bulgular consistency_check golden'larından,
case'ler case_generation golden'ından, test verisi demo-app seed'inden, mükerrer adayları jira-sim
seed'inden okunur. Kaynaklar değişirse golden testleri kırmızı olur.

Oynak alanlar (koşu kimliği, artefakt yolu, uuid8 dosya soneki, süre) bilerek konmuştur; kanonik
kurucular bunları anahtardan ve beyandan uzak tutmalıdır (`test_defect_inputs.py`).
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Sequence
from typing import Any

from tests.unit.gateway.demo_sources import REPO, demo_query, load_golden
from tp_core.features.cases.testdata import build_text
from tp_core.gateway import (
    bug_draft_messages,
    case_block,
    dup_rank_messages,
    failure_block,
    finding_block,
    triage_messages,
)
from tp_core.ports import JiraIssue, ModelMessage

C3_TITLE = "6 adet kampanyalı üründe bedava ürün verilmez"
C2_TITLE = "7 adet kampanyalı üründe 1 adet bedava verilir"
DUP_JQL = 'project = TPD AND issuetype = Bug AND statusCategory != Done AND text ~ "kampanya"'


def _evidence(run_id: str, test_dir: str, *, video: bool = False) -> dict[str, Any]:
    base = f"/artifacts/runs/{run_id}/src/e2e/results/artifacts/{test_dir}"
    item = {
        "trace": f"{base}/trace.zip",
        "error_context": f"{base}/error-context.md",
        "screenshot": f"{base}/test-failed-1.png",
    }
    out: dict[str, Any] = {
        k: {"path": p, "rel": p.removeprefix("/artifacts/"), "exists": True}
        for k, p in item.items()
    }
    out["video"] = {"path": f"{base}/video.webm", "rel": "x", "exists": True} if video else None
    return out


CART_ARIA = """- navigation:
  - link "Katalog"
  - link "Sepetim"
- heading "Sepet" [level=1]
- table:
  - row "Portakal Gazozu 1L":
    - cell "Portakal Gazozu 1L"
    - cell "{qty}"
    - cell "{free}"
- button "Siparişi onayla\""""


def free_quantity_failure(
    *, expected: int, received: int, qty: int, test_file: str, line: int, run_id: str | None = None
) -> dict[str, Any]:
    """`CartPage.expectFreeQuantity("P-001", n)` assertion hatası (toolchain `failure`)."""
    run = run_id or str(uuid.uuid4())
    return {
        "type": "assertion",
        "first_line": "Error: expect(locator).toHaveText(expected) failed",
        "matcher": "toHaveText",
        "action": None,
        "locator": "getByTestId('cart-line-free-P-001')",
        "expected": f'"{expected}"',
        "received": f'"{received}"',
        "timeout_ms": 5000,
        "signals": ["beklenen ≠ gerçekleşen"],
        "message": (
            "Error: expect(locator).toHaveText(expected) failed\n\n"
            "Locator:  getByTestId('cart-line-free-P-001')\n"
            f'Expected: "{expected}"\nReceived: "{received}"\nTimeout:  5000ms\n\n'
            'Call log:\n  - Expect "toHaveText" with timeout 5000ms\n'
            f"  - {9 if received else 8} × locator resolved to <span>{received}</span>"
        ),
        "messages": [],
        "location": {"file": "pages/cart/cart.page.ts", "line": 39, "column": 89},
        "test_location": {"file": test_file, "line": line, "column": 20},
        "step": None,
        "attempt": 0,
        "status": "failed",
        "evidence": _evidence(run, f"tests-{run[:8]}-chromium"),
        "aria_snapshot": CART_ARIA.format(qty=qty, free=received),
        "aria_snapshot_scope": "error_details",
    }


HEALTHY = {
    "ok": True,
    "zaman": "2026-10-31T10:00:00Z",
    "web": {"url": "http://demo-app-web:8080/", "status": 200, "ms": 12, "hata": None},
    "api": {"url": "http://demo-app-api:8000/health", "status": 200, "ms": 4, "hata": None},
    "hata": None,
}


# ------------------------------------------------------------------ hata girdileri


def c3_failure(run_id: str | None = None, suffix: str = "1a2b3c4d") -> dict[str, Any]:
    """Ana yol: C3 (f2-kod-hatasi) yerel kontrolü — kod `adet // 6` → 6 adette 1 bedava."""
    return free_quantity_failure(
        expected=0,
        received=1,
        qty=6,
        test_file=f"tests/generated/tpd-1-c3-{suffix}.spec.ts",
        line=22,
        run_id=run_id,
    )


def c3_case() -> dict[str, Any]:
    cases = load_golden("case_generation", "f2-kod-hatasi/TPD-1")["output"]["cases"]
    return next(c for c in cases if c["title"] == C3_TITLE)


def c3_failure_kwargs(run_id: str | None = None, suffix: str = "1a2b3c4d") -> dict[str, Any]:
    return {
        "test_title": f"TPD-1 · C3 › {C3_TITLE} @tp-uretilen",
        "test_file": f"tests/generated/tpd-1-c3-{suffix}.spec.ts",
        "story_key": "TPD-1",
        "case_ref": "TPD-1-C3",
        "saglik": {**HEALTHY, "zaman": f"2026-10-31T1{len(suffix) % 10}:00:00Z"},
        "statuses": {"unexpected": 3},
        "consistent": True,
        "break_campaign": False,
    }


# Kırarak doğrulama / kırık CI koşusu: üç kampanya testi aynı assertion'da kırmızı.
BREAK_TESTS: list[tuple[str, str, int]] = [
    (
        "Sepet (TPD-1) › kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL",
        "tests/cart.spec.ts",
        28,
    ),
    (
        "Page object'ler › 7 adet Portakal Gazozu sepette 1 bedava adet ve sayaç 7 gösterir",
        "tests/page-objects.spec.ts",
        63,
    ),
    (f"TPD-1 · C2 › {C2_TITLE} @tp-uretilen", "tests/generated/tpd-1-c2-9f8e7d6c.spec.ts", 22),
]


def break_failure(test_file: str, line: int, run_id: str | None = None) -> dict[str, Any]:
    return free_quantity_failure(
        expected=1, received=0, qty=7, test_file=test_file, line=line, run_id=run_id
    )


def break_failure_kwargs(title: str, test_file: str) -> dict[str, Any]:
    generated = test_file.startswith("tests/generated/")
    return {
        "test_title": title,
        "test_file": test_file,
        "story_key": "TPD-1",
        "case_ref": "TPD-1-C2" if generated else None,
        "saglik": HEALTHY,
        "statuses": {"unexpected": 2},
        "consistent": True,
        "break_campaign": True,
    }


def timeout_failure(run_id: str | None = None) -> dict[str, Any]:
    """Kuralların eşleşmediği hata (LLM triage yedeği): sipariş testinde test zaman aşımı."""
    run = run_id or str(uuid.uuid4())
    return {
        "type": "test_timeout",
        "first_line": "Test timeout of 30000ms exceeded.",
        "matcher": None,
        "action": None,
        "locator": None,
        "expected": None,
        "received": None,
        "timeout_ms": 30000,
        "signals": ["test zaman aşımı"],
        "message": "Test timeout of 30000ms exceeded.",
        "messages": [],
        "location": {"file": "tests/order.spec.ts", "line": 10, "column": 3},
        "test_location": {"file": "tests/order.spec.ts", "line": 10, "column": 3},
        "step": None,
        "attempt": 1,
        "status": "timedOut",
        "evidence": _evidence(run, f"order-{run[:8]}-chromium"),
        "aria_snapshot": """- navigation:
  - link "Katalog"
  - link "Sepetim"
- heading "Sepet" [level=1]
- table:
  - row "Limonata 330ml":
    - cell "Limonata 330ml"
    - cell "50"
- button "Siparişi onayla\"""",
        "aria_snapshot_scope": "page",
    }


TIMEOUT_TITLE = (
    "Sipariş geçmişi (TPD-1) › onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir"
)


def timeout_rule_signals() -> list[str]:
    """Üretimdeki LLM yedeği girdisinin `Kural sinyalleri` satırları: triage şeridinin kendi
    `kural_sinyalleri` fonksiyonu (iki denemesi de zaman aşımı, sağlık başarılı, ek sinyal yok).
    Golden testi böylece üretimin birebir metnini sınar (elle yazılmış benzer metni değil)."""
    from tp_core.features.triage.rules import Girdi
    from tp_core.features.triage.service import kural_sinyalleri

    failure = timeout_failure()
    girdi = Girdi(
        test_adi=TIMEOUT_TITLE,
        dosya="tests/order.spec.ts",
        satir=10,
        sonuc="timedout",
        hata_turu=failure["type"],
        mesaj=failure["message"],
        saglik=HEALTHY,
        deneme_durumlari=["timedOut", "timedOut"],
    )
    return kural_sinyalleri(girdi, [], None)


def timeout_kwargs() -> dict[str, Any]:
    return {
        "test_title": TIMEOUT_TITLE,
        "test_file": "tests/order.spec.ts",
        "story_key": "TPD-1",
        "saglik": HEALTHY,
        "statuses": {"timedOut": 2},
        "consistent": True,
        "rule_signals": timeout_rule_signals(),
        "include_aria": True,
    }


# ------------------------------------------------------------------ bulgular (Demo-A)


def _finding(golden: str, fid: str) -> dict[str, Any]:
    out = load_golden("consistency_check", golden)["output"]["findings"]
    return next(f for f in out if f["id"] == fid)


def finding_kwargs(golden: str, fid: str) -> dict[str, Any]:
    """Bulgu → `finding_block` argümanları (doküman metni jira-sim seed'indeki özgün AC)."""
    f = _finding(golden, fid)
    ref = f["doc_ref"]
    return {
        "story_key": "TPD-1",
        "finding_type": f["type"],
        "doc_ref": ref,
        "doc_text": story_ac(ref),
        "claim": f["claim"],
        "observed": f["observed"],
        "evidence": f["evidence"],
    }


def story_ac(ref: str) -> str:
    sim_src = str(REPO / "sims" / "jira-sim" / "src")
    if sim_src not in sys.path:
        sys.path.insert(0, sim_src)
    from jira_sim.seed import TPD1_ACS

    return next(a for a in TPD1_ACS if a.startswith(f"{ref}:"))


# F2 kampanya ve F4 kredi limiti: 1. tur (TPD-1) ve senaryonun 2. turu (f2-kod-hatasi/TPD-1-r2)
# aynı farkı farklı gözlem metniyle raporlar; ikisi de aynı golden'a düşmelidir.
F2_FINDINGS = [("TPD-1", "F2"), ("f2-kod-hatasi/TPD-1-r2", "F1")]
F4_FINDINGS = [("TPD-1", "F4"), ("f2-kod-hatasi/TPD-1-r2", "F2")]


def testdata_block() -> str:
    from tp_core.gateway import wrap_untrusted

    return wrap_untrusted(build_text(demo_query), source="testdata:demo-app", kind="data")


# ------------------------------------------------------------------ jira-sim adayları


def seed_bug(key: str) -> JiraIssue:
    """jira-sim seed'indeki Bug, `RestJira.search` sonucuyla aynı biçimde (ADF → düz metin)."""
    sim_src = str(REPO / "sims" / "jira-sim" / "src")
    if sim_src not in sys.path:
        sys.path.insert(0, sim_src)
    from jira_sim.seed import initial_state

    from tp_core.integrations.jira import issue_from_json

    raw = initial_state()["issues"][key]
    return issue_from_json(
        {
            "key": key,
            "fields": {
                "issuetype": {"name": raw["issuetype"]},
                "summary": raw["summary"],
                "description": raw["description"],
                "status": {"name": raw["status"]},
                "updated": raw["updated"],
            },
        }
    )


# Demo sırasında "Yeni kayıt" ile açılabilen Bug'lar: özet golden taslağının özetidir
# (publish_bug özeti aynen yazar, açıklama boş). Anahtarlar seed'den sonraki sıradandır; F4 canlı
# yığında TPD-8 olarak açıldı (C3/F2 araması [TPD-5, TPD-8] döndürdü).
PUBLISHED_BUGS: dict[str, tuple[str, str]] = {
    "@kredi-limiti": ("TPD-8", "f4-kredi-limiti/HATA"),
    "@kirma": ("TPD-12", "kirma-kampanya/HATA"),
    "@alti-adet": ("TPD-14", "HATA"),
}

# Mükerrer aramasının olası aday kümeleri: seed (metin araması / tüm açık Bug'lar) ve demo
# sırasında açılan Bug'larla genişleyen kümeler (F4, kırma ve C3 için "Yeni kayıt").
DUP_KEY_SETS: list[list[str]] = [
    ["TPD-5", "TPD-6"],
    ["TPD-5"],
    ["TPD-5", "@kredi-limiti"],
    ["TPD-5", "TPD-6", "@kredi-limiti"],
    ["TPD-5", "@kirma"],
    ["TPD-5", "TPD-6", "@kirma", "@kredi-limiti"],
    ["TPD-5", "@alti-adet", "@kirma", "@kredi-limiti"],
]


def published_bug(alias: str) -> JiraIssue:
    """`publish_bug` ile "Yeni kayıt" olarak açılmış Bug (`RestJira.search` biçimi)."""
    from tp_core.integrations.jira import issue_from_json

    key, golden = PUBLISHED_BUGS[alias]
    summary = load_golden("bug_draft", golden)["output"]["summary"]
    return issue_from_json(
        {
            "key": key,
            "fields": {
                "issuetype": {"name": "Bug"},
                "summary": summary,
                "description": None,
                "status": {"name": "To Do"},
                "updated": "2026-10-31T12:00:00.000+0000",
            },
        }
    )


def candidate(key: str) -> JiraIssue:
    return published_bug(key) if key.startswith("@") else seed_bug(key)


def candidate_key(key: str) -> str:
    return PUBLISHED_BUGS[key][0] if key.startswith("@") else key


# ------------------------------------------------------------------ mesajlar


def c3_sources(run_id: str | None = None, suffix: str = "1a2b3c4d") -> list[str]:
    return [
        failure_block(c3_failure(run_id, suffix), **c3_failure_kwargs(run_id, suffix)),
        case_block(c3_case(), "TPD-1-C3"),
    ]


def break_sources(index: int = 0, run_id: str | None = None) -> list[str]:
    title, path, line = BREAK_TESTS[index]
    return [failure_block(break_failure(path, line, run_id), **break_failure_kwargs(title, path))]


def finding_sources(golden: str, fid: str) -> list[str]:
    return [finding_block(**finding_kwargs(golden, fid))]


def bug_messages(sources: Sequence[str], *, test_case_key: str | None = None) -> list[ModelMessage]:
    return bug_draft_messages(
        sources, testdata=testdata_block(), story_key="TPD-1", test_case_key=test_case_key
    )


def dup_messages(
    sources: Sequence[str], keys: Sequence[str], draft: dict[str, Any] | None = None
) -> list[ModelMessage]:
    draft = draft or {"summary": "taslak", "expected": "-", "actual": "-", "story_key": "TPD-1"}
    return dup_rank_messages(
        sources, draft=draft, candidates=[candidate(k) for k in keys], jql=DUP_JQL
    )


def timeout_messages(run_id: str | None = None) -> list[ModelMessage]:
    return triage_messages(failure_block(timeout_failure(run_id), **timeout_kwargs()))
