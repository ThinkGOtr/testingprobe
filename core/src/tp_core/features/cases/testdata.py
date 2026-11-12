"""Case üretimine giden "Test verisi" bloğu (rules/prompts/case-generation.md "Input").

Prompt modele "test verisi, sayı ve mesaj uydurma" der (`_guardrails.md`). Bu yüzden somut kullanıcı
adı, bayi adı, ürün kodu/adı/fiyatı, kredi limiti, minimum tutar ve buton etiketleri girdide
bulunmalıdır; aksi hâlde canlı bir model ya tutarları atlar (Faz 3 `expects` değerleri onaylı case
metninde olmaz) ya da uydurur. Golden'lar bu değerlerle elle yazıldı; blok aynı değerleri
deterministik olarak verir.

Kaynaklar:
- `demoapp_ro` (salt okuma; `DEMOAPP_RO_DATABASE_URL`): `urun` (kod, ad, fiyat), aktif `kampanya`,
  `ayar` (ör. `min_siparis_tutari`), `bayi` (kullanıcı adı, ad, kredi limiti). Parola kolonu bu
  rolde hiç okunamaz.
- Sabit kısım (docs/DEMO-VERISI.md, bağlayıcı demo verisi): test kullanıcılarının ortak demo
  parolası ve arayüzdeki sabit etiketler (demo-app/web).

Blok ayrı bir güvenilmeyen veri bloğunda gider (kaynak `testdata:demo-app`, tür `data`): içerik
veritabanından gelir (§5), talimat taşıyamaz. Golden `input_match` yalnızca `jira:` kaynağını
okuduğundan replay eşleşmesi değişmez; aynı veritabanı aynı metni üretir (sıralı sorgular).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

KAYNAK = "testdata:demo-app"
VERITABANI_YOK = "Veritabanı okunamadı"
# docs/DEMO-VERISI.md: "bayi1 / Demo123!", "bayi2 / Demo123!" (yerel demo; gerçek kimlik değil).
DEMO_PAROLA = "Demo123!"
# demo-app/web arayüzündeki sabit etiketler (LoginPage, CatalogPage, CartPage, Layout).
UI_ETIKETLERI: tuple[str, ...] = (
    "Giriş yap",
    "Katalog",
    "Sepete ekle",
    "Sepetim",
    "Siparişi onayla",
    "Siparişlerim",
    "Siparişlerime git",
    "Çıkış yap",
)

SORGULAR: dict[str, str] = {
    "urun": "SELECT kod, ad, fiyat FROM urun WHERE aktif ORDER BY sira, kod",
    "kampanya": (
        "SELECT kampanya.kod, kampanya.ad, urun.kod FROM kampanya JOIN urun ON "
        "urun.id = kampanya.urun_id WHERE kampanya.aktif ORDER BY kampanya.kod"
    ),
    "ayar": "SELECT anahtar, deger FROM ayar ORDER BY anahtar",
    # bayi3 yalnızca doğrulama ajanının bayisidir (e2e fixture'ları reddeder): case'lere girmez.
    "bayi": (
        "SELECT kullanici_adi, ad, kredi_limiti FROM bayi WHERE kullanici_adi <> 'bayi3' "
        "ORDER BY kullanici_adi"
    ),
}

Sorgu = Callable[[str], Sequence[Sequence[Any]]]


def tl(deger: Any) -> str:
    """Tutar biçimi (tr-TR, iki ondalık): ``Decimal("1250")`` → ``1.250,00 TL``."""
    try:
        d = Decimal(str(deger)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return str(deger)
    tam, _, kusur = f"{d:,.2f}".partition(".")
    return f"{tam.replace(',', '.')},{kusur} TL"


def _tutar_mi(anahtar: str) -> bool:
    return any(p in anahtar for p in ("tutar", "limit", "fiyat"))


def build_text(sorgu: Sorgu | None) -> str:
    """Bloğun metni. `sorgu` None ya da hata verirse veritabanı kısmı yok sayılır (not düşülür)."""
    satirlar: list[str] = ["Test verisi (demo uygulaması):"]
    veri: dict[str, Sequence[Sequence[Any]]] = {}
    if sorgu is not None:
        try:
            veri = {ad: sorgu(sql) for ad, sql in SORGULAR.items()}
        except Exception as exc:  # veritabanı yoksa üretim yine çalışır
            log.warning("Test verisi okunamadı: %s", exc)
            veri = {}
    if veri:
        satirlar.append("Test kullanıcıları (bayi):")
        for kullanici, ad, limit in veri["bayi"]:
            satirlar.append(
                f'- {kullanici} / {DEMO_PAROLA} — bayi adı "{ad}", kredi limiti {tl(limit)}'
            )
        satirlar.append("Ürünler (kod · ad · birim fiyat):")
        for kod, ad, fiyat in veri["urun"]:
            satirlar.append(f'- {kod} · "{ad}" · {tl(fiyat)}')
        satirlar.append("Aktif kampanyalar:")
        satirlar += [f'- "{ad}" ({kod}) — ürün {urun}' for kod, ad, urun in veri["kampanya"]] or [
            "- yok"
        ]
        satirlar.append("Uygulama ayarları:")
        for anahtar, deger in veri["ayar"]:
            ek = f" ({tl(deger)})" if _tutar_mi(str(anahtar)) else ""
            satirlar.append(f"- {anahtar} = {deger}{ek}")
    else:
        satirlar.append(
            f"- {VERITABANI_YOK}; yalnızca sabit bilgiler. Test kullanıcılarının parolası: "
            f"{DEMO_PAROLA}"
        )
    satirlar.append("Arayüz etiketleri: " + ", ".join(f'"{e}"' for e in UI_ETIKETLERI))
    satirlar.append("Tutar biçimi: 1.250,00 TL (tr-TR, iki ondalık).")
    return "\n".join(satirlar)


def demo_db_query() -> Sorgu | None:
    """`DEMOAPP_RO_DATABASE_URL` tanımlıysa salt okuma sorgu fonksiyonu (core-worker)."""
    from tp_core.features.requirements.datatools import DemoDb
    from tp_core.features.requirements.settings import get_requirements_settings

    url = get_requirements_settings().demoapp_ro_database_url
    if not url:
        return None
    db = DemoDb(url)
    return lambda sql: db.query(sql).rows


_sorgu_fabrikasi: Callable[[], Sorgu | None] = demo_db_query


def set_query_factory(fabrika: Callable[[], Sorgu | None] | None) -> None:
    """Testler için (None → `DEMOAPP_RO_DATABASE_URL`)."""
    global _sorgu_fabrikasi
    _sorgu_fabrikasi = fabrika or demo_db_query


def model_kipi() -> str | None:
    """Geçidin yapılandırılmış kipi (`live` | `replay` | `record`); okunamazsa None."""
    try:
        from tp_core.gateway.config import GatewaySettings, resolve_mode

        return resolve_mode(GatewaySettings())
    except Exception as exc:  # pragma: no cover - yapılandırma okunamazsa eski yol
        log.warning("Model kipi okunamadı: %s", exc)
        return None


def block(session: Session | None = None) -> str:
    """Modele giden güvenilmeyen veri bloğu (kaynak `testdata:demo-app`).

    K17 (specs/013 §9): model kipi `live`/`record` ve `session` verilmişse blok **test verisi
    kataloğundan** kurulur (yeni kayıtlar ve değişen değerler dahil; biçim DB bloğuyla aynı
    kurallar). `replay`'de (ve katalog kurulamazsa) bugünkü demo DB bloğu kullanılır: REPLAY
    girdileri / golden'lar değişmez.
    """
    from tp_core.gateway import wrap_untrusted

    if session is not None and model_kipi() in ("live", "record"):
        katalogdan = _katalog_metni(session)
        if katalogdan is not None:
            return wrap_untrusted(katalogdan, source=KAYNAK, kind="data")
        log.warning("Test verisi bloğu katalogdan kurulamadı; model girdisi demo DB'den")
    try:
        sorgu = _sorgu_fabrikasi()
    except Exception as exc:
        log.warning("Test verisi kaynağı açılamadı: %s", exc)
        sorgu = None
    return wrap_untrusted(build_text(sorgu), source=KAYNAK, kind="data")


def _katalog_metni(session: Session) -> str | None:
    from tp_core.features.testveri.service import blok_metni

    try:
        return blok_metni(session)
    except Exception as exc:  # katalog okunamazsa model girdisi eski yoldan
        log.warning("Test verisi bloğu katalogdan kurulamadı: %s", exc)
        return None
