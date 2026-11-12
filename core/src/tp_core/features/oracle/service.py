"""Beklenen sonuç kontrolü servis katmanı (012 ANALIZ §4.3): iş, kayıt, geçerlilik, görünüm.

- `run_check_case` (`oracle.check_case` işi, worker): kapsayan tabloları bulur; yoksa
  `kapsam_disi` (model çağrılmaz). Varsa `case_facts` çağrısı → deterministik doğrulama ve
  karşılaştırma (`dogrulama`) → `case_oracle_kontrol`'e `(test_case_id, icerik_hash)` anahtarıyla
  yazar (upsert; `tp_app`'in DELETE yetkisi yoktur). Case içeriğine asla dokunmaz.
- `run_check_requirement` (`oracle.check_requirement` işi): gereksinimin `draft` / `approved`
  case'leri için (güncel içerik ve varsa düzeltilmemiş AI içeriği) `oracle.check_case` açar.
  Ş1 bir tablo onaylandığında / değiştiğinde bu işi bu adla kuyruğa alır.
- Geçerlilik: kayıt yalnız `tablo_hashleri` güncel kapsayan tabloların `{id: icerik_hash}`
  eşlemesine eşitken geçerlidir; değilse yok sayılır ve yeniden hesaplanır.
- `case_oracle_ozetleri`: `serialize_cases`'in `oracle` alanı (N+1 yok: gereksinim başına bir
  tablo sorgusu, tek kontrol sorgusu, tek kullanıcı sorgusu).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit, content_hash
from tp_core.events.bus import publish_tx
from tp_core.features.oracle import cikarma, dogrulama
from tp_core.features.oracle.tablolar import (
    gecerli_tablolar,
    kapsayanlar,
    tablo_hashleri,
    tablo_ref,
)
from tp_core.models import (
    AppUser,
    CaseOracleKontrol,
    KararTablosu,
    Requirement,
    Review,
    TestCase,
    session_scope,
)
from tp_core.ports import ModelGateway
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue

CHECK_CASE_JOB = "oracle.check_case"
CHECK_REQUIREMENT_JOB = "oracle.check_requirement"
OLAY = "oracle.checked"
# Yeni tablo / üretim sonrası kontrol edilen case durumları (§4.3 "Ne zaman koşar").
KONTROL_DURUMLARI = ("draft", "approved")

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


def kayit_bul(
    session: Session, case_id: uuid.UUID, icerik_hash: str, *, lock: bool = False
) -> CaseOracleKontrol | None:
    q = select(CaseOracleKontrol).where(
        CaseOracleKontrol.test_case_id == case_id, CaseOracleKontrol.icerik_hash == icerik_hash
    )
    if lock:
        q = q.with_for_update()
    return session.scalars(q).first()


def gecerli_mi(kayit: CaseOracleKontrol | None, kapsayan: Sequence[KararTablosu]) -> bool:
    return kayit is not None and dict(kayit.tablo_hashleri or {}) == tablo_hashleri(kapsayan)


def kapsayan_tablolar(
    session: Session, tc: TestCase, icerik: Mapping[str, Any] | None = None
) -> list[KararTablosu]:
    icerik = tc.icerik if icerik is None else icerik
    return gecerli_tablolar(
        session, tc.requirement_id, list(icerik.get("acceptance_criteria_refs") or [])
    )


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


# ------------------------------------------------------------------ kuyruk


def kontrol_kuyruga_al(
    session: Session,
    case_id: uuid.UUID,
    icerik_hash: str,
    icerik: Mapping[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
) -> uuid.UUID:
    """`oracle.check_case` işini çağıranın işleminde kuyruğa alır."""
    yuk: dict[str, Any] = {"case_id": str(case_id), "icerik_hash": icerik_hash}
    if icerik is not None:
        yuk["icerik"] = dict(icerik)
    return enqueue(session.connection(), CHECK_CASE_JOB, yuk, idempotency_key=idempotency_key)


def gereksinim_kontrolu_kuyruga_al(
    session: Session, requirement_id: uuid.UUID, neden: str
) -> uuid.UUID:
    return enqueue(
        session.connection(),
        CHECK_REQUIREMENT_JOB,
        {"requirement_id": str(requirement_id), "neden": neden},
    )


def uretim_sonrasi(session: Session, requirement_id: uuid.UUID) -> uuid.UUID | None:
    """`run_generation` kancası: gereksinimin geçerli (onaylı, bayat olmayan) bir karar tablosu
    varsa case'leri için kontrol işlerini açar; yoksa iş açılmaz (kontrol edilecek bir şey yok).

    Tablosu olmayan gereksinimde kontrol kaydı da olmaz; ilk tablo onaylanınca Ş1'in
    `oracle.check_requirement` işi tüm case'leri (kapsamayanlar `kapsam_disi`) kaydeder. Böylece
    §4.7 `kapsam_orani` karar tablosu olan gereksinimlerin AI case'leri üzerindendir.
    """
    if not gecerli_tablolar(session, requirement_id):
        return None
    return gereksinim_kontrolu_kuyruga_al(session, requirement_id, "case_uretildi")


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
        for tc in cases:
            hedefler: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any]]] = [
                (tc.icerik_hash, None, tc.icerik)
            ]
            ai_icerik = ai.get(tc.id)
            if ai_icerik is not None and content_hash(ai_icerik) != tc.icerik_hash:
                hedefler.append((content_hash(ai_icerik), ai_icerik, ai_icerik))
            for h, gonderilen, icerik in hedefler:
                kapsayan = kapsayanlar(tablolar, icerik)
                if gecerli_mi(kayit_bul(s, tc.id, h), kapsayan):
                    continue
                anahtar = f"{CHECK_CASE_JOB}:{tc.id}:{h}:{tablo_ozeti(tablo_hashleri(kapsayan))}"
                kontrol_kuyruga_al(s, tc.id, h, gonderilen, idempotency_key=anahtar)
                acilan += 1
    return {"kontrol_isi": acilan, "neden": yuk.get("neden")}


def run_check_case(
    ctx: JobContext, engine: Engine, gateway: ModelGateway | None = None
) -> dict[str, Any]:
    """`oracle.check_case`: tek case içeriğinin (güncel ya da önerilen) kontrolü."""
    yuk = ctx.yuk or {}
    cid = uuid.UUID(str(yuk["case_id"]))
    h = str(yuk["icerik_hash"])
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
        if gecerli_mi(mevcut, kapsayan):
            return {"sonuc": mevcut.sonuc, "onbellek": True}  # type: ignore[union-attr]
        tablolar = [tablo_gorunumu(t) for t in kapsayan]
        story = req.jira_key if req is not None else None
        sira_no, rid = tc.sira_no, tc.requirement_id
        ai_orijinal = ai_icerikleri(s, [tc]).get(tc.id)
        ai_icerik = ai_orijinal is not None and content_hash(ai_orijinal) == h

    call_id: uuid.UUID | None = None
    mod: str | None = None
    cagri_hatasi: str | None = None
    if not tablolar:
        sonuc, ayrintilar = dogrulama.degerlendir(icerik, [], None)
    else:
        cikti, call_id, mod, cagri_hatasi = _olgulari_cikar(
            ctx, engine, gateway, icerik, story, sira_no, tablolar
        )
        sonuc, ayrintilar = dogrulama.degerlendir(icerik, tablolar, cikti)

    with session_scope() as s:
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
                **({"cagri_hatasi": cagri_hatasi} if cagri_hatasi else {}),
            },
        )
        return {"sonuc": sonuc, "kontrol_id": str(kayit.id), "mode": mod}


def _olgulari_cikar(
    ctx: JobContext,
    engine: Engine,
    gateway: ModelGateway | None,
    icerik: Mapping[str, Any],
    story: str | None,
    sira_no: int,
    tablolar: Sequence[dogrulama.Tablo],
) -> tuple[Mapping[str, Any] | None, uuid.UUID | None, str | None, str | None]:
    """`case_facts` çağrısı → (çıktı, çağrı kimliği, mod, hata). Kalıcı çağrı hatası (son deneme
    ya da REPLAY kaydı yok) olgusuz sonuç verir: kapsayan tablo varken `kontrol_edilemedi`."""
    from tp_core.gateway import deterministic_call_id, find_rules_dir, load_schema
    from tp_core.gateway.errors import GatewayError, ReplayNotFound

    gw = gateway or _gateway_factory(engine)
    ref = cikarma.case_ref(story, sira_no)
    mesajlar = cikarma.facts_messages(
        icerik, ref, [{"ref": t.ref, "id": t.id, "icerik": t.icerik} for t in tablolar]
    )
    rules_dir = getattr(gw, "rules_dir", None) or find_rules_dir()
    try:
        result = gw.call(
            cikarma.PURPOSE,
            cikarma.BUNDLE,
            mesajlar,
            load_schema(rules_dir, cikarma.PURPOSE),
            replay_key=cikarma.replay_key_for(story, sira_no),
            call_id=deterministic_call_id(ctx.job_id, cikarma.PURPOSE),
        )
    except GatewayError as exc:
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
    """Upsert: kayıt varsa sonuç güncellenir. Tablo kümesi değiştiyse eski istisna da düşer (istisna
    eski tabloyla yapılan karşılaştırmaya verilmişti; denetim kaydı ayrıca durur)."""
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
    kayit.olusturma = func.now()
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


def oracle_gorunumu(
    kayit: CaseOracleKontrol | None,
    icerik_hash: str,
    kapsayan_var: bool,
    kullanicilar: Mapping[uuid.UUID, str],
) -> dict[str, Any] | None:
    """Portal `oracle` nesnesi; kapsayan tablo da geçerli kayıt da yoksa `None`."""
    if kayit is None:
        if not kapsayan_var:
            return None
        return {
            "sonuc": None,
            "icerik_hash": icerik_hash,
            "ozet": dogrulama.ozet(None, None),
            "karsilastirmalar": [],
            "istisna": None,
            "kontrol_suruyor": True,
        }
    istisna = None
    if kayit.istisna_gerekce:
        istisna = {
            "gerekce": kayit.istisna_gerekce,
            "veren": kullanicilar.get(kayit.istisna_veren_id) if kayit.istisna_veren_id else None,
            "zaman": kayit.istisna_zamani,
        }
    return {
        "sonuc": kayit.sonuc,
        "icerik_hash": icerik_hash,
        "ozet": dogrulama.ozet(kayit.sonuc, kayit.ayrintilar),
        "karsilastirmalar": karsilastirmalar(kayit),
        "istisna": istisna,
        "kontrol_suruyor": False,
    }


def _kullanicilar(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(
        session.execute(select(AppUser.id, AppUser.kullanici_adi).where(AppUser.id.in_(ids))).all()
    )  # type: ignore[arg-type]


def case_oracle_ozetleri(
    session: Session, cases: Sequence[TestCase]
) -> dict[uuid.UUID, dict[str, Any] | None]:
    """`serialize_cases` için case başına güncel içeriğin `oracle` nesnesi (toplu sorgularla)."""
    if not cases:
        return {}
    tablolar = {rid: gecerli_tablolar(session, rid) for rid in {c.requirement_id for c in cases}}
    kayitlar: dict[tuple[uuid.UUID, str], CaseOracleKontrol] = {
        (k.test_case_id, k.icerik_hash): k
        for k in session.scalars(
            select(CaseOracleKontrol).where(
                CaseOracleKontrol.test_case_id.in_([c.id for c in cases]),
                CaseOracleKontrol.icerik_hash.in_({c.icerik_hash for c in cases}),
            )
        )
    }
    kullanicilar = _kullanicilar(
        session, {k.istisna_veren_id for k in kayitlar.values() if k.istisna_veren_id}
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
    kullanicilar = _kullanicilar(
        session, {gecerli.istisna_veren_id} if gecerli and gecerli.istisna_veren_id else set()
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
        "oracle": oracle_gorunumu(gecerli, h, kapsayan_var, kullanicilar),
    }
