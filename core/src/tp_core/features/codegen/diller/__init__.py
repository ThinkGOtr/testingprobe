"""Çekirdek dil eklentileri (014 test dilleri; sözleşme specs/014-test-dilleri/plan.md §2).

Her modül `codegen/diller/<dil>.py` modül düzeyinde `EKLENTI` nesnesi tanımlar (`DilEklentisi`
protokolü). Keşif otomatiktir (`pkgutil`); merkezi listeye satır eklenmez. `_` ile başlayan
modüller (ortak yardımcılar) atlanır. Bir modülün yükleme hatası diğerlerini düşürmez:
uyarı loglanır, `hatalar()` döndürür (birim testi boş bekler).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from tp_core.features.codegen.platform import Cati
    from tp_core.features.codegen.render import Rendered, RenderInput

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlgilaKalibi:
    """Dil algılama kalıbı: `kok_ayari` kökünün altındaki `alt_dizin`de `test_dosyasi_mi`
    sayılır (yalnız `platformlar` için)."""

    platformlar: frozenset[str]
    kok_ayari: str
    alt_dizin: str


@runtime_checkable
class DilEklentisi(Protocol):
    ad: str
    proje_dosyasi: str
    algila_kaliplari: tuple[AlgilaKalibi, ...]

    def render(
        self,
        inp: RenderInput,
        cati: Cati,
        rules: Path,
        *,
        referans_dil: str | None = None,
        sembol_tablosu: Mapping[str, Any] | None = None,
    ) -> Rendered: ...

    def literal(self, value: Any) -> str: ...

    def ident(self, value: Any) -> str: ...

    def sinif_adi(
        self, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
    ) -> str | None: ...

    def uretilen_yol(
        self, cati: Cati, kok: str, story_key: str | None, sira_no: int, case_id: uuid.UUID
    ) -> str: ...

    def test_dosyasi_mi(self, yol: str) -> bool: ...

    def eslemeyi_donustur(self, output: Any) -> Any: ...


_KILIT = threading.Lock()
_KAYIT: dict[str, DilEklentisi] | None = None
_HATALAR: dict[str, str] = {}


def _kesfet() -> dict[str, DilEklentisi]:
    kayit: dict[str, DilEklentisi] = {}
    for mod in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
        if mod.name.startswith("_"):
            continue
        try:
            modul = importlib.import_module(f"{__name__}.{mod.name}")
            eklenti = modul.EKLENTI
        except Exception as exc:  # bir dilin hatası diğerlerini düşürmez
            _HATALAR[mod.name] = f"{type(exc).__name__}: {exc}"
            log.warning("dil eklentisi yüklenemedi: %s (%s)", mod.name, exc)
            continue
        kayit[eklenti.ad] = eklenti
    return kayit


def kayit() -> dict[str, DilEklentisi]:
    """Ad → eklenti (ilk çağrıda keşfedilir)."""
    global _KAYIT
    with _KILIT:
        if _KAYIT is None:
            _KAYIT = _kesfet()
        return _KAYIT


def eklenti(dil: str | None) -> DilEklentisi | None:
    return kayit().get(dil or "")


def adlar() -> tuple[str, ...]:
    return tuple(kayit())


def hatalar() -> dict[str, str]:
    kayit()
    return dict(_HATALAR)


def _sifirla() -> None:
    """Test: keşfi yeniden yap (eklenti ekleyip kaldıran testler için)."""
    global _KAYIT
    with _KILIT:
        _KAYIT = None
        _HATALAR.clear()
