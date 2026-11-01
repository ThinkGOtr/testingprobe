"""Locator onarımının saf (G/Ç'siz) parçaları — TEKNIK-TASARIM §8.7, Constitution VI.

- Hata metnindeki Playwright locator ifadesinden testId zinciri (`getByTestId('kapsayıcı')
  .getByTestId('aranan')`) çıkarılır.
- toolchain `/symbols` tablosunda kırık testId'yi taşıyan locator anahtarı bulunur.
- `locators.ts` metninde YALNIZCA o anahtarın `testId` string literal'i değiştirilir (metin
  düzeyinde, kesin konum). Anahtar kümesi, rol, ad, niyet ve `within` dokunulmaz; değişiklik
  sonradan satır farkıyla yeniden doğrulanır (çekirdekteki koruma; CI/toolchain'de AST koruması).

Bu modül model çağırmaz ve dosya sistemi/ağa dokunmaz; birim testleri doğrudan çağırır.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# data-testid değeri olarak kabul edilen biçim (tırnak, boşluk, ters bölü yok).
# `\Z` (ve `$` değil): `$` sondaki "\n"'den önce de eşleşir; DOM'dan okunan "cart-add\n" geçmemeli.
TESTID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
LOCATORS_FILE_RE = re.compile(r"\A(?:[\w.-]+/)*pages/(?:[\w.-]+/)*locators\.ts\Z")
_KEY_RE = re.compile(r"\A[A-Za-z_$][\w$]*\Z")
_Q = r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")"""
_TESTID_CALL_RE = re.compile(r"getByTestId\(\s*" + _Q + r"\s*\)")
_TESTID_ATTR_RE = re.compile(r"""\[data-testid=\\?["']([^"'\\\]]+)\\?["']\]""")
_PATHS_BLOCK_RE = re.compile(r"export\s+const\s+paths\s*=\s*\{(?P<body>[^}]*)\}", re.S)
_PATH_ENTRY_RE = re.compile(r"""(?P<key>[A-Za-z_$][\w$]*)\s*:\s*(["'])(?P<val>/[^"']*)\2""")


class PatchError(ValueError):
    """Yama güvenle üretilemedi (anahtar bulunamadı / birden çok / beklenmeyen fark)."""


@dataclass(frozen=True)
class LocatorRef:
    """Sembol tablosundaki bir locator anahtarı."""

    dosya: str  # forge köküne göre (e2e/pages/catalog/locators.ts)
    sinif: str  # page object sınıfı (CatalogPage)
    anahtar: str  # addToCart
    test_id: str
    rol: str
    ad: str
    niyet: str
    within: str | None = None
    grup: str | None = None  # locators.ts'teki dışa aktarılan nesne (catalog), biliniyorsa
    kardesler: dict[str, dict[str, Any]] = field(default_factory=dict, compare=False)

    @property
    def tam_ad(self) -> str:
        return f"{self.grup}.{self.anahtar}" if self.grup else self.anahtar

    def as_dict(self) -> dict[str, Any]:
        return {
            "tam_ad": self.tam_ad,
            "dosya": self.dosya,
            "sinif": self.sinif,
            "anahtar": self.anahtar,
            "test_id": self.test_id,
            "rol": self.rol,
            "ad": self.ad,
            "niyet": self.niyet,
            "within": self.within,
        }


def _unquote(single: str | None, double: str | None) -> str | None:
    raw = single if single is not None else double
    if raw is None:
        return None
    return re.sub(r"\\(.)", r"\1", raw)


def testid_chain(locator_text: str | None) -> list[str]:
    """Locator ifadesindeki testId'ler (soldan sağa). Güvenilmeyen metin: yalnızca okunur."""
    if not locator_text:
        return []
    found: list[tuple[int, str]] = []
    for m in _TESTID_CALL_RE.finditer(locator_text[:4000]):
        v = _unquote(m.group(1), m.group(2))
        if v is not None:
            found.append((m.start(), v))
    for m in _TESTID_ATTR_RE.finditer(locator_text[:4000]):
        found.append((m.start(), m.group(1)))
    found.sort()
    return [v[:200] for _, v in found][:10]


def kirik_testid(locator_text: str | None) -> tuple[str | None, str | None]:
    """(aranan testId, kapsayıcı testId) — zincirdeki son ve sondan bir önceki testId."""
    ids = testid_chain(locator_text)
    if not ids:
        return None, None
    return ids[-1], (ids[-2] if len(ids) > 1 else None)


def locators_dosyasi(po_file: str) -> str:
    """Page object dosyasının yanındaki locators.ts (locator kaydında `file` yoksa)."""
    if po_file.endswith("/locators.ts") or po_file == "locators.ts":
        return po_file
    dizin = po_file.rsplit("/", 1)[0] if "/" in po_file else ""
    return f"{dizin}/locators.ts" if dizin else "locators.ts"


def _anahtar_bol(tam: str) -> tuple[str | None, str]:
    """`catalog.addToCart` → ("catalog", "addToCart"); noktasız ad grupsuz döner."""
    if "." in tam:
        grup, ad = tam.rsplit(".", 1)
        return grup, ad
    return None, tam


def find_locators(
    symbols: Mapping[str, Any], test_id: str, *, anahtar: str | None = None
) -> list[LocatorRef]:
    """`test_id`'yi sabit değer olarak taşıyan tüm locator anahtarları (önek locator'lar hariç).

    Sembol tablosu (toolchain `/symbols`): `page_objects[].locators` anahtarları `grup.ad`
    (`catalog.addToCart`), her kayıtta `file` (e2e köküne göre `pages/catalog/locators.ts`),
    `prefix`, isteğe bağlı `within`. `anahtar` verilirse (triage önerisi; `addToCart` ya da
    `catalog.addToCart`) yalnızca o anahtar döner. Dosya yolu e2e köküne göredir.
    """
    out: list[LocatorRef] = []
    gorulen: set[tuple[str, str]] = set()
    for po in symbols.get("page_objects") or []:
        if not isinstance(po, Mapping):
            continue
        locs = po.get("locators") or {}
        if not isinstance(locs, Mapping):
            continue
        for tam, spec in locs.items():
            if not isinstance(spec, Mapping) or spec.get("testId") != test_id:
                continue
            if spec.get("prefix") or test_id.endswith("-"):
                continue  # önek locator: onarım kapsamı dışı (insana)
            grup, ad = _anahtar_bol(str(tam))
            if anahtar is not None and anahtar not in (str(tam), ad):
                continue
            dosya = str(spec.get("file") or locators_dosyasi(str(po.get("file") or "")))
            if (dosya, ad) in gorulen:
                continue
            gorulen.add((dosya, ad))
            within = spec.get("within")
            kardesler: dict[str, dict[str, Any]] = {}
            for k, v in locs.items():
                kg, kad = _anahtar_bol(str(k))
                if isinstance(v, Mapping) and kg == grup:
                    kardesler[kad] = dict(v)
            out.append(
                LocatorRef(
                    dosya=dosya,
                    sinif=str(po.get("class") or ""),
                    anahtar=ad,
                    test_id=test_id,
                    rol=str(spec.get("role") or ""),
                    ad=str(spec.get("name") or ""),
                    niyet=str(spec.get("intent") or ""),
                    within=str(within) if isinstance(within, str) and within else None,
                    grup=grup,
                    kardesler=kardesler,
                )
            )
    return out


def kullanilan_testidler(symbols: Mapping[str, Any]) -> dict[str, list[str]]:
    """testId (sabit ya da önek) → onu kullanan `Sınıf.anahtar` listesi."""
    out: dict[str, list[str]] = {}
    for po in symbols.get("page_objects") or []:
        if not isinstance(po, Mapping):
            continue
        for key, spec in (po.get("locators") or {}).items():
            if isinstance(spec, Mapping) and isinstance(spec.get("testId"), str):
                out.setdefault(spec["testId"], []).append(str(key))
    return out


def cakisma(symbols: Mapping[str, Any], yeni: str, loc: LocatorRef) -> str | None:
    """Yeni testId başka bir locator'ın değeri ya da öneki mi? (yanlış elemana "onarım")"""
    for tid, kullananlar in kullanilan_testidler(symbols).items():
        diger = [k for k in kullananlar if k not in (loc.tam_ad, loc.anahtar)]
        if not diger:
            continue
        if tid == yeni or (tid.endswith("-") and yeni.startswith(tid)):
            return f"'{yeni}' başka bir locator'ın testId'si ({', '.join(diger)})"
    return None


def kapsayici_rolu(loc: LocatorRef) -> tuple[str | None, str | None]:
    """`within` önekini testId olarak taşıyan kardeş locator'ın (rol, anahtar)'ı."""
    if not loc.within:
        return None, None
    for key, spec in loc.kardesler.items():
        if spec.get("testId") == loc.within:
            rol = spec.get("role")
            return (str(rol) if rol else None), key
    return None, None


def parse_paths(support_ts: str) -> dict[str, str]:
    """`export const paths = { catalog: "/katalog", ... }` → {catalog: /katalog}."""
    m = _PATHS_BLOCK_RE.search(support_ts or "")
    if not m:
        return {}
    return {e.group("key"): e.group("val") for e in _PATH_ENTRY_RE.finditer(m.group("body"))}


def url_path_for(dosya: str, paths: Mapping[str, str]) -> str | None:
    """`e2e/pages/catalog/locators.ts` → paths['catalog'] (yoksa çoğul 'orders')."""
    parcalar = dosya.split("/")
    if len(parcalar) < 2:
        return None
    dizin = parcalar[-2]
    for aday in (dizin, f"{dizin}s", dizin.rstrip("s")):
        if aday in paths:
            return paths[aday]
    return None


# ------------------------------------------------------------------------------- yama


def _nesne_araligi(kaynak: str, anahtar: str) -> tuple[int, int]:
    """`anahtar: { ... }` nesnesinin [başlangıç, bitiş) aralığı; tam olarak bir kez olmalı."""
    if not _KEY_RE.match(anahtar):
        raise PatchError(f"geçersiz locator anahtarı: {anahtar!r}")
    desen = re.compile(r"(?<![\w$.])" + re.escape(anahtar) + r"\s*:\s*\{")
    eslesmeler = list(desen.finditer(kaynak))
    if not eslesmeler:
        raise PatchError(f"'{anahtar}' anahtarı locators.ts içinde bulunamadı")
    if len(eslesmeler) > 1:
        raise PatchError(f"'{anahtar}' anahtarı locators.ts içinde birden çok kez geçiyor")
    bas = eslesmeler[0].end()
    derinlik = 1
    i = bas
    tirnak: str | None = None
    while i < len(kaynak):
        c = kaynak[i]
        if tirnak:
            if c == "\\":
                i += 2
                continue
            if c == tirnak:
                tirnak = None
        elif c in "'\"`":
            tirnak = c
        elif c == "{":
            derinlik += 1
        elif c == "}":
            derinlik -= 1
            if derinlik == 0:
                return bas, i
        i += 1
    raise PatchError(f"'{anahtar}' nesnesinin kapanışı bulunamadı")


def patch_testid(kaynak: str, anahtar: str, eski: str, yeni: str) -> str:
    """Yalnızca `anahtar` nesnesindeki `testId: "<eski>"` literal'inin içeriğini `yeni` yapar.

    Tırnak türü, boşluklar ve diğer tüm alanlar korunur. Sonuç satır farkıyla yeniden
    doğrulanır: tek satır değişir ve o satırda yalnızca testId değeri farklıdır.
    """
    if not TESTID_RE.match(yeni or ""):
        raise PatchError(f"yeni testId geçersiz: {yeni!r}")
    if not TESTID_RE.match(eski or ""):
        raise PatchError(f"eski testId geçersiz: {eski!r}")
    if eski == yeni:
        raise PatchError("eski ve yeni testId aynı")
    bas, bit = _nesne_araligi(kaynak, anahtar)
    govde = kaynak[bas:bit]
    desen = re.compile(r"(?<![\w$])testId\s*:\s*(['\"])" + re.escape(eski) + r"\1")
    eslesmeler = list(desen.finditer(govde))
    if len(eslesmeler) != 1:
        raise PatchError(
            f"'{anahtar}' nesnesinde testId '{eski}' "
            + ("bulunamadı" if not eslesmeler else "birden çok kez geçiyor")
        )
    m = eslesmeler[0]
    deger_bas = bas + m.start() + m.group(0).index(m.group(1)) + 1
    deger_bit = deger_bas + len(eski)
    if kaynak[deger_bas:deger_bit] != eski:  # pragma: no cover - savunma
        raise PatchError("yama konumu doğrulanamadı")
    sonuc = kaynak[:deger_bas] + yeni + kaynak[deger_bit:]
    dogrula_fark(kaynak, sonuc, eski, yeni)
    return sonuc


def dogrula_fark(once: str, sonra: str, eski: str, yeni: str) -> None:
    """İki metin arasındaki tek fark: bir satırda `eski` → `yeni` (başka hiçbir şey)."""
    a, b = once.splitlines(keepends=True), sonra.splitlines(keepends=True)
    if len(a) != len(b):
        raise PatchError("yama satır sayısını değiştirdi")
    farkli = [(x, y) for x, y in zip(a, b, strict=True) if x != y]
    if len(farkli) != 1:
        raise PatchError(f"yama {len(farkli)} satırı değiştirdi (yalnızca 1 olmalı)")
    x, y = farkli[0]
    if x.replace(eski, "\0") != y.replace(yeni, "\0") or x.count(eski) != y.count(yeni):
        raise PatchError("değişen satırda testId dışında fark var")


def birlesik_fark(dosya: str, once: str, sonra: str) -> str:
    return "".join(
        difflib.unified_diff(
            once.splitlines(keepends=True),
            sonra.splitlines(keepends=True),
            fromfile=f"a/{dosya}",
            tofile=f"b/{dosya}",
            n=1,
        )
    )


# ----------------------------------------------------------------- etkilenen testler


def _fixture_adi(sinif: str) -> str:
    return sinif[:1].lower() + sinif[1:] if sinif else sinif


def etkilenen_testler(
    dosyalar: Mapping[str, str], loc: LocatorRef, *, grup_adlari: Sequence[str] = ()
) -> list[str]:
    """Page object'i (sınıf, fixture adı) ya da locators.ts'i kullanan spec dosyaları.

    `dosyalar`: {yol: içerik} (e2e/tests/**). Yerel kontrol yine TAM paketi koşar; bu liste PR
    açıklamasında "etkilenen testler" ve kontrolün onları içerdiğinin denetimi içindir.
    """
    parca = loc.dosya.rsplit("/", 2)
    isaretler = {loc.sinif, _fixture_adi(loc.sinif), loc.grup or ""}
    if len(parca) >= 2:
        isaretler.add(f"{parca[-2]}/locators")
    isaretler |= {g for g in grup_adlari if g}
    isaretler.discard("")
    return sorted(
        yol
        for yol, icerik in dosyalar.items()
        if yol.endswith(".spec.ts") and any(i in icerik for i in isaretler)
    )


def ilk(it: Iterable[Any]) -> Any:
    return next(iter(it), None)


# ------------------------------------------------------------- sözleşme testi kapsamı

_TEST_CAGRI_RE = re.compile(
    r"""(?<![\w$.])(?:test|[A-Za-z_$][\w$]*Test)(?:\.(?:only|slow|fixme))?\s*\(\s*"""
    r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*,"""
)
_YAPI_BOZMA_RE = re.compile(r"\{([^{}]*)\}\s*=\s*$")


def _grup_kullaniyor_mu(govde: str, grup: str, anahtar: str) -> bool:
    """Test gövdesi locator grubunu (`catalog`) bütün olarak ya da `anahtar`ı içeren yapı bozma
    (`const { addToCart } = catalog`) ile kullanıyor mu?"""
    desen = re.compile(r"(?<![\w$.'\"`/-])" + re.escape(grup) + r"(?![\w$])")
    for m in desen.finditer(govde):
        once = govde[max(0, m.start() - 400) : m.start()]
        yb = _YAPI_BOZMA_RE.search(once)
        if yb is None:
            # grup bütün olarak kullanılıyor (ör. expectRoleNameMatchesTestId(page, catalog))
            return True
        adlar = {p.split(":")[0].strip().lstrip(".") for p in yb.group(1).split(",")}
        if anahtar in adlar:
            return True
    return False


def sozlesme_basliklari(spec_metni: str, loc: LocatorRef) -> list[str]:
    """`locators.spec.ts`'te bu locator'ı (grubunu) gerçekten sınayan testlerin başlıkları.

    Son yeşil koşuda geçen "herhangi bir" sözleşme testi kanıt değildir (ör. giriş sayfası testi
    `catalog.addToCart`'a hiç dokunmaz); yalnızca locator'ın grubunu kullanan test kanıttır.
    Grup bilinmiyorsa ya da hiçbir test kullanmıyorsa boş liste (kapalı başarısızlık).
    """
    if not loc.grup or not spec_metni:
        return []
    metin = spec_metni[:500_000]
    cagrilar = list(_TEST_CAGRI_RE.finditer(metin))
    out: list[str] = []
    for i, m in enumerate(cagrilar):
        bitis = cagrilar[i + 1].start() if i + 1 < len(cagrilar) else len(metin)
        baslik = _unquote(m.group(1), m.group(2))
        if baslik and _grup_kullaniyor_mu(metin[m.end() : bitis], loc.grup, loc.anahtar):
            out.append(baslik)
    return out
