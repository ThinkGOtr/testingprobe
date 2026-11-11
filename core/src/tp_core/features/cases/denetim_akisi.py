"""Case seti denetimi (P9; specs/011 F5, K2, K3) ve yayın kapısı.

Akış:

1. `request_audit` (`POST /requirements/{id}/case-audit`, analist, "Denetime gönder"): gereksinim
   `cases_ready|done` ve PO onayı güncel; setin v3 case'i var; aynı set için review sürmüyor; ve
   **güncel setin review'u tamamlanmış ya da setin en az bir onaylı v3 case'i var**. Gerekçe:
   P9, P8'i girdi olarak alır (tamamlanmış review en iyi girdi); review başarısız olduysa ya da hiç
   çalışmadıysa analist kalıcı olarak kilitlenmesin, ama denetime insan incelemesinden geçmemiş bir
   set gitmesin (en az bir onay = analist seti gördü). Aynı set için bekleyen denetim varsa o döner.
2. `run_audit` (core-worker, `cases.audit`): istek (`ports.CaseSetAuditRequest`) kurulur ve
   Agent Probe portuna gider (`get_agent_probe().audit_case_set`; bugün geçitte `case_audit`,
   Opus). Port hatası (erişilemiyor, REPLAY-MISS, model hatası) karar ÜRETMEZ: satır `hata` olur,
   yayın kapısı kapalı kalır (fail-closed).
3. Deterministik sertleştirme (Constitution XI; `deterministic_findings` + `harden`): kodda
   denetlenebilen ihlaller kararın ALT SINIRIDIR. Model KABUL dese bile karar en az bu sınırdır;
   model daha sert karar verdiyse o geçerlidir (kod yumuşatamaz). `model_karari` ve `karar`
   ayrı kolonlardır; kurallar `icerik.deterministik_bulgular`'dadır.
4. Yayın kapısı (K3; `gate_check`, `publish.set_gate_check` ile bağlanır): `TP_DENETIM_KAPISI`
   (`on` varsayılan | `off`). Açıkken v3 case, gereksinimin GÜNCEL `set_hash`'ine ait son
   tamamlanmış denetim KABUL değilse yayınlanmaz. Set değişince karar bayat olur.
"""

from __future__ import annotations

import fnmatch
import os
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.events.bus import publish_tx
from tp_core.features.cases import review as review_mod
from tp_core.models import CaseSetAudit, Requirement, TestCase, session_scope
from tp_core.ports import CaseSetAuditRequest, CaseSetAuditResult
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue
from tp_core.workflow.service import Principal, WorkflowError

AUDIT_JOB = "cases.audit"
KABUL, DUZELTME, ENGELLE = "KABUL", "DÜZELTME_GEREKLİ", "ENGELLE"
SIDDET = {KABUL: 0, DUZELTME: 1, ENGELLE: 2}
KAPI_ORTAMI = "TP_DENETIM_KAPISI"
POLITIKA_DOSYASI = Path("agent-probe") / "politikalar.md"


class AuditNotAllowed(WorkflowError):
    status_code = 409


# ---------------------------------------------------------------- kurum politikaları


def _rules_dir() -> Path:
    from tp_core.gateway import find_rules_dir

    return find_rules_dir()


def _bolum(metin: str, baslik: str) -> list[str]:
    """`## <baslik>` bölümündeki madde imli satırlar (sonraki `## `'e kadar)."""
    out: list[str] = []
    icinde = False
    for satir in metin.splitlines():
        if satir.startswith("## "):
            icinde = satir[3:].strip() == baslik
            continue
        if icinde and satir.lstrip().startswith("- "):
            out.append(satir.lstrip()[2:].strip())
    return out


@lru_cache(maxsize=4)
def _politika_metni(yol: str) -> str:
    p = Path(yol)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def policies(rules_dir: Path | None = None) -> list[str]:
    """Kurum politikaları (denetim girdisi; `rules/agent-probe/politikalar.md`, varsayılan)."""
    yol = (rules_dir or _rules_dir()) / POLITIKA_DOSYASI
    return _bolum(_politika_metni(str(yol)), "Politikalar")


def allowed_hosts(rules_dir: Path | None = None) -> list[str]:
    """İzinli test ortamları (deterministik ortam kontrolü; fnmatch desenleri)."""
    yol = (rules_dir or _rules_dir()) / POLITIKA_DOSYASI
    return [h.lower() for h in _bolum(_politika_metni(str(yol)), "İzinli test ortamları")]


# ------------------------------------------------------- deterministik kurallar (XI)

# Saldırı metni imzaları (prompt injection, XSS, SQLi). Yüksek kesinlikli, dar desenler: amaç
# işaretsiz ya da yanlış yere yazılmış saldırı verisini yakalamaktır, güvenlik taraması değil.
SALDIRI_DESENLERI = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(önceki|onceki|yukarıdaki|tüm|bütün)\s+(tüm\s+|bütün\s+)?talimat\w*\s+(yok\s+say|unut|görmezden)",
        r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions",
        r"<\s*script\b",
        r"javascript\s*:",
        r"\bon(error|load)\s*=",
        r"'\s*or\s+'?1'?\s*=\s*'?1",
        r"\bunion\s+(all\s+)?select\b",
        r"\bdrop\s+table\b",
    )
)
# Denetçiye / denetim kararına yönelik gömülü talimat (karar kuralı: ENGELLE).
DENETCIYE_TALIMAT = re.compile(
    r"\b(denetçi\w*|denetci\w*|denetleyici\w*|agent\s*probe|auditor)\W+(?:\w+\W+){0,6}?"
    r"(onayla|kabul\s+et|kabul\s+ver|approve)\b",
    re.IGNORECASE,
)
URL_DESENI = re.compile(r"https?://([^/\s:\"'<>)]+)", re.IGNORECASE)


def _saldiri_var(metin: str) -> bool:
    return any(d.search(metin) for d in SALDIRI_DESENLERI)


def _sade(deger: Any) -> str:
    return re.sub(r"\s+", " ", str(deger or "")).strip().casefold()


def _metin_alanlari(case: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Talimat/saldırı metninin yazılmaması gereken alanlar (test verisi hariç)."""
    out = [
        ("başlık", str(case.get("title") or "")),
        ("beklenen", str(case.get("expected_result") or "")),
    ]
    out += [("ön koşul", str(p)) for p in case.get("preconditions") or []]
    out += [("temizlik", str(t)) for t in case.get("teardown") or []]
    for adim in case.get("steps") or []:
        if isinstance(adim, Mapping):
            for k, ad in (
                ("action", "adım"),
                ("data", "adım verisi"),
                ("expected", "adım beklenen"),
            ):
                out.append((f"{ad} {adim.get('id') or ''}".strip(), str(adim.get(k) or "")))
    return out


def _host_izinli(host: str, izinli: Sequence[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(fnmatch.fnmatchcase(host, d) for d in izinli)


def _bulgu(kural: str, no: int | None, alt_sinir: str, aciklama: str) -> dict[str, Any]:
    return {"kural": kural, "case_ref": no, "alt_sinir": alt_sinir, "aciklama": aciklama}


def deterministic_findings(
    cases: Sequence[Mapping[str, Any]],
    requirement_text: str = "",
    izinli: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Kodda denetlenebilen ihlaller → karar alt sınırı (`alt_sinir`). Case'ler set sırasıyla
    (1 tabanlı `case_ref`). Kurallar:

    - `isaretsiz_payload_metinde`: saldırı imzası başlık/ön koşul/adım/beklenen/temizlik → DÜZELTME
    - `isaretsiz_payload_veride`: veride saldırı imzası, `is_attack_payload` true değil → DÜZELTME
    - `payload_baska_alanda`: işaretli saldırı verisinin metni başka alanda geçiyor → DÜZELTME
    - `sentetik_degil`: `synthetic` true değil → DÜZELTME
    - `ready_atifli`: `ready` case varsayım/açık soru atfı taşıyor → DÜZELTME
    - `izinsiz_ortam`: case metnindeki URL'nin ana makinesi izinli ortamlarda değil → DÜZELTME
    - `denetciye_talimat`: gereksinimde ya da case metninde denetçiye/denetim kararına yönelik
      talimat (işaretli saldırı verisi hariç) → ENGELLE
    """
    izinli = list(allowed_hosts() if izinli is None else izinli)
    out: list[dict[str, Any]] = []
    if DENETCIYE_TALIMAT.search(requirement_text or ""):
        out.append(
            _bulgu(
                "denetciye_talimat",
                None,
                ENGELLE,
                "Gereksinim metninde denetçiye / denetim kararına yönelik talimat var.",
            )
        )
    for no, case in enumerate(cases, start=1):
        alanlar = _metin_alanlari(case)
        veriler = [v for v in case.get("test_data") or [] if isinstance(v, Mapping)]
        isaretli = [_sade(v.get("value")) for v in veriler if v.get("is_attack_payload") is True]
        for ad, metin in alanlar:
            if _saldiri_var(metin):
                out.append(
                    _bulgu(
                        "isaretsiz_payload_metinde",
                        no,
                        DUZELTME,
                        f"Saldırı metni {ad} alanında (test_data dışında); test verisine "
                        "taşınıp is_attack_payload ile işaretlenmeli.",
                    )
                )
                break
        for ad, metin in alanlar:
            sade = _sade(metin)
            if any(p and p in sade for p in isaretli):
                out.append(
                    _bulgu(
                        "payload_baska_alanda",
                        no,
                        DUZELTME,
                        f"İşaretli saldırı verisinin metni {ad} alanında da geçiyor.",
                    )
                )
                break
        for v in veriler:
            deger = str(v.get("value") or "")
            if v.get("is_attack_payload") is not True and _saldiri_var(deger):
                out.append(
                    _bulgu(
                        "isaretsiz_payload_veride",
                        no,
                        DUZELTME,
                        f"Test verisi '{v.get('name')}' saldırı metni içeriyor ama "
                        "is_attack_payload işaretli değil.",
                    )
                )
            if v.get("synthetic") is not True:
                out.append(
                    _bulgu(
                        "sentetik_degil",
                        no,
                        DUZELTME,
                        f"Test verisi '{v.get('name')}' sentetik olarak işaretli değil.",
                    )
                )
        if case.get("readiness") == "ready" and (
            case.get("assumption_refs") or case.get("open_question_refs")
        ):
            out.append(
                _bulgu(
                    "ready_atifli",
                    no,
                    DUZELTME,
                    "Hazır (ready) case varsayıma / açık soruya atıf yapıyor.",
                )
            )
        metinler = [m for _, m in alanlar] + [
            str(v.get("value") or "") for v in veriler if v.get("is_attack_payload") is not True
        ]
        for metin in metinler:
            if DENETCIYE_TALIMAT.search(metin):
                out.append(
                    _bulgu(
                        "denetciye_talimat",
                        no,
                        ENGELLE,
                        "Case metninde denetçiye / denetim kararına yönelik talimat var.",
                    )
                )
                break
        yasak = sorted(
            {h for m in metinler for h in URL_DESENI.findall(m) if not _host_izinli(h, izinli)}
        )
        if yasak:
            out.append(
                _bulgu(
                    "izinsiz_ortam",
                    no,
                    DUZELTME,
                    "İzinli test ortamı dışında hedef: " + ", ".join(yasak),
                )
            )
    return out


def harden(model_karari: str, bulgular: Iterable[Mapping[str, Any]]) -> str:
    """Kararın deterministik alt sınırla sertleştirilmesi (yumuşatma yok)."""
    karar = model_karari if model_karari in SIDDET else ENGELLE
    for b in bulgular:
        sinir = str(b.get("alt_sinir"))
        if SIDDET.get(sinir, 0) > SIDDET[karar]:
            karar = sinir
    return karar


# ------------------------------------------------------------------------- istek


def _bekleyen(session: Session, requirement_id: uuid.UUID, hash_: str) -> CaseSetAudit | None:
    return session.scalars(
        select(CaseSetAudit)
        .where(
            CaseSetAudit.requirement_id == requirement_id,
            CaseSetAudit.set_hash == hash_,
            CaseSetAudit.durum == "bekliyor",
        )
        .order_by(CaseSetAudit.olusturma.desc())
        .limit(1)
    ).first()


def submit_block(session: Session, req: Requirement, hash_: str | None) -> str | None:
    """ "Denetime gönder" neden kapalı (None = gönderilebilir). Portal düğme açıklaması da budur."""
    from tp_core.features.cases.service import requirement_change_reason

    if req.durum not in review_mod.SET_KULLANILIR:
        return f"Denetim yalnızca case'leri hazır gereksinimde istenir (durum: {req.durum})"
    engel = requirement_change_reason(req)
    if engel is not None:
        return engel
    if hash_ is None:
        return "Gereksinimin güncel v3 case'i yok; denetlenecek set boş"
    if review_mod._bekleyen(session, req.id, hash_) is not None:
        return "Bu set için review sürüyor; review bitince denetime gönderin"
    if review_mod.latest_completed(session, req.id, hash_) is not None:
        return None
    onayli = session.scalar(
        select(TestCase.id)
        .where(
            TestCase.id.in_([tc.id for tc in review_mod.current_cases(session, req)]),
            TestCase.durum.in_(("approved", "published")),
        )
        .limit(1)
    )
    if onayli is None:
        return (
            "Bu setin review'u tamamlanmadı ve onaylı case yok: review'u yeniden çalıştırın ya da "
            "en az bir case'i inceleyip onaylayın"
        )
    return None


def request_audit(session: Session, requirement_id: uuid.UUID, user: Principal) -> dict[str, Any]:
    """`POST /requirements/{id}/case-audit` ("Denetime gönder")."""
    from tp_core.features.cases.service import get_requirement

    req = get_requirement(session, requirement_id, lock=True)
    hash_ = review_mod.set_hash(session, req)
    mevcut = _bekleyen(session, req.id, hash_) if hash_ else None
    if mevcut is None:
        engel = submit_block(session, req, hash_)
        if engel is not None:
            raise AuditNotAllowed(engel)
        assert hash_ is not None
        son_review = review_mod.latest_completed(session, req.id, hash_)
        satir = CaseSetAudit(
            requirement_id=req.id,
            set_hash=hash_,
            isteyen=user.kullanici_adi,
            review_id=son_review.id if son_review else None,
        )
        session.add(satir)
        session.flush()
        satir.job_id = enqueue(
            session.connection(),
            AUDIT_JOB,
            {"audit_id": str(satir.id)},
            idempotency_key=f"{AUDIT_JOB}:{satir.id}",
        )
        audit_on_commit(
            session,
            user.kullanici_adi,
            "cases.audit_requested",
            f"requirement:{req.id}",
            {"audit_id": satir.id, "set_hash": hash_, "review_id": satir.review_id},
        )
        session.flush()
    return view(session, req.id)


def build_request(
    session: Session, req: Requirement, girdi: review_mod.SetGirdisi
) -> CaseSetAuditRequest:
    blok, kok = review_mod.requirement_block_for(req)
    son_review = review_mod.latest_completed(session, req.id, girdi.set_hash)
    review_sonucu = None
    if son_review is not None:
        review_sonucu = {
            k: v
            for k, v in (son_review.icerik or {}).items()
            if k in ("items", "score", "missing_cases", "remove_or_merge", "summary")
        }
    return CaseSetAuditRequest(
        requirement_id=req.id,
        requirement_key=kok,
        set_hash=girdi.set_hash or "",
        requirement_block=blok,
        generated_set=review_mod.set_payload([tc.icerik for tc in girdi.cases], girdi.ozet),
        review_result=review_sonucu,
        policies=policies(),
    )


def _requirement_text(req: Any) -> str:
    return "\n".join(
        [str(req.baslik or ""), str(req.aciklama or "")]
        + [str(a) for a in req.kabul_kriterleri or []]
    )


def _hata_yaz(audit_id: uuid.UUID, neden: str) -> None:
    with session_scope() as s:
        satir = s.get(CaseSetAudit, audit_id, with_for_update=True)
        if satir is None or satir.durum != "bekliyor":
            return
        satir.durum, satir.hata = "hata", neden[:1000]
        audit_on_commit(
            s,
            "system",
            "cases.audit_failed",
            f"requirement:{satir.requirement_id}",
            {"audit_id": audit_id, "set_hash": satir.set_hash, "hata": neden[:300]},
        )
        publish_tx(
            s.connection(), "case.audit", {"requirement_id": satir.requirement_id, "durum": "hata"}
        )


def run_audit(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    """`cases.audit` işi: Agent Probe portu → deterministik sertleştirme → `case_set_audit`."""
    from tp_core.gateway import deterministic_call_id
    from tp_core.gateway.errors import GatewayError, ReplayNotFound
    from tp_core.integrations.agent_probe import AgentProbeUnavailable, denetim, get_agent_probe

    aid = uuid.UUID(str((ctx.yuk or {})["audit_id"]))
    with session_scope() as s:
        satir = s.get(CaseSetAudit, aid)
        if satir is None:
            raise PermanentJobError("denetim kaydı yok")
        if satir.durum != "bekliyor":
            return {"atlandi": True, "durum": satir.durum}
        req = s.get(Requirement, satir.requirement_id)
        if req is None:
            raise PermanentJobError("gereksinim silinmiş")
        girdi = review_mod.snapshot(s, req)
        if girdi.set_hash is None:
            satir.durum, satir.hata = "hata", "sette v3 case kalmadı"
            return {"atlandi": True, "neden": "boş set"}
        satir.set_hash = girdi.set_hash
        istek = build_request(s, req, girdi)
        harita = girdi.harita()
        cases = [dict(tc.icerik) for tc in girdi.cases]
        gereksinim_metni = _requirement_text(req)
    try:
        port = get_agent_probe()
        with denetim.cagri_baglami(call_id=deterministic_call_id(ctx.job_id, "case_audit")):
            sonuc: CaseSetAuditResult = port.audit_case_set(istek)
    except ReplayNotFound as exc:
        _hata_yaz(
            aid, f"REPLAY-MISS: bu set için kayıtlı denetim çıktısı yok ({type(exc).__name__})"
        )
        return {"hata": "replay_miss"}
    except (GatewayError, AgentProbeUnavailable) as exc:
        if not ctx.son_deneme and not isinstance(exc, AgentProbeUnavailable):
            raise
        _hata_yaz(aid, f"Agent Probe: {exc}")
        return {"hata": type(exc).__name__}
    except Exception as exc:
        _hata_yaz(aid, f"{type(exc).__name__}: {str(exc)[:300]}")
        return {"hata": type(exc).__name__}
    bulgular = deterministic_findings(cases, gereksinim_metni)
    karar = harden(sonuc.decision, bulgular)
    with session_scope() as s:
        satir = s.get(CaseSetAudit, aid, with_for_update=True)
        if satir is None or satir.durum != "bekliyor":
            return {"atlandi": True}
        mod = review_mod._mod(s, sonuc.ai_call_id)
        satir.durum = "tamamlandi"
        satir.model_karari = sonuc.decision
        satir.karar = karar
        satir.kaynak = sonuc.kaynak
        satir.talep_no = sonuc.talep_no
        satir.ai_call_id = sonuc.ai_call_id
        satir.icerik = {
            "decision": sonuc.decision,
            "decision_rationale": sonuc.decision_rationale,
            "findings": sonuc.findings,
            "missing_scenarios": sonuc.missing_scenarios,
            "deterministik_bulgular": bulgular,
            "sertlestirildi": karar != sonuc.decision,
            "case_haritasi": harita,
            "review_kullanildi": istek.review_result is not None,
            "mode": mod,
        }
        audit_on_commit(
            s,
            "system",
            "cases.audited",
            f"requirement:{satir.requirement_id}",
            {
                "audit_id": aid,
                "set_hash": satir.set_hash,
                "karar": karar,
                "model_karari": sonuc.decision,
                "kaynak": sonuc.kaynak,
                "talep_no": sonuc.talep_no,
                "ai_call_id": sonuc.ai_call_id,
                "deterministik": [b["kural"] for b in bulgular],
            },
        )
        publish_tx(
            s.connection(),
            "case.audit",
            {"requirement_id": satir.requirement_id, "durum": "tamamlandi", "karar": karar},
        )
    return {"audit_id": str(aid), "karar": karar, "model_karari": sonuc.decision}


# ------------------------------------------------------------------- yayın kapısı (K3)


def gate_enabled() -> bool:
    return (os.environ.get(KAPI_ORTAMI) or "on").strip().lower() not in (
        "off",
        "0",
        "false",
        "kapali",
    )


def latest_completed(
    session: Session, requirement_id: uuid.UUID, hash_: str | None
) -> CaseSetAudit | None:
    if hash_ is None:
        return None
    return session.scalars(
        select(CaseSetAudit)
        .where(
            CaseSetAudit.requirement_id == requirement_id,
            CaseSetAudit.set_hash == hash_,
            CaseSetAudit.durum == "tamamlandi",
        )
        .order_by(CaseSetAudit.olusturma.desc(), CaseSetAudit.id.desc())
        .limit(1)
    ).first()


def latest(session: Session, requirement_id: uuid.UUID) -> CaseSetAudit | None:
    return session.scalars(
        select(CaseSetAudit)
        .where(CaseSetAudit.requirement_id == requirement_id)
        .order_by(CaseSetAudit.olusturma.desc(), CaseSetAudit.id.desc())
        .limit(1)
    ).first()


def _kisa(metin: str | None, n: int = 240) -> str:
    metin = " ".join(str(metin or "").split())
    return metin if len(metin) <= n else metin[: n - 1] + "…"


def gate_reason(session: Session, req: Requirement) -> str | None:
    """Gereksinimin güncel seti için yayın engeli (None = KABUL var ya da kapı kapalı)."""
    if not gate_enabled():
        return None
    hash_ = review_mod.set_hash(session, req)
    karar = latest_completed(session, req.id, hash_)
    if karar is None:
        son = latest(session, req.id)
        if son is None:
            return "Denetim kararı yok: set Agent Probe denetiminden geçmedi ('Denetime gönder')"
        if son.set_hash == hash_ and son.durum == "bekliyor":
            return "Denetim bekliyor: bu set için Agent Probe kararı henüz gelmedi"
        if son.set_hash == hash_ and son.durum == "hata":
            return f"Denetim yapılamadı: {_kisa(son.hata, 160)}; yeniden denetime gönderin"
        return (
            "Denetim kararı bayat: set son denetimden sonra değişti (case eklendi, düzeltildi ya "
            "da reddedildi); yeniden denetime gönderin"
        )
    if karar.karar == KABUL:
        return None
    gerekce = _kisa((karar.icerik or {}).get("decision_rationale"))
    return f"{karar.karar}: {gerekce}" if gerekce else str(karar.karar)


def gate_check(session: Session, tc: TestCase) -> str | None:
    """`publish.set_gate_check` kancası (yalnız v3 case için çağrılır)."""
    req = session.get(Requirement, tc.requirement_id)
    if req is None:
        return "Gereksinim bulunamadı"
    return gate_reason(session, req)


def bind_gate() -> None:
    """Yayın kapısını bağlar (publish paketinin açılışında; core-api, core-worker, testler)."""
    from tp_core.features.publish import service as publish

    publish.set_gate_check(gate_check)


# ------------------------------------------------------------------------ görünüm


def serialize(session: Session, satir: CaseSetAudit | None, guncel: str | None) -> dict | None:
    if satir is None:
        return None
    return {
        "id": str(satir.id),
        "durum": satir.durum,
        "set_hash": satir.set_hash,
        "karar": satir.karar,
        "model_karari": satir.model_karari,
        "icerik": satir.icerik or {},
        "kaynak": satir.kaynak,
        "talep_no": satir.talep_no,
        "hata": satir.hata,
        "isteyen": satir.isteyen,
        "review_id": str(satir.review_id) if satir.review_id else None,
        "ai_call_id": str(satir.ai_call_id) if satir.ai_call_id else None,
        "olusturma": satir.olusturma,
        "guncelleme": satir.guncelleme,
        "guncel": satir.set_hash == guncel,
    }


def view(session: Session, requirement_id: uuid.UUID) -> dict[str, Any]:
    """`GET /requirements/{id}/case-audit`: son karar, güncel set hash'i, güncel mi, kapı durumu."""
    from tp_core.features.cases.service import get_requirement

    req = get_requirement(session, requirement_id)
    hash_ = review_mod.set_hash(session, req)
    son = latest(session, req.id)
    bekleyen = _bekleyen(session, req.id, hash_) if hash_ else None
    return {
        "requirement_id": str(req.id),
        "set_hash": hash_,
        "denetim": serialize(session, son, hash_),
        "guncel_karar": serialize(session, latest_completed(session, req.id, hash_), hash_),
        "calisiyor": bekleyen is not None,
        "gonder_engeli": None if bekleyen is not None else submit_block(session, req, hash_),
        "kapi_acik": gate_enabled(),
        "yayin_engeli": gate_reason(session, req) if hash_ else None,
    }


router = APIRouter(tags=["cases"])
Analyst = Annotated[Principal, Depends(require_role("analyst"))]


@router.get("/requirements/{requirement_id}/case-audit")
def get_case_audit(
    requirement_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    return view(session, requirement_id)


@router.post("/requirements/{requirement_id}/case-audit", status_code=202)
def post_case_audit(requirement_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
    return request_audit(session, requirement_id, user)
