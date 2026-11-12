"""Onay kapısı (012 ANALIZ §4.3, §13; K3, K10, K11, V1, V3, V11; review 2): `cases.service.decide`
approve / edit.

"Zorunlu" = yüksek risk (kalıcı taban ya da gönderilen içerik; `dogrulama.yuksek_risk_mi`) ya da
düşürme (aşağıda).

| Durum | Zorunlu | Diğer |
|---|---|---|
| `uyumlu`, `kapsam_disi` | onay | onay |
| `kismen`, nedeni yalnız `eksik_girdi` (K11) | onay + uyarı | onay + uyarı |
| `kismen`, başka nedenli (g2 Y4), gerekçe yok | 422 `oracle_kontrolsuz` | onay + uyarı |
| `uyumsuz`, istisna yok | 422 `oracle_uyumsuz` | onay + uyarı |
| `kontrol_edilemedi`, gerekçe yok (K10) | 422 `oracle_kontrolsuz` | onay + uyarı |
| gerekçe ya da aynı tür + tablolarla önceki istisna | onay; `oracle_istisna` | onay + uyarı |
| kontrol kaydı yok, kapsayan tablo var | 409 `oracle_bekleniyor` (V3) | onay |
| kapsayan tablo yok | onay | onay |

- Kalıcı taban (review 2 g2 Y2, Y3; `service.Taban`): risk ve AC atıfları case'in tarihindeki
  tüm içeriklerden (AI özgün, her düzeltmenin önce/sonra içeriği, türetilmiş case'te kaynak case)
  gelir. Kapsayan tablolar `taban ∪ gönderilen` AC'lerinden (tek kural, t2 N8); iki adımda
  (önce doğru değerle AC/risk düşür, sonra yanlış değer yaz) kapı aşılamaz.
- Kapı gereksinimin onaylı / PO bekleyen tablolarını `id` sırasıyla `FOR SHARE` kilitler (t2 N5).
- Düşürme: içerik riski ya da kapsanan bir tabloyu tabanın altına indiriyorsa `oracle.dusurme`
  denetim kaydı yazılır ve kapı "zorunlu" çalışır.
- Görülen kayıt (g2 Y9): karar gövdesindeki `oracle_kayit_damgasi` verilirse güncel geçerli
  kaydın damgasına (`service.kayit_damgasi`) eşit olmalı; değilse 409 `oracle_kayit_degisti`.
  Gerekçe verildiyse `oracle_istisna_turu` zorunludur (422 `gecersiz_karar`).
- İstisna (V1, V10): gerekçe boşluk atılınca ≥ 20 karakter ve ≥ 10 harf; verilen tür sonuca
  uymazsa 422. Geçerli istisna append-only `oracle_istisna`'ya (geriye uyum için kontrol satırına
  da) yazılır ve `oracle.exception` olarak denetlenir. Uyuşmazlık yoksa gerekçe yok sayılır. Aynı
  içerik, tür ve tablo kümesi için önceki istisna yeniden gerekçe istemez (S1, ürün sahibi
  kararı); kullanımı `oracle.exception_reused` ile denetlenir, `istisna_id` karar kaydına yazılır.
- 409'da kontrol ayrı işlemde kuyruğa alınır (istek geri alınsa da iş kalır); anahtarın canlı işi
  varsa ikinci bağlantı açılmaz. Hız sınırı `service.kontrol_kuyruga_al`'dadır (429). Geçici
  nedenli kayıt (`cagri_hatasi`, `replay_miss`) kullanılır ve yeniden kontrol istenir (g2 Y5).
- Uyarılar karar kaydına (`review.duzeltme_olculeri.oracle_uyarilari`) yazılır ve case'in
  `uyarilar` listesinde görünür; ayrıca `oracle.warning` olarak denetlenir.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.features.karar_tablosu.hatalar import (
    OracleBekleniyor,
    OracleKayitDegisti,
    OracleKontrolsuz,
    OracleUyumsuz,
)
from tp_core.features.oracle import dogrulama, service
from tp_core.features.oracle.tablolar import tablo_hashleri
from tp_core.models import CaseOracleKontrol, KararTablosu, TestCase, session_scope
from tp_core.models.enums import ORACLE_ISTISNA_TUR
from tp_core.workflow.service import InvalidDecision, Principal, WorkflowError

ISTISNA_EN_AZ = 20
ISTISNA_EN_AZ_HARF = 10
_HARF = re.compile(r"[^\W\d_]")
# Kapının kilitlediği tablo durumları (review 2 t2 N5): yalnız kontrolü etkileyebilecekler.
KILITLI_DURUMLAR = ("approved", "pending_po")

UYARI_KONTROL_EDILEMEDI = (
    "Case'in beklenen değerleri karar tablosuyla kontrol edilemedi "
    "(case'ten karşılaştırılabilir değer çıkarılamadı); onay kontrolsüz verildi."
)
UYARI_KISMEN = "Beklenen değerler karar tablosuyla yalnız kısmen kontrol edildi: {ozet}"
UYARI_UYUSMAZLIK = "Beklenen değer onaylı karar tablosuyla uyuşmuyor, onay uyarıyla verildi: {ozet}"


@dataclass
class KapiSonucu:
    """Kapının kararı: kayda geçecek uyarılar ve kullanılan istisna (yeni yazılan ya da yeniden
    kullanılan; review 2 g2 Y11 — `review.duzeltme_olculeri.oracle_istisna_id`)."""

    uyarilar: list[str] = field(default_factory=list)
    istisna_id: uuid.UUID | None = None
    istisna_yeniden: bool = False


def gerekce_hatasi(gerekce: str) -> str | None:
    """İstisna gerekçesinin kuralı (§13.2): ≥ 20 karakter ve ≥ 10 harf. Hata metni ya da None."""
    if len(gerekce) < ISTISNA_EN_AZ or len(_HARF.findall(gerekce)) < ISTISNA_EN_AZ_HARF:
        return (
            f"İstisna gerekçesi en az {ISTISNA_EN_AZ} karakter ve {ISTISNA_EN_AZ_HARF} harf "
            "olmalı (karar tablosu kontrolü)"
        )
    return None


def _kontrolu_baslat(
    session: Session,
    tc: TestCase,
    icerik_hash: str,
    icerik: Mapping[str, Any] | None,
    ac_refs: list[str],
    anahtar: str,
    user: Principal,
    *,
    sinir_hatasi: bool,
) -> None:
    """Kontrolü AYRI işlemde kuyruğa alır (istek geri alınınca iş kaybolmasın). Anahtarın canlı
    işi zaten varsa ikinci bağlantı açılmaz (review 2 t2 N14 / mimari 19). Hız sınırı
    `kontrol_kuyruga_al`'dadır (g2 Y6)."""
    if service.canli_is_var(session, anahtar):
        return
    gonderilen = None if icerik_hash == tc.icerik_hash else icerik
    with session_scope() as s:
        service.kontrol_kuyruga_al(
            s,
            tc.id,
            icerik_hash,
            gonderilen,
            ac_refs=ac_refs,
            idempotency_key=anahtar,
            isteyen_id=user.id,
            sinir_hatasi=sinir_hatasi,
        )


def _tablolari_kilitle(session: Session, tc: TestCase) -> None:
    """Gereksinimin onaylı / PO onayı bekleyen tablolarını `FOR SHARE` kilitler (review 1
    güvenlik 4): karar verilirken tablo onaylanamaz / yeniden açılamaz. Kilit sırası `id`'dir;
    `karar_tablosu`'nun çok satırlı her kilitleyicisi aynı sırayı kullanır (review 2 t2 N5;
    taslaklar kilitlenmez: AI taslaklarını geçersiz kılan iş yalnız taslakları kilitler)."""
    session.execute(
        select(KararTablosu.id)
        .where(
            KararTablosu.requirement_id == tc.requirement_id,
            KararTablosu.durum.in_(KILITLI_DURUMLAR),
        )
        .order_by(KararTablosu.id)
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
    kayit_damgasi: str | None = None,
) -> KapiSonucu:
    """Onay kapısı; engel yoksa kayda geçecek uyarıları ve kullanılan istisnayı döndürür.

    `icerik`: `edit`'te gönderilen içerik (`icerik_hash` onun hash'idir); `approve`'da `None`
    (case'in güncel içeriği). `kayit_damgasi`: analistin gördüğü kontrol kaydının damgası
    (`oracle.damga`); verilirse güncel kaydınkine eşit olmalı (409 `oracle_kayit_degisti`).
    Gerekçe verilirse `istisna_turu` zorunludur (422 `gecersiz_karar`; review 2 g2 Y9).
    """
    if istisna_turu is not None and istisna_turu not in ORACLE_ISTISNA_TUR:
        raise InvalidDecision("oracle_istisna_turu 'uyumsuz' ya da 'kontrolsuz' olmalı")
    if (istisna_gerekce or "").strip() and istisna_turu is None:
        raise InvalidDecision(
            "Gerekçe verildiğinde istisna türü (oracle_istisna_turu: 'uyumsuz' | "
            "'kontrolsuz') da gönderilmeli"
        )
    sakli = dict(tc.icerik)
    gonderilen = sakli if icerik is None else dict(icerik)
    taban = service.tabanlar(session, [tc])[tc.id]
    yuksek = taban.yuksek or dogrulama.yuksek_risk_mi(gonderilen)

    _tablolari_kilitle(session, tc)
    ac_refs = service.kontrol_refleri(taban, gonderilen)
    kapsayan = service.kapsayan_tablolar(session, tc, gonderilen, taban=taban)
    dusurme = _dusurme(session, tc, icerik_hash, sakli, taban, gonderilen, kapsayan)
    try:
        sonuc = _kapi(
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
            kayit_damgasi,
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
    return sonuc


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
    gorulen_damga: str | None,
) -> KapiSonucu:
    hashler = tablo_hashleri(kapsayan) if kapsayan else {}
    kayit = (
        service.gecerli_kayit(session, tc, icerik_hash, kapsayan, lock=True) if kapsayan else None
    )
    if gorulen_damga is not None and gorulen_damga != service.kayit_damgasi(kayit):
        raise OracleKayitDegisti(
            "Karar tablosu kontrolü siz baktıktan sonra yeniden hesaplandı; case'i yenileyip "
            "güncel sonuca göre karar verin"
        )
    if not kapsayan:
        return KapiSonucu()
    # İş anahtarı satırın gerçek sürümüyle (geçersiz de olsa): A → B → A'da yeni iş açılır.
    ham = kayit if kayit is not None else service.kayit_bul(session, tc.id, icerik_hash)
    anahtar = service.kontrol_anahtari(
        "kapi", tc.id, icerik_hash, service.tablo_ozeti(hashler), service.kayit_damgasi(ham)
    )
    if kayit is None:
        if not zorunlu:
            return KapiSonucu()
        _kontrolu_baslat(
            session, tc, icerik_hash, gonderilen, ac_refs, anahtar, user, sinir_hatasi=True
        )
        raise OracleBekleniyor(
            "Yüksek riskli case'in karar tablosu kontrolü henüz bitmedi; kontrol kuyruğa alındı, "
            "birkaç saniye sonra yeniden deneyin"
        )
    if service.gecici_mi(kayit):
        # Geçici neden (çağrı hatası / REPLAY kaydı yok): kayıt kullanılır, yeniden kontrol
        # hız sınırıyla istenir (review 2 g2 Y5).
        _kontrolu_baslat(
            session, tc, icerik_hash, gonderilen, ac_refs, anahtar, user, sinir_hatasi=False
        )
    if kayit.sonuc in (dogrulama.UYUMLU, dogrulama.KAPSAM_DISI):
        return KapiSonucu()
    ozet = dogrulama.ozet(kayit.sonuc, kayit.ayrintilar)
    gerekli = service.istisna_turu(kayit.sonuc, kayit.ayrintilar)
    if gerekli is None:  # yalnız eksik girdi yüzünden kısmen
        return _uyar(session, tc, icerik_hash, user, UYARI_KISMEN.format(ozet=ozet))
    if kayit.sonuc == dogrulama.KISMEN:
        uyari = UYARI_KISMEN.format(ozet=ozet)
    elif gerekli == "kontrolsuz":
        uyari = UYARI_KONTROL_EDILEMEDI
    else:
        uyari = UYARI_UYUSMAZLIK.format(ozet=ozet)
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
        istisna_id = _istisna_yaz(
            session, tc, kayit, icerik_hash, gerekli, gerekce, user, gonderilen, hashler
        )
        return KapiSonucu(istisna_id=istisna_id)
    onceki = service.gecerli_istisna(session, tc.id, icerik_hash, gerekli, hashler)
    if onceki is not None:
        # S1 (ürün sahibi): aynı tür, içerik ve tablo kümesiyle verilmiş geçerli istisna yeniden
        # gerekçe istemez; kullanımı iz bırakır (review 2 g2 Y11).
        audit_on_commit(
            session,
            user.kullanici_adi,
            "oracle.exception_reused",
            f"test_case:{tc.id}",
            {
                "icerik_hash": icerik_hash,
                "kontrol_id": kayit.id,
                "istisna_id": onceki.id,
                "tur": gerekli,
            },
        )
        return KapiSonucu(istisna_id=onceki.id, istisna_yeniden=True)
    if gerekli == "kontrolsuz":
        neden = (
            "yalnız kısmen kontrol edilebildi"
            if kayit.sonuc == dogrulama.KISMEN
            else "kontrol edilemedi"
        )
        raise OracleKontrolsuz(
            f"Yüksek riskli case'in beklenen değerleri karar tablosuyla {neden}: {ozet} "
            "Case'i düzeltin ya da gerekçe yazarak (kontrolsüz onay) onaylayın"
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
    taban: service.Taban,
    gonderilen: Mapping[str, Any],
    kapsayan: list[KararTablosu],
) -> dict[str, Any] | None:
    """Riski ya da kapsanan tabloyu kalıcı tabanın altına düşüren içeriğin `oracle.dusurme`
    özeti (V11; review 2 g2 Y2/Y3: taban saklı içerikle sınırlı değildir, onay da denetlenir);
    yoksa None."""
    risk = taban.yuksek and not dogrulama.yuksek_risk_mi(gonderilen)
    yalniz = {
        str(t.id)
        for t in service.kapsayan_tablolar(
            session, tc, gonderilen, ac_refs=service.ac_refleri(gonderilen)
        )
    }
    dusen = [t for t in kapsayan if str(t.id) not in yalniz]
    if not risk and not dusen:
        return None
    return {
        "icerik_hash": icerik_hash,
        "risk": {
            "once": sakli.get("risk") or sakli.get("priority"),
            "sonra": gonderilen.get("risk") or gonderilen.get("priority"),
            "taban": list(taban.riskler),
        }
        if risk
        else None,
        "dusen_tablolar": [{"id": str(t.id), "ad": t.icerik.get("ad")} for t in dusen],
        "ac_refs": {
            "once": list(sakli.get("acceptance_criteria_refs") or []),
            "sonra": list(gonderilen.get("acceptance_criteria_refs") or []),
            "taban": sorted(taban.ac_refs),
        },
    }


def _istisna_yaz(
    session: Session,
    tc: TestCase,
    kayit: CaseOracleKontrol,
    icerik_hash: str,
    tur: str,
    gerekce: str,
    user: Principal,
    icerik: Mapping[str, Any],
    hashler: Mapping[str, str],
) -> uuid.UUID:
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
    return istisna.id


def _uyar(
    session: Session, tc: TestCase, icerik_hash: str, user: Principal, uyari: str
) -> KapiSonucu:
    audit_on_commit(
        session,
        user.kullanici_adi,
        "oracle.warning",
        f"test_case:{tc.id}",
        {"icerik_hash": icerik_hash, "uyari": uyari},
    )
    return KapiSonucu(uyarilar=[uyari])
