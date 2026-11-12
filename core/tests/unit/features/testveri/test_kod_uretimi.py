"""Kod üretimi: atıflı case çözülmüş gider (REPLAY eşleşir), `veri_izi`, uyarı, ret (013 §3.3)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.cases.helpers import login, run_jobs
from tests.unit.features.codegen.conftest import golden_cases, tpd1_acs
from tp_core.audit import content_hash
from tp_core.features.codegen import service as codegen_service
from tp_core.features.testveri import atif, service
from tp_core.models import Requirement, Script, TestCase, case_id, session_scope
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.otomasyon_feature import TestVerisi
from tp_core.workflow.service import SYSTEM, content_hash_of, record_approval, transition

from .conftest import DEMO_PAROLA


@pytest.fixture
def atifli(engine: Engine, make_requirement: Any, make_user: Any, katalog: int) -> dict:
    """PO onaylı TPD-1 + katalogla eşlenmiş (store_cases gibi) golden case'ler, analist onaylı."""
    rid = make_requirement(
        "TPD-1",
        "Kampanyalı sepet ve sipariş onayı",
        "Bayi, katalogdan ürünleri sepete ekleyip kampanya indirimiyle siparişini "
        "onaylayabilmelidir.",
        tpd1_acs(),
    )
    analist = make_user("analyst")
    with session_scope() as s:
        req = s.get(Requirement, rid)
        transition(s, req, "generating", SYSTEM, "po_approved")
        transition(s, req, "cases_ready", SYSTEM, "generating")
    ids: dict[int, uuid.UUID] = {}
    for n, ham in enumerate(golden_cases(), start=1):
        with session_scope() as s:
            icerik = service.case_esle(s, ham)
            req = s.get(Requirement, rid)
            tc = TestCase(
                id=case_id(req, n, 1),
                requirement_id=rid,
                sira_no=n,
                uretim_no=1,
                icerik=icerik,
                icerik_hash=content_hash(icerik),
                uretim_modu="replay",
            )
            s.add(tc)
            s.flush()
            record_approval(s, tc, analist, "approve", beklenen_hash=content_hash_of(tc))
            transition(s, tc, "approved", analist, "draft")
            ids[n] = tc.id
    return {"requirement_id": rid, "cases": ids, "analist": analist}


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    u = make_user("engineer")
    login(api, u)
    return u


def _uret(api: TestClient, cid: uuid.UUID) -> Any:
    return api.post("/code/generate", json={"case_ids": [str(cid)]})


def _script(sid: str) -> tuple[Script, ScriptCodegen]:
    with session_scope() as s:
        return s.get(Script, uuid.UUID(sid)), s.get(ScriptCodegen, uuid.UUID(sid))


def test_atifli_case_cozulmus_gider_replay_eslesir_veri_izi(
    api: TestClient, engine: Engine, codegen: Any, atifli: dict, muhendis: Any
) -> None:
    cid = atifli["cases"][2]
    with session_scope() as s:
        icerik = dict(s.get(TestCase, cid).icerik)
    atiflar = atif.case_atiflari(icerik)
    assert "bayi.bayi1.kullanici_adi" in atiflar and "urun.p_001.kod" in atiflar
    assert "P-001" not in str(icerik["steps"])  # case metni gerçekten atıflı

    r = _uret(api, cid)
    assert r.status_code == 202, r.text
    sid = r.json()["script_ids"][0]
    run_jobs(engine)
    sc, cg = _script(sid)
    # REPLAY golden'ı (input_match.case_text) çözülmüş metinle eşleşti: PR açıldı.
    assert sc.durum == "pr_open", cg.engel_nedeni
    assert cg.uretim_modu == "replay"
    with session_scope() as s:
        degerler, _ = service.cozum_degerleri(s)
    assert cg.veri_izi == {a: service.deger_ozeti(degerler[a]) for a in atiflar}
    assert 'await cartPage.expectFreeQuantity("P-001", 1);' in sc.icerik
    assert "{veri:" not in sc.icerik
    # K19: gizli değer kodda ortamdan okunur; PR/commit içeriğinde düz parola yok.
    assert 'await loginPage.login("bayi1", process.env.TP_TESTVERI_DEMO_PAROLA);' in sc.icerik
    assert DEMO_PAROLA not in sc.icerik
    pr = codegen.forge.find_open_pr(f"tp/case-{cid}")
    assert pr is not None and "{veri:" not in pr.body
    assert DEMO_PAROLA not in pr.body and DEMO_PAROLA not in pr.title

    liste = api.get("/scripts").json()
    assert liste[0]["veri_izi"] == cg.veri_izi
    assert liste[0]["veri_degisti"] is False and liste[0]["veri_degisen"] == []
    # API (adım argümanı / ham çıktı / eşleme argümanları) bilinen gizli değeri göstermez.
    detay = api.get(f"/scripts/{sid}")
    assert DEMO_PAROLA not in detay.text and "•••" in detay.text
    with engine.connect() as c:
        adimlar = c.execute(
            text("SELECT arguman::text, ozet, ham FROM script_adim WHERE script_id = :s"),
            {"s": sid},
        ).all()
    assert adimlar and DEMO_PAROLA not in str(adimlar)
    # Aynı içerik + aynı veri değeri: açık PR varken yeniden üretim atlanır.
    tekrar = _uret(api, cid).json()
    assert tekrar["durum"] == "none" and tekrar["sonuclar"][0]["durum"] == "pr_acik"

    # Yalnız açıklama değişir (değer aynı): "veri değişti" sayılmaz, açık PR atlatmaz.
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "urun.p_001.kod")).one()
        service.guncelle(s, k.id, {"aciklama": "Kampanyalı ürün"}, 1, "analist")
    d = api.get(f"/scripts/{sid}").json()
    assert d["veri_degisti"] is False and d["veri_degisen"] == []
    assert _uret(api, cid).json()["sonuclar"][0]["durum"] == "pr_acik"

    # Değer değişir: uyarı (K10); aynı değere geri dönünce uyarı kalkar (değer özeti).
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "urun.p_001.kod")).one()
        service.guncelle(s, k.id, {"deger": "P-001X"}, 2, "analist")
    d = api.get(f"/scripts/{sid}").json()
    assert d["veri_degisti"] is True and d["veri_degisen"] == ["urun.p_001.kod"]
    assert api.get("/scripts").json()[0]["veri_degisen"] == ["urun.p_001.kod"]
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "urun.p_001.kod")).one()
        service.guncelle(s, k.id, {"deger": "P-001"}, 3, "analist")
    d = api.get(f"/scripts/{sid}").json()
    assert d["veri_degisti"] is False


def test_sir_tanimsiz_ya_da_silinmis_anahtar_uretimi_reddeder(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    atifli: dict,
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Parolaya atıf yapan case (golden'larda "bayi1 / Demo123!").
    with session_scope() as s:
        cid = next(
            c
            for c in atifli["cases"].values()
            if "ortak.demo_parola" in atif.case_atiflari(s.get(TestCase, c).icerik)
        )
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI)
    r = _uret(api, cid)
    assert r.status_code == 409
    assert "Test verisi sırrı tanımsız: ortak.demo_parola" in r.json()["detail"]

    # Silinmiş (katalogda olmayan) anahtar.
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "ortak.demo_parola")).one()
        k.silindi = True
    r = _uret(api, cid)
    assert r.status_code == 409
    assert "Katalogda olmayan test verisi anahtarı: ortak.demo_parola" in r.json()["detail"]
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "ortak.demo_parola")).one()
        k.silindi = False

    with session_scope() as s:
        tanim = s.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'script_codegen_engel_ck'"
            )
        ).scalar_one()
    if "test_verisi" not in tanim:
        pytest.skip("engel_turu CHECK'inde test_verisi yok (D3 migration 0030 birleşince koşar)")
    # İstekten sonra sır kalkarsa iş üretimi durdurur (Türkçe neden, insana).
    monkeypatch.setenv(service.DEMO_PAROLA_SIRRI, DEMO_PAROLA)
    sid = _uret(api, cid).json()["script_ids"][0]
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI)
    run_jobs(engine)
    sc, cg = _script(sid)
    # 013 K19: ayrı engel türü (model hatası sayılmaz).
    assert sc.durum == "failed" and cg.engel_turu == "test_verisi"
    assert "test verisi sırrı tanımsız: ortak.demo_parola" in cg.engel_nedeni.lower()
    assert "test_verisi" not in codegen_service.MODEL_ENGELLERI

    # Silinmiş (katalogda olmayan) anahtar.
    monkeypatch.setenv(service.DEMO_PAROLA_SIRRI, DEMO_PAROLA)
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "ortak.demo_parola")).one()
        k.silindi = True
    r = _uret(api, cid)
    assert r.status_code == 409
    assert "katalogda olmayan test verisi anahtarı: ortak.demo_parola" in r.json()["detail"].lower()


def test_negatif_kontrol_cozulmeden_giderse_replay_eslesmez(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    atifli: dict,
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Önceki testin anlamı: atıflı metin ajana çözülmeden gitseydi REPLAY golden'ı eşleşmezdi."""
    monkeypatch.setattr(service, "case_coz", lambda _s, icerik: (dict(icerik), {}))
    sid = _uret(api, atifli["cases"][2]).json()["script_ids"][0]
    run_jobs(engine)
    sc, cg = _script(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "replay_miss"
