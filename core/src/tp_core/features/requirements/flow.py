"""Gereksinim akışının iş mantığı (TEKNIK-TASARIM §2 adım 1–3, §8.2, §8.2a, §8.2b).

Durumlar yalnızca `workflow.service.transition()` ile değişir; insan kararları
`record_approval()` ile içerik hash'ine bağlanır. Dış etkili eylemler (Jira yorum/etiket/açıklama)
yalnızca worker'da, deterministik kodla ve `external_ref` ile idempotent yapılır.

Gereksinim yaşam döngüsü (requirement makinesi):

    new/failed ──review──▶ in_review ──(ön inceleme + tutarlılık turu)──▶ findings_open
                                   └──(engelleyici bulgu yok)──▶ doc_final ──▶ pending_po
    findings_open ──kararlar──▶ (engelleyici kalmadı, düzeltme yok) ──▶ doc_final ──▶ pending_po
    findings_open ──apply-doc-fixes──▶ in_review ──(Jira'ya yaz + yeniden kontrol)──▶ …
    pending_po ──PO onayı (Jira etiketi / portal)──▶ po_approved
    po_approved/generating/cases_ready/done ──Jira'da PO etiketi kaldırıldı──▶ new
                                   (yayın kapısı kapanır; yayınlanmışlar Jira'da kalır)

Jira yolunda PO'ya soru yorumu ve `tp-po-pending` etiketi belge **son hal** olunca yazılır
(§2 adım 2: "Kalan sorular Jira yorumu olarak yazılır"); düzeltmeyle değişen AC'lere ait sorular
ayrı listelenir. Son hal anından önce konmuş `tp-po-approved` etiketi onay sayılmaz (kaldırılır).

Denetim sonucu güvenilir değilse (REPLAY-MISS ya da dönen bulguların hepsi elendi) belge otomatik
son hal olmaz: gereksinim `findings_open`'da kalır, analist açıkça son hale alır (apply-doc-fixes).

Karar kuralı (§8.2b adım 5): doğrulanmış her bulgu — önem derecesinden bağımsız — insan kararı
bekler; karar bekleyen bulgu varken belge otomatik son hal olmaz. Analist "son hal olarak onayla"
(apply-doc-fixes, düzeltme yokken) ile kapatabilir: engelleyici bulgular kararsızsa reddedilir
(409); kararsız uyarılar "bilinçli fark" (accept_difference) olarak kayda geçer ve PO yorumunda
listelenir.

Yeniden denetim (findings_open'da "Yeniden denetle"): belge içeriği bulgunun turundan beri
değişmediyse karar bekleyen ve uygulanmamış (`fix_doc`) bulgular bayatlatılmaz, yeni tura
taşınır; yeni turun aynı farkı (tür + AC kümesi + AC metni) yeniden raporlaması taşınan bulgunun
tekrarı sayılır. REPLAY-MISS ya da modelin farkı tekrar raporlamaması insan kararını atlatamaz.

Önceki turda insan kararıyla kapanmış (code_defect / accept_difference) aynı fark — aynı tür,
aynı AC metni, aynı kanıt — sonraki turda yeniden karar istemez: bulgu bayatlatılır ve önceki
karara bağlanır (`consistency_finding_ek.onceki_finding_id`).

Takılı kalma: işi worker dışında biten (sahipsiz iş, zaman aşımı, nabız kaybı) gereksinim
`in_review`/`generating`'de kalmaz; PO sorgusu ve inceleme başlatma, bağlı etkin işi olmayan bu
gereksinimleri `failed`'a alır (yeniden başlatılabilir).

Tur sınırı (§8.2b adım 7): `requirement.kontrol_turu` içinde bulunulan döngünün denetim turudur.
`max_rounds` (3) turdan sonra AI denetimi yeniden koşmaz: onaylı düzeltmeler yine yazılır ama kalan
engelleyici bulgular insan kararıyla (code_defect / accept_difference) kapanır.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit, chain_tip, content_hash
from tp_core.events.bus import publish_tx
from tp_core.features.requirements import services
from tp_core.features.requirements.codetools import TOOL_SPECS, CodeTools
from tp_core.features.requirements.content import (
    DESC,
    DocFix,
    DocMergeConflict,
    DocMergeError,
    MergeResult,
    ac_refs,
    change_summary,
    changed_targets,
    current_doc_text,
    hedef_ad,
    merge_fixes,
    normalize_acs,
    parse_fix_text,
    refers_to_description,
    replaced_doc_text,
    requirement_hash,
    split_ac,
    validate_fix_text,
)
from tp_core.features.requirements.datatools import DataTools
from tp_core.features.requirements.settings import (
    AI_LABEL,
    PO_APPROVED_LABEL,
    PO_PENDING_LABEL,
    get_requirements_settings,
)
from tp_core.features.requirements.verifier import EvidenceVerifier, Verification
from tp_core.gateway import (
    FREE_TEXT_KEY,
    deterministic_call_id,
    golden_name,
    load_schema,
    mode_label,
    requirement_block,
)
from tp_core.integrations import jira_notify
from tp_core.models import (
    AiCall,
    BugDraft,
    ConsistencyFinding,
    ExternalRef,
    Requirement,
    RequirementReview,
    TestCase,
    WorkflowInstance,
    session_scope,
)
from tp_core.models.requirements_feature import (
    ConsistencyFindingEk,
    RequirementAkis,
    RequirementKontrol,
    RequirementReviewEk,
)
from tp_core.ports import AgentStep, ModelMessage
from tp_core.workflow.jobs import enqueue, idempotency_lock, start_workflow
from tp_core.workflow.service import (
    SYSTEM,
    Actor,
    Principal,
    WorkflowError,
    actor_name,
    approved_hash_matches,
    content_hash_of,
    record_approval,
    transition,
)

log = logging.getLogger("tp_core.features.requirements")

JOB_REVIEW = "requirements.review"
JOB_CONSISTENCY = "requirements.consistency"
JOB_APPLY = "requirements.apply_doc_fixes"
JOB_PO_POLL = "requirements.po_poll"
JOB_PO_REQUEST = "requirements.po_request"

EV_REQUIREMENT = "requirement.updated"
EV_FINDING = "finding.verified"
EV_PO = "po.approved"
EV_AGENT_STEP = "agent.step"

# Deterministik kimlikler için ad alanı (requirement_review satırı iş akışından türetilir).
NS = uuid.UUID("6f0f3f5e-2b8e-5d0c-9a51-3c1e1b6f7a02")
_PROJE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")
ACIK_BULGU = ("open", "decided")
# Jira'da PO onay etiketinin izlendiği durumlar (geri çekilirse kapı kapanır, §2 adım 3).
PO_IZLENEN = ("pending_po", "po_approved", "generating", "cases_ready", "done")
# İşi yarıda kalırsa takılabilecek durumlar (kurtarma süpürmesi).
IS_BEKLEYEN = ("in_review", "generating")
# Önceki insan kararı sonraki turlara devredilebilen kararlar (fix_doc belgeyi değiştirir).
DEVREDILEN_KARARLAR = ("code_defect", "accept_difference")
# Bitmiş PO sorgu işleri bu süreden sonra silinir (her 15 sn'de bir satır birikmesin).
PO_POLL_SAKLAMA = timedelta(hours=1)


class FlowError(WorkflowError):
    """Akış kuralı ihlali (409; Türkçe ayrıntı)."""


class FlowInputError(WorkflowError):
    status_code = 422


def now() -> datetime:
    return datetime.now(UTC)


def settings() -> Any:
    return get_requirements_settings()


# --------------------------------------------------------------------- olay / yardımcı


def emit(session: Session, event: str, data: dict[str, Any]) -> None:
    publish_tx(session.connection(), event, data)


def emit_requirement(session: Session, req: Requirement, **ek: Any) -> None:
    emit(
        session,
        EV_REQUIREMENT,
        {
            "id": req.id,
            "requirement_id": req.id,
            "durum": req.durum,
            "jira_key": req.jira_key,
            "kontrol_turu": req.kontrol_turu,
            **ek,
        },
    )


def akis(session: Session, req: Requirement) -> RequirementAkis:
    kayit = session.get(RequirementAkis, req.id)
    if kayit is None:
        kayit = RequirementAkis(requirement_id=req.id)
        session.add(kayit)
        session.flush()
    return kayit


def lock_requirement(session: Session, req_id: uuid.UUID) -> Requirement:
    req = session.get(Requirement, req_id, with_for_update=True, populate_existing=True)
    if req is None:
        raise FlowError("Gereksinim bulunamadı")
    return req


def active_reviews(session: Session, req_id: uuid.UUID) -> list[RequirementReview]:
    return list(
        session.scalars(
            select(RequirementReview)
            .where(
                RequirementReview.requirement_id == req_id,
                RequirementReview.durum != "superseded",
            )
            .order_by(RequirementReview.olusturma)
        )
    )


def cycle_start(session: Session, req_id: uuid.UUID) -> datetime | None:
    """Güncel inceleme döngüsünün başlangıcı: etkin (superseded olmayan) ön incelemenin anı.

    Döngü tam incelemeyle (ön inceleme) başlar; içerik sıfırlaması (`new`) ve PO onayının geri
    çekilmesi ön incelemeleri `superseded` yapar. Varsayılan bulgu listesi ve sayaçları bu andan
    sonra oluşan bulgularla sınırlanır (önceki döngülerin bulguları yalnızca `tumu=true`'da).
    Etkin ön inceleme yoksa güncel döngü yoktur (None).
    """
    return session.scalar(
        select(func.min(RequirementReview.olusturma)).where(
            RequirementReview.requirement_id == req_id,
            RequirementReview.durum != "superseded",
        )
    )


def supersede_reviews(session: Session, req_id: uuid.UUID, actor: Actor) -> None:
    for rr in active_reviews(session, req_id):
        transition(session, rr, "superseded", actor, rr.durum)


def findings_of(
    session: Session, req_id: uuid.UUID, durumlar: Sequence[str] | None = None
) -> list[ConsistencyFinding]:
    q = select(ConsistencyFinding).where(ConsistencyFinding.requirement_id == req_id)
    if durumlar is not None:
        q = q.where(ConsistencyFinding.durum.in_(list(durumlar)))
    return list(session.scalars(q.order_by(ConsistencyFinding.olusturma)))


def stale_findings(
    session: Session,
    req_id: uuid.UUID,
    actor: Actor,
    sebep: str,
    *,
    belge_hash: str | None = None,
) -> int:
    """Açık (karar bekleyen) ve uygulanmamış `fix_doc` kararlı bulguları bayatlatır.

    `belge_hash` verilirse yalnızca turu bu içerikten FARKLI bir belgeye ait bulgular bayatlar:
    içerik değişmediyse bulgu hâlâ geçerlidir ve insan kararı bekler (yeni tura taşınır).
    """
    n = 0
    for f in findings_of(session, req_id, ACIK_BULGU):
        if belge_hash is not None and finding_doc_hash(session, f) == belge_hash:
            continue
        transition(session, f, "stale", actor, f.durum, sebep=sebep)
        n += 1
    return n


def finding_doc_hash(session: Session, f: ConsistencyFinding) -> str | None:
    """Bulgunun üretildiği denetim turunda belgenin içerik hash'i."""
    ek = session.get(ConsistencyFindingEk, f.id)
    if ek is None or ek.kontrol_id is None:
        return None
    kontrol = session.get(RequirementKontrol, ek.kontrol_id)
    return kontrol.belge_hash if kontrol is not None else None


def finish_workflow(session: Session, wf_id: uuid.UUID | None) -> None:
    if wf_id is None:
        return
    wf = session.get(WorkflowInstance, wf_id, with_for_update=True)
    if wf is not None and wf.durum == "running":
        transition(session, wf, "done", SYSTEM, "running")


def _wf_yuk(wf_id: uuid.UUID | None) -> dict[str, str]:
    return {"workflow_id": str(wf_id)} if wf_id is not None else {}


def _wf_id(yuk: Any) -> uuid.UUID | None:
    deger = (yuk or {}).get("workflow_id")
    return uuid.UUID(str(deger)) if deger else None


# ------------------------------------------------------------------------- senkron


@dataclass
class SyncReport:
    proje: str
    sonuc: dict[str, str] = field(default_factory=dict)  # jira_key → yeni|guncellendi|…
    # rules/baz-degerler.yaml uygulama özeti (baseline_dosya.uygula_hepsi).
    baz_dosyasi: dict[str, Any] = field(default_factory=dict)

    def sayac(self, deger: str) -> int:
        return sum(1 for v in self.sonuc.values() if v == deger)

    def mesaj(self) -> str:
        parcalar = [f"{len(self.sonuc)} story çekildi"]
        for ad, etiket in (
            ("yeni", "yeni"),
            ("guncellendi", "güncellendi"),
            ("yeniden_kontrol", "yeniden kontrole alındı"),
            ("sifirlandi", "baştan incelenecek"),
            ("mesgul", "işlemde olduğu için atlandı"),
        ):
            n = self.sayac(ad)
            if n:
                parcalar.append(f"{n} {etiket}")
        baz = self.baz_dosyasi.get("sonuc") or {}
        uygulanan = sum(1 for v in baz.values() if v == "uygulandi")
        if uygulanan:
            parcalar.append(f"{uygulanan} story'ye baz değer ölçümü dosyadan uygulandı")
        if self.baz_dosyasi.get("hatalar"):
            parcalar.append(f"baz değer dosyasında {len(self.baz_dosyasi['hatalar'])} hata")
        return ", ".join(parcalar)


def sync_from_jira(session: Session, jira: Any, actor: Principal) -> SyncReport:
    proje = settings().jira_project
    if not _PROJE_RE.match(proje):
        raise FlowInputError(f"Geçersiz JIRA_PROJECT: {proje!r}")
    issues = jira.search(f"project = {proje} AND issuetype = Story ORDER BY key ASC", 200)
    rapor = SyncReport(proje)
    for issue in issues:
        rapor.sonuc[issue.key] = upsert_issue(session, issue, actor)
    # Story başına F0 ölçümleri `make reset`'ten sağ çıkan rules/baz-degerler.yaml'dadır: eşitlenen
    # (yeni UUID'li) gereksinimlere burada uygulanır. Dosya hatası eşitlemeyi durdurmaz.
    from tp_core.features.requirements import baseline_dosya

    keys = list(rapor.sonuc)
    reqs = (
        session.scalars(select(Requirement).where(Requirement.jira_key.in_(keys))).all()
        if keys
        else []
    )
    rapor.baz_dosyasi = baseline_dosya.uygula_hepsi(session, actor_name(actor), reqs)
    audit_on_commit(
        session,
        actor.kullanici_adi,
        "requirements.sync",
        f"jira:{proje}",
        {"sonuc": rapor.sonuc, "baz_dosyasi": rapor.baz_dosyasi},
    )
    return rapor


def upsert_issue(session: Session, issue: Any, actor: Actor) -> str:
    acs = [str(a) for a in issue.acceptance_criteria]
    h = requirement_hash(issue.summary, issue.description, acs)
    req = session.scalars(
        select(Requirement).where(Requirement.jira_key == issue.key).with_for_update()
    ).first()
    if req is None:
        req = Requirement(
            kaynak="jira",
            jira_key=issue.key,
            baslik=issue.summary,
            aciklama=issue.description,
            kabul_kriterleri=acs,
            kaynak_hash=h,
            ac_missing=not acs,
            cekim_zamani=now(),
        )
        session.add(req)
        session.flush()
        audit_on_commit(
            session,
            actor_name(actor),
            "requirement.created",
            f"requirement:{req.id}",
            {"jira_key": issue.key, "hash": h, "ac_missing": not acs},
        )
        emit_requirement(session, req, olay="created")
        return "yeni"
    req.cekim_zamani = now()
    if content_hash_of(req) == h:
        return "degismedi"
    return apply_content_change(
        session, req, issue.summary, issue.description, acs, actor, sebep="Jira'da içerik değişti"
    )


def apply_content_change(
    session: Session,
    req: Requirement,
    baslik: str,
    aciklama: str,
    acs: Sequence[str],
    actor: Actor,
    *,
    sebep: str,
) -> str:
    """Kaynakta değişen içeriği gereksinime yazar ve akışı buna göre geri alır.

    - in_review / generating: dokunulmaz ("mesgul"); süren iş kendi hash denetimini yapar.
    - findings_open / doc_final / pending_po: tur hakkı varsa denetim yeniden koşar (in_review).
    - diğerleri: `new`'e döner (PO onayı ve onaylanan hash silinir).
    """
    durum = req.durum
    if durum in ("in_review", "generating"):
        return "mesgul"
    onceki = content_hash_of(req)
    req.baslik, req.aciklama, req.kabul_kriterleri = baslik, aciklama, list(acs)
    req.ac_missing = not acs
    req.kaynak_hash = requirement_hash(baslik, aciklama, acs)
    session.flush()
    audit_on_commit(
        session,
        actor_name(actor),
        "requirement.content_changed",
        f"requirement:{req.id}",
        {"onceki_hash": onceki, "hash": req.kaynak_hash, "sebep": sebep, "durum": durum},
    )
    stale_findings(session, req.id, actor, sebep)
    if durum in ("findings_open", "doc_final", "pending_po") and (
        req.kontrol_turu < settings().max_rounds
    ):
        transition(session, req, "in_review", actor, durum, sebep=sebep)
        req.kontrol_turu += 1
        start_workflow(
            session.connection(),
            "requirement_recheck",
            actor_name(actor),
            yuk={"requirement_id": str(req.id), "tur": req.kontrol_turu},
            job_tur=JOB_CONSISTENCY,
            nesne_turu="requirement",
            nesne_id=req.id,
        )
        emit_requirement(session, req, olay="content_changed")
        return "yeniden_kontrol"
    if durum != "new":
        transition(session, req, "new", actor, durum, sebep=sebep)
        req.kontrol_turu = 0
        _po_temizle(req)
        supersede_reviews(session, req.id, actor)
        emit_requirement(session, req, olay="content_changed")
        return "sifirlandi"
    emit_requirement(session, req, olay="content_changed")
    return "guncellendi"


def create_free_text(
    session: Session, user: Principal, baslik: str, aciklama: str, ac: Sequence[str]
) -> Requirement:
    baslik = " ".join((baslik or "").split())
    if not baslik:
        raise FlowInputError("Başlık boş olamaz")
    if len(baslik) > 200:
        raise FlowInputError("Başlık en fazla 200 karakter olabilir")
    aciklama = (aciklama or "").strip()
    if len(aciklama) > 10000:
        raise FlowInputError("Açıklama en fazla 10.000 karakter olabilir")
    acs = normalize_acs(ac or [])
    if len(acs) > 30:
        raise FlowInputError("En fazla 30 kabul kriteri girilebilir")
    req = Requirement(
        kaynak="free_text",
        baslik=baslik,
        aciklama=aciklama,
        kabul_kriterleri=acs,
        kaynak_hash=requirement_hash(baslik, aciklama, acs),
        ac_missing=not acs,
        cekim_zamani=now(),
        olusturan_id=user.id,
    )
    session.add(req)
    session.flush()
    audit_on_commit(
        session,
        user.kullanici_adi,
        "requirements.free_text",
        f"requirement:{req.id}",
        {"baslik": baslik, "hash": req.kaynak_hash, "ac_sayisi": len(acs)},
    )
    emit_requirement(session, req, olay="created")
    return req


# ----------------------------------------------------------------- inceleme başlatma


@dataclass(frozen=True)
class Started:
    workflow_id: uuid.UUID
    job_id: uuid.UUID
    mesaj: str


def start_review(session: Session, req: Requirement, user: Principal) -> Started:
    """POST /requirements/{id}/review: tam inceleme (new/failed) ya da yeniden kontrol.

    `failed`'dan yeniden başlatma tur sayacını SIFIRLAMAZ (§8.2b adım 7, en fazla 3 tur): yarıda
    kalan tur yeniden koşar. Sayaç yalnızca gerçek içerik değişikliğinde (`new`) sıfırlanır.
    İşi worker dışında bitmiş (takılı) `in_review` gereksinim önce `failed`'a alınır.
    """
    durum = req.durum
    if durum == "in_review" and stuck(session, req.id):
        recover_stuck(session, req, "inceleme yeniden başlatılırken takılı iş bulundu")
        durum = req.durum
    if durum not in ("new", "failed", "findings_open"):
        raise FlowError(f"Bu durumda ({durum}) inceleme başlatılamaz")
    if durum == "findings_open":
        if req.kontrol_turu >= settings().max_rounds:
            raise FlowError(
                f"Kontrol turu sınırına ulaşıldı ({settings().max_rounds}); kalan bulgular için "
                "insan kararı gerekiyor"
            )
        tur, tam = req.kontrol_turu + 1, False
    elif durum == "failed":
        # Başarısız tur tamamlanmış sayılmaz; aynı tur yeniden koşar (yeni tur hakkı verilmez).
        tur = max(req.kontrol_turu, 1)
        tam = tur <= 1 or not active_reviews(session, req.id)
    else:
        tur, tam = 1, True
    # Yeniden kontrolde içeriği değişmemiş belgenin bulguları geçerliliğini korur: karar
    # bekleyenler ve uygulanmamış düzeltmeler yeni tura taşınır (REPLAY-MISS ya da modelin farkı
    # yeniden raporlamaması insan kararını atlatamaz; §8.2b, Constitution I). Tam incelemede
    # (yeni döngü) hepsi bayatlar.
    stale_findings(
        session,
        req.id,
        user,
        "inceleme yeniden başlatıldı",
        belge_hash=None if tam else content_hash_of(req),
    )
    transition(session, req, "in_review", user, durum, sebep="inceleme başlatıldı")
    req.kontrol_turu = tur
    wf, job = start_workflow(
        session.connection(),
        "requirement_review" if tam else "requirement_recheck",
        user.kullanici_adi,
        yuk={"requirement_id": str(req.id), "tur": req.kontrol_turu},
        job_tur=JOB_REVIEW if tam else JOB_CONSISTENCY,
        nesne_turu="requirement",
        nesne_id=req.id,
    )
    emit_requirement(session, req, olay="review_started")
    mesaj = (
        "Ön inceleme ve tutarlılık denetimi başlatıldı."
        if tam
        else f"Tutarlılık denetimi yeniden başlatıldı (tur {req.kontrol_turu})."
    )
    return Started(wf, job, mesaj)


# ----------------------------------------------------------- dış etki: idempotent Jira


def _marker(idempotency_key: str) -> str:
    return f"tp-{uuid.uuid5(NS, idempotency_key)}"


def jira_once(
    engine: Engine,
    *,
    entity_turu: str,
    entity_id: uuid.UUID,
    idempotency_key: str,
    action: Callable[[], str | None],
    find_existing: Callable[[], str | None],
    still_present: Callable[[], bool] | None = None,
) -> str | None:
    """Dış etkiyi bir kez yapar: önce `intent`, sonra eylem, sonra `created` (§8.3).

    Önceki deneme `intent`'te kaldıysa (eylem yapıldı mı belirsiz) önce `find_existing` ile Jira'da
    aranır; bulunursa tekrar yapılmaz.

    `still_present` (derinlemesine savunma): `created` kaydı varken etkinin Jira'da HÂLÂ durup
    durmadığını denetler. Durmuyorsa (ör. story başkasınca geri alındı: A→B→A) kayıt bayattır;
    eylem yeniden yapılır. Yalnızca durumu ölçülebilen etkiler (açıklama içeriği) için verilir.
    """
    with session_scope() as s:
        idempotency_lock(s.connection(), idempotency_key)
        ref = s.scalars(
            select(ExternalRef).where(ExternalRef.idempotency_key == idempotency_key)
        ).first()
        if ref is not None and ref.durum == "created":
            if still_present is None or still_present():
                return ref.external_key
            log.warning("%s: kayıtlı dış etki Jira'da yok; yeniden yapılıyor", idempotency_key)
            ref.durum, ref.hata = "intent", "created kaydı vardı ama etki Jira'da yoktu"
            s.flush()
            audit_on_commit(
                s,
                "system",
                "external_ref.stale",
                f"external_ref:{ref.id}",
                {"idempotency_key": idempotency_key, "external_key": ref.external_key},
            )
            ref = None  # belirsiz değil: etkinin olmadığı ölçüldü → doğrudan yeniden yap
        belirsiz = ref is not None
        if (
            ref is None
            and not s.scalars(
                select(ExternalRef.id).where(ExternalRef.idempotency_key == idempotency_key)
            ).first()
        ):
            s.add(
                ExternalRef(
                    entity_turu=entity_turu,
                    entity_id=entity_id,
                    sistem="jira",
                    idempotency_key=idempotency_key,
                )
            )
    mevcut = find_existing() if belirsiz else None
    try:
        sonuc = mevcut if mevcut is not None else action()
    except Exception as exc:
        with session_scope() as s:
            ref = s.scalars(
                select(ExternalRef).where(ExternalRef.idempotency_key == idempotency_key)
            ).one()
            ref.durum, ref.hata = "failed", f"{type(exc).__name__}: {exc}"[:1000]
        raise
    with session_scope() as s:
        ref = s.scalars(
            select(ExternalRef).where(ExternalRef.idempotency_key == idempotency_key)
        ).one()
        ref.durum, ref.external_key, ref.hata = "created", sonuc, None
    return sonuc


def _comment_with_marker(jira: Any, key: str, marker: str) -> str | None:
    for c in jira.get_comments(key):
        if marker in c.body:
            return c.id
    return None


_SORU_TURU = {
    "ambiguity": "belirsizlik",
    "missing_ac": "eksik kabul kriteri",
    "conflict": "çelişki",
    "untestable": "test edilemez",
}


def _soru_satiri(i: int, q: dict[str, Any]) -> str:
    """Soru, PO'nun cevapta kullanacağı kimlikle yazılır ("Q3: …" → `map_po_answers`). Sıra
    numarası kullanılmaz: açık / düzeltmeyle değişen listeleri ayrı sıralanır ve "Q1" yanlış
    soruya eşlenirdi."""
    ref = f"{q['ac_ref']} · " if q.get("ac_ref") else ""
    qid = str(q.get("id") or f"Q{i}")
    return f"- {qid} [{ref}{_SORU_TURU.get(q['type'], q['type'])}] {q['text']}"


def question_refs(q: dict[str, Any]) -> set[str]:
    """Sorunun ilgilendiği AC'ler: `ac_ref` ve metinde geçen ACn'ler (ör. "AC3 … AC6")."""
    refs = set(ac_refs(str(q.get("text") or "")))
    if q.get("ac_ref"):
        refs.update(ac_refs(str(q["ac_ref"])))
    return refs


def split_questions(
    sorular: Sequence[dict[str, Any]],
    degisen: set[str],
    cozulen: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """(açık sorular, düzeltmeyle metni değişen AC'lere ait sorular, tutarlılık bulgusunun insan
    kararıyla kapanan sorular — `cozulen`: soru kimliği → açıklama)."""
    acik, degisti, kapanan = [], [], []
    cozulen = cozulen or {}
    for q in sorular:
        if str(q.get("id") or "") in cozulen:
            kapanan.append(q)
        elif question_refs(q) & degisen:
            degisti.append(q)
        else:
            acik.append(q)
    return acik, degisti, kapanan


# Ön inceleme sorusunu kapatabilecek tutarlılık bulgusu türleri (soru türüne göre).
_SORU_BULGU_TURLERI: dict[str, frozenset[str]] = {
    "conflict": frozenset({"internal_contradiction", "doc_vs_code", "doc_vs_data"}),
    "ambiguity": frozenset({"ambiguous", "internal_contradiction", "doc_vs_code", "doc_vs_data"}),
    "missing_ac": frozenset({"missing_in_doc"}),
    "untestable": frozenset({"ambiguous"}),
}
# Soruyu belge düzeyinde kapatan kararlar (code_defect kodu düzeltir: soru açık kalır).
_SORU_KAPATAN_KARARLAR = ("fix_doc", "accept_difference")


def _ref_kumesi(doc_ref: str) -> set[str]:
    return set(ac_refs(doc_ref))


def questions_resolved_by_findings(
    s: Session, req_id: uuid.UUID, sorular: Sequence[dict[str, Any]]
) -> dict[str, str]:
    """Güncel döngüde `fix_doc` / `accept_difference` kararıyla kapanmış tutarlılık bulgularının
    cevapladığı ön inceleme soruları (deterministik; soru kimliği → "doküman düzeltmesiyle
    cevaplandı: F2 (tur 1)").

    Eşleşme: sorunun türü bulgu türüyle uyumlu (`_SORU_BULGU_TURLERI`), sorunun AC kümesi boş değil
    ve bu tür kapanmış bulguların AC kümelerinin birleşimince tamamen kapsanıyor (ör. "AC3 ↔ AC6"
    çelişki bulgusu düzeltildiyse AC3/AC6 çelişki sorusu). AC'siz sorular hiç kapanmaz.
    """
    bas = cycle_start(s, req_id)
    if bas is None or not sorular:
        return {}
    kapananlar = [
        f
        for f in findings_of(s, req_id, ("resolved",))
        if f.kanit_dogrulandi and f.olusturma >= bas and f.analist_karari in _SORU_KAPATAN_KARARLAR
    ]
    out: dict[str, str] = {}
    for q in sorular:
        qid = str(q.get("id") or "")
        refs = question_refs(q)
        if not qid or not refs:
            continue
        turler = _SORU_BULGU_TURLERI.get(str(q.get("type") or ""), frozenset())
        uygun = [f for f in kapananlar if f.tur in turler and _ref_kumesi(f.doc_ref) & refs]
        kapsanan: set[str] = set()
        for f in uygun:
            kapsanan |= _ref_kumesi(f.doc_ref)
        if not uygun or not refs <= kapsanan:
            continue
        parcalar = []
        duzeltenler = [_bulgu_etiketi(s, f) for f in uygun if f.analist_karari == "fix_doc"]
        farklar = [_bulgu_etiketi(s, f) for f in uygun if f.analist_karari == "accept_difference"]
        if duzeltenler:
            parcalar.append("doküman düzeltmesiyle cevaplandı: " + ", ".join(duzeltenler))
        if farklar:
            parcalar.append("bilinçli fark kararıyla kapandı: " + ", ".join(farklar))
        out[qid] = "; ".join(parcalar)
    return out


def accepted_differences(s: Session, req_id: uuid.UUID) -> list[str]:
    """Güncel döngüde 'bilinçli fark' (accept_difference) kararıyla kapanan doğrulanmış bulgular
    (PO yorumu için satırlar: etiket, doc_ref, tür, gerekçe)."""
    bas = cycle_start(s, req_id)
    if bas is None:
        return []
    out = []
    for f in findings_of(s, req_id, ("resolved",)):
        if not f.kanit_dogrulandi or f.olusturma < bas or f.analist_karari != "accept_difference":
            continue
        gerekce = " ".join((f.gerekce or "-").split())[:300]
        out.append(f"- {_bulgu_etiketi(s, f)} [{f.doc_ref} · {f.tur} · {f.severity}] {gerekce}")
    return out


def _hedef_anahtari(hedef: str) -> tuple[int, str]:
    m = re.fullmatch(r"AC(\d+)", hedef)
    return (int(m.group(1)), "") if m else (0, hedef)


def review_comment(
    jira_key: str,
    verdict: str,
    sorular: Sequence[dict[str, Any]],
    mode: str,
    tip: str,
    marker: str,
    *,
    degisen: set[str] | None = None,
    ozet: str | None = None,
    model: str | None = None,
    cozulen: dict[str, str] | None = None,
    kabul_edilen: Sequence[str] = (),
) -> str:
    """PO'ya giden tek yorum: belge son halindeyken kalan sorular (§2 adım 2, §8.2a).

    Üretim modu dürüst etiketlenir (`mode_label`: elle hazırlanmış golden "kayıtlı model çıktısı"
    diye sunulmaz). REPLAY-MISS'te AI ön incelemesi yapılmamıştır: "sorular var" denmez.
    Tutarlılık bulgusunun insan kararıyla (düzeltme / bilinçli fark) kapattığı sorular PO'ya
    sorulmaz, "Çözüldü" altında bilgi olarak listelenir (`cozulen`); bilinçli fark kararları da
    PO'nun görmesi için listelenir (`kabul_edilen`).
    """
    cozulen = cozulen or {}
    acik, degisti, kapanan = split_questions(sorular, degisen or set(), cozulen)
    satirlar = [
        f"[{AI_LABEL}] Testing Probe ön inceleme — {jira_key} için PO teyidi",
        f"Üretim modu: {mode_label(mode, model)}",
        "Doküman tutarlılık denetiminden sonra son haline geldi; bu yorum son hale göre yazıldı.",
    ]
    if mode == "replay_miss":
        satirlar.append(
            "AI ön incelemesi yapılamadı (REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok); "
            "içeriği lütfen kendiniz değerlendirin (PO teyidi her durumda gerekir)."
        )
    else:
        oneri = (
            "hazır görünüyor" if verdict == "ready" else "PO'nun cevaplaması gereken sorular var"
        )
        satirlar.append(f"AI önerisi: {oneri} (PO teyidi her durumda gerekir).")
    if ozet:
        if degisen:
            # Ön inceleme özgün metne göre yapıldı; düzeltilen maddeler için özet bayat olabilir.
            maddeler = ", ".join(sorted(degisen, key=_hedef_anahtari))
            satirlar.append(
                "AI özeti (özgün metne göre, doküman düzeltmelerinden önce yazıldı; "
                f"{maddeler} sonradan değişti; model çıktısı, karar dayanağı değildir): "
                f"{ozet[:1000]}"
            )
        else:
            satirlar.append(f"AI özeti (model çıktısı, karar dayanağı değildir): {ozet[:1000]}")
    satirlar.append("")
    if acik:
        satirlar += [_soru_satiri(i, q) for i, q in enumerate(acik, start=1)]
    elif not degisti and not kapanan:
        satirlar.append("Soru yok.")
    else:
        satirlar.append("Açık soru kalmadı.")
    if degisti:
        satirlar += [
            "",
            "Doküman düzeltmesiyle metni değişen maddelere ait sorular (güncel metne göre hâlâ "
            "geçerliyse cevaplayın):",
            "",
        ]
        satirlar += [_soru_satiri(i, q) for i, q in enumerate(degisti, start=1)]
    if kapanan:
        satirlar += [
            "",
            "Çözüldü — doküman tutarlılık denetiminde analist kararıyla kapanan sorular (bilgi "
            "için; cevap gerekmez):",
            "",
        ]
        satirlar += [
            f"{_soru_satiri(i, q)} → {cozulen[str(q.get('id') or '')]}"
            for i, q in enumerate(kapanan, start=1)
        ]
    if kabul_edilen:
        satirlar += [
            "",
            "Analistin bilinçli fark olarak kabul ettiği doğrulanmış bulgular (belge bu haliyle "
            "bırakıldı; itirazınız varsa yorum yazın):",
            "",
            *kabul_edilen,
        ]
    satirlar += [
        "",
        "Cevaplarınızı bu story'ye yorum olarak, sorunun kimliğiyle yazın (ör. 'Q3: …'); gerekirse "
        "açıklamayı/kabul kriterlerini güncelleyin. "
        f"Onay için '{PO_APPROVED_LABEL}' etiketini ekleyin (bu yorumdan önce konmuş etiket onay "
        "sayılmaz; böyle bir etiket kaldırılır ve size yorumla bildirilir).",
        f"Denetim zinciri: {tip}",
        f"Kayıt: {marker}",
    ]
    return "\n".join(satirlar)


# ------------------------------------------------------------------ iş: ön inceleme


@dataclass(frozen=True)
class Snapshot:
    id: uuid.UUID
    kaynak: str
    jira_key: str | None
    baslik: str
    aciklama: str
    acs: list[str]
    hash: str
    tur: int

    def message(self) -> ModelMessage:
        """Story/serbest metin → tek güvenilmeyen blok (geçidin kanonik biçimi; golden eşleşmesi
        ve replay anahtarı kararlılığı bu biçime bağlıdır, rules/replay/README.md)."""
        if self.jira_key:
            blok = requirement_block(
                summary=self.baslik,
                description=self.aciklama,
                acceptance_criteria=self.acs,
                jira_key=self.jira_key,
            )
        else:
            blok = requirement_block(
                summary=self.baslik,
                description=self.aciklama,
                acceptance_criteria=self.acs,
                requirement_id=str(self.id),
            )
        return ModelMessage(role="user", content=blok)

    def replay_key(self, check_round: int = 1) -> dict[str, Any]:
        if self.jira_key:
            return {
                "name": golden_name(self.jira_key, check_round=check_round),
                "jira_key": self.jira_key,
            }
        return {
            "name": golden_name(FREE_TEXT_KEY, check_round=check_round),
            "requirement_id": str(self.id),
        }


def replay_key_for(gw: Any, purpose: str, snap: Snapshot, tur: int = 1) -> dict[str, Any]:
    """REPLAY anahtarı; story'nin adlandırılmış golden'ı yoksa dürüst REPLAY-MISS yedeğine düşer.

    Golden yalnızca seed story'leri (TPD-1…4) ve serbest metin için vardır. Başka bir story (ör.
    sonradan açılan TPD-17) için adlandırılmış golden aranırsa geçit `ReplayNotFound` verir ve
    gereksinim nedeni görünmeden `failed` olurdu; oysa amacın nötr yedeği (`on_miss.json`) vardır.
    Sıra: bu turun golden'ı → story'nin 1. tur golden'ı (2+ turda) → girdi beyanı Jira story'leriyle
    hiçbir zaman eşleşmeyen serbest metin golden'ı (`sources: serbest:*`). Sonuncusu her zaman
    eşleşmez → geçit nötr yedeği döndürür: mod `replay_miss` (asla `replay`/`live` değil), nedenler
    `ai_call.ek.replay_eslesme`'de; akış bu turu güvenilmez sayar (insan kararı). Sıkı kipte
    (`TP_REPLAY_STRICT=1`) geçit yine `ReplayMiss` verir. Canlı modda ad kullanılmaz.
    """
    key = snap.replay_key(check_round=tur)
    store = getattr(gw, "replay_store", None)
    if not snap.jira_key or store is None:
        return key
    try:
        adaylar = [golden_name(snap.jira_key, check_round=tur), golden_name(snap.jira_key)]
        for ad in dict.fromkeys(adaylar):
            if store.golden_path(purpose, ad).is_file():
                return {**key, "name": ad}
        if store.miss_path(purpose).is_file():
            yedekler = [golden_name(FREE_TEXT_KEY, check_round=tur), golden_name(FREE_TEXT_KEY)]
            for ad in dict.fromkeys(yedekler):
                if store.golden_path(purpose, ad).is_file():
                    return {**key, "name": ad, "golden_yok": snap.jira_key}
    except Exception as exc:  # yapılandırma hatası: adlandırılmış anahtarla geçide bırak
        log.warning("REPLAY yedek adı belirlenemedi (%s): %s", purpose, exc)
    return key


def snapshot(session: Session, req_id: uuid.UUID, beklenen: str = "in_review") -> Snapshot | None:
    req = session.get(Requirement, req_id, populate_existing=True)
    if req is None or req.durum != beklenen:
        return None
    return Snapshot(
        req.id,
        req.kaynak,
        req.jira_key,
        req.baslik,
        req.aciklama,
        list(req.kabul_kriterleri),
        content_hash_of(req),
        req.kontrol_turu,
    )


def run_pre_review(engine: Engine, job_id: uuid.UUID, yuk: dict[str, Any]) -> dict[str, Any]:
    req_id = uuid.UUID(str(yuk["requirement_id"]))
    wf_id = _wf_id(yuk)
    with session_scope() as s:
        snap = snapshot(s, req_id)
    if snap is None:
        return {"atlandi": "gereksinim incelemede değil"}

    gw = services.gateway(engine)
    schema = load_schema(gw.rules_dir, "requirement_review")
    result = gw.call(
        "requirement_review",
        "requirement-review",
        [snap.message()],
        schema,
        replay_key=replay_key_for(gw, "requirement_review", snap),
        workflow_id=wf_id,
        call_id=deterministic_call_id(job_id, "requirement_review"),
    )
    cikti = result.output
    rr_id = uuid.uuid5(NS, f"{wf_id or job_id}:requirement_review")
    with session_scope() as s:
        req = lock_requirement(s, req_id)
        if req.durum != "in_review" or content_hash_of(req) != snap.hash:
            return {"atlandi": "gereksinim inceleme sırasında değişti"}
        rr = s.get(RequirementReview, rr_id)
        if rr is None:
            supersede_reviews(s, req.id, SYSTEM)
            rr = RequirementReview(
                id=rr_id,
                requirement_id=req.id,
                sorular=list(cikti["questions"]),
                verdict=cikti["verdict"],
                ai_call_id=result.call_id,
                uretim_modu=result.mode,
            )
            s.add(rr)
            s.flush()
            s.add(
                RequirementReviewEk(
                    review_id=rr.id,
                    ozet=str(cikti.get("summary") or "")[:4000],
                    aciklama=snap.aciklama,
                    kabul_kriterleri=list(snap.acs),
                )
            )
            s.flush()
            audit_on_commit(
                s,
                "system",
                "requirement.pre_review",
                f"requirement:{req.id}",
                {
                    "requirement_review_id": rr.id,
                    "verdict": rr.verdict,
                    "soru_sayisi": len(rr.sorular),
                    "mod": result.mode,
                    "ai_call_id": result.call_id,
                },
            )
            emit_requirement(s, req, olay="pre_review", mod=result.mode)
        verdict, mode = rr.verdict, rr.uretim_modu or result.mode

    # Jira yorumu burada YAZILMAZ: sorular tutarlılık döngüsünden sonra, belge son hal olunca
    # (`run_po_request`) gider; PO henüz değişecek metin hakkında soru almaz (§2 adım 2).
    with engine.begin() as conn:
        enqueue(
            conn,
            JOB_CONSISTENCY,
            {"requirement_id": str(req_id), "tur": snap.tur, **_wf_yuk(wf_id)},
            idempotency_key=f"{JOB_CONSISTENCY}:{wf_id or job_id}:{snap.tur}",
            workflow_id=wf_id,
        )
    return {"requirement_review_id": str(rr_id), "verdict": verdict, "mod": mode}


@dataclass(frozen=True)
class PoRequest:
    req_id: uuid.UUID
    key: str
    rr_id: uuid.UUID | None
    verdict: str
    sorular: list[dict[str, Any]]
    mode: str
    ozet: str | None
    degisen: set[str]
    son_hal_hash: str
    son_hal_zamani: datetime | None
    model: str | None = None
    cozulen: dict[str, str] = field(default_factory=dict)
    kabul_edilen: list[str] = field(default_factory=list)


def po_request_snapshot(s: Session, req_id: uuid.UUID) -> PoRequest | None:
    """Son halde (pending_po) PO'ya gidecek yorumun içeriği; durum uygun değilse None."""
    req = s.get(Requirement, req_id, populate_existing=True)
    if req is None or req.kaynak != "jira" or req.jira_key is None or req.durum != "pending_po":
        return None
    kayit = s.get(RequirementAkis, req.id)
    h = content_hash_of(req)
    if kayit is None or kayit.son_hal_hash != h:
        return None
    aktif = active_reviews(s, req.id)
    rr = aktif[-1] if aktif else None
    ek = s.get(RequirementReviewEk, rr.id) if rr is not None else None
    degisen = (
        changed_targets(ek.aciklama, ek.kabul_kriterleri, req.aciklama, req.kabul_kriterleri)
        if ek is not None
        else set()
    )
    return PoRequest(
        req.id,
        req.jira_key,
        rr.id if rr is not None else None,
        rr.verdict if rr is not None else "needs_po",
        list(rr.sorular) if rr is not None else [],
        (rr.uretim_modu if rr is not None else None) or "bilinmiyor",
        (ek.ozet or None) if ek is not None else None,
        degisen,
        h,
        kayit.son_hal_zamani,
        (s.get(AiCall, rr.ai_call_id).model if rr is not None and rr.ai_call_id else None),
        questions_resolved_by_findings(s, req.id, list(rr.sorular)) if rr is not None else {},
        accepted_differences(s, req.id),
    )


def run_po_request(engine: Engine, job_id: uuid.UUID, yuk: dict[str, Any]) -> dict[str, Any]:
    """Belge son hal: PO'ya soru yorumu + `tp-po-pending`; son halden önceki onay etiketi kalkar."""
    req_id = uuid.UUID(str(yuk["requirement_id"]))
    with session_scope() as s:
        istek = po_request_snapshot(s, req_id)
    if istek is None:
        return {"atlandi": "gereksinim PO teyidi beklemiyor ya da son hal değişti"}
    if istek.son_hal_hash != yuk.get("son_hal_hash"):
        return {"atlandi": "bu iş eski bir son hale ait"}
    yorum_id = post_po_request(engine, istek)
    return {"jira_comment_id": yorum_id, "degisen": sorted(istek.degisen)}


def po_request_key(sahip: uuid.UUID, son_hal_hash: str) -> str:
    """PO soru yorumunun idempotency anahtarı (son hal + etkin ön inceleme başına bir yorum)."""
    return f"jira:comment:po_request:{sahip}:{son_hal_hash}"


def post_po_request(engine: Engine, istek: PoRequest) -> str | None:
    jira = services.jira()
    key = istek.key
    sahip = istek.rr_id or istek.req_id
    anahtar = po_request_key(sahip, istek.son_hal_hash)
    marker = _marker(anahtar)
    with engine.connect() as conn:
        tip = chain_tip(conn)
    govde = review_comment(
        key,
        istek.verdict,
        istek.sorular,
        istek.mode,
        tip,
        marker,
        degisen=istek.degisen,
        ozet=istek.ozet,
        model=istek.model,
        cozulen=istek.cozulen,
        kabul_edilen=istek.kabul_edilen,
    )
    yorum_id = jira_once(
        engine,
        entity_turu="requirement_review" if istek.rr_id else "requirement",
        entity_id=sahip,
        idempotency_key=anahtar,
        action=lambda: jira_notify.post_comment(jira, key, govde, jira_notify.PO_SORU),
        find_existing=lambda: _comment_with_marker(jira, key, marker),
    )
    # Soru yorumundan önce konmuş onay etiketi bayattır (PO soruları/son hali görmeden kondu):
    # kaldırılır. Yorumdan sonra konmuş geçerli bir onay varsa dokunulmaz (PO hızlı davranmış).
    hesaplar = services.po_accounts()
    esik = approval_threshold(jira, key, anahtar, istek.son_hal_zamani)
    if PO_APPROVED_LABEL in jira.get_issue(key).labels and not fresh_approvals(
        jira, key, hesaplar, esik
    ):
        remove_stale_approval(
            engine, jira, istek.req_id, key, esik, hesaplar, istek.son_hal_hash, ekle_bekleme=False
        )
    jira.add_labels(key, [PO_PENDING_LABEL])
    with session_scope() as s:
        rr = s.get(RequirementReview, istek.rr_id) if istek.rr_id else None
        if rr is not None and rr.jira_comment_id != yorum_id:
            rr.jira_comment_id = yorum_id
        audit_on_commit(
            s,
            "system",
            "jira.comment",
            f"requirement:{istek.req_id}",
            {
                "jira_key": key,
                "comment_id": yorum_id,
                "etiket": PO_PENDING_LABEL,
                "requirement_review_id": istek.rr_id,
                "son_hal_hash": istek.son_hal_hash,
                "duzeltmeyle_degisen": sorted(istek.degisen),
                "kararla_kapanan_sorular": istek.cozulen,
            },
        )
    return yorum_id


def fresh_approvals(
    jira: Any, key: str, hesaplar: frozenset[str], esik: datetime | None
) -> list[Any]:
    """Eşikten (`approval_threshold`) SONRA yetkili PO'nun koyduğu, içerik değişmeden geçerli
    onaylar. Eşik yoksa (soru yorumu henüz yazılmadı) hiçbir onay taze değildir."""
    if esik is None:
        return []
    onaylar = jira.po_approvals(key, sorted(hesaplar))
    return [o for o in onaylar if o.at is not None and o.at >= esik]


def approval_threshold(
    jira: Any, key: str, istek_anahtari: str, son_hal_zamani: datetime | None
) -> datetime | None:
    """PO onay etiketinin taze sayılacağı an: belge son hal anı ile PO soru yorumunun Jira'daki
    yazılma anının geç olanı (yorum: "bu yorumdan önce konmuş etiket onay sayılmaz").

    Soru yorumu henüz yazılmadıysa (son hal işi kuyrukta ya da Jira'ya erişilemedi) None: PO
    soruları görmeden konan etiket onay sayılmaz; yorum yazılınca (PO sorgusu işi yeniden kuyruğa
    alır) yeniden konmalıdır. Etiket ve yorum zamanları aynı saatten (Jira) gelir.
    """
    if son_hal_zamani is None:
        return None
    marker = _marker(istek_anahtari)
    yorum = next((c for c in jira.get_comments(key) if marker in c.body), None)
    if yorum is None:
        return None
    if yorum.created is None:
        return son_hal_zamani
    return max(son_hal_zamani, yorum.created)


def _authorized_label_adds(jira: Any, key: str, hesaplar: frozenset[str]) -> list[Any]:
    from tp_core.integrations.jira import authorized_po_approvals

    botlar = getattr(jira, "bot_identities", None)
    return authorized_po_approvals(
        jira.label_history(key, PO_APPROVED_LABEL),
        sorted(hesaplar),
        botlar() if callable(botlar) else (),
    )


def remove_stale_approval(
    engine: Engine,
    jira: Any,
    req_id: uuid.UUID,
    key: str,
    esik: datetime | None,
    hesaplar: frozenset[str],
    son_hal_hash: str | None,
    *,
    ekle_bekleme: bool = True,
) -> str:
    """Taze sayılmayan `tp-po-approved` etiketini kaldırır ve PO'ya Jira yorumuyla bildirir.

    Okuma (taze onay yok) ile kaldırma ayrı Jira çağrılarıdır: arada PO geçerli bir etiket koymuş
    olabilir (TOCTOU). Bot onay etiketini geri koyamaz (yalnızca PO yazar); bu yüzden kaldırmadan
    sonra etiket geçmişi yeniden okunur, eşikten sonraki yetkili ekleme görülürse PO'dan etiketi
    yeniden eklemesi açıkça istenir. Her durumda PO'ya etiketinin neden sayılmadığı yazılır.
    """
    jira.remove_labels(key, [PO_APPROVED_LABEL])
    if ekle_bekleme:
        jira.add_labels(key, [PO_PENDING_LABEL])
    eklemeler = _authorized_label_adds(jira, key, hesaplar)
    son = eklemeler[-1] if eklemeler else None
    yarista = son is not None and esik is not None and son.at is not None and son.at >= esik
    sonuc = "yarista_kaldirildi" if yarista else "bayat_kaldirildi"
    if son is not None:
        zaman = son.at.isoformat() if son.at is not None else "?"
        if yarista:
            neden = (
                "etiketiniz, eski bir etiket temizlenirken aynı anda kaldırıldı (zamanlama "
                "çakışması). Onayınız kaydedilmedi"
            )
        elif esik is None:
            neden = "PO soru yorumu henüz yazılmadan konduğu için onay sayılmadı"
        else:
            neden = "belge son haline gelmeden / soru yorumundan önce konduğu için onay sayılmadı"
        govde = (
            f"[{AI_LABEL}] Testing Probe — {key}: '{PO_APPROVED_LABEL}' etiketi kaldırıldı "
            f"({son.author}, {zaman}): {neden}. Onaylıyorsanız soru yorumunu okuduktan sonra "
            f"etiketi yeniden ekleyin."
        )
        anahtar = f"jira:comment:po_label_removed:{req_id}:{son_hal_hash}:{zaman}"
        notu = _marker(anahtar)
        jira_once(
            engine,
            entity_turu="requirement",
            entity_id=req_id,
            idempotency_key=anahtar,
            action=lambda: jira_notify.post_comment(
                jira, key, f"{govde}\nKayıt: {notu}", jira_notify.PO_ETIKET_KALDIRILDI
            ),
            find_existing=lambda: _comment_with_marker(jira, key, notu),
        )
    with session_scope() as s:
        audit_on_commit(
            s,
            "system",
            "requirement.po_label_removed",
            f"requirement:{req_id}",
            {
                "jira_key": key,
                "esik": esik,
                "sonuc": sonuc,
                "son_ekleme": None
                if son is None
                else {"yazar": son.author, "zaman": son.at.isoformat() if son.at else None},
            },
        )
    return sonuc


def po_request_status(s: Session, req: Requirement) -> dict[str, Any] | None:
    """Jira yolunda son haldeki PO soru yorumunun durumu (portal: "PO'ya soru yazılamadı").

    `yazildi` (Jira'da), `bekliyor` (iş kuyrukta/çalışıyor ya da henüz kuyruğa girmedi; PO sorgusu
    kuyruğa alır), `basarisiz` (son iş kalıcı hata verdi; PO sorgusu yeniden kuyruğa alır).
    """
    if req.kaynak != "jira" or req.durum != "pending_po":
        return None
    kayit = s.get(RequirementAkis, req.id)
    if kayit is None or kayit.son_hal_hash is None or kayit.son_hal_hash != content_hash_of(req):
        return None
    aktif = active_reviews(s, req.id)
    anahtar = po_request_key(aktif[-1].id if aktif else req.id, kayit.son_hal_hash)
    ref = s.scalars(select(ExternalRef).where(ExternalRef.idempotency_key == anahtar)).first()
    if ref is not None and ref.durum == "created":
        return {"durum": "yazildi", "jira_comment_id": ref.external_key, "hata": None}
    son_is = s.execute(
        text(
            "SELECT durum, son_hata FROM job WHERE tur = :t AND yuk->>'requirement_id' = :id "
            "AND yuk->>'son_hal_hash' = :h ORDER BY olusturma DESC LIMIT 1"
        ),
        {"t": JOB_PO_REQUEST, "id": str(req.id), "h": kayit.son_hal_hash},
    ).first()
    if son_is is not None and son_is[0] in ("failed", "cancelled"):
        hata = son_is[1] or (ref.hata if ref is not None else None) or "iş tamamlanamadı"
        return {"durum": "basarisiz", "jira_comment_id": None, "hata": hata[:500]}
    return {"durum": "bekliyor", "jira_comment_id": None, "hata": None}


def ensure_po_request(engine: Engine, req_id: uuid.UUID) -> str | None:
    """Son haldeki Jira gereksiniminin PO soru yorumu yazılmadıysa ve etkin işi yoksa
    `requirements.po_request`'i yeniden kuyruğa alır (Jira bir süre erişilemediyse iş 5 denemede
    kalıcı hata verir; gereksinim `pending_po`'da kaldığı için `mark_failed` ona dokunmaz)."""
    with session_scope() as s:
        req = s.get(Requirement, req_id)
        if req is None:
            return None
        durum = po_request_status(s, req)
        if durum is None or durum["durum"] == "yazildi":
            return None
        kayit = s.get(RequirementAkis, req_id)
        conn = s.connection()
        idempotency_lock(conn, f"{JOB_PO_REQUEST}:{req_id}")
        etkin = conn.execute(
            text(
                "SELECT count(*) FROM job WHERE tur = :t AND yuk->>'requirement_id' = :id "
                "AND durum IN ('queued', 'retry', 'running')"
            ),
            {"t": JOB_PO_REQUEST, "id": str(req_id)},
        ).scalar_one()
        if etkin:
            return "kuyrukta"
        onceki = conn.execute(
            text("SELECT count(*) FROM job WHERE tur = :t AND yuk->>'requirement_id' = :id"),
            {"t": JOB_PO_REQUEST, "id": str(req_id)},
        ).scalar_one()
        enqueue(
            conn,
            JOB_PO_REQUEST,
            {"requirement_id": str(req_id), "son_hal_hash": kayit.son_hal_hash},
            idempotency_key=f"{JOB_PO_REQUEST}:{req_id}:{kayit.son_hal_hash}:yeniden:{onceki}",
        )
        audit_on_commit(
            s,
            "system",
            "requirement.po_request_requeued",
            f"requirement:{req_id}",
            {"onceki_is_sayisi": onceki, "onceki_durum": durum},
        )
        return "yeniden_kuyruga_alindi"


# ----------------------------------------------------------- iş: tutarlılık denetimi


def _executor(code: CodeTools, data: DataTools) -> Callable[[str, dict[str, Any]], str]:
    tablo: dict[str, Callable[[dict[str, Any]], str]] = {
        "search_code": code.search_code,
        "get_file_contents": code.get_file_contents,
        "db_schema": data.db_schema,
        "db_query": data.db_query,
    }

    def execute(name: str, args: dict[str, Any]) -> str:
        fn = tablo.get(name)
        if fn is None:  # geçit izin listesi zaten reddeder; ikinci savunma
            raise PermissionError(f"Araç izinli değil: {name}")
        return fn(args or {})

    return execute


def run_consistency(engine: Engine, job_id: uuid.UUID, yuk: dict[str, Any]) -> dict[str, Any]:
    req_id = uuid.UUID(str(yuk["requirement_id"]))
    wf_id = _wf_id(yuk)
    tur = int(yuk.get("tur") or 1)
    with session_scope() as s:
        snap = snapshot(s, req_id)
    if snap is None:
        return {"atlandi": "gereksinim incelemede değil"}

    ayar = settings()
    forge = services.forge()
    sha = forge.head_sha(ayar.forge_ref)
    db = services.demo_db()
    gw = services.gateway(engine)
    code = CodeTools(forge, sha, ayar.forge_repo)
    data = DataTools(db, gw.masker)

    def adim(step: AgentStep) -> None:
        with engine.begin() as conn:
            publish_tx(
                conn,
                EV_AGENT_STEP,
                {
                    "requirement_id": req_id,
                    "amac": "consistency_check",
                    "arac": step.tool,
                    "izinli": step.allowed,
                    "ozet": step.result_summary[:200],
                },
            )

    result = gw.run_agent(
        "consistency_check",
        "consistency-check",
        [snap.message()],
        list(TOOL_SPECS),
        _executor(code, data),
        load_schema(gw.rules_dir, "consistency_check"),
        replay_key=replay_key_for(gw, "consistency_check", snap, tur),
        workflow_id=wf_id,
        call_id=deterministic_call_id(job_id, "consistency_check"),
        on_step=adim,
    )
    bulgular: list[dict[str, Any]] = list(result.output.get("findings") or [])
    verifier = EvidenceVerifier(forge, sha, db, repo=ayar.forge_repo)
    dogrulamalar = [verifier.verify(f, snap.acs) for f in bulgular]
    ai_call_id = result.call_ids[0] if result.call_ids else None

    with session_scope() as s:
        req = lock_requirement(s, req_id)
        if req.durum != "in_review" or content_hash_of(req) != snap.hash:
            raise FlowError("Gereksinim denetim sırasında değişti; sonuç kaydedilmedi")
        kontrol = store_check(
            s, req, snap, tur, sha, wf_id, ai_call_id, result.mode, bulgular, dogrulamalar
        )
        kontrol.notlar = str(result.output.get("notes") or "")[:2000]
        conclude_round(s, req, SYSTEM)
        finish_workflow(s, wf_id)
        return {
            "kontrol_id": str(kontrol.id),
            "tur": tur,
            "bulgu": kontrol.bulgu_toplam,
            "dogrulanan": kontrol.dogrulanan,
            "elenen": kontrol.elenen,
            "durum": req.durum,
            "mod": result.mode,
        }


def _sonraki_tur_var(req: Requirement) -> bool:
    return req.kontrol_turu < settings().max_rounds


def store_check(
    s: Session,
    req: Requirement,
    snap: Snapshot,
    tur: int,
    sha: str,
    wf_id: uuid.UUID | None,
    ai_call_id: uuid.UUID | None,
    mode: str,
    bulgular: Sequence[dict[str, Any]],
    dogrulamalar: Sequence[Verification],
) -> RequirementKontrol:
    sira = (
        s.scalar(
            select(func.coalesce(func.max(RequirementKontrol.sira), 0)).where(
                RequirementKontrol.requirement_id == req.id
            )
        )
        or 0
    ) + 1
    kontrol = RequirementKontrol(
        requirement_id=req.id,
        sira=sira,
        tur=tur,
        belge_hash=snap.hash,
        head_sha=sha,
        workflow_id=wf_id,
        ai_call_id=ai_call_id,
        uretim_modu=mode,
        bulgu_toplam=len(bulgular),
    )
    s.add(kontrol)
    s.flush()
    for f, v in zip(bulgular, dogrulamalar, strict=True):
        ref_metni = current_doc_text(f["doc_ref"], snap.aciklama, snap.acs)
        cf = ConsistencyFinding(
            requirement_id=req.id,
            kontrol_turu=tur,
            tur=f["type"],
            doc_ref=f["doc_ref"],
            kanitlar=list(f.get("evidence") or []),
            severity=f["severity"],
            onerilen_metin=f.get("suggested_doc_text"),
            ai_call_id=ai_call_id,
            uretim_modu=mode,
            kanit_dogrulandi=v.ok,
        )
        s.add(cf)
        s.flush()
        ek = ConsistencyFindingEk(
            finding_id=cf.id,
            kontrol_id=kontrol.id,
            bulgu_no=str(f.get("id") or ""),
            iddia=str(f.get("claim") or ""),
            gozlem=str(f.get("observed") or ""),
            # Fark yalnızca önerinin gerçekten değiştireceği hedefler üzerinden (ör. "AC3 ↔ AC6"
            # bulgusunun önerisi yalnızca AC3'ü yazıyorsa AC6 "silindi" görünmez).
            mevcut_doc_text=replaced_doc_text(
                f.get("suggested_doc_text"), f["doc_ref"], snap.aciklama, snap.acs
            ),
            ref_metni=ref_metni,
            ai_onerisi=f.get("suggested_doc_text"),
            dogrulama=v.checks,
        )
        s.add(ek)
        s.flush()
        if v.ok:
            transition(s, cf, "open", SYSTEM, "unverified", sebep="kanıt doğrulandı")
            kontrol.dogrulanan += 1
            tasinan = carried_duplicate(s, cf, ref_metni)
            onceki = None if tasinan is not None else previous_decision(s, cf, ref_metni)
            if tasinan is not None:
                # İçerik değişmeden yeniden denetlendi: aynı fark önceki turdan taşınan bulguda
                # zaten açık (karar orada verilir); tekrar gösterilmez.
                transition(
                    s,
                    cf,
                    "stale",
                    SYSTEM,
                    "open",
                    sebep=f"aynı bulgu önceki turdan açık: {_bulgu_etiketi(s, tasinan)} "
                    f"(bulgu {tasinan.id})",
                )
            elif onceki is not None:
                # Aynı fark önceki turda insan kararıyla kapandı: yeniden karar istenmez.
                ek.onceki_finding_id = onceki.id
                transition(
                    s,
                    cf,
                    "stale",
                    SYSTEM,
                    "open",
                    sebep=f"önceki karar geçerli: {onceki.analist_karari} "
                    f"(tur {onceki.kontrol_turu}, bulgu {onceki.id})",
                )
            elif cf.severity == "blocking":
                kontrol.engelleyici += 1
        else:
            nedenler = "; ".join(c["neden"] for c in v.checks if not c.get("ok"))
            transition(s, cf, "discarded", SYSTEM, "unverified", sebep=nedenler[:500])
            kontrol.elenen += 1
        emit(
            s,
            EV_FINDING,
            {
                "id": cf.id,
                "requirement_id": req.id,
                "kontrol_turu": tur,
                "dogrulandi": v.ok,
                "durum": cf.durum,
            },
        )
    audit_on_commit(
        s,
        "system",
        "requirement.consistency_checked",
        f"requirement:{req.id}",
        {
            "kontrol_id": kontrol.id,
            "tur": tur,
            "head_sha": sha,
            "belge_hash": snap.hash,
            "mod": mode,
            "bulgu": len(bulgular),
            "dogrulanan": kontrol.dogrulanan,
            "elenen": kontrol.elenen,
        },
    )
    return kontrol


def _kanit_izi(kanitlar: Sequence[Any]) -> frozenset[tuple[str, ...]]:
    iz: set[tuple[str, ...]] = set()
    for ev in kanitlar or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("kind") == "code":
            iz.add(("code", str(ev.get("path") or ""), str(ev.get("line"))))
        elif ev.get("kind") == "data":
            iz.add(("data", " ".join(str(ev.get("query") or "").lower().split())))
    return frozenset(iz)


def _ref_anahtari(doc_ref: str) -> tuple[str, ...]:
    refs = ac_refs(doc_ref)
    return tuple(sorted(set(refs))) if refs else (" ".join(doc_ref.lower().split()),)


def carried_duplicate(
    s: Session, cf: ConsistencyFinding, ref_metni: str | None
) -> ConsistencyFinding | None:
    """Önceki turdan taşınan (karar bekleyen / uygulanmamış) aynı fark: aynı tür, aynı AC kümesi,
    bu AC'lerin metni aynı. Kanıt izi aranmaz: belge değişmediği için aynı farkın kanıtı (ör.
    satır) değişse de bulgu aynıdır ve karar taşınan bulguda verilir."""
    anahtar = _ref_anahtari(cf.doc_ref)
    for aday in findings_of(s, cf.requirement_id, ACIK_BULGU):
        if aday.id == cf.id or aday.tur != cf.tur or not aday.kanit_dogrulandi:
            continue
        if aday.kontrol_turu >= cf.kontrol_turu:
            continue
        ek = s.get(ConsistencyFindingEk, aday.id)
        if ek is None or ek.ref_metni != ref_metni:
            continue
        if _ref_anahtari(aday.doc_ref) == anahtar:
            return aday
    return None


def previous_decision(
    s: Session, cf: ConsistencyFinding, ref_metni: str | None
) -> ConsistencyFinding | None:
    """Aynı fark için önceki turdaki insan kararı (code_defect / accept_difference).

    Eşleşme deterministiktir: aynı bulgu türü, aynı AC kümesi, bu AC'lerin metni aynı ve kanıt izi
    (kod: dosya + satır; veri: normalize sorgu) aynı. Belge ya da kanıt değiştiyse eşleşmez ve
    analist yeniden karar verir.
    """
    adaylar = s.scalars(
        select(ConsistencyFinding)
        .where(
            ConsistencyFinding.requirement_id == cf.requirement_id,
            ConsistencyFinding.id != cf.id,
            ConsistencyFinding.tur == cf.tur,
            ConsistencyFinding.durum == "resolved",
            ConsistencyFinding.analist_karari.in_(DEVREDILEN_KARARLAR),
        )
        .order_by(ConsistencyFinding.karar_zamani.desc().nulls_last())
    )
    anahtar, iz = _ref_anahtari(cf.doc_ref), _kanit_izi(cf.kanitlar)
    for aday in adaylar:
        ek = s.get(ConsistencyFindingEk, aday.id)
        if ek is None or ek.ref_metni is None or ek.ref_metni != ref_metni:
            continue
        if _ref_anahtari(aday.doc_ref) == anahtar and _kanit_izi(aday.kanitlar) == iz:
            return aday
    return None


def blocking_unresolved(s: Session, req_id: uuid.UUID) -> list[ConsistencyFinding]:
    return [
        f
        for f in findings_of(s, req_id, ACIK_BULGU)
        if f.severity == "blocking" and f.kanit_dogrulandi
    ]


def undecided_findings(s: Session, req_id: uuid.UUID) -> list[ConsistencyFinding]:
    """Doğrulanmış ve henüz insan kararı almamış bulgular (önem derecesinden bağımsız)."""
    return [f for f in findings_of(s, req_id, ("open",)) if f.kanit_dogrulandi]


def pending_fixes(s: Session, req_id: uuid.UUID) -> list[ConsistencyFinding]:
    return [f for f in findings_of(s, req_id, ("decided",)) if f.analist_karari == "fix_doc"]


def untrusted_check(s: Session, req_id: uuid.UUID) -> str | None:
    """Son denetim sonucu "tutarlı" demeye yetmiyorsa nedeni (fail-closed; Constitution VIII/XI).

    - REPLAY-MISS: REPLAY örnek çıktısı bu girdiye ait değil (başka bir golden'dan).
    - Dönen bulguların hiçbiri doğrulanamadı: çıktı belgeyle/kodla ilgisiz olabilir.
    """
    son = s.scalars(
        select(RequirementKontrol)
        .where(RequirementKontrol.requirement_id == req_id)
        .order_by(RequirementKontrol.sira.desc())
        .limit(1)
    ).first()
    if son is None:
        return None
    if son.uretim_modu == "replay_miss":
        return "son denetim REPLAY-MISS (REPLAY örnek çıktısı bu belgeye ait değil)"
    if son.bulgu_toplam > 0 and son.dogrulanan == 0:
        return f"son denetimin {son.bulgu_toplam} bulgusunun hiçbiri doğrulanamadı"
    return None


def conclude_round(s: Session, req: Requirement, actor: Actor) -> str:
    """Tur sonucu: karar bekleyen bulgu (engelleyici ya da uyarı) / uygulanmamış düzeltme varsa ya
    da denetim sonucu güvenilir değilse findings_open (insan kararı), yoksa son hal → PO."""
    if blocking_unresolved(s, req.id) or pending_fixes(s, req.id):
        transition(s, req, "findings_open", actor, "in_review", sebep="engelleyici bulgu var")
        emit_requirement(s, req, olay="findings_open")
        return "findings_open"
    if undecided_findings(s, req.id):
        # Uyarı da analist kararı ister (§8.2b adım 5): code_defect → bug taslağı yolu açık kalır.
        transition(
            s, req, "findings_open", actor, "in_review", sebep="karar bekleyen uyarı bulgusu var"
        )
        emit_requirement(s, req, olay="findings_open")
        return "findings_open"
    neden = untrusted_check(s, req.id)
    if neden is not None:
        transition(
            s,
            req,
            "findings_open",
            actor,
            "in_review",
            sebep=f"denetim sonucu güvenilir değil: {neden}; son hal analist onayıyla",
        )
        emit_requirement(s, req, olay="findings_open", guvenilmez=neden)
        return "findings_open"
    finalize(s, req, actor)
    return "pending_po"


def finalize(s: Session, req: Requirement, actor: Actor, *, sebep: str | None = None) -> None:
    """Belge son hal (doc_final) → PO teyidi bekleniyor (pending_po).

    Jira yolunda PO'ya soru yorumu ve etiket işi (`requirements.po_request`) kuyruğa girer.
    """
    transition(s, req, "doc_final", actor, req.durum, sebep=sebep or "engelleyici bulgu kalmadı")
    kayit = akis(s, req)
    kayit.son_hal_hash = content_hash_of(req)
    kayit.son_hal_zamani = now()
    transition(s, req, "pending_po", actor, "doc_final", sebep="PO teyidi bekleniyor")
    audit_on_commit(
        s,
        actor_name(actor),
        "requirement.doc_final",
        f"requirement:{req.id}",
        {
            "son_hal_hash": kayit.son_hal_hash,
            "kontrol_turu": req.kontrol_turu,
            "sebep": sebep or "engelleyici bulgu kalmadı",
        },
    )
    if req.kaynak == "jira":
        enqueue(
            s.connection(),
            JOB_PO_REQUEST,
            {"requirement_id": str(req.id), "son_hal_hash": kayit.son_hal_hash},
            idempotency_key=f"{JOB_PO_REQUEST}:{req.id}:{kayit.son_hal_zamani.isoformat()}",
        )
        ensure_po_poll(s.connection())
    emit_requirement(s, req, olay="doc_final", son_hal_hash=kayit.son_hal_hash)


def maybe_finalize(s: Session, req: Requirement, actor: Actor) -> bool:
    if req.durum != "findings_open":
        return False
    if blocking_unresolved(s, req.id) or pending_fixes(s, req.id) or undecided_findings(s, req.id):
        return False
    if untrusted_check(s, req.id) is not None:
        return False  # son hali analist açıkça verir (apply-doc-fixes, düzeltme yokken)
    finalize(s, req, actor)
    return True


# --------------------------------------------------------------- analist kararları


def decide_finding(
    s: Session,
    finding: ConsistencyFinding,
    user: Principal,
    karar: str,
    icerik_hash: str | None,
    metin: str | None = None,
    gerekce: str | None = None,
) -> BugDraft | None:
    req = lock_requirement(s, finding.requirement_id)
    s.refresh(finding, with_for_update=True)
    if req.durum != "findings_open":
        raise FlowError(f"Gereksinim karar beklemiyor (durum: {req.durum})")
    if not finding.kanit_dogrulandi or finding.durum not in ACIK_BULGU:
        raise FlowError(f"Bu bulgu için karar verilemez (durum: {finding.durum})")
    if karar not in ("fix_doc", "code_defect", "accept_difference"):
        raise FlowInputError("Karar fix_doc, code_defect veya accept_difference olmalı")
    if icerik_hash is None:
        raise FlowInputError("Karar, görüntülenen içeriğin hash'ini (icerik_hash) taşımalı")
    gerekce = (gerekce or "").strip() or None
    if karar == "accept_difference" and not gerekce:
        raise FlowInputError("Bilinçli fark kararı için gerekçe zorunludur")

    degisiklik: dict[str, Any] | None = None
    if karar == "fix_doc":
        son_metin = (metin if metin is not None else finding.onerilen_metin or "").strip()
        if not son_metin:
            raise FlowInputError("Düzeltilmiş doküman metni boş olamaz")
        try:
            validate_fix_text(son_metin, req.aciklama, req.kabul_kriterleri)
            hedefler = parse_fix_text(son_metin)
        except DocMergeError as exc:
            raise FlowInputError(str(exc)) from exc
        if (
            son_metin == (finding.onerilen_metin or "").strip()
            and DESC in hedefler
            and not refers_to_description(finding.doc_ref)
        ):
            # Savunma derinliği (TPD-3): model önerisi "ACn: " önekisiz satırla açıklamanın
            # tamamını değiştirirdi, oysa bulgu yalnızca AC'lere atıf yapıyor.
            raise FlowInputError(
                "Önerilen düzeltme açıklamayı değiştiriyor ama bulgu yalnızca kabul kriterlerine "
                f"atıf yapıyor ({finding.doc_ref}); metni düzenleyip her satırı 'ACn: ' ile "
                "başlatın"
            )
        if son_metin != finding.onerilen_metin:
            degisiklik = {"onerilen_metin": son_metin}

    if karar == "fix_doc":
        ek = s.get(ConsistencyFindingEk, finding.id)
        if ek is not None:
            # Gösterilen fark = yazılacak düzeltmenin gerçekten değiştireceği metin.
            ek.mevcut_doc_text = replaced_doc_text(
                son_metin, finding.doc_ref, req.aciklama, req.kabul_kriterleri
            )
    if finding.durum == "decided":
        transition(s, finding, "open", user, "decided", sebep="karar değiştiriliyor")
    record_approval(
        s,
        finding,
        user,
        karar,
        gerekce=gerekce,
        beklenen_hash=icerik_hash,
        degisiklik=degisiklik,
    )
    transition(s, finding, "decided", user, "open")
    taslak: BugDraft | None = None
    if karar == "code_defect":
        taslak = ensure_bug_draft(s, finding, req, user)
        # Faz 4: taslak hemen mükerrer arama + AI taslak hattına girer (bugs.prepare).
        from tp_core.features.bugs import adopt_draft

        adopt_draft(s, taslak.id, aktor=user.kullanici_adi)
    if karar != "fix_doc":
        transition(s, finding, "resolved", user, "decided", sebep=karar)
    maybe_finalize(s, req, user)
    emit_requirement(s, req, olay="finding_decided", finding_id=finding.id, karar=karar)
    return taslak


def bug_draft_for(s: Session, finding: ConsistencyFinding) -> BugDraft | None:
    """Bulgunun bug taslağı: kendi taslağı; yoksa aynı farkın (gereksinim + tür + doc_ref)
    reddedilmemiş taslağı; yoksa devraldığı önceki kararın taslağı."""
    kendi = s.scalars(select(BugDraft).where(BugDraft.finding_id == finding.id)).first()
    if kendi is not None:
        return kendi
    ek = s.get(ConsistencyFindingEk, finding.id)
    if finding.analist_karari != "code_defect" and (ek is None or ek.onceki_finding_id is None):
        return None
    return s.scalars(
        select(BugDraft)
        .join(ConsistencyFinding, ConsistencyFinding.id == BugDraft.finding_id)
        .where(
            ConsistencyFinding.requirement_id == finding.requirement_id,
            ConsistencyFinding.tur == finding.tur,
            ConsistencyFinding.doc_ref == finding.doc_ref,
            BugDraft.durum != "dismissed",
        )
        .order_by(BugDraft.olusturma)
        .limit(1)
    ).first()


def ensure_bug_draft(
    s: Session, finding: ConsistencyFinding, req: Requirement, user: Principal
) -> BugDraft:
    """`code_defect` → bug taslağı (Faz 4 özelliği tamamlar; burada asgari içerik).

    İçerik şablonla, bulgunun doğrulanmış kanıtından üretilir (`icerik.uretim = "sablon"`); model
    çağrısı yoktur, bu yüzden `uretim_modu`/`ai_call_id` boştur (portalda AI rozeti çıkmaz).

    Aynı gereksinimde aynı fark (tür + doc_ref) için açık (reddedilmemiş) taslak varsa yenisi
    açılmaz; o döner (ör. 2. turda aynı kredi limiti farkına yeniden "kod hatalı" denmesi).
    """
    mevcut = bug_draft_for(s, finding)
    if mevcut is not None:
        return mevcut
    ek = s.get(ConsistencyFindingEk, finding.id)
    kontrol = s.get(RequirementKontrol, ek.kontrol_id) if ek is not None else None
    sha = (kontrol.head_sha or "")[:12] if kontrol is not None else ""
    iddia = ek.iddia if ek is not None else ""
    gozlem = ek.gozlem if ek is not None else ""
    kanitlar = []
    adimlar: list[str] = []
    for ev in finding.kanitlar:
        if ev.get("kind") == "code":
            yer = f"{ev.get('repo')} · {ev.get('path')}:{ev.get('line')}"
            kanitlar.append({"tur": "code", "url": None, "etiket": yer})
            alinti = " ".join(str(ev.get("snippet") or "").split())[:200]
            adimlar.append(
                f"Kodda {yer} (commit {sha or 'main'}) satırını açın"
                + (f": `{alinti}`" if alinti else "")
            )
        else:
            kanitlar.append({"tur": "data", "url": None, "etiket": str(ev.get("query"))})
            adimlar.append(
                f"Salt okuma veritabanında `{ev.get('query')}` sorgusunu çalıştırın; sonuç: "
                f"{ev.get('result_digest') or '-'}"
            )
    belge = ek.mevcut_doc_text if ek is not None and ek.mevcut_doc_text else finding.doc_ref
    adimlar.append(f"Dokümandaki beklenen davranışı ({belge[:300]}) uygulamada deneyin")
    if gozlem:
        adimlar.append(f"Gözlenen: {gozlem[:300]}")
    icerik = {
        "summary": f"{req.jira_key or req.baslik} {finding.doc_ref}: {iddia or finding.tur}"[:200],
        # Şablonla (deterministik) üretildi: model çıktısı değil; adımlar bulgunun doğrulanmış
        # kanıtından gelir (Faz 4 bug taslağı ajanı yerine geçmez).
        "uretim": "sablon",
        "steps": adimlar,
        "expected": (ek.mevcut_doc_text if ek is not None else None) or iddia,
        "actual": gozlem,
        "environment": f"Tutarlılık denetimi · {settings().forge_repo}@{sha or 'main'}",
        "evidence": kanitlar,
        "story_key": req.jira_key,
        "test_case_key": None,
        "severity_suggestion": "major" if finding.severity == "blocking" else "minor",
        "labels": [AI_LABEL],
        "kaynak": "consistency_finding",
        "finding_id": str(finding.id),
    }
    taslak = BugDraft(
        finding_id=finding.id,
        icerik=icerik,
        icerik_hash=content_hash(icerik),
        # Taslak modelden değil şablondan gelir: bulgunun AI modu (replay/live) taşınmaz.
        ai_call_id=None,
        uretim_modu=None,
    )
    s.add(taslak)
    s.flush()
    audit_on_commit(
        s,
        user.kullanici_adi,
        "bug_draft.created",
        f"bug_draft:{taslak.id}",
        {"finding_id": finding.id, "requirement_id": req.id, "hash": taslak.icerik_hash},
    )
    return taslak


# ------------------------------------------------------------ doküman düzeltmesi


def _fix_list(s: Session, fixes: Sequence[ConsistencyFinding]) -> list[DocFix]:
    out = []
    for f in fixes:
        # Portaldaki etiketle aynı (`bulgu_etiketi`): "F2 (tur 1)".
        out.append(DocFix(_bulgu_etiketi(s, f), f.doc_ref, f.onerilen_metin or ""))
    return out


def planned_merge(s: Session, req: Requirement) -> tuple[list[ConsistencyFinding], MergeResult]:
    fixes = pending_fixes(s, req.id)
    for f in fixes:
        if not approved_hash_matches(s, f, frozenset({"fix_doc"})):
            raise FlowError(
                "Bir düzeltmenin içeriği onaydan sonra değişmiş; bulguyu yeniden onaylayın"
            )
    return fixes, merge_fixes(req.aciklama, req.kabul_kriterleri, _fix_list(s, fixes))


def accept_difference_conflicts(
    s: Session, req: Requirement, fixes: Sequence[ConsistencyFinding]
) -> list[str]:
    """Onaylı düzeltmelerden, güncel döngüde 'bilinçli fark' (accept_difference) kararıyla olduğu
    gibi bırakılan bir maddeyi yeniden yazanlar (Türkçe açıklamalar; boş = çelişki yok).

    Bilinçli fark kararı, kararın verildiği andaki madde metnine bağlıdır (`ref_metni`): metin o
    zamandan beri değiştiyse karar artık o metni korumaz ve çelişki sayılmaz.
    """
    hedefler: dict[str, list[ConsistencyFinding]] = {}
    by_ref = {split_ac(a)[0]: a for a in req.kabul_kriterleri}
    for f in fixes:
        try:
            yeni = parse_fix_text(f.onerilen_metin or "")
        except DocMergeError:
            continue
        for hedef, metin in yeni.items():
            mevcut = req.aciklama if hedef == DESC else by_ref.get(hedef)
            if mevcut is not None and " ".join(mevcut.split()) == " ".join(metin.split()):
                continue  # madde değişmiyor
            hedefler.setdefault(hedef, []).append(f)
    if not hedefler:
        return []
    bas = cycle_start(s, req.id)
    adaylar: list[tuple[ConsistencyFinding, ConsistencyFinding]] = []
    for f in findings_of(s, req.id, ("resolved", "stale")):
        if not f.kanit_dogrulandi or (bas is not None and f.olusturma < bas):
            continue
        karar_veren = f
        if f.durum == "stale":
            ek = s.get(ConsistencyFindingEk, f.id)
            if ek is None or ek.onceki_finding_id is None:
                continue
            karar_veren = s.get(ConsistencyFinding, ek.onceki_finding_id) or f
        if karar_veren.analist_karari == "accept_difference":
            adaylar.append((f, karar_veren))
    out: list[str] = []
    for f, karar in adaylar:
        ek = s.get(ConsistencyFindingEk, f.id)
        guncel = current_doc_text(f.doc_ref, req.aciklama, req.kabul_kriterleri)
        if ek is not None and ek.ref_metni is not None and ek.ref_metni != guncel:
            continue
        refs = set(ac_refs(f.doc_ref))
        if not refs and refers_to_description(f.doc_ref):
            refs = {DESC}
        for hedef in sorted(refs & hedefler.keys(), key=str):
            duzeltenler = ", ".join(_bulgu_etiketi(s, x) for x in hedefler[hedef])
            out.append(
                f"{hedef_ad(hedef)}: {_bulgu_etiketi(s, f)} 'bilinçli fark' kararıyla olduğu gibi "
                f"bırakıldı (gerekçe: {karar.gerekce or '-'}), ama {duzeltenler} düzeltmesi bu "
                "maddeyi yeniden yazıyor"
            )
    return out


def _bulgu_etiketi(s: Session, f: ConsistencyFinding) -> str:
    ek = s.get(ConsistencyFindingEk, f.id)
    no = ek.bulgu_no if ek is not None and ek.bulgu_no else str(f.id)[:8]
    return f"{no} (tur {f.kontrol_turu})"


@dataclass(frozen=True)
class Finalized:
    """apply-doc-fixes düzeltme yokken belgeyi doğrudan son hale aldı."""

    mesaj: str
    kabul_edilen: list[str] = field(default_factory=list)


IMPLICIT_ACCEPT_GEREKCE = (
    "Analist belgeyi bu uyarıya ayrı karar vermeden son hale aldı (son hal onayı); bilinçli fark "
    "olarak kabul edildi"
)


def start_apply(
    s: Session, req: Requirement, user: Principal, *, cakismayi_onayla: bool = False
) -> Started | Finalized:
    """POST /requirements/{id}/apply-doc-fixes. Düzeltme yoksa ve engelleyici kalmadıysa belgeyi
    doğrudan son hale alır (`Finalized`). Karar bekleyen engelleyici bulgu varsa reddedilir (409);
    karar bekleyen uyarılar analistin bu açık eylemiyle "bilinçli fark" (accept_difference) olarak
    kayda geçer ve yanıt/PO yorumunda listelenir.

    Bir düzeltme, aynı döngüde 'bilinçli fark' kararıyla olduğu gibi bırakılan maddeyi yeniden
    yazıyorsa 409 döner; analist ya düzeltme kararını değiştirir ya da `cakismayi_onayla=true` ile
    bilinçli olarak uygular (kayda geçer).
    """
    if req.durum != "findings_open":
        raise FlowError(f"Bu durumda ({req.durum}) düzeltme uygulanamaz")
    try:
        fixes, _ = planned_merge(s, req)
    except DocMergeConflict as exc:
        raise FlowError(str(exc)) from exc
    except DocMergeError as exc:
        raise FlowInputError(str(exc)) from exc
    cakismalar = accept_difference_conflicts(s, req, fixes)
    if cakismalar and not cakismayi_onayla:
        raise FlowError(
            "Düzeltme, bilinçli fark kararıyla çelişiyor — "
            + "; ".join(cakismalar)
            + ". Düzeltme kararını değiştirin ya da çelişkiyi onaylayarak yeniden uygulayın "
            "(cakismayi_onayla=true)."
        )
    if cakismalar:
        audit_on_commit(
            s,
            user.kullanici_adi,
            "requirement.decision_conflict_confirmed",
            f"requirement:{req.id}",
            {"cakismalar": cakismalar, "bulgu_ids": [f.id for f in fixes]},
        )
    if not fixes:
        engelleyiciler = blocking_unresolved(s, req.id)
        if engelleyiciler:
            raise FlowError(
                "Uygulanacak onaylı doküman düzeltmesi yok; engelleyici bulgular karar bekliyor: "
                + ", ".join(_bulgu_etiketi(s, f) for f in engelleyiciler)
            )
        kabul_edilen: list[str] = []
        for f in undecided_findings(s, req.id):
            s.refresh(f, with_for_update=True)
            if f.durum != "open":
                continue
            record_approval(
                s,
                f,
                user,
                "accept_difference",
                gerekce=IMPLICIT_ACCEPT_GEREKCE,
                beklenen_hash=content_hash_of(f),
            )
            transition(s, f, "decided", user, "open", sebep="son hal onayı")
            transition(s, f, "resolved", user, "decided", sebep="accept_difference (son hal onayı)")
            kabul_edilen.append(_bulgu_etiketi(s, f))
        neden = untrusted_check(s, req.id)
        sebep = "analist belgeyi son hale aldı"
        if neden:
            sebep += f" (denetim uyarısına rağmen: {neden})"
        if kabul_edilen:
            sebep += f"; karar verilmemiş uyarılar bilinçli fark sayıldı: {', '.join(kabul_edilen)}"
        finalize(s, req, user, sebep=sebep)
        mesaj = "Uygulanacak düzeltme yok; belge son haline alındı, PO teyidi bekleniyor."
        if kabul_edilen:
            mesaj += (
                " Karar verilmemiş uyarı bulguları bilinçli fark olarak kaydedildi: "
                + ", ".join(kabul_edilen)
                + "."
            )
        return Finalized(mesaj, kabul_edilen)
    transition(s, req, "in_review", user, "findings_open", sebep="doküman düzeltmesi")
    wf, job = start_workflow(
        s.connection(),
        "requirement_doc_fix",
        user.kullanici_adi,
        yuk={"requirement_id": str(req.id), "bulgu_ids": [str(f.id) for f in fixes]},
        job_tur=JOB_APPLY,
        nesne_turu="requirement",
        nesne_id=req.id,
    )
    emit_requirement(s, req, olay="doc_fix_started")
    return Started(wf, job, f"{len(fixes)} onaylı düzeltme yazılıyor; ardından yeniden kontrol.")


def run_apply(engine: Engine, job_id: uuid.UUID, yuk: dict[str, Any]) -> dict[str, Any]:
    req_id = uuid.UUID(str(yuk["requirement_id"]))
    wf_id = _wf_id(yuk)
    with session_scope() as s:
        req = s.get(Requirement, req_id)
        if req is None or req.durum != "in_review":
            return {"atlandi": "gereksinim düzeltme beklemiyor"}
        try:
            fixes, merge = planned_merge(s, req)
        except DocMergeError as exc:
            raise FlowError(str(exc)) from exc
        if not fixes:
            raise FlowError("Uygulanacak onaylı düzeltme kalmadı")
        onceki = content_hash_of(req)
        yeni = requirement_hash(req.baslik, merge.aciklama, merge.kabul_kriterleri)
        key, baslik = req.jira_key, req.baslik
        fix_ids = [f.id for f in fixes]

    if key:
        write_fix_to_jira(
            engine, req_id, key, baslik, onceki, yeni, merge, is_kimligi=wf_id or job_id
        )

    with session_scope() as s:
        req = lock_requirement(s, req_id)
        if req.durum != "in_review" or content_hash_of(req) != onceki:
            raise FlowError("Gereksinim düzeltme sırasında değişti")
        req.aciklama = merge.aciklama
        req.kabul_kriterleri = list(merge.kabul_kriterleri)
        req.kaynak_hash = yeni
        req.ac_missing = not merge.kabul_kriterleri
        s.flush()
        for fid in fix_ids:
            f = s.get(ConsistencyFinding, fid, with_for_update=True)
            if f is not None and f.durum == "decided":
                transition(s, f, "resolved", SYSTEM, "decided", sebep="düzeltme belgeye yazıldı")
        audit_on_commit(
            s,
            "system",
            "requirement.doc_fixed",
            f"requirement:{req.id}",
            {
                "onceki_hash": onceki,
                "hash": yeni,
                "degisiklikler": merge.degisiklikler,
                "jira_key": key,
            },
        )
        if _sonraki_tur_var(req):
            stale_findings(s, req.id, SYSTEM, "belge düzeltildi; yeniden kontrol")
            req.kontrol_turu += 1
            enqueue(
                s.connection(),
                JOB_CONSISTENCY,
                {"requirement_id": str(req.id), "tur": req.kontrol_turu, **_wf_yuk(wf_id)},
                idempotency_key=f"{JOB_CONSISTENCY}:{wf_id or job_id}:{req.kontrol_turu}",
                workflow_id=wf_id,
            )
            emit_requirement(s, req, olay="doc_fixed", yeniden_kontrol=True)
            return {"hash": yeni, "yeniden_kontrol_turu": req.kontrol_turu}
        # Tur sınırı: AI denetimi yeniden koşmaz; kalan engelleyiciler insan kararıyla kapanır.
        sonuc = conclude_round(s, req, SYSTEM)
        finish_workflow(s, wf_id)
        emit_requirement(s, req, olay="doc_fixed", yeniden_kontrol=False)
        return {"hash": yeni, "yeniden_kontrol_turu": None, "durum": sonuc}


def write_fix_to_jira(
    engine: Engine,
    req_id: uuid.UUID,
    key: str,
    baslik: str,
    onceki: str,
    yeni: str,
    merge: MergeResult,
    *,
    is_kimligi: uuid.UUID | str,
) -> None:
    """Onaylı düzeltmeleri Jira'ya yazar (açıklama + özet yorumu + PO etiketleri).

    Idempotency anahtarı düzeltme iş akışına (`is_kimligi`: workflow ya da iş kimliği) bağlıdır:
    aynı işin yeniden denemesi Jira'ya ikinci kez yazmaz, ama story geri alınıp (A→B→A) aynı
    düzeltme yeni bir akışla yeniden uygulanırsa yazım yeniden yapılır. Ayrıca `created` kaydı
    varken açıklamanın Jira'da hâlâ hedef içerikte olduğu ölçülür (`still_present`).
    """
    jira = services.jira()

    def jira_hash() -> str:
        it = jira.get_issue(key)
        return requirement_hash(it.summary, it.description, list(it.acceptance_criteria))

    guncel = jira_hash()
    if guncel not in (onceki, yeni):
        raise FlowError(
            f"{key} Jira'da düzeltme kararlarından sonra değişmiş; story'yi yeniden çekip "
            "incelemeyi tekrar başlatın"
        )
    if guncel != yeni and baslik is not None:
        jira_once(
            engine,
            entity_turu="requirement",
            entity_id=req_id,
            idempotency_key=f"jira:update_description:{req_id}:{is_kimligi}:{onceki}->{yeni}",
            action=lambda: (
                jira.update_description(key, merge.aciklama, merge.kabul_kriterleri) or key
            ),
            find_existing=lambda: key if jira_hash() == yeni else None,
            still_present=lambda: jira_hash() == yeni,
        )
        if jira_hash() != yeni:
            raise FlowError(f"{key} Jira'ya yazılan içerik beklenen hash'le eşleşmiyor")
    anahtar = f"jira:comment:doc_fix:{req_id}:{is_kimligi}:{yeni}"
    marker = _marker(anahtar)
    with engine.connect() as conn:
        tip = chain_tip(conn)
    govde = change_summary(merge.degisiklikler, jira_key=key, audit_tip=tip) + f"\nKayıt: {marker}"
    jira_once(
        engine,
        entity_turu="requirement",
        entity_id=req_id,
        idempotency_key=anahtar,
        action=lambda: jira_notify.post_comment(jira, key, govde, jira_notify.DOKUMAN_DUZELTME),
        find_existing=lambda: _comment_with_marker(jira, key, marker),
    )
    # Bayat PO onayını geri çek, yeniden teyit iste (MIMARI-SOZLESME §6, 2. inceleme turu).
    jira.remove_labels(key, [PO_APPROVED_LABEL])
    jira.add_labels(key, [PO_PENDING_LABEL])


# ------------------------------------------------------------------------ PO teyidi


def po_label_current(req: Requirement) -> bool:
    """Jira yolunda PO onay etiketi ŞU AN geçerli mi (eşzamanlı, salt okuma Jira çağrısı)?

    Case üretimi/IDE taslağı başlatılırken çağrılmak içindir (poll aralığındaki yarışı kapatır:
    etiket kaldırıldıktan sonraki ≤15 sn'de generate-cases). Serbest metin yolunda onay portaldadır
    → True. Jira'ya erişilemezse istisna yükselir (çağıran fail-closed davranmalı).
    """
    if req.kaynak != "jira" or req.jira_key is None:
        return True
    jira = services.jira()
    if PO_APPROVED_LABEL not in jira.get_issue(req.jira_key).labels:
        return False
    return bool(jira.po_approvals(req.jira_key, sorted(services.po_accounts())))


def withdraw_po(req_id: uuid.UUID, key: str, durum: str) -> str:
    """Jira'da PO onay etiketi kalktı: kapı kapanır (§2 adım 3 "Etiket yoksa case üretimine
    geçilmez"). Gereksinim `new`'e döner (üretim sürüyorsa önce `failed`), onaylanan hash silinir;
    yayın kapısı (gereksinim cases_ready/done + güncel PO onayı ister) bu case'leri artık
    yayınlamaz. Yayınlanmış case'ler Jira'da kalır (geri alınamaz; kayıtta listelenir)."""
    with session_scope() as s:
        req = lock_requirement(s, req_id)
        if req.durum != durum:
            return "durum_degisti"
        onceki_onaylayan = req.po_onaylayan
        sebep = "PO onay etiketi kaldırıldı"
        if durum == "generating":
            transition(s, req, "failed", SYSTEM, "generating", sebep=sebep)
            durum = "failed"
        transition(s, req, "new", SYSTEM, durum, sebep=sebep)
        _po_temizle(req)
        req.kontrol_turu = 0
        supersede_reviews(s, req.id, SYSTEM)
        stale_findings(s, req.id, SYSTEM, sebep)
        # Case'lere dokunulmaz: yayın kapısı gereksinimin güncel PO onayını ister
        # (`publish.requirement_change_reason`; `new` → engelli) ve yeni üretim eski case'leri
        # geçersizler (`cases.invalidated`). Yayınlanmış olanlar Jira'da kalır; kayıtta listelenir.
        cases = list(
            s.execute(
                select(TestCase.id, TestCase.durum).where(
                    TestCase.requirement_id == req.id, TestCase.durum != "superseded"
                )
            )
        )
        audit_on_commit(
            s,
            "system",
            "requirement.po_withdrawn",
            f"requirement:{req.id}",
            {
                "jira_key": key,
                "onceki_onaylayan": onceki_onaylayan,
                "onceki_durum": durum,
                "yeni_durum": "new",
                "yayinlanmamis_case_ids": [i for i, d in cases if d != "published"],
                "yayinlanmis_case_ids": [i for i, d in cases if d == "published"],
            },
        )
        emit_requirement(s, req, olay="po_withdrawn")
    return "geri_cekildi:new"


def _po_temizle(req: Requirement) -> None:
    req.po_onaylayan = None
    req.po_onay_zamani = None
    req.po_onay_kaynagi = None


def _po_kaydet(s: Session, req: Requirement, onaylayan: str, zaman: datetime, kaynak: str) -> None:
    req.po_onaylayan, req.po_onay_zamani, req.po_onay_kaynagi = onaylayan, zaman, kaynak
    for rr in active_reviews(s, req.id):
        rr.po_onay_kullanicisi, rr.po_onay_zamani = onaylayan, zaman
        if rr.durum == "pending_po":
            transition(s, rr, "approved", SYSTEM, "pending_po", sebep="PO teyidi")


def po_approve_portal(
    s: Session, req: Requirement, user: Principal, icerik_hash: str | None
) -> None:
    """Serbest metin yolunda PO teyidi (portal, po rolü)."""
    if req.kaynak == "jira":
        raise FlowError("Jira yolunda PO teyidi Jira'daki tp-po-approved etiketiyle verilir")
    if req.durum != "pending_po":
        raise FlowError(f"Gereksinim PO teyidi beklemiyor (durum: {req.durum})")
    kayit = akis(s, req)
    if kayit.son_hal_hash is not None and kayit.son_hal_hash != content_hash_of(req):
        raise FlowError("Belge son halinden sonra değişmiş; yeniden kontrol gerekiyor")
    record_approval(s, req, user, "po_approve", beklenen_hash=icerik_hash)
    transition(s, req, "po_approved", user, "pending_po", sebep="PO teyidi (portal)")
    _po_kaydet(s, req, user.kullanici_adi, now(), "portal")
    emit(
        s,
        EV_PO,
        {
            "id": req.id,
            "requirement_id": req.id,
            "onaylayan": user.kullanici_adi,
            "kanal": "portal",
        },
    )
    emit_requirement(s, req, olay="po_approved")


def ensure_po_poll(conn: Connection, *, gecikme_s: float = 0.0) -> uuid.UUID | None:
    """PO etiket sorgusu işini (yoksa) kuyruğa ekler. Tek bekleyen iş kuralı advisory lock ile."""
    idempotency_lock(conn, JOB_PO_POLL)
    bekleyen = conn.execute(
        text("SELECT id FROM job WHERE tur = :t AND durum IN ('queued', 'retry') LIMIT 1"),
        {"t": JOB_PO_POLL},
    ).scalar_one_or_none()
    if bekleyen is not None:
        return None
    zaman = now() + timedelta(seconds=gecikme_s) if gecikme_s > 0 else None
    return enqueue(conn, JOB_PO_POLL, {}, run_after=zaman)


def run_po_poll(engine: Engine) -> dict[str, Any]:
    kurtarilan = sweep_stuck(engine)
    with session_scope() as s:
        ids = list(
            s.scalars(
                select(Requirement.id)
                .where(Requirement.kaynak == "jira", Requirement.durum.in_(PO_IZLENEN))
                .order_by(Requirement.jira_key)
            )
        )
    sonuc: dict[str, str] = {}
    if ids:
        jira = services.jira()
        hesaplar = services.po_accounts()
        for rid in ids:
            try:
                sonuc[str(rid)] = po_check(engine, jira, rid, hesaplar)
            except Exception as exc:
                log.warning("PO kontrolü başarısız (%s): %s", rid, exc)
                sonuc[str(rid)] = f"hata: {type(exc).__name__}: {str(exc)[:200]}"
    silinen = purge_po_poll_jobs(engine)
    return {
        "kontrol": sonuc,
        "kurtarilan": kurtarilan,
        "silinen_eski_is": silinen,
        "yeniden_planlandi": reschedule_po_poll(engine),
    }


def reschedule_po_poll(engine: Engine) -> bool:
    """Jira'da PO onayı izlenen ya da işi süren (takılabilecek) gereksinim varsa sonraki sorguyu
    planlar."""
    with session_scope() as s:
        kalan = s.scalar(
            select(func.count())
            .select_from(Requirement)
            .where(
                ((Requirement.kaynak == "jira") & Requirement.durum.in_(PO_IZLENEN))
                | Requirement.durum.in_(IS_BEKLEYEN)
            )
        )
        if kalan:
            ensure_po_poll(s.connection(), gecikme_s=settings().po_poll_s)
    return bool(kalan)


def purge_po_poll_jobs(engine: Engine, saklama: timedelta = PO_POLL_SAKLAMA) -> int:
    """Bitmiş PO sorgu işlerini siler (15 sn'de bir satır; günde ~5.800 satır birikmesin)."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "DELETE FROM job WHERE tur = :t AND durum IN ('done', 'failed', 'cancelled') "
                "AND COALESCE(bitis, guncelleme) < now() - make_interval(secs => :sn)"
            ),
            {"t": JOB_PO_POLL, "sn": saklama.total_seconds()},
        ).rowcount


# ------------------------------------------------------------------ takılı iş kurtarma

_ETKIN_IS_YOK = """
NOT EXISTS (
    SELECT 1 FROM job j JOIN workflow_instance w ON w.id = j.workflow_id
    WHERE w.nesne_turu = 'requirement' AND w.nesne_id = requirement.id
      AND j.durum IN ('queued', 'retry', 'running')
)
"""


def stuck(s: Session, req_id: uuid.UUID) -> bool:
    """Gereksinim iş bekleyen bir durumda ama ona bağlı etkin (kuyrukta/çalışan) iş yok mu?

    İş worker dışında bittiyse (sahipsiz iş, zaman aşımı, nabız kaybı) işleyicinin hata yolu hiç
    koşmaz; gereksinim aksi halde `in_review`/`generating`'de sonsuza dek kalır.
    """
    return bool(
        s.execute(
            text(
                "SELECT 1 FROM requirement WHERE id = :id AND durum = ANY(:d) AND " + _ETKIN_IS_YOK
            ),
            {"id": req_id, "d": list(IS_BEKLEYEN)},
        ).first()
    )


def _son_is_hatasi(s: Session, req_id: uuid.UUID) -> str | None:
    return s.execute(
        text(
            "SELECT j.son_hata FROM job j JOIN workflow_instance w ON w.id = j.workflow_id "
            "WHERE w.nesne_turu = 'requirement' AND w.nesne_id = :id AND j.durum = 'failed' "
            "ORDER BY COALESCE(j.bitis, j.guncelleme) DESC LIMIT 1"
        ),
        {"id": req_id},
    ).scalar_one_or_none()


def recover_stuck(s: Session, req: Requirement, baglam: str) -> bool:
    """Takılı gereksinimi `failed`'a alır (kilitli; koşul kilit altında yeniden denetlenir)."""
    req = lock_requirement(s, req.id)
    if req.durum not in IS_BEKLEYEN or not stuck(s, req.id):
        return False
    onceki = req.durum
    hata = _son_is_hatasi(s, req.id) or "bağlı iş bulunamadı"
    neden = f"İş yarıda kaldı ({hata}); yeniden başlatılabilir"
    transition(s, req, "failed", SYSTEM, onceki, sebep=neden[:500])
    audit_on_commit(
        s,
        "system",
        "requirement.recovered",
        f"requirement:{req.id}",
        {"onceki_durum": onceki, "is_hatasi": hata[:500], "baglam": baglam},
    )
    emit_requirement(s, req, olay="failed", neden=neden[:300])
    log.warning("takılı gereksinim kurtarıldı: %s %s → failed (%s)", req.id, onceki, hata)
    return True


def sweep_stuck(engine: Engine) -> list[str]:
    """`in_review`/`generating`'de bağlı etkin işi olmayan gereksinimleri `failed`'a alır."""
    with engine.connect() as conn:
        adaylar = list(
            conn.execute(
                text(
                    "SELECT id FROM requirement WHERE durum = ANY(:d) AND "
                    + _ETKIN_IS_YOK
                    + " ORDER BY id"
                ),
                {"d": list(IS_BEKLEYEN)},
            ).scalars()
        )
    out: list[str] = []
    for rid in adaylar:
        with session_scope() as s:
            req = s.get(Requirement, rid)
            if req is not None and recover_stuck(s, req, "periyodik süpürme"):
                out.append(str(rid))
    return out


def _po_cevaplari(jira: Any, key: str, hesaplar: frozenset[str], sonra: datetime | None) -> list:
    out = []
    for c in jira.get_comments(key):
        # Yetki kimlikleri (e-posta/accountId); görünen ad değil. Kimlik listesi olmayan
        # (eski/sahte) kayıtta yazar alanı kullanılır.
        kimlikler = {services.normalize_identity(i) for i in (c.author_ids or [c.author or ""])}
        if not kimlikler & hesaplar:
            continue
        if sonra is not None and c.created is not None and c.created < sonra:
            continue
        out.append(
            {
                "id": c.id,
                "yazar": c.author,
                "metin": c.body[:4000],
                "zaman": c.created.isoformat() if c.created else None,
            }
        )
    return out


def po_check(engine: Engine, jira: Any, req_id: uuid.UUID, hesaplar: frozenset[str]) -> str:
    """Tek gereksinim için Jira PO etiketi kontrolü (15 sn'lik sorgunun gövdesi)."""
    with session_scope() as s:
        req = s.get(Requirement, req_id)
        if req is None or req.jira_key is None:
            return "yok"
        durum, key, h = req.durum, req.jira_key, content_hash_of(req)
        kayit = s.get(RequirementAkis, req_id)
        son_hal = kayit.son_hal_hash if kayit is not None else None
        son_hal_zamani = kayit.son_hal_zamani if kayit is not None else None
        rr = active_reviews(s, req_id)
        soru_zamani = rr[-1].olusturma if rr else None
        sahip = rr[-1].id if rr else req_id

    issue = jira.get_issue(key)
    jira_h = requirement_hash(issue.summary, issue.description, list(issue.acceptance_criteria))
    if jira_h != h:
        with session_scope() as s:
            req = lock_requirement(s, req_id)
            if req.durum != durum or content_hash_of(req) != h:
                return "durum_degisti"
            sonuc = apply_content_change(
                s,
                req,
                issue.summary,
                issue.description,
                list(issue.acceptance_criteria),
                SYSTEM,
                sebep="Jira'da içerik değişti (PO teyidi sırasında)",
            )
        return f"icerik_degisti:{sonuc}"

    etiket_var = PO_APPROVED_LABEL in issue.labels
    onaylar = jira.po_approvals(key, sorted(hesaplar)) if etiket_var else []

    if durum in ("po_approved", "generating", "cases_ready", "done"):
        if onaylar:
            return "onayli"
        return withdraw_po(req_id, key, durum)

    if durum != "pending_po":
        return "bekliyor"
    son_hal_guncel = son_hal is not None and son_hal == h
    if son_hal_guncel:
        # Son hal işi kalıcı hata verdiyse (Jira erişilemedi) PO'ya sorular hiç gitmezdi.
        try:
            ensure_po_request(engine, req_id)
        except Exception as exc:
            log.warning("%s: PO soru yorumu işi yeniden kuyruğa alınamadı: %s", key, exc)
    # Yalnızca belge son hal olduktan ve PO soru yorumu yazıldıktan SONRA konmuş etiket onaydır (PO
    # son hali ve soruları görmüş olmalı); daha önce konmuş etiket kapıyı açmaz (Constitution I).
    esik: datetime | None = son_hal_zamani
    if onaylar and son_hal_guncel and son_hal is not None:
        esik = approval_threshold(jira, key, po_request_key(sahip, son_hal), son_hal_zamani)
    taze = [o for o in onaylar if o.at is not None and esik is not None and o.at >= esik]
    if not taze:
        if etiket_var:
            try:
                sonuc = remove_stale_approval(engine, jira, req_id, key, esik, hesaplar, son_hal)
            except Exception as exc:  # onay zaten sayılmadı; etiket temizliği kozmetik
                log.warning("%s: bayat %s kaldırılamadı: %s", key, PO_APPROVED_LABEL, exc)
                sonuc = "bayat_kaldirildi"
            with session_scope() as s:
                audit_on_commit(
                    s,
                    "system",
                    "requirement.po_label_stale",
                    f"requirement:{req_id}",
                    {
                        "jira_key": key,
                        "son_hal_zamani": son_hal_zamani,
                        "esik": esik,
                        "onaylar": [
                            {"yazar": o.author, "zaman": o.at.isoformat() if o.at else None}
                            for o in onaylar
                        ],
                    },
                )
            if sonuc == "yarista_kaldirildi":
                return "taze_etiket_yarista_kaldirildi"
            return "bayat_etiket_kaldirildi"
        return "bekliyor"
    onay = taze[-1]
    if son_hal is None or son_hal != h:
        # Son hal kaydı yok ya da güncel içerik son hal değil: onay yerine yeniden denetim.
        with session_scope() as s:
            req = lock_requirement(s, req_id)
            if req.durum != "pending_po":
                return "durum_degisti"
            stale_findings(s, req.id, SYSTEM, "son hal tutarsız")
            transition(s, req, "in_review", SYSTEM, "pending_po", sebep="son hal hash'i tutmuyor")
            req.kontrol_turu += 1
            start_workflow(
                s.connection(),
                "requirement_recheck",
                "system",
                yuk={"requirement_id": str(req.id), "tur": req.kontrol_turu},
                job_tur=JOB_CONSISTENCY,
                nesne_turu="requirement",
                nesne_id=req.id,
            )
        return "yeniden_kontrol"

    cevaplar = _po_cevaplari(jira, key, hesaplar, soru_zamani)
    with session_scope() as s:
        req = lock_requirement(s, req_id)
        if req.durum != "pending_po" or content_hash_of(req) != h:
            return "durum_degisti"
        record_approval(
            s,
            req,
            None,
            "po_approve",
            kanal="jira",
            harici_onaylayan=onay.author,
            onay_zamani=onay.at,
            beklenen_hash=son_hal,
        )
        transition(s, req, "po_approved", f"jira:{onay.author}", "pending_po", sebep="PO etiketi")
        _po_kaydet(s, req, onay.author, onay.at or now(), "jira_label")
        req.po_cevaplari = cevaplar
        emit(
            s,
            EV_PO,
            {"id": req.id, "requirement_id": req.id, "onaylayan": onay.author, "kanal": "jira"},
        )
        emit_requirement(s, req, olay="po_approved")
    try:
        jira.remove_labels(key, [PO_PENDING_LABEL])
    except Exception as exc:  # panodaki etiket kozmetik; onay kaydı esastır
        log.warning("%s: %s etiketi kaldırılamadı: %s", key, PO_PENDING_LABEL, exc)
    return "onaylandi"


# --------------------------------------------------------------------- iş hatası


def mark_failed(req_id: uuid.UUID, neden: str) -> None:
    """İş kalıcı olarak başarısız: gereksinim `in_review → failed` (insana düşer)."""
    with session_scope() as s:
        req = s.get(Requirement, req_id, with_for_update=True)
        if req is None or req.durum != "in_review":
            return
        transition(s, req, "failed", SYSTEM, "in_review", sebep=neden[:500])
        emit_requirement(s, req, olay="failed", neden=neden[:300])


_HATA_ONERILERI: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (
        ("REPLAY çıktısı yok", "REPLAY bu girdiyle eşleşmiyor", "ReplayNotFound", "ReplayMiss"),
        "Bu girdi için kayıtlı REPLAY yok; canlı model (ANTHROPIC_API_KEY) gerekir — yeniden "
        "denemek sonucu değiştirmez.",
        False,
    ),
    (
        ("bütçe", "Bütçe", "BudgetExceeded"),
        "Model bütçesi aşıldı; bütçe yenilendiğinde ya da artırıldığında yeniden deneyin.",
        True,
    ),
    (
        ("yarıda kal", "yeniden başladı", "zaman aşımı", "Zaman aşımı", "bağlı iş bulunamadı"),
        "İş yarıda kaldı; 'Yeniden denetle' ile yeniden başlatılabilir.",
        True,
    ),
    (
        ("Jira'da", "değişti", "değişmiş"),
        "Story inceleme sırasında değişti; story'yi yeniden çekip incelemeyi tekrar başlatın.",
        True,
    ),
)


def last_failure(s: Session, req: Requirement) -> dict[str, Any] | None:
    """`failed` gereksinimin son hata nedeni (portal "Hata" çipinin açıklaması).

    Neden durum geçişinin denetim kaydındaki `sebep`'tir (`mark_failed`, takılı iş kurtarma, PO
    onayının üretim sırasında geri çekilmesi); işin türü ve iş kaydındaki hata, gereksinime bağlı en
    son başarısız işten gelir. Türkçe öneri, yeniden denemenin işe yarayıp yaramayacağını söyler.
    """
    if req.durum != "failed":
        return None
    gecis = s.execute(
        text(
            "SELECT zaman, ozet->>'sebep' FROM audit_event WHERE eylem = 'requirement.transition' "
            "AND nesne = :n AND ozet->>'to' = 'failed' ORDER BY id DESC LIMIT 1"
        ),
        {"n": f"requirement:{req.id}"},
    ).first()
    is_ = s.execute(
        text(
            "SELECT j.tur, j.son_hata, COALESCE(j.bitis, j.guncelleme) FROM job j "
            "JOIN workflow_instance w ON w.id = j.workflow_id "
            "WHERE w.nesne_turu = 'requirement' AND w.nesne_id = :id AND j.durum = 'failed' "
            "ORDER BY COALESCE(j.bitis, j.guncelleme) DESC LIMIT 1"
        ),
        {"id": req.id},
    ).first()
    neden = (gecis[1] if gecis is not None else None) or (is_[1] if is_ is not None else None)
    neden = neden or "Hata nedeni kaydedilmemiş"
    oneri, yeniden = "Ayrıntı iş kaydında; yeniden denemek işe yarayabilir.", True
    for anahtarlar, metin, tekrar in _HATA_ONERILERI:
        if any(a in neden for a in anahtarlar):
            oneri, yeniden = metin, tekrar
            break
    zaman = gecis[0] if gecis is not None else (is_[2] if is_ is not None else None)
    return {
        "neden": neden[:1000],
        "zaman": zaman.isoformat() if zaman is not None else None,
        "job_tur": is_[0] if is_ is not None else None,
        "is_hatasi": (is_[1] or None)[:1000] if is_ is not None and is_[1] else None,
        "oneri": oneri,
        "yeniden_denemek_ise_yarar": yeniden,
    }


def counts_for(s: Session, req_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Liste ekranı sayaçları: açık bulgu, case toplam/onaylı."""
    out: dict[uuid.UUID, dict[str, int]] = {
        r: {"bulgu_acik": 0, "case_toplam": 0, "case_onayli": 0} for r in req_ids
    }
    if not req_ids:
        return out
    for rid, n in s.execute(
        select(ConsistencyFinding.requirement_id, func.count())
        .where(
            ConsistencyFinding.requirement_id.in_(req_ids),
            ConsistencyFinding.kanit_dogrulandi.is_(True),
            ConsistencyFinding.durum.in_(ACIK_BULGU),
        )
        .group_by(ConsistencyFinding.requirement_id)
    ):
        out[rid]["bulgu_acik"] = n
    for rid, durum, n in s.execute(
        select(TestCase.requirement_id, TestCase.durum, func.count())
        .where(TestCase.requirement_id.in_(req_ids), TestCase.durum != "superseded")
        .group_by(TestCase.requirement_id, TestCase.durum)
    ):
        out[rid]["case_toplam"] += n
        if durum in ("approved", "published"):
            out[rid]["case_onayli"] += n
    return out
