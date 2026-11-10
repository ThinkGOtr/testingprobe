"""Portal kullanıcılarının görünen adı (ör. "Cengizhan Gunaydin · Analist").

Yalnızca gösterim içindir: yetki ve kapı kararları her zaman `rol` ile verilir, ada asla
bakılmaz. Adlar `TP_GORUNEN_ADLAR` (`kullanici_adi=Ad Soyad`, virgülle) ile değiştirilir; yoksa
`seed.GORUNEN_ADLAR` demo varsayılanları kullanılır. Boş ad → yalnızca rol etiketi ("Sunucu");
eşlemede olmayan kullanıcı → `kullanici_adi · Rol`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from tp_core.config import get_settings
from tp_core.seed import GORUNEN_ADLAR

ROL_ETIKETI: dict[str, str] = {
    "analyst": "Analist",
    "engineer": "Mühendis",
    "presenter": "Sunucu",
    "po": "PO",
    "tester": "Testçi",
}


def parse_names(raw: str) -> dict[str, str]:
    """`analist=Ad Soyad,sunucu=` → {"analist": "Ad Soyad", "sunucu": ""} (bozuk parça atlanır)."""
    out: dict[str, str] = {}
    for parca in (raw or "").split(","):
        ad, sep, kisi = parca.partition("=")
        ad = ad.strip().lower()
        if sep and ad:
            out[ad] = " ".join(kisi.split())[:80]
    return out


def configured_names(raw: str | None = None) -> dict[str, str]:
    """Demo varsayılanları + `TP_GORUNEN_ADLAR` geçersiz kılmaları."""
    if raw is None:
        raw = get_settings().gorunen_adlar
    return {**GORUNEN_ADLAR, **parse_names(raw)}


def display_name(kullanici_adi: str, rol: str, names: Mapping[str, str] | None = None) -> str:
    names = configured_names() if names is None else names
    etiket = ROL_ETIKETI.get(rol, rol)
    ad = names.get(kullanici_adi.strip().lower(), kullanici_adi)
    return f"{ad} · {etiket}" if ad else etiket


SSO_ISARETI = "(AI Probe)"


def kaynakli_ad(ad: str | None, kaynak: str | None) -> str | None:
    """AI Probe devrinden gelen (TP'nin doğrulamadığı) adı işaretler: "Ayşe (AI Probe)"."""
    if ad and kaynak == "aiprobe":
        return f"{ad} {SSO_ISARETI}"
    return ad


def person_name(kullanici_adi: str, names: Mapping[str, str] | None = None) -> str | None:
    """Rol etiketi olmadan kişi adı (yoksa None)."""
    names = configured_names() if names is None else names
    return names.get(kullanici_adi.strip().lower()) or None


def display_names(users: Iterable[tuple[str, str]]) -> dict[str, str]:
    """(kullanici_adi, rol) çiftleri → {kullanici_adi: görünen ad} (portalın kişi eşlemesi)."""
    names = configured_names()
    return {ad: display_name(ad, rol, names) for ad, rol in users}
