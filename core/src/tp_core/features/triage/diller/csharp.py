"""C# (NUnit) triage eklentisi (014 Ş2): hata kalıpları, kimlik eşleme, kanıt yolu. AI yok.

İki hat:

- **web** (`e2e-csharp`, Playwright .NET): hata metni Playwright sürücüsünün metnidir (Java ile
  aynı İngilizce iletiler: "Locator expected to have text …", "Timeout 5000ms exceeded.", "waiting
  for GetByTestId(\"x\")"). Page object beklentileri `NUnit.Framework.AssertionException`'a
  çevrilir (`Ekran.DogrulaAsync`); eylem zaman aşımı `System.TimeoutException`'dır. Kanıt
  `<kanit>/<Sınıf>.<Metot>/{ekran.png, trace.zip, sayfa.html}` (web + Java ile aynı adlar):
  `triage.java_web.kanit_oku` aynen kullanılır.
- **windows** (`e2e-app-csharp`, Appium .NET): ileti biçimleri Java `Bekle` ile birebirdir
  ("…: beklenen <x>, görülen <y> (N ms)", "öğe görünmedi: kimlik 'x'"); kanıt
  `{ekran.png, sayfa-kaynagi.xml}`: `triage.java` yardımcıları aynen kullanılır.

JUnit (JunitXml.TestLogger) `failure@type` hep `failure`dır; tür iletinin önekindedir
(`"<Tam.Tür> : ileti"`, kurulumda `"SetUp : <Tür> : ileti"`; NUnit assertion iletisi öneksiz).
Test-runner (`runner/diller/csharp_run.py`) raporu normalleştirir; çekirdek ayrıca ham GitHub
artefaktını okuyabilsin diye aynı ayrıştırma burada da vardır (`istisna_ve_ileti`).

Kimlik: JUnit `classname` = `Antreklabs.Bayi.Tests.Generated.<Sınıf>`, `name` = `Senaryo` →
dosya `Tests/Generated/<Sınıf>.cs`, ad `<Sınıf> › Senaryo` (test-runner özetiyle aynı).
"""

from __future__ import annotations

import re
from typing import Any

from tp_core.features.triage import java as jv
from tp_core.features.triage import java_web as jw

DIL = "csharp"
NAMESPACE_ONEKI = "Antreklabs.Bayi."
ASSERTION = "NUnit.Framework.AssertionException"
KANIT_EKRAN = jv.KANIT_EKRAN
KANIT_DOM = jw.KANIT_DOM
KANIT_TRACE = jw.KANIT_TRACE
KANIT_KAYNAK = jv.KANIT_KAYNAK
# Koşu dizini içinde kanıt kökünün olası yerleri (test-runner C# yolu: `src/<kök>/results/kanit`,
# tekrarlı koşuda `kanit/tekrar-N/`; GitHub artefaktında `results/kanit`).
KANIT_KOKLERI = (
    "results/kanit",
    "kanit",
    "src/e2e-csharp/results/kanit",
    "src/e2e-app-csharp/results/kanit",
    "results/kanit/tekrar-1",
    "kanit/tekrar-1",
)
_ONEK_RE = re.compile(
    r"\A(?P<asama>(?:OneTime)?(?:SetUp|TearDown) : )?"
    r"(?P<tur>[A-Za-z_][\w.`]*(?:Exception|Error)) : "
)
_SINIF_RE = re.compile(r"\A(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*\Z")
_CS_ISTISNA_RE = re.compile(
    r"\b(?:NUnit\.Framework\.|Microsoft\.Playwright\.|OpenQA\.Selenium\.|System\.TimeoutException)"
)
_GETBY_RE = re.compile(r"\bGetBy(TestId|Role|Text|Label|Placeholder|AltText|Title)\(")
_KURULUM_RE = re.compile(r"/test/|giriş başarısız|DEMOAPP_TEST_TOKEN")
_BEKLE_RE = re.compile(r"beklenen <(?P<exp>.*?)>, görülen <(?P<rec>.*?)> \(\d+ ms\)", re.S)


def istisna_ve_ileti(mesaj: str | None) -> tuple[str, str, bool]:
    """JunitXml.TestLogger iletisi → (C# tür adı, öneksiz ileti, kurulum/temizlik aşaması mı).
    Önek yoksa NUnit assertion'ıdır."""
    m = _ONEK_RE.match(mesaj or "")
    if m is None:
        return ASSERTION, mesaj or "", False
    return m.group("tur"), (mesaj or "")[m.end() :], bool(m.group("asama"))


def csharp_mi(dosya: str | None, mesaj: str | None = None, dil: str | None = None) -> bool:
    """Kayıt C# mı? (`dil` biliniyorsa o; yoksa `.cs` dosyası ya da C# istisna adı.)"""
    if dil is not None:
        return dil == DIL
    if (dosya or "").strip().endswith(".cs"):
        return True
    return bool(_CS_ISTISNA_RE.search(mesaj or ""))


def _java_bicimi(metin: str) -> str:
    """Playwright .NET çağrı günlüğü yazımını Java/TS yazımına çevirir (`GetByTestId(` →
    `getByTestId(`): `triage.evidence` / `java_web` kalıpları bunu bekler."""
    return _GETBY_RE.sub(lambda x: f"getBy{x.group(1)}(", metin)


def hata_turu(mesaj: str | None, istisna: str | None = None, platform: str | None = None) -> str:
    """C# hata metni → test-runner `failure.type` sözlüğü (`test_data`, `navigation`,
    `assertion`, `locator_not_found`, `locator_timeout`, `other`).

    `istisna` verilmezse iletinin önekinden çıkarılır. Kural sırası Java ile aynıdır: kurulum →
    (web) Playwright kalıpları → (windows) `Bekle` kalıpları.
    """
    if istisna is None:
        istisna, mesaj, _ = istisna_ve_ileti(mesaj)
    m = _java_bicimi(mesaj or "")
    if _KURULUM_RE.search(m):
        return "test_data"
    if platform != "windows":
        pw_istisna = {
            ASSERTION: "org.opentest4j.AssertionFailedError",
            "System.TimeoutException": "com.microsoft.playwright.TimeoutError",
            "Microsoft.Playwright.PlaywrightException": (
                "com.microsoft.playwright.PlaywrightException"
            ),
        }.get(istisna or "", istisna)
        tur = jw.playwright_java_turu(m, pw_istisna)
        if tur is not None:
            return tur
    if istisna == ASSERTION:
        return "assertion"
    basit = (istisna or "").rsplit(".", 1)[-1]
    if basit == "NoSuchElementException" or (
        basit in ("WebDriverTimeoutException", "TimeoutException") and "öğe görünmedi" in m
    ):
        return "locator_not_found"
    if basit in ("WebDriverTimeoutException", "TimeoutException"):
        return "locator_timeout"
    return "other"


def beklenen_gorulen(mesaj: str | None) -> tuple[str | None, str | None]:
    """Assertion metnindeki (beklenen, görülen): `Bekle` biçimi, yoksa Playwright biçimi."""
    _, govde, _ = istisna_ve_ileti(mesaj)
    b = _BEKLE_RE.search(govde)
    if b is not None:
        return b.group("exp"), b.group("rec")
    return jw.beklenen_gorulen(govde)


def kirik_kimlik(*metinler: Any) -> tuple[str | None, str | None, bool]:
    """(aranan, kapsayıcı, belirsiz): `Ekran` biçimi ("kimlik 'x'") ya da Playwright çağrı
    günlüğündeki testId zinciri (.NET yazımı dahil)."""
    return jw.kirik_kimlik(*(_java_bicimi(m) if isinstance(m, str) else m for m in metinler))


def test_kimligi(classname: str | None, metot: str) -> tuple[str | None, str]:
    """JUnit (`classname`, `name`) → (`Tests/…/<Sınıf>.cs`, `<Sınıf> › <metot>`): test-runner
    C# özetiyle (`csharp_run.cs_dosyasi`) aynı kimlik. Sınıf adı değilse değer değişmez."""
    if not classname or not _SINIF_RE.match(classname):
        return classname, metot
    basit = classname.rsplit(".", 1)[-1]
    ad = metot if metot.startswith(f"{basit} › ") else f"{basit} › {metot}"
    yol = classname.removeprefix(NAMESPACE_ONEKI).replace(".", "/") + ".cs"
    return yol, ad


def sinif_adi(dosya: str | None) -> str | None:
    """`…/Tests/Generated/XTests.cs` ya da `Ns.XTests` → `XTests`."""
    d = (dosya or "").strip().rsplit("/", 1)[-1]
    if d.endswith(".cs"):
        d = d[:-3]
    return d.rsplit(".", 1)[-1] or None


def kanit_dizini_adi(dosya: str | None, test_adi: str) -> str | None:
    """`Kanit` adlandırması (`<Sınıf>.<Metot>`, güvensiz karakter `_`); Java ile aynı kural."""
    sinif = sinif_adi(dosya)
    if not sinif:
        return None
    return jv.kanit_dizini_adi(f"{sinif}.java", test_adi)


def kanit_oku(platform: str | None, *args: Any, **kwargs: Any) -> Any:
    """Web: `java_web.kanit_oku` (DOM + trace + ekran), windows: `java.sayfa_kaynagi_oku`."""
    if platform == "windows":
        return jv.sayfa_kaynagi_oku(*args, **kwargs)
    return jw.kanit_oku(*args, **kwargs)


# ------------------------------------------------------------------- Ş0 eklenti protokolü

_U8_RE = re.compile(r"C[0-9]+_(?P<u8>[0-9a-f]{8})Tests\Z")


def uretilen_kimligi(test_adi: str | None, dosya: str | None) -> str | None:
    """Üretilen testin `<uuid8>`'i (`…C2_3f9b1c2eTests` sınıfından; dosya ya da `classname`);
    üretilen test değilse None."""
    for aday in (sinif_adi(dosya), (test_adi or "").split(" › ", 1)[0].strip()):
        m = _U8_RE.search(aday or "")
        if m is not None:
            return m.group("u8")
    return None


def junit_kimligi(classname: str | None, metot: str) -> tuple[str | None, str]:
    """`ci.parse` dil kimliği kancası (Java `java_test_kimligi` karşılığı)."""
    return test_kimligi(classname, metot)


class _CsharpTriage:
    """plan.md §2.1 `TriageEklentisi` (Ş0 keşfi `EKLENTI`'yi okur; entegrasyon adaptörü)."""

    ad = DIL

    def hata_turu(self, mesaj: str, istisna: str | None = None) -> str | None:
        return hata_turu(mesaj, istisna)

    def beklenen_gorulen(self, mesaj: str | None) -> tuple[str | None, str | None]:
        return beklenen_gorulen(mesaj)

    def test_kimligi(self, test_adi: str, dosya: str | None) -> str | None:
        return uretilen_kimligi(test_adi, dosya)

    def test_dosyasi_mi(self, dosya: str | None) -> bool:
        return (dosya or "").strip().endswith(".cs")


EKLENTI = _CsharpTriage()
