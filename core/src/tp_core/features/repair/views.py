"""Onarım görünümleri: portal `LocatorOnarimi` bloğu ve PR yanıtı.

Triage şeridinin `GET /failures/{id}` yanıtı `oneri` alanını `oneri_blogu(session, failure_id)`
ile doldurabilir (onarım başlamadıysa None: triage kendi önerisini gösterir). Kayıt denetim
olaylarındadır (`repair.proposed` / `repair.checked` / `repair.pr_opened` / `repair.blocked` /
`repair.retry`).

- Kardeş hata (aynı `locator_key` + `new_testid`; aynı ya da önceki koşu) kendi onarımı yoksa ya da
  kendi denemesi engellendiyse PAYLAŞILAN onarımın kaydını görür (PR, AST, yerel kontrol, yama) ve
  `paylasilan_failure_id` ile onarımı taşıyan hataya bağlanır.
- Engellenen deneme triage önerisini silmez: eski/yeni testId, anahtar, rol, ad öneriden doldurulur;
  `engellendi=True` ve `engel` ayrıca döner.
- `yama`: onarımın birleşik farkı (unified diff; yalnızca testId satırı).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.features.repair import service as _svc
from tp_core.features.repair.service import TUR, repair_script_for_pr
from tp_core.models import AuditEvent, Failure, PullRequest, Script

KAYIT_EYLEMLERI = (
    "repair.pr_opened",
    "repair.checked",
    "repair.proposed",
    "repair.blocked",
    "repair.retry",
)
DURUM_ESLEME = {
    "pending": "checking",
    "verifying": "checking",
    "checking": "checking",
    "blocked": "failed",
    "failed": "failed",
    "pr_open": "pr_open",
    "merged": "merged",
    "closed": "rejected",
}


def son_kayit(session: Session, sid: uuid.UUID) -> tuple[str | None, dict[str, Any]]:
    row = session.execute(
        select(AuditEvent.eylem, AuditEvent.ozet)
        .where(AuditEvent.nesne == f"script:{sid}", AuditEvent.eylem.in_(KAYIT_EYLEMLERI))
        .order_by(AuditEvent.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None, {}
    return row.eylem, dict(row.ozet or {})


def _dogrulama(k: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    probe = k.get("probe") or {}
    if probe.get("matches") == 1:
        out.append(
            "Rol + ad eşleşmesi çalışan uygulamada tek eleman verdi"
            + (f" (kapsam {k.get('scope_test_id')})" if k.get("scope_test_id") else "")
        )
    if probe.get("sha_eslesmesi"):
        out.append(f"Çalışan uygulama sha eşleşmesi: {probe.get('sha_eslesmesi')}")
    aria = k.get("aria") or {}
    if aria.get("gecerli"):
        out.append(f"Son yeşil ({aria.get('kaynak')}): {aria.get('neden')}")
    ast = k.get("ast_guard") or {}
    if "ok" in ast:
        out.append(
            "AST koruması (repair): yalnızca testId değeri değişiyor"
            if ast.get("ok")
            else "AST koruması ihlal buldu"
        )
    yk = k.get("yerel_kontrol") or {}
    if yk.get("sonuc"):
        out.append(
            "Yerel kontrol (tam paket): " + ("yeşil" if yk.get("sonuc") == "success" else "kırmızı")
        )
    if k.get("engel"):
        out.append(f"Engellendi ({k['engel'].get('adim')}): {k['engel'].get('neden')}")
    return out


def pr_web_url(number: int) -> str | None:
    """Onarım PR'ının tarayıcı adresi: GitHub kipinde depo adından; LocalForge'da web arayüzü yok.

    Onarım PR'ı açılırken forge'un döndürdüğü adres saklanmaz; adres depo + numaradan
    deterministiktir (GitHub Enterprise'da web kökü `GITHUB_API_URL`'den türetilir).
    """
    import os

    from tp_core.config import get_settings

    ayar = get_settings()
    if ayar.forge != "github" or not ayar.github_repo:
        return None
    api = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
    web = "https://github.com" if api == "https://api.github.com" else api.removesuffix("/api/v3")
    return f"{web}/{ayar.github_repo}/pull/{number}"


def pr_response(session: Session, number: int) -> dict[str, Any] | None:
    sc = repair_script_for_pr(session, number)
    if sc is None:
        return None
    satir = session.get(PullRequest, number)
    return {
        "number": number,
        "url": pr_web_url(number),
        "baslik": satir.baslik if satir else None,
        "branch": sc.branch,
        "durum": satir.durum if satir else ("merged" if sc.durum == "merged" else "open"),
        "head_sha": sc.head_sha,
        "merge_sha": satir.merge_sha if satir else None,
        "icerik_hash": sc.icerik_hash,
        "govde": satir.govde if satir else None,
        "script_id": str(sc.id),
        "tur": TUR,
    }


def _son_tam_kayit(session: Session, sid: uuid.UUID) -> dict[str, Any]:
    """Önceki denemelerden en son PR/kontrol kaydı (yama, AST, yerel kontrol için)."""
    row = session.execute(
        select(AuditEvent.ozet)
        .where(
            AuditEvent.nesne == f"script:{sid}",
            AuditEvent.eylem.in_(("repair.pr_opened", "repair.checked")),
        )
        .order_by(AuditEvent.id.desc())
        .limit(1)
    ).first()
    return dict(row.ozet or {}) if row else {}


def onarim(
    session: Session, sc: Script, *, oneri: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    eylem, k = son_kayit(session, sc.id)
    if sc.durum in ("pr_open", "merged") and eylem not in ("repair.pr_opened",):
        # PR'lı onarımda gösterilen kanıt PR'ın kanıtıdır.
        k = {**_son_tam_kayit(session, sc.id), **{x: y for x, y in k.items() if y is not None}}
    o = (
        dict(oneri)
        if oneri is not None
        else (_svc._oneri(session, sc.failure_id) if sc.failure_id else {})
    )
    loc = k.get("locator") or {}
    pr = pr_response(session, sc.pr_no) if sc.pr_no else None
    engel = k.get("engel") if sc.durum in ("blocked", "failed") else None
    return {
        "tur": TUR,
        "script_id": str(sc.id),
        "failure_id": str(sc.failure_id) if sc.failure_id else None,
        "script_durumu": sc.durum,
        "durum": DURUM_ESLEME.get(sc.durum, "proposed"),
        "engellendi": sc.durum in ("blocked", "failed"),
        "dosya": k.get("dosya") or (loc.get("dosya")) or sc.dosya_yolu,
        # Engellenen deneme öneriyi silmez: kayıtta yoksa triage önerisinden.
        "anahtar": loc.get("tam_ad") or loc.get("anahtar") or o.get("locator_key"),
        "eski_test_id": k.get("eski_test_id") or o.get("old_testid"),
        "yeni_test_id": k.get("yeni_test_id") or o.get("new_testid"),
        "rol": loc.get("rol") or o.get("rol"),
        "ad": loc.get("ad") or o.get("ad"),
        "yama": k.get("fark") or None,
        "dogrulama": _dogrulama({**k, "engel": engel}),
        "probe": k.get("probe"),
        "aria": {key: v for key, v in (k.get("aria") or {}).items() if key != "denenen"},
        "ast_guard": k.get("ast_guard"),
        "yerel_kontrol": k.get("yerel_kontrol"),
        "etkilenen_testler": k.get("etkilenen_testler") or [],
        "engel": engel,
        "son_kayit": eylem,
        "ai_uretimi": False,
        "mode": None,  # model çağrısı yok
        "pr": pr,
    }


def oneri_blogu(session: Session, failure_id: uuid.UUID) -> dict[str, Any] | None:
    """Hatanın onarım bloğu: kendi onarımı; yoksa (ya da kendi denemesi engellendiyse) aynı
    değişikliğin paylaşılan onarımı (`paylasilan_failure_id`); hiçbiri yoksa None."""
    sc = session.scalars(
        select(Script)
        .where(Script.failure_id == failure_id, Script.tur == TUR)
        .order_by(Script.olusturma.desc())
        .limit(1)
    ).first()
    if sc is not None and sc.durum not in ("blocked", "failed", "closed"):
        return onarim(session, sc)
    f = session.get(Failure, failure_id)
    ortak = _svc.paylasilan_onarim(session, f) if f is not None else None
    if ortak is not None:
        blok = onarim(session, ortak, oneri=_svc._oneri(session, failure_id))
        blok.update(
            paylasilan=True,
            paylasilan_failure_id=str(ortak.failure_id),
            paylasilan_mesaj=(
                f"Bu onarım {str(ortak.failure_id)[:8]} hatasıyla paylaşılıyor "
                "(aynı locator değişikliği" + (f"; PR #{ortak.pr_no}" if ortak.pr_no else "") + ")."
            ),
            kendi_script_id=str(sc.id) if sc is not None else None,
        )
        return blok
    return onarim(session, sc) if sc is not None else None
