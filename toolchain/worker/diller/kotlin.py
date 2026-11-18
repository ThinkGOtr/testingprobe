"""Kotlin / Espresso statik araçları (TASARIM test-dilleri §3.3; şerit Ş3; hat `musteri_ci`).

Kotlin derleyicisi ve Android SDK imaja GİRMEZ (karar): derleme ve koşu müşterinin GitHub
Actions'ındadır. TP tarafında yalnız **ayrıştırma** yapılır (tree-sitter-kotlin; kod çalıştırılmaz):

- **Sembol tablosu (`symbols`):** ekran nesnesi kütüphanesinden (`Ekran`'dan türeyen sınıflar,
  `object Kimlikler`) `tp-symbols` şemasında tablo. Tür adları normalleştirilir (`String|int|long|
  double|boolean`): tablo Java `e2e-app` tablosuyla ad eşittir, ajan girdisi dilden bağımsızdır.
- **Koruma (`guard`):** `uretilen/` altındaki her test izin listesine uyar (şablonun tek biçimi):
  yalnız `//` yorumları, sabit paket, beş izinli import, `@RunWith(AndroidJUnit4::class)` + en çok
  bir `@Bayi("…")`, `TestTabani()`'ndan türeyen tek sınıf, tek `@Test fun senaryo()`, gövdede yalnız
  `<erişimci>().<metot>(<literal>…)` deyimleri. Sembol tablosu varsa erişimci/metot/argüman sayısı
  ve literal türleri tabloya göre denetlenir (R6: derleme hatası PR'dan önce yakalanır). Yansıma,
  `Runtime.exec`, dize şablonu (`$`), `\\u` kaçışı, blok yorum, adlı/yayılmış argüman yasaktır —
  izin listesi dışında hiçbir sözdizimi kabul edilmez. `ekranlar/Kimlikler.kt` saf veri olmalıdır.
  `repair` modunda base..head farkında yalnız `Kimlikler.kt` kimlik literal'leri değişebilir.

Savunma derinliği: tree-sitter dilbilgisi her Kotlin yapısını doğru tanımayabilir (ör. bu sürüm
`"$ad"` şablonunu düz metin sayar). Bu yüzden koruma AST biçimine ek olarak her izinli yapının
**ham metnini** kanonik biçimle karşılaştırır; dize literalleri ham bayt üzerinde sıkı bir
düzenli ifadeyle denetlenir. AST'de ERROR / MISSING düğümü varsa dosya reddedilir.

Dilbilgisi `tree-sitter` + `tree-sitter-kotlin` Python paketleridir (imajda `TP_DIL_STATIK`
dizinine kurulur: `toolchain/statik-deps/kotlin.txt`, hash kilitli). Yoksa adımlar kapalı tarafa
düşer (`KotlinAracYok` → `ok: false`).

Ş0'a not (geçici adaptör): `worker/diller/__init__.py` keşfi ve `diller.kok(...)` henüz yok;
kök çözümü burada yerel `kok_coz` ile yapılır (aynı öncelik: proje bloğu → `_<P>` env → env →
varsayılan).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

AD = "kotlin"
PLATFORMLAR: tuple[str, ...] = ("android",)
HAT = "musteri_ci"
# musteri_ci: derleme ve koşu müşterinin CI'ında; TP'de yalnız statik koruma.
STEPS: tuple[str, ...] = ("guard",)
KOK_AYARI = "TP_ANDROID_KOTLIN_ROOT"
KOK_VARSAYILAN = "app/src/androidTest/java"
URETILEN = "uretilen"
VARSAYILAN_KUTUPHANE_PAKETI = "com.antreklabs.bayisiparis.tp"
TEST_METODU = "senaryo"
MAX_DOSYA = 2_000
MAX_BOYUT = 512 * 1024

TUR_ESLEME = {
    "String": "String",
    "Int": "int",
    "Long": "long",
    "Double": "double",
    "Boolean": "boolean",
}
_YASAK_KATEGORI = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"})
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_IDENT_RE = re.compile(_IDENT)
_SINIF_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Test")
_PAKET_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
_BAYI_RE = re.compile(r'"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"')
# Şablonun bastığı dize: yalnız düz karakterler ve beş kaçış (`\\` `\"` `\n` `\r` `\t` `\$`).
_DIZE_RE = re.compile(r'"(?:[^"\\$\n\r]|\\[\\"nrt$])*"')
_TAMSAYI_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?P<L>L)?")
_ONDALIK_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+)")
_SIR_RE = re.compile(r'testVerisi\("TP_TESTVERI_[A-Z0-9_]{1,64}"\)')
_INT = (-(2**31), 2**31 - 1)
_KIMLIK_DOSYASI_RE = re.compile(r"\A(?:[^/]+/)*ekranlar/Kimlikler\.kt\Z")
TEST_FILE_RE = re.compile(r"\A(?:[A-Za-z_][A-Za-z0-9_]*/)+[A-Za-z_][A-Za-z0-9_]*\.kt\Z")
_KT_ANAHTAR = frozenset(
    {
        "as",
        "break",
        "class",
        "continue",
        "do",
        "else",
        "false",
        "for",
        "fun",
        "if",
        "in",
        "interface",
        "is",
        "null",
        "object",
        "package",
        "return",
        "super",
        "this",
        "throw",
        "true",
        "try",
        "typealias",
        "typeof",
        "val",
        "var",
        "when",
        "while",
    }
)


class KotlinAracYok(RuntimeError):
    """tree-sitter-kotlin yüklenemedi (imajda `TP_DIL_STATIK` yok)."""


# ------------------------------------------------------------------------------ ayrıştırıcı


@lru_cache(maxsize=1)
def _parser() -> Any:
    try:
        import tree_sitter
        import tree_sitter_kotlin
    except ImportError:
        dizin = os.environ.get("TP_DIL_STATIK", "/opt/dil-statik")
        if not os.path.isdir(dizin):
            raise KotlinAracYok(
                "Kotlin statik aracı yok (tree-sitter-kotlin; TP_DIL_STATIK dizini bulunamadı)"
            ) from None
        if dizin not in sys.path:
            sys.path.append(dizin)
        try:
            import tree_sitter
            import tree_sitter_kotlin
        except ImportError as exc:
            raise KotlinAracYok(f"Kotlin statik aracı yüklenemedi: {exc}") from exc
    return tree_sitter.Parser(tree_sitter.Language(tree_sitter_kotlin.language()))


def ayristir(kaynak: bytes) -> Any:
    return _parser().parse(kaynak)


def _metin(n: Any, kaynak: bytes) -> str:
    return kaynak[n.start_byte : n.end_byte].decode("utf-8", "replace")


def _sade(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _hata_dugumu(n: Any) -> Any | None:
    if n.type == "ERROR" or n.is_missing:
        return n
    if not n.has_error:
        return None
    for c in n.children:
        h = _hata_dugumu(c)
        if h is not None:
            return h
    return n


def _adlilar(n: Any) -> list[Any]:
    return [c for c in n.children if c.is_named]


def _ilk(n: Any, tur: str) -> Any | None:
    return next((c for c in n.children if c.type == tur), None)


def _satir(n: Any) -> int:
    return int(n.start_point[0]) + 1


# --------------------------------------------------------------------------- kök ve yollar


def kok_coz(cfg: Any = None, platform: str | None = "android") -> str:
    """Kotlin kaynak kökü (forge deposuna göre): proje bloğu `dil_kokleri` → `<AYAR>_<P>` env →
    `<AYAR>` env → varsayılan (Ş0 sözleşmesi §3.1 ile aynı öncelik)."""
    kokler = getattr(cfg, "dil_kokleri", None) or {}
    p = (platform or "android").upper()
    for deger in (
        kokler.get(f"{KOK_AYARI}_{p}") if isinstance(kokler, Mapping) else None,
        kokler.get(KOK_AYARI) if isinstance(kokler, Mapping) else None,
        os.environ.get(f"{KOK_AYARI}_{p}"),
        os.environ.get(KOK_AYARI),
    ):
        if deger and str(deger).strip("/"):
            return str(deger).strip("/")
    return KOK_VARSAYILAN


def validate_test_file(yol: str) -> str:
    """Kaynak köküne göre Kotlin test dosyası (`com/acme/tp/uretilen/<Ad>Test.kt`)."""
    if not isinstance(yol, str) or ".." in yol.split("/") or not TEST_FILE_RE.fullmatch(yol):
        raise ValueError(
            f"geçersiz Kotlin test dosyası (kaynak köküne göre <paket>/<Ad>.kt): {yol!r}"
        )
    return yol


# ---------------------------------------------------------------------------- KDoc


def _kdoc(n: Any, kaynak: bytes) -> str:
    """Düğümden hemen önceki `/** … */` metni (yıldızlar ve etiketler ayıklanmış; tek satır)."""
    onceki = n.prev_named_sibling
    if onceki is None or onceki.type != "block_comment":
        return ""
    ham = _metin(onceki, kaynak)
    if not ham.startswith("/**"):
        return ""
    govde = ham[3:-2] if ham.endswith("*/") else ham[3:]
    satirlar = [re.sub(r"^\s*\*?\s?", "", s).rstrip() for s in govde.splitlines()]
    metin = " ".join(s for s in satirlar if s and not s.lstrip().startswith("@"))
    return re.sub(r"\s+", " ", metin).strip()


def _niyet(doc: str) -> str:
    """Niyet = KDoc'un ilk cümlesi (Javadoc ilk cümle kuralı: nokta + boşluk ya da son)."""
    m = re.match(r"(.+?\.)(?:\s|$)", doc)
    return (m.group(1) if m else doc).strip()


# ------------------------------------------------------------------------ sembol tablosu


def _paket(agac: Any, kaynak: bytes) -> str | None:
    ph = _ilk(agac.root_node, "package_header")
    q = _ilk(ph, "qualified_identifier") if ph is not None else None
    return _sade(_metin(q, kaynak)) if q is not None else None


def _dize_degeri(n: Any, kaynak: bytes) -> str | None:
    """Düz dize literalinin değeri (yalnız `_DIZE_RE`; şablon / `\\u` kaçışı yoksa)."""
    if n is None or n.type != "string_literal":
        return None
    ham = _metin(n, kaynak)
    if not _DIZE_RE.fullmatch(ham):
        return None
    return re.sub(
        r"\\(.)", lambda m: {"n": "\n", "r": "\r", "t": "\t"}.get(m.group(1), m.group(1)), ham[1:-1]
    )


def _const_val(n: Any, kaynak: bytes) -> tuple[str, str] | None:
    """`const val AD = "değer"` → (AD, değer); başka biçim None."""
    if n.type != "property_declaration":
        return None
    m = re.fullmatch(
        r"const\s+val\s+(" + _IDENT + r")\s*=\s*(" + _DIZE_RE.pattern + r")",
        _metin(n, kaynak).strip(),
    )
    if m is None:
        return None
    deger = _dize_degeri(_ilk(n, "string_literal"), kaynak)
    return (m.group(1), deger) if deger is not None else None


def _kimlikler(
    agac: Any, kaynak: bytes, dosya: str
) -> tuple[dict[str, dict[str, Any]], list[str], list[dict[str, Any]]]:
    """`object Kimlikler { object Grup { /** niyet */ const val AD = "kimlik" } }` → locators."""
    locators: dict[str, dict[str, Any]] = {}
    gruplar: list[str] = []
    hatalar: list[dict[str, Any]] = []
    for kok in _adlilar(agac.root_node):
        if (
            kok.type != "object_declaration"
            or _metin(_ilk(kok, "identifier"), kaynak) != "Kimlikler"
        ):
            continue
        govde = _ilk(kok, "class_body")
        for grup in _adlilar(govde) if govde is not None else []:
            if grup.type != "object_declaration":
                continue
            gad = _metin(_ilk(grup, "identifier"), kaynak)
            gruplar.append(gad)
            ggovde = _ilk(grup, "class_body")
            for oge in _adlilar(ggovde) if ggovde is not None else []:
                if oge.type != "property_declaration":
                    continue
                cv = _const_val(oge, kaynak)
                if cv is None:
                    hatalar.append(
                        {
                            "file": dosya,
                            "line": _satir(oge),
                            "message": "Kimlikler: const val dize değil",
                        }
                    )
                    continue
                ad, deger = cv
                locators[f"{gad}.{ad}"] = {
                    "testId": deger,
                    "role": "",
                    "name": "",
                    "intent": _niyet(_kdoc(oge, kaynak)),
                    "prefix": ad.endswith("_ONEK"),
                    "file": dosya,
                    "line": _satir(oge),
                }
    return locators, gruplar, hatalar


def _gorunurluk(n: Any, kaynak: bytes) -> str:
    mods = _ilk(n, "modifiers")
    if mods is not None:
        for c in mods.children:
            if c.type == "visibility_modifier":
                return _metin(c, kaynak).strip()
    return "public"


def _tur(n: Any, kaynak: bytes) -> str | None:
    """Parametre türü (yalnız düz `user_type`; `String?` vb. desteklenmez → None)."""
    if n is None or n.type != "user_type":
        return None
    return TUR_ESLEME.get(_sade(_metin(n, kaynak)))


def _metot(fn: Any, kaynak: bytes, dosya: str) -> tuple[dict[str, Any] | None, str | None]:
    ad = _metin(_ilk(fn, "identifier"), kaynak)
    params_node = _ilk(fn, "function_value_parameters")
    params: list[dict[str, Any]] = []
    for p in _adlilar(params_node) if params_node is not None else []:
        if p.type != "parameter":
            return None, f"{ad}: desteklenmeyen parametre"
        tur = _tur(next((c for c in _adlilar(p) if c.type != "identifier"), None), kaynak)
        if tur is None:
            return None, f"{ad}: parametre türü String/Int/Long/Double/Boolean değil"
        params.append(
            {"name": _metin(_ilk(p, "identifier"), kaynak), "type": tur, "optional": False}
        )
    # Dönüş türü: parametrelerden sonra gelen `user_type` (yok ya da `Unit` → void).
    donus = None
    gecti = False
    for c in fn.children:
        if c is params_node or c.type == "function_value_parameters":
            gecti = True
        elif gecti and c.type in ("user_type", "nullable_type", "function_type"):
            donus = _sade(_metin(c, kaynak))
    if donus not in (None, "Unit"):
        return None, None  # değer döndüren metot sözleşme dışı (sembol tablosuna girmez)
    doc = _kdoc(fn, kaynak)
    return {
        "name": ad,
        "params": params,
        "returns": "void",
        "kind": "expect" if ad.startswith("dogrula") else "action",
        "async": False,
        "doc": doc,
        "line": _satir(fn),
    }, None


def _kimlik_referanslari(n: Any, kaynak: bytes, out: set[str]) -> None:
    if n.type == "navigation_expression":
        m = re.fullmatch(
            r"Kimlikler\.(" + _IDENT + r")\.(" + _IDENT + r")", _sade(_metin(n, kaynak))
        )
        if m is not None:
            out.add(f"{m.group(1)}.{m.group(2)}")
            return
    for c in n.children:
        _kimlik_referanslari(c, kaynak, out)


def _ekran_sinifi_mi(cls: Any, kaynak: bytes) -> bool:
    ds = _ilk(cls, "delegation_specifiers")
    if ds is None:
        return False
    for d in _adlilar(ds):
        ci = _ilk(d, "constructor_invocation")
        ut = _ilk(ci, "user_type") if ci is not None else None
        if ut is not None and _sade(_metin(ut, kaynak)) == "Ekran":
            return True
    return False


def fixture_adi(sinif: str) -> str:
    return sinif[:1].lower() + sinif[1:]


def sembol_tablosu_dizinden(root: Path, *, rel_root: str = "") -> dict[str, Any]:
    """Kotlin kaynak kökündeki ekran nesnesi kütüphanesinin tablosu (`tp-symbols` şeması +
    `lang: kotlin`, `paket`: kütüphanenin taban paketi)."""
    dosyalar = sorted(p for p in root.rglob("*.kt") if p.is_file() and not p.is_symlink())
    errors: list[dict[str, Any]] = []
    if len(dosyalar) > MAX_DOSYA:
        errors.append({"file": "", "message": f"en çok {MAX_DOSYA} Kotlin dosyası taranır"})
        dosyalar = dosyalar[:MAX_DOSYA]
    siniflar: list[tuple[str, Any, bytes, str]] = []
    locators: dict[str, dict[str, Any]] = {}
    locator_files: list[dict[str, Any]] = []
    ekran_paketi: str | None = None
    for yol in dosyalar:
        rel = yol.relative_to(root).as_posix()
        if URETILEN in rel.split("/")[:-1]:
            continue  # üretilen testler sembol değildir
        if yol.stat().st_size > MAX_BOYUT:
            errors.append({"file": rel, "message": "dosya çok büyük"})
            continue
        kaynak = yol.read_bytes()
        agac = ayristir(kaynak)
        if _hata_dugumu(agac.root_node) is not None:
            errors.append({"file": rel, "message": "Kotlin ayrıştırılamadı"})
            continue
        paket = _paket(agac, kaynak)
        if _KIMLIK_DOSYASI_RE.match(rel):
            locs, gruplar, hatalar = _kimlikler(agac, kaynak, rel)
            locators.update(locs)
            errors += hatalar
            if gruplar:
                locator_files.append({"file": rel, "exports": gruplar})
                ekran_paketi = ekran_paketi or paket
        for n in _adlilar(agac.root_node):
            if n.type == "class_declaration" and _ekran_sinifi_mi(n, kaynak):
                siniflar.append((rel, n, kaynak, paket or ""))
                ekran_paketi = ekran_paketi or paket
    page_objects: list[dict[str, Any]] = []
    for rel, cls, kaynak, _paketi in siniflar:
        ad = _metin(_ilk(cls, "identifier"), kaynak)
        govde = _ilk(cls, "class_body")
        metotlar: list[dict[str, Any]] = []
        refs: set[str] = set()
        for fn in _adlilar(govde) if govde is not None else []:
            if fn.type != "function_declaration":
                continue
            if _gorunurluk(fn, kaynak) != "public":
                continue
            m, hata = _metot(fn, kaynak, rel)
            if hata:
                errors.append({"file": rel, "line": _satir(fn), "message": hata})
            if m is not None:
                metotlar.append(m)
        if govde is not None:
            _kimlik_referanslari(govde, kaynak, refs)
        page_objects.append(
            {
                "class": ad,
                "file": rel if not rel_root else f"{rel_root.strip('/')}/{rel}",
                "doc": _kdoc(cls, kaynak),
                "methods": metotlar,
                "locators": {k: locators[k] for k in sorted(refs) if k in locators},
            }
        )
    page_objects.sort(key=lambda po: po["class"])
    kutuphane = VARSAYILAN_KUTUPHANE_PAKETI
    if ekran_paketi and ekran_paketi.endswith(".ekranlar"):
        kutuphane = ekran_paketi[: -len(".ekranlar")]
    return {
        "schema_version": 1,
        "root": rel_root,
        "lang": AD,
        "paket": kutuphane,
        "page_objects": page_objects,
        "locator_files": locator_files,
        "fixtures": sorted(fixture_adi(po["class"]) for po in page_objects),
        "errors": errors,
    }


# --------------------------------------------------------------------------------- koruma


def _ihlal(kod: str, dosya: str, mesaj: str, satir: int | None = None) -> dict[str, Any]:
    v: dict[str, Any] = {"code": kod, "file": dosya, "message": mesaj}
    if satir is not None:
        v["line"] = satir
    return v


def _karakter_denetimi(metin: str, dosya: str) -> list[dict[str, Any]]:
    out = []
    for i, satir in enumerate(metin.split("\n"), start=1):
        for ch in satir:
            if unicodedata.category(ch) in _YASAK_KATEGORI:
                out.append(_ihlal("forbidden_char", dosya, f"yasak karakter U+{ord(ch):04X}", i))
                break
    return out


def izinli_importlar(kutuphane: str) -> frozenset[str]:
    return frozenset(
        {
            "androidx.test.ext.junit.runners.AndroidJUnit4",
            "org.junit.Test",
            "org.junit.runner.RunWith",
            f"{kutuphane}.altyapi.TestTabani",
            f"{kutuphane}.altyapi.Bayi",
        }
    )


def _arg_turu(n: Any, kaynak: bytes) -> tuple[str | None, str]:
    """`value_argument` → (normalleştirilmiş tür, ham metin); izinli literal değilse (None, ham)."""
    ham = _metin(n, kaynak).strip()
    adlilar = _adlilar(n)
    if len(adlilar) != 1 or any(c.type in ("=", "*") for c in n.children):
        return None, ham  # adlı / yayılmış argüman
    c = adlilar[0]
    if c.type == "string_literal" and _DIZE_RE.fullmatch(ham):
        return "String", ham
    if c.type == "call_expression" and _SIR_RE.fullmatch(_sade(ham)):
        return "String", _sade(ham)
    if ham in ("true", "false"):
        return "boolean", ham
    if c.type in ("number_literal", "unary_expression") and (m := _TAMSAYI_RE.fullmatch(ham)):
        if m.group("L"):
            return "long", ham
        return ("int" if _INT[0] <= int(ham) <= _INT[1] else "int_disi"), ham
    if c.type in ("float_literal", "unary_expression") and _ONDALIK_RE.fullmatch(ham):
        return "double", ham
    return None, ham


def _tur_uyar(arg: str, param: str) -> bool:
    if arg == param:
        return True
    return param == "long" and arg == "int"  # tamsayı literali Long parametreye uyar


def _deyim(
    st: Any,
    kaynak: bytes,
    dosya: str,
    tablo_metotlari: Mapping[tuple[str, str], list[str]] | None,
    erisimciler: Mapping[str, str] | None,
) -> list[dict[str, Any]]:
    """`<erişimci>().<metot>(<literal>…)` deyimi."""
    satir = _satir(st)
    nav = st.children[0] if st.children else None
    va = _ilk(st, "value_arguments")
    ic = nav.children[0] if nav is not None and nav.children else None
    if (
        st.type != "call_expression"
        or nav is None
        or nav.type != "navigation_expression"
        or va is None
        or ic is None
        or ic.type != "call_expression"
        or len(_adlilar(nav)) != 2
    ):
        return [
            _ihlal("forbidden_statement", dosya, "yalnız <erişimci>().<metot>(…) deyimi", satir)
        ]
    erisimci_dugum = ic.children[0] if ic.children else None
    ic_args = _ilk(ic, "value_arguments")
    metot_dugum = _adlilar(nav)[1]
    if (
        erisimci_dugum is None
        or erisimci_dugum.type != "identifier"
        or ic_args is None
        or _adlilar(ic_args)
        or metot_dugum.type != "identifier"
    ):
        return [
            _ihlal("forbidden_statement", dosya, "yalnız <erişimci>().<metot>(…) deyimi", satir)
        ]
    erisimci = _metin(erisimci_dugum, kaynak)
    metot = _metin(metot_dugum, kaynak)
    if (
        not _IDENT_RE.fullmatch(erisimci)
        or not _IDENT_RE.fullmatch(metot)
        or erisimci in _KT_ANAHTAR
    ):
        return [_ihlal("forbidden_statement", dosya, "geçersiz tanımlayıcı", satir)]
    ihlaller: list[dict[str, Any]] = []
    argumanlar = [c for c in _adlilar(va) if c.type == "value_argument"]
    if len(argumanlar) != len(_adlilar(va)):
        return [_ihlal("forbidden_argument", dosya, "argüman listesi izinli değil", satir)]
    turler: list[str | None] = []
    hamlar: list[str] = []
    for a in argumanlar:
        tur, ham = _arg_turu(a, kaynak)
        if tur is None or tur == "int_disi":
            ihlaller.append(
                _ihlal("forbidden_argument", dosya, f"izinli literal değil: {ham[:60]}", satir)
            )
        turler.append(tur)
        hamlar.append(ham)
    kanonik = f"{erisimci}().{metot}({','.join(hamlar)})"
    if _sade(_metin(st, kaynak)) != _sade(kanonik):
        ihlaller.append(_ihlal("forbidden_statement", dosya, "deyim kanonik biçimde değil", satir))
    if erisimciler is not None:
        sinif = erisimciler.get(erisimci)
        if sinif is None:
            ihlaller.append(
                _ihlal(
                    "unknown_fixture", dosya, f"bilinmeyen ekran erişimcisi: {erisimci}()", satir
                )
            )
        elif tablo_metotlari is not None:
            params = tablo_metotlari.get((sinif, metot))
            if params is None:
                ihlaller.append(
                    _ihlal("unknown_method", dosya, f"{sinif}.{metot} sembol tablosunda yok", satir)
                )
            elif len(params) != len(turler):
                ihlaller.append(
                    _ihlal(
                        "arity_mismatch",
                        dosya,
                        f"{sinif}.{metot}: {len(params)} argüman bekleniyor",
                        satir,
                    )
                )
            else:
                for i, (t, p) in enumerate(zip(turler, params, strict=True), start=1):
                    if t is not None and t != "int_disi" and not _tur_uyar(t, p):
                        ihlaller.append(
                            _ihlal(
                                "type_mismatch",
                                dosya,
                                f"{sinif}.{metot} argüman {i}: {p} bekleniyor, {t} verildi",
                                satir,
                            )
                        )
    return ihlaller


def _tablo_dizinleri(
    tablo: Mapping[str, Any] | None,
) -> tuple[dict[tuple[str, str], list[str]] | None, dict[str, str] | None]:
    if not tablo or not tablo.get("page_objects"):
        return None, None
    metotlar: dict[tuple[str, str], list[str]] = {}
    erisimciler: dict[str, str] = {}
    for po in tablo["page_objects"]:
        sinif = str(po.get("class"))
        erisimciler[fixture_adi(sinif)] = sinif
        for m in po.get("methods") or []:
            metotlar[(sinif, str(m.get("name")))] = [
                str(p.get("type")) for p in m.get("params") or []
            ]
    return metotlar, erisimciler


def guard_kaynak(
    kaynak: bytes,
    dosya: str,
    *,
    kutuphane: str = VARSAYILAN_KUTUPHANE_PAKETI,
    tablo: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Tek üretilen test dosyasının ihlalleri (boş liste = geçti). `dosya` kaynak köküne göre."""
    try:
        metin = kaynak.decode("utf-8")
    except UnicodeDecodeError:
        return [_ihlal("encoding", dosya, "UTF-8 değil")]
    ihlaller = _karakter_denetimi(metin, dosya)
    if "\r" in metin or "\t" in metin:
        ihlaller.append(_ihlal("forbidden_char", dosya, "CR / sekme karakteri yasak"))
    if ihlaller:
        return ihlaller
    agac = ayristir(kaynak)
    hata = _hata_dugumu(agac.root_node)
    if hata is not None:
        return [_ihlal("parse_error", dosya, "Kotlin ayrıştırılamadı", _satir(hata))]
    beklenen_paket = f"{kutuphane}.{URETILEN}"
    sinif_beklenen = dosya.rsplit("/", 1)[-1].removesuffix(".kt")
    if not dosya.endswith(f"{beklenen_paket.replace('.', '/')}/{sinif_beklenen}.kt"):
        ihlaller.append(
            _ihlal("wrong_path", dosya, f"üretilen test {beklenen_paket} dizininde olmalı")
        )
    izinli = izinli_importlar(kutuphane)
    paket_sayisi = 0
    siniflar: list[Any] = []
    for n in agac.root_node.children:
        if n.type == "line_comment":
            continue
        if n.type == "package_header":
            paket_sayisi += 1
            if _sade(_metin(n, kaynak)) != _sade(f"package {beklenen_paket}"):
                ihlaller.append(
                    _ihlal("wrong_package", dosya, f"paket {beklenen_paket} olmalı", _satir(n))
                )
        elif n.type == "import":
            ad = _sade(_metin(n, kaynak))
            if not ad.startswith("import") or ad[len("import") :] not in izinli:
                ihlaller.append(
                    _ihlal(
                        "forbidden_import",
                        dosya,
                        f"izinsiz import: {_metin(n, kaynak)[:100]}",
                        _satir(n),
                    )
                )
        elif n.type == "class_declaration":
            siniflar.append(n)
        else:
            ihlaller.append(
                _ihlal("forbidden_top_level", dosya, f"izinsiz üst düzey yapı: {n.type}", _satir(n))
            )
    if paket_sayisi != 1:
        ihlaller.append(_ihlal("wrong_package", dosya, "tek paket bildirimi olmalı"))
    if len(siniflar) != 1:
        return [*ihlaller, _ihlal("class_count", dosya, "tek test sınıfı olmalı")]
    cls = siniflar[0]
    ad = _metin(_ilk(cls, "identifier"), kaynak) if _ilk(cls, "identifier") is not None else ""
    if not _SINIF_RE.fullmatch(ad) or ad != sinif_beklenen:
        ihlaller.append(
            _ihlal(
                "class_name",
                dosya,
                f"sınıf adı dosya adıyla aynı ve <Story>AndroidC<n>_<u8>Test olmalı: {ad}",
                _satir(cls),
            )
        )
    govde = _ilk(cls, "class_body")
    if govde is None:
        return [*ihlaller, _ihlal("class_shape", dosya, "sınıf gövdesi yok", _satir(cls))]
    # Sınıf başlığı (notasyonlar + ad + kalıtım) ham metinle kanonik karşılaştırılır.
    baslik = _sade(kaynak[cls.start_byte : govde.start_byte].decode("utf-8"))
    bayi = re.fullmatch(
        r"@RunWith\(AndroidJUnit4::class\)(?:@Bayi\((?P<b>\"[^\"]*\")\))?class"
        + re.escape(ad)
        + r":TestTabani\(\)",
        baslik,
    )
    if bayi is None or (bayi.group("b") is not None and not _BAYI_RE.fullmatch(bayi.group("b"))):
        ihlaller.append(
            _ihlal(
                "class_shape",
                dosya,
                'sınıf: @RunWith(AndroidJUnit4::class) [@Bayi("…")] class <Ad> : TestTabani()',
                _satir(cls),
            )
        )
    if (
        bayi is not None
        and bayi.group("b") is not None
        and f"{kutuphane}.altyapi.Bayi" not in _sade(metin)
    ):
        ihlaller.append(
            _ihlal("forbidden_import", dosya, "@Bayi için altyapi.Bayi importu gerekir")
        )
    fonksiyonlar = []
    for c in govde.children:
        if c.type in ("{", "}", "line_comment"):
            continue
        if c.type == "function_declaration":
            fonksiyonlar.append(c)
        else:
            ihlaller.append(
                _ihlal("class_shape", dosya, f"sınıf gövdesinde izinsiz yapı: {c.type}", _satir(c))
            )
    if len(fonksiyonlar) != 1:
        return [
            *ihlaller,
            _ihlal("method_count", dosya, "tek @Test fun senaryo() olmalı", _satir(govde)),
        ]
    fn = fonksiyonlar[0]
    fb = _ilk(fn, "function_body")
    blok = _ilk(fb, "block") if fb is not None else None
    if blok is None or len(fb.children) != 1:
        return [
            *ihlaller,
            _ihlal("method_shape", dosya, "senaryo() blok gövdeli olmalı", _satir(fn)),
        ]
    if _sade(kaynak[fn.start_byte : blok.start_byte].decode("utf-8")) != f"@Testfun{TEST_METODU}()":
        ihlaller.append(
            _ihlal(
                "method_shape",
                dosya,
                "yalnız @Test fun senaryo() (parametresiz, dönüşsüz)",
                _satir(fn),
            )
        )
    tablo_metotlari, erisimciler = _tablo_dizinleri(tablo)
    for st in blok.children:
        if st.type in ("{", "}", "line_comment"):
            continue
        ihlaller += _deyim(st, kaynak, dosya, tablo_metotlari, erisimciler)
    return ihlaller


def kimlikler_saf_mi(kaynak: bytes, dosya: str) -> list[dict[str, Any]]:
    """`ekranlar/Kimlikler.kt` saf veri mi: paket +
    `object Kimlikler { object G { const val A = "…" } }`
    + yorumlar; başka hiçbir şey (import, fonksiyon, init, şablon) yok."""
    try:
        metin = kaynak.decode("utf-8")
    except UnicodeDecodeError:
        return [_ihlal("encoding", dosya, "UTF-8 değil")]
    ihlaller = _karakter_denetimi(metin, dosya)
    agac = ayristir(kaynak)
    if _hata_dugumu(agac.root_node) is not None:
        return [*ihlaller, _ihlal("parse_error", dosya, "Kotlin ayrıştırılamadı")]
    yorum = ("line_comment", "block_comment")
    for n in _adlilar(agac.root_node):
        if n.type in yorum or n.type == "package_header":
            continue
        if (
            n.type != "object_declaration"
            or _sade(kaynak[n.start_byte : (_ilk(n, "class_body") or n).start_byte].decode("utf-8"))
            != "objectKimlikler"
        ):
            ihlaller.append(
                _ihlal(
                    "locator_file_impure",
                    dosya,
                    f"Kimlikler.kt'de izinsiz yapı: {n.type}",
                    _satir(n),
                )
            )
            continue
        govde = _ilk(n, "class_body")
        for g in _adlilar(govde) if govde is not None else []:
            if g.type in yorum:
                continue
            gg = _ilk(g, "class_body")
            if (
                g.type != "object_declaration"
                or gg is None
                or not re.fullmatch(
                    r"object" + _IDENT, _sade(kaynak[g.start_byte : gg.start_byte].decode("utf-8"))
                )
            ):
                ihlaller.append(
                    _ihlal(
                        "locator_file_impure",
                        dosya,
                        f"Kimlikler içinde izinsiz yapı: {g.type}",
                        _satir(g),
                    )
                )
                continue
            for p in _adlilar(gg):
                if p.type in yorum:
                    continue
                if _const_val(p, kaynak) is None:
                    ihlaller.append(
                        _ihlal(
                            "locator_file_impure",
                            dosya,
                            'yalnız const val AD = "kimlik"',
                            _satir(p),
                        )
                    )
    return ihlaller


def uretilen_dosyalar(root: Path, kutuphane: str) -> list[str]:
    dizin = root / kutuphane.replace(".", "/") / URETILEN
    if not dizin.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in dizin.rglob("*") if p.is_file())


def guard_dizin(
    root: Path,
    *,
    tablo: Mapping[str, Any] | None = None,
    dosyalar: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Kökteki üretilen testler (+ `Kimlikler.kt` saflığı). `dosyalar` verilirse yalnız onlar
    (yine de `uretilen/` dışındakiler reddedilir)."""
    tablo = tablo if tablo is not None else sembol_tablosu_dizinden(root)
    kutuphane = str(tablo.get("paket") or VARSAYILAN_KUTUPHANE_PAKETI)
    hedef = list(dosyalar) if dosyalar else uretilen_dosyalar(root, kutuphane)
    ihlaller: list[dict[str, Any]] = []
    for rel in hedef:
        yol = root / rel
        if URETILEN not in rel.split("/")[:-1]:
            ihlaller.append(
                _ihlal("not_generated", rel, "TP yalnız uretilen/ altındaki testleri yazar")
            )
            continue
        if not rel.endswith(".kt"):
            ihlaller.append(
                _ihlal("forbidden_file", rel, "uretilen/ altında yalnız .kt dosyası olabilir")
            )
            continue
        if yol.is_symlink() or not yol.is_file() or yol.stat().st_size > MAX_BOYUT:
            ihlaller.append(
                _ihlal("forbidden_file", rel, "dosya okunamadı (bağ / yok / çok büyük)")
            )
            continue
        ihlaller += guard_kaynak(yol.read_bytes(), rel, kutuphane=kutuphane, tablo=tablo)
    for lf in tablo.get("locator_files") or []:
        yol = root / str(lf.get("file"))
        if yol.is_file() and not yol.is_symlink():
            ihlaller += kimlikler_saf_mi(yol.read_bytes(), str(lf.get("file")))
    ok = not ihlaller
    return {
        "tool": "tp-kotlin-guard",
        "schema_version": 1,
        "ok": ok,
        "files": hedef,
        "paket": kutuphane,
        "violations": ihlaller,
        "summary": (
            f"Kotlin koruması {'geçti' if ok else 'başarısız'} · üretilen test: {len(hedef)} · "
            f"ihlal: {len(ihlaller)}"
        ),
    }


# --------------------------------------------------------------------- onarım (repair) farkı


def _kimlik_degerleri(kaynak: bytes) -> dict[str, str] | None:
    agac = ayristir(kaynak)
    if _hata_dugumu(agac.root_node) is not None:
        return None
    locs, _g, hatalar = _kimlikler(agac, kaynak, "")
    return None if hatalar else {k: v["testId"] for k, v in locs.items()}


def repair_farki(
    degisenler: Iterable[tuple[str, str]],
    oku: Any,
    *,
    kok: str,
) -> dict[str, Any]:
    """Onarım modu: base..head'de yalnız `Kimlikler.kt` değişir ve yalnız kimlik değerleri
    (anahtar kümesi aynı). `degisenler`: (durum A|M|D…, depo yolu); `oku(ref, yol)` → bayt."""
    on = kok.strip("/") + "/"
    ihlaller: list[dict[str, Any]] = []
    degisimler: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for durum, yol in degisenler:
        rel = yol[len(on) :] if yol.startswith(on) else None
        kimlik = rel is not None and bool(_KIMLIK_DOSYASI_RE.match(rel))
        st = {"A": "added", "D": "deleted"}.get(durum[:1], "modified")
        changed.append({"path": yol, "status": st, "locator": kimlik})
        if not kimlik:
            ihlaller.append(
                _ihlal(
                    "non_locator_file_changed",
                    yol,
                    "onarımda yalnızca ekranlar/Kimlikler.kt değişebilir",
                )
            )
            continue
        if st != "modified":
            ihlaller.append(
                _ihlal(f"locator_file_{st}", yol, "Kimlikler.kt onarımda eklenemez/silinemez")
            )
            continue
        once, sonra = _kimlik_degerleri(oku("base", yol)), _kimlik_degerleri(oku("head", yol))
        if once is None or sonra is None:
            ihlaller.append(_ihlal("locator_file_impure", yol, "Kimlikler.kt saf veri değil"))
            continue
        if set(once) != set(sonra):
            ihlaller.append(
                _ihlal("locator_keys_changed", yol, "onarım kimlik anahtarı ekleyemez/silemez")
            )
            continue
        for k in sorted(once):
            if once[k] != sonra[k]:
                degisimler.append({"key": k, "from": once[k], "to": sonra[k], "file": yol})
    return {
        "ok": not ihlaller,
        "changed_files": changed,
        "testid_changes": degisimler,
        "violations": ihlaller,
    }


# ------------------------------------------------------------------- git (yalnız okuma)


def _git(cfg: Any, repo: Path, *args: str) -> bytes:
    from toolchain_common import gitforge

    try:
        out = subprocess.run(
            gitforge._git_argv(repo, *args),
            env=gitforge.git_env(),
            capture_output=True,
            timeout=getattr(cfg, "git_timeout_s", 60),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise gitforge.ForgeError("git süre aşımı") from exc
    if out.returncode != 0:
        raise gitforge.ForgeError(
            f"git {args[0]} başarısız: {out.stderr.decode('utf-8', 'replace')[:300]}"
        )
    return out.stdout


def _degisenler(cfg: Any, repo: Path, base: str, head: str) -> list[tuple[str, str]]:
    raw = _git(
        cfg, repo, "diff", "--name-status", "--no-renames", "-z", "--end-of-options", base, head
    )
    parts = [p for p in raw.decode("utf-8", "replace").split("\0") if p]
    return list(zip(parts[0::2], parts[1::2], strict=False))


# ------------------------------------------------------------- Ş0 worker eklenti yüzeyi


def symbols(cfg: Any, full_sha: str, repo: Path, platform: str = "android") -> dict[str, Any]:
    from toolchain_common import gitforge

    kok = kok_coz(cfg, platform)
    with gitforge.checkout(repo, full_sha, kok, getattr(cfg, "git_timeout_s", 60)) as root:
        return sembol_tablosu_dizinden(root, rel_root="")


def guard(
    cfg: Any, repo: Path, base: str, head: str, mode: str, platform: str = "android"
) -> dict[str, Any]:
    from toolchain_common import gitforge

    kok = kok_coz(cfg, platform)
    try:
        with gitforge.checkout(repo, head, kok, getattr(cfg, "git_timeout_s", 60)) as root:
            rapor = guard_dizin(root)
    except KotlinAracYok as exc:
        return {"ok": False, "violations": [_ihlal("tool_missing", "", str(exc))], "mode": mode}
    rep = None
    if mode == "repair":
        rep = repair_farki(
            _degisenler(cfg, repo, base, head),
            lambda ref, yol: _git(cfg, repo, "show", f"{base if ref == 'base' else head}:{yol}"),
            kok=kok,
        )
    ihlaller = list(rapor["violations"]) + list((rep or {}).get("violations") or [])
    return {
        **rapor,
        "ok": not ihlaller,
        "mode": mode,
        "base": base,
        "head": head,
        "root": kok,
        "violations": ihlaller,
        "changed_files": (rep or {}).get("changed_files", []),
        "testid_changes": (rep or {}).get("testid_changes", []),
        "repair": rep,
    }


def run_static(
    cfg: Any,
    req: Any,
    head: Any,
    base: str | None,
    runner_client: Any,
    steps: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """musteri_ci `/check`: yalnız `guard` adımı (koşu müşterinin CI'ında; `run` adımı yok)."""
    from toolchain_common import gitforge

    platform = getattr(req, "platform", None) or "android"
    mode = getattr(req, "ast_guard_mode", "pr")
    kok = kok_coz(cfg, platform)
    test_files = list(getattr(req, "test_files", None) or [])
    base_sha = base or head.sha
    try:
        with gitforge.checkout(head.repo, head.sha, kok, getattr(cfg, "git_timeout_s", 60)) as root:
            eksik = [f for f in test_files if not (root / f).is_file()]
            if eksik:
                steps["guard"] = {
                    "ok": False,
                    "error": "Test dosyası commit'te yok: " + ", ".join(eksik),
                    "missing_test_files": eksik,
                }
                return steps
            rapor = guard_dizin(root, dosyalar=test_files or None)
    except KotlinAracYok as exc:
        steps["guard"] = {"ok": False, "mode": mode, "error": str(exc)}
        return steps
    rep = None
    if mode == "repair" and base:
        rep = repair_farki(
            _degisenler(cfg, head.repo, base_sha, head.sha),
            lambda ref, yol: _git(
                cfg, head.repo, "show", f"{base_sha if ref == 'base' else head.sha}:{yol}"
            ),
            kok=kok,
        )
        rapor = {
            **rapor,
            "repair": rep,
            "ok": rapor["ok"] and rep["ok"],
            "violations": rapor["violations"] + rep["violations"],
        }
    steps["guard"] = {"ok": bool(rapor["ok"]), "mode": mode, "base_sha": base_sha, "report": rapor}
    return steps


class _KotlinWorker:
    """`WorkerDili` protokolü (specs/014-test-dilleri/plan.md §3.1)."""

    ad = AD
    platformlar = PLATFORMLAR
    steps = STEPS
    hat = HAT

    def validate_test_file(self, yol: str) -> str:
        return validate_test_file(yol)

    def symbols(self, cfg: Any, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
        return symbols(cfg, full_sha, repo, platform)

    def guard(
        self, cfg: Any, repo: Path, base: str, head: str, mode: str, platform: str
    ) -> dict[str, Any]:
        return guard(cfg, repo, base, head, mode, platform)

    def run_static(
        self,
        cfg: Any,
        req: Any,
        head: Any,
        base: str | None,
        runner_client: Any,
        steps: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        return run_static(cfg, req, head, base, runner_client, steps)


EKLENTI = _KotlinWorker()
