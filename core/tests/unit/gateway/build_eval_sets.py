"""Faz 4 prompt paketlerinin değerlendirme setlerini (`rules/evaluation/<paket>.json`) üretir.

Girdiler golden testlerinin kullandığı kanonik kuruculardan (`defect_inputs`, yani
`tp_core.gateway.defects`) gelir; triage `Kural sinyalleri` satırları üretimdeki
`triage.service.kural_sinyalleri` ile kurulur. Setler bu modülden yeniden üretilir:

    cd core && uv run python -m tests.unit.gateway.build_eval_sets

`test_eval_sets` depodaki setin bu modülün çıktısıyla aynı olduğunu denetler (kurucu veya kaynak
değişince set bayatlar). Canlı koşu: `python -m tp_core.gateway.eval_set --bundle <paket>`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.unit.gateway import defect_inputs as di
from tests.unit.gateway.demo_sources import RULES
from tp_core.gateway import defect_replay_key, failure_block, triage_messages
from tp_core.gateway.eval_set import EVAL_DIR
from tp_core.gateway.evaluation import prompt_versions
from tp_core.ports import ModelMessage

NO_MONEY = {"actual": ["TL"]}


def _msgs(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    return [m.model_dump() for m in messages]


def _rule_signals(failure: Mapping[str, Any], *, saglik: Any, attempts: list[str]) -> list[str]:
    from tp_core.features.triage.rules import Girdi
    from tp_core.features.triage.service import kural_sinyalleri

    girdi = Girdi(
        test_adi="eval",
        hata_turu=failure.get("type"),
        mesaj=failure.get("message"),
        beklenen=failure.get("expected"),
        gerceklesen=failure.get("received"),
        locator=failure.get("locator"),
        saglik=saglik,
        deneme_durumlari=attempts,
    )
    return kural_sinyalleri(girdi, [], None)


def _failure(**over: Any) -> dict[str, Any]:
    base = di.timeout_failure("00000000-0000-4000-8000-000000000000")
    base.update(
        {
            "matcher": None,
            "action": None,
            "locator": None,
            "expected": None,
            "received": None,
            "signals": [],
            "aria_snapshot": None,
        }
    )
    base.update(over)
    return base


def _triage(
    failure: dict[str, Any],
    *,
    title: str,
    saglik: Any,
    statuses: dict[str, int],
    consistent: bool,
    attempts: list[str],
) -> list[dict[str, Any]]:
    blk = failure_block(
        failure,
        test_title=title,
        test_file=failure["test_location"]["file"],
        story_key="TPD-1",
        saglik=saglik,
        statuses=statuses,
        consistent=consistent,
        rule_signals=_rule_signals(failure, saglik=saglik, attempts=attempts),
        include_aria=True,
    )
    return _msgs(triage_messages(blk))


def triage_cases() -> list[dict[str, Any]]:
    order = {"file": "tests/order.spec.ts", "line": 10, "column": 3}
    # Kural 1'in ağ hatası kalıbına (ECONNREFUSED, net::ERR_ …) uymayan ama servisin ayakta
    # olmadığını söyleyen mesaj: kalıba uyan hata modele hiç gitmez (kural → environment).
    unavailable = (
        "Error: apiRequestContext.post: 503 Service Unavailable — upstream demo-app-api "
        "bağlantıyı reddetti (connection refused)"
    )
    refused = _failure(
        type="other",
        first_line=unavailable,
        message=unavailable,
        status="failed",
        timeout_ms=None,
    )
    hidden_button = _failure(
        type="locator_timeout",
        first_line="Error: locator.click: Timeout 5000ms exceeded.",
        message="Error: locator.click: Timeout 5000ms exceeded.",
        action="click",
        locator="getByRole('button', { name: 'Siparişi onayla' })",
        timeout_ms=5000,
        signals=["eleman görünür olmadı"],
        status="failed",
        location=order,
        aria_snapshot='- heading "Sepet" [level=1]\n- status: "Sepet yükleniyor"',
    )
    # Kural 5'in fixture kalıbına uymayan veri önkoşulu: test, seed'de olmayan bayiyle girer.
    no_dealer = "Error: giriş başarısız: 'bayi9' adlı bayi kullanıcısı bulunamadı (401)"
    missing_dealer = _failure(
        type="other",
        first_line=no_dealer,
        message=no_dealer,
        status="failed",
        timeout_ms=None,
    )
    return [
        {
            "id": "zaman-asimi-kuralsiz",
            "description": "Golden: kuralların eşleşmediği test zaman aşımı → unknown (tahmin yok)",
            "messages": _msgs(di.timeout_messages("00000000-0000-4000-8000-000000000000")),
            "expect": {"class": "unknown", "sub_type": None},
        },
        {
            "id": "saglikli-agsiz-eleman-gorunmedi",
            "description": "Sağlık başarılı, ağ hatası yok: ortam denmez (triage.md sert kural)",
            "messages": _triage(
                hidden_button,
                title="Sipariş › sepet onayı",
                saglik=di.HEALTHY,
                statuses={"unexpected": 2},
                consistent=True,
                attempts=["failed", "failed"],
            ),
            "expect": {"class_not": ["environment", "product_defect"]},
        },
        {
            "id": "saglik-bilinmiyor-baglanti-reddedildi",
            "description": "Sağlık bilgisi yok + kural kalıbı dışı bağlantı reddi (503): ortam",
            "messages": _triage(
                refused,
                title="Katalog › ürünler listelenir",
                saglik=None,
                statuses={"unexpected": 2},
                consistent=True,
                attempts=["failed", "failed"],
            ),
            "expect": {"class": "environment", "sub_type": None},
        },
        {
            "id": "test-verisi-eksik-bayi",
            "description": "Seed'de olmayan bayi ile giriş: test verisi",
            "messages": _triage(
                missing_dealer,
                title="Giriş › bayi9 ile giriş yapılır",
                saglik=di.HEALTHY,
                statuses={"unexpected": 2},
                consistent=True,
                attempts=["failed", "failed"],
            ),
            "expect": {"class": "test_data", "sub_type": None},
        },
    ]


def bug_draft_cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "c3-6-adet",
            "description": "Ana yol: C3 6 adet → bedava 1 (assertion: beklenen 0)",
            "messages": _msgs(di.bug_messages(di.c3_sources())),
            "expect": {
                "contains": {"summary": ["6 adet"], "actual": ["1"], "steps": ["bayi1", "6"]},
                "not_contains": NO_MONEY,
                "story_key": "TPD-1",
            },
        },
        {
            "id": "kirma-7-adet",
            "description": "BREAK_CAMPAIGN: 7 adet → bedava 0; ortam kasıtlı kırılmayı söyler",
            "messages": _msgs(di.bug_messages(di.break_sources(0))),
            "expect": {
                "contains": {"summary": ["7 adet"], "environment": ["BREAK_CAMPAIGN"]},
                "not_contains": NO_MONEY,
                "story_key": "TPD-1",
            },
        },
        {
            "id": "f2-kampanya-bulgusu",
            "description": "Demo-A F2: kod 6 adette 1 bedava (campaign.py:23)",
            "messages": _msgs(di.bug_messages(di.finding_sources("TPD-1", "F2"))),
            "expect": {"contains": {"steps": ["Portakal Gazozu"]}, "story_key": "TPD-1"},
        },
        {
            "id": "f4-kredi-limiti-bulgusu",
            "description": "Demo-A F4: kredi limiti kontrolü yok; adımlar bayi2 ile limiti aşar",
            "messages": _msgs(di.bug_messages(di.finding_sources("TPD-1", "F4"))),
            "expect": {
                "contains": {"steps": ["bayi2"], "expected": ["Kredi limiti aşıldı"]},
                "story_key": "TPD-1",
            },
        },
    ]


def _dup(
    case_id: str,
    description: str,
    sources: Callable[[], list[str]],
    keys: list[str],
    expect: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": case_id,
        "description": description,
        "messages": _msgs(di.dup_messages(sources(), keys)),
        "expect": {"candidate_keys": [di.candidate_key(k) for k in keys], **expect},
    }


def dup_rank_cases() -> list[dict[str, Any]]:
    link5 = {"top": "TPD-5", "recommendation": "link", "link_key": "TPD-5"}
    return [
        _dup("c3-seed", "C3 → TPD-5 aynı belirti", di.c3_sources, ["TPD-5", "TPD-6"], link5),
        _dup(
            "c3-f4-yayimlandi",
            "F4 yeni Bug olarak açıldıktan sonra C3: TPD-5 yine ilk",
            di.c3_sources,
            ["TPD-5", "@kredi-limiti"],
            link5,
        ),
        _dup(
            "f2-seed",
            "F2 bulgusu → TPD-5",
            lambda: di.finding_sources("TPD-1", "F2"),
            ["TPD-5", "TPD-6"],
            link5,
        ),
        _dup(
            "kirma-seed",
            "Kırma (7 adet → 0): TPD-5 ters belirti, yeni kayıt",
            di.break_sources,
            ["TPD-5", "TPD-6"],
            {"top": "TPD-5", "recommendation": "new", "link_key": None},
        ),
        _dup(
            "kirma-onceki-kirma-bug",
            "Önceki kırma koşusunun Bug'ı aramada: aynı belirti",
            di.break_sources,
            ["TPD-5", "@kirma"],
            {
                "top": di.candidate_key("@kirma"),
                "recommendation": "link",
                "link_key": di.candidate_key("@kirma"),
            },
        ),
        _dup(
            "f4-seed",
            "F4 kredi limiti: seed Bug'larının hiçbiri değil",
            lambda: di.finding_sources("TPD-1", "F4"),
            ["TPD-5", "TPD-6"],
            {"recommendation": "new", "link_key": None},
        ),
    ]


SETS: dict[str, tuple[str, Callable[[], list[dict[str, Any]]]]] = {
    "triage": ("triage", triage_cases),
    "bug-draft": ("bug_draft", bug_draft_cases),
    "dup-rank": ("dup_rank", dup_rank_cases),
}


def build_sets() -> dict[str, dict[str, Any]]:
    versions = prompt_versions(RULES)
    return {
        bundle: {
            "bundle": bundle,
            "purpose": purpose,
            "version": versions[bundle],
            # Geçidin golden kökü: REPLAY duman koşusu golden'ları kullanır, `record` kipi
            # demo girdileriyle aynı anahtarı yazar.
            "replay_key": defect_replay_key("TPD-1"),
            "note": (
                "Üretildi: core/tests/unit/gateway/build_eval_sets.py (elle düzenlemeyin). "
                "Canlı koşu: python -m tp_core.gateway.eval_set --bundle " + bundle
            ),
            "cases": build(),
        }
        for bundle, (purpose, build) in SETS.items()
    }


def dump(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_sets(rules_dir: Path = RULES) -> list[Path]:
    out = []
    for bundle, data in build_sets().items():
        path = rules_dir / EVAL_DIR / f"{bundle}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(data), encoding="utf-8")
        out.append(path)
    return out


if __name__ == "__main__":  # pragma: no cover
    for p in write_sets():
        print(p)
