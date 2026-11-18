"""Projenin test ortamları (Home `environments`) ve koşu başına ortam bağlamı.

Home'da bir projenin birden çok ortamı olabilir (Geliştirme, Test, Staging, Canlı); ortam adres,
test hesabı ve salt okuma veritabanı gibi `allow_override: [E]` anahtarlarını ezer. TP bu ortamları
Home etkin config'inin `environments` alanından okur (`home_config.durum.ortamlar`).

- **Seçim:** koşu başlatan uç `ortam` verirse o ortam; vermezse projenin **varsayılan** ortamı
  (Home'da tek varsayılan işaretlenir); projede ortam yoksa ya da varsayılan seçilmemişse ortamsız
  (bugünkü davranış: proje ayarları). Gece koşusu daima varsayılan ortamda (ya da ortamsız) koşar.
- **Bağlam:** `ortam_icinde(o)` içinde `proje.ayar.ayar(ad)` önce ortam düzeyi etkin config'e
  (`GET /v1/config/effective?project=&environment=`) bakar; ortamın A1 ile kaldırdığı adlar (hedefi
  ortamdan gelip sırrı gelmeyen) `None` döner. Ortam config'i çözülemezse `OrtamAyariYok` (409
  `proje_ayari_eksik`): koşu sessizce proje değerlerine (başka ortamın adresine) düşmez.
- **Canlı koruması:** `tur == "prod"` (Home'da "Canlı") ortamda veriyi değiştiren işlemler
  (kırarak doğrulama, demo kırma/sıfırlama, sepet sıfırlama, uygulamanın test verisi uçları)
  `canli_engelle` ile 409 `CanliOrtamEngeli` verir. Koşu (okuma) serbesttir.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

CANLI_TUR = "prod"
TURLER = ("dev", "test", "staging", "prod")
ORTAMSIZ = "-"  # liste süzgecinde "ortamsız koşular"


@dataclass(frozen=True, slots=True)
class Ortam:
    pid: str
    eid: str
    ad: str
    tur: str
    varsayilan: bool = False

    @property
    def canli(self) -> bool:
        return self.tur == CANLI_TUR

    def ozet(self) -> dict[str, Any]:
        """API / koşu kaydı görünümü."""
        return {"eid": self.eid, "ad": self.ad, "tur": self.tur, "canli": self.canli}


class OrtamBulunamadi(ValueError):
    """İstenen ortam projede yok."""


_ORTAM: contextvars.ContextVar[Ortam | None] = contextvars.ContextVar(
    "tp_test_ortami", default=None
)


def mevcut_ortam() -> Ortam | None:
    return _ORTAM.get()


@contextmanager
def ortam_icinde(ortam: Ortam | None) -> Iterator[Ortam | None]:
    """Ortam bağlamını kurar (`None` = ortamsız); çıkışta önceki bağlam geri gelir."""
    jeton = _ORTAM.set(ortam)
    try:
        yield ortam
    finally:
        _ORTAM.reset(jeton)


def _pid(pid: str | None) -> str:
    from tp_core.proje import ayar as _ayar

    return _ayar._pid(pid)


def _ortam(pid: str, ham: Mapping[str, Any]) -> Ortam:
    tur = str(ham.get("type") or "test")
    return Ortam(
        pid=pid,
        eid=str(ham["eid"]),
        ad=str(ham.get("name") or ham["eid"]),
        tur=tur if tur in TURLER else "test",
        varsayilan=ham.get("is_default") is True,
    )


def ortamlar(pid: str | None = None) -> list[Ortam]:
    """Projenin ortamları (ada göre). Home config'i yoksa boş liste."""
    from tp_core.home_config import durum

    p = _pid(pid)
    out = [_ortam(p, e) for e in durum.ortamlar(p)]
    return sorted(out, key=lambda o: (o.ad.casefold(), o.eid))


def ortam_bul(eid: str, pid: str | None = None) -> Ortam:
    for o in ortamlar(pid):
        if o.eid == eid:
            return o
    raise OrtamBulunamadi("Ortam bulunamadı (projede yok ya da Home'da silinmiş)")


def varsayilan_ortam(pid: str | None = None) -> Ortam | None:
    return next((o for o in ortamlar(pid) if o.varsayilan), None)


def sec(eid: str | None, pid: str | None = None) -> Ortam | None:
    """Koşunun ortamı: `eid` verilirse o (yoksa `OrtamBulunamadi`), değilse varsayılan ortam."""
    if eid:
        return ortam_bul(eid, pid)
    return varsayilan_ortam(pid)


def islem_ortami(pid: str | None = None) -> Ortam | None:
    """Ortam seçilmeden yapılan işlemin (kırarak doğrulama, demo, kod üretimi) ortamı: bağlamdaki
    ortam, yoksa projenin varsayılan ortamı."""
    o = mevcut_ortam()
    if o is not None:
        return o
    try:
        return varsayilan_ortam(pid)
    except Exception:  # bağlamsız/Home'suz çağrı: ortamsız
        return None


def gorunum(o: Ortam) -> tuple[dict[str, str], frozenset[str]]:
    """Ortamın legacy env görünümü; çözülemezse `OrtamAyariYok`."""
    from tp_core.home_config import durum

    g = durum.ortam_gorunumu(o.pid, o.eid)
    if g is None:
        from tp_core.api.errors import OrtamAyariYok

        raise OrtamAyariYok(
            f"'{o.ad}' ortamının ayarları Home'dan alınamadı; ortamı ve Home bağlantısını "
            "kontrol edin"
        )
    return g


def canli_engelle(islem: str, ortam: Ortam | None = None, *, pid: str | None = None) -> None:
    """`ortam` (verilmezse `islem_ortami`) Canlı ise 409 `CanliOrtamEngeli`."""
    o = ortam if ortam is not None else islem_ortami(pid)
    if o is not None and o.canli:
        from tp_core.api.errors import CanliOrtamEngeli

        raise CanliOrtamEngeli(islem, o.ozet())
