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
5. `test_data`     — test verisi ön koşulu sağlanamadı (seed/reset/fixture hatası).

Hiçbiri eşleşmezse karar `None` döner ve çağıran LLM'e gider (§8.6 adım 3). Sayısal güven yoktur;
her karar eşleşen sinyallerin listesini taşır (`{kod, aciklama, kaynak, kanit}`).

Kural 3 dış ölçüm (sembol tablosu + locator yoklaması) ister: motor bunu yalnızca 1–2 eşleşmediğinde
ve hata gerçekten locator hatasıyken `locator_analizi` geri çağrısıyla ister.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

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


def sinyal(kod: str, aciklama: str, kaynak: str, kanit: Any = None) -> dict[str, Any]:
    return {
        "kod": kod,
        "aciklama": temiz(aciklama, 300),
        "kaynak": kaynak,
        "kanit": temiz(kanit, 500) if kanit not in (None, "") else None,
    }


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

    def tur(self) -> str:
        """Biçimsel tür: runner'ınki, yoksa mesaj kalıbından."""
        if self.hata_turu:
            return self.hata_turu
        m = self.mesaj or ""
        if _VERI_RE.search(m):
            return "test_data"
        if _AG_RE.search(m):
            return "navigation"
        if _ASSERTION_RE.search(m) and (self.gerceklesen is not None or "Received" in m):
            return "assertion"
        if _LOCATOR_MESAJ_RE.search(m.partition("Call log:")[0]):
            return "locator_timeout" if "Timeout" in m else "locator_not_found"
        return "other"


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
        if self.oneri is not None and self.sinif == "test_maintenance":
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
                    "Ağ / sayfa yükleme hatası (uygulamaya erişilemedi)",
                    "Playwright hata mesajı",
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
    # Tekrarlar tutarlı olmalı: her kırmızı tekrar aynı doğrulamada aynı değerle kaldı.
    if len(set(g.tekrar_degerleri)) > 1:
        return []
    out = [
        sinyal(
            "assertion_farki",
            f"Beklenen {g.beklenen}, gerçekleşen {g.gerceklesen}",
            "Playwright hata mesajı",
            (g.matcher and f"expect(...).{g.matcher}")
            or (mesaj.splitlines()[0] if mesaj else None),
        ),
        sinyal(
            "eleman_bulundu",
            "Doğrulanan eleman sayfada bulundu ve değeri okundu (locator hatası değil)",
            "Playwright hata mesajı",
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


def veri_kurali(g: Girdi) -> list[dict[str, Any]]:
    """Kural 5: test verisi ön koşulu."""
    if g.testsiz:
        return []
    if g.tur() == "test_data" or _VERI_RE.search(g.mesaj or ""):
        return [
            sinyal(
                "veri_on_kosulu",
                "Test verisi ön koşulu sağlanamadı (sıfırlama / fixture hatası)",
                "Playwright hata mesajı",
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
    parcalar = [g.tur() if not g.testsiz else "kosu", yer, g.test_adi, hedef]
    return temiz(" · ".join(p for p in parcalar if p), 400)
