"""Review turu 2 birleştirme adımı: çekirdeğin portal (Q3) mock'uyla hizalanması.

- Kule `onayli_uyumsuz[]` öğesi `jira_key` ve `sira_no` taşır ("TPD-1 · C5" künyesi).
- "Tablo yanlış" yolu: onaylı tablonun yeniden açılması `{icerik_hash, gerekce, case_id}` alır
  (case_id varsa gerekçe zorunlu); kayıt `gecmis` listesi ve `son_karar` (reopen) taşır; denetim
  case bağlantısıyla yazılır. Gövdesiz yeniden açma eskisi gibi çalışır.
- Özet alıntısı zaten tırnaklıysa yeniden sarılmaz.
- Taslak notundaki PO sorusu tablonun açıklamasına eklenir (mock `T2_PO_SORUSU`).
- `beklenti_dogrulugu.toplam_story` = AI case'i olan gereksinimler (mock
  `beklentiDogruluguHesapla`).

Gerçek Postgres + sahte model; canlı model yok.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.features.karar_tablosu import service as kt
from tp_core.features.oracle import dogrulama as d
from tp_core.features.oracle import metrik, service
from tp_core.models import AuditEvent, Requirement, session_scope

from ..cases.helpers import latest_cases, login, run_jobs
from .helpers import BASIT, basit_case, tablo_ekle

UZUN = "Story 'altında' diyor; tabloda sınır yanlış yazılmış, PO düzeltmeli."


def _tablo(api: TestClient, rid: uuid.UUID, tid: uuid.UUID) -> dict:
    r = api.get(f"/requirements/{rid}/decision-tables")
    assert r.status_code == 200, r.text
    return next(t for t in r.json()["tablolar"] if t["id"] == str(tid))


# ================================================================== A1: onayli_uyumsuz künyesi


def test_onayli_uyumsuz_jira_key_ve_sira_no_tasir(api: TestClient, engine: Engine, kur) -> None:
    k = kur([basit_case(toplam="40,00")], tablo_once=True, olgu_sayisi=5)
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    with session_scope() as s:
        s.execute(text("UPDATE test_case SET durum = 'approved' WHERE id = :i"), {"i": c["id"]})
    with session_scope() as s:
        jira_key = s.get(Requirement, k["rid"]).jira_key
        (oge,) = service.onayli_uyumsuz(s)
    assert jira_key
    assert oge == {
        "case_id": c["id"],
        "requirement_id": str(k["rid"]),
        "baslik": c["icerik"]["title"],
        "jira_key": jira_key,
        "sira_no": c["sira_no"],
    }
    login(api, k["analist"])
    kule = api.get("/control-tower").json()
    assert kule["onayli_uyumsuz"] == [oge]


# ================================================================== A2: "Tablo yanlış" yolu


def test_tablo_yanlis_yeniden_acma_gerekce_case_ve_gecmis(
    api: TestClient, engine: Engine, kur
) -> None:
    k = kur([basit_case(toplam="40,00")], tablo_once=True, olgu_sayisi=5)
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    login(api, k["analist"])
    t = _tablo(api, k["rid"], k["tid"])
    yol = f"/decision-tables/{k['tid']}/reopen"

    # case_id verildi, gerekçe yok → 422 (durum değişmez).
    r = api.post(yol, json={"icerik_hash": t["icerik_hash"], "case_id": c["id"]})
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_karar", r.text
    r = api.post(yol, json={"icerik_hash": t["icerik_hash"], "case_id": c["id"], "gerekce": " "})
    assert r.status_code == 422
    # Bayat hash → 409.
    r = api.post(yol, json={"icerik_hash": "eski", "case_id": c["id"], "gerekce": UZUN})
    assert r.status_code == 409 and r.json()["kod"] == "onay_hash_uyusmuyor"
    # Başka gereksinimin case'i (ya da olmayan case) → 422.
    r = api.post(
        yol,
        json={"icerik_hash": t["icerik_hash"], "case_id": str(uuid.uuid4()), "gerekce": UZUN},
    )
    assert r.status_code == 422
    assert _tablo(api, k["rid"], k["tid"])["durum"] == "approved"

    r = api.post(yol, json={"icerik_hash": t["icerik_hash"], "case_id": c["id"], "gerekce": UZUN})
    assert r.status_code == 200, r.text
    oge = r.json()
    assert oge["durum"] == "draft"
    son = oge["gecmis"][-1]
    assert son["karar"] == "reopen" and son["gerekce"] == UZUN and son["case_id"] == c["id"]
    assert son["kullanici"] == k["analist"].kullanici_adi and son["zaman"]
    assert son["icerik_hash"] == t["icerik_hash"]
    assert oge["son_karar"]["karar"] == "reopen" and oge["son_karar"]["case_id"] == c["id"]

    # Kalıcı okuma: aynı geçmiş ve son karar (PO tablo ekranında görür).
    okunan = _tablo(api, k["rid"], k["tid"])
    assert okunan["gecmis"][-1]["karar"] == "reopen"
    assert okunan["gecmis"][-1]["case_id"] == c["id"]
    assert okunan["son_karar"]["gerekce"] == UZUN

    with session_scope() as s:
        tablo_kaydi = s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "karar_tablosu.reopened")
        ).one()
        case_kaydi = s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "oracle.tablo_yanlis")
        ).one()
        assert tablo_kaydi.ozet["case_id"] == c["id"] and tablo_kaydi.ozet["gerekce"] == UZUN
        assert case_kaydi.nesne == f"test_case:{c['id']}"
        assert case_kaydi.ozet["nesne_id"] == str(k["tid"])

    # Analist düzeltir, gönderir; PO onaylar → son karar yeniden PO'nun onayı; geçmiş sıralı.
    yeni = {**BASIT, "aciklama": "Her adet 10 TL (düzeltildi)"}
    r = api.put(
        f"/decision-tables/{k['tid']}", json={"icerik": yeni, "icerik_hash": oge["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    h = r.json()["icerik_hash"]
    assert (
        api.post(f"/decision-tables/{k['tid']}/submit", json={"icerik_hash": h}).status_code == 200
    )
    login(api, k["po"])
    r = api.post(f"/decision-tables/{k['tid']}/approve", json={"icerik_hash": h})
    assert r.status_code == 200, r.text
    assert [g["karar"] for g in r.json()["gecmis"]] == ["reopen", "duzenle", "submit", "approve"]
    assert r.json()["son_karar"]["karar"] == "approve"


def test_govdesiz_yeniden_acma_calisir(api: TestClient, engine: Engine, kur) -> None:
    k = kur([basit_case(toplam="30,00", risk="low")], tablo_once=True, olgu_sayisi=5)
    run_jobs(engine)
    login(api, k["analist"])
    r = api.post(f"/decision-tables/{k['tid']}/reopen")
    assert r.status_code == 200, r.text
    oge = r.json()
    assert oge["durum"] == "draft"
    assert oge["gecmis"][-1]["karar"] == "reopen" and "case_id" not in oge["gecmis"][-1]
    assert oge["gecmis"][-1]["gerekce"] is None
    # Gerekçesiz yeniden açma PO'nun son kararını değiştirmez ("Tablo yanlış" notu çizilmez).
    assert oge["son_karar"]["karar"] == "approve"
    with session_scope() as s:
        assert (
            s.scalar(
                select(AuditEvent.id).where(AuditEvent.eylem == "oracle.tablo_yanlis").limit(1)
            )
            is None
        )


def test_baska_gereksinimin_case_i_ile_tablo_yanlis_reddedilir(
    api: TestClient, engine: Engine, kur, make_requirement
) -> None:
    k = kur([basit_case(toplam="30,00", risk="low")], tablo_once=True, olgu_sayisi=5)
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    diger = make_requirement(jira_key="TPD-77")
    tid2 = tablo_ekle(diger, BASIT, k["analist"], k["po"])
    login(api, k["analist"])
    r = api.post(f"/decision-tables/{tid2}/reopen", json={"case_id": c["id"], "gerekce": UZUN})
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_karar"


# ================================================================== A4: özet alıntısı


def test_ozet_tirnakli_alintiyi_yeniden_sarmaz() -> None:
    assert d.alinti_metni("750,00 TL") == "“750,00 TL”"
    assert d.alinti_metni('"750,00 TL"') == '"750,00 TL"'
    assert (
        d.alinti_metni("“Minimum sipariş tutarı 750,00 TL”") == "“Minimum sipariş tutarı 750,00 TL”"
    )
    assert d.alinti_metni('uyarı "görünür"') == 'uyarı "görünür"'
    ayr = {
        "gruplar": [
            {
                "karsilastirmalar": [
                    {
                        "column": "minimum_uyarisi",
                        "alinti": '"Minimum sipariş tutarı 750,00 TL" uyarısı görünür',
                        "tablo_degeri": False,
                        "uyumlu": False,
                    }
                ]
            }
        ]
    }
    metin = d.ozet(d.UYUMSUZ, ayr)
    assert "““" not in metin and '“"' not in metin and '"”' not in metin
    assert 'case "Minimum sipariş tutarı 750,00 TL" uyarısı görünür, tablo yanlış.' in metin


# ================================================================== A5: T2 PO sorusu


def test_po_sorusu_ac_ile_tabloya_eslenir() -> None:
    notes = (
        "AC3: sınır <= 750 modellendi. PO sorusu: tam 750,00 TL'de uyarı olmalı mı? (750 satırı) "
        "AC2: indirim birim fiyat. PO sorusu: genel soru"
    )
    assert kt.po_sorulari(notes) == [
        ("AC3", "tam 750,00 TL'de uyarı olmalı mı? (750 satırı)"),
        ("AC2", "genel soru"),
    ]
    assert kt.po_sorulari("Etiketsiz. PO sorusu: herkese") == [(None, "herkese")]
    assert kt.po_sorulari("") == []
    t2 = {"ad": "Min", "ac_refs": ["AC3", "AC6"], "aciklama": "Kural."}
    t1 = {"ad": "Kampanya", "ac_refs": ["AC2"]}
    sorular = kt.po_sorulari(notes)
    assert kt._po_sorulu(t2, sorular)["aciklama"] == (
        "Kural. PO sorusu (AI taslak notu): tam 750,00 TL'de uyarı olmalı mı? (750 satırı)"
    )
    assert kt._po_sorulu(t1, sorular)["aciklama"] == "PO sorusu (AI taslak notu): genel soru"
    uzun = kt._po_sorulu({**t2, "aciklama": "x" * 990}, sorular)["aciklama"]
    assert len(uzun) == kt.ACIKLAMA_AZAMI and uzun.endswith("…")


# ================================================================== A6: toplam_story


def test_toplam_story_ai_case_i_olan_gereksinimler(api: TestClient, engine: Engine, kur) -> None:
    k = kur([basit_case(toplam="30,00", risk="low")], tablo_once=True, olgu_sayisi=5)
    run_jobs(engine)
    with session_scope() as s:
        m = metrik.beklenti_dogrulugu(s)
    assert (m["toplam_story"], m["tablolu_story"]) == (1, 1)
    with session_scope() as s:
        s.execute(
            text("UPDATE test_case SET ai_generated = false WHERE requirement_id = :r"),
            {"r": k["rid"]},
        )
    with session_scope() as s:
        m = metrik.beklenti_dogrulugu(s)
    assert (m["toplam_story"], m["tablolu_story"]) == (0, 0)
