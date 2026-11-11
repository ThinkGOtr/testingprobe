"""Otomasyon ayarları (`otomasyon_ayari` tablosu; specs/013-sprint-otomasyonu §3.1).

Satır yoksa varsayılan geçerlidir; portal yalnız değişeni yazar. Değerler tiplenmiş okunur:
tabloya elle yazılmış bozuk bir değer varsayılana düşer (otomasyon ayarı hatası akışı durdurmaz).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.orm import Session

from tp_core.audit.session import audit_on_commit
from tp_core.models.otomasyon_feature import OtomasyonAyari
from tp_core.workflow.service import Principal

# Otomatik işlerin (onay sonrası kod, Jira tetiği, otomatik case) tek sistem aktörü.
OTOMASYON_AKTORU = Principal(None, "otomasyon", "system", "system")

OTOMATIK_KOD = "otomatik_kod_uretimi"
JIRA_TETIK = "jira_tetik"

ARALIK_MIN_S = 30
ARALIK_MAX_S = 3600
DURUM_MAX = 100


@dataclass(frozen=True)
class OtomatikKod:
    """Case onaylanınca kod üretimi kuyruğa alınır mı (platform `web`, dil algılanır)."""

    acik: bool = True


@dataclass(frozen=True)
class JiraTetik:
    """Jira durum tetiği: `durum`a gelen story çekilir ve ön incelemeye girer; PO onayı
    geldiğinde (`otomatik_case` açıksa) case üretimi kendiliğinden başlar."""

    acik: bool = True
    durum: str = "QA To Do"
    aralik_s: int = 60
    otomatik_case: bool = True


VARSAYILAN: dict[str, Any] = {OTOMATIK_KOD: OtomatikKod(), JIRA_TETIK: JiraTetik()}


def _bool(d: dict[str, Any], k: str, v: bool) -> bool:
    x = d.get(k, v)
    return x if isinstance(x, bool) else v


def _parse(anahtar: str, ham: Any) -> Any:
    d = ham if isinstance(ham, dict) else {}
    if anahtar == OTOMATIK_KOD:
        return OtomatikKod(acik=_bool(d, "acik", True))
    v = JiraTetik()
    durum = d.get("durum")
    aralik = d.get("aralik_s")
    return JiraTetik(
        acik=_bool(d, "acik", v.acik),
        durum=durum.strip()
        if isinstance(durum, str) and durum.strip() and len(durum) <= DURUM_MAX
        else v.durum,
        aralik_s=aralik
        if isinstance(aralik, int)
        and not isinstance(aralik, bool)
        and ARALIK_MIN_S <= aralik <= ARALIK_MAX_S
        else v.aralik_s,
        otomatik_case=_bool(d, "otomatik_case", v.otomatik_case),
    )


def oku(session: Session, anahtar: str) -> Any:
    if anahtar not in VARSAYILAN:
        raise KeyError(anahtar)
    satir = session.get(OtomasyonAyari, anahtar)
    return VARSAYILAN[anahtar] if satir is None else _parse(anahtar, satir.deger)


def otomatik_kod(session: Session) -> OtomatikKod:
    return oku(session, OTOMATIK_KOD)


def jira_tetik(session: Session) -> JiraTetik:
    return oku(session, JIRA_TETIK)


def hepsi(session: Session) -> dict[str, dict[str, Any]]:
    """API/portal görünümü: {anahtar: {...değerler, guncelleyen, guncelleme}}."""
    out: dict[str, dict[str, Any]] = {}
    for anahtar in VARSAYILAN:
        satir = session.get(OtomasyonAyari, anahtar)
        out[anahtar] = {
            **asdict(oku(session, anahtar)),
            "guncelleyen": satir.guncelleyen if satir else None,
            "guncelleme": satir.guncelleme if satir else None,
        }
    return out


def yaz(session: Session, anahtar: str, deger: Any, aktor: str) -> Any:
    """Doğrulanmış değeri yazar (geçersiz alan ValueError) ve denetime kaydeder."""
    if anahtar not in VARSAYILAN:
        raise KeyError(anahtar)
    if not isinstance(deger, dict):
        raise ValueError("ayar değeri nesne olmalı")
    onceki = oku(session, anahtar)
    birlesik = {**asdict(onceki), **deger}
    yeni = _parse(anahtar, birlesik)
    if asdict(yeni) != birlesik:
        hatali = sorted(k for k in birlesik if asdict(yeni).get(k, object()) != birlesik[k])
        raise ValueError("geçersiz ayar alanı: " + ", ".join(hatali))
    satir = session.get(OtomasyonAyari, anahtar)
    if satir is None:
        session.add(OtomasyonAyari(anahtar=anahtar, deger=asdict(yeni), guncelleyen=aktor))
    else:
        satir.deger = asdict(yeni)
        satir.guncelleyen = aktor
    session.flush()
    audit_on_commit(
        session, aktor, "otomasyon.ayar", f"ayar:{anahtar}",
        {"onceki": asdict(onceki), "yeni": asdict(yeni)},
    )  # fmt: skip
    return yeni
