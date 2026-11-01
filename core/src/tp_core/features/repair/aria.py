"""Aria snapshot (Playwright YAML) üzerinde rol + ad doğrulaması — TEKNIK-TASARIM §8.7.

"Aday, son yeşil koşudaki aria snapshot'ının `role + name` değerleriyle eşleşmeli": yanlış butona
"onarmayı" önler. Aria snapshot data-testid taşımaz; bu modül yalnızca locator'ın rol + adının son
yeşil durumda **tam olarak bir** elemana (kapsamlı locator'da her kapsayıcıda tam bir elemana)
karşılık geldiğini denetler. 0 ya da birden çok eşleşme → öneri yok (insana).

Snapshot güvenilmeyen veridir: satır satır, boyut sınırıyla okunur; hiçbir şey yorumlanmaz.
Biçim (Playwright `ariaSnapshot()` / `error-context.md`):

    - main:
      - article "Kola 330 ml":
        - button "Sepete ekle" [ref=e4]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_BYTES = 2_000_000
MAX_LINES = 20_000
_LINE_RE = re.compile(
    r"""^(?P<indent>\s*)-\s+(?P<role>[a-zA-Z][\w-]*)"""
    r"""(?:\s+(?P<name>"(?:[^"\\]|\\.)*"))?(?P<rest>.*)$"""
)
_WS = re.compile(r"\s+")
_PAGE_SNAPSHOT_RE = re.compile(r"^# Page snapshot\s*\n+```(?:yaml)?\n(.*?)\n```", re.S | re.M)
_YAML_BLOCK_RE = re.compile(r"```(?:yaml)?\n(.*?)\n```", re.S)


@dataclass
class Dugum:
    rol: str
    ad: str | None
    girinti: int
    ebeveyn: Dugum | None = None
    cocuklar: list[Dugum] = field(default_factory=list)

    def etiket(self) -> str:
        return f'{self.rol} "{self.ad}"' if self.ad is not None else self.rol


def _norm(metin: str) -> str:
    return _WS.sub(" ", metin).strip()


def _ad(ham: str | None) -> str | None:
    if ham is None:
        return None
    return _norm(re.sub(r"\\(.)", r"\1", ham[1:-1]))


def yaml_metni(metin: str) -> str:
    """`error-context.md` ya da düz YAML → snapshot YAML'ı."""
    metin = (metin or "")[:MAX_BYTES]
    m = _PAGE_SNAPSHOT_RE.search(metin)
    if m:
        return m.group(1)
    if "```" in metin:
        m = _YAML_BLOCK_RE.search(metin)
        if m:
            return m.group(1)
    return metin


def ayristir(metin: str) -> list[Dugum]:
    """YAML satırlarını girintiye göre ebeveynli düğümlere çevirir."""
    dugumler: list[Dugum] = []
    yigin: list[Dugum] = []
    for satir in yaml_metni(metin).splitlines()[:MAX_LINES]:
        m = _LINE_RE.match(satir.rstrip())
        if not m:
            continue
        girinti = len(m.group("indent").replace("\t", "  "))
        while yigin and yigin[-1].girinti >= girinti:
            yigin.pop()
        d = Dugum(m.group("role"), _ad(m.group("name")), girinti, yigin[-1] if yigin else None)
        if d.ebeveyn is not None:
            d.ebeveyn.cocuklar.append(d)
        dugumler.append(d)
        yigin.append(d)
    return dugumler


@dataclass
class AriaSonucu:
    gecerli: bool
    eslesme: int
    neden: str
    kapsayici_sayisi: int | None = None
    ornekler: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gecerli": self.gecerli,
            "eslesme": self.eslesme,
            "neden": self.neden,
            "kapsayici_sayisi": self.kapsayici_sayisi,
            "ornekler": self.ornekler[:5],
        }


def _yol(d: Dugum) -> str:
    parca: list[str] = []
    cur: Dugum | None = d
    while cur is not None and len(parca) < 6:
        parca.append(cur.etiket())
        cur = cur.ebeveyn
    return " › ".join(reversed(parca))[:300]


def dogrula(
    metin: str, rol: str, ad: str, *, kapsayici_rol: str | None = None, kapsamli: bool = False
) -> AriaSonucu:
    """Rol + ad (birebir, boşluk sadeleştirilmiş) son yeşil snapshot'ta tek mi?

    - `kapsamli=False`: tüm sayfada tam olarak 1 eşleşme.
    - `kapsamli=True` (locator `within` taşıyor): her eşleşme `kapsayici_rol` rolündeki bir
      atanın altında olmalı ve her kapsayıcıda tam olarak 1 eşleşme bulunmalı (en az bir kapsayıcı).
    """
    if not rol or not ad:
        return AriaSonucu(False, 0, "Locator'ın rolü ya da adı yok; aria ile doğrulanamaz")
    hedef = _norm(ad)
    eslesen = [d for d in ayristir(metin) if d.rol == rol and d.ad == hedef]
    ornek = [_yol(d) for d in eslesen]
    etiket = f'{rol} "{hedef}"'
    if not eslesen:
        return AriaSonucu(False, 0, f"Son yeşil snapshot'ta {etiket} yok", ornekler=ornek)
    if not kapsamli:
        if len(eslesen) > 1:
            return AriaSonucu(
                False,
                len(eslesen),
                f"Son yeşil snapshot'ta {etiket} {len(eslesen)} kez geçiyor (kapsam yok)",
                ornekler=ornek,
            )
        return AriaSonucu(True, 1, f"Son yeşil snapshot'ta {etiket} tek eleman", ornekler=ornek)
    if not kapsayici_rol:
        return AriaSonucu(
            False, len(eslesen), "Kapsayıcının rolü bilinmiyor; kapsamlı doğrulama yapılamadı"
        )
    gruplar: dict[int, int] = {}
    for d in eslesen:
        ata = d.ebeveyn
        while ata is not None and ata.rol != kapsayici_rol:
            ata = ata.ebeveyn
        if ata is None:
            return AriaSonucu(
                False,
                len(eslesen),
                f"{etiket} bir '{kapsayici_rol}' kapsayıcısının dışında da geçiyor",
                ornekler=ornek,
            )
        gruplar[id(ata)] = gruplar.get(id(ata), 0) + 1
    fazla = [n for n in gruplar.values() if n != 1]
    if fazla:
        return AriaSonucu(
            False,
            len(eslesen),
            f"Bir '{kapsayici_rol}' kapsayıcısında {etiket} {max(fazla)} kez geçiyor",
            kapsayici_sayisi=len(gruplar),
            ornekler=ornek,
        )
    return AriaSonucu(
        True,
        len(eslesen),
        f"Son yeşil snapshot'ta her '{kapsayici_rol}' kapsayıcısında {etiket} tek eleman "
        f"({len(gruplar)} kapsayıcı)",
        kapsayici_sayisi=len(gruplar),
        ornekler=ornek,
    )
