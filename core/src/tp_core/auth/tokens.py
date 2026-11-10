"""MCP (Claude Code / IDE) kanalı için kısa ömürlü, kapsamlı bearer token'lar (§8.3).

Token yalnızca üretimde bir kez gösterilir (`tpt_` önekli, 256 bit rastgele); veritabanında
sha256 özeti saklanır. Doğrulama: özet eşleşir, iptal edilmemiş, süresi dolmamış, kapsam doğru ve
kullanıcının parolası token üretildiğinden beri değişmemiş (`parola_izi`) ve dış iptal sayacı
aynı (`auth_epoch`). AI Probe kipinde sahip bir kişiye bağlıysa en geç 60 sn'de bir (önbellekli)
oturum kontrolü yapılır (`tp_core.auth.aiprobe.token_kontrol`; `local` kipte dış çağrı yok).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.sessions import aiprobe_acik, password_fingerprint
from tp_core.models import ApiToken, AppUser
from tp_core.workflow.service import Principal

PREFIX = "tpt_"
KAPSAMLAR = frozenset({"publish", "submit"})


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_token(
    session: Session,
    user: Principal,
    kapsam: str,
    ttl_s: int,
    *,
    auth_time: int | None = None,
    acr: str | None = None,
    session_epoch_ms: int | None = None,
) -> tuple[ApiToken, str]:
    """Token üretir. `auth_time`/`acr`/`session_epoch_ms`: üreten AI Probe oturumunun alanları
    (yerel oturumda None).

    AI Probe oturumundan üretilen token o oturumun alanlarını taşır; böylece oturum açıldıktan
    sonra ama token üretilmeden önce yapılan bir iptal (CONTRACT v1.2: `revoked_at_ms ≥
    session_epoch_ms`) token'ı da düşürür ve MFA'lı (`acr=2`) oturumun `po` token'ı home'da
    `admin_roles` süzgecine takılmaz. Yerel oturumdan üretilende boştur; kontrol üretim anıyla.
    """
    if kapsam not in KAPSAMLAR:
        raise ValueError(f"geçersiz kapsam: {kapsam}")
    if user.id is None or user.kanal != "portal":
        raise PermissionError("token yalnızca portal oturumundan üretilir")
    sahip = session.get(AppUser, user.id)
    if sahip is None:
        raise PermissionError("kullanıcı bulunamadı")
    raw = PREFIX + secrets.token_urlsafe(32)
    tok = ApiToken(
        parola_izi=password_fingerprint(sahip.parola_hash),
        auth_epoch=sahip.auth_epoch,
        auth_time=auth_time,
        acr=acr,
        session_epoch_ms=session_epoch_ms,
        user_id=user.id,
        kapsam=kapsam,
        token_hash=token_hash(raw),
        son_kullanma=datetime.now(UTC) + timedelta(seconds=ttl_s),
    )
    session.add(tok)
    session.flush()
    audit_on_commit(
        session,
        user.kullanici_adi,
        "token.issued",
        f"api_token:{tok.id}",
        {"kapsam": kapsam, "son_kullanma": tok.son_kullanma},
    )
    return tok, raw


def verify_bearer(session: Session, raw: str | None, kapsam: str) -> Principal | None:
    """Geçerli token'a karşılık gelen kimlik (kanal='ide'); geçersizse None."""
    if not raw or not raw.startswith(PREFIX) or kapsam not in KAPSAMLAR:
        return None
    row = session.execute(
        select(ApiToken, AppUser)
        .join(AppUser, AppUser.id == ApiToken.user_id)
        .where(ApiToken.token_hash == token_hash(raw))
    ).first()
    if row is None:
        return None
    tok, user = row
    if (
        tok.iptal
        or tok.son_kullanma <= datetime.now(UTC)
        or tok.kapsam != kapsam
        or tok.parola_izi != password_fingerprint(user.parola_hash)
        or tok.auth_epoch != user.auth_epoch
    ):
        return None
    if aiprobe_acik():
        from tp_core.auth import aiprobe

        if tok.auth_time is not None:
            kimlik = aiprobe.OturumKimligi.of(tok)
        else:  # yerel oturumdan üretildi: üretim anı, acr 1, epoch yok (v1.2 öncesi kural)
            kimlik = aiprobe.OturumKimligi(int(tok.olusturma.timestamp()))
        if not aiprobe.token_kontrol(session, user, kimlik):
            return None
    session.execute(
        update(ApiToken).where(ApiToken.id == tok.id).values(son_kullanim=datetime.now(UTC))
    )
    return Principal(user.id, user.kullanici_adi, user.rol, kanal="ide", kapsam=kapsam)


def revoke_token(session: Session, user: Principal, token_id: uuid.UUID) -> bool:
    sonuc = session.execute(
        update(ApiToken)
        .where(ApiToken.id == token_id, ApiToken.user_id == user.id, ApiToken.iptal.is_(False))
        .values(iptal=True)
    )
    if sonuc.rowcount != 1:
        return False
    audit_on_commit(session, user.kullanici_adi, "token.revoked", f"api_token:{token_id}")
    return True
