"""Kotlin / Espresso triage eklentisi (TASARIM test-dilleri §3.3; şerit Ş3). AI yok.

Müşteri CI hattında (musteri_ci) sonuç `tp-results` artefaktından gelir: JUnit XML
(`testcase@classname` paketli Kotlin sınıfı, `@name` metot), ekler (`kanit/<Sınıf>.<metot>/
{ekran.png, sayfa-kaynagi.xml}`) ve derleme günlüğü. Ekran nesnesi kütüphanesi
(`demo-app/mobile/android-test/…/ekranlar/Ekran.kt`) Java kütüphanesiyle aynı hata metinlerini
üretir; bu yüzden beklenen/görülen ve kimlik zinciri ayrıştırması Java'yla ortaktır
(`codegen.classify.java_beklenen_gorulen`, `triage.java._KIMLIK_RE`).

Hata türleri (Ş0 sözleşmesi §2.1): `locator` | `assertion` | `navigation` | `environment` |
`timeout` | `derleme` | None.

- **derleme**: JUnit yok ve Kotlin derleyici satırı (`e: file:///…/X.kt:12:5 Unresolved reference
  …`) ya da Gradle `Compilation error` / `FAILURE: Build failed` (musteri_ci: derleme TP'de değil
  müşterinin CI'ında; R6). Sınıflandırma `test_maintenance`.
- **environment**: Espresso/enstrümantasyon altyapısı (`Instrumentation run failed`, `Process
  crashed`, `No connected devices`, `INSTALL_FAILED`, `AppNotIdleException`, bağlantı reddi).
- **assertion**: `AssertionError` (kütüphanenin `Bekle.dogrula`'sı) ya da JUnit/Espresso
  karşılaştırma hataları (`AssertionFailedError`, `ComparisonFailure`; demo API `/test/` kurulum
  hatası → environment).
- **locator**: `NoMatchingViewException`, `AmbiguousViewMatcherException`, kütüphanenin
  `TimeoutException` (öğe görünmedi / tıklanabilir olmadı: kimlik '…'), `PerformException`.
"""

from __future__ import annotations

import re
from typing import Any

from tp_core.features.codegen.classify import java_beklenen_gorulen

AD = "kotlin"

_DERLEME_SATIRI = re.compile(
    r"^e: (?:file://)?(?P<dosya>[^\s:]+\.kts?):(?P<satir>\d+):(?P<sutun>\d+) (?P<mesaj>.+)$", re.M
)
_DERLEME = re.compile(
    r"Compilation error|Compilation failed"
    r"|compileReleaseAndroidTestKotlin|compileDebugAndroidTestKotlin"
    r"|Execution failed for task ':[^']*AndroidTestKotlin'",
)
_ORTAM = re.compile(
    r"Instrumentation run failed|Process crashed|No connected devices|INSTALL_FAILED"
    r"|ShellCommandUnresponsiveException|AppNotIdleException|RootViewWithoutFocusException"
    r"|java\.net\.(?:Connect|NoRouteToHost|UnknownHost|SocketTimeout)Exception"
    r"|Connection refused|DeviceNotFound",
    re.I,
)
_KURULUM = re.compile(
    r"/test/|tpTestToken|DEMOAPP_TEST_TOKEN|sepet temizliği|giriş başarısız", re.I
)
_ASSERTION = re.compile(
    r"(?:java\.lang\.|kotlin\.)?AssertionError\b|junit\.framework\.AssertionFailedError"
    r"|org\.junit\.ComparisonFailure|AssertionFailedError"
)
_LOCATOR = re.compile(
    r"NoMatchingViewException|AmbiguousViewMatcherException|NoMatchingRootException"
    r"|(?:java\.util\.concurrent\.)?TimeoutException|PerformException"
)
_ZAMAN_ASIMI = re.compile(r"Test timed out|TestTimedOutException|shardTimeout", re.I)
# `<Story>AndroidC<sıra>_<uuid8>Test` (üretilen sınıf adı; Java ile aynı kural).
_URETILEN_SINIF = re.compile(
    r"(?:^|[./])[A-Za-z][A-Za-z0-9]*C[0-9]+_(?P<u8>[0-9a-f]{8})Test(?:\.kt)?\b"
)


def derleme_hatalari(log: str | None, *, en_cok: int = 50) -> list[dict[str, Any]]:
    """Kotlin derleyici satırları → [{dosya, satir, sutun, mesaj}] (dosya yolu göreli kalır)."""
    out: list[dict[str, Any]] = []
    for m in _DERLEME_SATIRI.finditer(log or ""):
        dosya = m.group("dosya")
        # Mutlak yol yalnız proje içi kısma indirgenir (runner ev dizini sızmaz).
        for isaret in ("/src/androidTest/java/", "/android-test/java/"):
            if isaret in dosya:
                dosya = dosya.split(isaret, 1)[1]
                break
        else:
            dosya = dosya.rsplit("/", 1)[-1]
        out.append(
            {
                "dosya": dosya,
                "satir": int(m.group("satir")),
                "sutun": int(m.group("sutun")),
                "mesaj": m.group("mesaj").strip()[:500],
            }
        )
        if len(out) >= en_cok:
            break
    return out


def hata_turu(mesaj: str | None, istisna: str | None = None) -> str | None:
    """Espresso / Kotlin hata metninin türü (Ş0 §2.1); tanınmazsa None (ortak kurallara düşer).

    Sıra: derleme → ortam → zaman aşımı → assertion (kurulum kaynaklıysa ortam) → locator.
    Assertion locator'dan önce gelir: `Bekle.dogrula` zaman aşımını AssertionError'a çevirir."""
    m = mesaj or ""
    ilk = f"{istisna or ''} {m.lstrip().splitlines()[0] if m.strip() else ''}"
    if _DERLEME_SATIRI.search(m) or _DERLEME.search(m):
        return "derleme"
    if _ORTAM.search(ilk) or _ORTAM.search(m[:2000]):
        return "environment"
    if _ZAMAN_ASIMI.search(ilk):
        return "timeout"
    if _ASSERTION.search(ilk) or java_beklenen_gorulen(m) != (None, None):
        return "environment" if _KURULUM.search(m) else "assertion"
    if _LOCATOR.search(ilk) or _LOCATOR.search(m):
        return "locator"
    return None


def beklenen_gorulen(mesaj: str | None) -> tuple[str | None, str | None]:
    """`Bekle.dogrula` metni (Java ile aynı: `beklenen <X>, görülen <Y> (N ms)`); JUnit
    `expected:<X> but was:<Y>` biçimi de okunur."""
    exp, rec = java_beklenen_gorulen(mesaj)
    if exp is not None or rec is not None:
        return exp, rec
    m = re.search(r"expected:<(?P<exp>.*?)> but was:<(?P<rec>.*?)>", mesaj or "", re.S)
    return (m.group("exp"), m.group("rec")) if m else (None, None)


def test_kimligi(test_adi: str | None, dosya: str | None) -> str | None:
    """Script eşleme anahtarı: üretilen sınıf adındaki case uuid'sinin ilk 8 hanesi (`u8`).

    Kaynak: dosya (`…/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt` ya da paketli sınıf adı) ya da
    test adı (`TPD1AndroidC2_3f9b1c2eTest › senaryo`)."""
    for aday in (dosya, test_adi):
        m = _URETILEN_SINIF.search(aday or "")
        if m is not None:
            return m.group("u8")
    return None


def test_dosyasi_mi(dosya: str | None) -> bool:
    """Sinyal bir Kotlin testine mi ait (`.kt` yolu)?"""
    return bool(dosya) and str(dosya).strip().endswith(".kt")


class _KotlinTriage:
    """`TriageEklentisi` protokolü (specs/014-test-dilleri/plan.md §2.1)."""

    ad = AD

    def hata_turu(self, mesaj: str, istisna: str | None = None) -> str | None:
        return hata_turu(mesaj, istisna)

    def beklenen_gorulen(self, mesaj: str | None) -> tuple[str | None, str | None]:
        return beklenen_gorulen(mesaj)

    def test_kimligi(self, test_adi: str, dosya: str | None) -> str | None:
        return test_kimligi(test_adi, dosya)

    def test_dosyasi_mi(self, dosya: str | None) -> bool:
        return test_dosyasi_mi(dosya)


EKLENTI = _KotlinTriage()
