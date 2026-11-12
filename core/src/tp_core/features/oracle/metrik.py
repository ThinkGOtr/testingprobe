"""Beklenti doğruluğu metriği (012 ANALIZ §4.7, §13.2, F4; kaynak belgede
`generatorExpectationAccuracy`).

Okuma anında hesaplanır (Kontrol Kulesi'nin kendi tablosu yoktur). Sayım, superseded olmayan
AI üretimi case'lerin **AI içeriğinin** (insan düzeltmesinden önceki hash; `ai_icerik=true`)
geçerli kontrol kayıtları üzerindendir (kaydın `tablo_hashleri` güncel kapsayan tablolarla aynı).

- Tekrar: aynı gereksinimde aynı tablo satırını aynı girdilerle aynı beklenen değerlere karşı
  denetleyen case'ler tek sayılır (ör. TPD-1 C10 = C2; review 1 bağımsızlık S2); `tekrar` sayısı
  ayrıca verilir. Yalnız `uyumlu`/`uyumsuz`/`kismen` kayıtlar tekilleştirilir.
- `oran = uyumlu / (uyumlu + uyumsuz)`; payda 0 ise `null` ("ölçülmedi"). `kismen`,
  `kontrol_edilemedi` ve `kapsam_disi` orana girmez.
- `n_case = uyumlu + uyumsuz` (oranın örneklemi), `n_story` = bu case'lerin story sayısı.
- `toplam_story`: AI case'i olan story'ler; `tablolu_story`: bunlardan geçerli karar tablosu
  olanlar.
- `kapsam_orani = (uyumlu + uyumsuz + kismen) / tablolu story'lerdeki AI case toplamı` (kayıt
  yoksa da paydada; tekrarlar paydadan da düşülür). Etiket: "tablosu olan story'lerde".
- `istisna` / `kontrolsuz_onay`: aynı case'lerin `oracle_istisna` kayıtları (`uyumsuz` /
  `kontrolsuz` türü; append-only tablodan; case ve tür başına bir — tekrar gerekçe şişirmez).
- `golden_kaynakli`: sayılan kayıtlardan REPLAY (elle golden) ile üretilenler; portal "REPLAY /
  elle golden" etiketini buna göre gösterir (doğruluk iddiası model ölçümü değildir).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import content_hash
from tp_core.features.oracle import dogrulama, service
from tp_core.features.oracle.tablolar import kapsayanlar
from tp_core.models import CaseOracleKontrol, OracleIstisna, TestCase

KAYNAK = (
    "AI'ın ürettiği case içeriklerinin (insan düzeltmesinden önceki hali) PO onaylı karar "
    "tablolarıyla deterministik karşılaştırması (case_oracle_kontrol, ai_icerik=true; güncel "
    "tablolarla yapılmış kontroller). Oran = uyumlu / (uyumlu + uyumsuz); kısmen kontrol edilen, "
    "kontrol edilemeyen ve kapsam dışı case'ler orana girmez, ayrı sayılır. Aynı tablo satırını "
    "aynı değerlerle denetleyen tekrar case'ler tek sayılır. Kapsam oranı tablosu olan "
    "story'lerdeki AI case'leri üzerindendir. İstisna ve kontrolsüz onay: oracle_istisna "
    "kayıtları. golden_kaynakli: REPLAY (elle hazırlanmış golden) ile üretilmiş kayıtlar — "
    "gösterge, model ölçümü değil."
)
_TEKILLESEN = (dogrulama.UYUMLU, dogrulama.UYUMSUZ, dogrulama.KISMEN)


def _oran(pay: int, payda: int) -> float | None:
    return round(pay / payda, 4) if payda else None


def _imza(rid: uuid.UUID, kayit: CaseOracleKontrol) -> tuple[Any, ...] | None:
    """Tekrar tespiti: (gereksinim, sonuç, [(tablo, satır, girdiler, karşılaştırmalar)])."""
    gruplar = []
    for g in (kayit.ayrintilar or {}).get("gruplar") or []:
        girdi = tuple(
            sorted({(o.get("column"), str(o.get("value"))) for o in g.get("girdiler") or []})
        )
        kars = tuple(
            sorted(
                {
                    (k.get("column"), str(k.get("case_degeri")), bool(k.get("uyumlu")))
                    for k in g.get("karsilastirmalar") or []
                }
            )
        )
        gruplar.append((g.get("tablo_id"), g.get("satir_id"), girdi, kars))
    if not gruplar:
        return None
    return (rid, kayit.sonuc, tuple(sorted(gruplar, key=repr)))


def beklenti_dogrulugu(session: Session, requirement_id: uuid.UUID | None = None) -> dict[str, Any]:
    """§13.2 `beklenti_dogrulugu` (gereksinim verilirse yalnız onun case'leri)."""
    q = select(TestCase).where(TestCase.ai_generated.is_(True), TestCase.durum != "superseded")
    if requirement_id is not None:
        q = q.where(TestCase.requirement_id == requirement_id)
    cases = session.scalars(q).all()
    sayac: dict[str, int] = defaultdict(int)
    istisna_turleri: dict[str, int] = defaultdict(int)
    tekrar = golden = 0
    story_oranda: set[uuid.UUID] = set()
    tablolu_case = 0
    tablolu_story: set[uuid.UUID] = set()
    if cases:
        ai = service.ai_icerikleri(session, cases)
        hedef = {c.id: content_hash(ai[c.id]) for c in cases}
        tablolar = service.gecerli_tablolar_toplu(session, {c.requirement_id for c in cases})
        tablolu_story = {rid for rid, t in tablolar.items() if t}
        kayitlar: Mapping[tuple[uuid.UUID, str], CaseOracleKontrol] = {
            (k.test_case_id, k.icerik_hash): k
            for k in session.scalars(
                select(CaseOracleKontrol).where(
                    CaseOracleKontrol.test_case_id.in_(list(hedef)),
                    CaseOracleKontrol.icerik_hash.in_(set(hedef.values())),
                    CaseOracleKontrol.ai_icerik.is_(True),
                )
            )
        }
        goruldu: set[tuple[Any, ...]] = set()
        for c in cases:
            if c.requirement_id in tablolu_story:
                tablolu_case += 1
            k = kayitlar.get((c.id, hedef[c.id]))
            if k is None or not service.gecerli_mi(
                k, kapsayanlar(tablolar[c.requirement_id], ai[c.id])
            ):
                continue
            if k.sonuc in _TEKILLESEN:
                imza = _imza(c.requirement_id, k)
                if imza is not None and imza in goruldu:
                    tekrar += 1
                    tablolu_case -= c.requirement_id in tablolu_story
                    continue
                if imza is not None:
                    goruldu.add(imza)
            sayac[k.sonuc] += 1
            if k.sonuc in (dogrulama.UYUMLU, dogrulama.UYUMSUZ):
                story_oranda.add(c.requirement_id)
            if k.uretim_modu == "replay":
                golden += 1
        for _cid, tur in session.execute(
            select(OracleIstisna.test_case_id, OracleIstisna.tur)
            .where(OracleIstisna.test_case_id.in_(list(hedef)))
            .distinct()
        ).all():
            istisna_turleri[tur] += 1
    uyumlu, uyumsuz, kismen = (
        sayac[dogrulama.UYUMLU],
        sayac[dogrulama.UYUMSUZ],
        sayac[dogrulama.KISMEN],
    )
    return {
        "oran": _oran(uyumlu, uyumlu + uyumsuz),
        "uyumlu": uyumlu,
        "uyumsuz": uyumsuz,
        "kismen": kismen,
        "kontrol_edilemedi": sayac[dogrulama.KONTROL_EDILEMEDI],
        "kapsam_disi": sayac[dogrulama.KAPSAM_DISI],
        "istisna": istisna_turleri["uyumsuz"],
        "kontrolsuz_onay": istisna_turleri["kontrolsuz"],
        "n_case": uyumlu + uyumsuz,
        "n_story": len(story_oranda),
        "tablolu_story": len(tablolu_story),
        "toplam_story": len({c.requirement_id for c in cases}),
        "kapsam_orani": _oran(uyumlu + uyumsuz + kismen, tablolu_case),
        "golden_kaynakli": golden,
        "tekrar": tekrar,
        "kaynak": KAYNAK,
    }
