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

# Portalda gösterilen kişi adları (demo varsayılanı; `TP_GORUNEN_ADLAR` ile değiştirilir). Ad
# yalnızca gösterim içindir: yetki her zaman roldedir. Boş ad = yalnızca rol etiketi ("Sunucu").
GORUNEN_ADLAR: Final[dict[str, str]] = {
    "analist": "Cengizhan Gunaydin",
    "po": "Cengizhan Gunaydin",
    "muhendis": "Gokhan Sipahi",
    "testci": "Fatih Arslan",
    "sunucu": "",
}


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


def seed_test_verisi() -> int:
    """Test verisi kataloğu tohumu (013 §3.3; idempotent). core-api demo DB'ye bağlanmaz: burada
    yalnız sabitler eklenir, demo DB kayıtlarını worker açılışı ekler."""
    from tp_core.features.testveri.service import tohumla
    from tp_core.models import session_scope

    with session_scope() as s:
        return tohumla(s)


def seed_otomasyon_demo() -> dict[str, str]:
    """Demo ortamı otomasyon ayarları (013 K20, K23): onay sonrası otomatik kod KAPALI; Demo-B
    kodu "Kod üret" düğmesiyle yürütür. Yalnız satır yoksa ve yalnız demo ortamında (doğrulanmış
    Jira sim'i ya da model kipi REPLAY) yazılır (denetimli, aktör `seed`); gerçek Jira'lı
    kurulumda ürün varsayılanı (açık) korunur (`gercek_ortam`)."""
    from tp_core.features.otomasyon import ayarlar
    from tp_core.models import session_scope

    with session_scope() as s:
        return ayarlar.demo_ayarlarini_yaz(s, "seed", yalniz_yoksa=True)


def main() -> None:
    yeni = seed()
    print(f"seed: {len(KULLANICILAR)} kullanıcı (yeni: {yeni})")
    print(f"seed: test verisi kataloğu (yeni: {seed_test_verisi()})")
    print(f"seed: demo otomasyon ayarları {seed_otomasyon_demo()}")


if __name__ == "__main__":
    main()
