"""Bug şeridi test yardımcıları: başarısızlık/bulgu kayıtları, jira-sim, geçit fikstürleri.

Kayıtlar demo hikâyesinin gerçek biçimindedir (docs/DEMO-VERISI.md): C3 yerel kontrolü
(`expectFreeQuantity("P-001", 0)` → "1"), kırma koşusu (C2, 7 adet → bedava "0"), F2/F4 tutarlılık
bulguları. Case'ler `case_generation/golden/f2-kod-hatasi/TPD-1` golden'ından okunur; böylece
REPLAY golden'larının `input_match` beyanları gerçek kod yoluyla sınanır.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine

import tp_core.features.bugs.jobs  # noqa: F401  (iş işleyicileri)
from tp_core.audit import PgCallRecorder, content_hash
from tp_core.features.bugs import services
from tp_core.features.cases.testdata import SORGULAR, build_text
from tp_core.gateway import build_gateway, find_rules_dir, wrap_untrusted
from tp_core.gateway.config import GatewaySettings
from tp_core.gateway.testing import FakeProvider
from tp_core.integrations.jira import RestJira
from tp_core.models import (
    BugDraft,
    ConsistencyFinding,
    ExternalRef,
    Failure,
    Requirement,
    Run,
    TestCase,
    TestResult,
    case_id,
    session_scope,
)
from tp_core.models.ci_feature import TestResultEk

TPD1_ACS = [
    'AC1: Bayi katalogda bir ürün için "Sepete ekle" butonuna bastığında ürün sepete eklenir '
    "ve sepet sayacı artar.",
    "AC2: Kampanyalı üründe her 6 adede 1 adet bedava verilir (6 öde + 1 bedava).",
    'AC4: Sipariş tutarı bayinin kredi limitini aşarsa "Kredi limiti aşıldı" uyarısı '
    "gösterilir ve sipariş onaylanamaz.",
]
LOCATOR = "getByTestId('cart-line-free-P-001')"

# demo-app seed'inin salt okuma sorgu sonuçları (testdata bloğu; DEMO-VERISI.md).
SEED_ROWS = {
    "urun": [
        ("P-001", "Portakal Gazozu 1L", Decimal("25.00")),
        ("P-002", "Limonata 330ml", Decimal("15.00")),
        ("P-003", "Maden Suyu 200ml", Decimal("8.00")),
        ("P-004", "Şeftalili Soğuk Çay 1L", Decimal("30.00")),
    ],
    "kampanya": [("K-6AL1", "6 al 1 bedava", "P-001")],
    "ayar": [("min_siparis_tutari", "750.00")],
    "bayi": [
        ("bayi1", "Merkez Bayi", Decimal("100000.00")),
        ("bayi2", "Sahil Bayi", Decimal("500.00")),
    ],
}


def testdata_block() -> str:
    sorgular = {sql: ad for ad, sql in SORGULAR.items()}
    return wrap_untrusted(
        build_text(lambda sql: SEED_ROWS[sorgular[sql]]), source="testdata:demo-app", kind="data"
    )


def golden_case(sira: int) -> dict[str, Any]:
    path = find_rules_dir() / "replay/case_generation/golden/f2-kod-hatasi/TPD-1.json"
    return json.loads(path.read_text(encoding="utf-8"))["output"]["cases"][sira - 1]


def _mesaj(beklenen: int, gerceklesen: int) -> str:
    return (
        "Error: \x1b[2mexpect(\x1b[22mlocator\x1b[2m).\x1b[22mtoHaveText(expected) failed\n\n"
        f'Locator:  {LOCATOR}\nExpected: "{beklenen}"\nReceived: "{gerceklesen}"\n'
        'Timeout:  5000ms\n\nCall log:\n  - Expect "toHaveText" with timeout 5000ms\n'
    )


SENARYO = {
    # Ana yol: C3 yerel kontrolü (kod adet // 6 → 6 adette 1 bedava).
    "c3": {"sira": 3, "beklenen": 0, "gerceklesen": 1, "kirma": False},
    # Kırma koşusu: BREAK_CAMPAIGN açık, C2 (7 adet → bedava 1 beklenir, 0 gelir).
    "c2_kirma": {"sira": 2, "beklenen": 1, "gerceklesen": 0, "kirma": True},
}


def make_requirement(jira_key: str = "TPD-1") -> uuid.UUID:
    with session_scope() as s:
        req = Requirement(
            kaynak="jira",
            jira_key=jira_key,
            baslik="Sepet ve kampanya",
            aciklama="Bayi, katalogdan ürünleri sepete ekleyip kampanya indirimiyle siparişini "
            "onaylayabilmelidir.",
            kabul_kriterleri=list(TPD1_ACS),
            kaynak_hash="test",
        )
        s.add(req)
        s.flush()
        return req.id


def seed_failure(
    jira: RestJira | None = None,
    *,
    senaryo: str = "c3",
    sinif: str = "product_defect",
    imza: str | None = None,
    req_id: uuid.UUID | None = None,
    test_issue: bool = True,
    triage_ek: bool = False,
) -> dict[str, Any]:
    """Kırmızı koşu: run + test_result (+ ekler) + failure (+ isteğe bağlı triage `failure_ek`)."""
    sc = SENARYO[senaryo]
    rid = req_id or make_requirement()
    test_key = None
    if test_issue and jira is not None:
        test_key = jira.create_issue("TPD", "Test", f"C{sc['sira']}", "", ["AI-generated"])
    icerik = golden_case(sc["sira"])
    test_adi = f"TPD-1 · C{sc['sira']} › {icerik['title']} @tp-uretilen"
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert req is not None
        tc_id = case_id(req, sc["sira"], 1)
        if s.get(TestCase, tc_id) is None:
            s.add(
                TestCase(
                    id=tc_id,
                    requirement_id=rid,
                    sira_no=sc["sira"],
                    icerik=icerik,
                    icerik_hash=content_hash(icerik),
                )
            )
            s.flush()
        if test_key:
            s.add(
                ExternalRef(
                    entity_turu="test_case",
                    entity_id=tc_id,
                    sistem="jira",
                    idempotency_key=f"publish:jira:test_case:{tc_id}:{uuid.uuid4()}",
                    external_key=test_key,
                    durum="created",
                )
            )
        run = Run(
            tetik="break_verify" if sc["kirma"] else "local_check",
            kaynak="local",
            commit="0123456789abcdef0123",
            sonuc="failed",
            ortam={"break_campaign": True} if sc["kirma"] else {},
            artefaktlar={
                "dizin": "run-20261031-c3",
                "allure_html": "allure-report/index.html",
                "html": "playwright-report",
                "log": "runner.log",
            },
        )
        s.add(run)
        s.flush()
        tr = TestResult(
            run_id=run.id,
            test_case_id=tc_id,
            test_adi=test_adi,
            dosya=f"tests/generated/tpd-1-c{sc['sira']}-0a1b2c3d.spec.ts",
            sonuc="failed",
            tetik=run.tetik,
            hata_mesaji=_mesaj(sc["beklenen"], sc["gerceklesen"]),
        )
        s.add(tr)
        s.flush()
        s.add(
            TestResultEk(
                test_result_id=tr.id,
                ekler=[
                    {"ad": "trace", "yol": "results/c/trace.zip", "tur": "application/zip"},
                    {"ad": "screenshot", "yol": "results/c/test-failed-1.png", "tur": "image/png"},
                ],
            )
        )
        f = Failure(
            run_id=run.id,
            test_result_id=tr.id,
            test_adi=test_adi,
            hata_imzasi=imza or f"assertion:{senaryo}:{LOCATOR}",
            sinif=sinif,
            alt_tur="assertion",
            eslesen_sinyaller=[
                {"kod": "assertion_mismatch", "aciklama": "beklenen ≠ gerçekleşen (tutarlı)"}
            ],
        )
        s.add(f)
        s.flush()
        if triage_ek:
            from tp_core.models.triage_feature import FailureEk

            s.add(
                FailureEk(
                    failure_id=f.id,
                    anahtar=f"{run.id}:{tr.dosya}:{test_adi}",
                    kaynak="kirma" if sc["kirma"] else "codegen",
                    kirma=sc["kirma"],
                    kanit={
                        "hata_mesaji": "Error: expect(locator).toHaveText(expected) failed",
                        "hata_turu": "assertion",
                        "beklenen": f'"{sc["beklenen"]}"',
                        "gerceklesen": f'"{sc["gerceklesen"]}"',
                        "locator": LOCATOR,
                        "matcher": "toHaveText",
                    },
                    kanit_linkleri=[
                        {
                            "etiket": "Playwright trace",
                            "yol": "results/t/trace.zip",
                            "tur": "trace",
                        },
                        {
                            "etiket": "Hata anı sayfa snapshot'ı (error-context)",
                            "yol": "results/t/error-context.md",
                            "tur": "error_context",
                        },
                    ],
                )
            )
        return {
            "failure_id": f.id,
            "run_id": run.id,
            "test_case_id": tc_id,
            "test_key": test_key,
            "requirement_id": rid,
        }


LEGACY = {
    "F4": {
        "tur": "missing_in_code",
        "doc_ref": "AC4",
        "kanit": {
            "kind": "code",
            "repo": "demo-app",
            "path": "api/src/demoapp_api/pricing.py",
            "line": 97,
            "snippet": "uyarilar.append(f'Minimum sipariş tutarı {tl(min_tutar)}')",
        },
        "summary": "TPD-1 AC4: Kredi limiti aşımında uyarı gösterilmeli",
    },
    "F2": {
        "tur": "doc_vs_code",
        "doc_ref": "AC2",
        "kanit": {
            "kind": "code",
            "repo": "demo-app",
            "path": "api/src/demoapp_api/campaign.py",
            "line": 23,
            "snippet": "return adet // 6",
        },
        "summary": "TPD-1 AC2: 6 adette bedava veriliyor",
    },
}


def seed_finding_draft(bulgu: str = "F4", req_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Faz 2 biçiminde (requirements.ensure_bug_draft) tutarlılık taslağı."""
    b_ = LEGACY[bulgu]
    rid = req_id or make_requirement()
    with session_scope() as s:
        f = ConsistencyFinding(
            requirement_id=rid,
            tur=b_["tur"],
            doc_ref=b_["doc_ref"],
            kanitlar=[b_["kanit"]],
            severity="blocking",
            kanit_dogrulandi=True,
        )
        s.add(f)
        s.flush()
        icerik = {
            "summary": b_["summary"],
            "uretim": "sablon",
            "steps": [f"Kodda {b_['kanit']['path']}:{b_['kanit']['line']} satırını açın"],
            "expected": "Dokümandaki davranış",
            "actual": "Kod farklı davranıyor",
            "environment": "Tutarlılık denetimi · demo-app@abc",
            "evidence": [
                {"tur": "code", "url": None, "etiket": f"demo-app · {b_['kanit']['path']}"}
            ],
            "story_key": "TPD-1",
            "test_case_key": None,
            "severity_suggestion": "major",
            "labels": ["AI-generated"],
            "kaynak": "consistency_finding",
            "finding_id": str(f.id),
        }
        b = BugDraft(finding_id=f.id, icerik=icerik, icerik_hash=content_hash(icerik))
        s.add(b)
        s.flush()
        return {"finding_id": f.id, "draft_id": b.id, "requirement_id": rid}


# ---------------------------------------------------------------------- fikstürler


@pytest.fixture
def bug_services(jira: RestJira) -> Iterator[RestJira]:
    with services.override(jira=lambda: jira, project=lambda: "TPD", testdata=testdata_block):
        yield jira


@pytest.fixture
def bug_replay_gateway(
    engine: Engine, bug_services: RestJira, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Any]:
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TP_REPLAY_STRICT", "0")
    monkeypatch.delenv("TP_RULES_DIR", raising=False)
    gw = build_gateway(PgCallRecorder(engine), settings=GatewaySettings(), engine=engine)
    with services.override(gateway=lambda _e: gw):
        yield gw


@pytest.fixture
def bug_fake_gateway(engine: Engine, bug_services: RestJira, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TP_MODEL_MODE", "live")
    monkeypatch.delenv("TP_RULES_DIR", raising=False)
    kurulan: list[Any] = []

    def _kur(script: list[Any]) -> FakeProvider:
        provider = FakeProvider(script)
        gw = build_gateway(
            PgCallRecorder(engine), settings=GatewaySettings(), engine=engine, provider=provider
        )
        kurulan.append(gw)
        return provider

    with services.override(gateway=lambda _e: kurulan[-1]):
        yield _kur
