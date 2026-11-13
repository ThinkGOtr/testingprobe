"""Ekilmiş hata kataloğu ("ekilmiş hata koşusu", 012 §4.6).

Demo uygulamaya bilerek konan dokuz hata. Her biri **bayi bazında** açılır
(`POST /test/break {kullanici_adi, hata}`, tablo `test_kirilma.hata`); bir bayide aynı anda en çok
bir hata etkindir. Diğer bayiler, `bayi3` (doğrulama ajanı) ve test modu dışındaki süreçler
etkilenmez. Katalog `GET /test/faults` ile okunur.

İki tür vardır:
- `kod`: hesap kuralı o bayi için değişir (`pricing.py` bu dosyadaki işlevleri çağırır).
- `veri`: okunan değer o bayi için ezilir (minimum sipariş tutarı, ürün fiyatı, kampanyalı ürün).
  `ayar` / `urun` / `kampanya` tablolarına YAZILMAZ: `/test/reset` tabloları yeniden tohumlar ve
  tabloya yazılan değer bütün bayileri etkilerdi.

Bu dosya saf işlevlerden oluşur; veritabanı bilmez. `hata=None` her işlevde normal davranıştır.
Süreç geneli `BREAK_CAMPAIGN=1` (`campaign.bedava_adet`) bundan bağımsızdır ve değişmemiştir.
"""

from dataclasses import asdict, dataclass
from decimal import Decimal

from demoapp_api import campaign

TUR_KOD = "kod"
TUR_VERI = "veri"

KAMPANYA_BEDAVA_YOK = "kampanya_bedava_yok"
KAMPANYA_TEK_BEDAVA = "kampanya_tek_bedava"
KAMPANYA_CIFT_INDIRIM = "kampanya_cift_indirim"
MIN_SIPARIS_HARIC = "min_siparis_haric"
MIN_SIPARIS_MUAFIYET_YOK = "min_siparis_muafiyet_yok"
MIN_SIPARIS_500 = "min_siparis_500"
MIN_SIPARIS_1000 = "min_siparis_1000"
FIYAT_P004_31 = "fiyat_p004_31"
KAMPANYA_URUNU_P002 = "kampanya_urunu_p002"

# Kolon genişliği ve koşucu sözleşmesi (`TP_FAULT`: ^[a-z0-9_]{1,40}$).
KOD_UZUNLUGU = 40


@dataclass(frozen=True)
class Hata:
    kod: str
    tur: str
    ad: str
    aciklama: str


KATALOG: tuple[Hata, ...] = (
    Hata(
        KAMPANYA_BEDAVA_YOK,
        TUR_KOD,
        "Kampanya: bedava adet verilmez",
        "Kampanyalı satırda bedava adet her zaman 0 olur; indirim uygulanmaz.",
    ),
    Hata(
        KAMPANYA_TEK_BEDAVA,
        TUR_KOD,
        "Kampanya: en çok 1 bedava",
        "Ayırt edici girdi 14 adet: doğru 2 bedava, hatalı 1. Bedava adet en çok 1 verilir "
        "(min(1, adet // 6)); hatasız uygulamayla 6 ve 7 adette aynı sonucu verir, 14 adette "
        "(7'nin 2 katı) ayrılır.",
    ),
    Hata(
        KAMPANYA_CIFT_INDIRIM,
        TUR_KOD,
        "Kampanya: indirim iki kez düşülür",
        "Kampanya indirimi satır tutarından iki kez düşülür; bedava adet değişmez.",
    ),
    Hata(
        MIN_SIPARIS_HARIC,
        TUR_KOD,
        "Minimum sipariş: sınır dahil değil",
        "Toplam minimum tutara eşitken sipariş kabul edilmez (toplam > minimum aranır).",
    ),
    Hata(
        MIN_SIPARIS_MUAFIYET_YOK,
        TUR_KOD,
        "Minimum sipariş: kampanya muafiyeti yok",
        "Kampanyalı ürün içeren sepet de minimum sipariş tutarına tabi tutulur.",
    ),
    Hata(
        MIN_SIPARIS_500,
        TUR_VERI,
        "Minimum sipariş tutarı 500,00 TL",
        "Minimum sipariş tutarı 750,00 TL yerine 500,00 TL okunur (story metnindeki eski değer; "
        "onaylı kural 750,00 TL).",
    ),
    Hata(
        MIN_SIPARIS_1000,
        TUR_VERI,
        "Minimum sipariş tutarı 1.000,00 TL",
        "Minimum sipariş tutarı 750,00 TL yerine 1.000,00 TL okunur.",
    ),
    Hata(
        FIYAT_P004_31,
        TUR_VERI,
        "P-004 fiyatı 31,00 TL",
        "P-004 ürününün birim fiyatı 30,00 TL yerine 31,00 TL okunur.",
    ),
    Hata(
        KAMPANYA_URUNU_P002,
        TUR_VERI,
        "Kampanyalı ürün P-002",
        "Kampanya P-001 yerine P-002 ürününde geçerli okunur.",
    ),
)

KODLAR: frozenset[str] = frozenset(h.kod for h in KATALOG)

_MIN_SIPARIS = {MIN_SIPARIS_500: Decimal("500.00"), MIN_SIPARIS_1000: Decimal("1000.00")}
_FIYAT = {FIYAT_P004_31: ("P-004", Decimal("31.00"))}
_KAMPANYA_URUNU = {KAMPANYA_URUNU_P002: "P-002"}


def gecerli(kod: str | None) -> bool:
    return kod in KODLAR


def katalog_json() -> list[dict[str, str]]:
    return [asdict(h) for h in KATALOG]


def bilinmeyen_kod_mesaji(kod: str) -> str:
    return f"Bilinmeyen hata kodu: '{kod}'. Geçerli kodlar: {', '.join(h.kod for h in KATALOG)}"


def satir_hatasi(satir) -> str | None:
    """`test_kirilma` satırındaki etkin hata kodu. `hata` kolonu boş ama `kampanya` açıksa
    (kolon eklenmeden önce yazılmış satır) `kampanya_bedava_yok`; tanınmayan kod yok sayılır."""
    if satir is None:
        return None
    if gecerli(satir.hata):
        return satir.hata
    return KAMPANYA_BEDAVA_YOK if satir.kampanya and not satir.hata else None


# --------------------------------------------------------------------------- kod hataları
def bedava_adet(adet: int, hata: str | None = None) -> int:
    """Kampanyalı satırın bedava adedi; normal kural `campaign.bedava_adet` içindedir."""
    normal = campaign.bedava_adet(adet, hata == KAMPANYA_BEDAVA_YOK)
    if hata == KAMPANYA_TEK_BEDAVA:
        return min(normal, 1)  # = min(1, adet // 6); süreç geneli BREAK_CAMPAIGN=1 yine 0 verir
    return normal


def indirim_kati(hata: str | None = None) -> int:
    """Kampanya indiriminin satır tutarından kaç kez düşüleceği (normal: 1)."""
    return 2 if hata == KAMPANYA_CIFT_INDIRIM else 1


def min_saglandi(toplam: Decimal, min_tutar: Decimal, hata: str | None = None) -> bool:
    """Minimum sipariş tutarı sağlandı mı (normal: sınır dahil)."""
    return toplam > min_tutar if hata == MIN_SIPARIS_HARIC else toplam >= min_tutar


def muafiyet_yok(hata: str | None = None) -> bool:
    """Kampanyalı sepetin minimum sipariş muafiyeti kaldırıldı mı (normal: False)."""
    return hata == MIN_SIPARIS_MUAFIYET_YOK


# --------------------------------------------------------------------------- veri hataları
def min_siparis(hata: str | None, gercek: Decimal) -> Decimal:
    """Bu bayinin gördüğü minimum sipariş tutarı."""
    return _MIN_SIPARIS.get(hata, gercek) if hata else gercek


def fiyat(hata: str | None, urun_kod: str, gercek: Decimal) -> Decimal:
    """Bu bayinin gördüğü ürün birim fiyatı."""
    kod, deger = _FIYAT.get(hata, (None, gercek)) if hata else (None, gercek)
    return deger if kod == urun_kod else gercek


def kampanya_urunu(hata: str | None) -> str | None:
    """Kampanyalı ürün ezilmişse ürün kodu; değilse None (kampanya tablosu geçerlidir)."""
    return _KAMPANYA_URUNU.get(hata) if hata else None
