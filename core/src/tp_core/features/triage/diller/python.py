"""Python triage eklentisi (014 Ş1; sözleşme specs/014-test-dilleri/plan.md §2.1, TASARIM §3.1).

İki kaynak, tek kalıp seti (AI yok):

- web (pytest + Playwright Python): istisnalar `playwright._impl._errors.TimeoutError` /
  `playwright.sync_api.Error`; `expect(...)` başarısızlığı `AssertionError: Locator expected to
  have text 'X'` + `Actual value: Y` (Python sürücüsünün biçimi; TS'teki `Received:` de kabul).
  Locator metni Python API'siyle yazılır: `get_by_test_id("login-submit")`.
- uygulama (pytest + Appium; `demo-app/e2e-app-python`): `ekranlar/ekran.py` Java `Ekran.java` ile
  aynı iletileri üretir ("öğe görünmedi: kimlik 'x'", "kimlik 'a' içinde 'b'") ve doğrulamalar
  `AssertionError: …: beklenen X, görülen Y (N ms)` atar; Selenium istisnaları
  (`selenium.common.exceptions.TimeoutException`, `NoSuchElementException`) locator'dır.

Tür sözlüğü (`triage.diller.TURLER`): `environment` (bağlantı: `ConnectionError`,
`urllib.error.URLError`, `MaxRetryError`, Appium oturumu açılamadı, tarayıcı başlatılamadı) →
`test_data` (hazırlık: `/test/reset|break`, giriş, `KurulumHatasi`) → `navigation` (`net::ERR_…`,
`Page.goto: Timeout`) → `assertion` (öğe hiç bulunamadıysa `locator`) → `locator` → `timeout` →
None (ortak kurallara düşer).

Kimlik eşleme (`test_kimligi`): `test_<story>_[<platform>_]c<sıra>_<uuid8>` → `<uuid8>` (script
kaydının case u8'i; Java `<Sinif>C<n>_<u8>Test` karşılığı).
"""

from __future__ import annotations

import re

AD = "python"

_ORTAM_RE = re.compile(
    r"\b(?:ConnectionError|ConnectionRefusedError|ConnectionResetError|URLError|MaxRetryError"
    r"|NewConnectionError|SessionNotCreatedException)\b"
    r"|Could not start a new session|Connection refused|Name or service not known"
    r"|net::ERR_(?:CONNECTION|NAME_NOT_RESOLVED|ADDRESS_UNREACHABLE)"
    r"|BrowserType\.launch|Executable doesn't exist"
    r"|Target (?:page|context|browser)[^\n]{0,40} closed",
    re.I,
)
_KURULUM_RE = re.compile(
    r"\bKurulumHatasi\b|/test/(?:reset|break|faults)\b|giriş başarısız|DEMOAPP_TEST_TOKEN"
    r"|sepet (?:boşaltılamadı|temizlenemedi)",
    re.I,
)
_NAV_RE = re.compile(
    r"net::ERR_|NS_ERROR_|Page\.(?:goto|reload|wait_for_url|wait_for_load_state): Timeout", re.I
)
_ASSERTION_RE = re.compile(
    r"\bAssertionError\b|\b(?:Locator|Page|APIResponse) expected (?:not )?to\b|beklenen .{0,400}"
    r", görülen\b",
    re.S,
)
_BULUNAMADI_RE = re.compile(
    r"element\(s\) not found|resolved to 0 elements|öğe görünmedi|\(öğe yok\)"
    r"|\bNoSuchElementException\b",
    re.I,
)
_LOCATOR_RE = re.compile(
    r"waiting for (?:locator|get_by_\w+|getBy\w+|selector)\b|Locator\.\w+: Timeout \d+ ?ms"
    r"|\bkimlik '[^'\n]{1,200}'|\bTimeoutException\b",
    re.I,
)
_ZAMAN_ASIMI_RE = re.compile(r"\bTimeoutError\b|Timeout \d+ ?ms exceeded|zaman aşımı", re.I)
_COKLU_RE = re.compile(r"strict mode violation", re.I)

# Playwright Python `expect`: "Locator expected to have text 'X'\nActual value: Y"; TS biçimi
# ("…: X\nReceived: Y") da kabul. Uygulama (`altyapi/bekle.py`): "beklenen X, görülen Y (N ms)".
_PW_BEKLENEN_RE = re.compile(
    r"\b(?:Locator|Page|APIResponse) expected (?:not )?to [a-z ]{0,60}?(?::[ \t]*| (?=['\"<]))"
    r"(?P<v>[^\n]+)$",
    re.M,
)
_PW_GORULEN_RE = re.compile(
    r"^\s*(?:Actual value|Received(?: string| value)?):[ \t]*(?P<v>.+)$", re.I | re.M
)
_UYG_RE = re.compile(
    r"beklenen (?P<exp>.{0,400}?), görülen (?P<rec>.{0,400}?)(?: \(\d+ ms\))?$", re.M
)
_KIMLIK_RE = re.compile(r"\Atest_[a-z0-9_]*?_c[0-9]+_(?P<u8>[0-9a-f]{8})\Z")
_DOSYA_RE = re.compile(r"(?:\A|/)(?:test_[A-Za-z0-9_]+|[A-Za-z0-9_]+_test)\.py\Z")
# pytest JUnit `classname` (importlib kipi): `tests.generated.test_tpd_1_c2_3f9b1c2e`.
_SINIF_RE = re.compile(r"\A(?:[a-z_][a-z0-9_]*\.)*test_[a-z0-9_]+\Z")
_PY_ISTISNA_RE = re.compile(
    r"\bplaywright\._impl\.|\bplaywright\.sync_api\.|\bselenium\.common\.|\bappium\.|"
    r"\bpytest\.|\.py:\d+: (?:in |[A-Z][A-Za-z]*Error)"
)


def _unquote(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if len(v) >= 2 and ((v[0] == v[-1] and v[0] in "'\"") or (v[0], v[-1]) == ("<", ">")):
        v = v[1:-1]
    return v or None


def hata_turu(mesaj: str | None, istisna: str | None = None) -> str | None:
    """Hata metni → tür (`triage.diller.TURLER`); tanınmıyorsa None."""
    m = mesaj or ""
    if not m.strip() and not (istisna or "").strip():
        return None
    metin = f"{istisna or ''}\n{m}"
    govde = m.partition("Call log:")[0]
    if _ORTAM_RE.search(metin):
        return "environment"
    if _KURULUM_RE.search(metin):
        return "test_data"
    if _NAV_RE.search(metin):
        return "navigation"
    if _COKLU_RE.search(govde):
        return "locator"
    ilk = f"{istisna or ''}\n{m.lstrip().splitlines()[0] if m.strip() else ''}"
    if _ASSERTION_RE.search(ilk) or _ASSERTION_RE.search(govde):
        # Doğrulanan öğe hiç bulunamadıysa değer farkı değil, 0 elemandır (kural 3'ün ön koşulu).
        return "locator" if _BULUNAMADI_RE.search(govde) else "assertion"
    if _BULUNAMADI_RE.search(metin) or _LOCATOR_RE.search(metin):
        return "locator"
    if _ZAMAN_ASIMI_RE.search(metin):
        return "timeout"
    return None


def beklenen_gorulen(mesaj: str | None) -> tuple[str | None, str | None]:
    """Assertion metnindeki (beklenen, görülen); yoksa (None, None). Çağrı günlüğü taranmaz."""
    govde = (mesaj or "").partition("Call log:")[0]
    u = _UYG_RE.search(govde)
    if u:
        return _unquote(u.group("exp")), _unquote(u.group("rec"))
    e, g = _PW_BEKLENEN_RE.search(govde), _PW_GORULEN_RE.search(govde)
    if e is None and g is None:
        return None, None
    return (_unquote(e.group("v")) if e else None), (_unquote(g.group("v")) if g else None)


def test_kimligi(test_adi: str, dosya: str | None = None) -> str | None:
    """`test_tpd_1_android_c2_3f9b1c2e` (ya da JUnit `classname.name`, parametreli
    `test_x[1-3]`) → `3f9b1c2e`; üretilen test değilse None."""
    ad = (test_adi or "").strip()
    ad = ad.rsplit(".", 1)[-1].split("[", 1)[0]
    m = _KIMLIK_RE.match(ad)
    if m is None and dosya:
        govde = dosya.rsplit("/", 1)[-1].removesuffix(".py")
        m = _KIMLIK_RE.match(govde)
    return m.group("u8") if m else None


def test_dosyasi_mi(dosya: str | None) -> bool:
    """Sinyal Python testine mi ait: `.py` test dosyası ya da pytest `classname`
    (`tests.generated.test_x`)."""
    d = (dosya or "").strip()
    if not d:
        return False
    if d.endswith(".py"):
        return bool(_DOSYA_RE.search(d))
    return bool(_SINIF_RE.match(d)) and "." in d


def python_istisnasi_mi(mesaj: str | None, istisna: str | None = None) -> bool:
    """Metin bir Python/pytest istisnası mı (dil bilinmeyen eski kayıt için ipucu)?"""
    return bool(_PY_ISTISNA_RE.search(f"{istisna or ''}\n{mesaj or ''}"))


_PY_MODUL_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def junit_kimligi(classname: str | None, metot: str) -> tuple[str | None, str]:
    """`ci.parse.dil_ayristirmasi` kancası: pytest JUnit (`classname` = modül yolu, `name` =
    işlev) → test-runner özetiyle (`runner/diller/_pytest_junit.py`) aynı kimlik: dosya
    `tests/…/test_x.py`, ad `test_x › <işlev>`. Modül yolu değilse değer değişmez."""
    if not classname or not _PY_MODUL_RE.fullmatch(classname):
        return classname, metot
    basit = classname.rsplit(".", 1)[-1]
    ad = metot if metot.startswith(f"{basit} › ") else f"{basit} › {metot}"
    return classname.replace(".", "/") + ".py", ad


class _PythonTriage:
    ad = AD

    def hata_turu(self, mesaj: str, istisna: str | None = None) -> str | None:
        return hata_turu(mesaj, istisna)

    def beklenen_gorulen(self, mesaj: str | None) -> tuple[str | None, str | None]:
        return beklenen_gorulen(mesaj)

    def test_kimligi(self, test_adi: str, dosya: str | None) -> str | None:
        return test_kimligi(test_adi, dosya)

    def test_dosyasi_mi(self, dosya: str | None) -> bool:
        return test_dosyasi_mi(dosya)


EKLENTI = _PythonTriage()
