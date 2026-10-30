"""Deterministik başlangıç verisi: 5 demo kullanıcısı + zincirli `seed.applied` denetim kaydı."""

import uuid
from typing import Final

from sqlalchemy import text

from tp_core.audit import append_audit
from tp_core.auth.passwords import hash_password
from tp_core.config import get_settings
from tp_core.db import get_engine

NAMESPACE_TP: Final = uuid.UUID("6f1d2c3a-8b4e-5f60-9a7b-1c2d3e4f5a6b")

KULLANICILAR: Final[tuple[tuple[str, str], ...]] = (
    ("analist", "analyst"),
    ("muhendis", "engineer"),
    ("sunucu", "presenter"),
    ("po", "po"),
    ("testci", "tester"),
)


def tp_uuid(tur: str, anahtar: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_TP, f"{tur}:{anahtar}")


def seed() -> int:
    parola = get_settings().seed_user_password
    if parola is None or not parola.get_secret_value():
        raise SystemExit("seed: SEED_USER_PASSWORD tanımlı değil")
    satirlar = [
        {
            "id": tp_uuid("user", ad),
            "ad": ad,
            "rol": rol,
            "hash": hash_password(parola.get_secret_value()),
        }
        for ad, rol in KULLANICILAR
    ]
    with get_engine().begin() as conn:
        yeni = sum(
            conn.execute(
                text(
                    "INSERT INTO app_user (id, kullanici_adi, rol, parola_hash) "
                    "VALUES (:id, :ad, :rol, :hash) ON CONFLICT DO NOTHING RETURNING id"
                ),
                satir,
            ).rowcount
            for satir in satirlar
        )
        append_audit(conn, "system", "seed.applied", None, {"yeni": yeni})
    return yeni


def main() -> None:
    yeni = seed()
    print(f"seed: {len(KULLANICILAR)} kullanıcı (yeni: {yeni})")


if __name__ == "__main__":
    main()
