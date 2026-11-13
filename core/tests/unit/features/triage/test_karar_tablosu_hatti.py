"""012 §4.4 tek boru hattı (review tur 1 Ö5): oracle kaydı elle yazılmaz.

Onaylı C3 ("6 adette bedava yok"; demo ana yolu `f2-kod-hatasi`) → onaylı karar tablosu → oracle
servisinin gerçek kontrol işi (`oracle.check_case`, sahte `case_facts` modeli) → kayıt → C3'ün
şablondan üretilmiş Playwright testi `// 6` uygulamasında `expectFreeQuantity("P-001", 0)`'da
kırmızı (Playwright rapor fikstürü) → `classify_run` → `product_defect` + `karar_tablosu_uyumlu`.

Tablo bu dosyanın kendisidir (bedava adet kolonu): oracle şeridinin TPD-1 T1'i değişse de
(review V9) bu hat aynı kalır.
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

import tp_core.features.oracle.jobs  # noqa: F401  (oracle.* iş işleyicileri)
from tp_core.audit import PgCallRecorder, content_hash
from tp_core.features.codegen.render import RenderInput, render_test
from tp_core.features.oracle import service as oracle_service
from tp_core.features.triage import classify_run
from tp_core.gateway import build_gateway, find_rules_dir
from tp_core.gateway.config import GatewaySettings
from tp_core.gateway.testing import FakeProvider, text_response
from tp_core.models import Failure, Requirement, Script, TestCase, session_scope
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.guard import allow_state_write
from tp_core.models.kalite_feature import CaseOracleKontrol, KararTablosu
from tp_core.models.triage_feature import FailureEk
from tp_core.workflow.service import content_hash_of

from .conftest import KTest, kosu_kur, run_jobs

pytestmark = pytest.mark.usefixtures("triage_env")

RULES = find_rules_dir()
C3: dict[str, Any] = json.loads(
    (RULES / "replay/case_generation/golden/f2-kod-hatasi/TPD-1.json").read_text(encoding="utf-8")
)["output"]["cases"][2]
ESLEME: dict[str, Any] = json.loads(
    (RULES / "replay/verify_and_map/golden/f2-kod-hatasi/TPD-1-C3.json").read_text(encoding="utf-8")
)["output"]
TABLO: dict[str, Any] = {
    "ad": "Kampanya: 7 adette 1 bedava",
    "ac_refs": ["AC2"],
    "girdiler": [{"ad": "adet", "tur": "sayi"}],
    "ciktilar": [{"ad": "bedava_adet", "tur": "sayi"}],
    "satirlar": [
        {"id": "R1", "kosul": "adet >= 7", "cikti": {"bedava_adet": "adet // 7"}},
        {"id": "R2", "kosul": "dogru", "cikti": {"bedava_adet": "0"}},
    ],
}
# Dikkatli bir modelin C3'ten çıkaracağı olgular (alıntılar case alanlarından birebir; beklenen
# alanlardaki her sayı bir olguda ya da `ignored`'da alıntılanır, yoksa sonuç `kismen` olur).
OLGULAR = {
    "groups": [
        {
            "table_ref": "T1",
            "inputs": [
                {"column": "adet", "value": "6", "field": "steps[2].data", "quote": "6"},
                {"column": "adet", "value": "6", "field": "steps[2].expected", "quote": "6"},
                {"column": "adet", "value": "6", "field": "steps[3].expected", "quote": "adet 6"},
                {"column": "adet", "value": "6", "field": "expected_result", "quote": "6 adette"},
            ],
            "expected": [
                {
                    "column": "bedava_adet",
                    "value": "0",
                    "field": "steps[3].expected",
                    "quote": "adet 0",
                },
                {
                    "column": "bedava_adet",
                    "value": "0",
                    "field": "expected_result",
                    "quote": "adet 0",
                },
            ],
        }
    ],
    # Beklenen alanlardaki tablonun kolonu olmayan sayılar (tamlık denetimi; şema zorunlu kılar).
    "ignored": [
        {
            "field": "steps[3].expected",
            "quote": "ara toplam 150,00 TL, indirim 0,00 TL, toplam 150,00 TL",
            "reason": "tutarlar bu tablonun kolonu değil",
        },
        {
            "field": "expected_result",
            "quote": "bedava 7. adette başlar",
            "reason": "kampanya eşiği; kural metni, kolon değeri değil",
        },
        {
            "field": "expected_result",
            "quote": "indirim 0,00 TL, toplam 150,00 TL",
            "reason": "tutarlar bu tablonun kolonu değil",
        },
    ],
}


@pytest.fixture
def olgu_modeli(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeProvider]:
    monkeypatch.setenv("TP_MODEL_MODE", "live")
    monkeypatch.delenv("TP_RULES_DIR", raising=False)
    provider = FakeProvider([text_response(OLGULAR)])
    gw = build_gateway(
        PgCallRecorder(engine), settings=GatewaySettings(), engine=engine, provider=provider
    )
    oracle_service.set_gateway_factory(lambda _e: gw)  # type: ignore[arg-type,return-value]
    yield provider
    oracle_service.set_gateway_factory(None)


def _bugs_modulu(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    cagrilar: list[uuid.UUID] = []
    mod = types.ModuleType("tp_core.features.bugs")

    def create_draft_from_failure(session: Session, failure_id: uuid.UUID) -> None:
        cagrilar.append(failure_id)

    mod.create_draft_from_failure = create_draft_from_failure  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tp_core.features.bugs", mod)
    return cagrilar


def _kur(engine: Engine) -> tuple[uuid.UUID, uuid.UUID, str]:
    """PO onaylı TPD-1 + onaylı tablo + onaylı C3 → (gereksinim, case, onaylı hash)."""
    h = content_hash(C3)
    with allow_state_write(), Session(engine) as s, s.begin():
        req = Requirement(
            kaynak="jira",
            jira_key="TPD-1",
            baslik="Kampanyalı sepet",
            aciklama="Kampanyalı üründe 6 al 1 bedava (7 adette 1 bedava)",
            kabul_kriterleri=["AC2: 7 adette 1 bedava"],
            kaynak_hash="k",
            durum="po_approved",
        )
        s.add(req)
        s.flush()
        tc = TestCase(
            id=uuid.uuid4(),
            requirement_id=req.id,
            sira_no=3,
            icerik=C3,
            icerik_hash=h,
            onaylanan_hash=h,
            durum="approved",
            ai_generated=True,
        )
        s.add(tc)
        s.add(
            KararTablosu(
                requirement_id=req.id,
                sira_no=1,
                icerik=TABLO,
                icerik_hash=content_hash(TABLO),
                onaylanan_hash=content_hash(TABLO),
                durum="approved",
                gereksinim_hash=content_hash_of(req),
            )
        )
        s.flush()
        return req.id, tc.id, h


def _oracle_kontrolu(engine: Engine, cid: uuid.UUID, h: str) -> CaseOracleKontrol:
    with session_scope() as s:
        oracle_service.kontrol_kuyruga_al(s, cid, h)
    sonuc = run_jobs(engine)
    assert [r.durum for r in sonuc] == ["done"], sonuc
    with Session(engine) as s:
        kayit = s.scalars(
            select(CaseOracleKontrol).where(CaseOracleKontrol.test_case_id == cid)
        ).one()
        s.expunge(kayit)
    return kayit


def _uretilen_test(engine: Engine, rid: uuid.UUID, cid: uuid.UUID, h: str) -> tuple[uuid.UUID, Any]:
    r = render_test(
        RenderInput(
            case_id=cid,
            case=C3,
            sira_no=3,
            story_key="TPD-1",
            test_key=None,
            case_hash=h,
            mode="replay",
            bundle_hash=None,
            mapping=ESLEME,
            dealers={},
        ),
        RULES,
    )
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(Script(id=sid, dosya_yolu=r.repo_path, icerik=r.content, platform="web"))
        s.flush()
        s.add(
            ScriptCodegen(
                script_id=sid,
                test_case_id=cid,
                requirement_id=rid,
                case_hash=h,
                story_key="TPD-1",
                sira_no=3,
            )
        )
    return sid, r


def _kirmizi_kosu(engine: Engine, kok: Path, sid: uuid.UUID, r: Any) -> uuid.UUID:
    """`// 6` uygulaması: 6 adette 1 bedava verir; test 0 bekler (Playwright raporu)."""
    satir = next(i for i, s in enumerate(r.content.splitlines(), 1) if "expectFreeQuantity(" in s)
    failure = {
        "type": "assertion",
        "message": "Error: expect(locator).toHaveText(expected) failed\n\n"
        'Locator: getByTestId(\'cart-line-free-P-001\')\nExpected: "0"\nReceived: "1"',
        "matcher": "toHaveText",
        "locator": "getByTestId('cart-line-free-P-001')",
        "expected": '"0"',
        "received": '"1"',
        "location": {"file": "pages/cart/cart.page.ts", "line": 39},
        "test_location": {"file": r.test_file, "line": satir},
        "step": {"title": 'Expect "toHaveText"', "path": ['Expect "toHaveText"']},
        "aria_snapshot": '- main:\n  - table "Sepetteki ürünler":\n    - cell: "1"',
        "aria_snapshot_scope": "page",
    }
    return kosu_kur(
        engine,
        kok,
        script_id=sid,
        testler=[
            KTest(
                "TPD-1 · C3 › 6 adet kampanyalı üründe bedava ürün verilmez @tp-uretilen",
                file=r.test_file,
                statuses=["unexpected"] * 3,
                failure=failure,
            )
        ],
    )


def test_oracle_kaydi_triagea_ulasir_c3_product_defect(
    engine: Engine,
    artefakt_kok: Path,
    monkeypatch: pytest.MonkeyPatch,
    olgu_modeli: FakeProvider,
) -> None:
    cagrilar = _bugs_modulu(monkeypatch)
    rid, cid, h = _kur(engine)

    kayit = _oracle_kontrolu(engine, cid, h)
    # Beklenen alandaki tutarlar bu tablonun kolonu değil (`ignored`): kontrol kısmen (012 review
    # 2); doğrulanmış karşılaştırmalar triage'da yine kullanılır.
    assert (kayit.sonuc, kayit.icerik_hash) == ("kismen", h)
    assert kayit.ayrintilar["kismen_nedeni"] == ["yok_sayilan"]
    assert len(olgu_modeli.requests) == 1  # gerçek kontrol işi modeli bir kez çağırdı
    [grup] = kayit.ayrintilar["gruplar"]
    assert grup["satir_id"] == "R2"
    assert {(k["alan"], k["case_degeri"], k["tablo_degeri"]) for k in grup["karsilastirmalar"]} == {
        ("steps[3].expected", "0", "0"),
        ("expected_result", "0", "0"),
    }

    sid, r = _uretilen_test(engine, rid, cid, h)
    run_id = _kirmizi_kosu(engine, artefakt_kok, sid, r)
    sonuc = classify_run(engine, run_id)

    with Session(engine) as s:
        [(f, ek)] = s.execute(
            select(Failure, FailureEk)
            .join(FailureEk, FailureEk.failure_id == Failure.id)
            .where(Failure.run_id == run_id)
        ).all()
    assert (f.sinif, f.alt_tur, f.karar_kaynagi, f.oneri_turu) == (
        "product_defect",
        None,
        "rule",
        "bug_draft",
    )
    assert ek.kural == "karar_tablosu" and f.ai_call_id is None
    [s_] = [x for x in f.eslesen_sinyaller if x["kod"].startswith("karar_tablosu_")]
    assert s_["kod"] == "karar_tablosu_uyumlu"
    assert s_["baslik"] == "Uygulama onaylı kurala aykırı (T1 · R2: adet 6 → bedava_adet 0)"
    assert "test beklentisi 0, gerçekleşen 1, tablo 0" in s_["aciklama"]
    assert TABLO["ad"] in s_["aciklama"]
    assert str(cid) in s_["kanit"] and h in s_["kanit"]
    assert sonuc["bug_taslagi_istenen"] == 1 and cagrilar == [f.id]


def test_kirmizi_baska_adimdaysa_inceltme_yok(
    engine: Engine,
    artefakt_kok: Path,
    monkeypatch: pytest.MonkeyPatch,
    olgu_modeli: FakeProvider,
) -> None:
    """Aynı hat; kırmızı S3'ün eylem çağrısında (`addToCart`), beklenen/gerçekleşen değerler
    S4'ün karşılaştırmasıyla tesadüfen aynı (0 / 1). Karşılaştırma başarısız adıma ait değil →
    karar tablosu kullanılmaz (kural `product_defect`, `karar_tablosu` değil; review O6)."""
    _bugs_modulu(monkeypatch)
    rid, cid, h = _kur(engine)
    _oracle_kontrolu(engine, cid, h)
    sid, r = _uretilen_test(engine, rid, cid, h)
    satir = next(i for i, s in enumerate(r.content.splitlines(), 1) if "addToCart(" in s)
    run_id = kosu_kur(
        engine,
        artefakt_kok,
        script_id=sid,
        testler=[
            KTest(
                "TPD-1 · C3",
                file=r.test_file,
                failure={
                    "type": "assertion",
                    "message": "Error: expect(locator).toHaveText(expected) failed\n\n"
                    'Expected: "0"\nReceived: "1"',
                    "matcher": "toHaveText",
                    "locator": "getByTestId('cart-badge-errors')",
                    "expected": '"0"',
                    "received": '"1"',
                    "location": {"file": "pages/catalog/catalog.page.ts", "line": 30},
                    "test_location": {"file": r.test_file, "line": satir},
                    "aria_snapshot": '- main:\n  - status: "1"',
                    "aria_snapshot_scope": "page",
                },
            )
        ],
    )
    classify_run(engine, run_id)
    with Session(engine) as s:
        [(f, ek)] = s.execute(
            select(Failure, FailureEk)
            .join(FailureEk, FailureEk.failure_id == Failure.id)
            .where(Failure.run_id == run_id)
        ).all()
    assert (f.sinif, ek.kural) == ("product_defect", "product_defect")
    assert not any(x["kod"].startswith("karar_tablosu") for x in f.eslesen_sinyaller)


def test_web_java_testi_java_kaynagi_olarak_eslenir(
    engine: Engine, olgu_modeli: FakeProvider
) -> None:
    """011 web + Java (Playwright for Java): üretilen test `script.platform = web`, `dil = java`;
    adım eşlemesi Java çağrı sözdizimiyle okunur (önceden yalnız Appium platformları Java
    sayılıyordu). Başarısız `expectFreeQuantity("P-001", 0)` satırı S4 + beklenen sonuca düşer."""
    from tp_core.features.codegen import platform as platformlar
    from tp_core.features.codegen.render import render_java_test
    from tp_core.features.triage.adim import hata_alanlari
    from tp_core.features.triage.service import (
        _test_kaynagi,
        _uretilen_testler,
        oracle_baglamlari,
    )
    from tp_core.models import Run

    rid, cid, h = _kur(engine)
    _oracle_kontrolu(engine, cid, h)
    r = render_java_test(
        RenderInput(
            case_id=cid,
            case=C3,
            sira_no=3,
            story_key="TPD-1",
            test_key=None,
            case_hash=h,
            mode="replay",
            bundle_hash=None,
            mapping=platformlar.java_eslemesi(ESLEME),
            dealers={},
        ),
        "web",
        RULES,
    )
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(Script(id=sid, dosya_yolu=r.repo_path, icerik=r.content, platform="web", dil="java"))
        s.flush()
        s.add(
            ScriptCodegen(
                script_id=sid,
                test_case_id=cid,
                requirement_id=rid,
                case_hash=h,
                story_key="TPD-1",
                sira_no=3,
            )
        )
    with Session(engine) as s:
        baglam = oracle_baglamlari(s, [cid])
        adaylar = _uretilen_testler(s, baglam)[cid]
        kaynak = _test_kaynagi(adaylar, Run(script_id=sid), None)
    assert kaynak is not None and kaynak[1] is True
    satir = next(i for i, x in enumerate(r.content.splitlines(), 1) if "expectFreeQuantity(" in x)
    alanlar = hata_alanlari(C3, kaynak=kaynak[0], satir=satir, java=kaynak[1], beklenen='"0"')
    assert alanlar == frozenset({"steps[3].expected", "expected_result"})
