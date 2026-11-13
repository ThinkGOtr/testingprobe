"""Başarısız doğrulamanın case'teki yeri (012 §4.4 inceltmesi; review tur 1 O6).

Karar tablosu inceltmesi yalnızca eşleşen karşılaştırma **başarısız adıma** aitse uygulanır:
karşılaştırmanın `alan`'ı (ör. `steps[3].expected`) hatanın geldiği case alanlarından biri
olmalıdır.
Değerin tesadüfen eşit olması (ör. sepet sayacında beklenen 1 ile bedava adet 1) yetmez.

Hatanın case alanları deterministik olarak şuradan çıkarılır (sırayla; hiçbiri çıkmazsa `None` →
inceltme yok, bugünkü davranış):

1. **Adım başlığı** — Playwright `failure.step.path` (`test.step("S4 — …")`): en derindeki `S<n>`
   başlıklı adım → `steps[i].expected` (case'te o kimlikte adım yoksa `None`).
2. **Üretilen testin satırı** — `failure.test_location.line` (Playwright) ya da test sınıfı
   çerçevesinin satırı (Java/Surefire) üretilen testin kaynağında (`script.icerik`, şablon:
   `rules/templates/`) bir çağrı satırı olmalıdır:
   - `// S<n> — …` adım grubundaki eylem çağrısı → `steps[i].expected`;
   - `// Beklenen sonuç` bloğundaki doğrulama (codegen `step_mapping` `expects`): argümanlarından
     hatanın beklenen değerine eşit olanlar; codegen kontrolü her beklenen değerin case'in
     `expected` / `expected_result` metninde geçmesini ister (`codegen.checks.check_mapping`),
     değerin geçtiği beklenen alanları döner. Değer birden çok **adımda** geçiyorsa (ör. "Sepet
     sayacı 1" ve "bedava adet 1") hangi adımın doğrulandığı belirsizdir → `None`.
     `expected_result` (case düzeyindeki özet) tek adımla birlikte kabul edilir.

Kaynak metinler (test kaynağı, hata metni) güvenilmez: yalnızca kalıp eşlenir, kod çalıştırılmaz.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from tp_core.features.codegen.normalize import find_source
from tp_core.features.karar_tablosu.ifade import sayi_ayristir

BEKLENEN_SONUC_ALANI = "expected_result"
_ADIM_ALANI = re.compile(r"^steps\[(?P<i>\d{1,3})\]\.")
_ADIM_BASLIGI = re.compile(r"^\s*(?P<sid>S\d{1,3})(?:\s*[—–:\-.]|\s|$)")
_TS_CAGRI = re.compile(r"^\s*await\s+[A-Za-z_$][\w$]*\.[A-Za-z_$][\w$]*\((?P<args>.*)\);\s*$")
_JAVA_CAGRI = re.compile(r"^\s*[A-Za-z_]\w*\(\)\.[A-Za-z_]\w*\((?P<args>.*)\);\s*$")
_ADIM_YORUMU = re.compile(r"^\s*//\s*(?P<sid>\S+)\s+—(?:\s|$)")
_BEKLENEN_YORUMU = re.compile(r"^\s*//\s*Beklenen sonuç\b")
_JAVA_SAYI = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[LlDdFf]?$")
MAX_KAYNAK_SATIRI = 5000


def adim_no(alan: str | None) -> int | None:
    """`steps[3].expected` → 3; adım alanı değilse None."""
    m = _ADIM_ALANI.match(alan or "")
    return int(m.group("i")) if m else None


def _adim_indeksi(icerik: Mapping[str, Any], sid: str) -> int | None:
    adimlar = icerik.get("steps")
    if not isinstance(adimlar, list):
        return None
    bulunan = [
        i for i, a in enumerate(adimlar) if isinstance(a, Mapping) and str(a.get("id")) == sid
    ]
    return bulunan[0] if len(bulunan) == 1 else None


def _adim_alani(icerik: Mapping[str, Any], sid: str) -> frozenset[str] | None:
    i = _adim_indeksi(icerik, sid)
    return frozenset({f"steps[{i}].expected"}) if i is not None else None


def beklenen_alanlari(icerik: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Case'in beklenen metinleri: `[(alan yolu, metin)]` (`codegen.checks.case_texts` sırası)."""
    out: list[tuple[str, str]] = []
    adimlar = icerik.get("steps")
    for i, a in enumerate(adimlar if isinstance(adimlar, list) else []):
        if isinstance(a, Mapping) and isinstance(a.get("expected"), str) and a["expected"]:
            out.append((f"steps[{i}].expected", a["expected"]))
    sonuc = icerik.get(BEKLENEN_SONUC_ALANI)
    if isinstance(sonuc, str) and sonuc:
        out.append((BEKLENEN_SONUC_ALANI, sonuc))
    return out


def _parcala(metin: str) -> list[str] | None:
    """Argüman listesini tırnak dışındaki virgüllerden böler (kaçışlar korunur)."""
    out: list[str] = []
    buf: list[str] = []
    tirnak = False
    kacis = False
    for ch in metin:
        if tirnak:
            buf.append(ch)
            if kacis:
                kacis = False
            elif ch == "\\":
                kacis = True
            elif ch == '"':
                tirnak = False
            continue
        if ch == '"':
            tirnak = True
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if tirnak:
        return None
    son = "".join(buf).strip()
    if son or out:
        out.append(son)
    return out


def cagri_argumanlari(satir: str, *, java: bool) -> list[Any] | None:
    """Üretilen testteki çağrı satırının literal argümanları; çağrı satırı değilse None.

    TypeScript şablonu JSON literal basar (`ts_literal`); Java şablonu String / int / long (`L`) /
    double / boolean (`java_literal`). Başka bir şey (değişken, ifade) → None."""
    m = (_JAVA_CAGRI if java else _TS_CAGRI).match(satir)
    if m is None:
        return None
    parcalar = _parcala(m.group("args"))
    if parcalar is None:
        return None
    out: list[Any] = []
    for p in parcalar:
        if p.startswith('"'):
            try:
                out.append(json.loads(p))
            except ValueError:
                return None
        elif p in ("true", "false"):
            out.append(p == "true")
        elif _JAVA_SAYI.match(p) if java else re.match(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$", p):
            try:
                out.append(Decimal(p.rstrip("LlDdFf")))
            except InvalidOperation:
                return None
        else:
            return None
    return out


def _deger(x: Any) -> Any:
    if isinstance(x, bool):
        return x
    if isinstance(x, int | Decimal):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(repr(x))
    if isinstance(x, str):
        m = x.strip()
        if len(m) >= 2 and m[0] == m[-1] and m[0] in "\"'`":
            m = m[1:-1].strip()
        sayi = sayi_ayristir(m)
        return sayi if sayi is not None else m.casefold()
    return None


def ayni_deger(a: Any, b: Any) -> bool:
    """Argüman ile hatanın beklenen metni aynı değer mi (sayı ise sayısal, metin ise harf
    duyarsız)."""
    x, y = _deger(a), _deger(b)
    if x is None or y is None or isinstance(x, bool) != isinstance(y, bool):
        return False
    if isinstance(x, Decimal) and isinstance(y, Decimal):
        return x == y
    return type(x) is type(y) and x == y


def _degerin_alanlari(icerik: Mapping[str, Any], degerler: Sequence[Any]) -> frozenset[str] | None:
    alanlar: set[str] = set()
    for alan, metin in beklenen_alanlari(icerik):
        for d in degerler:
            v = int(d) if isinstance(d, Decimal) and d == d.to_integral_value() else d
            v = float(v) if isinstance(v, Decimal) else v
            if find_source(v, [metin]) is not None:
                alanlar.add(alan)
    adimlar = {n for a in alanlar if (n := adim_no(a)) is not None}
    if not alanlar or len(adimlar) > 1:
        return None
    return frozenset(alanlar)


def _satir_bloku(satirlar: Sequence[str], idx: int) -> tuple[str, str | None] | None:
    """Satırın şablondaki bloğu: (`adim`, sid) ya da (`beklenen`, None); bulunamazsa None."""
    for j in range(idx - 1, -1, -1):
        s = satirlar[j]
        if _BEKLENEN_YORUMU.match(s):
            return "beklenen", None
        m = _ADIM_YORUMU.match(s)
        if m:
            return "adim", m.group("sid")
    return None


def hata_alanlari(
    icerik: Mapping[str, Any] | None,
    *,
    adim_yolu: Sequence[str] = (),
    kaynak: str | None = None,
    satir: int | None = None,
    java: bool = False,
    beklenen: str | None = None,
) -> frozenset[str] | None:
    """Başarısız doğrulamanın case alanları (modül belgesi); belirlenemiyorsa None."""
    if not isinstance(icerik, Mapping):
        return None
    for baslik in reversed(list(adim_yolu)):
        m = _ADIM_BASLIGI.match(str(baslik or ""))
        if m:
            return _adim_alani(icerik, m.group("sid"))
    if not kaynak or not isinstance(satir, int) or isinstance(satir, bool) or satir < 1:
        return None
    satirlar = kaynak.splitlines()[:MAX_KAYNAK_SATIRI]
    if satir > len(satirlar):
        return None
    args = cagri_argumanlari(satirlar[satir - 1], java=java)
    blok = _satir_bloku(satirlar, satir - 1) if args is not None else None
    if blok is None:
        return None
    tur, sid = blok
    if tur == "adim":
        return _adim_alani(icerik, sid or "")
    if beklenen is None:
        return None
    degerler = [a for a in args or [] if ayni_deger(a, beklenen)]
    if not degerler:
        return None  # doğrulamanın argümanları hatanın beklenen değerini taşımıyor
    return _degerin_alanlari(icerik, degerler)
