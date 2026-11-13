"""Öneri motoru testleri için tohum verisi (AI-ASISTAN-PLANI §13 "Öneri (§17)").

Varlıklar doğrudan istenen durumda kurulur (`allow_state_write`): öneri motoru durum yazmaz, yalnız
okur. `VAKALAR` her kural için bir olumlu ve bir olumsuz kurulum verir; kurulum `(rota, varlik_tur,
varlik_id, simdi)` döndürür. Yeni kural eklenince buraya vakası eklenmezse test düşer.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tp_core.audit.session import audit_on_commit
from tp_core.models import (
    AiCall,
    BugDraft,
    ConsistencyFinding,
    Failure,
    Requirement,
    RequirementReview,
    Run,
    Script,
    TestCase,
    TestResult,
)
from tp_core.models.bugs_feature import BugDraftEk
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.guard import allow_state_write

SAAT = timedelta(hours=1)


@dataclass(frozen=True)
class Ekran:
    rota: str
    varlik_tur: str | None
    varlik_id: uuid.UUID | None
    simdi: datetime


class Tohum:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sayac = 0

    def _ekle(self, *nesneler: Any) -> None:
        with Session(self.engine, expire_on_commit=False) as s, s.begin(), allow_state_write():
            for n in nesneler:
                s.add(n)
                s.flush()

    def _anahtar(self) -> str:
        self._sayac += 1
        return f"TPD-{900 + self._sayac}"

    # -------------------------------------------------------------- gereksinim ailesi

    def gereksinim(
        self,
        durum: str = "in_review",
        *,
        kaynak: str = "jira",
        jira_key: str | bool | None = True,
        ac_missing: bool = False,
        po_bekleme: int | None = None,
    ) -> uuid.UUID:
        anahtar = self._anahtar() if jira_key is True else (jira_key or None)
        req = Requirement(
            kaynak=kaynak,
            jira_key=anahtar,
            baslik="Kampanya {jira_key} {{x}} başlığı",  # serbest metin yer tutucuya girmez
            kaynak_hash="h",
            durum=durum,
            ac_missing=ac_missing,
            kontrol_turu=1,
        )
        self._ekle(req)
        if po_bekleme is not None:  # PO incelemesi `po_bekleme` saat önce açıldı
            inceleme = RequirementReview(
                requirement_id=req.id, verdict="needs_po", durum="pending_po"
            )
            inceleme.olusturma = datetime.now(UTC) - po_bekleme * SAAT
            self._ekle(inceleme)
        return req.id

    def pending_po_denetimi(self, req_id: uuid.UUID) -> None:
        """`requirement.transition` → `pending_po` denetim kaydı (zaman = şimdi)."""
        with Session(self.engine) as s, s.begin():
            audit_on_commit(
                s,
                "analist",
                "requirement.transition",
                f"requirement:{req_id}",
                {"from": "doc_final", "to": "pending_po"},
            )

    def bulgu(self, req_id: uuid.UUID, durum: str = "open", kanit: bool = True) -> uuid.UUID:
        f = ConsistencyFinding(
            requirement_id=req_id,
            tur="doc_vs_code",
            doc_ref="AC1",
            severity="blocking",
            durum=durum,
            kanit_dogrulandi=kanit,
        )
        self._ekle(f)
        return f.id

    def case(self, req_id: uuid.UUID, durum: str = "draft") -> uuid.UUID:
        self._sayac += 1
        tc = TestCase(
            id=uuid.uuid4(),
            requirement_id=req_id,
            sira_no=self._sayac,
            icerik={"title": "t"},
            icerik_hash=f"h{self._sayac}",
            durum=durum,
        )
        self._ekle(tc)
        return tc.id

    # -------------------------------------------------------------- script / koşu / hata

    def script(
        self,
        durum: str = "pr_open",
        break_durum: str | None = "not_started",
        *,
        engel_turu: str | None = None,
        yerel_kontrol: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        sc = Script(dosya_yolu=f"e2e/t{uuid.uuid4().hex[:6]}.spec.ts", durum=durum)
        self._ekle(sc)
        if break_durum is not None:
            req = self.gereksinim("cases_ready")
            tc = self.case(req, "published")
            self._ekle(
                ScriptCodegen(
                    script_id=sc.id,
                    test_case_id=tc,
                    requirement_id=req,
                    case_hash="h",
                    sira_no=1,
                    break_durum=break_durum,
                    engel_turu=engel_turu,
                    yerel_kontrol=yerel_kontrol,
                )
            )
        return sc.id

    def kosu(
        self,
        sonuc: str = "passed",
        *,
        tetik: str = "pr",
        bitis: datetime | None = None,
        olusturma: datetime | None = None,
    ) -> uuid.UUID:
        r = Run(tetik=tetik, sonuc=sonuc, bitis=bitis)
        if olusturma is not None:
            r.olusturma = olusturma
        self._ekle(r)
        return r.id

    def sonuc(self, run_id: uuid.UUID, test_adi: str, sonuc: str) -> None:
        self._ekle(TestResult(run_id=run_id, test_adi=test_adi, sonuc=sonuc, tetik="pr"))

    def hata(
        self,
        sinif: str,
        *,
        oneri_durumu: str = "none",
        run_id: uuid.UUID | None = None,
        test_adi: str = "kampanya testi",
        alt_tur: str | None = None,
    ) -> uuid.UUID:
        f = Failure(
            run_id=run_id or self.kosu("failed"),
            test_adi=test_adi,
            hata_imzasi="imza",
            sinif=sinif,
            alt_tur=alt_tur,
            oneri_durumu=oneri_durumu,
        )
        self._ekle(f)
        return f.id

    def bug_taslagi(
        self,
        durum: str = "draft",
        *,
        failure_id: uuid.UUID | None = None,
        finding_id: uuid.UUID | None = None,
        ilgili: list[uuid.UUID] | None = None,
        jira_key: str | None = None,
    ) -> uuid.UUID:
        b = BugDraft(
            failure_id=failure_id,
            finding_id=finding_id,
            icerik={"baslik": "b"},
            icerik_hash="h",
            durum=durum,
            jira_key=jira_key,
        )
        self._ekle(b)
        if ilgili is not None:
            self._ekle(
                BugDraftEk(
                    bug_draft_id=b.id,
                    kaynak="failure",
                    ilgili_failure_ids=[str(i) for i in ilgili],
                )
            )
        return b.id

    def harcama(self, usd: str, an: datetime | None = None) -> None:
        # `an`: değerlendirme anıyla aynı UTC günü (gece yarısı sınırında DB `now()` kayabilir).
        self._ekle(
            AiCall(
                amac="triage",
                saglayici="anthropic",
                model="m",
                mod="live",
                maliyet=Decimal(usd),
                **({"olusturma": an} if an is not None else {}),
            )
        )


# ------------------------------------------------------------------ kural başına vakalar

Kurulum = Callable[[Tohum, datetime], Ekran]


def _gd(req: uuid.UUID, simdi: datetime) -> Ekran:
    return Ekran(f"/gereksinimler/{req}", "requirement", req, simdi)


def _ci(req: uuid.UUID, simdi: datetime) -> Ekran:
    return Ekran(f"/gereksinimler/{req}/caseler", "requirement", req, simdi)


def _bulgu_olumlu(t: Tohum, n: datetime) -> Ekran:
    req = t.gereksinim("findings_open")
    t.bulgu(req)
    t.bulgu(req)
    return _gd(req, n)


def _bulgu_olumsuz(t: Tohum, n: datetime) -> Ekran:
    req = t.gereksinim("findings_open")
    t.bulgu(req, durum="decided")  # kararlı bulgu sayılmaz
    return _gd(req, n)


def _case_hazir_olumlu(t: Tohum, n: datetime) -> Ekran:
    req = t.gereksinim("cases_ready")
    t.case(req, "approved")
    t.case(req, "superseded")
    return _ci(req, n)


def _case_hazir_olumsuz(t: Tohum, n: datetime) -> Ekran:
    req = t.gereksinim("cases_ready")
    t.case(req, "approved")
    t.case(req, "draft")
    return _ci(req, n)


def _case_bekliyor(t: Tohum, n: datetime) -> Ekran:
    req = t.gereksinim("cases_ready")
    t.case(req, "draft")
    return _ci(req, n)


def _case_son_onayda(t: Tohum, n: datetime) -> Ekran:
    """Testçi kabul etti (`ready`); Analist'in son onayını bekler."""
    req = t.gereksinim("cases_ready")
    t.case(req, "ready")
    t.case(req, "approved")
    return _ci(req, n)


def _case_bitti(t: Tohum, n: datetime) -> Ekran:
    req = t.gereksinim("cases_ready")
    t.case(req, "approved")
    t.case(req, "rejected")
    return _ci(req, n)


def _script(durum: str, brk: str | None, **kw: Any) -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        sid = t.script(durum, brk, **kw)
        return Ekran(f"/kod/{sid}", "script", sid, n)

    return _k


def _kosu(sonuc: str) -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        rid = t.kosu(sonuc)
        return Ekran(f"/kosular/{rid}", "run", rid, n)

    return _k


def _hata(sinif: str, **kw: Any) -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        fid = t.hata(sinif, **kw)
        return Ekran(f"/hatalar/{fid}", "failure", fid, n)

    return _k


def _hata_bug(durum: str | None, *, kardes: bool = False) -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        fid = t.hata("product_defect")
        if durum is not None:
            if kardes:  # kardeş hata listesinden bağlı taslak
                t.bug_taslagi(durum, failure_id=t.hata("product_defect"), ilgili=[fid])
            else:
                t.bug_taslagi(durum, failure_id=fid)
        return Ekran(f"/hatalar/{fid}", "failure", fid, n)

    return _k


def _flaky(n_flaky: int) -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        ad = f"kararsız test {uuid.uuid4().hex[:6]}"
        baz = n - timedelta(days=30)
        # 12 koşu: en eski ikisi flaky (pencere dışında kalır), son 10'un `n_flaky`'si flaky.
        for i in range(12):
            rid = t.kosu("failed", olusturma=baz + timedelta(hours=i))
            flaky = i < 2 or (i >= 2 and i - 2 < n_flaky)
            t.sonuc(rid, ad, "flaky" if flaky else "passed")
        fid = t.hata("flaky", test_adi=ad, run_id=t.kosu("failed", olusturma=baz - SAAT))
        return Ekran(f"/hatalar/{fid}", "failure", fid, n)

    return _k


def _bug(durum: str, *, bulgu: bool = False) -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        finding = t.bulgu(t.gereksinim("findings_open"), durum="decided") if bulgu else None
        bid = t.bug_taslagi(durum, finding_id=finding)
        return Ekran(f"/bug-taslaklari/{bid}", "bug_draft", bid, n)

    return _k


def _butce(usd: str, *, gun_sonra: int = 0) -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        t.harcama(usd, n)  # TP_DAILY_BUDGET_USD=10 (test fikstürü)
        # Harcama gün başına sayılır (UTC): olumsuz vaka sonraki günü ölçer.
        return Ekran("/kontrol-kulesi", None, None, n + timedelta(days=gun_sonra))

    return _k


def _son_kosu(saat_once: int, tetik: str = "pr") -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        t.kosu("passed", tetik=tetik, bitis=datetime.now(UTC))
        # simdi'yi ileri alarak "N saat önce bitti" kurulur (DB saatine dokunmadan).
        return Ekran("/kosular", None, None, datetime.now(UTC) + saat_once * SAAT)

    return _k


def _po(kaynak: str, saat: int, *, jira: bool = True, durum: str = "pending_po") -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        bekleme = saat if durum == "pending_po" else None
        req = t.gereksinim(durum, kaynak=kaynak, jira_key=jira, po_bekleme=bekleme)
        return _gd(req, n)

    return _k


def _gereksinim(durum: str, **kw: Any) -> Kurulum:
    def _k(t: Tohum, n: datetime) -> Ekran:
        return _gd(t.gereksinim(durum, **kw), n)

    return _k


# kural_id → (rol, olumlu kurulum, olumsuz kurulum)
VAKALAR: dict[str, tuple[str, Kurulum, Kurulum]] = {
    "gereksinim-bulgu-karari": ("analyst", _bulgu_olumlu, _bulgu_olumsuz),
    "gereksinim-ac-eksik-jira": (
        "analyst",
        _gereksinim("new", ac_missing=True),
        _gereksinim("new", ac_missing=True, kaynak="free_text", jira_key=None),
    ),
    "gereksinim-ac-eksik": (
        "analyst",
        _gereksinim("new", ac_missing=True, kaynak="free_text", jira_key=None),
        _gereksinim("new", ac_missing=False, kaynak="free_text", jira_key=None),
    ),
    "gereksinim-po-hatirlatma-jira": ("analyst", _po("jira", 30), _po("jira", 5)),
    "gereksinim-po-bekliyor-portal": (
        "analyst",
        _po("free_text", 49, jira=False),
        _po("jira", 49),
    ),
    "gereksinim-po-onayi-portal": ("po", _po("free_text", 1, jira=False), _po("jira", 1)),
    "gereksinim-po-onayi-jira": (
        "po",
        _po("jira", 1),
        _po("jira", 1, durum="doc_final"),
    ),
    "gereksinim-case-uret": (
        "tester",
        _gereksinim("po_approved"),
        _gereksinim("po_approved", ac_missing=True),
    ),
    "gereksinim-basarisiz": ("analyst", _gereksinim("failed"), _gereksinim("done")),
    "case-inceleme-bekliyor": ("tester", _case_bekliyor, _case_bitti),
    "case-son-onay-bekliyor": ("analyst", _case_son_onayda, _case_bitti),
    "case-yayina-hazir": ("tester", _case_hazir_olumlu, _case_son_onayda),
    "case-inceleme-analistte": ("tester", _case_son_onayda, _case_bitti),
    "script-kirarak-dogrula": (
        "engineer",
        _script("pr_open", "weak"),
        _script("pr_open", "running"),
    ),
    "script-merge-karari": (
        "engineer",
        _script("pr_open", "passed"),
        _script("merged", "passed"),
    ),
    "script-insana-dustu": (
        "engineer",
        _script("blocked", "not_started", engel_turu="locator"),
        # Defect adayında yeniden üretim önerilmez (karar triage'da; Kod.tsx ile aynı).
        _script("blocked", "not_started", engel_turu="defect_candidate"),
    ),
    # 011 (MİM-L8): doğrulanmamış dil (C#/Python) — yalnız bilgi; PR/merge önerilmez.
    "script-dogrulanmamis": (
        "engineer",
        _script("unverified", None),
        _script("closed", None),
    ),
    "kosu-ortam-hatasi-task": ("engineer", _kosu("error"), _kosu("failed")),
    "kosu-ortam-hatasi-bilgi": ("admin", _kosu("error"), _kosu("passed")),
    "hata-bakim-onarim": (
        "engineer",
        _hata("test_maintenance", alt_tur="locator"),
        # 012 §4.4: beklenti farkında otomatik locator onarımı önerilmez.
        _hata("test_maintenance", alt_tur="beklenti"),
    ),
    "hata-beklenti-case-duzelt": (
        "tester",  # 012 rol modeli: case düzeltmesi Testçide
        _hata("test_maintenance", alt_tur="beklenti"),
        _hata("test_maintenance", alt_tur="locator"),
    ),
    "hata-beklenti-bilgi": (
        "engineer",
        _hata("test_maintenance", alt_tur="beklenti"),
        _hata("product_defect"),
    ),
    "hata-bug-taslagi-karari": (
        "tester",
        _hata_bug("draft", kardes=True),
        _hata_bug("published"),
    ),
    "hata-flaky-task": ("engineer", _flaky(3), _flaky(2)),
    "hata-test-verisi-task": ("tester", _hata("test_data"), _hata("environment")),
    "hata-test-verisi-bilgi": ("engineer", _hata("test_data"), _hata("unknown")),
    "bug-taslagi-karari": ("tester", _bug("draft"), _bug("dismissed")),
    "bug-taslagi-bulgudan": ("analyst", _bug("draft", bulgu=True), _bug("draft")),
    "butce-uyarisi": ("admin", _butce("8.5"), _butce("7.9", gun_sonra=2)),
    "guncel-kosu-yok": ("engineer", _son_kosu(30), _son_kosu(3)),
}
