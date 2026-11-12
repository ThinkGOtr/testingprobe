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
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit, content_hash
from tp_core.events.bus import publish_tx
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
# yayınlı case'ler de yeniden denetlenir).
KONTROL_DURUMLARI = ("draft", "approved", "published")
ONAYLI_DURUMLAR = ("approved", "published")
# `check_requirement` birleştirme: gereksinim başına tek bekleyen iş, kısa gecikmeyle (art arda
# gelen tablo olayları tek taramada toplanır). `TP_ORACLE_BIRLESTIRME_S` ile değişir (testler 0).
GEREKSINIM_GECIKME_S = 2.0
# Başarısız / iptal edilmiş iş idempotens anahtarını kilitlemez: yeni deneme son eki alır.
BITMIS_IS = ("failed", "cancelled")
NEDEN_CAGRI_HATASI = "cagri_hatasi"
NEDEN_REPLAY_MISS = "replay_miss"

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
    return kayit is not None and dict(kayit.tablo_hashleri or {}) == tablo_hashleri(kapsayan)


def kapsayan_tablolar(
    session: Session,
    tc: TestCase,
    icerik: Mapping[str, Any] | None = None,
    *,
    ac_refs: Iterable[Any] | None = None,
) -> list[KararTablosu]:
    """Case içeriğini kapsayan geçerli tablolar; `ac_refs` verilirse onunla (V11 birleşim)."""
    icerik = tc.icerik if icerik is None else icerik
    refs = list(ac_refs) if ac_refs is not None else ac_refleri(icerik)
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


def son_istisnalar(
    session: Session, anahtarlar: Iterable[tuple[uuid.UUID, str]]
) -> dict[tuple[uuid.UUID, str], OracleIstisna]:
    """`(case, hash)` başına son istisna (tek sorgu)."""
    anahtarlar = list(anahtarlar)
    if not anahtarlar:
        return {}
    out: dict[tuple[uuid.UUID, str], OracleIstisna] = {}
    for i in session.scalars(
        select(OracleIstisna)
        .where(
            OracleIstisna.test_case_id.in_({c for c, _ in anahtarlar}),
            OracleIstisna.icerik_hash.in_({h for _, h in anahtarlar}),
        )
        .order_by(OracleIstisna.zaman, OracleIstisna.id)
    ):
        out[(i.test_case_id, i.icerik_hash)] = i
    return {k: v for k, v in out.items() if k in set(anahtarlar)}


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


def istisna_turu(sonuc: str | None) -> str | None:
    """Sonucun gerektirdiği istisna türü: `uyumsuz` → `uyumsuz`, `kontrol_edilemedi` →
    `kontrolsuz`; diğerleri istisna gerektirmez."""
    if sonuc == dogrulama.UYUMSUZ:
        return "uyumsuz"
    if sonuc == dogrulama.KONTROL_EDILEMEDI:
        return "kontrolsuz"
    return None


# ------------------------------------------------------------------ kuyruk


def _bos_anahtar(conn: Any, anahtar: str) -> str:
    """Anahtarın kullanılabilir hâli: aynı anahtarlı iş `failed`/`cancelled` ise `:yeniden<n>` son
    eki (review 1 mimari 4: başarısız iş anahtarı ve dolayısıyla onayı kalıcı kilitlemez)."""
    aday, n = anahtar, 0
    while True:
        idempotency_lock(conn, aday)
        durum = conn.execute(
            text("SELECT durum FROM job WHERE idempotency_key = :k"), {"k": aday}
        ).scalar()
        if durum is None or durum not in BITMIS_IS:
            return aday
        n += 1
        aday = f"{anahtar}:yeniden{n}"


def kontrol_kuyruga_al(
    session: Session,
    case_id: uuid.UUID,
    icerik_hash: str,
    icerik: Mapping[str, Any] | None = None,
    *,
    ac_refs: Sequence[str] | None = None,
    idempotency_key: str | None = None,
) -> uuid.UUID:
    """`oracle.check_case` işini çağıranın işleminde kuyruğa alır."""
    yuk: dict[str, Any] = {"case_id": str(case_id), "icerik_hash": icerik_hash}
    if icerik is not None:
        yuk["icerik"] = dict(icerik)
    if ac_refs is not None:
        yuk["ac_refs"] = list(ac_refs)
    conn = session.connection()
    anahtar = _bos_anahtar(conn, idempotency_key) if idempotency_key else None
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

    Bekleyen (queued/retry) bir iş varsa o döner (`neden` eklenir); yoksa
    `GEREKSINIM_GECIKME_S` sonra koşacak yeni iş açılır. Tablo onayı, yeniden açma ve case üretimi
    art arda gelince tek tarama yapılır."""
    conn = session.connection()
    idempotency_lock(conn, f"{CHECK_REQUIREMENT_JOB}:birlestir:{requirement_id}")
    mevcut = conn.execute(
        text(
            "SELECT id, yuk FROM job WHERE tur = :t AND durum IN ('queued', 'retry') "
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
    if gecerli_mi(mevcut, kapsayan):
        return None
    anahtar = kontrol_anahtari(
        "karar",
        tc.id,
        tc.icerik_hash,
        tablo_ozeti(tablo_hashleri(kapsayan)),
        kayit_damgasi(mevcut),
    )
    return kontrol_kuyruga_al(session, tc.id, tc.icerik_hash, None, idempotency_key=anahtar)


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
                kapsayan = kapsayanlar(tablolar, icerik)
                mevcut = mevcutlar.get((tc.id, h))
                if gecerli_mi(mevcut, kapsayan):
                    continue
                anahtar = kontrol_anahtari(
                    "gereksinim",
                    tc.id,
                    h,
                    tablo_ozeti(tablo_hashleri(kapsayan)),
                    kayit_damgasi(mevcut),
                )
                kontrol_kuyruga_al(s, tc.id, h, gonderilen, idempotency_key=anahtar)
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
    ac_refs = yuk.get("ac_refs")
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
        kapsayan = kapsayan_tablolar(s, tc, icerik, ac_refs=ac_refs)
        hashler = tablo_hashleri(kapsayan)
        mevcut = kayit_bul(s, tc.id, h)
        if gecerli_mi(mevcut, kapsayan):
            return {"sonuc": mevcut.sonuc, "onbellek": True}  # type: ignore[union-attr]
        tablolar = [tablo_gorunumu(t) for t in kapsayan]
        story = req.jira_key if req is not None else None
        sira_no, rid = tc.sira_no, tc.requirement_id
        ai_orijinal = ai_icerikleri(s, [tc]).get(tc.id)
        ai_icerik = ai_orijinal is not None and content_hash(ai_orijinal) == h
        # Metamorfik türetilmiş case: olgular dönüşümden bilinir, model çağrılmaz (Ş6).
        turetilen = _turetilen_olgulari(s, tc) if h == tc.icerik_hash and tablolar else None

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
            ctx, engine, gateway, icerik, story, sira_no, tablolar
        )
        sonuc, ayrintilar = dogrulama.degerlendir(icerik, tablolar, cikti)
        if cagri_hatasi:
            ayrintilar["neden"] = NEDEN_CAGRI_HATASI
        elif mod == "replay_miss":
            ayrintilar["neden"] = NEDEN_REPLAY_MISS

    with session_scope() as s:
        tc = s.get(TestCase, cid)
        if tc is None:
            raise PermanentJobError("case silinmiş")
        # Yazım anında yeniden okunan tablo kümesi farklıysa sonuç bayattır (S6).
        guncel = tablo_hashleri(kapsayan_tablolar(s, tc, icerik, ac_refs=ac_refs))
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
    except Exception as exc:
        if not isinstance(exc, ReplayNotFound) and not ctx.son_deneme:
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


def karsilastirilamayanlar(kayit: CaseOracleKontrol) -> list[dict[str, Any]]:
    """Case'te doğrulanmış ama tablonun eksik girdi yüzünden hesaplayamadığı beklenen değerler
    (`dogrulama.kismi_degerlendir`) ve beklenen alanlarda hiçbir olguyla kapsanmayan sayılar
    (`neden: kapsanmayan_sayi`; tamlık denetimi)."""
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
                "neden": "Beklenen alandaki sayı hiçbir tablo değeriyle eşlenmedi",
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


def istisna_gorunumu(
    istisna: OracleIstisna | None,
    kullanicilar: Mapping[uuid.UUID, str],
    hashler: Mapping[str, str] | None,
) -> dict[str, Any] | None:
    if istisna is None:
        return None
    return {
        "tur": istisna.tur,
        "gerekce": istisna.gerekce,
        "veren": kullanicilar.get(istisna.veren_id) if istisna.veren_id else None,
        "zaman": istisna.zaman,
        # Aynı tablo kümesiyle verildiyse kapı yeniden gerekçe istemez.
        "gecerli": hashler is not None and dict(istisna.tablo_hashleri or {}) == dict(hashler),
    }


def oracle_gorunumu(
    kayit: CaseOracleKontrol | None,
    icerik_hash: str,
    kapsayan_var: bool,
    kullanicilar: Mapping[uuid.UUID, str],
    istisna: OracleIstisna | None = None,
) -> dict[str, Any] | None:
    """Portal `oracle` nesnesi (§13.2); kapsayan tablo da geçerli kayıt da yoksa `None`."""
    if kayit is None:
        if not kapsayan_var:
            return None
        return {
            "sonuc": None,
            "icerik_hash": icerik_hash,
            "ozet": dogrulama.ozet(None, None),
            "karsilastirmalar": [],
            "karsilastirilamayan": [],
            "degerler": {"uyumlu": 0, "uyumsuz": 0, "karsilastirilamayan": 0, "atilan": 0},
            "istisna": None,
            "neden": None,
            "kontrol_suruyor": True,
        }
    return {
        "sonuc": kayit.sonuc,
        "icerik_hash": icerik_hash,
        "ozet": dogrulama.ozet(kayit.sonuc, kayit.ayrintilar),
        "karsilastirmalar": karsilastirmalar(kayit),
        "karsilastirilamayan": karsilastirilamayanlar(kayit),
        "degerler": _degerler(kayit),
        "istisna": istisna_gorunumu(istisna, kullanicilar, kayit.tablo_hashleri),
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
    """Gereksinim başına geçerli tablolar (gereksinim başına bir sorgu; tek kaynak
    `karar_tablosu.service.gecerli_tablolar`). Tablosu hiç olmayan gereksinimler tek sorguyla
    elenir (Kontrol Kulesi'nde N+1'i sınırlar)."""
    ids = set(requirement_ids)
    if not ids:
        return {}
    tablolu = set(
        session.scalars(
            select(KararTablosu.requirement_id)
            .where(KararTablosu.requirement_id.in_(ids), KararTablosu.durum == "approved")
            .distinct()
        )
    )
    return {rid: (gecerli_tablolar(session, rid) if rid in tablolu else []) for rid in ids}


def case_oracle_ozetleri(
    session: Session, cases: Sequence[TestCase]
) -> dict[uuid.UUID, dict[str, Any] | None]:
    """`serialize_cases` için case başına güncel içeriğin `oracle` nesnesi (toplu sorgularla)."""
    if not cases:
        return {}
    tablolar = gecerli_tablolar_toplu(session, {c.requirement_id for c in cases})
    kayitlar: dict[tuple[uuid.UUID, str], CaseOracleKontrol] = {
        (k.test_case_id, k.icerik_hash): k
        for k in session.scalars(
            select(CaseOracleKontrol).where(
                CaseOracleKontrol.test_case_id.in_([c.id for c in cases]),
                CaseOracleKontrol.icerik_hash.in_({c.icerik_hash for c in cases}),
            )
        )
    }
    istisnalar = son_istisnalar(session, [(c.id, c.icerik_hash) for c in cases])
    kullanicilar = _kullanicilar(
        session, {i.veren_id for i in istisnalar.values() if i.veren_id is not None}
    )
    out: dict[uuid.UUID, dict[str, Any] | None] = {}
    for c in cases:
        kapsayan = kapsayanlar(tablolar[c.requirement_id], c.icerik)
        kayit = kayitlar.get((c.id, c.icerik_hash))
        out[c.id] = oracle_gorunumu(
            kayit if gecerli_mi(kayit, kapsayan) else None,
            c.icerik_hash,
            bool(kapsayan),
            kullanicilar,
            istisnalar.get((c.id, c.icerik_hash)),
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
        kapsayan = kapsayanlar(tablolar, tc.icerik)
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
    istisna = son_istisnalar(session, [(tc.id, h)]).get((tc.id, h))
    kullanicilar = _kullanicilar(
        session, {istisna.veren_id} if istisna and istisna.veren_id else set()
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
        "oracle": oracle_gorunumu(gecerli, h, kapsayan_var, kullanicilar, istisna),
    }


def onayli_uyumsuz(session: Session) -> list[dict[str, Any]]:
    """Kontrol Kulesi `onayli_uyumsuz` (§13.2): onaylı/yayınlı case'lerden güncel içeriğinin
    geçerli kaydı `uyumsuz` olup aynı tablo kümesiyle verilmiş `uyumsuz` istisnası olmayanlar.

    Tek sorgu (uyumsuz kayıtlı onaylı case'ler) + yalnız o gereksinimlerin tabloları."""
    satirlar = session.execute(
        select(TestCase, CaseOracleKontrol)
        .join(
            CaseOracleKontrol,
            (CaseOracleKontrol.test_case_id == TestCase.id)
            & (CaseOracleKontrol.icerik_hash == TestCase.icerik_hash),
        )
        .where(
            TestCase.durum.in_(ONAYLI_DURUMLAR),
            CaseOracleKontrol.sonuc == dogrulama.UYUMSUZ,
        )
        .order_by(TestCase.requirement_id, TestCase.uretim_no, TestCase.sira_no)
    ).all()
    if not satirlar:
        return []
    tablolar = gecerli_tablolar_toplu(session, {tc.requirement_id for tc, _ in satirlar})
    istisnalar: dict[tuple[uuid.UUID, str], list[OracleIstisna]] = {}
    for i in session.scalars(
        select(OracleIstisna).where(
            OracleIstisna.test_case_id.in_([tc.id for tc, _ in satirlar]),
            OracleIstisna.tur == "uyumsuz",
        )
    ):
        istisnalar.setdefault((i.test_case_id, i.icerik_hash), []).append(i)
    out = []
    for tc, kayit in satirlar:
        if not gecerli_mi(kayit, kapsayanlar(tablolar[tc.requirement_id], tc.icerik)):
            continue
        hashler = dict(kayit.tablo_hashleri or {})
        if any(
            dict(i.tablo_hashleri or {}) == hashler
            for i in istisnalar.get((tc.id, tc.icerik_hash), [])
        ):
            continue
        out.append(
            {
                "case_id": str(tc.id),
                "requirement_id": str(tc.requirement_id),
                "baslik": tc.icerik.get("title"),
            }
        )
    return out
