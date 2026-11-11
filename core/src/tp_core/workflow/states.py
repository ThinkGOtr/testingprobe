"""Varlık durum makineleri (TEKNIK-TASARIM §2, §2.1, §8.2a, §8.2b, §8.3, §8.4, §8.7, §8.12).

Bu modül saf veridir (model veya DB içe aktarmaz); hem `tp_core.models` (CHECK kısıtları, yazma
koruması) hem `tp_core.workflow.service.transition()` buradan okur. `durum` alanları YALNIZCA
`transition()` ile değişir; ORM `before_flush` koruması başka yoldan yazımı reddeder.

Kapı (gate): insan onayı gerektiren geçişlerde Postgres'teki `review` kaydı aranır. Kapı, nesnenin
**güncel içerik hash'i** ile son onay kaydının `onaylanan_hash`'i eşleşmedikçe açılmaz
(Constitution I). Yayın/PR/bug geçişleri aynı kontrolü tekrar yapar: onaydan sonra değişen içerik
reddedilir.

requirement (gereksinim; başlangıç ``new``)::

    new            -> in_review, failed
    in_review      -> findings_open, doc_final, failed   (ön inceleme + tutarlılık denetimi)
    findings_open  -> in_review, doc_final, new          (yeniden kontrol / bulgular kararlı)
    doc_final      -> pending_po, in_review, new         (doküman "son hal")
    pending_po     -> po_approved [KAPI: po_approve], in_review, new
    po_approved    -> generating | modeling [KAPI: PO onayı hâlâ güncel içerikte; koşul: ac_missing
                      değil], new
    modeling       -> model_ready, failed                       (iki tur — tur 1: tasarım modeli)
    model_ready    -> generating [KAPI: PO onayı güncel; servis: onaylı + güncel model],
                      modeling [KAPI] (model reddedildi / yeniden üret), new
    generating     -> cases_ready, failed
    cases_ready    -> generating | modeling [KAPI: PO onayı hâlâ güncel], done, new
    done           -> new                                       (kaynak değişti → yeniden)
    failed         -> in_review, generating | modeling [KAPI: PO onayı hâlâ güncel], new

    İki tur (011 F3, K1): `modeling` model üretimi (`model.generate`) sürerken, `model_ready`
    modelin analist kararını ve onaylı modelden case üretimini bekler. Tek tur eski yoldur
    (→ generating). `model_ready → generating` onaylı modelin varlığını kapı değil servis denetler
    (`features.cases.model_service`); kapı yine PO onayının güncelliğidir.

    `po_approved`'a girişte onaylanan içerik hash'i `requirement.onaylanan_hash`'e yazılır; case
    üretimine giden her geçiş bu hash'i güncel içerikle yeniden karşılaştırır (PO'nun görmediği
    metinden case üretilmez). `new`'e dönüş onaylanan hash'i siler.

requirement_review (başlangıç ``pending_po``)::

    pending_po -> approved, superseded
    approved   -> superseded
    superseded: son durum

consistency_finding (başlangıç ``unverified``)::

    unverified -> open (kanıt deterministik doğrulandı), discarded (doğrulanamadı; gösterilmez)
    open       -> decided [KAPI: fix_doc | code_defect | accept_difference; accept_difference
                  gerekçe ister], stale
    decided    -> resolved, open, stale
    resolved, stale, discarded: son durum

test_case (başlangıç ``draft``)::

    draft      -> approved [KAPI: approve | edit], rejected [KAPI: reject], superseded
    approved   -> published [KAPI: onaylı hash hâlâ güncel], draft, superseded
    rejected   -> draft, superseded
    published, superseded: son durum

design_model (tablo `tasarim_modeli`, 011 F3; başlangıç ``draft``)::

    draft      -> approved [KAPI: approve | edit], rejected [KAPI: reject], superseded
    approved   -> superseded
    rejected   -> superseded
    superseded: son durum

    Yeni model üretimi ve story değişikliği önceki modelleri `superseded` yapar.

script (üretilen test veya locator onarımı; başlangıç ``pending``)::

    pending    -> verifying, failed
    verifying  -> checking, blocked, failed                     (ajan doğrulama + eşleme)
    checking   -> verifying (tek düzeltme turu), pr_open, blocked, failed
    pr_open    -> merged [KAPI: merge], checking, closed
    blocked    -> verifying, closed                             (insana düştü)
    failed     -> pending, closed
    merged, closed: son durum

bug_draft (başlangıç ``draft``)::

    draft      -> approved [KAPI: new | link], dismissed [KAPI: dismiss]
    approved   -> published [KAPI: onaylı hash hâlâ güncel], draft
    dismissed  -> draft
    published: son durum

workflow_instance (başlangıç ``running``)::

    running       -> waiting_human, done, failed, paused, cancelled
    waiting_human -> running, cancelled
    paused        -> running, cancelled                         (bütçe aşımı → insan)
    failed        -> running, cancelled
    done, cancelled: son durum

`job`, `external_ref`, `pull_request`, `run`, `test_result` ve `failure` satırlarının durum benzeri
alanları altyapı kayıtlarıdır (kuyruk, idempotency, forge, koşu sonucu); kendi modüllerinin
fonksiyonlarıyla ve CHECK kısıtlarıyla yönetilir, insan kapısı taşımaz.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Gate:
    """İnsan onay kapısı: son `review` kaydının kararı `kararlar` içinde ve hash'i güncel olmalı."""

    kararlar: frozenset[str]


@dataclass(frozen=True)
class Guard:
    """Onaydan bağımsız deterministik koşul; `check(entity)` False ise geçiş reddedilir."""

    aciklama: str
    check: Callable[[Any], bool]


@dataclass(frozen=True)
class Machine:
    entity: str  # tablo adı
    initial: str
    transitions: dict[str, frozenset[str]]
    gates: dict[tuple[str, str], Gate] = field(default_factory=dict)
    guards: dict[tuple[str, str], Guard] = field(default_factory=dict)
    # Bu geçişe girildiğinde nesnenin `onaylanan_hash` alanı güncel hash'e yazılır.
    approval_targets: frozenset[str] = frozenset()
    # Bu durumlara giren kapılar nesnede kayıtlı `onaylanan_hash`'in güncel hash'e eşit olmasını
    # da ister (yalnızca son review kaydı yetmez). Hedefe dönüş (`initial`) hash'i sildiği için
    # geri çekilmiş bir onay kapıyı yeniden açamaz.
    approval_consumers: frozenset[str] = frozenset()

    @property
    def states(self) -> frozenset[str]:
        out = set(self.transitions)
        for hedefler in self.transitions.values():
            out |= hedefler
        return frozenset(out)

    def allowed(self, mevcut: str, hedef: str) -> bool:
        return hedef in self.transitions.get(mevcut, frozenset())


def _t(**kw: tuple[str, ...]) -> dict[str, frozenset[str]]:
    return {k: frozenset(v) for k, v in kw.items()}


# --------------------------------------------------------------------- karar kümeleri

# `reopen` ("Taslağa al"): onaylı/reddedilmiş case'i taslağa döndüren kayıtlı karar. Onaylayan
# değildir; son karar olduğu için eski bir `approve` kapıyı yeniden açamaz (Constitution I).
TEST_CASE_KARARLARI = frozenset({"approve", "edit", "reject", "reopen"})
DESIGN_MODEL_KARARLARI = frozenset({"approve", "edit", "reject"})
REQUIREMENT_KARARLARI = frozenset({"po_approve"})
BUG_DRAFT_KARARLARI = frozenset({"new", "link", "dismiss"})
SCRIPT_KARARLARI = frozenset({"merge", "request_changes"})
FINDING_KARARLARI = frozenset({"fix_doc", "code_defect", "accept_difference"})

# Onaylayan (kapıyı açan) kararlar; yayın/PR/bug kapıları bunlardan birini ister.
APPROVING: dict[str, frozenset[str]] = {
    "test_case": frozenset({"approve", "edit"}),
    "design_model": frozenset({"approve", "edit"}),
    "requirement": REQUIREMENT_KARARLARI,
    "bug_draft": frozenset({"new", "link"}),
    "script": frozenset({"merge"}),
    "consistency_finding": FINDING_KARARLARI,
}

KARARLAR: dict[str, frozenset[str]] = {
    "test_case": TEST_CASE_KARARLARI,
    "design_model": DESIGN_MODEL_KARARLARI,
    "requirement": REQUIREMENT_KARARLARI,
    "bug_draft": BUG_DRAFT_KARARLARI,
    "script": SCRIPT_KARARLARI,
    "consistency_finding": FINDING_KARARLARI,
}

# Karar verebilecek roller (API rol kontrolüne ek, derinlemesine savunma).
APPROVER_ROLES: dict[str, frozenset[str]] = {
    "test_case": frozenset({"analyst"}),
    "design_model": frozenset({"analyst"}),
    "requirement": frozenset({"po"}),
    "bug_draft": frozenset({"tester"}),
    "script": frozenset({"engineer"}),
    "consistency_finding": frozenset({"analyst"}),
}

# Ret nedeni taksonomisi (TEKNIK-TASARIM §7): halüsinasyon adımı · eksik kabul kriteri ·
# yanlış test verisi · kapsam dışı · tekrar · yanlış eleman/aksiyon.
RET_NEDENLERI = frozenset(
    {
        "hallucinated_step",
        "missing_ac",
        "wrong_test_data",
        "out_of_scope",
        "duplicate",
        "wrong_element",
    }
)


def _gerekce_var(f: Any) -> bool:
    karar = getattr(f, "analist_karari", None)
    if karar not in FINDING_KARARLARI:
        return False
    return karar != "accept_difference" or bool((getattr(f, "gerekce", None) or "").strip())


REQUIREMENT = Machine(
    entity="requirement",
    initial="new",
    transitions=_t(
        new=("in_review", "failed"),
        in_review=("findings_open", "doc_final", "failed"),
        findings_open=("in_review", "doc_final", "new"),
        doc_final=("pending_po", "in_review", "new"),
        pending_po=("po_approved", "in_review", "new"),
        po_approved=("generating", "modeling", "new"),
        modeling=("model_ready", "failed"),
        model_ready=("generating", "modeling", "new"),
        generating=("cases_ready", "failed"),
        cases_ready=("generating", "modeling", "done", "new"),
        done=("new",),
        failed=("in_review", "generating", "modeling", "new"),
    ),
    gates={
        ("pending_po", "po_approved"): Gate(REQUIREMENT_KARARLARI),
        # Case üretimi ve tasarım modeli yalnızca PO'nun onayladığı içerikten (Constitution I).
        ("po_approved", "generating"): Gate(REQUIREMENT_KARARLARI),
        ("cases_ready", "generating"): Gate(REQUIREMENT_KARARLARI),
        ("failed", "generating"): Gate(REQUIREMENT_KARARLARI),
        ("model_ready", "generating"): Gate(REQUIREMENT_KARARLARI),
        ("po_approved", "modeling"): Gate(REQUIREMENT_KARARLARI),
        ("cases_ready", "modeling"): Gate(REQUIREMENT_KARARLARI),
        ("failed", "modeling"): Gate(REQUIREMENT_KARARLARI),
        ("model_ready", "modeling"): Gate(REQUIREMENT_KARARLARI),
    },
    approval_targets=frozenset({"po_approved"}),
    approval_consumers=frozenset({"generating", "modeling"}),
    guards={
        ("po_approved", "generating"): Guard(
            "kabul kriteri eksik (ac_missing) gereksinim case üretimine gönderilmez",
            lambda r: not getattr(r, "ac_missing", False),
        ),
        ("po_approved", "modeling"): Guard(
            "kabul kriteri eksik (ac_missing) gereksinim tasarım modeline gönderilmez",
            lambda r: not getattr(r, "ac_missing", False),
        ),
    },
)

REQUIREMENT_REVIEW = Machine(
    entity="requirement_review",
    initial="pending_po",
    transitions=_t(pending_po=("approved", "superseded"), approved=("superseded",), superseded=()),
)

CONSISTENCY_FINDING = Machine(
    entity="consistency_finding",
    initial="unverified",
    transitions=_t(
        unverified=("open", "discarded"),
        open=("decided", "stale"),
        decided=("resolved", "open", "stale"),
        resolved=(),
        stale=(),
        discarded=(),
    ),
    gates={("open", "decided"): Gate(FINDING_KARARLARI)},
    guards={
        ("open", "decided"): Guard(
            "analist kararı gerekli; 'accept_difference' gerekçe ister", _gerekce_var
        ),
        ("unverified", "open"): Guard(
            "kanıtı doğrulanmamış bulgu gösterilmez",
            lambda f: bool(getattr(f, "kanit_dogrulandi", False)),
        ),
    },
)

TEST_CASE = Machine(
    entity="test_case",
    initial="draft",
    transitions=_t(
        draft=("approved", "rejected", "superseded"),
        approved=("published", "draft", "superseded"),
        rejected=("draft", "superseded"),
        published=(),
        superseded=(),
    ),
    gates={
        ("draft", "approved"): Gate(APPROVING["test_case"]),
        ("draft", "rejected"): Gate(frozenset({"reject"})),
        ("approved", "published"): Gate(APPROVING["test_case"]),
    },
    approval_targets=frozenset({"approved"}),
    approval_consumers=frozenset({"published"}),
)

DESIGN_MODEL = Machine(
    entity="design_model",
    initial="draft",
    transitions=_t(
        draft=("approved", "rejected", "superseded"),
        approved=("superseded",),
        rejected=("superseded",),
        superseded=(),
    ),
    gates={
        ("draft", "approved"): Gate(APPROVING["design_model"]),
        ("draft", "rejected"): Gate(frozenset({"reject"})),
    },
    approval_targets=frozenset({"approved"}),
)

SCRIPT = Machine(
    entity="script",
    initial="pending",
    transitions=_t(
        pending=("verifying", "failed"),
        verifying=("checking", "blocked", "failed"),
        checking=("verifying", "pr_open", "blocked", "failed"),
        pr_open=("merged", "checking", "closed"),
        blocked=("verifying", "closed"),
        failed=("pending", "closed"),
        merged=(),
        closed=(),
    ),
    gates={("pr_open", "merged"): Gate(APPROVING["script"])},
    approval_targets=frozenset({"merged"}),
)

BUG_DRAFT = Machine(
    entity="bug_draft",
    initial="draft",
    transitions=_t(
        draft=("approved", "dismissed"),
        approved=("published", "draft"),
        dismissed=("draft",),
        published=(),
    ),
    gates={
        ("draft", "approved"): Gate(APPROVING["bug_draft"]),
        ("draft", "dismissed"): Gate(frozenset({"dismiss"})),
        ("approved", "published"): Gate(APPROVING["bug_draft"]),
    },
    approval_targets=frozenset({"approved"}),
    approval_consumers=frozenset({"published"}),
)

WORKFLOW_INSTANCE = Machine(
    entity="workflow_instance",
    initial="running",
    transitions=_t(
        running=("waiting_human", "done", "failed", "paused", "cancelled"),
        waiting_human=("running", "cancelled"),
        paused=("running", "cancelled"),
        failed=("running", "cancelled"),
        done=(),
        cancelled=(),
    ),
)

MACHINES: dict[str, Machine] = {
    m.entity: m
    for m in (
        REQUIREMENT,
        REQUIREMENT_REVIEW,
        CONSISTENCY_FINDING,
        TEST_CASE,
        DESIGN_MODEL,
        SCRIPT,
        BUG_DRAFT,
        WORKFLOW_INSTANCE,
    )
}

# Durum makinesi adı tablo adından farklı olan varlıklar (`review.nesne_turu` = makine adı).
# `tasarim_modeli` tablosu `design_model` makinesidir (specs/011 §4.3).
ENTITY_BY_TABLE: dict[str, str] = {"tasarim_modeli": "design_model"}

# Kararın kendisiyle birlikte değiştirebileceği alanlar (`record_approval(degisiklik=...)`).
# İnsanın gördüğü içerik hash'i değişiklik UYGULANMADAN önce, onaylanan hash SONRA hesaplanır.
# consistency_finding'de `analist_karari`/`gerekce` kararın kendisinden yazılır (değişiklik değil).
DECISION_EDITS: dict[str, dict[str, frozenset[str]]] = {
    "test_case": {"edit": frozenset({"icerik"})},
    "design_model": {"edit": frozenset({"icerik"})},
    "bug_draft": {"new": frozenset({"icerik"}), "link": frozenset({"icerik"})},
    "consistency_finding": {"fix_doc": frozenset({"onerilen_metin"})},
}
# Bu kararlarda değişiklik zorunludur (ör. 'edit' içeriği değiştirmeden verilemez).
DECISION_EDIT_REQUIRED: dict[str, frozenset[str]] = {
    "test_case": frozenset({"edit"}),
    "design_model": frozenset({"edit"}),
}

# İçerik hash'ine giren alanlar (kanonik JSON). Onay ve yayın kapıları bunu karşılaştırır.
CONTENT_FIELDS: dict[str, tuple[str, ...]] = {
    "test_case": ("icerik",),
    "design_model": ("icerik",),
    "bug_draft": ("icerik",),
    "script": ("dosya_yolu", "icerik", "head_sha"),
    "requirement": ("baslik", "aciklama", "kabul_kriterleri"),
    "consistency_finding": (
        "tur",
        "doc_ref",
        "kanitlar",
        "onerilen_metin",
        "analist_karari",
        "gerekce",
    ),
}
