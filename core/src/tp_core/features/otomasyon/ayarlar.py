"""Otomasyon ayarları (`otomasyon_ayari` tablosu; specs/013-sprint-otomasyonu §3.1, K14).

Satır yoksa varsayılan geçerlidir; portal yalnız değişeni yazar. Değerler tiplenmiş okunur:
tabloya elle yazılmış bozuk bir değer varsayılana düşer (otomasyon ayarı hatası akışı durdurmaz).

K14: `jira_tetik.acik` varsayılanı ortama bağlıdır: jira-sim'de açık, gerçek Jira'da kapalı
(`JiraSettings.is_simulator`). Varsayılan tabloya yazılmaz; satır yokken her okumada hesaplanır.

Tablo ayrıca tetiğin iç durumunu tutar (`TETIK_TABANI`; API'ye açık değil, `VARSAYILAN`da yok):
tetiğin "başlangıç işareti". `jira_tetik` ayarında `acik` ya da `durum` değişince bu satır silinir,
böylece bir sonraki tur yeniden taban çizgisi kurar (bkz. `jira_tetik.py`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tp_core.audit.session import audit_on_commit
from tp_core.models.otomasyon_feature import OtomasyonAyari
from tp_core.workflow.service import Principal

# Otomatik işlerin (onay sonrası kod, Jira tetiği, otomatik case) tek sistem aktörü.
OTOMASYON_AKTORU = Principal(None, "otomasyon", "system", "system")

OTOMATIK_KOD = "otomatik_kod_uretimi"
JIRA_TETIK = "jira_tetik"
# Tetiğin iç durumu (başlangıç işareti); ayar değil, API'ye çıkmaz.
TETIK_TABANI = "jira_tetik.taban"

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

    acik: bool = False  # gerçek varsayılan ortama bağlı: `varsayilan(JIRA_TETIK)` (K14)
    durum: str = "QA To Do"
    aralik_s: int = 60
    otomatik_case: bool = True


VARSAYILAN: dict[str, Any] = {OTOMATIK_KOD: OtomatikKod(), JIRA_TETIK: JiraTetik()}


def jira_sim_mi() -> bool:
    """Bağlı Jira simülatör mü (yapılandırmadan; ağ isteği yok). Belirlenemezse gerçek sayılır."""
    try:
        from tp_core.integrations.jira import get_jira_settings

        return bool(get_jira_settings().is_simulator)
    except Exception:
        return False


def varsayilan(anahtar: str) -> Any:
    """Satır yokken geçerli değer. `jira_tetik.acik`: sim'de True, gerçek Jira'da False (K14)."""
    if anahtar == JIRA_TETIK:
        return JiraTetik(acik=jira_sim_mi())
    return VARSAYILAN[anahtar]


def _bool(d: dict[str, Any], k: str, v: bool) -> bool:
    x = d.get(k, v)
    return x if isinstance(x, bool) else v


def _parse(anahtar: str, ham: Any) -> Any:
    d = ham if isinstance(ham, dict) else {}
    if anahtar == OTOMATIK_KOD:
        return OtomatikKod(acik=_bool(d, "acik", True))
    v = varsayilan(JIRA_TETIK)
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
    return varsayilan(anahtar) if satir is None else _parse(anahtar, satir.deger)


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
    """Doğrulanmış değeri yazar (geçersiz alan ValueError) ve denetime kaydeder.

    Eşzamanlı yazımlar sıralanır: satır yoksa varsayılanla eklenir (`ON CONFLICT DO NOTHING`),
    ardından `FOR UPDATE` ile kilitlenip birleştirilir (kayıp güncelleme ve PK yarışı yok).
    `jira_tetik`te `acik`/`durum` değişirse tetiğin başlangıç işareti silinir (yeni taban).
    """
    if anahtar not in VARSAYILAN:
        raise KeyError(anahtar)
    if not isinstance(deger, dict):
        raise ValueError("ayar değeri nesne olmalı")
    session.flush()
    session.execute(
        pg_insert(OtomasyonAyari)
        .values(anahtar=anahtar, deger=asdict(varsayilan(anahtar)), guncelleyen=aktor)
        .on_conflict_do_nothing(index_elements=["anahtar"])
    )
    satir = session.scalars(
        select(OtomasyonAyari)
        .where(OtomasyonAyari.anahtar == anahtar)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    onceki = _parse(anahtar, satir.deger)
    birlesik = {**asdict(onceki), **deger}
    yeni = _parse(anahtar, birlesik)
    if asdict(yeni) != birlesik:
        hatali = sorted(k for k in birlesik if asdict(yeni).get(k, object()) != birlesik[k])
        raise ValueError("geçersiz ayar alanı: " + ", ".join(hatali))
    satir.deger = asdict(yeni)
    satir.guncelleyen = aktor
    if anahtar == JIRA_TETIK and (onceki.acik != yeni.acik or onceki.durum != yeni.durum):
        session.execute(delete(OtomasyonAyari).where(OtomasyonAyari.anahtar == TETIK_TABANI))
    session.flush()
    audit_on_commit(
        session, aktor, "otomasyon.ayar", f"ayar:{anahtar}",
        {"onceki": asdict(onceki), "yeni": asdict(yeni)},
    )  # fmt: skip
    return yeni


# ------------------------------------------------------------- tetik başlangıç işareti


def tetik_tabani(session: Session) -> dict[str, Any] | None:
    """Tetiğin başlangıç işareti (`{durum, zaman}`) ya da None (taban kurulmamış)."""
    satir = session.get(OtomasyonAyari, TETIK_TABANI)
    return satir.deger if satir is not None and isinstance(satir.deger, dict) else None


def tetik_tabani_yaz(session: Session, durum: str, zaman: Any) -> None:
    deger = {"durum": durum, "zaman": zaman.isoformat() if hasattr(zaman, "isoformat") else zaman}
    session.execute(
        pg_insert(OtomasyonAyari)
        .values(anahtar=TETIK_TABANI, deger=deger, guncelleyen="jira-tetik")
        .on_conflict_do_update(index_elements=["anahtar"], set_={"deger": deger})
    )
