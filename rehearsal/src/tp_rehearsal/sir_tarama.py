"""Prova rapor dizininde `.env` sır değerlerini arar — değeri hiçbir zaman yazdırmadan.

Arayüz provasının çıktısı (video, ekranlar, rapor) sunum makinesine yedek video olarak kopyalanır
(DEMO-AKISI §1.1). Playwright izi (trace.zip) form doldurma argümanlarını ve giriş POST
gövdelerini kaydeder; bu yüzden prova izi kapalıdır ve bu tarayıcı her koşudan sonra dizini
denetler:

    uv run --project rehearsal python -m tp_rehearsal.sir_tarama <dizin> [--iz-sil]

- Düz dosyalar baytça, `.zip` arşivlerinin üyeleri de açılarak taranır (büyük dosyalar parça
  parça okunur; .webm yüzlerce MB olabilir).
- Değer biçimleri: ham, JSON kaçışlı, URL kodlu (form gövdesi) — giriş isteklerinin taşıdığı haller.
- `--iz-sil`: taramadan önce `trace.zip` dosyalarını siler (eski koşulardan kalan izler dahil).

Çıktı yalnızca dosya yolu ve eşleşen değer SAYISIDIR. Çıkış: 0 temiz · 1 sır bulundu · 2 kullanım.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, quote_plus

from tp_rehearsal.env import Ortam, Sirlar

PARCA = 4 * 1024 * 1024
IZ_ADI = "trace.zip"


def bicimler(deger: str) -> set[bytes]:
    """Bir sır değerinin dosyada görünebileceği bayt biçimleri."""
    hal = {
        deger,
        json.dumps(deger)[1:-1],
        json.dumps(deger, ensure_ascii=False)[1:-1],
        quote(deger, safe=""),
        quote_plus(deger, safe=""),
    }
    return {h.encode("utf-8") for h in hal if h}


def _parcalar(akis: BinaryIO, ortusme: int) -> Iterator[bytes]:
    """Akışı, sınırda bölünen eşleşmeler kaçmasın diye örtüşen parçalarla okur."""
    onceki = b""
    while True:
        p = akis.read(PARCA)
        if not p:
            return
        blok = onceki + p
        yield blok
        onceki = blok[-ortusme:] if ortusme else b""


def _akista_bul(akis: BinaryIO, desenler: dict[bytes, int]) -> set[int]:
    """Akışta geçen sırların sıra numaraları."""
    ortusme = max((len(d) for d in desenler), default=1) - 1
    bulunan: set[int] = set()
    for blok in _parcalar(akis, ortusme):
        for d, i in desenler.items():
            if i not in bulunan and d in blok:
                bulunan.add(i)
    return bulunan


def _desenler(degerler: Iterable[str]) -> dict[bytes, int]:
    d: dict[bytes, int] = {}
    for i, v in enumerate(degerler):
        for b in bicimler(v):
            d.setdefault(b, i)
    return d


def iz_sil(kok: Path) -> list[Path]:
    silinen = []
    for p in sorted(kok.rglob(IZ_ADI)):
        if p.is_file():
            p.unlink()
            silinen.append(p)
    return silinen


def tara(kok: Path, sirlar: Sirlar) -> list[tuple[str, int]]:
    """[(göreli yol[!üye], eşleşen farklı sır sayısı)] — değer döndürülmez."""
    desenler = _desenler(sirlar.degerler)
    if not desenler or not kok.exists():
        return []
    bulgular: list[tuple[str, int]] = []
    dosyalar = [kok] if kok.is_file() else sorted(p for p in kok.rglob("*") if p.is_file())
    for p in dosyalar:
        ad = str(p.relative_to(kok)) if p != kok else p.name
        with p.open("rb") as f:
            n = _akista_bul(f, desenler)
        if n:
            bulgular.append((ad, len(n)))
        if zipfile.is_zipfile(p):
            try:
                with zipfile.ZipFile(p) as z:
                    for uye in z.infolist():
                        if uye.is_dir():
                            continue
                        with z.open(uye) as f:
                            n = _akista_bul(f, desenler)
                        if n:
                            bulgular.append((f"{ad}!{uye.filename}", len(n)))
            except (zipfile.BadZipFile, OSError, RuntimeError):
                bulgular.append((f"{ad}!<açılamadı>", 0))
    return [b for b in bulgular if b[1] > 0]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tp_rehearsal.sir_tarama", description=__doc__.split("\n")[0])
    p.add_argument("dizin", type=Path, nargs="+")
    p.add_argument("--iz-sil", action="store_true", help="önce trace.zip dosyalarını sil")
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    a = p.parse_args(argv)
    sirlar = Ortam.yukle(a.repo).sirlar
    if not sirlar.degerler:
        print("UYARI: .env'de taranacak sır değeri yok", file=sys.stderr)
    toplam = 0
    for kok in a.dizin:
        if not kok.exists():
            continue
        if a.iz_sil:
            for s in iz_sil(kok):
                print(f"iz silindi: {s}")
        for ad, n in tara(kok, sirlar):
            toplam += 1
            print(f"SIR BULUNDU: {kok}/{ad} ({n} farklı değer)")
    if toplam:
        print(
            f"HATA: {toplam} dosyada .env sır değeri var (değerler yazdırılmadı). "
            "Dosyaları silin; paylaşmayın.",
            file=sys.stderr,
        )
        return 1
    print("Sır taraması temiz: " + ", ".join(str(k) for k in a.dizin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
