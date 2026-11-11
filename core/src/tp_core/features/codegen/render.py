"""Doğrulanmış eşlemeden Playwright testini şablonla üretir (TEKNIK-TASARIM §8.4 adım 4).

Model TypeScript yazmaz (Constitution IV): `rules/templates/playwright_test.ts.j2` yalnızca
deterministik kontrollerden geçmiş `step_mapping` / `expects` ile render edilir.

- Değerler `ts` süzgeciyle JSON literal basılır (`json.dumps`, NaN/∞ reddedilir; U+2028/2029
  kaçışlanır). Yalnızca str / sayı / bool (ve bunların listesi) kabul edilir.
- Fikstür ve metot adları tanımlayıcı dilbilgisine uymalıdır (`ident`); kontroller ayrıca sembol
  tablosundaki varlığı denetlemiştir.
- Yorumlar tek satıra indirgenir, kontrol karakterleri ve satır ayırıcıları silinir.
- Case bir e2e bayisiyle giriş yapıyorsa (`LoginPage.login("bayi2", …)`) test o bayiye sabitlenir
  (`test.use({ dealerUsername })`, demo-app fixtures sözleşmesi): bayiye özgü değerler (kredi
  limiti) doğru bayide doğrulanır ve bayi kilidi paralel işçilerle çakışmayı önler.
- Çıktı deterministiktir (zaman/rastgelelik yok); dosya adı case'e göre sabittir
  (`<e2e kökü>/tests/generated/<story>-c<sıra>-<case uuid'nin ilk 8'i>.spec.ts`; e2e kökü
  LocalForge'da `e2e`, GitHub monoreposunda `demo-app/e2e`). Yeniden üretim aynı dosya yolunu
  main'den açılan YENİ bir dala yazar (service `_dal_sec`); merge'de main'deki dosyanın yerini alır.

Üretim dili (011 §2.7): tek giriş noktası `render_dil(inp, dil=…, platform=…, rules=…)`.
`ts` → `render_test`, `java` → `render_java_test` (uygulama: Appium; web: Playwright for Java),
`csharp` / `python` → doğrulanmamış çıktı (dosyanın sonundaki bölüm). Model hiçbir dilde kod
yazmaz; her dilin kendi literal/tanımlayıcı/yorum süzgeci vardır.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jinja2

from tp_core.audit import content_hash
from tp_core.audit.canonical import sha256_hex
from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen.checks import IDENT_RE, fixture_name

TEMPLATE_NAME = "playwright_test.ts.j2"
GENERATED_DIR = "tests/generated"  # e2e köküne göre
E2E_ROOT = "e2e"  # forge deposunda (LocalForge düzeni; GitHub'da `<uygulama kökü>/e2e`)
URETILEN_ETIKETI = "@tp-uretilen"
_KONTROL = re.compile(r"[\x00-\x1f\x7f\u0085\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_STORY_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
_DEALER_RE = re.compile(
    r"\{\s*username:\s*\"(?P<u>[A-Za-z0-9_.-]+)\"\s*,\s*password:\s*\"(?P<p>[^\"\\]*)\"\s*,"
    r"\s*name:\s*\"(?P<n>[^\"\\]*)\"\s*\}"
)


class RenderError(ValueError):
    """Şablona güvensiz/geçersiz değer gitti (kontrollerin kaçırdığı bir durum: insana)."""


# ----------------------------------------------------------------------------- süzgeçler


def _ts_deger(value: Any) -> Any:
    if isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise RenderError("sonlu olmayan sayı şablona basılamaz")
        return value
    if isinstance(value, list | tuple):
        return [_ts_deger(v) for v in value]
    raise RenderError(f"şablona basılamayan değer türü: {type(value).__name__}")


def ts_literal(value: Any) -> str:
    """TypeScript'e JSON literal olarak basılan değer (JSON.stringify eşdeğeri)."""
    metin = json.dumps(_ts_deger(value), ensure_ascii=False, allow_nan=False)
    return metin.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def ident(value: Any) -> str:
    if not isinstance(value, str) or not IDENT_RE.match(value):
        raise RenderError(f"geçersiz tanımlayıcı: {value!r}")
    return value


def comment(value: Any) -> str:
    ham = str(value if value is not None else "-")
    metin = _KONTROL.sub(" ", unicodedata.normalize("NFC", ham))
    metin = re.sub(r"\s+", " ", metin).strip() or "-"
    return metin if len(metin) <= 160 else metin[:159] + "…"


def args_literal(args: Sequence[Any]) -> str:
    return ", ".join(ts_literal(a) for a in args)


def _env(templates_dir: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=False,  # TypeScript üretilir; kaçış `ts` süzgecindedir
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["ts"] = ts_literal
    env.filters["ident"] = ident
    env.filters["comment"] = comment
    env.filters["args"] = args_literal
    return env


@lru_cache(maxsize=8)
def _template(templates_dir: str) -> tuple[jinja2.Template, str]:
    path = Path(templates_dir) / TEMPLATE_NAME
    kaynak = path.read_text(encoding="utf-8")
    return _env(Path(templates_dir)).get_template(TEMPLATE_NAME), sha256_hex(kaynak)


def templates_dir(rules_dir: Path) -> Path:
    return Path(rules_dir) / "templates"


# ------------------------------------------------------------------------------ girdi


def parse_dealers(fixtures_source: str) -> dict[str, dict[str, str]]:
    """`tests/fixtures.ts` `DEALERS` listesindeki e2e bayileri (çalıştırılmaz; sözdizimsel)."""
    m = re.search(r"DEALERS\s*:[^=]*=\s*\[(?P<govde>.*?)\]\s*;", fixtures_source, re.S)
    if m is None:
        return {}
    return {
        d.group("u"): {"password": d.group("p"), "name": d.group("n")}
        for d in _DEALER_RE.finditer(m.group("govde"))
    }


@dataclass(frozen=True)
class RenderInput:
    case_id: uuid.UUID
    case: Mapping[str, Any]
    sira_no: int
    story_key: str | None
    test_key: str | None
    case_hash: str
    mode: str | None
    bundle_hash: str | None
    mapping: Mapping[str, Any]
    dealers: Mapping[str, Mapping[str, str]]
    # Forge deposunda e2e kökü (`e2e` LocalForge; GitHub monoreposunda `demo-app/e2e`).
    e2e_root: str = E2E_ROOT


@dataclass(frozen=True)
class Rendered:
    content: str
    # Tam hat dillerinde forge deposundaki yol (e2e/tests/generated/…). Doğrulanmamış dillerde
    # forge'a yazılmaz: önerilen dosya yolu / indirme adıdır (`tests/Generated/<Sinif>Tests.cs`).
    repo_path: str
    test_file: str  # test projesi köküne göre (toolchain /check `test_files`)
    template_hash: str
    mapping_hash: str
    dealer: str | None
    # 011 üretim dili: `ts` | `java` | `csharp` | `python`.
    dil: str = "ts"
    sinif_adi: str | None = None  # java / csharp test sınıfı (ts / python: yok)
    test_adi: str | None = None  # ts: test başlığı; java / csharp: metot; python: test işlevi
    dogrulanmamis: bool = False  # csharp / python: derlenmedi, koşulmadı (PR'a giremez)
    referans_dil: str | None = None  # doğrulanmamışta adların türetildiği sembol tablosunun dili

    @property
    def kaynak(self) -> str:
        """Render edilen kaynak metin (`content` ile aynı; 011 §2.7 adı)."""
        return self.content


def slug(story_key: str | None, sira_no: int, case_id: uuid.UUID) -> str:
    kok = story_key.lower() if story_key and _STORY_RE.match(story_key) else "serbest"
    return f"{kok}-c{int(sira_no)}-{case_id.hex[:8]}"


def mapping_hash(mapping: Mapping[str, Any]) -> str:
    return content_hash(
        {"step_mapping": mapping.get("step_mapping") or [], "expects": mapping.get("expects") or []}
    )


def _pinned_dealer(
    mapping: Mapping[str, Any],
    dealers: Mapping[str, Any],
    login_metotlari: frozenset[str] = frozenset({"login"}),
) -> str | None:
    """Case'in giriş yaptığı e2e bayisi (tek ve bilinen ise)."""
    bulunan = {
        m["args"][0]
        for m in mapping.get("step_mapping") or []
        if m.get("method") in login_metotlari
        and m.get("args")
        and isinstance(m["args"][0], str)
        and m["args"][0] in dealers
    }
    return next(iter(bulunan)) if len(bulunan) == 1 else None


def build_context(inp: RenderInput, template_hash: str) -> dict[str, Any]:
    case = inp.case
    adimlar = {str(s.get("id")): s for s in case.get("steps") or [] if isinstance(s, Mapping)}
    kullanilan: list[str] = []

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        fx = ident(fixture_name(ident(str(item.get("po")))))
        if fx not in kullanilan:
            kullanilan.append(fx)
        return {"fixture": fx, "method": ident(str(item.get("method"))), "args": list(item["args"])}

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        steps.append({"sid": sid, "label": f"{sid} — {eylem}", "calls": [cagri(m)]})
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    story = inp.story_key if inp.story_key and _STORY_RE.match(inp.story_key) else None
    case_ref = f"{story or 'SERBEST'}-C{int(inp.sira_no)}"
    tags = [f"@tp-case-{inp.case_id}"] + ([f"@{story}"] if story else [])
    return {
        "case_ref": case_ref,
        "case_id": str(inp.case_id),
        "story_key": story or "-",
        "test_key": inp.test_key or "-",
        "case_hash": inp.case_hash,
        "mode": inp.mode or "-",
        "bundle_hash": inp.bundle_hash or "-",
        "mapping_hash": mapping_hash(inp.mapping),
        "template_hash": template_hash,
        "dealer": _pinned_dealer(inp.mapping, inp.dealers),
        "describe": f"{story or 'Serbest metin'} · C{int(inp.sira_no)}",
        "title": f"{str(case.get('title') or case_ref).strip()} {URETILEN_ETIKETI}",
        "tags": tags,
        "fixtures": sorted(kullanilan),
        "steps": steps,
        "expects": expects,
    }


def render_test(inp: RenderInput, rules_dir: Path) -> Rendered:
    template, template_hash = _template(str(templates_dir(rules_dir)))
    ctx = build_context(inp, template_hash)
    try:
        content = template.render(**ctx)
    except jinja2.TemplateError as exc:  # pragma: no cover - şablon hatası (geliştirici)
        raise RenderError(f"şablon render edilemedi: {exc}") from exc
    ad = slug(inp.story_key, inp.sira_no, inp.case_id)
    test_file = f"{GENERATED_DIR}/{ad}.spec.ts"
    return Rendered(
        content=content,
        repo_path=f"{inp.e2e_root.strip('/') or E2E_ROOT}/{test_file}",
        test_file=test_file,
        template_hash=template_hash,
        mapping_hash=ctx["mapping_hash"],
        dealer=ctx["dealer"],
        dil="ts",
        test_adi=ctx["title"],
    )


# ============================================================ Java / Appium / TestNG (009 §2.8)
#
# Platform `android` | `ios` | `windows` için aynı eşleme `rules/templates/appium_testng.java.j2`
# ile Java'ya render edilir. Dosya: `<e2e-app kökü>/src/test/java/com/antreklabs/bayi/uretilen/
# <Story><Platform>C<sıra>_<uuid8>Test.java` (ör. `TPD1AndroidC3_0a1b2c3dTest.java`): bir case'in
# her platformdaki script'i ayrı dosyadır, dallar/PR'lar merge'de çakışmaz. Ad `java-araclar guard`
# dosya adı kuralına (`^[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Test\.java$`) uyar. Test TestNG
# gruplarında platformunu taşır (`uretilen`, `<platform>`, `tp-case-<uuid>`, story): CI platform
# koşusu yalnız kendi platformunun üretilen testlerini seçebilir.

JAVA_TEMPLATE_NAME = "appium_testng.java.j2"
# Web + Java (011 §2.5, §2.7): Playwright for Java + TestNG; hedef proje `<uygulama kökü>/e2e-java`.
# Biçim uygulama Java şablonuyla aynıdır (aynı `java-araclar guard` izin listesi); sınıf adı
# `<Story>WebC<sıra>_<uuid8>Test`, gruplar `uretilen`, `web`, `tp-case-<uuid>`, story.
JAVA_WEB_TEMPLATE_NAME = "playwright_testng.java.j2"
E2E_JAVA_ROOT = "e2e-java"  # LocalForge düzeni; GitHub: `<uygulama kökü>/e2e-java`
JAVA_TEST_METODU = "senaryo"
JAVA_GENERATED_DIR = platformlar.JAVA_URETILEN_DIZIN  # e2e-app köküne göre (tek kaynak)
E2E_APP_ROOT = platformlar.E2E_APP_DIZINI  # LocalForge düzeni; GitHub: `<uygulama kökü>/e2e-app`
JAVA_URETILEN_GRUBU = "uretilen"
# Java giriş metodu (bayi sabitleme): web `LoginPage.login` ↔ `GirisEkrani.girisYap`.
LOGIN_METOTLARI = frozenset({"login", "girisYap"})
_JAVA_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JAVA_SINIF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Test$")
_JAVA_GRUP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_JAVA_BAYI_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_JAVA_DOUBLE_RE = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")
# Java string literalinde kaçışlı basılanlar; diğer kontrol/biçim karakterleri reddedilir.
_JAVA_KACIS = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
# java-araclar KarakterDenetimi: CONTROL, FORMAT, LINE/PARAGRAPH_SEPARATOR, PRIVATE_USE, SURROGATE,
# UNASSIGNED yasak (insan incelemesinde görülen metin derlenen metinle aynı olmalı).
_JAVA_YASAK_KATEGORI = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"})
_JAVA_INT = (-(2**31), 2**31 - 1)
_JAVA_LONG = (-(2**63), 2**63 - 1)
_JAVA_ANAHTAR = frozenset(
    [
        "_",
        "abstract",
        "assert",
        "boolean",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "class",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extends",
        "false",
        "final",
        "finally",
        "float",
        "for",
        "goto",
        "if",
        "implements",
        "import",
        "instanceof",
        "int",
        "interface",
        "long",
        "native",
        "new",
        "null",
        "package",
        "private",
        "protected",
        "public",
        "return",
        "short",
        "static",
        "strictfp",
        "super",
        "switch",
        "synchronized",
        "this",
        "throw",
        "throws",
        "transient",
        "true",
        "try",
        "void",
        "volatile",
        "while",
    ]
)
_BAYILER_RE = re.compile(
    r"new\s+BayiBilgisi\(\s*\"(?P<u>[A-Za-z0-9_.-]+)\"\s*,\s*\"(?P<p>[^\"\\]*)\"\s*,"
    r"\s*\"(?P<n>[^\"\\]*)\"\s*\)"
)


def _java_metin(value: str) -> str:
    out = []
    for ch in value:
        if ch in _JAVA_KACIS:
            out.append(_JAVA_KACIS[ch])
        elif unicodedata.category(ch) in _JAVA_YASAK_KATEGORI:
            raise RenderError(
                f"Java literaline basılamayan karakter (U+{ord(ch):04X}); değer reddedildi"
            )
        else:
            out.append(ch)  # ASCII dışı karakter ham UTF-8 (\uXXXX kaçışı guard'da yasak)
    return '"' + "".join(out) + '"'


def java_literal(value: Any) -> str:
    """Java literali: String / int / long (`L`) / double / boolean. Başka tür → RenderError.

    `java-araclar guard`'ın kabul ettiği literal biçimleri üretilir (negatif sayı tekli eksiyle);
    sonlu olmayan sayı, 64 biti aşan tamsayı ve kontrol/görünmez karakterli metin reddedilir.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if _JAVA_INT[0] <= value <= _JAVA_INT[1]:
            return str(value)
        if _JAVA_LONG[0] <= value <= _JAVA_LONG[1]:
            return f"{value}L"
        raise RenderError(f"Java long aralığı dışında tamsayı: {value}")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise RenderError("sonlu olmayan sayı şablona basılamaz")
        metin = repr(value)
        if not _JAVA_DOUBLE_RE.fullmatch(metin):
            raise RenderError(f"Java double literaline çevrilemeyen sayı: {metin}")
        return metin
    if isinstance(value, str):
        return _java_metin(value)
    raise RenderError(f"şablona basılamayan değer türü: {type(value).__name__}")


def java_comment(value: Any) -> str:
    """Java `//` yorumu: `comment` + javac'ın yorumda bile işlediği Unicode kaçışı (ters bölü + u)
    etkisizleştirilir (ters bölü `/` olur) ve görünmez/biçim karakterleri boşluk olur (guard
    `KarakterDenetimi` ile aynı kategoriler)."""
    metin = comment(value).replace("\\", "/")
    temiz = "".join(" " if unicodedata.category(ch) in _JAVA_YASAK_KATEGORI else ch for ch in metin)
    return re.sub(r"\s+", " ", temiz).strip() or "-"


def java_args(args: Sequence[Any]) -> str:
    return ", ".join(java_literal(a) for a in args)


def java_ident(value: Any) -> str:
    if not isinstance(value, str) or not _JAVA_IDENT_RE.match(value):
        raise RenderError(f"geçersiz Java tanımlayıcısı: {value!r}")
    if value in _JAVA_ANAHTAR:
        # Ör. TS page object metodu `goto`: Java'da ayrılmış sözcük, metot adı olamaz (011 §2.5).
        raise RenderError(f"Java ayrılmış sözcüğü tanımlayıcı olamaz: {value!r}")
    return value


def java_class_name(story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID) -> str:
    """`<Story><Platform>C<sıra>_<uuid8>Test` (Java tanımlayıcısı; guard dosya adı kuralı)."""
    kok = story_key if story_key and _STORY_RE.match(story_key) else "Serbest"
    kok = re.sub(r"[^A-Za-z0-9]", "", kok)
    ad = f"{kok}{platform[:1].upper()}{platform[1:]}C{int(sira_no)}_{case_id.hex[:8]}Test"
    if not _JAVA_SINIF_RE.match(ad):
        raise RenderError(f"üretilen Java sınıf adı geçersiz: {ad}")
    return ad


def java_repo_path(
    e2e_app_root: str, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
) -> str:
    kok = e2e_app_root.strip("/") or E2E_APP_ROOT
    ad = java_class_name(story_key, platform, sira_no, case_id)
    return f"{kok}/{JAVA_GENERATED_DIR}/{ad}.java"


def parse_java_dealers(bayiler_source: str) -> dict[str, dict[str, str]]:
    """`altyapi/Bayiler.java` `E2E = List.of(new BayiBilgisi(…), …)` bayileri (sözdizimsel)."""
    m = re.search(r"\bE2E\s*=\s*List\.of\((?P<govde>.*?)\)\s*;", bayiler_source, re.S)
    if m is None:
        return {}
    return {
        d.group("u"): {"password": d.group("p"), "name": d.group("n")}
        for d in _BAYILER_RE.finditer(m.group("govde"))
    }


def _java_env(templates_dir: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=False,  # Java üretilir; kaçış `java` süzgecindedir
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["java"] = java_literal
    env.filters["ident"] = java_ident
    env.filters["comment"] = java_comment
    env.filters["jargs"] = java_args
    return env


@lru_cache(maxsize=8)
def _java_template(templates_dir: str, ad: str = JAVA_TEMPLATE_NAME) -> tuple[jinja2.Template, str]:
    path = Path(templates_dir) / ad
    kaynak = path.read_text(encoding="utf-8")
    return _java_env(Path(templates_dir)).get_template(ad), sha256_hex(kaynak)


def build_java_context(inp: RenderInput, platform: str, template_hash: str) -> dict[str, Any]:
    case = inp.case
    adimlar = {str(s.get("id")): s for s in case.get("steps") or [] if isinstance(s, Mapping)}

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "fixture": java_ident(fixture_name(java_ident(str(item.get("po"))))),
            "method": java_ident(str(item.get("method"))),
            "args": list(item["args"]),
        }

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        steps.append({"sid": sid, "label": f"{sid} — {eylem}", "calls": [cagri(m)]})
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    story = inp.story_key if inp.story_key and _STORY_RE.match(inp.story_key) else None
    gruplar = [JAVA_URETILEN_GRUBU, platform, f"tp-case-{inp.case_id}"] + ([story] if story else [])
    for g in gruplar:
        if not _JAVA_GRUP_RE.match(g):
            raise RenderError(f"geçersiz TestNG grubu: {g!r}")
    dealer = _pinned_dealer(inp.mapping, inp.dealers, LOGIN_METOTLARI)
    if dealer is not None and not _JAVA_BAYI_RE.match(dealer):
        raise RenderError(f"geçersiz bayi adı: {dealer!r}")
    ref = f"{story or 'SERBEST'} C{int(inp.sira_no)}"
    return {
        "case_ref": ref,
        "case_id": str(inp.case_id),
        "story_key": story or "-",
        "test_key": inp.test_key or "-",
        "case_hash": inp.case_hash,
        "platform": platform,
        "mode": inp.mode or "-",
        "bundle_hash": inp.bundle_hash or "-",
        "mapping_hash": mapping_hash(inp.mapping),
        "template_hash": template_hash,
        "dealer": dealer,
        "class_name": java_class_name(inp.story_key, platform, inp.sira_no, inp.case_id),
        "groups": gruplar,
        "description": str(case.get("title") or "").strip() or ref,
        "steps": steps,
        "expects": expects,
    }


def render_java_test(inp: RenderInput, platform: str, rules_dir: Path) -> Rendered:
    """Java/TestNG testi. Uygulama platformu (009 §2.8): Appium şablonu, `inp.e2e_root` forge'daki
    e2e-app köküdür. `web` (011 §2.5): Playwright for Java şablonu, `inp.e2e_root` e2e-java köküdür.
    `test_file` proje köküne göredir (toolchain `/check` Java `test_files`)."""
    web = platform == platformlar.WEB
    template, template_hash = _java_template(
        str(templates_dir(rules_dir)), JAVA_WEB_TEMPLATE_NAME if web else JAVA_TEMPLATE_NAME
    )
    ctx = build_java_context(inp, platform, template_hash)
    try:
        content = template.render(**ctx)
    except jinja2.TemplateError as exc:  # pragma: no cover - şablon hatası (geliştirici)
        raise RenderError(f"şablon render edilemedi: {exc}") from exc
    test_file = f"{JAVA_GENERATED_DIR}/{ctx['class_name']}.java"
    return Rendered(
        content=content,
        repo_path=(
            f"{inp.e2e_root.strip('/') or (E2E_JAVA_ROOT if web else E2E_APP_ROOT)}/{test_file}"
        ),
        test_file=test_file,
        template_hash=template_hash,
        mapping_hash=ctx["mapping_hash"],
        dealer=ctx["dealer"],
        dil="java",
        sinif_adi=ctx["class_name"],
        test_adi=JAVA_TEST_METODU,
    )


# ================================================== doğrulanmamış diller: C# / Python (011 §2.7)
#
# `csharp` (Playwright .NET + NUnit) ve `python` (pytest-playwright) için aynı eşlemeden idiomatik
# test render edilir; çıktı DERLENMEZ / KOŞULMAZ (K3): forge'a yazılmaz, PR açılmaz. Page object
# kütüphanesi bu dillerde yoktur: adlar referans sembol tablosundaki (ts, yoksa java) adlardan
# türetilir — sınıf adı aynı; C#'ta metot PascalCase (`addToCart` → `AddToCart`), Python'da metot,
# değişken ve modül snake_case (`addToCart` → `add_to_cart`, `LoginPage` → `pages.login_page`).
# Dosya başlığı bunu açıkça yazar (`DOGRULANMAMIS_BASLIK`).
#
# Enjeksiyon: değerler `cs_literal` / `py_literal` ile yalnız düz (önek almayan) çift tırnaklı dize,
# sayı, bool ve null literali olur — C#'ta verbatim (`@"…"`) / interpolasyon (`$"…"`) / ham dize
# (`"""…"""`), Python'da f-string / üç tırnak / bytes ÜRETİLMEZ; `{` `}` bu yüzden düz karakterdir.
# Kontrol, biçim (yön denetimi, sıfır genişlik) ve satır ayırıcı karakterler `\uXXXX` kaçışıyla
# basılır (değer korunur, kaynakta görünür). Yorumlar tek satırdır.

CS_TEMPLATE_NAME = "playwright_nunit.cs.j2"
PY_TEMPLATE_NAME = "pytest_playwright.py.j2"
CS_GENERATED_DIR = "tests/Generated"
PY_GENERATED_DIR = "tests/generated"
DOGRULANMAMIS_KOKLER: dict[str, str] = {"csharp": "e2e-csharp", "python": "e2e-python"}
CS_NAMESPACE = "Antreklabs.Bayi.Tests.Generated"
CS_PO_NAMESPACE = "Antreklabs.Bayi.Pages"
CS_TEST_METODU = "Senaryo"
PY_PO_PAKETI = "pages"
DILLER: tuple[str, ...] = platformlar.DILLER  # tek kaynak platform.py
DOGRULANMAMIS_DILLER: tuple[str, ...] = platformlar.DOGRULANMAMIS_DILLER
REFERANS_DIL_ETIKETI = {"ts": "TypeScript", "java": "Java"}
DOGRULANMAMIS_BASLIK = (
    "Doğrulanmamış çıktı: adımlar tarayıcıda doğrulandı; bu kod derlenmedi ve koşulmadı; "
    "page object kütüphanesi {referans} tablosundan türetilen adları varsayar."
)
_DUZ_KACIS = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
# `\uXXXX` ile basılan kategoriler (yedek çift — Cs — reddedilir: UTF-8'e yazılamaz).
_KACISLI_KATEGORI = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cn"})
_CS_SINIF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Tests$")
_PY_TEST_RE = re.compile(r"^test_[a-z0-9_]+$")
_ETIKET_RE = _JAVA_GRUP_RE
_DEVE_SINIRI = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_CS_ANAHTAR = frozenset(
    [
        "abstract",
        "as",
        "base",
        "bool",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "checked",
        "class",
        "const",
        "continue",
        "decimal",
        "default",
        "delegate",
        "do",
        "double",
        "else",
        "enum",
        "event",
        "explicit",
        "extern",
        "false",
        "finally",
        "fixed",
        "float",
        "for",
        "foreach",
        "goto",
        "if",
        "implicit",
        "in",
        "int",
        "interface",
        "internal",
        "is",
        "lock",
        "long",
        "namespace",
        "new",
        "null",
        "object",
        "operator",
        "out",
        "override",
        "params",
        "private",
        "protected",
        "public",
        "readonly",
        "ref",
        "return",
        "sbyte",
        "sealed",
        "short",
        "sizeof",
        "stackalloc",
        "static",
        "string",
        "struct",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "uint",
        "ulong",
        "unchecked",
        "unsafe",
        "ushort",
        "using",
        "virtual",
        "void",
        "volatile",
        "while",
    ]
)
# Şablonun kendi adlarıyla çakışan page object sınıfı (çakışma sessizce yanlış kod üretirdi).
_CS_AYRILMIS_SINIF = frozenset({"Page", "PageTest", "Task", "Test", "TestFixture", "Category",
                                "Description", "Property"})  # fmt: skip
_PY_ANAHTAR = frozenset(
    [
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    ]
)
_PY_AYRILMIS_SINIF = frozenset({"Page"})
_PY_AYRILMIS_AD = frozenset({"page", "pytest"})


def _kacisli_metin(value: str) -> str:
    """Düz çift tırnaklı dize literali (C# ve Python'da aynı okunur): yalnız `\\\\ \\" \\n \\r \\t`
    ve `\\uXXXX` / `\\UXXXXXXXX` kaçışları. `\\0` ve `\\x` (iki dilde farklı uzunluk/anlam)
    kullanılmaz."""
    out = []
    for ch in value:
        if ch in _DUZ_KACIS:
            out.append(_DUZ_KACIS[ch])
            continue
        kategori = unicodedata.category(ch)
        if kategori == "Cs":
            raise RenderError(
                f"literale basılamayan yedek çift (U+{ord(ch):04X}); değer reddedildi"
            )
        if kategori in _KACISLI_KATEGORI:
            out.append(f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}")
        else:
            out.append(ch)  # yazdırılabilir karakter ham UTF-8
    return '"' + "".join(out) + '"'


def _sonlu_ondalik(value: float) -> str:
    if value != value or value in (float("inf"), float("-inf")):
        raise RenderError("sonlu olmayan sayı şablona basılamaz")
    metin = repr(value)
    if not _JAVA_DOUBLE_RE.fullmatch(metin):  # pragma: no cover - repr(float) hep bu biçimde
        raise RenderError(f"ondalık literale çevrilemeyen sayı: {metin}")
    return metin


def cs_literal(value: Any) -> str:
    """C# literali: string (düz `"…"`) / int / long (`L`) / double / bool / null.

    Tamsayı ↔ ondalık ayrımı korunur (`7` int, `7.0` double); 64 biti aşan tamsayı, sonlu olmayan
    sayı, yedek çift ve başka her tür (liste, sözlük, …) reddedilir.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if _JAVA_INT[0] <= value <= _JAVA_INT[1]:
            return str(value)
        if _JAVA_LONG[0] <= value <= _JAVA_LONG[1]:
            return f"{value}L"
        raise RenderError(f"C# long aralığı dışında tamsayı: {value}")
    if isinstance(value, float):
        return _sonlu_ondalik(value)
    if isinstance(value, str):
        return _kacisli_metin(value)
    raise RenderError(f"şablona basılamayan değer türü: {type(value).__name__}")


def py_literal(value: Any) -> str:
    """Python literali: str (düz `"…"`; önek yok → f-string / bytes / raw olamaz) / int / float /
    `True` / `False` / `None`. Sonlu olmayan sayı, yedek çift ve başka her tür reddedilir."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _sonlu_ondalik(value)
    if isinstance(value, str):
        return _kacisli_metin(value)
    raise RenderError(f"şablona basılamayan değer türü: {type(value).__name__}")


def cs_args(args: Sequence[Any]) -> str:
    return ", ".join(cs_literal(a) for a in args)


def py_args(args: Sequence[Any]) -> str:
    return ", ".join(py_literal(a) for a in args)


def _gorunmezsiz_yorum(value: Any) -> str:
    """Tek satır yorum (`comment`) + görünmez/biçim karakterleri boşluk (yön denetimi, sıfır
    genişlik: incelemede görülen metin kaynaktaki metinle aynı olmalı)."""
    metin = comment(value)
    temiz = "".join(" " if unicodedata.category(ch) in _JAVA_YASAK_KATEGORI else ch for ch in metin)
    return re.sub(r"\s+", " ", temiz).strip() or "-"


def cs_comment(value: Any) -> str:
    """C# `//` yorumu: tek satır (C# satır sonları U+0085 / U+2028 / U+2029 dahil silinir)."""
    return _gorunmezsiz_yorum(value)


def py_comment(value: Any) -> str:
    """Python `#` yorumu: tek satır. (Kodlama bildirimi yalnız ilk iki satırda anlam taşır; şablon
    o satırlara değişken metin basmaz.)"""
    return _gorunmezsiz_yorum(value)


def _duz_ident(value: Any, dil: str) -> str:
    """ASCII tanımlayıcı (`$` yok: TS'te geçerli, C#/Python'da değil)."""
    if not isinstance(value, str) or not _JAVA_IDENT_RE.match(value):
        raise RenderError(f"geçersiz {dil} tanımlayıcısı: {value!r}")
    return value


def cs_ident(value: Any) -> str:
    """C# tanımlayıcısı; anahtar sözcük reddedilir (şablon `@` öneki kullanmaz)."""
    ad = _duz_ident(value, "C#")
    if ad in _CS_ANAHTAR or ad == "_":  # `_`: C#'ta yok sayma (discard) anlamı taşır
        raise RenderError(f"C# anahtar sözcüğü tanımlayıcı olamaz: {ad!r}")
    return ad


def py_ident(value: Any) -> str:
    """Python tanımlayıcısı; anahtar sözcük ve `_` ile başlayan (özel / dunder) ad reddedilir."""
    ad = _duz_ident(value, "Python")
    if ad in _PY_ANAHTAR or ad.startswith("_"):
        raise RenderError(f"Python tanımlayıcısı olarak kullanılamayan ad: {ad!r}")
    return ad


def cs_method_name(ad: str) -> str:
    """Referans tablodaki metot adı → C# PascalCase (`addToCart` → `AddToCart`)."""
    kaynak = _duz_ident(ad, "C#")
    return cs_ident(kaynak[:1].upper() + kaynak[1:])


def cs_variable_name(po_class: str) -> str:
    """Page object sınıfı → yerel değişken (`CartPage` → `cartPage`; anahtar sözcükte `…Nesnesi`
    soneki)."""
    ad = fixture_name(_duz_ident(po_class, "C#"))
    return cs_ident(f"{ad}Nesnesi" if ad in _CS_ANAHTAR else ad)


def snake_case(ad: str) -> str:
    """`addToCart` → `add_to_cart`, `LoginPage` → `login_page`, `expectHTTPStatus` →
    `expect_http_status`."""
    return _DEVE_SINIRI.sub("_", ad).lower()


def py_name(ad: str) -> str:
    """Referans tablodaki metot / sınıf adı → Python snake_case adı (metot, değişken, modül).
    Anahtar sözcüğe denk gelen ad PEP 8'e göre `_` soneki alır (`pass` → `pass_`)."""
    yilan = snake_case(_duz_ident(ad, "Python"))
    return py_ident(f"{yilan}_" if yilan in _PY_ANAHTAR else yilan)


def cs_class_name(story_key: str | None, sira_no: int, case_id: uuid.UUID) -> str:
    """`<Story>C<sıra>_<uuid8>Tests` (ör. `TPD1C2_3f9b1c2eTests`)."""
    kok = story_key if story_key and _STORY_RE.match(story_key) else "Serbest"
    ad = f"{re.sub(r'[^A-Za-z0-9]', '', kok)}C{int(sira_no)}_{case_id.hex[:8]}Tests"
    if not _CS_SINIF_RE.match(ad):
        raise RenderError(f"üretilen C# sınıf adı geçersiz: {ad}")
    return ad


def py_test_name(story_key: str | None, sira_no: int, case_id: uuid.UUID) -> str:
    """`test_<slug>` (slug'daki `-` → `_`; modül ve işlev adı): `test_tpd_1_c2_3f9b1c2e`."""
    ad = "test_" + slug(story_key, sira_no, case_id).replace("-", "_")
    if not _PY_TEST_RE.match(ad):
        raise RenderError(f"üretilen Python test adı geçersiz: {ad}")
    return ad


def _dil_env(templates_dir: Path, dil: str) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=False,  # kaynak kod üretilir; kaçış dilin literal süzgecindedir
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    if dil == "csharp":
        env.filters.update(cs=cs_literal, ident=cs_ident, comment=cs_comment, csargs=cs_args)
    else:
        env.filters.update(py=py_literal, ident=py_ident, comment=py_comment, pyargs=py_args)
    return env


@lru_cache(maxsize=8)
def _dil_template(templates_dir: str, dil: str) -> tuple[jinja2.Template, str]:
    ad = CS_TEMPLATE_NAME if dil == "csharp" else PY_TEMPLATE_NAME
    kaynak = (Path(templates_dir) / ad).read_text(encoding="utf-8")
    return _dil_env(Path(templates_dir), dil).get_template(ad), sha256_hex(kaynak)


def build_unverified_context(
    inp: RenderInput, dil: str, referans_dil: str, template_hash: str
) -> dict[str, Any]:
    """C# / Python şablon bağlamı: page object başına bir yerel değişken, adlar türetilmiş."""
    if referans_dil not in REFERANS_DIL_ETIKETI:
        raise RenderError(f"referans dil yalnızca ts ya da java olabilir: {referans_dil!r}")
    cs = dil == "csharp"
    case = inp.case
    adimlar = {str(s.get("id")): s for s in case.get("steps") or [] if isinstance(s, Mapping)}
    nesneler: dict[str, dict[str, str]] = {}  # sınıf → {sinif, degisken, modul}
    ayrilmis_sinif = _CS_AYRILMIS_SINIF if cs else _PY_AYRILMIS_SINIF

    def nesne(po: Any) -> str:
        sinif = (cs_ident if cs else py_ident)(str(po))
        if sinif in nesneler:
            return nesneler[sinif]["degisken"]
        if sinif in ayrilmis_sinif:
            raise RenderError(f"page object sınıf adı şablonun adlarıyla çakışıyor: {sinif}")
        degisken = cs_variable_name(sinif) if cs else py_name(sinif)
        if not cs and degisken in _PY_AYRILMIS_AD:
            raise RenderError(f"page object değişken adı şablonun adlarıyla çakışıyor: {degisken}")
        if any(n["degisken"] == degisken for n in nesneler.values()):
            raise RenderError(f"iki page object aynı değişken adına düşüyor: {degisken}")
        nesneler[sinif] = {"sinif": sinif, "degisken": degisken, "modul": degisken}
        return degisken

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        metot = str(item.get("method"))
        args = list(item["args"])
        for a in args:  # basılamayan değer şablondan (ve eşleme hash'inden) önce reddedilir
            (cs_literal if cs else py_literal)(a)
        return {
            "fixture": nesne(item.get("po")),
            "method": cs_method_name(metot) if cs else py_name(metot),
            "args": args,
        }

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        steps.append({"sid": sid, "label": f"{sid} — {eylem}", "calls": [cagri(m)]})
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    if not nesneler:
        raise RenderError("eşleme boş: render edilecek çağrı yok")
    story = inp.story_key if inp.story_key and _STORY_RE.match(inp.story_key) else None
    etiketler = [JAVA_URETILEN_GRUBU, platformlar.WEB, f"tp-case-{inp.case_id}"]
    etiketler += [story] if story else []
    for e in etiketler:
        if not _ETIKET_RE.match(e):
            raise RenderError(f"geçersiz etiket: {e!r}")
    dealer = _pinned_dealer(inp.mapping, inp.dealers, LOGIN_METOTLARI)
    if dealer is not None and not _JAVA_BAYI_RE.match(dealer):
        raise RenderError(f"geçersiz bayi adı: {dealer!r}")
    ref = f"{story or 'SERBEST'} C{int(inp.sira_no)}"
    return {
        "unverified_note": DOGRULANMAMIS_BASLIK.format(referans=REFERANS_DIL_ETIKETI[referans_dil]),
        "case_ref": ref,
        "case_id": str(inp.case_id),
        "story_key": story or "-",
        "test_key": inp.test_key or "-",
        "case_hash": inp.case_hash,
        "mode": inp.mode or "-",
        "bundle_hash": inp.bundle_hash or "-",
        "mapping_hash": mapping_hash(inp.mapping),
        "template_hash": template_hash,
        "dealer": dealer,
        "description": str(case.get("title") or "").strip() or ref,
        "tags": etiketler,
        "story": story,
        "namespace": CS_NAMESPACE,
        "po_namespace": CS_PO_NAMESPACE,
        "po_package": PY_PO_PAKETI,
        "class_name": cs_class_name(inp.story_key, inp.sira_no, inp.case_id),
        "test_method": CS_TEST_METODU,
        "test_name": py_test_name(inp.story_key, inp.sira_no, inp.case_id),
        "objects": sorted(nesneler.values(), key=lambda n: n["sinif"]),
        "steps": steps,
        "expects": expects,
    }


def dogrulanmamis_alt_yol(dil: str, story_key: str | None, sira_no: int, case_id: uuid.UUID) -> str:
    """Doğrulanmamış çıktının proje köküne göre yolu (`Rendered.test_file`):
    `tests/Generated/<Sinif>.cs` | `tests/generated/test_<slug>.py`."""
    if dil == "csharp":
        return f"{CS_GENERATED_DIR}/{cs_class_name(story_key, sira_no, case_id)}.cs"
    if dil == "python":
        return f"{PY_GENERATED_DIR}/{py_test_name(story_key, sira_no, case_id)}.py"
    raise RenderError(f"doğrulanmamış dil yalnızca csharp ya da python olabilir: {dil!r}")


def dogrulanmamis_repo_path(
    dil: str,
    story_key: str | None,
    sira_no: int,
    case_id: uuid.UUID,
    kok: str | None = None,
) -> str:
    """Doğrulanmamış çıktının önerilen depo yolu (K-T6 tek kaynak): `<kök>/<alt yol>`.

    `kok` verilmezse (ya da boş / ts kökü `e2e` ise) `e2e-csharp` / `e2e-python`; GitHub kipinde
    service `<uygulama kökü>/e2e-<dil>` verir. `render_unverified_test` ve service
    `baslangic_dosya_yolu` bu işlevi çağırır (yol üretimden önce ve sonra aynıdır).
    """
    alt = dogrulanmamis_alt_yol(dil, story_key, sira_no, case_id)
    temiz = (kok or "").strip("/")
    if temiz in ("", E2E_ROOT):
        temiz = DOGRULANMAMIS_KOKLER[dil]
    return f"{temiz}/{alt}"


def render_unverified_test(
    inp: RenderInput, dil: str, rules_dir: Path, referans_dil: str = "ts"
) -> Rendered:
    """Doğrulanmamış dil (`csharp` | `python`) çıktısı. `repo_path` forge'a yazılmaz: önerilen
    dosya yolu / indirme adıdır, `<inp.e2e_root>/<alt yol>` (`dogrulanmamis_repo_path`);
    `test_file` alt yoldur (`tests/Generated/<Sinif>.cs`, `tests/generated/test_<slug>.py`)."""
    if dil not in DOGRULANMAMIS_DILLER:
        raise RenderError(f"doğrulanmamış dil yalnızca csharp ya da python olabilir: {dil!r}")
    template, template_hash = _dil_template(str(templates_dir(rules_dir)), dil)
    ctx = build_unverified_context(inp, dil, referans_dil, template_hash)
    try:
        content = template.render(**ctx)
    except jinja2.TemplateError as exc:  # pragma: no cover - şablon hatası (geliştirici)
        raise RenderError(f"şablon render edilemedi: {exc}") from exc
    if dil == "csharp":
        sinif, test = ctx["class_name"], ctx["test_method"]
    else:
        sinif, test = None, ctx["test_name"]
    yol = dogrulanmamis_alt_yol(dil, inp.story_key, inp.sira_no, inp.case_id)
    return Rendered(
        content=content,
        repo_path=dogrulanmamis_repo_path(
            dil, inp.story_key, inp.sira_no, inp.case_id, inp.e2e_root
        ),
        test_file=yol,
        template_hash=template_hash,
        mapping_hash=ctx["mapping_hash"],
        dealer=ctx["dealer"],
        dil=dil,
        sinif_adi=sinif,
        test_adi=test,
        dogrulanmamis=True,
        referans_dil=referans_dil,
    )


# ====================================================================== tek giriş noktası (011)


def render_dil(
    inp: RenderInput,
    *,
    dil: str,
    platform: str,
    rules: Path,
    referans_dil: str | None = None,
    sembol_tablosu: Mapping[str, Any] | None = None,
) -> Rendered:
    """(platform, dil) çiftine göre testi render eder (011 §2.1, §2.7).

    - `web` × `ts` → `playwright_test.ts.j2`; `web` × `java` → `playwright_testng.java.j2`
      (`inp.e2e_root` = e2e-java kökü); uygulama × `java` → `appium_testng.java.j2`.
    - `web` × `csharp` | `python` → doğrulanmamış çıktı; `referans_dil` adların türetildiği sembol
      tablosunun dilidir (`ts` varsayılan; repoda TS yoksa `java`). Tam hat dillerinde yok sayılır.
      `sembol_tablosu`: o tablonun ham `/symbols` çıktısı (parametre türleri için; D2).
    - Geçersiz dil / platform / çift → `RenderError` (API zaten 422 verir; savunma katmanı).
    """
    if platform not in platformlar.PLATFORMLAR:
        raise RenderError(f"geçersiz platform: {platform!r}")
    if dil not in DILLER:
        raise RenderError(f"geçersiz üretim dili: {dil!r}")
    if platform != platformlar.WEB and dil != "java":
        raise RenderError(f"{platform} platformunda üretim dili yalnızca java olabilir: {dil!r}")
    if dil == "ts":
        return render_test(inp, rules)
    if dil == "java":
        return render_java_test(inp, platform, rules)
    return render_unverified_test(inp, dil, rules, referans_dil or "ts")
