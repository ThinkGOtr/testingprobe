"""Triage dil eklentileri (014; sözleşme specs/014-test-dilleri/plan.md §2.1).

`triage/diller/<dil>.py` modül düzeyinde `EKLENTI` (`TriageEklentisi`) tanımlar; keşif otomatik.
ts/java kuralları `triage/rules.py`, `triage/java.py`, `triage/java_web.py`'de kalır (davranış
değişmez); yeni diller yalnız eklentiyle gelir.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import threading
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

# Hata türleri: `triage.rules.Sinyal.tur()` sözlüğü (test-runner `failure.type`) + müşteri CI
# derleme hatası (`derleme`).
TURLER = frozenset(
    {
        "locator_timeout",
        "locator_not_found",
        "assertion",
        "navigation",
        "test_data",
        "other",
        "derleme",
    }
)


# Dil şeritlerinin (Ş1 python, Ş3 kotlin, Ş4 swift) kısa türleri → `Sinyal.tur()` sözlüğü.
_KISA_TURLER = frozenset({"locator", "environment", "timeout"})
_BULUNAMADI = ("not found", "resolved to 0 elements", "öğe görünmedi", "öğe yok",
               "NoSuchElement", "NoMatchingView", "bulunamadı")  # fmt: skip


def normal_tur(tur: str | None, mesaj: str | None = None, veri_mi: bool = False) -> str | None:
    """014 entegrasyonu: eklentinin döndürdüğü tür `TURLER`'de değilse eşlenir — `locator` →
    `locator_not_found` (öğe yok iletisi) ya da `locator_timeout`; `timeout` → `locator_timeout`;
    `environment` → `test_data` (kurulum/veri iletisi, `veri_mi`) ya da `navigation` (Java
    `ortam` kuralıyla aynı). Bilinmeyen tür `other`."""
    if tur is None or tur in TURLER:
        return tur
    if tur == "locator":
        m = (mesaj or "").lower()
        return (
            "locator_not_found" if any(b.lower() in m for b in _BULUNAMADI) else ("locator_timeout")
        )
    if tur == "timeout":
        return "locator_timeout"
    if tur == "environment":
        return "test_data" if veri_mi else "navigation"
    return "other"


@runtime_checkable
class TriageEklentisi(Protocol):
    ad: str

    def hata_turu(self, mesaj: str, istisna: str | None = None) -> str | None: ...

    def beklenen_gorulen(self, mesaj: str | None) -> tuple[str | None, str | None]: ...

    def test_kimligi(self, test_adi: str, dosya: str | None) -> str | None: ...

    def test_dosyasi_mi(self, dosya: str | None) -> bool: ...


_KILIT = threading.Lock()
_KAYIT: dict[str, TriageEklentisi] | None = None
_HATALAR: dict[str, str] = {}


def kayit() -> dict[str, TriageEklentisi]:
    global _KAYIT
    with _KILIT:
        if _KAYIT is None:
            k: dict[str, TriageEklentisi] = {}
            for mod in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
                if mod.name.startswith("_"):
                    continue
                try:
                    e = importlib.import_module(f"{__name__}.{mod.name}").EKLENTI
                except Exception as exc:
                    _HATALAR[mod.name] = f"{type(exc).__name__}: {exc}"
                    log.warning("triage dil eklentisi yüklenemedi: %s (%s)", mod.name, exc)
                    continue
                k[e.ad] = e
            _KAYIT = k
        return _KAYIT


def eklenti(dil: str | None) -> TriageEklentisi | None:
    return kayit().get(dil or "")


def dosyadan(dosya: str | None) -> TriageEklentisi | None:
    """Dosya adından dil eklentisi (ilk eşleşen)."""
    for e in kayit().values():
        try:
            if e.test_dosyasi_mi(dosya):
                return e
        except Exception:  # pragma: no cover - eklenti hatası sınıflandırmayı düşürmez
            continue
    return None


def hatalar() -> dict[str, str]:
    kayit()
    return dict(_HATALAR)


def _sifirla() -> None:
    global _KAYIT
    with _KILIT:
        _KAYIT = None
        _HATALAR.clear()
