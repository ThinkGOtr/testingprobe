"""Story başına manuel baz değerin `make reset`'ten sağ çıkan kaynağı: `rules/baz-degerler.yaml`.

`requirement_baz_deger` gereksinim satırına bağlıdır; `make reset` Postgres volume'ünü sildiğinden
portalda girilmiş ölçümler de gider ve gereksinim satırları ancak Demo-A adım 1'deki Jira
eşitlemesinde (yeni UUID'lerle) geri gelir. Bu modül F0 ölçümlerini **story anahtarıyla** (jira_key)
depoda, gözden geçirilmiş bir dosyada tutar ve eşitlemede uygular:

```yaml
degerler:
  - story: TPD-1
    deger_s: 2700            # saniye, katı tam sayı (0 < x ≤ 144000)
    giren: İsmail            # ölçümü yapan adlı kişi
    not: "F0 kronometre ölçümü, 2026-10-20"   # kaynak notu (≥ 3 karakter)
```

Değer uydurulmaz: dosyada olmayan story "ölçülmedi" kalır. Geçersiz girdi uygulanmaz, `hatalar`'da
Türkçe gerekçesiyle raporlanır (eşitleme yine de sürer). Uygulama kuralları:

- story'nin hiç girişi yoksa dosya değeri yazılır (`giren` = dosyadaki kişi, `giren_rol='dosya'`);
- son giriş dosyadansa ve dosya değeri/notu değiştiyse yeni satır yazılır (geçmiş append-only);
- son giriş portalda bir insanın girişiyse (set ya da clear) dosya onu **ezmez** (`portal_girisi`).

Her uygulama hash zincirli `requirement.baseline_set` denetimi yazar: aktör `seed`, özet `kaynak:
'dosya'`, dosya yolu ve tetikleyen kullanıcı.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.features.requirements import baseline
from tp_core.models import Requirement

DOSYA_ADI = "baz-degerler.yaml"
DOSYA_ROLU = "dosya"
SEED_AKTORU = "seed"
GIREN_UST_SINIR = 100
_STORY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")
_ALANLAR = frozenset({"story", "deger_s", "giren", "not"})


@dataclass(frozen=True)
class Girdi:
    story: str
    deger_s: int
    giren: str
    not_metni: str


@dataclass
class Okuma:
    yol: str
    var: bool = False
    girdiler: dict[str, Girdi] = field(default_factory=dict)
    hatalar: list[str] = field(default_factory=list)

    def ozet(self) -> dict[str, Any]:
        return {
            "yol": self.yol,
            "var": self.var,
            "girdi": len(self.girdiler),
            "hatalar": list(self.hatalar),
        }


def dosya_yolu(rules_dir: Path | None = None) -> Path:
    from tp_core.gateway.config import find_rules_dir

    return Path(rules_dir if rules_dir is not None else find_rules_dir()) / DOSYA_ADI


def _girdi(ham: Any) -> Girdi:
    if not isinstance(ham, dict):
        raise baseline.BaselineError("girdi bir eşleme olmalı (story, deger_s, giren, not)")
    fazla = sorted(set(map(str, ham)) - _ALANLAR)
    if fazla:
        raise baseline.BaselineError(f"bilinmeyen alan: {', '.join(fazla)}")
    story = str(ham.get("story") or "").strip()
    if not _STORY_RE.match(story):
        raise baseline.BaselineError(f"geçersiz story anahtarı {story!r} (ör. TPD-1)")
    deger = baseline.validate_value(ham.get("deger_s"))
    giren = " ".join(str(ham.get("giren") or "").split())
    if not giren:
        raise baseline.BaselineError("'giren' zorunlu: ölçümü yapan adlı kişi")
    if len(giren) > GIREN_UST_SINIR:
        raise baseline.BaselineError(f"'giren' en çok {GIREN_UST_SINIR} karakter olabilir")
    notu = baseline._not(str(ham.get("not") or ""), zorunlu=True) or ""
    return Girdi(story, deger, giren, notu)


def oku(yol: Path | None = None) -> Okuma:
    """Dosyayı okur ve doğrular. Dosya yoksa boş (ölçüm yok); hatalı girdi atlanır, raporlanır."""
    yol = yol if yol is not None else dosya_yolu()
    okuma = Okuma(yol=str(yol))
    if not yol.is_file():
        return okuma
    okuma.var = True
    try:
        veri = yaml.safe_load(yol.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        okuma.hatalar.append(f"{DOSYA_ADI} okunamadı: {type(exc).__name__}")
        return okuma
    if veri is None:
        return okuma
    if not isinstance(veri, dict) or set(map(str, veri)) - {"degerler"}:
        okuma.hatalar.append(f"{DOSYA_ADI}: kök yalnızca 'degerler' listesini içermeli")
        return okuma
    liste = veri.get("degerler") or []
    if not isinstance(liste, list):
        okuma.hatalar.append(f"{DOSYA_ADI}: 'degerler' bir liste olmalı")
        return okuma
    gorulen: dict[str, int] = {}
    for i, ham in enumerate(liste, start=1):
        try:
            g = _girdi(ham)
        except baseline.BaselineError as exc:
            okuma.hatalar.append(f"{DOSYA_ADI} girdi {i}: {exc}; uygulanmadı")
            continue
        if g.story in gorulen:
            okuma.hatalar.append(
                f"{DOSYA_ADI} girdi {i}: {g.story} {gorulen[g.story]}. girdide de var; "
                "iki değer de uygulanmadı"
            )
            okuma.girdiler.pop(g.story, None)
            continue
        gorulen[g.story] = i
        okuma.girdiler[g.story] = g
    return okuma


def uygula(session: Session, req: Requirement, okuma: Okuma, tetikleyen: str) -> str | None:
    """Tek gereksinime dosya değerini uygular. Dönüş: uygulandi | ayni | portal_girisi | None."""
    if not req.jira_key:
        return None
    g = okuma.girdiler.get(req.jira_key)
    if g is None:
        return None
    son = baseline.current_rows(session, [req.id]).get(req.id)
    if son is not None and son.giren_rol != DOSYA_ROLU:
        return "portal_girisi"
    giren = baseline.Giren(
        g.giren,
        DOSYA_ROLU,
        aktor=SEED_AKTORU,
        ek={"kaynak": "dosya", "dosya": f"rules/{DOSYA_ADI}", "tetikleyen": tetikleyen},
    )
    _, degisti = baseline._yaz(session, req, giren, "set", g.deger_s, g.not_metni)
    return "uygulandi" if degisti else "ayni"


def uygula_hepsi(
    session: Session,
    tetikleyen: str,
    reqs: Iterable[Requirement] | None = None,
    okuma: Okuma | None = None,
) -> dict[str, Any]:
    """Dosyayı okuyup verilen (yoksa tüm Jira) gereksinimlere uygular; özet döner."""
    okuma = okuma if okuma is not None else oku()
    if reqs is None:
        reqs = (
            session.scalars(
                select(Requirement)
                .where(Requirement.jira_key.in_(list(okuma.girdiler)))
                .order_by(Requirement.jira_key)
                .with_for_update()
            ).all()
            if okuma.girdiler
            else []
        )
    sonuc: dict[str, str] = {}
    for req in reqs:
        durum = uygula(session, req, okuma, tetikleyen)
        if durum is not None and req.jira_key:
            sonuc[req.jira_key] = durum
    return {**okuma.ozet(), "sonuc": sonuc}


def durum(session: Session, okuma: Okuma | None = None) -> dict[str, Any]:
    """Dosya girdileri + her story'nin DB'deki etkin baz değeri (demo öncesi denetim için)."""
    okuma = okuma if okuma is not None else oku()
    reqs = (
        {
            r.jira_key: r
            for r in session.scalars(
                select(Requirement).where(Requirement.jira_key.in_(list(okuma.girdiler)))
            )
        }
        if okuma.girdiler
        else {}
    )
    bazlar = baseline.baselines_for(session, [r.id for r in reqs.values()])
    girdiler = []
    for key, g in sorted(okuma.girdiler.items()):
        req = reqs.get(key)
        etkin = bazlar.get(req.id) if req is not None else None
        girdiler.append(
            {
                "story": key,
                "deger_s": g.deger_s,
                "giren": g.giren,
                "not": g.not_metni,
                "requirement_id": str(req.id) if req is not None else None,
                # Gereksinim henüz eşitlenmediyse null: değer Jira eşitlemesinde uygulanır.
                "etkin_kaynak": etkin["kaynak"] if etkin else None,
                "etkin_etiket": etkin["etiket"] if etkin else None,
                "etkin_deger_s": etkin["deger_s"] if etkin else None,
                "etkin_giren_rol": etkin["giren_rol"] if etkin else None,
            }
        )
    return {**okuma.ozet(), "girdiler": girdiler}
