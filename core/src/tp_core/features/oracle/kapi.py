"""Onay kapısı (012 ANALIZ §4.3 tablosu; K3, V1, V2, V3): `cases.service.decide` approve / edit.

| Durum | Yüksek risk | Orta / düşük risk |
|---|---|---|
| `uyumlu`, `kapsam_disi` | onay | onay |
| `uyumsuz`, istisna yok | 422 `oracle_uyumsuz` | onay + uyarı kaydı |
| `uyumsuz`, geçerli istisna | onay; `oracle.exception` denetim kaydı | onay (istisna yazılır) |
| `kontrol_edilemedi` | onay + uyarı (V2) | onay |
| kontrol kaydı yok, kapsayan tablo var | 409 `oracle_bekleniyor` (V3) | onay |
| kapsayan tablo yok | onay | onay |

- Risk, kontrol edilen içerikten okunur (`edit`'te gönderilen içerik): yalnız `high` engeller.
- "Kayıt yok" = `(case, icerik_hash)` için güncel kapsayan tablolarla yapılmış geçerli kayıt yok
  (tablo değiştiyse eski kayıt sayılmaz). 409'da kontrol ayrı işlemde kuyruğa alınır (istek geri
  alınsa da iş kalır); analist kontrol bitince yeniden dener.
- İstisna (V1): gerekçe boşluk atılınca en az `ISTISNA_EN_AZ` karakter; kısa gerekçe 422
  (`gecersiz_karar`). Geçerli istisna kontrol satırına (`istisna_gerekce`, `istisna_veren_id`,
  `istisna_zamani`) yazılır ve `oracle.exception` olarak denetlenir. Uyuşmazlık yoksa verilen
  gerekçe yok sayılır.
- Uyarılar karar kaydına (`review.duzeltme_olculeri.oracle_uyarilari`) yazılır ve case'in
  `uyarilar` listesinde görünür; ayrıca `oracle.warning` olarak denetlenir.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.features.karar_tablosu.hatalar import OracleBekleniyor, OracleUyumsuz
from tp_core.features.oracle import dogrulama, service
from tp_core.models import TestCase, session_scope
from tp_core.workflow.service import InvalidDecision, Principal

ISTISNA_EN_AZ = 20
YUKSEK = "high"

UYARI_KONTROL_EDILEMEDI = (
    "Yüksek riskli case'in beklenen değerleri karar tablosuyla kontrol edilemedi "
    "(case'ten karşılaştırılabilir değer çıkarılamadı); onay kontrolsüz verildi."
)
UYARI_UYUSMAZLIK = "Beklenen değer onaylı karar tablosuyla uyuşmuyor, onay uyarıyla verildi: {ozet}"


def _uyumsuz_ozet(kayit: Any) -> str:
    return dogrulama.ozet(kayit.sonuc, kayit.ayrintilar)


def _kontrolu_baslat(
    tc: TestCase, icerik_hash: str, icerik: Mapping[str, Any] | None, tablo_ozeti: str, damga: str
) -> None:
    """409 öncesi kontrolü AYRI işlemde kuyruğa alır (istek geri alınınca iş kaybolmasın).

    Anahtar tablo kümesini ve mevcut (geçersiz) kaydın damgasını taşır: aynı durumda tekrar
    denemede yeni iş açılmaz; tablo değişince ya da önceki içeriğine dönünce (A → B → A) açılır."""
    gonderilen = None if icerik_hash == tc.icerik_hash else icerik
    with session_scope() as s:
        service.kontrol_kuyruga_al(
            s,
            tc.id,
            icerik_hash,
            gonderilen,
            idempotency_key=(
                f"{service.CHECK_CASE_JOB}:kapi:{tc.id}:{icerik_hash}:{tablo_ozeti}:{damga}"
            ),
        )


def onay_denetimi(
    session: Session,
    tc: TestCase,
    icerik_hash: str,
    istisna_gerekce: str | None,
    user: Principal,
    *,
    icerik: Mapping[str, Any] | None = None,
) -> list[str]:
    """Onay kapısı; engel yoksa kayda geçecek uyarıları döndürür (§4.3 tablosu).

    `icerik`: `edit`'te gönderilen içerik (`icerik_hash` onun hash'idir); `approve`'da `None`
    (case'in güncel içeriği).
    """
    icerik = tc.icerik if icerik is None else icerik
    yuksek = str(icerik.get("risk") or "").lower() == YUKSEK
    kapsayan = service.kapsayan_tablolar(session, tc, icerik)
    if not kapsayan:
        return []
    kayit = service.gecerli_kayit(session, tc, icerik_hash, kapsayan, lock=True)
    if kayit is None:
        if not yuksek:
            return []
        _kontrolu_baslat(
            tc,
            icerik_hash,
            icerik,
            service.tablo_ozeti(service.tablo_hashleri(kapsayan)),
            service.kayit_damgasi(service.kayit_bul(session, tc.id, icerik_hash)),
        )
        raise OracleBekleniyor(
            "Yüksek riskli case'in karar tablosu kontrolü henüz bitmedi; kontrol kuyruğa alındı, "
            "birkaç saniye sonra yeniden deneyin"
        )
    if kayit.sonuc in (dogrulama.UYUMLU, dogrulama.KAPSAM_DISI):
        return []
    if kayit.sonuc == dogrulama.KONTROL_EDILEMEDI:
        if not yuksek:
            return []
        _uyari_denetle(session, tc, icerik_hash, user, UYARI_KONTROL_EDILEMEDI)
        return [UYARI_KONTROL_EDILEMEDI]
    gerekce = (istisna_gerekce or "").strip()
    if gerekce:
        if len(gerekce) < ISTISNA_EN_AZ:
            raise InvalidDecision(
                f"İstisna gerekçesi en az {ISTISNA_EN_AZ} karakter olmalı "
                "(karar tablosu uyuşmazlığı)"
            )
        if user.id is None:
            raise InvalidDecision("istisna yalnızca oturumlu kullanıcıyla verilir")
        kayit.istisna_gerekce = gerekce
        kayit.istisna_veren_id = user.id
        kayit.istisna_zamani = datetime.now(UTC)
        session.flush()
        audit_on_commit(
            session,
            user.kullanici_adi,
            "oracle.exception",
            f"test_case:{tc.id}",
            {
                "icerik_hash": icerik_hash,
                "kontrol_id": kayit.id,
                "risk": icerik.get("risk"),
                "gerekce": gerekce,
                "uyusmayan": [k for k in service.karsilastirmalar(kayit) if not k["uyumlu"]],
            },
        )
        return []
    ozet = _uyumsuz_ozet(kayit)
    if yuksek:
        raise OracleUyumsuz(
            f"Yüksek riskli case onaylanamaz: {ozet} Case'i düzeltin ya da gerekçeli istisnayla "
            "onaylayın"
        )
    uyari = UYARI_UYUSMAZLIK.format(ozet=ozet)
    _uyari_denetle(session, tc, icerik_hash, user, uyari)
    return [uyari]


def _uyari_denetle(
    session: Session, tc: TestCase, icerik_hash: str, user: Principal, uyari: str
) -> None:
    audit_on_commit(
        session,
        user.kullanici_adi,
        "oracle.warning",
        f"test_case:{tc.id}",
        {"icerik_hash": icerik_hash, "uyari": uyari},
    )
