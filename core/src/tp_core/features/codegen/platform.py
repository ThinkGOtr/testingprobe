"""Platform boyutu (009 mobil-masaüstü §2.1): web | android | ios | windows.

Case platformdan bağımsızdır; kod üretimi (case, platform) çiftinedir. `web` mevcut
Playwright/TypeScript hattının aynısıdır (varsayılan, geriye uyum); `android`, `ios`, `windows`
Appium + Java + TestNG hattıdır (`demo-app/e2e-app`, `toolchain/java-araclar`, app-mcp).

**Üretim dili (011 §2.1):** dil ayrı bir boyuttur; platformdan türetilmez. `web` her dille
üretilebilir (`ts` | `java` | `csharp` | `python`), uygulama platformları yalnız `java` ile.
"Platform = dil" çıkarımı yapılmaz; iki ayrı soru vardır:

- **araç/ortam** (ajan aracı, tarayıcı/cihaz, tekrar sayısı, check adı) → platform (`uygulama_mi`);
- **kod/derleme/yama** (sembol tablosu, şablon, literal, derleme adımları) → dil (`java_mi`,
  `tam_hat_mi`).

Tam hat dilleri (`ts`, `java`) derlenir, koşulur ve PR'a girer; doğrulanmamış diller (`csharp`,
`python`) yalnız üretilir (commit/PR/yerel kontrol yok, script durumu `unverified`).

Bu modül saf yardımcıdır (veritabanı/ağ yok): hem core-api hem core-worker kullanır.
"""

from __future__ import annotations

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
DIL_KAYNAKLARI: tuple[str, ...] = ("algilandi", "secildi", "varsayilan")
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


def check_adi(platform: str | None) -> str:
    """Yerel CI check adı platformundur, dile bakmaz (011 §2.6): web `local-ci`, uygulama
    `local-ci-<platform>`."""
    return f"local-ci-{platform}" if uygulama_mi(platform) else "local-ci"


def dil(platform: str | None, dil: str | None = None) -> str:
    """toolchain-worker `lang` karşılığı: script'in dili; verilmemişse platformun varsayılanı
    (web → `ts`, diğerleri → `java`; 009 davranışı, geriye uyum)."""
    return dil if dil in DILLER else varsayilan_dil(platform)
