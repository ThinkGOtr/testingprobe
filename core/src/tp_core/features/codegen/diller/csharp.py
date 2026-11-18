"""C# / .NET dil eklentisi (014 test dilleri §3.2, Ş2) — TAM HAT: web + windows.

- web × csharp: Playwright .NET + NUnit, şablon `playwright_nunit.cs.j2`, kök `TP_E2E_CSHARP_ROOT`
  (varsayılan `e2e-csharp`);
- windows × csharp: Appium .NET (NovaWindows) + NUnit, şablon `appium_nunit.cs.j2`, kök
  `TP_E2E_APP_CSHARP_ROOT` (varsayılan `e2e-app-csharp`).

Model C# yazmaz (Constitution IV): doğrulanmış eşleme şablonla render edilir. Literal,
tanımlayıcı ve yorum süzgeçleri `codegen/render.py`'deki C# süzgeçleridir (`cs_literal`, `cs_ident`, `cs_comment`;
011'de doğrulanmamış hat için yazıldı, burada tam hatta kullanılır). Bu modül render.py'yi
DEĞİŞTİRMEZ; yalnız onun saf yardımcılarını kullanır.

Ad dönüşümü (PO eşitliği, TASARIM §3): ajan eşlemesi referans tablonun adlarını taşır (repoda TS
varsa TS, yoksa Java, yoksa C#):

- **web:** erişimci = page object sınıf adı (`LoginPage`), metot = PascalCase + `Async`
  (`addToCart` → `AddToCartAsync`; Java tablosundan gelen `goTo` önce TS adına (`goto`) çevrilir →
  `GotoAsync`; zaten `…Async` biten C# adı değişmez).
- **windows:** erişimci = ekran sınıf adı (`GirisEkrani`), metot = PascalCase (`girisYap` →
  `GirisYap`). Appium .NET istemcisi eşzamanlıdır; `…Async` soneki yoktur.

Üretilen dosya: `<kök>/Tests/Generated/<Story><Platform>C<sıra>_<uuid8>Tests.cs`, ad alanı
`Antreklabs.Bayi.Tests.Generated`, test metodu `Senaryo`, NUnit kategorileri `uretilen`,
`<platform>`, `tp-case-<uuid>`, story. JUnit kimliği `<ad alanı>.<Sınıf>.Senaryo`.

Ş0 eklenti protokolü (TASARIM §1.3) henüz tabanda yok: `Cati` ve `CATILAR` `platform.py`'de
tanımlanınca oradan alınır; yoksa bu modüldeki eşdeğer veri sınıfı kullanılır (geçici adaptör,
entegrasyon notu). Eklenti yüzeyi: `DIL`, `CATI_TANIMLARI`, `cati()`, `render()`, `literal()`,
`ident()`, `sinif_adi()`, `test_dosyasi_mi()`, `algila_kaliplari`, `check_adi()`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import jinja2

from tp_core.audit.canonical import sha256_hex
from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen import render as _r

DIL = "csharp"
ETIKET = "C#"
WEB = "web"
WINDOWS = "windows"
PLATFORMLAR: tuple[str, ...] = (WEB, WINDOWS)

URETILEN_ALT_YOL = "Tests/Generated"
NAMESPACE = "Antreklabs.Bayi.Tests.Generated"
TEST_METODU = "Senaryo"
ASYNC_SONEKI = "Async"
URETILEN_KATEGORISI = "uretilen"
# Giriş metotları (bayi sabitleme): referans tablonun (TS / Java) ve C# tablosunun adları.
LOGIN_METOTLARI = frozenset({"login", "girisYap", "LoginAsync", "GirisYap"})
# Java tablosundaki ayrılmış sözcük karşılıkları → TS adı (`goTo` → `goto`; C#'ta `Goto` geçerli).
_JAVA_TERS_AD = {v: k for k, v in platformlar.JAVA_AD_ESLEME.items()}
# Şablonun ve tabanın kendi adlarıyla çakışan erişimci (sessizce yanlış kod üretirdi).
_AYRILMIS_ERISIMCI = frozenset(
    {"TestTabani", "Test", "Category", "Description", "Bayi", "Gizli", "Task", "NUnit",
     "Antreklabs", "System", "Senaryo", "Page", "Driver", "Surucu"}
)  # fmt: skip
_SINIF_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Tests")
_SIR_ADI_RE = _r.SIR_ADI_RE
# Elle yazılmış C# test dosyası (algılama ve kapsam): `*Tests.cs` / `*Test.cs`, `Birim/` ve
# üretilenler (`Tests/Generated/`) hariç; derleme çıktısı (`bin/`, `obj/`) hiç sayılmaz.
CS_TEST_SONEKLERI: tuple[str, ...] = ("Tests.cs", "Test.cs")
CS_HARIC_DIZINLER: tuple[str, ...] = ("Birim", "bin", "obj", "Generated")

Hat = Literal["tam", "musteri_ci", "dogrulanmamis"]


@dataclass(frozen=True)
class _Cati:
    """`platform.Cati` (Ş0, TASARIM §1.3) yokken eşdeğeri (alan adları ve sırası aynı)."""

    platform: str
    dil: str
    hat: Hat
    etiket: str
    sablon: str
    kok_ayari: str
    kok_varsayilan: str
    uretilen_alt_yol: str
    sonuc: Literal["junit", "playwright-json", "surefire"]
    ajan: Literal["verify_and_map", "verify_and_map_app"]
    gh_is_akisi: str | None


Cati = getattr(platformlar, "Cati", _Cati)

# (platform, dil) → Cati alanları. Ş0 `CATILAR` tablosuna bu iki satırı alır (tek kaynak orası
# olur); eklenti keşfi bu sözlüğü de okuyabilir.
CATI_TANIMLARI: dict[tuple[str, str], dict[str, Any]] = {
    (WEB, DIL): {
        "hat": "tam",
        "etiket": "Playwright .NET + NUnit",
        "sablon": "playwright_nunit.cs.j2",
        "kok_ayari": "TP_E2E_CSHARP_ROOT",
        "kok_varsayilan": "e2e-csharp",
        "uretilen_alt_yol": URETILEN_ALT_YOL,
        "sonuc": "junit",
        "ajan": "verify_and_map",
        "gh_is_akisi": "web-csharp",
    },
    (WINDOWS, DIL): {
        "hat": "tam",
        "etiket": "Appium .NET + NUnit (NovaWindows)",
        "sablon": "appium_nunit.cs.j2",
        "kok_ayari": "TP_E2E_APP_CSHARP_ROOT",
        "kok_varsayilan": "e2e-app-csharp",
        "uretilen_alt_yol": URETILEN_ALT_YOL,
        "sonuc": "junit",
        "ajan": "verify_and_map_app",
        "gh_is_akisi": "masaustu-windows-csharp",
    },
}

# Dil algılama (Ş0 `dil_algila` eklentiden okur): proje dosyası ve paket başvurusu kalıpları.
algila_kaliplari: dict[str, Any] = {
    "proje_dosyasi": ("*.csproj",),
    "web_paketleri": ("Microsoft.Playwright",),
    "uygulama_paketleri": ("Appium.WebDriver",),
    "test_sonekleri": CS_TEST_SONEKLERI,
    "haric_dizinler": CS_HARIC_DIZINLER,
}


def cati(platform: str | None) -> Any:
    """(platform, csharp) çatısı; geçersiz çiftte `ValueError` (Türkçe)."""
    p = platform or WEB
    alanlar = CATI_TANIMLARI.get((p, DIL))
    if alanlar is None:
        raise ValueError(
            f"{p} platformunda C# ile kod üretilemez; geçerli platform: {', '.join(PLATFORMLAR)}"
        )
    return Cati(platform=p, dil=DIL, **alanlar)


def check_adi(platform: str | None) -> str:
    """Yerel CI check adı (TASARIM §2.1): `local-ci-web-csharp` | `local-ci-windows-csharp`."""
    return f"{platformlar.YEREL_CHECK}-{cati(platform).platform}-{DIL}"


# ------------------------------------------------------------------------------ süzgeçler


def literal(value: Any) -> str:
    """C# literali (`render.cs_literal`): düz "…" dize / int / long / double / bool / null."""
    return _r.cs_literal(value)


def ident(value: Any) -> str:
    """C# tanımlayıcısı (`render.cs_ident`): ASCII, anahtar sözcük değil."""
    return _r.cs_ident(value)


def _arg(value: Any) -> str:
    if isinstance(value, _r.OrtamDegeri):
        if not _SIR_ADI_RE.fullmatch(value.ad):  # pragma: no cover - OrtamDegeri zaten denetli
            raise _r.RenderError(f"geçersiz sır adı: {value.ad!r}")
        # 013 K19: TestTabani.Gizli ortamdan okur; tanımsızsa açık hatayla durur (null geçmez).
        return f'Gizli("{value.ad}")'
    return literal(value)


def args(values: list[Any]) -> str:
    return ", ".join(_arg(a) for a in values)


def comment(value: Any) -> str:
    return _r.cs_comment(value)


def pascal(ad: str) -> str:
    kaynak = _r._duz_ident(ad, "C#")
    return kaynak[:1].upper() + kaynak[1:]


def metot_adi(ad: str, platform: str) -> str:
    """Referans tablodaki metot adı → C# adı (web: PascalCase + `Async`; windows: PascalCase)."""
    temiz = _JAVA_TERS_AD.get(ad, ad)
    p = pascal(temiz)
    if platform == WEB and not p.endswith(ASYNC_SONEKI):
        p += ASYNC_SONEKI
    return ident(p)


def erisimci_adi(po: str) -> str:
    """Page object / ekran sınıfı → TestTabani erişimci özelliği (sınıf adının kendisi)."""
    ad = ident(pascal(str(po)))
    if ad in _AYRILMIS_ERISIMCI:
        raise _r.RenderError(f"page object sınıf adı şablonun adlarıyla çakışıyor: {ad}")
    return ad


def sinif_adi(story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID) -> str:
    """`<Story><Platform>C<sıra>_<uuid8>Tests` (ör. `TPD1WebC2_3f9b1c2eTests`,
    `TPD1WindowsC2_3f9b1c2eTests`): Java sınıf adı kuralı + NUnit `Tests` soneki."""
    ad = _r.java_class_name(story_key, platform, sira_no, case_id) + "s"
    if not _SINIF_RE.fullmatch(ad):  # pragma: no cover - java_class_name zaten denetler
        raise _r.RenderError(f"üretilen C# sınıf adı geçersiz: {ad}")
    return ad


def test_dosyasi(story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID) -> str:
    """Proje köküne göre üretilen dosya (`Rendered.test_file`, toolchain `/check` `test_files`)."""
    return f"{URETILEN_ALT_YOL}/{sinif_adi(story_key, platform, sira_no, case_id)}.cs"


def repo_yolu(
    kok: str | None, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
) -> str:
    """Forge deposundaki yol: `<kök>/Tests/Generated/<Sınıf>.cs` (kök boşsa çatının varsayılanı)."""
    temiz = (kok or "").strip("/") or cati(platform).kok_varsayilan
    return f"{temiz}/{test_dosyasi(story_key, platform, sira_no, case_id)}"


def test_dosyasi_mi(yol: str, *, haric: tuple[str, ...] = CS_HARIC_DIZINLER) -> bool:
    """Forge yolu elle yazılmış bir C# testi mi? (`*Tests.cs` / `*Test.cs`; `Birim/`,
    `Tests/Generated/`, `bin/`, `obj/` altı hariç.)"""
    if not yol.endswith(CS_TEST_SONEKLERI):
        return False
    return not any(h in haric for h in yol.split("/")[:-1])


def kapsam_dosyasi_mi(yol: str) -> bool:
    """Onarım/kontrol kapsamına (`/check` `test_files`) girebilen C# testi mi? Proje köküne göre
    `Tests/**/<Ad>Tests.cs` (üretilenler dahil, `Birim/` hariç)."""
    parcalar = yol.split("/")
    return (
        yol.endswith(CS_TEST_SONEKLERI)
        and parcalar[0] == "Tests"
        and ".." not in parcalar
        and "Birim" not in parcalar[:-1]
    )


# --------------------------------------------------------------------------------- render


def _env(templates_dir: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=False,  # C# üretilir; kaçış `cs` süzgecindedir
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(cs=literal, ident=ident, comment=comment, csargs=args)
    return env


@lru_cache(maxsize=8)
def _template(templates_dir: str, ad: str) -> tuple[jinja2.Template, str]:
    kaynak = (Path(templates_dir) / ad).read_text(encoding="utf-8")
    return _env(Path(templates_dir)).get_template(ad), sha256_hex(kaynak)


def build_context(inp: _r.RenderInput, platform: str, template_hash: str) -> dict[str, Any]:
    case = inp.case
    adimlar = {str(s.get("id")): s for s in case.get("steps") or [] if isinstance(s, Mapping)}
    gizli = inp.gizli_ortam
    maske = _r._tum_gizliler(inp)

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        degerler = list(item["args"])
        for a in degerler:  # basılamayan değer şablondan önce reddedilir
            literal(a)
        return {
            "fixture": erisimci_adi(str(item.get("po"))),
            "method": metot_adi(str(item.get("method")), platform),
            "args": [_r._gizli_arg(a, gizli) for a in degerler],
        }

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        etiket = _r._maskeli(f"{sid} — {eylem}", maske)
        steps.append({"sid": sid, "label": etiket, "calls": [cagri(m)]})
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    story = inp.story_key if inp.story_key and _r._STORY_RE.fullmatch(inp.story_key) else None
    kategoriler = [URETILEN_KATEGORISI, platform, f"tp-case-{inp.case_id}"] + (
        [story] if story else []
    )
    for k in kategoriler:
        if not _r._ETIKET_RE.fullmatch(k):
            raise _r.RenderError(f"geçersiz NUnit kategorisi: {k!r}")
    dealer = _r._pinned_dealer(inp.mapping, inp.dealers, LOGIN_METOTLARI)
    if dealer is not None and not _r._JAVA_BAYI_RE.fullmatch(dealer):
        raise _r.RenderError(f"geçersiz bayi adı: {dealer!r}")
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
        "namespace": NAMESPACE,
        "class_name": sinif_adi(inp.story_key, platform, inp.sira_no, inp.case_id),
        "test_method": TEST_METODU,
        "categories": kategoriler,
        "description": _r._maskeli(str(case.get("title") or "").strip(), maske) or ref,
        "steps": steps,
        "expects": expects,
    }


def render(inp: _r.RenderInput, cati_: Any, rules: Path) -> _r.Rendered:
    """Eklenti protokolü (TASARIM §1.3): `render(inp, cati, rules) -> Rendered`.

    `inp.e2e_root` forge'daki C# proje köküdür (`e2e-csharp` / `e2e-app-csharp`; GitHub
    monoreposunda `<uygulama kökü>/e2e-csharp`). Boş ya da TS kökü (`e2e`) verilirse çatının
    varsayılanı kullanılır."""
    platform = cati_.platform
    if (platform, cati_.dil) not in CATI_TANIMLARI:
        raise _r.RenderError(f"C# eklentisi bu çatıyı üretemez: {platform}/{cati_.dil}")
    template, template_hash = _template(str(_r.templates_dir(rules)), cati_.sablon)
    ctx = build_context(inp, platform, template_hash)
    try:
        content = template.render(**ctx)
    except jinja2.TemplateError as exc:  # pragma: no cover - şablon hatası (geliştirici)
        raise _r.RenderError(f"şablon render edilemedi: {exc}") from exc
    _r._sizinti_tara(content, inp)
    kok = inp.e2e_root.strip("/")
    if kok in ("", _r.E2E_ROOT):
        kok = cati_.kok_varsayilan
    test_file = f"{cati_.uretilen_alt_yol}/{ctx['class_name']}.cs"
    return _r.Rendered(
        content=content,
        repo_path=f"{kok}/{test_file}",
        test_file=test_file,
        template_hash=template_hash,
        mapping_hash=ctx["mapping_hash"],
        dealer=ctx["dealer"],
        dil=DIL,
        sinif_adi=ctx["class_name"],
        test_adi=TEST_METODU,
    )


def render_platform(inp: _r.RenderInput, platform: str, rules: Path) -> _r.Rendered:
    """Kolaylık: `render(inp, cati(platform), rules)`."""
    return render(inp, cati(platform), rules)


def junit_kimligi(sinif: str, metot: str = TEST_METODU) -> str:
    """JUnit `classname.name` (JunitXml.TestLogger: classname = tam ad alanlı sınıf)."""
    return f"{NAMESPACE}.{sinif}.{metot}"


# ------------------------------------------------------------------- Ş0 eklenti protokolü


class _CsharpEklentisi:
    """plan.md §2 `DilEklentisi` (Ş0 keşfi `EKLENTI`'yi okur; entegrasyon adaptörü).

    Ad dönüşümü render'dadır (`metot_adi`, `erisimci_adi`): eşleme referans tablonun (TS / Java)
    adlarını taşır, bu yüzden `eslemeyi_donustur` kimliktir."""

    ad = DIL
    # Proje dosyası adı müşteri projesine göre değişir: kökte tek `*.csproj` (glob; dil_algila).
    proje_dosyasi = "*.csproj"
    hat = "tam"

    @property
    def algila_kaliplari(self) -> tuple[Any, ...]:
        from tp_core.features.codegen.diller import AlgilaKalibi

        return (
            AlgilaKalibi(frozenset({WEB}), "TP_E2E_CSHARP_ROOT", "Tests/"),
            AlgilaKalibi(frozenset({WINDOWS}), "TP_E2E_APP_CSHARP_ROOT", "Tests/"),
        )

    def render(
        self,
        inp: _r.RenderInput,
        cati: Any,
        rules: Path,
        *,
        referans_dil: str | None = None,
        sembol_tablosu: Mapping[str, Any] | None = None,
    ) -> _r.Rendered:
        return render(inp, cati, rules)

    def literal(self, value: Any) -> str:
        return literal(value)

    def ident(self, value: Any) -> str:
        return ident(value)

    def sinif_adi(
        self, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
    ) -> str | None:
        return sinif_adi(story_key, platform, sira_no, case_id)

    def uretilen_yol(
        self, cati: Any, kok: str, story_key: str | None, sira_no: int, case_id: uuid.UUID
    ) -> str:
        temiz = (kok or "").strip("/")
        if temiz == _r.E2E_ROOT:
            temiz = ""
        return repo_yolu(temiz or cati.kok_varsayilan, story_key, cati.platform, sira_no, case_id)

    def test_dosyasi_mi(self, yol: str) -> bool:
        return test_dosyasi_mi(yol)

    def eslemeyi_donustur(self, output: Any) -> Any:
        return output


EKLENTI = _CsharpEklentisi()
