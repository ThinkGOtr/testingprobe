"""Yerel kontrol sonucunun deterministik sınıfı (TEKNIK-TASARIM §8.4 adım 5; Constitution VI, XI).

toolchain-worker `/check` raporu (`deps → tsc → eslint → ast_guard → run`) şu sınıflara ayrılır:

| Sınıf | Koşul | Sonraki adım |
|---|---|---|
| `gecti` | `conclusion = success` | PR |
| `derleme` | deps/tsc/eslint/AST koruması (Java: deps/guard/compile) başarısız | insana |
| `ortam` | sağlık, runner yok, rapor yok, uygulama≠commit (`app`) | insana (yeniden denenebilir) |
| `locator` | locator bulunamadı / bulma zaman aşımı / strict mode | 1 yeniden eşleme turu |
| `defect_adayi` | **tüm** tekrarlar aynı `expect(...)`'te farklı değer | onarım yok, insana |
| `kararsiz` | tekrarların bir kısmı geçti, bir kısmı kırmızı (flaky) | insana; defect adayı değil |
| `bilinmiyor` | diğer | insana |

`--repeat-each=3` kararlı kırmızıyı kararsızdan ayırmak içindir: 3 tekrardan biri bile geçtiyse
sonuç "uygulama onaylı case'in beklenen sonucunu vermedi" diye okunamaz (yarış, zamanlama ya da
test kararsızlığı olabilir); `kararsiz` sınıfı ayrı tutulur ve pass@1'de geçmedi sayılır.

Java/Appium raporu (009 §2.3; toolchain `/check` `lang=java`: `app → deps → guard → compile → run`)
aynı sınıflara ayrılır: `NoSuchElementException` / `TimeoutException` (eylem ön koşulu,
`Bekle.kosul`) / `StaleElementReferenceException` → locator; `java.lang.AssertionError`
(`Bekle.dogrula`: "<açıklama>: beklenen <X>, görülen <Y> (N ms)") → assertion; Appium oturumu
açılamadı / bağlantı reddedildi → ortam. Kurulum kaynaklı assertion (`/test/*` çağrısı, giriş,
`DEMOAPP_TEST_TOKEN`; `araclar/KirmiziDenetimi.java` süzgeci) defect adayı sayılmaz → ortam.

Hata metinleri test kodunun çıktısıdır (güvenilmez): yalnızca kalıp eşlenir, kırpılarak saklanır.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

MAX_HATA = 600
GECEN = ("passed", "expected", "flaky")

_LOCATOR_KALIPLARI = (
    re.compile(r"element\(s\) not found", re.I),
    re.compile(r"strict mode violation", re.I),
    re.compile(r"resolved to 0 elements", re.I),
    re.compile(r"locator\.\w+: Timeout \d+ms exceeded", re.I),
    re.compile(r"waiting for (getBy|locator)", re.I),
    re.compile(r"\.waitFor: Timeout", re.I),
)
_ASSERTION = re.compile(r"expect\([^)]*\)\.\w+", re.I)
_RECEIVED = re.compile(r"^\s*Received(?: string| value)?:\s*(?P<v>.+)$", re.I | re.M)
# Playwright: `Expected: …`, `Expected string: …` (toHaveText), `Expected substring: …`
# (toContainText), `Expected pattern: /…/` (düzenli ifade; triage değer saymaz).
_EXPECTED = re.compile(
    r"^\s*Expected(?: string| value| pattern| substring)?:\s*(?P<v>.+)$", re.I | re.M
)
_ORTAM = re.compile(r"net::ERR_|ECONNREFUSED|ENOTFOUND|page\.goto: Timeout", re.I)

# Java / Appium (009 §2.3). Sınıf adları paketli ya da paketsiz gelebilir (Surefire `type` ya da
# mesajın ilk satırı); yalnızca kalıp eşlenir.
JAVA_ORTAM = re.compile(
    r"SessionNotCreatedException|Could not start a new session|UnreachableBrowserException"
    r"|java\.net\.(?:Connect|NoRouteToHost|UnknownHost)Exception|ConnectException"
    r"|Connection refused",
    re.I,
)
JAVA_ASSERTION = re.compile(r"(?:java\.lang\.)?AssertionError\b")
JAVA_LOCATOR = re.compile(
    r"(?:org\.openqa\.selenium\.)?(?:NoSuchElementException|TimeoutException"
    r"|StaleElementReferenceException)\b"
)
# Assertion türünde olsa da kurulum kaynaklı (demo-app/e2e-app/araclar/KirmiziDenetimi.java).
JAVA_KURULUM = re.compile(r"/test/|giriş başarısız|DEMOAPP_TEST_TOKEN", re.I)
# `Bekle.dogrula`: "<açıklama>: beklenen <X>, görülen <Y> (N ms)"; TestNG Assert:
# "expected [X] but found [Y]".
_JAVA_BEKLENEN = re.compile(r"beklenen <(?P<exp>.*?)>, görülen <(?P<rec>.*)> \(\d+ ms\)", re.S)
_TESTNG_BEKLENEN = re.compile(r"expected \[(?P<exp>.*?)\] but found \[(?P<rec>.*?)\]", re.S)


def java_beklenen_gorulen(mesaj: str | None) -> tuple[str | None, str | None]:
    """Java assertion mesajındaki (beklenen, görülen); yoksa (None, None)."""
    m = _JAVA_BEKLENEN.search(mesaj or "") or _TESTNG_BEKLENEN.search(mesaj or "")
    if m is None:
        return None, None
    return m.group("exp"), m.group("rec")


def testng_bicimi(mesaj: str | None) -> bool:
    """Beklenen/görülen TestNG `Assert` biçiminden mi (`expected [X] but found [Y]`)?

    TestNG değerleri Java `toString()` ile basar: `Double` / `BigDecimal` binlik ayırıcı
    kullanmaz, ondalık ayırıcı her zaman noktadır (`new BigDecimal("2.500")` → `2.500` = 2,5).
    `Bekle.dogrula` ise ekrandaki metni (Türkçe yazım: `1.250,00 TL`) basar. İkisi de varsa
    `java_beklenen_gorulen` gibi `Bekle.dogrula` önceliklidir (False)."""
    m = mesaj or ""
    return _JAVA_BEKLENEN.search(m) is None and _TESTNG_BEKLENEN.search(m) is not None


def java_hata_turu(message: str | None) -> str | None:
    """Java/Appium hata metninin türü (`ortam` | `assertion` | `locator`); Java değilse None.

    Sıra: ortam (oturum/bağlantı) → kurulum assertion'ı (ortam) → assertion → locator. Assertion
    mesajı bir `TimeoutException`'ı anabilir (`Bekle.dogrula` zaman aşımını AssertionError'a
    çevirir); bu yüzden assertion locator'dan önce gelir.
    """
    m = message or ""
    if JAVA_ORTAM.search(m):
        return "ortam"
    ilk = m.lstrip().splitlines()[0] if m.strip() else ""
    if JAVA_ASSERTION.search(ilk) or _JAVA_BEKLENEN.search(m):
        return "ortam" if JAVA_KURULUM.search(m) else "assertion"
    if JAVA_LOCATOR.search(ilk) or JAVA_LOCATOR.search(m):
        return "locator"
    return None


ACIKLAMA = {
    "gecti": "Yerel kontrol geçti (tsc, eslint, AST koruması, Playwright tekrarları yeşil).",
    "gecti_java": "Yerel kontrol geçti (pom kilidi, Java AST koruması, test-compile, Appium "
    "tekrarları yeşil).",
    # 011: web + Java (Playwright for Java + TestNG; rapor `lang: "java"`, `platform: "web"`).
    "gecti_java_web": "Yerel kontrol geçti (pom kilidi, Java AST koruması, test-compile, "
    "Playwright tekrarları yeşil).",
    "derleme": "Derleme/lint/AST koruması başarısız: üretilen kod ya da kütüphane insan "
    "incelemesi ister.",
    "ortam": "Ortam hatası (uygulama/test-runner erişilemedi); test sonucu güvenilir değil, "
    "yeniden denenebilir.",
    "locator": "Locator/eşleme hatası: eleman bulunamadı ya da zaman aşımı (beklenen değerlere "
    "dokunmadan tek yeniden eşleme turu yapılır).",
    "defect_adayi": "Defect adayı: uygulama onaylı case'in beklenen sonucunu vermedi. Otomatik "
    "onarım yapılmaz; insana gider.",
    "kararsiz": "Kararsız (flaky): tekrarların bir kısmı geçti, bir kısmı kırmızı. Defect adayı "
    "sayılmaz; yarış/zamanlama ya da test kararsızlığı için insan incelemesi gerekli.",
    "bilinmiyor": "Sınıflandırılamayan kırmızı sonuç; insan incelemesi gerekli.",
    "kirma_beklenen_kirmizi": "Beklenen kırmızı: BREAK_CAMPAIGN ile kırılmış uygulamada test "
    "assertion ile kaldı (testin hata yakaladığının kanıtı; defect adayı değildir).",
}


def _kirp(metin: Any) -> str | None:
    if metin is None:
        return None
    s = str(metin)
    return s if len(s) <= MAX_HATA else s[:MAX_HATA] + "…"


@dataclass
class Siniflama:
    sinif: str
    sonuc: str  # success | failure | error
    aciklama: str
    run_status: str | None = None
    run_id: str | None = None
    basarisiz: list[dict[str, Any]] = field(default_factory=list)
    adimlar: dict[str, bool | None] = field(default_factory=dict)
    gecen: int = 0
    toplam: int = 0
    hata: str | None = None
    # test-runner Java yolunun kırarak doğrulama denetimi (`run.kirmizi_denetimi.ok`): BREAK
    # koşusunda ≥1 kırmızı ve her kırmızı `failure.type == "assertion"`. Web/kırılmasız: None.
    kirmizi_ok: bool | None = None

    def ozet(self) -> dict[str, Any]:
        return {
            "sinif": self.sinif,
            "sonuc": self.sonuc,
            "aciklama": self.aciklama,
            "run_status": self.run_status,
            "run_id": self.run_id,
            "basarisiz": self.basarisiz,
            "adimlar": self.adimlar,
            "gecen": self.gecen,
            "toplam": self.toplam,
            "hata": self.hata,
        }


# test-runner `failure.type` (toolchain/runner/results.py `classify_error`) → kontrol türü.
RUNNER_TURU = {
    "locator_not_found": "locator",
    "locator_ambiguous": "locator",
    "locator_timeout": "locator",
    "assertion": "assertion",
    "navigation": "ortam",
    "test_data": "ortam",
}


def test_error_kind(
    message: str | None, runner_type: str | None = None, *, java: bool = False
) -> str:
    """Tek bir test hatası: `locator` | `assertion` | `ortam` | `bilinmiyor`.

    Önce test-runner'ın biçimsel türü (`failure.type`), yoksa/`other` ise mesaj kalıpları.
    Java/Appium kalıpları yalnızca Java raporunda (`java=True`) uygulanır: web Playwright
    hatalarının sınıfı değişmez.
    """
    if runner_type in RUNNER_TURU:
        return RUNNER_TURU[runner_type]
    m = message or ""
    if _ORTAM.search(m):
        return "ortam"
    if java:
        jtur = java_hata_turu(m)
        if jtur is not None:
            return jtur
    # Assertion önce: Playwright'ın `expect(locator).toHaveText` zaman aşımı mesajı "Call log"
    # bölümünde `- waiting for getByTestId(...)` satırı taşır; bu bir locator hatası değildir.
    # Locator kalıpları "Call log" satırları dışında aranır.
    if _ASSERTION.search(m) and _RECEIVED.search(m):
        return "assertion"
    if any(k.search(_cagri_kaydi_disi(m)) for k in _LOCATOR_KALIPLARI):
        return "locator"
    return "bilinmiyor"


def _cagri_kaydi_disi(m: str) -> str:
    """Hata mesajının "Call log:" bölümünden önceki kısmı (bölüm yoksa tamamı)."""
    ana, _ayrac, _kayit = m.partition("Call log:")
    return ana


def _hata_satiri(test: Mapping[str, Any], java: bool = False) -> dict[str, Any]:
    err = str(test.get("error") or "")
    failure = test.get("failure") if isinstance(test.get("failure"), Mapping) else {}
    failure = failure or {}
    m_exp, m_rec = _EXPECTED.search(err), _RECEIVED.search(err)
    exp = failure.get("expected") or (m_exp.group("v").strip() if m_exp else None)
    rec = failure.get("received") or (m_rec.group("v").strip() if m_rec else None)
    if java and exp is None and rec is None:
        exp, rec = java_beklenen_gorulen(err or failure.get("message"))
    adim = failure.get("step") if isinstance(failure.get("step"), Mapping) else None
    konum = failure.get("test_location") or failure.get("location")
    satir = konum.get("line") if isinstance(konum, Mapping) else None
    return {
        "test_adi": _kirp(test.get("title")) or "",
        "hata_mesaji": _kirp(err.splitlines()[0] if err else failure.get("first_line")),
        "beklenen": _kirp(exp),
        "gerceklesen": _kirp(rec),
        "adim": _kirp(adim.get("title")) if adim else None,
        "locator": _kirp(failure.get("locator")),
        "tur": test_error_kind(err, failure.get("type"), java=java),
        "satir": satir if isinstance(satir, int) and not isinstance(satir, bool) else None,
    }


def _tekrarlari_birlestir(satirlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """repeat-each tekrarlarında aynı hata tek satır olur (`tekrar`: kaç kez görüldü)."""
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for s in satirlar:
        anahtar = tuple(s.get(k) for k in ("test_adi", "hata_mesaji", "beklenen", "gerceklesen",
                                            "locator", "satir"))  # fmt: skip
        if anahtar in out:
            out[anahtar]["tekrar"] += 1
        else:
            out[anahtar] = {**s, "tekrar": 1}
    return list(out.values())


def _adim_ok(report: Mapping[str, Any], ad: str) -> bool | None:
    adim = report.get(ad)
    if not isinstance(adim, Mapping) or adim.get("skipped"):
        return None
    return bool(adim.get("ok"))


# Statik adımlar: TS (`deps → tsc → eslint → ast_guard`) ve Java (`deps → guard → compile`).
TS_ADIMLARI = ("deps", "tsc", "eslint", "ast_guard")
JAVA_ADIMLARI = ("deps", "guard", "compile")
# Portal yerel kontrol kartında dile göre gösterilen adımlar (tek kaynak; `views._yerel_kontrol`).
# TS'de `deps` (bağımlılık kilidi) koşar ama kart bugün göstermez.
GORUNEN_ADIMLAR: dict[str, tuple[str, ...]] = {
    "ts": tuple(a for a in TS_ADIMLARI if a != "deps"),
    "java": JAVA_ADIMLARI,
}


def java_raporu_mu(report: Mapping[str, Any]) -> bool:
    """toolchain `/check` Java yolu raporu mu? (`lang=java` ya da Java adımları)."""
    if report.get("lang") == "java":
        return True
    return any(isinstance(report.get(a), Mapping) for a in ("guard", "compile")) and not any(
        isinstance(report.get(a), Mapping) for a in ("tsc", "eslint", "ast_guard")
    )


def classify(report: Mapping[str, Any]) -> Siniflama:
    statik = JAVA_ADIMLARI if java_raporu_mu(report) else TS_ADIMLARI
    adimlar = {ad: _adim_ok(report, ad) for ad in statik}
    run = report.get("run") if isinstance(report.get("run"), Mapping) else {}
    run = run or {}
    tests = [t for t in run.get("tests") or [] if isinstance(t, Mapping)]
    gecen = sum(1 for t in tests if t.get("status") in GECEN)
    kd = run.get("kirmizi_denetimi")
    ortak = {
        "run_status": run.get("status"),
        "run_id": run.get("run_id"),
        "adimlar": adimlar,
        "gecen": gecen,
        "toplam": len(tests),
        "kirmizi_ok": (kd.get("ok") is True) if isinstance(kd, Mapping) else None,
    }
    if report.get("conclusion") == "success":
        if statik != JAVA_ADIMLARI:
            aciklama = ACIKLAMA["gecti"]
        elif report.get("platform") == "web":
            aciklama = ACIKLAMA["gecti_java_web"]
        else:
            aciklama = ACIKLAMA["gecti_java"]
        return Siniflama("gecti", "success", aciklama, **ortak)
    app = report.get("app")
    if isinstance(app, Mapping) and not app.get("skipped") and app.get("ok") is False:
        # Çalışan uygulama commit'le eşleşmiyor (`sha_eslesmesi='farkli'`) ya da doğrulanamadı:
        # koşu yapılmadı; bu bir test/ürün sonucu değil ortam sorunudur (Constitution XI).
        return Siniflama(
            "ortam",
            "error",
            ACIKLAMA["ortam"],
            hata=_kirp(app.get("error") or f"uygulama eşleşmesi: {app.get('sha_eslesmesi')}"),
            **ortak,
        )
    if any(v is False for v in adimlar.values()):
        basarisiz = [ad for ad, v in adimlar.items() if v is False]
        return Siniflama(
            "derleme",
            "failure",
            ACIKLAMA["derleme"],
            hata="Başarısız adım: " + ", ".join(basarisiz),
            **ortak,
        )
    saglik = run.get("saglik")
    if (
        run.get("status") == "error"
        or (isinstance(saglik, Mapping) and saglik.get("ok") is False)
        or not run
    ):
        return Siniflama(
            "ortam",
            "error",
            ACIKLAMA["ortam"],
            hata=_kirp(run.get("error") or report.get("summary")),
            **ortak,
        )
    kirmizi = [t for t in tests if t.get("status") not in (*GECEN, "skipped")]
    java_rapor = java_raporu_mu(report)
    satirlar = [_hata_satiri(t, java_rapor) for t in kirmizi]
    turler = {s["tur"] for s in satirlar}
    if "ortam" in turler:
        sinif = "ortam"
    elif "locator" in turler:
        sinif = "locator"
    elif _kararsiz_mi(tests):
        # Aynı testin tekrarlarının bir kısmı geçti: kararlı kırmızı değil → defect adayı değil.
        sinif = "kararsiz"
    elif "assertion" in turler and _ayni_assertion(satirlar):
        sinif = "defect_adayi"
    else:
        sinif = "bilinmiyor"
    return Siniflama(
        sinif,
        "error" if sinif == "ortam" else "failure",
        ACIKLAMA[sinif],
        basarisiz=_tekrarlari_birlestir(satirlar)[:10],
        hata=_kirp(report.get("summary")),
        **ortak,
    )


def _kararsiz_mi(tests: list[Mapping[str, Any]]) -> bool:
    """Aynı başlıklı testin (repeat-each tekrarları) hem geçen hem kırmızı koşusu var mı?"""
    durumlar: dict[Any, set[bool]] = {}
    for t in tests:
        if t.get("status") == "skipped":
            continue
        durumlar.setdefault(t.get("title"), set()).add(t.get("status") in GECEN)
    return any(d == {True, False} for d in durumlar.values())


def _ayni_assertion(satirlar: list[dict[str, Any]]) -> bool:
    """Kırmızı tekrarların hepsi assertion mı ve her test tüm tekrarlarında aynı doğrulamada
    (satır, beklenen, gerçekleşen) mı kaldı?"""
    if not satirlar or any(s["tur"] != "assertion" for s in satirlar):
        return False
    testler: dict[Any, set[tuple[Any, ...]]] = {}
    for s in satirlar:
        testler.setdefault(s.get("test_adi"), set()).add(
            (s.get("satir"), s.get("beklenen"), s.get("gerceklesen"))
        )
    return all(len(a) == 1 for a in testler.values())


def kirma_sinifi(s: Siniflama) -> Siniflama:
    """Kırılmış (BREAK_CAMPAIGN) koşunun kayıt sınıfı: assertion kırmızısı beklenen kanıttır."""
    if s.sinif != "defect_adayi":
        return s
    return replace(s, sinif="kirma_beklenen_kirmizi", aciklama=ACIKLAMA["kirma_beklenen_kirmizi"])
