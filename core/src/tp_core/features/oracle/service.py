"""Beklenen sonuç kontrolü servis katmanı (012 ANALIZ §4.3, §13): iş, kayıt, geçerlilik, görünüm.

- `run_check_case` (`oracle.check_case` işi, worker): kapsayan tabloları bulur; yoksa
  `kapsam_disi` (model çağrılmaz). Varsa `case_facts` çağrısı → deterministik doğrulama ve
  karşılaştırma (`dogrulama`) → `case_oracle_kontrol`'e `(test_case_id, icerik_hash)` anahtarıyla
  yazar (upsert; `tp_app`'in DELETE yetkisi yoktur). Case içeriğine asla dokunmaz.
  - Aynı `(case, hash)` için eşzamanlı iki iş tek model çağrısı yapar (oturum düzeyi advisory
    lock; ikincisi bekler, sonra önbellekten döner).
  - Yazım anında kapsayan tablolar yeniden okunur; iş sürerken tablo kümesi değiştiyse sonuç
    bayattır ve yazılmaz (review 1 S6: yavaş eski iş yeniyi ezmez).
  - Model çağrısı son denemede de başarısızsa `kontrol_edilemedi` + `ayrintilar.neden =
    "cagri_hatasi"` yazılır (kapı kalıcı 409'da kalmaz; K10). REPLAY-MISS `neden: replay_miss`.
  - Yük `ac_refs` taşıyabilir: düzeltme / önerilen içerikte kapsayan tablolar saklı ∪ gönderilen
    AC ref'lerinden hesaplanır (V11); yoksa içeriğin kendi ref'leri.
  - Onaylı / yayınlı case'in güncel içeriği (geçerli istisnası olmadan) `uyumsuz` çıkarsa
    `oracle.onayli_uyumsuz` olayı ve denetim kaydı yazılır; Kontrol Kulesi listeler.
- `run_check_requirement` (`oracle.check_requirement` işi): gereksinimin `draft` / `approved` /
  `published` case'leri için (güncel içerik ve varsa düzeltilmemiş AI içeriği) `oracle.check_case`
  açar. `gereksinim_kontrolu_kuyruga_al` gereksinim başına tek bekleyen işe birleştirir.
- Geçerlilik: kayıt yalnız `tablo_hashleri` güncel kapsayan tabloların `{id: icerik_hash}`
  eşlemesine eşitken geçerlidir; değilse yok sayılır ve yeniden hesaplanır.
- İstisnalar append-only `oracle_istisna`'dadır (V10); bir istisna yalnız aynı `(case, hash,
  tur)` ve aynı tablo kümesi için geçerlidir.
- `case_oracle_ozetleri`: `serialize_cases`'in `oracle` alanı (toplu sorgular).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit, content_hash
from tp_core.events.bus import publish_tx
from tp_core.features.karar_tablosu.hatalar import OracleKontrolSiniri
from tp_core.features.oracle import cikarma, dogrulama
from tp_core.features.oracle.tablolar import (
    ac_normalize,
    gecerli_tablolar,
    kapsayanlar,
    tablo_hashleri,
    tablo_ref,
)
from tp_core.models import (
    AppUser,
    CaseOracleKontrol,
    KararTablosu,
    MetamorfikTuretme,
    OracleIstisna,
    Requirement,
    Review,
    TestCase,
    session_scope,
)
from tp_core.ports import ModelGateway
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue, idempotency_lock

CHECK_CASE_JOB = "oracle.check_case"
CHECK_REQUIREMENT_JOB = "oracle.check_requirement"
OLAY = "oracle.checked"
OLAY_ONAYLI_UYUMSUZ = "oracle.onayli_uyumsuz"
# Yeni tablo / üretim sonrası kontrol edilen case durumları (§4.3 "Ne zaman koşar"; review 1:
# yayınlı case'ler de yeniden denetlenir). `ready`: Testçinin kabul ettiği, Analist son onayını
# bekleyen case (012 rol modeli; son onay da kapıdan geçer).
KONTROL_DURUMLARI = ("draft", "ready", "approved", "published")
ONAYLI_DURUMLAR = ("approved", "published")
# `check_requirement` birleştirme: gereksinim başına tek bekleyen iş, kısa gecikmeyle (art arda
# gelen tablo olayları tek taramada toplanır). `TP_ORACLE_BIRLESTIRME_S` ile değişir (testler 0).
GEREKSINIM_GECIKME_S = 2.0
# Başarısız / iptal edilmiş iş idempotens anahtarını kilitlemez: yeni deneme son eki alır. Kayıt
# yazmadan biten (`done`, sonucu `atlandi`) iş de kilitlemez (review 2 t2 N1).
BITMIS_IS = ("failed", "cancelled")
NEDEN_CAGRI_HATASI = "cagri_hatasi"
NEDEN_REPLAY_MISS = "replay_miss"
# Geçici nedenli kayıt (model çağrısı hatası, REPLAY kaydı yok) gösterilir ve kapıda kullanılır
# ama önbellek sayılmaz: yeniden kontrol (hız sınırıyla) kuyruğa alınabilir (review 2 g2 Y5).
GECICI_NEDENLER = (NEDEN_CAGRI_HATASI, NEDEN_REPLAY_MISS)
# Hız sınırı (review 2 g2 Y6, t2 N10): son bir dakikada açılan yeni `oracle.check_case` işi.
# Var olan anahtarın işi sınıra takılmaz. Sayım gereksinim başına advisory lock altında (atomik).
DAKIKA_SINIRI_CASE = 10
DAKIKA_SINIRI_GEREKSINIM = 120
DAKIKA_SINIRI_KULLANICI = 30

GatewayFactory = Callable[[Engine], ModelGateway]


def _varsayilan_gecit(engine: Engine) -> ModelGateway:
    """Case üretimiyle aynı geçit fabrikası (testlerin `set_gateway_factory`'si de buraya düşer)."""
    from tp_core.features.cases import service as cases_service

    return cases_service._gateway_factory(engine)


_gateway_factory: GatewayFactory = _varsayilan_gecit


def set_gateway_factory(factory: GatewayFactory | None) -> None:
    """Testler için geçit fabrikası (None → case üretiminin fabrikası)."""
    global _gateway_factory
    _gateway_factory = factory or _varsayilan_gecit


# ------------------------------------------------------------------ yardımcılar


def tablo_gorunumu(tablo: KararTablosu) -> dogrulama.Tablo:
    return dogrulama.Tablo(
        str(tablo.id), tablo_ref(tablo), str(tablo.icerik.get("ad") or ""), tablo.icerik
    )


def tablo_ozeti(hashler: Mapping[str, str]) -> str:
    """İdempotens anahtarı için tablo kümesinin kısa özeti."""
    return hashlib.sha256(json.dumps(dict(hashler), sort_keys=True).encode()).hexdigest()[:16]


def ac_refleri(*icerikler: Mapping[str, Any] | None) -> list[str]:
    """İçeriklerin AC atıflarının birleşimi (normalize, sıralı; V11 saklı ∪ gönderilen)."""
    out: set[str] = set()
    for icerik in icerikler:
        out |= {ac_normalize(r) for r in (icerik or {}).get("acceptance_criteria_refs") or []}
    return sorted(out)


def kayit_bul(
    session: Session, case_id: uuid.UUID, icerik_hash: str, *, lock: bool = False
) -> CaseOracleKontrol | None:
    q = select(CaseOracleKontrol).where(
        CaseOracleKontrol.test_case_id == case_id, CaseOracleKontrol.icerik_hash == icerik_hash
    )
    if lock:
        q = q.with_for_update()
    return session.scalars(q).first()


def kayit_damgasi(kayit: CaseOracleKontrol | None) -> str:
    """İş anahtarı için mevcut kaydın sürümü: kayıt yoksa `yok`, varsa son yeniden hesaplama
    zamanı (`guncelleme`; `olusturma` ilk yazımdır ve değişmez — review 1 mimari 17).

    Tablo özeti tek başına yetmez: tablo önceki bir içeriğe dönünce (A → B → A) anahtar ilk A
    işiyle çakışır, yeni iş açılmaz ve satır B'de kalır (kayıt hiç geçerli olmaz)."""
    if kayit is None:
        return "yok"
    damga = kayit.guncelleme or kayit.olusturma
    return damga.isoformat() if damga is not None else "yok"


def gecerli_mi(kayit: CaseOracleKontrol | None, kapsayan: Sequence[KararTablosu]) -> bool:
    """Kayıt güncel kapsayan tablolarla mı yapılmış (gösterim, kapı ve metrik için geçerli)."""
    return kayit is not None and dict(kayit.tablo_hashleri or {}) == tablo_hashleri(kapsayan)


def gecici_mi(kayit: CaseOracleKontrol | None) -> bool:
    """Kaydın nedeni geçici mi (`cagri_hatasi` / `replay_miss`; review 2 g2 Y5)."""
    return kayit is not None and (kayit.ayrintilar or {}).get("neden") in GECICI_NEDENLER


def onbellek_mi(kayit: CaseOracleKontrol | None, kapsayan: Sequence[KararTablosu]) -> bool:
    """Kayıt yeniden kontrolü gereksiz kılar mı: geçerli ve nedeni geçici değil (review 2 g2 Y5).
    Geçici nedenli kayıt gösterilir/kapıda kullanılır ama işler onu yeniden hesaplar."""
    return gecerli_mi(kayit, kapsayan) and not gecici_mi(kayit)


# ------------------------------------------------------------------ kalıcı taban (risk, AC)


@dataclass(frozen=True)
class Taban:
    """Case'in kalıcı risk ve AC tabanı (review 2 g2 Y2, Y3).

    Taban = case'in tarihindeki tüm içerikler: güncel içerik + her `edit` kararının `review.once`
    ve `review.sonra` içeriği (ilk `once` AI'ın özgün içeriğidir; önceden onaylanmış her içerik
    bunlardan biridir). Metamorfik türetilmiş case'te kaynak case'in tabanı da "özgün" sayılır
    (`metamorfik_turetme`). Kolon eklenmedi: review append-only olduğundan taban geri alınamaz.

    - `ac_refs`: içeriklerin AC atıflarının birleşimi (normalize). Bir `(case, hash)` her zaman
      `taban.ac_refs ∪ içeriğin AC'leri` ile değerlendirilir (tek tablo kümesi kuralı; t2 N8).
    - `yuksek`: içeriklerden biri yüksek riskliyse (ya da v3 P1) kapı zorunludur; düzeltme riski
      tabandan aşağı çekemez."""

    ac_refs: frozenset[str]
    yuksek: bool
    riskler: tuple[str, ...] = ()


def _review_icerikleri(
    session: Session, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    out: dict[uuid.UUID, list[dict[str, Any]]] = {i: [] for i in ids}
    if not ids:
        return out
    for nesne_id, once, sonra in session.execute(
        select(Review.nesne_id, Review.once, Review.sonra)
        .where(
            Review.nesne_turu == "test_case",
            Review.nesne_id.in_(list(ids)),
            Review.karar == "edit",
        )
        .order_by(Review.sira)
    ).all():
        for taraf in (once, sonra):
            icerik = taraf.get("icerik") if isinstance(taraf, Mapping) else None
            if isinstance(icerik, Mapping):
                out[nesne_id].append(dict(icerik))
    return out


def tabanlar(
    session: Session, cases: Sequence[TestCase], *, _derinlik: int = 0
) -> dict[uuid.UUID, Taban]:
    """Case başına kalıcı taban (`Taban`); toplu sorgu (review'lar + türetme kaynakları)."""
    if not cases:
        return {}
    ids = [c.id for c in cases]
    icerikler: dict[uuid.UUID, list[Mapping[str, Any]]] = {c.id: [c.icerik] for c in cases}
    for cid, gecmis in _review_icerikleri(session, ids).items():
        icerikler[cid] += gecmis
    kaynak_tabani: dict[uuid.UUID, Taban] = {}
    if _derinlik < 5:
        kaynak_idleri = dict(
            session.execute(
                select(MetamorfikTuretme.turetilen_case_id, MetamorfikTuretme.kaynak_case_id).where(
                    MetamorfikTuretme.turetilen_case_id.in_(ids)
                )
            ).all()
        )
        if kaynak_idleri:
            kaynaklar = session.scalars(
                select(TestCase).where(TestCase.id.in_(set(kaynak_idleri.values())))
            ).all()
            ust = tabanlar(session, kaynaklar, _derinlik=_derinlik + 1)
            kaynak_tabani = {t: ust[k] for t, k in kaynak_idleri.items() if k in ust}
    out = {}
    for cid, liste in icerikler.items():
        refs = set(ac_refleri(*liste))
        riskler = {str(i.get("risk") or i.get("priority") or "") for i in liste} - {""}
        yuksek = any(dogrulama.yuksek_risk_mi(i) for i in liste)
        if cid in kaynak_tabani:
            k = kaynak_tabani[cid]
            refs |= k.ac_refs
            riskler |= set(k.riskler)
            yuksek = yuksek or k.yuksek
        out[cid] = Taban(frozenset(refs), yuksek, tuple(sorted(riskler)))
    return out


def kontrol_refleri(taban: Taban, icerik: Mapping[str, Any] | None = None) -> list[str]:
    """Bir içeriğin kontrol edildiği AC kümesi: taban ∪ içeriğin AC'leri (tek kural; t2 N8)."""
    return sorted(set(taban.ac_refs) | set(ac_refleri(icerik)))


def kapsayan_tablolar(
    session: Session,
    tc: TestCase,
    icerik: Mapping[str, Any] | None = None,
    *,
    ac_refs: Iterable[Any] | None = None,
    taban: Taban | None = None,
) -> list[KararTablosu]:
    """Case içeriğini kapsayan geçerli tablolar: `taban ∪ içerik` AC'leriyle (review 2 g2 Y2,
    t2 N8); `ac_refs` verilirse yalnız onunla (düşürme hesabı gibi özel durumlar)."""
    icerik = tc.icerik if icerik is None else icerik
    if ac_refs is not None:
        refs = list(ac_refs)
    else:
        taban = taban if taban is not None else tabanlar(session, [tc])[tc.id]
        refs = kontrol_refleri(taban, icerik)
    return gecerli_tablolar(session, tc.requirement_id, refs)


def gecerli_kayit(
    session: Session,
    tc: TestCase,
    icerik_hash: str,
    kapsayan: Sequence[KararTablosu],
    *,
    lock: bool = False,
) -> CaseOracleKontrol | None:
    """`(case, hash)` kaydı, yalnız güncel kapsayan tablolarla yapılmışsa."""
    kayit = kayit_bul(session, tc.id, icerik_hash, lock=lock)
    return kayit if gecerli_mi(kayit, kapsayan) else None


def ai_icerikleri(session: Session, cases: Sequence[TestCase]) -> dict[uuid.UUID, dict[str, Any]]:
    """AI'ın ürettiği (insan düzeltmesinden önceki) içerik: ilk `edit` kararının `once.icerik`'i,
    düzeltilmemişse güncel içerik. Yalnız `ai_generated` case'ler (`serialize_cases` ile aynı)."""
    ai = [c for c in cases if c.ai_generated]
    out = {c.id: dict(c.icerik) for c in ai}
    if not ai:
        return out
    goruldu: set[uuid.UUID] = set()
    for nesne_id, once in session.execute(
        select(Review.nesne_id, Review.once)
        .where(
            Review.nesne_turu == "test_case",
            Review.nesne_id.in_([c.id for c in ai]),
            Review.karar == "edit",
        )
        .order_by(Review.sira)
    ).all():
        if nesne_id in goruldu:
            continue
        goruldu.add(nesne_id)
        icerik = (once or {}).get("icerik") if isinstance(once, Mapping) else None
        if isinstance(icerik, Mapping):
            out[nesne_id] = dict(icerik)
    return out


# ------------------------------------------------------------------ istisna (append-only)


def istisna_kaydet(
    session: Session,
    tc: TestCase,
    icerik_hash: str,
    tur: str,
    gerekce: str,
    veren_id: uuid.UUID,
    hashler: Mapping[str, str],
) -> OracleIstisna:
    """`oracle_istisna`'ya yeni satır (asla güncellenmez)."""
    kayit = OracleIstisna(
        test_case_id=tc.id,
        icerik_hash=icerik_hash,
        tur=tur,
        gerekce=gerekce,
        veren_id=veren_id,
        tablo_hashleri=dict(hashler),
    )
    session.add(kayit)
    session.flush()
    return kayit


def gecerli_istisna(
    session: Session,
    case_id: uuid.UUID,
    icerik_hash: str,
    tur: str,
    hashler: Mapping[str, str],
) -> OracleIstisna | None:
    """Aynı içerik, tür ve tablo kümesi için verilmiş son istisna (yoksa None)."""
    for i in session.scalars(
        select(OracleIstisna)
        .where(
            OracleIstisna.test_case_id == case_id,
            OracleIstisna.icerik_hash == icerik_hash,
            OracleIstisna.tur == tur,
        )
        .order_by(OracleIstisna.zaman.desc(), OracleIstisna.id.desc())
    ):
        if dict(i.tablo_hashleri or {}) == dict(hashler):
            return i
    return None


def istisna_turu(sonuc: str | None, ayrintilar: Mapping[str, Any] | None = None) -> str | None:
    """Sonucun (zorunlu kapıda) gerektirdiği istisna türü: `uyumsuz` → `uyumsuz`,
    `kontrol_edilemedi` → `kontrolsuz`, nedeni yalnız `eksik_girdi` olmayan `kismen` →
    `kontrolsuz` (review 2 g2 Y4); diğerleri istisna gerektirmez."""
    if sonuc == dogrulama.UYUMSUZ:
        return "uyumsuz"
    if sonuc == dogrulama.KONTROL_EDILEMEDI or dogrulama.gerekce_gerekir_mi(sonuc, ayrintilar):
        return "kontrolsuz"
    return None


# ------------------------------------------------------------------ kuyruk


def _anahtar_kullanilabilir_mi(durum: str | None, sonuc: Any) -> bool:
    """Aynı anahtarlı iş varken anahtar yeniden kullanılabilir mi (yeni iş son ek alır):
    başarısız/iptal edilmiş ya da kayıt yazmadan bitmiş (`done` + `atlandi`) iş."""
    if durum in BITMIS_IS:
        return True
    return durum == "done" and isinstance(sonuc, Mapping) and bool(sonuc.get("atlandi"))


def _bos_anahtar(conn: Any, anahtar: str) -> tuple[str, uuid.UUID | None]:
    """Anahtarın kullanılabilir hâli ve (varsa) onu taşıyan canlı iş: aynı anahtarlı iş
    `failed`/`cancelled` ya da kayıt yazmadan bitmişse (`done` + `atlandi`; review 2 t2 N1: A → B
    → A sonrası kapı sonsuz 409'da kalmasın) `:yeniden<n>` son eki (review 1 mimari 4)."""
    aday, n = anahtar, 0
    while True:
        idempotency_lock(conn, aday)
        satir = conn.execute(
            text("SELECT id, durum, sonuc FROM job WHERE idempotency_key = :k"), {"k": aday}
        ).first()
        if satir is None:
            return aday, None
        if not _anahtar_kullanilabilir_mi(satir.durum, satir.sonuc):
            return aday, satir.id
        n += 1
        aday = f"{anahtar}:yeniden{n}"


def canli_is_var(session: Session, anahtar: str) -> bool:
    """Anahtarın (ya da `:yeniden<n>` son ekli hâlinin) yeniden kullanılamaz bir işi var mı (ana
    işlemden okunur; kapı varsa ikinci bağlantı açmaz — review 2 t2 N14 / mimari 19)."""
    for durum, sonuc in session.execute(
        text(
            "SELECT durum, sonuc FROM job WHERE idempotency_key = :k OR idempotency_key LIKE :onek"
        ),
        {"k": anahtar, "onek": anahtar.replace("%", r"\%").replace("_", r"\_") + ":yeniden%"},
    ).all():
        if not _anahtar_kullanilabilir_mi(durum, sonuc):
            return True
    return False


def _hiz_siniri(
    conn: Any, case_id: uuid.UUID, requirement_id: uuid.UUID, isteyen_id: uuid.UUID | None
) -> str | None:
    """Son bir dakikada açılan `oracle.check_case` işleri: case, gereksinim ve (verilirse)
    isteyen kullanıcı başına (review 2 g2 Y6). Gereksinim başına işlem kilidi altında sayılır
    (eşzamanlı iki istek sınırı birlikte aşamaz). Sorgular 0034'teki ifade indekslerini kullanır
    (`job_oracle_case_ix`, `job_oracle_gereksinim_ix`, `job_oracle_isteyen_ix`). Aşılırsa
    Türkçe neden, değilse None."""
    idempotency_lock(conn, f"oracle.hiz_siniri:{requirement_id}")
    sorgular = [
        ("case_id", str(case_id), DAKIKA_SINIRI_CASE, "Bu case"),
        ("requirement_id", str(requirement_id), DAKIKA_SINIRI_GEREKSINIM, "Bu gereksinim"),
    ]
    if isteyen_id is not None:
        sorgular.append(("isteyen_id", str(isteyen_id), DAKIKA_SINIRI_KULLANICI, "Siz"))
    for alan, deger, sinir, ozne in sorgular:
        son = conn.execute(
            text(
                f"SELECT count(*) FROM job WHERE tur = :t AND (yuk->>'{alan}') = :d "
                "AND olusturma > now() - interval '1 minute'"
            ),
            {"t": CHECK_CASE_JOB, "d": deger},
        ).scalar_one()
        if son >= sinir:
            return (
                f"{ozne} için son bir dakikada {son} karar tablosu kontrolü istendi; biraz "
                "bekleyip yeniden deneyin"
            )
    return None


def kontrol_kuyruga_al(
    session: Session,
    case_id: uuid.UUID,
    icerik_hash: str,
    icerik: Mapping[str, Any] | None = None,
    *,
    ac_refs: Sequence[str] | None = None,
    idempotency_key: str | None = None,
    isteyen_id: uuid.UUID | None = None,
    sinir_hatasi: bool = True,
) -> uuid.UUID | None:
    """`oracle.check_case` işini çağıranın işleminde kuyruğa alır (her kaynak için tek giriş).

    Aynı anahtarın canlı işi varsa o döner (hız sınırına takılmaz). Yeni iş hız sınırından geçer
    (`_hiz_siniri`): aşılırsa `sinir_hatasi` ise 429 `OracleKontrolSiniri`, değilse `None` (sistem
    işleri sessizce atlar; kapı bir sonraki denemede yeniden ister)."""
    conn = session.connection()
    requirement_id = session.execute(
        select(TestCase.requirement_id).where(TestCase.id == case_id)
    ).scalar_one()
    anahtar = None
    if idempotency_key:
        anahtar, mevcut = _bos_anahtar(conn, idempotency_key)
        if mevcut is not None:
            return mevcut
    neden = _hiz_siniri(conn, case_id, requirement_id, isteyen_id)
    if neden is not None:
        if sinir_hatasi:
            raise OracleKontrolSiniri(neden)
        return None
    yuk: dict[str, Any] = {
        "case_id": str(case_id),
        "requirement_id": str(requirement_id),
        "icerik_hash": icerik_hash,
    }
    if icerik is not None:
        yuk["icerik"] = dict(icerik)
    if ac_refs is not None:
        yuk["ac_refs"] = list(ac_refs)
    if isteyen_id is not None:
        yuk["isteyen_id"] = str(isteyen_id)
    return enqueue(conn, CHECK_CASE_JOB, yuk, idempotency_key=anahtar)


def kontrol_anahtari(
    tur: str, case_id: uuid.UUID, icerik_hash: str, tablo_ozeti_: str, damga: str
) -> str:
    """`(case, hash, tablo kümesi, kayıt sürümü)` başına tek iş: aynı durumda tekrar istek yeni
    model çağrısı açmaz."""
    return f"{CHECK_CASE_JOB}:{tur}:{case_id}:{icerik_hash}:{tablo_ozeti_}:{damga}"


def _gecikme_s() -> float:
    try:
        return max(0.0, float(os.environ.get("TP_ORACLE_BIRLESTIRME_S", GEREKSINIM_GECIKME_S)))
    except ValueError:
        return GEREKSINIM_GECIKME_S


def gereksinim_kontrolu_kuyruga_al(
    session: Session, requirement_id: uuid.UUID, neden: str
) -> uuid.UUID:
    """`oracle.check_requirement` (gereksinim başına tek bekleyen iş; review 1 mimari 14).

    Yalnız henüz hiç koşmamış (`queued`) işe birleşir (`neden` eklenir; review 2 g2 Y13 / t2 N6:
    `retry`'daki ya da koşan işe eklenen neden, iş kalıcı başarısız olursa kaybolurdu); yoksa
    `GEREKSINIM_GECIKME_S` sonra koşacak yeni iş açılır. Tablo onayı, yeniden açma ve case üretimi
    art arda gelince tek tarama yapılır."""
    conn = session.connection()
    idempotency_lock(conn, f"{CHECK_REQUIREMENT_JOB}:birlestir:{requirement_id}")
    mevcut = conn.execute(
        text(
            "SELECT id, yuk FROM job WHERE tur = :t AND durum = 'queued' "
            "AND yuk->>'requirement_id' = :r ORDER BY olusturma LIMIT 1 FOR UPDATE"
        ),
        {"t": CHECK_REQUIREMENT_JOB, "r": str(requirement_id)},
    ).first()
    if mevcut is not None:
        yuk = dict(mevcut.yuk or {})
        nedenler = list(yuk.get("nedenler") or [yuk.get("neden")])
        if neden not in nedenler:
            nedenler.append(neden)
            yuk["nedenler"] = [n for n in nedenler if n]
            conn.execute(
                text("UPDATE job SET yuk = CAST(:y AS jsonb) WHERE id = :i"),
                {"y": json.dumps(yuk, ensure_ascii=False), "i": mevcut.id},
            )
        return mevcut.id
    return enqueue(
        conn,
        CHECK_REQUIREMENT_JOB,
        {"requirement_id": str(requirement_id), "neden": neden},
        # Gecikme 0 ise DB saati (None → now()); uygulama ile DB saati arasındaki kayma işi
        # geciktirmesin.
        run_after=(datetime.now(UTC) + timedelta(seconds=g)) if (g := _gecikme_s()) > 0 else None,
    )


def uretim_sonrasi(session: Session, requirement_id: uuid.UUID) -> uuid.UUID | None:
    """Case yazımı kancası (`cases.service.store_cases`; portal üretimi, IDE/MCP taslakları):
    gereksinimin geçerli (onaylı, bayat olmayan) bir karar tablosu varsa case'leri için kontrol
    işlerini açar; yoksa iş açılmaz (kontrol edilecek bir şey yok).

    Tablosu olmayan gereksinimde kontrol kaydı da olmaz; ilk tablo onaylanınca Ş1'in
    `oracle.check_requirement` işi tüm case'leri (kapsamayanlar `kapsam_disi`) kaydeder.
    """
    if not gecerli_tablolar(session, requirement_id):
        return None
    return gereksinim_kontrolu_kuyruga_al(session, requirement_id, "case_uretildi")


def karar_sonrasi(session: Session, tc: TestCase) -> uuid.UUID | None:
    """`decide` (edit / reopen) kancası: case'in yeni güncel hash'i için kontrol aynı işlemde
    kuyruğa girer (review 1 mimari 5; portal `/oracle-check` çağırmasa da kayıt oluşur ve
    onaylı-uyumsuz sinyali çalışır). Kapsayan tablo yoksa iş açılmaz."""
    kapsayan = kapsayan_tablolar(session, tc)
    if not kapsayan:
        return None
    mevcut = kayit_bul(session, tc.id, tc.icerik_hash)
    if onbellek_mi(mevcut, kapsayan):
        return None
    anahtar = kontrol_anahtari(
        "karar",
        tc.id,
        tc.icerik_hash,
        tablo_ozeti(tablo_hashleri(kapsayan)),
        kayit_damgasi(mevcut),
    )
    return kontrol_kuyruga_al(
        session, tc.id, tc.icerik_hash, None, idempotency_key=anahtar, sinir_hatasi=False
    )


# ------------------------------------------------------------------ işler (worker)


def run_check_requirement(ctx: JobContext) -> dict[str, Any]:
    yuk = ctx.yuk or {}
    rid = uuid.UUID(str(yuk["requirement_id"]))
    acilan = 0
    with session_scope() as s:
        if s.get(Requirement, rid) is None:
            raise PermanentJobError("gereksinim silinmiş")
        tablolar = gecerli_tablolar(s, rid)
        cases = s.scalars(
            select(TestCase)
            .where(TestCase.requirement_id == rid, TestCase.durum.in_(KONTROL_DURUMLARI))
            .order_by(TestCase.uretim_no, TestCase.sira_no)
        ).all()
        ai = ai_icerikleri(s, cases)
        tabanlar_ = tabanlar(s, cases)
        mevcutlar = {
            (k.test_case_id, k.icerik_hash): k
            for k in s.scalars(
                select(CaseOracleKontrol).where(
                    CaseOracleKontrol.test_case_id.in_([c.id for c in cases])
                )
            )
        }
        for tc in cases:
            hedefler: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any]]] = [
                (tc.icerik_hash, None, tc.icerik)
            ]
            ai_icerik = ai.get(tc.id)
            if ai_icerik is not None and content_hash(ai_icerik) != tc.icerik_hash:
                hedefler.append((content_hash(ai_icerik), ai_icerik, ai_icerik))
            for h, gonderilen, icerik in hedefler:
                # Tek tablo kümesi kuralı: taban ∪ içerik AC'leri (t2 N8).
                kapsayan = kapsayanlar(tablolar, icerik, kontrol_refleri(tabanlar_[tc.id], icerik))
                mevcut = mevcutlar.get((tc.id, h))
                if onbellek_mi(mevcut, kapsayan):
                    continue
                anahtar = kontrol_anahtari(
                    "gereksinim",
                    tc.id,
                    h,
                    tablo_ozeti(tablo_hashleri(kapsayan)),
                    kayit_damgasi(mevcut),
                )
                if kontrol_kuyruga_al(
                    s, tc.id, h, gonderilen, idempotency_key=anahtar, sinir_hatasi=False
                ):
                    acilan += 1
    return {"kontrol_isi": acilan, "neden": yuk.get("neden"), "nedenler": yuk.get("nedenler")}


class _IcerikKilidi:
    """`(case, hash)` başına oturum düzeyi advisory lock (ayrı bağlantı; iş boyunca tutulur).
    Aynı içerik için ikinci iş, birincisi bitene kadar bekler ve önbellekten döner (çift model
    çağrısı yok; review 1 mimari 14)."""

    def __init__(self, engine: Engine, case_id: uuid.UUID, icerik_hash: str) -> None:
        self._engine = engine
        self._anahtar = f"oracle.kontrol:{case_id}:{icerik_hash}"
        self._conn: Any = None

    def __enter__(self) -> _IcerikKilidi:
        self._conn = self._engine.connect()
        self._conn.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"), {"k": self._anahtar}
        )
        return self

    def __exit__(self, *_exc: object) -> None:
        try:
            self._conn.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": self._anahtar}
            )
        finally:
            self._conn.close()


def run_check_case(
    ctx: JobContext, engine: Engine, gateway: ModelGateway | None = None
) -> dict[str, Any]:
    """`oracle.check_case`: tek case içeriğinin (güncel ya da önerilen) kontrolü."""
    yuk = ctx.yuk or {}
    cid = uuid.UUID(str(yuk["case_id"]))
    h = str(yuk["icerik_hash"])
    with _IcerikKilidi(engine, cid, h):
        return _check_case(ctx, engine, gateway, yuk, cid, h)


def _check_case(
    ctx: JobContext,
    engine: Engine,
    gateway: ModelGateway | None,
    yuk: Mapping[str, Any],
    cid: uuid.UUID,
    h: str,
) -> dict[str, Any]:
    # Yükteki `ac_refs` bilgi amaçlıdır; tablo kümesi koşu anında tek kuraldan (taban ∪ içerik)
    # hesaplanır (t2 N8: aynı `(case, hash)` her yerde aynı kümeyle değerlendirilir).
    with session_scope() as s:
        tc = s.get(TestCase, cid)
        if tc is None:
            raise PermanentJobError("case silinmiş")
        if isinstance(yuk.get("icerik"), Mapping):
            icerik = dict(yuk["icerik"])
            if content_hash(icerik) != h:
                raise PermanentJobError("önerilen içeriğin hash'i yükteki icerik_hash'e uymuyor")
        elif tc.icerik_hash == h:
            icerik = dict(tc.icerik)
        else:
            return {"atlandi": True, "neden": "case içeriği kuyruğa alındıktan sonra değişti"}
        req = s.get(Requirement, tc.requirement_id)
        kapsayan = kapsayan_tablolar(s, tc, icerik)
        hashler = tablo_hashleri(kapsayan)
        mevcut = kayit_bul(s, tc.id, h)
        if onbellek_mi(mevcut, kapsayan):
            return {"sonuc": mevcut.sonuc, "onbellek": True}  # type: ignore[union-attr]
        tablolar = [tablo_gorunumu(t) for t in kapsayan]
        story = req.jira_key if req is not None else None
        sira_no, rid = tc.sira_no, tc.requirement_id
        ai_orijinal = ai_icerikleri(s, [tc]).get(tc.id)
        ai_icerik = ai_orijinal is not None and content_hash(ai_orijinal) == h
        # Metamorfik türetilmiş case: olgular dönüşümden bilinir, model çağrılmaz (Ş6).
        turetilen = _turetilen_olgulari(s, tc) if h == tc.icerik_hash and tablolar else None
        # 013 test verisi kataloğu (dev birleşmesi): case alanları `{veri:<anahtar>}` atfı taşır.
        # Değer çıkarma ve alıntı doğrulaması case'in okunan anlamıyla (gizli olmayan değerler
        # çözülmüş) yapılır; gizli atıflar atıf kalır, modele sır gitmez. Kayıt hash'i saklanan
        # içeriğindir (değişmez).
        okunan = _veri_cozulmus(s, icerik) if tablolar and turetilen is None else icerik

    call_id: uuid.UUID | None = None
    mod: str | None = None
    cagri_hatasi: str | None = None
    if not tablolar:
        sonuc, ayrintilar = dogrulama.degerlendir(icerik, [], None)
    elif turetilen is not None:
        sonuc, ayrintilar = dogrulama.degerlendir(icerik, tablolar, turetilen)
        ayrintilar["kaynak"] = "metamorfik"
    else:
        cikti, call_id, mod, cagri_hatasi = _olgulari_cikar(
            ctx, engine, gateway, okunan, story, sira_no, tablolar
        )
        sonuc, ayrintilar = dogrulama.degerlendir(okunan, tablolar, cikti)
        if cagri_hatasi:
            ayrintilar["neden"] = NEDEN_CAGRI_HATASI
        elif mod == "replay_miss":
            ayrintilar["neden"] = NEDEN_REPLAY_MISS

    with session_scope() as s:
        tc = s.get(TestCase, cid)
        if tc is None:
            raise PermanentJobError("case silinmiş")
        # Yazım anında yeniden okunan tablo kümesi farklıysa sonuç bayattır (S6).
        guncel = tablo_hashleri(kapsayan_tablolar(s, tc, icerik))
        if guncel != hashler:
            return {"atlandi": True, "neden": "kontrol sürerken kapsayan tablolar değişti"}
        kayit = _kaydet(
            s,
            cid,
            h,
            sonuc=sonuc,
            ayrintilar=ayrintilar,
            hashler=hashler,
            ai_icerik=ai_icerik,
            call_id=call_id,
            mod=mod,
        )
        veri = {"case_id": cid, "requirement_id": rid, "icerik_hash": h, "sonuc": sonuc}
        publish_tx(s.connection(), OLAY, veri)
        audit_on_commit(
            s,
            "system",
            OLAY,
            f"test_case:{cid}",
            {
                "icerik_hash": h,
                "sonuc": sonuc,
                "tablo_hashleri": hashler,
                "ai_icerik": ai_icerik,
                "ai_call_id": call_id,
                "mode": mod,
                "atilan_olgular": ayrintilar.get("atilan_olgular", 0),
                "degerler": ayrintilar.get("degerler"),
                **({"cagri_hatasi": cagri_hatasi} if cagri_hatasi else {}),
            },
        )
        onayli_uyumsuz = _onayli_uyumsuz_sinyali(s, tc, h, sonuc, hashler)
        return {
            "sonuc": sonuc,
            "kontrol_id": str(kayit.id),
            "mode": mod,
            **({"onayli_uyumsuz": True} if onayli_uyumsuz else {}),
        }


def _veri_cozulmus(s: Session, icerik: Mapping[str, Any]) -> dict[str, Any]:
    """Gizli olmayan test verisi atıfları değerine çözülmüş içerik (013 katalog; çözülemeyen ve
    gizli atıflar olduğu gibi kalır)."""
    from tp_core.features.testveri import atif
    from tp_core.features.testveri import service as testveri

    if not atif.case_atiflari(icerik):
        return dict(icerik)
    return atif.case_coz(icerik, testveri.katalog(s), bilinmeyen="birak")


def _turetilen_olgulari(s: Session, tc: TestCase) -> Mapping[str, Any] | None:
    """`metamorfik.service.turetilen_olgulari` (türetme ürünü değilse ya da güncel içeriği
    vermiyorsa None → normal değer çıkarma)."""
    if tc.ai_generated:
        return None
    from tp_core.features.metamorfik.service import turetilen_olgulari

    return turetilen_olgulari(s, tc)


def _onayli_uyumsuz_sinyali(
    s: Session, tc: TestCase, h: str, sonuc: str, hashler: Mapping[str, str]
) -> bool:
    """Onaylı/yayınlı case'in güncel içeriği (geçerli istisnasız) `uyumsuz` çıktıysa olay +
    denetim (review 1 güvenlik 4, mimari 20; ör. tablo case onayından sonra onaylandı)."""
    if (
        sonuc != dogrulama.UYUMSUZ
        or tc.durum not in ONAYLI_DURUMLAR
        or h != tc.icerik_hash
        or gecerli_istisna(s, tc.id, h, "uyumsuz", hashler) is not None
    ):
        return False
    veri = {
        "case_id": tc.id,
        "requirement_id": tc.requirement_id,
        "icerik_hash": h,
        "durum": tc.durum,
        "baslik": tc.icerik.get("title"),
    }
    publish_tx(s.connection(), OLAY_ONAYLI_UYUMSUZ, veri)
    audit_on_commit(
        s,
        "system",
        OLAY_ONAYLI_UYUMSUZ,
        f"test_case:{tc.id}",
        {"icerik_hash": h, "durum": tc.durum, "tablo_hashleri": dict(hashler)},
    )
    return True


def _olgulari_cikar(
    ctx: JobContext,
    engine: Engine,
    gateway: ModelGateway | None,
    icerik: Mapping[str, Any],
    story: str | None,
    sira_no: int,
    tablolar: Sequence[dogrulama.Tablo],
) -> tuple[Mapping[str, Any] | None, uuid.UUID | None, str | None, str | None]:
    """`case_facts` çağrısı → (çıktı, çağrı kimliği, mod, hata). Son denemedeki herhangi bir
    çağrı hatası (ya da REPLAY kaydı yok) olgusuz sonuç verir: kapsayan tablo varken
    `kontrol_edilemedi` + `neden: cagri_hatasi` (K10; iş kalıcı başarısız olmaz, kapı 409'da
    kalmaz). Önceki denemelerde hata iş kuyruğunun yeniden denemesine bırakılır."""
    from tp_core.gateway import deterministic_call_id, find_rules_dir, load_schema
    from tp_core.gateway.errors import ReplayNotFound

    try:
        gw = gateway or _gateway_factory(engine)
        ref = cikarma.case_ref(story, sira_no)
        mesajlar = cikarma.facts_messages(
            icerik, ref, [{"ref": t.ref, "id": t.id, "icerik": t.icerik} for t in tablolar]
        )
        rules_dir = getattr(gw, "rules_dir", None) or find_rules_dir()
        result = gw.call(
            cikarma.PURPOSE,
            cikarma.BUNDLE,
            mesajlar,
            load_schema(rules_dir, cikarma.PURPOSE),
            replay_key=cikarma.replay_key_for(story, sira_no),
            call_id=deterministic_call_id(ctx.job_id, cikarma.PURPOSE),
        )
    except PermanentJobError:
        raise
    except ReplayNotFound:
        # Katı REPLAY (`TP_REPLAY_STRICT=1`) kayıt yokken `ReplayMiss` fırlatır; bu bir çağrı
        # hatası değil, gevşek kipteki nötr çıktıyla aynı anlam: `neden: replay_miss`.
        return None, None, "replay_miss", None
    except Exception as exc:
        if not ctx.son_deneme:
            raise
        return None, None, None, f"{type(exc).__name__}: {str(exc)[:300]}"
    return result.output, result.call_id, result.mode, None


def _kaydet(
    s: Session,
    cid: uuid.UUID,
    h: str,
    *,
    sonuc: str,
    ayrintilar: Mapping[str, Any],
    hashler: Mapping[str, str],
    ai_icerik: bool,
    call_id: uuid.UUID | None,
    mod: str | None,
) -> CaseOracleKontrol:
    """Upsert: kayıt varsa sonuç güncellenir (`guncelleme`; `olusturma` korunur). Tablo kümesi
    değiştiyse satırdaki (geriye uyum) istisna kolonları da düşer; istisnaların kaydı
    `oracle_istisna`'da kalır."""
    s.execute(
        pg_insert(CaseOracleKontrol)
        .values(test_case_id=cid, icerik_hash=h, sonuc=sonuc)
        .on_conflict_do_nothing(constraint="case_oracle_kontrol_case_hash_uq")
    )
    kayit = kayit_bul(s, cid, h, lock=True)
    assert kayit is not None
    if dict(kayit.tablo_hashleri or {}) != dict(hashler):
        kayit.istisna_gerekce = None
        kayit.istisna_veren_id = None
        kayit.istisna_zamani = None
    kayit.sonuc = sonuc
    kayit.ayrintilar = dict(ayrintilar)
    kayit.tablo_hashleri = dict(hashler)
    kayit.ai_icerik = ai_icerik
    kayit.ai_call_id = call_id
    kayit.uretim_modu = mod
    kayit.guncelleme = func.clock_timestamp()
    s.flush()
    s.refresh(kayit)
    return kayit


# ------------------------------------------------------------------ görünüm


def karsilastirmalar(kayit: CaseOracleKontrol) -> list[dict[str, Any]]:
    out = []
    for g in (kayit.ayrintilar or {}).get("gruplar") or []:
        for k in g.get("karsilastirmalar") or []:
            out.append(
                {
                    "tablo_id": g.get("tablo_id"),
                    "tablo_ad": g.get("tablo_ad"),
                    "satir_id": g.get("satir_id"),
                    "column": k.get("column"),
                    "alan": k.get("alan"),
                    "alinti": k.get("alinti"),
                    "case_degeri": k.get("case_degeri"),
                    "tablo_degeri": k.get("tablo_degeri"),
                    "uyumlu": k.get("uyumlu"),
                }
            )
    return out


_KAPSANMAYAN_NEDENI = {
    "sayi": "Beklenen alandaki sayı hiçbir tablo değeriyle eşlenmedi",
    "celiski": "Girdi alanındaki sayı çıkarılan değerlerle eşleşmiyor (çelişebilir)",
    "yaziyla": "Yazıyla yazılmış sayı karşılaştırılamaz",
}


def karsilastirilamayanlar(kayit: CaseOracleKontrol) -> list[dict[str, Any]]:
    """Case'te doğrulanmış ama tablonun eksik girdi yüzünden hesaplayamadığı beklenen değerler
    (`dogrulama.kismi_degerlendir`) ve tamlık denetiminde hiçbir olguyla kapsanmayan sayılar
    (beklenen alanda sayı, girdi alanında çelişebilecek sayı, yazıyla sayı; review 2 g2 Y1/Y14)."""
    ayr = kayit.ayrintilar or {}
    out = []
    for g in ayr.get("gruplar") or []:
        for o in g.get("karsilastirilamayan") or []:
            out.append(
                {
                    "tablo_id": g.get("tablo_id"),
                    "tablo_ad": g.get("tablo_ad"),
                    "column": o.get("column"),
                    "alan": o.get("field"),
                    "alinti": o.get("quote"),
                    "case_degeri": o.get("value"),
                    "neden": o.get("neden"),
                }
            )
    for k in ayr.get("kapsanmayan_sayilar") or []:
        out.append(
            {
                "tablo_id": None,
                "tablo_ad": None,
                "column": None,
                "alan": k.get("alan"),
                "alinti": k.get("alinti"),
                "case_degeri": None,
                "neden": _KAPSANMAYAN_NEDENI.get(k.get("tur"), _KAPSANMAYAN_NEDENI["sayi"]),
            }
        )
    return out


def _degerler(kayit: CaseOracleKontrol) -> dict[str, int]:
    d = dict((kayit.ayrintilar or {}).get("degerler") or {})
    if not d:  # eski kayıt: karşılaştırmalardan say
        ks = karsilastirmalar(kayit)
        d = {
            "uyumlu": sum(1 for k in ks if k["uyumlu"]),
            "uyumsuz": sum(1 for k in ks if not k["uyumlu"]),
            "karsilastirilamayan": len(karsilastirilamayanlar(kayit)),
            "atilan": int((kayit.ayrintilar or {}).get("atilan_olgular") or 0),
        }
    return {
        "uyumlu": int(d.get("uyumlu") or 0),
        "uyumsuz": int(d.get("uyumsuz") or 0),
        # Kapsanmayan sayılar da karşılaştırılmamış değerdir (§13.2 dört anahtar).
        "karsilastirilamayan": int(d.get("karsilastirilamayan") or 0)
        + int(d.get("kapsanmayan") or 0),
        "atilan": int(d.get("atilan") or 0),
    }


def istisna_gecerli_mi(istisna: OracleIstisna | None, kayit: CaseOracleKontrol | None) -> bool:
    """İstisna kapıda yeniden kullanılabilir mi (S1, §13.2): geçerli kaydın gerektirdiği türde ve
    kaydın tablo kümesiyle verilmiş."""
    if istisna is None or kayit is None:
        return False
    return istisna.tur == istisna_turu(kayit.sonuc, kayit.ayrintilar) and dict(
        istisna.tablo_hashleri or {}
    ) == dict(kayit.tablo_hashleri or {})


def istisna_sec(
    istisnalar: Sequence[OracleIstisna], kayit: CaseOracleKontrol | None
) -> OracleIstisna | None:
    """Gösterilecek istisna: geçerli olanların en yenisi, yoksa en yenisi (`zaman` sıralı liste)."""
    gecerli = [i for i in istisnalar if istisna_gecerli_mi(i, kayit)]
    if gecerli:
        return gecerli[-1]
    return istisnalar[-1] if istisnalar else None


def istisna_gorunumu(
    istisna: OracleIstisna | None,
    kullanicilar: Mapping[uuid.UUID, str],
    kayit: CaseOracleKontrol | None,
) -> dict[str, Any] | None:
    if istisna is None:
        return None
    return {
        "id": str(istisna.id),
        "tur": istisna.tur,
        "gerekce": istisna.gerekce,
        "veren": kullanicilar.get(istisna.veren_id) if istisna.veren_id else None,
        "zaman": istisna.zaman,
        # Kapı bu istisnayla yeniden gerekçe istemez (aynı tür + tablo kümesi; S1).
        "gecerli": istisna_gecerli_mi(istisna, kayit),
    }


def oracle_gorunumu(
    kayit: CaseOracleKontrol | None,
    icerik_hash: str,
    kapsayan_var: bool,
    kullanicilar: Mapping[uuid.UUID, str],
    istisnalar: Sequence[OracleIstisna] = (),
) -> dict[str, Any] | None:
    """Portal `oracle` nesnesi (§13.2 + review 2); kapsayan tablo da geçerli kayıt da yoksa
    `None`. `damga`: gösterilen kaydın sürüm damgası (`kayit_damgasi`; kayıt yoksa `yok`) —
    karar gövdesindeki `oracle_kayit_damgasi` buna eşit olmalı (g2 Y9). `kismen_nedeni`: sonuç
    `kismen` ise neden listesi (`dogrulama.KISMEN_NEDENLERI`), değilse `null` (g2 Y4)."""
    if kayit is None:
        if not kapsayan_var:
            return None
        return {
            "sonuc": None,
            "icerik_hash": icerik_hash,
            "damga": kayit_damgasi(None),
            "ozet": dogrulama.ozet(None, None),
            "karsilastirmalar": [],
            "karsilastirilamayan": [],
            "degerler": {"uyumlu": 0, "uyumsuz": 0, "karsilastirilamayan": 0, "atilan": 0},
            "kismen_nedeni": None,
            "istisna": None,
            "neden": None,
            "kontrol_suruyor": True,
        }
    istisna = istisna_sec(istisnalar, kayit)
    return {
        "sonuc": kayit.sonuc,
        "icerik_hash": icerik_hash,
        "damga": kayit_damgasi(kayit),
        "ozet": dogrulama.ozet(kayit.sonuc, kayit.ayrintilar),
        "karsilastirmalar": karsilastirmalar(kayit),
        "karsilastirilamayan": karsilastirilamayanlar(kayit),
        "degerler": _degerler(kayit),
        "kismen_nedeni": dogrulama.kismen_nedenleri(kayit.ayrintilar)
        if kayit.sonuc == dogrulama.KISMEN
        else None,
        "istisna": istisna_gorunumu(istisna, kullanicilar, kayit),
        "neden": (kayit.ayrintilar or {}).get("neden"),
        "kontrol_suruyor": False,
    }


def _kullanicilar(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(
        session.execute(select(AppUser.id, AppUser.kullanici_adi).where(AppUser.id.in_(ids))).all()
    )  # type: ignore[arg-type]


def gecerli_tablolar_toplu(
    session: Session, requirement_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[KararTablosu]]:
    """Gereksinim başına geçerli tablolar (tek kaynak `karar_tablosu.service.gecerli_tablolar`).
    Tablosu hiç olmayan gereksinimler tek sorguyla elenir. Sonuç işlem başına önbelleklenir
    (`session.info`; review 2 t2 N11: Kule'de beklenti doğruluğu ve onaylı-uyumsuz aynı
    gereksinimler için ikinci kez sorgulamaz); önbellek işlem bitince (commit/rollback) düşer."""
    ids = set(requirement_ids)
    if not ids:
        return {}
    onbellek = _tablo_onbellegi(session)
    eksik = ids - set(onbellek)
    if eksik:
        tablolu = set(
            session.scalars(
                select(KararTablosu.requirement_id)
                .where(KararTablosu.requirement_id.in_(eksik), KararTablosu.durum == "approved")
                .distinct()
            )
        )
        for rid in eksik:
            onbellek[rid] = gecerli_tablolar(session, rid) if rid in tablolu else []
    return {rid: onbellek[rid] for rid in ids}


_ONBELLEK_ANAHTARI = "oracle.gecerli_tablolar"


def _tablo_onbellegi(session: Session) -> dict[uuid.UUID, list[KararTablosu]]:
    """İşlem başına tablo önbelleği: anahtar işlem nesnesine bağlıdır (yeni işlem → boş)."""
    islem = session.get_transaction()
    kayit = session.info.get(_ONBELLEK_ANAHTARI)
    if kayit is None or kayit[0] is not islem:
        kayit = (islem, {})
        session.info[_ONBELLEK_ANAHTARI] = kayit
    return kayit[1]


def _istisna_listeleri(
    session: Session, anahtarlar: Iterable[tuple[uuid.UUID, str]]
) -> dict[tuple[uuid.UUID, str], list[OracleIstisna]]:
    """`(case, hash)` başına istisnalar (zaman sıralı; tek sorgu)."""
    anahtarlar = set(anahtarlar)
    out: dict[tuple[uuid.UUID, str], list[OracleIstisna]] = {}
    if not anahtarlar:
        return out
    for i in session.scalars(
        select(OracleIstisna)
        .where(
            OracleIstisna.test_case_id.in_({c for c, _ in anahtarlar}),
            OracleIstisna.icerik_hash.in_({h for _, h in anahtarlar}),
        )
        .order_by(OracleIstisna.zaman, OracleIstisna.id)
    ):
        if (i.test_case_id, i.icerik_hash) in anahtarlar:
            out.setdefault((i.test_case_id, i.icerik_hash), []).append(i)
    return out


def case_oracle_ozetleri(
    session: Session, cases: Sequence[TestCase]
) -> dict[uuid.UUID, dict[str, Any] | None]:
    """`serialize_cases` için case başına güncel içeriğin `oracle` nesnesi (toplu sorgularla)."""
    if not cases:
        return {}
    tablolar = gecerli_tablolar_toplu(session, {c.requirement_id for c in cases})
    tabanlar_ = tabanlar(session, cases)
    kayitlar: dict[tuple[uuid.UUID, str], CaseOracleKontrol] = {
        (k.test_case_id, k.icerik_hash): k
        for k in session.scalars(
            select(CaseOracleKontrol).where(
                CaseOracleKontrol.test_case_id.in_([c.id for c in cases]),
                CaseOracleKontrol.icerik_hash.in_({c.icerik_hash for c in cases}),
            )
        )
    }
    istisnalar = _istisna_listeleri(session, [(c.id, c.icerik_hash) for c in cases])
    kullanicilar = _kullanicilar(
        session,
        {i.veren_id for liste in istisnalar.values() for i in liste if i.veren_id is not None},
    )
    out: dict[uuid.UUID, dict[str, Any] | None] = {}
    for c in cases:
        kapsayan = kapsayanlar(
            tablolar[c.requirement_id], c.icerik, kontrol_refleri(tabanlar_[c.id], c.icerik)
        )
        kayit = kayitlar.get((c.id, c.icerik_hash))
        out[c.id] = oracle_gorunumu(
            kayit if gecerli_mi(kayit, kapsayan) else None,
            c.icerik_hash,
            bool(kapsayan),
            kullanicilar,
            istisnalar.get((c.id, c.icerik_hash), []),
        )
    return out


def case_oracle(session: Session, tc: TestCase, icerik_hash: str | None = None) -> dict[str, Any]:
    """`GET /cases/{id}/oracle`: güncel içeriğin (ya da `icerik_hash` ile önerilen içeriğin)
    kontrol sonucu.

    Önerilen içerik saklanmadığından onun AC atıfları bilinmez: kaydın kullandığı tabloların hâlâ
    geçerli ve aynı hash'te olması aranır (yeni onaylanan bir tablo burada görünmez; onay kapısı
    içerikle tam denetim yapar).
    """
    h = icerik_hash or tc.icerik_hash
    tablolar = gecerli_tablolar(session, tc.requirement_id)
    kayit = kayit_bul(session, tc.id, h)
    if h == tc.icerik_hash:
        kapsayan = kapsayanlar(
            tablolar, tc.icerik, kontrol_refleri(tabanlar(session, [tc])[tc.id], tc.icerik)
        )
        gecerli = kayit if gecerli_mi(kayit, kapsayan) else None
        kapsayan_var = bool(kapsayan)
    else:
        guncel = tablo_hashleri(tablolar)
        gecerli = (
            kayit
            if kayit is not None
            and all(guncel.get(t) == th for t, th in (kayit.tablo_hashleri or {}).items())
            else None
        )
        kapsayan_var = True  # önerilen içerik için kayıt yoksa kontrol beklenir
        kapsayan = [t for t in tablolar if str(t.id) in (kayit.tablo_hashleri if gecerli else {})]
    istisnalar = _istisna_listeleri(session, [(tc.id, h)]).get((tc.id, h), [])
    kullanicilar = _kullanicilar(
        session, {i.veren_id for i in istisnalar if i.veren_id is not None}
    )
    return {
        "case_id": str(tc.id),
        "icerik_hash": h,
        "guncel_icerik": h == tc.icerik_hash,
        "kapsayan_tablolar": [
            {
                "id": str(t.id),
                "ref": tablo_ref(t),
                "ad": t.icerik.get("ad"),
                "icerik_hash": t.icerik_hash,
            }
            for t in kapsayan
        ],
        "oracle": oracle_gorunumu(gecerli, h, kapsayan_var, kullanicilar, istisnalar),
    }


def onayli_uyumsuz(session: Session) -> list[dict[str, Any]]:
    """Kontrol Kulesi `onayli_uyumsuz` (§13.2; öğe `{case_id, requirement_id, baslik, jira_key,
    sira_no}` — portal "TPD-1 · C5" künyesi): onaylı/yayınlı case'lerden güncel içeriğinin
    geçerli kaydı `uyumsuz` olup aynı tablo kümesiyle verilmiş `uyumsuz` istisnası olmayanlar.

    Kaydı geçersizleşmiş case (tablosu yeniden açıldı / değişti / bayat) sayılmaz: geçerlilik
    güncel kapsayan tablolarla (taban ∪ içerik) denetlenir (review 2 u2 N1 çekirdek kısmı).
    Tek sorgu (uyumsuz kayıtlı onaylı case'ler) + yalnız o gereksinimlerin tabloları (işlem
    önbelleğiyle)."""
    satirlar = session.execute(
        select(TestCase, CaseOracleKontrol, Requirement.jira_key)
        .join(
            CaseOracleKontrol,
            (CaseOracleKontrol.test_case_id == TestCase.id)
            & (CaseOracleKontrol.icerik_hash == TestCase.icerik_hash),
        )
        .join(Requirement, Requirement.id == TestCase.requirement_id)
        .where(
            TestCase.durum.in_(ONAYLI_DURUMLAR),
            CaseOracleKontrol.sonuc == dogrulama.UYUMSUZ,
        )
        .order_by(TestCase.requirement_id, TestCase.uretim_no, TestCase.sira_no)
    ).all()
    if not satirlar:
        return []
    tablolar = gecerli_tablolar_toplu(session, {tc.requirement_id for tc, _, _ in satirlar})
    tabanlar_ = tabanlar(session, [tc for tc, _, _ in satirlar])
    istisnalar = _istisna_listeleri(session, [(tc.id, tc.icerik_hash) for tc, _, _ in satirlar])
    out = []
    for tc, kayit, jira_key in satirlar:
        kapsayan = kapsayanlar(
            tablolar[tc.requirement_id], tc.icerik, kontrol_refleri(tabanlar_[tc.id], tc.icerik)
        )
        if not gecerli_mi(kayit, kapsayan):
            continue
        if any(istisna_gecerli_mi(i, kayit) for i in istisnalar.get((tc.id, tc.icerik_hash), [])):
            continue
        out.append(
            {
                "case_id": str(tc.id),
                "requirement_id": str(tc.requirement_id),
                "baslik": tc.icerik.get("title"),
                "jira_key": jira_key,
                "sira_no": tc.sira_no,
            }
        )
    return out
