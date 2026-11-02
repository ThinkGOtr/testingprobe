"""Playwright raporlarını `test_result` satırlarına çevirir (TEKNIK-TASARIM §8.11). AI yok.

Girdi iki rapordur ve ikisi de **güvenilmeyen veridir** (test kodunun çıktısı):

- JUnit XML (`junit.xml`, zorunlu girdi §8.11): test adı, dosya, süre, failure/error/skipped.
  Yeniden deneme bilgisi taşımaz (Playwright JUnit yalnızca son sonucu yazar).
- JSON rapor (`results.json`): deneme sayısı (`retry`), `flaky` durumu, zaman aşımı, ekler
  (axe erişilebilirlik özeti `axe-<sayfa>.json`, trace/ekran görüntüsü yolları).

Birleştirme: her test (dosya + başlık yolu) için JSON varsa sonucu JSON'dan, yoksa JUnit'ten
alınır; yalnızca JUnit'te olan testler de eklenir (aynı adlı tekrarlar tek satırda toplanır, bir
tekrarın kalması kaybolmaz). Metinler kırpılır, ANSI kaçışları silinir,
ek dosya yolları yalnızca koşu dizini içindeyse (göreli) saklanır. XML/JSON boyutu sınırlıdır.

Sonuç eşlemesi (`test_result.sonuc`):
  JSON `expected` → passed · `flaky` → flaky · `skipped` → skipped ·
  `unexpected` → son deneme `timedOut` ise timedout, değilse failed.
  JUnit `<failure>`/`<error>` → failed · `<skipped>` → skipped · diğer → passed.
"""

from __future__ import annotations

import base64
import binascii
import fnmatch
import json
import os
import re
import stat
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_RAPOR_BAYT = 50 * 1024 * 1024
MAX_EK_BAYT = 1024 * 1024
MAX_HATA = 2000
MAX_AD = 500
MAX_TEST = 2000
MAX_EK = 20
AYIRAC = " › "
A11Y_EK_RE = re.compile(r"^axe-([A-Za-z0-9_.-]{1,80})\.json$")
ETKILER = ("critical", "serious", "moderate", "minor", "unknown")
# GitHub kipi: artefakttaki Playwright `error-context.md` (hata anı aria snapshot'ı). Sınırlar
# triage'ın yerel okumasıyla aynıdır (`triage.evidence.MAX_ERROR_CONTEXT` / `MAX_ARIA`).
ERROR_CONTEXT_AD = "error-context.md"
MAX_ERROR_CONTEXT = 2 * 1024 * 1024
MAX_ARIA = 20_000
_PAGE_SNAPSHOT_RE = re.compile(r"^# Page snapshot\s*\n+```(?:yaml)?\n(.*?)\n```", re.S | re.M)
_YAML_RE = re.compile(r"^```yaml\n(.*?)\n```", re.S | re.M)
# GitHub kipi: yeşil koşuda `locators.spec.ts`'in sayfa başına yazdığı `<sayfa>.aria.yml`
# (locator onarımının son yeşil aria kanıtı; repair `ARIA_DOSYA_KALIPLARI` ile aynı kalıplar,
# hata anı `error-context.md` hariç). Sınırı aşan dosya kesilmez, hiç alınmaz.
ARIA_DOSYA_KALIPLARI = ("*aria*.yml", "*aria*.yaml", "*.aria")
MAX_ARIA_DOSYA_BAYT = 512 * 1024
MAX_ARIA_DOSYA_SAYI = 50


class RaporHatasi(ValueError):
    """Rapor okunamadı / biçimi beklenen değil."""


def temiz(metin: Any, limit: int = MAX_HATA) -> str:
    s = CTRL_RE.sub("", ANSI_RE.sub("", str(metin if metin is not None else "")))
    return s if len(s) <= limit else s[:limit] + "…"


def _int(deger: Any) -> int:
    try:
        return max(int(float(deger)), 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class TestSatiri:
    """Ayrıştırılmış tek test (bir `test_result` + bir `test_result_ek` satırı)."""

    test_adi: str
    dosya: str | None
    sonuc: str
    sure_ms: int
    retry: int = 0
    hata_mesaji: str | None = None
    proje: str | None = None
    satir: int | None = None
    a11y: list[dict[str, Any]] = field(default_factory=list)
    ekler: list[dict[str, Any]] = field(default_factory=list)
    denemeler: list[dict[str, Any]] = field(default_factory=list)
    kaynak_rapor: str = "json"
    # GitHub kipi: hata anı bağlamı (artefakttaki error-context.md; `_hata_baglami`).
    hata_baglami: dict[str, Any] | None = None

    @property
    def anahtar(self) -> tuple[str, str]:
        return (self.dosya or "", self.test_adi)

    @property
    def a11y_ihlal(self) -> int:
        return sum(_int(s.get("ihlal")) for s in self.a11y)

    @property
    def a11y_kritik(self) -> int:
        return sum(_int((s.get("etki") or {}).get("critical")) for s in self.a11y)


@dataclass
class Ayristirma:
    testler: list[TestSatiri]
    uyarilar: list[str]
    istatistik: dict[str, int]
    raporlar: dict[str, bool]


def _oku(yol: Path | None, kok: Path | None = None) -> bytes | None:
    """Raporu güvenli okur: dosya güvenilmeyen test kodunun yazdığı dizindedir.

    - Sembolik bağ izlenmez (son bileşen `O_NOFOLLOW`; ara bileşenler `resolve()` ile koşu
      dizininin (`kok`) içinde kalmalı) → çekirdek koşu dizini dışındaki dosyaları okumaz.
    - Yalnızca normal dosya (`S_ISREG`): FIFO/aygıt (`/dev/zero`) reddedilir; açılış
      `O_NONBLOCK` ile yapılır, FIFO'da bloklanmaz.
    - Boyuta `st_size` ile güvenilmez: açık tanıtıcıdan en çok `MAX_RAPOR_BAYT + 1` bayt okunur.
    Dosya yoksa None; diğer her durum `RaporHatasi` (çağıran uyarıya çevirir).
    """
    if yol is None:
        return None
    ad = yol.name
    try:
        ls = os.lstat(yol)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RaporHatasi(f"rapor okunamadı: {ad}: {exc.strerror or exc}") from exc
    if stat.S_ISLNK(ls.st_mode):
        raise RaporHatasi(f"rapor okunmadı: {ad} sembolik bağ (koşu dizini dışına işaret edebilir)")
    if not stat.S_ISREG(ls.st_mode):
        raise RaporHatasi(f"rapor okunmadı: {ad} normal dosya değil")
    if kok is not None:
        try:
            kok_c = kok.resolve(strict=True)
            yol_c = yol.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RaporHatasi(f"rapor okunamadı: {ad}: yol çözülemedi") from exc
        if kok_c not in yol_c.parents:
            raise RaporHatasi(f"rapor okunmadı: {ad} koşu dizininin dışında")
    bayraklar = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(yol, bayraklar)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RaporHatasi(f"rapor okunamadı: {ad}: {exc.strerror or exc}") from exc
    try:
        fs = os.fstat(fd)
        if not stat.S_ISREG(fs.st_mode):
            raise RaporHatasi(f"rapor okunmadı: {ad} normal dosya değil")
        if fs.st_size > MAX_RAPOR_BAYT:
            raise RaporHatasi(f"rapor çok büyük: {ad} ({fs.st_size} bayt)")
        parcalar: list[bytes] = []
        kalan = MAX_RAPOR_BAYT + 1
        while kalan > 0:
            parca = os.read(fd, min(kalan, 1024 * 1024))
            if not parca:
                break
            parcalar.append(parca)
            kalan -= len(parca)
    except OSError as exc:
        raise RaporHatasi(f"rapor okunamadı: {ad}: {exc.strerror or exc}") from exc
    finally:
        os.close(fd)
    veri = b"".join(parcalar)
    if len(veri) > MAX_RAPOR_BAYT:
        raise RaporHatasi(f"rapor çok büyük: {ad} (> {MAX_RAPOR_BAYT} bayt)")
    return veri


# --------------------------------------------------------------------------- JUnit


def parse_junit(veri: bytes) -> list[TestSatiri]:
    """JUnit XML → test satırları. DTD/varlık bildirimi içeren belge reddedilir."""
    if len(veri) > MAX_RAPOR_BAYT:
        raise RaporHatasi("JUnit XML çok büyük")
    bas = veri[:4096].lower()
    if b"<!doctype" in bas or b"<!entity" in veri.lower():
        raise RaporHatasi("JUnit XML DTD/varlık bildirimi içeremez")
    # Bayt araması yalnızca ASCII uyumlu kodlamalarda çalışır (UTF-16 belgede `<!DOCTYPE` baytları
    # araya NUL girer). Asıl koruma: ağaç kurulmadan önce expat ile, belgenin KENDİ kodlamasıyla
    # ön tarama; DTD/varlık bildirimi görülür görülmez (varlık açılmadan) reddedilir.
    _dtd_yok(veri)
    try:
        kok = ET.fromstring(veri)
    except ET.ParseError as exc:
        raise RaporHatasi(f"JUnit XML ayrıştırılamadı: {exc}") from exc
    out: list[TestSatiri] = []
    for tc in kok.iter("testcase"):
        if len(out) >= MAX_TEST:
            break
        ad = temiz(tc.get("name"), MAX_AD)
        dosya = temiz(tc.get("classname"), MAX_AD) or None
        sure_ms = round(_float(tc.get("time")) * 1000)
        sonuc, hata = "passed", None
        for cocuk in tc:
            etiket = cocuk.tag
            if etiket in ("failure", "error"):
                sonuc = "failed"
                hata = temiz(cocuk.get("message") or (cocuk.text or "").strip() or etiket)
                break
            if etiket == "skipped":
                sonuc = "skipped"
        out.append(
            TestSatiri(
                test_adi=ad,
                dosya=dosya,
                sonuc=sonuc,
                sure_ms=sure_ms,
                hata_mesaji=hata,
                kaynak_rapor="junit",
            )
        )
    return out


class _DtdVar(Exception):
    pass


def _dtd_yok(veri: bytes) -> None:
    from xml.parsers import expat

    def _reddet(*_: Any) -> None:
        raise _DtdVar

    p = expat.ParserCreate()
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    p.StartDoctypeDeclHandler = _reddet
    p.EntityDeclHandler = _reddet
    p.UnparsedEntityDeclHandler = _reddet
    p.ExternalEntityRefHandler = _reddet
    try:
        p.Parse(veri, True)
    except _DtdVar as exc:
        raise RaporHatasi("JUnit XML DTD/varlık bildirimi içeremez") from exc
    except expat.ExpatError as exc:
        raise RaporHatasi(f"JUnit XML ayrıştırılamadı: {exc}") from exc
    except (ValueError, LookupError) as exc:
        # BOM'suz çok baytlı (utf-16) ya da bilinmeyen kodlama bildirimi.
        raise RaporHatasi(f"JUnit XML kodlaması desteklenmiyor: {temiz(exc, 200)}") from exc


def _float(deger: Any) -> float:
    try:
        f = float(deger)
    except (TypeError, ValueError):
        return 0.0
    return f if f >= 0 else 0.0


# --------------------------------------------------------------------------- JSON


@dataclass(frozen=True)
class KosuDizini:
    """Koşu dizini: raporun yazıldığı yer (`uzak`, test-runner'daki mutlak yol) ve çekirdeğin
    okuduğu yer (`yerel`, aynı volume'ün çekirdekteki bağlama noktası)."""

    uzak: str
    yerel: Path | None = None

    @classmethod
    def ayni(cls, yol: Path) -> KosuDizini:
        return cls(str(yol), yol)


def _ek_yolu(ham: Any, dizin: KosuDizini | None) -> str | None:
    """Ek dosyasının koşu dizinine göre göreli yolu; dizin dışındaysa None."""
    if not isinstance(ham, str) or not ham or dizin is None or "\x00" in ham:
        return None
    try:
        p = PurePosixPath(ham)
        if not p.is_absolute():
            return None
        rel = p.relative_to(PurePosixPath(dizin.uzak))
    except ValueError:
        return None
    if ".." in rel.parts or not rel.parts:
        return None
    return rel.as_posix()


def _a11y_ozeti(
    ad: str, ek: Mapping[str, Any], kosu_dizini: KosuDizini | None
) -> dict[str, Any] | None:
    m = A11Y_EK_RE.match(ad)
    if not m:
        return None
    ham: bytes | None = None
    govde = ek.get("body")
    if isinstance(govde, str) and govde:
        if len(govde) > MAX_EK_BAYT * 2:
            return None
        try:
            ham = base64.b64decode(govde, validate=False)
        except (binascii.Error, ValueError):
            return None
    elif kosu_dizini is not None and kosu_dizini.yerel is not None:
        rel = _ek_yolu(ek.get("path"), kosu_dizini)
        if rel is not None:
            p = kosu_dizini.yerel / rel
            try:
                icinde = kosu_dizini.yerel.resolve() in p.resolve().parents
                if icinde and p.is_file() and p.stat().st_size <= MAX_EK_BAYT:
                    ham = p.read_bytes()
            except OSError:
                ham = None
    if ham is None or len(ham) > MAX_EK_BAYT:
        return None
    try:
        veri = json.loads(ham.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(veri, dict):
        return None
    etki_ham = veri.get("byImpact") if isinstance(veri.get("byImpact"), dict) else {}
    etki = {k: _int(etki_ham.get(k)) for k in ETKILER if _int(etki_ham.get(k))}
    kurallar = []
    for d in (veri.get("details") or [])[:50]:
        if isinstance(d, dict):
            kurallar.append(
                {
                    "id": temiz(d.get("id"), 100),
                    "etki": temiz(d.get("impact"), 20) or None,
                    "dugum": len(d.get("nodes") or []) if isinstance(d.get("nodes"), list) else 0,
                }
            )
    return {
        "sayfa": temiz(veri.get("page") or m.group(1), 100),
        "url": temiz(veri.get("url"), 500) or None,
        "ihlal": _int(veri.get("violations")),
        "dugum": _int(veri.get("nodes")),
        "etki": etki,
        "kurallar": kurallar,
    }


def aria_ayikla(veri: bytes | None) -> tuple[str | None, str | None]:
    """`error-context.md` → (aria snapshot, kapsam `page` | `error_details`). Güvenilmeyen veri.

    toolchain `runner/results._aria_snapshot` ve triage `evidence.aria_oku` ile aynı kural:
    `# Page snapshot` bölümü sayfanın tamamıdır; yoksa hata ayrıntısındaki başlıksız YAML.
    """
    if not veri or len(veri) > MAX_ERROR_CONTEXT:
        return None, None
    metin = veri[:400_000].decode("utf-8", "replace")
    m = _PAGE_SNAPSHOT_RE.search(metin)
    if m:
        return temiz(m.group(1), MAX_ARIA), "page"
    m = _YAML_RE.search(metin)
    if m:
        return temiz(m.group(1), MAX_ARIA), "error_details"
    return None, None


def _nfc(yol: str) -> str:
    return unicodedata.normalize("NFC", yol)


def aria_dosyasi_mi(ad: str) -> bool:
    """Dosya adı (yolun son öğesi) son yeşil aria snapshot dosyası kalıbına uyuyor mu?"""
    return any(fnmatch.fnmatchcase(ad, k) for k in ARIA_DOSYA_KALIPLARI)


def aria_dosyalari(dosyalar: Mapping[str, bytes]) -> list[tuple[str, str]]:
    """Artefakt zip'indeki aria dosyaları → [(göreli yol (NFC), metin)]; güvenilmeyen veri.

    Mutlak / `..` içeren yollar, `MAX_ARIA_DOSYA_BAYT`'ı aşan ya da UTF-8 olmayan dosyalar
    alınmaz; yola göre sıralı ilk `MAX_ARIA_DOSYA_SAYI` dosya döner. Metinden ANSI / denetim
    karakterleri (NUL dahil) temizlenir; satır sonları korunur.
    """
    out: dict[str, str] = {}
    for ham in sorted(dosyalar):
        if not isinstance(ham, str) or "\x00" in ham:
            continue
        p = PurePosixPath(_nfc(ham.replace("\\", "/")))
        if p.is_absolute() or ".." in p.parts or not p.parts or not aria_dosyasi_mi(p.name):
            continue
        veri = dosyalar[ham]
        if not veri or len(veri) > MAX_ARIA_DOSYA_BAYT:
            continue
        try:
            metin = veri.decode("utf-8")
        except UnicodeDecodeError:
            continue
        yol = p.as_posix()
        if yol in out:
            continue
        out[yol] = CTRL_RE.sub("", ANSI_RE.sub("", metin))
        if len(out) >= MAX_ARIA_DOSYA_SAYI:
            break
    return list(out.items())


@dataclass(frozen=True)
class ArtefaktEkleri:
    """GitHub artefakt zip'inden okunan ek dosyaları (zip içi yol → içerik).

    Playwright ek yolu runner'daki mutlak yoldur
    (`/home/runner/work/<repo>/<repo>/demo-app/e2e/results/artifacts/<test>/error-context.md`);
    artefakt kökü `results/` dizininin içidir (`artifacts/<test>/error-context.md`). Eşleşme
    yol öğelerinin ortak sonekiyledir (en uzun kazanır, en az `<test dizini>/<dosya>`): uygulama
    kökü öneki (`demo-app/`), artefakt kökü ya da runner dizini bilinmek zorunda değildir. Kökteki
    tek bir `error-context.md` hiçbir teste uymaz; mutlak / `..` içeren yollar yok sayılır. Türkçe
    karakterli dizin adları için iki taraf da NFC'ye normalleştirilir.
    """

    dosyalar: Mapping[str, bytes]

    def bul(self, ham_yol: Any) -> bytes | None:
        if not isinstance(ham_yol, str) or not ham_yol or "\x00" in ham_yol:
            return None
        hedef = PurePosixPath(_nfc(ham_yol.replace("\\", "/"))).parts
        en_iyi: tuple[int, bytes] | None = None
        for ad in sorted(self.dosyalar):
            p = PurePosixPath(_nfc(ad))
            if p.is_absolute() or ".." in p.parts or len(p.parts) < 2:
                continue
            # Ortak son öğe sayısı (dosya + en az test dizini); en uzun ortak sonek kazanır.
            ortak = 0
            for a, b in zip(reversed(p.parts), reversed(hedef), strict=False):
                if a != b:
                    break
                ortak += 1
            if ortak >= 2 and (en_iyi is None or ortak > en_iyi[0]):
                en_iyi = (ortak, self.dosyalar[ad])
        return en_iyi[1] if en_iyi else None


def _hata_baglami(
    sonuclar: list[Mapping[str, Any]], ekler: ArtefaktEkleri | None
) -> dict[str, Any] | None:
    """Kırmızı denemelerin ilkinden başlayarak aria snapshot'ı olan ilk `error-context` eki.

    toolchain `failures[].failure` ilk kırmızı denemeden kurulur; aynı sıra izlenir.
    """
    if ekler is None:
        return None
    for r in sonuclar:
        if r.get("status") in ("passed", "skipped"):
            continue
        for ek in r.get("attachments") or []:
            if not isinstance(ek, Mapping) or ek.get("name") != "error-context":
                continue
            aria, kapsam = aria_ayikla(ekler.bul(ek.get("path")))
            if aria:
                return {
                    "aria_snapshot": aria,
                    "aria_snapshot_scope": kapsam,
                    "deneme": _int(r.get("retry")),
                    "kaynak": ERROR_CONTEXT_AD,
                }
    return None


def _json_testleri(
    suite: Mapping[str, Any],
    basliklar: list[str],
    dosya: str | None,
    out: list[TestSatiri],
    kosu_dizini: KosuDizini | None,
    ekler: ArtefaktEkleri | None = None,
) -> None:
    baslik = suite.get("title")
    # En üst suite dosyanın kendisidir (başlığı dosya adı); başlık yoluna girmez.
    if dosya is None:
        dosya = str(suite.get("file") or baslik or "") or None
        burada = basliklar
    else:
        burada = [*basliklar, str(baslik)] if isinstance(baslik, str) and baslik else basliklar
    for spec in suite.get("specs") or []:
        if not isinstance(spec, Mapping):
            continue
        spec_dosya = str(spec.get("file") or dosya or "") or None
        ad = temiz(AYIRAC.join([*burada, str(spec.get("title") or "")]), MAX_AD)
        for test in spec.get("tests") or []:
            if not isinstance(test, Mapping) or len(out) >= MAX_TEST:
                continue
            out.append(_json_test(ad, spec_dosya, spec, test, kosu_dizini, ekler))
    for alt in suite.get("suites") or []:
        if isinstance(alt, Mapping):
            _json_testleri(alt, burada, dosya, out, kosu_dizini, ekler)


def _json_test(
    ad: str,
    dosya: str | None,
    spec: Mapping[str, Any],
    test: Mapping[str, Any],
    kosu_dizini: KosuDizini | None,
    artefakt_ekleri: ArtefaktEkleri | None = None,
) -> TestSatiri:
    sonuclar = [r for r in test.get("results") or [] if isinstance(r, Mapping)]
    durum = str(test.get("status") or "")
    son = sonuclar[-1] if sonuclar else {}
    if durum == "flaky":
        sonuc = "flaky"
    elif durum == "skipped":
        sonuc = "skipped"
    elif durum == "unexpected":
        sonuc = "timedout" if son.get("status") == "timedOut" else "failed"
    elif durum == "expected":
        sonuc = "passed"
    else:
        sonuc = "failed"
    hata = None
    basarisiz = next(
        (r for r in reversed(sonuclar) if r.get("status") not in ("passed", "skipped")), None
    )
    if basarisiz is not None and sonuc != "passed":
        err = basarisiz.get("error")
        if not err and isinstance(basarisiz.get("errors"), list) and basarisiz["errors"]:
            err = basarisiz["errors"][0]
        mesaj = err.get("message") if isinstance(err, Mapping) else err
        hata = temiz(mesaj) if mesaj else f"Test durumu: {basarisiz.get('status')}"
    retry = max((_int(r.get("retry")) for r in sonuclar), default=0)
    denemeler = [
        {
            "deneme": _int(r.get("retry")),
            "sonuc": temiz(r.get("status"), 20),
            "sure_ms": _int(r.get("duration")),
        }
        for r in sonuclar[:10]
    ]
    a11y: list[dict[str, Any]] = []
    ekler: list[dict[str, Any]] = []
    for r in sonuclar:
        for ek in r.get("attachments") or []:
            if not isinstance(ek, Mapping):
                continue
            ek_adi = temiz(ek.get("name"), 120)
            ozet = _a11y_ozeti(ek_adi, ek, kosu_dizini)
            # Aynı sayfa için yalnızca son denemenin a11y özeti sayılır.
            if ozet is not None:
                a11y = [s for s in a11y if s["sayfa"] != ozet["sayfa"]] + [ozet]
            rel = _ek_yolu(ek.get("path"), kosu_dizini)
            if rel is not None and len(ekler) < MAX_EK:
                ekler.append(
                    {
                        "ad": ek_adi,
                        "yol": rel,
                        "tur": temiz(ek.get("contentType"), 100) or None,
                        "deneme": _int(r.get("retry")),
                    }
                )
    satir = spec.get("line")
    return TestSatiri(
        test_adi=ad,
        dosya=temiz(dosya, MAX_AD) if dosya else None,
        sonuc=sonuc,
        sure_ms=sum(_int(r.get("duration")) for r in sonuclar),
        retry=retry,
        hata_mesaji=hata,
        proje=temiz(test.get("projectName"), 100) or None,
        satir=_int(satir) if satir is not None else None,
        a11y=a11y,
        ekler=ekler,
        denemeler=denemeler,
        kaynak_rapor="json",
        hata_baglami=(
            _hata_baglami(sonuclar, artefakt_ekleri) if sonuc not in ("passed", "skipped") else None
        ),
    )


def parse_json_report(
    veri: bytes, kosu_dizini: KosuDizini | None = None, ekler: ArtefaktEkleri | None = None
) -> tuple[list[TestSatiri], dict[str, int], list[str]]:
    if len(veri) > MAX_RAPOR_BAYT:
        raise RaporHatasi("JSON rapor çok büyük")
    try:
        data = json.loads(veri.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RaporHatasi(f"JSON rapor ayrıştırılamadı: {exc}") from exc
    if not isinstance(data, Mapping):
        raise RaporHatasi("JSON rapor nesne değil")
    ham = data.get("stats") if isinstance(data.get("stats"), Mapping) else {}
    stats = {k: _int(ham.get(k)) for k in ("expected", "unexpected", "flaky", "skipped")}
    stats["duration_ms"] = _int(ham.get("duration"))
    out: list[TestSatiri] = []
    for suite in data.get("suites") or []:
        if isinstance(suite, Mapping):
            _json_testleri(suite, [], None, out, kosu_dizini, ekler)
    hatalar = [
        temiz(e.get("message") if isinstance(e, Mapping) else e) for e in data.get("errors") or []
    ][:20]
    return out, stats, hatalar


# --------------------------------------------------------------------------- birleştirme


def _junit_birlestir(satirlar: list[TestSatiri]) -> TestSatiri:
    """Aynı (dosya, ad) için birden çok JUnit `<testcase>` (repeat-each, projeler) → tek satır.

    Kaybolan sonuç olmaz: biri kaldıysa satır `failed` (geçen de varsa `flaky` DEĞİL — JUnit
    yeniden deneme mi tekrar mı olduğunu söylemez; kalan bir koşum her zaman kırmızıdır), hepsi
    atlandıysa `skipped`, aksi halde `passed`. `retry` = tekrar sayısı - 1; her tekrar `denemeler`e
    yazılır (aynı commit'te hem geçen hem kalan → Kontrol Kulesi flaky sinyali).
    """
    if len(satirlar) == 1:
        return satirlar[0]
    sonuclar = [t.sonuc for t in satirlar]
    kalan = next((t for t in satirlar if t.sonuc in ("failed", "timedout")), None)
    if kalan is not None:
        sonuc = kalan.sonuc
    elif all(x == "skipped" for x in sonuclar):
        sonuc = "skipped"
    else:
        sonuc = "passed"
    ilk = satirlar[0]
    return TestSatiri(
        test_adi=ilk.test_adi,
        dosya=ilk.dosya,
        sonuc=sonuc,
        sure_ms=sum(t.sure_ms for t in satirlar),
        retry=len(satirlar) - 1,
        hata_mesaji=kalan.hata_mesaji if kalan is not None else None,
        denemeler=[
            {"deneme": i, "sonuc": t.sonuc, "sure_ms": t.sure_ms}
            for i, t in enumerate(satirlar[:10])
        ],
        kaynak_rapor="junit",
    )


def merge(junit: Iterable[TestSatiri] | None, jsn: Iterable[TestSatiri] | None) -> list[TestSatiri]:
    """JSON önceliklidir; JUnit'te olup JSON'da olmayan testler eklenir.

    JUnit satırları yalnızca JSON'da bulunan anahtarlara karşı elenir. JSON'da olmayan bir anahtar
    JUnit'te birden çok kez geçiyorsa satırlar tek satırda toplanır (`_junit_birlestir`): bir
    tekrarın kalması asla kaybolmaz.
    """
    sonuc: list[TestSatiri] = list(jsn or [])
    json_anahtar = {t.anahtar for t in sonuc}
    gruplar: dict[tuple[str, str], list[TestSatiri]] = {}
    for t in junit or []:
        if t.anahtar not in json_anahtar:
            gruplar.setdefault(t.anahtar, []).append(t)
    sonuc.extend(_junit_birlestir(g) for g in gruplar.values())
    return sonuc


def parse_reports(
    junit_xml: bytes | None,
    results_json: bytes | None,
    kosu_dizini: KosuDizini | None = None,
    ekler: ArtefaktEkleri | None = None,
) -> Ayristirma:
    """`ekler`: GitHub kipinde artefakt zip'inden okunan `error-context.md` dosyaları."""
    uyarilar: list[str] = []
    junit: list[TestSatiri] | None = None
    jsn: list[TestSatiri] | None = None
    stats: dict[str, int] = {}
    if junit_xml is not None:
        try:
            junit = parse_junit(junit_xml)
        except RaporHatasi as exc:
            uyarilar.append(str(exc))
        except Exception as exc:  # güvenilmeyen girdi: okunamayan rapor yalnızca uyarı
            uyarilar.append(f"JUnit XML ayrıştırılamadı: {temiz(exc, 200)}")
    else:
        uyarilar.append("JUnit XML (junit.xml) bulunamadı.")
    if results_json is not None:
        try:
            jsn, stats, hatalar = parse_json_report(results_json, kosu_dizini, ekler)
            uyarilar.extend(f"Rapor hatası: {h}" for h in hatalar)
        except RaporHatasi as exc:
            uyarilar.append(str(exc))
        except Exception as exc:  # güvenilmeyen girdi: okunamayan rapor yalnızca uyarı
            uyarilar.append(f"JSON rapor ayrıştırılamadı: {temiz(exc, 200)}")
    else:
        uyarilar.append(
            "JSON rapor (results.json) bulunamadı: yeniden deneme ve flaky bilgisi yok."
        )
    if junit is not None and jsn is not None:
        j_anahtar = {t.anahtar for t in junit}
        eksik = [t for t in jsn if t.anahtar not in j_anahtar]
        if eksik and junit:
            uyarilar.append(f"JSON raporundaki {len(eksik)} test JUnit XML'de yok.")
    return Ayristirma(
        testler=merge(junit, jsn),
        uyarilar=uyarilar,
        istatistik=stats,
        raporlar={"junit": junit is not None, "json": jsn is not None},
    )


def parse_files(
    junit_yolu: Path | None, json_yolu: Path | None, kosu_dizini: KosuDizini | None
) -> Ayristirma:
    """Diskteki raporları okuyup ayrıştırır. Okunamayan (sembolik bağ, dizin dışı, normal dosya
    değil, çok büyük) rapor uyarı olur; diğer rapor yine işlenir."""
    kok = kosu_dizini.yerel if kosu_dizini is not None else None
    okuma_uyarilari: list[str] = []
    veriler: list[bytes | None] = []
    for yol in (junit_yolu, json_yolu):
        try:
            veriler.append(_oku(yol, kok))
        except RaporHatasi as exc:
            okuma_uyarilari.append(str(exc))
            veriler.append(None)
    ayr = parse_reports(veriler[0], veriler[1], kosu_dizini)
    ayr.uyarilar[:0] = okuma_uyarilari
    return ayr


def sayilar(testler: Iterable[TestSatiri | Mapping[str, Any]]) -> dict[str, int]:
    s = {"toplam": 0, "gecen": 0, "basarisiz": 0, "flaky": 0, "atlanan": 0}
    for t in testler:
        sonuc = t.sonuc if isinstance(t, TestSatiri) else t.get("sonuc")
        s["toplam"] += 1
        if sonuc == "passed":
            s["gecen"] += 1
        elif sonuc == "flaky":
            s["flaky"] += 1
        elif sonuc == "skipped":
            s["atlanan"] += 1
        else:
            s["basarisiz"] += 1
    return s
