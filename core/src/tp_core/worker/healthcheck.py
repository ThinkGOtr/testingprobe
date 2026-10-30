"""core-worker compose sağlık kontrolü.

1. Postgres'e bağlanıp job tablosunu okuyabiliyor mu?
2. Ana döngü canlı mı? Worker her turda (ve bir işi beklerken) canlılık dosyasını tazeler; dosya
   `CANLILIK_ESIGI_S`'den eskiyse döngü takılmış demektir. Dosya henüz yoksa (açılış) yalnızca
   DB denetimi yapılır.
"""

import sys
import time

from tp_core import db
from tp_core.worker import CANLILIK_ESIGI_S, canlilik_dosyasi


def canlilik_hatasi(esik_s: float = CANLILIK_ESIGI_S) -> str | None:
    yol = canlilik_dosyasi()
    try:
        yas = time.time() - yol.stat().st_mtime
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"canlılık dosyası okunamadı: {exc}"
    if yas > esik_s:
        return f"worker döngüsü {yas:.0f} sn'dir canlılık bildirmedi (eşik {esik_s:.0f} sn)"
    return None


def main() -> int:
    try:
        db.ping("SELECT 1 FROM job LIMIT 1")
    except Exception as exc:
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1
    hata = canlilik_hatasi()
    if hata:
        print(f"unhealthy: {hata}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
