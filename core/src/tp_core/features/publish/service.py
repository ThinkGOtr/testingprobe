"""`publish_test_cases` (TEKNIK-TASARIM §8.3): onaylı case'leri test yönetimine yazar.

- **Girdi:** yalnızca case kimlikleri; içerik kabul edilmez (portal `POST /publish` ve IDE
  `publish_test_cases` aynı yolu kullanır).
- **Kontrol (worker, her case için, yazmadan hemen önce ve sonra):** durum `approved` ve
  `approved_hash_matches` (son insan kararı Analistin son onayı `approve`, `review.onaylanan_hash ==
  test_case.icerik_hash == test_case.onaylanan_hash`) **ve** gereksinim `cases_ready|done` ve PO
  onayı güncel içerikte (`onaylanan_hash == content_hash_of(req)`; story değişip PO onayı
  sıfırlandıysa eski metnin case'i yayınlanmaz). Değilse o case yayınlanmaz.
- **Mevcut issue:** adaptör `tp-<uuid>` etiketli issue bulursa onu döndürür ve içeriğini
  güncellemez. Bu yüzden yazmadan önce bulunan issue'nun açıklamasındaki onaylanan içerik hash'i
  güncel hash'le karşılaştırılır; farklıysa (onaydan sonra düzeltilmiş case) yayın açık hatayla
  durur (Jira'da eski içerik "yayınlandı" sayılmaz).
- **Üretim modu:** Test issue'suna `tp-mod-<mod>` etiketi ve "Üretim modu: REPLAY/…" yorumu,
  story yorumuna mod özeti yazılır (REPLAY çıktısı canlı AI gibi görünmez).
- **Idempotency:** `external_ref` (anahtar `publish:<hedef>:test_case:<id>:<icerik_hash>`): önce
  `intent` yazılıp commit edilir, sonra dış çağrı, sonra `created` + anahtar. Adaptör yazmadan önce
  `tp-<uuid>` etiketiyle arar (`find_existing`); yeniden denemede ikinci issue açılmaz. Aynı hash
  `created` ise çağrı yapılmaz.
- **Kısmi başarı:** her case ayrı sonuçlanır (`created` | `exists` | `failed` + hata).
- **Gereksinim:** tüm onaylı case'ler yayınlanmış ve karar/son onay bekleyen (`draft`/`ready`)
  case kalmamışsa `cases_ready → done`. Story'ye yayın özeti ve denetim zincirinin son hash'i
  Jira yorumu olarak yazılır (§3/8).

Jira/Xray yazma kimlikleri yalnızca core-worker'dadır (MIMARI-SOZLESME §6): core-api işi kuyruğa
koyar (`request_publish`) ve sonucunu bekler (`await_job`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit, chain_tip
from tp_core.auth.yetki import izinli
from tp_core.events.bus import publish_tx
from tp_core.features.cases.service import get_requirement, requirement_change_reason
from tp_core.integrations import jira_notify
from tp_core.integrations.jira import get_jira_settings
from tp_core.integrations.jira_adf import strip_bot_header
from tp_core.integrations.testmgmt import (
    AI_LABEL,
    RELATES_LINK,
    TEST_LINK,
    CaseContent,
    case_description_adf,
)
from tp_core.models import (
    AppUser,
    ExternalRef,
    Requirement,
    Review,
    TestCase,
    session_scope,
)
from tp_core.ports import JiraPort, TestManagementPort
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue
from tp_core.workflow.service import (
    APPROVING,
    ApprovalNotAllowed,
    InvalidDecision,
    Principal,
    approved_hash_matches,
    eski_analist_onayi,
    latest_review,
    transition,
)

PUBLISH_JOB = "publish.cases"
# Taze `intent` (başka iş yazıyor) bu süre boyunca beklenir; daha eskisi yarım kalmış sayılır ve
# adaptörün `tp-<uuid>` aramasıyla (find_existing) güvenle yeniden denenir.
INTENT_KILIT_S = 120
MAX_CASE = 100
BEKLEME_S = 45.0
YOKLAMA_S = 0.25
STORY_YOK = "Serbest metin gereksinimin Jira story'si yok; Test issue story'ye bağlanamaz"


# ----------------------------------------------------------------------- hedefler


class IcerikFarkli(Exception):
    """Jira'da bu case için başka içerikle açılmış issue var (adaptör güncellemez)."""

    def __init__(self, mesaj: str, external_key: str | None) -> None:
        super().__init__(mesaj)
        self.external_key = external_key


@dataclass
class Targets:
    tm: TestManagementPort
    jira: JiraPort | None  # yayın özeti yorumu için (yoksa yorum yazılmaz)


def default_targets() -> Targets:
    from tp_core.integrations.jira import get_jira
    from tp_core.integrations.testmgmt import get_test_management

    s = get_jira_settings()
    jira = get_jira(s)
    return Targets(get_test_management(s, jira=jira), jira)


_targets_factory: Callable[[], Targets] = default_targets


def set_targets_factory(factory: Callable[[], Targets] | None) -> None:
    """Testler için hedef fabrikası (None → varsayılan: TP_TEST_MGMT + JIRA_* ortamı)."""
    global _targets_factory
    _targets_factory = factory or default_targets


# ----------------------------------------------------------------- ortak yardımcılar


def approver_of(session: Session, tc: TestCase) -> str | None:
    """Son onaylayan: Analistin `approve`'u ya da 012 öncesi analist `edit`'i."""
    son = next(
        (
            r
            for r in session.scalars(
                select(Review)
                .where(
                    Review.nesne_turu == "test_case",
                    Review.nesne_id == tc.id,
                    Review.karar.in_((*APPROVING["test_case"], "edit")),
                )
                .order_by(Review.sira.desc())
            )
            if r.karar in APPROVING["test_case"] or eski_analist_onayi(session, r)
        ),
        None,
    )
    if son is None or son.user_id is None:
        return None
    return session.scalar(select(AppUser.kullanici_adi).where(AppUser.id == son.user_id))


def case_mapping(session: Session, tc: TestCase) -> dict[str, Any]:
    """Adaptöre giden case (şema + kimlik + onaylayan + onaylanan hash + üretim modu)."""
    mod = mode_of(tc)
    return {
        **tc.icerik,
        "id": str(tc.id),
        "onaylayan": approver_of(session, tc),
        "onaylanan_hash": tc.onaylanan_hash,
        "uretim_modu": MOD_ETIKETI.get(mod, mod.upper()),
    }


def _created_ref(session: Session, cid: uuid.UUID) -> ExternalRef | None:
    return session.scalars(
        select(ExternalRef)
        .where(
            ExternalRef.entity_turu == "test_case",
            ExternalRef.entity_id == cid,
            ExternalRef.durum == "created",
        )
        .order_by(ExternalRef.guncelleme.desc())
        .limit(1)
    ).first()


def idempotency_key(hedef: str, tc: TestCase) -> str:
    return f"publish:{hedef}:test_case:{tc.id}:{tc.icerik_hash}"


def _engel(session: Session, tc: TestCase) -> str | None:
    """Yayın engeli (None = yayınlanabilir). Kararlar Postgres'teki onay kaydından okunur."""
    if tc.durum != "approved":
        if tc.durum == "ready":
            return "Analist son onayı bekleniyor (durum: ready)"
        return f"Onaylı değil (durum: {tc.durum})"
    if not approved_hash_matches(session, tc):
        son = latest_review(session, "test_case", tc.id)
        if (
            son is not None
            and son.karar not in APPROVING["test_case"]
            and not eski_analist_onayi(session, son)
        ):
            # Son karar onaylayan değil (ör. Testçi `edit`'i): yayın Analist son onayıyla açılır.
            return (
                f"Analist son onayı yok (son karar: {son.karar}); Taslağa alıp yeniden kabul "
                "ve son onay gerekir"
            )
        return "İçerik onaydan sonra değişmiş (onaylanan hash ≠ güncel hash)"
    gerekce = requirement_change_reason(session.get(Requirement, tc.requirement_id))
    if gerekce is not None:
        return gerekce
    return None


# ---------------------------------------------------------------------- üretim modu

MOD_ETIKETI = {
    "replay": "REPLAY (hazırlanmış veya kayıtlı örnek çıktı; canlı model çağrısı yapılmadı)",
    "replay_miss": "REPLAY-MISS (birebir kayıt yok; adlandırılmış golden kayıt kullanıldı)",
    "live": "CANLI (model geçidi)",
    "ide": "IDE (Claude Code; ürünün model geçidinden geçmedi)",
}


def mode_of(tc: TestCase) -> str:
    """Case'in üretim modu: `replay | replay_miss | live`, IDE taslağında `ide`."""
    if tc.kanal == "ide" or not tc.uretim_modu:
        return "ide" if tc.kanal == "ide" else "bilinmiyor"
    return tc.uretim_modu


def mode_label(mod: str) -> str:
    """Jira etiketi (boşluksuz): `tp-mod-replay`, `tp-mod-replay-miss`, `tp-mod-ide`."""
    return "tp-mod-" + mod.replace("_", "-")


def mode_comment(mod: str) -> str:
    return f"Testing Probe — Üretim modu: {MOD_ETIKETI.get(mod, mod.upper())}"


def _hash_izi(icerik_hash: str) -> str:
    return f"onaylanan içerik hash: {icerik_hash}"


# ---------------------------------------------------------------------- önizleme


def preview_payload(hedef: str, proje: str, content: CaseContent, story_key: str) -> dict[str, Any]:
    """Adaptörün göndereceği gövdenin birebir kopyası (oluşturma + story bağlantısı)."""
    link = {
        "type": {"name": TEST_LINK},
        "inwardIssue": {"key": "<oluşturulacak>"},
        "outwardIssue": {"key": story_key},
    }
    if hedef == "xray":
        from tp_core.integrations.xray import XrayTestManagement

        # _payload yalnızca proje adını kullanır; istemci gerekmez (gönderilen gövdeyle aynı kod).
        govde = XrayTestManagement(None, None, proje)._payload(content, story_key)  # type: ignore[arg-type]
        return {"xray_import": [govde], "issue_link": link}
    fields: dict[str, Any] = {
        "project": {"key": proje},
        "issuetype": {"name": "Test"},
        "summary": content.title[:255],
        "labels": list(dict.fromkeys([AI_LABEL, content.tp_label])),
        "description": case_description_adf(content, story_key),
    }
    return {"jira_issue": {"fields": fields}, "issue_link": link}


def preview(session: Session, requirement_id: uuid.UUID) -> dict[str, Any]:
    """`GET /publish/preview`: hedef başına gönderilecek gövde (dry-run; dış çağrı yok)."""
    req = get_requirement(session, requirement_id)
    s = get_jira_settings()
    hedef, proje = s.test_mgmt, s.jira_project
    cases = session.scalars(
        select(TestCase)
        .where(
            TestCase.requirement_id == req.id,
            TestCase.durum.notin_(("superseded", "rejected")),
        )
        .order_by(TestCase.uretim_no, TestCase.sira_no)
    ).all()
    uyarilar: list[str] = []
    if not req.jira_key:
        uyarilar.append(STORY_YOK + "; yayın engellenir.")
    if hedef == "jira":
        uyarilar.append(
            f"Projede 'Test' issue türü yoksa 'Task' + 'test-case' etiketi; '{TEST_LINK}' "
            f"bağlantı türü yoksa '{RELATES_LINK}' kullanılır."
        )
    gereksinim_engeli = requirement_change_reason(req)
    if gereksinim_engeli is not None:
        uyarilar.append(gereksinim_engeli + "; onaylı case'ler yayınlanamaz.")
    kalemler = []
    for tc in cases:
        ref = _created_ref(session, tc.id)
        if tc.durum == "published":
            islem = "skip_existing"
        elif tc.durum != "approved":
            islem = "blocked_not_approved"
        elif not approved_hash_matches(session, tc):
            islem = "blocked_hash_mismatch"
        elif gereksinim_engeli is not None:
            islem = "blocked_requirement_changed"
        elif not req.jira_key:
            islem = "blocked_no_story"
        else:
            islem = "create"
        content = CaseContent.from_mapping(case_mapping(session, tc))
        story_key = req.jira_key or ""
        mod = mode_of(tc)
        payload = preview_payload(hedef, proje, content, story_key)
        # Oluşturmadan sonra aynı issue'ya eklenen üretim modu etiketi ve yorumu (birebir).
        payload["mod_etiketi"] = mode_label(mod)
        payload["mod_yorumu"] = mode_comment(mod)
        kalemler.append(
            {
                "case_id": str(tc.id),
                "title": content.title,
                "issue_type": "Test",
                "summary": content.title[:255],
                "labels": [AI_LABEL, content.tp_label, mode_label(mod)],
                "uretim_modu": mod,
                "link": {"type": TEST_LINK, "story_key": req.jira_key},
                "adim_sayisi": len(content.steps),
                "islem": islem,
                "external_key": ref.external_key if ref else None,
                "icerik_hash": tc.icerik_hash,
                "onaylayan": content.approved_by,
                "payload": payload,
            }
        )
    return {
        "requirement_id": str(req.id),
        "hedef": hedef,
        "proje": proje,
        # Kullanıcıya gösterilen Jira bağlantı kökü (yerelde jira-sim'in host adresi).
        "jira_browse_url": (s.jira_browse_url or s.jira_base_url).rstrip("/"),
        "kalemler": kalemler,
        "uyarilar": uyarilar,
    }


# ------------------------------------------------------------------- kuyruğa alma


def _parse_ids(case_ids: Sequence[Any]) -> list[uuid.UUID]:
    if not isinstance(case_ids, Sequence) or isinstance(case_ids, str | bytes) or not case_ids:
        raise InvalidDecision("En az bir case seçilmeli")
    if len(case_ids) > MAX_CASE:
        raise InvalidDecision(f"Tek yayında en fazla {MAX_CASE} case")
    try:
        ids = [uuid.UUID(str(c)) for c in case_ids]
    except ValueError as exc:
        raise InvalidDecision("case_ids geçerli uuid listesi olmalı") from exc
    return list(dict.fromkeys(ids))


def request_publish(
    session: Session,
    case_ids: Sequence[Any],
    user: Principal,
    *,
    tool_call_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Yayın işini kuyruğa koyar (çağıranın işleminde). Kontroller worker'da yapılır."""
    if user.id is None:
        raise InvalidDecision("yayın oturumlu kullanıcıyla istenir")
    if user.kanal == "ide" and user.kapsam != "publish":
        raise InvalidDecision("yayın için 'publish' kapsamlı token gerekir")
    # Derinlemesine savunma: portal ucu `case.publish` ister; IDE token'ı da yayın yetkili rolün
    # (Testçi) olmalıdır (token rolü üretim anındaki hesabın rolüdür).
    if not izinli(user.rol, "case.publish"):
        raise ApprovalNotAllowed(f"{user.rol} rolü case yayınlayamaz")
    ids = _parse_ids(case_ids)
    isteyen = {**user.as_dict(), "kanal": user.kanal}
    job_id = enqueue(
        session.connection(),
        PUBLISH_JOB,
        {
            "case_ids": [str(i) for i in ids],
            "isteyen": isteyen,
            "tool_call_id": str(tool_call_id) if tool_call_id else None,
        },
    )
    audit_on_commit(
        session,
        user.kullanici_adi if user.kanal == "portal" else f"{user.kanal}:{user.kullanici_adi}",
        "publish.requested",
        f"job:{job_id}",
        {"case_ids": ids, "kanal": user.kanal},
    )
    return job_id


def job_status(engine: Engine, job_id: uuid.UUID) -> tuple[str, Any, str | None]:
    with engine.connect() as c:
        row = c.execute(
            text("SELECT durum, sonuc, son_hata FROM job WHERE id = :id"), {"id": job_id}
        ).one()
    return row.durum, row.sonuc, row.son_hata


async def await_job(
    engine: Engine, job_id: uuid.UUID, timeout_s: float | None = None
) -> tuple[str, Any, str | None]:
    """İş bitene (done/failed/cancelled) ya da süre dolana kadar bekler; (durum, sonuç, hata)."""
    sure = BEKLEME_S if timeout_s is None else timeout_s
    with anyio.move_on_after(sure):
        while True:
            durum, sonuc, hata = await anyio.to_thread.run_sync(job_status, engine, job_id)
            if durum in ("done", "failed", "cancelled"):
                return durum, sonuc, hata
            await anyio.sleep(YOKLAMA_S)
    return await anyio.to_thread.run_sync(job_status, engine, job_id)


# ------------------------------------------------------------------- yayın (worker)


def _sonuc(
    cid: Any, durum: str, key: str | None = None, hata: str | None = None, **ek: Any
) -> dict[str, Any]:
    return {"case_id": str(cid), "durum": durum, "external_key": key, "hata": hata, **ek}


def _sahibi_calisiyor(session: Session, cid: uuid.UUID, job_id: uuid.UUID | None) -> bool:
    """Bu case'i içeren ve hâlâ `running` olan BAŞKA bir yayın işi var mı?

    Taze `intent`'in sahibi ölmüşse (worker çöktü, `release_orphans`/`reap_stale` işi bıraktı ya
    da bu, aynı işin yeniden denemesi) beklemeye gerek yoktur: adaptörün `tp-<uuid>` araması
    (`find_existing`) mükerrer issue açmadan devam eder.
    """
    return bool(
        session.execute(
            text(
                "SELECT 1 FROM job WHERE tur = :t AND durum = 'running' "
                "AND id IS DISTINCT FROM :j AND (yuk -> 'case_ids') @> CAST(:c AS jsonb) LIMIT 1"
            ),
            {"t": PUBLISH_JOB, "j": job_id, "c": json.dumps([str(cid)])},
        ).first()
    )


def _mevcut_issue_engeli(
    t: Targets, cid: uuid.UUID, title: str, icerik_hash: str
) -> tuple[str | None, str | None]:
    """(mevcut issue anahtarı, engel). Adaptör bulunan issue'yu güncellemez; içerik farklıysa dur.

    Jira'daki issue başka (eski) bir onaylı içerikle açılmışsa onu "yayınlandı" saymak, onaylanan
    içerikle Jira'daki içeriğin ayrışması demektir (Constitution I, §8.3).
    """
    if t.jira is None:
        return None, None
    key = t.tm.find_existing(cid)
    if key is None:
        return None, None
    issue = t.jira.get_issue(key)
    if _hash_izi(icerik_hash) in (issue.description or "") and issue.summary == title[:255]:
        return key, None
    return key, (
        f"Jira'da bu case için farklı (eski) içerikle açılmış {key} var; adaptör mevcut issue'yu "
        "güncellemez. Onaylı içerik yayınlanmadı: issue'yu Jira'da onaylı içerikle güncelleyin ya "
        f"da 'tp-{cid}' etiketini kaldırıp yeniden yayınlayın."
    )


def _mod_isaretle(jira: JiraPort | None, key: str, mod: str) -> None:
    """Test issue'suna üretim modu etiketi ve (bir kez) yorumu (REPLAY canlı AI gibi görünmesin)."""
    if jira is None:
        return
    jira.add_labels(key, [mode_label(mod)])
    yorum = mode_comment(mod)
    if not any(yorum in (c.body or "") for c in jira.get_comments(key)):
        jira.add_comment(key, yorum)


def _po_etiket_engelleri(ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Jira etiketiyle PO onaylı gereksinimlerde etiketin ŞU AN durduğunu denetler (case → engel).

    Etiket kaldırıldıktan sonra PO sorgusu (`TP_PO_POLL_S`) gereksinimi `new`'e alana kadar DB
    durumu hâlâ "onaylı" görünür; bu pencerede yayın, geri çekilmiş onayla Jira'ya Test issue
    yazardı. Gereksinim başına bir kez, dış çağrıdan önce; Jira okunamazsa fail-closed.
    """
    from tp_core.features.cases.service import _jira_po_etiketi_denetle
    from tp_core.workflow.service import WorkflowError

    if not ids:
        return {}
    engeller: dict[uuid.UUID, str] = {}
    with session_scope() as s:
        satirlar = s.execute(
            select(TestCase.id, TestCase.requirement_id).where(
                TestCase.id.in_(ids), TestCase.durum == "approved"
            )
        ).all()
        req_engeli: dict[uuid.UUID, str | None] = {}
        for rid in sorted({r for _, r in satirlar}, key=str):
            req = s.get(Requirement, rid)
            if req is None or req.po_onay_kaynagi != "jira_label":
                req_engeli[rid] = None
                continue
            try:
                _jira_po_etiketi_denetle(req)
                req_engeli[rid] = None
            except WorkflowError as exc:
                req_engeli[rid] = str(exc)
        for cid, rid in satirlar:
            if req_engeli.get(rid):
                engeller[cid] = req_engeli[rid]  # type: ignore[assignment]
    return engeller


def _publish_one(
    t: Targets,
    cid: uuid.UUID,
    aktor: str,
    job_id: uuid.UUID | None = None,
    po_engeli: str | None = None,
) -> dict[str, Any]:
    tm = t.tm
    hedef = tm.name
    with session_scope() as s:
        tc = s.get(TestCase, cid, with_for_update=True)
        if tc is None:
            return _sonuc(cid, "failed", hata="Case bulunamadı")
        if tc.durum == "published":
            ref = _created_ref(s, cid)
            return _sonuc(
                cid, "exists", ref.external_key if ref else None, url=ref.url if ref else None
            )
        engel = _engel(s, tc) or po_engeli
        if engel:
            return _sonuc(cid, "failed", hata=engel)
        req = s.get(Requirement, tc.requirement_id)
        if req is None or not req.jira_key:
            return _sonuc(cid, "failed", hata=STORY_YOK)
        anahtar = idempotency_key(hedef, tc)
        ref = s.scalars(select(ExternalRef).where(ExternalRef.idempotency_key == anahtar)).first()
        if ref is not None and ref.durum == "created":
            # Önceki deneme dışarıda oluşturdu ama durum geçişi yazılamadı: dış çağrı yok.
            transition(
                s, tc, "published", aktor, "approved", ozet={"external_key": ref.external_key}
            )
            return _sonuc(cid, "exists", ref.external_key, url=ref.url)
        if (
            ref is not None
            and ref.durum == "intent"
            and datetime.now(UTC) - ref.guncelleme < timedelta(seconds=INTENT_KILIT_S)
            and _sahibi_calisiyor(s, cid, job_id)
        ):
            # Başka bir iş bu case'i şu an yazıyor: ikinci create (mükerrer issue) açılmaz.
            return _sonuc(cid, "failed", hata="Bu case için yayın sürüyor; biraz sonra deneyin")
        if ref is None:
            ref = ExternalRef(
                entity_turu="test_case",
                entity_id=tc.id,
                sistem=hedef,
                idempotency_key=anahtar,
                durum="intent",
            )
            s.add(ref)
        else:
            ref.durum = "intent"
            ref.hata = None
            ref.guncelleme = datetime.now(UTC)
        mapping = case_mapping(s, tc)
        story_key = req.jira_key
        icerik_hash = tc.icerik_hash
        baslik = str(tc.icerik.get("title") or "")
        mod = mode_of(tc)
        # intent commit edilir: dış çağrıdan sonra çöksek de kayıt (ve tp-<uuid> araması) kalır.
    try:
        mevcut, engel = _mevcut_issue_engeli(t, cid, baslik, icerik_hash)
        if engel is not None:
            raise IcerikFarkli(engel, mevcut)
        yayin = tm.publish_case(mapping, story_key)
        _mod_isaretle(t.jira, yayin.external_key, mod)
    except Exception as exc:
        kismi = getattr(exc, "external_key", None)
        if kismi is None and "yayin" in locals():
            kismi = yayin.external_key
        with session_scope() as s:
            ref = s.scalars(select(ExternalRef).where(ExternalRef.idempotency_key == anahtar)).one()
            ref.durum = "failed"
            ref.hata = f"{type(exc).__name__}: {exc}"[:2000]
            ref.external_key = kismi or ref.external_key
            audit_on_commit(
                s,
                aktor,
                "publish.failed",
                f"test_case:{cid}",
                {"hedef": hedef, "hata": ref.hata, "kismi": kismi},
            )
            rid = s.scalar(select(TestCase.requirement_id).where(TestCase.id == cid))
            publish_tx(
                s.connection(),
                "publish.failed",
                {"case_id": cid, "requirement_id": rid, "hedef": hedef, "hata": ref.hata},
            )
        return _sonuc(cid, "failed", kismi, hata=str(exc)[:500])
    with session_scope() as s:
        ref = s.scalars(select(ExternalRef).where(ExternalRef.idempotency_key == anahtar)).one()
        ref.durum = "created"
        ref.external_key = yayin.external_key
        ref.url = yayin.url
        ref.hata = None
        tc = s.get(TestCase, cid, with_for_update=True)
        assert tc is not None
        engel = _engel(s, tc) if tc.durum != "published" else None
        if engel or tc.icerik_hash != icerik_hash:
            # Dış çağrı sırasında case taslağa alındı/değişti: Jira kaydı var, durum ilerlemez.
            return _sonuc(
                cid,
                "failed",
                yayin.external_key,
                hata=f"Yayın sırasında case değişti; {yayin.external_key} incelenmeli ({engel})",
            )
        if tc.durum == "approved":
            transition(
                s,
                tc,
                "published",
                aktor,
                "approved",
                ozet={
                    "external_key": yayin.external_key,
                    "hedef": hedef,
                    "hash": icerik_hash,
                    "mode": mod,
                },
            )
        return _sonuc(
            cid,
            "created",
            yayin.external_key,
            url=yayin.url,
            onaylayan=mapping.get("onaylayan"),
            mode=mod,
        )


def _complete_requirements(req_ids: set[uuid.UUID], aktor: str) -> list[str]:
    tamam: list[str] = []
    for rid in sorted(req_ids, key=str):
        with session_scope() as s:
            req = s.get(Requirement, rid, with_for_update=True)
            if req is None or req.durum != "cases_ready":
                continue
            sayim = dict(
                s.execute(
                    select(TestCase.durum, func.count())
                    .where(TestCase.requirement_id == rid)
                    .group_by(TestCase.durum)
                ).all()
            )
            if (
                sayim.get("published", 0)
                and not sayim.get("approved")
                and not sayim.get("draft")
                and not sayim.get("ready")
            ):
                transition(
                    s, req, "done", aktor, "cases_ready", sebep="onaylı case'lerin tümü yayınlandı"
                )
                tamam.append(str(rid))
    return tamam


def _unanchored(session: Session, case_ids: Sequence[str]) -> set[str]:
    """Hiçbir `publish.anchored` kaydında geçmeyen case kimlikleri."""
    if not case_ids:
        return set()
    sabit = set(
        session.execute(
            text(
                "SELECT DISTINCT x FROM audit_event, "
                "jsonb_array_elements_text(COALESCE(ozet -> 'case_ids', '[]'::jsonb)) AS x "
                "WHERE eylem = 'publish.anchored' AND (ozet -> 'case_ids') ?| CAST(:ids AS text[])"
            ),
            {"ids": list(case_ids)},
        ).scalars()
    )
    return {c for c in case_ids if c not in sabit}


def _pin_chain(
    engine: Engine,
    jira: JiraPort | None,
    story_keys: Mapping[str, list[dict[str, Any]]],
    aktor: str,
) -> list[str]:
    """Yayın özeti + denetim zincirinin son hash'i story yorumu olarak (dış sabitleme, §3/8)."""
    uyarilar: list[str] = []
    if jira is None:
        return uyarilar
    for story, kalemler in story_keys.items():
        case_ids = sorted(k["case_id"] for k in kalemler)
        anahtarlar_l = [k["external_key"] for k in kalemler if k.get("external_key")]
        if all(k.get("kurtarma") for k in kalemler):
            # Önceki deneme yayınladı ama sabitleme kaydı yok: yorum yazılmış olabilir (yorumdan
            # sonra çöküş). Jira'da bu anahtarları anan yayın yorumu varsa yalnızca kaydedilir.
            try:
                var = next(
                    (
                        c
                        for c in jira.get_comments(story)
                        if strip_bot_header(c.body or "").startswith("Testing Probe:")
                        and all(a in (c.body or "") for a in anahtarlar_l)
                    ),
                    None,
                )
            except Exception as exc:
                uyarilar.append(f"{story} yorumları okunamadı: {exc}")
                continue
            if var is not None:
                with session_scope() as s:
                    audit_on_commit(
                        s,
                        aktor,
                        "publish.anchored",
                        f"jira:{story}",
                        {
                            "comment_id": var.id,
                            "case_ids": case_ids,
                            "external_keys": anahtarlar_l,
                            "kurtarma": True,
                        },
                    )
                continue
        with engine.connect() as c:
            tip = chain_tip(c)
        anahtarlar = ", ".join(k["external_key"] for k in kalemler if k.get("external_key"))
        onaylayanlar = ", ".join(sorted({k.get("onaylayan") or "?" for k in kalemler}))
        modlar: dict[str, int] = {}
        for k in kalemler:
            modlar[k.get("mode") or "bilinmiyor"] = modlar.get(k.get("mode") or "bilinmiyor", 0) + 1
        mod_ozeti = "; ".join(
            f"{MOD_ETIKETI.get(m, m.upper())} ×{n}" for m, n in sorted(modlar.items())
        )
        govde = (
            f"Testing Probe: {len(kalemler)} AI üretimli ve insan onaylı test case yayınlandı "
            f"({anahtarlar}). Üretim modu: {mod_ozeti}. Onaylayan: {onaylayanlar}. "
            f"Yayınlayan: {aktor}. Denetim zinciri son hash: {tip}"
        )
        try:
            yorum_id = jira_notify.post_comment(jira, story, govde, jira_notify.YAYIN)
        except Exception as exc:
            uyarilar.append(f"{story} yorumuna zincir hash'i yazılamadı: {exc}")
            continue
        with session_scope() as s:
            audit_on_commit(
                s,
                aktor,
                "publish.anchored",
                f"jira:{story}",
                {
                    "comment_id": yorum_id,
                    "zincir_hash": tip,
                    "case_ids": case_ids,
                    "external_keys": anahtarlar_l,
                    "kurtarma": any(k.get("kurtarma") for k in kalemler),
                },
            )
    return uyarilar


def run_publish(ctx: JobContext, engine: Engine, targets: Targets | None = None) -> dict[str, Any]:
    """`publish.cases` işi: her case ayrı ayrı denetlenir ve yayınlanır (kısmi başarı)."""
    yuk = ctx.yuk or {}
    isteyen = yuk.get("isteyen") or {}
    if not isteyen.get("kullanici_adi"):
        raise PermanentJobError("yayın işinde isteyen yok")
    kanal = isteyen.get("kanal", "portal")
    aktor = isteyen["kullanici_adi"] if kanal == "portal" else f"{kanal}:{isteyen['kullanici_adi']}"
    try:
        ids = [uuid.UUID(str(c)) for c in yuk.get("case_ids") or []]
    except ValueError as exc:
        raise PermanentJobError("geçersiz case kimliği") from exc
    t = targets or _targets_factory()
    po_engelleri = _po_etiket_engelleri(ids)
    sonuclar = [
        _publish_one(t, cid, aktor, ctx.job_id, po_engeli=po_engelleri.get(cid)) for cid in ids
    ]

    with session_scope() as s:
        req_ids = set(s.scalars(select(TestCase.requirement_id).where(TestCase.id.in_(ids))).all())
        # Yayınlanmış ama hiç sabitlenmemiş case'ler (önceki deneme yayından sonra, story yorumundan
        # önce çöktü): bu denemede 'exists' görünürler; sabitleme yine yapılır (§3/8).
        sabitsiz = _unanchored(
            s, [r["case_id"] for r in sonuclar if r["durum"] == "exists" and r["external_key"]]
        )
        hikayeler: dict[str, list[dict[str, Any]]] = {}
        for r in sonuclar:
            if r["durum"] == "exists" and r["case_id"] in sabitsiz:
                r = {**r, "kurtarma": True}
            elif r["durum"] != "created":
                continue
            jk = s.scalar(
                select(Requirement.jira_key)
                .join(TestCase, TestCase.requirement_id == Requirement.id)
                .where(TestCase.id == uuid.UUID(r["case_id"]))
            )
            if jk:
                hikayeler.setdefault(jk, []).append(r)
        audit_on_commit(
            s,
            aktor,
            "publish.completed",
            f"job:{ctx.job_id}",
            {
                "hedef": t.tm.name,
                "kanal": kanal,
                "sonuclar": [
                    {k: r[k] for k in ("case_id", "durum", "external_key")} for r in sonuclar
                ],
            },
        )
        # Portal 202 (bekleme) modundan bu olayla çıkar; requirement_id konu eşlemesi içindir.
        publish_tx(
            s.connection(),
            "publish.completed",
            {
                "job_id": ctx.job_id,
                "requirement_id": next(iter(req_ids)) if len(req_ids) == 1 else None,
                "requirement_ids": sorted(str(r) for r in req_ids),
                "hedef": t.tm.name,
                "sonuclar": [
                    {k: r[k] for k in ("case_id", "durum", "external_key")} for r in sonuclar
                ],
            },
        )
    tamamlanan = _complete_requirements(req_ids, aktor)
    uyarilar = _pin_chain(engine, t.jira, hikayeler, aktor)
    return {
        "hedef": t.tm.name,
        "sonuclar": sonuclar,
        "tamamlanan_gereksinimler": tamamlanan,
        "uyarilar": uyarilar,
    }
