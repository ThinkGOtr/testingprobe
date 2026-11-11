"""Asistan niyet sinyalleri ve kart dedektörü (specs/013-asistan-guvenlik/ANALIZ.md §5, K2).

İki tür dedektör vardır:

- **Kesin** (`kart_bul`): Luhn'lu kart numarası. Uç (`api._kisisel_veri_kontrol`) soruyu 422
  `kisisel_veri` ile reddeder; değer hiçbir yere yazılmaz. TCKN/IBAN `maskeleme.mesaj_oturumu`'nda
  her zaman maskelenir (bu modülde değil).
- **Niyet** (`girdi_sinyalleri`, `cikti_sinyalleri`): `rules/assistant/sinyaller.yaml`'daki
  desenler. Yalnız sinyaldir, hiçbir şeyi engellemez: girdi sinyali modele sunucu notu olarak
  ipucu verir ve cevaba kimlik olarak yazılır; çıktı sinyali cevaba sabit bir not ekler, cevabı
  değiştirmez. Değer ya da eşleşen metin hiçbir yere yazılmaz.

Eşleşme metni katlanır (`katla`): Türkçe küçük harf (I→ı, İ→i; `siniflandir.normalize`), tek
boşluk, sonra Türkçe harfler ASCII karşılığına (ı→i, ş→s, ğ→g, ü→u, ö→o, ç→c). Böylece
"Üretim", "URETIM" ve "uretim" aynı desene düşer; desenler katlanmış (küçük harf ASCII) yazılır.
Yükleyici Türkçe harf içeren deseni reddeder (hiç eşleşmeyecek bir desen sessizce kalmasın).

Desen dosyası bilgi paketine alınmaz (K7): asistan kendi dedektörlerinin desenini okuyamaz.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from tp_core.features.assistant.siniflandir import normalize

SINYAL_DOSYASI: Final = "sinyaller.yaml"
YONLER: Final = ("girdi", "cikti")
_KAYIT_ALANLARI: Final = frozenset({"id", "yon", "regex", "istisna_regex", "ipucu", "not"})
_UST_ALANLAR: Final = frozenset({"surum", "parcalar", "sinyaller"})
_PARCA: Final = re.compile(r"\{\{([a-z_]+)\}\}")
_KIMLIK: Final = re.compile(r"[a-z][a-z0-9_]*")
_TURKCE_HARF: Final = re.compile(r"[ıİşŞğĞüÜöÖçÇâÂîÎûÛ]")
_KATLAMA: Final = str.maketrans(
    {"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "â": "a", "î": "i", "û": "u"}
)
_BIRLESIK_NOKTA: Final = "̇"  # "İ".lower() artığı (normalize zaten önler; savunma)
_KESME: Final = str.maketrans({"’": "'", "‘": "'", "`": "'"})


class SinyalHatasi(ValueError):
    """`sinyaller.yaml` geçersiz (bilinmeyen alan, eksik alan, derlenemeyen desen…)."""


@dataclass(frozen=True)
class Sinyal:
    id: str
    yon: Literal["girdi", "cikti"]
    ipucu: str
    not_: str | None


@dataclass(frozen=True)
class SinyalTanimi:
    id: str
    yon: Literal["girdi", "cikti"]
    desenler: tuple[re.Pattern[str], ...]
    istisnalar: tuple[re.Pattern[str], ...]
    ipucu: str
    not_: str | None

    @property
    def sinyal(self) -> Sinyal:
        return Sinyal(self.id, self.yon, self.ipucu, self.not_)

    def eslesir(self, katli: str) -> bool:
        """`katli`: `katla`'dan geçmiş metin."""
        if not katli or not any(d.search(katli) for d in self.desenler):
            return False
        return not any(i.search(katli) for i in self.istisnalar)


def katla(metin: str | None) -> str:
    """Eşleşme metni: Türkçe küçük harf + tek boşluk + ASCII katlama (modül belgesi)."""
    return normalize(metin).replace(_BIRLESIK_NOKTA, "").translate(_KATLAMA).translate(_KESME)


# ------------------------------------------------------------------ yükleme


def _liste(deger: Any, alan: str, kimlik: str) -> list[str]:
    if deger is None:
        return []
    ogeler = [deger] if isinstance(deger, str) else deger
    if not isinstance(ogeler, list) or not all(isinstance(o, str) and o for o in ogeler):
        raise SinyalHatasi(f"{kimlik}: '{alan}' bir dizge ya da dizge listesi olmalı")
    return list(ogeler)


def _derle(desen: str, parcalar: Mapping[str, str], kimlik: str) -> re.Pattern[str]:
    def yerlestir(m: re.Match[str]) -> str:
        if m.group(1) not in parcalar:
            raise SinyalHatasi(f"{kimlik}: bilinmeyen parça '{m.group(1)}'")
        return parcalar[m.group(1)]

    acik = _PARCA.sub(yerlestir, desen)
    if _TURKCE_HARF.search(acik):
        raise SinyalHatasi(f"{kimlik}: desen katlanmış (ASCII) yazılmalı: Türkçe harf var")
    try:
        return re.compile(acik)
    except re.error as exc:
        raise SinyalHatasi(f"{kimlik}: desen derlenemedi ({exc})") from exc


def _tanim(kayit: Any, parcalar: Mapping[str, str], sira: int) -> SinyalTanimi:
    if not isinstance(kayit, Mapping):
        raise SinyalHatasi(f"sinyal #{sira}: kayıt bir eşleme olmalı")
    kimlik = kayit.get("id")
    if not isinstance(kimlik, str) or not _KIMLIK.fullmatch(kimlik):
        raise SinyalHatasi(f"sinyal #{sira}: geçersiz 'id'")
    fazla = set(kayit) - _KAYIT_ALANLARI
    if fazla:
        raise SinyalHatasi(f"{kimlik}: bilinmeyen alan(lar) {sorted(fazla)}")
    yon = kayit.get("yon")
    if yon not in YONLER:
        raise SinyalHatasi(f"{kimlik}: 'yon' girdi ya da cikti olmalı")
    ipucu = kayit.get("ipucu")
    if not isinstance(ipucu, str) or not ipucu.strip():
        raise SinyalHatasi(f"{kimlik}: 'ipucu' gerekli")
    not_ = kayit.get("not")
    if yon == "cikti" and (not isinstance(not_, str) or not not_.strip()):
        raise SinyalHatasi(f"{kimlik}: çıktı sinyalinde 'not' gerekli")
    if yon == "girdi" and not_ is not None:
        raise SinyalHatasi(f"{kimlik}: 'not' yalnız çıktı sinyallerinde")
    desenler = _liste(kayit.get("regex"), "regex", kimlik)
    if not desenler:
        raise SinyalHatasi(f"{kimlik}: 'regex' gerekli")
    return SinyalTanimi(
        id=kimlik,
        yon=yon,
        desenler=tuple(_derle(d, parcalar, kimlik) for d in desenler),
        istisnalar=tuple(
            _derle(d, parcalar, kimlik)
            for d in _liste(kayit.get("istisna_regex"), "istisna_regex", kimlik)
        ),
        ipucu=" ".join(ipucu.split()),
        not_=" ".join(not_.split()) if isinstance(not_, str) else None,
    )


def tanimlari_ayristir(veri: Any) -> tuple[SinyalTanimi, ...]:
    """YAML içeriği → tanımlar; her hata `SinyalHatasi` (yükleme anında, sessiz geçiş yok)."""
    if not isinstance(veri, Mapping):
        raise SinyalHatasi("sinyaller.yaml bir eşleme olmalı")
    fazla = set(veri) - _UST_ALANLAR
    if fazla:
        raise SinyalHatasi(f"bilinmeyen üst alan(lar) {sorted(fazla)}")
    if veri.get("surum") != 1:
        raise SinyalHatasi("desteklenen sürüm: 1")
    ham_parcalar = veri.get("parcalar") or {}
    if not isinstance(ham_parcalar, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in ham_parcalar.items()
    ):
        raise SinyalHatasi("'parcalar' ad → dizge eşlemesi olmalı")
    # Parçalar birbirine başvurabilir (tek düzey yeterli değil); döngü/bilinmeyen ad hata verir.
    parcalar: dict[str, str] = {}

    def coz(ad: str, yol: tuple[str, ...]) -> str:
        if ad in parcalar:
            return parcalar[ad]
        if ad in yol:
            raise SinyalHatasi(f"parça döngüsü: {' → '.join((*yol, ad))}")
        if ad not in ham_parcalar:
            raise SinyalHatasi(f"bilinmeyen parça '{ad}'")
        parcalar[ad] = _PARCA.sub(lambda m: coz(m.group(1), (*yol, ad)), ham_parcalar[ad])
        return parcalar[ad]

    for ad in ham_parcalar:
        coz(ad, ())
    kayitlar = veri.get("sinyaller")
    if not isinstance(kayitlar, list) or not kayitlar:
        raise SinyalHatasi("'sinyaller' boş olmayan bir liste olmalı")
    tanimlar = tuple(_tanim(k, parcalar, i) for i, k in enumerate(kayitlar, 1))
    kimlikler = [t.id for t in tanimlar]
    if len(set(kimlikler)) != len(kimlikler):
        raise SinyalHatasi("yinelenen sinyal kimliği")
    return tanimlar


@lru_cache(maxsize=4)
def _yukle(yol: str) -> tuple[SinyalTanimi, ...]:
    try:
        veri = yaml.safe_load(Path(yol).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SinyalHatasi(f"sinyaller.yaml okunamadı ({type(exc).__name__})") from exc
    return tanimlari_ayristir(veri)


def sinyal_dosyasi(rules_dir: Path | None = None) -> Path:
    from tp_core.gateway.config import find_rules_dir

    return find_rules_dir(rules_dir) / "assistant" / SINYAL_DOSYASI


def sinyaller_yukle(rules_dir: Path | None = None) -> tuple[SinyalTanimi, ...]:
    """Önbellekli (dosya yolu başına); geçersiz dosya `SinyalHatasi` yükseltir."""
    return _yukle(str(sinyal_dosyasi(rules_dir)))


# ------------------------------------------------------------------ sinyaller


def _eslesenler(metinler: Iterable[str], yon: str, rules_dir: Path | None) -> list[Sinyal]:
    katlilar = [k for k in (katla(m) for m in metinler) if k]
    if not katlilar:
        return []
    return [
        t.sinyal
        for t in sinyaller_yukle(rules_dir)
        if t.yon == yon and any(t.eslesir(k) for k in katlilar)
    ]


def girdi_sinyalleri(metin: str, *, rules_dir: Path | None = None) -> list[Sinyal]:
    """Sorudaki niyet sinyalleri (dosya sırasıyla, tekil). Rol bağımsızdır (tüm rollerde)."""
    return _eslesenler([metin or ""], "girdi", rules_dir)


def _dizgeler(deger: Any) -> Iterator[str]:
    if isinstance(deger, str):
        yield deger
    elif isinstance(deger, Mapping):
        for v in deger.values():
            yield from _dizgeler(v)
    elif isinstance(deger, list | tuple):
        for v in deger:
            yield from _dizgeler(v)


def gorunur_metinler(cevap: Mapping[str, Any]) -> list[str]:
    """Kullanıcının gördüğü cevap metni: bloklar (kod blokları dahil) metin + maddeler, öneri
    başlık/neden/eylem (taslak) metinleri. Her parça ayrı taranır (desen bloklar arası atlamaz)."""
    out: list[str] = []
    for blok in cevap.get("cevap_bloklari") or []:
        if isinstance(blok, Mapping):
            out.append(str(blok.get("metin") or ""))
            out += [str(m) for m in blok.get("maddeler") or []]
    for oneri in cevap.get("oneriler") or []:
        if isinstance(oneri, Mapping):
            out += [str(oneri.get("baslik") or ""), str(oneri.get("neden") or "")]
            out += list(_dizgeler(oneri.get("eylem")))
    return [m for m in out if m]


def cikti_sinyalleri(cevap: Mapping[str, Any], *, rules_dir: Path | None = None) -> list[Sinyal]:
    """Saklanacak cevabın görünür metnindeki çıktı sinyalleri (dosya sırasıyla, tekil)."""
    return _eslesenler(gorunur_metinler(cevap), "cikti", rules_dir)


# ------------------------------------------------------------------ kart (kesin)

# Herkese açık ödeme sağlayıcı test kartları (belgelerde, demo verisinde geçer): 422 almaz.
TEST_KARTLARI: Final = frozenset(
    {
        "4111111111111111",
        "5555555555554444",
        "4242424242424242",
        "5528790000000008",
        "4000056655665556",
    }
)
# Ayraçlı rakam grupları dizisi: ayraç tek boşluk, tire ya da nokta. Dizinin iki yanında harf/
# rakam/alt çizgi olmaz (hex özetler, kimlikler); ondalık/sürüm parçası da değildir. Kart, dizinin
# ardışık gruplarından oluşur ("toplam 3 5105 1051 …" gibi önüne sayı gelmiş kart da bulunur).
_KART_ADAYI: Final = re.compile(r"(?<![\w.,-])[0-9]+(?:[ .-][0-9]+)*(?![\w-]|[.,][0-9])")
# Bilinen kart ağlarının IIN önekleri (Visa, Mastercard 51–55 / 2221–2720, Amex, Diners, JCB,
# Discover/UnionPay, Troy). Zaman damgası (`17…` ms) ve benzeri sayılar elenir.
_KART_ONEKI: Final = re.compile(r"(?:4|5[1-5]|2[2-7]|3[47]|3[0689]|35|6|9792)")
# URL (şemalı), yol parçası (`/…/123`) ve sorgu dizesi (`?id=…&x=…`) taranmaz.
_URL_PARCASI: Final = re.compile(
    r"\b[a-z][a-z0-9+.-]*://\S+|\S*/\S*|[?&][^\s=&]+=[^\s&#]*", re.IGNORECASE
)
# IBAN rakam grupları kart sanılmasın (mod-97 ayrıca maskelemede).
_IBAN_PARCASI: Final = re.compile(r"\bTR\d{2}(?:[ ]?\d){22}\b", re.IGNORECASE)


def luhn_gecerli(rakamlar: str) -> bool:
    toplam = 0
    for i, c in enumerate(reversed(rakamlar)):
        n = int(c)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        toplam += n
    return toplam % 10 == 0


def kart_bul(metin: str) -> bool:
    """Metinde (URL/yol/sorgu dizesi dışında) Luhn'u tutan, bilinen bir kart ağı önekiyle
    başlayan 13–19 haneli, herkese açık test kartı olmayan bir numara var mı."""
    if not metin:
        return False
    temiz = _URL_PARCASI.sub(" ", _IBAN_PARCASI.sub(" ", metin))
    for m in _KART_ADAYI.finditer(temiz):
        gruplar = re.split(r"[ .-]", m.group(0))
        for bas in range(len(gruplar)):
            for son in range(bas + 1, len(gruplar) + 1):
                rakamlar = "".join(gruplar[bas:son])
                if len(rakamlar) > 19:
                    break
                if _kart_mi(rakamlar):
                    return True
    return False


def _kart_mi(rakamlar: str) -> bool:
    return (
        13 <= len(rakamlar) <= 19
        and _KART_ONEKI.match(rakamlar) is not None
        and rakamlar not in TEST_KARTLARI
        and luhn_gecerli(rakamlar)
    )
