"""GitHub koşu artefaktlarının yerel kopyası (portal raporları GitHub'a gitmeden açabilsin).

GitHub kipinde (`TP_FORGE=github`) koşunun raporları GitHub artefaktlarındadır; kullanıcı onları
GitHub'da bulup zip olarak indirmek zorundaydı. Alım (`github_ingest`) `test-local-results`
artefaktını (yoksa/eksikse ayrıca `playwright-report`'u) core-worker'ın yazabildiği ayrı volume'e
(`TP_GITHUB_ARTIFACTS_PATH`, core-api salt okur) açar:

    <kök>/gh/<github_run_id>-<deneme>/src/e2e/results/   ← test-local-results kökü (aynen)
        junit.xml, results.json, ci-meta.json, allure-results/, playwright-report/, artifacts/,
        run-checks.log

Düzen yerel koşunun (`runs/<id>/src/e2e/results/`) izinli alt ağacıyla aynıdır: mevcut oturumlu /
imzalı artefakt ucu (`artifacts.coz`) değişmeden sunar. Artefakt güvenilmeyen test çıktısıdır:
açma `safe_extract_zip` ile yapılır (zip-slip, sembolik bağ, dosya sayısı/açılmış boyut sınırı).

- **İdempotent:** dizin önce gizli geçici ada açılır, bitince tek `rename` ile yerine konur; işaret
  dosyası (`.tp-github.json`, gizli → sunulmaz) olan dizin tekrar indirilmez. Yeniden alım /
  geri doldurma diskteki kopyayı okur.
- **Saklama:** en yeni `TP_GITHUB_ARTIFACTS_KEEP` (varsayılan 30) dizin kalır; silinenlerin koşu
  kaydı `budandi` olarak işaretlenir (çağıran).
- Hata alımı düşürmez: `durum="hata"` + kısa neden döner; portal GitHub bağlantısına düşer.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tp_core.features.ci import services
from tp_core.features.ci.clients import (
    RESULTS_ARTIFACT,
    GitHubCiError,
    dosya_sec,
)
from tp_core.features.ci.parse import temiz

log = logging.getLogger(__name__)

REPORT_ARTIFACT = "playwright-report"
SONUC_KOK = "src/e2e/results"  # yerel koşunun sonuç dizini (izinli alt ağaç `src/**/results/**`)
ISARET = ".tp-github.json"
GH_DIR_RE = re.compile(r"^gh/[0-9]{1,20}-[0-9]{1,4}$")
GECICI_ESKI_S = 3600  # yarıda kalmış geçici dizinler bu süreden sonra silinir
MAX_ARAMA = 20_000  # disk taraması üst sınırı (safe_extract_zip dosya sınırıyla aynı)


def kok() -> Path:
    return services.github_artifacts_root()


def dizin_adi(github_run_id: Any, deneme: Any) -> str | None:
    try:
        rid, d = int(github_run_id), int(deneme or 1)
    except (TypeError, ValueError):
        return None
    ad = f"gh/{rid}-{max(d, 1)}"
    return ad if GH_DIR_RE.match(ad) else None


def yol(dizin: Any) -> Path | None:
    """Doğrulanmış koşu dizini (`gh/<id>-<deneme>`) → mutlak yol; geçersizse None."""
    if not isinstance(dizin, str) or not GH_DIR_RE.match(dizin):
        return None
    return kok() / dizin


def mevcut(dizin: str | None) -> Path | None:
    """Tamamlanmış (işaret dosyası olan) yerel kopya; yoksa None."""
    p = yol(dizin)
    if p is None:
        return None
    try:
        return p if (p / ISARET).is_file() else None
    except OSError:
        return None


def _dosyalari_gez(sonuc: Path) -> list[tuple[str, int, Path]]:
    """`sonuc` altındaki normal dosyalar (göreli yol = zip içi yol); sembolik bağlar atlanır."""
    out: list[tuple[str, int, Path]] = []
    for kok_, dizinler, dosyalar in os.walk(sonuc, followlinks=False):
        dizinler.sort()
        for ad in sorted(dosyalar):
            p = Path(kok_) / ad
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                boyut = p.stat().st_size
            except OSError:
                continue
            out.append((p.relative_to(sonuc).as_posix(), boyut, p))
            if len(out) >= MAX_ARAMA:
                return out
    return out


def disk_dosyalari(
    yerel: Path, adlar: tuple[str, ...], ekler: tuple[str, ...] = ()
) -> dict[str, bytes]:
    """Yerel kopyadan `GitHubCi.artifact_files` ile aynı seçim (anahtarlar zip içi yollardır)."""
    girdiler = ((r, b, p.read_bytes) for r, b, p in _dosyalari_gez(yerel / SONUC_KOK))
    return dosya_sec(girdiler, adlar, ekler)


def _en_kisa(adaylar: list[str]) -> str | None:
    return min(adaylar, key=lambda y: (y.count("/"), len(y), y)) if adaylar else None


def yollari_bul(yerel: Path) -> dict[str, str]:
    """Yerel kopyadaki raporların koşu dizinine göre yolları (`_url` ile sunulur)."""
    sonuc = yerel / SONUC_KOK
    dosyalar = [r for r, _b, _p in _dosyalari_gez(sonuc)]

    def ada_gore(ad: str) -> str | None:
        return _en_kisa([r for r in dosyalar if r.rsplit("/", 1)[-1] == ad])

    def dizin_index(*adlar: str) -> str | None:
        return _en_kisa(
            [
                r.rsplit("/", 1)[0]
                for r in dosyalar
                if r.endswith("/index.html") and r.rsplit("/", 2)[-2] in adlar
            ]
        )

    def dizin_ici(ad: str) -> str | None:
        return _en_kisa(
            [
                "/".join(r.split("/")[: r.split("/").index(ad) + 1])
                for r in dosyalar
                if ad in r.split("/")[:-1]
            ]
        )

    bulunan = {
        "junit": ada_gore("junit.xml"),
        "json": ada_gore("results.json"),
        "html": dizin_index("playwright-report", "html"),
        "allure": dizin_ici("allure-results"),
        "allure_html": (lambda d: f"{d}/index.html" if d else None)(dizin_index("allure-report")),
        "log": ada_gore("run-checks.log"),
        "meta": ada_gore("ci-meta.json"),
    }
    return {k: f"{SONUC_KOK}/{v}" for k, v in bulunan.items() if v}


def _gecicileri_temizle(gh_kok: Path) -> None:
    simdi = time.time()
    try:
        for p in gh_kok.iterdir():
            if p.name.startswith(".") and ".tmp-" in p.name:
                try:
                    if simdi - p.stat().st_mtime > GECICI_ESKI_S:
                        shutil.rmtree(p, ignore_errors=True)
                except OSError:
                    continue
    except OSError:
        return


def _ac(veri: bytes, hedef: Path) -> None:
    from tp_core.integrations.forge_github import safe_extract_zip

    try:
        safe_extract_zip(veri, hedef)
    except Exception as exc:  # ForgeValidationError: güvensiz/bozuk/çok büyük
        raise GitHubCiError(f"artefakt açılamadı: {temiz(exc, 200)}") from exc


def hazirla(
    gh: Any,
    artefaktlar: Sequence[Mapping[str, Any]],
    dizin: str,
    *,
    sonuc_zip: bytes | None = None,
) -> dict[str, Any]:
    """Koşunun yerel kopyasını hazırlar (varsa dokunmaz). Hata fırlatmaz.

    Döner: `{dizin, durum: indirildi|mevcut|yok|hata, yollar, hata?, indirilen: [ad]}`.
    `sonuc_zip`: alımın ayrıştırma için zaten indirdiği `test-local-results` zip'i (ikinci indirme
    yapılmaz).
    """
    hedef = yol(dizin)
    if hedef is None:
        return {"dizin": None, "durum": "hata", "hata": "geçersiz yerel dizin", "yollar": {}}
    var = mevcut(dizin)
    if var is not None:
        return {"dizin": dizin, "durum": "mevcut", "yollar": yollari_bul(var), "indirilen": []}
    canli = [a for a in artefaktlar if isinstance(a, Mapping) and not a.get("expired")]
    sonuc_art = next((a for a in canli if a.get("name") == RESULTS_ARTIFACT), None)
    rapor_art = next((a for a in canli if a.get("name") == REPORT_ARTIFACT), None)
    if sonuc_art is None and rapor_art is None:
        return {
            "dizin": dizin,
            "durum": "yok",
            "hata": f"'{RESULTS_ARTIFACT}' / '{REPORT_ARTIFACT}' artefaktı yok ya da süresi dolmuş",
            "yollar": {},
        }
    gh_kok = hedef.parent
    gecici = gh_kok / f".{hedef.name}.tmp-{uuid.uuid4().hex[:8]}"
    indirilen: list[str] = []
    try:
        gh_kok.mkdir(parents=True, exist_ok=True)
        _gecicileri_temizle(gh_kok)
        sonuc = gecici / SONUC_KOK
        sonuc.mkdir(parents=True)
        if sonuc_art is not None:
            _ac(sonuc_zip if sonuc_zip is not None else gh.artifact_zip(sonuc_art), sonuc)
            indirilen.append(RESULTS_ARTIFACT)
        if rapor_art is not None and "html" not in yollari_bul(gecici):
            # test-local-results raporu taşımıyorsa (eski ci.yml) ayrı rapor artefaktı.
            _ac(gh.artifact_zip(rapor_art), sonuc / "playwright-report")
            indirilen.append(REPORT_ARTIFACT)
        (gecici / ISARET).write_text(
            json.dumps(
                {
                    "artefaktlar": {
                        str(a.get("name")): a.get("id")
                        for a in (sonuc_art, rapor_art)
                        if a is not None and a.get("name") in indirilen
                    },
                    "zaman": services.now().isoformat(),
                },
                ensure_ascii=False,
            )
        )
        # Eşzamanlı ikinci alım (yeniden alım / geri doldurma) bu arada tamamlanmış bir kopya
        # koymuş olabilir: işaretliyse ona dokunulmaz, bu kopya atılır.
        if (var := mevcut(dizin)) is not None:
            shutil.rmtree(gecici, ignore_errors=True)
            return {"dizin": dizin, "durum": "mevcut", "yollar": yollari_bul(var), "indirilen": []}
        if hedef.exists():  # işaretsiz (yarım) eski kopya
            shutil.rmtree(hedef)
        gecici.rename(hedef)
    except Exception as exc:  # yerel kopya alımı asla düşürmez
        shutil.rmtree(gecici, ignore_errors=True)
        if (var := mevcut(dizin)) is not None:  # yarışı başka alım kazandı: geçerli kopya var
            return {"dizin": dizin, "durum": "mevcut", "yollar": yollari_bul(var), "indirilen": []}
        log.warning("GitHub artefaktı yerel kopyaya alınamadı (%s): %s", dizin, exc)
        return {
            "dizin": dizin,
            "durum": "hata",
            "hata": temiz(exc, 300),
            "yollar": {},
            "indirilen": [],
        }
    return {
        "dizin": dizin,
        "durum": "indirildi",
        "yollar": yollari_bul(hedef),
        "indirilen": indirilen,
    }


def saklama_sayisi() -> int:
    try:
        return max(1, int(float((os.environ.get("TP_GITHUB_ARTIFACTS_KEEP") or "").strip() or 30)))
    except ValueError:
        return 30


def disk_butcesi() -> int:
    """Yerel kopyaların toplam bayt sınırı (`TP_GITHUB_ARTIFACTS_MAX_GB`, varsayılan 5 GB)."""
    try:
        gb = float((os.environ.get("TP_GITHUB_ARTIFACTS_MAX_GB") or "").strip() or 5)
    except ValueError:
        gb = 5.0
    return max(1, int(gb * 1024**3))


def _boyut(p: Path) -> int:
    toplam = 0
    for kok_, _, dosyalar in os.walk(p):
        for ad in dosyalar:
            with contextlib.suppress(OSError):
                toplam += (Path(kok_) / ad).lstat().st_size
    return toplam


def budama(
    koru: Sequence[str] = (), en_cok: int | None = None, butce: int | None = None
) -> list[str]:
    """En yeni `TP_GITHUB_ARTIFACTS_KEEP` kopya dışındakileri, ayrıca toplam boyut
    `TP_GITHUB_ARTIFACTS_MAX_GB`'yi aşıyorsa en eskilerden başlayarak fazlasını siler; silinen
    dizin adlarını döner (tek VM diski Postgres'le paylaşılır).

    `koru`: az önce hazırlanan dizin(ler) — sayıya ve boyuta girer ama asla silinmez.
    """
    sinir = en_cok if en_cok is not None else saklama_sayisi()
    butce_ = butce if butce is not None else disk_butcesi()
    gh_kok = kok() / "gh"
    try:
        adaylar = [
            p
            for p in gh_kok.iterdir()
            if p.is_dir() and not p.is_symlink() and GH_DIR_RE.match(f"gh/{p.name}")
        ]
    except OSError:
        return []

    def zaman(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    adaylar.sort(key=lambda p: (f"gh/{p.name}" in koru, zaman(p)), reverse=True)
    silinen: list[str] = []
    kullanilan = 0
    for i, p in enumerate(adaylar):
        ad = f"gh/{p.name}"
        boyut = _boyut(p)
        if ad in koru or (i < sinir and kullanilan + boyut <= butce_):
            kullanilan += boyut
            continue
        shutil.rmtree(p, ignore_errors=True)
        silinen.append(ad)
    return silinen
