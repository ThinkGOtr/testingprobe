"""Web + Java (Playwright for Java + TestNG; 011 üretim dili §2.8) triage kanıtı ve kalıpları.
AI yok.

Web + Java testleri (`demo-app/e2e-java`) dil olarak Java'dır (hata metni Java istisnasıdır,
kimlik ↔ sabit eşlemesi `ekranlar/Kimlikler.java` üzerindendir) ama araç/ortam olarak web'dir:
Appium sayfa kaynağı XML'i yoktur; kanıt `target/kanit/<Sınıf>.<metot>/{ekran.png, trace.zip,
sayfa.html}` altındadır ve web yöntemiyle (Playwright trace + hata anı DOM'u) değerlendirilir.

- `playwright_java_turu`: Playwright for Java hata metni → test-runner `failure.type` sözlüğü
  (`com.microsoft.playwright.TimeoutError` + "waiting for locator" → locator; `AssertionFailedError`
  / `AssertionError` → assertion; bağlantı / `net::ERR_` → navigation, yani ortam).
- `beklenen_gorulen`: Playwright Java / opentest4j assertion metnindeki (beklenen, görülen).
- `kirik_kimlik`: hata metnindeki kırık testId (+ kapsayıcı): `Ekran.java` biçimi ("kimlik 'x'")
  ya da Playwright çağrı günlüğü (`getByTestId("x")`, `[data-testid="x"]`).
- `kanit_oku`: koşu dizininden (sembolik bağ / kök dışı yol yok, boyut sınırlı) hata anı DOM'u
  (`sayfa.html`), ekran görüntüsü ve trace yolu.
- `dom_dugumleri`: `sayfa.html` (güvenilmeyen) içindeki `data-testid`'li öğeler ve kapsayıcı testId
  zinciri — `triage.java.aday_kimlik` ile aynı aday kuralına girer (eski kimlik hata anındaki
  sayfada YOK ve sembol tablosunda tanımsız, eski kimlikle ortak sözcüğü olan TEK kimlik var).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from tp_core.features.triage import evidence as ev
from tp_core.features.triage import java as jv

KANIT_DOM = "sayfa.html"
KANIT_TRACE = "trace.zip"
KANIT_EKRAN = jv.KANIT_EKRAN
MAX_DOM = 4 * 1024 * 1024
MAX_DUGUM = 50_000
MAX_DERINLIK = 512
# Koşu dizini içinde kanıt kökünün olası yerleri (test-runner Java yolu; tekrarlı koşuda
# `kanit/tekrar-N/`). Rapor `failure.evidence.*.rel` verirse o önceliklidir.
KANIT_KOKLERI = (
    "target/kanit",
    "kanit",
    "e2e-java/target/kanit",
    "src/e2e-java/target/kanit",
    "target/kanit/tekrar-1",
    "kanit/tekrar-1",
)
# Raporun (`run.json` `failure.evidence`) hata anı DOM'unu taşıyabileceği anahtarlar.
_DOM_ANAHTARLARI = ("dom", "page_html", "sayfa_html", "page_source")

# ----------------------------------------------------------------------------- hata kalıpları

_PW_ISTISNA_RE = re.compile(
    r"com\.microsoft\.playwright\.|\bPlaywrightException\b|\bTimeoutError\b"
    r"|org\.opentest4j\.|\bAssertionFailedError\b"
)
_PW_ZAMAN_ASIMI_RE = re.compile(r"\bTimeoutError\b|Timeout \d+ ?ms exceeded", re.I)
_PW_ASSERTION_RE = re.compile(
    r"\bAssertionFailedError\b|(?:java\.lang\.)?AssertionError\b"
    r"|\b(?:Locator|Page|APIResponse) expected (?:not )?to\b"
)
# Bağlantı / gezinme: uygulamaya ya da tarayıcıya erişilemedi (ortam).
_PW_ORTAM_RE = re.compile(
    r"net::ERR_|NS_ERROR_|ECONNREFUSED|ECONNRESET|ENOTFOUND|EAI_AGAIN|Connection refused"
    r"|java\.net\.(?:Connect|NoRouteToHost|UnknownHost|SocketTimeout)Exception"
    r"|(?:Page|Frame)\.(?:navigate|goto|reload|waitForURL|waitForLoadState): Timeout"
    r"|BrowserType\.launch|Executable doesn't exist|Failed to launch|browser has been closed"
    r"|Target (?:page|context|browser)[^\n]{0,40} closed",
    re.I,
)
# 0 eleman: locator eleman bulamadı / bulmayı beklerken zaman aşımı.
_PW_LOCATOR_RE = re.compile(
    r"waiting for (?:locator|getBy\w+|selector)\b|Locator\.\w+: Timeout \d+ ?ms exceeded"
    r"|\.waitFor: Timeout",
    re.I,
)
_PW_BULUNAMADI_RE = re.compile(r"element\(s\) not found|resolved to 0 elements", re.I)
_PW_COKLU_RE = re.compile(r"strict mode violation", re.I)

# `assertThat(locator).hasText(..)`: "Locator expected to have text: X\nReceived: Y";
# opentest4j / JUnit: "expected: <X> but was: <Y>".
_PW_BEKLENEN_RE = re.compile(
    r"\b(?:Locator|Page|APIResponse) expected (?:not )?to [^:\n]{0,80}:[ \t]*(?P<v>.+)$", re.M
)
_PW_GORULEN_RE = re.compile(r"^\s*Received(?: string| value)?:[ \t]*(?P<v>.+)$", re.I | re.M)
_OT4J_RE = re.compile(r"expected: <(?P<exp>.*?)> but was: <(?P<rec>.*?)>", re.S)


def playwright_java_mi(mesaj: str | None, istisna: str | None = None) -> bool:
    """Hata Playwright for Java / opentest4j istisnası mı (sınıf adı ya da metin)?"""
    return bool(_PW_ISTISNA_RE.search(f"{istisna or ''}\n{mesaj or ''}"))


def playwright_java_turu(mesaj: str | None, istisna: str | None = None) -> str | None:
    """Playwright for Java hata metni → test-runner `failure.type` sözlüğü; tanınmıyorsa None
    (çağıran Java/Appium kalıplarına — `Ekran.java` biçimi — düşer).

    Sıra: ortam (bağlantı / gezinme) → assertion (öğe bulunamadıysa locator) → locator (0 eleman
    beklerken zaman aşımı). "strict mode violation" 0 eleman değildir (`other`).
    """
    m = mesaj or ""
    metin = f"{istisna or ''}\n{m}"
    if not m.strip() and not (istisna or "").strip():
        return None
    govde = m.partition("Call log:")[0]
    if _PW_ORTAM_RE.search(metin):
        return "navigation"
    if _PW_COKLU_RE.search(m):
        return "other"
    ilk = f"{istisna or ''}\n{m.lstrip().splitlines()[0] if m.strip() else ''}"
    if _PW_ASSERTION_RE.search(ilk) or _PW_ASSERTION_RE.search(govde):
        # Doğrulanan öğe hiç bulunamadıysa değer farkı değil, 0 elemandır (kural 3'ün ön koşulu).
        if _PW_BULUNAMADI_RE.search(govde):
            return "locator_not_found"
        return "assertion"
    if _PW_BULUNAMADI_RE.search(govde):
        return "locator_not_found"
    if _PW_ZAMAN_ASIMI_RE.search(metin):
        return "locator_timeout" if _PW_LOCATOR_RE.search(m) else "other"
    if _PW_ISTISNA_RE.search(metin):
        return "other"  # PlaywrightException (hedef kapandı vb. dışında): sınıflandırılamadı
    return None


def beklenen_gorulen(mesaj: str | None) -> tuple[str | None, str | None]:
    """Playwright Java / opentest4j assertion metnindeki (beklenen, görülen); yoksa (None, None).
    Çağrı günlüğü (`Call log:`) taranmaz."""
    govde = (mesaj or "").partition("Call log:")[0]
    e, g = _PW_BEKLENEN_RE.search(govde), _PW_GORULEN_RE.search(govde)
    if e is not None and g is not None:
        return e.group("v").strip(), g.group("v").strip()
    o = _OT4J_RE.search(govde)
    if o is not None:
        return o.group("exp"), o.group("rec")
    return None, None


def kirik_kimlik(*metinler: Any) -> tuple[str | None, str | None, bool]:
    """(aranan, kapsayıcı, belirsiz) — önce `Ekran.java` biçimi ("kimlik 'kapsayıcı' içinde
    'aranan'"), yoksa Playwright çağrı günlüğündeki testId zinciri (son öğe aranan, bir önceki
    kapsayıcı)."""
    hedef, kapsam, belirsiz = jv.kimlik_zinciri(*metinler)
    if hedef or belirsiz:
        return hedef, kapsam, belirsiz
    for m in metinler:
        tids = ev.locator_test_idleri(m if isinstance(m, str) else None)
        if tids:
            return tids[-1], (tids[-2] if len(tids) > 1 and tids[-2] != tids[-1] else None), False
    return None, None, False


# ----------------------------------------------------------------------------- kanıt


@dataclass
class WebJavaKaniti:
    sayfa_html: str | None = None
    dom_rel: str | None = None  # koşu dizinine göre
    ekran_rel: str | None = None
    trace_rel: str | None = None
    uyari: str | None = None


def _dosya_var(kosu: Path, rel: str) -> bool:
    try:
        yol = kosu / rel
        if not yol.is_file() or yol.is_symlink():
            return False
        return kosu.resolve() in yol.resolve().parents
    except OSError:
        return False


def kanit_oku(
    kosu: Path | None,
    kosu_rel: str | None,
    failure: Any,
    dosya: str | None,
    test_adi: str,
) -> WebJavaKaniti:
    """Koşu dizinindeki web + Java kanıtı. Önce raporun `failure.evidence.*.rel` yolları
    (TP_ARTIFACTS_PATH'e göre), yoksa `KANIT_KOKLERI/<Sınıf.metot>/{sayfa.html, ekran.png,
    trace.zip}` (`Kanit.dizin` adlandırması; `triage.java.kanit_dizini_adi`)."""
    out = WebJavaKaniti()
    if kosu is None or not kosu_rel:
        return out
    kanitlar = ev.mapping(ev.mapping(failure).get("evidence"))
    dom_adaylari: list[str] = []
    ekran_adaylari: list[str] = []
    trace_adaylari: list[str] = []
    # test-runner (Ş3): `failure.page_html_rel` ve `failure.evidence.page_html.rel`.
    for rel in (
        ev.mapping(failure).get("page_html_rel"),
        *(ev.mapping(kanitlar.get(anahtar)).get("rel") for anahtar in _DOM_ANAHTARLARI),
    ):
        k = ev.kanit_yolu(kosu_rel, rel)
        if k and k.endswith((".html", ".htm")) and k not in dom_adaylari:
            dom_adaylari.append(k)
    e = ev.kanit_yolu(kosu_rel, ev.mapping(kanitlar.get("screenshot")).get("rel"))
    if e:
        ekran_adaylari.append(e)
    t = ev.kanit_yolu(
        kosu_rel,
        ev.mapping(failure).get("trace_rel") or ev.mapping(kanitlar.get("trace")).get("rel"),
    )
    if t:
        trace_adaylari.append(t)
    ad = jv.kanit_dizini_adi(dosya, test_adi)
    if ad:
        dom_adaylari += [f"{kok}/{ad}/{KANIT_DOM}" for kok in KANIT_KOKLERI]
        ekran_adaylari += [f"{kok}/{ad}/{KANIT_EKRAN}" for kok in KANIT_KOKLERI]
        trace_adaylari += [f"{kok}/{ad}/{KANIT_TRACE}" for kok in KANIT_KOKLERI]
    for rel in dom_adaylari:
        try:
            veri = ev.guvenli_oku(kosu / rel, kosu, MAX_DOM)
        except ev.KanitHatasi as exc:
            out.uyari = f"hata anı DOM'u ({KANIT_DOM}) okunamadı: {exc}"
            continue
        if veri is not None:
            out.sayfa_html = veri.decode("utf-8", "replace")
            out.dom_rel = rel
            break
    out.ekran_rel = next((r for r in ekran_adaylari if _dosya_var(kosu, r)), None)
    out.trace_rel = next((r for r in trace_adaylari if _dosya_var(kosu, r)), None)
    return out


# ----------------------------------------------------------------------------- hata anı DOM'u


class DomHatasi(ValueError):
    pass


_BOS_OGELER = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
     "source", "track", "wbr"}
)  # fmt: skip


class _TestIdToplayici(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # açık öğeler: (etiket, testId | None)
        self.yigin: list[tuple[str, str | None]] = []
        # [kimlik, etiket, metin parçaları, kapsayıcılar]
        self.dugumler: list[list[Any]] = []
        self._acik: list[int] = []  # açık testId'li öğelerin `dugumler` indeksleri
        self.sayac = 0

    def _zincir(self) -> tuple[str, ...]:
        return tuple(t for _e, t in self.yigin if t)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.sayac += 1
        if self.sayac > MAX_DUGUM or len(self.yigin) > MAX_DERINLIK:
            raise DomHatasi("hata anı DOM'u düğüm/derinlik sınırını aşıyor")
        tid: str | None = None
        for ad, deger in attrs:
            if ad == "data-testid" and deger and ev.TESTID_RE.match(deger.strip()):
                tid = deger.strip()
                break
        if tid:
            self.dugumler.append([tid, tag[:80], [], self._zincir()])
        if tag not in _BOS_OGELER:
            self.yigin.append((tag, tid))
            if tid:
                self._acik.append(len(self.dugumler) - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        bos = tag in _BOS_OGELER
        self.handle_starttag(tag, attrs)
        if not bos:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        # Hoşgörülü kapanış: yığında eşleşen en içteki öğeye kadar kapat; yoksa yok say.
        for i in range(len(self.yigin) - 1, -1, -1):
            if self.yigin[i][0] == tag:
                for _e, t in self.yigin[i:]:
                    if t and self._acik:
                        self._acik.pop()
                del self.yigin[i:]
                return

    def handle_data(self, data: str) -> None:
        if not self._acik or (self.yigin and self.yigin[-1][0] in ("script", "style")):
            return
        parca = data.strip()
        if parca:
            metin = self.dugumler[self._acik[-1]][2]
            if sum(len(p) for p in metin) < 200:
                metin.append(parca)


def dom_dugumleri(html: str | None) -> list[jv.KimlikDugumu]:
    """Hata anı DOM'undaki `data-testid`'li öğeler (belge sırası) + kapsayıcı testId zinciri.
    Güvenilmeyen girdi: boyut, düğüm ve derinlik sınırlı; yalnızca geçerli testId'ler alınır."""
    if not html:
        return []
    if len(html.encode("utf-8", "replace")) > MAX_DOM:
        raise DomHatasi("hata anı DOM'u boyut sınırını aşıyor")
    t = _TestIdToplayici()
    try:
        t.feed(html)
        t.close()
    except DomHatasi:
        raise
    except Exception as exc:  # html.parser bozuk girdide AssertionError vb. atabilir
        raise DomHatasi(f"hata anı DOM'u ayrıştırılamadı: {type(exc).__name__}") from exc
    return [
        jv.KimlikDugumu(kimlik, etiket, ev.temiz(" ".join(metin), 120), tuple(zincir))
        for kimlik, etiket, metin, zincir in t.dugumler
    ]


def kisalt(metin: str | None) -> str | None:
    """Hata anı DOM'unun saklanan/LLM'e giden kırpılmış hali."""
    return jv.kisalt(metin)
