"""Müşteri CI hattının sözleşmesi (TASARIM test-dilleri §1.3, §3.3, §3.4; Ş5).

`musteri_ci` hattında TP testi **üretir**, statik korumadan geçirir ve PR açar; derleme ve koşu
müşterinin GitHub Actions'ındadır. TP check sonucunu ve `tp-results` artefaktını okur. Kırarak
doğrulama yoktur: PR gövdesi ve portal bunu "kırarak doğrulanmadı" bilgisiyle açıkça söyler.

Bu modül saf veridir (veritabanı/ağ yok). Ş0'ın `codegen/platform.py` `CATILAR` tablosu
geldiğinde `hat == "musteri_ci"` olan çiftler buradaki `HEDEFLER` ile aynı olmalıdır
(`test_musteri_ci_sozlesme.py` iki tabloyu karşılaştırır; tablo yoksa yerel tablo geçerlidir).

Şablon iş adı = GitHub check adı (`is_adi`): merge kapısı bu adı zorunlu check olarak ister.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

HAT = "musteri_ci"
TP_RESULTS_ARTIFACT = "tp-results"
CI_META_AD = "ci-meta.json"
# Şablonların tp-results artefaktı içindeki düzeni (artefakt köküne göre).
JUNIT_DIZINI = "junit"  # JUnit XML'leri (Android: TEST-*.xml kopyaları; iOS: xcresult-junit.xml)
EK_DIZINI = "ekler"  # ekran görüntüleri / xcresult ekleri
DERLEME_LOG_AD = "derleme.log"  # derleme/koşu adımının son satırları (derleme hatası kesiti)
SABLON_KOKU = "rules/ci-sablonlari"

_AD_RE = re.compile(r"[a-z][a-z0-9]{1,15}")


@dataclass(frozen=True)
class MusteriCiHedefi:
    """(platform, dil) çiftinin müşteri CI tanımı."""

    platform: str
    dil: str
    is_adi: str  # GitHub job adı = check adı ("mobil-android-kotlin")
    is_akisi: str  # müşteri deposundaki iş akışı dosyası ("mobil-android-kotlin.yml")
    sablon: str  # rules/ci-sablonlari altındaki iş akışı şablonu
    yardimcilar: tuple[str, ...] = ()  # şablonla birlikte depoya giren betikler (ci-sablonlari adı)
    yardimci_hedef_dizini: str = ".github/tp"  # yardımcı betiklerin depodaki dizini

    @property
    def is_akisi_yolu(self) -> str:
        return f".github/workflows/{self.is_akisi}"

    @property
    def sonuc_kok(self) -> str:
        return sonuc_koku(self.platform, self.dil)


HEDEFLER: dict[tuple[str, str], MusteriCiHedefi] = {
    ("android", "kotlin"): MusteriCiHedefi(
        platform="android",
        dil="kotlin",
        is_adi="mobil-android-kotlin",
        is_akisi="mobil-android-kotlin.yml",
        sablon="android-espresso.yml",
    ),
    ("ios", "swift"): MusteriCiHedefi(
        platform="ios",
        dil="swift",
        is_adi="mobil-ios-swift",
        is_akisi="mobil-ios-swift.yml",
        sablon="ios-xcuitest.yml",
        yardimcilar=("xcresult_junit.py",),
    ),
}


class MusteriCiHatasi(ValueError):
    """Geçersiz (platform, dil) ya da sözleşme ihlali."""


def musteri_ci_mi(platform: Any, dil: Any) -> bool:
    """(platform, dil) müşteri CI hattında mı (Kotlin/Espresso, Swift/XCUITest)?"""
    try:
        return (platform, dil) in HEDEFLER
    except TypeError:  # hash'lenemeyen girdi
        return False


def hedef(platform: Any, dil: Any) -> MusteriCiHedefi:
    """Çiftin tanımı; müşteri CI hattı değilse `MusteriCiHatasi`."""
    try:
        return HEDEFLER[(platform, dil)]
    except (KeyError, TypeError):
        raise MusteriCiHatasi(f"müşteri CI hattı değil: {platform}/{dil}") from None


def is_adi(platform: str, dil: str) -> str:
    """Şablondaki job adı = GitHub check adı (merge kapısının istediği ad)."""
    return hedef(platform, dil).is_adi


def is_adlari() -> tuple[str, ...]:
    return tuple(h.is_adi for h in HEDEFLER.values())


def hedef_is_adindan(ad: Any) -> MusteriCiHedefi | None:
    """GitHub check/job adından hedef (bilinmiyorsa None)."""
    return next((h for h in HEDEFLER.values() if h.is_adi == ad), None)


def sonuc_koku(platform: str, dil: str) -> str:
    """tp-results yerel kopyasının koşu dizinine göre kökü: `src/<platform>-<dil>/results`.

    Artefakt sunumunun izinli alt ağacı `src/**/results/**` içindedir. Yalnız küçük harfli
    alfasayısal adlar kabul edilir (yol enjeksiyonu yok)."""
    if not (
        isinstance(platform, str)
        and isinstance(dil, str)
        and _AD_RE.fullmatch(platform)
        and _AD_RE.fullmatch(dil)
    ):
        raise MusteriCiHatasi(f"geçersiz platform/dil: {platform!r}/{dil!r}")
    return f"src/{platform}-{dil}/results"


# ------------------------------------------------------------------ "kırarak doğrulanmadı"

KIRARAK_DOGRULANMADI: dict[str, str] = {
    "kod": "kirarak_dogrulanmadi",
    "etiket": "Kırarak doğrulanmadı",
    "aciklama": (
        "Bu test müşterinin CI'ında derlenip koşuldu; TP uygulamayı kasıtlı bozarak testin "
        "hatayı yakaladığını doğrulayamadı. Yeşil CI merge için yeterlidir, ancak yanlış-yeşil "
        "riski tam hattan yüksektir."
    ),
}


def dogrulama_bilgisi(platform: Any, dil: Any) -> dict[str, Any] | None:
    """Portal/API için hat bilgisi. Müşteri CI hattıysa
    `{hat, check, is_akisi, kirarak_dogrulama: False, rozet: KIRARAK_DOGRULANMADI}`;
    değilse None."""
    if not musteri_ci_mi(platform, dil):
        return None
    h = hedef(platform, dil)
    return {
        "hat": HAT,
        "check": h.is_adi,
        "is_akisi": h.is_akisi_yolu,
        "kirarak_dogrulama": False,
        "rozet": dict(KIRARAK_DOGRULANMADI),
    }


def pr_govdesi_notu(platform: Any, dil: Any) -> str:
    """Üretim PR'ının gövdesine eklenecek Markdown bölümü; müşteri CI hattı değilse ""."""
    if not musteri_ci_mi(platform, dil):
        return ""
    h = hedef(platform, dil)
    return (
        f"### {KIRARAK_DOGRULANMADI['etiket']}\n\n"
        f"Bu test TP'de statik korumadan geçti; derleme ve koşu bu deponun GitHub Actions "
        f"iş akışında (`{h.is_akisi_yolu}`, check `{h.is_adi}`) yapılır. "
        f"{KIRARAK_DOGRULANMADI['aciklama']}\n"
    )
