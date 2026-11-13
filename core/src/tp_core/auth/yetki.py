"""Rol ve izin kataloğu — tek kaynak (specs/012-rol-yetki/ANALIZ.md §4).

Her API ucu bir izin anahtarı ister: `user: Annotated[Principal, Depends(izin("case.approve"))]`.
Katalogda olmayan izin hiçbir role verilmez (varsayılan ret). Reddedilen istek 403
(`kod: "yetki_yok"`) döner ve `authz.denied` olarak denetim kaydına ayrı bir işlemde yazılır
(isteğin kendi işlemi geri alınsa da kayıt kalır).

Görevler ayrılığı role göredir (K2): aynı kişinin farklı rol hesapları farklı aktördür.
UI'da düğme gizlemek kontrol değildir; kontrol buradadır.
"""

from __future__ import annotations

import logging
import threading
import time
import unicodedata
from collections.abc import Callable
from typing import Final

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tp_core.api.errors import KodluHata
from tp_core.audit.chain import append_audit
from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.workflow.service import Principal

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ roller (ANALIZ §3)
ADMIN: Final = "admin"
AUDITOR: Final = "auditor"
ANALYST: Final = "analyst"
PO: Final = "po"
TESTER: Final = "tester"
ENGINEER: Final = "engineer"
DEVELOPER: Final = "developer"
VIEWER: Final = "viewer"

ROLLER: Final = frozenset({ADMIN, AUDITOR, ANALYST, PO, TESTER, ENGINEER, DEVELOPER, VIEWER})

ROL_ETIKETLERI: Final[dict[str, str]] = {
    ADMIN: "Sistem Yöneticisi",
    AUDITOR: "Denetçi",
    ANALYST: "Analist",
    PO: "PO",
    TESTER: "Testçi",
    ENGINEER: "Automation Engineer",
    DEVELOPER: "Developer",
    VIEWER: "Görüntüleyici",
}

# Kaldırılan rol → yerine geçen (AI Probe'daki canlı rol kayıtları güncellenene kadar).
ESKI_ROLLER: Final[dict[str, str]] = {"presenter": ADMIN}

_HEPSI = ROLLER
_IS_ROLLERI = frozenset({ADMIN, ANALYST, PO, TESTER, ENGINEER, DEVELOPER})


def _r(*roller: str) -> frozenset[str]:
    bilinmeyen = set(roller) - ROLLER
    if bilinmeyen:
        raise ValueError(f"bilinmeyen rol: {sorted(bilinmeyen)}")
    return frozenset(roller)


# ------------------------------------------------------------------ izinler (ANALIZ §4.1, §4.2)
IZINLER: Final[dict[str, frozenset[str]]] = {
    # aksiyonlar
    "requirement.import": _r(ANALYST),
    "requirement.review": _r(ANALYST),
    # Serbest metin gereksiniminde Jira kaydı yok: PO teyidi portaldan verilir (K6 istisnası).
    "requirement.po_approve_free_text": _r(PO),
    "requirement.po_reject_free_text": _r(PO),
    "baseline.manage": _r(PO),
    "case.generate": _r(TESTER),
    "case.decide": _r(TESTER),
    "case.approve": _r(ANALYST),
    "case.publish": _r(TESTER),
    "token.issue": _r(TESTER),
    "code.generate": _r(ENGINEER),
    "code.break_verify": _r(ENGINEER),
    "code.review": _r(ENGINEER),
    "code.merge": _r(ENGINEER),
    "code.repair": _r(ENGINEER),
    "run.trigger_scheduled": _r(ENGINEER),
    "run.trigger_manual": _r(ENGINEER, DEVELOPER),
    "bug.decide": _r(TESTER),
    "demo.manage": _r(ADMIN, ENGINEER),
    "audit.verify": _r(ADMIN, AUDITOR),
    # 013 sprint otomasyonu: otomasyon ayarları ve test verisi kataloğu (specs/013 Y3, K11).
    # Katalogu case'i düzelten Testçi (012) de düzenler: düzeltmedeki `{veri:…}` atfı katalogda
    # olmalı. Jira tetiğinin durum adı yalnız Otomasyon mühendisinin (K14).
    "automation.manage": _r(ANALYST, ENGINEER),
    "automation.jira_status": _r(ENGINEER),
    "testdata.manage": _r(ANALYST, TESTER, ENGINEER),
    # 012 test kalite doğrulama (specs/012-test-kalite-dogrulama/ANALIZ.md §13.3 rol eşlemesi).
    # Karar tablosu / metamorfik ilişki: Analist yazar ve PO onayına gönderir, PO portalda onaylar
    # (paketin kapsamadığı özellik, K7: sahibi PO). Kontrolü yeniden isteme case'i kabul eden
    # Testçi ve son onayı veren Analist'te. Ekilmiş hata koşusu: eski `engineer` + `presenter`
    # (→ `admin`). İlişkiden ek case türetme case üretimidir (`case.generate`, Testçi).
    "decision_table.edit": _r(ANALYST),
    "decision_table.approve": _r(PO),
    "case.oracle_check": _r(ANALYST, TESTER),
    "fault_run.manage": _r(ADMIN, ENGINEER),
    # okuma
    "dashboard.read": _HEPSI,
    "requirement.read": _IS_ROLLERI,
    "case.read": _IS_ROLLERI,  # developer: yalnız approved/published, geçmiş ve chat yok
    "code.read": _r(ADMIN, ANALYST, TESTER, ENGINEER),
    "run.read": _HEPSI,
    "run.artifacts": _IS_ROLLERI,
    "failure.read": _IS_ROLLERI,
    "bug.read": _IS_ROLLERI,  # developer: yalnız açılmış / bağlanmış bug
    "audit.read_all": _r(ADMIN, AUDITOR),
    "audit.read_own": _r(ANALYST, PO, TESTER, ENGINEER, DEVELOPER),
    "events.read": _IS_ROLLERI,
    "assistant.use": _HEPSI,
    "token.read": _HEPSI,
    "publish.preview": _r(ADMIN, ANALYST, PO, TESTER, ENGINEER),
    # Sayfa izinleri (çekirdek ucu yok; portal menü/rota koruması için).
    "claude_code.read": _r(ADMIN, ANALYST, TESTER, ENGINEER),
    "demo.read": _r(ADMIN, ANALYST, PO, TESTER, ENGINEER),
    # 012 test kalite doğrulama: tablolar gereksinim düzeyi tanımdır (developer görür); case'in
    # kontrol sonucu ve istisna gerekçesi karar geçmişidir (developer, auditor, viewer görmez).
    # Hata koşuları koşu özetidir (`run.read`).
    "decision_table.read": _IS_ROLLERI,
    "case.oracle_read": _r(ADMIN, ANALYST, PO, TESTER, ENGINEER),
}

# Durum makinesi kapılarında karar verebilecek roller (derinlemesine savunma; workflow/states.py).
KARAR_IZNI: Final[dict[str, str]] = {
    # `requirement` yok: PO teyidi Jira kanalından (kullanıcısız) ya da serbest metinde portal
    # ucundan (`requirement.po_approve_free_text`) gelir; onay rolü {po} durum makinesinde kalır.
    "consistency_finding": "requirement.review",
    "test_case": "case.decide",  # son onay: case.approve (S2)
    "bug_draft": "bug.decide",
    "script": "code.merge",
    "karar_tablosu": "decision_table.approve",
    "metamorfik_iliski": "decision_table.approve",
}


def normalize_rol(rol: str) -> str:
    return ESKI_ROLLER.get(rol, rol)


def izinli(rol: str | None, izin_adi: str) -> bool:
    """Rol bu izne sahip mi? Katalogda olmayan izin her rol için False (varsayılan ret)."""
    if not rol:
        return False
    return normalize_rol(rol) in IZINLER.get(izin_adi, frozenset())


def rol_izinleri(rol: str | None) -> list[str]:
    """Rolün sahip olduğu izinler (sıralı); `GET /auth/me` → `izinler`."""
    return sorted(k for k in IZINLER if izinli(rol, k))


def roller_icin(izin_adi: str) -> frozenset[str]:
    if izin_adi not in IZINLER:
        raise KeyError(f"katalogda olmayan izin: {izin_adi}")
    return IZINLER[izin_adi]


# ------------------------------------------------------------------ red ve denetim
# Red seli havuzu kilitlemesin: aynı (kullanıcı, rol, izin, neden, nesne) 60 sn içinde bir kez
# yazılır; eşzamanlı ayrı bağlantı sayısı sınırlıdır (dolu ise kayıt atlanır, log'a düşer).
RED_TEKRAR_S: Final = 60.0
RED_ESZAMANLI: Final = 2
_RED_ONBELLEK_UST: Final = 2048
NESNE_UST: Final = 200
_son_redler: dict[tuple[str, ...], float] = {}
_red_kilidi = threading.Lock()
_red_yazici = threading.BoundedSemaphore(RED_ESZAMANLI)


def red_onbellegini_temizle() -> None:
    """Tekrar süzgecini boşaltır (testler)."""
    with _red_kilidi:
        _son_redler.clear()


def _temiz_nesne(yol: str) -> str | None:
    """Denetim `nesne` alanı: kontrol karakterleri atılır, `NESNE_UST` karaktere kırpılır."""
    temiz = "".join(c for c in (yol or "") if unicodedata.category(c)[0] != "C")
    return temiz[:NESNE_UST] or None


def _tekrar_mi(anahtar: tuple[str, ...], simdi: float) -> bool:
    with _red_kilidi:
        once = _son_redler.get(anahtar)
        if once is not None and simdi - once < RED_TEKRAR_S:
            return True
        if len(_son_redler) >= _RED_ONBELLEK_UST:
            esik = simdi - RED_TEKRAR_S
            for k in [k for k, t in _son_redler.items() if t < esik]:
                del _son_redler[k]
            if len(_son_redler) >= _RED_ONBELLEK_UST:
                _son_redler.clear()
        _son_redler[anahtar] = simdi
        return False


def denetle_red(
    session: Session | Engine,
    p: Principal,
    izin_adi: str,
    neden: str,
    yol: str = "",
    *,
    karar: str | None = None,
) -> None:
    """`authz.denied` kaydını isteğin işleminden bağımsız yazar; hata yanıtı engellemez.

    Aynı red `RED_TEKRAR_S` içinde tekrar yazılmaz; `RED_ESZAMANLI` yazım sürüyorsa beklenmez,
    kayıt atlanır (red yanıtı her durumda verilir).
    """
    nesne = _temiz_nesne(yol)
    aktor = p.kullanici_adi or "bilinmeyen"
    anahtar = (aktor, str(p.rol), izin_adi, neden, nesne or "", karar or "")
    if _tekrar_mi(anahtar, time.monotonic()):
        return
    if not _red_yazici.acquire(blocking=False):
        log.warning("authz.denied yazımı atlandı (eşzamanlı sınır): %s %s", aktor, izin_adi)
        with _red_kilidi:
            _son_redler.pop(anahtar, None)
        return
    try:
        if isinstance(session, Engine):
            engine = session
        else:
            bind = session.get_bind()
            engine = bind if isinstance(bind, Engine) else bind.engine
        with engine.begin() as conn:
            # Ayrı bağlantı: isteğin kendi işlemi denetim kilidini tutuyorsa sonsuz beklemesin.
            conn.execute(text("SET LOCAL lock_timeout = '1s'"))
            append_audit(
                conn,
                aktor,
                "authz.denied",
                nesne,
                {"izin": izin_adi, "rol": p.rol, "neden": neden, "kanal": p.kanal}
                | ({"karar": karar} if karar else {}),
            )
    except Exception:  # pragma: no cover - denetim yazılamazsa red yine verilir
        log.exception("authz.denied denetim kaydı yazılamadı")
    finally:
        _red_yazici.release()


def reddet(
    session: Session,
    p: Principal,
    izin_adi: str,
    neden: str = "rol",
    yol: str = "",
    *,
    karar: str | None = None,
) -> KodluHata:
    """Kaydı yazar ve fırlatılacak 403'ü döner: `raise reddet(...)`."""
    denetle_red(session, p, izin_adi, neden, yol, karar=karar)
    return KodluHata(403, "yetki_yok", "Bu işlem için yetkiniz yok")


def izin(izin_adi: str) -> Callable[..., Principal]:
    """FastAPI bağımlılığı: oturumdaki rol `izin_adi`'na sahip değilse 403 + `authz.denied`."""
    roller_icin(izin_adi)  # tanımsız izin modül yüklenirken yakalanır

    def kontrol(request: Request, session: DbSession, user: CurrentUser) -> Principal:
        if not izinli(user.rol, izin_adi):
            raise reddet(session, user, izin_adi, "rol", request.url.path)
        return user

    kontrol.__name__ = f"izin_{izin_adi.replace('.', '_')}"
    kontrol.izin_adi = izin_adi  # type: ignore[attr-defined]  # katalog testi okur
    return kontrol


def izinlerden_biri(*izin_adlari: str) -> Callable[..., Principal]:
    """FastAPI bağımlılığı: rol verilen izinlerden en az birine sahip değilse 403 + `authz.denied`.

    İzni gövdeye göre değişen uçlar içindir (ör. `POST /ci/trigger`: `tetik`e göre
    `run.trigger_scheduled` ya da `run.trigger_manual`); uç kesin izni ayrıca `reddet` ile denetler.
    """
    if not izin_adlari:
        raise ValueError("en az bir izin verilmeli")
    for ad in izin_adlari:
        roller_icin(ad)
    birlesik = "|".join(izin_adlari)

    def kontrol(request: Request, session: DbSession, user: CurrentUser) -> Principal:
        if not any(izinli(user.rol, ad) for ad in izin_adlari):
            raise reddet(session, user, birlesik, "rol", request.url.path)
        return user

    kontrol.__name__ = "izin_" + "_veya_".join(ad.replace(".", "_") for ad in izin_adlari)
    kontrol.izin_adlari = izin_adlari  # type: ignore[attr-defined]  # katalog testi okur
    return kontrol
