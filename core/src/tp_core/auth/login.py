"""Giriş: argon2 doğrulama, denetim kaydı ve (kullanıcı adı, istemci) başına deneme sınırı.

Başarısız denemenin denetim kaydında `aktor` sabittir (`anonim`): kimliği doğrulanmamış çağıran
append-only kaydın aktör kolonunu belirleyemez; denenen ad `ozet.denenen_kullanici`'dadır.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.passwords import verify_password
from tp_core.config import get_settings
from tp_core.models import AppUser, KimlikBagi

MAX_DENEME = 5
ANONIM = "anonim"
PENCERE_S = 300.0
MAX_ANAHTAR = 10_000


class LoginThrottle:
    """Süreç içi sayaç: `PENCERE_S` içinde `MAX_DENEME` denemeden sonra kilitler.

    Anahtar çağıranın seçimidir; API `"<kullanıcı adı>|<istemci>"` kullanır.

    Deneme, parola doğrulamasından **önce** `try_acquire` ile atomik olarak ayrılır: eşzamanlı
    istekler aynı pencerede en çok `max_deneme` doğrulama yaptırabilir (kontrol ve kayıt aynı
    kilit altında). Başarılı giriş `success` ile anahtarı temizler; başarısız denemenin ayrılmış
    kaydı pencere boyunca kalır.

    Bellek sınırı: boş kuyruklar silinir; anahtar sayısı `max_anahtar`'ı aşınca süresi dolmuş
    kayıtlar süpürülür, yine aşıyorsa en eski anahtarlar düşürülür (saldırganın seçtiği kullanıcı
    adları sözlüğü sınırsız büyütemez).
    """

    def __init__(
        self,
        max_deneme: int = MAX_DENEME,
        pencere_s: float = PENCERE_S,
        max_anahtar: int = MAX_ANAHTAR,
    ) -> None:
        self.max_deneme = max_deneme
        self.pencere_s = pencere_s
        self.max_anahtar = max_anahtar
        self._kayit: dict[str, deque[float]] = {}
        self._kilit = threading.Lock()

    def _temizle(self, anahtar: str, simdi: float) -> deque[float] | None:
        """Penceresi geçmiş kayıtları atar; kuyruk boşalırsa anahtarı siler (kilit altında)."""
        q = self._kayit.get(anahtar)
        if q is None:
            return None
        while q and simdi - q[0] > self.pencere_s:
            q.popleft()
        if not q:
            del self._kayit[anahtar]
            return None
        return q

    def _supur(self, simdi: float) -> None:
        """Yeni anahtara yer açar: süresi dolanları, gerekirse en eskileri atar (%90'a kadar).

        Sınıra dayanınca her eklemede tüm sözlüğü taramamak için payla süpürülür.
        """
        for anahtar in list(self._kayit):
            self._temizle(anahtar, simdi)
        hedef = max(0, (self.max_anahtar * 9) // 10)
        fazla = len(self._kayit) - min(hedef, self.max_anahtar - 1)
        if fazla > 0:
            for anahtar in list(self._kayit)[:fazla]:
                del self._kayit[anahtar]

    def blocked(self, anahtar: str) -> bool:
        with self._kilit:
            q = self._temizle(anahtar, time.monotonic())
            return q is not None and len(q) >= self.max_deneme

    def try_acquire(self, anahtar: str) -> bool:
        """Bir deneme hakkı ayırır; pencere doluysa False (ayırma yapılmaz)."""
        with self._kilit:
            simdi = time.monotonic()
            q = self._temizle(anahtar, simdi)
            if q is not None and len(q) >= self.max_deneme:
                return False
            if q is None:
                if len(self._kayit) >= self.max_anahtar:
                    self._supur(simdi)
                q = self._kayit[anahtar] = deque()
            q.append(simdi)
            return True

    def failure(self, anahtar: str) -> None:
        """Ayırmadan kaydedilen başarısız deneme (try_acquire kullanan çağıran bunu çağırmaz)."""
        with self._kilit:
            simdi = time.monotonic()
            q = self._temizle(anahtar, simdi)
            if q is None:
                if len(self._kayit) >= self.max_anahtar:
                    self._supur(simdi)
                q = self._kayit[anahtar] = deque()
            q.append(simdi)

    def success(self, anahtar: str) -> None:
        with self._kilit:
            self._kayit.pop(anahtar, None)


THROTTLE = LoginThrottle()


class OrtakKimlikGerekli(Exception):
    """Parola doğru ama hesap bir AI Probe kişisine bağlı (`both` kipi): yerel giriş reddedilir."""


def authenticate(
    session: Session, kullanici_adi: str, parola: str, istemci: str | None = None
) -> AppUser | None:
    """Doğrular ve denetime yazar (`auth.login` / `auth.login_failed`).

    `both` kipinde `kimlik_bagi` satırı olan hesap yerel parolayla açılmaz (AI Probe ile girmeli):
    `auth.login_rejected` yazılır ve `OrtakKimlikGerekli` yükselir. Kontrol parola doğrulandıktan
    sonra yapılır: bağ durumu parolayı bilmeyene sızmaz.
    """
    ad = kullanici_adi.strip()[:64]
    user = session.scalars(select(AppUser).where(AppUser.kullanici_adi == ad)).first()
    ok = verify_password(user.parola_hash if user else None, parola)
    if not ok or user is None:
        ozet: dict[str, str] = {"denenen_kullanici": ad}
        if istemci:
            ozet["istemci"] = istemci
        audit_on_commit(session, ANONIM, "auth.login_failed", None, ozet)
        return None
    if get_settings().auth_mode != "local" and session.scalar(
        select(KimlikBagi.app_user_id).where(KimlikBagi.app_user_id == user.id)
    ):
        audit_on_commit(
            session,
            user.kullanici_adi,
            "auth.login_rejected",
            f"app_user:{user.id}",
            {"neden": "aiprobe_bagli"},
        )
        raise OrtakKimlikGerekli()
    audit_on_commit(session, user.kullanici_adi, "auth.login", f"app_user:{user.id}", {})
    return user
