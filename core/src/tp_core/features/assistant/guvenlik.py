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

import os
import re
import threading
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from tp_core.features.assistant.siniflandir import normalize

SINYAL_DOSYASI: Final = "sinyaller.yaml"
YONLER: Final = ("girdi", "cikti")
_KAYIT_ALANLARI: Final = frozenset({"id", "yon", "regex", "istisna_regex", "ipucu", "not"})
_UST_ALANLAR: Final = frozenset({"surum", "parcalar", "cikti_olumsuz", "sinyaller"})
_OLUMSUZ_ALANLARI: Final = frozenset({"sinyaller", "kuyruk", "ek"})
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
class Olumsuzluk:
    """Çıktı sinyallerinde olumsuz kip/alıntı istisnası (`sinyaller.yaml` `cikti_olumsuz`)."""

    sinyaller: frozenset[str]
    kuyruk: re.Pattern[str]
    ek: re.Pattern[str]

    def olumsuz_mu(self, katli: str, m: re.Match[str]) -> bool:
        """Eşleşme olumsuzlanmış ya da tırnak içinde alıntılanmış mı (YAML belgesi)."""
        cumle_sonu = _CUMLE_SONU.search(katli, m.end(), m.end() + _KUYRUK_EN_COK)
        kuyruk = katli[m.end() : cumle_sonu.start() if cumle_sonu else m.end() + _KUYRUK_EN_COK]
        son_sozcuk = _SON_SOZCUK.search(katli, m.start(), m.end())
        metin = (son_sozcuk.group(0) if son_sozcuk else "") + kuyruk
        if self.kuyruk.search(metin) or self.ek.search(metin):
            return True
        bas = max((katli.rfind(c, 0, m.start()) for c in ".;!?\n"), default=-1) + 1
        return bool(_ACIK_ALINTI.search(katli[bas : m.start()]) and _KAPANAN_ALINTI.search(kuyruk))


_CUMLE_SONU: Final = re.compile(r"[.;!?\n]")
_KUYRUK_EN_COK: Final = 60
_SON_SOZCUK: Final = re.compile(r"\w+\W*\Z")
_ACIK_ALINTI: Final = re.compile(r"(?:^|(?<=[\s(:]))['\"“«][^'\"”»]*\Z")
_KAPANAN_ALINTI: Final = re.compile(r"['\"”»]")


@dataclass(frozen=True)
class SinyalTanimi:
    id: str
    yon: Literal["girdi", "cikti"]
    desenler: tuple[re.Pattern[str], ...]
    istisnalar: tuple[re.Pattern[str], ...]
    ipucu: str
    not_: str | None
    olumsuzluk: Olumsuzluk | None = None

    @property
    def sinyal(self) -> Sinyal:
        return Sinyal(self.id, self.yon, self.ipucu, self.not_)

    def eslesir(self, katli: str) -> bool:
        """`katli`: `katla`'dan geçmiş metin. Çıktı sinyalinde olumsuzlanmış/alıntılanmış
        eşleşmeler sayılmaz (`Olumsuzluk`)."""
        if not katli or not any(self._olumlu_eslesme(d, katli) for d in self.desenler):
            return False
        return not any(i.search(katli) for i in self.istisnalar)

    def _olumlu_eslesme(self, desen: re.Pattern[str], katli: str) -> bool:
        if self.olumsuzluk is None:
            return desen.search(katli) is not None
        return any(not self.olumsuzluk.olumsuz_mu(katli, m) for m in desen.finditer(katli))


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


def _tanim(
    kayit: Any, parcalar: Mapping[str, str], sira: int, olumsuzluk: Olumsuzluk | None
) -> SinyalTanimi:
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
        olumsuzluk=olumsuzluk if olumsuzluk and kimlik in olumsuzluk.sinyaller else None,
    )


def _olumsuzluk(veri: Any, parcalar: Mapping[str, str]) -> Olumsuzluk | None:
    if veri is None:
        return None
    if (
        not isinstance(veri, Mapping)
        or set(veri) != _OLUMSUZ_ALANLARI
        or not all(isinstance(veri[a], str) and veri[a] for a in ("kuyruk", "ek"))
    ):
        raise SinyalHatasi(
            "'cikti_olumsuz': 'sinyaller' listesi, 'kuyruk' ve 'ek' desenleri gerekli"
        )
    return Olumsuzluk(
        sinyaller=frozenset(_liste(veri["sinyaller"], "sinyaller", "cikti_olumsuz")),
        kuyruk=_derle(veri["kuyruk"], parcalar, "cikti_olumsuz"),
        ek=_derle(veri["ek"], parcalar, "cikti_olumsuz"),
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
    olumsuzluk = _olumsuzluk(veri.get("cikti_olumsuz"), parcalar)
    tanimlar = tuple(_tanim(k, parcalar, i, olumsuzluk) for i, k in enumerate(kayitlar, 1))
    kimlikler = [t.id for t in tanimlar]
    if len(set(kimlikler)) != len(kimlikler):
        raise SinyalHatasi("yinelenen sinyal kimliği")
    cikti_kimlikleri = {t.id for t in tanimlar if t.yon == "cikti"}
    if olumsuzluk and not olumsuzluk.sinyaller <= cikti_kimlikleri:
        raise SinyalHatasi("cikti_olumsuz: 'sinyaller' yalnız çıktı sinyali kimlikleri içermeli")
    return tanimlar


def _ayristir_dosya(yol: str) -> tuple[SinyalTanimi, ...]:
    try:
        veri = yaml.safe_load(Path(yol).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SinyalHatasi(f"sinyaller.yaml okunamadı ({type(exc).__name__})") from exc
    return tanimlari_ayristir(veri)


# Önbellek: yol → (dosya imzası, tanımlar ya da hata). Hata da önbelleğe alınır: bozuk dosya her
# mesajda yeniden okunup ayrıştırılmaz; dosya değişince (mtime/boyut) yeniden denenir.
_ONBELLEK: dict[str, tuple[tuple[int, int] | None, tuple[SinyalTanimi, ...] | SinyalHatasi]] = {}
_ONBELLEK_KILIDI: Final = threading.Lock()
_ONBELLEK_EN_COK: Final = 8


def _imza(yol: str) -> tuple[int, int] | None:
    try:
        st = os.stat(yol)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _yukle(yol: str) -> tuple[SinyalTanimi, ...]:
    imza = _imza(yol)
    with _ONBELLEK_KILIDI:
        kayit = _ONBELLEK.get(yol)
    if kayit is None or kayit[0] != imza:
        try:
            sonuc: tuple[SinyalTanimi, ...] | SinyalHatasi = _ayristir_dosya(yol)
        except SinyalHatasi as exc:
            sonuc = exc
        with _ONBELLEK_KILIDI:
            if len(_ONBELLEK) >= _ONBELLEK_EN_COK and yol not in _ONBELLEK:
                _ONBELLEK.pop(next(iter(_ONBELLEK)))
            _ONBELLEK[yol] = kayit = (imza, sonuc)
    if isinstance(kayit[1], SinyalHatasi):
        raise SinyalHatasi(*kayit[1].args)
    return kayit[1]


def sinyal_dosyasi(rules_dir: Path | None = None) -> Path:
    from tp_core.gateway.config import find_rules_dir

    return find_rules_dir(rules_dir) / "assistant" / SINYAL_DOSYASI


def sinyaller_yukle(rules_dir: Path | None = None) -> tuple[SinyalTanimi, ...]:
    """Önbellekli (dosya yolu ve imzası başına; hata da önbellekte); geçersiz dosya
    `SinyalHatasi` yükseltir."""
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
    """Çıktı SİNYALİ için taranan görünür metin: bloklar (kod blokları dahil) metin + maddeler,
    öneri başlık/neden/eylem (taslak) metinleri. Her parça ayrı taranır (desen bloklar arası
    atlamaz).

    Notlar ve kaynaklar bilerek hariç: notlar sunucunun eklediği sabit metinlerdir (sinyal notları
    dahil; kendi notunu yeniden işaretlemesin), kaynak alıntıları kayıtlardan birebir gelir ve
    asistanın iddiası değildir. Sızıntı (kanarya/iz) taraması bu listeyi değil, cevabın bütün
    dizgelerini kullanır (`guvenlik_cikti.gorunur_dizgeler`)."""
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
# `5105105105105100` (Mastercard belge örneği) bilerek listede YOK: §9 kabul vakasında müşteri
# kartı gibi verilmiş bir numaradır ("Müşterinin kartı 5105.1051.0510.5100") ve engellenmelidir;
# kullanıcı kartı yazarken hangi numarayı seçtiğini bilemeyiz, test kartı listesi yalnız ödeme
# sağlayıcı test ortamı belgelerindeki tipik kartlardır.
TEST_KARTLARI: Final = frozenset(
    {
        "4111111111111111",
        "5555555555554444",
        "4242424242424242",
        "5528790000000008",
        "4000056655665556",
        "4012888888881881",
        "378282246310005",
        "371449635398431",
        "6011111111111117",
    }
)
# Görünmez karakterler (rakamların arasına konup dedektörü atlatmasın) silinir; tire benzerleri
# (en/em dash, eksi) tireye çevrilir. Tam genişlik rakamlar NFKC ile, diğer yazı sistemlerinin
# ondalık rakamları (Arapça-Hint ٥١٠٥…) `unicodedata.decimal` ile ASCII olur.
_GORUNMEZ: Final = str.maketrans(
    {
        "​": None,
        "‌": None,
        "‍": None,
        "⁠": None,
        "﻿": None,
        "­": None,
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)
# Rakam grupları arası ayraç: boşluk/sekme/satır sonu (en çok 3), ya da `.` `-` `_` `/` `,` `*`
# `|` (yanında boşluk olabilir). `,` `*` `|` kart yazımında olağan değildir (tablo satırı, sayı
# listesi): bu ayraçlarla yazılmış kart yalnız yakınında kart kelimesi varken sayılır (`_ZAYIF`).
_AYRAC: Final = r"(?:[ \t]*[.\-_/,*|][ \t]*|\s{1,3})"
_ZAYIF_AYRAC: Final = re.compile(r"[,*|]")
# Ayraçlı rakam grupları dizisi. Sol sınır yalnız rakam (ve ondalık parçası `3.5…`): harfe bitişik
# kart (`kart5105…`) da bulunur. Kart, dizinin ardışık gruplarından oluşur ("toplam 3 5105 1051 …"
# gibi önüne sayı gelmiş kart da bulunur; `_kart_gruplari`).
_KART_ADAYI: Final = re.compile(rf"(?<!\d)(?<!\d[.,])[0-9]+(?:{_AYRAC}[0-9]+)*")
_AYRAC_BOL: Final = re.compile(f"({_AYRAC})")
# Bilinen kart ağlarının IIN önekleri (Visa, Mastercard 51–55 / 2221–2720, Amex, Diners, JCB,
# Discover/UnionPay, Troy). Zaman damgası (`17…` ms) ve benzeri sayılar elenir.
_KART_ONEKI: Final = re.compile(r"(?:4|5[1-5]|2[2-7]|3[47]|3[0689]|35|6|9792)")
# Taranmayan parçalar:
# - şemalı URL (`https://…`, tırnak/boşlukta biter: JSON alanı komşu alanı yutmaz);
# - harf içeren yol (`/siparis/5105…/detay`, `rapor?no=…&x=1`): yolda iki harflik bir sözcük
#   yoksa (`5105…/12/27`, `5105/1051/…`, `a/5105…`) yol sayılmaz, rakamlar taranır. Sorgu dizesi
#   yalnız bir yolun ardındaki `?` ile başlar (çıplak `&k=5105…` taranır).
# İstisna (`_ODEME_PARCASI`): sorgu anahtarı ya da yol parçası kart/ödeme adı olan URL ve yol
# (`?kart=5105…`, `?pan=…`, `/odeme/5105…`, `/payment/…`) boşaltılmaz, taranır.
_URL: Final = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>`]+", re.IGNORECASE)
_YOL: Final = re.compile(
    r"(?<![\w.~%/-])(?P<yol>[\w.~%-]*(?:/[\w.~%-]*)+|[\w.~%-]+(?=\?))(?:\?[^\s\"'<>`#]*)?"
)
_SOZCUK: Final = re.compile(r"[^\W\d_]{2}")
_ODEME_PARCASI: Final = re.compile(
    r"(?:^|[/?&;#.])(?:kart\w*|card\w*|kredi\w*|pan|cc|ccnum|cvv|odeme\w*|payment\w*|pay|pos"
    r"|checkout|tahsilat)(?=$|[/?&;#=.])"
)
# Rakam grupları kart sanılmasın: IBAN (mod-97 maskelemede; boşluk/tire ayraçlı, çift boşluk
# dahil), UUID ve uzun onaltılık özetler (commit, kimlik). Onaltılık parça içinde 13+ ardışık
# rakam varsa boşaltılmaz (`kart: ab5105105105105100cd` atlatması): harfe bitişik kalan aday
# yalnız kart kelimesiyle sayılır (`_harfe_bitisik`); SHA gibi özetlerin yakınında kart kelimesi
# olmaz.
_IBAN_PARCASI: Final = re.compile(r"\bTR\d{2}(?:[ \-]{0,2}\d){22}(?!\d)", re.IGNORECASE)
_UUID: Final = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
_HEX: Final = re.compile(r"(?<![0-9a-z])(?=[0-9a-f]*[a-f])[0-9a-f]{20,}(?![0-9a-z])", re.IGNORECASE)
_UZUN_RAKAM: Final = re.compile(r"\d{13,}")
# Kart kelimesi (katlanmış metinde aranır): kart/kredi/pan, kart ağları, güvenlik kodu, son
# kullanma tarihi. Soru metninde ödeme bağlamı da kart kelimesi sayılır (`_ODEME_KELIMESI`):
# "5105 1051 0510 5100 ile ödeme denedi". Bağlam (ekran JSON'u) kipinde sayılmaz: ödeme
# ekranındaki sipariş/işlem numaraları da kart sanılırdı.
_KART_KELIMESI: Final = re.compile(
    r"kart|card|kredi|(?<![a-z])(?:pan|visa|amex|troy|maestro|cvv|cvc|cv2|skt)(?![a-z])"
    r"|master ?card|american express|son kullanma|expir"
)
_ODEME_KELIMESI: Final = re.compile(r"odeme|payment|tahsilat|provizyon|(?<![a-z])pos(?![a-z])")
# Soru metninde negatif bağlam: numaranın hemen yakınında bir kimlik adı varsa (ve kart kelimesi
# yoksa) numara kimliktir ("Sipariş numarası 4532… olan senaryo", `"amount": 4532…`). Rastgele 16
# haneli bir kimliğin Luhn + IIN süzgecini tutma olasılığı ~%4'tür; bu kimlikler soruyu 422 ile
# reddettirmesin (K2: kesin dedektör masum metinde ~0 yanlış pozitif).
_KIMLIK_KELIMESI: Final = re.compile(
    r"siparis|order|fatura|invoice|kayit|kayd|record|numara|number|barkod|barcode|timestamp"
    r"|zaman damga|amount|tutar|referans|takip|tracking|commit|serial|ticket|kosu"
    r"|(?<![a-z])(?:ids?|no|nr|ts|ref|sha|hash|seri|sku|build|run|msg|mesaj)(?![a-z])"
)
_KELIME_ONCE: Final = 60
_KELIME_SONRA: Final = 20
_KIMLIK_ONCE: Final = 40
_KIMLIK_SONRA: Final = 20
# Adayın solunda bitişik harf (en çok bir birleştirici ile: `TPD-4532…`, `ID:4532…`, `v1.2.3-…`)
# ya da sağında harf/`@` (`4532…abc`, `<4532…@mail…>`) varsa numara bir kimliğin parçasıdır.
_SOL_BITISIK: Final = re.compile(r"[^\W\d_][-_.:#/]?\Z")
_SAG_BITISIK: Final = re.compile(r"[^\W\d_]|@")


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


def _bosluk(m: re.Match[str]) -> str:
    return " " * len(m.group(0))


def _odeme_parcali(metin: str) -> bool:
    return _ODEME_PARCASI.search(katla(metin)) is not None


def _url_sil(m: re.Match[str]) -> str:
    return m.group(0) if _odeme_parcali(m.group(0)) else _bosluk(m)


def _yol_sil(m: re.Match[str]) -> str:
    if not _SOZCUK.search(m.group("yol")) or _odeme_parcali(m.group(0)):
        return m.group(0)
    return _bosluk(m)


def _hex_sil(m: re.Match[str]) -> str:
    return m.group(0) if _UZUN_RAKAM.search(m.group(0)) else _bosluk(m)


def _ascii_rakam(c: str) -> str:
    if c.isascii() or not c.isdecimal():
        return c
    return str(unicodedata.decimal(c))


def _kart_metni(metin: str) -> str:
    """Taranacak metin: NFKC + görünmez karakter/tire benzeri temizliği + ASCII rakam, taranmayan
    parçalar boşluk (konumlar korunur; kelime pencereleri aynı metinde aranır)."""
    temiz = unicodedata.normalize("NFKC", metin).translate(_GORUNMEZ)
    temiz = "".join(_ascii_rakam(c) for c in temiz)
    temiz = _URL.sub(_url_sil, temiz)
    for desen in (_IBAN_PARCASI, _UUID):
        temiz = desen.sub(_bosluk, temiz)
    temiz = _HEX.sub(_hex_sil, temiz)
    return _YOL.sub(_yol_sil, temiz)


def kart_bul(metin: str, *, baglam: bool = False) -> bool:
    """Metinde (URL/yol/sorgu dizesi dışında) Luhn'u tutan, bilinen bir kart ağı önekiyle
    başlayan 13–19 haneli, herkese açık test kartı olmayan bir numara var mı.

    Yakınında (önce 60, sonra 20 karakter) kart kelimesi (`_KART_KELIMESI`; soru metninde ödeme
    kelimeleri de) olan numara her zaman karttır. Kelime yoksa:

    - `baglam=True` (ekran bağlamı JSON'u): kart sayılmaz.
    - Soru metni: yalnız 16–19 haneli, olağan ayraçlı (boşluk `.` `-` `_` `/`), harfe bitişik
      olmayan ve yakınında (önce 40, sonra 20 karakter) kimlik adı (sipariş, order, id, no,
      amount…) geçmeyen numara karttır. 13–15 hane kelimesiz sayılmaz (ms zaman damgası, kayıt
      numarası)."""
    if not metin:
        return False
    temiz = _kart_metni(metin)
    for m in _KART_ADAYI.finditer(temiz):
        parcalar = _AYRAC_BOL.split(m.group(0))
        adaylar = _kart_gruplari(parcalar[0::2], parcalar[1::2])
        if not adaylar:
            continue
        pencere = katla(temiz[max(0, m.start() - _KELIME_ONCE) : m.end() + _KELIME_SONRA])
        if _KART_KELIMESI.search(pencere) or (not baglam and _ODEME_KELIMESI.search(pencere)):
            return True
        if baglam or _harfe_bitisik(temiz, m):
            continue
        yakin = katla(temiz[max(0, m.start() - _KIMLIK_ONCE) : m.end() + _KIMLIK_SONRA])
        if _KIMLIK_KELIMESI.search(yakin):
            continue
        if any(len(rakamlar) >= 16 and not zayif for rakamlar, zayif in adaylar):
            return True
    return False


def _harfe_bitisik(temiz: str, m: re.Match[str]) -> bool:
    return bool(
        _SOL_BITISIK.search(temiz[max(0, m.start() - 2) : m.start()])
        or _SAG_BITISIK.match(temiz, m.end())
    )


def _kart_gruplari(gruplar: list[str], ayraclar: list[str]) -> list[tuple[str, bool]]:
    """Ardışık gruplardan kart olanlar: (rakamlar, olağan dışı ayraçlı mı). Tek grup 13–19 hane
    olabilir; birden çok grup kart yazımına uymalı: ilk grup 4 hane, aradakiler 4–6, sonuncu 1–7
    (4-4-4-4, 4-6-5, 4-4-4-1…). Böylece satır satır sayı listeleri ya da tarihler birleşip kart
    sanılmaz."""
    out: list[tuple[str, bool]] = []
    for bas in range(len(gruplar)):
        if _kart_mi(gruplar[bas]):
            out.append((gruplar[bas], False))
        if len(gruplar[bas]) != 4:
            continue
        rakamlar = gruplar[bas]
        zayif = False
        for son in range(bas + 1, len(gruplar)):
            g = gruplar[son]
            if not 1 <= len(g) <= 7:
                break
            rakamlar += g
            zayif = zayif or _ZAYIF_AYRAC.search(ayraclar[son - 1]) is not None
            if len(rakamlar) > 19:
                break
            if _kart_mi(rakamlar):
                out.append((rakamlar, zayif))
            if not 4 <= len(g) <= 6:
                break
    return out


def _kart_mi(rakamlar: str) -> bool:
    return (
        13 <= len(rakamlar) <= 19
        and _KART_ONEKI.match(rakamlar) is not None
        and rakamlar not in TEST_KARTLARI
        and luhn_gecerli(rakamlar)
    )
