"""Sınırlı ifade dili ve karar tablosu değerlendirmesi (012 ANALIZ §4.2).

Saf ve yan etkisiz modül: veritabanı, ağ ya da model çağrısı yoktur; aynı girdi her zaman aynı
sonucu verir. Kullanıcı metni asla `eval` / `exec` / `ast` ile çalıştırılmaz; kendi simgeleyicisi
ve özyinelemeli iniş ayrıştırıcısı vardır. Tek dosya girişi `dogrula` / `iliski_dogrula`'nın
okuduğu içerik şemalarıdır (`rules/schemas/icerik/*.schema.json`, önbellekli).

Dil::

    değerler   sayı (7, 25.00) · metin ("min_siparis" ya da 'min_siparis') · dogru / yanlis · ad
    işleçler   + - * /   // (tam bölme, aşağı yuvarlar)   % (kalan, bölenin işaretini alır)
               == != < <= > >=   ve   veya   degil   parantez
    işlevler   min(a, b) · max(a, b) · yuvarla(x, hane) (HALF_UP, hane 0–12) · taban(x) · tavan(x)
               eger(kosul, a, b)

Öncelik (düşükten yükseğe): `veya` < `ve` < `degil` < karşılaştırma < `+ -` < `* / // %` < tekli
`- +`. Karşılaştırmalar zincirlenmez (`a < b < c` hatadır). `ve`, `veya` ve `eger` tembeldir
(`b != 0 ve a / b > 2` sıfıra bölmez). Türler: `sayi` (Decimal), `metin` (str), `mantiksal` (bool);
örtük dönüşüm yoktur. Aritmetik `Decimal`'dir: 60 anlamlı basamak, ROUND_HALF_UP; mutlak değeri
10^30 ve üstü olan sonuç hatadır.

Sınırlar: ifade en çok 300 karakter, iç içe derinlik en çok 32; tablo en çok 12 girdi, 12 çıktı,
60 satır. Hatalar `IfadeHatasi(mesaj, konum)`'dur; `konum` ifadedeki 0 tabanlı karakter indeksidir
(`str(hata)` 1 tabanlı yazar: "… (konum 5)").

Genel arayüz (şeritler bunu kullanır, yeniden yazmaz):

- tablo: `dogrula`, `gonderim_hatalari`, `degerlendir` → `Degerlendirme`
- ilişki: `iliski_dogrula`, `iliski_uygula` → `IliskiSonucu`
- tek ifade: `ayristir`, `adlar`, `ifade_turu`, `hesapla`
- sayı metni: `sayi_ayristir`, `sayi_bicimle`, `esit_mi`
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

AZAMI_IFADE_UZUNLUGU: Final = 300
AZAMI_DERINLIK: Final = 32
AZAMI_GIRDI: Final = 12
AZAMI_CIKTI: Final = 12
AZAMI_SATIR: Final = 60
AZAMI_HANE: Final = 12  # yuvarla(x, hane)
HASSASIYET: Final = 60  # anlamlı basamak
AZAMI_BUYUKLUK: Final = 30  # |x| < 10^30
AZAMI_HATA: Final = 20  # dogrula'nın döndürdüğü en çok hata metni
# Yuvarlaması belirtilmemiş sayı çıktısında izin verilen en büyük tolerans (kuruş).
TOLERANS_AZAMI: Final = Decimal("0.01")

SAYI: Final = "sayi"
METIN: Final = "metin"
MANTIKSAL: Final = "mantiksal"
TURLER: Final = frozenset({SAYI, METIN, MANTIKSAL})
_TUR_ADI: Final = {SAYI: "sayı", METIN: "metin", MANTIKSAL: "mantıksal"}

ANAHTAR_SOZCUKLER: Final = frozenset({"ve", "veya", "degil", "dogru", "yanlis"})
# işlev adı → parametre sayısı
ISLEVLER: Final[dict[str, int]] = {
    "min": 2,
    "max": 2,
    "yuvarla": 2,
    "taban": 1,
    "tavan": 1,
    "eger": 3,
}
# Girdi / çıktı adı olamayan sözcükler.
AYRILMIS_ADLAR: Final = ANAHTAR_SOZCUKLER | frozenset(ISLEVLER)

SEMA_DIZINI: Final = "schemas/icerik"
KARAR_TABLOSU_SEMASI: Final = "karar_tablosu"
METAMORFIK_ILISKI_SEMASI: Final = "metamorfik_iliski"

_KARSILASTIRMA: Final = frozenset({"==", "!=", "<", "<=", ">", ">="})
_AD_DESENI: Final = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_KESIN_SAYI: Final = re.compile(r"^[+-]?[0-9]+(\.[0-9]+)?$")


class IfadeHatasi(ValueError):
    """İfade ayrıştırma / tür / değerlendirme hatası.

    `mesaj`: Türkçe açıklama; `konum`: ifadedeki 0 tabanlı karakter indeksi (bilinmiyorsa None).
    """

    def __init__(self, mesaj: str, konum: int | None = None) -> None:
        self.mesaj = mesaj
        self.konum = konum
        super().__init__(mesaj if konum is None else f"{mesaj} (konum {konum + 1})")


# ---------------------------------------------------------------------- simgeleyici


@dataclass(frozen=True, slots=True)
class _Simge:
    cins: str  # sayi | metin | ad | anahtar | op | son
    deger: Any
    konum: int


_OPLAR: Final = ("//", "==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "<", ">", "(", ")", ",")
_AD_BAS: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_RAKAM: Final = frozenset("0123456789")
_AD_DEVAM: Final = _AD_BAS | _RAKAM
_BOSLUKLAR: Final = frozenset(" \t\r\n")


def _simgele(metin: str) -> list[_Simge]:
    simgeler: list[_Simge] = []
    i, n = 0, len(metin)
    while i < n:
        c = metin[i]
        if c in _BOSLUKLAR:
            i += 1
            continue
        if c in _RAKAM:
            j = i
            while j < n and metin[j] in _RAKAM:
                j += 1
            if j < n and metin[j] == ".":
                k = j + 1
                while k < n and metin[k] in _RAKAM:
                    k += 1
                if k == j + 1:
                    raise IfadeHatasi("ondalık noktadan sonra rakam bekleniyor", j)
                j = k
            if j < n and (metin[j] in _AD_BAS or metin[j] == "."):
                raise IfadeHatasi("sayı biçimi geçersiz", i)
            deger = Decimal(metin[i:j])
            if deger.adjusted() >= AZAMI_BUYUKLUK:
                raise IfadeHatasi("sayı çok büyük", i)
            simgeler.append(_Simge("sayi", deger, i))
            i = j
            continue
        if c in _AD_BAS:
            j = i
            while j < n and metin[j] in _AD_DEVAM:
                j += 1
            ad = metin[i:j]
            simgeler.append(_Simge("anahtar" if ad in ANAHTAR_SOZCUKLER else "ad", ad, i))
            i = j
            continue
        if c in "\"'":
            j = metin.find(c, i + 1)
            if j < 0:
                raise IfadeHatasi("metin kapatılmamış (tırnak eksik)", i)
            icerik = metin[i + 1 : j]
            if "\n" in icerik or "\r" in icerik:
                raise IfadeHatasi("metin satır sonu içeremez", i)
            simgeler.append(_Simge("metin", icerik, i))
            i = j + 1
            continue
        for op in _OPLAR:
            if metin.startswith(op, i):
                simgeler.append(_Simge("op", op, i))
                i += len(op)
                break
        else:
            if c == "=":
                raise IfadeHatasi("eşitlik için '==' kullanın", i)
            if c == "!":
                raise IfadeHatasi("'!' tek başına kullanılamaz; 'degil' ya da '!=' kullanın", i)
            if c in "&|":
                raise IfadeHatasi(f"'{c}' yerine 've' / 'veya' kullanın", i)
            raise IfadeHatasi(f"beklenmeyen karakter: {c!r}", i)
    simgeler.append(_Simge("son", None, n))
    return simgeler


# ---------------------------------------------------------------------- ayrıştırıcı


@dataclass(frozen=True, slots=True)
class Dugum:
    """Soyut sözdizimi ağacı düğümü (değişmez).

    `cins`: sayi | metin | mantik | ad | tekli | ikili | islev. `deger`: sabitin değeri, ad,
    işleç ya da işlev adı. `alt`: alt düğümler.
    """

    cins: str
    konum: int
    deger: Any = None
    alt: tuple[Dugum, ...] = ()


class _Ayristirici:
    def __init__(self, metin: str) -> None:
        self.s = _simgele(metin)
        self.i = 0
        self.derinlik = 0

    # -- yardımcılar

    def _bak(self) -> _Simge:
        return self.s[self.i]

    def _al(self) -> _Simge:
        simge = self.s[self.i]
        self.i += 1
        return simge

    def _op_mu(self, *oplar: str) -> bool:
        simge = self.s[self.i]
        return simge.cins == "op" and simge.deger in oplar

    def _anahtar_mi(self, sozcuk: str) -> bool:
        simge = self.s[self.i]
        return simge.cins == "anahtar" and simge.deger == sozcuk

    def _bekle(self, op: str) -> _Simge:
        if not self._op_mu(op):
            raise IfadeHatasi(f"'{op}' bekleniyor", self._bak().konum)
        return self._al()

    def _gir(self, konum: int) -> None:
        self.derinlik += 1
        if self.derinlik > AZAMI_DERINLIK:
            raise IfadeHatasi(f"ifade çok derin (en çok {AZAMI_DERINLIK} düzey)", konum)

    def _cik(self) -> None:
        self.derinlik -= 1

    # -- dilbilgisi

    def tumu(self) -> Dugum:
        dugum = self.ifade()
        simge = self._bak()
        if simge.cins != "son":
            raise IfadeHatasi(f"beklenmeyen simge: {_goster(simge)}", simge.konum)
        return dugum

    def ifade(self) -> Dugum:
        sol = self.ve()
        while self._anahtar_mi("veya"):
            op = self._al()
            sol = Dugum("ikili", op.konum, "veya", (sol, self.ve()))
        return sol

    def ve(self) -> Dugum:
        sol = self.degil()
        while self._anahtar_mi("ve"):
            op = self._al()
            sol = Dugum("ikili", op.konum, "ve", (sol, self.degil()))
        return sol

    def degil(self) -> Dugum:
        if self._anahtar_mi("degil"):
            op = self._al()
            self._gir(op.konum)
            alt = self.degil()
            self._cik()
            return Dugum("tekli", op.konum, "degil", (alt,))
        return self.karsilastirma()

    def karsilastirma(self) -> Dugum:
        sol = self.toplam()
        if self._op_mu(*_KARSILASTIRMA):
            op = self._al()
            sol = Dugum("ikili", op.konum, op.deger, (sol, self.toplam()))
            if self._op_mu(*_KARSILASTIRMA):
                raise IfadeHatasi(
                    "karşılaştırmalar zincirlenemez; 've' ile bağlayın", self._bak().konum
                )
        return sol

    def toplam(self) -> Dugum:
        sol = self.carpim()
        while self._op_mu("+", "-"):
            op = self._al()
            sol = Dugum("ikili", op.konum, op.deger, (sol, self.carpim()))
        return sol

    def carpim(self) -> Dugum:
        sol = self.tekli()
        while self._op_mu("*", "/", "//", "%"):
            op = self._al()
            sol = Dugum("ikili", op.konum, op.deger, (sol, self.tekli()))
        return sol

    def tekli(self) -> Dugum:
        if self._op_mu("-", "+"):
            op = self._al()
            self._gir(op.konum)
            alt = self.tekli()
            self._cik()
            return Dugum("tekli", op.konum, op.deger, (alt,))
        return self.birincil()

    def birincil(self) -> Dugum:
        simge = self._al()
        if simge.cins == "sayi":
            return Dugum("sayi", simge.konum, simge.deger)
        if simge.cins == "metin":
            return Dugum("metin", simge.konum, simge.deger)
        if simge.cins == "anahtar" and simge.deger in ("dogru", "yanlis"):
            return Dugum("mantik", simge.konum, simge.deger == "dogru")
        if simge.cins == "ad":
            return self._ad_ya_da_islev(simge)
        if simge.cins == "op" and simge.deger == "(":
            self._gir(simge.konum)
            ic = self.ifade()
            self._cik()
            self._bekle(")")
            return ic
        if simge.cins == "son":
            raise IfadeHatasi("ifade eksik (değer bekleniyor)", simge.konum)
        raise IfadeHatasi(f"beklenmeyen simge: {_goster(simge)}", simge.konum)

    def _ad_ya_da_islev(self, simge: _Simge) -> Dugum:
        ad: str = simge.deger
        cagri = self._op_mu("(")
        if ad not in ISLEVLER:
            if cagri:
                raise IfadeHatasi(f"bilinmeyen işlev: {ad}", simge.konum)
            return Dugum("ad", simge.konum, ad)
        if not cagri:
            raise IfadeHatasi(f"'{ad}' bir işlevdir; '{ad}(…)' biçiminde çağrılır", simge.konum)
        self._al()
        self._gir(simge.konum)
        argumanlar: list[Dugum] = []
        if not self._op_mu(")"):
            argumanlar.append(self.ifade())
            while self._op_mu(","):
                self._al()
                argumanlar.append(self.ifade())
        self._cik()
        self._bekle(")")
        if len(argumanlar) != ISLEVLER[ad]:
            raise IfadeHatasi(
                f"{ad} işlevi {ISLEVLER[ad]} değer alır ({len(argumanlar)} verildi)", simge.konum
            )
        return Dugum("islev", simge.konum, ad, tuple(argumanlar))


def _goster(simge: _Simge) -> str:
    if simge.cins == "son":
        return "ifade sonu"
    if simge.cins == "metin":
        return f'"{simge.deger}"'
    return f"'{simge.deger}'"


@lru_cache(maxsize=4096)
def _ayristir(metin: str) -> Dugum:
    return _Ayristirici(metin).tumu()


def ayristir(metin: str) -> Dugum:
    """İfadeyi ayrıştırır (yalnız sözdizimi); hata `IfadeHatasi`."""
    if not isinstance(metin, str):
        raise IfadeHatasi("ifade metin olmalı")
    if len(metin) > AZAMI_IFADE_UZUNLUGU:
        raise IfadeHatasi(f"ifade en çok {AZAMI_IFADE_UZUNLUGU} karakter olabilir")
    if not metin.strip():
        raise IfadeHatasi("ifade boş")
    try:
        return _ayristir(metin)
    except RecursionError:  # derinlik sınırı bunu önler; yine de kullanıcıya düzgün hata
        raise IfadeHatasi(f"ifade çok derin (en çok {AZAMI_DERINLIK} düzey)") from None


def _adlari_topla(dugum: Dugum, cikti: dict[str, None]) -> None:
    yigin = [dugum]
    while yigin:
        d = yigin.pop()
        if d.cins == "ad":
            cikti.setdefault(d.deger)
        yigin.extend(reversed(d.alt))


def adlar(metin: str) -> list[str]:
    """İfadede geçen adlar (ilk geçiş sırasıyla, tekil)."""
    cikti: dict[str, None] = {}
    _adlari_topla(ayristir(metin), cikti)
    return list(cikti)


# ---------------------------------------------------------------------- tür denetimi


def _tur_bekle(gercek: str, beklenen: str, ne: str, konum: int) -> None:
    if gercek != beklenen:
        raise IfadeHatasi(f"{ne} {_TUR_ADI[beklenen]} olmalı ({_TUR_ADI[gercek]} verildi)", konum)


def _tur(d: Dugum, turler: Mapping[str, str]) -> str:
    if d.cins == "sayi":
        return SAYI
    if d.cins == "metin":
        return METIN
    if d.cins == "mantik":
        return MANTIKSAL
    if d.cins == "ad":
        tur = turler.get(d.deger)
        if tur is None:
            raise IfadeHatasi(f"bilinmeyen ad: {d.deger}", d.konum)
        if tur not in TURLER:
            raise IfadeHatasi(f"'{d.deger}' için geçersiz tür: {tur}", d.konum)
        return tur
    if d.cins == "tekli":
        alt = _tur(d.alt[0], turler)
        if d.deger == "degil":
            _tur_bekle(alt, MANTIKSAL, "'degil' işlecinin değeri", d.konum)
            return MANTIKSAL
        _tur_bekle(alt, SAYI, f"'{d.deger}' işlecinin değeri", d.konum)
        return SAYI
    if d.cins == "ikili":
        sol, sag = _tur(d.alt[0], turler), _tur(d.alt[1], turler)
        op = d.deger
        if op in ("ve", "veya"):
            _tur_bekle(sol, MANTIKSAL, f"'{op}' işlecinin sol tarafı", d.konum)
            _tur_bekle(sag, MANTIKSAL, f"'{op}' işlecinin sağ tarafı", d.konum)
            return MANTIKSAL
        if op in ("==", "!="):
            if sol != sag:
                raise IfadeHatasi(
                    f"'{op}' farklı türleri karşılaştıramaz ({_TUR_ADI[sol]} ile {_TUR_ADI[sag]})",
                    d.konum,
                )
            return MANTIKSAL
        _tur_bekle(sol, SAYI, f"'{op}' işlecinin sol tarafı", d.konum)
        _tur_bekle(sag, SAYI, f"'{op}' işlecinin sağ tarafı", d.konum)
        return MANTIKSAL if op in _KARSILASTIRMA else SAYI
    # işlev
    ad = d.deger
    alt_turler = [_tur(a, turler) for a in d.alt]
    if ad == "eger":
        _tur_bekle(alt_turler[0], MANTIKSAL, "eger işlevinin koşulu", d.alt[0].konum)
        if alt_turler[1] != alt_turler[2]:
            raise IfadeHatasi(
                "eger işlevinin iki sonucu aynı türde olmalı "
                f"({_TUR_ADI[alt_turler[1]]} ile {_TUR_ADI[alt_turler[2]]})",
                d.konum,
            )
        return alt_turler[1]
    for sira, (alt, tur) in enumerate(zip(d.alt, alt_turler, strict=True), start=1):
        _tur_bekle(tur, SAYI, f"{ad} işlevinin {sira}. değeri", alt.konum)
    return SAYI


def ifade_turu(metin: str, turler: Mapping[str, str]) -> str:
    """İfadenin statik türü (`sayi` | `metin` | `mantiksal`); `turler`: ad → tür.

    Bilinmeyen ad ve tür uyuşmazlığı burada (değerlendirmeden önce) `IfadeHatasi` verir.
    """
    return _tur(ayristir(metin), turler)


# ---------------------------------------------------------------------- değerlendirme


def _baglam() -> Context:
    return Context(
        prec=HASSASIYET,
        rounding=ROUND_HALF_UP,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def _sinirla(x: Decimal, konum: int | None) -> Decimal:
    if not x.is_finite() or (not x.is_zero() and x.adjusted() >= AZAMI_BUYUKLUK):
        raise IfadeHatasi("sayı çok büyük", konum)
    if x.is_zero() and x.is_signed():
        return x.copy_abs()
    return x


def _tam_bol(a: Decimal, b: Decimal, ctx: Context) -> Decimal:
    """⌊a / b⌋ (aşağı yuvarlar; Python tam sayı bölmesiyle aynı)."""
    q = ctx.divide_int(a, b)
    kalan = ctx.subtract(a, ctx.multiply(q, b))
    if not kalan.is_zero() and (kalan < 0) != (b < 0):
        q = ctx.subtract(q, Decimal(1))
    return q


def _sayi(deger: Any, ne: str, konum: int) -> Decimal:
    if isinstance(deger, Decimal):
        return deger
    raise IfadeHatasi(f"{ne} sayı olmalı ({_deger_turu_adi(deger)} verildi)", konum)


def _mantik(deger: Any, ne: str, konum: int) -> bool:
    if isinstance(deger, bool):
        return deger
    raise IfadeHatasi(f"{ne} mantıksal olmalı ({_deger_turu_adi(deger)} verildi)", konum)


def _deger_turu(deger: Any) -> str | None:
    if isinstance(deger, bool):
        return MANTIKSAL
    if isinstance(deger, Decimal):
        return SAYI
    if isinstance(deger, str):
        return METIN
    return None


def _deger_turu_adi(deger: Any) -> str:
    tur = _deger_turu(deger)
    return _TUR_ADI[tur] if tur else "geçersiz değer"


def _hesapla(d: Dugum, degerler: Mapping[str, Any], ctx: Context) -> Any:
    cins = d.cins
    if cins in ("sayi", "metin", "mantik"):
        return d.deger
    if cins == "ad":
        if d.deger not in degerler:
            raise IfadeHatasi(f"bilinmeyen ad: {d.deger}", d.konum)
        deger = degerler[d.deger]
        if _deger_turu(deger) is None:
            raise IfadeHatasi(f"'{d.deger}' için geçersiz değer", d.konum)
        return deger
    if cins == "tekli":
        alt = _hesapla(d.alt[0], degerler, ctx)
        if d.deger == "degil":
            return not _mantik(alt, "'degil' işlecinin değeri", d.konum)
        sayi = _sayi(alt, f"'{d.deger}' işlecinin değeri", d.konum)
        return _sinirla(ctx.minus(sayi) if d.deger == "-" else ctx.plus(sayi), d.konum)
    if cins == "ikili":
        return _ikili(d, degerler, ctx)
    return _islev(d, degerler, ctx)


def _ikili(d: Dugum, degerler: Mapping[str, Any], ctx: Context) -> Any:
    op = d.deger
    if op in ("ve", "veya"):
        sol = _mantik(_hesapla(d.alt[0], degerler, ctx), f"'{op}' işlecinin sol tarafı", d.konum)
        if sol is (op == "veya"):  # kısa devre: `yanlis ve …` / `dogru veya …`
            return sol
        return _mantik(_hesapla(d.alt[1], degerler, ctx), f"'{op}' işlecinin sağ tarafı", d.konum)
    sol = _hesapla(d.alt[0], degerler, ctx)
    sag = _hesapla(d.alt[1], degerler, ctx)
    if op in ("==", "!="):
        if _deger_turu(sol) != _deger_turu(sag):
            raise IfadeHatasi(
                f"'{op}' farklı türleri karşılaştıramaz "
                f"({_deger_turu_adi(sol)} ile {_deger_turu_adi(sag)})",
                d.konum,
            )
        return (sol == sag) is (op == "==")
    a = _sayi(sol, f"'{op}' işlecinin sol tarafı", d.konum)
    b = _sayi(sag, f"'{op}' işlecinin sağ tarafı", d.konum)
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op in ("/", "//", "%") and b.is_zero():
        raise IfadeHatasi("sıfıra bölme", d.konum)
    try:
        if op == "+":
            sonuc = ctx.add(a, b)
        elif op == "-":
            sonuc = ctx.subtract(a, b)
        elif op == "*":
            sonuc = ctx.multiply(a, b)
        elif op == "/":
            sonuc = ctx.divide(a, b)
        elif op == "//":
            sonuc = _tam_bol(a, b, ctx)
        else:  # "%": a - b * ⌊a / b⌋
            sonuc = ctx.subtract(a, ctx.multiply(b, _tam_bol(a, b, ctx)))
    except DecimalException:
        raise IfadeHatasi("sayı işlemi yapılamadı (sonuç çok büyük)", d.konum) from None
    return _sinirla(sonuc, d.konum)


def _islev(d: Dugum, degerler: Mapping[str, Any], ctx: Context) -> Any:
    ad = d.deger
    if ad == "eger":
        kosul = _mantik(_hesapla(d.alt[0], degerler, ctx), "eger işlevinin koşulu", d.alt[0].konum)
        return _hesapla(d.alt[1] if kosul else d.alt[2], degerler, ctx)
    sayilar = [
        _sayi(_hesapla(a, degerler, ctx), f"{ad} işlevinin {sira}. değeri", a.konum)
        for sira, a in enumerate(d.alt, start=1)
    ]
    try:
        if ad == "min":
            return min(sayilar)
        if ad == "max":
            return max(sayilar)
        if ad == "taban":
            return _sinirla(sayilar[0].to_integral_value(rounding=ROUND_FLOOR), d.konum)
        if ad == "tavan":
            return _sinirla(sayilar[0].to_integral_value(rounding=ROUND_CEILING), d.konum)
        # yuvarla(x, hane)
        x, hane = sayilar
        if hane != hane.to_integral_value() or not 0 <= hane <= AZAMI_HANE:
            raise IfadeHatasi(
                f"yuvarla: hane 0 ile {AZAMI_HANE} arasında tam sayı olmalı", d.alt[1].konum
            )
        adim = Decimal(1).scaleb(-int(hane))
        return _sinirla(x.quantize(adim, rounding=ROUND_HALF_UP, context=ctx), d.konum)
    except DecimalException:
        raise IfadeHatasi("sayı işlemi yapılamadı (sonuç çok büyük)", d.konum) from None


def _deger_donustur(deger: Any) -> Any:
    """Çağıranın verdiği değeri dil değerine çevirir (int/float → Decimal); geçersizse None."""
    if isinstance(deger, bool | str):
        return deger
    if isinstance(deger, Decimal):
        return deger if deger.is_finite() else None
    if isinstance(deger, int):
        return Decimal(deger)
    if isinstance(deger, float):
        return Decimal(repr(deger)) if deger == deger and abs(deger) != float("inf") else None
    return None


def hesapla(metin: str, degerler: Mapping[str, Any]) -> Any:
    """Tek ifadeyi `degerler` (ad → Decimal | int | str | bool) ile değerlendirir.

    Sonuç `Decimal`, `str` ya da `bool`'dur. Bilinmeyen ad, tür uyuşmazlığı, sıfıra bölme ve
    sınır aşımı `IfadeHatasi` verir.
    """
    dugum = ayristir(metin)
    ortam: dict[str, Any] = {}
    for ad, deger in degerler.items():
        cevrilen = _deger_donustur(deger)
        if cevrilen is None:
            raise IfadeHatasi(f"'{ad}' için geçersiz değer")
        ortam[ad] = cevrilen
    try:
        return _hesapla(dugum, ortam, _baglam())
    except RecursionError:
        raise IfadeHatasi(f"ifade çok derin (en çok {AZAMI_DERINLIK} düzey)") from None


# ---------------------------------------------------------------------- sayı metni

_EKSILER: Final = "-−"  # ASCII eksi ve U+2212 (−)
_ARA_BOSLUK: Final = "   "
_SAYI_DESENI: Final = re.compile(
    r"^(?P<i1>[+\-−]?)[   ]?"
    r"(?:(?P<sembol>[%₺$€£]{1,3})[   ]?(?P<i2>[+\-−]?)"
    r"|(?P<harf>[^\W\d_]{1,5})[   ])?"
    r"(?P<govde>[0-9](?:[0-9.,   ]*[0-9])?)"
    r"(?P<son>[   ]?[^\W\d_%₺$€£/]*[%₺$€£/]?[^\W\d_]*"
    r"(?:[   ][^\W\d_%₺$€£/]+){0,2})$"
)
_AZAMI_SAYI_METNI: Final = 64


@dataclass(frozen=True, slots=True)
class _SayiBicimi:
    deger: Decimal
    isaret: str  # "", "+", "-", "−"
    isaret_sembolden_sonra: bool
    on_ek: str  # işaret hariç, sayıdan önceki metin (boşluğu ile)
    son_ek: str  # sayıdan sonraki metin (boşluğu ile)
    ondalik: str  # "", "," ya da "."
    binlik: str  # "", ".", "," ya da boşluk karakteri
    hane: int


def _gruplar_gecerli(gruplar: Sequence[str]) -> bool:
    if not gruplar or not all(g.isdigit() and g.isascii() for g in gruplar):
        return False
    if not 1 <= len(gruplar[0]) <= 3 or any(len(g) != 3 for g in gruplar[1:]):
        return False
    return len(gruplar) == 1 or not gruplar[0].startswith("0")


def _govde_coz(govde: str) -> tuple[str, str, str, str] | None:
    """Sayı gövdesi → (tam kısım rakamları, kesir rakamları, ondalık ayırıcı, binlik ayırıcı)."""
    bosluklar = {c for c in govde if c in _ARA_BOSLUK}
    nokta, virgul = govde.count("."), govde.count(",")
    if bosluklar:
        # Boşluk binlik ayırıcıdır ("1 250,00"); en çok bir ondalık ayırıcı kalır.
        if len(bosluklar) != 1 or nokta + virgul > 1:
            return None
        binlik = next(iter(bosluklar))
        ondalik = "." if nokta else "," if virgul else ""
        tam, _, kesir = govde.partition(ondalik) if ondalik else (govde, "", "")
        gruplar = tam.split(binlik)
        if len(gruplar) < 2 or not _gruplar_gecerli(gruplar) or (ondalik and not kesir.isdigit()):
            return None
        return "".join(gruplar), kesir, ondalik, binlik
    if nokta and virgul:
        # Sonda gelen ayırıcı ondalıktır: "1.250,00" (TR) ve "1,250.00" (EN).
        ondalik = "." if govde.rfind(".") > govde.rfind(",") else ","
        binlik = "," if ondalik == "." else "."
        if govde.count(ondalik) != 1:
            return None
        tam, kesir = govde.split(ondalik)
        gruplar = tam.split(binlik)
        if not _gruplar_gecerli(gruplar) or not kesir.isdigit():
            return None
        return "".join(gruplar), kesir, ondalik, binlik
    if virgul == 1:
        # Tek virgül Türkçe ondalık ayırıcıdır: "750,00", "1,250" → 1.250.
        tam, kesir = govde.split(",")
        return (tam, kesir, ",", "") if tam.isdigit() and kesir.isdigit() else None
    if virgul > 1:
        gruplar = govde.split(",")
        return ("".join(gruplar), "", "", ",") if _gruplar_gecerli(gruplar) else None
    if nokta == 1:
        tam, kesir = govde.split(".")
        if not (tam.isdigit() and kesir.isdigit()):
            return None
        # "1.250" Türkçe binlik yazımıdır (1250); "1250.00", "0.125", "1.5" ondalık noktadır.
        if len(kesir) == 3 and 1 <= len(tam) <= 3 and not tam.startswith("0"):
            return tam + kesir, "", "", "."
        return tam, kesir, ".", ""
    if nokta > 1:
        gruplar = govde.split(".")
        return ("".join(gruplar), "", "", ".") if _gruplar_gecerli(gruplar) else None
    return (govde, "", "", "") if govde.isdigit() else None


def _sayi_coz(metin: Any) -> _SayiBicimi | None:
    if not isinstance(metin, str):
        return None
    metin = metin.strip()
    if not metin or len(metin) > _AZAMI_SAYI_METNI:
        return None
    m = _SAYI_DESENI.match(metin)
    if m is None:
        return None
    i1, i2 = m["i1"], m["i2"] or ""
    if i1 and i2:
        return None
    cozulen = _govde_coz(m["govde"])
    if cozulen is None:
        return None
    tam, kesir, ondalik, binlik = cozulen
    if len(tam) + len(kesir) > AZAMI_BUYUKLUK:
        return None
    isaret = i1 or i2
    deger = Decimal(f"{tam}.{kesir}" if kesir else tam)
    if isaret in _EKSILER and isaret:
        deger = -deger
    if deger.is_zero() and deger.is_signed():
        deger = deger.copy_abs()
    # on_ek: işaretten sonra, gövdeden önce ne varsa (sembol / harf ve boşluğu), işaretsiz.
    on_ham = metin[len(i1) : m.start("govde")]
    if i2:
        on_ham = on_ham[: len(on_ham) - len(i2)]
    return _SayiBicimi(
        deger=deger,
        isaret=isaret,
        isaret_sembolden_sonra=bool(i2),
        on_ek=on_ham,
        son_ek=m["son"],
        ondalik=ondalik,
        binlik=binlik,
        hane=len(kesir),
    )


def sayi_ayristir(metin: str) -> Decimal | None:
    """Metindeki tek sayıyı `Decimal` olarak okur; sayı değilse ya da belirsizse `None`.

    Türkçe ve düz biçimler: `"1.250,00 TL"` → 1250.00, `"−25,00 TL"` / `"-25,00 TL"` → -25.00,
    `"750,00"` → 750.00, `"7"` → 7, `"1250.00"` → 1250.00, `"1 250,00"` → 1250.00,
    `"₺1.250,00"` → 1250.00, `"%20"` → 20, `"7 adet"` → 7. Ondalık hane sayısı korunur.

    Kurallar: metinde tek sayı olmalı; önünde yalnız işaret, para/yüzde simgesi ya da boşlukla
    ayrılmış kısa bir birim, arkasında kısa bir birim (en çok üç sözcük) bulunabilir. Nokta ve
    virgül birlikteyse sonda gelen ondalık ayırıcıdır. Tek virgül ondalıktır (`"1,250"` → 1.250).
    Tek nokta, ardından tam üç rakam ve önünde 1–3 rakam (başı 0 değil) varsa binlik ayırıcıdır
    (`"1.250"` → 1250); değilse ondalık noktadır (`"1250.00"`, `"0.125"`, `"1.5"`).
    """
    bicim = _sayi_coz(metin)
    return bicim.deger if bicim is not None else None


def _binlikle(tam: str, ayirici: str) -> str:
    if not ayirici or len(tam) <= 3:
        return tam
    bas = len(tam) % 3 or 3
    return ayirici.join([tam[:bas], *(tam[i : i + 3] for i in range(bas, len(tam), 3))])


def _bicimle(deger: Decimal, b: _SayiBicimi, hane: int) -> str:
    q = deger.quantize(Decimal(1).scaleb(-hane), context=Context(prec=200))
    tam, _, kesir = format(abs(q), "f").partition(".")
    govde = _binlikle(tam, b.binlik)
    if kesir:
        govde += (b.ondalik or ("." if b.binlik == "," else ",")) + kesir
    isaret = ""
    if q < 0:
        isaret = b.isaret if b.isaret and b.isaret in _EKSILER else "-"
    elif q > 0 and b.isaret == "+":
        isaret = "+"
    if b.isaret_sembolden_sonra:
        return f"{b.on_ek}{isaret}{govde}{b.son_ek}"
    # İşaret yoksa işaretle sayı arasındaki boşluk ("- 25" → "25") başta kalmaz.
    return f"{isaret}{b.on_ek if isaret else b.on_ek.lstrip(_ARA_BOSLUK)}{govde}{b.son_ek}"


def sayi_bicimle(deger: Decimal, ornek: str) -> str:
    """`deger`'i `ornek`'in biçiminde yazar: `(Decimal(300), "150,00 TL")` → `"300,00 TL"`.

    Örnekten alınanlar: ondalık ayırıcı (virgül / nokta), binlik ayırıcı, ondalık hane sayısı,
    eksi işaretinin glifi (`-` ya da `−`) ve yeri, ön ek ve son ek (birim, simge, boşluk).
    Değer yuvarlanmaz: örneğin hane sayısına sığmıyorsa gereken kadar hane yazılır
    (`(Decimal("187.5"), "125 TL")` → `"187,5 TL"`). Sonuç `sayi_ayristir` ile aynı değere geri
    okunur; okunamıyorsa (ya da `ornek` sayı değilse, `deger` sonlu değilse) `ValueError`.
    """
    if isinstance(deger, bool) or not isinstance(deger, Decimal | int):
        raise ValueError("biçimlenecek değer sayı olmalı")
    sayi = Decimal(deger)
    if not sayi.is_finite() or (not sayi.is_zero() and sayi.adjusted() >= AZAMI_BUYUKLUK):
        raise ValueError("biçimlenecek değer sonlu ve sınır içinde olmalı")
    b = _sayi_coz(ornek)
    if b is None:
        raise ValueError(f"örnek sayı biçiminde değil: {ornek!r}")
    us = sayi.normalize().as_tuple().exponent
    gereken = max(0, -us) if isinstance(us, int) else 0
    hane = max(b.hane, gereken)
    # Tek noktalı yazım belirsizleşirse ("1.234" binlik gibi okunur) bir hane eklenir ("1.2340").
    for h in (hane, hane + 1):
        sonuc = _bicimle(sayi, b, h)
        if sayi_ayristir(sonuc) == sayi:
            return sonuc
    raise ValueError(f"değer örneğin biçiminde yazılamıyor: {sayi} / {ornek!r}")


def esit_mi(a: Any, b: Any, tolerans: Decimal = Decimal(0)) -> bool:
    """İki değer eşit mi: sayılar `|a - b| <= tolerans`, metin ve mantıksal birebir.

    Sayı: `Decimal`, `int` ya da sonlu `float` (bool sayı değildir). Metin baştaki / sondaki
    boşluk atılarak karşılaştırılır. Türler farklıysa ya da değer `None` ise `False`.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a.strip() == b.strip()
    x, y = _deger_donustur(a), _deger_donustur(b)
    if not isinstance(x, Decimal) or not isinstance(y, Decimal):
        return False
    tol = _deger_donustur(tolerans)
    if not isinstance(tol, Decimal) or isinstance(tolerans, bool) or tol < 0:
        raise ValueError("tolerans negatif olmayan bir sayı olmalı")
    return abs(x - y) <= tol


# ---------------------------------------------------------------------- şema


@lru_cache(maxsize=8)
def _sema(rules_dir: str, ad: str) -> dict[str, Any]:
    yol = Path(rules_dir) / SEMA_DIZINI / f"{ad}.schema.json"
    return json.loads(yol.read_text(encoding="utf-8"))


def sema(ad: str, rules_dir: Path | None = None) -> dict[str, Any]:
    """İçerik şeması: `ad` = `karar_tablosu` | `metamorfik_iliski`
    (`rules/schemas/icerik/<ad>.schema.json`)."""
    if ad not in (KARAR_TABLOSU_SEMASI, METAMORFIK_ILISKI_SEMASI):
        raise ValueError(f"bilinmeyen içerik şeması: {ad}")
    from tp_core.gateway.config import find_rules_dir

    return _sema(str(find_rules_dir(rules_dir)), ad)


def _yol(parcalar: Iterator[Any] | Sequence[Any]) -> str:
    cikti = ""
    for p in parcalar:
        cikti += f"[{p}]" if isinstance(p, int) else (f".{p}" if cikti else str(p))
    return cikti or "(kök)"


_JSON_TUR_ADI: Final = {
    "object": "nesne",
    "array": "liste",
    "string": "metin",
    "number": "sayı",
    "integer": "tam sayı",
    "boolean": "mantıksal",
    "null": "boş",
}


def _sema_mesaji(h: Any) -> str:
    """jsonschema hatasının Türkçe karşılığı (`alan.yolu: açıklama`)."""
    yol = _yol(h.absolute_path)
    kural, deger = h.validator, h.validator_value
    if "propertyNames" in h.absolute_schema_path:  # alt şemanın hatası alan ADINA aittir
        return f"{yol}: alan adı geçersiz: {h.instance!r}"
    if kural == "required":
        eksik = [a for a in deger if isinstance(h.instance, dict) and a not in h.instance]
        return f"{yol}: zorunlu alan eksik: {', '.join(eksik)}"
    if kural == "additionalProperties":
        izinli = set(h.schema.get("properties", {}))
        fazla = sorted(a for a in h.instance if a not in izinli)
        if deger is False:
            return f"{yol}: bilinmeyen alan: {', '.join(fazla)}"
    if kural == "type":
        turler = deger if isinstance(deger, list) else [deger]
        return f"{yol}: {' ya da '.join(_JSON_TUR_ADI.get(t, t) for t in turler)} olmalı"
    if kural == "enum":
        return f"{yol}: şu değerlerden biri olmalı: {', '.join(map(str, deger))}"
    if kural == "maxItems":
        return f"{yol}: en çok {deger} öğe olabilir"
    if kural == "minItems":
        return f"{yol}: en az {deger} öğe olmalı"
    if kural == "maxProperties":
        return f"{yol}: en çok {deger} alan olabilir"
    if kural == "minProperties":
        return f"{yol}: en az {deger} alan olmalı"
    if kural == "maxLength":
        return f"{yol}: en çok {deger} karakter olabilir"
    if kural == "minLength":
        return f"{yol}: boş olamaz" if deger == 1 else f"{yol}: en az {deger} karakter olmalı"
    if kural == "pattern":
        return f"{yol}: biçim geçersiz (beklenen desen: {deger})"
    if kural == "uniqueItems":
        return f"{yol}: yinelenen öğe var"
    return f"{yol}: geçersiz değer ({kural})"


def _sema_hatalari(icerik: Any, ad: str, rules_dir: Path | None) -> list[str]:
    from jsonschema import Draft202012Validator

    hatalar = sorted(
        Draft202012Validator(sema(ad, rules_dir)).iter_errors(icerik),
        key=lambda h: (_yol(h.absolute_path), str(h.validator)),
    )
    return list(dict.fromkeys(_sema_mesaji(h) for h in hatalar))


# ---------------------------------------------------------------------- karar tablosu


def _kolon_turleri(kolonlar: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {k["ad"]: k["tur"] for k in kolonlar}


def _ifade_denetle(
    etiket: str, metin: str, turler: Mapping[str, str], beklenen: str | None, hatalar: list[str]
) -> None:
    try:
        tur = ifade_turu(metin, turler)
    except IfadeHatasi as h:
        hatalar.append(f"{etiket}: {h}")
        return
    if beklenen is not None and tur != beklenen:
        hatalar.append(f"{etiket}: sonuç {_TUR_ADI[beklenen]} olmalı ({_TUR_ADI[tur]} bulundu)")


def _yuvarla_hanesi(metin: Any) -> int | None:
    """İfade en dışta `yuvarla(x, <sabit hane>)` ise hane; değilse None."""
    try:
        d = ayristir(metin)
    except (IfadeHatasi, TypeError):
        return None
    if d.cins == "islev" and d.deger == "yuvarla" and d.alt[1].cins == "sayi":
        hane = d.alt[1].deger
        if hane == hane.to_integral_value() and 0 <= hane <= AZAMI_HANE:
            return int(hane)
    return None


def _sabit_mi(metin: Any) -> bool:
    try:
        d = ayristir(metin)
    except (IfadeHatasi, TypeError):
        return False
    while d.cins == "tekli" and d.deger in ("-", "+"):
        d = d.alt[0]
    return d.cins == "sayi"


def cikti_hassasiyeti(kolon: Mapping[str, Any], satirlar: Sequence[Mapping[str, Any]]) -> Decimal:
    """Sayı çıktısının hassasiyeti (izin verilen en büyük tolerans).

    Sabit olmayan her satır ifadesi en dışta `yuvarla(x, h)` ise `10^-h` (birden çok hane varsa
    en incesi); değilse `TOLERANS_AZAMI` (0.01: kuruş). Tolerans bu değeri aşamaz: "1" toleranslı
    bir `bedava_adet` 6 ile 7 adet arasındaki farkı (tam da yakalanması gereken hatayı) gizlerdi.
    """
    ad = kolon.get("ad")
    haneler: list[int] = []
    for satir in satirlar:
        metin = (satir.get("cikti") or {}).get(ad)
        if metin is None or _sabit_mi(metin):
            continue
        hane = _yuvarla_hanesi(metin)
        if hane is None:
            return TOLERANS_AZAMI
        haneler.append(hane)
    if not haneler:
        return TOLERANS_AZAMI
    return Decimal(1).scaleb(-max(haneler))


def _tolerans_hatasi(kolon: Mapping[str, Any], satirlar: Sequence[Mapping[str, Any]]) -> str | None:
    try:
        tol = Decimal(str(kolon["tolerans"]))
    except (InvalidOperation, ValueError):
        return "sayı olmalı"
    if not tol.is_finite() or tol < 0:
        return "negatif olmayan bir sayı olmalı"
    azami = cikti_hassasiyeti(kolon, satirlar)
    if tol > azami:
        return (
            f"{tol} çıktının hassasiyetinden ({azami}) büyük olamaz; tolerans yalnız yuvarlama "
            "farkını örter (yuvarla(x, h) ile hassasiyet 10^-h olur)"
        )
    return None


def _tablo_hatalari(icerik: Mapping[str, Any]) -> list[str]:
    """Şemayı geçmiş içeriğin anlam denetimi (adlar, satırlar, ifadeler)."""
    hatalar: list[str] = []
    girdiler, ciktilar = icerik["girdiler"], icerik["ciktilar"]
    gorulen: set[str] = set()
    for bolum, kolonlar in (("girdiler", girdiler), ("ciktilar", ciktilar)):
        for i, kolon in enumerate(kolonlar):
            ad = kolon["ad"]
            if ad in AYRILMIS_ADLAR:
                hatalar.append(f"{bolum}[{i}].ad: '{ad}' ayrılmış sözcüktür, ad olamaz")
            if ad in gorulen:
                hatalar.append(f"{bolum}[{i}].ad: '{ad}' adı birden çok kez kullanılmış")
            gorulen.add(ad)
            if "tolerans" in kolon and kolon["tur"] != SAYI:
                hatalar.append(f"{bolum}[{i}].tolerans: yalnız sayı türündeki çıktıda verilir")
    for i, kolon in enumerate(ciktilar):
        if kolon["tur"] == SAYI and "tolerans" in kolon:
            hata = _tolerans_hatasi(kolon, icerik["satirlar"])
            if hata:
                hatalar.append(f"ciktilar[{i}].tolerans: {hata}")
    girdi_turleri = _kolon_turleri(girdiler)
    cikti_turleri = _kolon_turleri(ciktilar)
    satir_idleri: set[str] = set()
    for i, satir in enumerate(icerik["satirlar"]):
        sid = satir["id"]
        etiket = f"satirlar[{i}] ({sid})"
        if sid in satir_idleri:
            hatalar.append(f"{etiket}: satır kimliği birden çok kez kullanılmış")
        satir_idleri.add(sid)
        _ifade_denetle(f"{etiket} koşul", satir["kosul"], girdi_turleri, MANTIKSAL, hatalar)
        eksik = [a for a in cikti_turleri if a not in satir["cikti"]]
        if eksik:
            hatalar.append(f"{etiket}: çıktı eksik: {', '.join(eksik)}")
        for ad, metin in satir["cikti"].items():
            if ad not in cikti_turleri:
                hatalar.append(f"{etiket} çıktı '{ad}': tanımlı bir çıktı değil")
                continue
            _ifade_denetle(
                f"{etiket} çıktı '{ad}'", metin, girdi_turleri, cikti_turleri[ad], hatalar
            )
    return hatalar


def dogrula(icerik: dict[str, Any], rules_dir: Path | None = None) -> list[str]:
    """Karar tablosu içeriğinin hataları (boş liste = geçerli); en çok `AZAMI_HATA` metin.

    1. Şema (`rules/schemas/icerik/karar_tablosu.schema.json`): alanlar, sınırlar (12 girdi,
       12 çıktı, 60 satır, ifade 300 karakter). Şema hatası varsa yalnız onlar döner.
    2. Anlam: girdi ve çıktı adları tekil ve ayrılmış sözcük değil; satır kimlikleri tekil; her
       satır her çıktıyı tanımlar; `kosul` mantıksal, çıkış ifadesi çıktının türünde; ifadeler
       yalnız girdi adlarını kullanır.

    Boş `girdiler` / `ciktilar` / `satirlar` geçerlidir (taslak); PO'ya gönderim için
    `gonderim_hatalari`'na bakılır.
    """
    hatalar = _sema_hatalari(icerik, KARAR_TABLOSU_SEMASI, rules_dir)
    if not hatalar:
        hatalar = _tablo_hatalari(icerik)
    return hatalar[:AZAMI_HATA]


def gonderim_hatalari(icerik: dict[str, Any], rules_dir: Path | None = None) -> list[str]:
    """`dogrula` + PO onayına gönderilecek tablonun tamlığı: en az bir kabul kriteri, bir girdi,
    bir çıktı ve bir satır."""
    hatalar = dogrula(icerik, rules_dir)
    if hatalar:
        return hatalar
    for alan, ne in (
        ("ac_refs", "kabul kriteri"),
        ("girdiler", "girdi"),
        ("ciktilar", "çıktı"),
        ("satirlar", "satır"),
    ):
        if not icerik[alan]:
            hatalar.append(f"{alan}: en az bir {ne} olmalı")
    return hatalar


@dataclass(frozen=True)
class Degerlendirme:
    """`degerlendir` sonucu.

    - `satir_id`: koşulu sağlayan ilk satır; hiçbiri sağlamıyorsa (ya da değerlendirilemediyse)
      `None` ("satır yok" uyuşmazlık değildir).
    - `ciktilar`: çıktı adı → `Decimal` | `str` | `bool` (satır yoksa boş).
    - `eksik_girdiler`: tablonun ifadelerinde kullanılan ama verilmemiş girdiler (tanım sırasıyla).
      Doluysa değerlendirme yapılmamıştır.
    - `hata`: değerlendirme sorunu (geçersiz tablo, geçersiz girdi değeri, sıfıra bölme …).
    """

    satir_id: str | None = None
    ciktilar: dict[str, Any] = field(default_factory=dict)
    eksik_girdiler: list[str] = field(default_factory=list)
    hata: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON'a uygun sözlük: sayılar metin olarak (`"150.00"`), diğerleri olduğu gibi."""
        return {
            "satir_id": self.satir_id,
            "ciktilar": {
                ad: str(d) if isinstance(d, Decimal) else d for ad, d in self.ciktilar.items()
            },
            "eksik_girdiler": list(self.eksik_girdiler),
            "hata": self.hata,
        }


def girdi_donustur(deger: Any, tur: str) -> Any:
    """Verilen girdi değerini kolon türüne çevirir; uymuyorsa `IfadeHatasi`.

    - `sayi`: `Decimal`, `int`, sonlu `float`, ya da sayı metni (`"25.00"`; değilse
      `sayi_ayristir` ile `"25,00 TL"`).
    - `metin`: `str`.
    - `mantiksal`: `bool` ya da `"dogru"` / `"yanlis"` / `"true"` / `"false"`.
    """
    if tur == SAYI:
        if isinstance(deger, str):
            metin = deger.strip()
            sayi = Decimal(metin) if _KESIN_SAYI.match(metin) else sayi_ayristir(metin)
        else:
            sayi = None if isinstance(deger, bool) else _deger_donustur(deger)
        if not isinstance(sayi, Decimal):
            raise IfadeHatasi("sayı bekleniyor")
        if not sayi.is_zero() and sayi.adjusted() >= AZAMI_BUYUKLUK:
            raise IfadeHatasi("sayı çok büyük")
        return sayi
    if tur == METIN:
        if not isinstance(deger, str):
            raise IfadeHatasi("metin bekleniyor")
        return deger
    if tur == MANTIKSAL:
        if isinstance(deger, bool):
            return deger
        if isinstance(deger, str) and deger.strip().lower() in ("dogru", "true"):
            return True
        if isinstance(deger, str) and deger.strip().lower() in ("yanlis", "false"):
            return False
        raise IfadeHatasi("mantıksal değer (dogru / yanlis) bekleniyor")
    raise IfadeHatasi(f"geçersiz tür: {tur}")


def _kullanilan_adlar(ifadeler: Sequence[str]) -> set[str]:
    cikti: dict[str, None] = {}
    for metin in ifadeler:
        _adlari_topla(ayristir(metin), cikti)
    return set(cikti)


def degerlendir(
    icerik: dict[str, Any], girdiler: dict[str, Any], rules_dir: Path | None = None
) -> Degerlendirme:
    """Tabloyu `girdiler` ile değerlendirir: koşulu sağlayan İLK satırın çıktıları.

    Hata fırlatmaz. Tablo geçersizse ya da bir girdi değeri türüne uymuyorsa `hata` dolar.
    Tablonun ifadelerinde geçen bir girdi verilmemişse (`None` dahil) `eksik_girdiler` dolar ve
    değerlendirme yapılmaz. Hiçbir satır eşleşmezse `satir_id` `None`, `ciktilar` boştur.
    Tabloda tanımlı olmayan fazladan girdiler yok sayılır.
    """
    hatalar = dogrula(icerik, rules_dir)
    if hatalar:
        return Degerlendirme(hata="karar tablosu geçersiz: " + "; ".join(hatalar[:3]))
    if not isinstance(girdiler, Mapping):
        return Degerlendirme(hata="girdiler ad → değer sözlüğü olmalı")
    satirlar = icerik["satirlar"]
    kullanilan = _kullanilan_adlar(
        [m for s in satirlar for m in (s["kosul"], *s["cikti"].values())]
    )
    ortam: dict[str, Any] = {}
    eksik: list[str] = []
    for kolon in icerik["girdiler"]:
        ad = kolon["ad"]
        if girdiler.get(ad) is None:
            if ad in kullanilan:
                eksik.append(ad)
            continue
        try:
            ortam[ad] = girdi_donustur(girdiler[ad], kolon["tur"])
        except IfadeHatasi as h:
            return Degerlendirme(hata=f"girdi '{ad}': {h}")
    if eksik:
        return Degerlendirme(eksik_girdiler=eksik)
    ctx = _baglam()
    for satir in satirlar:
        sid = satir["id"]
        try:
            if _hesapla(ayristir(satir["kosul"]), ortam, ctx) is not True:
                continue
        except IfadeHatasi as h:
            return Degerlendirme(hata=f"satır {sid} koşul: {h}")
        ciktilar: dict[str, Any] = {}
        for kolon in icerik["ciktilar"]:
            ad = kolon["ad"]
            try:
                ciktilar[ad] = _hesapla(ayristir(satir["cikti"][ad]), ortam, ctx)
            except IfadeHatasi as h:
                return Degerlendirme(satir_id=sid, hata=f"satır {sid} çıktı '{ad}': {h}")
        return Degerlendirme(satir_id=sid, ciktilar=ciktilar)
    return Degerlendirme()


def toleranslar(icerik: Mapping[str, Any]) -> dict[str, Decimal]:
    """Çıktı adı → tolerans (`esit_mi` için); `tolerans` verilmemiş ya da sayı olmayan çıktıda 0."""
    return {k["ad"]: Decimal(k.get("tolerans", "0")) for k in icerik.get("ciktilar", [])}


# ---------------------------------------------------------------------- sınır analizi

AZAMI_ORNEK: Final = 200
_PARA_BIRIMLERI: Final = frozenset({"tl", "₺", "try", "usd", "eur", "$", "€", "kurus", "kuruş"})
_TEMSILI_SAYI: Final = Decimal(100)
_BASKA_METIN: Final = "baska"


def _sabit_sayi(d: Dugum) -> Decimal | None:
    """Sabit sayı düğümü (`7`, `-5`, `750.00`) → değer; değilse None."""
    isaret = 1
    while d.cins == "tekli" and d.deger in ("-", "+"):
        if d.deger == "-":
            isaret = -isaret
        d = d.alt[0]
    if d.cins == "sayi":
        return d.deger if isaret == 1 else -d.deger
    return None


def _dugumler(d: Dugum) -> Iterator[Dugum]:
    yield d
    for alt in d.alt:
        yield from _dugumler(alt)


def _ondalik(deger: Decimal) -> int:
    us = deger.as_tuple().exponent
    return -us if isinstance(us, int) and us < 0 else 0


def _sinir_adaylari(icerik: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Girdi adı → sınır değerleri (koşullardaki sabitlerin bir adım altı / kendisi / üstü,
    `ad // k` ve `ad % k`'da k ve 2k çevresi; mantıksal: doğru/yanlış; metin: karşılaştırılan
    sabitler + başka bir değer)."""
    turler = _kolon_turleri(icerik["girdiler"])
    birimler = {k["ad"]: str(k.get("birim") or "").strip().lower() for k in icerik["girdiler"]}
    sabitler: dict[str, list[Decimal]] = {ad: [] for ad in turler}
    bolenler: dict[str, list[Decimal]] = {ad: [] for ad in turler}
    metinler: dict[str, list[str]] = {ad: [] for ad in turler}
    ifadeler = [m for s in icerik["satirlar"] for m in (s["kosul"], *s["cikti"].values())]
    for metin in ifadeler:
        try:
            kok = ayristir(metin)
        except IfadeHatasi:
            continue
        for d in _dugumler(kok):
            if d.cins != "ikili" or len(d.alt) != 2:
                continue
            sol, sag = d.alt
            for ad_d, sabit_d in ((sol, sag), (sag, sol)):
                if ad_d.cins != "ad" or ad_d.deger not in turler:
                    continue
                ad = ad_d.deger
                if d.deger in _KARSILASTIRMA:
                    if sabit_d.cins == "metin":
                        metinler[ad].append(sabit_d.deger)
                    elif (c := _sabit_sayi(sabit_d)) is not None:
                        sabitler[ad].append(c)
                elif d.deger in ("//", "%") and ad_d is sol:
                    c = _sabit_sayi(sabit_d)
                    if c is not None and c > 0:
                        bolenler[ad].append(c)
    out: dict[str, list[Any]] = {}
    for ad, tur in turler.items():
        if tur == MANTIKSAL:
            out[ad] = [True, False]
            continue
        if tur == METIN:
            gorulen = list(dict.fromkeys(metinler[ad]))
            if gorulen:
                baska = _BASKA_METIN
                while baska in gorulen:
                    baska += "_"
                gorulen.append(baska)
            out[ad] = gorulen or ["ornek"]
            continue
        hepsi = sabitler[ad] + bolenler[ad]
        hane = max((_ondalik(c) for c in hepsi), default=0)
        if birimler[ad] in _PARA_BIRIMLERI:
            hane = max(hane, 2)
        adim = Decimal(1).scaleb(-hane)
        degerler: set[Decimal] = set()
        for c in sabitler[ad]:
            degerler.update((c - adim, c, c + adim))
        for k in bolenler[ad]:
            for kat in (k, 2 * k):
                degerler.update((kat - adim, kat, kat + adim))
        negatif_olabilir = any(c < 0 for c in hepsi)
        sonuc = sorted({d.quantize(adim) for d in degerler if negatif_olabilir or d >= 0})
        out[ad] = sonuc or [_TEMSILI_SAYI.quantize(adim)]
    return out


def _izgara(adaylar: Mapping[str, Sequence[Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Tam kartezyen çarpım `AZAMI_ORNEK`'i aşmıyorsa o; aşıyorsa her girdiyi tek tek değiştiren
    (diğerleri orta değerde) örnekler. İkinci değer: ızgara sınırlandı mı."""
    adlar = list(adaylar)
    toplam = 1
    for ad in adlar:
        toplam *= max(1, len(adaylar[ad]))
    if toplam <= AZAMI_ORNEK:
        ornekler: list[dict[str, Any]] = [{}]
        for ad in adlar:
            ornekler = [{**o, ad: d} for o in ornekler for d in adaylar[ad]]
        return ornekler, False
    taban = {ad: adaylar[ad][len(adaylar[ad]) // 2] for ad in adlar}
    out = [dict(taban)]
    for ad in adlar:
        for d in adaylar[ad]:
            if d != taban[ad]:
                out.append({**taban, ad: d})
    return out[:AZAMI_ORNEK], True


def _goster_deger(deger: Any) -> Any:
    return str(deger) if isinstance(deger, Decimal) else deger


def _ornek_metni(girdiler: Mapping[str, Any]) -> str:
    return ", ".join(f"{a}={_goster_deger(d)}" for a, d in girdiler.items())


def sinir_ornekleri(icerik: dict[str, Any], rules_dir: Path | None = None) -> dict[str, Any]:
    """Tablonun sınır örnekleri ve satır uyarıları (PO'ya göndermeden önce kalite görünümü).

    Girdi değerleri koşullardaki sabitlerden kendiliğinden üretilir (`adet >= 7` → 6, 7, 8;
    `sepet_tutari < 750` ve birim TL → 749.99, 750.00, 750.01; `adet // 7` → 6, 7, 8, 13, 14,
    15) ve her örnek `degerlendir` ile değerlendirilir. Dönüş:
    `{ornekler: [{girdiler, satir_id, ciktilar, hata}], uyarilar: [{tur, mesaj, satirlar?,
    girdiler?}]}`. Uyarı türleri:

    - `ortusme`: iki (genel olmayan) satırın koşulu aynı örnekte sağlanıyor ve çıktıları farklı;
      ilk satır geçerli olur — bilinçli değilse sınır yorumu PO'ya sorulmalı.
    - `hic_eslesmez`: satırın koşulu hiçbir örnekte sağlanmıyor.
    - `golgede`: satırın koşulu sağlanıyor ama her seferinde önceki bir satır seçiliyor.
    - `satir_yok`: hiçbir satırın eşleşmediği örnekler (sonuç "satır yok" olur).
    - `hata`: değerlendirme hatası (sıfıra bölme …).
    - `ornek_sinirli`: girdi çok olduğundan örnekler tek tek değiştirilerek üretildi.
    - `gecersiz`: tablo geçersiz ya da eksik; örnek üretilmedi.

    Izgara sezgiseldir (yalnız sabitle karşılaştırmaları görür); boş uyarı listesi tablonun
    doğru olduğunu kanıtlamaz.
    """
    hatalar = gonderim_hatalari(icerik, rules_dir)
    if hatalar:
        return {
            "ornekler": [],
            "uyarilar": [
                {
                    "tur": "gecersiz",
                    "mesaj": "Tablo geçersiz ya da eksik: " + "; ".join(hatalar[:3]),
                }
            ],
        }
    satirlar = icerik["satirlar"]
    turler = _kolon_turleri(icerik["girdiler"])
    izgara, sinirli = _izgara(_sinir_adaylari(icerik))
    ornekler: list[dict[str, Any]] = []
    uyarilar: list[dict[str, Any]] = []
    saglanan: dict[str, int] = {s["id"]: 0 for s in satirlar}
    secilen: dict[str, int] = {s["id"]: 0 for s in satirlar}
    ortusme: dict[tuple[str, str], dict[str, Any]] = {}
    satir_yok: list[dict[str, Any]] = []
    hatali: list[tuple[dict[str, Any], str]] = []
    ctx = _baglam()
    for girdiler in izgara:
        sonuc = degerlendir(icerik, girdiler, rules_dir)
        gosterilen = {a: _goster_deger(d) for a, d in girdiler.items()}
        ornekler.append({"girdiler": gosterilen, **sonuc.as_dict()})
        ornekler[-1].pop("eksik_girdiler", None)
        if sonuc.hata:
            hatali.append((gosterilen, sonuc.hata))
            continue
        if sonuc.satir_id is None:
            satir_yok.append(gosterilen)
        else:
            secilen[sonuc.satir_id] += 1
        ortam = {a: girdi_donustur(d, turler[a]) for a, d in girdiler.items()}
        dogru_satirlar: list[tuple[str, dict[str, Any] | None]] = []
        for satir in satirlar:
            try:
                if _hesapla(ayristir(satir["kosul"]), ortam, ctx) is not True:
                    continue
            except IfadeHatasi:
                continue
            saglanan[satir["id"]] += 1
            if satir["kosul"].strip() == "dogru":
                continue
            try:
                cikti = {a: _hesapla(ayristir(m), ortam, ctx) for a, m in satir["cikti"].items()}
            except IfadeHatasi:
                cikti = None
            dogru_satirlar.append((satir["id"], cikti))
        for i, (a, ca) in enumerate(dogru_satirlar):
            for b, cb in dogru_satirlar[i + 1 :]:
                if ca is not None and ca == cb:
                    continue
                ortusme.setdefault((a, b), gosterilen)
    for (a, b), girdiler in ortusme.items():
        uyarilar.append(
            {
                "tur": "ortusme",
                "satirlar": [a, b],
                "girdiler": girdiler,
                "mesaj": (
                    f"{a} ve {b} koşulları aynı girdide birlikte sağlanıyor "
                    f"({_ornek_metni(girdiler)}); ilk satır {a} geçerli olur, {b} satırının "
                    "çıktıları farklı. Bilinçli değilse sınır yorumunu PO'ya sorun."
                ),
            }
        )
    for satir in satirlar:
        sid = satir["id"]
        if saglanan[sid] == 0:
            uyarilar.append(
                {
                    "tur": "hic_eslesmez",
                    "satirlar": [sid],
                    "mesaj": (
                        f"{sid} koşulu hiçbir sınır örneğinde sağlanmıyor; satır hiç "
                        "seçilmeyebilir."
                    ),
                }
            )
        elif secilen[sid] == 0:
            uyarilar.append(
                {
                    "tur": "golgede",
                    "satirlar": [sid],
                    "mesaj": (
                        f"{sid} koşulu sağlanan her örnekte önceki bir satır seçiliyor; {sid} hiç "
                        "uygulanmıyor."
                    ),
                }
            )
    if satir_yok:
        uyarilar.append(
            {
                "tur": "satir_yok",
                "girdiler": satir_yok[0],
                "mesaj": (
                    f"{len(satir_yok)} örnekte hiçbir satır eşleşmiyor (ör. "
                    f"{_ornek_metni(satir_yok[0])}); kapsanmayan durum PO'ya sorulmalı ya da genel "
                    "bir satır (kosul: dogru) eklenmeli."
                ),
            }
        )
    for girdiler, hata in hatali[:5]:
        uyarilar.append(
            {"tur": "hata", "girdiler": girdiler, "mesaj": f"{_ornek_metni(girdiler)}: {hata}"}
        )
    if sinirli:
        uyarilar.append(
            {
                "tur": "ornek_sinirli",
                "mesaj": (
                    f"Girdi çok olduğundan örnekler her girdi tek tek değiştirilerek üretildi "
                    f"(en çok {AZAMI_ORNEK})."
                ),
            }
        )
    return {"ornekler": ornekler, "uyarilar": uyarilar}


# ---------------------------------------------------------------------- metamorfik ilişki


def iliski_dogrula(
    icerik: dict[str, Any],
    tablo_icerik: Mapping[str, Any] | None = None,
    rules_dir: Path | None = None,
) -> list[str]:
    """Metamorfik ilişki içeriğinin hataları (boş liste = geçerli).

    Şema (`rules/schemas/icerik/metamorfik_iliski.schema.json`) ve her ifadenin sözdizimi her
    zaman denetlenir. `tablo_icerik` (geçerli bir karar tablosu içeriği) verilirse adlar ve
    türler de denetlenir: `on_kosul` kaynak GİRDİLER üzerinde mantıksal; `donusum` anahtarları
    girdi, `iliski` anahtarları çıktı adıdır; iki bölümün ifadeleri kaynak girdi VE çıktı
    adlarını kullanabilir ve hedef kolonun türünde olmalıdır.
    """
    hatalar = _sema_hatalari(icerik, METAMORFIK_ILISKI_SEMASI, rules_dir)
    if hatalar:
        return hatalar[:AZAMI_HATA]
    bolumler = (("donusum", "girdi"), ("iliski", "çıktı"))
    if tablo_icerik is None:
        for etiket, metin in (
            ("on_kosul", icerik["on_kosul"]),
            *((f"{b}.{ad}", m) for b, _ in bolumler for ad, m in icerik[b].items()),
        ):
            try:
                ayristir(metin)
            except IfadeHatasi as h:
                hatalar.append(f"{etiket}: {h}")
        return hatalar[:AZAMI_HATA]
    girdi_turleri = _kolon_turleri(tablo_icerik["girdiler"])
    cikti_turleri = _kolon_turleri(tablo_icerik["ciktilar"])
    hepsi = {**girdi_turleri, **cikti_turleri}
    _ifade_denetle("on_kosul", icerik["on_kosul"], girdi_turleri, MANTIKSAL, hatalar)
    for (bolum, ne), hedefler in zip(bolumler, (girdi_turleri, cikti_turleri), strict=True):
        for ad, metin in icerik[bolum].items():
            if ad not in hedefler:
                hatalar.append(f"{bolum}.{ad}: tabloda böyle bir {ne} yok")
                continue
            _ifade_denetle(f"{bolum}.{ad}", metin, hepsi, hedefler[ad], hatalar)
    return hatalar[:AZAMI_HATA]


@dataclass(frozen=True)
class IliskiSonucu:
    """`iliski_uygula` sonucu.

    - `gecerli`: `on_kosul` sağlandı ve dönüşüm hesaplandı.
    - `girdiler`: türetilen case'in girdileri (kaynak girdiler + `donusum` ile değişenler).
    - `ciktilar`: ilişkinin hesapladığı yeni beklenen çıktılar (yalnız `iliski` anahtarları).
    - `eksik`: ifadelerde kullanılan ama kaynakta bulunmayan adlar (doluysa hesaplanmamıştır).
    - `hata`: değerlendirme sorunu; `on_kosul` sağlanmadıysa `None` kalır (`gecerli=False`).
    """

    gecerli: bool = False
    girdiler: dict[str, Any] = field(default_factory=dict)
    ciktilar: dict[str, Any] = field(default_factory=dict)
    eksik: list[str] = field(default_factory=list)
    hata: str | None = None


def iliski_uygula(
    icerik: Mapping[str, Any], girdiler: Mapping[str, Any], ciktilar: Mapping[str, Any]
) -> IliskiSonucu:
    """İlişkiyi kaynak case'in değerlerine uygular (§4.5); hata fırlatmaz.

    `girdiler` / `ciktilar`: kaynak case'in doğrulanmış olgularından ad → değer (Decimal | int |
    str | bool). `on_kosul` kaynak girdilerle, `donusum` ve `iliski` kaynak girdi + çıktılarla
    hesaplanır (tablodan değil). İçeriğin `iliski_dogrula`'dan geçmiş olması beklenir.
    """
    try:
        kaynak_girdi = {a: _zorunlu_deger(a, d) for a, d in girdiler.items() if d is not None}
        kaynak_cikti = {a: _zorunlu_deger(a, d) for a, d in ciktilar.items() if d is not None}
        ortam = {**kaynak_girdi, **kaynak_cikti}
        eksik = sorted(set(adlar(icerik["on_kosul"])) - set(kaynak_girdi))
        for bolum in ("donusum", "iliski"):
            for metin in icerik[bolum].values():
                eksik.extend(a for a in adlar(metin) if a not in ortam and a not in eksik)
        if eksik:
            return IliskiSonucu(eksik=eksik)
        ctx = _baglam()
        if _hesapla(ayristir(icerik["on_kosul"]), kaynak_girdi, ctx) is not True:
            return IliskiSonucu()
        yeni_girdi = dict(kaynak_girdi)
        for ad, metin in icerik["donusum"].items():
            yeni_girdi[ad] = _hesapla(ayristir(metin), ortam, ctx)
        yeni_cikti = {
            ad: _hesapla(ayristir(metin), ortam, ctx) for ad, metin in icerik["iliski"].items()
        }
    except IfadeHatasi as h:
        return IliskiSonucu(hata=str(h))
    return IliskiSonucu(gecerli=True, girdiler=yeni_girdi, ciktilar=yeni_cikti)


def _zorunlu_deger(ad: str, deger: Any) -> Any:
    cevrilen = _deger_donustur(deger)
    if cevrilen is None:
        raise IfadeHatasi(f"'{ad}' için geçersiz değer")
    return cevrilen


__all__ = [
    "AYRILMIS_ADLAR",
    "AZAMI_CIKTI",
    "AZAMI_DERINLIK",
    "AZAMI_GIRDI",
    "AZAMI_IFADE_UZUNLUGU",
    "AZAMI_ORNEK",
    "AZAMI_SATIR",
    "TOLERANS_AZAMI",
    "Degerlendirme",
    "Dugum",
    "IfadeHatasi",
    "IliskiSonucu",
    "adlar",
    "ayristir",
    "cikti_hassasiyeti",
    "degerlendir",
    "dogrula",
    "esit_mi",
    "girdi_donustur",
    "gonderim_hatalari",
    "hesapla",
    "ifade_turu",
    "iliski_dogrula",
    "iliski_uygula",
    "sayi_ayristir",
    "sayi_bicimle",
    "sema",
    "sinir_ornekleri",
    "toleranslar",
]
