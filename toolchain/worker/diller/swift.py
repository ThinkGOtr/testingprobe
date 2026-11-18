r"""Swift / XCUITest worker eklentisi (014 test dilleri, TASARIM §3.4; şerit Ş4).

Hat **musteri_ci**: TP Swift'i derlemez ve koşmaz (TP VM'inde Xcode yok); derleme ve koşu
müşterinin macOS GitHub Actions runner'ındadır. Worker'ın işi statiktir ve tree-sitter-swift ile
yapılır (Swift derleyicisi gerekmez):

- **`symbols`** — UI test hedefinin (eşitlenmiş klasör) ekran nesnesi kütüphanesinden sembol tablosu
  (`tp-symbols` şeması: `page_objects`, `locator_files`, `fixtures`, …; ek olarak normalleştirilmiş
  `classes`/`ids`). Ekran nesnesi = `Ekran`'dan türeyen sınıf; tabloya `private`/`fileprivate`/
  `static`/`class`/`override` olmayan, dönüş türsüz örnek metotları girer. `dogrula` ön ekli metot
  beklentidir (`kind=expect`), diğerleri eylem. Parametre türleri normalleştirilir (`String` →
  `string`, `Int` → `long` (64 bit), `Double`/`Float` → `double`, `Bool` → `boolean`; özgün tür
  `swift_type`), Swift argüman etiketi `label` (`_` = etiketsiz). Kimlikler
  `Ekranlar/Kimlikler.swift`
  (iç içe `enum` + `static let` dize; `///` ilk cümlesi niyet, `…Onek` önek).
- **`guard`** — (1) üretilen testler (`TPUretilen/*.swift`) şablonun izin listesine birebir uyar:
  yalnız `//` yorumları, tek `import XCTest`, `TestTabani`'ndan türeyen tek `final class` (adı dosya
  adıyla aynı, `<…>C<n>_<u8>Tests`), en çok bir `override class var bayi: String? { "<lit>" }`, tek
  parametresiz `func testSenaryo()`, gövdede yalnız `<erişimci>.<metot>(<etiket>: <literal>…)`
  deyimleri; literal = düz dize (interpolasyonsuz) / tamsayı / ondalık / mantıksal ya da
  `ortam("TP_TESTVERI_…")`. Görünmez/yön denetimi karakteri dosyanın hiçbir yerinde olamaz.
  (2) `Kimlikler.swift` SAF VERİ'dir. (3) `repair` modunda base..head farkında yalnız
  `Kimlikler.swift`'in dize değerleri değişebilir (anahtar ekleme/silme yok).
- **`semboller`** adımı — üretilen her çağrı sembol tablosunda var olan bir metoda, doğru
  etiket/sayı/türle gider (R6: derleme hatası PR'da değil TP'de yakalanır). Erişimci adı
  `lowerCamel(Sınıf)` ve `fixtures` listesindedir.

Adım sırası `STEPS = ("guard", "semboller")`; `run` adımı yoktur (koşu müşteri CI'ında, sonucu Ş5
`musteri_ci` okur). tree-sitter yükleme: önce kurulu paket (`tree_sitter`, `tree_sitter_swift`),
yoksa `TP_DIL_STATIK` (varsayılan `/opt/dil-statik`; Dockerfile `dil-statik` aşaması) `sys.path`'e
eklenip yeniden denenir.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AD = "swift"
PLATFORMLAR: tuple[str, ...] = ("ios",)
HAT = "musteri_ci"
STEPS: tuple[str, ...] = ("guard", "semboller")
KOK_AYARI = "TP_IOS_SWIFT_ROOT"
KOK_VARSAYILAN = "UITests"
URETILEN_DIZINI = "TPUretilen"
KIMLIKLER = "Ekranlar/Kimlikler.swift"
EKRAN_TABANI = "Ekran"
TEST_TABANI = "TestTabani"
TEST_METODU = "testSenaryo"
DIL_STATIK_VARSAYILAN = "/opt/dil-statik"
TEST_DOSYASI_RE = re.compile(
    r"\A" + URETILEN_DIZINI + r"/(?P<ad>[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Tests)\.swift\Z"
)
_SINIF_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Tests\Z")
_SIR_RE = re.compile(r'\A"TP_TESTVERI_[A-Z0-9_]{1,64}"\Z')
# Düz Swift dize literali: kaçışlar yalnız \\ \" \n \r \t \0 \u{…}; `\(` interpolasyonu yok.
_DIZE_RE = re.compile(r'\A"(?:[^"\\\n\r]|\\[\\"nrt0]|\\u\{[0-9A-Fa-f]{1,8}\})*"\Z')
_TAMSAYI_RE = re.compile(r"\A[0-9]+\Z")
_ONDALIK_RE = re.compile(r"\A[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?\Z")
# Kaynakta hiçbir yerde bulunamayacak karakter kategorileri (insan incelemesinde görülen metin
# derlenen metinle aynı olmalı). Satır sonu dışındaki Cc de yasak.
_YASAK_KATEGORI = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"})
TUR_NORMAL = {
    "String": "string",
    "Int": "long",
    "Int64": "long",
    "Int32": "int",
    "Double": "double",
    "Float": "double",
    "Bool": "boolean",
}
_GIZLI_DEGISTIRICI = frozenset({"private", "fileprivate"})
_SINIF_DEGISTIRICI = frozenset({"static", "class", "override"})


class SwiftAracError(RuntimeError):
    """tree-sitter-swift yüklenemedi ya da çözümleme yapılamadı."""


# ------------------------------------------------------------------------------ tree-sitter


_PARSER: Any = None


def _ts_yukle() -> tuple[Any, Any]:
    import tree_sitter
    import tree_sitter_swift

    return tree_sitter, tree_sitter_swift


def parser() -> Any:
    """tree-sitter-swift ayrıştırıcısı (süreç başına bir kez)."""
    global _PARSER
    if _PARSER is not None:
        return _PARSER
    try:
        ts, sw = _ts_yukle()
    except ImportError:
        yol = os.environ.get("TP_DIL_STATIK", DIL_STATIK_VARSAYILAN)
        if yol not in sys.path:
            sys.path.append(yol)
        try:
            ts, sw = _ts_yukle()
        except ImportError as exc:
            raise SwiftAracError(
                f"tree-sitter-swift yüklü değil (pip paketi ya da {yol}): {exc}"
            ) from exc
    _PARSER = ts.Parser(ts.Language(sw.language()))
    return _PARSER


@dataclass
class _Kaynak:
    yol: str
    veri: bytes
    agac: Any

    def metin(self, n: Any) -> str:
        return self.veri[n.start_byte : n.end_byte].decode("utf-8", "replace")

    def satir(self, n: Any) -> int:
        return int(n.start_point[0]) + 1


def cozumle(yol: str, veri: bytes) -> _Kaynak:
    return _Kaynak(yol, veri, parser().parse(veri))


def _cocuklar(n: Any, tur: str | None = None) -> list[Any]:
    return [c for c in n.named_children if tur is None or c.type == tur]


def _alan(n: Any, ad: str) -> Any:
    return n.child_by_field_name(ad)


def _alanlar(n: Any, ad: str) -> list[Any]:
    return [c for i, c in enumerate(n.children) if n.field_name_for_child(i) == ad]


def _degistiriciler(k: _Kaynak, n: Any) -> set[str]:
    m = next((c for c in n.children if c.type == "modifiers"), None)
    return set(k.metin(m).split()) if m is not None else set()


def _hatalar(k: _Kaynak) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def gez(n: Any) -> None:
        if n.type == "ERROR" or n.is_missing:
            out.append({"file": k.yol, "line": k.satir(n), "message": "Swift sözdizimi hatası"})
            return
        if n.has_error:
            for c in n.children:
                gez(c)

    gez(k.agac.root_node)
    return out


# ------------------------------------------------------------------------------ belge yorumu


def _belge(k: _Kaynak, n: Any) -> str:
    """Düğümün hemen önündeki `///` yorumlarının metni (ilk cümle niyettir)."""
    satirlar: list[str] = []
    onceki = n.prev_sibling
    while onceki is not None and onceki.type == "comment":
        t = k.metin(onceki)
        if not t.startswith("///"):
            break
        satirlar.insert(0, t[3:].strip())
        onceki = onceki.prev_sibling
    return " ".join(s for s in satirlar if s)


def _ilk_cumle(metin: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", metin)
    return (m.group(1) if m else metin).strip()


# ------------------------------------------------------------------------------ sembol tablosu


def _swift_dosyalari(kok: Path) -> Iterator[Path]:
    for p in sorted(kok.rglob("*.swift")):
        rel = p.relative_to(kok).parts
        if URETILEN_DIZINI in rel[:-1] or p.is_symlink():
            continue
        yield p


def _miras(k: _Kaynak, sinif: Any) -> list[str]:
    return [
        k.metin(_alan(s, "inherits_from")).strip()
        for s in _cocuklar(sinif, "inheritance_specifier")
        if _alan(s, "inherits_from") is not None
    ]


def _tur_metni(k: _Kaynak, p: Any) -> str:
    turler = [c for c in _alanlar(p, "name") if c.type != "simple_identifier"]
    return k.metin(turler[0]).strip() if turler else ""


def _parametreler(k: _Kaynak, f: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cocuk = f.children
    for i, c in enumerate(cocuk):
        if c.type != "parameter":
            continue
        dis = _alan(c, "external_name")
        adlar = [x for x in _alanlar(c, "name") if x.type == "simple_identifier"]
        ad = k.metin(adlar[0]) if adlar else ""
        swift_turu = _tur_metni(k, c)
        param: dict[str, Any] = {
            "name": ad,
            "label": k.metin(dis) if dis is not None else ad,
            "type": TUR_NORMAL.get(swift_turu, swift_turu),
            "swift_type": swift_turu,
            "optional": False,
        }
        # Varsayılan değer parametre düğümünün kardeşidir (`= <değer>`, alan `default_value`).
        j = i + 1
        while j < len(cocuk) and cocuk[j].type not in ("parameter", ")"):
            if f.field_name_for_child(j) == "default_value":
                param["default"] = k.metin(cocuk[j])
                param["optional"] = True
            j += 1
        out.append(param)
    return out


def _sinif_bildirimleri(n: Any) -> Iterator[Any]:
    for c in n.named_children:
        if c.type == "class_declaration":
            yield c
            govde = _alan(c, "body")
            if govde is not None:
                yield from _sinif_bildirimleri(govde)


def _kimlikler(k: _Kaynak) -> tuple[dict[str, dict[str, Any]], list[str], list[dict[str, Any]]]:
    """`enum Kimlikler { enum X { static let y = "…" } }` → ({"X.y": {...}}, ["X", …], ihlaller)."""
    kimlik: dict[str, dict[str, Any]] = {}
    gruplar: list[str] = []
    ihlal: list[dict[str, Any]] = []

    def kotu(n: Any, mesaj: str) -> None:
        ihlal.append(
            {"code": "kimlikler_saf_degil", "file": k.yol, "line": k.satir(n), "message": mesaj}
        )

    kok = k.agac.root_node
    ust = [c for c in kok.named_children if c.type != "comment"]
    if (
        len(ust) != 1
        or ust[0].type != "class_declaration"
        or k.metin(_alan(ust[0], "name")) != "Kimlikler"
    ):
        kotu(kok, "Kimlikler.swift yalnız tek `enum Kimlikler` içerebilir")
        return kimlik, gruplar, ihlal
    for g in _cocuklar(_alan(ust[0], "body")):
        if g.type == "comment":
            continue
        if g.type != "class_declaration" or k.metin(_alan(g, "declaration_kind")) != "enum":
            kotu(g, "Kimlikler içinde yalnız iç içe `enum` olabilir")
            continue
        grup = k.metin(_alan(g, "name"))
        gruplar.append(grup)
        for s in _cocuklar(_alan(g, "body")):
            if s.type == "comment":
                continue
            deger = _alan(s, "value")
            ad_dugum = _alan(s, "name")
            if (
                s.type != "property_declaration"
                or _degistiriciler(k, s) != {"static"}
                or k.metin(
                    next((c for c in s.named_children if c.type == "value_binding_pattern"), s)
                )
                != "let"
                or deger is None
                or deger.type != "line_string_literal"
                or not _DIZE_RE.match(k.metin(deger))
                or ad_dugum is None
            ):
                kotu(s, 'Kimlikler grubunda yalnız `static let <ad> = "<kimlik>"` olabilir')
                continue
            ad = k.metin(ad_dugum)
            ham = k.metin(deger)[1:-1]
            kimlik[f"{grup}.{ad}"] = {
                "testId": ham,
                "role": "",
                "name": "",
                "intent": _ilk_cumle(_belge(k, s)),
                "prefix": ad.endswith("Onek"),
                "file": k.yol,
                "line": k.satir(s),
            }
    return kimlik, gruplar, ihlal


_KIMLIK_BASVURU_RE = re.compile(r"\bKimlikler\.([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")


def semboller(kok: Path) -> dict[str, Any]:
    """Kök (UI test hedefinin klasörü) altındaki ekran nesnesi kütüphanesinin sembol tablosu."""
    kaynaklar = [
        cozumle(p.relative_to(kok).as_posix(), p.read_bytes()) for p in _swift_dosyalari(kok)
    ]
    errors: list[dict[str, Any]] = []
    for k in kaynaklar:
        errors += _hatalar(k)
    kimlik: dict[str, dict[str, Any]] = {}
    locator_files: list[dict[str, Any]] = []
    for k in kaynaklar:
        if k.yol == KIMLIKLER or k.yol.endswith("/" + KIMLIKLER):
            kim, gruplar, ihlal = _kimlikler(k)
            kimlik.update(kim)
            locator_files.append({"file": k.yol, "exports": gruplar})
            errors += [
                {"file": i["file"], "line": i["line"], "message": i["message"]} for i in ihlal
            ]

    page_objects: list[dict[str, Any]] = []
    fixtures: list[str] = []
    for k in kaynaklar:
        for s in _sinif_bildirimleri(k.agac.root_node):
            if k.metin(_alan(s, "declaration_kind")) != "class":
                continue
            ad = k.metin(_alan(s, "name"))
            miras = _miras(k, s)
            if ad == TEST_TABANI:
                for pr in _cocuklar(_alan(s, "body"), "property_declaration"):
                    deger = _alan(pr, "value")
                    adn = _alan(pr, "name")
                    if deger is not None and adn is not None and deger.type == "call_expression":
                        fixtures.append(k.metin(adn))
                continue
            if EKRAN_TABANI not in miras:
                continue
            metotlar = []
            for f in _cocuklar(_alan(s, "body"), "function_declaration"):
                d = _degistiriciler(k, f)
                if d & _GIZLI_DEGISTIRICI or d & _SINIF_DEGISTIRICI:
                    continue
                if any(
                    f.field_name_for_child(i) == "name" and c.type != "simple_identifier"
                    for i, c in enumerate(f.children)
                ):
                    continue  # dönüş türü var: eylem/beklenti değil (yardımcı)
                madi = k.metin(_alan(f, "name"))
                metotlar.append(
                    {
                        "name": madi,
                        "params": _parametreler(k, f),
                        "returns": "Void",
                        "kind": "expect" if madi.startswith("dogrula") else "action",
                        "async": False,
                        "doc": _belge(k, f),
                        "line": k.satir(f),
                    }
                )
            govde = k.metin(s)
            kullanilan = {f"{g}.{a}" for g, a in _KIMLIK_BASVURU_RE.findall(govde)}
            page_objects.append(
                {
                    "class": ad,
                    "file": k.yol,
                    "doc": _belge(k, s),
                    "methods": metotlar,
                    "locators": {a: kimlik[a] for a in sorted(kullanilan) if a in kimlik},
                }
            )
    page_objects.sort(key=lambda p: p["class"])
    if not fixtures:
        fixtures = [p["class"][:1].lower() + p["class"][1:] for p in page_objects]
    return {
        "schema_version": 1,
        "root": ".",
        "lang": AD,
        "page_objects": page_objects,
        "locator_files": locator_files,
        "errors": errors,
        "fixtures": sorted(fixtures),
        # Normalleştirilmiş görünüm (plan.md §3.3)
        "classes": [
            {
                "name": p["class"],
                "methods": [
                    {
                        "name": m["name"],
                        "params": [{"name": x["label"], "type": x["type"]} for x in m["params"]],
                        "kind": m["kind"],
                    }
                    for m in p["methods"]
                ],
            }
            for p in page_objects
        ],
        "ids": [
            {"key": a, "testId": v["testId"], "intent": v["intent"], "prefix": v["prefix"]}
            for a, v in sorted(kimlik.items())
        ],
    }


# ------------------------------------------------------------------------------ koruma


def _ihlal(k: _Kaynak, n: Any, kod: str, mesaj: str) -> dict[str, Any]:
    return {"code": kod, "file": k.yol, "line": k.satir(n), "message": mesaj}


def _karakter_ihlalleri(yol: str, veri: bytes) -> list[dict[str, Any]]:
    try:
        metin = veri.decode("utf-8")
    except UnicodeDecodeError:
        return [{"code": "kodlama", "file": yol, "line": 1, "message": "dosya UTF-8 değil"}]
    out = []
    for no, satir in enumerate(metin.split("\n"), 1):
        for ch in satir:
            if unicodedata.category(ch) in _YASAK_KATEGORI:
                out.append(
                    {
                        "code": "gorunmez_karakter",
                        "file": yol,
                        "line": no,
                        "message": f"görünmez/denetim karakteri yasak (U+{ord(ch):04X})",
                    }
                )
                break
    return out


def _literal_mi(k: _Kaynak, n: Any) -> bool:
    t = k.metin(n)
    if n.type == "line_string_literal":
        return bool(_DIZE_RE.match(t))
    if n.type == "integer_literal":
        return bool(_TAMSAYI_RE.match(t))
    if n.type == "real_literal":
        return bool(_ONDALIK_RE.match(t))
    if n.type == "boolean_literal":
        return t in ("true", "false")
    if n.type == "prefix_expression":
        op = _alan(n, "operation")
        hedef = _alan(n, "target")
        return (
            op is not None
            and k.metin(op) == "-"
            and hedef is not None
            and hedef.type in ("integer_literal", "real_literal")
            and _literal_mi(k, hedef)
        )
    if n.type == "call_expression":  # ortam("TP_TESTVERI_…")
        cs = n.named_children
        if len(cs) != 2 or cs[0].type != "simple_identifier" or k.metin(cs[0]) != "ortam":
            return False
        args = (
            _cocuklar(_cocuklar(cs[1], "value_arguments")[0])
            if _cocuklar(cs[1], "value_arguments")
            else []
        )
        return (
            len(args) == 1
            and _alan(args[0], "name") is None
            and _alan(args[0], "value") is not None
            and bool(_SIR_RE.match(k.metin(_alan(args[0], "value"))))
            and len(_cocuklar(cs[1])) == 1
        )
    return False


@dataclass(frozen=True)
class Cagri:
    erisimci: str
    metot: str
    argumanlar: tuple[tuple[str | None, str, Any], ...]  # (etiket, düğüm türü, metin)
    satir: int


def _cagri(k: _Kaynak, st: Any) -> Cagri | None:
    """`<erişimci>.<metot>(<etiket>: <literal>, …)` deyimi; biçim dışıysa None."""
    if st.type != "call_expression":
        return None
    cs = st.named_children
    if len(cs) != 2 or cs[0].type != "navigation_expression" or cs[1].type != "call_suffix":
        return None
    hedef = _alan(cs[0], "target")
    sonek = _alan(cs[0], "suffix")
    if hedef is None or hedef.type != "simple_identifier" or sonek is None:
        return None
    metot = _alan(sonek, "suffix")
    if metot is None or metot.type != "simple_identifier":
        return None
    suffix_cocuk = _cocuklar(cs[1])
    if len(suffix_cocuk) != 1 or suffix_cocuk[0].type != "value_arguments":
        return None  # sondaki kapanış (trailing closure) yasak
    argumanlar = []
    for a in _cocuklar(suffix_cocuk[0], "value_argument"):
        etiket = _alan(a, "name")
        deger = _alan(a, "value")
        if deger is None or not _literal_mi(k, deger):
            return None
        argumanlar.append(
            (k.metin(etiket) if etiket is not None else None, deger.type, k.metin(deger))
        )
    if len(argumanlar) != len(_cocuklar(suffix_cocuk[0])):
        return None
    return Cagri(k.metin(hedef), k.metin(metot), tuple(argumanlar), k.satir(st))


def uretilen_koruma(yol: str, veri: bytes) -> tuple[list[dict[str, Any]], list[Cagri]]:
    """Üretilen test dosyasının izin listesi denetimi → (ihlaller, çağrılar)."""
    ihlaller = _karakter_ihlalleri(yol, veri)
    beklenen_ad = Path(yol).stem
    k = cozumle(yol, veri)
    ihlaller += [{"code": "sozdizimi", **h} for h in _hatalar(k)]
    if ihlaller:
        return ihlaller, []
    kok = k.agac.root_node
    cagrilar: list[Cagri] = []
    importlar = siniflar = 0
    for n in kok.named_children:
        if n.type in ("comment", "multiline_comment"):
            if n.type != "comment" or not k.metin(n).startswith("//"):
                ihlaller.append(_ihlal(k, n, "yorum", "yalnız // yorumu"))
            continue
        if n.type == "import_declaration":
            importlar += 1
            if k.metin(n).split() != ["import", "XCTest"]:
                ihlaller.append(_ihlal(k, n, "import", "yalnız `import XCTest`"))
            continue
        if n.type == "class_declaration":
            siniflar += 1
            ihlaller += _sinif_korumasi(k, n, beklenen_ad, cagrilar)
            continue
        ihlaller.append(_ihlal(k, n, "ust_duzey", f"izinsiz üst düzey bildirim: {n.type}"))
    if importlar != 1:
        ihlaller.append(_ihlal(k, kok, "import", "tam bir `import XCTest` olmalı"))
    if siniflar != 1:
        ihlaller.append(_ihlal(k, kok, "sinif", "tam bir test sınıfı olmalı"))
    return ihlaller, cagrilar


def _sinif_korumasi(
    k: _Kaynak, s: Any, beklenen_ad: str, cagrilar: list[Cagri]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ad = k.metin(_alan(s, "name"))
    if k.metin(_alan(s, "declaration_kind")) != "class" or _degistiriciler(k, s) != {"final"}:
        out.append(_ihlal(k, s, "sinif", "test sınıfı `final class` olmalı"))
    if not _SINIF_RE.match(ad) or ad != beklenen_ad:
        out.append(
            _ihlal(
                k, s, "sinif_adi", f"sınıf adı dosya adıyla aynı ve <…>C<n>_<u8>Tests olmalı: {ad}"
            )
        )
    if _miras(k, s) != [TEST_TABANI]:
        out.append(_ihlal(k, s, "miras", f"test sınıfı yalnız `{TEST_TABANI}`'ndan türer"))
    if any(c.type in ("type_parameters", "type_constraints") for c in s.named_children):
        out.append(_ihlal(k, s, "sinif", "genel (generic) sınıf yasak"))
    bayi = test = 0
    for u in _cocuklar(_alan(s, "body")):
        if u.type in ("comment", "multiline_comment"):
            if u.type != "comment":
                out.append(_ihlal(k, u, "yorum", "yalnız // yorumu"))
            continue
        if u.type == "property_declaration":
            bayi += 1
            if not _bayi_ozelligi_mi(k, u):
                out.append(
                    _ihlal(
                        k, u, "ozellik", 'yalnız `override class var bayi: String? { "<bayi>" }`'
                    )
                )
            continue
        if u.type == "function_declaration":
            test += 1
            out += _test_metodu(k, u, cagrilar)
            continue
        out.append(_ihlal(k, u, "uye", f"izinsiz sınıf üyesi: {u.type}"))
    if bayi > 1:
        out.append(_ihlal(k, s, "ozellik", "en çok bir bayi özelliği"))
    if test != 1:
        out.append(_ihlal(k, s, "test", f"tam bir `func {TEST_METODU}()` olmalı"))
    return out


def _bayi_ozelligi_mi(k: _Kaynak, u: Any) -> bool:
    if _degistiriciler(k, u) != {"override", "class"} or k.metin(_alan(u, "name") or u) != "bayi":
        return False
    tur = next((c for c in u.named_children if c.type == "type_annotation"), None)
    if tur is None or re.sub(r"\s", "", k.metin(tur)) != ":String?":
        return False
    hesap = _alan(u, "computed_value")
    if hesap is None:
        return False
    st = _cocuklar(hesap, "statements")
    if len(st) != 1 or len(st[0].named_children) != 1:
        return False
    lit = st[0].named_children[0]
    return lit.type == "line_string_literal" and bool(
        re.fullmatch(r'"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"', k.metin(lit))
    )


def _test_metodu(k: _Kaynak, f: Any, cagrilar: list[Cagri]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if k.metin(_alan(f, "name")) != TEST_METODU or _degistiriciler(k, f):
        out.append(
            _ihlal(k, f, "test", f"test metodu değiştiricisiz `func {TEST_METODU}()` olmalı")
        )
    imza = k.metin(f)[: (_alan(f, "body").start_byte - f.start_byte)]
    if re.sub(r"\s", "", imza) != f"func{TEST_METODU}()":
        out.append(_ihlal(k, f, "test", "test metodu parametresiz; throws/async/dönüş türü yok"))
    govde = _alan(f, "body")
    for st in _cocuklar(govde):
        if st.type in ("comment", "multiline_comment"):
            if st.type != "comment" or not k.metin(st).startswith("//"):
                out.append(_ihlal(k, st, "yorum", "yalnız // yorumu"))
            continue
        if st.type != "statements":
            out.append(_ihlal(k, st, "deyim", f"izinsiz deyim: {st.type}"))
            continue
        for d in st.named_children:
            if d.type in ("comment", "multiline_comment"):
                if d.type != "comment":
                    out.append(_ihlal(k, d, "yorum", "yalnız // yorumu"))
                continue
            c = _cagri(k, d)
            if c is None:
                out.append(
                    _ihlal(
                        k, d, "deyim", "yalnız `<erişimci>.<metot>(<etiket>: <literal>, …)` deyimi"
                    )
                )
            else:
                cagrilar.append(c)
    return out


def kimlikler_korumasi(yol: str, veri: bytes) -> list[dict[str, Any]]:
    ihlal = _karakter_ihlalleri(yol, veri)
    if ihlal:
        return ihlal
    k = cozumle(yol, veri)
    hatalar = _hatalar(k)
    if hatalar:
        return [{"code": "sozdizimi", **h} for h in hatalar]
    return _kimlikler(k)[2]


# ------------------------------------------------------------------------------ sembol doğrulaması


def _deger_turu(dugum_turu: str, metin: str) -> str:
    if dugum_turu == "line_string_literal" or dugum_turu == "call_expression":
        return "string"
    if dugum_turu == "boolean_literal":
        return "boolean"
    if dugum_turu == "real_literal" or (
        dugum_turu == "prefix_expression" and re.search(r"[.eE]", metin)
    ):
        return "double"
    return "long"


_TUR_UYUMU = {
    "string": {"string"},
    "boolean": {"boolean"},
    "long": {"long", "int", "double"},  # tamsayı literali Double'a da geçer
    "double": {"double"},
}


def cagrilari_dogrula(
    yol: str, cagrilar: list[Cagri], tablo: dict[str, Any]
) -> list[dict[str, Any]]:
    """Her çağrı tabloda var olan bir metoda doğru etiket/sayı/türle gider mi?"""
    siniflar = {p["class"]: p for p in tablo.get("page_objects") or []}
    erisim = {s[:1].lower() + s[1:]: s for s in siniflar}
    fixtures = set(tablo.get("fixtures") or [])
    out: list[dict[str, Any]] = []

    def hata(c: Cagri, kod: str, mesaj: str) -> None:
        out.append({"code": kod, "file": yol, "line": c.satir, "message": mesaj})

    for c in cagrilar:
        sinif = erisim.get(c.erisimci)
        if sinif is None or (fixtures and c.erisimci not in fixtures):
            hata(c, "bilinmeyen_erisimci", f"{c.erisimci}: TestTabani'nda ekran erişimcisi yok")
            continue
        metot = next((m for m in siniflar[sinif]["methods"] if m["name"] == c.metot), None)
        if metot is None:
            hata(c, "bilinmeyen_metot", f"{sinif}.{c.metot} ekran nesnesi kütüphanesinde yok")
            continue
        params = metot["params"]
        zorunlu = sum(1 for p in params if not p.get("optional"))
        if not zorunlu <= len(c.argumanlar) <= len(params):
            hata(c, "arguman_sayisi", f"{sinif}.{c.metot} {zorunlu}–{len(params)} argüman alır")
            continue
        for p, (etiket, tur, metin) in zip(params, c.argumanlar, strict=False):
            beklenen_etiket = None if p["label"] == "_" else p["label"]
            if etiket != beklenen_etiket:
                hata(
                    c,
                    "etiket",
                    f"{sinif}.{c.metot}: '{p['name']}' etiketi {beklenen_etiket!r} olmalı, "
                    f"{etiket!r} verildi",
                )
                continue
            if p["type"] not in _TUR_UYUMU.get(_deger_turu(tur, metin), set()):
                hata(
                    c,
                    "tur",
                    f"{sinif}.{c.metot}({p['name']}: {p.get('swift_type')}) için tür uyumsuz "
                    f"değer: {metin}",
                )
    return out


# ------------------------------------------------------------------------------ kök / git


def kok(cfg: Any, platform: str | None = "ios") -> str:
    """UI test klasörünün forge'daki yolu: proje bloğu (`cfg.dil_kokleri`) > `<AYAR>_<P>` env >
    `<AYAR>` env > varsayılan. Ş0 `worker.diller.kok` varsa o kullanılır."""
    try:  # pragma: no cover - Ş0 entegrasyonu
        from worker.diller import kok as genel_kok  # type: ignore[attr-defined]

        return str(genel_kok(cfg, KOK_AYARI, KOK_VARSAYILAN, platform)).strip("/") or KOK_VARSAYILAN
    except ImportError:
        pass
    bloklar = getattr(cfg, "dil_kokleri", None) or {}
    p = (platform or "ios").upper()
    for deger in (
        bloklar.get(f"{KOK_AYARI}_{p}"),
        bloklar.get(KOK_AYARI),
        os.environ.get(f"{KOK_AYARI}_{p}"),
        os.environ.get(KOK_AYARI),
    ):
        if deger and deger.strip("/"):
            return deger.strip("/")
    return KOK_VARSAYILAN


def validate_test_file(yol: str) -> str:
    if not isinstance(yol, str) or not TEST_DOSYASI_RE.match(yol):
        raise ValueError(
            f"Swift test dosyası `{URETILEN_DIZINI}/<…>C<n>_<u8>Tests.swift` olmalı: {yol!r}"
        )
    return yol


def _git(cfg: Any, repo: Path, *args: str) -> bytes:
    from toolchain_common import gitforge

    try:
        out = subprocess.run(
            gitforge._git_argv(repo, *args),
            env=gitforge.git_env(),
            capture_output=True,
            timeout=cfg.git_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise gitforge.ForgeError("git süre aşımı") from exc
    if out.returncode != 0:
        raise gitforge.ForgeError(
            f"git {args[0]} başarısız: {out.stderr.decode('utf-8', 'replace').strip()[:300]}"
        )
    return out.stdout


def kok_korumasi(kokdizin: Path) -> dict[str, Any]:
    """Checkout edilmiş kökte: üretilen testler + Kimlikler saflığı (+ çağrılar)."""
    uretilen = kokdizin / URETILEN_DIZINI
    dosyalar: list[str] = []
    ihlaller: list[dict[str, Any]] = []
    cagrilar: dict[str, list[Cagri]] = {}
    if uretilen.is_dir() and not uretilen.is_symlink():
        for p in sorted(uretilen.rglob("*")):
            rel = p.relative_to(kokdizin).as_posix()
            if p.is_dir() or p.name == ".gitkeep":
                continue
            if p.is_symlink() or not TEST_DOSYASI_RE.match(rel):
                ihlaller.append(
                    {
                        "code": "dosya",
                        "file": rel,
                        "line": 1,
                        "message": (
                            f"{URETILEN_DIZINI}/ altında yalnız üretilen test dosyası olabilir"
                        ),
                    }
                )
                continue
            dosyalar.append(rel)
            ih, cg = uretilen_koruma(rel, p.read_bytes())
            ihlaller += ih
            cagrilar[rel] = cg
    kim = kokdizin / KIMLIKLER
    if kim.is_file() and not kim.is_symlink():
        ihlaller += kimlikler_korumasi(KIMLIKLER, kim.read_bytes())
    else:
        ihlaller.append(
            {
                "code": "kimlikler_yok",
                "file": KIMLIKLER,
                "line": 1,
                "message": "ekran nesnesi kütüphanesi (Ekranlar/Kimlikler.swift) yok",
            }
        )
    return {"files": dosyalar, "violations": ihlaller, "cagrilar": cagrilar}


def onarim_korumasi(cfg: Any, repo: Path, base: str, head: str, kok_yolu: str) -> dict[str, Any]:
    """Onarım (repair): base..head'de yalnız Kimlikler.swift dize değerleri değişir."""
    ham = _git(
        cfg, repo, "diff", "--name-status", "--no-renames", "-z", "--end-of-options", base, head
    )
    parcalar = [p for p in ham.decode("utf-8", "replace").split("\0") if p]
    hedef = f"{kok_yolu.strip('/')}/{KIMLIKLER}"
    degisen: list[dict[str, Any]] = []
    ihlaller: list[dict[str, Any]] = []
    testid: list[dict[str, Any]] = []
    for durum, yol in zip(parcalar[0::2], parcalar[1::2], strict=False):
        st = {"A": "added", "D": "deleted"}.get(durum[:1], "modified")
        kimlik_mi = yol == hedef
        degisen.append({"path": yol, "status": st, "locator": kimlik_mi})
        if not kimlik_mi:
            ihlaller.append(
                {
                    "code": "non_locator_file_changed",
                    "file": yol,
                    "message": f"onarımda yalnızca {KIMLIKLER} değişebilir",
                }
            )
            continue
        if st != "modified":
            ihlaller.append(
                {
                    "code": f"locator_file_{st}",
                    "file": yol,
                    "message": "Kimlikler.swift onarımda eklenemez/silinemez",
                }
            )
            continue
        a = cozumle(yol, _git(cfg, repo, "show", f"{base}:{yol}"))
        b_veri = _git(cfg, repo, "show", f"{head}:{yol}")
        ihlaller += kimlikler_korumasi(yol, b_veri)
        b = cozumle(yol, b_veri)
        eski, yeni = _kimlikler(a)[0], _kimlikler(b)[0]
        if set(eski) != set(yeni):
            ihlaller.append(
                {
                    "code": "locator_keys_changed",
                    "file": yol,
                    "message": "onarımda kimlik anahtarı eklenemez/silinemez",
                }
            )
        for anahtar in sorted(set(eski) & set(yeni)):
            if eski[anahtar]["testId"] != yeni[anahtar]["testId"]:
                testid.append(
                    {"key": anahtar, "from": eski[anahtar]["testId"], "to": yeni[anahtar]["testId"]}
                )
    return {"changed_files": degisen, "violations": ihlaller, "testid_changes": testid}


def _rapor(
    mode: str, base: str, head: str, kok_yolu: str, gen: dict[str, Any], rep: dict[str, Any] | None
) -> dict[str, Any]:
    ihlaller = list(gen["violations"]) + list((rep or {}).get("violations") or [])
    ok = not ihlaller
    return {
        "tool": "tree-sitter-swift",
        "schema_version": 1,
        "mode": mode,
        "ok": ok,
        "noop": False,
        "base": base,
        "head": head,
        "root": kok_yolu,
        "files": gen["files"],
        "changed_files": (rep or {}).get("changed_files", []),
        "testid_changes": (rep or {}).get("testid_changes", []),
        "added_entries": [],
        "removed_entries": [],
        "violations": ihlaller,
        "summary": (
            f"Swift koruması {'geçti' if ok else 'başarısız'} (mod: {mode}) · üretilen test: "
            f"{len(gen['files'])} · ihlal: {len(ihlaller)}"
        ),
    }


# ------------------------------------------------------------------------------ eklenti nesnesi


class _SwiftWorker:
    ad = AD
    platformlar = PLATFORMLAR
    steps = STEPS
    hat = HAT

    def validate_test_file(self, yol: str) -> str:
        return validate_test_file(yol)

    def symbols(self, cfg: Any, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
        from toolchain_common import gitforge

        kok_yolu = kok(cfg, platform)
        with gitforge.checkout(repo, full_sha, kok_yolu, cfg.git_timeout_s) as kokdizin:
            tablo = semboller(kokdizin)
        tablo["root"] = kok_yolu
        tablo["platform"] = platform
        return tablo

    def guard(
        self, cfg: Any, repo: Path, base: str, head: str, mode: str, platform: str
    ) -> dict[str, Any]:
        from toolchain_common import gitforge

        kok_yolu = kok(cfg, platform)
        with gitforge.checkout(repo, head, kok_yolu, cfg.git_timeout_s) as kokdizin:
            gen = kok_korumasi(kokdizin)
        rep = onarim_korumasi(cfg, repo, base, head, kok_yolu) if mode == "repair" else None
        return _rapor(mode, base, head, kok_yolu, gen, rep)

    def run_static(
        self,
        cfg: Any,
        req: Any,
        head: Any,
        base: str | None,
        runner_client: Any,
        steps: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """guard → semboller. Koşu yok (müşteri CI); `runner_client` kullanılmaz."""
        from toolchain_common import gitforge

        platform = getattr(req, "platform", None) or "ios"
        kok_yolu = kok(cfg, platform)
        full = head.sha
        base_sha = base or gitforge.merge_base(head.repo, full, "main", cfg.git_timeout_s) or full
        mode = getattr(req, "ast_guard_mode", "pr")
        try:
            with gitforge.checkout(head.repo, full, kok_yolu, cfg.git_timeout_s) as kokdizin:
                eksik = [f for f in req.test_files if not (kokdizin / f).is_file()]
                if eksik:
                    steps["guard"] = {
                        "ok": False,
                        "error": "Test dosyası commit'te yok: " + ", ".join(eksik),
                        "missing_test_files": eksik,
                    }
                    return steps
                gen = kok_korumasi(kokdizin)
                rep = (
                    onarim_korumasi(cfg, head.repo, base_sha, full, kok_yolu)
                    if mode == "repair"
                    else None
                )
                rapor = _rapor(mode, base_sha, full, kok_yolu, gen, rep)
                steps["guard"] = {
                    "ok": rapor["ok"],
                    "mode": mode,
                    "base_sha": base_sha,
                    "report": rapor,
                }
                if not rapor["ok"]:
                    return steps
                tablo = semboller(kokdizin)
        except (SwiftAracError, gitforge.ForgeError) as exc:
            steps["guard"] = {"ok": False, "mode": mode, "error": str(exc)}
            return steps
        ihlaller: list[dict[str, Any]] = []
        for yol, cagrilar in gen["cagrilar"].items():
            ihlaller += cagrilari_dogrula(yol, cagrilar, tablo)
        steps["semboller"] = {
            "ok": not ihlaller,
            "violations": ihlaller,
            "page_objects": len(tablo["page_objects"]),
            "errors": tablo["errors"],
        }
        return steps


EKLENTI = _SwiftWorker()
