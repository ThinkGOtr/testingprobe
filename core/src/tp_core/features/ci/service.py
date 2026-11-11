"""Yerel CI ve koşu sonuçları (TEKNIK-TASARIM §8.5, §8.11; MIMARI-SOZLESME §5). AI yok (II).

Akış:

1. `enqueue_ci(session, sha, trigger, pr_number)` → `run` satırı (`queued`) + `ci.run` işi
   (idempotency `ci.run:<run_id>`) + `ci.status` olayı + denetim kaydı. Aynı commit/tetik/PR için
   kuyrukta ya da koşmakta olan bir koşu varsa yeni koşu açılmaz (o koşunun kimliği döner).
   `anahtar` verilirse (`ci_tetik.anahtar` UNIQUE) aynı anahtarla ikinci koşu asla açılmaz
   (gece zamanlayıcısı: `nightly:<tarih>`).
2. `ci.run` işi:
   - **local** (`TP_FORGE=local`): toolchain-worker `POST /check` (tüm testler, `retries=1`,
     `repeat_each=1` — CI ile aynı). `/check` `checks/<sha>.json`'u (LocalForge merge kapısının
     okuduğu `local-ci` kontrolü) kendisi yazar; çekirdek bu dosyayı yazmaz, yalnızca okuyup
     koşu kaydına tutarlılığını işler (core-worker artefakt volume'ünü salt okur).
     JUnit XML + JSON rapor `test_result` (+ `test_result_ek`) satırlarına yazılır.
   - **github**: dispatch gerekiyorsa (deploy → `repository_dispatch` `deploy`; elle gece →
     `workflow_dispatch` `tetik=nightly`) idempotent gönderilir (`external_ref`), sonra
     `ci.github_poll` işi workflow koşusunu bulana ve bitene kadar kendini yeniden planlar;
     `test-local-results` artefaktındaki junit.xml/results.json aynı ayrıştırıcıdan geçer,
     `sauce-results` içindeki Sauce job linkleri koşuya yazılır.
3. Gece: `ci.nightly` işi (idempotency `ci.nightly:<tarih>`) `TP_CI_NIGHTLY_SAAT`'te
   (varsayılan 02:00 Europe/Istanbul) koşar, `enqueue_ci(..., anahtar="nightly:<tarih>")` çağırır ve
   ertesi günü planlar. Worker açılışında plan yoksa eklenir.
"""

from __future__ import annotations

import logging
import os
import re
import time as _time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.events import publish_tx
from tp_core.features.ci import github_artifacts, services
from tp_core.features.ci.clients import (
    RESULTS_ARTIFACT,
    SAUCE_ARTIFACT,
    GitHubCiError,
    ToolchainError,
    _zip_dosyalari,
    parse_gh_time,
    surefire_dosyalari,
)
from tp_core.features.ci.parse import (
    ARIA_DOSYA_KALIPLARI,
    ERROR_CONTEXT_AD,
    ArtefaktEkleri,
    Ayristirma,
    KosuDizini,
    RaporHatasi,
    TestSatiri,
    aria_dosyalari,
    java_ayristirmasi,
    parse_files,
    parse_reports,
    sayilar,
    surefire_ayristir,
    temiz,
)
from tp_core.models import (
    ExternalRef,
    Failure,
    Job,
    Run,
    Script,
    ScriptTestCase,
    TestCase,
    TestResult,
)
from tp_core.models.ci_feature import CI_TETIK, CiTetik, RunAria, TestResultEk
from tp_core.workflow import jobs as jobq

log = logging.getLogger(__name__)

JOB_RUN = "ci.run"
JOB_GITHUB_POLL = "ci.github_poll"
JOB_NIGHTLY = "ci.nightly"

CI_RETRIES = 1
CI_REPEAT_EACH = 1
AKTIF = ("queued", "running")
BITMIS = ("passed", "failed", "error")
TOOLCHAIN_ADIMLAR = ("deps", "tsc", "eslint", "ast_guard", "run")
# Java (Appium + TestNG, 009 §2.3) yolunun adımları: toolchain `worker/java.py` `STEPS` ile aynı.
TOOLCHAIN_ADIMLAR_JAVA = ("app", "deps", "guard", "compile", "run")
# Uygulama platformları (009 §2.1); `web` mevcut Playwright/TypeScript yoludur.
UYGULAMA_PLATFORMLARI = ("android", "ios", "windows")
WEB = "web"
ISTANBUL_SABIT = timezone(timedelta(hours=3), "+03")
RUN_DIR_RE = re.compile(r"^runs/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
SAUCE_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]*saucelabs\.com/[^\s\"'<>]{1,300}$")

# Tetik → GitHub olay(lar)ı (ci.yml `on:`; elle gece workflow_dispatch ile gider).
GITHUB_OLAY = {
    "pr": ("pull_request",),
    "push": ("push",),
    "nightly": ("schedule", "workflow_dispatch"),
    "deploy": ("repository_dispatch",),
    # Elle koşu (specs/012-rol-yetki: `run.trigger_manual`) ci.yml workflow_dispatch `tetik=manual`.
    "manual": ("workflow_dispatch",),
}
# Kullanıcının portaldan başlattığı tetikler (`POST /ci/trigger`). `manual` ci_tetik tablosuna
# yazılmaz (webhook idempotency kaydı yok); koşu `run.tetik = manual` ile kaydedilir.
ELLE_TETIKLER = ("deploy", "nightly", "manual")
GITHUB_SONUC = {
    "success": "passed",
    "failure": "failed",
    "neutral": "passed",
    "skipped": "passed",
}


class CiError(ValueError):
    """Geçersiz CI isteği (API 422)."""


# =============================================================================== yardımcılar


def _istanbul() -> Any:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Istanbul")
    except Exception:  # tzdata yoksa: Türkiye 2016'dan beri sabit UTC+3
        return ISTANBUL_SABIT


def _int_env(ad: str, varsayilan: int) -> int:
    try:
        return int(float((os.environ.get(ad) or "").strip() or varsayilan))
    except ValueError:
        return varsayilan


def _etkinlik(conn: Connection, run: Run, **ek: Any) -> None:
    publish_tx(
        conn,
        "ci.status",
        {
            "id": str(run.id),
            "run_id": str(run.id),
            "durum": run.sonuc,
            "tetik": run.tetik,
            "kaynak": run.kaynak,
            "commit": run.commit,
            "pr_no": run.pr_no,
            "script_id": str(run.script_id) if run.script_id else None,
            **ek,
        },
    )


def _kaynak() -> str:
    return "github" if services.mode() == "github" else "local"


def validate_sha(sha: str | None) -> str | None:
    if sha is None:
        return None
    if not isinstance(sha, str) or not REF_RE.match(sha) or ".." in sha:
        raise CiError(f"geçersiz commit: {sha!r}")
    return sha


# =============================================================================== kuyruğa alma


def enqueue_ci(
    session: Session,
    sha: str | None,
    trigger: str,
    pr_number: int | None = None,
    *,
    isteyen: str = "system",
    anahtar: str | None = None,
    ref: str = "main",
    script_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """CI koşusunu kuyruğa alır ve `run.id` döndürür (çağıranın işleminde; commit çağırana).

    `trigger`: `pr` | `push` | `nightly` | `deploy`. `sha` None ise iş `ref`'in (main) o anki
    head'ini çözer. Codegen şeridi PR açılınca/güncellenince `('pr', pr_number)`, merge sonrası
    `('push')` ile çağırır.

    **Platform (009 §2.9):** koşunun platformu `script_id`'nin `script.platform`'udur (script yoksa
    `web`) ve `run.ortam.platform`'a yazılır. Uygulama platformunda (`android|ios|windows`) yerel
    iş toolchain `/check`'e `lang=java` + `platform` gönderir: tam kapsamlı Java koşusu merge
    kapısının okuduğu `local-ci-<platform>` kaydını yazar; GitHub kipinde platformun iş akışı
    (`mobil-android.yml` …) izlenir.
    """
    return _enqueue(
        session,
        sha,
        trigger,
        pr_number,
        isteyen=isteyen,
        anahtar=anahtar,
        ref=ref,
        script_id=script_id,
    )["run_id"]


def _enqueue(
    session: Session,
    sha: str | None,
    trigger: str,
    pr_number: int | None = None,
    *,
    isteyen: str = "system",
    anahtar: str | None = None,
    ref: str = "main",
    script_id: uuid.UUID | None = None,
    dispatch: bool = False,
) -> dict[str, Any]:
    if trigger not in CI_TETIK and trigger != "manual":
        raise CiError(f"geçersiz tetik: {trigger!r} (pr | push | nightly | deploy)")
    if trigger == "pr" and pr_number is None:
        raise CiError("pr tetiği için pr_number gerekli")
    sha = validate_sha(sha)
    if not REF_RE.match(ref) or ".." in ref:
        raise CiError(f"geçersiz ref: {ref!r}")
    kaynak = _kaynak()
    conn = session.connection()
    if anahtar is not None:
        jobq.idempotency_lock(conn, f"ci_tetik:{anahtar}")
        mevcut = session.scalar(select(CiTetik).where(CiTetik.anahtar == anahtar))
        if mevcut is not None:
            return {"run_id": mevcut.run_id, "job_id": None, "yeni": False}
    platform = script_platformu(session, script_id)
    # Aynı commit/tetik/PR/platform için etkin koşu varsa ikinci koşu açılmaz (merge sonrası main'de
    # web ve android koşuları ayrı kontrollerdir: biri ötekinin yerine geçmez).
    kilit = f"ci_aktif:{trigger}:{kaynak}:{sha or ref}:{pr_number}"
    jobq.idempotency_lock(conn, kilit if platform == WEB else f"{kilit}:{platform}")
    q = select(Run).where(
        Run.tetik == trigger,
        Run.kaynak == kaynak,
        Run.sonuc.in_(AKTIF),
        Run.pr_no.is_(None) if pr_number is None else Run.pr_no == pr_number,
        func.coalesce(Run.ortam["platform"].astext, WEB) == platform,
    )
    q = q.where(Run.commit == sha) if sha else q.where(Run.ortam["ref"].astext == ref)
    aktif = session.scalars(q.order_by(Run.olusturma.desc()).limit(1)).first()
    # İşi bitmiş (worker öldü, son deneme beklenmedik hatayla düştü) ama `queued/running`'de
    # kalmış koşu yeni tetiği sonsuza dek engellemesin: önce `error` ile kapatılır.
    if aktif is not None and anahtar is None and recover_stuck_run(session, aktif):
        aktif = None
    if (
        aktif is not None
        and anahtar is None
        and dispatch
        and kaynak == "github"
        and not (aktif.ortam or {}).get("dispatch")
    ):
        # GitHub cron'unu (02:00 UTC) bekleyen sistem gece koşusu varken sunucu elle tetikledi:
        # aynı kayıt tetiklemeye yükseltilir (yeni koşu açılmaz, istek GitHub'a gider).
        aktif.ortam = {**(aktif.ortam or {}), "dispatch": trigger, "isteyen": isteyen}
        session.flush()
        # Yoklama işi her turda `_dispatch` çağırır: hemen bir tur kuyruğa alınır.
        job_id = jobq.enqueue(
            conn,
            JOB_GITHUB_POLL,
            {"run_id": str(aktif.id), "tur": 0},
            idempotency_key=f"ci.github_poll:{aktif.id}:dispatch",
        )
        audit_on_commit(
            session,
            isteyen,
            "ci.dispatch_requested",
            f"run:{aktif.id}",
            {"tetik": trigger, "kaynak": kaynak, "job_id": str(job_id)},
        )
        return {"run_id": aktif.id, "job_id": job_id, "yeni": True}
    if aktif is not None and anahtar is None:
        return {"run_id": aktif.id, "job_id": None, "yeni": False}

    run = Run(
        id=uuid.uuid4(),
        script_id=script_id,
        pr_no=pr_number,
        commit=sha,
        kaynak=kaynak,
        tetik=trigger,
        sonuc="queued",
        ortam={
            "retries": CI_RETRIES,
            "repeat_each": CI_REPEAT_EACH,
            "isteyen": isteyen,
            "ref": None if sha else ref,
            "break_campaign": False,
            "dispatch": trigger if (dispatch and kaynak == "github") else None,
            # 009 §2.9: `script.platform` (web | android | ios | windows).
            "platform": platform,
        },
        artefaktlar={},
    )
    session.add(run)
    session.flush()
    session.add(
        CiTetik(
            anahtar=anahtar or f"{trigger}:{run.id}",
            tetik=trigger,
            kaynak=kaynak,
            run_id=run.id,
            ref=None if sha else ref,
            commit=sha,
            pr_no=pr_number,
            isteyen=isteyen,
        )
    )
    session.flush()
    job_id = jobq.enqueue(
        conn, JOB_RUN, {"run_id": str(run.id)}, idempotency_key=f"ci.run:{run.id}"
    )
    _etkinlik(conn, run)
    audit_on_commit(
        session,
        isteyen,
        "ci.queued",
        f"run:{run.id}",
        {
            "tetik": trigger,
            "kaynak": kaynak,
            "commit": sha,
            "ref": None if sha else ref,
            "pr_no": pr_number,
            "anahtar": anahtar,
            "job_id": str(job_id),
            "platform": platform,
        },
    )
    return {"run_id": run.id, "job_id": job_id, "yeni": True}


def script_platformu(session: Session, script_id: uuid.UUID | None) -> str:
    """Koşunun platformu: script'in `platform`'u; script yoksa ya da bilinmeyen değerse `web`."""
    if script_id is None:
        return WEB
    sc = session.get(Script, script_id)
    deger = getattr(sc, "platform", None) if sc is not None else None
    return deger if deger in UYGULAMA_PLATFORMLARI else WEB


def kosu_platformu(run: Run) -> str:
    """`run.ortam.platform` (eski kayıtlarda yok → `web`)."""
    deger = (run.ortam or {}).get("platform")
    return deger if deger in UYGULAMA_PLATFORMLARI else WEB


def gh_is_akisi(run: Run) -> dict[str, str]:
    """GitHub kipinde koşunun iş akışı: web `ci.yml` (varsayılan, argüman verilmez → mevcut
    istemci çağrısı değişmez), uygulama `mobil-android.yml` | `mobil-ios.yml` |
    `masaustu-windows.yml` (PR'da `pull_request` ile kendiliğinden koşar; elle gece/deploy
    `workflow_dispatch` ile aynı dosyaya gider)."""
    from tp_core.integrations.forge import GITHUB_PLATFORM_WORKFLOWS

    p = kosu_platformu(run)
    return {"workflow": GITHUB_PLATFORM_WORKFLOWS[p]} if p in UYGULAMA_PLATFORMLARI else {}


def gh_sonuc_artefakti(run: Run) -> str:
    """Sonuç artefaktının adı: web `test-local-results`, uygulama `<job>-results`
    (.github/CI.md "Uygulama iş akışları")."""
    from tp_core.integrations.forge import GITHUB_PLATFORM_CHECKS

    p = kosu_platformu(run)
    if p in UYGULAMA_PLATFORMLARI:
        return f"{GITHUB_PLATFORM_CHECKS[p]}-results"
    return RESULTS_ARTIFACT


def check_body_platformu(platform: str) -> dict[str, Any]:
    """toolchain `/check` gövdesinin dil alanları: web için boş (istek baytları değişmez), uygulama
    için `lang=java` + `platform` (toolchain `/check` Java yolu, `local-ci-<platform>` kaydı)."""
    if platform in UYGULAMA_PLATFORMLARI:
        return {"lang": "java", "platform": platform}
    return {}


def trigger_manual(session: Session, tetik: str, isteyen: str) -> dict[str, Any]:
    """Portal düğmesi (`POST /ci/trigger`): deploy | nightly | manual, main'in o anki head'inde.

    local: CI'yı main head'inde koşturur. github: iş `repository_dispatch` (deploy) ya da
    `workflow_dispatch` (`tetik=nightly|manual`) gönderir ve GitHub koşusunu alır. Rol kontrolü
    API'dedir (`run.trigger_scheduled` / `run.trigger_manual`).
    """
    if tetik not in ELLE_TETIKLER:
        raise CiError("tetik yalnızca deploy | nightly | manual olabilir")
    sonuc = _enqueue(session, None, tetik, isteyen=isteyen, dispatch=True)
    kaynak = _kaynak()
    if not sonuc["yeni"]:
        mesaj = "Aynı tetik için koşu zaten kuyrukta ya da sürüyor."
        durum = "zaten_kuyrukta"
    elif kaynak == "github":
        olay = (
            "repository_dispatch (deploy)" if tetik == "deploy" else f"workflow_dispatch ({tetik})"
        )
        mesaj = f"GitHub Actions tetikleniyor: {olay}; sonuç GitHub API'den alınacak."
        durum = "queued"
    else:
        mesaj = f"Yerel CI ({tetik}) main üzerinde kuyruğa alındı."
        durum = "queued"
    return {
        "job_id": sonuc["job_id"],
        "run_id": sonuc["run_id"],
        "durum": durum,
        "mesaj": mesaj,
        "kaynak": kaynak,
        "tetik": tetik,
    }


# =============================================================================== koşu sonucu


def _bitir(
    session: Session,
    run: Run,
    sonuc: str,
    *,
    hata: str | None = None,
    sure_ms: int | None = None,
) -> None:
    simdi = services.now()
    run.sonuc = sonuc
    run.bitis = simdi
    if sure_ms is None and run.baslama is not None:
        sure_ms = int((simdi - run.baslama).total_seconds() * 1000)
    run.sure_ms = sure_ms
    if hata:
        run.artefaktlar = {**(run.artefaktlar or {}), "hata": temiz(hata)}
    session.flush()
    sayac = sayilar(
        {"sonuc": s}
        for (s,) in session.execute(select(TestResult.sonuc).where(TestResult.run_id == run.id))
    )
    _etkinlik(session.connection(), run, **sayac)
    audit_on_commit(
        session,
        "system",
        "ci.completed",
        f"run:{run.id}",
        {
            "sonuc": sonuc,
            "tetik": run.tetik,
            "kaynak": run.kaynak,
            "commit": run.commit,
            "pr_no": run.pr_no,
            "github_run_id": run.github_run_id,
            "sure_ms": sure_ms,
            "hata": temiz(hata, 300) if hata else None,
            **sayac,
        },
    )
    # Faz 4: kırmızı koşu → triage.classify (çağıranın işleminde; yeşilde no-op).
    from tp_core.features.triage import on_run_finished

    on_run_finished(session, run)


def _case_eslemesi(
    session: Session, testler: Sequence[TestSatiri]
) -> dict[tuple[str, str], uuid.UUID]:
    """Test → onaylı case: testin dosyası bir üretilen script'in dosyasıysa (script_test_case).

    Script tek case'e bağlıysa o case; birden çok case'e bağlıysa test adında case başlığı geçen.
    """
    scriptler = session.execute(
        select(Script.dosya_yolu, ScriptTestCase.test_case_id)
        .join(ScriptTestCase, ScriptTestCase.script_id == Script.id)
        .where(Script.tur == "test")
    ).all()
    if not scriptler:
        return {}
    dosyaya: dict[str, set[uuid.UUID]] = defaultdict(set)
    for yol, tc in scriptler:
        dosyaya[PurePosixPath(yol).as_posix()].add(tc)
    basliklar = {
        tc.id: str((tc.icerik or {}).get("title") or "").casefold()
        for tc in session.scalars(
            select(TestCase).where(TestCase.id.in_({tc for _, tc in scriptler}))
        )
    }
    out: dict[tuple[str, str], uuid.UUID] = {}
    for t in testler:
        if not t.dosya:
            continue
        adaylar: set[uuid.UUID] = set()
        for yol, ids in dosyaya.items():
            if yol == t.dosya or yol.endswith("/" + t.dosya.lstrip("/")):
                adaylar |= ids
        if len(adaylar) == 1:
            out[t.anahtar] = next(iter(adaylar))
        elif adaylar:
            ad = t.test_adi.casefold()
            eslesen = [c for c in adaylar if basliklar.get(c) and basliklar[c] in ad]
            if len(eslesen) == 1:
                out[t.anahtar] = eslesen[0]
    return out


def record_results(session: Session, run: Run, ayr: Ayristirma) -> dict[str, int]:
    """Ayrıştırılmış testleri koşuya yazar. Koşunun satırları zaten varsa yeniden yazılmaz."""
    var = session.scalar(select(func.count()).where(TestResult.run_id == run.id)) or 0
    if var:
        hata_baglami_doldur(session, run, ayr)
        return sayilar(
            {"sonuc": s}
            for (s,) in session.execute(select(TestResult.sonuc).where(TestResult.run_id == run.id))
        )
    eslesme = _case_eslemesi(session, ayr.testler)
    satirlar: list[tuple[TestResult, TestSatiri]] = []
    for t in ayr.testler:
        tr = TestResult(
            id=uuid.uuid4(),
            run_id=run.id,
            test_case_id=eslesme.get(t.anahtar),
            test_adi=t.test_adi,
            dosya=t.dosya,
            sonuc=t.sonuc,
            sure_ms=t.sure_ms,
            retry=t.retry,
            commit=run.commit,
            tetik=run.tetik,
            kaynak=run.kaynak,
            hata_mesaji=t.hata_mesaji,
        )
        session.add(tr)
        satirlar.append((tr, t))
    # Ek satırları ayrı flush'ta: ORM ilişkisi olmadığından ekleme sırası garanti değildir.
    session.flush()
    for tr, t in satirlar:
        session.add(
            TestResultEk(
                test_result_id=tr.id,
                a11y_ihlal=t.a11y_ihlal,
                a11y_kritik=t.a11y_kritik,
                a11y=t.a11y,
                ekler=t.ekler,
                denemeler=t.denemeler,
                proje=t.proje,
                satir=t.satir,
                hata_baglami=t.hata_baglami,
            )
        )
    session.flush()
    return sayilar(ayr.testler)


def hata_baglami_doldur(session: Session, run: Run, ayr: Ayristirma) -> int:
    """Koşunun mevcut satırlarına eksik hata bağlamını yazar (yeniden içe aktarma / geri doldurma).

    Yalnızca `hata_baglami` boş olan `test_result_ek` satırları güncellenir; eşleşme (dosya, ad)
    iledir. Güncellenen satır sayısı döner.
    """
    bagl = {t.anahtar: t.hata_baglami for t in ayr.testler if t.hata_baglami}
    if not bagl:
        return 0
    n = 0
    for tr, ek in session.execute(
        select(TestResult, TestResultEk)
        .join(TestResultEk, TestResultEk.test_result_id == TestResult.id)
        .where(TestResult.run_id == run.id, TestResultEk.hata_baglami.is_(None))
    ):
        hb = bagl.get((tr.dosya or "", tr.test_adi))
        if hb:
            ek.hata_baglami = hb
            n += 1
    session.flush()
    return n


# ------------------------------------------------------------------------------ yerel koşu


def _rel(yol: Any, uzak_dizin: str | None) -> str | None:
    """toolchain'in mutlak yolunu koşu dizinine göre göreli yola çevirir (dışındaysa None)."""
    if not isinstance(yol, str) or not yol or not uzak_dizin:
        return None
    try:
        rel = PurePosixPath(yol).relative_to(PurePosixPath(uzak_dizin))
    except ValueError:
        return None
    if ".." in rel.parts:
        return None
    return rel.as_posix() or None


def _allure_html(rr: Mapping[str, Any], uzak: str | None) -> str | None:
    """`reports.allure_html` (`allure-report/` + `index.html`) varsa koşu dizinine göre yolu."""
    raporlar = rr.get("reports") if isinstance(rr.get("reports"), Mapping) else {}
    ah = (raporlar or {}).get("allure_html")
    if not isinstance(ah, Mapping) or not ah.get("exists"):
        return None
    dizin = _rel(ah.get("path"), uzak)
    return f"{dizin.rstrip('/')}/index.html" if dizin else None


def _adim_ozeti(adim: Any) -> dict[str, Any]:
    if not isinstance(adim, Mapping):
        return {"ok": False, "atlandi": True}
    out: dict[str, Any] = {"ok": bool(adim.get("ok")), "atlandi": bool(adim.get("skipped"))}
    for k in ("reason", "error", "mode", "status"):
        if adim.get(k) is not None:
            out[k] = temiz(adim.get(k), 500)
    return out


def _checks_dosyasi(sha: str | None, ad: str = "local-ci") -> dict[str, Any] | None:
    """toolchain'in yazdığı `checks/<sha>.json`'u okur (çekirdek bu dosyayı YAZMAZ). `durum` /
    `conclusion` koşunun kendi kontrolüdür: web `local-ci`, uygulama `local-ci-<platform>`."""
    if not sha or not SHA_RE.match(sha):
        return None
    yol = services.checks_root() / f"{sha}.json"
    import json

    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"yol": f"checks/{sha}.json", "var": False}
    except (OSError, ValueError) as exc:
        return {"yol": f"checks/{sha}.json", "var": True, "hata": temiz(exc, 200)}
    checks = veri.get("checks") if isinstance(veri, dict) else None
    local = next((c for c in checks or [] if isinstance(c, dict) and c.get("name") == ad), None)
    # Kontroller platform başına ayrı kayıttır (web `local-ci`, uygulama `local-ci-<platform>`,
    # 009 §2.7); portal her birini ayrıntı bağlantısıyla gösterir.
    platformlar = {
        str(c["name"]): {
            "durum": c.get("status"),
            "conclusion": c.get("conclusion"),
            "details_url": c.get("url") if isinstance(c.get("url"), str) else None,
        }
        for c in checks or []
        if isinstance(c, dict) and isinstance(c.get("name"), str)
        and (c["name"] == "local-ci" or c["name"].startswith("local-ci-"))
    }  # fmt: skip
    return {
        "yol": f"checks/{sha}.json",
        "var": True,
        "durum": (local or {}).get("status"),
        "conclusion": (local or {}).get("conclusion"),
        **({"platformlar": platformlar} if platformlar else {}),
    }


def _ast_guard_mode(run: Run) -> str:
    if run.pr_no is None:
        return "pr"
    try:
        from tp_core.integrations.forge import REPAIR_BRANCH_PREFIX, REPAIR_LABEL

        pr = services.forge().get_pr(run.pr_no)
    except Exception:
        return "pr"
    if pr.branch.startswith(REPAIR_BRANCH_PREFIX) or REPAIR_LABEL in (pr.labels or []):
        return "repair"
    return "pr"


def kirmizi_denetimi_ozeti(kd: Mapping[str, Any]) -> dict[str, Any]:
    """test-runner `kirmizi_denetimi` (`ok`, `kirmizi[]`, `kotu[]`; test başlıkları güvenilmeyen
    test çıktısıdır) → kırpılmış, sınırlı kopya."""

    def liste(x: Any) -> list[str]:
        return [temiz(v, 200) for v in (x if isinstance(x, list) else [])[:20]]

    return {
        "ok": kd.get("ok") is True,
        "kirmizi": liste(kd.get("kirmizi")),
        "kotu": liste(kd.get("kotu")),
    }


def rapor_platformu(report: Mapping[str, Any]) -> str | None:
    """`/check` raporunun platformu: üst düzey `platform` (toolchain) ya da `run.platform`
    (test-runner Java yolu); `lang=java` ise ve platform yoksa None (bilinmiyor)."""
    rr = report.get("run") if isinstance(report.get("run"), Mapping) else {}
    for aday in (report.get("platform"), (rr or {}).get("platform")):
        if aday in UYGULAMA_PLATFORMLARI:
            return str(aday)
    if report.get("lang") == "java" or (rr or {}).get("lang") == "java":
        return None
    return WEB


def ingest_check_report(session: Session, run: Run, report: Mapping[str, Any]) -> str:
    """toolchain `/check` yanıtını koşuya işler; koşunun sonucunu döndürür (testten bağımsız).

    Java (Appium) raporu (009): adımlar `app → deps → guard → compile → run`; test-runner JSON
    rapor yazmaz (`run.json` null), sonuçlar Surefire'dan birleştirilmiş `run.junit`'ten okunur ve
    test kimliği test-runner/triage ile aynı biçime çevrilir (`parse.java_junit_satirlari`).
    `run.ortam.platform` rapordan (yoksa koşunun kendi platformu) yazılır.
    """
    rr = report.get("run") if isinstance(report.get("run"), Mapping) else {}
    platform = rapor_platformu(report) or kosu_platformu(run)
    java = platform in UYGULAMA_PLATFORMLARI or report.get("lang") == "java"
    adim_adlari = TOOLCHAIN_ADIMLAR_JAVA if java else TOOLCHAIN_ADIMLAR
    adimlar = {k: _adim_ozeti(report.get(k)) for k in adim_adlari}
    uzak = rr.get("artifacts_dir") if isinstance(rr.get("artifacts_dir"), str) else None
    dizin_rel = rr.get("artifacts_rel") if isinstance(rr.get("artifacts_rel"), str) else None
    if dizin_rel is not None and not RUN_DIR_RE.match(dizin_rel):
        dizin_rel = None
    yerel = services.artifacts_root() / dizin_rel if dizin_rel else None
    yollar = {
        "junit": _rel(rr.get("junit_path") or rr.get("junit"), uzak),
        "json": _rel(rr.get("json_path") or rr.get("json"), uzak),
        "html": _rel(rr.get("html_dir"), uzak),
        "allure": _rel(rr.get("allure_dir"), uzak),
        # test-runner'ın ürettiği statik, tek dosyalık Allure raporu (yalnızca üretildiyse).
        "allure_html": _allure_html(rr, uzak),
        "log": _rel(rr.get("log"), uzak),
    }
    uyarilar: list[str] = []
    ayr: Ayristirma | None = None
    if yerel is not None and uzak and (yollar["junit"] or yollar["json"]):
        try:
            ayr = parse_files(
                yerel / yollar["junit"] if yollar["junit"] else None,
                yerel / yollar["json"] if yollar["json"] else None,
                KosuDizini(uzak, yerel),
            )
            if java:
                ayr = java_ayristirmasi(ayr)
            uyarilar.extend(ayr.uyarilar)
        except RaporHatasi as exc:
            uyarilar.append(str(exc))
    elif adimlar["run"].get("atlandi"):
        uyarilar.append("Testler koşmadı: önceki CI adımı başarısız.")
    sayac = record_results(session, run, ayr) if ayr is not None else sayilar([])
    saglik = rr.get("saglik") if isinstance(rr.get("saglik"), Mapping) else None
    conclusion = report.get("conclusion")
    runner_durum = rr.get("status")
    # Statik adım (bağımlılık, tsc, eslint, AST koruması) kırmızıysa CI kırmızıdır (failed);
    # test-runner koşamadıysa (sağlık, süre aşımı, rapor yok) error.
    if conclusion == "success":
        sonuc = "passed"
    elif runner_durum == "error":
        sonuc = "error"
    else:
        sonuc = "failed"
    koruma = adimlar.get("guard" if java else "ast_guard") or {}
    run.ortam = {
        **(run.ortam or {}),
        "saglik": dict(saglik) if saglik else None,
        "ast_guard_mode": koruma.get("mode"),
        "platform": platform,
        **({"lang": "java"} if java else {}),
    }
    run.artefaktlar = {
        **(run.artefaktlar or {}),
        "dizin": dizin_rel,
        **{k: v for k, v in yollar.items() if v},
        "adimlar": adimlar,
        "ozet": temiz(report.get("summary"), 500) if report.get("summary") else None,
        "conclusion": conclusion,
        "basarisiz_adimlar": [str(x) for x in report.get("failed_steps") or []][:10],
        "raporlar": ayr.raporlar if ayr else {"junit": False, "json": False},
        "istatistik": ayr.istatistik if ayr else {},
        "uyarilar": uyarilar[:20],
        "checks": _checks_dosyasi(
            run.commit, f"local-ci-{platform}" if platform in UYGULAMA_PLATFORMLARI else "local-ci"
        ),
        # Kırarak doğrulamanın kırmızı denetimi (test-runner Java yolu; KirmiziDenetimi kuralı).
        **(
            {"kirmizi_denetimi": kirmizi_denetimi_ozeti(rr["kirmizi_denetimi"])}
            if isinstance(rr.get("kirmizi_denetimi"), Mapping)
            else {}
        ),
        "runner_hata": temiz(rr.get("error"), 1000) if rr.get("error") else None,
        "sayilar": sayac,
    }
    sure = report.get("duration_ms") if isinstance(report.get("duration_ms"), int) else None
    _bitir(session, run, sonuc, sure_ms=sure)
    return sonuc


def _kilitle(session: Session, run_id: uuid.UUID) -> Run | None:
    return session.scalars(select(Run).where(Run.id == run_id).with_for_update()).first()


def run_job(engine: Engine, run_id: uuid.UUID, *, deneme: int, son_deneme: bool) -> dict[str, Any]:
    """`ci.run` işinin gövdesi.

    Son denemede (ya da kalıcı hatada) beklenmeyen her hata koşuyu `error` ile kapatır; aksi
    halde koşu `running`'de kalır ve aynı tetiği engeller (bkz. `recover_stuck_run`).
    """
    try:
        return _run_job(engine, run_id, deneme=deneme, son_deneme=son_deneme)
    except Exception as exc:
        if son_deneme or isinstance(exc, jobq.PermanentJobError):
            try:
                finalize_error(engine, run_id, f"CI işi beklenmeyen hatayla bitti: {exc}")
            except Exception:  # asıl hata yüzeye çıksın; kalan koşuyu tarama kapatır
                log.exception("ci.run %s: koşu error olarak kapatılamadı", run_id)
        raise


def _run_job(engine: Engine, run_id: uuid.UUID, *, deneme: int, son_deneme: bool) -> dict[str, Any]:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        run = _kilitle(session, run_id)
        if run is None:
            return {"durum": "yok", "run_id": str(run_id)}
        if run.sonuc in BITMIS:
            return {"durum": "atlandi", "sonuc": run.sonuc}
        if run.kaynak == "github":
            jobq.enqueue(
                session.connection(),
                JOB_GITHUB_POLL,
                {"run_id": str(run.id), "tur": 0},
                idempotency_key=f"ci.github_poll:{run.id}:0",
            )
            return {"durum": "github_bekleniyor", "run_id": str(run.id)}
        try:
            if not run.commit:
                ref = (run.ortam or {}).get("ref") or "main"
                run.commit = services.forge().head_sha(ref)
        except Exception as exc:
            if not son_deneme:
                raise
            _bitir(session, run, "error", hata=f"Commit çözülemedi: {exc}")
            return {"durum": "error", "run_id": str(run.id)}
        if run.sonuc != "running":
            run.sonuc = "running"
            run.baslama = services.now()
            _etkinlik(session.connection(), run)
            audit_on_commit(
                session, "system", "ci.started", f"run:{run.id}", {"commit": run.commit}
            )
        sha = run.commit
        mode = _ast_guard_mode(run)
        platform = kosu_platformu(run)

    body = {
        "sha": sha,
        "test_files": [],
        "repeat_each": CI_REPEAT_EACH,
        "retries": CI_RETRIES,
        "ast_guard_mode": mode,
        "run_id": f"ci-{run_id}-{deneme}",
        # Uygulama koşusu: tam kapsamlı Java koşusu → `local-ci-<platform>` (009 §2.7).
        **check_body_platformu(platform),
    }
    try:
        report = services.toolchain().check(body)
    except ToolchainError as exc:
        if exc.gecici and not son_deneme:
            raise
        with Session(engine, expire_on_commit=False) as session, session.begin():
            run = _kilitle(session, run_id)
            if run is not None and run.sonuc not in BITMIS:
                _bitir(session, run, "error", hata=str(exc))
        if exc.gecici:
            raise
        raise jobq.PermanentJobError(str(exc)) from exc

    with Session(engine, expire_on_commit=False) as session, session.begin():
        run = _kilitle(session, run_id)
        if run is None or run.sonuc in BITMIS:
            return {"durum": "atlandi"}
        sonuc = ingest_check_report(session, run, report)
        return {"durum": sonuc, "run_id": str(run_id), **(run.artefaktlar.get("sayilar") or {})}


def finalize_error(engine: Engine, run_id: uuid.UUID, hata: str) -> None:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        run = _kilitle(session, run_id)
        if run is not None and run.sonuc not in BITMIS:
            _bitir(session, run, "error", hata=hata)


YARIM_KALDI = "CI işi yarıda kaldı (worker durdu, süre aşıldı ya da iş başarısız oldu)"


def _son_is_hatasi(session: Session, run_id: uuid.UUID) -> tuple[bool, str | None]:
    """Koşunun işleri (`ci.run`, `ci.github_poll`): (hâlâ süren iş var mı, son işin hatası)."""
    isler = session.execute(
        select(Job.durum, Job.son_hata)
        .where(
            or_(
                Job.idempotency_key == f"ci.run:{run_id}",
                Job.idempotency_key.like(f"ci.github_poll:{run_id}:%"),
            )
        )
        .order_by(Job.guncelleme.desc())
    ).all()
    if any(d in ("queued", "retry", "running") for d, _ in isler):
        return True, None
    if not isler:
        return False, "iş kaydı yok"
    durum, hata = isler[0]
    return False, str(hata or durum)


def recover_stuck_run(session: Session, run: Run) -> bool:
    """İşi bitmiş ama `queued/running`'de kalmış koşuyu `error` yapar (çağıranın işleminde).

    İşleyici son denemede koşuyu kendisi kapatır; worker öldürülür, süre aşılır ya da nabız kesilir
    (`reap_stale`/`release_orphans`) ise yalnızca iş `failed` olur. Yeni tetik (`_enqueue`) ve
    worker açılışı (`sweep_stuck_runs`) bu koşuları kapatır.
    """
    if run.sonuc not in AKTIF:
        return False
    suruyor, _ = _son_is_hatasi(session, run.id)
    if suruyor:
        return False
    kilitli = _kilitle(session, run.id)
    if kilitli is None or kilitli.sonuc not in AKTIF:
        return False
    suruyor, neden = _son_is_hatasi(session, run.id)
    if suruyor:
        return False
    _bitir(session, kilitli, "error", hata=f"{YARIM_KALDI}: {neden}")
    return True


def sweep_stuck_runs(session: Session) -> int:
    """`queued/running`'de kalıp işi bitmiş tüm koşuları `error` yapar (worker açılışı)."""
    n = 0
    for run in session.scalars(select(Run).where(Run.sonuc.in_(AKTIF))).all():
        n += recover_stuck_run(session, run)
    return n


# ------------------------------------------------------------------------------ GitHub


def _zaman_capasi(run: Run) -> datetime:
    """Süre sınırı ve koşu eşlemesi için başlangıç: koşu kaydı ya da (sonradan elle tetiklenen
    gece koşusunda) dispatch denemesi anı — hangisi daha yeniyse."""
    capa = run.olusturma
    deneme = parse_gh_time((run.ortam or {}).get("dispatch_deneme_zamani"))
    return max(capa, deneme) if deneme is not None else capa


def _dispatch(engine: Engine, run_id: uuid.UUID) -> None:
    """GitHub kipinde deploy/elle gece için dispatch — tek seferlik (`external_ref`).

    Dispatch kendi işlemlerinde yapılır ve koşu araması bundan sonra ayrı işlemdedir: arama
    hatası (GitHub 5xx) dispatch kaydını geri almaz. Akış: (1) `intent` + deneme zamanı commit;
    (2) API çağrısı (işlem dışında); (3) `created` + denetim commit. Çağrı hata verirse `hata`
    yazılır (yeniden denemede tekrar dispatch güvenlidir). `intent` hatasız kaldıysa (süreç
    çağrıdan sonra öldü) önce GitHub'da koşu aranır; bulunursa `created` işaretlenir; bulunamazsa
    `TP_CI_DISPATCH_GRACE_S` (180 sn) dolana kadar yeniden dispatch edilmez.
    """
    key = f"github:dispatch:{run_id}"
    with Session(engine, expire_on_commit=False) as session, session.begin():
        run = _kilitle(session, run_id)
        if run is None or run.sonuc in BITMIS:
            return
        tetik = (run.ortam or {}).get("dispatch")
        if not tetik:
            return
        ref = session.scalar(
            select(ExternalRef).where(ExternalRef.idempotency_key == key).with_for_update()
        )
        if ref is not None and ref.durum == "created":
            return
        simdi = services.now()
        if ref is not None and ref.hata is None:
            # Önceki deneme çağrıyı yapmış olabilir: kör tekrar yok.
            gh = services.github()
            adaylar: list[dict[str, Any]] = []
            for olay in _olaylar(run):
                adaylar += gh.workflow_runs(head_sha=None, event=olay, **gh_is_akisi(run))
            if _aday_sec(session, run, adaylar) is not None:
                ref.durum = "created"
                ref.external_key = ref.external_key or _dispatch_olayi(tetik)
                audit_on_commit(
                    session,
                    "system",
                    "ci.github_dispatch_recovered",
                    f"run:{run.id}",
                    {"tetik": tetik, "olay": ref.external_key},
                )
                return
            onceki = parse_gh_time((run.ortam or {}).get("dispatch_deneme_zamani"))
            bekle = _int_env("TP_CI_DISPATCH_GRACE_S", 180)
            if onceki is not None and simdi - onceki < timedelta(seconds=bekle):
                return
        if ref is None:
            ref = ExternalRef(
                entity_turu="run",
                entity_id=run.id,
                sistem="github",
                idempotency_key=key,
                durum="intent",
            )
            session.add(ref)
        ref.hata = None
        deneme = int((run.ortam or {}).get("dispatch_deneme") or 0) + 1
        run.ortam = {
            **(run.ortam or {}),
            "dispatch_deneme": deneme,
            "dispatch_deneme_zamani": simdi.isoformat(),
        }
        hedef_ref = (run.ortam or {}).get("ref") or "main"
        isteyen = str((run.ortam or {}).get("isteyen") or "system")
        is_akisi = gh_is_akisi(run)
    # (2) API çağrısı: işlem dışında; `intent` kalıcı.
    gh = services.github()
    try:
        if tetik == "deploy":
            gh.repository_dispatch("deploy", {"tetik": "deploy", "tp_run_id": str(run_id)})
        else:
            gh.workflow_dispatch(hedef_ref, {"tetik": tetik}, **is_akisi)
    except Exception as exc:
        # Yanıt okunamadıysa (zaman aşımı/bağlantı koptu) istek GitHub'a ulaşmış olabilir: `hata`
        # yazılmaz → sonraki deneme önce koşuyu arar (kör tekrar yok).
        if not _belirsiz_hata(exc):
            with Session(engine, expire_on_commit=False) as session, session.begin():
                ref = session.scalar(select(ExternalRef).where(ExternalRef.idempotency_key == key))
                if ref is not None and ref.durum == "intent":
                    ref.hata = temiz(exc, 500) or type(exc).__name__
        raise
    # (3) `created`
    with Session(engine, expire_on_commit=False) as session, session.begin():
        ref = session.scalar(
            select(ExternalRef).where(ExternalRef.idempotency_key == key).with_for_update()
        )
        run = session.get(Run, run_id)
        if ref is None or run is None:
            return
        ref.durum = "created"
        ref.hata = None
        ref.external_key = _dispatch_olayi(tetik)
        run.ortam = {**(run.ortam or {}), "dispatch_zamani": services.now().isoformat()}
        audit_on_commit(
            session,
            isteyen,
            "ci.github_dispatched",
            f"run:{run.id}",
            {
                "tetik": tetik,
                "olay": ref.external_key,
                "repo": getattr(gh, "repo", None),
                "deneme": deneme,
            },
        )


def _belirsiz_hata(exc: BaseException) -> bool:
    import httpx

    e: BaseException | None = exc
    for _ in range(6):
        if e is None:
            return False
        if isinstance(e, (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError)):
            return True
        e = e.__cause__ or e.__context__
    return False


def _dispatch_olayi(tetik: str) -> str:
    return "repository_dispatch:deploy" if tetik == "deploy" else f"workflow_dispatch:{tetik}"


def _olaylar(run: Run) -> tuple[str, ...]:
    if run.tetik == "nightly":
        # Elle gece → workflow_dispatch; zamanlanmış gece → GitHub'ın kendi cron'u (schedule).
        return ("workflow_dispatch",) if (run.ortam or {}).get("dispatch") else ("schedule",)
    return GITHUB_OLAY[run.tetik]


def _aday_sec(
    session: Session, run: Run, adaylar: Iterable[Mapping[str, Any]]
) -> dict[str, Any] | None:
    kullanilan = set(
        session.scalars(
            select(Run.github_run_id).where(Run.github_run_id.is_not(None), Run.id != run.id)
        )
    )
    alt_sinir = _zaman_capasi(run) - timedelta(seconds=120)
    secilen: list[dict[str, Any]] = []
    for a in adaylar:
        if str(a.get("id")) in kullanilan:
            continue
        if a.get("event") not in _olaylar(run):
            continue
        olusma = parse_gh_time(a.get("created_at"))
        if run.tetik in ELLE_TETIKLER and (olusma is None or olusma < alt_sinir):
            continue
        if run.commit and run.tetik in ("pr", "push") and a.get("head_sha") != run.commit:
            continue
        if run.tetik == "pr" and run.pr_no is not None:
            prs = [p.get("number") for p in a.get("pull_requests") or [] if isinstance(p, dict)]
            if prs and run.pr_no not in prs:
                continue
        secilen.append(dict(a))
    secilen.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
    return secilen[0] if secilen else None


def _sauce_bilgisi(
    gh: Any, artefaktlar: list[dict[str, Any]], isler: list[dict[str, Any]]
) -> dict[str, Any] | None:
    is_ = next((j for j in isler if str(j.get("name") or "").lower() == "sauce"), None)
    urls: list[str] = []
    # sauce.json (scripts/github-sauce-summary.sh): passed | failed | error (Sauce'a ulaşılamadı) |
    # atlandi. Job sonucu tek başına yetmez: altyapı hatasında job bilerek yeşil biter.
    ozet: dict[str, Any] = {}
    art = next((a for a in artefaktlar if a.get("name") == SAUCE_ARTIFACT), None)
    if art is not None:
        try:
            import json

            dosyalar = gh.artifact_files(art, ("saucectl-report.json", "sauce.json"))
            for ad, icerik in dosyalar.items():
                try:
                    veri = json.loads(icerik.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue
                # Yalnız artefakt kökündeki sauce.json (özet betiği); artifacts/** altındaki
                # Sauce VM çıktısı güvenilmez test çıktısıdır.
                if str(ad) == "sauce.json" and isinstance(veri, dict):
                    ozet = veri
                    if veri.get("job_url"):
                        urls.append(str(veri["job_url"]))
                else:
                    urls.extend(_urlleri_topla(veri))
        except GitHubCiError as exc:
            log.warning("sauce artefaktı okunamadı: %s", exc)
    urls = sorted({u for u in urls if SAUCE_URL_RE.match(u)})[:20]
    if is_ is None and not urls and not ozet:
        return None
    durum = ozet.get("durum")
    return {
        "url": urls[0] if urls else None,
        "urls": urls,
        "is_sonucu": (is_ or {}).get("conclusion"),
        "is_url": (is_ or {}).get("html_url"),
        "durum": durum if durum in ("passed", "failed", "error", "atlandi") else None,
        "neden": temiz(ozet.get("neden"), 300) if ozet.get("neden") else None,
    }


def _urlleri_topla(veri: Any, derinlik: int = 0) -> list[str]:
    if derinlik > 8:
        return []
    out: list[str] = []
    if isinstance(veri, dict):
        for k, v in veri.items():
            if k == "url" and isinstance(v, str):
                out.append(v)
            else:
                out.extend(_urlleri_topla(v, derinlik + 1))
    elif isinstance(veri, list):
        for v in veri[:200]:
            out.extend(_urlleri_topla(v, derinlik + 1))
    return out


def _sec_dosya(dosyalar: Mapping[str, bytes], ad: str) -> bytes | None:
    adaylar = sorted(
        (y for y in dosyalar if y.rsplit("/", 1)[-1] == ad),
        key=lambda y: (not y.startswith("results/"), len(y)),
    )
    return dosyalar[adaylar[0]] if adaylar else None


def _artefakt_ekleri(dosyalar: Mapping[str, bytes]) -> ArtefaktEkleri:
    """GitHub artefaktındaki `error-context.md` kopyaları: triage'ın hata anı aria snapshot'ı.

    GitHub kipinde yerel koşu dizini (`run.json`, kanıt dosyaları) yoktur; snapshot içe aktarımda
    `test_result_ek.hata_baglami`'na yazılmazsa triage locator kuralı (kural 3) hiç çalışamaz.
    """
    return ArtefaktEkleri(
        {y: v for y, v in dosyalar.items() if y.rsplit("/", 1)[-1] == ERROR_CONTEXT_AD}
    )


# Sonuç artefaktından rapor dışı okunan ek dosyalarının ad kalıpları: hata anı bağlamı (0015) ve
# yeşil koşunun sayfa başına aria snapshot'ları (0016).
EK_KALIPLARI = (ERROR_CONTEXT_AD, *ARIA_DOSYA_KALIPLARI)
ARIA_KAYNAK_INGEST = "github_artefakt"
ARIA_KAYNAK_GERI_DOLDURMA = "github_artefakt_geri_doldurma"


def aria_kaydet(
    session: Session, run: Run, dosyalar: Mapping[str, bytes], kaynak: str = ARIA_KAYNAK_INGEST
) -> dict[str, int]:
    """Artefakttaki `<sayfa>.aria.yml` dosyalarını `run_aria`'ya yazar (GitHub kipi, 0016).

    GitHub kipinde yerel koşu dizini yoktur; locator onarımının son yeşil aria kanıtı
    (`repair.service.aria_kaniti`) bu kopyayı okur. İdempotent: koşuda aynı yol zaten varsa
    yeniden yazılmaz. {bulunan, eklenen} döner.
    """
    adaylar = aria_dosyalari(dosyalar)
    if not adaylar:
        return {"bulunan": 0, "eklenen": 0}
    var = set(session.scalars(select(RunAria.yol).where(RunAria.run_id == run.id)))
    eklenen = 0
    for yol, metin in adaylar:
        if yol in var:
            continue
        session.add(
            RunAria(
                run_id=run.id,
                yol=yol,
                ad=yol.rsplit("/", 1)[-1],
                icerik=metin,
                boyut=len(metin.encode("utf-8")),
                kaynak=kaynak,
            )
        )
        eklenen += 1
    session.flush()
    return {"bulunan": len(adaylar), "eklenen": eklenen}


def _sonuc_artefakti(run: Run) -> tuple[Any, Mapping[str, Any]]:
    if run.kaynak != "github" or not run.github_run_id:
        raise CiError("koşu GitHub kaynaklı değil ya da GitHub koşu kimliği yok")
    gh = services.github()
    art = next(
        (a for a in gh.artifacts(run.github_run_id) if a.get("name") == RESULTS_ARTIFACT), None
    )
    if art is None:
        raise CiError(f"'{RESULTS_ARTIFACT}' artefaktı yok")
    return gh, art


def github_aria_doldur(session: Session, run: Run, isteyen: str = "system") -> dict[str, Any]:
    """Önceden içe aktarılmış GitHub koşusunun aria snapshot'larını artefakttan geri doldurur.

    0016 öncesi içe aktarılan koşular için (artefakt GitHub'da saklama süresi içindeyken).
    Yalnızca core-worker'da çalışır (GitHub kimlik bilgisi). İdempotent: var olan yollar yeniden
    yazılmaz. Denetim kaydı `ci.aria_snapshots_backfilled`.
    """
    gh, art = _sonuc_artefakti(run)
    dosyalar = gh.artifact_files(art, (), ARIA_DOSYA_KALIPLARI)
    sonuc = aria_kaydet(session, run, dosyalar, kaynak=ARIA_KAYNAK_GERI_DOLDURMA)
    audit_on_commit(
        session,
        isteyen,
        "ci.aria_snapshots_backfilled",
        f"run:{run.id}",
        {"github_run_id": run.github_run_id, **sonuc},
    )
    return {"run_id": str(run.id), "github_run_id": run.github_run_id, **sonuc}


def github_hata_baglami_doldur(session: Session, run: Run) -> dict[str, Any]:
    """Önceden içe aktarılmış GitHub koşusunun hata bağlamını artefakttan yeniden okur.

    0015 öncesi içe aktarılan koşular için (artefakt GitHub'da saklama süresi içindeyken).
    Test satırları yeniden yazılmaz; yalnızca boş `hata_baglami` doldurulur.
    """
    gh, art = _sonuc_artefakti(run)
    dosyalar = gh.artifact_files(art, ("results.json",), (ERROR_CONTEXT_AD,))
    ayr = parse_reports(
        None, _sec_dosya(dosyalar, "results.json"), ekler=_artefakt_ekleri(dosyalar)
    )
    bulunan = sum(1 for t in ayr.testler if t.hata_baglami)
    n = hata_baglami_doldur(session, run, ayr)
    audit_on_commit(
        session,
        "system",
        "ci.failure_context_backfilled",
        f"run:{run.id}",
        {"github_run_id": run.github_run_id, "bulunan": bulunan, "guncellenen": n},
    )
    return {"run_id": str(run.id), "bulunan": bulunan, "guncellenen": n}


# ci-meta.json'dan koşu kaydına alınan alanlar (portal özeti; `.github/CI.md` "ci-meta.json").
CI_META_ALANLARI = (
    "tetik",
    "sha",
    "event",
    "run_id",
    "job",
    "ref",
    "durum",
    "hata",
    "exit_code",
    "playwright",
)


def _ci_meta(ham: bytes | None, uyarilar: list[str]) -> dict[str, Any]:
    if not ham:
        return {}
    import json

    try:
        m = json.loads(ham.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        uyarilar.append("ci-meta.json okunamadı.")
        return {}
    return m if isinstance(m, dict) else {}


def _gh_kosu_dizini(yerel: Mapping[str, Any], results_kok: Any) -> tuple[KosuDizini | None, str]:
    """Yerel kopya varsa: (results.json'daki runner yollarını kopyaya eşleyen dizin, ek öneki).

    `results_kok` (ci-meta.json) ek yollarının runner'daki köküdür; artefakt kökü (results.json'ın
    dizini) ona karşılık gelir. Ek yolları önce o köke, sonra öneke göre koşu dizinine göreli olur.
    """
    if yerel.get("durum") not in ("indirildi", "mevcut") or not isinstance(results_kok, str):
        return None, ""
    p = github_artifacts.yol(yerel.get("dizin"))
    json_rel = (yerel.get("yollar") or {}).get("json")
    if p is None or not isinstance(json_rel, str) or not results_kok.startswith("/"):
        return None, ""
    onek = PurePosixPath(json_rel).parent.as_posix()
    return KosuDizini(results_kok.rstrip("/") or "/", p / onek), onek


def _github_yerel(
    session: Session,
    gh: Any,
    artefaktlar: Sequence[Mapping[str, Any]],
    gh_dizin: str | None,
    sonuc_zip: bytes | None = None,
) -> dict[str, Any]:
    """GitHub artefaktlarının yerel kopyasını hazırlar (bkz. `github_artifacts`); saklama dışına
    düşen eski kopyaların koşu kayıtlarını `budandi` yapar. Hata alımı düşürmez."""
    if gh_dizin is None:
        return {"dizin": None, "durum": "hata", "hata": "GitHub koşu kimliği yok", "yollar": {}}
    sonuc = github_artifacts.hazirla(gh, artefaktlar, gh_dizin, sonuc_zip=sonuc_zip)
    if sonuc["durum"] == "indirildi":
        try:
            silinen = github_artifacts.budama(koru=(gh_dizin,))
        except Exception:  # saklama hatası alımı düşürmez
            log.exception("GitHub artefakt kopyaları budanamadı")
            silinen = []
        if silinen:
            session.execute(
                text(
                    "UPDATE run SET artefaktlar = jsonb_set(artefaktlar, '{github_yerel,durum}', "
                    "'\"budandi\"') WHERE artefaktlar->'github_yerel'->>'dizin' = ANY(:d)"
                ),
                {"d": silinen},
            )
    return {k: v for k, v in sonuc.items() if k != "indirilen"}


def github_artefakt_indir(session: Session, run: Run, isteyen: str = "system") -> dict[str, Any]:
    """Önceden içe aktarılmış GitHub koşusunun artefaktlarını yerel kopyaya alır (geri doldurma).

    Yerel kopya özelliğinden önce alınan koşular için (artefakt GitHub'da saklama süresi
    içindeyken). Yalnızca core-worker'da çalışır (GitHub kimlik bilgisi + yazılabilir volume).
    İdempotent: kopya varsa indirme yapılmaz. Test satırları yeniden yazılmaz. Denetim kaydı
    `ci.github_artifacts_mirrored`.
    """
    if run.kaynak != "github" or not run.github_run_id:
        raise CiError("koşu GitHub kaynaklı değil ya da GitHub koşu kimliği yok")
    a = run.artefaktlar or {}
    gh_bilgi = a.get("github") if isinstance(a.get("github"), dict) else {}
    gh_dizin = github_artifacts.dizin_adi(run.github_run_id, gh_bilgi.get("deneme"))
    gh = services.github()
    artefaktlar = [] if github_artifacts.mevcut(gh_dizin) else gh.artifacts(run.github_run_id)
    yerel = _github_yerel(session, gh, artefaktlar, gh_dizin)
    run.artefaktlar = {**a, "github_yerel": yerel}
    audit_on_commit(
        session,
        isteyen,
        "ci.github_artifacts_mirrored",
        f"run:{run.id}",
        {"github_run_id": run.github_run_id, "durum": yerel["durum"], "dizin": yerel["dizin"]},
    )
    return {"run_id": str(run.id), "github_run_id": run.github_run_id, **yerel}


def github_ingest(session: Session, run: Run, wr: Mapping[str, Any]) -> str:
    """Tamamlanmış GitHub workflow koşusunu koşu kaydına işler."""
    gh = services.github()
    artefaktlar = gh.artifacts(wr["id"])
    isler = gh.jobs(wr["id"])
    uyarilar: list[str] = []
    ayr: Ayristirma | None = None
    meta: dict[str, Any] = {}
    dosyalar: Mapping[str, bytes] = {}
    # 009: uygulama iş akışının artefaktı `<job>-results` (Surefire TEST-*.xml + ci-meta.json).
    java = kosu_platformu(run) in UYGULAMA_PLATFORMLARI
    art_adi = gh_sonuc_artefakti(run)
    surefire: dict[str, bytes] = {}
    surefire_uyari: list[str] = []
    sonuc_art = next((a for a in artefaktlar if a.get("name") == art_adi), None)
    gh_dizin = github_artifacts.dizin_adi(wr.get("id"), wr.get("run_attempt"))
    yerel_kopya = None if java else github_artifacts.mevcut(gh_dizin)
    sonuc_zip: bytes | None = None
    okundu = False
    if sonuc_art is None:
        uyarilar.append(f"'{art_adi}' artefaktı yok (testler no-op olabilir).")
    else:
        try:
            adlar = ("junit.xml", "results.json", "ci-meta.json")
            dosyalar = None
            if yerel_kopya is not None:
                # Yeniden alım (iş yeniden denemesi): yerel kopya varsa yeniden indirilmez. Kopya
                # okunamazsa (ör. budama sildi) zip'e düşülür; yerel kopya alımı düşürmez.
                try:
                    dosyalar = github_artifacts.disk_dosyalari(yerel_kopya, adlar, EK_KALIPLARI)
                except OSError as exc:
                    log.warning("yerel artefakt kopyası okunamadı, indiriliyor: %s", exc)
                    dosyalar = None
                # os.walk hataları yutar: kopya okuma sırasında silindiyse sonuç boş/eksik gelir.
                if (
                    dosyalar is None
                    or github_artifacts.mevcut(gh_dizin) is None
                    or not any(
                        k.rsplit("/", 1)[-1] in ("junit.xml", "results.json") for k in dosyalar
                    )
                ):
                    dosyalar = None
                    yerel_kopya = None
            if dosyalar is None:
                sonuc_zip = gh.artifact_zip(sonuc_art)
                dosyalar = _zip_dosyalari(sonuc_zip, adlar, EK_KALIPLARI)
                if java:
                    # Surefire raporları ek değil rapordur: kendi boyut/sayı sınırı + uyarı.
                    surefire, surefire_uyari = surefire_dosyalari(sonuc_zip)
            okundu = True
        except GitHubCiError as exc:
            uyarilar.append(str(exc))
    # Raporların yerel kopyası (portal GitHub'a gitmeden açar); ayrıştırma için indirilen zip
    # yeniden kullanılır. Hata alımı düşürmez.
    # Uygulama artefaktı yerel kopya düzeninde (`test-local-results`) değildir: zip verilmez.
    yerel = _github_yerel(session, gh, artefaktlar, gh_dizin, None if java else sonuc_zip)
    sonuc_zip = None  # büyük zip bellekte tutulmaz
    if okundu:
        ham_meta = _sec_dosya(dosyalar, "ci-meta.json")
        m = _ci_meta(ham_meta, uyarilar)
        meta = {k: temiz(m.get(k), 200) for k in CI_META_ALANLARI if m.get(k) not in (None, "")}
        kosu_dizini, ek_onek = _gh_kosu_dizini(yerel, m.get("results_kok"))
        if java:
            ayr = surefire_ayristir(surefire, surefire_uyari)
        else:
            ayr = parse_reports(
                _sec_dosya(dosyalar, "junit.xml"),
                _sec_dosya(dosyalar, "results.json"),
                kosu_dizini=kosu_dizini,
                ekler=_artefakt_ekleri(dosyalar),
            )
        if ek_onek:
            # Ek yolları sonuç köküne göreli → koşu (yerel kopya) dizinine göreli.
            for t in ayr.testler:
                for e in t.ekler:
                    e["yol"] = f"{ek_onek}/{e['yol']}"
        uyarilar.extend(ayr.uyarilar)
    if wr.get("head_sha") and SHA_RE.match(str(wr["head_sha"])):
        run.commit = str(wr["head_sha"])
    sayac = record_results(session, run, ayr) if ayr is not None else sayilar([])
    # Yeşil koşunun sayfa başına aria snapshot'ları: GitHub kipinde onarımın son yeşil kanıtı.
    aria_kayit = aria_kaydet(session, run, dosyalar)
    sauce = _sauce_bilgisi(gh, artefaktlar, isler)
    html = str(wr.get("html_url") or "") or None
    sonuc = GITHUB_SONUC.get(str(wr.get("conclusion") or ""), "error")
    run.artefaktlar = {
        **(run.artefaktlar or {}),
        "ci_url": html,
        "rapor_url": f"{html}#artifacts" if html and sonuc_art else None,
        "allure_url": f"{html}#artifacts" if html and sonuc_art else None,
        "github": {
            "run_id": wr.get("id"),
            "olay": wr.get("event"),
            "conclusion": wr.get("conclusion"),
            "deneme": wr.get("run_attempt"),
            "isler": [
                {
                    "ad": temiz(j.get("name"), 100),
                    "sonuc": j.get("conclusion"),
                    "url": j.get("html_url"),
                }
                for j in isler[:30]
            ],
            "artefaktlar": [
                {
                    "ad": temiz(a.get("name"), 100),
                    "id": a.get("id"),
                    "boyut": a.get("size_in_bytes"),
                }
                for a in artefaktlar[:30]
            ],
            "meta": meta,
            "aria_dosya": aria_kayit["bulunan"],
        },
        "sauce": sauce,
        "github_yerel": yerel,
        "raporlar": ayr.raporlar if ayr else {"junit": False, "json": False},
        "istatistik": ayr.istatistik if ayr else {},
        "uyarilar": uyarilar[:20],
        "sayilar": sayac,
    }
    bas = parse_gh_time(wr.get("run_started_at")) or parse_gh_time(wr.get("created_at"))
    son = parse_gh_time(wr.get("updated_at"))
    if bas is not None:
        run.baslama = bas
    sure = int((son - bas).total_seconds() * 1000) if bas and son and son >= bas else None
    _bitir(session, run, sonuc, sure_ms=sure)
    return sonuc


def github_poll(engine: Engine, run_id: uuid.UUID, tur: int) -> dict[str, Any]:
    """`ci.github_poll`: koşuyu bul → bitene kadar bekle → artefaktları al → PR yorumu."""
    aralik = _int_env("TP_CI_GITHUB_POLL_S", 30)
    _dispatch(engine, run_id)  # kendi işlemlerinde: aşağıdaki arama hatası dispatch'i geri almaz
    pr_no: int | None = None
    with Session(engine, expire_on_commit=False) as session, session.begin():
        run = _kilitle(session, run_id)
        if run is None:
            return {"durum": "atlandi"}
        if run.sonuc in BITMIS:
            # Alım yapılmış; PR yorumu kesin hatayla kaldıysa işin yeniden denemesi onu tamamlar.
            alindi: dict[str, Any] = {"durum": "atlandi", "sonuc": run.sonuc}
            pr_no = run.pr_no if run.kaynak == "github" else None
        else:
            gh = services.github()
            if not run.commit and (run.ortam or {}).get("ref") and run.tetik in ("pr", "push"):
                run.commit = services.forge().head_sha((run.ortam or {}).get("ref"))
            wr: dict[str, Any] | None = None
            if run.github_run_id:
                wr = gh.workflow_run(run.github_run_id)
            else:
                adaylar: list[dict[str, Any]] = []
                for olay in _olaylar(run):
                    adaylar += gh.workflow_runs(
                        head_sha=run.commit if run.tetik in ("pr", "push") else None,
                        event=olay,
                        **gh_is_akisi(run),
                    )
                wr = _aday_sec(session, run, adaylar)
                if wr is not None:
                    run.github_run_id = str(wr["id"])
                    run.artefaktlar = {**(run.artefaktlar or {}), "ci_url": wr.get("html_url")}
            if wr is not None and wr.get("status") == "completed":
                sonuc = github_ingest(session, run, wr)
                alindi = {"durum": sonuc, "github_run_id": run.github_run_id}
                pr_no = run.pr_no
            else:
                alindi = _bekle(session, run, wr, tur, aralik)
    # PR yorumu koşu kaydı commit edildikten SONRA, ayrı işlemlerde: yorum hatası alımı geri almaz.
    if pr_no is not None:
        _pr_yorumu_yaz(engine, run_id, alindi)
    return alindi


def _pr_yorumu_yaz(engine: Engine, run_id: uuid.UUID, alindi: dict[str, Any]) -> None:
    alindi["pr_yorumu"] = post_pr_comment(engine, run_id)
    if alindi["pr_yorumu"] == "hata":
        # Koşu kaydı commit edildi; iş yeniden denenince yalnızca yorum tekrar denenir.
        raise GitHubCiError("PR yorumu yazılamadı (koşu sonucu kaydedildi; yeniden denenecek)")


def _bekle(
    session: Session, run: Run, wr: Mapping[str, Any] | None, tur: int, aralik: int
) -> dict[str, Any]:
    """GitHub koşusu sürüyor: `running` yap, süre sınırını denetle, sonraki yoklamayı planla."""
    if wr is not None and run.sonuc != "running":
        run.sonuc = "running"
        run.baslama = parse_gh_time(wr.get("run_started_at")) or services.now()
        _etkinlik(session.connection(), run, github_run_id=run.github_run_id)
    # Gece koşusu GitHub'ın kendi cron'unu (02:00 UTC) bekleyebilir: daha uzun süre sınırı.
    sinir = _int_env("TP_CI_GITHUB_TIMEOUT_S", 5400)
    if run.tetik == "nightly" and not (run.ortam or {}).get("dispatch"):
        sinir = max(sinir, 12 * 3600)
    if services.now() - _zaman_capasi(run) > timedelta(seconds=sinir):
        neden = "GitHub koşusu bitmedi" if wr is not None else "GitHub koşusu bulunamadı"
        _bitir(session, run, "error", hata=f"{neden} ({sinir} sn süre sınırı aşıldı).")
        return {"durum": "error"}
    if wr is None and run.tetik == "nightly" and not (run.ortam or {}).get("dispatch"):
        aralik = max(aralik, 300)  # GitHub cron'u saatler sonra: seyrek yokla
    jobq.enqueue(
        session.connection(),
        JOB_GITHUB_POLL,
        {"run_id": str(run.id), "tur": tur + 1},
        idempotency_key=f"ci.github_poll:{run.id}:{tur + 1}",
        run_after=services.now() + timedelta(seconds=aralik),
    )
    return {"durum": "bekleniyor", "tur": tur + 1, "github_run_id": run.github_run_id}


# ------------------------------------------------------------------------------ PR yorumu

PR_YORUM_ISARETI = "<!-- testing-probe:ci-sonucu -->"
_SONUC_ETIKETI = {"passed": "geçti", "failed": "kaldı", "error": "hata (sonuç alınamadı)"}


def pr_comment_body(run: Run) -> str:
    """GitHub PR koşusunun sonucu (§8.5): test-local sonucu, sayılar, GitHub ve Sauce bağlantıları.

    Yalnızca doğrulanmış bağlantılar yazılır (Sauce: `SAUCE_URL_RE`; GitHub: koşunun `html_url`'i).
    Sauce job sayfası video ve log'u barındırır.
    """
    a = run.artefaktlar or {}
    gh = a.get("github") if isinstance(a.get("github"), dict) else {}
    sayac = a.get("sayilar") if isinstance(a.get("sayilar"), dict) else {}
    sauce = a.get("sauce") if isinstance(a.get("sauce"), dict) else None
    isler = {
        str(j.get("ad") or "").lower(): j for j in gh.get("isler") or [] if isinstance(j, dict)
    }
    yerel = isler.get("test-local") or {}
    satirlar = [
        PR_YORUM_ISARETI,
        f"### Testing Probe — CI sonucu: {_SONUC_ETIKETI.get(run.sonuc, run.sonuc)}",
        "",
        f"- Commit: `{(run.commit or '')[:12]}` · tetik: `{run.tetik}`",
        "- test-local: "
        + str(yerel.get("sonuc") or "—")
        + (
            f" — {sayac.get('toplam', 0)} test: {sayac.get('gecen', 0)} geçti, "
            f"{sayac.get('basarisiz', 0)} kaldı, {sayac.get('flaky', 0)} flaky, "
            f"{sayac.get('atlanan', 0)} atlandı"
            if sayac
            else ""
        ),
    ]
    if a.get("ci_url"):
        satirlar.append(f"- GitHub Actions koşusu: {a['ci_url']}")
    if sauce:
        satirlar.append(f"- Sauce Labs job'u: {sauce.get('is_sonucu') or '—'}")
        urls = [u for u in sauce.get("urls") or [] if isinstance(u, str) and SAUCE_URL_RE.match(u)]
        for u in urls[:5]:
            satirlar.append(f"  - Sauce oturumu (video + log): {u}")
        if not urls:
            satirlar.append("  - Sauce oturum bağlantısı raporda yok (video/log okunamadı).")
    else:
        satirlar.append("- Sauce Labs: bu koşuda Sauce job'u yok ya da sonucu okunamadı.")
    satirlar += ["", "_AI'sız CI; sonuç çekirdek tarafından GitHub API'den alındı._"]
    return "\n".join(satirlar)


def post_pr_comment(engine: Engine, run_id: uuid.UUID) -> str:
    """PR koşusunun sonucunu PR'a bir kez yorum olarak yazar (`external_ref`, idempotent).

    Akış `_dispatch` ile aynı: (1) `intent` commit; (2) `forge.comment_pr` (işlem dışında);
    (3) `created` + denetim. Kesin hatada `hata` yazılır ve `ci.github_poll` yeniden denenir (koşu
    zaten bitmiş olduğundan yalnızca yorum tekrar denenir);
    yanıt belirsizse (istek ulaşmış olabilir) kör tekrar yapılmaz. Yorum hatası koşuyu etkilemez.
    """
    key = f"github:pr_comment:{run_id}"
    with Session(engine, expire_on_commit=False) as session, session.begin():
        run = session.get(Run, run_id)
        if run is None or run.pr_no is None or run.kaynak != "github" or run.sonuc not in BITMIS:
            return "yok"
        ref = session.scalar(
            select(ExternalRef).where(ExternalRef.idempotency_key == key).with_for_update()
        )
        if ref is not None and (ref.durum == "created" or ref.hata is None):
            return "zaten"
        if ref is None:
            ref = ExternalRef(
                entity_turu="run",
                entity_id=run.id,
                sistem="github",
                idempotency_key=key,
                durum="intent",
            )
            session.add(ref)
        ref.hata = None
        pr_no = run.pr_no
        govde = pr_comment_body(run)
    try:
        services.forge().comment_pr(pr_no, govde)
    except Exception as exc:
        log.warning("PR #%s yorumu yazılamadı (koşu %s): %s", pr_no, run_id, exc)
        if not _belirsiz_hata(exc):
            with Session(engine, expire_on_commit=False) as session, session.begin():
                ref = session.scalar(select(ExternalRef).where(ExternalRef.idempotency_key == key))
                if ref is not None and ref.durum == "intent":
                    ref.hata = temiz(exc, 500) or type(exc).__name__
        return "hata"
    with Session(engine, expire_on_commit=False) as session, session.begin():
        ref = session.scalar(
            select(ExternalRef).where(ExternalRef.idempotency_key == key).with_for_update()
        )
        if ref is not None:
            ref.durum = "created"
            ref.external_key = f"pr:{pr_no}"
        audit_on_commit(session, "system", "ci.pr_comment", f"run:{run_id}", {"pr_no": pr_no})
    return "yazildi"


# =============================================================================== gece


def nightly_saati() -> time | None:
    ham = (os.environ.get("TP_CI_NIGHTLY_SAAT") or "02:00").strip().lower()
    if ham in ("", "0", "kapali", "off", "none"):
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", ham)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        log.warning("geçersiz TP_CI_NIGHTLY_SAAT=%r; 02:00 kullanılıyor", ham)
        return time(2, 0)
    return time(int(m.group(1)), int(m.group(2)))


def next_nightly(simdi: datetime, saat: time) -> tuple[str, datetime]:
    """`simdi`'den sonraki ilk gece koşusu: (Istanbul tarihi, UTC zamanı)."""
    tz = _istanbul()
    yerel = simdi.astimezone(tz)
    aday = datetime.combine(yerel.date(), saat, tzinfo=tz)
    if aday <= yerel:
        aday = datetime.combine(yerel.date() + timedelta(days=1), saat, tzinfo=tz)
    return aday.date().isoformat(), aday.astimezone(UTC)


def plan_nightly(conn: Connection, simdi: datetime | None = None) -> uuid.UUID | None:
    """Sonraki gece işini planlar (idempotent: `ci.nightly:<tarih>`)."""
    saat = nightly_saati()
    if saat is None:
        return None
    tarih, zaman = next_nightly(simdi or services.now(), saat)
    return jobq.enqueue(
        conn,
        JOB_NIGHTLY,
        {"tarih": tarih},
        idempotency_key=f"{JOB_NIGHTLY}:{tarih}",
        run_after=zaman,
    )


def nightly_job(engine: Engine, tarih: str) -> dict[str, Any]:
    # Zincir önce ve AYRI işlemde planlanır: koşu açılamasa (DB/CiError, tüm denemeler) da ertesi
    # günün işi kalıcıdır (idempotent anahtar `ci.nightly:<tarih>`; tekrar planlama çift açmaz).
    with engine.begin() as conn:
        plan_nightly(conn, services.now() + timedelta(minutes=1))
    with Session(engine, expire_on_commit=False) as session, session.begin():
        sonuc = _enqueue(
            session, None, "nightly", isteyen="system:gece", anahtar=f"nightly:{tarih}"
        )
        return {"run_id": str(sonuc["run_id"]) if sonuc["run_id"] else None, "yeni": sonuc["yeni"]}


# =============================================================================== okuma


def _url(run_id: uuid.UUID, rel: str | None, dizin: str | None) -> str | None:
    if not rel or not dizin:
        return None
    return f"/api/artifacts/runs/{run_id}/{rel}"


def _html_index(rel: str | None) -> str | None:
    return f"{rel.rstrip('/')}/index.html" if rel else None


def _imzali_url(run_id: uuid.UUID, rel: str | None, dizin: str | None) -> str | None:
    """Sandbox'lı HTML raporu için imzalı, süreli bağlantı (bkz. `artifacts`); oturum sırrı
    yoksa oturumlu yol."""
    if not rel or not dizin:
        return None
    from tp_core.features.ci import artifacts

    onek = artifacts.imzali_onek(run_id, _time.time())
    return f"{onek}{rel}" if onek else _url(run_id, rel, dizin)


def serialize_runs(session: Session, runs: Sequence[Run]) -> list[dict[str, Any]]:
    ids = [r.id for r in runs]
    sayac: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if ids:
        for run_id, sonuc, n in session.execute(
            select(TestResult.run_id, TestResult.sonuc, func.count())
            .where(TestResult.run_id.in_(ids))
            .group_by(TestResult.run_id, TestResult.sonuc)
        ):
            sayac[run_id][sonuc] += int(n)
    # 009: koşunun platformu `ortam.platform`; eski kayıtlarda script'in platformu.
    sids = {r.script_id for r in runs if r.script_id and not (r.ortam or {}).get("platform")}
    script_platform = (
        dict(session.execute(select(Script.id, Script.platform).where(Script.id.in_(sids))).all())
        if sids
        else {}
    )
    out = []
    for r in runs:
        s = sayac.get(r.id, {})
        a = r.artefaktlar or {}
        o = r.ortam or {}
        saglik = o.get("saglik") if isinstance(o.get("saglik"), dict) else None
        dizin = a.get("dizin")
        if saglik is not None and saglik.get("ok") is False:
            # Sağlık kontrolü başarısız: Playwright başlatılmadı, rapor dosyaları yok
            # (toolchain yolları yine bildirir; kırık bağlantı gösterilmez).
            a = {k: v for k, v in a.items() if k not in ("html", "allure", "allure_html", "junit")}
        sauce = a.get("sauce") if isinstance(a.get("sauce"), dict) else {}
        gy = _github_yerel_ozeti(a)
        if gy["kullanilir"]:
            # GitHub koşusu: core'un yerel kopyası yerel koşu düzeninde sunulur (önce yerel
            # bağlantı; GitHub bağlantıları `ci_url` ve yerel kopya yoksa yedek olarak kalır).
            dizin = gy["dizin"]
            a = {**a, **gy["yollar"]}
        out.append(
            {
                "id": str(r.id),
                "tetik": r.tetik,
                "kaynak": r.kaynak,
                "commit": r.commit or "",
                "pr_no": r.pr_no,
                "durum": r.sonuc,
                "baslangic": (r.baslama or r.olusturma).isoformat(),
                "bitis": r.bitis.isoformat() if r.bitis else None,
                "olusturma": r.olusturma.isoformat(),
                "sure_ms": r.sure_ms,
                "toplam": sum(s.values()),
                "gecen": s.get("passed", 0),
                "basarisiz": s.get("failed", 0) + s.get("timedout", 0),
                "flaky": s.get("flaky", 0),
                "atlanan": s.get("skipped", 0),
                # Önce okunur Allure raporu; yoksa ham allure-results (ikincil bağlantı).
                "allure_url": _url(r.id, a.get("allure_html"), dizin)
                or _url(r.id, a.get("allure"), dizin)
                or a.get("allure_url"),
                "allure_rapor": bool(a.get("allure_html")),
                "allure_sonuclari_url": _url(r.id, a.get("allure"), dizin),
                # Playwright HTML raporu imzalı yoldan: rapor içi ekran görüntüsü/ekler çerezsiz
                # yüklenir. JUnit bağlantısı ayrıca verilir (portal rapor yolundan türetmesin).
                "rapor_url": _imzali_url(r.id, _html_index(a.get("html")), dizin)
                or a.get("rapor_url"),
                "junit_url": _url(r.id, a.get("junit"), dizin),
                "sauce_url": sauce.get("url"),
                "sauce_durum": sauce.get("durum"),
                "sauce_neden": sauce.get("neden"),
                "ci_url": a.get("ci_url"),
                "log_url": _url(r.id, a.get("log"), dizin),
                "break_campaign": bool(o.get("break_campaign")),
                "script_id": str(r.script_id) if r.script_id else None,
                "platform": o.get("platform") or script_platform.get(r.script_id) or WEB,
                "saglik_hatasi": (saglik or {}).get("hata")
                if saglik and not saglik.get("ok")
                else None,
                "github_run_id": r.github_run_id,
                "hata": a.get("hata") or a.get("runner_hata"),
                "ozet": a.get("ozet"),
                "isteyen": o.get("isteyen"),
                # Koşu dizini saklama nedeniyle silindi (test-runner `prune_runs`): bağlantı yok.
                "artefakt_budandi": a.get("artefakt_budandi"),
                # GitHub koşusunun yerel kopyası: {durum: indirildi|mevcut|yok|hata|budandi, hata}.
                "github_artefakt": {"durum": gy["durum"], "hata": gy["hata"]}
                if r.kaynak == "github" and gy["durum"]
                else None,
            }
        )
    return out


def _github_yerel_ozeti(a: Mapping[str, Any]) -> dict[str, Any]:
    gy = a.get("github_yerel") if isinstance(a.get("github_yerel"), Mapping) else {}
    durum = gy.get("durum") if isinstance(gy.get("durum"), str) else None
    dizin = gy.get("dizin") if github_artifacts.yol(gy.get("dizin")) is not None else None
    yollar = gy.get("yollar") if isinstance(gy.get("yollar"), Mapping) else {}
    temiz_yollar = {
        k: v
        for k, v in yollar.items()
        if k in ("junit", "json", "html", "allure", "allure_html", "log")
        and isinstance(v, str)
        and not v.startswith("/")
        and ".." not in PurePosixPath(v).parts
    }
    return {
        "kullanilir": bool(dizin and durum in ("indirildi", "mevcut")),
        "dizin": dizin,
        "durum": durum,
        "hata": temiz(gy.get("hata"), 300) if gy.get("hata") else None,
        "yollar": temiz_yollar,
    }


def list_runs(
    session: Session,
    *,
    tetik: str | None = None,
    kaynak: str | None = None,
    sonuc: str | None = None,
    pr_no: int | None = None,
    script_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = select(Run)
    if tetik:
        q = q.where(Run.tetik == tetik)
    if kaynak:
        q = q.where(Run.kaynak == kaynak)
    if sonuc:
        q = q.where(Run.sonuc == sonuc)
    if pr_no is not None:
        q = q.where(Run.pr_no == pr_no)
    if script_id is not None:
        q = q.where(Run.script_id == script_id)
    runs = list(
        session.scalars(q.order_by(Run.olusturma.desc(), Run.id).limit(max(1, min(limit, 200))))
    )
    sabit: set[uuid.UUID] = set()
    if all(x is None for x in (tetik, kaynak, sonuc, pr_no, script_id)):
        # Açık defect adayının kırmızı kanıtı (son yerel kontrolü) pencereden düşmez: yeni
        # tetikler listeyi doldursa da filtresiz listede kalır (`sabit=true`).
        gorulen = {r.id for r in runs}
        for r in _defect_adayi_kosulari(session):
            sabit.add(r.id)
            if r.id not in gorulen:
                runs.append(r)
        runs.sort(key=lambda r: (r.olusturma, str(r.id)), reverse=True)
    out = serialize_runs(session, runs)
    for o in out:
        o["sabit"] = uuid.UUID(o["id"]) in sabit
    return out


def _defect_adayi_kosulari(session: Session, en_cok: int = 20) -> list[Run]:
    """Son durumu `blocked` + `defect_candidate` olan script'lerin en son yerel kontrol koşusu."""
    from tp_core.models.codegen_feature import ScriptCodegen

    scriptler = session.scalars(
        select(Script.id)
        .join(ScriptCodegen, ScriptCodegen.script_id == Script.id)
        .where(Script.durum == "blocked", ScriptCodegen.engel_turu == "defect_candidate")
        .order_by(Script.olusturma.desc())
        .limit(en_cok)
    ).all()
    out: list[Run] = []
    for sid in scriptler:
        run = session.scalars(
            select(Run)
            .where(Run.script_id == sid, Run.tetik == "local_check", Run.sonuc.in_(BITMIS))
            .order_by(Run.olusturma.desc(), Run.id)
            .limit(1)
        ).first()
        if run is not None:
            out.append(run)
    return out


def run_detail(session: Session, run_id: uuid.UUID) -> dict[str, Any] | None:
    run = session.get(Run, run_id)
    if run is None:
        return None
    temel = serialize_runs(session, [run])[0]
    rows = session.execute(
        select(TestResult, TestResultEk)
        .outerjoin(TestResultEk, TestResultEk.test_result_id == TestResult.id)
        .where(TestResult.run_id == run.id)
        .order_by(TestResult.dosya, TestResult.test_adi)
    ).all()
    f_rows = session.execute(
        select(Failure.test_result_id, Failure.id, Failure.test_adi, Failure.sinif, Failure.alt_tur)
        .where(Failure.run_id == run.id)
        .order_by(Failure.test_adi)
    ).all()
    failures = {r.test_result_id: r.id for r in f_rows if r.test_result_id is not None}
    triage = {r.test_result_id: r for r in f_rows if r.test_result_id is not None}
    a = run.artefaktlar or {}
    dizin = a.get("dizin")
    gy = _github_yerel_ozeti(a)
    if not dizin and gy["kullanilir"]:
        dizin = gy["dizin"]
    sonuclar = []
    for tr, ek in rows:
        ekler = []
        for e in (ek.ekler if ek else []) or []:
            if isinstance(e, dict) and e.get("yol") and dizin:
                ekler.append({**e, "url": _url(run.id, e["yol"], dizin)})
        sonuclar.append(
            {
                "id": str(tr.id),
                "test_adi": tr.test_adi,
                "dosya": tr.dosya,
                # Portal birliği: passed | failed | flaky | skipped (timedout → failed, ham ayrı).
                "durum": "failed" if tr.sonuc == "timedout" else tr.sonuc,
                "ham_durum": tr.sonuc,
                "sure_ms": tr.sure_ms or 0,
                "retry": tr.retry,
                "hata_mesaji": tr.hata_mesaji,
                "failure_id": str(failures[tr.id]) if tr.id in failures else None,
                # Faz 4 triage sınıfı (sınıflandırılmadıysa null).
                "triage_sinifi": triage[tr.id].sinif if tr.id in triage else None,
                "triage_alt_tur": triage[tr.id].alt_tur if tr.id in triage else None,
                "case_id": str(tr.test_case_id) if tr.test_case_id else None,
                "a11y": {"ihlal": ek.a11y_ihlal, "kritik": ek.a11y_kritik, "sayfalar": ek.a11y}
                if ek and ek.a11y
                else None,
                "ekler": ekler,
                "denemeler": (ek.denemeler if ek else []) or [],
            }
        )
    return {
        **temel,
        "sonuclar": sonuclar,
        # Koşunun triage sonuçları (test sonucu olmayan ortam hataları dahil).
        "hatalar": [
            {
                "id": str(r.id),
                "test_adi": r.test_adi,
                "sinif": r.sinif,
                "alt_tur": r.alt_tur,
                "test_result_id": str(r.test_result_id) if r.test_result_id else None,
            }
            for r in f_rows
        ],
        "adimlar": a.get("adimlar"),
        "uyarilar": a.get("uyarilar") or [],
        "raporlar": a.get("raporlar"),
        "checks": a.get("checks"),
        "sauce": a.get("sauce"),
        "github": a.get("github"),
        "artefakt_kok": f"/api/artifacts/runs/{run.id}/" if dizin else None,
        "ortam": {k: v for k, v in (run.ortam or {}).items() if k != "saglik"},
        "saglik": (run.ortam or {}).get("saglik"),
    }


def artifact_dir(session: Session, run_id: uuid.UUID) -> Path | None:
    run = session.get(Run, run_id)
    if run is None:
        return None
    a = run.artefaktlar or {}
    dizin = a.get("dizin")
    if isinstance(dizin, str) and RUN_DIR_RE.match(dizin):
        return services.artifacts_root() / dizin
    gy = _github_yerel_ozeti(a)
    if run.kaynak == "github" and gy["kullanilir"]:
        return github_artifacts.yol(gy["dizin"])
    return None


# ------------------------------------------------------------------- artefakt saklama


def mark_pruned_runs(session: Session, *, en_cok: int = 500) -> int:
    """Koşu dizini artık volume'de olmayan bitmiş koşuları `artefakt_budandi` olarak işaretler.

    Dizinleri silen çekirdek değildir: core-worker artefakt volume'ünü salt okur; saklama
    test-runner'dadır (`prune_runs`: en yeni `TP_RUNS_KEEP` işaretsiz koşu, `.keep` kanıtları
    `TP_RUNS_KEEP_EVIDENCE_DAYS`/`_MAX`). Bu geçiş koşu kaydını buna uydurur: `dizin` boşaltılır
    (eski değer `budanan_dizin`), böylece portal/triage/bug bağlamı silinmiş dosyaya bağlantı
    üretmez. Volume bağlı değilse (`<kök>/runs` yok) hiçbir şey işaretlenmez. Dönen: işaretlenen.
    """
    kok = services.artifacts_root()
    try:
        if not (kok / "runs").is_dir():
            return 0
    except OSError:
        return 0
    adaylar = session.execute(
        select(Run.id, Run.artefaktlar["dizin"].astext)
        .where(Run.sonuc.in_(BITMIS), Run.artefaktlar["dizin"].astext.isnot(None))
        .order_by(Run.olusturma)
        .limit(max(1, en_cok))
    ).all()
    zaman = services.now().isoformat()
    n = 0
    for run_id, dizin in adaylar:
        if not dizin or not RUN_DIR_RE.match(dizin):
            continue
        try:
            if (kok / dizin).is_dir():
                continue
        except OSError:
            continue
        n += (
            session.execute(
                text(
                    "UPDATE run SET artefaktlar = artefaktlar || jsonb_build_object("
                    "'dizin', NULL, 'budanan_dizin', CAST(:d AS text), "
                    "'artefakt_budandi', CAST(:z AS text)) "
                    "WHERE id = :id AND artefaktlar->>'dizin' = :d"
                ),
                {"id": run_id, "d": dizin, "z": zaman},
            ).rowcount
            or 0
        )
    return n


# ------------------------------------------------------------------- asistan: koşu logu


def log_yolu(run: Run) -> tuple[Path, str] | None:
    """Koşunun runner logu: `(koşu kökü, köke göre yol)`; yoksa None (AI-ASISTAN-PLANI §5.7).

    Yerel koşu: `artifact_dir` kökü + `artefaktlar["log"]`. GitHub koşusu: core'un yerel kopyası
    (`_github_yerel_ozeti`; durum `indirildi|mevcut`) + `github_yerel.yollar.log`. Yol burada
    doğrulanmaz: okuyan taraf `artifacts.coz(kok, yol)` ve güvenli açma ile okur (artefaktı
    test-runner yazar, güvenilmez).
    """
    a = run.artefaktlar or {}
    dizin = a.get("dizin")
    log = a.get("log")
    if isinstance(dizin, str) and RUN_DIR_RE.match(dizin) and isinstance(log, str) and log:
        return services.artifacts_root() / dizin, log
    gy = _github_yerel_ozeti(a)
    gy_log = gy["yollar"].get("log")
    if run.kaynak == "github" and gy["kullanilir"] and gy_log:
        kok = github_artifacts.yol(gy["dizin"])
        if kok is not None:
            return kok, gy_log
    return None
