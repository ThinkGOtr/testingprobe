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
AC_RE = re.compile(r"^AC[1-9][0-9]{0,2}$")
TABLO_RE = re.compile(r"^T[1-9][0-9]{0,2}$")
METIN = ("kod", "ad", "tur", "aciklama", "yakalayan_kural")
ALANLAR = (*METIN, "ac_refs", "tablo", "ayirt_edici")
ZORUNLU = ("kod", "ad", "tur", "aciklama")
# K9: her kayıtta bulunmalı (`ac_refs` boş, `tablo` null olabilir).
ZORUNLU_ANAHTAR = ("ac_refs", "tablo", "ayirt_edici")
AYIRT_EDICI = ("girdi", "dogru", "hatali")

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
        eksik_anahtar = [a for a in ZORUNLU_ANAHTAR if a not in h]
        if eksik_anahtar:
            raise KatalogHatasi(f"{kod}: eksik alan: {', '.join(eksik_anahtar)}")
        gorulen.add(kod)
        kayit: dict[str, Any] = {
            a: (h.get(a).strip() if isinstance(h.get(a), str) else None) for a in METIN
        }
        kayit["ac_refs"] = _ac_refs(kod, h["ac_refs"])
        kayit["tablo"] = _tablo(kod, h["tablo"])
        kayit["ayirt_edici"] = _ayirt_edici(kod, h["ayirt_edici"])
        out.append(kayit)
    if not out:
        raise KatalogHatasi("hata kataloğu boş")
    return out


def _ac_refs(kod: str, v: Any) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) and AC_RE.match(x) for x in v):
        raise KatalogHatasi(f"{kod}: ac_refs AC<n> listesi olmalı (boş olabilir)")
    if len(set(v)) != len(v):
        raise KatalogHatasi(f"{kod}: ac_refs tekrar içeriyor")
    return list(v)


def _tablo(kod: str, v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not TABLO_RE.match(v):
        raise KatalogHatasi(f"{kod}: tablo T<n> ya da null olmalı")
    return v


def _deger_sozlugu(kod: str, ad: str, v: Any) -> dict[str, Any]:
    if not isinstance(v, dict) or not v:
        raise KatalogHatasi(f"{kod}: ayirt_edici.{ad} boş olmayan nesne olmalı")
    for k, x in v.items():
        if not isinstance(k, str) or not isinstance(x, (str, int, float, bool)):
            raise KatalogHatasi(f"{kod}: ayirt_edici.{ad}.{k} düz değer olmalı")
    return dict(v)


def _ayirt_edici(kod: str, v: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(v, dict) or set(v) != set(AYIRT_EDICI):
        raise KatalogHatasi(f"{kod}: ayirt_edici {{girdi, dogru, hatali}} olmalı")
    out = {a: _deger_sozlugu(kod, a, v[a]) for a in AYIRT_EDICI}
    if set(out["dogru"]) != set(out["hatali"]):
        raise KatalogHatasi(f"{kod}: ayirt_edici.dogru ve hatali aynı çıktıları vermeli")
    if out["dogru"] == out["hatali"]:
        raise KatalogHatasi(f"{kod}: ayirt_edici doğru ve hatalı çıktıyı ayırt etmiyor")
    return out


def yukle(yol: Path) -> list[dict[str, Any]]:
    try:
        veri = yaml.safe_load(yol.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KatalogHatasi(f"hata kataloğu okunamadı ({yol}): {exc}") from exc
    return dogrula(veri)


def katalog() -> list[dict[str, Any]]:
    """Doğrulanmış katalog (`kod, ad, tur, aciklama, yakalayan_kural, ac_refs, tablo,
    ayirt_edici: {girdi, dogru, hatali}`); kopyası döner."""
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
