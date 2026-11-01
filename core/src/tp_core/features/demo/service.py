"""Sunucu (presenter) demo kontrolleri: locator kırılması ve demo sıfırlaması.

- `POST /demo/break-locator` → iş `demo.break_locator`: `demo/break-locator` dalı `demo-admin`
  kural bypass'ıyla merge edilir (`integrations.forge_demo.break_locator`; denetim "demo
  kırılması"), çalışan demo uygulamasının main'den yeniden derlenmesi istenir (`web`), ardından
  `demo.await_web` uygulama main'i yansıttığında main için `push` CI'ını kuyruğa alır → CI
  kırmızı → triage `test_maintenance/locator` → `POST /failures/{id}/fix`.
- `POST /demo/reset` → iş `demo.reset`: main → `demo-baseline` (`restore_baseline`, yalnızca
  yerel forge; denetim "demo sıfırlaması"), açık `tp/*` ve kırılma PR'ları yorumlanıp kapatılır
  (bağlı script'ler `closed`), uygulama baseline'a yeniden derletilir + baseline için push CI.
  Jira (yalnızca jira-sim): SIFIRLANMAZ — veritabanı korunduğu için `external_ref` satırlarının
  gösterdiği Story/Test anahtarları (TPD-1 onayı, TPD-8.. Test issue'ları) geçerli kalmalı;
  `/sim/reset` anahtar sayacını geri sardığından yeni Bug'lar eski anahtarları yeniden alır ve
  çakışırdı. Bunun yerine yalnızca bu sistemin açtığı Faz 4 Bug'ları (`AI-generated` + `tp-<uuid>`
  etiketli) silinir; sayaç ilerlemeye devam eder, mükerrer aramasında TPD-5 yine ilk adaydır.
  Çekirdek veritabanı silinmez (denetim append-only); tam sıfırlama (jira-sim dahil) `make reset`.

Locator kırılma/onarım demosu yalnızca yerel forge'da (TP_FORGE=local): `/locator-probe` ve onarımın
`/check`'i compose'da ÇALIŞAN demo-app-web'i ölçer ve onu yalnızca `scripts/demo-web-sync.sh` yerel
forge arşivinden yeniden derler. GitHub kipinde kırılma `409` + Türkçe neden ile reddedilir (yoksa
uygulama eski testid'yi sunar → `sha_eslesmesi=farkli` → öneri yok → onarılamaz kırılma).

Ön koşul (locator onarımı): kırılmadan ÖNCE en az bir yeşil koşu (push/deploy/baseline…) olmalı;
onarım rol + adı "son yeşil" kanıtla doğrular. Yoksa `POST /demo/break-locator` 409 ile yönerge
verir (`make demo-reset` baseline push CI'ı kuyruğa alır); `?zorla=true` bilerek atlar (onarım
sonra "son yeşil yok" diye engellenir). `GET /demo/status` → `onarim_on_kosulu`.

İstek koruması: kırılma/sıfırlama isteği işlem ömürlü advisory kilit (`demo:forge`) altında
"süren iş var mı" denetler; iki eşzamanlı tıklama iki iş açamaz.

Kırılma/sıfırlamayı isteyen sunucu (portal kullanıcısı) ayrı denetim olayına (`demo.break`,
`demo.reset`) yazılır; bypass'ı kullanan kimlik her zaman insan `demo-admin` hesabıdır (bot merge
etmez — Constitution, Güvenlik: "ruleset bypass yalnızca insan demo-admin hesabındadır").
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from tp_core.audit import PgAuditLog, append_audit, audit_on_commit
from tp_core.events.bus import publish_tx
from tp_core.features.demo import web
from tp_core.integrations import forge_demo
from tp_core.integrations.forge import BYPASS_ACTOR, ForgeError
from tp_core.models import PullRequest, Script, session_scope
from tp_core.ports import ForgePort
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue
from tp_core.workflow.service import SYSTEM, Principal, WorkflowError, transition

log = logging.getLogger(__name__)

BREAK_JOB = "demo.break_locator"
RESET_JOB = "demo.reset"
AWAIT_JOB = "demo.await_web"
POLL_ENV = "TP_DEMO_WEB_POLL_S"
WAIT_ENV = "TP_DEMO_WEB_WAIT_S"
# Uygulama hedef commit'i zaten yansıtsa da bu süre boyunca uygulanmamış yenileme isteği beklenir
# (demo-web-sync konteyneri yeniden oluştururken CI sağlıkta düşmesin); süre dolunca CI açılır.
ISTEK_GRACE_ENV = "TP_DEMO_WEB_ISTEK_BEKLEME_S"
KAPATILACAK_ONEKLER = ("tp/", "demo/")
KAPANIS_YORUMU = (
    "Demo sıfırlaması: main demo-baseline'a döndü; bu PR kapatıldı (sunucu isteği, denetimli)."
)


class DemoRejected(WorkflowError):
    pass


GITHUB_KIRILMA_YOK = (
    "Locator kırılma/onarım demosu yalnızca yerel forge'da çalışır (TP_FORGE=local). GitHub "
    "kipinde çalışan demo-app-web GitHub main'inden yeniden derlenmez; locator ölçümü ve onarım "
    "kontrolü eski uygulamayı görür ('sha_eslesmesi=farkli') ve onarım önerisi üretilemez. "
    "Sunum için TP_FORGE=local kullanın; GitHub'da kırılmayı elle yapacaksanız demo-app-web'i "
    "GitHub main sha'sından elle derleyip /forge/demo-app-web.sha'yı güncelleyin."
)


# ---------------------------------------------------------------------- fabrikalar

_factories: dict[str, Callable[..., Any]] = {}


def set_factories(
    *,
    forge: Callable[[], ForgePort] | None = None,
    yenileyici: Callable[[], web.WebYenileyici] | None = None,
    calisan: Callable[[], web.CalisanUygulama] | None = None,
    jira_reset: Callable[[], dict[str, Any]] | None = None,
    simdi: Callable[[], datetime] | None = None,
    sha_dosyasi: Callable[[], str | None] | None = None,
) -> None:
    _factories.update(
        forge=forge,
        yenileyici=yenileyici,
        calisan=calisan,
        jira_reset=jira_reset,
        simdi=simdi,
        sha_dosyasi=sha_dosyasi,
    )


def reset_factories() -> None:
    _factories.clear()


def _forge() -> ForgePort:
    f = _factories.get("forge")
    if f is not None:
        return f()
    from tp_core.integrations.forge import get_forge

    return get_forge()


def _yenileyici() -> web.WebYenileyici:
    f = _factories.get("yenileyici")
    return f() if f is not None else web.varsayilan_yenileyici()


def _calisan() -> web.CalisanUygulama:
    f = _factories.get("calisan")
    return f() if f is not None else web.calisan_uygulama()


def _uygulanmamis_istek(sha: str, en_erken: datetime) -> dict[str, Any] | None:
    f = _factories.get("uygulanmamis_istek")
    return f(sha, en_erken) if f is not None else web.uygulanmamis_istek(sha, en_erken)


def _sha_dosyasi() -> str | None:
    f = _factories.get("sha_dosyasi")
    return f() if f is not None else web.sha_dosyasindaki()


def _simdi() -> datetime:
    f = _factories.get("simdi")
    return f() if f is not None else datetime.now(UTC)


def _yerel_forge_mu(forge: Any) -> bool:
    return callable(getattr(forge, "reset_branch", None))


def _yerel_forge_kipi() -> bool:
    """İstek yolunda forge kurmadan kip denetimi (fabrika varsa onun forge'u belirler)."""
    f = _factories.get("forge")
    if f is not None:
        return _yerel_forge_mu(f())
    from tp_core.config import get_settings

    return get_settings().forge == "local"


def _ortam_int(ad: str, varsayilan: int) -> int:
    try:
        return max(int((os.environ.get(ad) or "").strip() or varsayilan), 1)
    except ValueError:
        return varsayilan


def _olay(conn: Any, ad: str, veri: Mapping[str, Any]) -> None:
    publish_tx(conn, ad, veri)


# ------------------------------------------------------------------------ istekler


def _is_iste(session: Session, tur: str, user: Principal, eylem: str) -> dict[str, Any]:
    from tp_core.workflow.jobs import idempotency_lock

    # Denetle-sonra-kuyruğa-al yarışı: eşzamanlı istekler kilitte sıralanır (işlem sonuna dek).
    idempotency_lock(session.connection(), "demo:forge")
    suren = session.execute(
        text(
            "SELECT id FROM job WHERE tur IN (:a, :b) AND durum IN ('queued', 'retry', 'running') "
            "ORDER BY olusturma LIMIT 1"
        ),
        {"a": BREAK_JOB, "b": RESET_JOB},
    ).first()
    if suren is not None:
        raise DemoRejected("Başka bir demo kırılması/sıfırlaması sürüyor; bitince yeniden deneyin.")
    job_id = enqueue(
        session.connection(),
        tur,
        {"isteyen": user.kullanici_adi},
        max_deneme=1,
    )
    audit_on_commit(
        session,
        user.kullanici_adi,
        f"demo.{eylem}_requested",
        "forge:main",
        {"job_id": str(job_id)},
    )
    return {"job_id": str(job_id), "durum": "queued", "eylem": eylem}


ON_KOSUL_YONERGE = (
    "Önce yeşil bir temel koşu gerekir: `make demo-reset` (main → demo-baseline + baseline push "
    "CI) çalıştırın ya da Kontrol Kulesi'nden main için push CI koşturun; koşu yeşile dönünce "
    "kırın. (Bilerek atlamak için: zorla=true — onarım sonra 'son yeşil yok' diye engellenir.)"
)


def onarim_on_kosulu(session: Session) -> dict[str, Any]:
    """Locator onarımının ön koşulu: kırılmadan önce yeşil bir koşu (son yeşil kanıt)."""
    from tp_core.features.repair.service import SON_YESIL_TETIKLER

    row = session.execute(
        text(
            "SELECT id, commit, tetik, olusturma FROM run WHERE sonuc = 'passed' "
            "AND tetik = ANY(:t) ORDER BY olusturma DESC LIMIT 1"
        ),
        {"t": list(SON_YESIL_TETIKLER)},
    ).first()
    if row is None:
        return {"hazir": False, "son_yesil_kosu": None, "yonerge": ON_KOSUL_YONERGE}
    return {
        "hazir": True,
        "son_yesil_kosu": {"run_id": str(row.id), "commit": row.commit, "tetik": row.tetik,
                           "zaman": row.olusturma.isoformat() if row.olusturma else None},
        "yonerge": None,
    }  # fmt: skip


def request_break(session: Session, user: Principal, *, zorla: bool = False) -> dict[str, Any]:
    if not _yerel_forge_kipi():
        # `zorla` yalnızca yeşil-koşu ön koşulunu atlar; GitHub kipindeki kırılma her durumda
        # onarılamaz olurdu (çalışan uygulama main'i yansıtmaz).
        audit_on_commit(
            session, user.kullanici_adi, "demo.break_refused", "forge:main",
            {"neden": "GitHub kipi: locator demosu yalnızca yerel forge", "yonerge":
             GITHUB_KIRILMA_YOK},
        )  # fmt: skip
        session.commit()
        raise DemoRejected(f"Kırılma yapılmadı. {GITHUB_KIRILMA_YOK}")
    on = onarim_on_kosulu(session)
    if not on["hazir"] and not zorla:
        audit_on_commit(
            session, user.kullanici_adi, "demo.break_refused", "forge:main",
            {"neden": "son yeşil koşu yok", "yonerge": ON_KOSUL_YONERGE},
        )  # fmt: skip
        session.commit()
        raise DemoRejected(f"Kırılma yapılmadı: kırılmadan önce yeşil koşu yok. {ON_KOSUL_YONERGE}")
    out = _is_iste(session, BREAK_JOB, user, "break")
    return {
        **out,
        "mesaj": "Demo locator kırılması kuyruğa alındı (demo-admin bypass'ı)."
        + ("" if on["hazir"] else " UYARI: yeşil temel koşu yok; onarım engellenecek."),
        "onarim_on_kosulu": on,
    }


def request_reset(session: Session, user: Principal) -> dict[str, Any]:
    out = _is_iste(session, RESET_JOB, user, "reset")
    return {**out, "mesaj": "Demo sıfırlaması kuyruğa alındı."}


# ------------------------------------------------------------------ CI kapısı (web)


def ci_after_web(
    conn: Any, sha: str, eylem: str, isteyen: str, *, baslangic: datetime | None = None
) -> uuid.UUID:
    """`sha` için push CI'ını çalışan uygulama onu yansıtınca kuyruğa alacak işi planlar.

    Diğer yollar da kullanabilir (ör. `forge_demo` CLI: `make break` CI yarışını önlemek için).
    """
    bas = (baslangic or _simdi()).isoformat()
    return enqueue(
        conn,
        AWAIT_JOB,
        {"sha": sha, "eylem": eylem, "isteyen": isteyen, "baslangic": bas, "deneme": 0},
        idempotency_key=f"{AWAIT_JOB}:{sha}:{eylem}:{bas}",
        max_deneme=1,
    )


def run_await_web(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    yuk = dict(ctx.yuk or {})
    sha = str(yuk["sha"])
    eylem = str(yuk.get("eylem") or "break")
    isteyen = str(yuk.get("isteyen") or BYPASS_ACTOR)
    deneme = int(yuk.get("deneme") or 0)
    baslangic = datetime.fromisoformat(str(yuk.get("baslangic") or _simdi().isoformat()))
    forge = _forge()
    try:
        main = forge.head_sha("main")
    except ForgeError as exc:
        raise PermanentJobError(f"forge okunamadı: {exc}") from exc
    if main != sha:
        with engine.begin() as conn:
            append_audit(
                conn,
                "system",
                "demo.ci_skipped",
                "forge:main",
                {"sha": sha, "main": main, "neden": "main bu arada değişti"},
            )
        return {"durum": "atlandi", "neden": "main değişti", "main": main}
    calisan = _calisan()
    eslesiyor, neden = web.uygulama_eslesiyor(forge, sha, calisan.sha)
    if eslesiyor and calisan.kaynak == "build_json":
        # Konteyner `/build.json` ile yeni commit'i beyan etse de toolchain `/check` `app` adımı
        # `/forge/demo-app-web.sha`'yı okur (demo-web-sync.sh onu servis sağlıklı olunca yazar).
        # Dosya geride kalırsa CI `app=farkli` ile ortam koşusu olurdu: dosya da eşleşene dek
        # beklenir. (Dosya hiç yoksa toolchain `DEMO_APP_BUILD_SHA`'ya düşer; engel değil.)
        dosya_sha = _sha_dosyasi()
        if dosya_sha is not None:
            dosya_ok, dosya_neden = web.uygulama_eslesiyor(forge, sha, dosya_sha)
            if not dosya_ok:
                eslesiyor = False
                neden = f"/forge/demo-app-web.sha henüz güncel değil ({dosya_neden})"
    if eslesiyor:
        gecen_s = (_simdi() - baslangic).total_seconds()
        if gecen_s < _ortam_int(ISTEK_GRACE_ENV, 180):
            istek = _uygulanmamis_istek(sha, baslangic - timedelta(seconds=60))
            if istek is not None:
                eslesiyor = False
                neden = (
                    "demo-app-web yenileme isteği henüz uygulanmadı (demo-web-sync konteyneri "
                    "yeniden oluşturuyor olabilir); CI uygulama hazır olunca açılır"
                )
    if eslesiyor:
        from tp_core.features.ci import enqueue_ci

        with session_scope() as s:
            mevcut = _push_ci_zaten(s, sha)
            if mevcut is not None:
                # Aynı forge değişikliği için ikinci bekleme işi (ör. tekrar basılan "kır"
                # düğmesi): ikinci CI koşusu açılmaz.
                return {"durum": "zaten_kuyrukta", "run_id": mevcut,
                        "uygulama": calisan.as_dict()}  # fmt: skip
            run_id = enqueue_ci(
                s,
                sha,
                "push",
                None,
                isteyen=isteyen,
                anahtar=f"demo:{eylem}:{sha}:{baslangic.isoformat()}",
            )
            audit_on_commit(
                s,
                isteyen,
                "demo.ci_enqueued",
                "forge:main",
                {"sha": sha, "eylem": eylem, "run_id": str(run_id), "uygulama": calisan.as_dict(),
                 "eslesme": neden, "bekleme_turu": deneme},
            )  # fmt: skip
            _olay(
                s.connection(),
                "demo.web_ready",
                {"sha": sha, "eylem": eylem, "run_id": run_id, "uygulama_sha": calisan.sha},
            )
        return {"durum": "ci_kuyrukta", "run_id": str(run_id), "uygulama": calisan.as_dict()}
    gecen = (_simdi() - baslangic).total_seconds()
    if gecen >= _ortam_int(WAIT_ENV, 900):
        with engine.begin() as conn:
            append_audit(
                conn,
                "system",
                "demo.web_timeout",
                "forge:main",
                {"sha": sha, "eylem": eylem, "uygulama": calisan.as_dict(), "neden": neden,
                 "yonerge": web.YONERGE},
            )  # fmt: skip
            _olay(
                conn,
                "demo.web_timeout",
                {"sha": sha, "eylem": eylem, "neden": neden, "yonerge": web.YONERGE},
            )
        raise PermanentJobError(
            "Çalışan demo uygulaması main'i yansıtmadı; CI kuyruğa alınmadı (ortam koşusu "
            f"üretilmez). Neden: {neden}. {web.YONERGE}"
        )
    with engine.begin() as conn:
        enqueue(
            conn,
            AWAIT_JOB,
            {**yuk, "deneme": deneme + 1},
            idempotency_key=f"{AWAIT_JOB}:{sha}:{eylem}:{baslangic.isoformat()}:{deneme + 1}",
            run_after=_simdi() + timedelta(seconds=_ortam_int(POLL_ENV, 5)),
            max_deneme=1,
        )
        if deneme == 0:
            _olay(
                conn,
                "demo.web_waiting",
                {"sha": sha, "eylem": eylem, "neden": neden, "yonerge": web.YONERGE},
            )
    return {"durum": "bekleniyor", "neden": neden, "deneme": deneme}


def _push_ci_zaten(s: Session, sha: str) -> str | None:
    """Son forge değişikliğinden (demo kırılması/sıfırlaması) sonra `sha` için açılmış push CI."""
    row = s.execute(
        text(
            "SELECT r.id FROM run r WHERE r.commit = :sha AND r.tetik = 'push' AND r.olusturma >= "
            "COALESCE((SELECT max(zaman) FROM audit_event WHERE eylem IN (:b, :z)), "
            "'-infinity'::timestamptz) ORDER BY r.olusturma DESC LIMIT 1"
        ),
        {"sha": sha, "b": forge_demo.AUDIT_BREAK, "z": forge_demo.AUDIT_BASELINE},
    ).first()
    return str(row.id) if row else None


def _web_ve_ci(engine: Engine, forge: Any, sha: str, eylem: str, isteyen: str) -> dict[str, Any]:
    """Uygulama yenileme isteği + CI kapısı işi. GitHub kipinde CI doğrudan (Actions)."""
    if not _yerel_forge_mu(forge):
        from tp_core.features.ci import enqueue_ci

        with session_scope() as s:
            run_id = enqueue_ci(
                s, sha, "push", None, isteyen=isteyen,
                anahtar=f"demo:{eylem}:{sha}:{_simdi().isoformat()}",
            )  # fmt: skip
        return {"web": {"yontem": "kapali", "durum": "atlandi"}, "ci_run_id": str(run_id)}
    try:
        istek = _yenileyici().iste(sha, eylem, isteyen)
    except Exception as exc:  # yenileme isteği yazılamadı: CI yine beklemeye alınır
        istek = {"durum": "hata", "hata": f"{type(exc).__name__}: {exc}"[:300]}
    with engine.begin() as conn:
        job = ci_after_web(conn, sha, eylem, isteyen)
    return {"web": istek, "ci_bekleme_isi": str(job)}


# ------------------------------------------------------------------------ kırılma


def run_break(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    isteyen = str((ctx.yuk or {}).get("isteyen") or "presenter")
    forge = _forge()
    if not _yerel_forge_mu(forge):
        raise PermanentJobError(f"Kırılma yapılmadı. {GITHUB_KIRILMA_YOK}")
    if not callable(getattr(forge, "merge_pr_detailed", None)):
        raise PermanentJobError("forge demo kırılmasını desteklemiyor (merge_pr_detailed yok)")
    try:
        sonuc = forge_demo.break_locator(
            forge,  # type: ignore[arg-type]
            PgAuditLog(engine),
            actor=BYPASS_ACTOR,
            ci=lambda _sha, _actor: None,  # CI uygulama yenilenince (demo.await_web)
        )
    except ForgeError as exc:
        with engine.begin() as conn:
            append_audit(
                conn,
                isteyen,
                "demo.break_failed",
                "forge:main",
                {"hata": str(exc)[:500], "yonerge": "demo-admin yetkisini ve forge'u denetleyin"},
            )
        raise PermanentJobError(f"Demo kırılması başarısız: {exc}") from exc
    ek = _web_ve_ci(engine, forge, sonuc.main_after, "break", isteyen)
    ozet = {
        "isteyen": isteyen,
        "bypass_aktoru": BYPASS_ACTOR,
        "degisti": sonuc.changed,
        "pr": sonuc.pr_number,
        "main_once": sonuc.main_before,
        "main_sonra": sonuc.main_after,
        "testid": sonuc.testid,
        "forge_denetim_id": sonuc.audit_id,
        **ek,
    }
    with engine.begin() as conn:
        append_audit(conn, isteyen, "demo.break", "forge:main", ozet)
        _olay(conn, "demo.break", ozet)
    return ozet


# ----------------------------------------------------------------------- sıfırlama


_TP_ETIKETI = re.compile(r"tp-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
AI_ETIKETI = "AI-generated"
SILME_SINIRI = 200


def _jira_sil(jira: Any, key: str) -> None:
    sil = getattr(jira, "delete_issue", None)
    if callable(sil):
        sil(key)
        return
    # RestJira'da genel silme yöntemi yok; aynı kimlik/yeniden deneme yolu (yazma kimliği).
    jira._call("DELETE", f"/issue/{quote(key, safe='')}", write=True)


def ai_buglarini_sil(jira: Any, proje: str) -> dict[str, Any]:
    """Sistemin açtığı Bug'ları (`AI-generated` + `tp-<uuid>`) siler; başka kayda dokunmaz.

    jira-sim'i `/sim/reset` ile sıfırlamak yerine: anahtar sayacı ilerlemeye devam eder (silinen
    anahtar yeniden verilmez), Story/Test issue'ları ve PO onayı yerinde kalır; veritabanındaki
    `external_ref` satırları geçerli kalır. Tohum Bug'ları (TPD-5…) etiketsizdir, silinmez.
    """
    from tp_core.features.bugs.jql import label_jql

    silinen: list[str] = []
    hatalar: list[dict[str, str]] = []
    goruldu: set[str] = set()
    for _ in range(10):
        bulunan = jira.search(label_jql(proje, AI_ETIKETI), max_results=100)
        adaylar = [
            i for i in bulunan
            if i.key not in goruldu and i.issue_type == "Bug"
            and any(_TP_ETIKETI.fullmatch(str(e)) for e in i.labels or [])
        ]  # fmt: skip
        if not adaylar:
            break
        for i in adaylar:
            goruldu.add(i.key)
            if len(silinen) >= SILME_SINIRI:
                break
            try:
                _jira_sil(jira, i.key)
            except Exception as exc:  # tek kayıt hatası diğerlerini durdurmaz
                hatalar.append({"key": i.key, "hata": f"{type(exc).__name__}: {exc}"[:200]})
                continue
            silinen.append(i.key)
    durum = "tamam" if not hatalar else "kismi"
    return {
        "durum": durum,
        "yontem": "ai_bug_temizligi",
        "silinen": silinen,
        "hatalar": hatalar,
        "not": "jira-sim sıfırlanmadı: anahtar sayacı ve Story/Test issue'ları korunur",
    }


def _jira_temizle() -> dict[str, Any]:
    f = _factories.get("jira_reset")
    if f is not None:
        return f()
    try:
        from tp_core.integrations.jira import get_jira, get_jira_settings

        ayar = get_jira_settings()
        if not ayar.is_simulator:
            return {"durum": "atlandi",
                    "neden": "gerçek Jira: demo sıfırlaması dokunmaz (make jira-seed)"}  # fmt: skip
        return ai_buglarini_sil(get_jira(), ayar.jira_project)
    except Exception as exc:  # Jira erişilemedi: forge sıfırlaması yine tamamlanır
        return {"durum": "hata", "neden": f"{type(exc).__name__}: {exc}"[:300]}


def _silinen_buglari_isaretle(silinen: list[str], isteyen: str) -> list[str]:
    """Silinen Jira Bug'larını açan taslaklar portalda ölü bağlantı göstermesin (bugs şeridi)."""
    if not silinen:
        return []
    try:
        from tp_core.features.bugs.service import mark_jira_deleted
    except ImportError:
        return []
    try:
        with session_scope() as s:
            return mark_jira_deleted(s, list(silinen), neden="demo sıfırlaması", aktor=isteyen)
    except Exception as exc:  # işaret sıfırlamayı düşürmesin; denetimde görünür
        log.warning("silinen Bug taslakları işaretlenemedi: %s", exc)
        return []


def _prlari_kapat(engine: Engine, forge: Any, isteyen: str) -> list[dict[str, Any]]:
    listele = getattr(forge, "list_prs", None)
    kapat = getattr(forge, "close_pr", None)
    if listele is None or kapat is None:
        return []
    kapanan: list[dict[str, Any]] = []
    for pr in listele("open"):
        if not pr.branch.startswith(KAPATILACAK_ONEKLER):
            continue
        with contextlib.suppress(ForgeError):
            forge.comment_pr(pr.number, KAPANIS_YORUMU)
        try:
            kapat(pr.number)
        except ForgeError as exc:
            kapanan.append({"pr": pr.number, "dal": pr.branch, "hata": str(exc)[:200]})
            continue
        kapanan.append({"pr": pr.number, "dal": pr.branch, "hata": None})
    numaralar = [k["pr"] for k in kapanan if k["hata"] is None]
    if numaralar:
        with session_scope() as s:
            for sc in s.scalars(
                select(Script).where(Script.pr_no.in_(numaralar), Script.durum == "pr_open")
            ).all():
                transition(s, sc, "closed", SYSTEM, "pr_open", sebep="demo sıfırlaması",
                           ozet={"pr": sc.pr_no, "isteyen": isteyen})  # fmt: skip
            for satir in s.scalars(
                select(PullRequest).where(PullRequest.number.in_(numaralar))
            ).all():
                if satir.durum == "open":
                    satir.durum = "closed"
    return kapanan


def run_reset(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    isteyen = str((ctx.yuk or {}).get("isteyen") or "presenter")
    forge = _forge()
    if not _yerel_forge_mu(forge):
        raise PermanentJobError(
            "Demo sıfırlaması yalnızca yerel forge'da (TP_FORGE=local); GitHub'da revert PR'ı "
            "ve make jira-seed kullanın."
        )
    try:
        sonuc = forge_demo.restore_baseline(
            forge, PgAuditLog(engine), actor=BYPASS_ACTOR, ci=lambda _s, _a: None
        )
    except ForgeError as exc:
        raise PermanentJobError(f"main demo-baseline'a döndürülemedi: {exc}") from exc
    kapanan = _prlari_kapat(engine, forge, isteyen)
    ek = _web_ve_ci(engine, forge, sonuc.main_after, "baseline", isteyen)
    jira = _jira_temizle()
    isaretlenen = _silinen_buglari_isaretle(jira.get("silinen") or [], isteyen)
    ozet = {
        "isteyen": isteyen,
        "bypass_aktoru": BYPASS_ACTOR,
        "forge": {
            "degisti": sonuc.changed,
            "main_once": sonuc.main_before,
            "main_sonra": sonuc.main_after,
            "testid": sonuc.testid,
            "denetim_id": sonuc.audit_id,
        },
        "kapanan_prlar": kapanan,
        "jira": jira,
        "veritabani": {
            "durum": "dokunulmadi",
            "neden": "denetim ve geçmiş append-only; tam sıfırlama için `make reset` (denetim "
            "dışa aktarılır, sonra silinir)",
            # Silinen Bug'ları açan taslaklar: yalnızca `bug_draft_ek.yayin.jira_silindi` işareti
            # (bağlantı kaldırılır; durum/onay geçmişi değişmez).
            "jira_silindi_isaretlenen_taslaklar": isaretlenen,
        },
        **ek,
    }
    with engine.begin() as conn:
        append_audit(conn, isteyen, "demo.reset", "forge:main", ozet)
        _olay(conn, "demo.reset", ozet)
    return ozet


# ------------------------------------------------------------------------- durum


MODEL_DURUMU_EYLEM = "worker.model_mode"


def model_durumu_hesapla() -> dict[str, Any]:
    """core-worker'ın etkin model kipi; anahtarın yalnızca VARLIĞI (değer asla) yazılır."""
    from tp_core.gateway.config import GatewaySettings, resolve_mode

    gs = GatewaySettings()
    key = gs.anthropic_api_key.get_secret_value() if gs.anthropic_api_key else ""
    ws = gs.anthropic_workspace_id.get_secret_value() if gs.anthropic_workspace_id else ""
    return {
        "ayar": gs.model_mode,
        "mod": resolve_mode(gs),
        "replay_strict": bool(gs.replay_strict),
        "anahtar_var": bool(key),
        "calisma_alani_var": bool(ws),
        "saglayici": gs.model_provider,
    }


def model_durumunu_kaydet(conn: Any) -> None:
    """Worker açılışında model kipini denetime yazar (son kayıtla aynıysa yazmaz)."""
    yeni = model_durumu_hesapla()
    son = conn.execute(
        text("SELECT ozet FROM audit_event WHERE eylem = :e ORDER BY id DESC LIMIT 1"),
        {"e": MODEL_DURUMU_EYLEM},
    ).scalar()
    if isinstance(son, dict) and {k: son.get(k) for k in yeni} == yeni:
        return
    append_audit(conn, "system", MODEL_DURUMU_EYLEM, "core-worker", yeni)


def model_durumu_oku(session: Session) -> dict[str, Any] | None:
    """`/demo/status` → `model`: core-worker'ın son açılış bildirimi (yoksa null = bilinmiyor)."""
    row = session.execute(
        text("SELECT ozet, zaman FROM audit_event WHERE eylem = :e ORDER BY id DESC LIMIT 1"),
        {"e": MODEL_DURUMU_EYLEM},
    ).first()
    if row is None or not isinstance(row[0], dict):
        return None
    ozet = dict(row[0])
    ozet["aciklama"] = f"core-worker açılışında bildirdi ({row[1].isoformat()})"
    ozet["zaman"] = row[1].isoformat()
    return ozet


def degerlendirme_durumu() -> list[dict[str, Any]] | dict[str, Any]:
    """Prompt paketlerinin değerlendirme durumu (rules/evaluations.yaml; "canlı değerlendirme
    bekliyor" dürüst etiketiyle). Okunamazsa `{hata}` (portal "bilinmiyor" gösterir)."""
    from tp_core.gateway.config import find_rules_dir
    from tp_core.gateway.evaluation import evaluation_statuses

    try:
        st = evaluation_statuses(find_rules_dir())
    except Exception as exc:
        return {"hata": str(exc)[:200]}
    return [
        {"paket": s.bundle_id, "surum": s.prompt_version, "durum": s.status, "etiket": s.label}
        for s in sorted(st.values(), key=lambda s: s.bundle_id)
    ]


def durum(forge: Any | None = None, session: Session | None = None) -> dict[str, Any]:
    forge = forge or _forge()
    out: dict[str, Any] = {"forge": {}, "uygulama": {}, "web_yenileme_istegi": None}
    out["degerlendirme"] = degerlendirme_durumu()
    yerel = _yerel_forge_mu(forge)
    out["locator_demo"] = {"destekleniyor": yerel, "neden": None if yerel else GITHUB_KIRILMA_YOK}
    if session is not None:
        try:
            out["model"] = model_durumu_oku(session)
        except Exception:  # durum ucu yine yanıt verir; model bilinmiyor
            out["model"] = None
        try:
            out["onarim_on_kosulu"] = onarim_on_kosulu(session)
        except Exception as exc:  # durum ucu yine yanıt verir
            out["onarim_on_kosulu"] = {"hazir": None, "hata": str(exc)[:200]}
    try:
        main = forge.head_sha("main")
        web_testid = forge_demo.testid_state(forge, "main")
        e2e_testid = forge_demo.e2e_testid_state(forge, "main")
        out["forge"] = {"main": main, "testid": web_testid, "e2e_testid": e2e_testid}
        out["locator_durumu"] = forge_demo.locator_durumu(web_testid, e2e_testid)
        try:
            baseline = forge.head_sha(forge_demo.BASELINE_TAG)
        except ForgeError:
            baseline = None
        out["forge"].update(baseline=baseline, main_baseline_mi=baseline == main)
    except ForgeError as exc:
        out["forge"] = {"hata": str(exc)[:300]}
        main = None
    calisan = _calisan()
    out["uygulama"] = calisan.as_dict()
    if main:
        eslesiyor, neden = web.uygulama_eslesiyor(forge, main, calisan.sha)
        out["uygulama"].update(main_ile_eslesiyor=eslesiyor, neden=neden)
        if not eslesiyor:
            out["uygulama"]["yonerge"] = web.YONERGE
    out["web_yenileme_istegi"] = web.bekleyen_istek()
    return out
