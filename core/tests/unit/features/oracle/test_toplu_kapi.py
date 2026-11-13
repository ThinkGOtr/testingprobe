"""012 kalite × 013 toplu karar (ANALIZ §14.5, dev birleşmesi): karar tablosu kapısı toplu kararda
öğe başına uygulanır.

- Testçinin toplu kabulünde (`accept`) kapının engellediği öğe tek başına düşer; öğe sonucu
  `kod` taşır (`oracle_uyumsuz`, `oracle_bekleniyor` …), diğerleri kabul edilir.
- İstisna gerekçesi toplu kararda verilmez: case tekil kararda istisnayla kabul edilir.
- Analistin toplu son onayı (`approve`) kapıdan yeniden geçer: aynı tür + tablo kümesiyle verilmiş
  istisna yeniden gerekçe istemez; kabulden sonra uyumsuzlaşan case düşer.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tp_core.features.cases import service as cases_service
from tp_core.models import AuditEvent, OracleIstisna, TestCase, session_scope

from ..cases.helpers import goruntule, latest_cases, login
from .helpers import basit_case, kayit_yaz, uyumsuz_ayrinti
from .test_oracle_db import UZUN_GEREKCE, _karar


def _toplu(api: TestClient, karar: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    r = api.post(
        "/cases/bulk-decision",
        json={
            "karar": karar,
            "ogeler": [{"case_id": c["id"], "icerik_hash": c["icerik_hash"]} for c in cases],
        },
    )
    assert r.status_code == 200, r.text
    return {s["case_id"]: s for s in r.json()["sonuclar"]}


def _durum(cid: str) -> str:
    with session_scope() as s:
        return s.get(TestCase, uuid.UUID(cid)).durum


def test_toplu_karar_kapisi_oge_bazinda(
    api: TestClient, engine: Engine, kur, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    k = kur(
        [
            basit_case(adet=3, toplam="30,00"),
            basit_case(adet=4, toplam="45,00"),
            basit_case(adet=5, toplam="50,00"),
        ]
    )
    uyumlu, uyumsuz, kayitsiz = sorted(latest_cases(api, k["rid"]), key=lambda c: c["sira_no"])
    kayit_yaz(uuid.UUID(uyumlu["id"]), "uyumlu")
    kayit_yaz(uuid.UUID(uyumsuz["id"]), "uyumsuz", uyumsuz_ayrinti(str(k["tid"]), "45.00"))
    goruntule(api, db, uyumlu["id"], uyumsuz["id"], kayitsiz["id"])

    # 1) Testçinin toplu kabulü: yüksek riskli uyuşmazlık ve bekleyen kontrol öğe başına düşer.
    sonuc = _toplu(api, "accept", [uyumlu, uyumsuz, kayitsiz])
    assert (sonuc[uyumlu["id"]]["durum"], sonuc[uyumlu["id"]]["kod"]) == ("onaylandi", None)
    assert (sonuc[uyumsuz["id"]]["durum"], sonuc[uyumsuz["id"]]["kod"]) == (
        "hata",
        "oracle_uyumsuz",
    )
    assert (sonuc[kayitsiz["id"]]["durum"], sonuc[kayitsiz["id"]]["kod"]) == (
        "hata",
        "oracle_bekleniyor",
    )
    assert "tablo" in sonuc[uyumsuz["id"]]["neden"]
    assert [_durum(c["id"]) for c in (uyumlu, uyumsuz, kayitsiz)] == ["ready", "draft", "draft"]
    with session_scope() as s:
        [d] = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.bulk_decision")).all()
        kodlar = {o["case_id"]: o["kod"] for o in d.ozet["ogeler"]}
    assert kodlar[uyumsuz["id"]] == "oracle_uyumsuz"

    # 2) İstisna yalnız tekil kararda: Testçi gerekçeyle kabul eder.
    r = _karar(
        api,
        uyumsuz,
        karar="accept",
        oracle_istisna_gerekce=UZUN_GEREKCE,
        oracle_istisna_turu="uyumsuz",
    )
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "ready"

    # 3) Analistin toplu son onayı: geçerli istisna yeniden kullanılır; kabulden sonra
    # uyumsuzlaşan (yeniden hesaplanan kayıt) case kapıda düşer.
    hazir = {c["id"]: c for c in latest_cases(api, k["rid"])}
    kayit_yaz(uuid.UUID(uyumlu["id"]), "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
    api.cookies.clear()
    login(api, k["analist"])
    # Görülme süresi ayrı testte; burada eşik (son karar) yeni kabulden sonradır.
    monkeypatch.setattr(cases_service, "GORULME_MIN_S", 0)
    for c in (uyumlu, uyumsuz):
        assert api.post(f"/cases/{c['id']}/viewed").status_code == 200
    sonuc = _toplu(api, "approve", [hazir[uyumlu["id"]], hazir[uyumsuz["id"]]])
    assert (sonuc[uyumsuz["id"]]["durum"], sonuc[uyumsuz["id"]]["kod"]) == ("onaylandi", None)
    assert (sonuc[uyumlu["id"]]["durum"], sonuc[uyumlu["id"]]["kod"]) == (
        "hata",
        "oracle_uyumsuz",
    )
    assert _durum(uyumsuz["id"]) == "approved" and _durum(uyumlu["id"]) == "ready"
    with session_scope() as s:
        assert len(s.scalars(select(OracleIstisna)).all()) == 1
        [ev] = s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "oracle.exception_reused")
        ).all()
        assert ev.aktor == k["analist"].kullanici_adi


def test_veri_atiflari_degerle_kontrol_edilir(api: TestClient, kur) -> None:
    """Dev birleşmesi (013 test verisi kataloğu): case alanlarındaki gizli olmayan `{veri:…}`
    atıfları değer çıkarmadan önce değerine çözülür; gizli ve bilinmeyen atıflar atıf kalır."""
    from tp_core.features.oracle import service as oracle_service

    k = kur([basit_case()])
    api.cookies.clear()
    login(api, k["analist"])
    r = api.post("/test-data", json={"anahtar": "ortak.adet_metni", "deger": "adet 3"})
    assert r.status_code in (200, 201), r.text
    icerik = {
        **basit_case(),
        "steps": [
            {"id": "S1", "action": "Ekle", "data": "{veri:ortak.adet_metni}", "expected": "Eklenir"},
            {"id": "S2", "action": "Git", "data": "{veri:ortak.yok}", "expected": "Toplam 30,00 TL"},
        ],
    }
    with session_scope() as s:
        okunan = oracle_service._veri_cozulmus(s, icerik)
    assert okunan["steps"][0]["data"] == "adet 3"
    assert okunan["steps"][1]["data"] == "{veri:ortak.yok}"
    assert icerik["steps"][0]["data"] == "{veri:ortak.adet_metni}"  # girdi değişmez
