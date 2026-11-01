"""Triage kanıtının güvenli okunması (TEKNIK-TASARIM §8.6 adım 1). AI yok.

Kanıt test kodunun ve test edilen uygulamanın çıktısıdır: **güvenilmeyen veridir** (Constitution:
CI log'ları ve sayfa snapshot'ları güvenilmez). Bu modül yalnızca okur, kırpar ve kalıp eşler:

- `kosu_raporu`: test-runner'ın koşu dizinindeki `run.json`'u (sağlık bloğu, `failures`, `tests`).
  Dosya koşu dizininin içinde olmalı; sembolik bağ izlenmez, normal dosya değilse ve boyut sınırını
  aşarsa okunmaz.
- `aria_oku`: `error-context.md`'deki aria snapshot'ı (yalnızca rol + ad ağacı).
- `trace_oku`: `trace.zip`'i **açmadan** (diske çıkarmadan; zip-slip yok) bellek içinde, üye
  sayısı / açılmış boyut / sıkıştırma oranı sınırlarıyla okur; son sayfa adresinin yolu ve
  başarısız eylemin (yoksa son) DOM snapshot'ındaki `data-testid` değerleri (§8.7). Playwright
  snapshot'ları artımlıdır (`[[geri, düğüm]]` başvuruları); toolchain_common/trace.py ile aynı
  çözümleme yapılır.
- `locator_test_idleri`: Playwright locator metninden testId zinciri (`getByTestId('a')
  .getByTestId('b')` → `["a", "b"]`).
"""

from __future__ import annotations

import io
import json
import os
import re
import stat
import zipfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_RUN_JSON = 32 * 1024 * 1024
MAX_ERROR_CONTEXT = 2 * 1024 * 1024
MAX_ARIA = 20_000
MAX_TRACE_ZIP = 64 * 1024 * 1024
MAX_TRACE_UYE = 5_000
MAX_TRACE_ACIK = 256 * 1024 * 1024  # tüm üyelerin beyan edilen açılmış boyutu
MAX_TRACE_OKU = 32 * 1024 * 1024  # okunan tek `*.trace` üyesi
MAX_ORAN = 200  # açılmış / sıkıştırılmış (zip bombası)
MAX_TRACE_SATIR = 200_000
MAX_TESTID = 2_000
MAX_METIN = 2_000

RUN_DIR_RE = re.compile(r"^runs/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
TESTID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
URL_PATH_RE = re.compile(r"^/[A-Za-z0-9/_.~-]{0,200}$")

# getByTestId('x') · getByTestId("x") · internal:testid=[data-testid="x"s] · [data-testid="x"]
_TESTID_PARCA_RE = re.compile(
    r"getByTestId\(\s*(['\"])(?P<a>[^'\"]{1,200})\1\s*\)"
    r"|internal:testid=\[data-testid=(?:\\?['\"])(?P<b>[^'\"\\]{1,200})(?:\\?['\"])[si]?\]"
    r"|\[data-testid=(?:\\?['\"])(?P<c>[^'\"\\]{1,200})(?:\\?['\"])\]"
)
_URUN_KODU_RE = re.compile(r"\b(P-\d{3,6})\b")


class KanitHatasi(ValueError):
    """Kanıt dosyası okunamadı (çağıran sinyale/uyarıya çevirir)."""


def temiz(metin: Any, limit: int = MAX_METIN) -> str:
    s = CTRL_RE.sub("", ANSI_RE.sub("", str(metin if metin is not None else "")))
    return s if len(s) <= limit else s[:limit] + "…"


def temiz_or_none(metin: Any, limit: int = MAX_METIN) -> str | None:
    if metin is None:
        return None
    s = temiz(metin, limit).strip()
    return s or None


# ----------------------------------------------------------------------------- dosya okuma


def guvenli_oku(yol: Path, kok: Path, limit: int) -> bytes | None:
    """Koşu dizini (`kok`) içindeki normal dosyayı en çok `limit` bayt okur.

    Yoksa None. Sembolik bağ, normal olmayan dosya, kök dışı yol ve boyut aşımı `KanitHatasi`.
    """
    ad = yol.name
    try:
        ls = os.lstat(yol)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise KanitHatasi(f"{ad} okunamadı: {exc.strerror or exc}") from exc
    if stat.S_ISLNK(ls.st_mode):
        raise KanitHatasi(f"{ad} sembolik bağ; okunmadı")
    if not stat.S_ISREG(ls.st_mode):
        raise KanitHatasi(f"{ad} normal dosya değil; okunmadı")
    try:
        kok_c = kok.resolve(strict=True)
        yol_c = yol.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise KanitHatasi(f"{ad}: yol çözülemedi") from exc
    if kok_c != yol_c and kok_c not in yol_c.parents:
        raise KanitHatasi(f"{ad} koşu dizininin dışında; okunmadı")
    bayrak = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(yol, bayrak)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise KanitHatasi(f"{ad} açılamadı: {exc.strerror or exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise KanitHatasi(f"{ad} normal dosya değil; okunmadı")
        parcalar: list[bytes] = []
        kalan = limit + 1
        while kalan > 0:
            parca = os.read(fd, min(kalan, 1 << 20))
            if not parca:
                break
            parcalar.append(parca)
            kalan -= len(parca)
    finally:
        os.close(fd)
    veri = b"".join(parcalar)
    if len(veri) > limit:
        raise KanitHatasi(f"{ad} boyut sınırını ({limit} bayt) aşıyor; okunmadı")
    return veri


def kosu_dizini(artifacts_root: Path, dizin: Any) -> Path | None:
    """`run.artefaktlar.dizin` (`runs/<id>`) → yerel koşu dizini (biçim doğrulanır)."""
    if not isinstance(dizin, str) or not RUN_DIR_RE.match(dizin):
        return None
    return artifacts_root / dizin


def kosu_raporu(kosu: Path) -> dict[str, Any] | None:
    """test-runner'ın `run.json`'u (yoksa None)."""
    veri = guvenli_oku(kosu / "run.json", kosu, MAX_RUN_JSON)
    if veri is None:
        return None
    try:
        rapor = json.loads(veri.decode("utf-8", "replace"))
    except ValueError as exc:
        raise KanitHatasi("run.json geçerli JSON değil") from exc
    if not isinstance(rapor, dict):
        raise KanitHatasi("run.json nesne değil")
    return rapor


def kanit_yolu(kosu_rel: str, rel: Any) -> str | None:
    """Kanıtın `TP_ARTIFACTS_PATH`'e göre yolu (`runs/<id>/src/...`) → koşu dizinine göre yol.

    Koşu dizini dışına çıkan, mutlak ya da `..` içeren yollar reddedilir (None).
    """
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        return None
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts:
        return None
    try:
        ic = p.relative_to(PurePosixPath(kosu_rel))
    except ValueError:
        return None
    s = ic.as_posix()
    return s if s and s != "." else None


# ---------------------------------------------------------------------------- aria snapshot

_PAGE_SNAPSHOT_RE = re.compile(r"^# Page snapshot\s*\n+```(?:yaml)?\n(.*?)\n```", re.S | re.M)
_YAML_RE = re.compile(r"^```yaml\n(.*?)\n```", re.S | re.M)


def aria_oku(kosu: Path, rel_in_run: str | None) -> tuple[str | None, str | None]:
    """`error-context.md`'den aria snapshot ve kapsamı (`page` | `error_details`)."""
    if not rel_in_run:
        return None, None
    try:
        veri = guvenli_oku(kosu / rel_in_run, kosu, MAX_ERROR_CONTEXT)
    except KanitHatasi:
        return None, None
    if veri is None:
        return None, None
    metin = veri[:400_000].decode("utf-8", "replace")
    m = _PAGE_SNAPSHOT_RE.search(metin)
    if m:
        return temiz(m.group(1), MAX_ARIA), "page"
    m = _YAML_RE.search(metin)
    if m:
        return temiz(m.group(1), MAX_ARIA), "error_details"
    return None, None


def _aria_ad(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"')


def aria_eslesmeleri(aria: str | None, role: str, name: str) -> list[str]:
    """Aria snapshot'ında `- <role> "<name>"` satırları (en çok 20; kırpılmış)."""
    if not aria or not role or not name:
        return []
    kalip = re.compile(
        rf"^\s*-\s*{re.escape(role)}\s+\"{re.escape(_aria_ad(name))}\"(?=[\s:\[]|$)", re.M
    )
    out: list[str] = []
    for satir in aria.splitlines():
        if kalip.match(satir):
            out.append(temiz(satir.strip(), 200))
            if len(out) >= 20:
                break
    return out


def aria_parcasi(aria: str | None, anahtarlar: list[str], cevre: int = 3) -> str | None:
    """Aria snapshot'ından ilgili satırların çevresi (portalda gösterim için; ≤ 1500 karakter)."""
    if not aria:
        return None
    satirlar = aria.splitlines()
    secilen: set[int] = set()
    for i, s in enumerate(satirlar):
        if any(a and a in s for a in anahtarlar):
            secilen.update(range(max(0, i - cevre), min(len(satirlar), i + cevre + 1)))
    if not secilen:
        secilen = set(range(min(len(satirlar), 12)))
    metin = "\n".join(satirlar[i] for i in sorted(secilen))
    return temiz(metin, 1500)


# ------------------------------------------------------------------------------- trace.zip


@dataclass
class TraceOzeti:
    okundu: bool = False
    hata: str | None = None
    son_url_yolu: str | None = None
    # Seçilen DOM snapshot'ındaki (başarısız eylemin anı; yoksa son snapshot) elemanlar:
    # [{etiket, test_id, metin}]. Playwright'ın `[[geri, düğüm]]` başvuruları çözülmüş olarak.
    elemanlar: list[dict[str, str]] = field(default_factory=list)
    olay_sayisi: int = 0
    snapshot_sayisi: int = 0
    dom_cozuldu: bool = False  # seçilen snapshot'tan en az bir eleman çıkarıldı mı
    dom_kismi: bool = False  # çözümleme bütçe/derinlik/geçersiz başvuru nedeniyle eksik
    dom_kaynagi: str | None = None  # "basarisiz_eylem" | "son_snapshot"
    dom_url_yolu: str | None = None

    def ozet(self) -> dict[str, Any]:
        return {
            "okundu": self.okundu,
            "hata": self.hata,
            "son_url_yolu": self.son_url_yolu,
            "dom_test_id_sayisi": len(self.elemanlar),
            "olay_sayisi": self.olay_sayisi,
            "snapshot_sayisi": self.snapshot_sayisi,
            "dom_cozuldu": self.dom_cozuldu,
            "dom_kismi": self.dom_kismi,
            "dom_kaynagi": self.dom_kaynagi,
            "dom_url_yolu": self.dom_url_yolu,
        }

    @property
    def dom_kullanilabilir(self) -> bool:
        """testId var/yok yargısı yalnızca DOM'dan testId'li eleman çıkarıldıysa anlamlıdır."""
        return self.okundu and bool(self.elemanlar)

    def test_id_var_mi(self, test_id: str) -> bool:
        return any(e.get("test_id") == test_id for e in self.elemanlar)


def _guvenli_uye(ad: str) -> bool:
    p = PurePosixPath(ad)
    return bool(ad) and not p.is_absolute() and ".." not in p.parts and "\\" not in ad


def _url_yolu(url: Any) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    try:
        yol = urlsplit(url).path or "/"
    except ValueError:
        return None
    return yol if URL_PATH_RE.match(yol) else None


# Playwright frame-snapshot `html` biçimi (snapshotRenderer.ts ile aynı):
#   metin düğümü: "str" · eleman: [ETIKET, {öznitelikler}?, ...çocuklar]
#   başvuru: [[geri, düğümIndeksi]] → aynı çerçevenin `geri` önceki snapshot'ının post-order
#   (metin + eleman; başvurular sayılmaz) düğüm listesindeki `düğümIndeksi`. Değişmeyen alt
#   ağaçlar böyle yazılır; son snapshot çoğu zaman yalnızca `[[1, 10]]`'dur.
MAX_DUGUM = 100_000
MAX_DERINLIK = 256


def _eleman_mi(n: Any) -> bool:
    return isinstance(n, list) and bool(n) and isinstance(n[0], str)


def _basvuru_mu(n: Any) -> bool:
    return (
        isinstance(n, list)
        and len(n) == 1
        and isinstance(n[0], list)
        and len(n[0]) == 2
        and all(isinstance(x, int) and not isinstance(x, bool) for x in n[0])
    )


def _cocuklar(n: list[Any]) -> list[Any]:
    return n[2:] if len(n) > 1 and isinstance(n[1], dict) else n[1:]


class _CerceveSnapshotlari:
    """Bir çerçevenin snapshot dizisi + başvuru çözümü (bütçe, derinlik, döngü korumalı)."""

    def __init__(self, htmller: list[Any]) -> None:
        self.htmller = htmller
        self._dugumler: dict[int, list[Any]] = {}
        self.butce = MAX_DUGUM
        self.kismi = False

    def dugumler(self, idx: int) -> list[Any]:
        if idx in self._dugumler:
            return self._dugumler[idx]
        out: list[Any] = []
        yigin: list[tuple[Any, bool]] = [(self.htmller[idx], False)]
        while yigin:
            n, bitti = yigin.pop()
            if isinstance(n, str):
                out.append(n)
            elif _eleman_mi(n):
                if bitti:
                    out.append(n)
                else:
                    yigin.append((n, True))
                    for c in reversed(_cocuklar(n)):
                        yigin.append((c, False))
            if len(out) > MAX_DUGUM:
                self.kismi = True
                break
        self._dugumler[idx] = out
        return out

    def coz(self, n: Any, idx: int, derinlik: int = 0) -> Any:
        """Başvuruları açılmış ağaç: str | [ETIKET, attrs, *çocuklar] | None."""
        self.butce -= 1
        if self.butce < 0 or derinlik > MAX_DERINLIK:
            self.kismi = True
            return None
        if isinstance(n, str):
            return n
        if _basvuru_mu(n):
            geri, dugum_idx = n[0]
            ref = idx - geri
            if geri < 1 or ref < 0:  # aynı/ileri snapshot'a başvuru: döngü riski → yok say
                self.kismi = True
                return None
            dugumler = self.dugumler(ref)
            if not 0 <= dugum_idx < len(dugumler):
                self.kismi = True
                return None
            return self.coz(dugumler[dugum_idx], ref, derinlik + 1)
        if _eleman_mi(n):
            attrs = n[1] if len(n) > 1 and isinstance(n[1], dict) else {}
            out: list[Any] = [n[0], attrs]
            for c in _cocuklar(n):
                r = self.coz(c, idx, derinlik + 1)
                if r is not None:
                    out.append(r)
            return out
        return None


def _dom_dugumleri(dugum: Any, derinlik: int = 0) -> Iterator[tuple[str, dict[str, Any], str]]:
    """Çözülmüş `html` ağacı: `[etiket, {öznitelikler}, ...çocuklar]` ya da metin."""
    if derinlik > MAX_DERINLIK or not _eleman_mi(dugum):
        return
    etiket = dugum[0]
    attrs_var = len(dugum) > 1 and isinstance(dugum[1], dict)
    attrs: dict[str, Any] = dugum[1] if attrs_var else {}
    cocuklar = dugum[2:] if attrs_var else dugum[1:]
    metin = " ".join(_metin(c) for c in cocuklar)
    yield etiket, attrs, " ".join(metin.split())
    for c in cocuklar:
        yield from _dom_dugumleri(c, derinlik + 1)


def _metin(dugum: Any, derinlik: int = 0) -> str:
    """Düğümün görünür metni (kırpılmış; SCRIPT/STYLE atlanır)."""
    if isinstance(dugum, str):
        return dugum.strip()
    if derinlik > 20 or not _eleman_mi(dugum) or dugum[0].upper() in {"SCRIPT", "STYLE"}:
        return ""
    parcalar = [_metin(c, derinlik + 1) for c in _cocuklar(dugum)]
    return " ".join(p for p in parcalar if p)[:400]


def trace_oku(kosu: Path, rel_in_run: str | None) -> TraceOzeti:
    """`trace.zip`'i bellek içinde, sınırlarla okur (diske hiçbir şey çıkarılmaz).

    DOM, başarısız eylemin (hata taşıyan `after`) ana çerçeve snapshot'ından; o yoksa son
    snapshot'tan okunur. Snapshot başvuruları aynı çerçevenin önceki snapshot'larına çözülür.
    """
    oz = TraceOzeti()
    if not rel_in_run:
        oz.hata = "trace yok"
        return oz
    try:
        veri = guvenli_oku(kosu / rel_in_run, kosu, MAX_TRACE_ZIP)
    except KanitHatasi as exc:
        oz.hata = str(exc)
        return oz
    if veri is None:
        oz.hata = "trace dosyası yok"
        return oz
    try:
        zf = zipfile.ZipFile(io.BytesIO(veri))
    except (zipfile.BadZipFile, ValueError, OSError):
        oz.hata = "trace.zip geçerli bir zip değil"
        return oz
    # çerçeve anahtarı (üye:frameId) → [(html, frameUrl)]
    cerceveler: dict[str, list[tuple[Any, Any]]] = {}
    snap_konum: dict[str, tuple[str, int]] = {}  # callId → (çerçeve, indeks)
    son_konum: tuple[str, int] | None = None
    basarisiz: str | None = None
    with zf:
        uyeler = zf.infolist()
        if len(uyeler) > MAX_TRACE_UYE:
            oz.hata = "trace.zip üye sayısı sınırı aşıldı; okunmadı"
            return oz
        if sum(max(u.file_size, 0) for u in uyeler) > MAX_TRACE_ACIK:
            oz.hata = "trace.zip açılmış boyut sınırı aşıldı; okunmadı"
            return oz
        izler = sorted(
            (
                u
                for u in uyeler
                if _guvenli_uye(u.filename)
                and not u.is_dir()
                and PurePosixPath(u.filename).suffix == ".trace"
                and "/" not in u.filename
            ),
            key=lambda u: u.filename,
        )
        for u in izler:
            if u.file_size > MAX_TRACE_OKU or (
                u.compress_size > 0 and u.file_size / u.compress_size > MAX_ORAN
            ):
                oz.hata = f"{u.filename}: boyut/oran sınırı aşıldı; atlandı"
                continue
            try:
                with zf.open(u) as f:
                    ham = f.read(MAX_TRACE_OKU + 1)
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
                oz.hata = f"{u.filename} okunamadı"
                continue
            if len(ham) > MAX_TRACE_OKU:
                oz.hata = f"{u.filename}: boyut sınırı aşıldı; atlandı"
                continue
            secicili: set[str] = set()
            for i, satir in enumerate(ham.splitlines()):
                if i >= MAX_TRACE_SATIR:
                    break
                try:
                    olay = json.loads(satir)
                except ValueError:
                    continue
                if not isinstance(olay, dict):
                    continue
                oz.olay_sayisi += 1
                tur = olay.get("type")
                params = olay.get("params") if isinstance(olay.get("params"), dict) else {}
                if tur == "frame-snapshot":
                    snap = olay.get("snapshot") if isinstance(olay.get("snapshot"), dict) else {}
                    snap = snap or {}
                    yol = _url_yolu(snap.get("frameUrl"))
                    if yol:
                        oz.son_url_yolu = yol
                    html = snap.get("html")
                    if not isinstance(html, list):
                        continue
                    anahtar = f"{u.filename}:{str(snap.get('frameId') or '')[:100]}"
                    liste = cerceveler.setdefault(anahtar, [])
                    liste.append((html, snap.get("frameUrl")))
                    oz.snapshot_sayisi += 1
                    son_konum = (anahtar, len(liste) - 1)
                    cid = snap.get("callId")
                    if isinstance(cid, str) and cid and snap.get("isMainFrame", True):
                        snap_konum[cid] = son_konum  # aynı eylemin son (after) snapshot'ı kalır
                elif tur == "before":
                    cid = olay.get("callId")
                    if isinstance(cid, str) and isinstance((params or {}).get("selector"), str):
                        secicili.add(cid)
                    yol = _url_yolu((params or {}).get("url"))
                    if yol and str(olay.get("method") or olay.get("apiName") or "").endswith(
                        "goto"
                    ):
                        oz.son_url_yolu = yol
                elif tur == "after" and isinstance(olay.get("error"), dict):
                    cid = olay.get("callId")
                    if isinstance(cid, str) and cid and (basarisiz is None or cid in secicili):
                        basarisiz = cid
            oz.okundu = True
        konum = snap_konum.get(basarisiz) if basarisiz else None
        oz.dom_kaynagi = "basarisiz_eylem" if konum else None
        if konum is None and son_konum is not None:
            konum, oz.dom_kaynagi = son_konum, "son_snapshot"
        if konum is not None:
            anahtar, idx = konum
            liste = cerceveler[anahtar]
            cs = _CerceveSnapshotlari([h for h, _ in liste])
            kok = cs.coz(liste[idx][0], idx)
            oz.dom_url_yolu = _url_yolu(liste[idx][1])
            for etiket, attrs, metin in _dom_dugumleri(kok):
                oz.dom_cozuldu = True
                tid = attrs.get("data-testid")
                if isinstance(tid, str) and TESTID_RE.match(tid):
                    oz.elemanlar.append(
                        {"etiket": etiket.lower()[:40], "test_id": tid, "metin": temiz(metin, 120)}
                    )
                    if len(oz.elemanlar) >= MAX_TESTID:
                        break
            oz.dom_kismi = cs.kismi
    if not izler and oz.hata is None:
        oz.hata = "trace.zip içinde iz dosyası yok"
    return oz


# ------------------------------------------------------------------------------- locator


def locator_test_idleri(locator: Any) -> list[str]:
    """Locator metnindeki testId zinciri (sırayla; geçersizler atılır)."""
    if not isinstance(locator, str) or not locator:
        return []
    out: list[str] = []
    for m in _TESTID_PARCA_RE.finditer(locator[:2000]):
        tid = m.group("a") or m.group("b") or m.group("c")
        if tid and TESTID_RE.match(tid):
            out.append(tid)
    return out


def urun_kodu(*metinler: Any) -> str | None:
    for m in metinler:
        if isinstance(m, str):
            bul = _URUN_KODU_RE.search(m)
            if bul:
                return bul.group(1)
    return None


def mapping(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}
