"""Swift / XCUITest triage eklentisi (014 test dilleri, TASARIM §3.4; şerit Ş4). AI yok.

Müşteri CI hattında sonuç `tp-results` artefaktındaki JUnit'tir (xcresult → JUnit, Ş5
`xcresult_junit.py`). JUnit'te `testcase@classname` `<UITestHedefi>.<Sınıf>` (ör.
`BayiSiparisUITests.TPD1IosC2_3f9b1c2eTests`), `@name` `testSenaryo` / `testSenaryo()`'dur; hata
metni XCTest'in başarısızlık iletisidir.

Ekran nesnesi tabanı (`Ekranlar/Ekran.swift`) hata iletilerini iki işaretle başlatır; sınıflandırma
önce bunlara bakar:

- `[TP-BEKLENTI] '<kimlik>' metni: beklenen "…", görülen "…"` → `assertion` (defect adayı;
  görülen `(öğe yok)` ise öğe bulunamamıştır → `locator`).
- `[TP-EYLEM] öğe görünmedi / dokunulabilir olmadı: kimlik '…'` → `locator`;
  `[TP-EYLEM] …tamamlanmadı` (bekleme) → `timeout`.

Diğerleri: uygulama başlatılamadı / çöktü → `environment`; test verisi sıfırlanamadı
(`/test/reset`, `DEMOAPP_TEST_TOKEN`) → `test_data`; derleme hatası (Swift `error:`, `Testing
failed`, `** TEST BUILD FAILED **`) → `derleme` (musteri_ci: JUnit yok, iş adımı kırmızı).
"""

from __future__ import annotations

import re

AD = "swift"
EYLEM = "[TP-EYLEM]"
BEKLENTI = "[TP-BEKLENTI]"
YOK = "(öğe yok)"

_U8_RE = re.compile(r"C[0-9]+_(?P<u8>[0-9a-f]{8})Tests\b")
_BEKLENEN_RE = re.compile(r'beklenen "(?P<b>(?:[^"\\]|\\.)*)", görülen "(?P<g>(?:[^"\\]|\\.)*)"')
# XCTAssertEqual biçimi: XCTAssertEqual failed: ("a") is not equal to ("b")
_XCT_ESIT_RE = re.compile(
    r'XCTAssertEqual failed: \("(?P<g>.*?)"\) is not equal to \("(?P<b>.*?)"\)'
)
_DERLEME_RE = re.compile(
    r"\*\* (?:TEST )?BUILD FAILED \*\*|Testing failed:|\.swift:\d+:\d+: error:|"
    r"Compiling .* failed|The following build commands failed|xcodebuild: error:",
)
_ORTAM_RE = re.compile(
    r"Failed to launch|Application .* is not running|Failed to terminate|"
    r"Lost connection to the test manager|Test runner exited|crashed|"
    r"Unable to boot|simulator.*(?:failed|timed out)|Early unexpected exit",
    re.IGNORECASE,
)
_TEST_VERISI_RE = re.compile(r"/test/reset|DEMOAPP_TEST_TOKEN|test verisi sıfırlanamaz")
_KIMLIKSIZ_ZAMAN_RE = re.compile(r"tamamlanmadı|okunamadı|kalkmadı|zaman aşımı|timed out", re.I)


def hata_turu(mesaj: str, istisna: str | None = None) -> str | None:
    """`locator` | `assertion` | `timeout` | `environment` | `test_data` | `derleme` | None."""
    m = mesaj or ""
    if _DERLEME_RE.search(m):
        return "derleme"
    if BEKLENTI in m:
        b = _BEKLENEN_RE.search(m)
        if b is not None and b.group("g") == YOK:
            return "locator"
        return "assertion"
    if EYLEM in m:
        if "kimlik '" in m:
            return "locator"
        if _KIMLIKSIZ_ZAMAN_RE.search(m):
            return "timeout"
        return "locator"
    if _TEST_VERISI_RE.search(m):
        return "test_data"
    if _ORTAM_RE.search(m):
        return "environment"
    if "XCTAssert" in m:
        return "assertion"
    return None


def beklenen_gorulen(mesaj: str | None) -> tuple[str | None, str | None]:
    m = mesaj or ""
    b = _BEKLENEN_RE.search(m) or _XCT_ESIT_RE.search(m)
    if b is None:
        return None, None
    return b.group("b"), b.group("g")


def test_kimligi(test_adi: str, dosya: str | None) -> str | None:
    """Script eşleme anahtarı: sınıf adındaki case uuid'sinin ilk 8'i (`…C2_3f9b1c2eTests` →
    `3f9b1c2e`); önce `test_adi` (JUnit classname/name), sonra dosya."""
    for aday in (test_adi, dosya):
        if aday:
            m = _U8_RE.search(aday)
            if m is not None:
                return m.group("u8")
    return None


# JUnit classname: `<Hedef>.<…>IosC<n>_<u8>Tests` (C# web `…WebC…Tests`, Java `…Test` ile karışmaz).
_SINIF_RE = re.compile(r"\A(?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z0-9]*IosC[0-9]+_[0-9a-f]{8}Tests\Z")


def test_dosyasi_mi(dosya: str | None) -> bool:
    """Sinyal bu dile mi ait: `.swift` dosya yolu ya da XCUITest JUnit sınıf adı."""
    d = (dosya or "").strip()
    return d.endswith(".swift") or bool(_SINIF_RE.match(d))


class _SwiftTriage:
    ad = AD

    def hata_turu(self, mesaj: str, istisna: str | None = None) -> str | None:
        return hata_turu(mesaj, istisna)

    def beklenen_gorulen(self, mesaj: str | None) -> tuple[str | None, str | None]:
        return beklenen_gorulen(mesaj)

    def test_kimligi(self, test_adi: str, dosya: str | None) -> str | None:
        return test_kimligi(test_adi, dosya)

    def test_dosyasi_mi(self, dosya: str | None) -> bool:
        return test_dosyasi_mi(dosya)


EKLENTI = _SwiftTriage()
