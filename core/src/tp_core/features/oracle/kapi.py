"""Onay kapısı (012 ANALIZ §4.3, §13; K3, K10, K11, V1, V3, V11): `cases.service.decide`
approve / edit.

"Zorunlu" = yüksek risk (V11: sakli, AI özgün ya da gönderilen içerikten herhangi biri yüksek;
`dogrulama.yuksek_risk_mi`) ya da düşürme (aşağıda).

| Durum | Zorunlu | Diğer |
|---|---|---|
| `uyumlu`, `kapsam_disi` | onay | onay |
| `kismen` (K11) | onay + uyarı | onay + uyarı |
| `uyumsuz`, istisna yok | 422 `oracle_uyumsuz` | onay + uyarı |
| `kontrol_edilemedi`, gerekçe yok (K10) | 422 `oracle_kontrolsuz` | onay + uyarı |
| gerekçe ya da aynı tablolarla önceki istisna | onay; `oracle_istisna` | onay + uyarı |
| kontrol kaydı yok, kapsayan tablo var | 409 `oracle_bekleniyor` (V3) | onay |
| kapsayan tablo yok | onay | onay |

- Kapsayan tablolar sakli ∪ gönderilen AC ref'lerinden (V11); gönderilen içeriğin kontrolü de bu
  birleşimle yapılır (iş yükünde `ac_refs`). Kapı gereksinimin tablolarını `FOR SHARE` kilitler:
  karar verilirken tablo onaylanamaz / yeniden açılamaz (sonradan onaylanan tablo onaylı case'i
  uyumsuz bulursa `oracle.onayli_uyumsuz` sinyali çalışır).
- Düşürme: `edit` riski yüksekten aşağı indiriyor ya da kapsanan bir tabloyu düşüren AC ref'i
  siliyorsa `oracle.dusurme` denetim kaydı yazılır ve kapı "zorunlu" çalışır.
- İstisna (V1, V10): gerekçe boşluk atılınca ≥ 20 karakter ve ≥ 10 harf. Tür
  (`oracle_istisna_turu`) verilmezse sonuçtan çıkarılır (`uyumsuz` | `kontrolsuz`); verilen tür
  sonuca uymazsa 422. Geçerli istisna append-only `oracle_istisna`'ya (geriye uyum için kontrol
  satırına da) yazılır ve `oracle.exception` olarak denetlenir. Uyuşmazlık yoksa gerekçe yok
  sayılır. Aynı içerik, tür ve tablo kümesi için önceki istisna yeniden gerekçe istemez (portalın
  "istisna verilmiş" görünümüyle aynı; review 1 test S1).
- 409'da kontrol ayrı işlemde kuyruğa alınır (istek geri alınsa da iş kalır); başarısız iş
  anahtarı kilitlemez (`service.kontrol_kuyruga_al`).
- Uyarılar karar kaydına (`review.duzeltme_olculeri.oracle_uyarilari`) yazılır ve case'in
  `uyarilar` listesinde görünür; ayrıca `oracle.warning` olarak denetlenir.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.features.karar_tablosu.hatalar import (
    OracleBekleniyor,
    OracleKontrolsuz,
    OracleUyumsuz,
)
from tp_core.features.oracle import dogrulama, service
from tp_core.features.oracle.tablolar import tablo_hashleri
from tp_core.models import KararTablosu, TestCase, session_scope
from tp_core.models.enums import ORACLE_ISTISNA_TUR
from tp_core.workflow.service import InvalidDecision, Principal, WorkflowError

ISTISNA_EN_AZ = 20
ISTISNA_EN_AZ_HARF = 10
_HARF = re.compile(r"[^\W\d_]")

UYARI_KONTROL_EDILEMEDI = (
    "Case'in beklenen değerleri karar tablosuyla kontrol edilemedi "
    "(case'ten karşılaştırılabilir değer çıkarılamadı); onay kontrolsüz verildi."
)
UYARI_KISMEN = "Beklenen değerler karar tablosuyla yalnız kısmen kontrol edildi: {ozet}"
UYARI_UYUSMAZLIK = "Beklenen değer onaylı karar tablosuyla uyuşmuyor, onay uyarıyla verildi: {ozet}"


def gerekce_hatasi(gerekce: str) -> str | None:
    """İstisna gerekçesinin kuralı (§13.2): ≥ 20 karakter ve ≥ 10 harf. Hata metni ya da None."""
    if len(gerekce) < ISTISNA_EN_AZ or len(_HARF.findall(gerekce)) < ISTISNA_EN_AZ_HARF:
        return (
            f"İstisna gerekçesi en az {ISTISNA_EN_AZ} karakter ve {ISTISNA_EN_AZ_HARF} harf "
            "olmalı (karar tablosu kontrolü)"
        )
    return None


def _kontrolu_baslat(
    tc: TestCase,
    icerik_hash: str,
    icerik: Mapping[str, Any] | None,
    ac_refs: list[str],
    tablo_ozeti: str,
    damga: str,
) -> None:
    """409 öncesi kontrolü AYRI işlemde kuyruğa alır (istek geri alınınca iş kaybolmasın)."""
    gonderilen = None if icerik_hash == tc.icerik_hash else icerik
    with session_scope() as s:
        service.kontrol_kuyruga_al(
            s,
            tc.id,
            icerik_hash,
            gonderilen,
            ac_refs=ac_refs,
            idempotency_key=service.kontrol_anahtari(
                "kapi", tc.id, icerik_hash, tablo_ozeti, damga
            ),
        )


def _tablolari_kilitle(session: Session, tc: TestCase) -> None:
    """Gereksinimin karar tablolarını `FOR SHARE` kilitler (review 1 güvenlik 4)."""
    session.execute(
        select(KararTablosu.id)
        .where(KararTablosu.requirement_id == tc.requirement_id)
        .with_for_update(read=True)
    ).all()


def onay_denetimi(
    session: Session,
    tc: TestCase,
    icerik_hash: str,
    istisna_gerekce: str | None,
    user: Principal,
    *,
    icerik: Mapping[str, Any] | None = None,
    istisna_turu: str | None = None,
) -> list[str]:
    """Onay kapısı; engel yoksa kayda geçecek uyarıları döndürür (modül tablosu).

    `icerik`: `edit`'te gönderilen içerik (`icerik_hash` onun hash'idir); `approve`'da `None`
    (case'in güncel içeriği).
    """
    if istisna_turu is not None and istisna_turu not in ORACLE_ISTISNA_TUR:
        raise InvalidDecision("oracle_istisna_turu 'uyumsuz' ya da 'kontrolsuz' olmalı")
    sakli = dict(tc.icerik)
    gonderilen = sakli if icerik is None else dict(icerik)
    ai = service.ai_icerikleri(session, [tc]).get(tc.id)
    yuksek = any(dogrulama.yuksek_risk_mi(x) for x in (sakli, ai, gonderilen))

    _tablolari_kilitle(session, tc)
    ac_refs = service.ac_refleri(sakli, gonderilen)
    kapsayan = service.kapsayan_tablolar(session, tc, gonderilen, ac_refs=ac_refs)
    dusurme = _dusurme(session, tc, icerik_hash, sakli, ai, gonderilen, kapsayan)
    try:
        uyarilar = _kapi(
            session,
            tc,
            icerik_hash,
            istisna_gerekce,
            user,
            gonderilen,
            istisna_turu,
            yuksek or dusurme is not None,
            kapsayan,
            ac_refs,
        )
    except WorkflowError:
        if dusurme is not None:
            # Engellenen düşürme denemesi de denetlenir (istek geri alınır; ayrı işlem).
            with session_scope() as s:
                audit_on_commit(
                    s,
                    user.kullanici_adi,
                    "oracle.dusurme",
                    f"test_case:{tc.id}",
                    {**dusurme, "engellendi": True},
                )
        raise
    if dusurme is not None:
        audit_on_commit(
            session,
            user.kullanici_adi,
            "oracle.dusurme",
            f"test_case:{tc.id}",
            {**dusurme, "engellendi": False},
        )
    return uyarilar


def _kapi(
    session: Session,
    tc: TestCase,
    icerik_hash: str,
    istisna_gerekce: str | None,
    user: Principal,
    gonderilen: Mapping[str, Any],
    istisna_turu: str | None,
    zorunlu: bool,
    kapsayan: list[KararTablosu],
    ac_refs: list[str],
) -> list[str]:
    if not kapsayan:
        return []
    hashler = tablo_hashleri(kapsayan)
    kayit = service.gecerli_kayit(session, tc, icerik_hash, kapsayan, lock=True)
    if kayit is None:
        if not zorunlu:
            return []
        _kontrolu_baslat(
            tc,
            icerik_hash,
            gonderilen,
            ac_refs,
            service.tablo_ozeti(hashler),
            service.kayit_damgasi(service.kayit_bul(session, tc.id, icerik_hash)),
        )
        raise OracleBekleniyor(
            "Yüksek riskli case'in karar tablosu kontrolü henüz bitmedi; kontrol kuyruğa alındı, "
            "birkaç saniye sonra yeniden deneyin"
        )
    if kayit.sonuc in (dogrulama.UYUMLU, dogrulama.KAPSAM_DISI):
        return []
    ozet = dogrulama.ozet(kayit.sonuc, kayit.ayrintilar)
    if kayit.sonuc == dogrulama.KISMEN:
        return _uyar(session, tc, icerik_hash, user, UYARI_KISMEN.format(ozet=ozet))
    gerekli = service.istisna_turu(kayit.sonuc)
    uyari = (
        UYARI_KONTROL_EDILEMEDI if gerekli == "kontrolsuz" else UYARI_UYUSMAZLIK.format(ozet=ozet)
    )
    if not zorunlu:
        return _uyar(session, tc, icerik_hash, user, uyari)
    if istisna_turu is not None and istisna_turu != gerekli:
        raise InvalidDecision(
            f"İstisna türü '{istisna_turu}' bu kontrol sonucuna uymuyor (gereken: '{gerekli}'); "
            "sayfayı yenileyin"
        )
    gerekce = (istisna_gerekce or "").strip()
    if gerekce:
        hata = gerekce_hatasi(gerekce)
        if hata:
            raise InvalidDecision(hata)
        if user.id is None:
            raise InvalidDecision("istisna yalnızca oturumlu kullanıcıyla verilir")
        _istisna_yaz(session, tc, kayit, icerik_hash, gerekli, gerekce, user, gonderilen, hashler)
        return []
    onceki = service.gecerli_istisna(session, tc.id, icerik_hash, gerekli, hashler)
    if onceki is not None:
        return []
    if gerekli == "kontrolsuz":
        raise OracleKontrolsuz(
            "Yüksek riskli case'in beklenen değerleri karar tablosuyla kontrol edilemedi: "
            f"{ozet} Case'i düzeltin ya da gerekçe yazarak (kontrolsüz onay) onaylayın"
        )
    raise OracleUyumsuz(
        f"Yüksek riskli case onaylanamaz: {ozet} Case'i düzeltin ya da gerekçeli istisnayla "
        "onaylayın"
    )


def _dusurme(
    session: Session,
    tc: TestCase,
    icerik_hash: str,
    sakli: Mapping[str, Any],
    ai: Mapping[str, Any] | None,
    gonderilen: Mapping[str, Any],
    kapsayan: list[KararTablosu],
) -> dict[str, Any] | None:
    """Riski ya da kapsanan tabloyu düşüren düzeltmenin `oracle.dusurme` özeti (V11); yoksa None."""
    if gonderilen is sakli:
        return None
    risk = (dogrulama.yuksek_risk_mi(sakli) or dogrulama.yuksek_risk_mi(ai)) and not (
        dogrulama.yuksek_risk_mi(gonderilen)
    )
    yalniz = {str(t.id) for t in service.kapsayan_tablolar(session, tc, gonderilen)}
    dusen = [t for t in kapsayan if str(t.id) not in yalniz]
    if not risk and not dusen:
        return None
    return {
        "icerik_hash": icerik_hash,
        "risk": {
            "once": sakli.get("risk") or sakli.get("priority"),
            "sonra": gonderilen.get("risk") or gonderilen.get("priority"),
        }
        if risk
        else None,
        "dusen_tablolar": [{"id": str(t.id), "ad": t.icerik.get("ad")} for t in dusen],
        "ac_refs": {
            "once": list(sakli.get("acceptance_criteria_refs") or []),
            "sonra": list(gonderilen.get("acceptance_criteria_refs") or []),
        },
    }


def _istisna_yaz(
    session: Session,
    tc: TestCase,
    kayit: Any,
    icerik_hash: str,
    tur: str,
    gerekce: str,
    user: Principal,
    icerik: Mapping[str, Any],
    hashler: Mapping[str, str],
) -> None:
    assert user.id is not None
    istisna = service.istisna_kaydet(session, tc, icerik_hash, tur, gerekce, user.id, hashler)
    # Geriye uyum: kontrol satırının istisna kolonları (sayımlar `oracle_istisna`'dan).
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
            "istisna_id": istisna.id,
            "tur": tur,
            "risk": icerik.get("risk") or icerik.get("priority"),
            "gerekce": gerekce,
            "uyusmayan": [k for k in service.karsilastirmalar(kayit) if not k["uyumlu"]],
        },
    )


def _uyar(
    session: Session, tc: TestCase, icerik_hash: str, user: Principal, uyari: str
) -> list[str]:
    audit_on_commit(
        session,
        user.kullanici_adi,
        "oracle.warning",
        f"test_case:{tc.id}",
        {"icerik_hash": icerik_hash, "uyari": uyari},
    )
    return [uyari]
