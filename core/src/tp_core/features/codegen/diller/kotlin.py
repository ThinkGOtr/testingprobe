"""Kotlin / Espresso dil eklentisi (TASARIM test-dilleri §3.3; şerit Ş3; hat `musteri_ci`).

Android × Kotlin: aynı uygulama eşlemesi (`verify_and_map_app`)
`rules/templates/espresso_junit.kt.j2` ile Kotlin'e render edilir. Ekran nesnesi kütüphanesi
(demo: `demo-app/mobile/android-test/java/com/antreklabs/bayisiparis/tp/`) Java `e2e-app`
kütüphanesiyle **ad eşittir** (sınıf, metot, parametre adları camelCase; tür adları
normalleştirilmiş tabloda aynı). Bu yüzden ajan eşlemesi
dönüştürülmez (`eslemeyi_donustur` kimlik işlevi) ve REPLAY golden'ları dilden bağımsız kalır.

Model kod yazmaz: şablon + literal süzgeçleri. Kotlin'e özgü enjeksiyon yüzeyleri:

- **Dize şablonu:** `"…$ad…"` / `"…${ifade}…"` Kotlin'de kod çalıştırır. `kotlin_literal` her `$`'ı
  `\\$` olarak basar; ham dize (`\"\"\"…\"\"\"`) hiç üretilmez.
- **Unicode kaçışı:** Kotlin yorumlarda `\\uXXXX` işlemez (Java'nın aksine) ama tutarlılık için
  yorumda   ters bölü `/` olur; literalde kontrol / biçim / görünmez karakterler reddedilir (insan
  incelemesinde görülen metin derlenen metinle aynı olmalı — Java ile aynı kural).
- **Tür uyumu:** Kotlin tamsayı literalini `Double` parametreye genişletmez (Java genişletir).
  Sembol tablosu verilirse tamsayı argüman `Double` parametrede `7.0` olarak basılır; tablo
  verilmezse statik koruma (worker) tür uyumsuzluğunu PR'dan önce yakalar.

Yol (sözleşme: specs/014-test-dilleri/plan.md §1; TASARIM §3.3):
`<android_kotlin_root>/<kütüphane paketi yolu>/uretilen/<Story>AndroidC<sıra>_<uuid8>Test.kt`, paket
`<kütüphane paketi>.uretilen`. Kütüphane paketi sembol tablosunun `paket` alanından gelir (worker
`symbols`: `ekranlar/` ve `altyapi/` paketlerinin ortak atası); yoksa demo varsayılanı
`com.antreklabs.bayisiparis.tp`. Müşteri CI iş akışı yalnız bu paketi koşar
(`-Pandroid.testInstrumentationRunnerArguments.package=<kütüphane paketi>`).

Ş0'a not (geçici adaptör): `codegen/diller/__init__.py` (keşif, `AlgilaKalibi`) ve
`platform.Cati` henüz bu dalda yok. Bu modül onlara yalnız ördek tiplemeyle bağlanır
(`cati` öznitelikleri `getattr` ile okunur; `AlgilaKalibi` yoksa yerel eşdeğeri kullanılır).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import jinja2

from tp_core.audit.canonical import sha256_hex
from tp_core.features.codegen import render as _r
from tp_core.features.codegen.render import (
    OrtamDegeri,
    Rendered,
    RenderError,
    RenderInput,
    fixture_name,
)

try:  # Ş0 sözleşmesi (specs/014-test-dilleri/plan.md §2)
    from tp_core.features.codegen.diller import AlgilaKalibi  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Ş0 birleşmeden önce

    @dataclass(frozen=True)
    class AlgilaKalibi:  # type: ignore[no-redef]
        platformlar: frozenset[str]
        kok_ayari: str
        alt_dizin: str


AD = "kotlin"
PLATFORM = "android"
HAT = "musteri_ci"
TEMPLATE_NAME = "espresso_junit.kt.j2"
KOK_AYARI = "TP_ANDROID_KOTLIN_ROOT"
KOK_VARSAYILAN = "app/src/androidTest/java"
URETILEN_ALT_PAKET = "uretilen"
VARSAYILAN_KUTUPHANE_PAKETI = "com.antreklabs.bayisiparis.tp"
TEST_METODU = "senaryo"
GH_IS_AKISI = "mobil-android-kotlin"
ETIKET = "Espresso (AndroidX Test, JUnit4)"
# Elle yazılmış Kotlin enstrümantasyon testi (algılama): `<Ad>Test.kt` / `Testi.kt` / `Tests.kt`;
# aracın ürettikleri (`uretilen/`) ve kütüphane (`altyapi/`, `ekranlar/`) sayılmaz.
TEST_SONEKLERI: tuple[str, ...] = ("Test.kt", "Testi.kt", "Tests.kt")
HARIC_DIZINLER: tuple[str, ...] = ("uretilen", "altyapi", "ekranlar")
# Kurulum PR'ı ve "proje var mı" sorusu: kütüphanenin taban sınıfı (kökten bağımsız).
PROJE_DOSYASI = "**/altyapi/TestTabani.kt"

# Kotlin sert anahtar sözcükleri (tanımlayıcı olamaz; geri tırnak üretmiyoruz).
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
_KT_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_KT_SINIF_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Test")
_PAKET_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
_BAYI_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_DOUBLE_RE = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_KACIS = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "$": "\\$"}
_YASAK_KATEGORI = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"})
_INT = (-(2**31), 2**31 - 1)
_LONG = (-(2**63), 2**63 - 1)
# `Bayiler.kt` E2E listesi: `BayiBilgisi("bayi1", "Demo123!", "Merkez Bayi")`.
_BAYILER_RE = re.compile(
    r"BayiBilgisi\(\s*\"(?P<u>[A-Za-z0-9_.-]+)\"\s*,\s*\"(?P<p>[^\"\\$]*)\"\s*,"
    r"\s*\"(?P<n>[^\"\\$]*)\"\s*,?\s*\)"
)
LOGIN_METOTLARI = frozenset({"girisYap"})


# ---------------------------------------------------------------------------- süzgeçler


def _metin(value: str) -> str:
    out = []
    for ch in value:
        if ch in _KACIS:
            out.append(_KACIS[ch])
        elif unicodedata.category(ch) in _YASAK_KATEGORI:
            raise RenderError(
                f"Kotlin literaline basılamayan karakter (U+{ord(ch):04X}); değer reddedildi"
            )
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def kotlin_literal(value: Any, tur: str | None = None) -> str:
    """Kotlin literali: String / Int / Long (`L`) / Double / Boolean. Başka tür → RenderError.

    `tur` (normalleştirilmiş sembol tablosu türü: `String|int|long|double|boolean`) verilirse
    tamsayı `double` parametrede `7.0`, `long` parametrede `7L` basılır; uyumsuz tür reddedilir.
    """
    if isinstance(value, bool):
        if tur not in (None, "boolean"):
            raise RenderError(f"boolean değer {tur} parametreye basılamaz")
        return "true" if value else "false"
    if isinstance(value, int):
        if tur == "double":
            return kotlin_literal(float(value))
        if tur not in (None, "int", "long"):
            raise RenderError(f"tamsayı değer {tur} parametreye basılamaz")
        if tur == "long":
            if not _LONG[0] <= value <= _LONG[1]:
                raise RenderError(f"Kotlin Long aralığı dışında tamsayı: {value}")
            return f"{value}L"
        if _INT[0] <= value <= _INT[1]:
            return str(value)
        if tur == "int":
            raise RenderError(f"Kotlin Int aralığı dışında tamsayı: {value}")
        if _LONG[0] <= value <= _LONG[1]:
            return f"{value}L"
        raise RenderError(f"Kotlin Long aralığı dışında tamsayı: {value}")
    if isinstance(value, float):
        if tur not in (None, "double"):
            raise RenderError(f"ondalık değer {tur} parametreye basılamaz")
        if value != value or value in (float("inf"), float("-inf")):
            raise RenderError("sonlu olmayan sayı şablona basılamaz")
        metin = repr(value)
        if not _DOUBLE_RE.fullmatch(metin):
            raise RenderError(f"Kotlin Double literaline çevrilemeyen sayı: {metin}")
        return metin
    if isinstance(value, str):
        if tur not in (None, "String"):
            raise RenderError(f"metin değer {tur} parametreye basılamaz")
        return _metin(value)
    raise RenderError(f"şablona basılamayan değer türü: {type(value).__name__}")


def kotlin_comment(value: Any) -> str:
    """Kotlin `//` yorumu: tek satır; ters bölü `/` olur, görünmez/biçim karakterleri boşluk."""
    metin = _r.comment(value).replace("\\", "/")
    temiz = "".join(" " if unicodedata.category(ch) in _YASAK_KATEGORI else ch for ch in metin)
    return re.sub(r"\s+", " ", temiz).strip() or "-"


def kotlin_ident(value: Any) -> str:
    if not isinstance(value, str) or not _KT_IDENT_RE.fullmatch(value):
        raise RenderError(f"geçersiz Kotlin tanımlayıcısı: {value!r}")
    if value in _KT_ANAHTAR:
        raise RenderError(f"Kotlin anahtar sözcüğü tanımlayıcı olamaz: {value!r}")
    return value


@dataclass(frozen=True)
class _Arg:
    deger: Any
    tur: str | None


def _arg(a: Any) -> str:
    deger, tur = (a.deger, a.tur) if isinstance(a, _Arg) else (a, None)
    if isinstance(deger, OrtamDegeri):
        if tur not in (None, "String"):
            raise RenderError(f"gizli test verisi {tur} parametreye basılamaz")
        if not _r.SIR_ADI_RE.fullmatch(deger.ad):
            raise RenderError(f"geçersiz sır adı: {deger.ad!r}")
        return f'testVerisi("{deger.ad}")'
    return kotlin_literal(deger, tur)


def kotlin_args(args: Sequence[Any]) -> str:
    return ", ".join(_arg(a) for a in args)


def paket_dogrula(paket: Any) -> str:
    if not isinstance(paket, str) or not _PAKET_RE.fullmatch(paket):
        raise RenderError(f"geçersiz Kotlin paket adı: {paket!r}")
    if any(p in _KT_ANAHTAR for p in paket.split(".")):
        raise RenderError(f"Kotlin paket adında anahtar sözcük: {paket!r}")
    return paket


# ---------------------------------------------------------------------- adlar ve yollar


def sinif_adi(story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID) -> str:
    """`<Story><Platform>C<sıra>_<uuid8>Test` (Java ile aynı ad; dosya `<ad>.kt`)."""
    kok = story_key if story_key and _r._STORY_RE.fullmatch(story_key) else "Serbest"
    kok = re.sub(r"[^A-Za-z0-9]", "", kok)
    ad = f"{kok}{platform[:1].upper()}{platform[1:]}C{int(sira_no)}_{case_id.hex[:8]}Test"
    if not _KT_SINIF_RE.fullmatch(ad):
        raise RenderError(f"üretilen Kotlin sınıf adı geçersiz: {ad}")
    return ad


def kutuphane_paketi(
    sembol_tablosu: Mapping[str, Any] | None = None, paket: str | None = None
) -> str:
    """Ekran nesnesi kütüphanesinin taban paketi: `paket` > tablo `paket` > demo varsayılanı."""
    secilen = paket or (sembol_tablosu or {}).get("paket") or VARSAYILAN_KUTUPHANE_PAKETI
    return paket_dogrula(secilen)


def uretilen_paket(kutuphane: str) -> str:
    return f"{paket_dogrula(kutuphane)}.{URETILEN_ALT_PAKET}"


def test_dosyasi(kutuphane: str, sinif: str) -> str:
    """Kaynak köküne göre: `<paket yolu>/uretilen/<Sınıf>.kt` (worker `/check` `test_files`)."""
    return f"{uretilen_paket(kutuphane).replace('.', '/')}/{sinif}.kt"


def kok_coz(cati: Any = None, kok: str | None = None) -> str:
    kok = (kok or "").strip("/")
    return kok or str(getattr(cati, "kok_varsayilan", "") or KOK_VARSAYILAN).strip("/")


def uretilen_yol(
    cati: Any,
    kok: str,
    story_key: str | None,
    sira_no: int,
    case_id: uuid.UUID,
    *,
    paket: str | None = None,
    sembol_tablosu: Mapping[str, Any] | None = None,
) -> str:
    """Forge'daki tam depo yolu (`<kök>/<paket yolu>/uretilen/<Sınıf>.kt`).

    Ş0'a not: sözleşmedeki imzada kütüphane paketi yok; `paket` / `sembol_tablosu` isteğe bağlı
    ek anahtar sözcüklerdir (verilmezse demo varsayılanı)."""
    platform = str(getattr(cati, "platform", "") or PLATFORM)
    ad = sinif_adi(story_key, platform, sira_no, case_id)
    return f"{kok_coz(cati, kok)}/{test_dosyasi(kutuphane_paketi(sembol_tablosu, paket), ad)}"


def test_dosyasi_mi(yol: str) -> bool:
    """Elle yazılmış bir Kotlin (Espresso) testi mi? Kökten bağımsız: sonek + hariç dizinler.

    Algılama yalnız `TP_ANDROID_KOTLIN_ROOT` altında arar (`ALGILA_KALIPLARI`); JVM birim testleri
    (`src/test/`) o kökün dışındadır."""
    if not yol.endswith(TEST_SONEKLERI):
        return False
    return not any(h in yol.split("/")[:-1] for h in HARIC_DIZINLER)


ALGILA_KALIPLARI: tuple[AlgilaKalibi, ...] = (
    AlgilaKalibi(platformlar=frozenset({PLATFORM}), kok_ayari=KOK_AYARI, alt_dizin=""),
)


def parse_dealers(bayiler_source: str) -> dict[str, dict[str, str]]:
    """`altyapi/Bayiler.kt` `E2E = listOf(BayiBilgisi(…), …)` bayileri (sözdizimsel;
    çalıştırılmaz)."""
    m = re.search(r"\bE2E\b[^=]*=\s*listOf\((?P<govde>.*?)\)\s*\n\s*\n", bayiler_source, re.S)
    if m is None:
        m = re.search(r"\bE2E\b[^=]*=\s*listOf\((?P<govde>.*)", bayiler_source, re.S)
    if m is None:
        return {}
    return {
        d.group("u"): {"password": d.group("p"), "name": d.group("n")}
        for d in _BAYILER_RE.finditer(m.group("govde"))
    }


def eslemeyi_donustur(output: Any) -> Any:
    """Kotlin ekran nesneleri Java ile ad eşittir: uygulama eşlemesi aynen kullanılır."""
    return output


# --------------------------------------------------------------------------- render


def _env(templates_dir: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=False,  # Kotlin üretilir; kaçış `kt` süzgecindedir
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["kt"] = kotlin_literal
    env.filters["ident"] = kotlin_ident
    env.filters["comment"] = kotlin_comment
    env.filters["ktargs"] = kotlin_args
    return env


@lru_cache(maxsize=4)
def _template(templates_dir: str) -> tuple[jinja2.Template, str]:
    kaynak = (Path(templates_dir) / TEMPLATE_NAME).read_text(encoding="utf-8")
    return _env(Path(templates_dir)).get_template(TEMPLATE_NAME), sha256_hex(kaynak)


def _param_turleri(sembol_tablosu: Mapping[str, Any] | None) -> dict[tuple[str, str], list[str]]:
    """(sınıf, metot) → normalleştirilmiş parametre türleri (aşırı yükleme yoksa)."""
    out: dict[tuple[str, str], list[str]] = {}
    sayi: dict[tuple[str, str], int] = {}
    for po in (sembol_tablosu or {}).get("page_objects") or []:
        for m in po.get("methods") or []:
            k = (str(po.get("class")), str(m.get("name")))
            sayi[k] = sayi.get(k, 0) + 1
            out[k] = [str(p.get("type")) for p in m.get("params") or []]
    return {k: v for k, v in out.items() if sayi[k] == 1}


def build_context(
    inp: RenderInput,
    platform: str,
    template_hash: str,
    *,
    kutuphane: str,
    sembol_tablosu: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    case = inp.case
    adimlar = {str(s.get("id")): s for s in case.get("steps") or [] if isinstance(s, Mapping)}
    gizli = inp.gizli_ortam
    maske = _r._tum_gizliler(inp)
    turler = _param_turleri(sembol_tablosu)

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        po = kotlin_ident(str(item.get("po")))
        metot = kotlin_ident(str(item.get("method")))
        args = [_r._gizli_arg(a, gizli) for a in item["args"]]
        tur = turler.get((po, metot))
        if tur is not None and len(tur) == len(args):
            args = [_Arg(a, t) for a, t in zip(args, tur, strict=True)]
        return {"fixture": kotlin_ident(fixture_name(po)), "method": metot, "args": args}

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        steps.append(
            {"sid": sid, "label": _r._maskeli(f"{sid} — {eylem}", maske), "calls": [cagri(m)]}
        )
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    story = inp.story_key if inp.story_key and _r._STORY_RE.fullmatch(inp.story_key) else None
    dealer = _r._pinned_dealer(inp.mapping, inp.dealers, LOGIN_METOTLARI | _r.LOGIN_METOTLARI)
    if dealer is not None and not _BAYI_RE.fullmatch(dealer):
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
        "mapping_hash": _r.mapping_hash(inp.mapping),
        "template_hash": template_hash,
        "dealer": dealer,
        "package": uretilen_paket(kutuphane),
        "library_package": paket_dogrula(kutuphane),
        "class_name": sinif_adi(inp.story_key, platform, inp.sira_no, inp.case_id),
        "description": _r._maskeli(str(case.get("title") or "").strip(), maske) or ref,
        "steps": steps,
        "expects": expects,
    }


def _kotlin_sizinti_tara(content: str, inp: RenderInput) -> None:
    """Ortak tarama ham ve JSON kaçışlı biçimlere bakar; Kotlin kaçışlı biçim (`\\$`, `\\"`) ayrıca
    taranır (ör. `$` içeren gizli değer literalde `\\$` olarak geçer)."""
    from tp_core.features.testveri.atif import gizli_geciyor_mu

    adaylar = set()
    for g in _r._tum_gizliler(inp):
        try:
            adaylar.add(kotlin_literal(g)[1:-1])
        except RenderError:
            continue
    if adaylar and gizli_geciyor_mu(content, adaylar):
        raise _r.GizliSizinti(_r.GIZLI_SIZINTI_METNI)


def render(
    inp: RenderInput,
    cati: Any = None,
    rules: Path | None = None,
    *,
    referans_dil: str | None = None,
    sembol_tablosu: Mapping[str, Any] | None = None,
    paket: str | None = None,
) -> Rendered:
    """Espresso testi. `inp.e2e_root` forge'daki Kotlin kaynak köküdür (`TP_ANDROID_KOTLIN_ROOT`;
    boşsa `cati.kok_varsayilan`). `referans_dil` yok sayılır (Kotlin tablosu her zaman hedef dilin
    kendi tablosudur ya da ad eşit Java tablosu)."""
    if rules is None:
        raise RenderError("rules dizini verilmedi")
    platform = str(getattr(cati, "platform", "") or PLATFORM)
    if platform != PLATFORM:
        raise RenderError(f"Kotlin/Espresso yalnız android platformunda üretilir: {platform!r}")
    template, template_hash = _template(str(_r.templates_dir(rules)))
    kutuphane = kutuphane_paketi(sembol_tablosu, paket)
    ctx = build_context(
        inp, platform, template_hash, kutuphane=kutuphane, sembol_tablosu=sembol_tablosu
    )
    try:
        content = template.render(**ctx)
    except jinja2.TemplateError as exc:  # pragma: no cover - şablon hatası (geliştirici)
        raise RenderError(f"şablon render edilemedi: {exc}") from exc
    _r._sizinti_tara(content, inp)
    _kotlin_sizinti_tara(content, inp)
    test_file = test_dosyasi(kutuphane, ctx["class_name"])
    kok = inp.e2e_root.strip("/")
    if kok in ("", _r.E2E_ROOT, _r.E2E_APP_ROOT):  # ts/java varsayılanı geldiyse Kotlin kökü
        kok = kok_coz(cati)
    return Rendered(
        content=content,
        repo_path=f"{kok}/{test_file}",
        test_file=test_file,
        template_hash=template_hash,
        mapping_hash=ctx["mapping_hash"],
        dealer=ctx["dealer"],
        dil=AD,
        sinif_adi=ctx["class_name"],
        test_adi=TEST_METODU,
    )


# ------------------------------------------------------------- müşteri CI sonuç kimliği

_FQCN_RE = re.compile(r"\A(?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*\Z")


def test_kimligi(classname: str | None, metot: str, kok: str = "") -> tuple[str | None, str]:
    """JUnit (`classname`, `name`) → (`dosya`, `test_adi`): dosya `<kök>/<paket yolu>/<Dış>.kt`,
    ad `<Sınıf> › <metot>` (Java `ci.parse.java_test_kimligi` ile aynı biçim; üretilen script'in
    forge yoluyla eşleşir). Paketli sınıf adı değilse değer değişmez."""
    if not classname or not _FQCN_RE.match(classname):
        return classname, metot
    dis = classname.split("$", 1)[0]
    basit = classname.rsplit(".", 1)[-1]
    ad = metot if metot.startswith(f"{basit} › ") else f"{basit} › {metot}"
    on = f"{kok.strip('/')}/" if kok.strip("/") else ""
    return f"{on}{dis.replace('.', '/')}.kt", ad


def kimlik_donusturucu(kok: str = KOK_VARSAYILAN) -> Any:
    """Ş5 `musteri_ci.tp_results_ayristir(kimlik=…)` için `TestSatiri → TestSatiri`."""

    def donustur(satir: Any) -> Any:
        dosya, ad = test_kimligi(getattr(satir, "dosya", None), satir.test_adi, kok)
        return replace(satir, dosya=dosya, test_adi=ad)

    return donustur


# ----------------------------------------------------------------- kurulum PR'ı iskeleti

# Kurulum PR'ı (kullanıcı kararı 1): kütüphane altyapısı demo kütüphanesinden paket adı
# değiştirilerek alınır. Ekranlar (GirisEkrani …) uygulamaya özgüdür: iskelete girmez; boş bir
# `Kimlikler.kt` ve `Ekran.kt` tabanı girer.
ISKELET_DOSYALARI: tuple[str, ...] = (
    "altyapi/Ayarlar.kt",
    "altyapi/Bayi.kt",
    "altyapi/Bekle.kt",
    "altyapi/Kanit.kt",
    "altyapi/Kimlik.kt",
    "altyapi/UygulamaOturumu.kt",
    "ekranlar/Ekran.kt",
)
_BOS_KIMLIKLER = """package {paket}.ekranlar

/**
 * Erişilebilirlik kimlikleri — SAF VERİ (TP kurulum PR'ı). Yalnızca iç içe `object`'ler ve
 * `const val` dize sabitleri; KDoc ilk cümlesi = niyet. Uygulamanın test kimliklerini
 * (RN `testID`, yerel `android:id`) buraya ekleyin.
 */
object Kimlikler
"""


def kurulum_iskeleti(
    kaynak_kok: Path,
    kok: str,
    paket: str,
    *,
    demo_paket: str = VARSAYILAN_KUTUPHANE_PAKETI,
) -> dict[str, str]:
    """Ş5 `musteri_ci.kurulum_plani(iskelet=…)` için depo yolu → içerik.

    `kaynak_kok`: demo kütüphanesinin paket dizini (`…/android-test/java/com/antreklabs/
    bayisiparis/tp`). Paket adları `demo_paket` → `paket` olarak değiştirilir. TestTabani demo
    ekranlarına bağlı olduğundan iskelete girmez; müşteri kendi erişimcileriyle yazar (PR gövdesi
    `elle_adimlar`)."""
    paket = paket_dogrula(paket)
    on = f"{kok_coz(None, kok)}/{paket.replace('.', '/')}"
    out: dict[str, str] = {}
    for rel in ISKELET_DOSYALARI:
        metin = (kaynak_kok / rel).read_text(encoding="utf-8")
        out[f"{on}/{rel}"] = metin.replace(demo_paket, paket)
    out[f"{on}/ekranlar/Kimlikler.kt"] = _BOS_KIMLIKLER.format(paket=paket)
    return out


# ------------------------------------------------------------------ Ş0 eklenti nesnesi


class _KotlinEklentisi:
    """`DilEklentisi` protokolü (specs/014-test-dilleri/plan.md §2)."""

    ad = AD
    proje_dosyasi = PROJE_DOSYASI
    algila_kaliplari = ALGILA_KALIPLARI
    hat = HAT
    sablon = TEMPLATE_NAME
    kok_ayari = KOK_AYARI
    kok_varsayilan = KOK_VARSAYILAN
    gh_is_akisi = GH_IS_AKISI
    etiket = ETIKET
    # Render hedef dilin kendi sembol tablosunu ister (service: referans tablo java olsa da).
    hedef_tablo_gerekli = True

    def render(
        self,
        inp: RenderInput,
        cati: Any,
        rules: Path,
        *,
        referans_dil: str | None = None,
        sembol_tablosu: Mapping[str, Any] | None = None,
        paket: str | None = None,
    ) -> Rendered:
        return render(
            inp, cati, rules, referans_dil=referans_dil, sembol_tablosu=sembol_tablosu, paket=paket
        )

    def literal(self, value: Any) -> str:
        return kotlin_literal(value)

    def ident(self, value: Any) -> str:
        return kotlin_ident(value)

    def sinif_adi(
        self, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
    ) -> str | None:
        return sinif_adi(story_key, platform, sira_no, case_id)

    def uretilen_yol(
        self,
        cati: Any,
        kok: str,
        story_key: str | None,
        sira_no: int,
        case_id: uuid.UUID,
        **ek: Any,
    ) -> str:
        return uretilen_yol(cati, kok, story_key, sira_no, case_id, **ek)

    def test_dosyasi_mi(self, yol: str) -> bool:
        return test_dosyasi_mi(yol)

    def eslemeyi_donustur(self, output: Any) -> Any:
        return eslemeyi_donustur(output)


EKLENTI = _KotlinEklentisi()

__all__ = [
    "AD",
    "ALGILA_KALIPLARI",
    "EKLENTI",
    "KOK_AYARI",
    "KOK_VARSAYILAN",
    "TEMPLATE_NAME",
    "VARSAYILAN_KUTUPHANE_PAKETI",
    "kimlik_donusturucu",
    "kotlin_args",
    "kotlin_comment",
    "kotlin_ident",
    "kotlin_literal",
    "kurulum_iskeleti",
    "parse_dealers",
    "render",
    "sinif_adi",
    "test_dosyasi",
    "test_dosyasi_mi",
    "test_kimligi",
    "uretilen_yol",
]
