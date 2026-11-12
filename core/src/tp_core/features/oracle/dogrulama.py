"""Olgu doğrulama ve tablo karşılaştırması — LLM'siz, saf (012 ANALIZ §4.3 adım 3–4).

Modelin çıkardığı her olgu (`{column, value, field, quote}`) şu kurallarla doğrulanır; tutmayan
olgu atılır (`atilan_olgular` sayılır), asla düzeltilmez:

1. `field` case içinde bir metin alanının yoludur: `title`, `expected_result`,
   `preconditions[i]`, `steps[i].action | .data | .expected` (`i` 0 tabanlı JSON dizinidir).
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
     kabul edilir) ya da olumsuz kip ekleri (`-maz/-mez`, `-mıyor/-miyor/-muyor/-müyor`; en az 5
     harfli sözcükte) taşıyan sözcüklerdir: `"Sepette kampanyalı ürün yok"` → false,
     `"butonu pasiftir"` → false, `"uyarısı görünür"` → true, `"uyarısı görünmez"` → false.

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

Genel sonuç: herhangi bir karşılaştırma tutmuyorsa `uyumsuz`; değilse en az bir karşılaştırma
varsa `uyumlu`; hiç kapsayan tablo yoksa `kapsam_disi`; kapsayan tablo var ama kullanılabilir
karşılaştırma yoksa `kontrol_edilemedi`.
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

# Grup durumları (`ayrintilar.gruplar[].durum`).
G_UYUMLU = "uyumlu"
G_UYUMSUZ = "uyumsuz"
G_CIKARILAMADI = "cikarilamadi"
G_SATIR_YOK = "satir_yok"
G_HATA = "hata"
G_KARSILASTIRMA_YOK = "karsilastirma_yok"

_ALAN_DESENI = re.compile(
    r"^(?:(?P<kok>title|expected_result)"
    r"|preconditions\[(?P<on>\d{1,3})\]"
    r"|steps\[(?P<adim>\d{1,3})\]\.(?P<adim_alan>action|data|expected))$"
)
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
_OLUMSUZ_EKLER = ("maz", "mez", "mıyor", "miyor", "muyor", "müyor")


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
    a, q = unicodedata.normalize("NFC", alan), unicodedata.normalize("NFC", alinti)
    if not q.strip():
        return False
    bas = a.find(q)
    while bas >= 0:
        if _sinir_mi(a, bas, bas + len(q)):
            return True
        bas = a.find(q, bas + 1)
    return False


def _olumsuz_mu(sozcuk: str) -> bool:
    for kok in OLUMSUZ_SOZCUKLER:
        if sozcuk.startswith(kok) and sozcuk[len(kok) :] in _EK_FIIL:
            return True
    return len(sozcuk) >= 5 and any(
        sozcuk.endswith(ek + ekf) for ek in _OLUMSUZ_EKLER for ekf in _EK_FIIL
    )


def kutup(alinti: str) -> bool | None:
    """Alıntının mantıksal kutbu: olumsuzluk yok → True, bir tane → False, fazlası → None."""
    sozcukler = re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", alinti).casefold())
    n = sum(1 for s in sozcukler if _olumsuz_mu(s))
    if n == 0:
        return True
    return False if n == 1 else None


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
    return {"column": kolon, "value": deger, "field": str(olgu["field"]).strip(), "quote": alinti}


def _olgu_kaydi(o: Mapping[str, Any]) -> dict[str, Any]:
    return {**o, "value": goster(o["value"])}


def degerlendir(
    icerik: Mapping[str, Any], tablolar: Sequence[Tablo], cikti: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """Model çıktısını doğrular ve tablolarla karşılaştırır → (sonuç, ayrıntılar).

    `tablolar` case'i kapsayan geçerli tablolardır (boşsa `kapsam_disi`, model çıktısına
    bakılmaz). `ayrintilar` §4.3 biçimindedir.
    """
    if not tablolar:
        return KAPSAM_DISI, {"gruplar": [], "atilan_olgular": 0}
    atilan = 0
    gruplar: list[dict[str, Any]] = []
    for grup in (cikti or {}).get("groups") or []:
        if not isinstance(grup, Mapping):
            continue
        ham_girdi = [o for o in grup.get("inputs") or []]
        ham_beklenen = [o for o in grup.get("expected") or []]
        tablo = _tablo_bul(tablolar, grup.get("table_ref"))
        if tablo is None:
            atilan += len(ham_girdi) + len(ham_beklenen)
            continue
        g_tur, c_tur = tablo.kolon_turleri("girdiler"), tablo.kolon_turleri("ciktilar")
        girdiler = [v for o in ham_girdi if (v := _olgu_dogrula(icerik, o, g_tur))]
        beklenen = [v for o in ham_beklenen if (v := _olgu_dogrula(icerik, o, c_tur))]
        atilan += len(ham_girdi) - len(girdiler) + len(ham_beklenen) - len(beklenen)
        gruplar.append(_grup_degerlendir(tablo, girdiler, beklenen))
    return _genel_sonuc(gruplar), {"gruplar": gruplar, "atilan_olgular": atilan}


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


def _genel_sonuc(gruplar: Sequence[Mapping[str, Any]]) -> str:
    karsilastirmalar = [k for g in gruplar for k in g["karsilastirmalar"]]
    if any(not k["uyumlu"] for k in karsilastirmalar):
        return UYUMSUZ
    if karsilastirmalar:
        return UYUMLU
    return KONTROL_EDILEMEDI


def ozet(sonuc: str | None, ayrintilar: Mapping[str, Any] | None) -> str:
    """Portal çipinin yanındaki tek cümlelik Türkçe özet."""
    ayr = ayrintilar or {}
    karsilastirmalar = [
        k for g in ayr.get("gruplar") or [] for k in g.get("karsilastirmalar") or []
    ]
    if sonuc == KAPSAM_DISI:
        return "Bu case'i kapsayan onaylı karar tablosu yok."
    disarida = [k for g in ayr.get("gruplar") or [] for k in g.get("karsilastirilamayan") or []]
    ek = (
        f" {len(disarida)} değer karşılaştırılamadı ({disarida[0].get('neden')})."
        if disarida
        else ""
    )
    if sonuc == UYUMLU:
        return f"{len(karsilastirmalar)} beklenen değer onaylı karar tablosuyla uyumlu.{ek}"
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
            return f"Kontrol edilemedi: {nedenler[0]}."
        return "Kontrol edilemedi: case'ten tabloyla karşılaştırılabilir değer çıkarılamadı."
    return "Tablo kontrolü sürüyor."
