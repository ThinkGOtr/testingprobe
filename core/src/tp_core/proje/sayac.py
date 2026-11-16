"""Proje başına sayaç (TP-COK-PROJE-PLANI §1.5): LocalForge PR no (`'pr'`), talep no (`'talep'`).

Yarışsız ve işlem kapsamlı: satır kilidi işlem sonuna kadar tutulur; işlem geri alınırsa numara da
geri alınır (boşluksuz). İlk çağrı 1 döner (tohum yoksa).
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from tp_core.proje.baglam import mevcut_pid


def sonraki(conn: Connection, ad: str, project_id: str | None = None) -> int:
    if not ad or len(ad) > 64:
        raise ValueError(f"geçersiz sayaç adı: {ad!r}")
    pid = project_id if project_id is not None else mevcut_pid()
    return int(
        conn.execute(
            text(
                "INSERT INTO proje_sayac (project_id, ad, deger) VALUES (:pid, :ad, 1) "
                "ON CONFLICT (project_id, ad) DO UPDATE SET deger = proje_sayac.deger + 1 "
                "RETURNING deger"
            ),
            {"pid": pid, "ad": ad},
        ).scalar_one()
    )
