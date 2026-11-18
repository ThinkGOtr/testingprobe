"""Platform boyutu (009 mobil-masaüstü §2.1): web | android | ios | windows.

Case platformdan bağımsızdır; kod üretimi (case, platform) çiftinedir. `web` mevcut
Playwright/TypeScript hattının aynısıdır (varsayılan, geriye uyum); `android`, `ios`, `windows`
Appium + Java + TestNG hattıdır (`demo-app/e2e-app`, `toolchain/java-araclar`, app-mcp).

**Üretim dili (011 §2.1):** dil ayrı bir boyuttur; platformdan türetilmez. `web` her dille
üretilebilir (`ts` | `java` | `csharp` | `python`), uygulama platformları yalnız `java` ile.
"Platform = dil" çıkarımı yapılmaz; iki ayrı soru vardır:

- **araç/ortam** (ajan aracı, tarayıcı/cihaz, tekrar sayısı) → platform (`uygulama_mi`);
- **kod/derleme/yama** (sembol tablosu, şablon, literal, derleme adımları) → dil (`java_mi`,
  `tam_hat_mi`).

Yerel CI check adı ikisine birden bakar (`check_adi(platform, dil)`, K-T1): web + ts `local-ci`,
web + Java `local-ci-web-java`, uygulama `local-ci-<platform>`.

Tam hat dilleri (`ts`, `java`) derlenir, koşulur ve PR'a girer; doğrulanmamış diller (`csharp`,
`python`) yalnız üretilir (commit/PR/yerel kontrol yok, script durumu `unverified`).

Bu modül saf yardımcıdır (veritabanı/ağ yok): hem core-api hem core-worker kullanır.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

Platform = Literal["web", "android", "ios", "windows"]
WEB = "web"
UYGULAMA_PLATFORMLARI: tuple[str, ...] = ("android", "ios", "windows")
PLATFORMLAR: tuple[str, ...] = (WEB, *UYGULAMA_PLATFORMLARI)
# Forge deposunda Java test projesinin kökü (uygulama köküne göre): `<app root>/e2e-app`.
E2E_APP_DIZINI = "e2e-app"
# Web + Java (Playwright for Java + TestNG) test projesinin kökü: `<app root>/e2e-java` (011 §2.5).
E2E_JAVA_DIZINI = "e2e-java"
# Web + TS (Playwright) test projesinin kökü: `<app root>/e2e`.
E2E_DIZINI = "e2e"
# e2e-app / e2e-java köküne göre (iki Java projesi aynı paket düzenini kullanır).
JAVA_URETILEN_DIZIN = "src/test/java/com/antreklabs/bayi/uretilen"

Dil = Literal["ts", "java", "csharp", "python", "kotlin", "swift"]
TS = "ts"
JAVA = "java"
TAM_HAT_DILLERI: tuple[str, ...] = ("ts", "java")
DOGRULANMAMIS_DILLER: tuple[str, ...] = ("csharp", "python")
# Sıra aynı zamanda algılama eşitlik önceliğidir (011 §2.4): ts > java > csharp > python >
# kotlin > swift (014). Geçerli çiftler `CATILAR`'dadır (aşağıda).
DILLER: tuple[str, ...] = ("ts", "java", "csharp", "python", "kotlin", "swift")
DIL_ETIKETI: dict[str, str] = {
    "ts": "TypeScript",
    "java": "Java",
    "csharp": "C#",
    "python": "Python",
    "kotlin": "Kotlin",
    "swift": "Swift",
}
_WEB_CATISI: dict[str, str] = {
    "ts": "Playwright Test",
    "java": "Playwright for Java + TestNG",
    "csharp": "Playwright .NET + NUnit",
    "python": "pytest-playwright",
}
UYGULAMA_CATISI = "Appium + TestNG"
# Java test dosyası kalıbı (K-T7, tek kaynak: `dil_algila` ve `ci/dil` kullanır). Tam hat sayımı
# bu sonekleri sayar; algılama ayrıca Kotlin testlerini (`*Test.kt`) Java sinyali sayar. Tarayıcısız
# birim testleri (`birim/`) ve aracın ürettikleri (`uretilen/`) elle yazılmış test sayılmaz.
JAVA_TEST_SONEKLERI: tuple[str, ...] = ("Test.java", "Testi.java", "Tests.java", "IT.java")
KOTLIN_TEST_SONEKLERI: tuple[str, ...] = ("Test.kt",)
JAVA_HARIC_DIZINLER: tuple[str, ...] = ("birim", "uretilen")
# Onarım kapsamının (`/check` `test_files`) Java test dosyası sonekleri: toolchain
# `worker/java.py` `JAVA_TEST_FILE_RE` yalnız bunları kabul eder. Gerekçeli alt küme (MİM-B4):
# onarım yalnız aracın kendi projelerinde (e2e-app, e2e-java) çalışır; bu projelerin konvansiyonu
# `<Ad>Test.java` (üretilen) ve `<Ad>Testi.java` (elle yazılmış referans testler). `Tests.java` /
# `IT.java` yabancı repolardaki elle yazılmış testleri ALGILAMAK içindir (K-T7). Eşitlik:
# `toolchain/tests/data/core_sozlesme.json` (core ve toolchain testleri aynı dosyayı okur).
JAVA_KAPSAM_SONEKLERI: tuple[str, ...] = ("Test.java", "Testi.java")
# TS page object adı Java'da ayrılmış sözcük (ya da geçersiz) ise Java page object'teki karşılığı.
# `goto` Java'da ayrılmış sözcüktür: e2e-java `LoginPage.goTo()` (011 §2.5 eşitliğinin tek
# istisnası).
JAVA_AD_ESLEME: dict[str, str] = {"goto": "goTo"}


def gecerli(platform: str | None) -> str:
    """Boş → `web`; bilinmeyen değer `ValueError` (Türkçe)."""
    deger = (platform or WEB).strip().lower()
    if deger not in PLATFORMLAR:
        raise ValueError(f"platform yalnızca {', '.join(PLATFORMLAR)} olabilir: {platform!r}")
    return deger


def uygulama_mi(platform: str | None) -> bool:
    """Appium/Java hattı mı? (`android` | `ios` | `windows`)"""
    return (platform or WEB) in UYGULAMA_PLATFORMLARI


def varsayilan_dil(platform: str | None) -> str:
    """Algılama/seçim yokken (ve eski kayıtlarda) dil: web → `ts`, uygulama → `java`."""
    return JAVA if uygulama_mi(platform) else TS


def gecerli_cift(platform: str | None, dil: str | None) -> bool:
    """(platform, dil) matriste mi (`CATILAR`, 014 plan.md §1)? Seçilebilirlik ayrıca değerlendirme
    kapısına (`cift_durumu`) ve dil eklentisine bağlıdır."""
    return ((platform or WEB), dil) in CATILAR


def platform_dilleri(platform: str | None) -> tuple[str, ...]:
    """Platformun geçerli dilleri (seçici sırası)."""
    return tuple(d for d in DILLER if gecerli_cift(platform, d))


def gecerli_dil(platform: str | None, dil: str | None) -> str:
    """Boş → platformun varsayılanı; bilinmeyen dil ya da geçersiz çift `ValueError` (Türkçe)."""
    if dil is None or not str(dil).strip():
        return varsayilan_dil(platform)
    deger = str(dil).strip().lower()
    if deger not in DILLER:
        raise ValueError(f"dil yalnızca {', '.join(DILLER)} olabilir: {dil!r}")
    if not gecerli_cift(platform, deger):
        raise ValueError(
            f"{platform or WEB} platformunda {DIL_ETIKETI[deger]} ile kod üretilemez; "
            f"geçerli dil: {', '.join(platform_dilleri(platform))}"
        )
    return deger


def java_mi(dil: str | None) -> bool:
    """Kod/derleme/yama sorusu: üretilen kod Java mı? (Platform sorusu değildir: web + Java da
    Java'dır; araç/ortam için `uygulama_mi(platform)` kullanılır.)"""
    return dil == JAVA


def tam_hat_mi(dil: str | None, platform: str | None = None) -> bool:
    """Tam hat mı (TP derler, korur, koşar, kırarak doğrular)? `platform` verilirse çiftin hattı
    (`CATILAR`); verilmezse 011 anlamı (yalnız `ts` / `java`)."""
    if platform is not None:
        return etkin_hat(platform, dil) == "tam"
    return dil in TAM_HAT_DILLERI


def dogrulanmamis_mi(dil: str | None, platform: str | None = None) -> bool:
    """Doğrulanmamış (011) çıktı mı? `platform` verilirse çiftin etkin hattı (`etkin_hat`);
    verilmezse 011 anlamı (`csharp` | `python`; geçmiş kayıtlar)."""
    if platform is not None:
        return etkin_hat(platform, dil) == "dogrulanmamis"
    return dil in DOGRULANMAMIS_DILLER


def cati(platform: str | None, dil: str | None) -> str:
    """Test çatısının görünen adı (`GET /code/languages` `cati`; `CATILAR` etiketi)."""
    c = cati_bul(platform, dil)
    if c is not None:
        return c.etiket
    if uygulama_mi(platform):
        return UYGULAMA_CATISI
    return _WEB_CATISI.get(dil or "", "")


def java_metot_adi(ad: str) -> str:
    """TS page object metot adının Java page object'teki adı (`goto` → `goTo`; diğerleri aynı)."""
    return JAVA_AD_ESLEME.get(ad, ad)


def java_eslemesi(output: Any) -> Any:
    """Web + Java: ajan eşlemesindeki (`step_mapping`, `expects`) TS metot adlarını Java adlarına
    çevirir (REPLAY golden'ları ve web ajanı TS adlarıyla yazar). Girdi değiştirilmez; sözlük
    değilse aynen döner."""
    if not isinstance(output, dict):
        return output
    out = dict(output)
    for alan in ("step_mapping", "expects"):
        liste = output.get(alan)
        if not isinstance(liste, list):
            continue
        out[alan] = [
            {**m, "method": java_metot_adi(m["method"])}
            if isinstance(m, dict) and isinstance(m.get("method"), str)
            else m
            for m in liste
        ]
    return out


YEREL_CHECK = "local-ci"
WEB_JAVA_CHECK_EKI = "web-java"


def check_adi(platform: str | None, dil: str | None = None) -> str:
    """Yerel CI check adı (K-T1, tek kaynak): web + ts `local-ci` (değişmez); web + Java
    `local-ci-web-java` (GitHub karşılığı `web-java`); uygulama `local-ci-<platform>` (değişmez,
    dil her zaman Java). Doğrulanmamış diller CI'a girmez; verilirse web `local-ci` döner."""
    if dil not in (None, "", TS, JAVA) and ((platform or WEB), dil) in CATILAR:
        # 014: yeni çiftler `local-ci-<platform>-<dil>` (plan.md §1).
        return f"{YEREL_CHECK}-{platform or WEB}-{dil}"
    if uygulama_mi(platform):
        return f"{YEREL_CHECK}-{platform}"
    if java_mi(dil):
        return f"{YEREL_CHECK}-{WEB_JAVA_CHECK_EKI}"
    return YEREL_CHECK


def java_test_dosyasi_mi(
    yol: str, *, kotlin: bool = False, haric: tuple[str, ...] = JAVA_HARIC_DIZINLER
) -> bool:
    """Forge yolu elle yazılmış bir Java testi mi (K-T7)? Ad `JAVA_TEST_SONEKLERI`'nden biriyle
    biter (`kotlin=True` → `*Test.kt` de) ve `haric` dizinlerinin (varsayılan `birim/`,
    `uretilen/`) altında değildir. Paket koşusu üretilenleri de koşacaksa `haric=("birim",)`."""
    sonekler = (*JAVA_TEST_SONEKLERI, *KOTLIN_TEST_SONEKLERI) if kotlin else JAVA_TEST_SONEKLERI
    if not yol.endswith(sonekler):
        return False
    parcalar = yol.split("/")[:-1]
    return not any(h in parcalar for h in haric)


def dil(platform: str | None, dil: str | None = None) -> str:
    """Kaydın etkin dili: `dil` bilinen bir dilse (`DILLER`: tam hat ya da doğrulanmamış) odur;
    boş ya da bilinmeyen değerde platformun varsayılanı (web → `ts`, uygulama → `java`; 0021
    öncesi kayıtlar). Geçerli çift denetimi yapmaz (`gecerli_dil` yapar). toolchain-worker `lang`
    değeri yalnız tam hat dilleri için bunun sonucudur; doğrulanmamış diller toolchain'e gitmez."""
    return dil if dil in DILLER else varsayilan_dil(platform)


def java_kapsam_dosyasi_mi(yol: str) -> bool:
    """Onarım kapsamına (`/check` `test_files`) girebilen Java testi mi? (`JAVA_KAPSAM_SONEKLERI`;
    tarayıcısız birim testleri `birim/` hariç, üretilenler dahil.)"""
    return yol.endswith(JAVA_KAPSAM_SONEKLERI) and "birim" not in yol.split("/")[:-1]


def _kok(yol: str) -> str:
    return f"{yol.rstrip('/')}/"


class E2eKokleri(NamedTuple):
    """Forge deposundaki test kökleri (sonu `/`). Tek liste (MİM-O1): CI'ın script'siz PR dil
    seçimi (`ci/service._web_dilleri`) ve LocalForge merge kapısı (`forge.local_required_checks`)
    aynı kökleri `e2e_kokleri(<app root>)` ile kurar; bunların DIŞINDA bir değişiklik uygulama
    kodudur (K-T11)."""

    e2e: str
    e2e_java: str
    e2e_app: str

    @property
    def hepsi(self) -> tuple[str, ...]:
        return (self.e2e, self.e2e_java, self.e2e_app)

    def degisen_web_dilleri(
        self, degisen: Sequence[str], repodaki: Sequence[str] = ("ts",)
    ) -> tuple[str, ...]:
        """`degisen_web_dilleri` bu köklerle (diğer test kökü: `e2e_app`)."""
        return degisen_web_dilleri(
            degisen,
            e2e=self.e2e,
            e2e_java=self.e2e_java,
            repodaki=repodaki,
            diger_test_kokleri=(self.e2e_app,),
        )


def e2e_kokleri(kok: str = "") -> E2eKokleri:
    """`kok` (uygulama kökü; LocalForge '' , GitHub `demo-app`) altındaki test kökleri."""
    on = f"{kok.strip('/')}/" if kok.strip("/") else ""
    return E2eKokleri(
        e2e=f"{on}{E2E_DIZINI}/",
        e2e_java=f"{on}{E2E_JAVA_DIZINI}/",
        e2e_app=f"{on}{E2E_APP_DIZINI}/",
    )


def repodaki_web_dilleri(
    list_files: Callable[[str, str], list[str]],
    ref: str,
    *,
    e2e: str,
    e2e_java: str,
    okunamazsa: Sequence[str] = ("ts",),
) -> tuple[str, ...]:
    """`ref`'te web testi bulunan tam hat dilleri (sıra `ts`, `java`).

    Saf sayım (model yok): ts → `<e2e>/tests/**/*.spec.ts`; java →
    `<e2e-java>/src/test/java/**` + `java_test_dosyasi_mi` (`birim/` hariç, `uretilen/` dahil:
    paket koşusu üretilenleri de koşar). Hiçbiri yoksa ya da forge okunamazsa `("ts",)`: bugünkü
    davranış (koşu engellenmez). LocalForge merge kapısı ve CI aynı fonksiyonu kullanır; kapı
    okuma hatasında kapalı tarafa düşer (`okunamazsa=TAM_HAT_DILLERI`: her iki dilin check'i
    zorunlu), CI varsayılanla (`("ts",)`) koşar.
    """
    out: list[str] = []
    try:
        if any(y.endswith(".spec.ts") for y in list_files(f"{_kok(e2e)}tests/", ref)):
            out.append(TS)
        if any(
            java_test_dosyasi_mi(y, haric=("birim",))
            for y in list_files(f"{_kok(e2e_java)}src/test/java/", ref)
        ):
            out.append(JAVA)
    except Exception:
        return tuple(okunamazsa)
    return tuple(out) or (TS,)


def degisen_web_dilleri(
    degisen: Sequence[str],
    *,
    e2e: str,
    e2e_java: str,
    repodaki: Sequence[str] = (TS,),
    diger_test_kokleri: Sequence[str] = (),
) -> tuple[str, ...]:
    """Script'siz PR'ın koşturacağı web dilleri (K-T1 + K-T11; sıra `ts`, `java`).

    - `<e2e>/` değiştiyse `ts`, `<e2e-java>/` değiştiyse `java`.
    - Test köklerinin (`e2e`, `e2e_java`, `diger_test_kokleri` — ör. `e2e-app/`) **dışında** bir
      değişiklik (uygulama kodu vb.) varsa `repodaki` dillerin tümü (K-T11): uygulama değişikliği
      her iki dilin testini de kırabilir.
    - Hiçbiri değişmediyse (boş fark ya da yalnız başka test kökü) `("ts",)`: yapılandırılmış
      `local-ci` kapısı.
    """
    ts_kok, java_kok = _kok(e2e), _kok(e2e_java)
    test_kokleri = (ts_kok, java_kok, *(_kok(k) for k in diger_test_kokleri))
    secilen: set[str] = set()
    if any(y.startswith(ts_kok) for y in degisen):
        secilen.add(TS)
    if any(y.startswith(java_kok) for y in degisen):
        secilen.add(JAVA)
    if any(not y.startswith(test_kokleri) for y in degisen):
        secilen.update(d for d in repodaki if d in TAM_HAT_DILLERI)
    return tuple(d for d in TAM_HAT_DILLERI if d in secilen) or (TS,)


# ===================================================== 014 test dilleri: (platform, dil) matrisi
# Sözleşme: specs/014-test-dilleri/plan.md §1. `CATILAR` tek kaynaktır; yeni dil yeni satır +
# eklenti modülüdür (`codegen/diller/<dil>.py`). Eski yardımcılar (yukarıda) ts/java
# davranışını korur.

Hat = Literal["tam", "musteri_ci", "dogrulanmamis"]
HATLAR: tuple[str, ...] = ("tam", "musteri_ci", "dogrulanmamis")
Sonuc = Literal["junit", "playwright-json", "surefire"]
Ajan = Literal["verify_and_map", "verify_and_map_app"]
TUM_DILLER: tuple[str, ...] = ("ts", "java", "csharp", "python", "kotlin", "swift")
TUM_DIL_ETIKETI: dict[str, str] = DIL_ETIKETI
# Değerlendirme kapısı (Ş8 `rules/diller.yaml`) yoksa açık sayılan çiftler (011 öncesi hat,
# "devralındı").
DEVRALINAN_CIFTLER: frozenset[tuple[str, str]] = frozenset(
    {("web", "ts"), ("web", "java"), ("android", "java"), ("ios", "java"), ("windows", "java")}
)
DIL_DURUM_DOSYASI = "diller.yaml"
YAKINDA_NEDENI = "Değerlendirme sürüyor"  # Ş8 dil_kapisi.YAKINDA_NEDENI ile aynı


@dataclass(frozen=True)
class Cati:
    """Bir (platform, dil) çiftinin test çatısı (plan.md §1)."""

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

    @property
    def anahtar(self) -> str:
        """`rules/diller.yaml` anahtarı (`web/python`)."""
        return f"{self.platform}/{self.dil}"

    @property
    def check(self) -> str:
        return check_adi_genel(self.platform, self.dil)


def _uygulama_catisi(
    p: str, dil: str, hat: str, etiket: str, sablon: str, kok_ayari: str, kok: str, alt: str,
    sonuc: str, is_akisi: str | None,
) -> Cati:  # fmt: skip
    return Cati(p, dil, hat, etiket, sablon, kok_ayari, kok, alt, sonuc, "verify_and_map_app",
                is_akisi)  # fmt: skip


_UYGULAMA_IS_AKISI = {"android": "mobil-android", "ios": "mobil-ios", "windows": "masaustu-windows"}

CATILAR: dict[tuple[str, str], Cati] = {
    ("web", "ts"): Cati(
        "web",
        "ts",
        "tam",
        "Playwright Test",
        "playwright_test.ts.j2",
        "TP_E2E_ROOT",
        E2E_DIZINI,
        "tests/generated",
        "playwright-json",
        "verify_and_map",
        "ci",
    ),
    ("web", "java"): Cati(
        "web",
        "java",
        "tam",
        "Playwright for Java + TestNG",
        "playwright_testng.java.j2",
        "TP_E2E_JAVA_ROOT",
        E2E_JAVA_DIZINI,
        JAVA_URETILEN_DIZIN,
        "surefire",
        "verify_and_map",
        "web-java",
    ),
    ("web", "python"): Cati(
        "web",
        "python",
        "tam",
        "pytest + Playwright",
        "playwright_pytest.py.j2",
        "TP_E2E_PYTHON_ROOT",
        "e2e-python",
        "tests/generated",
        "junit",
        "verify_and_map",
        "web-python",
    ),
    ("web", "csharp"): Cati(
        "web",
        "csharp",
        "tam",
        "Playwright .NET + NUnit",
        "playwright_nunit.cs.j2",
        "TP_E2E_CSHARP_ROOT",
        "e2e-csharp",
        "Tests/Generated",
        "junit",
        "verify_and_map",
        "web-csharp",
    ),
    **{
        (p, "java"): _uygulama_catisi(
            p,
            "java",
            "tam",
            UYGULAMA_CATISI,
            "appium_testng.java.j2",
            "TP_E2E_APP_ROOT",
            E2E_APP_DIZINI,
            JAVA_URETILEN_DIZIN,
            "surefire",
            _UYGULAMA_IS_AKISI[p],
        )
        for p in UYGULAMA_PLATFORMLARI
    },
    **{
        (p, "python"): _uygulama_catisi(
            p,
            "python",
            "tam",
            "pytest + Appium",
            "appium_pytest.py.j2",
            "TP_E2E_APP_PYTHON_ROOT",
            "e2e-app-python",
            "tests/generated",
            "junit",
            f"{_UYGULAMA_IS_AKISI[p]}-python",
        )
        for p in UYGULAMA_PLATFORMLARI
    },
    ("windows", "csharp"): _uygulama_catisi(
        "windows",
        "csharp",
        "tam",
        "Appium .NET + NUnit (NovaWindows)",
        "appium_nunit.cs.j2",
        "TP_E2E_APP_CSHARP_ROOT",
        "e2e-app-csharp",
        "Tests/Generated",
        "junit",
        "masaustu-windows-csharp",
    ),
    ("android", "kotlin"): _uygulama_catisi(
        "android",
        "kotlin",
        "musteri_ci",
        "Espresso (AndroidX Test, JUnit4)",
        "espresso_junit.kt.j2",
        "TP_ANDROID_KOTLIN_ROOT",
        "app/src/androidTest/java",
        # Demo kütüphane paketi yolu; gerçek yol sembol tablosunun `paket` alanından (Ş3).
        "com/antreklabs/bayisiparis/tp/uretilen",
        "junit",
        "mobil-android-kotlin",
    ),
    ("ios", "swift"): _uygulama_catisi(
        "ios",
        "swift",
        "musteri_ci",
        "XCUITest",
        "xcuitest.swift.j2",
        "TP_IOS_SWIFT_ROOT",
        "UITests",
        "TPUretilen",
        "junit",
        "mobil-ios-swift",
    ),
}

# Platform başına dil listesi env'i (proje ayarı; boş = platformun varsayılan dili).
DIL_LISTESI_AYARI: dict[str, str] = {
    "web": "TP_WEB_DILLERI",
    "android": "TP_DILLERI_ANDROID",
    "ios": "TP_DILLERI_IOS",
    "windows": "TP_DILLERI_WINDOWS",
}


def cati_bul(platform: str | None, dil: str | None) -> Cati | None:
    return CATILAR.get((platform or WEB, dil or ""))


def hat(platform: str | None, dil: str | None) -> str | None:
    c = cati_bul(platform, dil)
    return c.hat if c else None


def musteri_ci_mi(platform: str | None, dil: str | None) -> bool:
    return hat(platform, dil) == "musteri_ci"


def check_adi_genel(platform: str | None, dil: str | None) -> str:
    """Genel yerel CI check adı (plan.md §1): ts/java için `check_adi` (değişmez), diğer çiftlerde
    `local-ci-<platform>-<dil>`."""
    return check_adi(platform or WEB, dil)


def gh_check_adi(platform: str | None, dil: str | None) -> str | None:
    """GitHub kipinde çiftin iş akışı check adı (`web-python`, `mobil-android-kotlin`)."""
    c = cati_bul(platform, dil)
    return c.gh_is_akisi if c else None


def kok_ayari_platform(kok_ayari: str, platform: str | None) -> str | None:
    """Ayrı platform deposu kaplaması: `<kok_ayari>_<P>` (web için yok)."""
    if not platform or platform == WEB:
        return None
    return f"{kok_ayari}_{platform.upper()}"


def _durum_dosyasi(rules_dir: Any = None) -> Any:
    from pathlib import Path

    if rules_dir is not None:
        return Path(rules_dir) / DIL_DURUM_DOSYASI
    from tp_core.gateway.config import find_rules_dir

    return find_rules_dir() / DIL_DURUM_DOSYASI


def dil_durumlari(rules_dir: Any = None) -> dict[str, str]:
    """`rules/diller.yaml` (Ş8) `ciftler` → {"web/ts": "acik", ...}. Dosya yoksa ya da okunamazsa
    devralınan çiftler `acik`, diğerleri `yakinda` (güvenli taraf: yeni dil kapalı)."""
    out = {
        c.anahtar: ("acik" if k in DEVRALINAN_CIFTLER else "yakinda") for k, c in CATILAR.items()
    }
    try:
        import yaml

        veri = yaml.safe_load(_durum_dosyasi(rules_dir).read_text(encoding="utf-8")) or {}
        ciftler = veri.get("ciftler") or {}
    except Exception:
        return out
    if not isinstance(ciftler, dict):
        return out
    for anahtar, kayit in ciftler.items():
        if anahtar not in out:
            continue
        durum = kayit.get("durum") if isinstance(kayit, dict) else kayit
        if durum in ("acik", "yakinda"):
            out[anahtar] = durum
    return out


def cift_durumu(platform: str | None, dil: str | None, rules_dir: Any = None) -> str:
    """`acik` | `yakinda` (matriste olmayan çift `yakinda`). Tek kaynak Ş8 kapısıdır
    (`tp_core.gateway.dil_kapisi.kullanilabilir_mi`: kayıt yok / dosya bozuk → kapalı); modül
    yoksa (Ş8 birleşmeden) `dil_durumlari` yedeği."""
    c = cati_bul(platform, dil)
    if c is None:
        return "yakinda"
    try:
        from tp_core.gateway import dil_kapisi  # type: ignore[attr-defined]
    except ImportError:
        return dil_durumlari(rules_dir).get(c.anahtar, "yakinda")
    from pathlib import Path

    from tp_core.gateway.config import find_rules_dir

    kok = Path(rules_dir) if rules_dir is not None else find_rules_dir()
    return "acik" if dil_kapisi.kullanilabilir_mi(kok, c.platform, c.dil) else "yakinda"


def etkin_hat(platform: str | None, dil: str | None) -> str | None:
    """Çiftin bugünkü hattı: `CATILAR` hattı; web C#/Python'un çekirdek dil eklentisi henüz
    yoksa (Ş1/Ş2 birleşmeden) 011 `dogrulanmamis` yolu (yeni üretim kapıyla zaten kapalı)."""
    c = cati_bul(platform, dil)
    if c is None:
        return None
    if c.platform == WEB and c.dil in DOGRULANMAMIS_DILLER:
        from tp_core.features.codegen import diller

        if diller.eklenti(c.dil) is None:
            return "dogrulanmamis"
    return c.hat


def repoya_yazar_mi(dil: str | None, platform: str | None) -> bool:
    """Üretim forge'a commit + PR açar mı (`tam` ya da `musteri_ci`)?"""
    return etkin_hat(platform, dil) in ("tam", "musteri_ci")


def kirarak_dogrulama_var_mi(platform: str | None, dil: str | None) -> bool:
    """Kırarak doğrulama yalnız tam hatta (müşteri CI: "kırarak doğrulanmadı" rozeti)."""
    return etkin_hat(platform, dil) == "tam"
