"""Locator onarımı (TEKNIK-TASARIM §8.7; Constitution I, VI, VIII, XI).

Akış (`POST /failures/{id}/fix` → iş `repair.fix`, model çağrısı YOK — tamamen deterministik):

1. Hata `test_maintenance/locator` olmalı; `environment` (sağlık kontrolü başarısız) asla onarılmaz.
2. Kırık testId ve kapsayıcı: triage önerisi (`failure_ek.oneri`) ya da hata metnindeki locator.
3. `main`'in sembol tablosunda o testId'yi taşıyan locator anahtarı (rol, ad, `within`).
4. Aday: toolchain `/locator-probe` (çalışan uygulamada `getByRole(rol, {ad})`, `within` varsa
   başarısız adımdaki kapsayıcıda). Tek eşleşme + geçerli testId + `sha_eslesmesi != farkli`
   olmalı; 0 / çoklu → öneri yok (insana). Dört sha alanı onarım kaydında aynen saklanır.
5. Doğrulama: son yeşil durumun aria snapshot'ında rol + ad tek elemana (kapsamlıysa her
   kapsayıcıda tek elemana) karşılık gelmeli. Kaynaklar sırayla: triage önerisindeki son yeşil
   snapshot → son yeşil koşunun artefaktlarındaki aria dosyaları (`locators.spec.ts` yeşil
   koşuda `<sayfa>.aria.yml` yazar; GitHub kipinde koşu dizini yoktur, içe aktarımda artefakttan
   alınan `run_aria` kopyası okunur) → insan onaylı (merge edilmiş) kod üretiminin ajan
   snapshot'ları → yalnızca `TP_REPAIR_ARIA_FALLBACK=sozlesme` ile açıkça istenirse ve son yeşil
   koşuda HİÇ aria dosyası yoksa: o koşuda geçen ve bu locator'ın grubunu gerçekten sınayan
   `locators.spec.ts` sözleşme testi (etiketli yedek). Hiçbiri yoksa PR açılmaz.
6. Yama: `main`'deki `pages/**/locators.ts` içinde YALNIZCA o anahtarın `testId` literal'i;
   `tp/repair-<failure-id>` dalına bot commit'i. toolchain `/ast-guard mode=repair` (base=main)
   ok olmalı.
7. Yerel kontrol: `/check` TAM paket (etkilenen tüm testler dahil), `ast_guard_mode=repair`,
   CI ile aynı yeniden deneme (`retries=1`: yeniden denemede geçen test `flaky` olarak kayda
   yazılır, engellemez); yeşil olmalı ve etkilenen her spec raporda koşmuş olmalı (kayıt `run`,
   tetik `local_check`). Sağlık başarısızsa `environment`, PR yok. Kırmızıysa engel nedeni
   kırmızı testleri (etkilenen/ilgisiz) adlarıyla verir.
8. Bot PR (`tp-repair` etiketi) — merge yalnızca insanla (`/prs/{n}/merge` → `request_merge`).

Uygulama (Java/Appium; 009 mobil-masaüstü) hataları aynı kapılardan geçer, adımlar platforma göre:
2. sembol tablosu `/symbols` + `platform` (Java, `java-araclar symbols`); 3–4. aday ve kanıt
triage önerisindeki hata anı sayfa kaynağından (`triage.java`; mümkünse koşu dizinindeki
`sayfa-kaynagi.xml` yeniden okunup aday yeniden hesaplanır); 5. yama
`<e2e-app kökü>/src/test/java/**/ekranlar/Kimlikler.java` içinde YALNIZCA o sabitin string
literal'i (`locators.patch_kimlik`, `java-araclar locators patch` kurallarıyla); 6. `/ast-guard`
`mode=repair` + `platform` (Java repair koruması: yalnızca Kimlikler.java kimlik literal'i değişir);
7. `/check` tam paket + `platform` (cihazda Appium koşusu). Script `platform`'u onarılan testin
platformudur.

Web + Java (Playwright for Java; 011 üretim dili §2.8) hataları da aynı kapılardan geçer: hat
koşunun DİLİNE göre seçilir (`onarim_dili`), araç/ortam platforma göre. Aday web yöntemiyle
(triage önerisinin hata anı DOM'u `sayfa.html` / trace DOM'u; mümkünse koşu dizininden yeniden
okunup aday yeniden hesaplanır), yama Java yöntemiyle (`<e2e-java kökü>/…/ekranlar/Kimlikler.java`,
`locators.patch_kimlik`), sembol tablosu / koruma / yerel kontrol `{lang: java, platform: web}`
(check adı `local-ci`), etkilenen testler `e2e-java/src/test/java` (`uretilen/` + `testler/`).

Uygunluk (Constitution XI): yalnızca deterministik kuralın (`karar_kaynagi='rule'`) locator önerisi
(`oneri_turu='locator_fix'`, `failure_ek.oneri`) onarılır; model etiketi yetmez.

Aynı locator değişikliği (`locator_key` + `new_testid`) birden çok hatada (aynı ya da önceki
koşularda) önerildiyse tek onarım hepsini kapatır: açık/merge edilmiş paylaşılan onarım döner,
merge sonrası eski koşulardaki aynı öneriler `merged` olur. Engellenen onarımın yeniden denemesi
aynı script'i kullanır (yeni satır açılmaz). Worker yarıda kalan onarımları (`sweep_stuck`)
`failed` yapar; forge'da merge edilmiş ama DB'de `pr_open` kalan onarım uzlaştırılır.

Her adım denetime (`repair.*`) ve SSE'ye (`repair.step`) yazılır. Onarım kaydı (öneri, kanıt,
AST, yerel kontrol) `repair.proposed` / `repair.checked` / `repair.pr_opened` denetim olaylarının
özetindedir (append-only, zincirli); `views` oradan okur.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from tp_core.audit import append_audit, audit_on_commit
from tp_core.events.bus import publish_tx
from tp_core.features.codegen import platform as platformlar
from tp_core.features.repair import aria, locators
from tp_core.features.repair.toolchain import RepairToolchain, ToolchainHatasi
from tp_core.integrations.forge import (
    REPAIR_BRANCH_PREFIX,
    REPAIR_LABEL,
    ForgeError,
    ForgeNotFoundError,
)
from tp_core.models import (
    AuditEvent,
    Failure,
    PullRequest,
    Run,
    Script,
    TestResult,
    session_scope,
)
from tp_core.models.ci_feature import RunAria
from tp_core.ports import ForgePort
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue
from tp_core.workflow.service import (
    SYSTEM,
    GateClosed,
    Principal,
    WorkflowError,
    approved_hash_matches,
    record_approval,
    transition,
)

log = logging.getLogger(__name__)

FIX_JOB = "repair.fix"
MERGE_JOB = "repair.merge"
TUR = "locator_fix"
ACIK_DURUMLAR = frozenset({"pending", "verifying", "checking", "pr_open"})
AKTIF_DURUMLAR = frozenset({"pending", "verifying", "checking"})
TEKRAR_DURUMLARI = frozenset({"blocked", "failed"})
ARIA_FALLBACK_ENV = "TP_REPAIR_ARIA_FALLBACK"
SON_YESIL_TETIKLER = ("push", "pr", "nightly", "deploy", "manual", "local_check")
KONTROL_RETRIES = 1  # CI ile aynı (`--retries=1`): tek bir ilgisiz flake onarımı düşürmez
SON_YESIL_YOK_YONERGE = (
    "Kırık koşudan önce yeşil koşu yok: önce main için yeşil bir push CI koşturun (make "
    "demo-reset ya da Kontrol Kulesi), koşu yeşile dönünce kırılmayı yeniden yapın."
)
ARIA_DOSYA_KALIPLARI = ("*aria*.yml", "*aria*.yaml", "*.aria", "error-context.md")
MAX_ARIA_DOSYA = 50


class RepairNotFound(WorkflowError):
    status_code = 404


class RepairRejected(WorkflowError):
    """Onarım bu hata için başlatılamaz (409)."""


class RepairGirdisiHatali(WorkflowError):
    """Merge isteğinin girdisi eksik (422; codegen merge sözleşmesiyle aynı)."""

    status_code = 422


# ---------------------------------------------------------------------- fabrikalar

_factories: dict[str, Callable[..., Any]] = {}


def set_factories(
    *,
    forge: Callable[[], ForgePort] | None = None,
    toolchain: Callable[[], RepairToolchain] | None = None,
    artifacts_root: Callable[[], Path] | None = None,
) -> None:
    """Testler/araçlar için fabrikalar (None → varsayılan: ortam değişkenleri)."""
    _factories.update(forge=forge, toolchain=toolchain, artifacts_root=artifacts_root)


def reset_factories() -> None:
    _factories.clear()


def _forge() -> ForgePort:
    f = _factories.get("forge")
    if f is not None:
        return f()
    from tp_core.integrations.forge import get_forge

    return get_forge()


def _toolchain() -> RepairToolchain:
    f = _factories.get("toolchain")
    if f is not None:
        return f()
    from tp_core.config import get_settings

    s = get_settings()
    return RepairToolchain(s.toolchain_url, token=s.toolchain_token)


def _artifacts_root() -> Path:
    f = _factories.get("artifacts_root")
    if f is not None:
        return Path(f())
    from tp_core.config import get_settings

    return Path(get_settings().artifacts_path)


def e2e_root() -> str:
    from tp_core.features.codegen.service import e2e_root as _kok

    return _kok()


def e2e_app_root() -> str:
    """Forge deposunda Java test projesinin kökü (`e2e-app` ya da `demo-app/e2e-app`)."""
    from tp_core.features.codegen import service as cg

    return cg.e2e_app_root()


def forge_yolu_java(goreli: str, kok: str | None = None) -> str:
    """Java sembol tablosu yolu (Java proje köküne göre `src/test/java/...`) → forge yolu.
    `kok` verilmezse uygulama (Appium) kökü `e2e-app`; web + Java'da `e2e_java_root()`."""
    kok = kok or e2e_app_root()
    return goreli if goreli.startswith(kok + "/") else f"{kok}/{goreli}"


def e2e_java_root() -> str:
    """Forge deposunda web + Java test projesinin kökü (`e2e-java` ya da `demo-app/e2e-java`)."""
    from tp_core.features.codegen import service as cg

    return cg.e2e_java_root()


def onarim_dili(session: Session, f: Failure, oneri: Mapping[str, Any], platform: str) -> str:
    """Onarılan testin üretim dili (011): uygulama → `java`; web: triage önerisi → koşu ortamı
    (`dil` / `lang`) → koşunun script'i (`script.dil`) → `ts`."""
    if platform != "web":
        return "java"
    adaylar: list[Any] = [oneri.get("dil")]
    run = session.get(Run, f.run_id)
    if run is not None:
        adaylar += [(run.ortam or {}).get("dil"), (run.ortam or {}).get("lang")]
        if run.script_id is not None:
            sc = session.get(Script, run.script_id)
            adaylar.append(sc.dil if sc is not None else None)
    for a in adaylar:
        if a in platformlar.TAM_HAT_DILLERI:
            return str(a)
    return platformlar.TS


def onarim_platformu(session: Session, f: Failure, oneri: Mapping[str, Any]) -> str:
    """Onarılan testin platformu: triage önerisi → koşu ortamı → koşunun script'i → `web`."""
    from tp_core.features.codegen.platform import PLATFORMLAR

    adaylar: list[Any] = [oneri.get("platform")]
    run = session.get(Run, f.run_id)
    if run is not None:
        adaylar.append((run.ortam or {}).get("platform"))
        if run.script_id is not None:
            sc = session.get(Script, run.script_id)
            adaylar.append(getattr(sc, "platform", None) if sc is not None else None)
    for a in adaylar:
        if isinstance(a, str) and a in PLATFORMLAR:
            return a
    return "web"


def forge_yolu(e2e_goreli: str) -> str:
    """Sembol tablosu yolu (e2e köküne göre `pages/...`) → forge yolu (`e2e/pages/...`)."""
    kok = e2e_root()
    return e2e_goreli if e2e_goreli.startswith(kok + "/") else f"{kok}/{e2e_goreli}"


def aria_fallback_acik() -> bool:
    """Sözleşme testi yedeği yalnızca açıkça istenirse (`TP_REPAIR_ARIA_FALLBACK=sozlesme`)."""
    return (os.environ.get(ARIA_FALLBACK_ENV) or "kapali").strip().lower() == "sozlesme"


def _olay(session: Session, ad: str, veri: Mapping[str, Any]) -> None:
    publish_tx(session.connection(), ad, veri)


def branch_for(failure_id: uuid.UUID, n: int = 1) -> str:
    return f"{REPAIR_BRANCH_PREFIX}{failure_id}" + (f"-{n}" if n > 1 else "")


# ------------------------------------------------------------------ uygunluk


def saglik_basarisiz(run: Run | None) -> bool:
    """Koşu öncesi sağlık kontrolü başarısız mı? (deterministik `environment`, §8.6 kural 1)."""
    if run is None:
        return False
    saglik = (run.ortam or {}).get("saglik")
    if isinstance(saglik, Mapping) and saglik.get("ok") is False:
        return True
    # `saglik`'sız `error` koşusu da ortam sinyalidir (MIMARI-SOZLESME §2).
    return run.sonuc == "error" and not isinstance(saglik, Mapping)


def failure_ek(session: Session, failure_id: uuid.UUID) -> dict[str, Any]:
    """Triage şeridinin `failure_ek` kaydı (yoksa {}): `oneri`, `kanit`, `oneri_yok_nedeni`."""
    var = session.execute(text("SELECT to_regclass('failure_ek') IS NOT NULL")).scalar()
    if not var:
        return {}
    row = (
        session.execute(
            text(
                "SELECT oneri, kanit, oneri_yok_nedeni, kural FROM failure_ek WHERE failure_id = :f"
            ),
            {"f": failure_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def uygunluk_engeli(session: Session, f: Failure) -> str | None:
    """Onarım başlatılamıyorsa Türkçe neden (None: uygun)."""
    run = session.get(Run, f.run_id)
    if f.sinif == "environment" or saglik_basarisiz(run):
        return (
            "Ortam hatası (sağlık kontrolü başarısız): locator onarımı yapılmaz; önce ortamı "
            "düzeltip koşuyu yineleyin."
        )
    if f.sinif != "test_maintenance" or (f.alt_tur or "") != "locator":
        return (
            f"Bu hata '{f.sinif}{'/' + f.alt_tur if f.alt_tur else ''}' olarak sınıflandı; "
            "locator onarımı yalnızca test_maintenance/locator için yapılır."
        )
    # Constitution XI / §8.6 kural 3: locator önerisinin kapısı deterministik kuraldır. Modelin
    # `test_maintenance/locator` etiketi (karar_kaynagi='llm', öneri yok) onarım başlatmaz.
    if (f.karar_kaynagi or "") != "rule" or f.oneri_turu != "locator_fix":
        return (
            "Kural önerisi yok (locator önerisi deterministik kuraldan gelmedi); insan incelemesi."
        )
    if _failure_ek_var(session) and not _oneri(session, f.id):
        return "Kural önerisi yok (failure_ek.oneri boş); insan incelemesi."
    return None


def _failure_ek_var(session: Session) -> bool:
    return bool(session.execute(text("SELECT to_regclass('failure_ek') IS NOT NULL")).scalar())


def _oneri(session: Session, failure_id: uuid.UUID) -> dict[str, Any]:
    ek = failure_ek(session, failure_id)
    return dict(ek["oneri"]) if isinstance(ek.get("oneri"), Mapping) else {}


def degisiklik_anahtari(session: Session, f: Failure) -> tuple[str, str] | None:
    """Triage önerisinin locator değişikliği: (`locator_key`, `new_testid`)."""
    oneri = _oneri(session, f.id)
    anahtar, yeni = oneri.get("locator_key"), oneri.get("new_testid")
    return (str(anahtar), str(yeni)) if anahtar and yeni else None


def kardes_failure_ids(
    session: Session, f: Failure, *, tum_kosular: bool = False
) -> list[uuid.UUID]:
    """Aynı locator değişikliğini öneren diğer hatalar (ör. `make break` sonrası aynı
    `catalog.addToCart` testId'si yüzünden kırılan 19 test). Tek onarım hepsini kapatır.

    `tum_kosular=True`: önceki/sonraki koşulardaki aynı öneriler de (paylaşılan onarım ve merge
    sonrası "zaten onarıldı" işaretlemesi için)."""
    dk = degisiklik_anahtari(session, f)
    if dk is None:
        return []
    rows = session.execute(
        text(
            "SELECT fl.id FROM failure fl JOIN failure_ek fe ON fe.failure_id = fl.id "
            "WHERE fl.id <> :id AND fl.sinif = 'test_maintenance' "
            "AND (CAST(:tum AS boolean) OR fl.run_id = :run) "
            "AND fe.oneri->>'locator_key' = :k AND fe.oneri->>'new_testid' = :n"
        ),
        {"run": f.run_id, "id": f.id, "k": dk[0], "n": dk[1], "tum": tum_kosular},
    )
    return [r.id for r in rows]


def _kardeslere_yaz(session: Session, f: Failure, durum: str, *, tum_kosular: bool = False) -> int:
    ids = kardes_failure_ids(session, f, tum_kosular=tum_kosular)
    if not ids:
        return 0
    res = session.execute(
        text(
            "UPDATE failure SET oneri_durumu = :d WHERE id = ANY(:ids) "
            "AND oneri_durumu IN ('proposed', 'pr_open', 'none')"
        ),
        {"d": durum, "ids": ids},
    )
    return int(res.rowcount or 0)


def _merge_eskilere_yaz(session: Session, f: Failure, merge_zamani: datetime) -> int:
    """Merge edilen onarımla aynı değişikliği öneren, merge'ten ÖNCE oluşmuş koşulardaki
    (eskimiş) önerileri `merged` yapar; sonraki koşular (yeniden kırılma) etkilenmez."""
    ids = kardes_failure_ids(session, f, tum_kosular=True)
    if not ids:
        return 0
    res = session.execute(
        text(
            "UPDATE failure fl SET oneri_durumu = 'merged' FROM run r "
            "WHERE fl.id = ANY(:ids) AND r.id = fl.run_id AND r.olusturma <= :z "
            "AND fl.oneri_durumu IN ('proposed', 'pr_open', 'none')"
        ),
        {"ids": ids, "z": merge_zamani},
    )
    return int(res.rowcount or 0)


def _acik_onarim(session: Session, failure_id: uuid.UUID, *, lock: bool = False) -> Script | None:
    sorgu = (
        select(Script)
        .where(Script.failure_id == failure_id, Script.tur == TUR)
        .order_by(Script.olusturma.desc())
        .limit(1)
    )
    if lock:
        sorgu = sorgu.with_for_update()
    return session.scalars(sorgu).first()


def merge_zamani(session: Session, sc: Script) -> datetime | None:
    if sc.durum != "merged":
        return None
    z = session.execute(
        select(AuditEvent.zaman)
        .where(AuditEvent.nesne == f"script:{sc.id}", AuditEvent.eylem == "repair.merged")
        .order_by(AuditEvent.id.desc())
        .limit(1)
    ).scalar()
    return z or sc.guncelleme


def paylasilan_onarim(session: Session, f: Failure) -> Script | None:
    """Bu hatanın önerisiyle aynı değişikliği taşıyan başka bir hatanın onarımı: süren/PR'ı açık
    olan ya da bu hatanın koşusundan SONRA merge edilen (o koşunun kırığını kapatan) onarım."""
    ids = kardes_failure_ids(session, f, tum_kosular=True)
    if not ids:
        return None
    adaylar = session.scalars(
        select(Script)
        .where(
            Script.failure_id.in_(ids),
            Script.tur == TUR,
            Script.durum.in_([*ACIK_DURUMLAR, "merged"]),
        )
        .order_by(Script.olusturma.desc())
    ).all()
    for sc in adaylar:
        if sc.durum in ACIK_DURUMLAR:
            return sc
    run = session.get(Run, f.run_id)
    for sc in adaylar:
        z = merge_zamani(session, sc)
        if z is not None and (run is None or run.olusturma <= z):
            return sc
    return None


def _fix_isi(session: Session, sid: uuid.UUID) -> Any:
    """Script'in en son `repair.fix` işi (id, durum, son_hata) ya da None."""
    return session.execute(
        text(
            "SELECT id, durum, son_hata FROM job WHERE tur = :t AND yuk->>'script_id' = :s "
            "ORDER BY olusturma DESC LIMIT 1"
        ),
        {"t": FIX_JOB, "s": str(sid)},
    ).first()


def recover_stuck(session: Session, sc: Script) -> bool:
    """İşi bitmiş (ya da hiç olmayan) ama `pending|verifying|checking`'de kalmış onarımı
    `failed` yapar (worker öldü/zaman aşımı: `reap_stale`/`release_orphans` işi `failed` yapar,
    script'e dokunmaz). Denetime `repair.blocked` (adım `is`) yazılır; yeniden deneme açılır."""
    if sc.durum not in AKTIF_DURUMLAR:
        return False
    is_ = _fix_isi(session, sc.id)
    if is_ is not None and is_.durum in ("queued", "retry", "running"):
        return False
    neden = (
        "onarım işi yarıda kaldı: "
        + (str(is_.son_hata or is_.durum) if is_ is not None else "iş kaydı yok")
    )[:500]
    transition(session, sc, "failed", SYSTEM, sc.durum, sebep=neden[:300])
    audit_on_commit(
        session,
        "system",
        "repair.blocked",
        f"script:{sc.id}",
        {
            "failure_id": str(sc.failure_id) if sc.failure_id else None,
            "engel": {"adim": "is", "sinif": "environment", "neden": neden},
            "ai_uretimi": False,
        },
    )
    return True


def sweep_stuck(session: Session) -> int:
    n = 0
    for sc in session.scalars(
        select(Script)
        .where(Script.tur == TUR, Script.durum.in_(AKTIF_DURUMLAR))
        .with_for_update(skip_locked=True)
    ).all():
        n += recover_stuck(session, sc)
    return n


def _paylasilan_yaniti(f: Failure, sc: Script) -> dict[str, Any]:
    return {
        "job_id": None,
        "script_id": str(sc.id),
        "failure_id": str(sc.failure_id),
        "durum": sc.durum,
        "pr_no": sc.pr_no,
        "paylasilan": True,
        "mesaj": "Aynı locator değişikliği için onarım zaten sürüyor"
        + (f" (PR #{sc.pr_no})." if sc.pr_no else "."),
    }


def request_fix(session: Session, failure_id: uuid.UUID, user: Principal) -> dict[str, Any]:
    """Mühendisin onarım isteği: uygunluk denetimi + `repair` script'i + `repair.fix` işi.

    İdempotent: süren ya da PR'ı açık onarım (bu hatanın ya da aynı değişikliği öneren kardeşin)
    varsa o döner (yeni iş açılmaz). Merge edilmiş onarım için 409. Engellenmiş/başarısız
    onarımın yeniden denemesi AYNI script'i yeniden kuyruğa alır.

    Eşzamanlılık: aynı değişiklik (`locator_key`, `new_testid`) için işlem ömürlü advisory kilit;
    iki kardeş hataya aynı anda gelen istekler iki PR açamaz.
    """
    from tp_core.workflow.jobs import idempotency_lock

    f = session.get(Failure, failure_id, with_for_update=True)
    if f is None:
        raise RepairNotFound("Hata analizi bulunamadı")
    engel = uygunluk_engeli(session, f)
    if engel is not None:
        audit_on_commit(
            session,
            user.kullanici_adi,
            "repair.refused",
            f"failure:{f.id}",
            {"neden": engel, "sinif": f.sinif, "alt_tur": f.alt_tur,
             "karar_kaynagi": f.karar_kaynagi},
        )  # fmt: skip
        session.commit()
        raise RepairRejected(engel)
    dk = degisiklik_anahtari(session, f)
    idempotency_lock(session.connection(), f"repair:{dk[0]}:{dk[1]}" if dk else f"repair:{f.id}")
    mevcut = _acik_onarim(session, f.id, lock=True)
    if mevcut is not None and mevcut.durum in AKTIF_DURUMLAR:
        recover_stuck(session, mevcut)  # iş bitmiş ama script takılı kaldıysa → failed
    if mevcut is not None and mevcut.durum in ACIK_DURUMLAR:
        return {
            "job_id": None,
            "script_id": str(mevcut.id),
            "failure_id": str(f.id),
            "durum": mevcut.durum,
            "pr_no": mevcut.pr_no,
            "mesaj": "Bu hata için onarım zaten sürüyor"
            + (f" (PR #{mevcut.pr_no})." if mevcut.pr_no else "."),
        }
    if mevcut is not None and mevcut.durum == "merged":
        raise RepairRejected(f"Bu hata zaten onarıldı (PR #{mevcut.pr_no} merge edildi).")
    ortak = paylasilan_onarim(session, f)
    if ortak is not None and ortak.durum in AKTIF_DURUMLAR:
        recover_stuck(session, ortak)
    if ortak is not None and ortak.durum in ACIK_DURUMLAR:
        return _paylasilan_yaniti(f, ortak)
    if ortak is not None and ortak.durum == "merged":
        if f.oneri_durumu in ("proposed", "pr_open", "none"):
            f.oneri_durumu = "merged"
        session.commit()
        raise RepairRejected(
            f"Aynı locator değişikliği PR #{ortak.pr_no} ile zaten onarıldı (merge edildi)."
        )
    oneri = _oneri(session, f.id)
    platform = onarim_platformu(session, f, oneri)
    dil = onarim_dili(session, f, oneri, platform)
    if platform == "web" and dil == "java":
        dosya = forge_yolu_java(
            str(oneri.get("dosya") or locators.KIMLIKLER_VARSAYILAN), e2e_java_root()
        )
    elif platform == "web":
        dosya = forge_yolu(str(oneri.get("dosya") or "pages/locators.ts"))
    else:
        dosya = forge_yolu_java(str(oneri.get("dosya") or locators.KIMLIKLER_VARSAYILAN))
    yeniden = mevcut is not None and mevcut.durum in TEKRAR_DURUMLARI
    if yeniden:
        assert mevcut is not None
        sc = mevcut
        if sc.durum == "failed":
            transition(session, sc, "pending", user.kullanici_adi, "failed",
                       sebep="onarım yeniden denendi")  # fmt: skip
        else:  # blocked → verifying (makinede blocked'tan pending'e geçiş yok)
            transition(session, sc, "verifying", user.kullanici_adi, "blocked",
                       sebep="onarım yeniden denendi")  # fmt: skip
        deneme = (
            int(
                session.execute(
                    text("SELECT count(*) FROM job WHERE tur = :t AND yuk->>'script_id' = :s"),
                    {"t": FIX_JOB, "s": str(sc.id)},
                ).scalar()
                or 0
            )
            + 1
        )
        anahtar = f"{FIX_JOB}:{sc.id}:{deneme}"
    else:
        sc = Script(
            id=uuid.uuid4(),
            tur=TUR,
            dosya_yolu=dosya,
            failure_id=f.id,
            uretim_modu=None,  # model çağrısı yok (deterministik)
            platform=platform,
        )
        # 011: merge sonrası `push` koşusu onarılan testin dilinde koşar (`ci.enqueue_ci`).
        sc.dil = dil
        session.add(sc)
        session.flush()
        deneme = 1
        anahtar = f"{FIX_JOB}:{sc.id}"
    job_id = enqueue(
        session.connection(),
        FIX_JOB,
        {"script_id": str(sc.id), "failure_id": str(f.id), "actor": user.kullanici_adi,
         "deneme": deneme},
        idempotency_key=anahtar,
        max_deneme=1,
    )  # fmt: skip
    audit_on_commit(
        session,
        user.kullanici_adi,
        "repair.retry" if yeniden else "repair.requested",
        f"script:{sc.id}",
        {"failure_id": str(f.id), "test": f.test_adi, "job_id": str(job_id), "deneme": deneme},
    )
    _olay(
        session,
        "repair.requested",
        {"script_id": sc.id, "failure_id": f.id, "job_id": job_id, "aktor": user.kullanici_adi,
         "deneme": deneme},
    )  # fmt: skip
    return {
        "job_id": str(job_id),
        "script_id": str(sc.id),
        "failure_id": str(f.id),
        "durum": "queued",
        "pr_no": None,
        "deneme": deneme,
        "mesaj": (
            "Locator onarımı yeniden denendi (aynı onarım kaydı; deterministik)."
            if yeniden
            else "Locator onarımı başlatıldı (deterministik; model çağrısı yok)."
        ),
    }


# ------------------------------------------------------------------- iş: repair.fix


class _Engel(Exception):
    """Onarım insana düştü (PR yok)."""

    def __init__(self, adim: str, neden: str, sinif: str = "insan", **ayrinti: Any) -> None:
        super().__init__(neden)
        self.adim = adim
        self.neden = neden
        self.sinif = sinif
        self.ayrinti = ayrinti


def _adim(engine: Engine, sid: uuid.UUID, fid: uuid.UUID, adim: str, sonuc: str, mesaj: str):
    with engine.begin() as conn:
        publish_tx(
            conn,
            "repair.step",
            {"script_id": sid, "failure_id": fid, "adim": adim, "sonuc": sonuc, "mesaj": mesaj},
        )


def _test_result(session: Session, f: Failure) -> TestResult | None:
    return session.get(TestResult, f.test_result_id) if f.test_result_id else None


def _locator_metni(f: Failure, tr: TestResult | None, kanit: Mapping[str, Any]) -> str:
    parca = [
        str(kanit.get("locator") or ""),
        str(kanit.get("hata_mesaji") or ""),
        (tr.hata_mesaji if tr is not None else "") or "",
        f.hata_imzasi or "",
    ]
    return "\n".join(p for p in parca if p)


def _son_yesil_run(session: Session, f: Failure, oneri: Mapping[str, Any]) -> Run | None:
    rid = oneri.get("son_yesil_run_id")
    if rid:
        try:
            run = session.get(Run, uuid.UUID(str(rid)))
        except ValueError:
            run = None
        if run is not None and run.sonuc == "passed":
            return run
    kirik = session.get(Run, f.run_id)
    sorgu = select(Run).where(Run.sonuc == "passed", Run.tetik.in_(SON_YESIL_TETIKLER))
    if kirik is not None:
        sorgu = sorgu.where(Run.olusturma < kirik.olusturma)
    return session.scalars(sorgu.order_by(Run.olusturma.desc()).limit(1)).first()


def _aria_dosyalari(run: Run, sayfa_ipucu: str | None = None) -> list[Path]:
    """Koşu artefaktlarındaki aria snapshot dosyaları; sayfa ipucunu (ör. `katalog`) adında
    taşıyanlar önce (yeşil koşuda `locators.spec.ts` sayfa başına `<sayfa>.aria.yml` yazar)."""
    dizin = (run.artefaktlar or {}).get("dizin")
    if not isinstance(dizin, str) or not dizin or ".." in dizin or dizin.startswith("/"):
        return []
    kok = (_artifacts_root() / dizin).resolve()
    try:
        kok.relative_to(_artifacts_root().resolve())
    except ValueError:
        return []
    if not kok.is_dir():
        return []
    out: list[Path] = []
    gorulen: set[Path] = set()
    for kalip in ARIA_DOSYA_KALIPLARI:
        for p in kok.rglob(kalip):
            if p.is_file() and not p.is_symlink() and p not in gorulen:
                gorulen.add(p)
                out.append(p)
            if len(out) >= MAX_ARIA_DOSYA:
                break
    if sayfa_ipucu:
        out.sort(key=lambda p: (sayfa_ipucu not in p.name.lower(), str(p)))
    return out


def _aria_metinleri(
    session: Session, run: Run, sayfa_ipucu: str | None = None
) -> list[tuple[str, str, str]]:
    """Son yeşil koşunun aria snapshot'ları: [(dosya adı, depo, metin)].

    Yerel kip: koşu dizinindeki dosyalar (`_aria_dosyalari`; depo `artefakt_dizini`). Koşu dizini
    yoksa (GitHub kipi) core-worker'ın içe aktarımda artefakttan aldığı kopya (`run_aria`, 0016;
    depo `run_aria`). Sayfa ipucunu adında taşıyanlar önce.
    """
    out: list[tuple[str, str, str]] = []
    for p in _aria_dosyalari(run, sayfa_ipucu):
        try:
            out.append((p.name, "artefakt_dizini", _aria_oku(p.read_bytes())))
        except OSError:
            continue
    if out:
        return out
    satirlar = session.execute(
        select(RunAria.ad, RunAria.yol, RunAria.icerik)
        .where(RunAria.run_id == run.id)
        .order_by(RunAria.yol)
        .limit(MAX_ARIA_DOSYA)
    ).all()
    if sayfa_ipucu:
        satirlar = sorted(satirlar, key=lambda r: (sayfa_ipucu not in r.ad.lower(), r.yol))
    return [(r.ad, "run_aria", r.icerik[: aria.MAX_BYTES]) for r in satirlar]


def _aria_oku(veri: bytes) -> str:
    return veri[: aria.MAX_BYTES].decode("utf-8", "replace")


def _ajan_snapshotlari(
    session: Session, loc: locators.LocatorRef, once: datetime | None
) -> list[tuple[str, str]]:
    """İnsan onaylı (merge edilmiş) kod üretimlerinin ajan snapshot'ları: (kaynak, metin)."""
    var = session.execute(text("SELECT to_regclass('script_adim') IS NOT NULL")).scalar()
    if not var:
        return []
    desen = f'%- {loc.rol} "{loc.ad}"%'
    rows = session.execute(
        text(
            "SELECT a.script_id, a.sira, a.ham, a.zaman FROM script_adim a "
            "JOIN script s ON s.id = a.script_id "
            "WHERE s.durum = 'merged' AND s.tur = 'test' AND a.hata = false AND a.ham LIKE :d "
            "AND (CAST(:once AS timestamptz) IS NULL OR a.zaman < CAST(:once AS timestamptz)) "
            "ORDER BY a.zaman DESC LIMIT 5"
        ),
        {"d": desen, "once": once},
    ).all()
    return [(f"script:{r.script_id}#adim-{r.sira}", r.ham or "") for r in rows]


SOZLESME_SPEC = "tests/locators.spec.ts"


def _sozlesme_spec_metni(forge: ForgePort | None, shalar: list[str | None]) -> str | None:
    if forge is None:
        return None
    yol = f"{e2e_root()}/{SOZLESME_SPEC}"
    for sha in shalar:
        if not sha:
            continue
        try:
            return forge.read_file(yol, sha)
        except ForgeError:
            continue
    return None


def _sozlesme_testi(
    session: Session,
    run: Run | None,
    loc: locators.LocatorRef,
    forge: ForgePort | None = None,
    main_sha: str | None = None,
) -> tuple[TestResult | None, str]:
    """Son yeşil koşuda geçen ve BU locator'ın grubunu sınayan `locators.spec.ts` testi.

    Kapsam spec metninden çıkarılır (yeşil koşunun commit'i, yoksa main): ör. `catalog.addToCart`
    için "menü, katalog, sepet ve sipariş sayfaları" testi; "giriş sayfası" testi kanıt değildir.
    Kapsayan test bulunamazsa (None, neden) — kapalı başarısızlık.
    """
    if run is None:
        return None, "son yeşil koşu yok"
    metin = _sozlesme_spec_metni(forge, [run.commit, main_sha])
    if not metin:
        return None, f"{SOZLESME_SPEC} okunamadı; sözleşme testinin kapsamı doğrulanamadı"
    basliklar = locators.sozlesme_basliklari(metin, loc)
    if not basliklar:
        return None, f"{SOZLESME_SPEC}'te '{loc.tam_ad}' grubunu sınayan test yok"
    adaylar = session.scalars(
        select(TestResult)
        .where(
            TestResult.run_id == run.id,
            TestResult.sonuc == "passed",
            TestResult.dosya.like("%locators.spec.ts"),
        )
        .order_by(TestResult.test_adi)
    ).all()
    for tr in adaylar:
        ad = tr.test_adi or ""
        if any(ad == b or ad.endswith(" › " + b) or ad.endswith(" > " + b) for b in basliklar):
            return tr, ""
    return None, (
        f"son yeşil koşuda '{loc.tam_ad}'i sınayan sözleşme testi geçmemiş "
        f"(beklenen: {', '.join(basliklar)[:200]})"
    )


def _sayfa_ipucu(url_path: str | None) -> str | None:
    parca = [p for p in (url_path or "").strip("/").split("/") if p]
    return parca[0].lower() if parca else None


def aria_kaniti(
    session: Session,
    f: Failure,
    oneri: Mapping[str, Any],
    loc: locators.LocatorRef,
    kapsayici_rol: str | None,
    *,
    forge: ForgePort | None = None,
    main_sha: str | None = None,
    url_path: str | None = None,
) -> dict[str, Any]:
    """Son yeşil durumda rol + adın tek elemana karşılık geldiğinin kanıtı (§8.7 doğrulama).

    Dönen sözlük `gecerli` taşır; geçersiz kaynaklar `denenen`'e yazılır (denetim için).
    Son yeşil koşu hiç yoksa `son_yesil_yok=True` (sunucuya yönerge verilir).
    """
    kapsamli = bool(loc.within)
    denenen: list[dict[str, Any]] = []
    kirik = session.get(Run, f.run_id)

    def dene(kaynak: str, metin: str, **ek: Any) -> dict[str, Any] | None:
        sonuc = aria.dogrula(metin, loc.rol, loc.ad, kapsayici_rol=kapsayici_rol, kapsamli=kapsamli)
        kayit = {"kaynak": kaynak, **ek, **sonuc.as_dict()}
        denenen.append(kayit)
        return kayit if sonuc.gecerli else None

    metin = oneri.get("son_yesil_aria")
    if isinstance(metin, str) and metin.strip():
        bulunan = dene("triage_onerisi", metin, run_id=oneri.get("son_yesil_run_id"))
        if bulunan:
            return {"gecerli": True, **bulunan, "denenen": denenen}
    yesil = _son_yesil_run(session, f, oneri)
    aria_dosyasi_vardi = False
    if yesil is not None:
        for ad, depo, metin in _aria_metinleri(session, yesil, _sayfa_ipucu(url_path)):
            aria_dosyasi_vardi = True
            bulunan = dene(
                "son_yesil_kosu", metin, run_id=str(yesil.id), dosya=ad, depo=depo,
                commit=yesil.commit,
            )  # fmt: skip
            if bulunan:
                return {"gecerli": True, **bulunan, "denenen": denenen}
    for kaynak, metin in _ajan_snapshotlari(session, loc, kirik.olusturma if kirik else None):
        bulunan = dene("ajan_snapshot", metin, ref=kaynak)
        if bulunan:
            return {"gecerli": True, **bulunan, "denenen": denenen}
    # Etiketli yedek: yalnızca açıkça istenirse ve son yeşil koşuda HİÇ snapshot yoksa (snapshot
    # vardı ama doğrulamadıysa yedek kullanılmaz: kanıt aleyhte).
    if aria_fallback_acik() and yesil is not None and not aria_dosyasi_vardi:
        tr, neden = _sozlesme_testi(session, yesil, loc, forge, main_sha)
        if tr is not None:
            kayit = {
                "kaynak": "sozlesme_testi",
                "run_id": str(yesil.id),
                "commit": yesil.commit,
                "test": tr.test_adi,
                "gecerli": True,
                "eslesme": None,
                "neden": (
                    f"Son yeşil koşuda ({str(yesil.id)[:8]}, {(yesil.commit or '')[:12]}) "
                    f"'{loc.tam_ad}'i sınayan sözleşme testi geçti ({tr.test_adi}): "
                    f'{loc.rol} "{loc.ad}" '
                    + ("her kapsayıcıda tek elemana" if kapsamli else "tek elemana")
                    + f" ve testId '{loc.test_id}'e karşılık geliyordu (aria snapshot dosyası "
                    "yoktu; etiketli yedek: sözleşme testi kanıtı)."
                ),
            }
            denenen.append(kayit)
            return {**kayit, "denenen": denenen}
        denenen.append({"kaynak": "sozlesme_testi", "gecerli": False, "neden": neden})
    if yesil is None:
        return {
            "gecerli": False,
            "neden": "kırık koşudan önce yeşil koşu yok; son yeşil aria kanıtı bulunamadı.",
            "denenen": denenen,
            "son_yesil_yok": True,
        }
    son = (
        denenen[-1]["neden"]
        if denenen
        else f"son yeşil koşunun ({str(yesil.id)[:8]}) aria snapshot'ı bulunamadı"
    )
    return {"gecerli": False, "neden": son, "denenen": denenen, "run_id": str(yesil.id)}


def _durum(engine: Engine, sid: uuid.UUID, hedef: str, sebep: str, ozet: Mapping[str, Any]):
    with session_scope() as s:
        sc = s.get(Script, sid, with_for_update=True)
        if sc is None or sc.durum == hedef:
            return
        transition(s, sc, hedef, SYSTEM, sc.durum, sebep=sebep, ozet=dict(ozet))


def _engelle(engine: Engine, sid: uuid.UUID, fid: uuid.UUID, e: _Engel, kayit: dict[str, Any]):
    with session_scope() as s:
        sc = s.get(Script, sid, with_for_update=True)
        if sc is not None and sc.durum in ("verifying", "checking"):
            transition(
                s, sc, "blocked", SYSTEM, sc.durum, sebep=e.neden[:300], ozet={"adim": e.adim}
            )
        elif sc is not None and sc.durum == "pending":
            transition(s, sc, "failed", SYSTEM, "pending", sebep=e.neden[:300])
        audit_on_commit(
            s,
            "system",
            "repair.blocked",
            f"script:{sid}",
            {
                **kayit,
                "failure_id": str(fid),
                "engel": {"adim": e.adim, "sinif": e.sinif, "neden": e.neden[:500]},
                "ayrinti": e.ayrinti,
            },
        )
        _olay(
            s,
            "repair.blocked",
            {"script_id": sid, "failure_id": fid, "adim": e.adim, "sinif": e.sinif,
             "neden": e.neden[:300]},
        )  # fmt: skip


def run_fix(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    yuk = ctx.yuk or {}
    sid = uuid.UUID(str(yuk["script_id"]))
    fid = uuid.UUID(str(yuk["failure_id"]))
    actor = str(yuk.get("actor") or "system")
    kayit: dict[str, Any] = {"failure_id": str(fid), "isteyen": actor, "ai_uretimi": False}
    with session_scope() as s:
        sc = s.get(Script, sid, with_for_update=True)
        if sc is None:
            raise PermanentJobError("onarım script'i bulunamadı")
        yeniden_deneme = int(yuk.get("deneme") or 1) > 1
        if sc.durum == "pending":
            transition(s, sc, "verifying", SYSTEM, "pending", sebep="locator onarımı başladı")
        elif not (sc.durum == "verifying" and yeniden_deneme):
            # Yeniden deneme isteği script'i zaten `verifying`'e aldı (blocked → verifying).
            return {"durum": sc.durum, "zaten": True}
        _olay(s, "repair.started", {"script_id": sid, "failure_id": fid})
    try:
        sonuc = _onar(engine, sid, fid, kayit)
    except _Engel as e:
        kayit["engel"] = {"adim": e.adim, "sinif": e.sinif, "neden": e.neden}
        _engelle(engine, sid, fid, e, kayit)
        return {"durum": "blocked", "adim": e.adim, "sinif": e.sinif, "neden": e.neden}
    except Exception as exc:
        e = _Engel("hata", f"Onarım beklenmedik hatayla durdu: {type(exc).__name__}: {exc}"[:500])
        kayit["engel"] = {"adim": e.adim, "sinif": "hata", "neden": e.neden}
        _engelle(engine, sid, fid, e, kayit)
        raise PermanentJobError(e.neden) from exc
    return sonuc


def _onar(engine: Engine, sid: uuid.UUID, fid: uuid.UUID, kayit: dict[str, Any]) -> dict[str, Any]:
    # 1) bağlam + ortam denetimi (XI: deterministik `environment` hiçbir şeyle ezilmez)
    with session_scope() as s:
        f = s.get(Failure, fid)
        if f is None:
            raise _Engel("baglam", "Hata analizi bulunamadı")
        engel = uygunluk_engeli(s, f)
        if engel is not None:
            sinif = "environment" if f.sinif == "environment" else "uygun_degil"
            raise _Engel("baglam", engel, sinif)
        ek = failure_ek(s, fid)
        oneri: dict[str, Any] = dict(ek.get("oneri") or {})
        kanit: dict[str, Any] = dict(ek.get("kanit") or {})
        tr = _test_result(s, f)
        metin = _locator_metni(f, tr, kanit)
        test_adi = f.test_adi
        kirik_run = s.get(Run, f.run_id)
        kayit["kirik_commit"] = kirik_run.commit if kirik_run is not None else None
        platform = onarim_platformu(s, f, oneri)
        dil = onarim_dili(s, f, oneri, platform)
        kirik_dizin = (kirik_run.artefaktlar or {}).get("dizin") if kirik_run is not None else None
        kayit.update(
            test=test_adi,
            run_id=str(f.run_id),
            hata_imzasi=f.hata_imzasi,
            sinyaller=list(f.eslesen_sinyaller or [])[:20],
            triage_onerisi=bool(oneri),
            platform=platform,
            dil=dil,
        )
    web_java = platform == "web" and dil == "java"
    if web_java:
        from tp_core.features.triage.java_web import kirik_kimlik

        eski_tid, kapsam, _belirsiz = kirik_kimlik(metin)
    elif platform != "web":
        from tp_core.features.triage.java import kimlik_zinciri

        eski_tid, kapsam, _belirsiz = kimlik_zinciri(metin)
    else:
        eski_tid, kapsam = locators.kirik_testid(metin)
    eski = str(oneri.get("old_testid") or eski_tid or "")
    kapsam = str(oneri.get("scope_test_id") or kapsam or "") or None
    if not eski:
        raise _Engel("locator", "Kırık locator'ın testId'si hata metninden çıkarılamadı")
    _adim(engine, sid, fid, "locator", "ok", f"Kırık testId: {eski}")

    forge = _forge()
    try:
        main_sha = forge.head_sha("main")
    except ForgeError as exc:
        raise _Engel("forge", f"Forge okunamadı: {exc}", "environment") from exc
    kayit["main_sha"] = main_sha

    if platform != "web" or web_java:
        with _toolchain() as tc:
            rapor, run_uuid, hata, etkilenen, yeni_j = _onar_java(
                engine, tc, sid, fid, kayit, forge, main_sha, oneri, eski, kapsam, platform,
                kirik_dizin,
            )  # fmt: skip
        return _kontrol_sonrasi(engine, forge, sid, fid, kayit, rapor, run_uuid, hata,
                                etkilenen, yeni_j)  # fmt: skip

    with _toolchain() as tc:
        # 2) sembol tablosu → locator anahtarı
        try:
            semboller = tc.symbols(main_sha)
        except ToolchainHatasi as exc:
            raise _Engel("semboller", exc.detay, "environment") from exc
        anahtar = oneri.get("locator_key")
        adaylar = locators.find_locators(semboller, eski, anahtar=str(anahtar) if anahtar else None)
        if not adaylar:
            raise _Engel(
                "semboller",
                f"main'de testId '{eski}' taşıyan sabit locator yok (zaten onarılmış ya da önek "
                "locator olabilir)",
            )
        if len(adaylar) > 1:
            raise _Engel(
                "semboller",
                f"testId '{eski}' birden çok locator'da: "
                + ", ".join(f"{a.dosya}:{a.tam_ad}" for a in adaylar),
            )
        loc = adaylar[0]
        kapsayici_rol, kapsayici_anahtar = locators.kapsayici_rolu(loc)
        dosya = forge_yolu(loc.dosya)
        if not locators.LOCATORS_FILE_RE.match(dosya):
            raise _Engel("semboller", f"locator dosyası pages/**/locators.ts değil: {dosya}")
        kayit["locator"] = {**loc.as_dict(), "dosya": dosya, "kapsayici_rol": kapsayici_rol}
        if loc.within and not (kapsam and kapsam.startswith(loc.within)):
            raise _Engel(
                "kapsam",
                f"'{loc.tam_ad}' kapsamlı locator (within '{loc.within}') ama başarısız adımdaki "
                "kapsayıcı testId'si bulunamadı; çoklu eşleşmede öneri üretilmez",
            )
        url_path = oneri.get("url_path")
        if not url_path:
            try:
                destek = forge.read_file(f"{e2e_root()}/pages/support.ts", main_sha)
            except ForgeError:
                destek = ""
            url_path = locators.url_path_for(loc.dosya, locators.parse_paths(destek))
        if not url_path:
            raise _Engel("yoklama", f"'{loc.dosya}' için sayfa yolu (url_path) bulunamadı")
        _adim(engine, sid, fid, "semboller", "ok", f"{loc.sinif} · {loc.tam_ad} ({loc.rol} "
              f'"{loc.ad}")')  # fmt: skip

        # 3) aday: çalışan uygulamada rol + ad yoklaması
        try:
            probe = tc.locator_probe(main_sha, loc.rol, loc.ad, str(url_path), kapsam)
        except ToolchainHatasi as exc:
            raise _Engel(
                "yoklama", f"Locator yoklaması yapılamadı: {exc.detay}", "environment"
            ) from exc
        kayit["probe"] = {
            k: probe.get(k)
            for k in (
                "matches",
                "test_id",
                "test_ids",
                "scope_test_id",
                "scope_matches",
                "url_path",
                "final_path",
                "olculen",
                "uygulama_sha",
                "sha_eslesmesi",
                "uyari",
                "oneri_uretilebilir",
            )
        }
        kayit["probe"].setdefault("url_path", url_path)
        yeni = probe.get("test_id")
        if probe.get("sha_eslesmesi") == "farkli":
            kirik_c = str(kayit.get("kirik_commit") or "")
            raise _Engel(
                "yoklama",
                "Yoklama sha eşleşmesi 'farkli': çalışan uygulama "
                f"{str(probe.get('uygulama_sha') or '?')[:12]}, yoklanan main {main_sha[:12]}"
                + (
                    f", kırık koşunun commit'i {kirik_c[:12]} (main o koşudan sonra değişti)"
                    if kirik_c and kirik_c != main_sha
                    else ""
                )
                + f"; öneri üretilmez ({probe.get('uyari') or 'sha_eslesmesi=farkli'})",
                "environment",
            )
        if int(probe.get("matches") or 0) != 1 or not isinstance(yeni, str):
            raise _Engel(
                "yoklama",
                f'{loc.rol} "{loc.ad}" çalışan uygulamada {int(probe.get("matches") or 0)} '
                "elemana uydu (tek eleman gerekir); öneri yok",
            )
        if not probe.get("oneri_uretilebilir", True):
            raise _Engel("yoklama", "toolchain yoklaması öneri üretilemez dedi")
        if not locators.TESTID_RE.match(yeni):
            raise _Engel("yoklama", f"Okunan data-testid geçersiz: {yeni[:80]!r}")
        if yeni == eski:
            raise _Engel(
                "yoklama",
                f"Çalışan uygulamada testId hâlâ '{eski}': locator kırılması değil (insana)",
            )
        beklenen_yeni = oneri.get("new_testid")
        if beklenen_yeni and beklenen_yeni != yeni:
            raise _Engel(
                "yoklama",
                f"Triage önerisi ({beklenen_yeni}) ile yeniden yoklama ({yeni}) farklı; insana",
            )
        cakisan = locators.cakisma(semboller, yeni, loc)
        if cakisan:
            raise _Engel("yoklama", f"Aday çakışıyor: {cakisan}")
        kayit.update(eski_test_id=eski, yeni_test_id=yeni, scope_test_id=kapsam)
        _adim(engine, sid, fid, "yoklama", "ok", f"Aday testId: {eski} → {yeni}")

        # 4) son yeşil aria doğrulaması
        with session_scope() as s:
            f = s.get(Failure, fid)
            assert f is not None
            kanit_aria = aria_kaniti(
                s, f, oneri, loc, kapsayici_rol, forge=forge, main_sha=main_sha,
                url_path=str(url_path),
            )  # fmt: skip
        kayit["aria"] = kanit_aria
        if not kanit_aria.get("gecerli"):
            raise _Engel(
                "aria",
                f"Son yeşil aria doğrulaması başarısız: {kanit_aria['neden']}"
                + (f" {SON_YESIL_YOK_YONERGE}" if kanit_aria.get("son_yesil_yok") else ""),
                **({"yonerge": SON_YESIL_YOK_YONERGE} if kanit_aria.get("son_yesil_yok") else {}),
            )
        kayit["aria_kapsayici"] = kapsayici_anahtar
        _adim(engine, sid, fid, "aria", "ok", str(kanit_aria.get("neden"))[:300])
        with engine.begin() as conn:
            append_audit(conn, "system", "repair.proposed", f"script:{sid}", kayit)

        # 5) yama + dal
        try:
            once = forge.read_file(dosya, main_sha)
        except ForgeError as exc:
            raise _Engel("yama", f"{dosya} okunamadı: {exc}") from exc
        try:
            sonra = locators.patch_testid(once, loc.anahtar, eski, yeni)
        except locators.PatchError as exc:
            raise _Engel("yama", f"Yama üretilemedi: {exc}") from exc
        fark = locators.birlesik_fark(dosya, once, sonra)
        dal = _bos_dal(forge, fid)
        mesaj = (
            f"fix(locators): {loc.tam_ad} testId {eski} → {yeni}\n\n"
            f"Locator onarımı (deterministik, AI yok). Hata: {fid}"
        )
        try:
            head = forge.commit_files(dal, {dosya: sonra}, mesaj, base=main_sha)
        except ForgeError as exc:
            raise _Engel("yama", f"Onarım dalı yazılamadı: {exc}", "environment") from exc
        kayit.update(dal=dal, head_sha=head, fark=fark, dosya=dosya)
        with session_scope() as s:
            sc = s.get(Script, sid, with_for_update=True)
            assert sc is not None
            sc.dosya_yolu = dosya
            sc.icerik = sonra
            sc.branch = dal
            sc.head_sha = head
            from tp_core.audit import content_hash

            sc.icerik_hash = content_hash({"dosya_yolu": dosya, "icerik": sonra, "head_sha": head})
            transition(s, sc, "checking", SYSTEM, "verifying", sebep="yama hazır",
                       ozet={"dal": dal, "head_sha": head})  # fmt: skip
        _adim(engine, sid, fid, "yama", "ok", f"{dosya}: yalnızca testId değişti ({dal})")

        # 6) AST koruması (onarım modu)
        try:
            ast = tc.ast_guard(main_sha, head)
        except ToolchainHatasi as exc:
            raise _Engel(
                "ast_guard", f"AST koruması çalışamadı: {exc.detay}", "environment"
            ) from exc
        kayit["ast_guard"] = {
            "ok": bool(ast.get("ok")),
            "mode": ast.get("mode", "repair"),
            "violations": list(ast.get("violations") or [])[:20],
        }
        if not ast.get("ok"):
            raise _Engel(
                "ast_guard",
                "AST koruması (repair) ihlal buldu: "
                + "; ".join(str(v) for v in (ast.get("violations") or [])[:5]),
            )
        _adim(engine, sid, fid, "ast_guard", "ok", "AST koruması (repair): yalnızca testId")

        # 7) yerel kontrol: tam paket (etkilenen tüm testler)
        etkilenen = _etkilenen(forge, main_sha, loc)
        kayit["etkilenen_testler"] = etkilenen
        rapor, run_uuid, hata = _yerel_kontrol(tc, sid, head, main_sha)
    return _kontrol_sonrasi(
        engine, forge, sid, fid, kayit, rapor, run_uuid, hata, etkilenen, str(yeni)
    )


def _kontrol_sonrasi(
    engine: Engine,
    forge: ForgePort,
    sid: uuid.UUID,
    fid: uuid.UUID,
    kayit: dict[str, Any],
    rapor: Mapping[str, Any] | None,
    run_uuid: str | None,
    hata: str | None,
    etkilenen: list[str],
    yeni: str,
) -> dict[str, Any]:
    """Adım 7'nin değerlendirmesi (web ve uygulama ortak) + adım 8 (bot PR)."""
    platform = kayit.get("platform") or "web"
    java = platform != "web" or kayit.get("dil") == "java"
    kayit["yerel_kontrol"] = _kontrol_ozeti(
        rapor,
        run_uuid,
        hata,
        etkilenen,
        (str(kayit.get("eski_test_id") or ""), str(yeni)),
        java=java,
        kok=e2e_java_root() if platform == "web" and java else None,
    )
    if rapor is None:
        raise _Engel("yerel_kontrol", f"Yerel kontrol koşturulamadı: {hata}", "environment")
    saglik = rapor.get("saglik") or (rapor.get("run") or {}).get("saglik")
    if isinstance(saglik, Mapping) and saglik.get("ok") is False:
        raise _Engel(
            "yerel_kontrol",
            "Yerel kontrol öncesi sağlık kontrolü başarısız (ortam); onarım PR'ı açılmadı",
            "environment",
        )
    app = rapor.get("app") if isinstance(rapor.get("app"), Mapping) else {}
    if app.get("ok") is False:
        raise _Engel(
            "yerel_kontrol",
            f"Çalışan uygulama commit ile eşleşmiyor: {app.get('hata') or app.get('uyari') or ''}",
            "environment",
        )
    yk = kayit["yerel_kontrol"]
    if rapor.get("conclusion") != "success":
        kirmizi = yk.get("kirmizi_testler") or []
        # İlgili: hata testId'yi anıyor ya da (hata metni yoksa) spec etkilenen dosyada.
        ilgili = [
            t
            for t in kirmizi
            if t.get("testid_hatasi") or (t.get("testid_hatasi") is None and t.get("etkilenen"))
        ]
        if kirmizi:
            ayrinti = "; ".join(
                f"{t['test']} ({t.get('dosya') or '?'}"
                + ("" if t in ilgili else ", hata testId'yi anmıyor")
                + ")"
                for t in kirmizi[:5]
            )
            neden = f"Yerel kontrol (tam paket) kırmızı: {len(kirmizi)} test — {ayrinti}" + (
                ". Kırmızı testlerin hatası onarılan testId'yi "
                f"({kayit.get('eski_test_id')} / {yeni}) anmıyor (olası ilgisiz flake): "
                "onarımı yeniden deneyin."
                if not ilgili
                else ""
            )
        else:
            neden = "Yerel kontrol (tam paket) kırmızı: " + str(
                rapor.get("summary") or rapor.get("failed_steps") or ""
            )
        raise _Engel(
            "yerel_kontrol",
            neden[:800],
            "insan" if ilgili or not kirmizi else "ilgisiz_kirmizi",
            kirmizi_testler=kirmizi[:20],
        )
    etk_gorulen = yk.get("etkilenen_kosuldu")
    if etkilenen and etk_gorulen is not True:
        eksik = (
            "eksik: " + ", ".join(yk.get("etkilenen_eksik") or [])
            if etk_gorulen is False
            else "raporda dosya bilgisi yok"
        )
        raise _Engel(
            "yerel_kontrol",
            "Yerel kontrol raporu etkilenen testlerin hepsinin koştuğunu göstermiyor "
            f"({eksik}); onarım PR'ı açılmadı",
        )
    with engine.begin() as conn:
        append_audit(conn, "system", "repair.checked", f"script:{sid}", kayit)
    _adim(engine, sid, fid, "yerel_kontrol", "ok", "Tam paket yeşil")

    # 8) bot PR
    return _pr_ac(engine, forge, sid, fid, kayit)


def _sayfa_kaynagi_yeniden(
    kirik_dizin: Any, rel: Any, eski: str, kapsam: str | None, platform: str, semboller: Any
) -> tuple[str | None, str | None]:
    """Kırık koşunun dizinindeki hata anı sayfa kaynağından aday yeniden hesaplanır.

    Dönüş: (aday | None, Türkçe not). Dosya okunamıyorsa (GitHub kipi, koşu dizini temizlenmiş)
    aday None ve not "okunamadı" olur; çağıran triage kaydına (append-only) dayanır.
    """
    from tp_core.features.triage import evidence as ev
    from tp_core.features.triage import java as jv

    kosu = ev.kosu_dizini(_artifacts_root(), kirik_dizin)
    if kosu is None or not isinstance(rel, str) or not rel:
        return None, "koşu dizini/kanıt yolu yok"
    try:
        veri = ev.guvenli_oku(kosu / rel, kosu, jv.MAX_SAYFA_KAYNAGI)
    except ev.KanitHatasi as exc:
        return None, f"okunamadı: {exc}"
    if veri is None:
        return None, "kanıt dosyası yok (koşu dizini temizlenmiş olabilir)"
    try:
        dugumler = jv.kimlik_dugumleri(veri.decode("utf-8", "replace"), platform)
    except jv.SayfaKaynagiHatasi as exc:
        raise _Engel("aria", f"Hata anı sayfa kaynağı ayrıştırılamadı: {exc}") from exc
    sabit, onek = jv.bilinen_kimlikler(semboller)
    aday = jv.aday_kimlik(dugumler, eski, kapsam, sabit, onek)
    if aday.yeni is None:
        raise _Engel("aria", f"Hata anı sayfa kaynağı adayı doğrulamıyor: {aday.neden}")
    return aday.yeni, "yeniden hesaplandı"


def _onar_java(
    engine: Engine,
    tc: RepairToolchain,
    sid: uuid.UUID,
    fid: uuid.UUID,
    kayit: dict[str, Any],
    forge: ForgePort,
    main_sha: str,
    oneri: Mapping[str, Any],
    eski: str,
    kapsam: str | None,
    platform: str,
    kirik_dizin: Any,
) -> tuple[dict[str, Any] | None, str | None, str | None, list[str], str]:
    """Java onarımının 2–7. adımları (yalnızca kimlik değeri değişir).

    Uygulama (009, Appium): aday triage kuralının hata anı sayfa kaynağı önerisidir (Java
    kimliklerinde rol/ad yok; CI'da cihaz ajan aracı olmadan yoklanamaz). Web + Java (011,
    `platform == "web"`): aday hata anı DOM'u önerisidir (web yöntemi), yama ve koruma Java
    yöntemi, kök `e2e-java`. Yerel kontrol (tam paket) asıl doğrulamadır.
    """
    web = platform == "web"
    kok = e2e_java_root() if web else e2e_app_root()
    dil_alani: dict[str, Any] = {"lang": "java"} if web else {}
    # 2) sembol tablosu (Java) → kimlik sabiti
    try:
        semboller = tc.symbols_platform(main_sha, platform, **dil_alani)
    except ToolchainHatasi as exc:
        raise _Engel("semboller", exc.detay, "environment") from exc
    anahtar = oneri.get("locator_key")
    adaylar = locators.find_locators(semboller, eski, anahtar=str(anahtar) if anahtar else None)
    if not adaylar:
        raise _Engel(
            "semboller",
            f"main'de kimlik '{eski}' taşıyan sabit yok (zaten onarılmış ya da önek kimlik "
            "olabilir)",
        )
    if len(adaylar) > 1:
        raise _Engel(
            "semboller",
            f"kimlik '{eski}' birden çok sabitte: "
            + ", ".join(f"{a.dosya}:{a.tam_ad}" for a in adaylar),
        )
    loc = adaylar[0]
    dosya = forge_yolu_java(loc.dosya, kok)
    if not dosya.startswith(kok + "/") or not locators.KIMLIKLER_FILE_RE.match(dosya):
        raise _Engel("semboller", f"kimlik dosyası ekranlar/Kimlikler.java değil: {dosya}")
    if loc.anahtar.endswith("_ONEK"):
        raise _Engel("semboller", f"{loc.tam_ad} önek kimliktir (_ONEK); onarım kapsamı dışı")
    kayit["locator"] = {**loc.as_dict(), "dosya": dosya, "kapsayici_rol": None}
    hat = "web, Playwright for Java" if web else platform
    _adim(engine, sid, fid, "semboller", "ok", f"{loc.sinif} · {loc.tam_ad} ({hat})")

    # 3) aday: triage önerisinin hata anı kanıtı (uygulama: sayfa kaynağı; web + Java: DOM)
    if web and (
        oneri.get("kaynak") != "hata_ani_dom"
        or oneri.get("platform") != "web"
        or oneri.get("dil") != "java"
    ):
        raise _Engel(
            "yoklama",
            "Web + Java (Playwright for Java) onarımı yalnızca hata anı DOM'undan gelen kural "
            f"önerisiyle yapılır (öneri kaynağı {oneri.get('kaynak') or '—'}, platform "
            f"{oneri.get('platform') or '—'}, dil {oneri.get('dil') or '—'}); Java kimliklerinde "
            "rol + ad olmadığından çalışan uygulamada yoklama yapılamaz — insan incelemesi.",
        )
    if not web and (oneri.get("kaynak") != "sayfa_kaynagi" or oneri.get("platform") != platform):
        raise _Engel(
            "yoklama",
            "Uygulama onarımı yalnızca hata anı sayfa kaynağından gelen kural önerisiyle yapılır "
            f"(öneri kaynağı {oneri.get('kaynak') or '—'}, "
            f"platform {oneri.get('platform') or '—'})",
        )
    yeni = oneri.get("new_testid")
    if not isinstance(yeni, str) or not locators.TESTID_RE.match(yeni):
        raise _Engel("yoklama", f"Önerideki yeni kimlik geçersiz: {str(yeni)[:80]!r}")
    if yeni == eski:
        raise _Engel("yoklama", f"Önerideki kimlik hâlâ '{eski}': kimlik kırılması değil")
    cakisan = locators.cakisma(semboller, yeni, loc)
    if cakisan:
        raise _Engel("yoklama", f"Aday çakışıyor: {cakisan}")
    kanit_anahtari = "dom" if web else "sayfa_kaynagi"
    sk = oneri.get(kanit_anahtari) if isinstance(oneri.get(kanit_anahtari), Mapping) else {}
    kayit["probe"] = {
        **{k: v for k, v in dict(oneri.get("probe") or {}).items() if k != "url_path"},
        "url_path": oneri.get("url_path") if web else None,
        kanit_anahtari: sk.get("rel"),
    }
    kayit.update(eski_test_id=eski, yeni_test_id=yeni, scope_test_id=kapsam)
    _adim(engine, sid, fid, "yoklama", "ok", f"Aday kimlik: {eski} → {yeni}")

    # 4) kanıt: hata anı sayfa kaynağı / DOM (mümkünse yeniden okunup aday yeniden hesaplanır)
    kanit_adi = "hata anı DOM'u" if web else "hata anı sayfa kaynağı"
    if sk.get("eski_var") is not False or sk.get("aday_sayisi") != 1:
        raise _Engel("aria", f"Triage önerisinde {kanit_adi} kanıtı eksik")
    if web:
        yeniden, not_ = _dom_yeniden(
            kirik_dizin, sk.get("rel"), sk.get("kaynak"), eski, kapsam, semboller
        )
    else:
        yeniden, not_ = _sayfa_kaynagi_yeniden(
            kirik_dizin, sk.get("rel"), eski, kapsam, platform, semboller
        )
    if yeniden is not None and yeniden != yeni:
        raise _Engel(
            "aria",
            ("Hata anı DOM'undan" if web else "Sayfa kaynağından")
            + f" yeniden hesaplanan aday ({yeniden}) öneriden ({yeni}) farklı",
        )
    kayit["aria"] = {
        "gecerli": True,
        "kaynak": "hata_ani_dom" if web else "hata_ani_sayfa_kaynagi",
        "ref": sk.get("rel"),
        "neden": (
            f"{kanit_adi[0].upper()}{kanit_adi[1:]}nda '{eski}' yok, tek aday '{yeni}'"
            + (f" ('{kapsam}' içinde)" if kapsam else "")
            + f"; kanıt {not_}"
        ),
    }
    _adim(engine, sid, fid, "aria", "ok", str(kayit["aria"]["neden"])[:300])
    with engine.begin() as conn:
        append_audit(conn, "system", "repair.proposed", f"script:{sid}", kayit)

    # 5) yama (yalnızca o sabitin literal'i) + dal
    try:
        once = forge.read_file(dosya, main_sha)
    except ForgeError as exc:
        raise _Engel("yama", f"{dosya} okunamadı: {exc}") from exc
    try:
        sonra = locators.patch_kimlik(once, loc.tam_ad, eski, yeni)
    except locators.PatchError as exc:
        raise _Engel("yama", f"Yama üretilemedi: {exc}") from exc
    fark = locators.birlesik_fark(dosya, once, sonra)
    dal = _bos_dal(forge, fid)
    mesaj = (
        f"fix(kimlikler): {loc.tam_ad} kimlik {eski} → {yeni}\n\n"
        f"Kimlik onarımı ({'web, Playwright for Java' if web else platform}; deterministik, "
        f"AI yok). Hata: {fid}"
    )
    try:
        head = forge.commit_files(dal, {dosya: sonra}, mesaj, base=main_sha)
    except ForgeError as exc:
        raise _Engel("yama", f"Onarım dalı yazılamadı: {exc}", "environment") from exc
    kayit.update(dal=dal, head_sha=head, fark=fark, dosya=dosya)
    with session_scope() as s:
        sc = s.get(Script, sid, with_for_update=True)
        assert sc is not None
        sc.dosya_yolu = dosya
        sc.icerik = sonra
        sc.branch = dal
        sc.head_sha = head
        sc.platform = platform
        from tp_core.audit import content_hash

        sc.icerik_hash = content_hash({"dosya_yolu": dosya, "icerik": sonra, "head_sha": head})
        transition(s, sc, "checking", SYSTEM, "verifying", sebep="yama hazır",
                   ozet={"dal": dal, "head_sha": head})  # fmt: skip
    _adim(engine, sid, fid, "yama", "ok", f"{dosya}: yalnızca kimlik değeri değişti ({dal})")

    # 6) AST koruması (Java repair: yalnızca Kimlikler.java kimlik literal'i)
    try:
        ast = tc.ast_guard(main_sha, head, platform=platform, **dil_alani)
    except ToolchainHatasi as exc:
        raise _Engel("ast_guard", f"AST koruması çalışamadı: {exc.detay}", "environment") from exc
    kayit["ast_guard"] = {
        "ok": bool(ast.get("ok")),
        "mode": ast.get("mode", "repair"),
        "violations": list(ast.get("violations") or [])[:20],
    }
    if not ast.get("ok"):
        raise _Engel(
            "ast_guard",
            "Java koruması (repair) ihlal buldu: "
            + "; ".join(str(v) for v in (ast.get("violations") or [])[:5]),
        )
    _adim(engine, sid, fid, "ast_guard", "ok", "Java koruması (repair): yalnızca kimlik değeri")

    # 7) yerel kontrol: tam paket, cihazda (platform) / tarayıcıda (web + Java)
    etkilenen = _etkilenen_java(forge, main_sha, loc, kok)
    kayit["etkilenen_testler"] = etkilenen
    rapor, run_uuid, hata = _yerel_kontrol(
        tc, sid, head, main_sha, platform, dil="java" if web else None
    )
    return rapor, run_uuid, hata, etkilenen, yeni


def _dom_yeniden(
    kirik_dizin: Any, rel: Any, kaynak: Any, eski: str, kapsam: str | None, semboller: Any
) -> tuple[str | None, str | None]:
    """Web + Java: kırık koşunun dizinindeki hata anı DOM'undan (`sayfa.html`; öneri trace'ten
    geldiyse trace DOM snapshot'ı) aday yeniden hesaplanır. Dönüş: (aday | None, Türkçe not);
    dosya okunamıyorsa aday None ve çağıran triage kaydına (append-only) dayanır."""
    from tp_core.features.triage import evidence as ev
    from tp_core.features.triage import java as jv
    from tp_core.features.triage import java_web as jw

    kosu = ev.kosu_dizini(_artifacts_root(), kirik_dizin)
    if kosu is None or not isinstance(rel, str) or not rel:
        return None, "koşu dizini/kanıt yolu yok"
    if kaynak == "trace.zip":
        trace = ev.trace_oku(kosu, rel)
        if not trace.dom_kullanilabilir:
            return None, f"trace okunamadı: {trace.hata or 'DOM yok'}"
        dugumler = [
            jv.KimlikDugumu(str(e["test_id"]), str(e.get("etiket") or ""), "")
            for e in trace.elemanlar
        ]
    else:
        try:
            veri = ev.guvenli_oku(kosu / rel, kosu, jw.MAX_DOM)
        except ev.KanitHatasi as exc:
            return None, f"okunamadı: {exc}"
        if veri is None:
            return None, "kanıt dosyası yok (koşu dizini temizlenmiş olabilir)"
        try:
            dugumler = jw.dom_dugumleri(veri.decode("utf-8", "replace"))
        except jw.DomHatasi as exc:
            raise _Engel("aria", f"Hata anı DOM'u ayrıştırılamadı: {exc}") from exc
    sabit, onek = jv.bilinen_kimlikler(semboller)
    aday = jv.aday_kimlik(dugumler, eski, kapsam, sabit, onek)
    if aday.yeni is None:
        raise _Engel("aria", f"Hata anı DOM'u adayı doğrulamıyor: {aday.neden}")
    return aday.yeni, "yeniden hesaplandı"


def _etkilenen_java(
    forge: ForgePort, sha: str, loc: locators.LocatorRef, kok: str | None = None
) -> list[str]:
    """Kimlik sabitini kullanan ekranın erişimcisini çağıran Java testleri (forge yolları).
    `kok`: Java proje kökü (uygulama `e2e-app`, web + Java `e2e-java`); `src/test/java` altındaki
    `uretilen/` ve `testler/` testleri taranır, tarayıcısız birim testleri (`birim/`) hariç."""
    kok = kok or e2e_app_root()
    try:
        yollar = [
            y
            for y in forge.list_files(f"{kok}/src/test/java/", sha)
            if (y.endswith("Test.java") or y.endswith("Testi.java")) and "/birim/" not in y
        ]
    except ForgeError:
        return []
    icerik: dict[str, str] = {}
    for y in yollar[:500]:
        try:
            icerik[y] = forge.read_file(y, sha)
        except ForgeError:
            continue
    return locators.etkilenen_java_testler(icerik, loc)


def _bos_dal(forge: ForgePort, fid: uuid.UUID) -> str:
    for n in range(1, 50):
        dal = branch_for(fid, n)
        try:
            forge.head_sha(dal)
        except ForgeNotFoundError:
            return dal
        except ForgeError:
            return dal
    raise _Engel("yama", "Boş onarım dalı adı bulunamadı")


def _etkilenen(forge: ForgePort, sha: str, loc: locators.LocatorRef) -> list[str]:
    kok = e2e_root()
    try:
        yollar = [y for y in forge.list_files(f"{kok}/tests/", sha) if y.endswith(".spec.ts")]
    except ForgeError:
        return []
    icerik: dict[str, str] = {}
    for y in yollar[:500]:
        try:
            icerik[y] = forge.read_file(y, sha)
        except ForgeError:
            continue
    return locators.etkilenen_testler(icerik, loc)


def _yerel_kontrol(
    tc: RepairToolchain,
    sid: uuid.UUID,
    head: str,
    base: str,
    platform: str | None = None,
    *,
    dil: str | None = None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """`/check` (tam paket) + `run` kaydı (tetik `local_check`). `platform` (android | ios |
    windows) → Java yolu (cihazda Appium koşusu); web + `dil="java"` → `{lang: java, platform:
    web}` (Playwright for Java, kayıt `local-ci`); web/None → mevcut Playwright yolu."""
    web_java = (platform or "web") == "web" and dil == "java"
    toolchain_run_id = f"rp-{sid.hex[:8]}-{uuid.uuid4().hex[:6]}"
    baslama = datetime.now(UTC)
    rapor: dict[str, Any] | None = None
    hata: str | None = None
    try:
        if platform and platform != "web":
            rapor = tc.check(
                head, base, toolchain_run_id, retries=KONTROL_RETRIES, platform=platform
            )
        elif web_java:
            rapor = tc.check(
                head, base, toolchain_run_id, retries=KONTROL_RETRIES, platform="web", lang="java"
            )
        else:
            rapor = tc.check(head, base, toolchain_run_id, retries=KONTROL_RETRIES)
    except ToolchainHatasi as exc:
        hata = exc.detay[:500]
    run_uuid: str | None = None
    try:
        with session_scope() as s:
            run = Run(
                id=uuid.uuid4(),
                script_id=sid,
                commit=head,
                kaynak="local",
                tetik="local_check",
                sonuc="running",
                baslama=baslama,
                ortam={
                    "retries": KONTROL_RETRIES,
                    "repeat_each": 1,
                    "break_campaign": False,
                    "isteyen": "system",
                    "ref": None,
                    "onarim": True,
                    "ast_guard_mode": "repair",
                    **({"platform": platform} if platform and platform != "web" else {}),
                    **({"platform": "web", "dil": "java"} if web_java else {}),
                },
                artefaktlar={},
            )
            s.add(run)
            s.flush()
            if rapor is None:
                run.sonuc = "error"
                run.bitis = datetime.now(UTC)
                run.artefaktlar = {"hata": hata}
            else:
                from tp_core.features.ci.service import ingest_check_report

                ingest_check_report(s, run, rapor)
                if isinstance(rapor.get("run"), Mapping):
                    run.artefaktlar = {
                        **(run.artefaktlar or {}),
                        "toolchain_run_id": rapor["run"].get("run_id"),
                    }
            run_uuid = str(run.id)
    except Exception as exc:  # kayıt onarımı durdurmaz; denetime yazılır
        log.warning("onarım yerel kontrolü run tablosuna yazılamadı: %s", exc)
        with session_scope() as s:
            append_audit(
                s.connection(),
                "system",
                "repair.run_record_failed",
                f"script:{sid}",
                {"sha": head, "hata": str(exc)[:300]},
            )
    return rapor, run_uuid, hata


def _kontrol_ozeti(
    rapor: Mapping[str, Any] | None,
    run_uuid: str | None,
    hata: str | None,
    etkilenen: list[str],
    test_idler: tuple[str, ...] = (),
    *,
    java: bool = False,
    kok: str | None = None,
) -> dict[str, Any]:
    if rapor is None:
        return {"sonuc": "error", "hata": hata, "run_id": run_uuid}
    rr = rapor.get("run") if isinstance(rapor.get("run"), Mapping) else {}
    testler = [t for t in (rr.get("tests") or []) if isinstance(t, Mapping)]
    if java:
        # Java raporunda test dosyası paketli sınıf adı (Surefire classname) ya da
        # `src/test/java/…/X.java` olabilir: ikisi de paketli sınıf adına indirgenir.
        dosyalar = sorted({locators.java_sinif_adi(str(t.get("file"))) for t in testler
                           if t.get("file")})  # fmt: skip
        kok = kok or e2e_app_root()
        goreli = [locators.java_sinif_adi(e[len(kok) + 1 :] if e.startswith(kok + "/") else e)
                  for e in etkilenen]  # fmt: skip
    else:
        dosyalar = sorted({str(t.get("file")) for t in testler if t.get("file")})
        kok = e2e_root()
        goreli = [e[len(kok) + 1 :] if e.startswith(kok + "/") else e for e in etkilenen]

    def _uyar(d: str, g: str) -> bool:
        return d.endswith(g) or g.endswith(d)

    def _kisa(t: Mapping[str, Any]) -> dict[str, Any]:
        dosya = str(t.get("file") or "") or None
        if java and dosya:
            dosya = locators.java_sinif_adi(dosya)
        hata_m = t.get("error")
        hata_metni = str(hata_m.get("message") if isinstance(hata_m, Mapping) else hata_m or "")
        return {
            "test": str(t.get("title") or "")[:200],
            "dosya": dosya,
            # Dosya düzeyinde: spec onarılan page object'i/locator grubunu kullanıyor mu.
            "etkilenen": bool(dosya) and any(_uyar(dosya, g) for g in goreli),  # type: ignore[arg-type]
            # Hata metni onarılan testId'yi (eski ya da yeni) anıyor mu (None: hata metni yok).
            "testid_hatasi": (
                any(x in hata_metni for x in test_idler if x) if hata_metni else None
            ),
            "hata": hata_metni[:300] or None,
        }

    eksik = [g for g in goreli if not any(_uyar(d, g) for d in dosyalar)] if dosyalar else []
    return {
        "sonuc": rapor.get("conclusion"),
        "ozet": str(rapor.get("summary") or "")[:300],
        "run_id": run_uuid,
        "toolchain_run_id": rr.get("run_id"),
        "kapsam": "tam_paket",
        "retries": KONTROL_RETRIES,
        "test_sayilari": rapor.get("test_counts"),
        "saglik": rapor.get("saglik"),
        "ast_guard": (rapor.get("ast_guard") or {}).get("ok")
        if isinstance(rapor.get("ast_guard"), Mapping)
        else None,
        # Kırmızı testler adlarıyla (etkilenen mi, ilgisiz mi); yeniden denemede geçen `flaky`.
        "kirmizi_testler": [_kisa(t) for t in testler if t.get("status") == "unexpected"][:50],
        "flaky_testler": [_kisa(t) for t in testler if t.get("status") == "flaky"][:50],
        # Etkilenen testlerin koşuda yer aldığı (rapor dosya bilgisi taşıyorsa) denetlenir;
        # PR açılmadan önce zorunludur (`_onar`).
        "etkilenen_kosuldu": (not eksik) if dosyalar else None,
        "etkilenen_eksik": eksik[:20],
    }


def _pr_ac(
    engine: Engine, forge: ForgePort, sid: uuid.UUID, fid: uuid.UUID, kayit: dict[str, Any]
) -> dict[str, Any]:
    from tp_core.audit import chain_tip
    from tp_core.features.repair.prbody import pr_basligi, pr_govdesi

    with engine.connect() as conn:
        zincir = chain_tip(conn)
    kayit["denetim_zinciri"] = zincir
    baslik = pr_basligi(kayit)
    govde = pr_govdesi(kayit)
    try:
        pr = forge.open_pr(kayit["dal"], baslik, govde, (REPAIR_LABEL,))
    except ForgeError as exc:
        raise _Engel("pr", f"Onarım PR'ı açılamadı: {exc}", "environment") from exc
    if pr.head_sha != kayit["head_sha"]:
        raise _Engel("pr", "PR head'i doğrulanan commit değil; insana")
    with session_scope() as s:
        sc = s.get(Script, sid, with_for_update=True)
        assert sc is not None
        sc.pr_no = pr.number
        satir = s.get(PullRequest, pr.number)
        if satir is None:
            s.add(
                PullRequest(
                    number=pr.number,
                    branch=pr.branch,
                    base=pr.base,
                    baslik=pr.title[:300],
                    govde=govde,
                    head_sha=pr.head_sha,
                    etiketler=list(pr.labels),
                    acan="tp-bot",
                )
            )
        else:
            satir.head_sha = pr.head_sha
            satir.govde = govde
        s.flush()
        transition(s, sc, "pr_open", SYSTEM, "checking", sebep="onarım PR'ı açıldı",
                   ozet={"pr": pr.number})  # fmt: skip
        f = s.get(Failure, fid, with_for_update=True)
        if f is not None:
            f.oneri_turu = "locator_fix"
            f.oneri_durumu = "pr_open"
            _kardeslere_yaz(s, f, "pr_open")
        audit_on_commit(
            s,
            "tp-bot",
            "repair.pr_opened",
            f"script:{sid}",
            {**kayit, "pr": pr.number, "baslik": baslik},
        )
        _olay(
            s,
            "repair.pr_opened",
            {"script_id": sid, "failure_id": fid, "pr_number": pr.number, "branch": pr.branch,
             "head_sha": pr.head_sha, "eski": kayit["eski_test_id"],
             "yeni": kayit["yeni_test_id"]},
        )  # fmt: skip
        _olay(
            s,
            "pr.opened",
            {"script_id": sid, "failure_id": fid, "pr_number": pr.number, "url": pr.url,
             "branch": pr.branch, "head_sha": pr.head_sha, "tur": TUR, "guncellendi": False},
        )  # fmt: skip
    return {
        "durum": "pr_open",
        "pr": pr.number,
        "dal": pr.branch,
        "head_sha": pr.head_sha,
        "eski": kayit["eski_test_id"],
        "yeni": kayit["yeni_test_id"],
    }


# --------------------------------------------------------------------- merge (insan)


def repair_script_for_pr(session: Session, number: int, *, lock: bool = False) -> Script | None:
    """PR bir locator onarımına mı ait? (codegen `/prs/{n}/merge` yönlendirmesi için)."""
    sorgu = (
        select(Script)
        .where(Script.pr_no == number, Script.tur == TUR)
        .order_by(Script.olusturma.desc())
        .limit(1)
    )
    if lock:
        sorgu = sorgu.with_for_update()
    return session.scalars(sorgu).first()


def _merge_isi(session: Session, sid: uuid.UUID, head: str) -> tuple[uuid.UUID, str] | None:
    row = session.execute(
        text(
            "SELECT id, durum FROM job WHERE tur = :t AND yuk->>'script_id' = :s "
            "AND yuk->>'head_sha' = :h AND durum IN ('queued', 'retry', 'running', 'done') "
            "ORDER BY olusturma DESC LIMIT 1"
        ),
        {"t": MERGE_JOB, "s": str(sid), "h": head},
    ).first()
    return (row.id, row.durum) if row else None


def request_merge(
    session: Session,
    number: int,
    user: Principal,
    icerik_hash: str | None,
    head_sha: str | None,
) -> uuid.UUID:
    """İnsan merge kararı (görülen içerik hash'i + head) → `repair.merge` işi (Constitution I).

    Bot merge etmez; forge merge'ü onaylayan mühendis adına, onaylanan head'e bağlı yapılır.
    """
    sc = repair_script_for_pr(session, number, lock=True)
    if sc is None:
        raise RepairNotFound(f"PR #{number} bir locator onarımı değil")
    if not head_sha:
        raise RepairGirdisiHatali(
            "head_sha zorunlu: incelediğiniz PR head commit'ini gönderin (sayfayı yenileyin)"
        )
    mevcut = _merge_isi(session, sc.id, head_sha)
    if sc.durum == "merged":
        # İdempotent yanıt yalnızca AYNI kararın tekrarına: head ve görülen içerik hash'i
        # onaylananla eşleşmeli (aksi halde 409; bir hash'le "onaylanmış gibi" yanıt verilmez).
        if sc.head_sha == head_sha and mevcut is not None and icerik_hash == sc.icerik_hash:
            return mevcut[0]
        if sc.head_sha == head_sha and mevcut is not None:
            raise GateClosed(
                f"PR #{number} zaten merge edildi; gönderilen içerik hash'i onaylananla eşleşmiyor"
            )
        raise WorkflowError(f"PR #{number} zaten merge edildi")
    if sc.durum != "pr_open":
        raise WorkflowError(f"PR #{number} merge edilebilir durumda değil (onarım: {sc.durum})")
    if head_sha != sc.head_sha:
        raise WorkflowError("PR head commit'i incelenenden farklı; yenileyip yeniden inceleyin")
    if mevcut is not None and mevcut[1] != "done":
        return mevcut[0]
    review = record_approval(session, sc, user, "merge", beklenen_hash=icerik_hash)
    session.flush()
    return enqueue(
        session.connection(),
        MERGE_JOB,
        {
            "script_id": str(sc.id),
            "pr_number": number,
            "actor": user.kullanici_adi,
            "head_sha": head_sha,
            "review_id": str(review.id),
        },
        idempotency_key=f"{MERGE_JOB}:{sc.id}:{head_sha}:{review.id}",
        max_deneme=1,
    )


def run_merge(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    from tp_core.integrations.forge import ForgeProtectionError

    yuk = ctx.yuk or {}
    sid = uuid.UUID(str(yuk["script_id"]))
    number = int(yuk["pr_number"])
    actor = str(yuk["actor"])
    head = str(yuk["head_sha"])
    with session_scope() as s:
        sc = s.get(Script, sid, with_for_update=True)
        if sc is None:
            raise PermanentJobError("onarım script'i bulunamadı")
        if sc.durum == "merged" and sc.head_sha == head:
            satir = s.get(PullRequest, number)
            return {"durum": "merged", "pr": number, "zaten": True,
                    "merge_sha": satir.merge_sha if satir else None}  # fmt: skip
        if sc.durum != "pr_open" or sc.head_sha != head or sc.pr_no != number:
            raise PermanentJobError("PR/onarım durumu merge kararından sonra değişti")
        if not approved_hash_matches(s, sc, frozenset({"merge"})):
            raise PermanentJobError("güncel içerikle eşleşen insan merge onayı yok")
    forge = _forge()
    zaten = _forge_merge_sha(forge, number, head)
    try:
        merge_sha = zaten or forge.merge_pr(number, actor, expected_head_sha=head)
    except ForgeError as exc:
        geride = isinstance(exc, ForgeProtectionError) and (
            "güncel değil" in str(exc) or "update_branch" in str(exc)
        )
        with engine.begin() as conn:
            append_audit(
                conn,
                actor,
                "repair.merge_refused",
                f"script:{sid}",
                {"pr": number, "head_sha": head, "neden": str(exc)[:500],
                 "review_id": yuk.get("review_id"), "dal_geride": geride},
            )  # fmt: skip
        if geride:
            raise PermanentJobError(
                "Merge yapılmadı: onarım dalı main'in gerisinde (başka bir PR merge edildi). "
                "Onarımı yeniden başlatın (POST /failures/{id}/fix): yama güncel main'e "
                "yeniden uygulanır ve yerel kontrol yeniden koşar."
            ) from exc
        raise PermanentJobError(f"Merge reddedildi: {exc}") from exc
    ci_run = _merge_kaydet(sid, number, head, merge_sha, actor, uzlastirma=zaten is not None)
    return {"durum": "merged", "pr": number, "merge_sha": merge_sha,
            "ci_run_id": str(ci_run) if ci_run else None}  # fmt: skip


def _forge_merge_sha(forge: ForgePort, number: int, head: str) -> str | None:
    """Forge'da PR zaten (bu head'le) merge edildiyse merge commit'i (çökme sonrası uzlaştırma:
    forge merge etti, DB işlemi commit edilmeden worker düştü). Değilse None."""
    try:
        pr = forge.get_pr(number)
    except ForgeError:
        return None
    if pr.state != "merged" or pr.head_sha != head:
        return None
    kayit_al = getattr(forge, "get_pr_record", None)
    if callable(kayit_al):
        try:
            sha = (kayit_al(number) or {}).get("merged_sha")
        except ForgeError:
            sha = None
        if isinstance(sha, str) and sha:
            return sha
    try:
        return forge.head_sha(pr.base)
    except ForgeError:
        return None


def _merge_kaydet(
    sid: uuid.UUID, number: int, head: str, merge_sha: str, actor: str, *, uzlastirma: bool
) -> uuid.UUID | None:
    with session_scope() as s:
        sc = s.get(Script, sid, with_for_update=True)
        assert sc is not None
        if sc.durum == "merged":  # eşzamanlı uzlaştırma/merge zaten kaydetti
            return None
        fid = sc.failure_id
        sc.insan_review_sonucu = "kabul"
        transition(s, sc, "merged", actor, "pr_open",
                   sebep="insan onaylı onarım merge'ü"
                   + (" (forge'da merge edilmişti; uzlaştırıldı)" if uzlastirma else ""),
                   ozet={"pr": number})  # fmt: skip
        satir = s.get(PullRequest, number)
        if satir is not None:
            satir.durum = "merged"
            satir.merge_sha = merge_sha
            satir.merge_eden = actor
        eskiyen = 0
        if fid is not None:
            f = s.get(Failure, fid, with_for_update=True)
            if f is not None:
                f.oneri_durumu = "merged"
                _kardeslere_yaz(s, f, "merged")
                # Önceki koşulardaki aynı değişiklik önerileri de artık eskidir (onarıldı).
                eskiyen = _merge_eskilere_yaz(s, f, datetime.now(UTC))
        audit_on_commit(
            s,
            actor,
            "repair.merged",
            f"script:{sid}",
            {"pr": number, "head_sha": head, "merge_sha": merge_sha,
             "failure_id": str(fid) if fid else None, "uzlastirma": uzlastirma,
             "eskiyen_oneri": eskiyen},
        )  # fmt: skip
        _olay(s, "pr.merged", {"script_id": sid, "pr_number": number, "merge_sha": merge_sha,
                               "aktor": actor, "tur": TUR})  # fmt: skip
        _olay(s, "repair.merged", {"script_id": sid, "failure_id": fid, "pr_number": number,
                                   "merge_sha": merge_sha, "aktor": actor})  # fmt: skip
        from tp_core.features.ci import enqueue_ci

        try:
            ci_run = enqueue_ci(s, merge_sha, "push", None, isteyen=actor, script_id=sid)
        except Exception as exc:  # merge yapıldı; CI hatası denetime yazılır
            ci_run = None
            audit_on_commit(s, actor, "repair.ci_failed", f"script:{sid}", {"hata": str(exc)[:300]})
    return ci_run


def reconcile_merged(forge: ForgePort | None = None) -> int:
    """`pr_open` kalmış onarımlardan forge'da (onaylanan head'le) merge edilmiş olanları
    `merged` yapar ve push CI'ını kuyruğa alır (worker açılışı; çökme sonrası uzlaştırma).

    Yalnızca güncel içerikle eşleşen insan merge onayı olanlar uzlaştırılır (Constitution I)."""
    with session_scope() as s:
        adaylar = [
            (sc.id, sc.pr_no, sc.head_sha)
            for sc in s.scalars(
                select(Script).where(
                    Script.tur == TUR, Script.durum == "pr_open", Script.pr_no.is_not(None)
                )
            ).all()
            if approved_hash_matches(s, sc, frozenset({"merge"}))
        ]
    if not adaylar:
        return 0
    forge = forge or _forge()
    n = 0
    for sid, number, head in adaylar:
        if number is None or not head:
            continue
        merge_sha = _forge_merge_sha(forge, number, head)
        if merge_sha is None:
            continue
        aktor = _son_merge_onaylayan(sid) or "system"
        _merge_kaydet(sid, number, head, merge_sha, aktor, uzlastirma=True)
        n += 1
    return n


def _son_merge_onaylayan(sid: uuid.UUID) -> str | None:
    with session_scope() as s:
        return s.execute(
            text(
                "SELECT yuk->>'actor' FROM job WHERE tur = :t AND yuk->>'script_id' = :s "
                "ORDER BY olusturma DESC LIMIT 1"
            ),
            {"t": MERGE_JOB, "s": str(sid)},
        ).scalar()
