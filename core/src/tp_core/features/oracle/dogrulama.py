"""Olgu doğrulama ve tablo karşılaştırması — LLM'siz, saf (012 ANALIZ §4.3 adım 3–4).

Modelin çıkardığı her olgu (`{column, value, field, quote}`) şu kurallarla doğrulanır; tutmayan
olgu atılır (`atilan_olgular` sayılır), asla düzeltilmez:

1. `field` case içinde bir metin alanının yoludur: `title`, `expected_result`,
   `preconditions[i]`, `steps[i].action | .data | .expected` (`i` 0 tabanlı JSON dizinidir) ve
   v3 içeriğinde `test_data[i].value`, `verification_point`, `teardown` (V12).
2. `quote` boş olamaz ve o alanda **birebir** geçmelidir; geçtiği yerin önünde harf/rakam (ya da
   rakama bitişik `.`/`,`; sayı alıntısında işaret), arkasında harf/rakam olmamalıdır (`"7"`,
   `"P-001 × 17"` içinde; `"25,00 TL"`, `"125,00 TL"` ya da `"−25,00 TL"` içinde geçmiş sayılmaz).
3. `column` grubun tablosunda tanımlı olmalı: `inputs` yalnız girdi, `expected` yalnız çıktı kolonu.
4. Değer türü kolon türüne göre denetlenir:
   - `sayi`: `sayi_ayristir(quote)` bir sayı vermeli ve `value`'ya (sayı ya da `"150.00"` /
     `"150,00 TL"` gibi sayı metni) **tam** eşit olmalı (tolerans yok).
   - `metin`: `value` metin olmalı; alıntı (baştaki/sondaki tırnak işaretleri atılarak) NFC +
     boşluk daraltma sonrası `value`'ya birebir eşit olmalı.
   - `mantiksal`: `value` JSON boolean olmalı. Alıntının kutbu olumsuzluk işaretlerinden okunur:
     hiç yoksa `true`, tam bir tane varsa `false`; iki ve fazlası (çifte olumsuzluk) belirsizdir
     ve olgu atılır. İşaretler `OLUMSUZ_SOZCUKLER` (ek olarak yalnız ek-fiil `-dır/-dir/-tır…`
     kabul edilir), olumsuz kip ekleri (`-maz/-mez`, `-mıyor…`, `-mamalı/-memeli`,
     `-mayacak/-meyecek`, `-madı/-medi`, `-mamış/-memiş`; en az 5 harfli sözcükte) ya da anlamca
     olumsuz kökler (`kaybol`, `gizlen`) taşıyan sözcüklerdir. Çift tırnaklı arayüz metni sayılmaz
     (`"Sipariş verilemez" uyarısı görünür` → true). Kutup ayrıca alıntıyı içeren **cümlecikten**
     okunur ve alıntınınkiyle aynı olmalıdır (review 1 K4): alıntı olumsuzluğu dışarıda bırakacak
     biçimde kırpılamaz (`"…" uyarısı görünmez` alanında `"…" uyarısı` → atılır). Cümlecik
     sınırları: noktalama (rakam arası `,`/`.` ve tırnak içi hariç), bağlaçlar (`ve`, `veya`,
     `ya da`, `ama`, `fakat`, `ancak`) ve yan cümle bitiren sözcükler (`olsa`, `ise`, `iken`,
     `-ken`, `-dığında`, `-ınca`). Sınırlı bir sezgiseldir; tam Türkçe çözümleme değildir.

Grup değerlendirmesi: grubun tablosu bilinmiyorsa grup atılır (olguları atılmış sayılır). Aynı
girdi kolonu için farklı değerli iki doğrulanmış olgu `cikarilamadi` (çelişkili girdi) olur.
Tablo `kismi_degerlendir` ile hesaplanır: case'te bulunmayan bir girdi yalnız onu kullanan
koşulları ve çıktıları etkiler (satırlar sırayla denenir; karar verilemeyen ilk koşulda durulur,
yani seçilen satır tam değerlendirmeyle aynıdır). Seçilen satırın eksik girdiye dayanan
çıktıları karşılaştırılmaz; o çıktıların doğrulanmış beklenen olguları `karsilastirilamayan`
listesine (neden ile) yazılır — sonuç onlardan etkilenmez, metamorfik türetme onları da okur.
Satır seçilemiyorsa `cikarilamadi`, hata varsa `hata`, satır bulunmazsa `satir_yok` olur;
karşılaştırılabilir beklenen olgusu kalmayan grup `karsilastirma_yok` (hiç beklenen yoksa) ya da
`cikarilamadi` (yalnız hesaplanamayan çıktılar varsa) olur. Her karşılaştırılan beklenen olgu
`ifade.esit_mi(case_degeri, tablo_degeri, kolon toleransı)` ile karşılaştırılır.

Tamlık denetimi (review 1, bağımsızlık O1 / güvenlik 3): beklenen alanlardaki
(`steps[i].expected`, `expected_result`, `verification_point`) her sayı, aynı alandaki doğrulanmış
bir olgunun ya da modelin `ignored[]` ile "hiçbir kolona ait değil" dediği alıntının içinde
olmalıdır; kapsanmayan sayı `kapsanmayan_sayilar`'a yazılır ve karşılaştırılmamış sayılır.
Model yanlış değeri hiç çıkarmayarak karşılaştırmadan kaçıramaz (`ignored` ise görünür kalır).
Yalnız sayılar denetlenir; mantıksal yüklemlerin tamlığı denetlenmez.

Genel sonuç: herhangi bir karşılaştırma tutmuyorsa `uyumsuz`; değilse en az bir karşılaştırma
varsa ve kontrol eksiksizse `uyumlu`, eksikse `kismen` (K11: değerlendirilemeyen grup ya da hiç
grubu olmayan kapsayan tablo, atılan olgu, karşılaştırılamayan değer ya da kapsanmayan sayı); hiç
kapsayan tablo yoksa `kapsam_disi`; kapsayan tablo var ama karşılaştırma yoksa
`kontrol_edilemedi`. `ayrintilar.degerler` değer düzeyinde sayımdır: `{uyumlu, uyumsuz,
karsilastirilamayan, atilan, kapsanmayan}`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from tp_core.features.karar_tablosu import ifade

UYUMLU = "uyumlu"
UYUMSUZ = "uyumsuz"
KAPSAM_DISI = "kapsam_disi"
KONTROL_EDILEMEDI = "kontrol_edilemedi"
KISMEN = "kismen"

# Grup durumları (`ayrintilar.gruplar[].durum`).
G_UYUMLU = "uyumlu"
G_UYUMSUZ = "uyumsuz"
G_CIKARILAMADI = "cikarilamadi"
G_SATIR_YOK = "satir_yok"
G_HATA = "hata"
G_KARSILASTIRMA_YOK = "karsilastirma_yok"

_ALAN_DESENI = re.compile(
    r"^(?:(?P<kok>title|expected_result|verification_point|teardown)"
    r"|preconditions\[(?P<on>\d{1,3})\]"
    r"|test_data\[(?P<veri>\d{1,3})\]\.value"
    r"|steps\[(?P<adim>\d{1,3})\]\.(?P<adim_alan>action|data|expected))$"
)
# Tamlık denetiminin taradığı "beklenen" alanlar (sayı içeren her geçiş bir olguyla ya da açıkça
# `ignored` ile kapsanmalı).
_BEKLENEN_ALAN = re.compile(r"^(?:expected_result|verification_point|steps\[\d{1,3}\]\.expected)$")
_WS = re.compile(r"\s+")
_TIRNAK = "\"'“”‘’«»„"

OLUMSUZ_SOZCUKLER = frozenset(
    {
        "yok",
        "değil",
        "pasif",
        "hayır",
        "yanlış",
        "kapalı",
        "false",
        "olmaz",
        "görünmez",
        "gösterilmez",
        "aranmaz",
        "verilmez",
        "uygulanmaz",
        "onaylanamaz",
        "edilemez",
        "yapılamaz",
    }
)
_EK_FIIL = ("", "dır", "dir", "dur", "dür", "tır", "tir", "tur", "tür")
_OLUMSUZ_EKLER = (
    "maz",
    "mez",
    "mıyor",
    "miyor",
    "muyor",
    "müyor",
    "mamalı",
    "memeli",
    "mayacak",
    "meyecek",
    "madı",
    "medi",
    "mamış",
    "memiş",
)
# Anlamca olumsuz (görünmeyi bitiren) fiil kökleri: "uyarı kaybolur" → false.
OLUMSUZ_KOKLER = ("kaybol", "gizlen")
_LITERAL = re.compile(r'"[^"]*"|“[^”]*”')
_SOZCUK = re.compile(r"[^\W\d_]+")
_NOKTALAMA = ".;:!?,()"
_BAGLAC = frozenset({"ve", "veya", "ama", "fakat", "ancak"})
_YAN_CUMLE = frozenset({"olsa", "ise", "iken"})
_YAN_CUMLE_EKLERI = (
    "dığında",
    "diğinde",
    "duğunda",
    "düğünde",
    "tığında",
    "tiğinde",
    "tuğunda",
    "tüğünde",
)
_ZARF_EKLERI = ("ınca", "ince", "unca", "ünce")


def norm(metin: str) -> str:
    """NFC + boşluk daraltma + baş/son boşluk yok (metin karşılaştırması ve alıntı araması)."""
    return _WS.sub(" ", unicodedata.normalize("NFC", metin)).strip()


def alan_coz(icerik: Mapping[str, Any], yol: Any) -> str | None:
    """`field` yolunu case içeriğinde çözer; yol geçersizse ya da alan metin değilse `None`."""
    if not isinstance(yol, str):
        return None
    m = _ALAN_DESENI.match(yol.strip())
    if m is None:
        return None
    deger: Any
    if m.group("kok"):
        deger = icerik.get(m.group("kok"))
    elif m.group("on") is not None:
        liste = icerik.get("preconditions") or []
        i = int(m.group("on"))
        deger = liste[i] if isinstance(liste, list) and i < len(liste) else None
    elif m.group("veri") is not None:
        liste = icerik.get("test_data") or []
        i = int(m.group("veri"))
        oge = liste[i] if isinstance(liste, list) and i < len(liste) else None
        deger = oge.get("value") if isinstance(oge, Mapping) else None
        if isinstance(deger, int | float | Decimal) and not isinstance(deger, bool):
            deger = str(deger)
    else:
        liste = icerik.get("steps") or []
        i = int(m.group("adim"))
        adim = liste[i] if isinstance(liste, list) and i < len(liste) else None
        deger = adim.get(m.group("adim_alan")) if isinstance(adim, Mapping) else None
    return deger if isinstance(deger, str) else None


def _sinir_mi(metin: str, bas: int, son: int) -> bool:
    once = metin[bas - 1] if bas > 0 else ""
    sonra = metin[son] if son < len(metin) else ""
    if once and once.isalnum():
        return False
    # `""` her dizginin içindedir: alan başı/sonu ayrı denetlenir (birleştirme: alanın başındaki
    # sayı alıntısı — "7 adette …" — önceden "işaret düşmüş" sayılıp atılıyordu).
    if once and once in ".," and bas > 1 and metin[bas - 2].isdigit():
        return False
    if once and once in "+-−" and metin[bas : bas + 1].isdigit():  # işaret düşmüş: "−25,00"
        return False
    if sonra and sonra.isalnum():
        return False
    return not (sonra and sonra in ".," and son + 1 < len(metin) and metin[son + 1].isdigit())


def alinti_geciyor_mu(alan: str, alinti: str) -> bool:
    """Alıntı alanda birebir (NFC) ve sözcük sınırında geçiyor mu (kural 2)."""
    return bool(_gecisler(alan, alinti))


def _olumsuz_mu(sozcuk: str) -> bool:
    for kok in OLUMSUZ_SOZCUKLER:
        if sozcuk.startswith(kok) and sozcuk[len(kok) :] in _EK_FIIL:
            return True
    if sozcuk.startswith(OLUMSUZ_KOKLER):
        return True
    return len(sozcuk) >= 5 and any(
        sozcuk.endswith(ek + ekf) for ek in _OLUMSUZ_EKLER for ekf in _EK_FIIL
    )


def _literal_maskesi(metin: str) -> list[bool]:
    """Çift tırnaklı arayüz metinlerinin (`"Sipariş verilemez"`) karakterleri: kutupta sayılmaz,
    içlerindeki noktalama cümlecik sınırı değildir."""
    maske = [False] * len(metin)
    for m in _LITERAL.finditer(metin):
        for i in range(m.start(), m.end()):
            maske[i] = True
    return maske


def _kutup_say(metin: str, bas: int, son: int, maske: Sequence[bool]) -> bool | None:
    n = 0
    for m in _SOZCUK.finditer(metin, bas, son):
        if maske[m.start()]:
            continue
        if _olumsuz_mu(m.group().casefold()):
            n += 1
    if n == 0:
        return True
    return False if n == 1 else None


def kutup(alinti: str) -> bool | None:
    """Alıntının mantıksal kutbu: olumsuzluk yok → True, bir tane → False, fazlası → None.
    Çift tırnaklı arayüz metinleri sayılmaz (`"Sipariş verilemez" uyarısı görünür` → True)."""
    metin = unicodedata.normalize("NFC", alinti)
    return _kutup_say(metin, 0, len(metin), _literal_maskesi(metin))


def _kesimler(metin: str, maske: Sequence[bool]) -> list[tuple[int, int]]:
    """Cümlecik sınırları `[(bas, son)]`: noktalama (rakamlar arasındaki `,`/`.` ve tırnak içi
    hariç), bağlaçlar (`ve`, `veya`, `ya da`, `ama`, `fakat`, `ancak`) ve yan cümle bitiren
    sözcüklerin ardı (`olsa`, `ise`, `iken`, `-ken`, `-dığında`, `-ınca`; sıfır genişlik)."""
    out: list[tuple[int, int]] = []
    for i, ch in enumerate(metin):
        if maske[i] or ch not in _NOKTALAMA:
            continue
        if (
            ch in ".,"
            and 0 < i < len(metin) - 1
            and metin[i - 1].isdigit()
            and metin[i + 1].isdigit()
        ):
            continue
        out.append((i, i + 1))
    sozcukler = [m for m in _SOZCUK.finditer(metin) if not maske[m.start()]]
    for j, m in enumerate(sozcukler):
        w = m.group().casefold()
        if w in _BAGLAC:
            out.append((m.start(), m.end()))
        elif w == "ya" and j + 1 < len(sozcukler) and sozcukler[j + 1].group().casefold() == "da":
            out.append((m.start(), sozcukler[j + 1].end()))
        elif (
            w in _YAN_CUMLE
            or (len(w) >= 5 and w.endswith("ken"))
            or w.endswith(_YAN_CUMLE_EKLERI)
            or (len(w) >= 6 and w.endswith(_ZARF_EKLERI))
        ):
            out.append((m.end(), m.end()))
    return out


def cumlecik(metin: str, bas: int, son: int) -> tuple[int, int]:
    """`metin[bas:son]` alıntısını içeren cümlecik (alıntı birden çok cümleciğe yayılıyorsa
    birleşimi)."""
    maske = _literal_maskesi(metin)
    c_bas, c_son = 0, len(metin)
    for a, b in _kesimler(metin, maske):
        if b <= bas:
            c_bas = max(c_bas, b)
        elif a >= son:
            c_son = min(c_son, a)
    return c_bas, c_son


def _gecisler(alan: str, alinti: str) -> list[tuple[int, int]]:
    """Alıntının alanda sözcük sınırında geçtiği yerler (NFC metin üzerinde)."""
    a, q = unicodedata.normalize("NFC", alan), unicodedata.normalize("NFC", alinti)
    out: list[tuple[int, int]] = []
    if not q.strip():
        return out
    bas = a.find(q)
    while bas >= 0:
        if _sinir_mi(a, bas, bas + len(q)):
            out.append((bas, bas + len(q)))
        bas = a.find(q, bas + 1)
    return out


def cumlecik_kutbu(alan: str, alinti: str) -> tuple[bool | None, str | None]:
    """Mantıksal olgunun kutbu, alıntının ve onu içeren cümleciğin kutbu birlikte okunarak
    (bağımsızlık K4). Alıntı kırpılarak olumsuzluk dışarıda bırakılamaz:
    `"… 750,00 TL" uyarısı görünmez` alanında `"… 750,00 TL" uyarısı` alıntısı reddedilir.
    Her geçiş aynı kutbu vermelidir. → (kutup, ret nedeni)."""
    metin = unicodedata.normalize("NFC", alan)
    gecisler = _gecisler(alan, alinti)
    if not gecisler:
        return None, "alıntı alanda geçmiyor"
    maske = _literal_maskesi(metin)
    sonuc: bool | None = None
    for i, (bas, son) in enumerate(gecisler):
        k_alinti = _kutup_say(metin, bas, son, maske)
        c_bas, c_son = cumlecik(metin, bas, son)
        k_cumle = _kutup_say(metin, c_bas, c_son, maske)
        if k_alinti is None or k_cumle is None:
            return None, "alıntının kutbu belirsiz"
        if k_alinti is not k_cumle:
            return None, "alıntının kutbu cümleciğinkinden farklı (olumsuzluk alıntı dışında)"
        if i and k_cumle is not sonuc:
            return None, "alıntının geçişleri farklı kutuplu"
        sonuc = k_cumle
    return sonuc, None


def deger_oku(tur: str, alinti: str, deger: Any) -> tuple[Any, str | None]:
    """Alıntıdan okunan değer ve beyan edilen `value` aynı mı (kural 4). (değer, ret nedeni)."""
    if tur == ifade.SAYI:
        sayi = ifade.sayi_ayristir(alinti)
        if sayi is None:
            return None, "alıntı tek bir sayı değil"
        if isinstance(deger, bool) or deger is None:
            return None, "değer sayı değil"
        try:
            beyan = ifade.girdi_donustur(deger, ifade.SAYI)
        except ifade.IfadeHatasi:
            return None, "değer sayı değil"
        if beyan != sayi:
            return None, "alıntıdaki sayı değere eşit değil"
        return sayi, None
    if tur == ifade.METIN:
        if not isinstance(deger, str):
            return None, "değer metin değil"
        if norm(alinti).strip(_TIRNAK).strip() != norm(deger):
            return None, "alıntı değere eşit değil"
        return norm(deger), None
    if tur == ifade.MANTIKSAL:
        if not isinstance(deger, bool):
            return None, "değer mantıksal değil"
        k = kutup(alinti)
        if k is None:
            return None, "alıntının kutbu belirsiz"
        if k is not deger:
            return None, "alıntının kutbu değere uymuyor"
        return deger, None
    return None, f"bilinmeyen kolon türü: {tur}"


def goster(deger: Any) -> Any:
    """JSON'a yazılan değer: sayılar metin (`"150.00"`), diğerleri olduğu gibi."""
    return str(deger) if isinstance(deger, Decimal) else deger


@dataclass(frozen=True)
class Tablo:
    """Değerlendirmede kullanılan tablo görünümü (DB'den bağımsız)."""

    id: str
    ref: str
    ad: str
    icerik: Mapping[str, Any]

    def kolon_turleri(self, alan: str) -> dict[str, str]:
        return {k["ad"]: k["tur"] for k in self.icerik.get(alan) or []}


@dataclass(frozen=True)
class KismiDegerlendirme:
    """`kismi_degerlendir` sonucu; `ifade.Degerlendirme`'ye ek olarak `hesaplanamayan`: seçilen
    satırda eksik girdiye dayandığı için hesaplanmayan çıktı → eksik girdiler."""

    satir_id: str | None = None
    ciktilar: dict[str, Any] = field(default_factory=dict)
    hesaplanamayan: dict[str, list[str]] = field(default_factory=dict)
    eksik_girdiler: list[str] = field(default_factory=list)
    hata: str | None = None


def kismi_degerlendir(icerik: Mapping[str, Any], girdiler: Mapping[str, Any]) -> KismiDegerlendirme:
    """Eksik girdiye dayanıklı değerlendirme (birleştirme, 012 §12).

    Tüm girdiler varsa `ifade.degerlendir` ile aynıdır. Eksik girdi varsa satırlar sırayla denenir:
    koşulu eksik bir girdiyi kullanan ilk satırda durulur (`eksik_girdiler` dolar; tam
    değerlendirme o satırı seçebilirdi). Koşulu sağlanan satırın eksik girdi kullanmayan çıktıları
    hesaplanır, kullananlar `hesaplanamayan`'a yazılır. Ör. TPD-1 T1: case birim fiyatı yazmıyorsa
    6 adette `bedava_adet` ve `indirim` (R2, sabit) yine de karşılaştırılır; 7 adette `bedava_adet`
    karşılaştırılır, `indirim` (birim fiyata dayanır) karşılaştırılamaz.
    """
    tam = ifade.degerlendir(dict(icerik), dict(girdiler))
    if not tam.eksik_girdiler:
        return KismiDegerlendirme(tam.satir_id, dict(tam.ciktilar), {}, [], tam.hata)
    eksik = set(tam.eksik_girdiler)
    ortam: dict[str, Any] = {}
    for kolon in icerik.get("girdiler") or []:
        ad = kolon["ad"]
        if girdiler.get(ad) is None:
            continue
        try:
            ortam[ad] = ifade.girdi_donustur(girdiler[ad], kolon["tur"])
        except ifade.IfadeHatasi as h:
            return KismiDegerlendirme(hata=f"girdi '{ad}': {h}")
    for satir in icerik.get("satirlar") or []:
        sid = satir["id"]
        gerekli = [a for a in ifade.adlar(satir["kosul"]) if a in eksik]
        if gerekli:
            return KismiDegerlendirme(eksik_girdiler=_sirali(icerik, gerekli))
        try:
            if ifade.hesapla(satir["kosul"], ortam) is not True:
                continue
        except ifade.IfadeHatasi as h:
            return KismiDegerlendirme(hata=f"satır {sid} koşul: {h}")
        ciktilar: dict[str, Any] = {}
        hesaplanamayan: dict[str, list[str]] = {}
        for kolon in icerik.get("ciktilar") or []:
            ad = kolon["ad"]
            metin = satir["cikti"][ad]
            gerekli = [a for a in ifade.adlar(metin) if a in eksik]
            if gerekli:
                hesaplanamayan[ad] = _sirali(icerik, gerekli)
                continue
            try:
                ciktilar[ad] = ifade.hesapla(metin, ortam)
            except ifade.IfadeHatasi as h:
                return KismiDegerlendirme(satir_id=sid, hata=f"satır {sid} çıktı '{ad}': {h}")
        return KismiDegerlendirme(sid, ciktilar, hesaplanamayan)
    return KismiDegerlendirme()


def _sirali(icerik: Mapping[str, Any], adlar: Sequence[str]) -> list[str]:
    """Adlar tablonun girdi tanım sırasıyla (`ifade.degerlendir.eksik_girdiler` ile aynı)."""
    sira = [k["ad"] for k in icerik.get("girdiler") or []]
    return [a for a in sira if a in adlar]


def _tablo_bul(tablolar: Sequence[Tablo], ref: Any) -> Tablo | None:
    r = str(ref or "").strip()
    return next((t for t in tablolar if r in (t.ref, t.id)), None)


def _olgu_dogrula(
    icerik: Mapping[str, Any], olgu: Any, turler: Mapping[str, str]
) -> dict[str, Any] | None:
    if not isinstance(olgu, Mapping):
        return None
    kolon, alinti = olgu.get("column"), olgu.get("quote")
    if not isinstance(kolon, str) or kolon not in turler or not isinstance(alinti, str):
        return None
    alan = alan_coz(icerik, olgu.get("field"))
    if alan is None or not alinti_geciyor_mu(alan, alinti):
        return None
    deger, neden = deger_oku(turler[kolon], alinti, olgu.get("value"))
    if neden is not None:
        return None
    if turler[kolon] == ifade.MANTIKSAL:
        k, neden = cumlecik_kutbu(alan, alinti)
        if neden is not None or k is not deger:
            return None
    return {"column": kolon, "value": deger, "field": str(olgu["field"]).strip(), "quote": alinti}


def _olgu_kaydi(o: Mapping[str, Any]) -> dict[str, Any]:
    return {**o, "value": goster(o["value"])}


_SAYI = re.compile(r"\d+(?:[.,]\d+)*")


def sayi_gecisleri(metin: str) -> list[tuple[int, int]]:
    """Tamlık denetiminin saydığı sayılar: harfe/rakama bitişik olmayan (`P-001`, `1L`, `330ml`,
    `Demo123` sayılmaz) her sayı geçişi `(bas, son)`."""
    out = []
    for m in _SAYI.finditer(metin):
        bas, son = m.start(), m.end()
        once = metin[bas - 1] if bas else ""
        if once and (once.isalnum() or once == "_"):
            continue
        if once in "-‐" and bas >= 2 and metin[bas - 2].isalnum():
            continue
        if son < len(metin) and metin[son].isalpha():
            continue
        out.append((bas, son))
    return out


def _yok_sayilan_dogrula(icerik: Mapping[str, Any], oge: Any) -> dict[str, Any] | None:
    """Modelin hiçbir kolona ait olmadığını söylediği sayı alıntısı (`ignored[]`): alan beklenen
    alan olmalı, alıntı orada sınırda geçmeli ve en az bir sayı içermeli."""
    if not isinstance(oge, Mapping):
        return None
    yol, alinti = oge.get("field"), oge.get("quote")
    if not isinstance(yol, str) or not isinstance(alinti, str):
        return None
    if not _BEKLENEN_ALAN.match(yol.strip()):
        return None
    alan = alan_coz(icerik, yol)
    if alan is None or not alinti_geciyor_mu(alan, alinti) or not sayi_gecisleri(alinti):
        return None
    neden = oge.get("reason")
    return {"alan": yol.strip(), "alinti": alinti, "neden": neden if isinstance(neden, str) else ""}


def _beklenen_alanlar(icerik: Mapping[str, Any]) -> list[str]:
    yollar = ["expected_result", "verification_point"]
    adimlar = icerik.get("steps") or []
    if isinstance(adimlar, list):
        yollar[1:1] = [f"steps[{i}].expected" for i in range(len(adimlar))]
    return yollar


def kapsanmayan_sayilar(
    icerik: Mapping[str, Any], alintilar: Sequence[tuple[str, str]]
) -> list[dict[str, str]]:
    """Tamlık denetimi (bağımsızlık O1, güvenlik 3): beklenen alanlardaki (`steps[i].expected`,
    `expected_result`, `verification_point`) her sayı, aynı alandaki doğrulanmış bir olgunun ya da
    `ignored` kaydının alıntısı içinde olmalı. Kapsanmayan sayı model tarafından atlanmış bir
    beklentidir; karşılaştırılmamış sayılır (`kismen` / `kontrol_edilemedi`).
    `alintilar`: `(alan yolu, alıntı)`."""
    alan_alintilari: dict[str, list[str]] = {}
    for yol, alinti in alintilar:
        alan_alintilari.setdefault(yol, []).append(alinti)
    out = []
    for yol in _beklenen_alanlar(icerik):
        alan = alan_coz(icerik, yol)
        if not alan:
            continue
        metin = unicodedata.normalize("NFC", alan)
        kapsam = [g for q in alan_alintilari.get(yol, []) for g in _gecisler(alan, q)]
        for bas, son in sayi_gecisleri(metin):
            if not any(a <= bas and son <= b for a, b in kapsam):
                out.append({"alan": yol, "alinti": metin[bas:son]})
    return out


_DEGERLENDIRILMEDI = frozenset({"cikarilamadi", "satir_yok", "hata"})


def degerlendir(
    icerik: Mapping[str, Any], tablolar: Sequence[Tablo], cikti: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """Model çıktısını doğrular ve tablolarla karşılaştırır → (sonuç, ayrıntılar).

    `tablolar` case'i kapsayan geçerli tablolardır (boşsa `kapsam_disi`, model çıktısına
    bakılmaz). `ayrintilar`: `{gruplar, atilan_olgular, degerler, kapsanmayan_sayilar,
    yok_sayilan, degerlendirilmeyen_tablolar}` (§4.3 + 013 §13.2).
    """
    if not tablolar:
        return KAPSAM_DISI, _ayrintilar([], 0, [], [], [])
    cikti = cikti if isinstance(cikti, Mapping) else {}
    atilan = 0
    gruplar: list[dict[str, Any]] = []
    alintilar: list[tuple[str, str]] = []
    gorulen: set[str] = set()
    for grup in cikti.get("groups") or []:
        if not isinstance(grup, Mapping):
            continue
        ham_girdi = [o for o in grup.get("inputs") or []]
        ham_beklenen = [o for o in grup.get("expected") or []]
        tablo = _tablo_bul(tablolar, grup.get("table_ref"))
        if tablo is None:
            atilan += len(ham_girdi) + len(ham_beklenen)
            continue
        gorulen.add(tablo.id)
        g_tur, c_tur = tablo.kolon_turleri("girdiler"), tablo.kolon_turleri("ciktilar")
        girdiler = [v for o in ham_girdi if (v := _olgu_dogrula(icerik, o, g_tur))]
        beklenen = [v for o in ham_beklenen if (v := _olgu_dogrula(icerik, o, c_tur))]
        atilan += len(ham_girdi) - len(girdiler) + len(ham_beklenen) - len(beklenen)
        alintilar += [(o["field"], o["quote"]) for o in girdiler + beklenen]
        g = _grup_degerlendir(tablo, girdiler, beklenen)
        # Değerlendirilemeyen grubun doğrulanmış beklenen olguları da karşılaştırılmadı.
        g["_karsilastirilmayan"] = (
            len(beklenen) if g["durum"] in _DEGERLENDIRILMEDI else len(g["karsilastirilamayan"])
        )
        gruplar.append(g)
    yok_sayilan = [v for o in cikti.get("ignored") or [] if (v := _yok_sayilan_dogrula(icerik, o))]
    alintilar += [(o["alan"], o["alinti"]) for o in yok_sayilan]
    kapsanmayan = kapsanmayan_sayilar(icerik, alintilar)
    eksik_tablolar = [t.ref for t in tablolar if t.id not in gorulen]
    ayr = _ayrintilar(gruplar, atilan, kapsanmayan, yok_sayilan, eksik_tablolar)
    return _genel_sonuc(gruplar, ayr), ayr


def _ayrintilar(
    gruplar: list[dict[str, Any]],
    atilan: int,
    kapsanmayan: list[dict[str, str]],
    yok_sayilan: list[dict[str, Any]],
    eksik_tablolar: list[str],
) -> dict[str, Any]:
    karsilastirmalar = [k for g in gruplar for k in g["karsilastirmalar"]]
    karsilastirilmayan = sum(g.pop("_karsilastirilmayan", 0) for g in gruplar)
    return {
        "gruplar": gruplar,
        "atilan_olgular": atilan,
        "degerler": {
            "uyumlu": sum(1 for k in karsilastirmalar if k["uyumlu"]),
            "uyumsuz": sum(1 for k in karsilastirmalar if not k["uyumlu"]),
            "karsilastirilamayan": karsilastirilmayan,
            "atilan": atilan,
            "kapsanmayan": len(kapsanmayan),
        },
        "kapsanmayan_sayilar": kapsanmayan,
        "yok_sayilan": yok_sayilan,
        "degerlendirilmeyen_tablolar": eksik_tablolar,
    }


def _grup_degerlendir(
    tablo: Tablo, girdiler: list[dict[str, Any]], beklenen: list[dict[str, Any]]
) -> dict[str, Any]:
    kayit: dict[str, Any] = {
        "tablo_id": tablo.id,
        "tablo_ad": tablo.ad,
        "satir_id": None,
        "girdiler": [_olgu_kaydi(o) for o in girdiler],
        "karsilastirmalar": [],
        "karsilastirilamayan": [],
        "durum": G_CIKARILAMADI,
        "neden": None,
    }
    degerler: dict[str, Any] = {}
    for o in girdiler:
        onceki = degerler.get(o["column"])
        if onceki is not None and onceki != o["value"]:
            kayit["neden"] = f"çelişkili girdi: {o['column']}"
            return kayit
        degerler[o["column"]] = o["value"]
    sonuc = kismi_degerlendir(tablo.icerik, degerler)
    if sonuc.eksik_girdiler:
        kayit["neden"] = "case'te bulunamayan girdi: " + ", ".join(sonuc.eksik_girdiler)
        return kayit
    if sonuc.hata is not None:
        kayit.update(satir_id=sonuc.satir_id, durum=G_HATA, neden=sonuc.hata)
        return kayit
    if sonuc.satir_id is None:
        kayit.update(durum=G_SATIR_YOK, neden="bu girdilerle eşleşen tablo satırı yok")
        return kayit
    kayit["satir_id"] = sonuc.satir_id
    hesaplanan = [o for o in beklenen if o["column"] not in sonuc.hesaplanamayan]
    kayit["karsilastirilamayan"] = [
        {
            **_olgu_kaydi(o),
            "neden": "case'te bulunamayan girdi: " + ", ".join(sonuc.hesaplanamayan[o["column"]]),
        }
        for o in beklenen
        if o["column"] in sonuc.hesaplanamayan
    ]
    if not hesaplanan:
        if kayit["karsilastirilamayan"]:
            kayit.update(neden=kayit["karsilastirilamayan"][0]["neden"])
            return kayit
        kayit.update(durum=G_KARSILASTIRMA_YOK, neden="case'te doğrulanan beklenen değer yok")
        return kayit
    tol = ifade.toleranslar(tablo.icerik)
    karsilastirmalar = []
    for o in hesaplanan:
        tablo_degeri = sonuc.ciktilar.get(o["column"])
        uyumlu = ifade.esit_mi(o["value"], tablo_degeri, tol.get(o["column"], Decimal(0)))
        karsilastirmalar.append(
            {
                "column": o["column"],
                "alan": o["field"],
                "alinti": o["quote"],
                "case_degeri": goster(o["value"]),
                "tablo_degeri": goster(tablo_degeri),
                "uyumlu": uyumlu,
            }
        )
    kayit["karsilastirmalar"] = karsilastirmalar
    kayit["durum"] = G_UYUMLU if all(k["uyumlu"] for k in karsilastirmalar) else G_UYUMSUZ
    return kayit


def _eksik_mi(gruplar: Sequence[Mapping[str, Any]], ayr: Mapping[str, Any]) -> bool:
    """K11 `kismen`: kapsanan bir grup / tablo değerlendirilemedi, ya da bir olgu atıldı,
    karşılaştırılamadı ya da beklenen alandaki bir sayı hiçbir olguyla kapsanmadı."""
    d = ayr.get("degerler") or {}
    return bool(
        any(g.get("durum") in _DEGERLENDIRILMEDI for g in gruplar)
        or ayr.get("degerlendirilmeyen_tablolar")
        or d.get("atilan")
        or d.get("karsilastirilamayan")
        or d.get("kapsanmayan")
    )


def _genel_sonuc(gruplar: Sequence[Mapping[str, Any]], ayr: Mapping[str, Any]) -> str:
    karsilastirmalar = [k for g in gruplar for k in g["karsilastirmalar"]]
    if any(not k["uyumlu"] for k in karsilastirmalar):
        return UYUMSUZ
    if karsilastirmalar:
        return KISMEN if _eksik_mi(gruplar, ayr) else UYUMLU
    return KONTROL_EDILEMEDI


def _eksik_ozeti(ayr: Mapping[str, Any]) -> str:
    """Karşılaştırılamayan / atılan / kapsanmayan değerlerin kısa dökümü (boşsa "")."""
    d = ayr.get("degerler") or {}
    parcalar = []
    disarida = [k for g in ayr.get("gruplar") or [] for k in g.get("karsilastirilamayan") or []]
    if d.get("karsilastirilamayan"):
        neden = (
            disarida[0].get("neden")
            if disarida
            else next(
                (
                    g.get("neden")
                    for g in ayr.get("gruplar") or []
                    if g.get("durum") in _DEGERLENDIRILMEDI
                ),
                None,
            )
        )
        sebep = f" ({neden})" if neden else ""
        parcalar.append(f"{d['karsilastirilamayan']} değer karşılaştırılamadı{sebep}")
    if d.get("atilan"):
        parcalar.append(f"{d['atilan']} olgu doğrulanamadığı için atıldı")
    kapsanmayan = ayr.get("kapsanmayan_sayilar") or []
    if kapsanmayan:
        ilk = kapsanmayan[0]
        parcalar.append(
            f"{len(kapsanmayan)} sayı hiçbir olguyla kapsanmadı (ör. {ilk['alinti']!r}, "
            f"{ilk['alan']})"
        )
    tablolar = ayr.get("degerlendirilmeyen_tablolar") or []
    if tablolar:
        parcalar.append(f"{', '.join(tablolar)} için değer çıkarılmadı")
    return "; ".join(parcalar)


def ozet(sonuc: str | None, ayrintilar: Mapping[str, Any] | None) -> str:
    """Portal çipinin yanındaki tek cümlelik Türkçe özet."""
    ayr = ayrintilar or {}
    karsilastirmalar = [
        k for g in ayr.get("gruplar") or [] for k in g.get("karsilastirmalar") or []
    ]
    if sonuc == KAPSAM_DISI:
        return "Bu case'i kapsayan onaylı karar tablosu yok."
    eksik = _eksik_ozeti(ayr)
    ek = f" Ayrıca {eksik}." if eksik else ""
    if sonuc == UYUMLU:
        return f"{len(karsilastirmalar)} beklenen değer onaylı karar tablosuyla uyumlu.{ek}"
    if sonuc == KISMEN:
        uyumlu = sum(1 for k in karsilastirmalar if k.get("uyumlu"))
        return (
            f"Kısmen kontrol edildi: {uyumlu} beklenen değer tabloyla uyumlu, fark yok; "
            f"{eksik or 'bazı değerler kontrol edilemedi'}."
        )
    if sonuc == UYUMSUZ:
        bozuk = [k for k in karsilastirmalar if not k.get("uyumlu")]
        ilk = bozuk[0]
        return (
            f"{len(bozuk)} beklenen değer tabloyla uyuşmuyor; ör. {ilk['column']}: case "
            f"{ilk['alinti']!r}, tablo {ilk['tablo_degeri']}.{ek}"
        )
    if sonuc == KONTROL_EDILEMEDI:
        nedenler = [g.get("neden") for g in ayr.get("gruplar") or [] if g.get("neden")]
        if nedenler:
            return f"Kontrol edilemedi: {nedenler[0]}.{ek}"
        return f"Kontrol edilemedi: case'ten tabloyla karşılaştırılabilir değer çıkarılamadı.{ek}"
    return "Tablo kontrolü sürüyor."


def yuksek_risk_mi(icerik: Mapping[str, Any] | None) -> bool:
    """Tek "yüksek risk" tanımı (V11): `risk == "high"` ya da (v3 içeriği) `priority == "P1"`."""
    icerik = icerik or {}
    return (
        str(icerik.get("risk") or "").strip().lower() == "high"
        or str(icerik.get("priority") or "").strip().upper() == "P1"
    )
