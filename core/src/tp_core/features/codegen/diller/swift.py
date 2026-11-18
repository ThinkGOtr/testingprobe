r"""Swift / XCUITest dil eklentisi (014 test dilleri, TASARIM §3.4; şerit Ş4).

Hat: **musteri_ci** — TP testi üretir, statik korumadan geçirir (`toolchain/worker/diller/swift.py`,
tree-sitter-swift) ve PR açar; derleme ve koşu müşterinin macOS GitHub Actions runner'ındadır (TP
VM'ine Xcode girmez). Kırarak doğrulama yoktur (PR gövdesi ve portal "kırarak doğrulanmadı" der).

Kod deterministik şablonla (`rules/templates/xcuitest.swift.j2`) üretilir; model Swift yazmaz.

- **Sınıf:** `<Story>IosC<sıra>_<uuid8>Tests` (`final class …: TestTabani`), tek test metodu
  `testSenaryo`. Ad koruyucunun dosya adı kuralına uyar (`SINIF_RE`).
- **Yol:** `<TP_IOS_SWIFT_ROOT>/<Cati.uretilen_alt_yol>/<Sınıf>.swift` (varsayılan
  `UITests/TPUretilen/…`). Kök, UI test hedefinin **Xcode 16+ eşitlenmiş klasörüdür**
  (`PBXFileSystemSynchronizedRootGroup`): klasöre eklenen dosya hedefe kendiliğinden girer; TP
  `project.pbxproj`'a dokunmaz (kullanıcı kararı 1). Demo: `demo-app/mobile/ios-test/
  BayiSiparisUITests` (prebuild eklentisi `plugins/xcuitest-hedefi.js`).
- **Çağrı:** `<erişimci>.<metot>(<etiket>: <değer>, …)`. Swift argüman etiketleri sembol tablosundan
  gelir (`params[].label`; `_` = etiketsiz). Bu yüzden render **sembol tablosu ister**
  (`sembol_tablosu=`); yoksa `RenderError`.
- **Literal (`swift_literal`):** String / Int (64 bit) / Double (sonlu) / Bool. Dize yalnız düz çift
  tırnaklı; `\\` `\"` `\n` `\r` `\t` kaçışlı, diğer kontrol / biçim / satır ayırıcı karakterler
  `\u{XXXX}` (değer korunur, kaynakta görünür). Ters bölü hep kaçışlandığı için `\(…)`
  interpolasyonu, `#"…"#` ham dize ve `\"""` üretilemez.
- **Gizli test verisi (013 K19):** `ortam("TP_TESTVERI_…")` (`TestTabani.ortam`; xcodebuild'e
  `TEST_RUNNER_TP_TESTVERI_…` ile verilir). Render sonrası sızıntı taraması ortak yardımcıdır.
- **Bayi sabitleme:** case bir e2e bayisiyle giriş yapıyorsa `override class var bayi: String?`.
  Bayiler `Altyapi/Bayiler.swift`'ten okunur (`parse_dealers`; müşteri projesinde yoksa sabitleme
  yapılmaz).
"""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jinja2

from tp_core.audit.canonical import sha256_hex
from tp_core.features.codegen import render as r
from tp_core.features.codegen.checks import fixture_name

# ---------------------------------------------------------------- Ş0 sözleşme adaptörleri
# Ş0 (`codegen/diller/__init__.py`, `platform.CATILAR`) birleşmeden de bu modül tek başına
# çalışsın diye: varsa Ş0 türleri kullanılır, yoksa aynı alanlı yerel karşılıklar.
try:  # pragma: no cover - entegrasyonda Ş0 türü gelir
    from tp_core.features.codegen.diller import AlgilaKalibi  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Ş0 öncesi

    @dataclass(frozen=True)
    class AlgilaKalibi:  # type: ignore[no-redef]
        platformlar: frozenset[str]
        kok_ayari: str
        alt_dizin: str


try:  # pragma: no cover
    from tp_core.features.codegen.platform import Cati  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover

    @dataclass(frozen=True)
    class Cati:  # type: ignore[no-redef]
        platform: str
        dil: str
        hat: str
        etiket: str
        sablon: str
        kok_ayari: str
        kok_varsayilan: str
        uretilen_alt_yol: str
        sonuc: str
        ajan: str
        gh_is_akisi: str | None


# ------------------------------------------------------------------------------ sabitler

AD = "swift"
PLATFORM = "ios"
SABLON = "xcuitest.swift.j2"
KOK_AYARI = "TP_IOS_SWIFT_ROOT"
KOK_VARSAYILAN = "UITests"
URETILEN_ALT_YOL = "TPUretilen"
IS_AKISI = "mobil-ios-swift"  # GitHub job/check adı (Ş5 musteri_ci.is_adi ile aynı)
TEST_METODU = "testSenaryo"
TABAN_SINIF = "TestTabani"
EKRAN_TABANI = "Ekran"
KIMLIKLER_DOSYASI = "Ekranlar/Kimlikler.swift"
BAYILER_DOSYASI = "Altyapi/Bayiler.swift"
# Giriş metodu (bayi sabitleme): Java ile aynı ad (`GirisEkrani.girisYap`), web `login`.
LOGIN_METOTLARI = frozenset({"login", "girisYap"})
SINIF_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Tests")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BAYI_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_DOUBLE_RE = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_INT64 = (-(2**63), 2**63 - 1)
_KACIS = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
# `\u{…}` ile basılan kategoriler: kontrol, biçim (yön denetimi, sıfır genişlik), satır/paragraf
# ayırıcı, özel kullanım, atanmamış. Vekil (Cs) Python dizesinde tek başına geçemez → reddedilir.
_KACISLI_KATEGORI = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cn"})
# Swift'te tanımlayıcı olarak kullanılamayan (ters tırnaksız) anahtar sözcükler.
SWIFT_ANAHTAR = frozenset(
    """
    associatedtype class deinit enum extension fileprivate func import init inout internal let
    open operator private precedencegroup protocol public rethrows static struct subscript
    typealias var break case catch continue default defer do else fallthrough for guard if in
    repeat return throw switch where while Any as await false is nil self Self super throws
    true try _ Type Protocol
    """.split()  # noqa: SIM905
)
_BAYILER_RE = re.compile(
    r"BayiBilgisi\(\s*kullaniciAdi:\s*\"(?P<u>[A-Za-z0-9_.-]+)\"\s*,"
    r"\s*parola:\s*\"(?P<p>[^\"\\]*)\"\s*,\s*ad:\s*\"(?P<n>[^\"\\]*)\"\s*\)"
)
ELLE_ADIMLAR: tuple[str, ...] = (
    "Xcode 16+ ile projeye bir **UI Testing Bundle** hedefi ekleyin (File → New → Target → "
    "UI Testing Bundle; 'Target to be Tested' = uygulama hedefi).",
    "Hedefin kaynak klasörünün **eşitlenmiş klasör** olduğundan emin olun (Xcode 16'da yeni "
    "hedefin varsayılanı; eski bir gruptan geliyorsa sağ tık → 'Convert to Folder'). TP yalnız bu "
    "klasöre `.swift` dosyası ekler, `project.pbxproj`'a dokunmaz.",
    "Paylaşılan şemanın (Product → Scheme → Manage Schemes → Shared) Test eyleminde UI test "
    "hedefini işaretleyin; iş akışı `xcodebuild test -scheme <şema> -only-testing:<hedef>` koşar.",
    "Klasörün yolunu proje ayarında `TP_IOS_SWIFT_ROOT` (ayrı iOS deposunda "
    "`TP_IOS_SWIFT_ROOT_IOS`) olarak verin.",
)

CATI = Cati(
    platform=PLATFORM,
    dil=AD,
    hat="musteri_ci",
    etiket="XCUITest",
    sablon=SABLON,
    kok_ayari=KOK_AYARI,
    kok_varsayilan=KOK_VARSAYILAN,
    uretilen_alt_yol=URETILEN_ALT_YOL,
    sonuc="junit",
    ajan="verify_and_map_app",
    gh_is_akisi=IS_AKISI,
)


# ------------------------------------------------------------------------------ süzgeçler


def _metin(value: str) -> str:
    out = []
    for ch in value:
        if ch in _KACIS:
            out.append(_KACIS[ch])
        elif unicodedata.category(ch) == "Cs":
            raise r.RenderError(f"Swift literaline basılamayan vekil karakter (U+{ord(ch):04X})")
        elif unicodedata.category(ch) in _KACISLI_KATEGORI:
            out.append(f"\\u{{{ord(ch):X}}}")
        else:
            out.append(ch)  # ASCII dışı karakter ham UTF-8 (Swift kaynağı UTF-8)
    return '"' + "".join(out) + '"'


def swift_literal(value: Any) -> str:
    """Swift literali: String / Int (64 bit) / Double / Bool. Başka tür → RenderError."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if _INT64[0] <= value <= _INT64[1]:
            return str(value)
        raise r.RenderError(f"Swift Int (64 bit) aralığı dışında tamsayı: {value}")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise r.RenderError("sonlu olmayan sayı şablona basılamaz")
        metin = repr(value)
        if not _DOUBLE_RE.fullmatch(metin):
            raise r.RenderError(f"Swift Double literaline çevrilemeyen sayı: {metin}")
        return metin
    if isinstance(value, str):
        return _metin(value)
    raise r.RenderError(f"şablona basılamayan değer türü: {type(value).__name__}")


def swift_ident(value: Any) -> str:
    if not isinstance(value, str) or not _IDENT_RE.fullmatch(value):
        raise r.RenderError(f"geçersiz Swift tanımlayıcısı: {value!r}")
    if value in SWIFT_ANAHTAR:
        raise r.RenderError(f"Swift anahtar sözcüğü tanımlayıcı olamaz: {value!r}")
    return value


def swift_comment(value: Any) -> str:
    """`//` yorumu: tek satır, kontrol/biçim karakteri yok; `/*` `*/` iç içe yorum açamaz."""
    metin = r.comment(value)
    temiz = "".join(" " if unicodedata.category(ch) in _KACISLI_KATEGORI else ch for ch in metin)
    temiz = temiz.replace("/*", "/ *").replace("*/", "* /")
    return re.sub(r"\s+", " ", temiz).strip() or "-"


def _arg(value: Any) -> str:
    if isinstance(value, r.OrtamDegeri):
        return f'ortam("{value.ad}")'
    return swift_literal(value)


def swift_args(args: Sequence[tuple[str | None, Any]]) -> str:
    """`[(etiket|None, değer), …]` → `etiket: değer, …` (etiketsiz parametre: yalnız değer)."""
    parcalar = []
    for etiket, deger in args:
        parcalar.append(_arg(deger) if etiket is None else f"{swift_ident(etiket)}: {_arg(deger)}")
    return ", ".join(parcalar)


def _env(templates_dir: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=False,  # Swift üretilir; kaçış `swift` süzgecindedir
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["swift"] = swift_literal
    env.filters["ident"] = swift_ident
    env.filters["comment"] = swift_comment
    env.filters["sargs"] = swift_args
    return env


@lru_cache(maxsize=4)
def _template(templates_dir: str) -> tuple[jinja2.Template, str]:
    kaynak = (Path(templates_dir) / SABLON).read_text(encoding="utf-8")
    return _env(Path(templates_dir)).get_template(SABLON), sha256_hex(kaynak)


# ------------------------------------------------------------------------------ adlar / yollar


def sinif_adi(story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID) -> str:
    """`<Story><Platform>C<sıra>_<uuid8>Tests` (ör. `TPD1IosC2_3f9b1c2eTests`)."""
    kok = story_key if story_key and r._STORY_RE.fullmatch(story_key) else "Serbest"
    kok = re.sub(r"[^A-Za-z0-9]", "", kok)
    ad = f"{kok}{platform[:1].upper()}{platform[1:]}C{int(sira_no)}_{case_id.hex[:8]}Tests"
    if not SINIF_RE.fullmatch(ad):
        raise r.RenderError(f"üretilen Swift sınıf adı geçersiz: {ad}")
    return ad


def uretilen_yol(
    cati: Any, kok: str, story_key: str | None, sira_no: int, case_id: uuid.UUID
) -> str:
    """Forge'daki tam depo yolu: `<kök>/<alt yol>/<Sınıf>.swift`."""
    k = (kok or "").strip("/") or cati.kok_varsayilan
    ad = sinif_adi(story_key, cati.platform, sira_no, case_id)
    return f"{k}/{cati.uretilen_alt_yol}/{ad}.swift"


def test_dosyasi_mi(yol: str) -> bool:
    """Elle yazılmış XCUITest dosyası mı? `*Tests.swift` / `*Test.swift` / `*Testi.swift`;
    TP'nin ürettikleri (`TPUretilen/`) sayılmaz. UI test ile birim testini ayırmak için algılama
    ayrıca içerikte `XCUIApplication` arar (`ICERIK_ISARETI`)."""
    if not isinstance(yol, str) or not yol.endswith(("Tests.swift", "Test.swift", "Testi.swift")):
        return False
    return URETILEN_ALT_YOL not in yol.split("/")[:-1]


# UI testi işareti (birim testleri `XCTestCase` kullanır ama uygulamayı başlatmaz).
ICERIK_ISARETI = re.compile(r"\bXCUIApplication\b|\b" + TABAN_SINIF + r"\b")


def parse_dealers(bayiler_source: str) -> dict[str, dict[str, str]]:
    """`Altyapi/Bayiler.swift` `BayiBilgisi(kullaniciAdi:parola:ad:)` girdileri (sözdizimsel)."""
    return {
        d.group("u"): {"password": d.group("p"), "name": d.group("n")}
        for d in _BAYILER_RE.finditer(bayiler_source or "")
    }


# ------------------------------------------------------------------------------ sembol etiketleri


def etiketler(sembol_tablosu: Mapping[str, Any] | None) -> dict[tuple[str, str], list[str | None]]:
    """(sınıf, metot) → parametre etiketleri (None = etiketsiz `_`). Swift sembol tablosu her
    parametrede `label` taşır; yoksa parametre adı etikettir (Swift varsayılanı)."""
    out: dict[tuple[str, str], list[str | None]] = {}
    for po in (sembol_tablosu or {}).get("page_objects") or []:
        cls = po.get("class")
        if not isinstance(cls, str):
            continue
        for m in po.get("methods") or []:
            if not isinstance(m.get("name"), str):
                continue
            lst: list[str | None] = []
            for p in m.get("params") or []:
                etiket = p.get("label", p.get("name"))
                lst.append(None if etiket in (None, "_") else str(etiket))
            out[(cls, m["name"])] = lst
    return out


# ------------------------------------------------------------------------------ render


def build_context(
    inp: r.RenderInput, template_hash: str, etiket: Mapping[tuple[str, str], list[str | None]]
) -> dict[str, Any]:
    case = inp.case
    adimlar = {str(s.get("id")): s for s in case.get("steps") or [] if isinstance(s, Mapping)}
    gizli = inp.gizli_ortam
    maske = r._tum_gizliler(inp)

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        po = swift_ident(str(item.get("po")))
        metot = swift_ident(str(item.get("method")))
        args = list(item.get("args") or [])
        anahtar = (po, metot)
        if anahtar not in etiket:
            raise r.RenderError(f"{po}.{metot} Swift sembol tablosunda yok (etiket bilinmiyor)")
        etiketler_ = etiket[anahtar]
        if len(args) > len(etiketler_):
            raise r.RenderError(
                f"{po}.{metot} en çok {len(etiketler_)} argüman alır, {len(args)} verildi"
            )
        return {
            "fixture": swift_ident(fixture_name(po)),
            "method": metot,
            "args": [(etiketler_[i], r._gizli_arg(a, gizli)) for i, a in enumerate(args)],
        }

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        steps.append(
            {"sid": sid, "label": r._maskeli(f"{sid} — {eylem}", maske), "calls": [cagri(m)]}
        )
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    story = inp.story_key if inp.story_key and r._STORY_RE.fullmatch(inp.story_key) else None
    dealer = r._pinned_dealer(inp.mapping, inp.dealers, LOGIN_METOTLARI)
    if dealer is not None and not _BAYI_RE.fullmatch(dealer):
        raise r.RenderError(f"geçersiz bayi adı: {dealer!r}")
    ref = f"{story or 'SERBEST'} C{int(inp.sira_no)}"
    return {
        "case_ref": ref,
        "case_id": str(inp.case_id),
        "story_key": story or "-",
        "test_key": inp.test_key or "-",
        "case_hash": inp.case_hash,
        "mode": inp.mode or "-",
        "bundle_hash": inp.bundle_hash or "-",
        "mapping_hash": r.mapping_hash(inp.mapping),
        "template_hash": template_hash,
        "check": IS_AKISI,
        "dealer": dealer,
        "class_name": sinif_adi(inp.story_key, PLATFORM, inp.sira_no, inp.case_id),
        "description": r._maskeli(str(case.get("title") or "").strip(), maske) or ref,
        "steps": steps,
        "expects": expects,
    }


def render(
    inp: r.RenderInput,
    cati: Any,
    rules: Path,
    *,
    referans_dil: str | None = None,
    sembol_tablosu: Mapping[str, Any] | None = None,
) -> r.Rendered:
    """XCUITest dosyası. `inp.e2e_root` UI test hedefinin (eşitlenmiş) klasörüdür; `test_file`
    bu köke göredir (`TPUretilen/<Sınıf>.swift`; toolchain `/check` `test_files`)."""
    if sembol_tablosu is None:
        raise r.RenderError(
            "Swift render için sembol tablosu gerekli (argüman etiketleri tablodan okunur)"
        )
    cati = cati or CATI
    template, template_hash = _template(str(r.templates_dir(rules)))
    ctx = build_context(inp, template_hash, etiketler(sembol_tablosu))
    try:
        content = template.render(**ctx)
    except jinja2.TemplateError as exc:  # pragma: no cover - şablon hatası (geliştirici)
        raise r.RenderError(f"şablon render edilemedi: {exc}") from exc
    r._sizinti_tara(content, inp)
    test_file = f"{cati.uretilen_alt_yol}/{ctx['class_name']}.swift"
    kok = inp.e2e_root.strip("/") if inp.e2e_root and inp.e2e_root != r.E2E_ROOT else ""
    return r.Rendered(
        content=content,
        repo_path=f"{kok or cati.kok_varsayilan}/{test_file}",
        test_file=test_file,
        template_hash=template_hash,
        mapping_hash=ctx["mapping_hash"],
        dealer=ctx["dealer"],
        dil=AD,
        sinif_adi=ctx["class_name"],
        test_adi=TEST_METODU,
    )


# ------------------------------------------------------------------------------ kurulum iskeleti


def iskelet(kok: str, rules: Path) -> dict[str, str]:
    """Kurulum PR'ının (Ş5 `musteri_ci.kurulum_plani(iskelet=…)`) Swift dosyaları: depo yolu →
    içerik. Ekran tabanı, test tabanı ve boş kimlik dosyası (`rules/templates/xcuitest_iskelet/`).
    UI test hedefinin kendisi pbxproj gerektirir: `ELLE_ADIMLAR` (TP eklemez)."""
    k = (kok or "").strip("/") or KOK_VARSAYILAN
    dizin = r.templates_dir(rules) / "xcuitest_iskelet"
    out: dict[str, str] = {}
    for yol in sorted(dizin.rglob("*.swift")):
        out[f"{k}/{yol.relative_to(dizin).as_posix()}"] = yol.read_text(encoding="utf-8")
    out[f"{k}/{URETILEN_ALT_YOL}/.gitkeep"] = ""
    return out


# ------------------------------------------------------------------------------ eklenti nesnesi


class _SwiftEklentisi:
    ad = AD
    # Proje dosyası: kök (eşitlenmiş klasör) altında kimlik dosyası = ekran nesnesi kütüphanesi.
    proje_dosyasi = KIMLIKLER_DOSYASI
    algila_kaliplari = (AlgilaKalibi(frozenset({PLATFORM}), KOK_AYARI, ""),)
    cati = CATI
    # Render hedef dilin kendi sembol tablosunu ister (argüman etiketleri; service ayrıca alır).
    hedef_tablo_gerekli = True
    elle_adimlar = ELLE_ADIMLAR

    def render(
        self,
        inp: r.RenderInput,
        cati: Any,
        rules: Path,
        *,
        referans_dil: str | None = None,
        sembol_tablosu: Mapping[str, Any] | None = None,
    ) -> r.Rendered:
        return render(inp, cati, rules, referans_dil=referans_dil, sembol_tablosu=sembol_tablosu)

    def literal(self, value: Any) -> str:
        return swift_literal(value)

    def ident(self, value: Any) -> str:
        return swift_ident(value)

    def sinif_adi(
        self, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
    ) -> str | None:
        return sinif_adi(story_key, platform, sira_no, case_id)

    def uretilen_yol(
        self, cati: Any, kok: str, story_key: str | None, sira_no: int, case_id: uuid.UUID
    ) -> str:
        return uretilen_yol(cati, kok, story_key, sira_no, case_id)

    def test_dosyasi_mi(self, yol: str) -> bool:
        return test_dosyasi_mi(yol)

    def eslemeyi_donustur(self, output: Any) -> Any:
        """Uygulama ajanı Swift tablosunun adlarıyla eşler (camelCase, Java ile aynı); dönüşüm
        yok. Web adı `goto` Swift'te geçerli bir tanımlayıcıdır."""
        return output

    def parse_dealers(self, kaynak: str) -> dict[str, dict[str, str]]:
        return parse_dealers(kaynak)

    def iskelet(self, kok: str, rules: Path) -> dict[str, str]:
        return iskelet(kok, rules)


EKLENTI = _SwiftEklentisi()
