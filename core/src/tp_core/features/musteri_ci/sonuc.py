"""`tp-results` artefaktının alımı ve ayrıştırılması (TASARIM test-dilleri §3.3, §3.4).

Müşteri iş akışı (rules/ci-sablonlari) koşu sonunda **her durumda** `tp-results` artefaktını
yükler:

    ci-meta.json            {platform, dil, sha, run_id, job, durum, exit_code}
    junit/*.xml             Android: Gradle `androidTest-results/connected/**/TEST-*.xml`
                            kopyaları; iOS: `xcresult_junit.py` çıktısı `xcresult-junit.xml`
    ekler/**                ekran görüntüleri / xcresult ekleri
    derleme.log             derleme/koşu adımının son satırları (derleme hatası kesiti)

Artefakt güvenilmeyen test çıktısıdır: zip `clients._zip_dosyalari` / `safe_extract_zip` ile
okunur, JUnit `parse.parse_junit` ile (DTD yok, boyut sınırlı) ayrıştırılır. Gradle'ın özgün yol
düzeni de kabul edilir (`parse.gradle_androidtest_yolu_mu`).
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tp_core.features.ci.parse import (
    MAX_RAPOR_BAYT,
    MAX_SUREFIRE_DOSYA,
    MAX_TEST,
    Ayristirma,
    RaporHatasi,
    TestSatiri,
    _guvenli_parcalar,
    merge,
    musteri_ci_junit_yolu_mu,
    parse_junit,
    sayilar,
    temiz,
)
from tp_core.features.musteri_ci.sozlesme import (
    CI_META_AD,
    DERLEME_LOG_AD,
    EK_DIZINI,
    JUNIT_DIZINI,
    TP_RESULTS_ARTIFACT,
    hedef,
    sonuc_koku,
)

log = logging.getLogger(__name__)

KimlikDonusturucu = Callable[[TestSatiri], TestSatiri]

MAX_TOPLAM_BAYT = 200 * 1024 * 1024  # okunan JUnit + meta + log toplamı
MAX_META_BAYT = 64 * 1024
MAX_LOG_BAYT = 512 * 1024
MAX_EK_LISTE = 500
SHA_RE = re.compile(r"[0-9a-f]{40}")
META_ALANLARI = ("platform", "dil", "sha", "run_id", "run_attempt", "job", "durum", "exit_code")


@dataclass
class MusteriCiSonucu:
    """tp-results ayrıştırması. `ayristirma` None: JUnit yok (derleme hatası ya da artefakt yok)."""

    platform: str
    dil: str
    ayristirma: Ayristirma | None
    meta: dict[str, Any] = field(default_factory=dict)
    junit_dosyalari: list[str] = field(default_factory=list)
    ekler: list[str] = field(default_factory=list)
    derleme_kesiti: str | None = None
    uyarilar: list[str] = field(default_factory=list)
    yerel: dict[str, Any] | None = None  # github_artifacts.hazirla sonucu (yerel kopya)

    @property
    def sayac(self) -> dict[str, int] | None:
        """`parse.sayilar` biçimi; JUnit yoksa None."""
        return sayilar(self.ayristirma.testler) if self.ayristirma is not None else None


def tp_results_sec(artefaktlar: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Koşunun artefakt listesinden süresi dolmamış `tp-results` (yoksa None)."""
    return next(
        (
            a
            for a in artefaktlar
            if isinstance(a, Mapping)
            and a.get("name") == TP_RESULTS_ARTIFACT
            and not a.get("expired")
        ),
        None,
    )


def _meta(ham: bytes | None, uyarilar: list[str]) -> dict[str, Any]:
    if not ham:
        uyarilar.append(f"{CI_META_AD} yok.")
        return {}
    if len(ham) > MAX_META_BAYT:
        uyarilar.append(f"{CI_META_AD} çok büyük, okunmadı.")
        return {}
    try:
        m = json.loads(ham.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        uyarilar.append(f"{CI_META_AD} okunamadı.")
        return {}
    if not isinstance(m, dict):
        uyarilar.append(f"{CI_META_AD} nesne değil.")
        return {}
    return {k: temiz(m.get(k), 200) for k in META_ALANLARI if m.get(k) not in (None, "")}


def _meta_dogrula(
    meta: Mapping[str, Any], platform: str, dil: str, beklenen_sha: str | None
) -> list[str]:
    out: list[str] = []
    for alan, beklenen in (("platform", platform), ("dil", dil)):
        deger = meta.get(alan)
        if deger and deger != beklenen:
            out.append(f"{CI_META_AD} {alan}={deger!r}, beklenen {beklenen!r}.")
    sha = meta.get("sha")
    if beklenen_sha and sha and sha != beklenen_sha:
        out.append(
            f"{CI_META_AD} sha {sha[:12]} beklenen {beklenen_sha[:12]} değil "
            "(başka commit'in koşusu olabilir)."
        )
    return out


def _junit_sec(yollar: Sequence[str]) -> list[str]:
    """JUnit yolları; `junit/` kopyaları varsa yalnız onlar (Gradle özgün yolu aynı raporun
    ikinci kopyası olabilir)."""
    adaylar = sorted(y for y in yollar if musteri_ci_junit_yolu_mu(y))
    kopyalar = [y for y in adaylar if JUNIT_DIZINI in y.split("/")[:-1]]
    return kopyalar or adaylar


def _ek_mi(yol: str) -> bool:
    parcalar = _guvenli_parcalar(yol)
    return bool(parcalar) and EK_DIZINI in parcalar[:-1]


def _ada_gore(dosyalar: Mapping[str, bytes], ad: str) -> bytes | None:
    adaylar = [y for y in dosyalar if y.rsplit("/", 1)[-1] == ad and _guvenli_parcalar(y)]
    if not adaylar:
        return None
    return dosyalar[min(adaylar, key=lambda y: (y.count("/"), len(y), y))]


def tp_results_ayristir(
    dosyalar: Mapping[str, bytes],
    platform: str,
    dil: str,
    *,
    kimlik: KimlikDonusturucu | None = None,
    beklenen_sha: str | None = None,
    ek_yollari: Sequence[str] = (),
) -> MusteriCiSonucu:
    """Artefakt içi yol → bayt eşlemesinden ayrıştırma (zip ya da yerel kopya aynı).

    `kimlik`: dil şeridinin test kimliği dönüşümü (JUnit `classname`/`name` → script'in
    `dosya`/`test_adi`; Ş3 Kotlin, Ş4 Swift verir). `beklenen_sha`: ci-meta.json'daki sha farklıysa
    uyarı (yanlış koşunun artefaktı). `ek_yollari`: baytları okunmamış ek dosyalarının yolları
    (zip listesi); `dosyalar` içindeki `ekler/**` de eklenir."""
    hedef(platform, dil)  # müşteri CI hattı değilse MusteriCiHatasi
    uyarilar: list[str] = []
    meta = _meta(_ada_gore(dosyalar, CI_META_AD), uyarilar)
    uyarilar.extend(_meta_dogrula(meta, platform, dil, beklenen_sha))
    junit_yollari = _junit_sec(list(dosyalar))
    if len(junit_yollari) > MAX_SUREFIRE_DOSYA:
        uyarilar.append(
            f"{len(junit_yollari)} JUnit raporundan yalnızca {MAX_SUREFIRE_DOSYA} okundu."
        )
        junit_yollari = junit_yollari[:MAX_SUREFIRE_DOSYA]
    satirlar: list[TestSatiri] = []
    okunan: list[str] = []
    for y in junit_yollari:
        ad = temiz(y.rsplit("/", 1)[-1], 120)
        try:
            satirlar.extend(parse_junit(dosyalar[y]))
            okunan.append(y)
        except RaporHatasi as exc:
            uyarilar.append(f"{ad}: {temiz(exc, 200)}")
        except Exception as exc:  # güvenilmeyen girdi: okunamayan rapor yalnızca uyarı
            uyarilar.append(f"{ad}: ayrıştırılamadı ({temiz(exc, 200)})")
        if len(satirlar) >= MAX_TEST:
            uyarilar.append(f"Test sayısı üst sınırı ({MAX_TEST}) aşıldı; kalan raporlar okunmadı.")
            break
    if kimlik is not None:
        donusmus: list[TestSatiri] = []
        for t in satirlar[:MAX_TEST]:
            try:
                donusmus.append(kimlik(t))
            except Exception as exc:  # dil şeridinin hatası alımı düşürmez
                uyarilar.append(f"test kimliği dönüştürülemedi ({temiz(exc, 120)}): {t.test_adi}")
                donusmus.append(t)
        satirlar = donusmus
    ayr: Ayristirma | None = None
    if okunan:
        ayr = Ayristirma(
            testler=merge(satirlar[:MAX_TEST], None),
            uyarilar=[],
            istatistik={},
            raporlar={"junit": True, "json": False},
        )
    elif not junit_yollari:
        uyarilar.append("tp-results içinde JUnit raporu yok.")
    ekler = sorted({*(y for y in dosyalar if _ek_mi(y)), *(y for y in ek_yollari if _ek_mi(y))})
    if len(ekler) > MAX_EK_LISTE:
        uyarilar.append(f"{len(ekler)} ekten yalnızca {MAX_EK_LISTE} listelendi.")
        ekler = ekler[:MAX_EK_LISTE]
    ham_log = _ada_gore(dosyalar, DERLEME_LOG_AD)
    kesit = derleme_kesiti(ham_log[-MAX_LOG_BAYT:], dil) if ham_log else None
    if ayr is not None:
        ayr.uyarilar = list(uyarilar)
    return MusteriCiSonucu(
        platform=platform,
        dil=dil,
        ayristirma=ayr,
        meta=meta,
        junit_dosyalari=okunan,
        ekler=ekler,
        derleme_kesiti=kesit,
        uyarilar=uyarilar,
    )


def _zip_oku(veri: bytes) -> tuple[dict[str, bytes], list[str], list[str]]:
    """tp-results zip'inden JUnit + meta + log baytları (sınırlı), ek yolları ve uyarılar."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(veri))
    except zipfile.BadZipFile as exc:
        raise RaporHatasi(f"tp-results zip'i bozuk: {exc}") from exc
    dosyalar: dict[str, bytes] = {}
    ek_yollari: list[str] = []
    uyarilar: list[str] = []
    toplam = 0
    junit_sayi = 0
    with zf:
        for info in zf.infolist():
            ad = info.filename
            if info.is_dir() or _guvenli_parcalar(ad) is None:
                continue
            son = ad.rsplit("/", 1)[-1]
            if _ek_mi(ad):
                if len(ek_yollari) < MAX_EK_LISTE * 2:
                    ek_yollari.append(ad)
                continue
            if son == CI_META_AD:
                sinir = MAX_META_BAYT
            elif son == DERLEME_LOG_AD:
                sinir = MAX_RAPOR_BAYT
            elif musteri_ci_junit_yolu_mu(ad):
                if junit_sayi >= MAX_SUREFIRE_DOSYA * 2:
                    continue
                junit_sayi += 1
                sinir = MAX_RAPOR_BAYT
            else:
                continue
            if info.file_size > sinir or toplam + info.file_size > MAX_TOPLAM_BAYT:
                uyarilar.append(f"{temiz(son, 120)}: çok büyük ({info.file_size} bayt), okunmadı")
                continue
            icerik = zf.read(info)
            if son == DERLEME_LOG_AD and len(icerik) > MAX_LOG_BAYT:
                icerik = icerik[-MAX_LOG_BAYT:]
            toplam += len(icerik)
            dosyalar[ad] = icerik
    return dosyalar, ek_yollari, uyarilar


def tp_results_zip_ayristir(
    veri: bytes,
    platform: str,
    dil: str,
    *,
    kimlik: KimlikDonusturucu | None = None,
    beklenen_sha: str | None = None,
) -> MusteriCiSonucu:
    """tp-results zip baytlarından `tp_results_ayristir` (sınırlı okuma). Bozuk zip
    `RaporHatasi`."""
    dosyalar, ek_yollari, okuma_uyarilari = _zip_oku(veri)
    sonuc = tp_results_ayristir(
        dosyalar, platform, dil, kimlik=kimlik, beklenen_sha=beklenen_sha, ek_yollari=ek_yollari
    )
    sonuc.uyarilar[:0] = okuma_uyarilari
    if sonuc.ayristirma is not None:
        sonuc.ayristirma.uyarilar[:0] = okuma_uyarilari
    return sonuc


def tp_results_al(
    gh: Any,
    workflow_run: Mapping[str, Any],
    platform: str,
    dil: str,
    *,
    kimlik: KimlikDonusturucu | None = None,
    yerel_kopya: bool = True,
) -> MusteriCiSonucu:
    """Tamamlanmış müşteri iş akışı koşusunun tp-results'ını indirir ve ayrıştırır.

    `gh`: `ci.clients.GitHubCi` (yalnız `artifacts`, `artifact_zip` kullanılır). `yerel_kopya`:
    portal raporları GitHub'a gitmeden açabilsin diye `github_artifacts.hazirla` ile
    `src/<platform>-<dil>/results/` düzenine yerel kopya. Hata fırlatmaz: artefakt yoksa
    `ayristirma=None` + uyarı."""
    hedef(platform, dil)
    sha = workflow_run.get("head_sha")
    beklenen = str(sha) if isinstance(sha, str) and SHA_RE.fullmatch(sha) else None
    bos = MusteriCiSonucu(platform=platform, dil=dil, ayristirma=None)
    try:
        artefaktlar = gh.artifacts(workflow_run["id"])
    except Exception as exc:  # GitHubCiError + beklenmeyen: alım düşmez
        bos.uyarilar.append(f"artefakt listesi alınamadı: {temiz(exc, 200)}")
        return bos
    art = tp_results_sec(artefaktlar)
    if art is None:
        bos.uyarilar.append(f"'{TP_RESULTS_ARTIFACT}' artefaktı yok ya da süresi dolmuş.")
        return bos
    try:
        veri = gh.artifact_zip(art)
        sonuc = tp_results_zip_ayristir(veri, platform, dil, kimlik=kimlik, beklenen_sha=beklenen)
    except Exception as exc:
        bos.uyarilar.append(f"'{TP_RESULTS_ARTIFACT}' okunamadı: {temiz(exc, 200)}")
        return bos
    if yerel_kopya:
        from tp_core.features.ci import github_artifacts

        dizin = github_artifacts.dizin_adi(workflow_run.get("id"), workflow_run.get("run_attempt"))
        if dizin is None:
            sonuc.yerel = {"dizin": None, "durum": "hata", "hata": "GitHub koşu kimliği yok"}
        else:
            sonuc.yerel = github_artifacts.hazirla(
                gh,
                [art],
                dizin,
                sonuc_zip=veri,
                sonuc_adi=TP_RESULTS_ARTIFACT,
                sonuc_kok=sonuc_koku(platform, dil),
                rapor_adi=None,
            )
    return sonuc


# Derleme/koşu logunda hata satırı kalıpları (dil başına; ortak olanlar her dilde).
_ORTAK_KALIPLAR = (
    r"^FAILURE:",
    r"^BUILD FAILED",
    r"^\*\* (?:TEST|BUILD) FAILED \*\*",
    r"^Error:",
    r"^##\[error\]",
)
_DIL_KALIPLARI: dict[str, tuple[str, ...]] = {
    "kotlin": (r"^e: ", r"^> Task .* FAILED", r"^\s*What went wrong:", r"Compilation error"),
    "swift": (r"(?:^|\s)error: ", r"^Testing failed:", r"^\s*\S+\.swift:\d+:\d+: error"),
}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_ZAMAN_ONEKI = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ")
MAX_KESIT = 6000


def derleme_kesiti(log: str | bytes | None, dil: str, *, en_cok_satir: int = 40) -> str | None:
    """Derleme/koşu logundan hata kesiti (Kotlin `e: …`, Gradle `FAILURE:`, Swift `error:`,
    xcodebuild `** TEST FAILED **`); bulunamazsa son satırlar. Metin temizlenir ve kırpılır."""
    if not log:
        return None
    metin = log.decode("utf-8", "replace") if isinstance(log, bytes) else str(log)
    satirlar = [_ZAMAN_ONEKI.sub("", _ANSI.sub("", s)).rstrip() for s in metin.splitlines()]
    satirlar = [s for s in satirlar if s.strip()]
    if not satirlar:
        return None
    kaliplar = [re.compile(k) for k in (*_DIL_KALIPLARI.get(dil, ()), *_ORTAK_KALIPLAR)]
    secili: list[int] = []
    for i, s in enumerate(satirlar):
        if any(k.search(s) for k in kaliplar):
            # Eşleşen satır + bağlam (sonraki 2 satır: Gradle "What went wrong" açıklaması).
            for j in range(i, min(i + 3, len(satirlar))):
                if j not in secili:
                    secili.append(j)
        if len(secili) >= en_cok_satir:
            break
    if not secili:
        secili = list(range(max(0, len(satirlar) - en_cok_satir), len(satirlar)))
    kesit = "\n".join(satirlar[i] for i in secili[:en_cok_satir])
    return temiz(kesit, MAX_KESIT) or None
