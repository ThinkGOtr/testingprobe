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
- 013 K19: bilinen gizli test verisi değeri (`RenderInput.gizli_ortam`: değer → sır adı) üst
  düzey çağrı argümanıysa literal yerine ortam okuması basılır (TS `process.env.<SIR>`, Java
  `System.getenv("<SIR>")`); adım etiketlerinde ve başlıkta değer `•••` olur. PR/commit'te düz
  parola kalmaz; e2e sözleşmeleri (eslint `generatedTestSyntax`, `java-araclar guard`) yalnız bu
  biçimi ve `TP_TESTVERI_*` adlarını kabul eder. Şablonlar değişmez (süzgeç düzeyinde).
  Render sonrası tarama (güvenlik #4/#5): `RenderInput.gizli_taranacak` (bilinen tüm gizli
  değerler; sırrı tanımsız olanlar dahil) çıktıda alt dize olarak geçerse (kelime sınırı yok:
  `Demo123!x`, kaçışlı biçim; güvenlik tur 3 #2) `GizliSizinti` (fail-closed; servis
  `test_verisi` engeliyle durdurur, commit/PR yok). Etiket/başlık maskesi de bu listeyi ve
  `atif.maskele` kuralını kullanır.
- Çıktı deterministiktir (zaman/rastgelelik yok); dosya adı case'e göre sabittir
  (`<e2e kökü>/tests/generated/<story>-c<sıra>-<case uuid'nin ilk 8'i>.spec.ts`; e2e kökü
  LocalForge'da `e2e`, GitHub monoreposunda `demo-app/e2e`). Yeniden üretim aynı dosya yolunu
  main'den açılan YENİ bir dala yazar (service `_dal_sec`); merge'de main'deki dosyanın yerini alır.

Üretim dili (011 §2.7): tek giriş noktası `render_dil(inp, dil=…, platform=…, rules=…)`.
`ts` → `render_test`, `java` → `render_java_test` (uygulama: Appium; web: Playwright for Java),
diğer diller (014) → `codegen/diller/<dil>.py` eklentisi. Model hiçbir dilde kod yazmaz; her
dilin kendi literal/tanımlayıcı/yorum süzgeci vardır.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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
# Doğrulama kalıpları çapasızdır ve hep `fullmatch` ile kullanılır: `^…$` + `match` sondaki `\n`'i
# geçirirdi (GÜV-D1). Rakamlar `[0-9]` (`\d` Unicode rakamlarını da kabul eder).
_STORY_RE = re.compile(r"[A-Z][A-Z0-9]*-[0-9]+")
_DEALER_RE = re.compile(
    r"\{\s*username:\s*\"(?P<u>[A-Za-z0-9_.-]+)\"\s*,\s*password:\s*\"(?P<p>[^\"\\]*)\"\s*,"
    r"\s*name:\s*\"(?P<n>[^\"\\]*)\"\s*\}"
)


class RenderError(ValueError):
    """Şablona güvensiz/geçersiz değer gitti (kontrollerin kaçırdığı bir durum: insana)."""


class GizliSizinti(RenderError):
    """Üretilen kod bilinen bir gizli test verisini düz taşıyor (K19; değer mesajda yok)."""


GIZLI_SIZINTI_METNI = (
    "Test verisi sırrı tanımsız ya da case'te atıf değil: üretilen kod gizli test verisini düz "
    "içeriyordu; commit/PR açılmadı. Sırrı (TP_TESTVERI_*) tanımlayıp yeniden üretin"
)


SIR_ADI_RE = re.compile(r"^TP_TESTVERI_[A-Z0-9_]{1,64}$")
GIZLI_MASKE = "•••"


@dataclass(frozen=True)
class OrtamDegeri:
    """Gizli test verisi argümanı: üretilen kod değeri bu ortam değişkeninden okur (K19)."""

    ad: str

    def __post_init__(self) -> None:
        if not SIR_ADI_RE.match(self.ad):
            raise RenderError(f"geçersiz sır adı: {self.ad!r}")


def _gizli_arg(value: Any, gizli_ortam: Mapping[str, str]) -> Any:
    if isinstance(value, str) and value in gizli_ortam:
        return OrtamDegeri(gizli_ortam[value])
    return value


def _maskeli(metin: str, gizli: Iterable[str]) -> str:
    """Etiket / başlık maskesi: `atif.maskele` ile aynı kural (alt dize, en az `MIN_DEGER`)."""
    from tp_core.features.testveri.atif import maskele

    return maskele(metin, gizli)


def _tum_gizliler(inp: RenderInput) -> tuple[str, ...]:
    return tuple(dict.fromkeys([*inp.gizli_ortam, *inp.gizli_taranacak]))


def _sizinti_tara(content: str, inp: RenderInput) -> None:
    from tp_core.features.testveri.atif import gizli_geciyor_mu

    # Literal kaçışlı biçimler de (JSON/Java: `\"`, `\uXXXX`) taranır.
    adaylar = {
        v
        for g in _tum_gizliler(inp)
        for v in (g, json.dumps(g)[1:-1], json.dumps(g, ensure_ascii=False)[1:-1])
    }
    if gizli_geciyor_mu(content, adaylar):
        raise GizliSizinti(GIZLI_SIZINTI_METNI)


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
    if not isinstance(value, str) or not IDENT_RE.fullmatch(value):
        raise RenderError(f"geçersiz tanımlayıcı: {value!r}")
    return value


def comment(value: Any) -> str:
    ham = str(value if value is not None else "-")
    metin = _KONTROL.sub(" ", unicodedata.normalize("NFC", ham))
    metin = re.sub(r"\s+", " ", metin).strip() or "-"
    return metin if len(metin) <= 160 else metin[:159] + "…"


def _ts_arg(value: Any) -> str:
    if isinstance(value, OrtamDegeri):
        return f"process.env.{value.ad}"
    return ts_literal(value)


def args_literal(args: Sequence[Any]) -> str:
    return ", ".join(_ts_arg(a) for a in args)


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
    # 013 K19: bilinen gizli test verisi değeri → sır (ortam değişkeni) adı.
    gizli_ortam: Mapping[str, str] = field(default_factory=dict)
    # Render sonrası taranacak bilinen gizli değerler (sırrı tanımsız olanlar dahil).
    gizli_taranacak: Sequence[str] = ()


@dataclass(frozen=True)
class Rendered:
    content: str
    # Tam hat dillerinde forge deposundaki yol (e2e/tests/generated/…). Doğrulanmamış dillerde
    # forge'a yazılmaz: önerilen depo yolu / indirme adıdır (`dogrulanmamis_repo_path`:
    # `e2e-csharp/tests/Generated/<Story>WebC<n>_<uuid8>Tests.cs`).
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
    kok = story_key.lower() if story_key and _STORY_RE.fullmatch(story_key) else "serbest"
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

    gizli = inp.gizli_ortam
    maske = _tum_gizliler(inp)

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        fx = ident(fixture_name(ident(str(item.get("po")))))
        if fx not in kullanilan:
            kullanilan.append(fx)
        return {
            "fixture": fx,
            "method": ident(str(item.get("method"))),
            "args": [_gizli_arg(a, gizli) for a in item["args"]],
        }

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        etiket = _maskeli(f"{sid} — {eylem}", maske)
        steps.append({"sid": sid, "label": etiket, "calls": [cagri(m)]})
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    story = inp.story_key if inp.story_key and _STORY_RE.fullmatch(inp.story_key) else None
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
        "title": _maskeli(
            f"{str(case.get('title') or case_ref).strip()} {URETILEN_ETIKETI}", maske
        ),
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
    _sizinti_tara(content, inp)
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
_JAVA_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_JAVA_SINIF_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Test")
_JAVA_GRUP_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_JAVA_BAYI_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
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


def _java_arg(value: Any) -> str:
    if isinstance(value, OrtamDegeri):
        return f'System.getenv("{value.ad}")'
    return java_literal(value)


def java_args(args: Sequence[Any]) -> str:
    return ", ".join(_java_arg(a) for a in args)


def java_ident(value: Any) -> str:
    if not isinstance(value, str) or not _JAVA_IDENT_RE.fullmatch(value):
        raise RenderError(f"geçersiz Java tanımlayıcısı: {value!r}")
    if value in _JAVA_ANAHTAR:
        # Ör. TS page object metodu `goto`: Java'da ayrılmış sözcük, metot adı olamaz (011 §2.5).
        raise RenderError(f"Java ayrılmış sözcüğü tanımlayıcı olamaz: {value!r}")
    return value


def java_class_name(story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID) -> str:
    """`<Story><Platform>C<sıra>_<uuid8>Test` (Java tanımlayıcısı; guard dosya adı kuralı)."""
    kok = story_key if story_key and _STORY_RE.fullmatch(story_key) else "Serbest"
    kok = re.sub(r"[^A-Za-z0-9]", "", kok)
    ad = f"{kok}{platform[:1].upper()}{platform[1:]}C{int(sira_no)}_{case_id.hex[:8]}Test"
    if not _JAVA_SINIF_RE.fullmatch(ad):
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

    gizli = inp.gizli_ortam
    maske = _tum_gizliler(inp)

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "fixture": java_ident(fixture_name(java_ident(str(item.get("po"))))),
            "method": java_ident(str(item.get("method"))),
            "args": [_gizli_arg(a, gizli) for a in item["args"]],
        }

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        etiket = _maskeli(f"{sid} — {eylem}", maske)
        steps.append({"sid": sid, "label": etiket, "calls": [cagri(m)]})
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    story = inp.story_key if inp.story_key and _STORY_RE.fullmatch(inp.story_key) else None
    gruplar = [JAVA_URETILEN_GRUBU, platform, f"tp-case-{inp.case_id}"] + ([story] if story else [])
    for g in gruplar:
        if not _JAVA_GRUP_RE.fullmatch(g):
            raise RenderError(f"geçersiz TestNG grubu: {g!r}")
    dealer = _pinned_dealer(inp.mapping, inp.dealers, LOGIN_METOTLARI)
    if dealer is not None and not _JAVA_BAYI_RE.fullmatch(dealer):
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
        "description": _maskeli(str(case.get("title") or "").strip(), maske) or ref,
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
    _sizinti_tara(content, inp)
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


# ========================================= C# / Python süzgeçleri ve 011 doğrulanmamış yol adları
#
# 014 karar 3a: 011'in doğrulanmamış web C#/Python render yolu (`render_unverified_test`,
# `pytest_playwright.py.j2`) emekliye ayrıldı; bu diller tam hat eklentileriyle üretilir
# (`codegen/diller/csharp.py`, `python.py`). Buradaki saf süzgeçler (`cs_literal`, `py_literal`,
# `cs_ident` …) eklentilerce kullanılır; `dogrulanmamis_repo_path` geçmiş `unverified` kayıtların
# yol kuralıdır.
#
# Enjeksiyon: değerler `cs_literal` / `py_literal` ile yalnız düz (önek almayan) çift tırnaklı dize,
# sayı, bool ve null literali olur — C#'ta verbatim (`@"…"`) / interpolasyon (`$"…"`) / ham dize
# (`"""…"""`), Python'da f-string / üç tırnak / bytes ÜRETİLMEZ; `{` `}` bu yüzden düz karakterdir.
# Kontrol, biçim (yön denetimi, sıfır genişlik) ve satır ayırıcı karakterler `\uXXXX` kaçışıyla
# basılır (değer korunur, kaynakta görünür). Yorumlar tek satırdır.

CS_GENERATED_DIR = "tests/Generated"
PY_GENERATED_DIR = "tests/generated"
CS_NAMESPACE = "Antreklabs.Bayi.Tests.Generated"
CS_TEST_METODU = "Senaryo"
CS_ASYNC_SONEKI = "Async"  # Playwright .NET: `GotoAsync`, `LoginAsync`, `ExpectTotalAsync`
# Doğrulanmamış dillerin varsayılan proje kökleri (LocalForge düzeni; forge'a yazılmaz).
DOGRULANMAMIS_KOKLER: dict[str, str] = {"csharp": "e2e-csharp", "python": "e2e-python"}
DILLER: tuple[str, ...] = platformlar.DILLER  # tek kaynak platform.py
DOGRULANMAMIS_DILLER: tuple[str, ...] = platformlar.DOGRULANMAMIS_DILLER
_DUZ_KACIS = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
# `\uXXXX` ile basılan kategoriler (yedek çift — Cs — reddedilir: UTF-8'e yazılamaz).
_KACISLI_KATEGORI = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cn"})
_CS_SINIF_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Tests")
_PY_TEST_RE = re.compile(r"test_[a-z0-9_]+")
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


def _cs_arg(value: Any) -> str:
    if isinstance(value, OrtamDegeri):
        return f'System.Environment.GetEnvironmentVariable("{value.ad}")'
    return cs_literal(value)


def _py_arg(value: Any) -> str:
    if isinstance(value, OrtamDegeri):
        # Şablon `os`'u içe aktarmaz; ifade kendi içinde (013 K19).
        return f'__import__("os").environ["{value.ad}"]'
    return py_literal(value)


def cs_args(args: Sequence[Any]) -> str:
    return ", ".join(_cs_arg(a) for a in args)


def py_args(args: Sequence[Any]) -> str:
    return ", ".join(_py_arg(a) for a in args)


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
    if not isinstance(value, str) or not _JAVA_IDENT_RE.fullmatch(value):
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
    """Referans tablodaki metot adı → C# PascalCase + `Async` (Playwright .NET konvansiyonu:
    `addToCart` → `AddToCartAsync`, `goto` → `GotoAsync`; zaten `…Async` ise sonek eklenmez)."""
    kaynak = _duz_ident(ad, "C#")
    pascal = cs_ident(kaynak[:1].upper() + kaynak[1:])
    return pascal if pascal.endswith(CS_ASYNC_SONEKI) else cs_ident(pascal + CS_ASYNC_SONEKI)


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
    """`<Story>WebC<sıra>_<uuid8>Tests` (ör. `TPD1WebC2_3f9b1c2eTests`): web + Java sınıf adıyla
    (`java_class_name`, `…Test`) aynı kural, NUnit konvansiyonuyla `Tests` soneki."""
    ad = java_class_name(story_key, platformlar.WEB, sira_no, case_id) + "s"
    if not _CS_SINIF_RE.fullmatch(ad):  # pragma: no cover - java_class_name zaten denetler
        raise RenderError(f"üretilen C# sınıf adı geçersiz: {ad}")
    return ad


def py_test_name(story_key: str | None, sira_no: int, case_id: uuid.UUID) -> str:
    """`test_<slug>` (slug'daki `-` → `_`; modül ve işlev adı): `test_tpd_1_c2_3f9b1c2e`."""
    ad = "test_" + slug(story_key, sira_no, case_id).replace("-", "_")
    if not _PY_TEST_RE.fullmatch(ad):
        raise RenderError(f"üretilen Python test adı geçersiz: {ad}")
    return ad


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
    service `<uygulama kökü>/e2e-<dil>` verir. Service `baslangic_dosya_yolu` bu işlevi çağırır
    (eklentisiz eski kayıtlar).
    """
    alt = dogrulanmamis_alt_yol(dil, story_key, sira_no, case_id)
    temiz = (kok or "").strip("/")
    if temiz in ("", E2E_ROOT):
        temiz = DOGRULANMAMIS_KOKLER[dil]
    return f"{temiz}/{alt}"


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
    - 014: diğer çiftler dil eklentisine gider (`codegen/diller/<dil>.py` `render`);
      `referans_dil` eşlemenin denetlendiği tablonun dili, `sembol_tablosu` render'ın kullandığı
      tablo (Swift etiketleri, Kotlin paketi/türleri). Eklentisi olmayan dil → `RenderError`
      (011 doğrulanmamış web C#/Python yolu emekliye ayrıldı, karar 3a).
    - Geçersiz dil / platform / çift → `RenderError` (API zaten 422 verir; savunma katmanı).
    """
    if platform not in platformlar.PLATFORMLAR:
        raise RenderError(f"geçersiz platform: {platform!r}")
    if dil not in DILLER:
        raise RenderError(f"geçersiz üretim dili: {dil!r}")
    cati = platformlar.cati_bul(platform, dil)
    if cati is None:
        raise RenderError(
            f"{platform} platformunda {dil} ile üretim yok; geçerli dil: "
            f"{', '.join(platformlar.platform_dilleri(platform))}"
        )
    # 014: dil eklentisine dağıtım (`codegen/diller/<dil>.py`). ts/java eklentileri bugünkü
    # render işlevlerini çağırır (bayt eşit).
    from tp_core.features.codegen import diller

    eklenti = diller.eklenti(dil)
    if eklenti is not None:
        return eklenti.render(
            inp, cati, rules, referans_dil=referans_dil, sembol_tablosu=sembol_tablosu
        )
    # 014 karar 3a: 011'in doğrulanmamış web C#/Python render yolu emekliye ayrıldı; bu diller
    # yalnız tam hat eklentisiyle üretilir (geçmiş `unverified` kayıtların kaynağı DB'dedir).
    raise RenderError(f"{dil} dil eklentisi yüklü değil")
