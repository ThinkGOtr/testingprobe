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
from typing import Any, Literal

Platform = Literal["web", "android", "ios", "windows"]
WEB = "web"
UYGULAMA_PLATFORMLARI: tuple[str, ...] = ("android", "ios", "windows")
PLATFORMLAR: tuple[str, ...] = (WEB, *UYGULAMA_PLATFORMLARI)
# Forge deposunda Java test projesinin kökü (uygulama köküne göre): `<app root>/e2e-app`.
E2E_APP_DIZINI = "e2e-app"
# Web + Java (Playwright for Java + TestNG) test projesinin kökü: `<app root>/e2e-java` (011 §2.5).
E2E_JAVA_DIZINI = "e2e-java"
# e2e-app / e2e-java köküne göre (iki Java projesi aynı paket düzenini kullanır).
JAVA_URETILEN_DIZIN = "src/test/java/com/antreklabs/bayi/uretilen"

Dil = Literal["ts", "java", "csharp", "python"]
TS = "ts"
JAVA = "java"
TAM_HAT_DILLERI: tuple[str, ...] = ("ts", "java")
DOGRULANMAMIS_DILLER: tuple[str, ...] = ("csharp", "python")
# Sıra aynı zamanda algılama eşitlik önceliğidir (011 §2.4): ts > java > csharp > python.
DILLER: tuple[str, ...] = (*TAM_HAT_DILLERI, *DOGRULANMAMIS_DILLER)
DIL_ETIKETI: dict[str, str] = {
    "ts": "TypeScript",
    "java": "Java",
    "csharp": "C#",
    "python": "Python",
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
    """(platform, dil) üretilebilir mi? `web` × her dil; `android|ios|windows` × yalnız `java`."""
    p = platform or WEB
    if p not in PLATFORMLAR or dil not in DILLER:
        return False
    return dil == JAVA if p in UYGULAMA_PLATFORMLARI else True


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


def tam_hat_mi(dil: str | None) -> bool:
    """Dil tam hat mı (derleme + koşu + PR)? `csharp` / `python` doğrulanmamıştır."""
    return dil in TAM_HAT_DILLERI


def dogrulanmamis_mi(dil: str | None) -> bool:
    return dil in DOGRULANMAMIS_DILLER


def cati(platform: str | None, dil: str | None) -> str:
    """Test çatısının görünen adı (`GET /code/languages` `cati`)."""
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


def repodaki_web_dilleri(
    list_files: Callable[[str, str], list[str]], ref: str, *, e2e: str, e2e_java: str
) -> tuple[str, ...]:
    """`ref`'te web testi bulunan tam hat dilleri (sıra `ts`, `java`).

    Saf sayım (model yok): ts → `<e2e>/tests/**/*.spec.ts`; java →
    `<e2e-java>/src/test/java/**` + `java_test_dosyasi_mi` (`birim/` hariç, `uretilen/` dahil:
    paket koşusu üretilenleri de koşar). Hiçbiri yoksa ya da forge okunamazsa `("ts",)`: bugünkü
    davranış (koşu / kapı engellenmez). LocalForge merge kapısı ve CI aynı fonksiyonu kullanır.
    """
    out: list[str] = []
    try:
        if any(y.endswith(".spec.ts") for y in list_files(f"{_kok(e2e)}tests/", ref)):
            out.append(TS)
    except Exception:
        return (TS,)
    try:
        if any(
            java_test_dosyasi_mi(y, haric=("birim",))
            for y in list_files(f"{_kok(e2e_java)}src/test/java/", ref)
        ):
            out.append(JAVA)
    except Exception:
        return tuple(out) or (TS,)
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
