"""Yerel forge yolları proje başına (TP-COK-PROJE-PLANI §4.3) — tek yol çözücü.

Kökler kurulum ayarıdır (D): `TP_FORGE_PATH` (bugün varsayılan projenin bare deposu,
`/forge/demo-app.git`) ve `TP_FORGE_MIRROR_PATH` (`/forge-mirror/demo-app.git`); kök bu yolların
üst dizinidir (`/forge`, `/forge-mirror`; compose volume bağlama noktaları).

- **Varsayılan proje** (`varsayilan_pid()`): eski yollar birebir (`/forge/demo-app.git`,
  `TP_FORGE_PRS_PATH`'in dizini, `/forge-mirror/demo-app.git`) — canlı göçte dosya taşınmaz.
- **Diğer projeler:** `/forge/<pid>/repo.git`, `/forge/<pid>/prs/`, `/forge-mirror/<pid>.git`.

pid yol bileşeni olarak kullanıldığından burada doğrulanır (`/`, `..`, boşluk yok).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from tp_core.proje.baglam import varsayilan_pid

VARSAYILAN_DEPO = "/forge/demo-app.git"
VARSAYILAN_AYNA = "/forge-mirror/demo-app.git"
PRS_DOSYASI = "tp-prs.json"
_PID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class GecersizProjeKimligi(ValueError):
    """pid yol bileşeni olamaz."""


def _dogrula(pid: str) -> str:
    if not _PID_RE.fullmatch(pid or "") or ".." in pid:
        raise GecersizProjeKimligi(f"proje kimliği yol bileşeni olamaz: {pid!r}")
    # Varsayılan projenin depo/ayna adlarıyla çakışma ve `.git` soneki yasak: türetilen yol başka
    # projenin deposuna ya da aynasına denk gelmesin (güvenlik review: pid/yol çakışması).
    ayrilmis = {
        _ortam("TP_FORGE_PATH", VARSAYILAN_DEPO).name,
        _ortam("TP_FORGE_PATH", VARSAYILAN_DEPO).stem,
        _ortam("TP_FORGE_MIRROR_PATH", VARSAYILAN_AYNA).name,
        _ortam("TP_FORGE_MIRROR_PATH", VARSAYILAN_AYNA).stem,
    }
    if pid.lower().endswith(".git") or pid in ayrilmis:
        raise GecersizProjeKimligi(f"proje kimliği ayrılmış bir yol adıyla çakışıyor: {pid!r}")
    return pid


def _ortam(ad: str, varsayilan: str) -> Path:
    return Path((os.environ.get(ad) or "").strip() or varsayilan)


def varsayilan_mi(pid: str) -> bool:
    return pid == varsayilan_pid()


def forge_koku() -> Path:
    """`/forge` (TP_FORGE_PATH'in üst dizini)."""
    return _ortam("TP_FORGE_PATH", VARSAYILAN_DEPO).parent


def ayna_koku() -> Path:
    """`/forge-mirror` (TP_FORGE_MIRROR_PATH'in üst dizini)."""
    return _ortam("TP_FORGE_MIRROR_PATH", VARSAYILAN_AYNA).parent


def depo_yolu(pid: str) -> Path:
    """Projenin bare deposu."""
    if varsayilan_mi(pid):
        return _ortam("TP_FORGE_PATH", VARSAYILAN_DEPO)
    return forge_koku() / _dogrula(pid) / "repo.git"


def pr_dizini(pid: str) -> Path:
    """Projenin PR kaydı dizini (`<dizin>/tp-prs.json`)."""
    if varsayilan_mi(pid):
        prs = (os.environ.get("TP_FORGE_PRS_PATH") or "").strip()
        return Path(prs).parent if prs else depo_yolu(pid).parent
    return forge_koku() / _dogrula(pid) / "prs"


def pr_dosyasi(pid: str) -> Path:
    """Projenin PR kaydı dosyası (varsayılan projede `TP_FORGE_PRS_PATH` aynen)."""
    if varsayilan_mi(pid):
        prs = (os.environ.get("TP_FORGE_PRS_PATH") or "").strip()
        if prs:
            return Path(prs)
    return pr_dizini(pid) / PRS_DOSYASI


def ayna_yolu(pid: str) -> Path:
    """GitHub kipinde toolchain'in salt okunur aynası."""
    if varsayilan_mi(pid):
        return _ortam("TP_FORGE_MIRROR_PATH", VARSAYILAN_AYNA)
    return ayna_koku() / f"{_dogrula(pid)}.git"
