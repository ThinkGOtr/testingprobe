"""Bug taslağı ve `publish_bug` (TEKNIK-TASARIM §2 adım 12–14, §8.12; MIMARI-SOZLESME §5).

Akış:

1. **Taslak açılışı.** Triage gerçek defect'i `create_draft_from_failure(session, failure_id)` ile
   (çağıranın işleminde) taslağa çevirir; tutarlılık bulgusunun `code_defect` taslakları (Faz 2,
   `requirements.ensure_bug_draft`) `adopt_draft` ile aynı hatta alınır (bulgu bağı korunur).
   Taslak hemen deterministik şablon içerikle görünür ve `bugs.prepare` işi kuyruğa girer.
   Aynı hata imzasıyla açık (draft/approved) taslak varsa yenisi açılmaz; başarısızlık o taslağa
   eklenir (`bug_draft_ek.ilgili_failure_ids`).
2. **`bugs.prepare` (core-worker).** (a) Hata imzasından güvenli JQL ile Jira'da açık Bug araması
   (`jql.duplicate_search_jql`), deterministik terim örtüşmesiyle en çok 5 aday; (b) model geçidi
   `dup_rank` adayları kısa gerekçeyle sıralar (adaylar `<untrusted>` blokta; modelin uydurduğu
   anahtar atılır, `link` önerisi yalnızca `high` aday için); (c) model geçidi `bug_draft` şemalı
   taslak üretir; deterministik düzeltmeler uygulanır (`content.apply_guards`: gerçekleşen literal
   değer, kanıt yalnızca koşudan, story/Test anahtarları). REPLAY-MISS / model hatasında taslak
   şablonda kalır (dürüst: `uretim = sablon`). İş sürerken testçi karar verdiyse ya da içeriği
   düzenlediyse içerik ezilmez (yalnızca adaylar güncellenir).
3. **Karar (testçi, `POST /bug-drafts/{id}/decision`).** `edit` (şemayla doğrulanır, yeni hash;
   onay değildir), `new` / `link {link_key}` (onay: `record_approval` kullanıcı + görülen hash +
   düzenleme; `draft → approved`; `bugs.publish` işi kuyruğa girer), `dismiss` (gerekçe zorunlu),
   `reopen` (reddedilmiş ya da yayını başarısız kalmış onaylı taslağı taslağa döndürür).
4. **`publish_bug(draft_id)` (core-worker, `bugs.publish`).** Yalnızca `approved` ve
   `approved_hash_matches` (son insan kararı onaylayan, `review.onaylanan_hash == icerik_hash ==
   bug_draft.onaylanan_hash`) taslak. `external_ref` önce `intent` (commit), sonra Jira:
   - `new`: `tp-<uuid>` etiketiyle mevcut kayıt aranır (yeniden denemede ikinci Bug açılmaz;
     içerik hash'i farklıysa durur), yoksa Bug açılır (özet, ADF açıklama, etiketler
     `AI-generated` + `tp-<uuid>` + üretim modu, öncelik destekleniyorsa önem önerisinden);
     story'ye `Relates`, Test issue'ya `Test` ("is tested by"; yoksa `Relates`) bağlantısı.
   - `link`: mevcut Bug'a kanıtlı yorum (bir kez; `tp-<uuid>` işaretiyle) + aynı bağlantılar;
     yeni Bug açılmaz.
   Sonra `created` + `approved → published` (kapı hash'i yeniden denetler) + `bug.published` SSE.

Jira yazma kimliği yalnızca core-worker'dadır: core-api yalnızca kuyruğa koyar ve bekler.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit, chain_tip, content_hash
from tp_core.events.bus import publish_tx
from tp_core.features.bugs import content, jql, services
from tp_core.features.bugs.context import BugContext, failure_context, finding_context
from tp_core.features.testveri.atif import maskele_obje
from tp_core.integrations import jira_notify
from tp_core.integrations.jira_adf import with_bot_header
from tp_core.integrations.testmgmt import AI_LABEL, RELATES_LINK, TEST_LINK, tp_label
from tp_core.models import (
    AiCall,
    AppUser,
    BugDraft,
    ConsistencyFinding,
    ExternalRef,
    Failure,
    Run,
    TestCase,
    TestResult,
    session_scope,
)
from tp_core.models.bugs_feature import BugDraftEk
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.ports import JiraIssue
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue, idempotency_lock
from tp_core.workflow.service import (
    SYSTEM,
    ApprovalNotAllowed,
    GateClosed,
    InvalidDecision,
    Principal,
    WorkflowError,
    approved_hash_matches,
    record_approval,
    transition,
)

PREPARE_JOB = "bugs.prepare"
PUBLISH_JOB = "bugs.publish"
SWEEP_JOB = "bugs.adopt_sweep"
DUP_PURPOSE, DUP_BUNDLE = "dup_rank", "dup-rank"
DRAFT_PURPOSE, DRAFT_BUNDLE = "bug_draft", "bug-draft"
MAX_ADAY = 5
# Aday olmak için en az bu kadar arama terimi Bug metninde geçmeli (tek ortak sözcük ≠ mükerrer).
MIN_SKOR = 2
ARAMA_LIMITI = 20
INTENT_KILIT_S = 120
ACIK_DURUMLAR = ("draft", "approved")
MOD_ETIKETI_SABLON = "şablon (model çıktısı değil; deterministik taslak)"


class BugNotFound(WorkflowError):
    status_code = 404


class BugStateError(WorkflowError):
    status_code = 409


class JiraUnreachable(WorkflowError):
    """Bağlantı hedefi Jira'da doğrulanamadı (Jira'ya ulaşılamadı); karar kaydedilmez."""

    status_code = 503


class LinkTargetError(PermanentJobError):
    """`link` hedefi bağlanamaz (yok / Bug değil / kapalı / başka proje).

    Yayın bu hatayla durursa taslak `approved → draft` döner: testçi yeniden karar verebilir.
    """


# ----------------------------------------------------------------------- yardımcılar


def _ek(s: Session, draft: BugDraft, kaynak: str | None = None) -> BugDraftEk:
    ek = s.get(BugDraftEk, draft.id)
    if ek is None:
        ek = BugDraftEk(
            bug_draft_id=draft.id,
            kaynak=kaynak or ("finding" if draft.finding_id else "failure"),
        )
        s.add(ek)
        s.flush()
    return ek


def _requirement_id(s: Session, draft: BugDraft) -> uuid.UUID | None:
    if draft.finding_id is not None:
        return s.scalar(
            select(ConsistencyFinding.requirement_id).where(
                ConsistencyFinding.id == draft.finding_id
            )
        )
    if draft.failure_id is None:
        return None
    rid = s.scalar(
        select(TestCase.requirement_id)
        .join(TestResult, TestResult.test_case_id == TestCase.id)
        .join(Failure, Failure.test_result_id == TestResult.id)
        .where(Failure.id == draft.failure_id)
    )
    if rid is not None:
        return rid
    # Test sonucu case'e bağlı değilse (kod üretimi yerel kontrolü): koşunun script'i üzerinden.
    return s.scalar(
        select(ScriptCodegen.requirement_id)
        .join(Run, Run.script_id == ScriptCodegen.script_id)
        .join(Failure, Failure.run_id == Run.id)
        .where(Failure.id == draft.failure_id)
    )


def _event(s: Session, ad: str, draft: BugDraft, **ek: Any) -> None:
    publish_tx(
        s.connection(),
        ad,
        {
            "id": draft.id,
            "durum": draft.durum,
            "failure_id": draft.failure_id,
            "finding_id": draft.finding_id,
            "requirement_id": _requirement_id(s, draft),
            **ek,
        },
    )


def _oneri_durumu_yaz(s: Session, draft: BugDraft, durum: str) -> int:
    """Taslağın başarısızlık(lar)ının triage öneri durumu (`failure.oneri_durumu`).

    Triage `product_defect` için `oneri_turu='bug_draft', oneri_durumu='proposed'` yazar; testçi
    kararı/yayın bunu ilerletir: yayın (yeni kayıt ya da mevcut kayda bağla) → `merged`, ret →
    `rejected`, yeniden taslağa alma → `proposed`. Aynı imzayla bu taslağa eklenen başarısızlıklar
    (`ilgili_failure_ids`) da güncellenir. Jira anahtarı taslakta (`bug_draft.jira_key`) kalır.
    """
    ids: list[uuid.UUID] = []
    if draft.failure_id is not None:
        ids.append(draft.failure_id)
    ek = s.get(BugDraftEk, draft.id)
    for fid in (ek.ilgili_failure_ids if ek is not None else None) or []:
        try:
            ids.append(uuid.UUID(str(fid)))
        except ValueError:
            continue
    if not ids:
        return 0
    s.flush()
    sonuc = s.execute(
        text(
            "UPDATE failure SET oneri_durumu = :d, guncelleme = now() "
            "WHERE id = ANY(:ids) AND oneri_turu = 'bug_draft' AND oneri_durumu <> :d"
        ),
        {"d": durum, "ids": ids},
    )
    return int(getattr(sonuc, "rowcount", 0) or 0)


def _context(s: Session, draft: BugDraft, ek: BugDraftEk) -> BugContext:
    if draft.finding_id is not None:
        # İlk hazırlıkta Faz 2 şablonu korunur (model yoksa taslak ondan normalize edilir).
        eski = draft.icerik if ek.uretim is None else None
        return finding_context(s, draft.finding_id, eski)
    if draft.failure_id is None:
        raise PermanentJobError("taslağın başarısızlık ya da bulgu bağı yok")
    return failure_context(s, draft.failure_id)


def _enqueue_prepare(s: Session, draft: BugDraft, ek: BugDraftEk, aktor: str) -> uuid.UUID:
    ek.hazirlik_no += 1
    ek.hazirlik_durum = "kuyrukta"
    ek.hazirlik_hatasi = None
    s.flush()
    job_id = enqueue(
        s.connection(),
        PREPARE_JOB,
        {"draft_id": str(draft.id), "no": ek.hazirlik_no, "isteyen": aktor},
        idempotency_key=f"{PREPARE_JOB}:{draft.id}:{ek.hazirlik_no}",
    )
    ek.job_id = job_id
    return job_id


# ------------------------------------------------------------------- taslak açılışı


def create_draft_from_failure(
    session: Session, failure_id: uuid.UUID, *, aktor: str = "system"
) -> uuid.UUID:
    """Gerçek defect sınıflı başarısızlıktan bug taslağı (çağıranın işleminde; idempotent).

    Aynı başarısızlık için taslak varsa onu, aynı hata imzasıyla açık taslak varsa onu döndürür
    (başarısızlık `ilgili_failure_ids`'e eklenir). `environment` vb. sınıflar taslak açmaz.
    """
    f = session.get(Failure, failure_id, with_for_update=True)
    if f is None:
        raise BugNotFound(f"Başarısızlık bulunamadı: {failure_id}")
    if f.sinif != "product_defect":
        raise BugStateError(
            f"Bug taslağı yalnızca gerçek defect (product_defect) için açılır; sınıf: {f.sinif}"
        )
    mevcut = session.scalars(
        select(BugDraft).where(BugDraft.failure_id == f.id).order_by(BugDraft.olusturma).limit(1)
    ).first()
    if mevcut is not None:
        return mevcut.id
    idempotency_lock(session.connection(), f"bug_draft:imza:{f.hata_imzasi}")
    ayni = session.scalars(
        select(BugDraft)
        .join(Failure, Failure.id == BugDraft.failure_id)
        .where(Failure.hata_imzasi == f.hata_imzasi, BugDraft.durum.in_(ACIK_DURUMLAR))
        .order_by(BugDraft.olusturma)
        .limit(1)
    ).first()
    if ayni is not None:
        ek = _ek(session, ayni)
        if str(f.id) not in ek.ilgili_failure_ids:
            ek.ilgili_failure_ids = [*ek.ilgili_failure_ids, str(f.id)]
        audit_on_commit(
            session,
            aktor,
            "bug_draft.failure_attached",
            f"bug_draft:{ayni.id}",
            {"failure_id": f.id, "hata_imzasi": f.hata_imzasi},
        )
        return ayni.id

    ctx = failure_context(session, f.id)
    icerik = content.template_draft(ctx)
    draft = BugDraft(
        failure_id=f.id, icerik=icerik, icerik_hash=content_hash(icerik), uretim_modu=None
    )
    session.add(draft)
    session.flush()
    ek = BugDraftEk(bug_draft_id=draft.id, kaynak="failure", imza=ctx.imza(), uretim="sablon")
    session.add(ek)
    session.flush()
    job_id = _enqueue_prepare(session, draft, ek, aktor)
    audit_on_commit(
        session,
        aktor,
        "bug_draft.created",
        f"bug_draft:{draft.id}",
        {"failure_id": f.id, "hash": draft.icerik_hash, "job_id": job_id},
    )
    _event(session, "bug.draft_created", draft, job_id=job_id)
    return draft.id


def adopt_draft(session: Session, draft_id: uuid.UUID, *, aktor: str = "system") -> bool:
    """Hazırlık hattına girmemiş taslağı (ör. Faz 2 tutarlılık taslağı) hatta alır.

    Bulgu/başarısızlık bağı korunur; içerik `bugs.prepare` ile yükseltilir. Zaten alınmışsa
    ya da taslak karar almışsa False.
    """
    draft = session.get(BugDraft, draft_id, with_for_update=True)
    if draft is None:
        raise BugNotFound(f"Bug taslağı bulunamadı: {draft_id}")
    if session.get(BugDraftEk, draft.id) is not None or draft.durum != "draft":
        return False
    ek = _ek(session, draft)
    ctx = _context(session, draft, ek)
    ek.imza = ctx.imza()
    job_id = _enqueue_prepare(session, draft, ek, aktor)
    audit_on_commit(
        session,
        aktor,
        "bug_draft.adopted",
        f"bug_draft:{draft.id}",
        {"kaynak": ek.kaynak, "finding_id": draft.finding_id, "job_id": job_id},
    )
    return True


def adopt_pending(engine: Engine | None = None) -> list[str]:
    """Hazırlık kaydı olmayan açık taslakları hatta alır (worker açılışı süpürmesi)."""
    with session_scope() as s:
        ids = list(
            s.scalars(
                select(BugDraft.id)
                .outerjoin(BugDraftEk, BugDraftEk.bug_draft_id == BugDraft.id)
                .where(BugDraftEk.bug_draft_id.is_(None), BugDraft.durum == "draft")
                .order_by(BugDraft.olusturma)
            )
        )
    alinan = []
    for did in ids:
        with session_scope() as s:
            if adopt_draft(s, did, aktor="system:bugs"):
                alinan.append(str(did))
    return alinan


def request_prepare(session: Session, draft_id: uuid.UUID, user: Principal) -> uuid.UUID:
    """Testçinin "mükerrer aramasını/taslağı yenile" isteği (yalnızca karar verilmemiş taslak)."""
    draft = session.get(BugDraft, draft_id, with_for_update=True)
    if draft is None:
        raise BugNotFound("Bug taslağı bulunamadı")
    if draft.durum != "draft":
        raise BugStateError(f"Yalnızca taslak yeniden hazırlanır (durum: {draft.durum})")
    ek = _ek(session, draft)
    if ek.hazirlik_durum in ("kuyrukta", "hazirlaniyor") and ek.job_id is not None:
        durum = session.execute(
            text("SELECT durum FROM job WHERE id = :j"), {"j": ek.job_id}
        ).scalar_one_or_none()
        if durum in ("queued", "running", "retry"):
            return ek.job_id
    if ek.imza == {}:
        ek.imza = _context(session, draft, ek).imza()
    job_id = _enqueue_prepare(session, draft, ek, user.kullanici_adi)
    audit_on_commit(
        session,
        user.kullanici_adi,
        "bug_draft.prepare_requested",
        f"bug_draft:{draft.id}",
        {"job_id": job_id, "no": ek.hazirlik_no},
    )
    return job_id


# ---------------------------------------------------------------- hazırlık (worker)


def _issue_text(issue: JiraIssue) -> str:
    return f"{issue.summary}\n{issue.description or ''}"


def search_candidates(
    jira: Any, proje: str, ctx: BugContext, haric: set[str]
) -> tuple[str | None, dict[str, Any], list[dict[str, Any]]]:
    """(jql, arama özeti, adaylar ≤ MAX_ADAY). Jira hatası taslağı durdurmaz; özetle bildirilir."""
    terimler = ctx.terms()
    sorgu = jql.duplicate_search_jql(proje, terimler)
    if sorgu is None:
        return None, {"durum": "atlandi", "neden": "hata imzasında arama terimi yok"}, []
    try:
        bulunan = jira.search(sorgu, max_results=ARAMA_LIMITI)
    except Exception as exc:
        return sorgu, {"durum": "hata", "hata": f"{type(exc).__name__}: {exc}"[:500]}, []
    adaylar = []
    elenen = 0
    for issue in bulunan:
        if issue.key in haric or issue.issue_type != "Bug" or issue.status == "Done":
            continue
        skor = jql.overlap_score(terimler, _issue_text(issue))
        if skor < MIN_SKOR:
            elenen += 1
            continue
        adaylar.append(
            {
                "key": issue.key,
                "summary": issue.summary,
                "status": issue.status,
                "description": issue.description or "",
                "skor": skor,
            }
        )
    adaylar.sort(key=lambda a: (-a["skor"], a["key"]))
    secilen = adaylar[:MAX_ADAY]
    return (
        sorgu,
        {
            "durum": "yapildi",
            "bulunan": len(bulunan),
            "aday_sayisi": len(secilen),
            "dusuk_skor_elenen": elenen,
            "terimler": terimler,
        },
        secilen,
    )


def _sirasiz(
    temel: list[dict[str, Any]], neden: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    for a in temel:
        a.update({"rank": None, "likelihood": None, "rationale": None, "ai": False})
    return temel, {"recommendation": "new", "link_key": None, "neden": neden}


def siralama_hatasi_metni(exc: Exception) -> str:
    """Portalda gösterilen Türkçe neden (istisna sınıf adı sahneye çıkmaz)."""
    from tp_core.gateway.errors import (
        BudgetExceeded,
        ProviderNotConfigured,
        ProviderRefusal,
        ProviderTransientError,
        ReplayNotFound,
        SchemaValidationFailed,
    )

    son = "adaylar sıralanmadı; karar testçinin"
    if isinstance(exc, ReplayNotFound):
        return f"REPLAY kaydı yok: {son}"
    if isinstance(exc, BudgetExceeded):
        return f"Model maliyet tavanı aşıldı: {son}"
    if isinstance(exc, ProviderNotConfigured):
        return f"Model sağlayıcısı yapılandırılmamış: {son}"
    if isinstance(exc, ProviderTransientError):
        return f"Model şu an yanıt vermiyor: {son}"
    if isinstance(exc, ProviderRefusal):
        return f"Model isteği reddetti: {son}"
    if isinstance(exc, SchemaValidationFailed):
        return f"AI çıktısı şemaya uymadı: {son}"
    return f"AI sıralaması yapılamadı: {son}"


def rank_candidates(
    gw: Any,
    ctx: BugContext,
    taslak: Mapping[str, Any],
    adaylar: list[dict[str, Any]],
    *,
    sorgu: str | None,
    call_id: uuid.UUID | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], Any]:
    """(adaylar, öneri, CallResult|None). Model yalnızca aramanın bulduğu anahtarları sıralar;
    aramada olmayan anahtar dönerse ya da sıralama değişmezleri bozuksa (`dup_rank_problems`)
    sıralama hiç kullanılmaz."""
    from tp_core.gateway import (
        GatewayError,
        defect_replay_key,
        dup_rank_messages,
        dup_rank_problems,
        invented_dup_keys,
        load_schema,
    )

    temel = [{k: v for k, v in a.items() if k != "description"} for a in adaylar]
    if not adaylar:
        return [], {"recommendation": "new", "link_key": None, "neden": "aday yok"}, None
    try:
        sonuc = gw.call(
            DUP_PURPOSE,
            DUP_BUNDLE,
            dup_rank_messages(ctx.sources(), draft=taslak, candidates=adaylar, jql=sorgu),
            load_schema(gw.rules_dir, DUP_PURPOSE),
            replay_key=defect_replay_key(ctx.story_key),
            call_id=call_id,
        )
    except GatewayError as exc:
        sirali, oneri = _sirasiz(temel, siralama_hatasi_metni(exc))
        return sirali, oneri, None
    cikti = sonuc.output or {}
    uydurulan = invented_dup_keys(cikti, adaylar)
    if uydurulan:
        sirali, oneri = _sirasiz(
            temel, "AI aramada olmayan anahtar(lar) sıraladı; sıralama kullanılmadı"
        )
        oneri["atilan_anahtarlar"] = uydurulan
        return sirali, oneri, sonuc
    sorunlar = dup_rank_problems(cikti, adaylar)
    if sorunlar:
        sirali, oneri = _sirasiz(temel, ("AI sıralaması geçersiz: " + "; ".join(sorunlar))[:300])
        return sirali, oneri, sonuc
    sira = {c["key"]: c for c in cikti.get("candidates") or [] if isinstance(c, Mapping)}
    for a in temel:
        c = sira.get(a["key"])
        a.update(
            {
                "rank": c.get("rank") if c else None,
                "likelihood": c.get("likelihood") if c else None,
                "rationale": c.get("rationale") if c else None,
                "ai": c is not None,
            }
        )
    temel.sort(key=lambda a: (a["rank"] is None, a["rank"] or 0, -a["skor"], a["key"]))
    link_key = cikti.get("link_key")
    oneri: dict[str, Any] = {"recommendation": "new", "link_key": None, "neden": None}
    if (
        cikti.get("recommendation") == "link"
        and link_key in sira
        and sira[link_key].get("likelihood") == "high"
    ):
        oneri = {"recommendation": "link", "link_key": link_key, "neden": None}
    elif cikti.get("recommendation") == "link":
        oneri["neden"] = "AI 'link' önerdi ama yüksek olasılıklı aday yok; öneri 'new'"
    return temel, oneri, sonuc


def draft_with_ai(
    gw: Any, ctx: BugContext, sablon: dict[str, Any], *, call_id: uuid.UUID | None
) -> tuple[dict[str, Any], list[dict[str, Any]], Any, str | None]:
    """(içerik, düzeltmeler, CallResult|None, hata). Hata/REPLAY-MISS'te şablon döner."""
    from tp_core.gateway import (
        GatewayError,
        bug_draft_messages,
        defect_replay_key,
        load_schema,
        resolve_evidence,
    )

    mesajlar = bug_draft_messages(
        ctx.sources(),
        testdata=services.testdata(),
        story_key=ctx.story_key,
        test_case_key=ctx.test_case_key,
    )
    try:
        sonuc = gw.call(
            DRAFT_PURPOSE,
            DRAFT_BUNDLE,
            mesajlar,
            load_schema(gw.rules_dir, DRAFT_PURPOSE),
            replay_key=defect_replay_key(ctx.story_key),
            call_id=call_id,
        )
    except GatewayError as exc:
        return dict(sablon), [], None, f"{type(exc).__name__}: {exc}"[:500]
    cikti = resolve_evidence(sonuc.output or {}, ctx.baglantilar, literal_refs=ctx.literal_refs())
    icerik, duzeltmeler = content.apply_guards(cikti, ctx, sablon)
    return icerik, duzeltmeler, sonuc, None


def run_prepare(ctx_job: JobContext, engine: Engine) -> dict[str, Any]:
    from tp_core.gateway import deterministic_call_id

    yuk = ctx_job.yuk or {}
    try:
        draft_id = uuid.UUID(str(yuk.get("draft_id")))
    except ValueError as exc:
        raise PermanentJobError("geçersiz taslak kimliği") from exc
    no = int(yuk.get("no") or 0)
    with session_scope() as s:
        draft = s.get(BugDraft, draft_id, with_for_update=True)
        if draft is None:
            raise PermanentJobError("taslak silinmiş")
        ek = _ek(s, draft)
        if draft.durum != "draft" or (no and ek.hazirlik_no != no):
            return {"atlandi": True, "durum": draft.durum, "hazirlik_no": ek.hazirlik_no}
        ek.hazirlik_durum = "hazirlaniyor"
        ctx = _context(s, draft, ek)
        baslangic_hash = draft.icerik_hash
        haric = {draft.jira_key} if draft.jira_key else set()
        ilk = ek.uretim is None
    try:
        sablon = content.template_draft(ctx)
        proje = services.project()
        sorgu, arama, adaylar = search_candidates(services.jira(), proje, ctx, haric)
        gw = services.gateway(engine)
        icerik, duzeltmeler, taslak_sonuc, taslak_hatasi = draft_with_ai(
            gw, ctx, sablon, call_id=deterministic_call_id(ctx_job.job_id, f"bug_draft:{no}")
        )
        sirali, oneri, dup_sonuc = rank_candidates(
            gw,
            ctx,
            icerik,
            adaylar,
            sorgu=sorgu,
            call_id=deterministic_call_id(ctx_job.job_id, f"dup:{no}"),
        )
    except Exception as exc:
        if ctx_job.son_deneme or isinstance(exc, PermanentJobError):
            with session_scope() as s:
                draft = s.get(BugDraft, draft_id, with_for_update=True)
                if draft is not None:
                    ek = _ek(s, draft)
                    ek.hazirlik_durum = "basarisiz"
                    # K19 / güvenlik #11: ham istisna metni maskeli saklanır.
                    ek.hazirlik_hatasi = maskele_obje(
                        f"{type(exc).__name__}: {exc}"[:1000], ctx.gizli_degerler
                    )
                    audit_on_commit(
                        s,
                        "system:bugs",
                        "bug_draft.prepare_failed",
                        f"bug_draft:{draft.id}",
                        {"hata": ek.hazirlik_hatasi},
                    )
                    _event(s, "bug.prepare_failed", draft, hata=ek.hazirlik_hatasi)
        raise

    with session_scope() as s:
        draft = s.get(BugDraft, draft_id, with_for_update=True)
        if draft is None:
            raise PermanentJobError("taslak silinmiş")
        ek = _ek(s, draft)
        icerik_yazildi = (
            draft.durum == "draft" and draft.icerik_hash == baslangic_hash and ek.duzenleyen is None
        )
        if icerik_yazildi:
            draft.icerik = icerik
            draft.icerik_hash = content_hash(icerik)
            draft.ai_call_id = taslak_sonuc.call_id if taslak_sonuc else None
            draft.uretim_modu = taslak_sonuc.mode if taslak_sonuc else None
            ek.uretim = "ai" if taslak_sonuc else "sablon"
            # K19 / güvenlik #11: ham model çıktısı maskeli saklanır (model girdisi değişmez).
            ek.ai_icerik = (
                maskele_obje(taslak_sonuc.output, ctx.gizli_degerler) if taslak_sonuc else None
            )
            ek.duzeltmeler = duzeltmeler
        elif ilk:
            ek.uretim = "sablon"
        draft.mukerrer_adaylari = sirali
        ek.imza = ctx.imza()
        # K19 / güvenlik #1: terimler sırrın parçalarını içermez; yine de maskeli yazılır.
        sorgu = maskele_obje(sorgu, ctx.gizli_degerler)
        arama = maskele_obje(arama, ctx.gizli_degerler)
        ek.jql = sorgu
        ek.arama = arama
        ek.dup_ai_call_id = dup_sonuc.call_id if dup_sonuc else None
        ek.dup_uretim_modu = dup_sonuc.mode if dup_sonuc else None
        ek.oneri = oneri
        ek.hazirlik_durum = "hazir"
        ek.hazirlik_hatasi = maskele_obje(taslak_hatasi, ctx.gizli_degerler)
        ozet = {
            "hazirlik_no": no,
            "jql": sorgu,
            "arama": arama.get("durum"),
            "adaylar": [a["key"] for a in sirali],
            "oneri": oneri.get("recommendation"),
            "link_key": oneri.get("link_key"),
            "icerik_yazildi": icerik_yazildi,
            "uretim": ek.uretim,
            "mode": draft.uretim_modu,
            "dup_mode": ek.dup_uretim_modu,
            "duzeltmeler": [d["alan"] for d in duzeltmeler],
            "hash": draft.icerik_hash,
        }
        audit_on_commit(s, "system:bugs", "bug_draft.prepared", f"bug_draft:{draft.id}", ozet)
        _event(
            s,
            "bug.draft_ready",
            draft,
            adaylar=[a["key"] for a in sirali],
            oneri=oneri.get("recommendation"),
            mode=draft.uretim_modu,
        )
    return ozet


# ------------------------------------------------------------------- karar (API)


def _lock_draft(s: Session, draft_id: uuid.UUID) -> BugDraft:
    draft = s.get(BugDraft, draft_id, with_for_update=True)
    if draft is None:
        raise BugNotFound("Bug taslağı bulunamadı")
    return draft


def _enqueue_publish(s: Session, draft: BugDraft, user: Principal) -> uuid.UUID:
    ek = _ek(s, draft)
    deneme = int((ek.yayin or {}).get("deneme") or 0) + 1
    job_id = enqueue(
        s.connection(),
        PUBLISH_JOB,
        {"draft_id": str(draft.id), "isteyen": user.as_dict()},
        idempotency_key=f"{PUBLISH_JOB}:{draft.id}:{draft.icerik_hash}:{deneme}",
    )
    ek.yayin = {**(ek.yayin or {}), "durum": "kuyrukta", "job_id": str(job_id), "deneme": deneme}
    return job_id


def link_target_problem(jira: Any, proje: str, link_key: str) -> str | None:
    """`link` hedefinin neden bağlanamayacağı (Türkçe) ya da None. Jira'ya ulaşılamazsa
    `JiraUnreachable`. Hem karar anında (core-api, okuma kimliği) hem yayında denetlenir."""
    from tp_core.integrations.jira import JiraError, JiraNotFound

    if not jql.is_issue_key(link_key):
        return f"'{link_key}' geçerli bir Jira anahtarı değil"
    if link_key.rsplit("-", 1)[0] != proje:
        return f"{link_key} {proje} projesinde değil; yalnızca {proje} projesindeki Bug'a bağlanır"
    try:
        hedef = jira.get_issue(link_key)
    except JiraNotFound:
        return f"{link_key} Jira'da bulunamadı"
    except JiraError as exc:
        raise JiraUnreachable(
            f"{link_key} Jira'da doğrulanamadı (Jira'ya ulaşılamadı); biraz sonra tekrar deneyin"
        ) from exc
    if hedef.issue_type != "Bug":
        return f"{link_key} bir Bug değil ({hedef.issue_type}); yalnızca Bug'a bağlanır"
    if hedef.status.strip().casefold() in ("done", "tamamlandı", "closed", "kapalı"):
        return f"{link_key} kapalı ({hedef.status}); açık bir Bug seçin ya da 'Yeni kayıt' verin"
    return None


def _check_human_content(s: Session, draft: BugDraft, yeni: Mapping[str, Any] | None) -> None:
    if yeni is None:
        return
    ek = _ek(s, draft)
    try:
        ctx = _context(s, draft, ek)
    except (PermanentJobError, LookupError) as exc:
        raise InvalidDecision(f"Taslağın bağlamı okunamadı: {exc}") from exc
    try:
        content.check_human_edit(yeni, draft.icerik or {}, ctx)
    except content.ContentError as exc:
        raise InvalidDecision(str(exc)) from exc


def decide(
    s: Session,
    draft_id: uuid.UUID,
    user: Principal,
    karar: str,
    icerik_hash: str | None,
    *,
    icerik: Mapping[str, Any] | None = None,
    link_key: str | None = None,
    gerekce: str | None = None,
) -> uuid.UUID | None:
    """Testçi kararı; `new`/`link` için kuyruğa giren yayın işinin kimliğini döndürür."""
    if user.rol != "tester" or user.kanal != "portal":
        raise ApprovalNotAllowed("Bug taslağı kararını yalnızca portaldaki testçi verir")
    if not icerik_hash:
        raise InvalidDecision("Karar, görüntülenen içeriğin hash'ini (icerik_hash) taşımalı")
    draft = _lock_draft(s, draft_id)
    gerekce = (gerekce or "").strip() or None

    if karar == "reopen":
        yayin_basarisiz = draft.durum == "approved" and _yayin_takili(s, draft)
        if draft.durum != "dismissed" and not yayin_basarisiz:
            raise BugStateError(
                "Yalnızca reddedilmiş ya da yayını başarısız olmuş onaylı taslak taslağa alınır "
                f"({draft.durum})"
            )
        if icerik_hash != draft.icerik_hash:
            raise GateClosed("İçerik siz görüntüledikten sonra değişmiş; yenileyin")
        onceki = draft.durum
        if yayin_basarisiz:
            draft.karar = None
            draft.link_key = None
        transition(s, draft, "draft", user, onceki, sebep=gerekce or "taslağa alındı")
        _oneri_durumu_yaz(s, draft, "proposed")
        _event(s, "bug.reopened", draft, onceki=onceki)
        return None

    if draft.durum != "draft":
        raise BugStateError(f"Taslak karar beklemiyor (durum: {draft.durum})")
    yeni_icerik: dict[str, Any] | None = None
    if icerik is not None:
        try:
            yeni_icerik = content.validate(dict(icerik))
        except content.ContentError as exc:
            raise InvalidDecision(str(exc)) from exc
        if yeni_icerik == draft.icerik:
            yeni_icerik = None
    if karar in ("edit", "new", "link"):
        # İnsan düzenlemesine de bağlam korumaları: story/Test anahtarı ve kanıt kökeni.
        _check_human_content(s, draft, yeni_icerik)

    if karar == "edit":
        if yeni_icerik is None:
            raise InvalidDecision("Düzenleme kararı değişmiş içerik ister")
        if icerik_hash != draft.icerik_hash:
            raise GateClosed("İçerik siz görüntüledikten sonra değişmiş; yenileyin")
        once = draft.icerik_hash
        draft.icerik = yeni_icerik
        draft.icerik_hash = content_hash(yeni_icerik)
        _ek(s, draft).duzenleyen = user.kullanici_adi
        audit_on_commit(
            s,
            user.kullanici_adi,
            "bug_draft.edited",
            f"bug_draft:{draft.id}",
            {"once_hash": once, "hash": draft.icerik_hash},
        )
        _event(s, "bug.draft_edited", draft, hash=draft.icerik_hash)
        return None

    if karar == "dismiss":
        if not gerekce:
            raise InvalidDecision("Taslağı reddetmek için gerekçe zorunludur")
        record_approval(s, draft, user, "dismiss", gerekce=gerekce, beklenen_hash=icerik_hash)
        transition(s, draft, "dismissed", user, "draft", sebep=gerekce)
        _oneri_durumu_yaz(s, draft, "rejected")
        _event(s, "bug.dismissed", draft, gerekce=gerekce)
        return None

    if karar not in ("new", "link"):
        raise InvalidDecision("Karar new, link, edit, dismiss veya reopen olmalı")
    if karar == "link":
        if not jql.is_issue_key(link_key):
            raise InvalidDecision("'Mevcut kayda bağla' için geçerli bir Jira anahtarı gerekir")
        assert link_key is not None
        if icerik_hash != draft.icerik_hash:
            raise GateClosed("İçerik siz görüntüledikten sonra değişmiş; yenileyin")
        # Hedef onaydan ÖNCE doğrulanır: Bug olmayan / olmayan / kapalı kayda bağlanan taslak
        # yayında kalıcı olarak takılırdı.
        sorun = link_target_problem(services.jira(), services.project(), link_key)
        if sorun:
            raise InvalidDecision(sorun)
    elif link_key:
        raise InvalidDecision("'Yeni kayıt' kararı link_key almaz")
    record_approval(
        s,
        draft,
        user,
        karar,
        gerekce=gerekce,
        beklenen_hash=icerik_hash,
        degisiklik={"icerik": yeni_icerik} if yeni_icerik is not None else None,
    )
    draft.karar = karar
    draft.link_key = link_key if karar == "link" else None
    draft.onaylayan_id = user.id
    transition(s, draft, "approved", user, "draft", ozet={"karar": karar, "link_key": link_key})
    job_id = _enqueue_publish(s, draft, user)
    audit_on_commit(
        s,
        user.kullanici_adi,
        "bug.publish_requested",
        f"bug_draft:{draft.id}",
        {"karar": karar, "link_key": link_key, "job_id": job_id, "hash": draft.icerik_hash},
    )
    return job_id


def _yayin_isi_bekliyor(s: Session, draft_id: uuid.UUID) -> bool:
    """Bu taslak için kuyrukta / çalışan / yeniden denenecek yayın işi var mı?"""
    return bool(
        s.execute(
            text(
                "SELECT 1 FROM job WHERE tur = :t AND durum IN ('queued', 'running', 'retry') "
                "AND yuk ->> 'draft_id' = :d LIMIT 1"
            ),
            {"t": PUBLISH_JOB, "d": str(draft_id)},
        ).first()
    )


def _yayin_takili(s: Session, draft: BugDraft) -> bool:
    """Onaylı taslağın yayını başarısız oldu ve bekleyen yayın işi yok (testçi taslağa alabilir)."""
    ek = s.get(BugDraftEk, draft.id)
    if ek is None or (ek.yayin or {}).get("durum") != "basarisiz":
        return False
    return not _yayin_isi_bekliyor(s, draft.id)


def retry_publish(s: Session, draft_id: uuid.UUID, user: Principal) -> uuid.UUID:
    if user.rol != "tester":
        raise ApprovalNotAllowed("Yayını yalnızca testçi yeniden dener")
    draft = _lock_draft(s, draft_id)
    if draft.durum != "approved":
        raise BugStateError(f"Yalnızca onaylı taslak yayınlanır (durum: {draft.durum})")
    if not approved_hash_matches(s, draft):
        raise GateClosed("İçerik onaydan sonra değişmiş; yeniden onay gerekir")
    job_id = _enqueue_publish(s, draft, user)
    audit_on_commit(
        s, user.kullanici_adi, "bug.publish_retry", f"bug_draft:{draft.id}", {"job_id": job_id}
    )
    return job_id


# ------------------------------------------------------------------ yayın (worker)


class JiraContentMismatch(Exception):
    def __init__(self, mesaj: str, key: str | None) -> None:
        super().__init__(mesaj)
        self.external_key = key


def mark_jira_deleted(
    session: Session, keys: list[str], *, neden: str, aktor: str = "system"
) -> list[str]:
    """Sistemin açıp dışarıda (demo sıfırlaması) silinen Bug'larını taslaklarda işaretler.

    Yalnızca `karar='new'` ile yayınlanmış (anahtarı bu sistem açmış) taslaklar; bağlanan mevcut
    kayıtlar (`link`, ör. TPD-5) silinmez. Durum makinesi ve onay kaydı değişmez (published son
    durumdur); işaret `bug_draft_ek.yayin.jira_silindi`'dedir, görünüm bağlantıyı kaldırır.
    """
    if not keys:
        return []
    isaretlenen: list[str] = []
    zaman = datetime.now(UTC).isoformat()
    for draft in session.scalars(
        select(BugDraft).where(
            BugDraft.jira_key.in_(keys), BugDraft.durum == "published", BugDraft.karar == "new"
        )
    ).all():
        ek = _ek(session, draft)
        yayin = dict(ek.yayin or {})
        if yayin.get("jira_silindi"):
            continue
        yayin["jira_silindi"] = {"key": draft.jira_key, "zaman": zaman, "neden": neden}
        ek.yayin = yayin
        isaretlenen.append(str(draft.id))
        audit_on_commit(
            session,
            aktor,
            "bug_draft.jira_deleted",
            f"bug_draft:{draft.id}",
            {"jira_key": draft.jira_key, "neden": neden},
        )
    return isaretlenen


def mod_label_of(s: Session, draft: BugDraft) -> tuple[str, str]:
    """(dürüst üretim modu metni, Jira etiketi)."""
    from tp_core.gateway import mode_label

    if draft.uretim_modu is None or draft.ai_call_id is None:
        return MOD_ETIKETI_SABLON, "tp-mod-sablon"
    model = s.scalar(select(AiCall.model).where(AiCall.id == draft.ai_call_id))
    return mode_label(draft.uretim_modu, model), "tp-mod-" + draft.uretim_modu.replace("_", "-")


def _link_types(jira: Any) -> list[str] | None:
    fn = getattr(jira, "link_type_names", None)
    if fn is None:
        return None
    try:
        return list(fn())
    except Exception:
        return None


def _link(
    jira: Any, inward: str, outward: str, adaylar: list[str], mevcut: list[str] | None
) -> str:
    """Bağlantıyı ilk kullanılabilir türle kurar; kullanılan türü döndürür."""
    from tp_core.integrations.jira import JiraBadRequest, JiraNotFound

    secenek = [t for t in adaylar if mevcut is None or t in mevcut] or adaylar[-1:]
    son: Exception | None = None
    for tur in secenek:
        try:
            jira.link_issues(inward, outward, tur)
            return tur
        except (JiraBadRequest, JiraNotFound) as exc:
            son = exc
    raise RuntimeError(f"{inward} ↔ {outward} bağlanamadı: {son}")


def _bag_hedefleri_var(jira: Any, icerik: Mapping[str, Any]) -> None:
    """Bağlanacak Story/Test issue'ları Jira'da var mı — Jira'ya HİÇBİR şey yazmadan önce.

    Yoksa (ör. jira-sim elle sıfırlanmış) kalıcı ret: yetim Bug açılmaz, taslak yeniden karara
    döner. Jira'ya ulaşılamazsa geçici hata (iş yeniden denenir).
    """
    from tp_core.integrations.jira import JiraError, JiraNotFound

    for rol, alan in (("Story", "story_key"), ("Test issue", "test_case_key")):
        key = icerik.get(alan)
        if not key:
            continue
        try:
            jira.get_issue(str(key))
        except JiraNotFound as exc:
            raise LinkTargetError(
                f"{rol} {key} Jira'da yok (jira-sim sıfırlanmış olabilir); make reset ya da "
                "case'leri yeniden yayınlayın"
            ) from exc
        except JiraError as exc:
            raise RuntimeError(f"{rol} {key} Jira'da doğrulanamadı: {exc}") from exc


def _links(jira: Any, bug_key: str, icerik: Mapping[str, Any]) -> list[dict[str, str]]:
    mevcut = _link_types(jira)
    out = []
    story = icerik.get("story_key")
    if story and story != bug_key:
        tur = _link(jira, bug_key, story, [RELATES_LINK], mevcut)
        out.append({"hedef": story, "tur": tur, "rol": "story"})
    test_key = icerik.get("test_case_key")
    if test_key and test_key != bug_key:
        # Test türü: inward "tests" outward → Bug "is tested by" Test (yoksa Relates).
        tur = _link(jira, test_key, bug_key, [TEST_LINK, RELATES_LINK], mevcut)
        out.append({"hedef": test_key, "tur": tur, "rol": "test"})
    return out


def _create_bug(
    jira: Any, proje: str, icerik: Mapping[str, Any], etiketler: list[str], adf: dict[str, Any]
) -> str:
    from tp_core.integrations.jira import JiraBadRequest

    oncelik = content.SEVERITY_PRIORITY.get(str(icerik.get("severity_suggestion")))
    alanlar: dict[str, Any] = {"description": adf}
    if oncelik:
        alanlar["priority"] = {"name": oncelik}
    try:
        return jira.create_issue(proje, "Bug", str(icerik["summary"]), "", etiketler, alanlar)
    except JiraBadRequest as exc:
        if "priority" not in exc.errors:
            raise
    alanlar.pop("priority", None)
    return jira.create_issue(proje, "Bug", str(icerik["summary"]), "", etiketler, alanlar)


def _sonuc(draft_id: uuid.UUID, durum: str, key: str | None = None, **ek: Any) -> dict[str, Any]:
    return {"draft_id": str(draft_id), "durum": durum, "jira_key": key, **ek}


def publish_bug(
    draft_id: uuid.UUID,
    *,
    aktor: str = "system:bugs",
    job_id: uuid.UUID | None = None,
    son_deneme: bool = False,
) -> dict[str, Any]:
    """Onaylı taslağı Jira'ya yazar (`new`: Bug aç; `link`: mevcut Bug'a yorum + bağlantı).

    Kalıcı hata (`PermanentJobError`, Jira içerik uyuşmazlığı) ya da son denemede de süren geçici
    hata taslağı `approved → draft` döndürür: testçi yeniden karar verir (takılı onay kalmaz).
    Jira'ya kısmen yazılanlar `yayin.key`'de kalır; aynı içerikle verilen yeni `new` kararı
    `tp-<uuid>` etiketiyle aynı Bug'ı bulur (ikinci Bug açılmaz), `link` yorumu bir kez yazılır.
    """
    with session_scope() as s:
        draft = _lock_draft(s, draft_id)
        if draft.durum == "published":
            return _sonuc(draft.id, "exists", draft.jira_key)
        if draft.durum != "approved":
            raise PermanentJobError(f"Taslak onaylı değil (durum: {draft.durum})")
        if not approved_hash_matches(s, draft):
            raise PermanentJobError("İçerik onaydan sonra değişmiş (onaylanan hash ≠ güncel)")
        karar = draft.karar
        if karar not in ("new", "link"):
            raise PermanentJobError(f"geçersiz karar: {karar}")
        anahtar = f"jira:bug:{karar}:{draft.id}:{draft.icerik_hash}"
        if karar == "link":
            anahtar += f":{draft.link_key}"
        ref = s.scalars(select(ExternalRef).where(ExternalRef.idempotency_key == anahtar)).first()
        if ref is not None and ref.durum == "created":
            key = ref.external_key
            yayin_onceki: dict[str, Any] | None = {"external_key": key, "url": ref.url}
        else:
            yayin_onceki = None
            if (
                ref is not None
                and ref.durum == "intent"
                and datetime.now(UTC) - ref.guncelleme < timedelta(seconds=INTENT_KILIT_S)
                and _baska_is_calisiyor(s, draft.id, job_id)
            ):
                raise RuntimeError("Bu taslak için yayın sürüyor; yeniden denenecek")
            if ref is None:
                ref = ExternalRef(
                    entity_turu="bug_draft",
                    entity_id=draft.id,
                    sistem="jira",
                    idempotency_key=anahtar,
                    durum="intent",
                )
                s.add(ref)
            else:
                ref.durum = "intent"
                ref.hata = None
                ref.guncelleme = datetime.now(UTC)
        icerik = dict(draft.icerik)
        icerik_hash = draft.icerik_hash
        link_key = draft.link_key
        onaylayan = (
            s.scalar(select(AppUser.kullanici_adi).where(AppUser.id == draft.onaylayan_id))
            if draft.onaylayan_id
            else None
        )
        mod_metni, mod_etiketi = mod_label_of(s, draft)
        etiket = tp_label(draft.id)
        kod_sha = _kod_sha(s, draft)
    jira = services.jira()
    bag: list[dict[str, str]] = []
    yorum_id: str | None = None
    key = yayin_onceki["external_key"] if yayin_onceki else None
    try:
        if yayin_onceki is None:
            from tp_core.db import get_engine

            with get_engine().connect() as c:
                zincir = chain_tip(c)
            ortak = {
                "draft_label": etiket,
                "onaylayan": onaylayan,
                "mod_etiketi": mod_metni,
                "icerik_hash": icerik_hash,
                "zincir_hash": zincir,
                "kanit": content.public_evidence(
                    icerik.get("evidence"),
                    base_url=services.public_base_url(),
                    kod_sha=kod_sha,
                    kod_url=services.code_url,
                ),
            }
            _bag_hedefleri_var(jira, icerik)
            if karar == "new":
                proje = services.project()
                bulunan = jira.search(jql.label_jql(proje, etiket), max_results=1)
                if bulunan:
                    key = bulunan[0].key
                    mevcut = jira.get_issue(key)
                    if f"onaylanan içerik hash: {icerik_hash}" not in (mevcut.description or ""):
                        raise JiraContentMismatch(
                            f"Jira'da bu taslak için farklı içerikle açılmış {key} var; onaylı "
                            "içerik yazılmadı (kaydı Jira'da düzeltin ya da etiketi kaldırın)",
                            key,
                        )
                else:
                    # Yeni Bug: açıklamanın ilk satırı bot imi + @Mühendis @Testçi (yorum yazılmaz;
                    # Jira açıklamadaki bahsetmeyi de bildirir). Onaylanan içerik/hash aynıdır.
                    key = _create_bug(
                        jira,
                        proje,
                        icerik,
                        [AI_LABEL, etiket, mod_etiketi],
                        with_bot_header(
                            content.description_adf(icerik, **ortak),
                            jira_notify.role_mentions(jira_notify.BUG),
                        ),
                    )
            else:
                assert link_key is not None
                try:
                    sorun = link_target_problem(jira, services.project(), link_key)
                except JiraUnreachable as exc:
                    raise RuntimeError(str(exc)) from exc  # geçici: iş yeniden denenir
                if sorun:
                    raise LinkTargetError(sorun)
                key = link_key
                yorumlar = jira.get_comments(link_key)
                var = next((c for c in yorumlar if etiket in (c.body or "")), None)
                yorum_id = (
                    var.id
                    if var is not None
                    else services.add_adf_comment(
                        jira,
                        link_key,
                        content.link_comment(icerik, **ortak),
                        mentions=jira_notify.role_mentions(jira_notify.BUG),
                    )
                )
            bag = _links(jira, key, icerik)
    except Exception as exc:
        kismi = getattr(exc, "external_key", None) or key
        with session_scope() as s:
            ref = s.scalars(select(ExternalRef).where(ExternalRef.idempotency_key == anahtar)).one()
            ref.durum = "failed"
            ref.hata = f"{type(exc).__name__}: {exc}"[:2000]
            ref.external_key = kismi or ref.external_key
            draft = _lock_draft(s, draft_id)
            ek = _ek(s, draft)
            ek.yayin = {**(ek.yayin or {}), "durum": "basarisiz", "hata": ref.hata, "key": kismi}
            kalici = son_deneme or isinstance(exc, PermanentJobError | JiraContentMismatch)
            taslaga_dondu = kalici and draft.durum == "approved"
            if taslaga_dondu:
                # Yayın kalıcı olarak başarısız: taslak takılı kalmaz, testçi yeniden karar verir.
                not_ = f"{exc} — taslak yeniden karar için taslağa alındı"
                if kismi and not isinstance(exc, LinkTargetError):
                    not_ += (
                        f" (Jira'ya kısmen yazıldı: {kismi}; aynı içerikle yeniden onay bu "
                        "kaydı yeniden kullanır)"
                    )
                ek.yayin["hata"] = not_
                ek.yayin["onceki_karar"] = karar
                if karar == "link":
                    ek.yayin["onceki_link_key"] = link_key
                draft.karar = None
                draft.link_key = None
                transition(s, draft, "draft", aktor, "approved", sebep=f"yayın başarısız: {exc}")
                _oneri_durumu_yaz(s, draft, "proposed")
            audit_on_commit(
                s,
                aktor,
                "bug.publish_failed",
                f"bug_draft:{draft.id}",
                {
                    "karar": karar,
                    "hata": ref.hata,
                    "kismi": kismi,
                    "link_key": link_key,
                    "taslaga_dondu": taslaga_dondu,
                },
            )
            _event(
                s,
                "bug.publish_failed",
                draft,
                hata=ek.yayin["hata"],
                jira_key=kismi,
                taslaga_dondu=taslaga_dondu,
            )
        if isinstance(exc, PermanentJobError | JiraContentMismatch):
            raise PermanentJobError(str(exc)) from exc
        raise

    url_fn = getattr(jira, "issue_url", None)
    url = url_fn(key) if url_fn and key else None
    with session_scope() as s:
        ref = s.scalars(select(ExternalRef).where(ExternalRef.idempotency_key == anahtar)).one()
        ref.durum = "created"
        ref.external_key = key
        ref.url = url or ref.url
        ref.hata = None
        draft = _lock_draft(s, draft_id)
        ek = _ek(s, draft)
        degisti = draft.icerik_hash != icerik_hash or (
            draft.durum == "approved" and not approved_hash_matches(s, draft)
        )
        if degisti:
            # Jira kaydı var ama taslak yazım sırasında değişti: durum ilerlemez, insan inceler.
            ek.yayin = {**(ek.yayin or {}), "durum": "incelenmeli", "key": key, "url": url}
            audit_on_commit(
                s,
                aktor,
                "bug.publish_changed",
                f"bug_draft:{draft.id}",
                {"jira_key": key, "yayinlanan_hash": icerik_hash, "guncel": draft.icerik_hash},
            )
            return _sonuc(draft_id, "failed", key, hata="Yayın sırasında taslak değişti")
        if draft.durum == "approved":
            draft.jira_key = key
            transition(
                s,
                draft,
                "published",
                aktor,
                "approved",
                ozet={"jira_key": key, "karar": karar, "hash": icerik_hash},
            )
        if draft.durum == "published":
            _oneri_durumu_yaz(s, draft, "merged")
        ek.yayin = {
            **(ek.yayin or {}),
            "durum": "tamam",
            "key": key,
            "url": url,
            "karar": karar,
            "baglantilar": bag or (ek.yayin or {}).get("baglantilar") or [],
            "yorum_id": yorum_id,
            "hata": None,
        }
        audit_on_commit(
            s,
            aktor,
            "bug.published" if karar == "new" else "bug.linked",
            f"bug_draft:{draft.id}",
            {
                "jira_key": key,
                "karar": karar,
                "hash": icerik_hash,
                "baglantilar": bag,
                "yorum_id": yorum_id,
                "mode": draft.uretim_modu,
            },
        )
        _event(s, "bug.published", draft, jira_key=key, karar=karar, url=url)
    return _sonuc(
        draft_id, "created" if karar == "new" else "linked", key, url=url, baglantilar=bag
    )


def _kod_sha(s: Session, draft: BugDraft) -> str | None:
    """Kod kanıtının okunduğu commit: bulgunun denetimi (`requirement_kontrol.head_sha`) ya da
    başarısızlığın koşusu (`run.commit`)."""
    from tp_core.models.requirements_feature import ConsistencyFindingEk, RequirementKontrol

    if draft.finding_id is not None:
        return s.scalar(
            select(RequirementKontrol.head_sha)
            .join(ConsistencyFindingEk, ConsistencyFindingEk.kontrol_id == RequirementKontrol.id)
            .where(ConsistencyFindingEk.finding_id == draft.finding_id)
        )
    if draft.failure_id is not None:
        return s.scalar(
            select(Run.commit)
            .join(Failure, Failure.run_id == Run.id)
            .where(Failure.id == draft.failure_id)
        )
    return None


def _baska_is_calisiyor(s: Session, draft_id: uuid.UUID, job_id: uuid.UUID | None) -> bool:
    """Bu taslağı yayınlayan ve hâlâ `running` olan BAŞKA bir iş var mı?"""
    return bool(
        s.execute(
            text(
                "SELECT 1 FROM job WHERE tur = :t AND durum = 'running' "
                "AND id IS DISTINCT FROM :j AND yuk ->> 'draft_id' = :d LIMIT 1"
            ),
            {"t": PUBLISH_JOB, "d": str(draft_id), "j": job_id},
        ).first()
    )


def run_publish(ctx: JobContext) -> dict[str, Any]:
    yuk = ctx.yuk or {}
    try:
        draft_id = uuid.UUID(str(yuk.get("draft_id")))
    except ValueError as exc:
        raise PermanentJobError("geçersiz taslak kimliği") from exc
    isteyen = yuk.get("isteyen") or {}
    return publish_bug(
        draft_id,
        aktor=str(isteyen.get("kullanici_adi") or SYSTEM.kullanici_adi),
        job_id=ctx.job_id,
        son_deneme=ctx.son_deneme,
    )
