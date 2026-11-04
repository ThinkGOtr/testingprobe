"""Kontrol Kulesi'nin asistan ölçüleri (AI-ASISTAN-PLANI §6.4 son madde, §17.7; Şerit KK).

- **Maliyet grupları:** `ai_call.amac` `assistant` ile başlayanlar (`assistant`, `assistant_deep`)
  "asistan", geri kalanı "diğer" grubunda toplanır; toplam/bugün/çağrı sayısı ve grubun amaçları.
  `ai_call` append-only'dir, asistan saklama temizliği ona dokunmaz: maliyet tüm zamanlardır.
- **Öneriler kartı:** kural başına "Neden? Sor" sayısı (`asistan_mesaj` kullanıcı sorusu,
  `baglam.oneri.kural_id`) ve "Faydalı / Gizle / Yaptım" sayıları (`asistan_oneri_geri_bildirim`
  `deger` 1 / -1 / 2). Yalnız kural başına toplam: **kişi bazlı rapor yok** (kullanıcı kimliği
  sorguya girmez, yanıtta yoktur). Gösterim sayısı tutulmaz (istemci izleme yok). Bu tablolar
  saklama süresiyle (`TP_ASISTAN_SAKLAMA_GUN`) temizlendiği için sayılar son N günü kapsar.

Kural listesi yüklü kural setinden gelir (sıfır sayılı kurallar da görünür); kural dosyasından
kaldırılmış ama kaydı kalan kimlikler `kural_setinde=false` ile ayrıca listelenir. Kural seti
yüklenemezse (bozuk dosya) yalnız kayıtlı kimlikler döner, kart yine çizilir.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Final

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from tp_core.features.assistant import temizlik
from tp_core.models import AiCall
from tp_core.models.asistan import AsistanMesaj, AsistanOneriGeriBildirim

log = logging.getLogger(__name__)

ASISTAN_ONEKI: Final = "assistant"
GERI_BILDIRIM_ALANLARI: Final = {1: "faydali", -1: "gizle", 2: "yaptim"}
SAYAC_ALANLARI: Final = ("neden_sor", "faydali", "gizle", "yaptim")
_YER_TUTUCU: Final = re.compile(r"\{[a-z_]+\}")


def asistan_amaci_mi(amac: str | None) -> bool:
    return bool(amac) and str(amac).startswith(ASISTAN_ONEKI)


def maliyet_gruplari(session: Session, gun_basi: datetime) -> dict[str, Any]:
    """`ai_call` maliyeti amaç grubuna göre: `{asistan: {...}, diger: {...}}`."""
    satirlar = session.execute(
        select(
            AiCall.amac,
            func.count(),
            func.coalesce(func.sum(AiCall.maliyet), 0),
            func.coalesce(
                func.sum(case((AiCall.olusturma >= gun_basi, AiCall.maliyet), else_=0)), 0
            ),
        ).group_by(AiCall.amac)
    ).all()
    gruplar: dict[str, dict[str, Any]] = {
        ad: {"cagri": 0, "maliyet_usd": 0.0, "maliyet_usd_bugun": 0.0, "amaclar": []}
        for ad in ("asistan", "diger")
    }
    for amac, n, toplam, bugun in satirlar:
        g = gruplar["asistan" if asistan_amaci_mi(amac) else "diger"]
        g["cagri"] += int(n)
        g["maliyet_usd"] += float(toplam)
        g["maliyet_usd_bugun"] += float(bugun)
        g["amaclar"].append(amac)
    for g in gruplar.values():
        g["maliyet_usd"] = round(g["maliyet_usd"], 6)
        g["maliyet_usd_bugun"] = round(g["maliyet_usd_bugun"], 6)
        g["amaclar"] = sorted(g["amaclar"])
    return gruplar


def _kural_listesi() -> list[tuple[str, str, str]]:
    """Yüklü kural seti: (kural_id, başlık, ekran). Yer tutucular "…" olur (varlık verisi yok)."""
    from tp_core.features.assistant import oneri

    try:
        kurallar = oneri.kural_seti().kurallar
    except Exception as exc:  # bozuk kural dosyası ölçüm kartını düşürmez
        log.warning(
            "öneri kural seti yüklenemedi (%s): yalnız kayıtlı kimlikler", type(exc).__name__
        )
        return []
    return [(k.id, _YER_TUTUCU.sub("…", k.baslik), k.ekran) for k in kurallar]


def oneri_olcumu(session: Session) -> list[dict[str, Any]]:
    """Kural başına "Neden? Sor" ve Faydalı/Gizle/Yaptım sayıları (kişi bazlı değil)."""
    kural_ifadesi = AsistanMesaj.baglam["oneri"]["kural_id"].astext
    neden = dict(
        session.execute(
            select(kural_ifadesi, func.count())
            .where(AsistanMesaj.rol == "user", kural_ifadesi.is_not(None))
            .group_by(kural_ifadesi)
        ).all()
    )
    geri: dict[str, dict[str, int]] = {}
    for kural_id, deger, n in session.execute(
        select(
            AsistanOneriGeriBildirim.kural_id, AsistanOneriGeriBildirim.deger, func.count()
        ).group_by(AsistanOneriGeriBildirim.kural_id, AsistanOneriGeriBildirim.deger)
    ):
        alan = GERI_BILDIRIM_ALANLARI.get(int(deger))
        if alan is not None:
            geri.setdefault(kural_id, {})[alan] = int(n)

    def _satir(kural_id: str, baslik: str | None, ekran: str | None, kural_setinde: bool):
        sayilar = geri.get(kural_id, {})
        return {
            "kural_id": kural_id,
            "baslik": baslik,
            "ekran": ekran,
            "kural_setinde": kural_setinde,
            "neden_sor": int(neden.get(kural_id, 0)),
            **{a: sayilar.get(a, 0) for a in ("faydali", "gizle", "yaptim")},
        }

    satirlar = [_satir(i, b, e, True) for i, b, e in _kural_listesi()]
    bilinen = {s["kural_id"] for s in satirlar}
    for kural_id in sorted((set(neden) | set(geri)) - bilinen):
        satirlar.append(_satir(kural_id, None, None, False))
    # Etkileşimi çok olan önce; eşitlikte kural dosyası sırası korunur (sorted kararlı).
    return sorted(satirlar, key=lambda s: -sum(s[a] for a in SAYAC_ALANLARI))


def asistan_olcumu(session: Session, maliyet: dict[str, Any]) -> dict[str, Any]:
    """Kontrol Kulesi `asistan` bölümü; `maliyet` = `ai_katkisi.amac_gruplari` (tek sorgu)."""
    satirlar = oneri_olcumu(session)
    return {
        "maliyet": maliyet,
        "oneriler": satirlar,
        "oneri_toplam": {a: sum(s[a] for s in satirlar) for a in SAYAC_ALANLARI},
        "saklama_gun": temizlik.saklama_gun(),
    }


KAYNAK: Final = (
    "maliyet: ai_call.maliyet, amac 'assistant*' (assistant, assistant_deep) = asistan grubu, "
    "geri kalanı diğer; tüm zamanlar (ai_call saklama temizliğine girmez), bugün: Europe/Istanbul "
    "gün başından (asistan bütçe tavanları — günlük ve kullanıcı başı — UTC gününe göre, "
    "03:00 TR'de sıfırlanır; bu dilimle birebir örtüşmez) · öneriler: kural başına 'Neden? Sor' "
    "= öneri bağlamlı kullanıcı sorusu "
    "(asistan_mesaj.baglam.oneri.kural_id), Faydalı/Gizle/Yaptım = asistan_oneri_geri_bildirim."
    "deger 1/-1/2; son TP_ASISTAN_SAKLAMA_GUN gün (saklama temizliği); gösterim sayısı tutulmaz, "
    "kişi bazlı rapor yok"
)
