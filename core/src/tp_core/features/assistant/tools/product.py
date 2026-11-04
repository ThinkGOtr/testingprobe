"""Ürünün kendisi hakkında araçlar: `product_search`, `product_read` (AI-ASISTAN-PLANI §5.1).

Kaynak, core-worker'a salt okunur bağlanan ürün bilgi paketidir (`/opt/tp-bilgi`; üretici:
`tp_core.features.assistant.paket`). Yalnızca MANIFEST.json'daki yollar okunur:

- `product_read {path, start_line?, end_line?}` — MANIFEST anahtarıyla **birebir** eşleşme (büyük/
  küçük harf dahil); satır numaralı, en çok 400 satır. `path` boş ya da `/` ile bitiyorsa paketteki
  dosyaların listesi.
- `product_search {query, kapsam?: portal|core|docs}` — manifest dosyalarında sabit metin araması
  (büyük/küçük harf duyarsız); en çok 50 sonuç, `yol:satır: metin`.

Yol güvenliği: `..`/`.`/boş bileşen, mutlak yol, ters bölü ve NUL reddedilir; dosya, paket
kökünden itibaren her bileşen `O_NOFOLLOW` ile açılarak okunur (symlink izlenmez, kontrol ile
açma arasında değiştirilen ara dizin de okunmaz) ve içerik MANIFEST'teki sha256 ile doğrulanır.
Kabuk yok.

Araçlar ham metin döndürür; sır temizleme, maskeleme, kanıt kimliği ve `<untrusted>` sarma ortak
sarmalayıcıdadır (`tools.base`, §5.0).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tp_core.features.assistant.paket import MANIFEST_ADI, SURUMLER_DIZINI
from tp_core.ports import ToolSpec

BILGI_DIZINI_ORTAM = "TP_BILGI_DIZIN"
BILGI_DIZINI_VARSAYILAN = "/opt/tp-bilgi"
MAX_LINES = 400
MAX_SEARCH_RESULTS = 50
MAX_LIST = 300
MAX_QUERY = 200
MAX_SNIPPET = 240
KAPSAMLAR: dict[str, tuple[str, ...]] = {
    "portal": ("review-portal/",),
    "core": ("core/",),
    "docs": ("docs/", "README.md", "rules/assistant/"),
}


class ProductToolError(RuntimeError):
    """Modele araç hatası olarak dönen, ayrıntı sızdırmayan hata."""


def _int_arg(args: dict[str, Any], key: str) -> int | None:
    deger = args.get(key)
    if deger is None:
        return None
    if isinstance(deger, bool) or not isinstance(deger, int | str):
        raise ProductToolError(f"'{key}' tam sayı olmalı")
    try:
        sayi = int(deger)
    except ValueError as exc:
        raise ProductToolError(f"'{key}' tam sayı olmalı") from exc
    if sayi < 1:
        raise ProductToolError(f"'{key}' 1'den başlar")
    return sayi


def _parcalar(yol: str) -> list[str]:
    """Güvenli göreli yol bileşenleri; kaçış/özel karakter varsa ProductToolError."""
    if "\x00" in yol or "\\" in yol:
        raise ProductToolError("geçersiz yol")
    if yol.startswith("/"):
        raise ProductToolError("mutlak yol kabul edilmez")
    parcalar = yol.split("/")
    if any(p in ("", ".", "..") for p in parcalar):
        raise ProductToolError("geçersiz yol")
    return parcalar


class UrunBilgisi:
    def __init__(self, kok: Path | str | None = None) -> None:
        kok = kok or os.environ.get(BILGI_DIZINI_ORTAM) or BILGI_DIZINI_VARSAYILAN
        # Kök (mount noktası / test geçici dizini) çözülür; altındaki hiçbir symlink izlenmez.
        self.kok = Path(kok).resolve()
        self._manifest_anahtar: tuple[int, int, int] | None = None
        self._manifest: dict[str, Any] = {}
        self._onbellek: dict[tuple[str, str], str] = {}

    # ------------------------------------------------------------ manifest

    def manifest(self) -> dict[str, Any]:
        yol = self.kok / MANIFEST_ADI
        try:
            st = os.stat(yol, follow_symlinks=False)
        except OSError as exc:
            raise ProductToolError(
                "ürün bilgi paketi yok (sunucuda `make asistan-paket` çalıştırılmalı)"
            ) from exc
        if not stat.S_ISREG(st.st_mode):
            raise ProductToolError("ürün bilgi paketi geçersiz")
        anahtar = (st.st_ino, st.st_mtime_ns, st.st_size)
        if anahtar != self._manifest_anahtar:
            try:
                veri = json.loads(self._oku_bayt([MANIFEST_ADI]).decode("utf-8"))
            except (OSError, ValueError) as exc:
                raise ProductToolError("ürün bilgi paketi okunamadı") from exc
            dizin = veri.get("dizin") if isinstance(veri, dict) else None
            dosyalar = veri.get("dosyalar") if isinstance(veri, dict) else None
            if not isinstance(dizin, str) or not isinstance(dosyalar, dict):
                raise ProductToolError("ürün bilgi paketi geçersiz")
            dizin_parcalari = _parcalar(dizin)
            if len(dizin_parcalari) != 2 or dizin_parcalari[0] != SURUMLER_DIZINI:
                raise ProductToolError("ürün bilgi paketi geçersiz")
            self._manifest = veri
            self._manifest_anahtar = anahtar
            self._onbellek.clear()
        return self._manifest

    # ------------------------------------------------------------ güvenli okuma

    def _oku_bayt(self, parcalar: list[str], en_cok: int = 64 * 1024 * 1024) -> bytes:
        """Kökten itibaren her bileşeni `O_NOFOLLOW` ile açarak düzenli dosyayı okur."""
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        dizin_bayragi = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
        fd = os.open(self.kok, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            for parca in parcalar[:-1]:
                yeni = os.open(parca, dizin_bayragi, dir_fd=fd)
                os.close(fd)
                fd = yeni
            dosya_fd = os.open(parcalar[-1], os.O_RDONLY | nofollow, dir_fd=fd)
        finally:
            os.close(fd)
        with os.fdopen(dosya_fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise OSError("düzenli dosya değil")
            veri = f.read(en_cok + 1)
        if len(veri) > en_cok:
            raise OSError("dosya beklenenden büyük")
        return veri

    def _metin(self, yol: str) -> str:
        manifest = self.manifest()
        kayit = manifest["dosyalar"].get(yol)
        if not isinstance(kayit, dict):
            raise ProductToolError(f"Dosya pakette yok: {yol}")
        anahtar = (manifest["dizin"], yol)
        if anahtar in self._onbellek:
            return self._onbellek[anahtar]
        try:
            boyut = int(kayit.get("boyut", 0))
            veri = self._oku_bayt([*_parcalar(manifest["dizin"]), *_parcalar(yol)], boyut)
        except (OSError, ValueError, TypeError) as exc:
            raise ProductToolError(f"Dosya okunamadı: {yol}") from exc
        if hashlib.sha256(veri).hexdigest() != kayit.get("sha256"):
            raise ProductToolError(f"Dosya doğrulanamadı (paket güncelleniyor olabilir): {yol}")
        metin = veri.decode("utf-8", errors="replace")
        self._onbellek[anahtar] = metin
        return metin

    # ------------------------------------------------------------ araçlar

    def _liste(self, onek: str) -> str:
        dosyalar = sorted(k for k in self.manifest()["dosyalar"] if k.startswith(onek))
        if not dosyalar:
            return f"'{onek}' altında dosya yok" if onek else "paket boş"
        metin = "\n".join(dosyalar[:MAX_LIST])
        if len(dosyalar) > MAX_LIST:
            metin += f"\n… {len(dosyalar) - MAX_LIST} dosya daha (dizinle daraltın: 'core/src/')"
        return metin

    def product_read(self, args: dict[str, Any]) -> str:
        args = args if isinstance(args, dict) else {}
        path = args.get("path", "")
        if path is None:
            path = ""
        if not isinstance(path, str):
            raise ProductToolError("'path' metin olmalı")
        path = path.strip()
        bas = _int_arg(args, "start_line")
        son = _int_arg(args, "end_line")
        if not path:
            return self._liste("")
        if path.endswith("/"):
            _parcalar(path.rstrip("/"))
            return self._liste(path)
        _parcalar(path)
        metin = self._metin(path)
        satirlar = metin.splitlines()
        if not satirlar:
            return f"{path} (boş dosya)"
        bas = bas or 1
        if bas > len(satirlar):
            raise ProductToolError(f"{path} {len(satirlar)} satır; start_line={bas} dışında")
        son = min(son or len(satirlar), len(satirlar), bas + MAX_LINES - 1)
        if son < bas:
            raise ProductToolError("'end_line' start_line'dan küçük olamaz")
        govde = [f"{i}| {satirlar[i - 1]}" for i in range(bas, son + 1)]
        ust = f"{path} (satır {bas}-{son} / {len(satirlar)})"
        return "\n".join([ust, *govde])

    def product_search(self, args: dict[str, Any]) -> str:
        args = args if isinstance(args, dict) else {}
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ProductToolError("'query' gerekli")
        if len(query) > MAX_QUERY or "\x00" in query:
            raise ProductToolError(f"'query' en çok {MAX_QUERY} karakter")
        kapsam = args.get("kapsam")
        if kapsam is not None and kapsam not in KAPSAMLAR:
            raise ProductToolError("'kapsam' portal, core ya da docs olmalı")
        onekler = KAPSAMLAR[kapsam] if kapsam else ("",)
        aranan = query.strip().casefold()
        sonuclar: list[str] = []
        toplam = 0
        for yol in sorted(self.manifest()["dosyalar"]):
            if not yol.startswith(onekler):
                continue
            for no, satir in enumerate(self._metin(yol).splitlines(), start=1):
                if aranan in satir.casefold():
                    toplam += 1
                    if len(sonuclar) < MAX_SEARCH_RESULTS:
                        sonuclar.append(f"{yol}:{no}: {satir.strip()[:MAX_SNIPPET]}")
        if not sonuclar:
            return "eşleşme yok"
        if toplam > MAX_SEARCH_RESULTS:
            sonuclar.append(
                f"… {toplam - MAX_SEARCH_RESULTS} sonuç daha (sorguyu ya da kapsamı daraltın)"
            )
        return "\n".join(sonuclar)

    def tablo(self) -> dict[str, Callable[[dict[str, Any]], str]]:
        return {"product_search": self.product_search, "product_read": self.product_read}


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="product_search",
        description=(
            "Testing Probe ürününün kendi kaynak kodu ve belgelerinde sabit metin araması (büyük/"
            "küçük harf duyarsız, en çok 50 sonuç). Sonuç: 'yol:satır: metin'. kapsam: portal "
            "(arayüz), core (sunucu), docs (belgeler)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY},
                "kapsam": {"type": "string", "enum": sorted(KAPSAMLAR)},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="product_read",
        description=(
            "Testing Probe ürün dosyasını okur (satır numaralı, en çok 400 satır). path, "
            "product_search sonucundaki yolla birebir aynı olmalı; boş ya da '/' ile biten path "
            "dosya listesini verir."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "maxLength": 300},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
)
