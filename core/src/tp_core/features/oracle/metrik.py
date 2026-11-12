"""Beklenti doğruluğu metriği (012 ANALIZ §4.7, F4; kaynak belgede `generatorExpectationAccuracy`).

Okuma anında hesaplanır (Kontrol Kulesi'nin kendi tablosu yoktur). Sayım, superseded olmayan
AI üretimi case'lerin **AI içeriğinin** (insan düzeltmesinden önceki hash; `ai_icerik=true`)
kontrol sonuçları üzerindendir. Yalnız geçerli kayıtlar sayılır: kaydın `tablo_hashleri` o
içeriği kapsayan güncel tablolarla aynı olmalı (tablo değişip kontrol henüz yenilenmediyse kayıt
sayılmaz).

- `oran = uyumlu / (uyumlu + uyumsuz)`; payda 0 ise `null` ("ölçülmedi").
- `kapsam_orani = (kapsam_disi olmayan AI kontrolleri) / (tüm AI kontrolleri)`; payda 0 → `null`.
  Kontrol kaydı yalnız geçerli karar tablosu olan gereksinimlerde oluşur (üretim kancası tablo
  yoksa iş açmaz; ilk tablo onaylanınca tüm case'ler kontrol edilir).
- `istisna`: aynı case'lerin (hangi içerikte olursa olsun) gerekçeli istisna sayısı.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import content_hash
from tp_core.features.oracle import dogrulama, service
from tp_core.features.oracle.tablolar import gecerli_tablolar, kapsayanlar
from tp_core.models import CaseOracleKontrol, TestCase

KAYNAK = (
    "AI'ın ürettiği case içeriklerinin (insan düzeltmesinden önceki hali) PO onaylı karar "
    "tablolarıyla deterministik karşılaştırması (case_oracle_kontrol, ai_icerik=true; güncel "
    "tablolarla yapılmış kontroller). Oran = uyumlu / (uyumlu + uyumsuz); kontrol edilemeyen ve "
    "kapsam dışı case'ler orana girmez, ayrı sayılır. İstisna: gerekçeli istisnayla onaylanan "
    "uyuşmazlıklar."
)


def _oran(pay: int, payda: int) -> float | None:
    return round(pay / payda, 4) if payda else None


def beklenti_dogrulugu(session: Session, requirement_id: uuid.UUID | None = None) -> dict[str, Any]:
    """§4.7 `beklenti_dogrulugu` (gereksinim verilirse yalnız onun case'leri)."""
    q = select(TestCase).where(TestCase.ai_generated.is_(True), TestCase.durum != "superseded")
    if requirement_id is not None:
        q = q.where(TestCase.requirement_id == requirement_id)
    cases = session.scalars(q).all()
    sayac: dict[str, int] = defaultdict(int)
    istisna = 0
    if cases:
        ai = service.ai_icerikleri(session, cases)
        hedef = {c.id: content_hash(ai[c.id]) for c in cases}
        tablolar = {
            rid: gecerli_tablolar(session, rid) for rid in {c.requirement_id for c in cases}
        }
        kayitlar = session.scalars(
            select(CaseOracleKontrol).where(CaseOracleKontrol.test_case_id.in_(list(hedef)))
        ).all()
        case_by_id = {c.id: c for c in cases}
        for k in kayitlar:
            if k.istisna_gerekce:
                istisna += 1
            if not k.ai_icerik or hedef.get(k.test_case_id) != k.icerik_hash:
                continue
            c = case_by_id[k.test_case_id]
            if not service.gecerli_mi(k, kapsayanlar(tablolar[c.requirement_id], ai[c.id])):
                continue
            sayac[k.sonuc] += 1
    uyumlu, uyumsuz = sayac[dogrulama.UYUMLU], sayac[dogrulama.UYUMSUZ]
    kapsam_disi, edilemedi = sayac[dogrulama.KAPSAM_DISI], sayac[dogrulama.KONTROL_EDILEMEDI]
    toplam = uyumlu + uyumsuz + kapsam_disi + edilemedi
    return {
        "oran": _oran(uyumlu, uyumlu + uyumsuz),
        "uyumlu": uyumlu,
        "uyumsuz": uyumsuz,
        "kapsam_disi": kapsam_disi,
        "kontrol_edilemedi": edilemedi,
        "istisna": istisna,
        "kapsam_orani": _oran(toplam - kapsam_disi, toplam),
        "kaynak": KAYNAK,
    }
