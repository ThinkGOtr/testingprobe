"""Hata sözlüğü dalı (AI-ASISTAN-PLANI §10.2 adım 2; constitution XI — modelsiz, ücretsiz).

Kullanıcı ekranda gördüğü hatayı sorduğunda ("Bu hata ne demek?") ve bağlamda `son_hata` varsa
cevap `rules/assistant/hata-sozlugu.yaml`'dan verilir (`kaynak=sozluk`). Eşleşme sırası dosya
başlığında belgelidir ve kural testi (`test_rules_asistan.py`) aynı sırayı zorlar:

1. `metinler`: son hatanın normalize `detail`/`gorunen_metin`'i kaydın bir parçasını içeriyorsa
   (dosyadaki ilk kayıt; özgül kayıtlar önce yazılır);
2. `kodlar`: `son_hata.kod` kaydın kod listesindeyse (dosyadaki ilk kayıt).

Kaydın `rota`'sındaki `:id` yalnız bağlamdaki varlık o ekranın türündeyse doldurulur; değilse
bağlantı verilmez.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from tp_core.features.assistant.siniflandir import normalize

SOZLUK_DOSYASI: Final = "hata-sozlugu.yaml"
ROTA_DOSYASI: Final = "rotalar.json"
SOZLUK_REF: Final = f"rules/assistant/{SOZLUK_DOSYASI}"
_KIMLIK: Final = re.compile(r"^[A-Za-z0-9-]{1,64}$")


@dataclass(frozen=True)
class SozlukKaydi:
    id: str
    kodlar: tuple[str, ...]
    metinler: tuple[str, ...]
    baslik: str
    anlam: str
    neden: str
    cozum: str
    rota: str | None


@lru_cache(maxsize=4)
def _yukle(yol: str) -> tuple[SozlukKaydi, ...]:
    veri = yaml.safe_load(Path(yol).read_text(encoding="utf-8")) or {}
    out = []
    for k in veri.get("kayitlar") or []:
        out.append(
            SozlukKaydi(
                id=str(k["id"]),
                kodlar=tuple(str(x) for x in k.get("kodlar") or []),
                metinler=tuple(normalize(str(x)) for x in k.get("metinler") or []),
                baslik=str(k.get("baslik") or ""),
                anlam=str(k.get("anlam") or ""),
                neden=str(k.get("neden") or ""),
                cozum=str(k.get("cozum") or ""),
                rota=k.get("rota") or None,
            )
        )
    return tuple(out)


@lru_cache(maxsize=4)
def _rota_varliklari(yol: str) -> dict[str, str | None]:
    try:
        veri = json.loads(Path(yol).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        r["kalip"]: r.get("varlik")
        for r in veri.get("rotalar") or []
        if isinstance(r, dict) and isinstance(r.get("kalip"), str)
    }


def _asistan_dizini(rules_dir: Path | None) -> Path:
    from tp_core.gateway.config import find_rules_dir

    return find_rules_dir(rules_dir) / "assistant"


def rota_varliklari(rules_dir: Path | None = None) -> dict[str, str | None]:
    """`rotalar.json` kalıbı → ekrandaki `:id`'nin varlık türü (None: varlıksız ekran)."""
    return _rota_varliklari(str(_asistan_dizini(rules_dir) / ROTA_DOSYASI))


def kayitlar(rules_dir: Path | None = None) -> tuple[SozlukKaydi, ...]:
    return _yukle(str(_asistan_dizini(rules_dir) / SOZLUK_DOSYASI))


def bul(son_hata: Mapping[str, Any] | None, *, rules_dir: Path | None = None) -> SozlukKaydi | None:
    """Son hata için sözlük kaydı (önce metin, sonra kod); yoksa None."""
    if not isinstance(son_hata, Mapping):
        return None
    tum = kayitlar(rules_dir)
    norm = [
        normalize(m)
        for m in (son_hata.get("detail"), son_hata.get("gorunen_metin"))
        if isinstance(m, str) and m.strip()
    ]
    for k in tum:
        if any(p and p in m for p in k.metinler for m in norm):
            return k
    kod = son_hata.get("kod")
    if isinstance(kod, str) and kod:
        for k in tum:
            if kod in k.kodlar:
                return k
    return None


def rota_doldur(
    kalip: str | None, baglam: Mapping[str, Any] | None, *, rules_dir: Path | None = None
) -> str | None:
    """`:id`'li kalıbı bağlamdaki varlıkla doldurur; tür uymuyor ya da kimlik yoksa None."""
    if not kalip:
        return None
    if ":id" not in kalip:
        return kalip
    beklenen = _rota_varliklari(str(_asistan_dizini(rules_dir) / ROTA_DOSYASI)).get(kalip)
    varlik = baglam.get("varlik") if isinstance(baglam, Mapping) else None
    if not isinstance(varlik, Mapping) or beklenen is None:
        return None
    if varlik.get("tur") not in (beklenen, None, ""):
        return None
    kimlik = varlik.get("id")
    if not isinstance(kimlik, str) or not _KIMLIK.match(kimlik):
        return None
    try:
        uuid.UUID(kimlik)
    except ValueError:
        return None
    return kalip.replace(":id", kimlik)


def cevap(
    kayit: SozlukKaydi, baglam: Mapping[str, Any] | None, *, rules_dir: Path | None = None
) -> dict[str, Any]:
    """Saklanan cevap biçiminde (§7.3 "Saklanan cevap") sözlük cevabı."""
    from tp_core.features.assistant.sonislem import bos_cevap

    out = bos_cevap()
    out["cevap_bloklari"] = [
        {"tur": "baslik", "metin": kayit.baslik, "maddeler": []},
        {"tur": "paragraf", "metin": kayit.anlam, "maddeler": []},
        {"tur": "paragraf", "metin": f"Neden olur: {kayit.neden}", "maddeler": []},
        {"tur": "paragraf", "metin": f"Ne yapmalı: {kayit.cozum}", "maddeler": []},
    ]
    out["guven"] = "yuksek"
    out["guven_gosterimi"] = "Kaynakla doğrulandı"
    out["kaynaklar"] = [
        {
            "tur": "dokuman",
            "ref": f"{SOZLUK_REF}#{kayit.id}",
            "alinti": kayit.anlam[:300],
            "dogrulandi": True,
        }
    ]
    out["dogrulama"] = {f"{SOZLUK_REF}#{kayit.id}": {"dogrulandi": True, "sha256": None}}
    out["urune_ozgu"] = True
    rota = rota_doldur(kayit.rota, baglam, rules_dir=rules_dir)
    if rota:
        out["yonlendirmeler"] = [{"etiket": "İlgili ekran", "rota": rota}]
    return out
