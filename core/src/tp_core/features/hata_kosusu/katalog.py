"""Ekilmiş hata kataloğu: `rules/hata-katalogu.yaml` (ANALIZ §4.6).

Dosya bir kez okunur ve doğrulanır (süreç önbelleği); bozuk dosya `KatalogHatasi` verir. Kodlar
demo uygulamanın kataloğuyla aynıdır (`demo-app/api/src/demoapp_api/faults.py`); core yalnız kodu
toolchain'e iletir (`fault=<kod>`), hatayı test fixture'ı uygular.
"""

from __future__ import annotations

import copy
import re
import threading
from pathlib import Path
from typing import Any

import yaml

from tp_core.models import enums

KOD_RE = re.compile(r"^[a-z0-9_]{1,40}$")
ALANLAR = ("kod", "ad", "tur", "aciklama", "yakalayan_kural")
ZORUNLU = ("kod", "ad", "tur", "aciklama")

_LOCK = threading.Lock()
_ONBELLEK: dict[Path, list[dict[str, Any]]] = {}


class KatalogHatasi(ValueError):
    """`rules/hata-katalogu.yaml` okunamadı ya da biçimi geçersiz."""


def katalog_yolu() -> Path:
    from tp_core.gateway import find_rules_dir

    return find_rules_dir() / "hata-katalogu.yaml"


def dogrula(veri: Any) -> list[dict[str, Any]]:
    """Ham YAML → doğrulanmış hata listesi (sıra korunur). Hata varsa `KatalogHatasi`."""
    if not isinstance(veri, dict) or not isinstance(veri.get("hatalar"), list):
        raise KatalogHatasi("hata kataloğu `hatalar` listesi içermiyor")
    if veri.get("version") != 1:
        raise KatalogHatasi(f"desteklenmeyen katalog sürümü: {veri.get('version')!r}")
    out: list[dict[str, Any]] = []
    gorulen: set[str] = set()
    for i, h in enumerate(veri["hatalar"]):
        if not isinstance(h, dict):
            raise KatalogHatasi(f"{i}. kayıt nesne değil")
        eksik = [a for a in ZORUNLU if not isinstance(h.get(a), str) or not h[a].strip()]
        if eksik:
            raise KatalogHatasi(f"{i}. kayıtta eksik alan: {', '.join(eksik)}")
        fazla = sorted(set(h) - set(ALANLAR))
        if fazla:
            raise KatalogHatasi(f"{i}. kayıtta bilinmeyen alan: {', '.join(fazla)}")
        kod = h["kod"]
        if not KOD_RE.match(kod):
            raise KatalogHatasi(f"geçersiz hata kodu: {kod!r}")
        if kod in gorulen:
            raise KatalogHatasi(f"hata kodu iki kez geçiyor: {kod}")
        if h["tur"] not in enums.HATA_TURU:
            raise KatalogHatasi(f"{kod}: geçersiz tür {h['tur']!r} (kod | veri)")
        kural = h.get("yakalayan_kural")
        if kural is not None and not isinstance(kural, str):
            raise KatalogHatasi(f"{kod}: yakalayan_kural metin olmalı")
        gorulen.add(kod)
        out.append({a: (h.get(a).strip() if isinstance(h.get(a), str) else None) for a in ALANLAR})
    if not out:
        raise KatalogHatasi("hata kataloğu boş")
    return out


def yukle(yol: Path) -> list[dict[str, Any]]:
    try:
        veri = yaml.safe_load(yol.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KatalogHatasi(f"hata kataloğu okunamadı ({yol}): {exc}") from exc
    return dogrula(veri)


def katalog() -> list[dict[str, Any]]:
    """Doğrulanmış katalog (`kod, ad, tur, aciklama, yakalayan_kural`); kopyası döner."""
    yol = katalog_yolu()
    with _LOCK:
        if yol not in _ONBELLEK:
            _ONBELLEK[yol] = yukle(yol)
        return copy.deepcopy(_ONBELLEK[yol])


def kodlar() -> list[str]:
    return [h["kod"] for h in katalog()]


def ad(kod: str) -> str:
    """Hatanın görünen adı; katalogda yoksa kodun kendisi."""
    return next((h["ad"] for h in katalog() if h["kod"] == kod), kod)


def onbellegi_temizle() -> None:
    with _LOCK:
        _ONBELLEK.clear()
