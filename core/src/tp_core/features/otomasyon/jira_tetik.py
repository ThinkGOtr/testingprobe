"""Jira durum tetiği (specs/013-sprint-otomasyonu §3.4, K5, Y2, Y5).

Worker işi `requirements.jira_tetik` her `aralik_s` saniyede bir Jira'da ayarlanan duruma
(varsayılan "QA To Do") gelmiş story'leri arar:

- Her eşleşen issue `flow.upsert_issue(..., aktor="jira-tetik")` ile çekilir, `jira_durumu` yazılır.
- Gereksinim `new` ve `qa_tetik_zamani` NULL ise: `qa_tetik_zamani = now()` ve ön inceleme
  `flow.start_review(..., JIRA_TETIK_AKTORU)` ile başlar; denetim `requirements.jira_tetik`.
  Diğer durumlarda dokunulmaz: bir story yalnız bir kez otomatik akışa alınır (çift tetik yok).
- Her issue kendi işleminde işlenir: biri hata verirse atlanır, diğerleri sürer. Jira
  erişilemezse tur boş geçer, sonraki tura kalır.
- Ayar kapalıysa Jira'ya gidilmez; iş yalnız kendini yeniden planlar.

Tetik Jira'ya yalnız okur (§4); ön incelemenin kendi yazma yolları (yorum/etiket) değişmez. PO
kapısı korunur: tetik yalnız ön incelemeyi başlatır, PO onayını atlatmaz.

**Otomatik case üretimi** (Y2): Jira PO etiketiyle `po_approved`'a giren gereksinimde
`qa_tetik_zamani` doluysa ve `otomatik_case` açıksa `flow.po_check` aynı işlemde
`po_onayi_sonrasi`'nı çağırır → `requirements.otomatik_case` işi kuyruğa girer →
`cases.service.start_generation(..., JIRA_TETIK_AKTORU)`. Kapı reddederse denetime yazılır,
gereksinim olduğu gibi kalır (analist elle başlatabilir). Elle çekilmiş gereksinim
(`qa_tetik_zamani` NULL) etkilenmez.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.orm import Session

from tp_core.audit.session import audit_on_commit
from tp_core.features.otomasyon import ayarlar
from tp_core.features.requirements import flow, services
from tp_core.models import Requirement, session_scope
from tp_core.workflow.jobs import enqueue, idempotency_lock
from tp_core.workflow.service import WorkflowError

log = logging.getLogger("tp_core.features.otomasyon.jira_tetik")

JOB_JIRA_TETIK = "requirements.jira_tetik"
JOB_OTOMATIK_CASE = "requirements.otomatik_case"

# Otomasyonun principal'ı (insan değil; rol kapıları bilinçli olarak atlanır, K4/K5). Ş1'in
JIRA_TETIK_AKTORU = ayarlar.OTOMASYON_AKTORU
# Jira'dan çekme (upsert) ve tetik denetim kayıtlarının aktörü.
CEKIM_AKTORU = "jira-tetik"

ARAMA_SINIRI = 200
TUR_SAKLAMA = timedelta(hours=1)
SON_TETIKLENEN_SAYISI = 10

_KONTROL = re.compile(r"[\x00-\x1f\x7f]")


# ------------------------------------------------------------------------------ JQL


def jql_dizesi(deger: str) -> str:
    """JQL çift tırnaklı dize: `\\` ve `"` kaçışlı, kontrol karakterleri boşluk."""
    temiz = _KONTROL.sub(" ", deger)
    return '"' + temiz.replace("\\", "\\\\").replace('"', '\\"') + '"'


def tetik_jql(proje: str, durum: str) -> str:
    if not flow._PROJE_RE.match(proje):
        raise flow.FlowInputError(f"Geçersiz JIRA_PROJECT: {proje!r}")
    return (
        f"project = {proje} AND issuetype = Story AND status = {jql_dizesi(durum)} ORDER BY key ASC"
    )


def _ayni_durum(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


# ------------------------------------------------------------------------- tetik turu


def issue_isle(s: Session, issue: Any, durum: str) -> str:
    """Tek issue: çek, `jira_durumu` yaz; ilk kez geliyorsa ön incelemeyi başlat."""
    cekim = flow.upsert_issue(s, issue, CEKIM_AKTORU)
    req = s.scalars(
        select(Requirement).where(Requirement.jira_key == issue.key).with_for_update()
    ).one()
    req.jira_durumu = (issue.status or durum)[:200]
    if req.durum != "new" or req.qa_tetik_zamani is not None:
        return f"dokunulmadi:{cekim}"
    req.qa_tetik_zamani = flow.now()
    basladi = flow.start_review(s, req, JIRA_TETIK_AKTORU)
    audit_on_commit(
        s,
        CEKIM_AKTORU,
        "requirements.jira_tetik",
        f"requirement:{req.id}",
        {
            "jira_key": issue.key,
            "durum": req.jira_durumu,
            "cekim": cekim,
            "workflow_id": basladi.workflow_id,
            "job_id": basladi.job_id,
        },
    )
    return "tetiklendi"


def tur(engine: Engine | None = None, jira: Any = None) -> dict[str, Any]:
    """Bir tetik turu; dönen özet iş sonucuna (`job.sonuc`) yazılır."""
    with session_scope() as s:
        ayar = ayarlar.jira_tetik(s)
    ozet: dict[str, Any] = {
        "zaman": flow.now(),
        "acik": ayar.acik,
        "durum": ayar.durum,
        "bulunan": 0,
        "tetiklenen": 0,
        "hata": None,
        "tetiklenenler": [],
        "hatalar": [],
        "sonuc": {},
    }
    if not ayar.acik:
        return ozet
    try:
        jql = tetik_jql(flow.settings().jira_project, ayar.durum)
        issues = (jira or services.jira()).search(jql, ARAMA_SINIRI)
    except Exception as exc:  # Jira erişilemedi / yapılandırma: sonraki tura kalır
        log.warning("Jira tetiği: arama başarısız: %s", exc)
        ozet["hata"] = f"Jira'ya erişilemedi: {type(exc).__name__}: {exc}"[:300]
        return ozet
    for issue in issues:
        if issue.issue_type and issue.issue_type != "Story":
            continue
        if issue.status and not _ayni_durum(issue.status, ayar.durum):
            continue  # arama ile okuma arasında durum değişmiş
        ozet["bulunan"] += 1
        try:
            with session_scope() as s:
                sonuc = issue_isle(s, issue, ayar.durum)
        except Exception as exc:  # tek issue'nun hatası turu durdurmaz
            log.warning("Jira tetiği: %s işlenemedi: %s", issue.key, exc)
            metin = (str(exc).strip() or type(exc).__name__)[:200]
            ozet["hatalar"].append({"jira_key": issue.key, "hata": metin})
            ozet["sonuc"][issue.key] = "hata"
            continue
        ozet["sonuc"][issue.key] = sonuc
        if sonuc == "tetiklendi":
            ozet["tetiklenenler"].append(issue.key)
    ozet["tetiklenen"] = len(ozet["tetiklenenler"])
    if ozet["hatalar"]:
        ozet["hata"] = f"{len(ozet['hatalar'])} story işlenemedi: " + ", ".join(
            h["jira_key"] for h in ozet["hatalar"]
        )
    return ozet


# --------------------------------------------------------------------------- zamanlama


def ensure(conn: Connection, *, gecikme_s: float = 0.0) -> uuid.UUID | None:
    """Tetik işini (kuyrukta bekleyen yoksa) ekler; tek bekleyen iş kuralı advisory lock ile."""
    idempotency_lock(conn, JOB_JIRA_TETIK)
    bekleyen = conn.execute(
        text("SELECT id FROM job WHERE tur = :t AND durum IN ('queued', 'retry') LIMIT 1"),
        {"t": JOB_JIRA_TETIK},
    ).scalar_one_or_none()
    if bekleyen is not None:
        return None
    zaman = flow.now() + timedelta(seconds=gecikme_s) if gecikme_s > 0 else None
    return enqueue(conn, JOB_JIRA_TETIK, {}, run_after=zaman)


def yeniden_planla(engine: Engine | None = None) -> datetime:
    """Sonraki turu `aralik_s` sonrasına planlar (ayar kapalıyken de: açılınca devreye girer)."""
    with session_scope() as s:
        aralik = ayarlar.jira_tetik(s).aralik_s
        ensure(s.connection(), gecikme_s=aralik)
    return flow.now() + timedelta(seconds=aralik)


def eski_turlari_sil(engine: Engine, saklama: timedelta = TUR_SAKLAMA) -> int:
    """Bitmiş tur işlerini siler; son taramalı tur (API'nin `son_tur`'u) hep kalır."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "DELETE FROM job WHERE tur = :t AND durum IN ('done', 'failed', 'cancelled') "
                "AND COALESCE(bitis, guncelleme) < now() - make_interval(secs => :sn) "
                "AND id <> COALESCE((SELECT id FROM job WHERE tur = :t AND durum = 'done' "
                "AND sonuc ? 'bulunan' AND (sonuc->>'acik')::boolean "
                "ORDER BY bitis DESC NULLS LAST LIMIT 1), "
                "'00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            {"t": JOB_JIRA_TETIK, "sn": saklama.total_seconds()},
        ).rowcount


# ------------------------------------------------------------------ otomatik case üretimi


def po_onayi_sonrasi(s: Session, req: Requirement) -> uuid.UUID | None:
    """`po_check` PO etiketiyle `po_approved`'a geçişten hemen sonra (aynı işlemde) çağırır.

    Yalnız tetikle akışa alınmış (`qa_tetik_zamani` dolu) gereksinimde ve `otomatik_case`
    açıkken `requirements.otomatik_case` işini kuyruğa alır; aksi halde hiçbir şey yapmaz.
    """
    if req.qa_tetik_zamani is None:
        return None
    if not ayarlar.jira_tetik(s).otomatik_case:
        return None
    onay = req.po_onay_zamani.isoformat() if req.po_onay_zamani else ""
    return enqueue(
        s.connection(),
        JOB_OTOMATIK_CASE,
        {"requirement_id": str(req.id), "po_onay_zamani": onay},
        idempotency_key=f"{JOB_OTOMATIK_CASE}:{req.id}:{onay}",
    )


def otomatik_case_baslat(yuk: dict[str, Any]) -> dict[str, Any]:
    """`requirements.otomatik_case` işinin gövdesi: case üretimini otomasyon aktörüyle başlatır."""
    from tp_core.features.cases import service as cases_service

    req_id = uuid.UUID(str(yuk["requirement_id"]))
    with session_scope() as s:
        req = s.get(Requirement, req_id, with_for_update=True)
        if req is None:
            return {"durum": "atlandi", "neden": "gereksinim yok"}
        nesne = f"requirement:{req.id}"
        temel = {"jira_key": req.jira_key, "tetikleyen": "jira-po-onayi"}
        if not ayarlar.jira_tetik(s).otomatik_case:
            audit_on_commit(s, CEKIM_AKTORU, "requirements.otomatik_case", nesne,
                            {**temel, "sonuc": "kapali"})  # fmt: skip
            return {"durum": "kapali"}
        if req.durum != "po_approved" or req.qa_tetik_zamani is None:
            # Analist elle başlatmış ya da onay geri çekilmiş: dokunma.
            return {"durum": "atlandi", "neden": f"gereksinim durumu {req.durum}"}
        try:
            with s.begin_nested():
                out = cases_service.start_generation(s, req.id, JIRA_TETIK_AKTORU)
        except WorkflowError as exc:
            neden = (str(exc).strip() or type(exc).__name__)[:300]
            audit_on_commit(s, CEKIM_AKTORU, "requirements.otomatik_case", nesne,
                            {**temel, "sonuc": "reddedildi", "neden": neden})  # fmt: skip
            return {"durum": "reddedildi", "neden": neden}
        audit_on_commit(
            s, CEKIM_AKTORU, "requirements.otomatik_case", nesne,
            {**temel, "sonuc": "baslatildi", "job_id": out["job_id"],
             "uretim_no": out["uretim_no"]},
        )  # fmt: skip
        return {"durum": "baslatildi", "job_id": out["job_id"], "uretim_no": out["uretim_no"]}


# ------------------------------------------------------------------------- durum (API)


def durum_ozeti(s: Session) -> dict[str, Any]:
    """`GET /automation/jira-trigger` gövdesi."""
    ayar = ayarlar.jira_tetik(s)
    son = s.execute(
        text(
            "SELECT sonuc FROM job WHERE tur = :t AND durum = 'done' AND sonuc ? 'bulunan' "
            "AND (sonuc->>'acik')::boolean ORDER BY bitis DESC NULLS LAST LIMIT 1"
        ),
        {"t": JOB_JIRA_TETIK},
    ).scalar_one_or_none()
    son_tur = None
    if isinstance(son, dict):
        son_tur = {
            "zaman": son.get("zaman"),
            "bulunan": int(son.get("bulunan") or 0),
            "tetiklenen": int(son.get("tetiklenen") or 0),
            "hata": son.get("hata"),
        }
    satirlar = s.execute(
        text(
            "SELECT ozet->>'jira_key' AS jira_key, zaman FROM audit_event "
            "WHERE eylem = 'requirements.jira_tetik' ORDER BY id DESC LIMIT :n"
        ),
        {"n": SON_TETIKLENEN_SAYISI},
    ).all()
    return {
        "acik": ayar.acik,
        "durum": ayar.durum,
        "aralik_s": ayar.aralik_s,
        "son_tur": son_tur,
        "son_tetiklenenler": [{"jira_key": r.jira_key, "zaman": r.zaman} for r in satirlar],
    }
