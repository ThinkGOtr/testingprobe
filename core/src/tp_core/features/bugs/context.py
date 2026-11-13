"""Bug taslağının bağlamı: başarısızlık (triage) ya da tutarlılık bulgusu → hata imzası.

Bağlam yalnızca Postgres'teki kayıtlardan deterministik olarak toplanır: `failure` + triage ek
kaydı (`failure_ek`: kanıt özeti, kanıt bağlantıları, kırılma bayrağı), `test_result`
(+ `test_result_ek` ekleri), `run` (kırılma bayrağı, sağlık, artefaktlar), kod üretiminin yerel
kontrol özeti (`script_kontrol.ozet.basarisiz`), onaylı case, gereksinim (story, AC metinleri) ve
yayınlanmış Test issue anahtarı (`external_ref`). Hata metinleri test kodunun çıktısıdır
(güvenilmez): modele yalnızca `tp_core.gateway.defects` kurucularıyla, `<untrusted>` blokta gider.

Kanıt bağlantıları yalnızca koşunun kendi artefaktlarından üretilir; modele yalnızca adları
(`kanit:trace` …) gider, gerçek bağlantıyı `resolve_evidence` koyar (model URL uyduramaz).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.features.bugs import jql
from tp_core.models import (
    ConsistencyFinding,
    ExternalRef,
    Failure,
    Requirement,
    Run,
    TestCase,
    TestResult,
)
from tp_core.models.ci_feature import TestResultEk
from tp_core.models.codegen_feature import ScriptCodegen, ScriptKontrol
from tp_core.models.requirements_feature import ConsistencyFindingEk

MAX_METIN = 600
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_EXPECTED = re.compile(r"^\s*Expected(?: string| value| pattern)?:\s*(?P<v>.+)$", re.I | re.M)
_RECEIVED = re.compile(r"^\s*Received(?: string| value)?:\s*(?P<v>.+)$", re.I | re.M)
_LOCATOR = re.compile(r"^\s*Locator:\s*(?P<v>.+)$", re.I | re.M)
_MATCHER = re.compile(r"expect\([^)]*\)\.(?:not\.)?(?P<v>to\w+)", re.I)
_AC = re.compile(r"\bAC\s*(\d+)\b", re.I)
_PAGE_CLASS = re.compile(r"\b([A-Z][A-Za-z]+Page)\b")

# Kanıt adı (gateway.defects.EVIDENCE_NAMES) ← ek dosyası adı / triage bağlantı türü.
EK_ADI = {
    "trace": "trace",
    "screenshot": "screenshot",
    "video": "video",
    "error-context": "error_context",
    "error_context": "error_context",
}


def temiz(metin: Any, limit: int = MAX_METIN) -> str | None:
    if metin is None:
        return None
    s = _ANSI.sub("", str(metin)).strip()
    if not s:
        return None
    return s if len(s) <= limit else s[:limit] + "…"


def literal(metin: str | None) -> str | None:
    """Playwright `"0"` değerinden literal (tırnaksız) değer."""
    if metin is None:
        return None
    v = metin.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'`":
        v = v[1:-1]
    return v or None


@dataclass
class BugContext:
    """Taslak ve mükerrer araması için toplanan bağlam (deterministik)."""

    kaynak: str  # failure | finding
    failure_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None
    requirement_id: uuid.UUID | None = None
    story_key: str | None = None
    story_baslik: str | None = None
    test_case_id: uuid.UUID | None = None
    test_case_key: str | None = None
    case_ref: str | None = None
    case_icerik: dict[str, Any] | None = None
    case_baslik: str | None = None
    case_adimlar: list[dict[str, Any]] = field(default_factory=list)
    case_beklenen: str | None = None
    ac_refs: list[str] = field(default_factory=list)
    ac_metinleri: list[str] = field(default_factory=list)
    test_adi: str | None = None
    test_dosya: str | None = None
    hata_turu: str | None = None
    sinif: str | None = None
    hata_mesaji: str | None = None
    hata_imzasi: str | None = None
    # Ham (tırnaklı) beklenen/gerçekleşen modele; literal değerler taslak denetimine.
    beklenen: str | None = None
    gerceklesen: str | None = None
    adim: str | None = None
    sayfa: str | None = None
    run_id: uuid.UUID | None = None
    commit: str | None = None
    run_kaynak: str | None = None
    tetik: str | None = None
    kirma: bool = False
    saglik: dict[str, Any] | None = None
    ham_failure: dict[str, Any] = field(default_factory=dict)
    statuses: dict[str, int] | None = None
    consistent: bool | None = None
    kural_sinyalleri: list[str] = field(default_factory=list)
    # Kanıt adı → bağlantı (resolve_evidence) ve şemadaki kanıt listesi.
    baglantilar: dict[str, str] = field(default_factory=dict)
    kanitlar: list[dict[str, str]] = field(default_factory=list)
    # Tutarlılık bulgusu
    bulgu_turu: str | None = None
    bulgu_no: str | None = None
    doc_ref: str | None = None
    iddia: str | None = None
    gozlem: str | None = None
    belge_metni: str | None = None
    bulgu_kanitlari: list[dict[str, Any]] = field(default_factory=list)
    severity: str | None = None
    mevcut_icerik: dict[str, Any] | None = None
    # 013 K19: bilinen gizli test verisi değerleri. Model girdisi çözülmüş kalır (REPLAY); taslak
    # içeriği (kullanıcıya görünen, Jira'ya giden) `content` içinde bunlarla maskelenir.
    gizli_degerler: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ türetilenler
    @property
    def ac(self) -> str | None:
        for ref in [*self.ac_refs, self.doc_ref or ""]:
            m = _AC.search(ref or "")
            if m:
                return f"AC{m.group(1)}"
        return None

    @property
    def beklenen_deger(self) -> str | None:
        return literal(self.beklenen)

    @property
    def gerceklesen_deger(self) -> str | None:
        return literal(self.gerceklesen)

    def terms(self) -> list[str]:
        """Mükerrer araması terimleri: önce ayırt edici metinler (AC/bulgu, case başlığı)."""
        return jql.key_terms(
            gizliler=self.gizli_degerler,
            metinler=[
                *self.ac_metinleri,
                self.iddia,
                self.case_baslik,
                self.case_beklenen,
                self.adim,
                self.test_adi,
                self.belge_metni,
                self.gozlem,
            ],
        )

    def imza(self) -> dict[str, Any]:
        """Hata imzası (TEKNIK-TASARIM §8.12): test adı, hata türü, sayfa/AC, anahtar terimler.

        013 K19 (güvenlik #1): bilinen gizli değerler maskeli (taslak API'si ve denetim)."""
        from tp_core.features.testveri.atif import maskele_obje

        return maskele_obje(self._imza(), self.gizli_degerler)

    def _imza(self) -> dict[str, Any]:
        return {
            "kaynak": self.kaynak,
            "test_adi": self.test_adi,
            "test_dosya": self.test_dosya,
            "hata_turu": self.hata_turu or self.bulgu_turu,
            "sinif": self.sinif,
            "sayfa": self.sayfa,
            "ac": self.ac,
            "ac_refs": self.ac_refs,
            "story_key": self.story_key,
            "case_ref": self.case_ref,
            "test_case_key": self.test_case_key,
            "case_baslik": self.case_baslik,
            "locator": self.ham_failure.get("locator"),
            "beklenen": self.beklenen,
            "gerceklesen": self.gerceklesen,
            "hata_mesaji": self.hata_mesaji,
            "hata_imzasi": self.hata_imzasi,
            "doc_ref": self.doc_ref,
            "bulgu_no": self.bulgu_no,
            "kirma": self.kirma,
            "terimler": self.terms(),
        }

    def literal_values(self) -> list[str]:
        """Taslakta birebir geçmesi gereken gerçekleşen değerler (başarısızlıktan)."""
        return [v for v in (self.gerceklesen_deger,) if v]

    # --------------------------------------------------------- model girdisi (gateway)
    def sources(self) -> list[str]:
        """`gateway.defects` kanonik blokları: hata (+ onaylı case) ya da bulgu."""
        from tp_core.gateway import case_block, failure_block, finding_block

        if self.kaynak == "finding":
            return [
                finding_block(
                    story_key=self.story_key,
                    finding_type=self.bulgu_turu or "",
                    doc_ref=self.doc_ref or "",
                    doc_text=self.belge_metni,
                    claim=self.iddia,
                    observed=self.gozlem,
                    evidence=self.bulgu_kanitlari,
                )
            ]
        var = set((self.ham_failure.get("evidence") or {}).keys())
        out = [
            failure_block(
                self.ham_failure,
                test_title=self.test_adi or "",
                test_file=self.test_dosya,
                story_key=self.story_key,
                case_ref=self.case_ref,
                saglik=self.saglik,
                statuses=self.statuses,
                consistent=self.consistent,
                break_campaign=self.kirma,
                rule_signals=self.kural_sinyalleri,
                extra_evidence=[a for a in self.baglantilar if a not in var],
            )
        ]
        if self.case_icerik and self.case_ref:
            out.append(case_block(self.case_icerik, self.case_ref))
        return out

    def literal_refs(self) -> list[str]:
        from tp_core.gateway import literal_evidence_refs

        return literal_evidence_refs(self.bulgu_kanitlari)


# ---------------------------------------------------------------------- toplama


def _artifact_url(run_id: uuid.UUID, rel: Any) -> str | None:
    if not isinstance(rel, str) or not rel or ".." in rel.split("/"):
        return None
    return f"/api/artifacts/runs/{run_id}/{rel.lstrip('/')}"


def _evidence_links(
    run: Run, ek: TestResultEk | None, fek: Any | None
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """(kanıt adı → bağlantı, şema kanıt listesi). Yalnızca koşunun kendi artefaktları."""
    from tp_core.gateway.defects import EVIDENCE_KIND, EVIDENCE_NAMES

    a = run.artefaktlar or {}
    dizin = a.get("dizin") if isinstance(a.get("dizin"), str) else None
    linkler: dict[str, str] = {}
    for x in (getattr(fek, "kanit_linkleri", None) or []) if fek is not None else []:
        if isinstance(x, Mapping):
            ad = EK_ADI.get(str(x.get("tur") or ""), str(x.get("tur") or ""))
            url = _artifact_url(run.id, x.get("yol"))
            if ad in EVIDENCE_NAMES and url:
                linkler.setdefault(ad, url)
    if dizin:
        for e in (ek.ekler if ek else []) or []:
            if isinstance(e, Mapping):
                ad = EK_ADI.get(str(e.get("ad") or "").lower())
                url = _artifact_url(run.id, e.get("yol"))
                if ad and url:
                    linkler.setdefault(ad, url)
        allure = a.get("allure_html") or a.get("allure")
        url = _artifact_url(run.id, allure) if allure else None
        if url:
            linkler.setdefault("allure", url)
    elif isinstance(a.get("allure_url"), str):
        linkler.setdefault("allure", a["allure_url"])
    sauce = a.get("sauce") if isinstance(a.get("sauce"), Mapping) else {}
    video = (sauce or {}).get("video_url") or (sauce or {}).get("url")
    if isinstance(video, str) and video:
        linkler.setdefault("sauce_video", video)
    kanitlar = []
    for ad in EVIDENCE_NAMES:
        if ad in linkler:
            kanitlar.append({"kind": EVIDENCE_KIND[ad], "ref": linkler[ad]})
    log = _artifact_url(run.id, a.get("log")) if dizin else None
    if log:
        kanitlar.append({"kind": "log", "ref": log})
    return linkler, kanitlar[:10]


def _published_test_key(s: Session, tc_id: uuid.UUID) -> str | None:
    return s.scalar(
        select(ExternalRef.external_key)
        .where(
            ExternalRef.entity_turu == "test_case",
            ExternalRef.entity_id == tc_id,
            ExternalRef.durum == "created",
        )
        .order_by(ExternalRef.guncelleme.desc())
        .limit(1)
    )


def _check_row(s: Session, run: Run, test_adi: str | None) -> dict[str, Any] | None:
    """Kod üretiminin yerel kontrol özetindeki başarısız test satırı (beklenen/gerçekleşen)."""
    kontrol = s.scalars(
        select(ScriptKontrol)
        .where(ScriptKontrol.run_id == str(run.id))
        .order_by(ScriptKontrol.zaman.desc())
        .limit(1)
    ).first()
    if kontrol is None:
        return None
    satirlar = [r for r in (kontrol.ozet or {}).get("basarisiz") or [] if isinstance(r, Mapping)]
    for r in satirlar:
        if test_adi and str(r.get("test_adi") or "").strip() == test_adi.strip():
            return dict(r)
    return dict(satirlar[0]) if satirlar else None


def _fill_case(s: Session, ctx: BugContext, tc: TestCase) -> None:
    ctx.test_case_id = tc.id
    # 013 §3.3: model girdisi bugünküyle aynı kalsın diye test verisi atıfları çözülür.
    from tp_core.features.testveri.service import case_coz_gevsek, gizli_degerler

    icerik = case_coz_gevsek(s, tc.icerik or {})
    ctx.gizli_degerler = gizli_degerler(s)
    ctx.case_icerik = icerik
    ctx.case_baslik = temiz(icerik.get("title"), 200)
    ctx.case_adimlar = [a for a in icerik.get("steps") or [] if isinstance(a, Mapping)]
    ctx.case_beklenen = temiz(icerik.get("expected_result"))
    ctx.ac_refs = [str(r) for r in icerik.get("acceptance_criteria_refs") or []]
    ctx.test_case_key = ctx.test_case_key or _published_test_key(s, tc.id)
    req = s.get(Requirement, tc.requirement_id)
    _fill_requirement(s, ctx, req)
    if ctx.case_ref is None and req is not None and req.jira_key:
        ctx.case_ref = f"{req.jira_key}-C{tc.sira_no}"


def _fill_requirement(s: Session, ctx: BugContext, req: Requirement | None) -> None:
    if req is None:
        return
    ctx.requirement_id = req.id
    ctx.story_key = ctx.story_key or req.jira_key
    ctx.story_baslik = req.baslik
    acs = [str(a) for a in req.kabul_kriterleri or []]
    if ctx.ac_refs:
        isteni = {r.upper().replace(" ", "") for r in ctx.ac_refs}
        ctx.ac_metinleri = [a for a in acs if a.split(":", 1)[0].upper().replace(" ", "") in isteni]
    elif ctx.doc_ref:
        m = _AC.search(ctx.doc_ref)
        ctx.ac_metinleri = [a for a in acs if m and a.upper().startswith(f"AC{m.group(1)}:")]


def _triage_ek(s: Session, failure_id: uuid.UUID) -> Any | None:
    """Triage şeridinin `failure_ek` kaydı (yoksa None; şerit sırası bağımsız)."""
    try:
        from tp_core.models.triage_feature import FailureEk
    except ImportError:  # pragma: no cover - triage şeridi yoksa
        return None
    return s.get(FailureEk, failure_id)


def _ham_failure(ctx: BugContext, kanit: Mapping[str, Any], mesaj: str) -> dict[str, Any]:
    """Toolchain `failure` biçimi: triage ham kaydı saklıyorsa o, yoksa özetten kurulur."""
    ham = kanit.get("ham") if isinstance(kanit.get("ham"), Mapping) else None
    if ham and isinstance(ham.get("failure"), Mapping):
        ctx.statuses = dict(ham.get("statuses") or {}) or None
        ctx.consistent = ham.get("consistent")
        return dict(ham["failure"])
    m_loc, m_exp, m_rec = _LOCATOR.search(mesaj), _EXPECTED.search(mesaj), _RECEIVED.search(mesaj)
    m_match = _MATCHER.search(mesaj)
    adim = kanit.get("adim") or ctx.adim
    return {
        "type": kanit.get("hata_turu") or ctx.hata_turu or "assertion",
        "first_line": (mesaj.splitlines() or [None])[0],
        "matcher": kanit.get("matcher") or (m_match.group("v") if m_match else None),
        "locator": kanit.get("locator") or (m_loc.group("v").strip() if m_loc else None),
        "expected": kanit.get("beklenen") or (m_exp.group("v").strip() if m_exp else None),
        "received": kanit.get("gerceklesen") or (m_rec.group("v").strip() if m_rec else None),
        "step": {"title": adim} if adim else None,
        "evidence": {},
    }


def failure_context(s: Session, failure_id: uuid.UUID) -> BugContext:
    f = s.get(Failure, failure_id)
    if f is None:
        raise LookupError(f"failure bulunamadı: {failure_id}")
    ctx = BugContext(
        kaynak="failure",
        failure_id=f.id,
        test_adi=temiz(f.test_adi, 300),
        hata_imzasi=temiz(f.hata_imzasi, 300),
        sinif=f.sinif,
        hata_turu=f.alt_tur,
    )
    fek = _triage_ek(s, f.id)
    kanit: dict[str, Any] = dict(fek.kanit or {}) if fek is not None else {}
    run = s.get(Run, f.run_id)
    tr = s.get(TestResult, f.test_result_id) if f.test_result_id else None
    ek = s.get(TestResultEk, tr.id) if tr is not None else None
    mesaj = temiz(kanit.get("hata_mesaji"), 4000) or ""
    if tr is not None:
        ctx.test_dosya = temiz(tr.dosya, 300)
        mesaj = mesaj or (temiz(tr.hata_mesaji, 4000) or "")
    ctx.adim = temiz(kanit.get("adim"), 200)
    ctx.kural_sinyalleri = [
        str(x.get("aciklama") or x.get("kod"))
        for x in f.eslesen_sinyaller or []
        if isinstance(x, Mapping) and (x.get("aciklama") or x.get("kod"))
    ][:10]
    if run is not None:
        ctx.run_id = run.id
        ctx.commit = run.commit
        ctx.run_kaynak = run.kaynak
        ctx.tetik = run.tetik
        ortam = run.ortam or {}
        ctx.kirma = (
            bool(getattr(fek, "kirma", False))
            or bool(ortam.get("break_campaign"))
            or run.tetik == "break_verify"
        )
        saglik = kanit.get("saglik") or ortam.get("saglik")
        ctx.saglik = dict(saglik) if isinstance(saglik, Mapping) else None
        ctx.baglantilar, ctx.kanitlar = _evidence_links(run, ek, fek)
        satir = _check_row(s, run, f.test_adi)
        if satir:
            ctx.adim = ctx.adim or temiz(satir.get("adim"), 200)
            mesaj = mesaj or (temiz(satir.get("hata_mesaji")) or "")
            kanit.setdefault("beklenen", satir.get("beklenen"))
            kanit.setdefault("gerceklesen", satir.get("gerceklesen"))
            kanit.setdefault("locator", satir.get("locator"))
        if run.script_id is not None:
            sc = s.get(ScriptCodegen, run.script_id)
            if sc is not None:
                ctx.story_key = sc.story_key
                ctx.test_case_key = sc.test_key
                if sc.story_key:
                    ctx.case_ref = f"{sc.story_key}-C{sc.sira_no}"
                if tr is None or tr.test_case_id is None:
                    tc = s.get(TestCase, sc.test_case_id)
                    if tc is not None:
                        _fill_case(s, ctx, tc)
    if tr is not None and tr.test_case_id is not None and ctx.test_case_id is None:
        tc = s.get(TestCase, tr.test_case_id)
        if tc is not None:
            _fill_case(s, ctx, tc)
    if not ctx.gizli_degerler:  # case'siz başarısızlıkta da hata metni parolayı taşıyabilir
        from tp_core.features.testveri.service import gizli_degerler

        ctx.gizli_degerler = gizli_degerler(s)
    ctx.ham_failure = _ham_failure(ctx, kanit, mesaj)
    ctx.beklenen = temiz(ctx.ham_failure.get("expected"), 200)
    ctx.gerceklesen = temiz(ctx.ham_failure.get("received"), 200)
    ctx.hata_turu = ctx.hata_turu or ctx.ham_failure.get("type") or f.sinif
    ctx.hata_mesaji = temiz(ctx.ham_failure.get("first_line"), 300) or (
        mesaj.splitlines()[0][:300] if mesaj else None
    )
    sayfa = _PAGE_CLASS.search(" ".join(p for p in (mesaj, ctx.adim or "") if p))
    ctx.sayfa = sayfa.group(1) if sayfa else None
    return ctx


def finding_context(
    s: Session, finding_id: uuid.UUID, mevcut_icerik: Mapping[str, Any] | None = None
) -> BugContext:
    f = s.get(ConsistencyFinding, finding_id)
    if f is None:
        raise LookupError(f"bulgu bulunamadı: {finding_id}")
    ek = s.get(ConsistencyFindingEk, f.id)
    ctx = BugContext(
        kaynak="finding",
        finding_id=f.id,
        bulgu_turu=f.tur,
        doc_ref=temiz(f.doc_ref, 300),
        severity=f.severity,
        bulgu_no=ek.bulgu_no if ek else None,
        iddia=temiz(ek.iddia if ek else None),
        gozlem=temiz(ek.gozlem if ek else None),
        belge_metni=temiz((ek.mevcut_doc_text or ek.ref_metni) if ek else None),
        mevcut_icerik=dict(mevcut_icerik) if mevcut_icerik else None,
        bulgu_kanitlari=[dict(e) for e in f.kanitlar or [] if isinstance(e, Mapping)],
    )
    for ev in ctx.bulgu_kanitlari:
        if ev.get("kind") == "code" and ev.get("path"):
            ctx.kanitlar.append({"kind": "code", "ref": f"{ev['path']}:{ev.get('line')}"[:300]})
        elif ev.get("query"):
            ctx.kanitlar.append({"kind": "data", "ref": " ".join(str(ev["query"]).split())[:300]})
    _fill_requirement(s, ctx, s.get(Requirement, f.requirement_id))
    return ctx
