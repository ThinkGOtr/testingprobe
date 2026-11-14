"""case_review (P8) ve case_audit (P9) golden'ları (011 D şeridi).

- Depodaki dosyalar üreticinin (`build_review_goldens`) çıktısıyla aynı.
- Üretimin girdi kurucularıyla (`review.review_messages`, `denetim.audit_messages`) kurulan girdi,
  sıkı prova kipinde (`TP_REPLAY_STRICT=1`) golden beyanına uyar → REPLAY / golden_matched.
- Set değişince (tek case düzeltildi) dürüst REPLAY-MISS: sıkı kipte `ReplayMiss`, gevşek kipte
  `on_miss: raise` (başka setin review'u/kararı asla dönmez).
- Golden setlerinde deterministik sertleştirme kuralı tetiklenmez (KABUL'ler KABUL kalır).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tests.unit.gateway import build_review_goldens as brg
from tests.unit.gateway.build_eval_sets import _golden_set
from tests.unit.gateway.demo_sources import RULES
from tp_core.audit import content_hash
from tp_core.features.cases import denetim_akisi, review
from tp_core.features.cases.schema import coverage_matrix
from tp_core.gateway import MATCHED, Gateway, load_schema
from tp_core.gateway.config import GatewaySettings
from tp_core.gateway.errors import ReplayNotFound
from tp_core.gateway.factory import build_gateway
from tp_core.gateway.testing import InMemoryCallRecorder
from tp_core.integrations.agent_probe import denetim
from tp_core.ports import CaseSetAuditRequest

BEKLENEN_KARAR = {
    "TPD-1": "KABUL",
    "f2-kod-hatasi/TPD-1": "KABUL",
    "TPD-3": "DÜZELTME_GEREKLİ",
    "TPD-4": "KABUL",
    "SERBEST": "KABUL",
    "c10-reddedildi/TPD-1": "KABUL",
    "f2-kod-hatasi-c10-reddedildi/TPD-1": "KABUL",
}


def _set(ad: str) -> tuple[Any, list, dict]:
    """Golden adının seti: varyantta reddedilen case'ler çıkarılır (`brg.VARYANTLAR`)."""
    gen_ad, cases = brg.golden_set_cases(ad)
    req, _, ozet = _golden_set(gen_ad)
    return req, copy.deepcopy(cases), ozet


@pytest.fixture
def strict_gateway(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.setenv("TP_REPLAY_STRICT", "1")
    monkeypatch.setenv("TP_RULES_DIR", str(RULES))
    return build_gateway(InMemoryCallRecorder(), settings=GatewaySettings())


def _review_call(gw: Gateway, req: Any, cases: list, ozet: dict) -> Any:
    m = coverage_matrix(cases, ozet, req.kabul_kriterleri)
    h = review.hash_of([content_hash(dict(c)) for c in cases]) or ""
    return gw.call(
        "case_review",
        "case-review",
        review.review_messages(req, cases, ozet, m["satirlar"], m["oranlar"], h),
        load_schema(RULES, "case_review"),
        replay_key=review.replay_key_for(req),
    )


def _audit_istek(req: Any, cases: list, ozet: dict) -> CaseSetAuditRequest:
    blok, kok = review.requirement_block_for(req)
    return CaseSetAuditRequest(
        requirement_id=req.id,
        requirement_key=kok,
        set_hash=review.hash_of([content_hash(dict(c)) for c in cases]) or "",
        requirement_block=blok,
        generated_set=review.set_payload(cases, ozet),
        review_result={"score": 10, "summary": "örnek"},
        policies=denetim_akisi.policies(RULES),
    )


def _audit_call(gw: Gateway, req: Any, cases: list, ozet: dict) -> Any:
    istek = _audit_istek(req, cases, ozet)
    return gw.call(
        "case_audit",
        "case-audit",
        denetim.audit_messages(istek),
        load_schema(RULES, "case_audit"),
        replay_key=denetim.replay_key_for(istek),
    )


def test_golden_dosyalari_ureticiyle_ayni() -> None:
    for (amac, ad), kayit in brg.build().items():
        yol = RULES / "replay" / amac / "golden" / f"{ad}.json"
        assert yol.read_text(encoding="utf-8") == brg.dump(kayit), yol


@pytest.mark.parametrize("ad", [*brg.GOLDENLER, *brg.VARYANTLAR])
def test_uretim_girdisi_golden_beyanina_uyar(strict_gateway: Gateway, ad: str) -> None:
    req, cases, ozet = _set(ad)
    r = _review_call(strict_gateway, req, cases, ozet)
    a = _audit_call(strict_gateway, req, cases, ozet)
    assert r.mode == a.mode == "replay"
    for row in strict_gateway.recorder.ai_calls:  # type: ignore[attr-defined]
        assert row["ek"]["replay_kokeni"] == MATCHED
        assert row["ek"]["replay_kaynagi"].endswith(f"/golden/{ad}.json"), row["ek"]
    assert a.output["decision"] == BEKLENEN_KARAR[ad]
    assert r.output["score"] == review.score_of(r.output)
    assert review.output_problems(r.output, len(cases)) == []
    # Demo setlerinde deterministik kural tetiklenmez: karar sertleşmez.
    metin = "\n".join([req.baslik, req.aciklama, *req.kabul_kriterleri])
    assert (
        denetim_akisi.deterministic_findings(cases, metin, denetim_akisi.allowed_hosts(RULES)) == []
    )


def test_set_degisince_durust_replay_miss(strict_gateway: Gateway) -> None:
    req, cases, ozet = _golden_set("TPD-4")
    duzeltilmis = copy.deepcopy(cases)
    duzeltilmis[0]["title"] += " (düzeltildi)"
    with pytest.raises(ReplayNotFound):
        _review_call(strict_gateway, req, duzeltilmis, ozet)
    with pytest.raises(ReplayNotFound):
        _audit_call(strict_gateway, req, duzeltilmis, ozet)


def test_gevsek_kipte_de_baska_setin_karari_donmez(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TP_REPLAY_STRICT", raising=False)
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.setenv("TP_RULES_DIR", str(RULES))
    gw = build_gateway(InMemoryCallRecorder(), settings=GatewaySettings())
    req, cases, ozet = _golden_set("TPD-1")
    with pytest.raises(ReplayNotFound):
        _audit_call(gw, req, cases[:-1], ozet)  # son case (C15) reddedildi → set değişti


def test_review_girdisi_test_verisi_blogunu_tasir(strict_gateway: Gateway) -> None:
    """P8 girdisi üretimin test verisi bloğunu taşır (canlı eval 2026-11-13: bloksuz girdide
    golden'ın bayi adı "uydurma" sayıldı); blok golden beyanını bozmaz (REPLAY eşleşir)."""
    from tests.unit.gateway.build_eval_sets import _test_data_block

    req, cases, ozet = _set("TPD-4")
    m = coverage_matrix(cases, ozet, req.kabul_kriterleri)
    h = review.hash_of([content_hash(dict(c)) for c in cases]) or ""
    blok = _test_data_block()
    bloksuz = review.review_messages(req, cases, ozet, m["satirlar"], m["oranlar"], h)
    bloklu = review.review_messages(
        req, cases, ozet, m["satirlar"], m["oranlar"], h, test_data_block=blok
    )
    assert blok not in bloksuz[0].content
    icerik = bloklu[0].content
    assert blok in icerik and '"Merkez Bayi"' in icerik
    # Blok gereksinimden sonra, setten önce.
    assert icerik.index("Gereksinim:") < icerik.index(blok) < icerik.index("Üretilmiş set")
    res = strict_gateway.call(
        "case_review",
        "case-review",
        bloklu,
        load_schema(RULES, "case_review"),
        replay_key=review.replay_key_for(req),
    )
    assert res.mode == "replay"
    row = strict_gateway.recorder.ai_calls[-1]  # type: ignore[attr-defined]
    assert row["ek"]["replay_kokeni"] == MATCHED


def _review_cikti(uygun: int, score: Any) -> dict[str, Any]:
    items = [{"no": i, "verdict": "UYGUN" if i <= uygun else "UYGUN_DEGIL"} for i in range(1, 13)]
    return {"items": items, "score": score, "missing_cases": [], "remove_or_merge": []}


def test_skor_kodda_sayilir_model_skoru_saklanir(caplog: pytest.LogCaptureFixture) -> None:
    islenmis = review.normalize_output(_review_cikti(10, 9))
    assert islenmis["score"] == 10
    assert islenmis["model_skoru"] == 9
    assert "model skoru 9" in caplog.text


def test_degerlendirme_kullanicinin_gordugu_skoru_olcer() -> None:
    from tp_core.gateway.eval_agents import review_set_problems

    # Modelin yazdığı skor farklı; kullanıcı kodun saydığı 8'i görür: tutarlılık hatası değildir.
    assert review_set_problems(_review_cikti(8, 7), {}) == []
    # Aralık denetimi işlenmiş (kodda sayılmış) skora yapılır.
    assert review_set_problems(_review_cikti(8, 12), {"min_score": 9}) == ["skor 8, en az 9"]
