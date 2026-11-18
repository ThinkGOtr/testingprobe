"""Python dil eklentisi (014 Ş1; sözleşme specs/014-test-dilleri/plan.md §2, TASARIM §3.1).

Tam hat: web pytest + Playwright (`playwright_pytest.py.j2`, proje `e2e-python`), uygulama
(android | ios | windows) pytest + Appium (`appium_pytest.py.j2`, proje `e2e-app-python`, üç
platform tek proje). Toolchain derler (`py_compile`), korur (`py-guard`), koşar (pytest) ve kırarak
doğrular.

Model Python yazmaz: ajan eşlemesi (TS ya da Java page/screen object adlarıyla, K-T5) şablona
deterministik süzgeçlerle basılır. Ad kuralı (PO eşitliği, TASARIM §3): sınıf adı aynı; metot,
değişken ve modül adı snake_case (`addToCart` → `add_to_cart`, `LoginPage` → `pages.login_page`,
`GirisEkrani` → `ekranlar.giris_ekrani`). Python tablosuyla eşlenmiş ad (zaten snake_case) aynen
kalır (dönüşüm eşgüçlüdür).

Üretilen dosya (proje köküne göre `tests/generated/`):

- web: `test_<story>_c<sıra>_<uuid8>.py` (doğrulanmamış hattaki adla aynı; `render.py_test_name`)
- uygulama: `test_<story>_<platform>_c<sıra>_<uuid8>.py` (bir case'in her platformdaki script'i ayrı
  dosyadır; dallar/PR'lar merge'de çakışmaz — Java `<Story><Platform>C…Test` kuralı)

İşlev adı modül adıyla aynıdır (py-guard dosya adı kuralı). Gizli test verisi (013 K19)
`os.environ["TP_TESTVERI_…"]` ile okunur: doğrulanmamış hattın `__import__("os")` biçimi py-guard'da
yasaktır.

Bu modül `codegen/diller/__init__.py` (Ş0) keşfiyle yüklenir (`EKLENTI`). Ş0 paketi henüz yokken de
içe aktarılabilir: `AlgilaKalibi` yoksa yerel eşdeğeri kullanılır (geçici adaptör; entegrasyonda
Ş0'ınki geçerlidir).
"""

from __future__ import annotations

import contextlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jinja2

from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen import render as r

try:  # Ş0 sözleşmesi (codegen/diller/__init__.py)
    from tp_core.features.codegen.diller import AlgilaKalibi
except ImportError:  # pragma: no cover - Ş0 birleşmeden önce (geçici adaptör)

    @dataclass(frozen=True)
    class AlgilaKalibi:  # type: ignore[no-redef]
        platformlar: frozenset[str]
        kok_ayari: str
        alt_dizin: str


if TYPE_CHECKING:  # pragma: no cover
    from tp_core.features.codegen.platform import Cati

DIL = "python"
# Not: 011 doğrulanmamış hattın `pytest_playwright.py.j2` şablonu emekliye ayrıldı (014 karar 3a);
# tam hat şablonunun adı çatı_koşucu biçimindedir (`appium_pytest.py.j2` ile simetrik).
WEB_SABLONU = "playwright_pytest.py.j2"
UYGULAMA_SABLONU = "appium_pytest.py.j2"
URETILEN_DIZIN = "tests/generated"
WEB_KOK_AYARI = "TP_E2E_PYTHON_ROOT"
UYGULAMA_KOK_AYARI = "TP_E2E_APP_PYTHON_ROOT"
WEB_KOK = "e2e-python"
UYGULAMA_KOK = "e2e-app-python"
WEB_PAKETI = "pages"  # demo-app/e2e-python/pages/<modül>.py
UYGULAMA_PAKETI = "ekranlar"  # demo-app/e2e-app-python/ekranlar/<modül>.py
WEB_SURUCU = "page"  # pytest-playwright fikstürü
UYGULAMA_SURUCU = "driver"  # e2e-app-python/conftest.py fikstürü
# Giriş metotları (sabitlenen bayi): TS `login`, Java `girisYap`, Python `giris_yap`.
LOGIN_METOTLARI = frozenset({*r.LOGIN_METOTLARI, "giris_yap"})
# Şablonun kendi adları: sınıf/değişken bunlarla çakışırsa sessizce yanlış kod üretilirdi.
_AYRILMIS_SINIF = frozenset({"Page"})
_AYRILMIS_DEGISKEN = frozenset({"page", "driver", "pytest", "os"})
_TEST_RE = re.compile(r"test_[a-z0-9_]+")
_ELLE_TEST_RE = re.compile(r"(?:\A|/)(?:test_[A-Za-z0-9_]+|[A-Za-z0-9_]+_test)\.py\Z")
# Elle yazılmış test sayılmayan dizinler: aracın ürettikleri ve tarayıcısız birim testleri.
HARIC_DIZINLER = ("generated", "birim")


def _test_adi(story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID) -> str:
    """web `test_tpd_1_c2_3f9b1c2e`; uygulama `test_tpd_1_android_c2_3f9b1c2e`."""
    if platform == platformlar.WEB:
        return r.py_test_name(story_key, sira_no, case_id)
    kok = story_key.lower() if story_key and r._STORY_RE.fullmatch(story_key) else "serbest"
    ad = "test_" + f"{kok}-{platform}-c{int(sira_no)}-{case_id.hex[:8]}".replace("-", "_")
    if not _TEST_RE.fullmatch(ad):
        raise r.RenderError(f"üretilen Python test adı geçersiz: {ad}")
    return ad


def alt_yol(story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID) -> str:
    """Proje köküne göre üretilen dosya (`Rendered.test_file`, toolchain `test_files`)."""
    return f"{URETILEN_DIZIN}/{_test_adi(story_key, platform, sira_no, case_id)}.py"


def varsayilan_kok(platform: str) -> str:
    return WEB_KOK if platform == platformlar.WEB else UYGULAMA_KOK


def _arg(value: Any) -> str:
    if isinstance(value, r.OrtamDegeri):
        if not r.SIR_ADI_RE.fullmatch(value.ad):  # pragma: no cover - OrtamDegeri zaten denetler
            raise r.RenderError(f"geçersiz sır adı: {value.ad!r}")
        return f'os.environ["{value.ad}"]'
    return r.py_literal(value)


def py_args(args: Sequence[Any]) -> str:
    return ", ".join(_arg(a) for a in args)


def _env(templates_dir: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=False,  # Python üretilir; kaçış `py` süzgecindedir
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(py=r.py_literal, ident=r.py_ident, comment=r.py_comment, pyargs=py_args)
    return env


@lru_cache(maxsize=8)
def _sablon(templates_dir: str, ad: str) -> tuple[jinja2.Template, str]:
    kaynak = (Path(templates_dir) / ad).read_text(encoding="utf-8")
    return _env(Path(templates_dir)).get_template(ad), r.sha256_hex(kaynak)


def metot_adi(ad: Any) -> str:
    """TS/Java metot adı → Python adı (eşgüçlü: `add_to_cart` aynen kalır)."""
    return r.py_name(str(ad))


def eslemeyi_donustur(output: Any) -> Any:
    """Ajan çıktısındaki (`step_mapping`, `expects`) metot adlarını Python adlarına çevirir.
    Girdi değiştirilmez; sözlük değilse aynen döner. Geçersiz ad olduğu gibi bırakılır (render
    `RenderError` verir; eşleme denetimi zaten yakalar)."""
    if not isinstance(output, dict):
        return output
    out = dict(output)
    for alan in ("step_mapping", "expects"):
        liste = output.get(alan)
        if not isinstance(liste, list):
            continue
        yeni = []
        for m in liste:
            if isinstance(m, dict) and isinstance(m.get("method"), str):
                with contextlib.suppress(r.RenderError):
                    m = {**m, "method": metot_adi(m["method"])}
            yeni.append(m)
        out[alan] = yeni
    return out


def build_context(inp: r.RenderInput, platform: str, template_hash: str) -> dict[str, Any]:
    web = platform == platformlar.WEB
    case = inp.case
    adimlar = {str(s.get("id")): s for s in case.get("steps") or [] if isinstance(s, Mapping)}
    maske = r._tum_gizliler(inp)
    nesneler: dict[str, dict[str, str]] = {}
    os_gerekli = False

    def nesne(po: Any) -> str:
        sinif = r.py_ident(str(po))
        if sinif in nesneler:
            return nesneler[sinif]["degisken"]
        if sinif in _AYRILMIS_SINIF:
            raise r.RenderError(f"page object sınıf adı şablonun adlarıyla çakışıyor: {sinif}")
        degisken = r.py_name(sinif)
        if degisken in _AYRILMIS_DEGISKEN:
            raise r.RenderError(
                f"page object değişken adı şablonun adlarıyla çakışıyor: {degisken}"
            )
        if any(n["degisken"] == degisken for n in nesneler.values()):
            raise r.RenderError(f"iki page object aynı değişken adına düşüyor: {degisken}")
        nesneler[sinif] = {"sinif": sinif, "degisken": degisken, "modul": degisken}
        return degisken

    def cagri(item: Mapping[str, Any]) -> dict[str, Any]:
        nonlocal os_gerekli
        args = list(item["args"])
        for a in args:  # basılamayan değer şablondan önce reddedilir
            r.py_literal(a)
        args = r._kosu_arglari(item, inp.dealers, LOGIN_METOTLARI, inp.gizli_ortam)
        os_gerekli = os_gerekli or any(isinstance(a, r.OrtamDegeri) for a in args)
        return {
            "fixture": nesne(item.get("po")),
            "method": metot_adi(item.get("method")),
            "args": args,
        }

    steps: list[dict[str, Any]] = []
    for m in inp.mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        if steps and steps[-1]["sid"] == sid:
            steps[-1]["calls"].append(cagri(m))
            continue
        eylem = (adimlar.get(sid) or {}).get("action") or ""
        etiket = r._maskeli(f"{sid} — {eylem}", maske)
        steps.append({"sid": sid, "label": etiket, "calls": [cagri(m)]})
    expects = [cagri(e) for e in inp.mapping.get("expects") or []]
    if not nesneler:
        raise r.RenderError("eşleme boş: render edilecek çağrı yok")
    story = inp.story_key if inp.story_key and r._STORY_RE.fullmatch(inp.story_key) else None
    if story is not None and not r._ETIKET_RE.fullmatch(story):  # pragma: no cover - _STORY_RE dar
        raise r.RenderError(f"geçersiz story: {story!r}")
    dealer = r._pinned_dealer(inp.mapping, inp.dealers, LOGIN_METOTLARI)
    if dealer is not None and not r._JAVA_BAYI_RE.fullmatch(dealer):
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
        "ajan": "verify_and_map" if web else "verify_and_map_app",
        "platform": platform,
        "dealer": dealer,
        "story": story,
        "description": r._maskeli(str(case.get("title") or "").strip() or ref, maske),
        "po_package": WEB_PAKETI if web else UYGULAMA_PAKETI,
        "surucu": WEB_SURUCU if web else UYGULAMA_SURUCU,
        "test_name": _test_adi(inp.story_key, platform, inp.sira_no, inp.case_id),
        "objects": sorted(nesneler.values(), key=lambda n: n["sinif"]),
        "os_gerekli": os_gerekli,
        "steps": steps,
        "expects": expects,
    }


def render_python(inp: r.RenderInput, platform: str, rules: Path) -> r.Rendered:
    """(platform, python) testi. `inp.e2e_root` forge'daki Python proje köküdür (boş ya da TS kökü
    `e2e` ise platformun varsayılanı: `e2e-python` | `e2e-app-python`)."""
    if platform not in platformlar.PLATFORMLAR:
        raise r.RenderError(f"geçersiz platform: {platform!r}")
    web = platform == platformlar.WEB
    template, template_hash = _sablon(
        str(r.templates_dir(rules)), WEB_SABLONU if web else UYGULAMA_SABLONU
    )
    ctx = build_context(inp, platform, template_hash)
    try:
        content = template.render(**ctx)
    except jinja2.TemplateError as exc:  # pragma: no cover - şablon hatası (geliştirici)
        raise r.RenderError(f"şablon render edilemedi: {exc}") from exc
    r._sizinti_tara(content, inp)
    test_file = f"{URETILEN_DIZIN}/{ctx['test_name']}.py"
    kok = inp.e2e_root.strip("/")
    if kok in ("", r.E2E_ROOT):
        kok = varsayilan_kok(platform)
    return r.Rendered(
        content=content,
        repo_path=f"{kok}/{test_file}",
        test_file=test_file,
        template_hash=template_hash,
        mapping_hash=ctx["mapping_hash"],
        dealer=ctx["dealer"],
        dil=DIL,
        test_adi=ctx["test_name"],
    )


def test_dosyasi_mi(yol: str) -> bool:
    """Elle yazılmış pytest testi mi (`test_*.py` / `*_test.py`)? Üretilenler (`generated/`) ve
    tarayıcısız birim testleri (`birim/`) sayılmaz; `conftest.py` test değildir."""
    if not _ELLE_TEST_RE.search(yol):
        return False
    return not any(h in yol.split("/")[:-1] for h in HARIC_DIZINLER)


class _Python:
    ad = DIL
    proje_dosyasi = "pyproject.toml"
    algila_kaliplari = (
        AlgilaKalibi(frozenset({platformlar.WEB}), WEB_KOK_AYARI, "tests/"),
        AlgilaKalibi(frozenset(platformlar.UYGULAMA_PLATFORMLARI), UYGULAMA_KOK_AYARI, "tests/"),
    )

    def render(
        self,
        inp: r.RenderInput,
        cati: Cati,
        rules: Path,
        *,
        referans_dil: str | None = None,
        sembol_tablosu: Mapping[str, Any] | None = None,
    ) -> r.Rendered:
        # Tam hatta imza başlığı yoktur: page object kütüphanesi hedef projededir (sembol tablosu
        # eşlemeyi zaten doğruladı); `referans_dil` / `sembol_tablosu` kullanılmaz.
        return render_python(inp, cati.platform, rules)

    def literal(self, value: Any) -> str:
        return r.py_literal(value)

    def ident(self, value: Any) -> str:
        return r.py_ident(value)

    def sinif_adi(
        self, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
    ) -> str | None:
        return None  # pytest: sınıf yok; test kimliği işlev adıdır

    def uretilen_yol(
        self, cati: Cati, kok: str, story_key: str | None, sira_no: int, case_id: uuid.UUID
    ) -> str:
        temiz = (kok or "").strip("/")
        if temiz in ("", r.E2E_ROOT):
            temiz = getattr(cati, "kok_varsayilan", None) or varsayilan_kok(cati.platform)
        return f"{temiz}/{alt_yol(story_key, cati.platform, sira_no, case_id)}"

    def test_dosyasi_mi(self, yol: str) -> bool:
        return test_dosyasi_mi(yol)

    def eslemeyi_donustur(self, output: Any) -> Any:
        return eslemeyi_donustur(output)


EKLENTI = _Python()
