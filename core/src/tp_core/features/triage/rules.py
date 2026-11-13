"""Deterministik triage kuralları (TEKNIK-TASARIM §8.6 adım 2; Constitution XI). AI yok.

Kurallar **sırayla** denenir; ilk eşleşen karar verir:

1. `environment`   — koşu öncesi sağlık kontrolü başarısız (`saglik.ok=false`), sağlıksız `error`
                     koşusu, çalışan uygulama commit'le eşleşmiyor ya da ağ/gezinme hatası.
2. `flaky`         — Playwright `flaky` (yeniden denemede geçti) ya da aynı testin tekrarlarının bir
                     kısmı geçti.
3. `test_maintenance/locator` — locator 0 eleman döndürdü **ve** niyetteki rol + ad (sembol
                     tablosundan) hata anındaki aria snapshot'ında var **ve** çalışan uygulamada
                     (toolchain `/locator-probe`, `within` kapsamıyla, sha eşleşmesi gözetilerek)
                     o elemanın `data-testid`'si farklı → öneri `{locator_key, old_testid,
                     new_testid}`.
4. `product_defect` — assertion farkı (beklenen ≠ gerçekleşen) ve sayfa yapısı beklendiği gibi
                     (eleman bulundu, değer okundu, sayfa snapshot'ı var; tekrarlar tutarlı).
                     012 §4.4: hatanın case'ine ait onaylı karar tablosu kontrolü (`Girdi.oracle`)
                     varsa karar tablosuyla inceltilir (`karar_tablosu_karari`, kural
                     `karar_tablosu`): beklenti = tablo ≠ gerçekleşen → `product_defect`;
                     beklenti ≠ tablo = gerçekleşen → `test_maintenance/beklenti` (case
                     düzeltilmeli; bug taslağı ve locator onarımı yok); ikisi de ≠ tablo →
                     `product_defect`. Tablo yok / eşleşme yok / başarısız adım belirlenemedi
                     (`triage.adim`) / case içeriğinde kayıtlı oracle istisnası var → yukarıdaki
                     davranış aynen.
5. `test_data`     — test verisi ön koşulu sağlanamadı (seed/reset/fixture hatası).

Java / Appium testleri (009 mobil-masaüstü; `triage.java`) aynı kurallardan geçer: oturum /
bağlantı hatası → 1; `NoSuchElementException` / `TimeoutException` (eylem ön koşulu) → 3'ün ön
koşulu (öneri sayfa kaynağından, `service.java_locator_analizi`); `java.lang.AssertionError`
("beklenen <X>, görülen <Y>") + eleman okundu → 4.

Web + Java testleri (011 üretim dili; Playwright for Java + TestNG, `triage.java_web`): "Java mı"
sorusu dile bakar (`Girdi.dil`), araç/ortam sorusu platforma. Kalıplar: bağlantı / `net::ERR_` →
1; `com.microsoft.playwright.TimeoutError` / "waiting for locator" / `Locator.click: Timeout` → 3'ün
ön koşulu (öneri hata anı DOM'undan, `service.web_java_locator_analizi`); `AssertionFailedError` /
`AssertionError` + eleman okundu → 4.

Hiçbiri eşleşmezse karar `None` döner ve çağıran LLM'e gider (§8.6 adım 3). Sayısal güven yoktur;
her karar eşleşen sinyallerin listesini taşır (`{kod, aciklama, kaynak, kanit}`).

Kural 3 dış ölçüm (sembol tablosu + locator yoklaması) ister: motor bunu yalnızca 1–2 eşleşmediğinde
ve hata gerçekten locator hatasıyken `locator_analizi` geri çağrısıyla ister.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from tp_core.features.karar_tablosu.ifade import esit_mi, sayi_ayristir
from tp_core.features.triage.evidence import temiz

LOCATOR_0_TURLERI = frozenset({"locator_not_found", "locator_timeout"})
GECEN_DURUMLAR = frozenset({"passed", "expected", "flaky"})
KIRMIZI_DURUMLAR = frozenset({"failed", "timedOut", "timedout", "interrupted", "unexpected"})

_AG_RE = re.compile(
    r"net::ERR_|ECONNREFUSED|ECONNRESET|ENOTFOUND|EAI_AGAIN|ETIMEDOUT|socket hang up"
    r"|page\.goto: Timeout|NS_ERROR_",
    re.I,
)
_VERI_RE = re.compile(
    r"POST /test/(?:reset|break) başarısız|sepet temizliği için giriş başarısız"
    r"|sepet boşaltılamadı|DEMOAPP_TEST_TOKEN|seed (?:hatası|başarısız)",
    re.I,
)
_BULUNAMADI_RE = re.compile(r"element\(s\) not found|resolved to 0 elements", re.I)
_ASSERTION_RE = re.compile(r"expect\([^)]*\)\.\w+", re.I)
_LOCATOR_MESAJ_RE = re.compile(
    r"element\(s\) not found|resolved to 0 elements|locator\.\w+: Timeout \d+ms exceeded", re.I
)


def sinyal(
    kod: str, aciklama: str, kaynak: str, kanit: Any = None, *, baslik: str | None = None
) -> dict[str, Any]:
    """Eşleşen sinyal. `baslik` (isteğe bağlı): insan için tek satırlık başlık; ayrıntı
    `aciklama`'dadır (012 karar tablosu sinyalleri)."""
    out = {
        "kod": kod,
        "aciklama": temiz(aciklama, 300),
        "kaynak": kaynak,
        "kanit": temiz(kanit, 500) if kanit not in (None, "") else None,
    }
    if baslik:
        out["baslik"] = temiz(baslik, 160)
    return out


KARAR_TABLOSU_KURALI = "karar_tablosu"
BEKLENTI_ALT_TURU = "beklenti"
BEKLENTI_ONERISI = "Case'in beklenen değeri onaylı karar tablosuyla uyuşmuyor; case düzeltilmeli."
BEKLENTI_ONERI_YOK = (
    "Test beklentisi onaylı karar tablosundan farklı, uygulama tabloya uygun: bug taslağı ve "
    "locator onarımı açılmaz. " + BEKLENTI_ONERISI
)
# Review tur 1 O7: tablo tek doğruluk kaynağı değildir; uygulama ile tablo aynı yanlış okumayı
# paylaşabilir ("6 al 1 bedava" belirsiz). `test_maintenance/beklenti` kararına eklenir.
TABLO_SUPHESI = (
    "Tablo da yanlış olabilir; uygulama ile tablo aynı yanlış okumayı paylaşıyor olabilir"
)


@dataclass(frozen=True)
class OracleKarsilastirma:
    """Case'in güncel onaylı içeriğine ait `case_oracle_kontrol` karşılaştırması (012 §4.3).

    `case_degeri` / `tablo_degeri` `ayrintilar.gruplar[].karsilastirmalar[]`'dan gelir (sayı metni,
    sayı, metin ya da mantıksal). `tolerans` tablonun o çıktı kolonundaki toleransıdır.
    """

    case_degeri: Any
    tablo_degeri: Any
    column: str | None = None
    alan: str | None = None
    tablo_id: str | None = None
    tablo_ad: str | None = None
    tolerans: Decimal = Decimal(0)
    test_case_id: str | None = None  # kanıt: hangi case
    icerik_hash: str | None = None  # kanıt: case'in kontrol edilen (onaylı) içerik hash'i
    tablo_ref: str | None = None  # `T<sira_no>` (başlık)
    satir_id: str | None = None  # tablonun seçilen satırı (`R2`)
    girdiler: tuple[tuple[str, Any], ...] = ()  # satırı seçen girdiler: ((kolon, değer), …)


@dataclass
class Girdi:
    """Tek başarısız testin (ya da testsiz koşunun) deterministik girdileri."""

    test_adi: str
    dosya: str | None = None
    satir: int | None = None
    sonuc: str = "failed"  # test_result.sonuc (passed|failed|flaky|skipped|timedout) ya da "kosu"
    hata_turu: str | None = None  # test-runner failure.type
    mesaj: str | None = None
    beklenen: str | None = None
    gerceklesen: str | None = None
    matcher: str | None = None
    locator: str | None = None
    adim: str | None = None
    konum: str | None = None
    page_location: str | None = None
    aria: str | None = None
    aria_kapsami: str | None = None
    saglik: Mapping[str, Any] | None = None
    run_sonuc: str | None = None
    uygulama_farkli: str | None = None  # çalışan uygulama ≠ commit (gerekçe)
    tekrar_durumlari: list[str] = field(default_factory=list)  # repeat-each durumları
    tekrar_degerleri: list[tuple[Any, ...]] = field(default_factory=list)  # (satır, exp, rec)
    deneme_durumlari: list[str] = field(default_factory=list)  # retry denemeleri
    kirma: bool = False
    testsiz: bool = False  # koşu test üretmeden bitti (sağlık / runner)
    runner_hata: str | None = None
    # 009: hedef platform (web | android | ios | windows; None = bilinmiyor) ve Java kanıtı.
    platform: str | None = None
    sayfa_kaynagi: str | None = None  # hata anı sayfa kaynağı XML'i (güvenilmeyen)
    sayfa_kaynagi_rel: str | None = None
    # 011: üretim dili (ts | java; None = bilinmiyor) ve web + Java hata anı DOM'u (sayfa.html).
    dil: str | None = None
    sayfa_html: str | None = None
    sayfa_html_rel: str | None = None
    # 012 §4.4: hatanın bağlı olduğu case'in onaylı içeriğine ait karar tablosu karşılaştırmaları
    # (yoksa None; service `_oracle_ekle` doldurur).
    oracle: list[OracleKarsilastirma] | None = None
    # Başarısız doğrulamanın case alanları (`triage.adim.hata_alanlari`; ör.
    # {"steps[3].expected", "expected_result"}). None: belirlenemedi → karar tablosu inceltmesi yok.
    adim_alanlari: frozenset[str] | None = None
    adim_yolu: list[str] = field(default_factory=list)  # Playwright `failure.step.path`
    test_satiri: int | None = None  # `failure.test_location.line` (testin kendi dosyasında)

    @property
    def java(self) -> bool:
        """Java testi mi (Appium ya da web + Playwright for Java)? (`triage.java.java_mi`)."""
        from tp_core.features.triage.java import java_mi

        return java_mi(self.platform, self.dosya, self.mesaj, self.dil)

    @property
    def web_java(self) -> bool:
        """Web + Java (Playwright for Java) testi mi? Kanıt web yöntemiyle (trace / DOM) okunur."""
        from tp_core.features.triage.java import UYGULAMA_PLATFORMLARI

        return self.platform not in UYGULAMA_PLATFORMLARI and (
            self.dil == "java" or (self.platform == "web" and self.java)
        )

    @property
    def kaynak_adi(self) -> str:
        """Sinyal kaynağının adı (hata metni Playwright'ın mı, Java testinin mi)."""
        if self.web_java:
            return "Playwright for Java hata mesajı"
        return "Java/Appium hata mesajı" if self.java else "Playwright hata mesajı"

    def tur(self) -> str:
        """Biçimsel tür: runner'ınki, yoksa mesaj kalıbından."""
        if self.hata_turu:
            return self.hata_turu
        m = self.mesaj or ""
        if _VERI_RE.search(m):
            return "test_data"
        if self.web_java:
            from tp_core.features.triage.java_web import playwright_java_turu

            pw = playwright_java_turu(m)
            if pw is not None:
                return pw
        if self.java:
            java = _java_turu(m)
            if java is not None:
                return java
        if _AG_RE.search(m):
            return "navigation"
        if _ASSERTION_RE.search(m) and (self.gerceklesen is not None or "Received" in m):
            return "assertion"
        if _LOCATOR_MESAJ_RE.search(m.partition("Call log:")[0]):
            return "locator_timeout" if "Timeout" in m else "locator_not_found"
        return "other"


def _java_turu(m: str) -> str | None:
    """Java/Appium hata metni → test-runner `failure.type` sözlüğü (yoksa None)."""
    from tp_core.features.codegen.classify import java_hata_turu

    tur = java_hata_turu(m)
    if tur == "ortam":
        return "test_data" if _VERI_RE.search(m) else "navigation"
    if tur == "assertion":
        return "assertion"
    if tur == "locator":
        ilk = m.lstrip().splitlines()[0] if m.strip() else ""
        if "StaleElementReference" in ilk:
            return "other"  # eleman bulundu ama bayatladı: 0 eleman değil
        return "locator_timeout" if "TimeoutException" in ilk else "locator_not_found"
    return None


@dataclass
class LocatorAnalizi:
    """Kural 3'ün dış ölçümü (sembol tablosu + aria + locator yoklaması)."""

    oneri: dict[str, Any] | None
    sinyaller: list[dict[str, Any]]
    neden: str | None = None  # öneri üretilmediyse Türkçe gerekçe


@dataclass
class Karar:
    sinif: str
    alt_tur: str | None
    kural: str | None
    sinyaller: list[dict[str, Any]]
    karar_kaynagi: str = "rule"
    gerekce: str | None = None
    oneri: dict[str, Any] | None = None
    oneri_yok_nedeni: str | None = None

    @property
    def oneri_turu(self) -> str:
        if (
            self.oneri is not None
            and self.sinif == "test_maintenance"
            and self.alt_tur != BEKLENTI_ALT_TURU
        ):
            return "locator_fix"
        if self.sinif == "product_defect":
            return "bug_draft"
        return "none"


def _saglik_basarisiz(g: Girdi) -> dict[str, Any] | None:
    s = g.saglik
    if isinstance(s, Mapping) and s.get("ok") is False:
        parcalar = [str(s.get("hata") or "")]
        for uc in ("web", "api"):
            d = s.get(uc)
            if isinstance(d, Mapping) and (d.get("hata") or d.get("status")):
                parcalar.append(f"{uc}: {d.get('status')} {d.get('hata') or ''}".strip())
        return sinyal(
            "saglik_basarisiz",
            "Koşu öncesi sağlık kontrolü başarısız: Playwright başlatılmadı",
            "test-runner saglik",
            " · ".join(p for p in parcalar if p),
        )
    return None


def ag_sinyali_var(g: Girdi) -> bool:
    """Girdide ağ / sayfa yükleme hatası sinyali var mı (LLM `environment` doğrulaması için)."""
    if g.testsiz:
        return False
    return g.tur() == "navigation" or bool(_AG_RE.search(g.mesaj or ""))


def ortam_kurali(g: Girdi) -> list[dict[str, Any]]:
    """Kural 1: environment sinyalleri (boşsa eşleşmedi)."""
    out: list[dict[str, Any]] = []
    s = _saglik_basarisiz(g)
    if s:
        out.append(s)
    if g.testsiz and g.run_sonuc == "error" and not isinstance(g.saglik, Mapping):
        out.append(
            sinyal(
                "saglik_yok_hata",
                "Koşu test sonucu üretmeden hata ile bitti ve sağlık bloğu yok "
                "(test-runner/ağ erişilemedi)",
                "run",
                g.runner_hata,
            )
        )
    elif g.testsiz and g.run_sonuc == "error" and not out:
        out.append(
            sinyal(
                "kosu_tamamlanamadi",
                "Koşu test sonucu üretmeden hata ile bitti (runner süre aşımı / rapor yok)",
                "run",
                g.runner_hata,
            )
        )
    if g.uygulama_farkli:
        out.append(
            sinyal(
                "uygulama_sha_farkli",
                "Çalışan demo uygulaması koşulan commit'le eşleşmiyor; sonuç güvenilir değil",
                "toolchain /check app",
                g.uygulama_farkli,
            )
        )
    if not g.testsiz:
        tur = g.tur()
        if tur == "navigation" or _AG_RE.search(g.mesaj or ""):
            out.append(
                sinyal(
                    "ag_hatasi",
                    "Ağ / sayfa yükleme hatası (uygulamaya erişilemedi)"
                    if not g.java or g.web_java
                    else "Appium oturumu / bağlantı hatası (uygulamaya erişilemedi)",
                    g.kaynak_adi,
                    (g.mesaj or "").splitlines()[0] if g.mesaj else None,
                )
            )
    return out


def flaky_kurali(g: Girdi) -> list[dict[str, Any]]:
    """Kural 2: flaky sinyalleri."""
    out: list[dict[str, Any]] = []
    if g.sonuc == "flaky":
        out.append(
            sinyal(
                "playwright_flaky",
                "Playwright 'flaky': ilk deneme kırmızı, yeniden denemede geçti",
                "JSON rapor",
                " → ".join(g.deneme_durumlari) or None,
            )
        )
    elif g.deneme_durumlari and any(d in GECEN_DURUMLAR for d in g.deneme_durumlari):
        out.append(
            sinyal(
                "yeniden_denemede_gecti",
                "Yeniden denemelerden biri geçti",
                "JSON rapor",
                " → ".join(g.deneme_durumlari),
            )
        )
    gecen = sum(1 for d in g.tekrar_durumlari if d in GECEN_DURUMLAR)
    if gecen and gecen < len(g.tekrar_durumlari):
        out.append(
            sinyal(
                "tekrarlarin_bir_kismi_gecti",
                f"Aynı testin tekrarlarından {gecen}/{len(g.tekrar_durumlari)} geçti",
                "repeat-each",
                ", ".join(g.tekrar_durumlari),
            )
        )
    return out


def locator_adayi_mi(g: Girdi) -> bool:
    """Kural 3'ün ön koşulu: hata 0 eleman (bulunamadı / bulma zaman aşımı) türünde mi?"""
    if g.testsiz:
        return False
    return g.tur() in LOCATOR_0_TURLERI


def urun_yapisi_beklenen(g: Girdi) -> list[dict[str, Any]]:
    """Kural 4: assertion farkı + sayfa yapısı beklenen sinyalleri (boş → eşleşmedi)."""
    if g.testsiz or g.tur() != "assertion":
        return []
    if g.beklenen is None or g.gerceklesen is None:
        return []
    mesaj = g.mesaj or ""
    if _BULUNAMADI_RE.search(mesaj.partition("Call log:")[0]):
        return []
    if g.java and (g.gerceklesen == "(öğe yok)" or g.gerceklesen.startswith("(okunamadı")):
        return []  # Ekran.java: doğrulanan öğe bulunamadı/okunamadı — değer farkı değil
    # Tekrarlar tutarlı olmalı: her kırmızı tekrar aynı doğrulamada aynı değerle kaldı.
    if len(set(g.tekrar_degerleri)) > 1:
        return []
    out = [
        sinyal(
            "assertion_farki",
            f"Beklenen {g.beklenen}, gerçekleşen {g.gerceklesen}",
            g.kaynak_adi,
            (g.matcher and f"expect(...).{g.matcher}")
            or (mesaj.splitlines()[0] if mesaj else None),
        ),
        sinyal(
            "eleman_bulundu",
            "Doğrulanan eleman sayfada bulundu ve değeri okundu (locator hatası değil)",
            g.kaynak_adi,
            g.locator,
        ),
    ]
    if g.aria:
        out.append(
            sinyal(
                "sayfa_yapisi_beklenen",
                # Yalnızca snapshot'ın varlığı denetlenir; beklenen yapıyla karşılaştırma yapılmaz.
                "Hata anı aria snapshot'ı var (sayfa render edilmişti); beklenen yapıyla ayrıca "
                "karşılaştırılmadı",
                f"error-context aria snapshot ({g.aria_kapsami or 'bilinmiyor'})",
                None,
            )
        )
    if g.sayfa_kaynagi:
        out.append(
            sinyal(
                "sayfa_yapisi_beklenen",
                "Hata anı sayfa kaynağı var (ekran render edilmişti); beklenen yapıyla ayrıca "
                "karşılaştırılmadı",
                "Java kanıtı sayfa-kaynagi.xml",
                g.sayfa_kaynagi_rel,
            )
        )
    if g.sayfa_html:
        out.append(
            sinyal(
                "sayfa_yapisi_beklenen",
                "Hata anı DOM'u var (sayfa render edilmişti); beklenen yapıyla ayrıca "
                "karşılaştırılmadı",
                "Playwright for Java kanıtı sayfa.html",
                g.sayfa_html_rel,
            )
        )
    kirmizi = [d for d in g.tekrar_durumlari if d not in GECEN_DURUMLAR]
    if len(kirmizi) > 1:
        out.append(
            sinyal(
                "tutarli_tekrar",
                f"Tüm tekrarlar ({len(kirmizi)}/{len(g.tekrar_durumlari)}) aynı doğrulamada "
                "aynı değerle kaldı",
                "repeat-each",
                None,
            )
        )
    if g.kirma:
        out.append(
            sinyal(
                "kasitli_kirilma",
                "Koşu BREAK_CAMPAIGN ile kasıtlı kırılmış uygulamada yapıldı "
                "(hata yakalama kanıtı)",
                "run.ortam.break_campaign",
                None,
            )
        )
    return out


# ----------------------------------------------------------------------- 012 §4.4 karar tablosu

_DUZ_SAYI_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_TIRNAKLAR = ('"', "'", "`")
_MANTIK = {"true": True, "false": False, "doğru": True, "yanlış": False}
# Biçimli metindeki sayı adayı ("Toplam: 150,00 TL" → "150,00"). Kod parçası değildir: önünde harf,
# rakam ya da tire yoktur ("P-001" sayılmaz); tek başına eksi işareti alabilir.
_SAYI_ADAYI = re.compile(r"(?<![\w\-−])[-−+]?\d(?:[\d.,]*\d)?(?![\w])")


def _hata_degeri(metin: str | None, *, java_tostring: bool = False) -> Any:
    r"""Hata mesajındaki beklenen / gerçekleşen metin → karşılaştırılabilir değer (yoksa None).

    Playwright `Expected: "150,00 TL"` / `Expected substring: "…"` (tırnaklı), Java `beklenen
    <150,00 TL>` ve TestNG `expected [150.0]` biçimleri: tırnak atılır, sayı `sayi_ayristir` ile
    okunur (ekrandaki Türkçe yazım: `"1.250"` → 1250); sayı değilse kırpılmış metin döner (biçimli
    metindeki tek sayı karşılaştırmada `_uyarla` ile alınır). Düzenli ifade (`/…/`, Playwright
    `Expected pattern`) beklentisi değer değildir (None).

    `java_tostring` (TestNG `Assert` biçimi, `classify.testng_bicimi`): değer Java `toString()`
    çıktısıdır; `Double` / `BigDecimal` binlik ayırıcı kullanmaz, nokta her zaman ondalıktır. Bu
    yüzden düz `[+-]?\d+\.\d+` yazımı ondalık okunur: `expected [2.500]` (BigDecimal, ölçek 3) =
    2,5 — Türkçe binlik kuralı (`"2.500"` → 2500) yalnız ekran metnine uygulanır.
    """
    if metin is None:
        return None
    m = metin.strip()
    if len(m) >= 2 and m[0] == m[-1] and m[0] in _TIRNAKLAR:
        m = m[1:-1].strip()
    elif len(m) >= 2 and m.startswith("/") and m.rstrip("dgimsuvy").endswith("/"):
        return None
    if not m:
        return None
    if java_tostring and _DUZ_SAYI_RE.match(m):
        return Decimal(m)
    sayi = sayi_ayristir(m)
    return sayi if sayi is not None else m


def tek_sayi(metin: str) -> Decimal | None:
    """Biçimli metindeki tek sayı ("Toplam: 150,00 TL" → 150.00); sayı yoksa ya da birden çoksa
    (ör. "P-001 satırı 6 adet, 150,00 TL") None."""
    sayilar = [
        d for a in _SAYI_ADAYI.findall(metin) if (d := sayi_ayristir(a.rstrip(".,"))) is not None
    ]
    return sayilar[0] if len(sayilar) == 1 else None


def _oracle_degeri(deger: Any) -> Any:
    """Kontrol kaydındaki değer → karşılaştırılabilir değer (sayı `Decimal`; yoksa None).

    Kayıt sayıları metin olarak taşır (`Degerlendirme.as_dict`: `"150.00"`, nokta ondalık);
    düz ondalık yazım önce denenir, sonra ekran yazımı (`sayi_ayristir`)."""
    if deger is None or isinstance(deger, bool | Decimal):
        return deger
    if isinstance(deger, int | float):
        try:
            return Decimal(repr(deger)) if isinstance(deger, float) else Decimal(deger)
        except InvalidOperation:  # pragma: no cover - nan/inf JSON'dan gelmez
            return None
    if isinstance(deger, str):
        m = deger.strip()
        if _DUZ_SAYI_RE.match(m):
            return Decimal(m)
        sayi = sayi_ayristir(m)
        return sayi if sayi is not None else m
    return None


def _ayni_tur(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool)
    return isinstance(a, Decimal) == isinstance(b, Decimal)


def _uyarla(deger: Any, hedef: Any) -> Any:
    """Hata değerini tablo değerinin türüne uyarlar: mantıksal tabloda `true` / `false` metni
    mantıksala, sayısal tabloda biçimli metnin tek sayısı (`tek_sayi`) sayıya çevrilir."""
    if isinstance(hedef, bool) and isinstance(deger, str):
        return _MANTIK.get(deger.strip().casefold(), deger)
    if isinstance(hedef, Decimal) and isinstance(deger, str):
        sayi = tek_sayi(deger)
        return sayi if sayi is not None else deger
    return deger


def _esit(a: Any, b: Any, tolerans: Decimal) -> bool:
    try:
        return esit_mi(a, b, tolerans)
    except ValueError:
        return False


def _goster(deger: Any) -> str:
    """Sinyal metninde değer: mantıksal doğru/yanlış, ondalık sayı virgülle (`150,00`; Python
    biçimi `150.00` kullanıcıya gösterilmez — birleştirme turu 2 ekran turu)."""
    if isinstance(deger, bool):
        return "doğru" if deger else "yanlış"
    metin = str(deger)
    return metin.replace(".", ",") if re.fullmatch(r"-?\d+\.\d+", metin) else metin


def _kural_ozeti(o: OracleKarsilastirma, tablo: Any) -> str:
    """Başlıktaki kural: `T1 · R2: adet 6 → bedava_adet 0` (bilinmeyen parçalar atlanır)."""
    yer = " · ".join(p for p in (o.tablo_ref or o.tablo_ad or "karar tablosu", o.satir_id) if p)
    girdiler = ", ".join(f"{k} {_goster(v)}" for k, v in o.girdiler[:3])
    cikti = f"{o.column} {_goster(tablo)}" if o.column else _goster(tablo)
    return f"{yer}: {girdiler} → {cikti}" if girdiler else f"{yer}: {cikti}"


def karar_tablosu_karari(g: Girdi, urun: list[dict[str, Any]] | None = None) -> Karar | None:
    """Kural 4'ün karar tablosu inceltmesi (012 §4.4); uygulanamıyorsa None (bugünkü davranış).

    Yalnızca kural 4 eşleştiğinde çağrılır (`urun`: kural 4'ün sinyalleri; kararın sinyal listesinin
    başına konur, verilmezse yeniden hesaplanır). Yalnız **başarısız adıma ait** karşılaştırmalar
    (`alan` ∈ `g.adim_alanlari`; adım belirlenemediyse inceltme yok — review O6) ve hatanın
    beklenen değerine eşit `case_degeri` taşıyanlar alınır; tablo değerleri tek değilse (ya da
    eşleşme yoksa) karar verilmez. Kayıtlı istisnası olan case'in karşılaştırmaları servis
    tarafında hiç yüklenmez (`service.oracle_karsilastirmalari`; review K2).
    """
    if not g.oracle or not g.adim_alanlari:
        return None
    from tp_core.features.codegen.classify import testng_bicimi

    java_tostring = g.java and testng_bicimi(g.mesaj)
    beklenen = _hata_degeri(g.beklenen, java_tostring=java_tostring)
    gerceklesen = _hata_degeri(g.gerceklesen, java_tostring=java_tostring)
    if beklenen is None or gerceklesen is None:
        return None
    eslesen: list[tuple[OracleKarsilastirma, Any]] = []
    for o in g.oracle:
        if o.alan not in g.adim_alanlari:
            continue  # başka adımın karşılaştırması: değer tesadüfen eşit olabilir
        case_d, tablo_d = _oracle_degeri(o.case_degeri), _oracle_degeri(o.tablo_degeri)
        if case_d is None or tablo_d is None:
            continue
        if _esit(_uyarla(beklenen, case_d), case_d, o.tolerans):
            eslesen.append((o, tablo_d))
    if not eslesen:
        return None
    o, tablo = eslesen[0]
    if not all(_ayni_tur(t, tablo) and _esit(t, tablo, Decimal(0)) for _, t in eslesen[1:]):
        return None  # aynı beklenen değer farklı tablo değerlerine karşılık geliyor: belirsiz
    tolerans = max(x.tolerans for x, _ in eslesen)
    beklenen, gerceklesen = _uyarla(beklenen, tablo), _uyarla(gerceklesen, tablo)
    if not (_ayni_tur(beklenen, tablo) and _ayni_tur(gerceklesen, tablo)):
        return None  # gerçekleşen değer tablo değeriyle karşılaştırılamıyor
    beklenti_uyar = _esit(beklenen, tablo, tolerans)
    gercek_uyar = _esit(gerceklesen, tablo, tolerans)
    if beklenti_uyar and gercek_uyar:
        return None  # tolerans içinde ikisi de tabloya uyuyor: tablo ayırt etmiyor
    ad = o.tablo_ad or o.tablo_id or "karar tablosu"
    yer = f"'{ad}'" + (f" ({o.column})" if o.column else "")
    degerler = (
        f"test beklentisi {_goster(beklenen)}, gerçekleşen {_goster(gerceklesen)}, "
        f"tablo {_goster(tablo)}"
    )
    kural = _kural_ozeti(o, tablo)
    satir = " · ".join(
        p for p in (o.tablo_ref, o.satir_id, f"alan {o.alan}" if o.alan else "") if p
    )
    ek = f"; {satir}" if satir else ""
    kanit = " · ".join(
        p
        for p in (
            f"case_oracle_kontrol: test_case {o.test_case_id or '-'}",
            f"icerik_hash {o.icerik_hash or '-'}",
            f"tablo {o.tablo_id or '-'}",
            f"kolon {o.column}" if o.column else "",
            f"alan {o.alan}" if o.alan else "",
        )
        if p
    )
    kaynak = "onaylı karar tablosu (case_oracle_kontrol)"
    if urun is None:
        urun = urun_yapisi_beklenen(g)
    if beklenti_uyar:
        s = sinyal(
            "karar_tablosu_uyumlu",
            f"Test beklentisi onaylı karar tablosu {yer} ile aynı, uygulama tablodan farklı "
            f"değer üretti ({degerler}{ek})",
            kaynak,
            kanit,
            baslik=f"Uygulama onaylı kurala aykırı ({kural})",
        )
        return Karar("product_defect", None, KARAR_TABLOSU_KURALI, [*urun, s])
    if gercek_uyar:
        s = sinyal(
            "karar_tablosu_beklenti_farkli",
            f"Test beklentisi onaylı karar tablosu {yer} ile uyuşmuyor, uygulama tabloya uygun "
            f"({degerler}{ek})",
            kaynak,
            kanit,
            baslik=f"Test beklentisi onaylı kurala aykırı ({kural})",
        )
        suphe = sinyal(
            "karar_tablosu_tablo_suphesi",
            TABLO_SUPHESI,
            kaynak,
            None,
            baslik="Tablo da yanlış olabilir",
        )
        return Karar(
            "test_maintenance",
            BEKLENTI_ALT_TURU,
            KARAR_TABLOSU_KURALI,
            [*urun, s, suphe],
            gerekce=BEKLENTI_ONERISI,
            oneri_yok_nedeni=BEKLENTI_ONERI_YOK,
        )
    s = sinyal(
        "karar_tablosu_ikisi_de_farkli",
        f"Hem test beklentisi hem uygulama onaylı karar tablosu {yer} ile uyuşmuyor "
        f"({degerler}{ek})",
        kaynak,
        kanit,
        baslik=f"Test ve uygulama onaylı kurala aykırı ({kural})",
    )
    return Karar("product_defect", None, KARAR_TABLOSU_KURALI, [*urun, s])


def veri_kurali(g: Girdi) -> list[dict[str, Any]]:
    """Kural 5: test verisi ön koşulu."""
    if g.testsiz:
        return []
    if g.tur() == "test_data" or _VERI_RE.search(g.mesaj or ""):
        return [
            sinyal(
                "veri_on_kosulu",
                "Test verisi ön koşulu sağlanamadı (sıfırlama / fixture hatası)",
                g.kaynak_adi,
                (g.mesaj or "").splitlines()[0] if g.mesaj else None,
            )
        ]
    return []


def siniflandir(
    g: Girdi, locator_analizi: Callable[[Girdi], LocatorAnalizi | None] | None = None
) -> tuple[Karar | None, list[dict[str, Any]], str | None]:
    """Kuralları sırayla uygular.

    Dönüş: (karar | None, değerlendirilen ama karar vermeyen sinyaller, öneri yok nedeni).
    Karar None ise çağıran LLM'e gider; ek sinyaller LLM girdisine ve kayda eklenir.
    """
    ortam = ortam_kurali(g)
    if ortam:
        return Karar("environment", None, "environment", ortam), [], None
    flaky = flaky_kurali(g)
    if flaky:
        return Karar("flaky", None, "flaky", flaky), [], None
    ek: list[dict[str, Any]] = []
    neden: str | None = None
    if locator_adayi_mi(g):
        ek.append(
            sinyal(
                "locator_0_eleman",
                "Locator eleman bulamadı (0 eleman / bulma zaman aşımı)",
                "test-runner failure.type",
                g.locator or g.tur(),
            )
        )
        analiz = locator_analizi(g) if locator_analizi is not None else None
        if analiz is not None and analiz.oneri is not None:
            return (
                Karar(
                    "test_maintenance",
                    "locator",
                    "test_maintenance/locator",
                    ek + analiz.sinyaller,
                    oneri=analiz.oneri,
                ),
                [],
                None,
            )
        if analiz is not None:
            ek.extend(analiz.sinyaller)
            neden = analiz.neden
        else:
            neden = "Locator analizi yapılamadı"
    urun = urun_yapisi_beklenen(g)
    if urun:
        tablo = karar_tablosu_karari(g, urun)
        if tablo is not None:
            return tablo, ek, neden
        return Karar("product_defect", None, "product_defect", urun), ek, neden
    veri = veri_kurali(g)
    if veri:
        return Karar("test_data", None, "test_data", veri), ek, neden
    return None, ek, neden


def hata_imzasi(g: Girdi) -> str:
    """İnsan okunur, kararlı hata imzası (mükerrer araması girdisi: test, tür, sayfa/doğrulama)."""
    yer = f"{g.dosya}:{g.satir}" if g.dosya and g.satir else (g.dosya or "")
    hedef = g.matcher or ""
    if g.locator:
        from tp_core.features.triage.evidence import locator_test_idleri

        tids = locator_test_idleri(g.locator)
        if tids:
            hedef = f"{hedef} {tids[-1]}".strip()
    elif g.web_java:
        from tp_core.features.triage.java_web import kirik_kimlik

        kimlik, _kapsam, _belirsiz = kirik_kimlik(g.mesaj)
        if kimlik:
            hedef = f"{hedef} {kimlik}".strip()
    elif g.java:
        from tp_core.features.triage.java import kimlik_zinciri

        kimlik, _kapsam, _belirsiz = kimlik_zinciri(g.mesaj)
        if kimlik:
            hedef = f"{hedef} {kimlik}".strip()
    parcalar = [g.tur() if not g.testsiz else "kosu", yer, g.test_adi, hedef]
    return temiz(" · ".join(p for p in parcalar if p), 400)
