"""Portal kullanıcılarının görünen adı (ör. "Cengizhan Gunaydin · Analist").

Yalnızca gösterim içindir: yetki ve kapı kararları her zaman `rol` ile verilir, ada asla
bakılmaz. Adlar `TP_GORUNEN_ADLAR` (`kullanici_adi=Ad Soyad`, virgülle) ile değiştirilir; yoksa
`seed.GORUNEN_ADLAR` demo varsayılanları kullanılır. Boş ad → yalnızca rol etiketi
("Sistem Yöneticisi"); eşlemede olmayan kullanıcı → `kullanici_adi · Rol`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from tp_core.auth.yetki import ESKI_ROLLER, ROL_ETIKETLERI
from tp_core.config import get_settings
from tp_core.seed import GORUNEN_ADLAR

# Rol etiketleri tek kaynaktan (specs/012-rol-yetki §3). Kaldırılan `presenter` eski kayıtlarda
# yerine geçen rolün etiketiyle gösterilir.
ROL_ETIKETI: dict[str, str] = {
    **{eski: ROL_ETIKETLERI[yeni] for eski, yeni in ESKI_ROLLER.items()},
    **ROL_ETIKETLERI,
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


# "Last name unknown" yer tutucusu (ör. AI Probe hesabında soyadı boş: "gokhansipahi LNU").
_YER_TUTUCU = re.compile(r"\b(lnu|fnu)\b", re.IGNORECASE)


def _ad_anahtari(ad: str | None) -> str:
    """Ad karşılaştırma anahtarı: küçük harf, yer tutucu ve işaretsiz; yalnız harf/rakam.
    "Gokhan Sipahi (AI Probe)" ve "gokhansipahi LNU" → "gokhansipahi"."""
    if not ad:
        return ""
    a = ad.replace(SSO_ISARETI, "")
    a = _YER_TUTUCU.sub("", a).casefold()
    return re.sub(r"[\W_]+", "", a)


def _ad_puani(ad: str | None, yapilandirilmis: bool) -> tuple[int, int, int, int]:
    """Görünen ad önceliği: yapılandırılmış ad > yer tutucusuz > ad soyad (boşluklu) > uzun."""
    if not ad:
        return (0, 0, 0, 0)
    return (int(yapilandirilmis), int(not _YER_TUTUCU.search(ad)), int(" " in ad.strip()), len(ad))


def ayni_kisi_adlari(
    kullanicilar: Iterable[Sequence[object]],
    yapilandirilmis: Mapping[str, str] | None = None,
) -> dict[str, tuple[str, str, str]]:
    """Aynı kişinin hesaplarını birleştirir (TP UX YD-05).

    Girdi: (kullanici_adi, rol, ad_soyad, ad_kaynak, external_uid|None) satırları. Aynı kişi:
    aynı AI Probe kimliği (`kimlik_bagi.external_uid`) ya da aynı ad anahtarı (`_ad_anahtari`,
    en az 4 karakter). Çıktı: kullanici_adi → (kişi anahtarı, kişinin tercih edilen görünen adı
    — AI Probe kaynaklıysa "(AI Probe)" işaretli —, o adı taşıyan hesabın kullanıcı adı).
    Yalnız gösterim; yetki rolle verilir.
    """
    names = configured_names() if yapilandirilmis is None else yapilandirilmis
    satirlar = [tuple(k) + (None,) * (5 - len(k)) for k in kullanicilar]
    ebeveyn: dict[str, str] = {}

    def bul(x: str) -> str:
        while ebeveyn.setdefault(x, x) != x:
            ebeveyn[x] = ebeveyn[ebeveyn[x]]
            x = ebeveyn[x]
        return x

    def birlestir(a: str, b: str) -> None:
        ra, rb = bul(a), bul(b)
        if ra != rb:
            ebeveyn[max(ra, rb)] = min(ra, rb)

    bilgi: dict[str, tuple[str | None, str | None, bool]] = {}
    for k, _rol, ad_soyad, ad_kaynak, uid in satirlar:
        kad = str(k)
        anahtar = kad.strip().lower()
        yap = names.get(anahtar)
        ad = yap if yap else (str(ad_soyad) if ad_soyad else None)
        gorunen = yap if yap else kaynakli_ad(ad, str(ad_kaynak) if ad_kaynak else None)
        bilgi[kad] = (ad, gorunen, bool(yap))
        bul(f"h:{kad}")
        if uid:
            birlestir(f"h:{kad}", f"u:{uid}")
        anahtar_ad = _ad_anahtari(ad)
        if len(anahtar_ad) >= 4:
            birlestir(f"h:{kad}", f"n:{anahtar_ad}")
    en_iyi: dict[str, str] = {}
    for kad, (ad, _g, yap) in bilgi.items():
        kok = bul(f"h:{kad}")
        mevcut = en_iyi.get(kok)
        if mevcut is None or _ad_puani(ad, yap) > _ad_puani(bilgi[mevcut][0], bilgi[mevcut][2]):
            en_iyi[kok] = kad
    out: dict[str, tuple[str, str, str]] = {}
    for kad in bilgi:
        kok = bul(f"h:{kad}")
        temsilci = en_iyi[kok]
        out[kad] = (kok, bilgi[temsilci][1] or temsilci, temsilci)
    return out
