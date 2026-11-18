"""Tek seferlik, insan onaylı kurulum PR'ı (kullanıcı kararı 1; TASARIM test-dilleri §5.2/1).

Müşteri deposunda dilin ekran nesnesi kütüphanesi, test iskeleti ya da CI iş akışı yoksa TP
**bir kez** bir kurulum PR'ı önerir: `rules/ci-sablonlari` iş akışı (+ iOS `xcresult_junit.py`)
ve dil şeridinin verdiği iskelet dosyaları (Ş3: `Kimlikler.kt`, `Ekran.kt` …; Ş4: Swift
karşılıkları). PR yalnız açık bir insan onayıyla açılır (`kurulum_pr_ac(onaylayan=…)`).

TP `project.pbxproj`'a **dokunmaz**: Xcode UI test hedefi yoksa bu, PR gövdesine elle adım
olarak yazılır (`elle_adimlar`), TP otomatik eklemez.

Akış: `eksikleri_bul` (salt okuma) → `kurulum_plani` (dosyalar + gövde; önizleme) → insan onayı
→ `kurulum_pr_ac` (forge yazma; idempotent: aynı dalda açık PR varsa onu döner).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tp_core.features.musteri_ci.sozlesme import (
    KIRARAK_DOGRULANMADI,
    SABLON_KOKU,
    MusteriCiHatasi,
    MusteriCiHedefi,
    hedef,
)

KURULUM_DAL_ONEKI = "tp/kurulum"
KURULUM_ETIKETI = "tp-kurulum"


class KurulumOnayiYok(PermissionError):
    """Kurulum PR'ı insan onayı olmadan açılamaz."""


@dataclass(frozen=True)
class KurulumParametreleri:
    """Şablon parametreleri. Android: `gradle_modulu`, `test_paketi`; iOS: `xcode_proje`
    (`.xcodeproj` ya da `.xcworkspace` yolu), `sema` (scheme), `ui_test_hedefi`, `runs_on`,
    `simulator`, `yapilandirma` (ör. `Release`; boşsa şemanın test yapılandırması).
    `varsayilan_dal`: iş akışının PR tetiği.

    İsteğe bağlı (iki platform): `hazirlik_betigi` — derlemeden önce depo kökünden `bash` ile
    koşulan, müşteriye ait betik (ör. Expo/RN `expo prebuild`, test arka ucunu başlatma, test
    argümanları). Verilirse yerel proje (gradlew / .xcworkspace) depoda aranmaz: betik üretir.
    `node_surumu`: verilirse iş akışı Node kurar (betik npm/npx kullanıyorsa). `izlenen_kok`: PR'da
    değişince testleri koşturan dizin (boşsa `uygulama_koku`; üretilen proje depoda değilse
    uygulamanın kaynak kökü verilmelidir, yoksa iş akışı her PR'da no-op kalır)."""

    platform: str
    dil: str
    varsayilan_dal: str = "main"
    uygulama_koku: str = "."  # Gradle/Xcode projesinin depo içi kökü
    hazirlik_betigi: str = ""  # ör. ".github/tp/hazirlik.sh" (müşterinin; isteğe bağlı)
    node_surumu: str = ""  # ör. "22" (isteğe bağlı)
    izlenen_kok: str = ""  # boşsa uygulama_koku
    # Android
    gradle_modulu: str = "app"
    test_paketi: str = ""  # ör. "com.acme.bayi.tp"
    emulator_api: int = 34
    # iOS
    xcode_proje: str = ""  # ör. "ios/BayiSiparis.xcworkspace"
    sema: str = ""
    ui_test_hedefi: str = ""
    runs_on: str = "macos-15"
    simulator: str = "iPhone 16"
    yapilandirma: str = ""  # ör. "Release" (React Native: Debug Metro ister)


@dataclass(frozen=True)
class KurulumEksigi:
    kod: str  # "is_akisi" | "yardimci" | "iskelet" | "ui_test_hedefi" | "test_paketi"
    aciklama: str
    otomatik: bool  # TP kurulum PR'ıyla ekleyebilir mi (pbxproj hedefi: False)
    yol: str | None = None


@dataclass(frozen=True)
class KurulumPlani:
    hedef: MusteriCiHedefi
    parametreler: KurulumParametreleri
    eksikler: tuple[KurulumEksigi, ...]
    dosyalar: Mapping[str, str]  # depo yolu → içerik (yalnız yoksa eklenir)
    elle_adimlar: tuple[str, ...]
    dal: str
    baslik: str
    govde: str
    commit_mesaji: str
    hazir: bool = True  # parametre eksiği yok (PR açılabilir)

    @property
    def gerekli(self) -> bool:
        """PR'a girecek dosya ya da kullanıcıya gösterilecek elle adım var mı?"""
        return bool(self.dosyalar or self.elle_adimlar)


_DAL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
_YOL_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/ -]{0,199}")
_MODUL_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}")
_PAKET_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_AD_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9 _.-]{0,99}")
_RUNNER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_SIM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()._-]{0,63}")
_BETIK_RE = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9._/-]{0,199}")  # .github/tp/… olabilir
_NODE_RE = re.compile(r"[0-9]{1,2}(?:\.[0-9]{1,3}){0,2}")
_YER_TUTUCU_RE = re.compile(r"__TP_[A-Z_]+__")
EMULATOR_API_ARALIGI = (24, 40)
UI_TEST_URUN_TURU = "com.apple.product-type.bundle.ui-testing"
PARAMETRE_EKSIGI = "parametre"


def _yol_gecerli(deger: str, *, nokta: bool = False) -> bool:
    if nokta and deger == ".":
        return True
    return (
        isinstance(deger, str)
        and bool(_YOL_RE.fullmatch(deger))
        and not deger.startswith("/")
        and all(p not in ("", ".", "..") for p in deger.split("/"))
    )


def parametre_hatalari(p: KurulumParametreleri) -> list[str]:
    """Şablona girecek değerlerin doğrulaması (YAML/kabuk enjeksiyonu yok). Boş liste = geçerli."""
    h: list[str] = []
    try:
        hedef(p.platform, p.dil)
    except MusteriCiHatasi as exc:
        return [str(exc)]
    dal = p.varsayilan_dal
    if not (isinstance(dal, str) and _DAL_RE.fullmatch(dal) and ".." not in dal):
        h.append(f"varsayılan dal geçersiz: {dal!r}")
    if not _yol_gecerli(p.uygulama_koku, nokta=True):
        h.append(f"uygulama kökü geçersiz: {p.uygulama_koku!r}")
    if p.hazirlik_betigi and not (
        isinstance(p.hazirlik_betigi, str)
        and _BETIK_RE.fullmatch(p.hazirlik_betigi)
        and all(s not in ("", ".", "..") for s in p.hazirlik_betigi.split("/"))
        and p.hazirlik_betigi.endswith(".sh")
    ):
        h.append(f"hazırlık betiği geçersiz (depo içi .sh yolu): {p.hazirlik_betigi!r}")
    if p.node_surumu and not (isinstance(p.node_surumu, str) and _NODE_RE.fullmatch(p.node_surumu)):
        h.append(f"Node sürümü geçersiz: {p.node_surumu!r}")
    if p.izlenen_kok and not _yol_gecerli(p.izlenen_kok, nokta=True):
        h.append(f"izlenen kök geçersiz: {p.izlenen_kok!r}")
    if p.platform == "android":
        if not (isinstance(p.gradle_modulu, str) and _MODUL_RE.fullmatch(p.gradle_modulu)):
            h.append(f"Gradle modülü geçersiz: {p.gradle_modulu!r}")
        if not (isinstance(p.test_paketi, str) and _PAKET_RE.fullmatch(p.test_paketi)):
            h.append(f"test paketi gerekli (ör. com.acme.uygulama.tp): {p.test_paketi!r}")
        lo, hi = EMULATOR_API_ARALIGI
        if not (isinstance(p.emulator_api, int) and lo <= p.emulator_api <= hi):
            h.append(f"emülatör API düzeyi {lo}–{hi} aralığında olmalı: {p.emulator_api!r}")
    elif p.platform == "ios":
        if not (
            _yol_gecerli(p.xcode_proje) and p.xcode_proje.endswith((".xcodeproj", ".xcworkspace"))
        ):
            h.append(f"Xcode projesi (.xcodeproj/.xcworkspace) gerekli: {p.xcode_proje!r}")
        for ad, deger in (("şema", p.sema), ("UI test hedefi", p.ui_test_hedefi)):
            if not (isinstance(deger, str) and _AD_RE.fullmatch(deger)):
                h.append(f"{ad} gerekli: {deger!r}")
        if not (isinstance(p.runs_on, str) and _RUNNER_RE.fullmatch(p.runs_on)):
            h.append(f"runs-on geçersiz: {p.runs_on!r}")
        if not (isinstance(p.simulator, str) and _SIM_RE.fullmatch(p.simulator)):
            h.append(f"simülatör adı geçersiz: {p.simulator!r}")
        if p.yapilandirma and not (
            isinstance(p.yapilandirma, str) and _AD_RE.fullmatch(p.yapilandirma)
        ):
            h.append(f"yapılandırma geçersiz: {p.yapilandirma!r}")
    return h


def _sablon_dizini() -> Path:
    from tp_core.gateway.config import find_rules_dir

    return find_rules_dir() / SABLON_KOKU.split("/", 1)[1]


def _bilinen_sablonlar() -> frozenset[str]:
    from tp_core.features.musteri_ci.sozlesme import HEDEFLER

    return frozenset(ad for h in HEDEFLER.values() for ad in (h.sablon, *h.yardimcilar))


def sablon_metni(ad: str) -> str:
    """`rules/ci-sablonlari/<ad>` içeriği (yalnız bilinen adlar; yol enjeksiyonu yok)."""
    if ad not in _bilinen_sablonlar():
        raise MusteriCiHatasi(f"bilinmeyen CI şablonu: {ad!r}")
    return (_sablon_dizini() / ad).read_text(encoding="utf-8")


def _izlenen_yol(koku: str) -> str:
    return "**" if koku == "." else f"{koku}/**"


def sablon_degerleri(h: MusteriCiHedefi, p: KurulumParametreleri) -> dict[str, str]:
    """Yer tutucu → değer (doğrulanmış). Geçersiz parametre `MusteriCiHatasi`."""
    hatalar = parametre_hatalari(p)
    if hatalar:
        raise MusteriCiHatasi("; ".join(hatalar))
    d = {
        "__TP_IS_ADI__": h.is_adi,
        "__TP_VARSAYILAN_DAL__": p.varsayilan_dal,
        "__TP_UYGULAMA_KOKU__": p.uygulama_koku,
        "__TP_IZLENEN_YOL__": _izlenen_yol(p.izlenen_kok or p.uygulama_koku),
        "__TP_HAZIRLIK_BETIGI__": p.hazirlik_betigi,
        "__TP_NODE_SURUMU__": p.node_surumu,
    }
    if h.platform == "android":
        d |= {
            "__TP_GRADLE_MODULU__": p.gradle_modulu,
            "__TP_TEST_PAKETI__": p.test_paketi,
            "__TP_EMULATOR_API__": str(p.emulator_api),
        }
    else:
        d |= {
            "__TP_XCODE_BAYRAGI__": (
                "-workspace" if p.xcode_proje.endswith(".xcworkspace") else "-project"
            ),
            "__TP_XCODE_PROJE__": p.xcode_proje,
            "__TP_SEMA__": p.sema,
            "__TP_UI_TEST_HEDEFI__": p.ui_test_hedefi,
            "__TP_RUNS_ON__": p.runs_on,
            "__TP_SIMULATOR__": p.simulator,
            "__TP_YAPILANDIRMA__": p.yapilandirma,
        }
    return d


def sablon_isle(h: MusteriCiHedefi, p: KurulumParametreleri) -> str:
    """İş akışı şablonunu parametrelerle doldurur (`__TP_<AD>__` yer tutucuları; doğrulanmış
    değerler). Job adı her zaman `h.is_adi` (= check adı). Doldurulmamış yer tutucu kalırsa
    `MusteriCiHatasi`."""
    if (h.platform, h.dil) != (p.platform, p.dil):
        raise MusteriCiHatasi("hedef ile parametrelerin platform/dil'i farklı")
    metin = sablon_metni(h.sablon)
    degerler = sablon_degerleri(h, p)
    metin = _YER_TUTUCU_RE.sub(lambda m: degerler.get(m.group(0), m.group(0)), metin)
    kalan = sorted(set(_YER_TUTUCU_RE.findall(metin)))
    if kalan:
        raise MusteriCiHatasi(f"şablonda doldurulmamış yer tutucu: {', '.join(kalan)}")
    return metin


def _yardimci_yolu(h: MusteriCiHedefi, ad: str) -> str:
    return f"{h.yardimci_hedef_dizini}/{ad}"


def _kok_ici(koku: str, yol: str) -> str:
    return yol if koku == "." else f"{koku}/{yol}"


_HEDEF_BLOK_RE = re.compile(r"\{[^{}]*?isa = PBXNativeTarget;[^{}]*\}", re.S)


def ui_test_hedefi_durumu(pbxproj: str, ad: str) -> str:
    """pbxproj metninde UI test hedefinin durumu: `yok` | `esitlenmis` (Xcode 16+
    `fileSystemSynchronizedGroups`; TP yalnız .swift dosyası ekler) | `klasik` (dosyalar hedefe
    elle eklenmeli). TP pbxproj'u yalnız OKUR."""
    for blok in _HEDEF_BLOK_RE.findall(pbxproj or ""):
        ad_m = re.search(r"\bname = (\"?)(.+?)\1;", blok)
        if not ad_m or ad_m.group(2) != ad or UI_TEST_URUN_TURU not in blok:
            continue
        return "esitlenmis" if "fileSystemSynchronizedGroups" in blok else "klasik"
    return "yok"


def _pbxproj_yolu(p: KurulumParametreleri, dosyalar: set[str]) -> str | None:
    if p.xcode_proje.endswith(".xcodeproj"):
        y = _kok_ici(p.uygulama_koku, f"{p.xcode_proje}/project.pbxproj")
        return y if y in dosyalar else None
    # .xcworkspace: kök altındaki ilk .xcodeproj (Pods hariç).
    onek = "" if p.uygulama_koku == "." else f"{p.uygulama_koku}/"
    adaylar = sorted(
        y
        for y in dosyalar
        if y.startswith(onek)
        and y.endswith(".xcodeproj/project.pbxproj")
        and "/Pods/" not in f"/{y}"
    )
    return min(adaylar, key=lambda y: (y.count("/"), y)) if adaylar else None


def eksikleri_bul(
    depo_dosyalari: Iterable[str],
    p: KurulumParametreleri,
    *,
    iskelet_yollari: Iterable[str] = (),
    oku: Callable[[str], str | None] | None = None,
) -> list[KurulumEksigi]:
    """Depo dosya listesine (forge `list_files`) bakarak eksik kurulum öğeleri.

    `iskelet_yollari`: dil şeridinin beklediği kütüphane/iskelet dosyaları (Ş3/Ş4). `oku`: dosya
    içeriği okuyucu (ör. pbxproj'da UI test hedefi var mı; verilmezse yalnız dosya varlığına
    bakılır)."""
    h = hedef(p.platform, p.dil)
    dosyalar = set(depo_dosyalari)
    out: list[KurulumEksigi] = [
        KurulumEksigi(PARAMETRE_EKSIGI, hata, otomatik=False) for hata in parametre_hatalari(p)
    ]
    if h.is_akisi_yolu not in dosyalar:
        out.append(
            KurulumEksigi(
                "is_akisi",
                f"Müşteri CI iş akışı yok ({h.is_akisi_yolu}; job/check adı {h.is_adi}).",
                otomatik=True,
                yol=h.is_akisi_yolu,
            )
        )
    for ad in h.yardimcilar:
        y = _yardimci_yolu(h, ad)
        if y not in dosyalar:
            out.append(KurulumEksigi("yardimci", f"CI yardımcı betiği yok ({y}).", True, y))
    for y in dict.fromkeys(iskelet_yollari):
        if y not in dosyalar:
            out.append(
                KurulumEksigi("iskelet", f"Test iskeleti/kütüphane dosyası yok ({y}).", True, y)
            )
    if any(e.kod == PARAMETRE_EKSIGI for e in out):
        return out
    if p.hazirlik_betigi:
        # Yerel proje (gradlew / Xcode projesi, UI test hedefi) hazırlık betiğinde üretilir
        # (ör. Expo prebuild + config plugin): depoda aranmaz; betiğin kendisi müşterinindir.
        if p.hazirlik_betigi not in dosyalar:
            out.append(
                KurulumEksigi(
                    "hazirlik_betigi",
                    f"Hazırlık betiği yok ({p.hazirlik_betigi}): iş akışı derlemeden önce bu "
                    "betiği koşar (yerel projeyi üretir, test arka ucunu başlatır). Betik "
                    "uygulamaya özgüdür; TP eklemez.",
                    otomatik=False,
                    yol=p.hazirlik_betigi,
                )
            )
        return out
    if h.platform == "android":
        gradlew = _kok_ici(p.uygulama_koku, "gradlew")
        if gradlew not in dosyalar:
            out.append(
                KurulumEksigi(
                    "gradle_projesi",
                    f"Gradle sarmalayıcısı yok ({gradlew}): iş akışı `./gradlew` ile derler. "
                    "Android projesi depoda değilse (ör. Expo prebuild) derleme adımı elle "
                    "uyarlanmalıdır.",
                    otomatik=False,
                    yol=gradlew,
                )
            )
    else:
        pbx = _pbxproj_yolu(p, dosyalar)
        durum = "bilinmiyor"
        if pbx is None:
            durum = "yok_proje"
        elif oku is not None:
            try:
                durum = ui_test_hedefi_durumu(oku(pbx) or "", p.ui_test_hedefi)
            except Exception:  # okuma hatası: bilinmiyor (elle kontrol önerilir)
                durum = "bilinmiyor"
        if durum == "yok_proje":
            out.append(
                KurulumEksigi(
                    "xcode_projesi",
                    f"Xcode projesi bulunamadı ({_kok_ici(p.uygulama_koku, p.xcode_proje)}).",
                    otomatik=False,
                )
            )
        elif durum == "yok":
            out.append(
                KurulumEksigi(
                    "ui_test_hedefi",
                    f"Xcode projesinde '{p.ui_test_hedefi}' UI test hedefi yok. Xcode'da "
                    "File > New > Target > UI Testing Bundle ile ekleyin; Xcode 16+ eşitlenmiş "
                    "klasör (varsayılan) kullanın. TP project.pbxproj'a dokunmaz.",
                    otomatik=False,
                    yol=pbx,
                )
            )
        elif durum == "klasik":
            out.append(
                KurulumEksigi(
                    "esitlenmis_klasor",
                    f"'{p.ui_test_hedefi}' hedefi eşitlenmiş klasör kullanmıyor: TP'nin eklediği "
                    ".swift dosyaları hedefe otomatik girmez. Hedefin klasörünü Xcode'da "
                    "'Convert to Folder' ile eşitlenmiş klasöre çevirin.",
                    otomatik=False,
                    yol=pbx,
                )
            )
    return out


def _govde(
    h: MusteriCiHedefi,
    p: KurulumParametreleri,
    dosyalar: Mapping[str, str],
    elle: Iterable[str],
) -> str:
    satirlar = [
        "## Testing Probe kurulum PR'ı (tek seferlik)",
        "",
        f"Bu PR, TP'nin ürettiği **{h.platform} / {h.dil}** testlerinin bu deponun GitHub "
        "Actions'ında derlenip koşması için gereken dosyaları ekler. Bir kez birleştirilir; "
        "sonraki test PR'ları bu kuruluma dayanır. TP'de bir kullanıcı tarafından onaylandı.",
        "",
        "### Eklenen dosyalar",
        *[f"- `{y}`" for y in sorted(dosyalar)],
        "",
        "### Zorunlu check",
        f"İş akışının job adı **`{h.is_adi}`** TP'nin merge kapısının beklediği check adıdır; "
        "değiştirmeyin. Branch protection / ruleset'e zorunlu check olarak ekleyin.",
        "",
        f"### {KIRARAK_DOGRULANMADI['etiket']}",
        KIRARAK_DOGRULANMADI["aciklama"],
    ]
    elle = list(elle)
    if elle:
        satirlar += ["", "### Elle yapılacak adımlar", *[f"- [ ] {a}" for a in elle]]
    return "\n".join(satirlar) + "\n"


def kurulum_plani(
    p: KurulumParametreleri,
    depo_dosyalari: Iterable[str],
    *,
    iskelet: Mapping[str, str] | None = None,
    oku: Callable[[str], str | None] | None = None,
) -> KurulumPlani:
    """Kurulum önizlemesi (yazma yok). `iskelet`: dil şeridinin ürettiği depo yolu → içerik
    (yalnız depoda olmayanlar plana girer). Parametre eksiği varsa plan `hazir=False` döner
    (dosya üretilmez; eksikler kullanıcıya gösterilir)."""
    h = hedef(p.platform, p.dil)
    iskelet = dict(iskelet or {})
    eksikler = eksikleri_bul(depo_dosyalari, p, iskelet_yollari=iskelet, oku=oku)
    hazir = not any(e.kod == PARAMETRE_EKSIGI for e in eksikler)
    dosyalar: dict[str, str] = {}
    if hazir:
        for e in eksikler:
            if not e.otomatik or e.yol is None:
                continue
            if e.kod == "is_akisi":
                dosyalar[e.yol] = sablon_isle(h, p)
            elif e.kod == "yardimci":
                dosyalar[e.yol] = sablon_metni(e.yol.rsplit("/", 1)[-1])
            elif e.kod == "iskelet":
                dosyalar[e.yol] = iskelet[e.yol]
    elle = [e.aciklama for e in eksikler if not e.otomatik and e.kod != PARAMETRE_EKSIGI]
    if any(e.kod == "is_akisi" for e in eksikler):
        if h.platform == "android":
            # Ş3: iş akışı `assembleTpTest` / `connectedTpTestAndroidTest` koşar.
            elle.append(
                f"`{p.gradle_modulu}` modülüne `tpTest` derleme türünü ekleyin (initWith release, "
                'R8/minify kapalı) ve `testBuildType "tpTest"` yapın (Expo/RN: config plugin).'
            )
        elle.append(f"Branch protection / ruleset'e `{h.is_adi}` check'ini zorunlu olarak ekleyin.")
    return KurulumPlani(
        hedef=h,
        parametreler=p,
        eksikler=tuple(eksikler),
        dosyalar=dosyalar,
        elle_adimlar=tuple(elle),
        dal=f"{KURULUM_DAL_ONEKI}-{h.platform}-{h.dil}",
        baslik=f"TP kurulumu: {h.platform}/{h.dil} müşteri CI ({h.is_adi})",
        govde=_govde(h, p, dosyalar, elle),
        commit_mesaji=f"TP kurulumu: {h.platform}/{h.dil} müşteri CI iş akışı ve iskelet",
        hazir=hazir,
    )


def kurulum_pr_ac(
    forge: Any,
    plan: KurulumPlani,
    *,
    onaylayan: str | None,
    base: str | None = None,
) -> dict[str, Any]:
    """İnsan onaylı kurulum PR'ını açar (`forge.commit_files` + `forge.open_pr`).

    `onaylayan` boşsa `KurulumOnayiYok`; plan hazır değilse (parametre eksiği) `MusteriCiHatasi`.
    PR'a girecek dosya yoksa forge'a dokunmaz (`{"durum": "gereksiz"}`). Tek seferlik: kurulum
    dalında açık PR varsa yeni commit atılmaz, o PR döner (`mevcut`). Döner: `{durum:
    acildi|mevcut|gereksiz, pr_no, url, dal, sha, onaylayan, dosyalar, elle_adimlar}`. Denetim
    kaydını çağıran yazar (`musteri_ci.kurulum_pr_acildi`)."""
    if not isinstance(onaylayan, str) or not onaylayan.strip():
        raise KurulumOnayiYok("kurulum PR'ı insan onayı olmadan açılamaz")
    if not plan.hazir:
        eksik = "; ".join(e.aciklama for e in plan.eksikler if e.kod == PARAMETRE_EKSIGI)
        raise MusteriCiHatasi(f"kurulum planı hazır değil: {eksik}")
    temel = {
        "dal": plan.dal,
        "onaylayan": onaylayan.strip(),
        "dosyalar": sorted(plan.dosyalar),
        "elle_adimlar": list(plan.elle_adimlar),
    }
    if not plan.dosyalar:
        return {"durum": "gereksiz", "pr_no": None, "url": None, "sha": None, **temel}
    mevcut = forge.find_open_pr(plan.dal)
    if mevcut is not None:
        return {
            "durum": "mevcut",
            "pr_no": mevcut.number,
            "url": getattr(mevcut, "url", None),
            "sha": getattr(mevcut, "head_sha", None),
            **temel,
        }
    taban = base or getattr(forge, "base_branch", None) or "main"
    sha = forge.commit_files(plan.dal, dict(plan.dosyalar), plan.commit_mesaji, base=taban)
    govde = f"{plan.govde}\n---\nOnaylayan: {onaylayan.strip()}\n"
    pr = forge.open_pr(plan.dal, plan.baslik, govde, labels=(KURULUM_ETIKETI,))
    return {
        "durum": "acildi",
        "pr_no": pr.number,
        "url": getattr(pr, "url", None),
        "sha": sha,
        **temel,
    }
