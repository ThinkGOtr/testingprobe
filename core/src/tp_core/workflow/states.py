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
    po_approved    -> generating [KAPI: PO onayı hâlâ güncel içerikte; koşul: ac_missing değil], new
    generating     -> cases_ready, failed
    cases_ready    -> generating [KAPI: PO onayı hâlâ güncel], done, new
    done           -> new                                       (kaynak değişti → yeniden)
    failed         -> in_review, generating [KAPI: PO onayı hâlâ güncel], new

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

test_case (başlangıç ``draft``; specs/012-rol-yetki/ANALIZ.md §5)::

    draft      -> ready [KAPI: accept | edit], rejected [KAPI: reject], superseded   (Testçi)
    ready      -> approved [KAPI: approve] (Analist son onayı), draft (send_back | reopen),
                  superseded
    approved   -> published [KAPI: approve; onaylı hash hâlâ güncel], draft (reopen), superseded
    rejected   -> draft (reopen), superseded
    published, superseded: son durum

    Eski kayıtlar: 012 öncesinde `draft → approved` doğrudan (analist `approve`/`edit`) idi;
    `approved` case'ler olduğu gibi kalır, eski `approve` kaydı yayın kapısını açmaya devam eder.

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

# Case kararları (ANALIZ §5). Testçi: `accept` (olduğu gibi kabul) ve `edit` (düzelterek kabul)
# case'i `ready` yapar, `reject` reddeder, `reopen` ("Taslağa al") hazır/onaylı/reddedilmiş case'i
# taslağa döndürür. Analist (son onay): `approve` ready → approved, `send_back` ready → draft
# (gerekçe zorunlu). `reopen`/`send_back` onaylayan değildir; son karar oldukları için eski bir
# `approve` kapıyı yeniden açamaz (Constitution I).
TEST_CASE_TESTCI_KARARLARI = frozenset({"accept", "edit", "reject", "reopen"})
TEST_CASE_SON_ONAY_KARARLARI = frozenset({"approve", "send_back"})
TEST_CASE_KARARLARI = TEST_CASE_TESTCI_KARARLARI | TEST_CASE_SON_ONAY_KARARLARI
# Case'i `ready` yapan (Testçi kabulü) kararlar.
TEST_CASE_KABUL = frozenset({"accept", "edit"})
# Kararın gerektirdiği izin (auth/yetki.py kataloğu; rol kümesi oradan türetilir).
TEST_CASE_KARAR_IZNI: dict[str, str] = {
    **dict.fromkeys(TEST_CASE_TESTCI_KARARLARI, "case.decide"),
    **dict.fromkeys(TEST_CASE_SON_ONAY_KARARLARI, "case.approve"),
}
REQUIREMENT_KARARLARI = frozenset({"po_approve"})
BUG_DRAFT_KARARLARI = frozenset({"new", "link", "dismiss"})
SCRIPT_KARARLARI = frozenset({"merge", "request_changes"})
FINDING_KARARLARI = frozenset({"fix_doc", "code_defect", "accept_difference"})

# Onaylayan (kapıyı açan) kararlar; yayın/PR/bug kapıları bunlardan birini ister.
APPROVING: dict[str, frozenset[str]] = {
    # Yalnız Analist'in son onayı yayını açar (012; önceden `edit` de sayılıyordu).
    "test_case": frozenset({"approve"}),
    "requirement": REQUIREMENT_KARARLARI,
    "bug_draft": frozenset({"new", "link"}),
    "script": frozenset({"merge"}),
    "consistency_finding": FINDING_KARARLARI,
}

KARARLAR: dict[str, frozenset[str]] = {
    "test_case": TEST_CASE_KARARLARI,
    "requirement": REQUIREMENT_KARARLARI,
    "bug_draft": BUG_DRAFT_KARARLARI,
    "script": SCRIPT_KARARLARI,
    "consistency_finding": FINDING_KARARLARI,
}

# Karar verebilecek roller (API izin kontrolüne ek, derinlemesine savunma). Bu modül saf veri
# olduğu için kümeler burada yazılıdır; auth/yetki.py kataloğuyla eşitliği test edilir
# (test_canonical_and_states). test_case'te karar başına izin `TEST_CASE_KARAR_IZNI`'dedir:
# `record_approval` kararın kendi iznini ister (Testçi `approve` veremez, Analist `accept`
# veremez); buradaki küme o iki iznin birleşimidir (kuyruk/asistan gibi tür düzeyi okuyucular).
APPROVER_ROLES: dict[str, frozenset[str]] = {
    "test_case": frozenset({"tester", "analyst"}),
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
        po_approved=("generating", "new"),
        generating=("cases_ready", "failed"),
        cases_ready=("generating", "done", "new"),
        done=("new",),
        failed=("in_review", "generating", "new"),
    ),
    gates={
        ("pending_po", "po_approved"): Gate(REQUIREMENT_KARARLARI),
        # Case üretimi yalnızca PO'nun onayladığı içerikten (Constitution I).
        ("po_approved", "generating"): Gate(REQUIREMENT_KARARLARI),
        ("cases_ready", "generating"): Gate(REQUIREMENT_KARARLARI),
        ("failed", "generating"): Gate(REQUIREMENT_KARARLARI),
    },
    approval_targets=frozenset({"po_approved"}),
    approval_consumers=frozenset({"generating"}),
    guards={
        ("po_approved", "generating"): Guard(
            "kabul kriteri eksik (ac_missing) gereksinim case üretimine gönderilmez",
            lambda r: not getattr(r, "ac_missing", False),
        )
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
        draft=("ready", "rejected", "superseded"),
        ready=("approved", "draft", "superseded"),
        approved=("published", "draft", "superseded"),
        rejected=("draft", "superseded"),
        published=(),
        superseded=(),
    ),
    gates={
        ("draft", "ready"): Gate(TEST_CASE_KABUL),
        ("draft", "rejected"): Gate(frozenset({"reject"})),
        ("ready", "approved"): Gate(APPROVING["test_case"]),
        ("approved", "published"): Gate(APPROVING["test_case"]),
    },
    approval_targets=frozenset({"approved"}),
    approval_consumers=frozenset({"published"}),
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
        SCRIPT,
        BUG_DRAFT,
        WORKFLOW_INSTANCE,
    )
}

# Kararın kendisiyle birlikte değiştirebileceği alanlar (`record_approval(degisiklik=...)`).
# İnsanın gördüğü içerik hash'i değişiklik UYGULANMADAN önce, onaylanan hash SONRA hesaplanır.
# consistency_finding'de `analist_karari`/`gerekce` kararın kendisinden yazılır (değişiklik değil).
DECISION_EDITS: dict[str, dict[str, frozenset[str]]] = {
    "test_case": {"edit": frozenset({"icerik"})},
    "bug_draft": {"new": frozenset({"icerik"}), "link": frozenset({"icerik"})},
    "consistency_finding": {"fix_doc": frozenset({"onerilen_metin"})},
}
# Bu kararlarda değişiklik zorunludur (ör. 'edit' içeriği değiştirmeden verilemez).
DECISION_EDIT_REQUIRED: dict[str, frozenset[str]] = {"test_case": frozenset({"edit"})}
# Bu kararlar boş olmayan gerekçe ister.
DECISION_GEREKCE_REQUIRED: dict[str, frozenset[str]] = {
    "test_case": frozenset({"send_back"}),
    "consistency_finding": frozenset({"accept_difference"}),
}

# İçerik hash'ine giren alanlar (kanonik JSON). Onay ve yayın kapıları bunu karşılaştırır.
CONTENT_FIELDS: dict[str, tuple[str, ...]] = {
    "test_case": ("icerik",),
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
