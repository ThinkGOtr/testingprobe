"""012 uçtan uca REPLAY: demo story TPD-1 (ana yol `f2-kod-hatasi`) üzerinde F1–F5 zinciri.

PO onaylı TPD-1 → AI karar tablosu taslağı (decision_table_draft REPLAY) → analist PO'ya gönderir
→ PO T1/T2 ve ilişkiyi onaylar → case üretimi (case_generation REPLAY, senaryo golden'ı) → tablo
onayı kontrolü tetikler (case_facts REPLAY) → onay kapısı (C3 "6 adette bedava yok" uyumlu;
düzeltilmiş yüksek riskli C5 uyuşmaz → 422 → istisna) → beklenti doğruluğu metriği (gereksinim
ve Kontrol Kulesi) → onaylı ilişkiden metamorfik ek case (metriğe girmez) → C3'ün `// 6`
uygulamasına karşı kırmızı koşusu (Playwright rapor fikstürü) `classify_run`'da `product_defect` +
`karar_tablosu_uyumlu` (oracle kaydı yukarıdaki gerçek kontrolden gelir).

Canlı model yoktur: tüm çağrılar REPLAY golden'larıdır; yalnız düzeltilmiş C5 içeriğinin değer
çıkarması sahte modeldir (golden'ı yoktur, REPLAY-MISS nötr çıktı verirdi).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from tests.unit.features.cases.helpers import latest_cases, login, run_jobs
from tests.unit.features.oracle import tpd1
from tests.unit.features.triage.conftest import (  # noqa: F401  (pytest fikstürleri)
    KTest,
    artefakt_kok,
    kosu_kur,
    toolchain,
    triage_env,
)
from tp_core.audit import PgCallRecorder
from tp_core.features.cases import service as cases_service
from tp_core.features.karar_tablosu import service as kt_service
from tp_core.features.oracle import service as oracle_service
from tp_core.features.triage import classify_run
from tp_core.gateway import build_gateway
from tp_core.gateway.config import GatewaySettings
from tp_core.gateway.matching import untrusted_blocks
from tp_core.models import (
    AiCall,
    AuditEvent,
    CaseOracleKontrol,
    Failure,
    TestCase,
    TestResult,
    session_scope,
)

GEREKCE = "PO ile görüşüldü: kampanya dışı istisna, tablo güncellenecek."
# Analistin düzelttiği C5: toplam 150 TL iken "uyarı görünmez" (T2: 750 altında uyarı görünür).
C5_YANLIS_S4 = (
    'Toplam 150,00 TL; "Minimum sipariş tutarı 750,00 TL" uyarısı görünmez ve "Siparişi onayla" '
    "butonu aktiftir"
)


class OracleGecidi:
    """REPLAY geçidi; yalnız düzeltilmiş C5 içeriğinin `case_facts` çağrısı sahte modeldir."""

    def __init__(self, gw: Any) -> None:
        self.gw = gw
        self.rules_dir = gw.rules_dir
        self.sahte_cagri = 0

    def call(self, purpose: str, bundle: str, messages: Any, schema: Any, **kw: Any) -> Any:
        bloklar = untrusted_blocks([m.model_dump(mode="json") for m in messages])
        govde = next((b.body for b in bloklar if b.source.startswith("case:")), None)
        case = json.loads(govde) if govde else {}
        adimlar = case.get("steps") or []
        if purpose == "case_facts" and len(adimlar) > 3 and adimlar[3]["expected"] == C5_YANLIS_S4:
            self.sahte_cagri += 1
            s4 = "steps[3].expected"
            o = lambda c, v, f, q: {"column": c, "value": v, "field": f, "quote": q}  # noqa: E731
            assert case["preconditions"][1] == "Sepette kampanyalı ürün yok"
            cikti = {
                "groups": [
                    {
                        "table_ref": "T2",
                        "inputs": [
                            o(
                                "kampanyali_sepet",
                                False,
                                "preconditions[1]",
                                case["preconditions"][1],
                            ),
                            o("sepet_tutari", "150.00", s4, "150,00 TL"),
                        ],
                        "expected": [
                            o(
                                "minimum_uyarisi",
                                False,
                                s4,
                                '"Minimum sipariş tutarı 750,00 TL" uyarısı görünmez',
                            )
                        ],
                    }
                ]
            }
            return SimpleNamespace(output=cikti, call_id=None, mode="live")
        return self.gw.call(purpose, bundle, messages, schema, **kw)


@pytest.fixture
def gecit(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[OracleGecidi]:
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TP_REPLAY_STRICT", raising=False)
    monkeypatch.delenv("TP_RULES_DIR", raising=False)
    gw = build_gateway(PgCallRecorder(engine), settings=GatewaySettings(), engine=engine)
    oracle = OracleGecidi(gw)
    cases_service.set_gateway_factory(lambda _e: gw)
    kt_service.set_gateway_factory(lambda _e: gw)
    oracle_service.set_gateway_factory(lambda _e: oracle)  # type: ignore[arg-type,return-value]
    yield oracle
    cases_service.set_gateway_factory(None)
    kt_service.set_gateway_factory(None)
    oracle_service.set_gateway_factory(None)


def _rol(api: TestClient, user: Any) -> TestClient:
    api.cookies.clear()
    login(api, user)
    return api


def _ok(r: Any, kod: int = 200) -> Any:
    assert r.status_code == kod, r.text
    return r.json()


def _by_sira(cases: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {c["sira_no"]: c for c in cases if c["uretim_no"] == 1}


def test_tpd1_kalite_dogrulama_uctan_uca(
    api: TestClient,
    engine: Engine,
    make_user,
    make_requirement,
    gecit: OracleGecidi,
    triage_env: Any,  # noqa: F811  (sahte toolchain, artefakt kökü)
    artefakt_kok: Any,  # noqa: F811
) -> None:
    beyan = tpd1.taslak_golden()["input_match"]
    rid = make_requirement(
        "TPD-1",
        "Kampanyalı sepet ve sipariş onayı",
        beyan["contains"][0],
        beyan["acceptance_criteria"],
    )
    analist, po = make_user("analyst"), make_user("po")

    # 1) AI taslağı (REPLAY golden) → iki tablo + bir ilişki, taslak.
    _rol(api, analist)
    _ok(api.post(f"/requirements/{rid}/decision-tables/draft"), 202)
    sonuc = run_jobs(engine)
    assert [s.durum for s in sonuc] == ["done"] and sonuc[0].deger["mode"] == "replay"
    liste = _ok(api.get(f"/requirements/{rid}/decision-tables"))
    t1, t2 = liste["tablolar"]
    [iliski] = liste["iliskiler"]
    assert t1["icerik"] == tpd1.T1 and t2["icerik"] == tpd1.T2  # oracle şeridiyle aynı tablolar
    assert (t1["durum"], t1["ai_generated"], t1["uretim_modu"]) == ("draft", True, "replay")
    assert iliski["karar_tablosu_id"] == t1["id"]

    # 2) Case üretimi (tablolar henüz onaysız: kontrol işi açılmaz).
    _ok(api.post(f"/requirements/{rid}/generate-cases"), 202)
    run_jobs(engine, limit=100)
    cases = _by_sira(latest_cases(api, rid))
    assert len(cases) == 10 and all(c["oracle"] is None for c in cases.values())
    assert cases[3]["icerik"]["title"] == "6 adet kampanyalı üründe bedava ürün verilmez"

    # 3) Analist PO'ya gönderir, PO onaylar (görülen hash ile) → oracle.check_requirement.
    for yol, n in (("decision-tables", t1), ("decision-tables", t2), ("relations", iliski)):
        _rol(api, analist)
        _ok(api.post(f"/{yol}/{n['id']}/submit"))
        _rol(api, po)
        r = _ok(api.post(f"/{yol}/{n['id']}/approve", json={"icerik_hash": n["icerik_hash"]}))
        assert r["durum"] == "approved" and r["onaylayan"] == po.kullanici_adi
    run_jobs(engine, limit=100)

    # 4) Story tablolarıyla dürüst sonuçlar (C3 = demo'nun defect adayı: tabloyla aynı).
    _rol(api, analist)
    cases = _by_sira(latest_cases(api, rid))
    sonuclar = {n: (c["oracle"] or {}).get("sonuc") for n, c in cases.items()}
    assert sonuclar == tpd1.BEKLENEN_SONUC_ANA_YOL
    c3 = cases[3]["oracle"]
    assert {(k["column"], k["case_degeri"], k["tablo_degeri"]) for k in c3["karsilastirmalar"]} == {
        ("bedava_adet", "0", "0"),
        ("indirim", "0.00", "0"),
    }
    assert [k["column"] for k in cases[2]["oracle"]["karsilastirilamayan"]] == [
        "indirim",
        "indirim",
    ]
    with session_scope() as s:
        modlar = s.scalars(select(AiCall.mod).where(AiCall.amac == "case_facts")).all()
    assert sorted(modlar) == ["replay"] * 7  # C2–C6, C9, C10; AC1/AC4/AC5 modele gitmez

    # 5) Onay kapısı: uyumlu yüksek riskli C3 serbest.
    r = _ok(
        api.post(
            f"/cases/{cases[3]['id']}/decision",
            json={"karar": "approve", "icerik_hash": cases[3]["icerik_hash"]},
        )
    )
    assert r["durum"] == "approved" and not any("tablo" in u for u in r["uyarilar"])

    # 6) Analist C5'i (yüksek risk) yanlış düzeltir: önerilen içerik kontrol edilir → uyumsuz.
    c5 = cases[5]
    yanlis = json.loads(json.dumps(c5["icerik"]))
    yanlis["steps"][3]["expected"] = C5_YANLIS_S4
    yanlis["expected_result"] = "Minimum sipariş uyarısı gösterilmez ve sipariş onaylanabilir"
    karar = {"karar": "edit", "icerik_hash": c5["icerik_hash"], "icerik": yanlis}
    r = api.post(f"/cases/{c5['id']}/decision", json=karar)
    assert r.status_code == 409 and r.json()["kod"] == "oracle_bekleniyor"  # V3
    h = _ok(api.post(f"/cases/{c5['id']}/oracle-check", json={"icerik": yanlis}), 202)[
        "icerik_hash"
    ]
    run_jobs(engine)
    assert gecit.sahte_cagri == 1
    o = _ok(api.get(f"/cases/{c5['id']}/oracle", params={"icerik_hash": h}))["oracle"]
    assert o["sonuc"] == "uyumsuz"
    assert o["karsilastirmalar"][0]["tablo_degeri"] is True
    r = api.post(f"/cases/{c5['id']}/decision", json=karar)
    assert r.status_code == 422 and r.json()["kod"] == "oracle_uyumsuz"
    # 7) Gerekçeli istisna: onaylanır, denetime ve sayaca düşer.
    r = _ok(
        api.post(f"/cases/{c5['id']}/decision", json={**karar, "oracle_istisna_gerekce": GEREKCE})
    )
    assert r["durum"] == "approved"
    with session_scope() as s:
        ev = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "oracle.exception")).one()
        assert ev.ozet["gerekce"] == GEREKCE and ev.aktor == analist.kullanici_adi

    # 8) Beklenti doğruluğu: AI içeriği üzerinden (C5'in AI içeriği uyumluydu; düzeltme sayılmaz).
    beklenen_metrik = {
        "oran": 1.0,
        "uyumlu": 7,
        "uyumsuz": 0,
        "kapsam_disi": 3,
        "kontrol_edilemedi": 0,
        "istisna": 1,
        "kapsam_orani": 0.7,
    }
    m = _ok(api.get(f"/requirements/{rid}/case-metrics"))["beklenti_dogrulugu"]
    assert {k: v for k, v in m.items() if k != "kaynak"} == beklenen_metrik
    kule = _ok(api.get("/control-tower"))
    assert kule["beklenti_dogrulugu"] == beklenen_metrik
    assert kule["kaynaklar"]["beklenti_dogrulugu"] == m["kaynak"]
    assert kule["hata_yakalama"] is None

    # 9) Onaylı ilişkiden ek case: 7'nin katı olan C2 ve C10 türer; C3, C4 ön koşulu sağlamaz.
    t = _ok(api.post(f"/requirements/{rid}/metamorphic-cases", json={"iliski_id": iliski["id"]}))
    kaynak_sira = {c["id"]: n for n, c in cases.items()}
    assert sorted(kaynak_sira[x["kaynak_case_id"]] for x in t["turetilen"]) == [2, 10]
    assert {kaynak_sira[x["kaynak_case_id"]]: x["sonuc"] for x in t["atlanan"]} == {
        3: "iliski_gecersiz",
        4: "iliski_gecersiz",
    }
    with session_scope() as s:
        turev = s.get(
            TestCase,
            uuid.UUID(
                next(x["case_id"] for x in t["turetilen"] if kaynak_sira[x["kaynak_case_id"]] == 2)
            ),
        )
        assert turev.durum == "draft" and turev.ai_generated is False
        assert "metamorfik" in turev.icerik["tags"]
        assert turev.icerik["steps"][2]["data"] == "P-001 × 14"
        assert "adet 14, bedava adet 2" in turev.icerik["steps"][3]["expected"]
        assert "indirim 50,00 TL" in turev.icerik["steps"][3]["expected"]
        # Bilinen sınır: tabloda kolonu olmayan ara toplam/toplam kaynaktaki değerde kalır.
        assert "ara toplam 175,00 TL" in turev.icerik["steps"][3]["expected"]
        turev_id = turev.id
    run_jobs(engine, limit=50)
    with session_scope() as s:
        k = s.scalars(
            select(CaseOracleKontrol).where(CaseOracleKontrol.test_case_id == turev_id)
        ).one()
        assert k.sonuc == "kontrol_edilemedi" and k.ai_icerik is False  # golden'ı yok: nötr
    m2 = _ok(api.get(f"/requirements/{rid}/case-metrics"))["beklenti_dogrulugu"]
    assert {k: v for k, v in m2.items() if k != "kaynak"} == beklenen_metrik  # türetilen sayılmaz

    # 10) Triage: onaylı C3'ün testi `// 6` uygulamasında kırmızı (S4'te bedava 0 beklenir, 1
    # gelir). Oracle kaydı adım 3'teki gerçek kontrolün kaydıdır; `classify_run` onu okur.
    c3_id = uuid.UUID(cases[3]["id"])
    run_id = kosu_kur(
        engine,
        artefakt_kok,
        testler=[
            KTest(
                "TPD-1 C3 › 6 adet kampanyalı üründe bedava ürün verilmez",
                file="tests/sepet/kampanya.spec.ts",
                statuses=["unexpected"] * 3,
                failure={
                    "type": "assertion",
                    "message": "Error: expect(locator).toHaveText(expected) failed\n\n"
                    "Locator: getByTestId('cart-line-free-P-001')\n"
                    'Expected: "0"\nReceived: "1"',
                    "matcher": "toHaveText",
                    "locator": "getByTestId('cart-line-free-P-001')",
                    "expected": '"0"',
                    "received": '"1"',
                    "step": {
                        "title": 'Expect "toHaveText"',
                        "path": ["S4 — Üst menüden sepete git", 'Expect "toHaveText"'],
                    },
                    "aria_snapshot": '- main:\n  - cell: "1"',
                    "aria_snapshot_scope": "page",
                },
            )
        ],
    )
    with session_scope() as s:
        s.execute(update(TestResult).where(TestResult.run_id == run_id).values(test_case_id=c3_id))
    classify_run(engine, run_id)
    with session_scope() as s:
        f = s.scalars(select(Failure).where(Failure.run_id == run_id)).one()
        assert (f.sinif, f.alt_tur, f.karar_kaynagi, f.oneri_turu) == (
            "product_defect",
            None,
            "rule",
            "bug_draft",
        )
        [sinyal] = [x for x in f.eslesen_sinyaller if str(x["kod"]).startswith("karar_tablosu_")]
    assert sinyal["kod"] == "karar_tablosu_uyumlu"
    assert "test beklentisi 0, gerçekleşen 1, tablo 0" in sinyal["aciklama"]
    assert tpd1.T1["ad"] in sinyal["aciklama"]
    assert sinyal["baslik"].startswith("Uygulama onaylı kurala aykırı (T1 · R2: adet 6")
    assert sinyal["baslik"].endswith("→ bedava_adet 0)")
