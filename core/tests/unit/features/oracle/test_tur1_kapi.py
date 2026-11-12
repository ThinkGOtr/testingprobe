"""Review turu 1 (012 §13) — kapı girdileri (V11), istisnalar (V10, K10), işler ve sinyaller.

Gerçek Postgres; model çağrısı yok (sahte `olgu_modeli` ya da elle kontrol kaydı). Karşı örnekler
review dosyalarından: düzeltmede riski / AC ref'ini düşürerek kapıdan kaçma, kalıcı 409, sınırsız
`/oracle-check`, onaydan sonra onaylanan tablonun sessiz kalması.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.audit import content_hash
from tp_core.features.cases import service as cases_service
from tp_core.features.control_tower import service as ct
from tp_core.features.oracle import kapi, service
from tp_core.models import AuditEvent, OracleIstisna, Requirement, TestCase, session_scope
from tp_core.workflow.jobs import JobContext
from tp_core.workflow.service import transition

from ..cases.helpers import latest_cases, login, run_jobs
from .helpers import BASIT, basit_case, kayit_yaz, tablo_degistir, tablo_ekle, uyumsuz_ayrinti
from .test_oracle_db import UZUN_GEREKCE, _karar, _kayitlar


def _denetim(eylem: str) -> list[AuditEvent]:
    with session_scope() as s:
        rows = s.scalars(select(AuditEvent).where(AuditEvent.eylem == eylem)).all()
        s.expunge_all()
        return list(rows)


def _isler(engine: Engine, tur: str) -> list[Any]:
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT id, durum, yuk, idempotency_key FROM job WHERE tur = :t ORDER BY olusturma"
            ),
            {"t": tur},
        ).all()


# ------------------------------------------------------------------ V11: risk ve AC düşürme


def test_riski_dusuren_duzeltme_kapidan_kacamaz(api: TestClient, engine: Engine, kur) -> None:
    """Güvenlik 1 / test K1: high → medium düzeltmesi uyuşmazlıkta yine 422 ve `oracle.dusurme`."""
    k = kur([basit_case(toplam="40,00")], tablo_once=True, olgu_sayisi=10)
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["sonuc"] == "uyumsuz"
    dusuk = basit_case(toplam="45,00", risk="medium")  # yine yanlış, risk düşürülmüş
    r = api.post(f"/cases/{c['id']}/oracle-check", json={"icerik": dusuk})
    assert r.status_code == 202
    run_jobs(engine)
    r = _karar(api, c, karar="edit", icerik=dusuk)
    assert r.status_code == 422 and r.json()["kod"] == "oracle_uyumsuz", r.text
    ev = _denetim("oracle.dusurme")[-1]
    assert ev.ozet["risk"] == {"once": "high", "sonra": "medium", "taban": ["high"]}
    # Gerekçeyle geçer (istisna yolu).
    r = _karar(
        api,
        c,
        karar="edit",
        icerik=dusuk,
        oracle_istisna_gerekce=UZUN_GEREKCE,
        oracle_istisna_turu="uyumsuz",
    )
    assert r.status_code == 200, r.text


def test_ac_refini_silen_duzeltme_kapsami_dusurmez(api: TestClient, engine: Engine, kur) -> None:
    """Güvenlik 2 / bağımsızlık K2: AC1'i silip AC2 yazmak tabloyu kapsam dışına atmaz; kapsayan
    tablolar saklı ∪ gönderilen ref'lerden hesaplanır, kontrol de bu birleşimle yapılır."""
    k = kur([basit_case(toplam="40,00", risk="medium")], tablo_once=True, olgu_sayisi=10)
    c = latest_cases(api, k["rid"])[0]
    kacak = basit_case(toplam="40,00", risk="medium", acceptance_criteria_refs=["AC2"])
    r = _karar(api, c, karar="edit", icerik=kacak)
    # Orta risk ama düşürme: zorunlu kapı → kontrol yok → 409.
    assert r.status_code == 409 and r.json()["kod"] == "oracle_bekleniyor", r.text
    [is_] = [j for j in _isler(engine, service.CHECK_CASE_JOB) if j.durum == "queued"]
    assert is_.yuk["ac_refs"] == ["AC1", "AC2"]
    run_jobs(engine)
    r = _karar(api, c, karar="edit", icerik=kacak)
    assert r.status_code == 422 and r.json()["kod"] == "oracle_uyumsuz", r.text
    ev = _denetim("oracle.dusurme")[-1]
    assert [t["id"] for t in ev.ozet["dusen_tablolar"]] == [str(k["tid"])]
    assert ev.ozet["risk"] is None


def test_ai_ozgun_riski_yuksekse_kapı_zorunlu(api: TestClient, engine: Engine, kur) -> None:
    """Risk = max(saklı, AI özgün, gönderilen): AI high yazmış, analist önce medium'a düzeltmiş;
    sonraki onayda kayıt yoksa yine 409 (yüksek)."""
    k = kur([basit_case(toplam="30,00")], olgu_sayisi=10)
    c = latest_cases(api, k["rid"])[0]
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        assert kapi.dogrulama.yuksek_risk_mi(tc.icerik)
    orta = basit_case(toplam="30,00", risk="medium")
    r = _karar(api, c, karar="edit", icerik=orta)
    assert r.status_code == 409  # gönderilen orta ama saklı/AI yüksek


def test_v3_priority_p1_yuksek_risk_sayilir() -> None:
    assert kapi.dogrulama.yuksek_risk_mi({"priority": "P1"})
    assert not kapi.dogrulama.yuksek_risk_mi({"priority": "P2", "risk": "medium"})
    assert kapi.dogrulama.yuksek_risk_mi({"risk": "HIGH"})


# ------------------------------------------------------------------ istisna kuralları (V10)


@pytest.mark.parametrize(
    ("gerekce", "gecerli"),
    [
        ("....................", False),  # 20 nokta
        ("1234567890 123456789 abc", False),  # 3 harf
        ("a b c d e f g h i j k", True),  # 21 karakter, 11 harf
        ("PO onayı var, tablo yanlış", True),
    ],
)
def test_gerekce_kurali(gerekce: str, gecerli: bool) -> None:
    assert (kapi.gerekce_hatasi(gerekce) is None) is gecerli


def test_istisna_append_only_ve_yeniden_kullanim(api: TestClient, engine: Engine, kur) -> None:
    """İstisna `oracle_istisna`'ya eklenir; taslağa al + yeniden onay aynı tablolarla gerekçe
    istemez (portal görünümüyle aynı, test S1); tablo değişince istisna geçersiz olur."""
    k = kur([basit_case(toplam="40,00")])
    c = latest_cases(api, k["rid"])[0]
    cid = uuid.UUID(c["id"])
    kayit_yaz(cid, "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
    r = _karar(
        api,
        c,
        karar="approve",
        oracle_istisna_turu="uyumsuz",
        oracle_istisna_gerekce="1234567890 123456789 abc",
    )
    assert r.status_code == 422 and "10 harf" in r.json()["detail"]
    assert (
        _karar(
            api,
            c,
            karar="approve",
            oracle_istisna_turu="uyumsuz",
            oracle_istisna_gerekce=UZUN_GEREKCE,
        ).status_code
        == 200
    )
    assert _karar(api, c, karar="reopen").status_code == 200
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["istisna"]["gecerli"] is True
    r = _karar(api, c, karar="approve")
    assert r.status_code == 200, r.text
    with session_scope() as s:
        assert len(s.scalars(select(OracleIstisna)).all()) == 1
    # tp_app istisnayı güncelleyemez / silemez (append-only).
    with engine.connect() as conn:
        haklar = conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'tp_app' AND table_name = 'oracle_istisna'"
            )
        ).scalars()
        assert set(haklar) == {"SELECT", "INSERT"}
    m = api.get(f"/requirements/{k['rid']}/case-metrics").json()["beklenti_dogrulugu"]
    assert m["istisna"] == 1  # aynı case'in tekrar onayı sayacı şişirmez


# ------------------------------------------------------------------ işler


def test_basarisiz_is_anahtari_onayi_kilitlemez(api: TestClient, engine: Engine, kur) -> None:
    """Mimari 4: kapının açtığı iş `failed` olursa sonraki deneme yeni iş açar (kalıcı 409 yok)."""
    k = kur([basit_case(toplam="30,00")], olgu_sayisi=10)
    c = latest_cases(api, k["rid"])[0]
    assert _karar(api, c, karar="approve").status_code == 409
    [is_] = _isler(engine, service.CHECK_CASE_JOB)
    with engine.begin() as conn:
        conn.execute(text("UPDATE job SET durum = 'failed' WHERE id = :i"), {"i": is_.id})
    assert _karar(api, c, karar="approve").status_code == 409
    isler = _isler(engine, service.CHECK_CASE_JOB)
    assert len(isler) == 2 and isler[1].idempotency_key == f"{is_.idempotency_key}:yeniden1"
    run_jobs(engine)
    assert _karar(api, c, karar="approve").status_code == 200


def test_edit_sonrasi_yeni_hash_kontrol_kuyruğunda(api: TestClient, engine: Engine, kur) -> None:
    """Mimari 5: orta riskte kapı kayıt istemez; düzeltme aynı işlemde yeni hash'i kuyruğa alır."""
    k = kur([basit_case(toplam="30,00", risk="medium")], olgu_sayisi=10)
    c = latest_cases(api, k["rid"])[0]
    yeni = basit_case(adet=4, toplam="40,00", risk="medium")
    assert _karar(api, c, karar="edit", icerik=yeni).status_code == 200
    yukler = [j.yuk for j in _isler(engine, service.CHECK_CASE_JOB)]
    assert {
        "case_id": c["id"],
        "requirement_id": str(k["rid"]),
        "icerik_hash": content_hash(yeni),
    } in yukler
    run_jobs(engine)
    assert latest_cases(api, k["rid"])[0]["oracle"]["sonuc"] == "uyumlu"


def test_gereksinim_isi_birlestirilir_ve_yayinli_case_kontrol_edilir(
    api: TestClient, engine: Engine, kur
) -> None:
    """Mimari 14 ve 6: bekleyen tek `check_requirement`; `published` case de kontrol edilir."""
    k = kur([basit_case(toplam="30,00", risk="low")], olgu_sayisi=10)
    c = latest_cases(api, k["rid"])[0]
    with session_scope() as s:
        s.execute(text("UPDATE test_case SET durum = 'published' WHERE id = :i"), {"i": c["id"]})
    with session_scope() as s:
        a = service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "tablo_onaylandi")
        b = service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "tablo_degisti")
    assert a == b
    [is_] = [j for j in _isler(engine, service.CHECK_REQUIREMENT_JOB) if j.durum == "queued"]
    assert is_.yuk["nedenler"] == ["tablo_onaylandi", "tablo_degisti"]
    run_jobs(engine)
    assert [r.sonuc for r in _kayitlar(c["id"])] == ["uyumlu"]


def test_case_yazimi_kancasi_tek_yerde(api: TestClient, engine: Engine, kur) -> None:
    """Mimari 7: `store_cases` (IDE/MCP `submit_drafts` de onu çağırır) kontrol işini açar."""
    k = kur([basit_case(toplam="30,00", risk="low")], olgu_sayisi=10)
    run_jobs(engine)
    once = len(_isler(engine, service.CHECK_REQUIREMENT_JOB))
    with session_scope() as s:
        req = s.get(Requirement, k["rid"])
        eklenen, _ = cases_service.store_cases(
            s,
            req,
            [basit_case(adet=6, toplam="60,00", risk="low")],
            uretim_no=99,
            kanal="ide",
            ai_call_id=None,
            uretim_modu=None,
        )
        assert len(eklenen) == 1
    assert len(_isler(engine, service.CHECK_REQUIREMENT_JOB)) == once + 1


def test_oracle_check_hiz_siniri_ve_anahtar(api: TestClient, engine: Engine, kur) -> None:
    """Güvenlik 10: aynı içerik yeni iş açmaz; farklı içeriklerle dakikada en çok N iş."""
    k = kur([basit_case(toplam="30,00", risk="low")])
    c = latest_cases(api, k["rid"])[0]
    a = api.post(f"/cases/{c['id']}/oracle-check").json()["job_id"]
    assert api.post(f"/cases/{c['id']}/oracle-check").json()["job_id"] == a
    kodlar = [
        api.post(
            f"/cases/{c['id']}/oracle-check",
            json={"icerik": basit_case(adet=n, toplam=f"{n * 10},00", risk="low")},
        ).status_code
        for n in range(4, 4 + 12)  # adet 3 case'in kendi içeriği
    ]
    assert kodlar.count(202) == 9 and kodlar[-1] == 429  # 1 + 9 = DAKIKA_SINIRI
    r = api.post(f"/cases/{c['id']}/oracle-check", json={"icerik": basit_case(adet=50)})
    assert r.json()["kod"] == "oracle_kontrol_siniri"


def test_is_surerken_tablo_degisirse_sonuc_yazilmaz(
    api: TestClient, engine: Engine, kur, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test S6: eski tablo kümesiyle hesaplanan yavaş iş yeni kaydı ezmez."""
    k = kur([basit_case(toplam="30,00", risk="low")])
    c = latest_cases(api, k["rid"])[0]
    gercek = service._olgulari_cikar

    def yavas(*a: Any, **kw: Any) -> Any:
        tablo_degistir(
            k["tid"],
            {**BASIT, "satirlar": [{"id": "R1", "kosul": "adet >= 1", "cikti": {"toplam": "9"}}]},
            k["analist"],
            k["po"],
        )
        return {"groups": [], "ignored": []}, None, None, None

    monkeypatch.setattr(service, "_olgulari_cikar", yavas)
    yuk = {"case_id": c["id"], "icerik_hash": c["icerik_hash"]}
    ctx = JobContext(uuid.uuid4(), service.CHECK_CASE_JOB, yuk, deneme=1, max_deneme=3)
    sonuc = service.run_check_case(ctx, engine)
    assert sonuc["atlandi"] is True and _kayitlar(c["id"]) == []
    monkeypatch.setattr(service, "_olgulari_cikar", gercek)


def test_guncelleme_damgasi_olusturmayi_korur(api: TestClient, kur) -> None:
    """Mimari 17: yeniden hesaplama `guncelleme`'yi yazar, `olusturma` değişmez."""
    k = kur([basit_case(toplam="30,00", risk="low")])
    c = latest_cases(api, k["rid"])[0]
    cid = uuid.UUID(c["id"])
    kayit_yaz(cid, "uyumlu")
    [ilk] = _kayitlar(c["id"])
    kayit_yaz(cid, "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
    [son] = _kayitlar(c["id"])
    assert son.olusturma == ilk.olusturma and son.guncelleme > ilk.guncelleme
    assert service.kayit_damgasi(son) == son.guncelleme.isoformat()


# ------------------------------------------------------------------ onaylı-uyumsuz sinyali


def test_onaydan_sonra_onaylanan_tablo_onayli_uyumsuz_listesine_duser(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    """Güvenlik 4 / mimari 20 / bağımsızlık S5: tablo case onayından sonra onaylanır; kontrol
    case'i uyumsuz bulur → `oracle.onayli_uyumsuz` olayı + Kule `onayli_uyumsuz`."""
    from tp_core.gateway.testing import text_response

    from .helpers import olgu_modeli

    fake_gateway([text_response({"cases": [basit_case(toplam="40,00")]}), olgu_modeli])
    rid = make_requirement()
    analist, po = make_user("analyst"), make_user("po")
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    c = latest_cases(api, rid)[0]
    assert _karar(api, c, karar="approve").status_code == 200  # tablo yok: serbest
    tablo_ekle(rid, BASIT, analist, po)
    with session_scope() as s:
        service.gereksinim_kontrolu_kuyruga_al(s, rid, "tablo_onaylandi")
    run_jobs(engine)
    [ev] = _denetim("oracle.onayli_uyumsuz")
    assert ev.nesne == f"test_case:{c['id']}"
    with session_scope() as s:
        liste = ct.control_tower(s)["onayli_uyumsuz"]
    assert liste == [
        {"case_id": c["id"], "requirement_id": str(rid), "baslik": c["icerik"]["title"]}
    ]


# ------------------------------------------------------------------ AI sınır hatası (REPLAY)


def test_ai_sinir_hatasi_replay_kapisi(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    """Analist/PO 1, 3a: AI'ın klasik sınır hatası (tam 750,00 TL'de uyarı görünür) REPLAY'de
    golden'la (`ai-sinir-hatasi/TPD-1-C6`) uyumsuz çıkar; yüksek risk → 422; oran 5/6."""
    from . import tpd1

    beyan = tpd1.taslak_golden()["input_match"]
    rid = make_requirement(
        jira_key="TPD-1",
        baslik="Sepet ve sipariş",
        aciklama=beyan["contains"][0],
        acs=beyan["acceptance_criteria"],
    )
    analist, po = make_user("analyst"), make_user("po")
    for n in sorted(tpd1.TABLOLAR):
        tablo_ekle(rid, tpd1.TABLOLAR[n], analist, po)
    cases = tpd1.ana_yol_cases()
    cases[5] = tpd1.c6_ai_sinir_hatasi()
    with session_scope() as s:
        req = s.get(Requirement, rid)
        # IDE taslağı gibi (submit_drafts): PO onaylı → case'li duruma, sonra case yazımı.
        transition(s, req, "generating", "ide:test", "po_approved", sebep="test")
        transition(s, req, "cases_ready", "ide:test", "generating", sebep="test")
        cases_service.store_cases(
            s, req, cases, uretim_no=1, kanal="ide", ai_call_id=None, uretim_modu=None
        )
    run_jobs(engine, limit=100)
    login(api, analist)
    by = {c["sira_no"]: c for c in latest_cases(api, rid)}
    assert by[6]["oracle"]["sonuc"] == "uyumsuz", by[6]["oracle"]
    bozuk = [k for k in by[6]["oracle"]["karsilastirmalar"] if not k["uyumlu"]]
    assert {(k["column"], k["case_degeri"], k["tablo_degeri"]) for k in bozuk} == {
        ("minimum_uyarisi", True, False)
    }
    r = _karar(api, by[6], karar="approve")
    assert r.status_code == 422 and r.json()["kod"] == "oracle_uyumsuz", r.text
    m = api.get(f"/requirements/{rid}/case-metrics").json()["beklenti_dogrulugu"]
    assert (m["uyumlu"], m["uyumsuz"], m["oran"], m["n_case"]) == (5, 1, round(5 / 6, 4), 6)
    assert m["kismen"] == 0
    assert m["golden_kaynakli"] == 6
