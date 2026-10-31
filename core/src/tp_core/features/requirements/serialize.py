"""API yanıt biçimleri (review-portal `src/api/types.ts`: Gereksinim, GereksinimDetay, Bulgu)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from tp_core.features.requirements import services
from tp_core.features.requirements.content import (
    AC_MISSING_UYARISI,
    ac_items,
    changed_targets,
    injection_warnings,
)
from tp_core.features.requirements.flow import (
    active_reviews,
    bug_draft_for,
    counts_for,
    cycle_start,
    last_failure,
    po_request_status,
    question_refs,
    questions_resolved_by_findings,
    settings,
    untrusted_check,
)
from tp_core.models import AppUser, BugDraft, ConsistencyFinding, Requirement
from tp_core.models.requirements_feature import (
    ConsistencyFindingEk,
    RequirementAkis,
    RequirementKontrol,
    RequirementReviewEk,
)
from tp_core.workflow.service import content_hash_of

PO_ONAYLI = ("po_approved", "generating", "cases_ready", "done")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def po_status(req: Requirement) -> dict[str, Any]:
    kanal = "jira" if req.kaynak == "jira" else "portal"
    if req.durum in PO_ONAYLI and req.po_onaylayan:
        durum = "approved"
    elif (
        req.durum == "failed"
        and req.po_onaylayan
        and req.onaylanan_hash is not None
        and req.onaylanan_hash == content_hash_of(req)
    ):
        # Case üretimi hata ile bittiyse PO onayı hâlâ güncel içeriğe bağlıdır (portal "yeniden
        # dene"de onaylayanı gösterir). İçerik değiştiyse onay bayat sayılır ve gösterilmez.
        durum = "approved"
    elif req.durum == "pending_po":
        durum = "pending"
    else:
        durum = "not_requested"
    return {
        "durum": durum,
        "onaylayan": req.po_onaylayan if durum == "approved" else None,
        "zaman": _iso(req.po_onay_zamani) if durum == "approved" else None,
        "kanal": kanal,
        # PO'nun onayladığı içerik hash'i (portal: içerik onaydan sonra değişti mi?).
        "onaylanan_hash": req.onaylanan_hash if durum == "approved" else None,
    }


def requirement_summary(req: Requirement, sayaclar: dict[str, int]) -> dict[str, Any]:
    return {
        "id": str(req.id),
        "kaynak": req.kaynak,
        "jira_key": req.jira_key,
        "baslik": req.baslik,
        "aciklama": req.aciklama,
        "kabul_kriterleri": ac_items(req.kabul_kriterleri),
        "ac_missing": req.ac_missing,
        "durum": req.durum,
        "cekim_zamani": _iso(req.cekim_zamani or req.olusturma),
        "po": po_status(req),
        "sayaclar": sayaclar,
    }


def list_requirements(s: Session) -> list[dict[str, Any]]:
    reqs = list(
        s.scalars(
            select(Requirement).order_by(
                Requirement.jira_key.is_(None), Requirement.jira_key, Requirement.olusturma
            )
        )
    )
    sayac = counts_for(s, [r.id for r in reqs])
    return [requirement_summary(r, sayac[r.id]) for r in reqs]


_SORU_ETIKETI = re.compile(r"(?<![\w])Q(\d{1,2})\s*[:.)\-–]\s*", re.IGNORECASE)


def map_po_answers(
    sorular: Sequence[dict[str, Any]], cevaplar: Sequence[dict[str, Any]]
) -> dict[str, str]:
    """PO yorumlarındaki ``Qn: …`` bölümlerini soru kimliklerine eşler (deterministik).

    Bir yorumda ``Q1: … Q2: …`` gibi birden çok bölüm olabilir; aynı soruya birden çok yorum
    cevap verdiyse sırayla birleştirilir. Etiketsiz yorum hiçbir soruya eşlenmez (portal onu
    "PO cevapları" altında bütün olarak gösterir). Metin güvenilmeyen içeriktir; düz metindir.
    """
    gecerli = {str(q.get("id") or "").upper() for q in sorular}
    out: dict[str, list[str]] = {}
    for c in cevaplar:
        metin = str(c.get("metin") or "")
        eslesmeler = list(_SORU_ETIKETI.finditer(metin))
        for i, m in enumerate(eslesmeler):
            qid = f"Q{int(m.group(1))}"
            if qid not in gecerli:
                continue
            son = eslesmeler[i + 1].start() if i + 1 < len(eslesmeler) else len(metin)
            parca = metin[m.end() : son].strip()
            if parca:
                out.setdefault(qid, []).append(parca)
    return {k: " / ".join(v) for k, v in out.items()}


def _on_inceleme(s: Session, req: Requirement) -> dict[str, Any] | None:
    aktif = active_reviews(s, req.id)
    if not aktif:
        return None
    rr = aktif[-1]
    ek = s.get(RequirementReviewEk, rr.id)
    cevaplar = map_po_answers(rr.sorular, req.po_cevaplari or [])
    degisen = (
        changed_targets(ek.aciklama, ek.kabul_kriterleri, req.aciklama, req.kabul_kriterleri)
        if ek is not None
        else set()
    )
    cozulen = questions_resolved_by_findings(s, req.id, list(rr.sorular))
    return {
        "id": str(rr.id),
        "verdict": rr.verdict,
        "questions": [
            {
                **q,
                "cevap": cevaplar.get(str(q.get("id") or "").upper()),
                # Soru ön incelemeden sonra doküman düzeltmesiyle değişen bir AC'ye ait mi?
                "duzeltmeyle_degisti": bool(question_refs(q) & degisen),
                # Tutarlılık bulgusunun insan kararıyla (fix_doc / accept_difference) kapandıysa
                # açıklama ("doküman düzeltmesiyle cevaplandı: F2 (tur 1)"); PO'ya sorulmaz.
                "kararla_cozuldu": cozulen.get(str(q.get("id") or "")),
            }
            for q in rr.sorular
        ],
        "jira_comment_id": rr.jira_comment_id,
        # Mod bilinmiyorsa null: hiçbir koşulda "live" varsayılmaz (REPLAY kuralı).
        "mode": rr.uretim_modu or None,
        # Modelin özeti (şüpheli içerik bildirimi dahil; ör. TPD-3'teki talimat). Karar dayanağı
        # değildir; deterministik uyarı `uyarilar`'dadır.
        "ozet": (ek.ozet or None) if ek is not None else None,
        "zaman": _iso(rr.olusturma),
        "durum": rr.durum,
    }


def _dongu_kosulu(s: Session, req_id: uuid.UUID) -> Any:
    """Varsayılan görünümün kapsamı: güncel inceleme döngüsünün bulguları (`cycle_start`).

    Döngü yoksa (ör. içerik değişip gereksinim `new`'e döndü) hiçbir bulgu güncel değildir.
    """
    bas = cycle_start(s, req_id)
    if bas is None:
        return false()
    return ConsistencyFinding.olusturma >= bas


def finding_counts(s: Session, req_id: uuid.UUID, *, tumu: bool = False) -> dict[str, int]:
    """Bulgu sayaçları; varsayılan olarak `findings_for` ile aynı kapsam (güncel döngü)."""
    q = select(ConsistencyFinding.kanit_dogrulandi, ConsistencyFinding.durum, func.count()).where(
        ConsistencyFinding.requirement_id == req_id
    )
    if not tumu:
        q = q.where(_dongu_kosulu(s, req_id))
        # Varsayılan listeyle aynı: bayat (devralmayan) bulgular sayılmaz.
        q = q.where(
            (ConsistencyFinding.durum != "stale") | ConsistencyFinding.id.in_(_devralanlar())
        )
    rows = s.execute(
        q.group_by(ConsistencyFinding.kanit_dogrulandi, ConsistencyFinding.durum)
    ).all()
    out = {"dogrulanan": 0, "elenen": 0, "acik": 0}
    for dogrulandi, durum, n in rows:
        if dogrulandi:
            out["dogrulanan"] += n
            if durum in ("open", "decided"):
                out["acik"] += n
        else:
            out["elenen"] += n
    return out


def requirement_detail(s: Session, req: Requirement) -> dict[str, Any]:
    sayac = counts_for(s, [req.id])[req.id]
    out = requirement_summary(req, sayac)
    uyarilar = injection_warnings(req.baslik, req.aciklama, *req.kabul_kriterleri)
    if req.ac_missing:
        uyarilar.insert(0, AC_MISSING_UYARISI)
    guvenilmez = untrusted_check(s, req.id) if req.durum == "findings_open" else None
    if guvenilmez is not None:
        uyarilar.append(
            f"Denetim sonucu güvenilir değil ({guvenilmez}); doküman otomatik olarak son hale "
            "alınmadı. Bulguları inceleyip belgeyi açıkça son hale alın (apply-doc-fixes) ya da "
            "yeniden denetleyin."
        )
    po_istegi = po_request_status(s, req)
    if po_istegi is not None and po_istegi["durum"] == "basarisiz":
        uyarilar.append(
            "PO'ya soru yorumu Jira'ya yazılamadı "
            f"({po_istegi['hata']}); PO sorgusu yorumu otomatik olarak yeniden dener. Yorum "
            "yazılmadan konan onay etiketi sayılmaz."
        )
    son_hata = last_failure(s, req)
    if son_hata is not None:
        uyarilar.append(f"Son işlem başarısız: {son_hata['neden']} — {son_hata['oneri']}")
    son = s.scalars(
        select(RequirementKontrol)
        .where(RequirementKontrol.requirement_id == req.id)
        .order_by(RequirementKontrol.sira.desc())
        .limit(1)
    ).first()
    akis = s.get(RequirementAkis, req.id)
    ust = settings().max_rounds
    out.update(
        {
            "icerik_hash": content_hash_of(req),
            "kaynak_hash": req.kaynak_hash,
            "on_inceleme": _on_inceleme(s, req),
            "kontrol_turu": req.kontrol_turu,
            "kontrol_turu_ust_sinir": ust,
            "insan_karari_gerekli": req.durum == "findings_open"
            and (req.kontrol_turu >= ust or guvenilmez is not None),
            "denetim_guvenilmez": guvenilmez,
            "jira_url": services.jira_url(req.jira_key),
            "uyarilar": uyarilar,
            "bulgu_sayaclari": finding_counts(s, req.id),
            "son_kontrol": None
            if son is None
            else {
                "id": str(son.id),
                "sira": son.sira,
                "tur": son.tur,
                "head_sha": son.head_sha,
                "mode": son.uretim_modu,
                "bulgu": son.bulgu_toplam,
                "dogrulanan": son.dogrulanan,
                "elenen": son.elenen,
                "zaman": _iso(son.olusturma),
            },
            "son_hal_hash": akis.son_hal_hash if akis is not None else None,
            # `failed` iken son hatanın nedeni + Türkçe öneri (yoksa null).
            "son_hata": son_hata,
            # Jira yolunda son haldeki PO soru yorumu: yazildi | bekliyor | basarisiz (yoksa null).
            "po_istegi": po_istegi,
            "po_cevaplari": req.po_cevaplari or [],
        }
    )
    return out


def finding_label(bulgu_no: str | None, f: ConsistencyFinding) -> str:
    no = bulgu_no or str(f.id)[:8]
    return f"{no} (tur {f.kontrol_turu})"


def finding_out(
    f: ConsistencyFinding,
    ek: ConsistencyFindingEk | None,
    karar_veren: str | None,
    bug_draft_id: uuid.UUID | None,
    onceki: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ozet = " — ".join(p for p in ((ek.iddia if ek else ""), (ek.gozlem if ek else "")) if p)
    out = {
        "id": str(f.id),
        "requirement_id": str(f.requirement_id),
        "bulgu_no": ek.bulgu_no if ek else None,
        # Jira düzeltme yorumundaki etiketle aynı ("F2 (tur 1)"): turlar arası aynı numara
        # (2. turun F1'i ≠ 1. turun F1'i) ve Jira yorumu ↔ portal kartı eşlemesi için.
        "bulgu_etiketi": finding_label(ek.bulgu_no if ek else None, f),
        "type": f.tur,
        "doc_ref": f.doc_ref,
        "ozet": ozet,
        "claim": ek.iddia if ek else "",
        "observed": ek.gozlem if ek else "",
        "evidence": f.kanitlar,
        "kanit_dogrulandi": f.kanit_dogrulandi,
        "dogrulama": ek.dogrulama if ek else [],
        "severity": f.severity,
        "mevcut_doc_text": ek.mevcut_doc_text if ek else None,
        "suggested_doc_text": ek.ai_onerisi if ek else f.onerilen_metin,
        "karar": f.analist_karari,
        "karar_metni": f.onerilen_metin if f.analist_karari == "fix_doc" else None,
        "gerekce": f.gerekce,
        "karar_veren": karar_veren,
        "karar_zamani": _iso(f.karar_zamani),
        "kontrol_turu": f.kontrol_turu,
        "durum": f.durum,
        "bug_draft_id": str(bug_draft_id) if bug_draft_id else None,
        "icerik_hash": content_hash_of(f),
        "mode": f.uretim_modu or None,
        # Aynı fark önceki turda insan kararıyla kapandıysa: o karar (yeniden karar istenmez).
        "onceki_karar": onceki,
    }
    if onceki is not None and f.analist_karari is None:
        # Kart karar özetini göstersin (düğmesiz); karar önceki bulgunun insan kararıdır.
        out["karar"] = onceki["karar"]
        out["gerekce"] = onceki["gerekce"]
        out["karar_veren"] = onceki["karar_veren"]
        out["karar_zamani"] = onceki["karar_zamani"]
    return out


def findings_for(
    s: Session, req_id: uuid.UUID, *, tumu: bool = False
) -> tuple[list[dict[str, Any]], int]:
    """Doğrulanmış bulgular (elenenler hiçbir zaman dönmez) ve elenen bulgu sayısı."""
    q = select(ConsistencyFinding).where(
        ConsistencyFinding.requirement_id == req_id,
        ConsistencyFinding.kanit_dogrulandi.is_(True),
        ConsistencyFinding.durum != "discarded",
    )
    elenen_q = (
        select(func.count())
        .select_from(ConsistencyFinding)
        .where(
            ConsistencyFinding.requirement_id == req_id,
            ConsistencyFinding.kanit_dogrulandi.is_(False),
        )
    )
    if not tumu:
        # Yalnızca güncel inceleme döngüsü (önceki döngülerin çözülmüş/bayat bulguları ve
        # numaraları karışmaz). Döngü içinde bayat bulgular gizlenir; önceki kararı devralan
        # bulgu (son turun parçası) gösterilir.
        dongu = _dongu_kosulu(s, req_id)
        q = q.where(dongu).where(
            (ConsistencyFinding.durum != "stale") | ConsistencyFinding.id.in_(_devralanlar())
        )
        elenen_q = elenen_q.where(dongu)
    bulgular = list(
        s.scalars(q.order_by(ConsistencyFinding.kontrol_turu.desc(), ConsistencyFinding.olusturma))
    )
    elenen = s.scalar(elenen_q) or 0
    return [one_finding(s, f) for f in bulgular], elenen


def _devralanlar() -> Any:
    return select(ConsistencyFindingEk.finding_id).where(
        ConsistencyFindingEk.onceki_finding_id.is_not(None)
    )


def _veren(s: Session, f: ConsistencyFinding) -> str | None:
    return s.get(AppUser, f.karar_veren_id).kullanici_adi if f.karar_veren_id else None


def one_finding(s: Session, f: ConsistencyFinding) -> dict[str, Any]:
    ek = s.get(ConsistencyFindingEk, f.id)
    bug = bug_draft_for(s, f)
    onceki: dict[str, Any] | None = None
    if ek is not None and ek.onceki_finding_id is not None:
        o = s.get(ConsistencyFinding, ek.onceki_finding_id)
        if o is not None:
            o_ek = s.get(ConsistencyFindingEk, o.id)
            onceki = {
                "finding_id": str(o.id),
                "bulgu_no": o_ek.bulgu_no if o_ek else None,
                "kontrol_turu": o.kontrol_turu,
                "karar": o.analist_karari,
                "gerekce": o.gerekce
                or f"Önceki turda (tur {o.kontrol_turu}) verilen karar devralındı.",
                "karar_veren": _veren(s, o),
                "karar_zamani": _iso(o.karar_zamani),
            }
    return finding_out(f, ek, _veren(s, f), bug.id if bug is not None else None, onceki)


def bug_draft_out(s: Session, b: BugDraft) -> dict[str, Any]:
    """Portal `BugTaslagi` biçimi (salt okuma; karar/yayın Faz 4 özelliğinde)."""
    onaylayan = s.get(AppUser, b.onaylayan_id).kullanici_adi if b.onaylayan_id else None
    return {
        "id": str(b.id),
        "kaynak": "consistency" if b.finding_id else "triage",
        "failure_id": str(b.failure_id) if b.failure_id else None,
        "finding_id": str(b.finding_id) if b.finding_id else None,
        "icerik": b.icerik,
        "mukerrer_adaylari": b.mukerrer_adaylari or [],
        "karar": b.karar,
        "durum": b.durum,
        "link_key": b.link_key,
        "icerik_hash": b.icerik_hash,
        "onaylayan": onaylayan,
        "onay_zamani": None,
        "jira_key": b.jira_key,
        "mode": b.uretim_modu or None,
        "olusturma": _iso(b.olusturma),
    }


def bug_drafts(s: Session, requirement_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    q = select(BugDraft).order_by(BugDraft.olusturma.desc())
    if requirement_id is not None:
        q = q.join(ConsistencyFinding, ConsistencyFinding.id == BugDraft.finding_id).where(
            ConsistencyFinding.requirement_id == requirement_id
        )
    return [bug_draft_out(s, b) for b in s.scalars(q)]
