"""Asistan uçlarının istek şemaları ve ekran bağlamı doğrulaması (AI-ASISTAN-PLANI §5.5, §9).

- Soru ≤ 2000 karakter; bağlam (istemcinin gönderdiği JSON) ≤ 2 KB. Aşım → 422 `gecersiz_istek`.
- Bağlam kapalı şemadır: bilinmeyen alan reddedilir. İstemcinin `rol` alanı (rol oturumdan gelir)
  ve `oneri` alanı (sunucu `oneri_kural_id`'den yeniden üretir) sessizce atılır.
- Rota `rules/assistant/rotalar.json` kalıbına indirgenir (`/gereksinimler/0f3c…/caseler` →
  `/gereksinimler/:id/caseler`); eşleşmeyen rota bağlamdan düşer, ekran adı kural dosyasından gelir.
- Sır taraması (`sir_bul`) burada değil, uçta yapılır: 422 `sir_icerik` gövdesinde değer yoktur.
"""

from __future__ import annotations

import json
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SORU_AZAMI = 2000
BAGLAM_AZAMI_BAYT = 2048
BASLIK_AZAMI = 200
ONERI_SORUSU = "Bu ekranda başka ne yapabilirim?"
KURAL_ID_DESENI = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

# İstemciden gelse de güvenilmeyen, sessizce atılan üst düzey bağlam alanları.
YOK_SAYILAN_ALANLAR = ("rol", "oneri")


class _Kapali(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BaglamVarlik(_Kapali):
    tur: str | None = Field(None, max_length=40)
    id: str | None = Field(None, max_length=64)
    anahtar: str | None = Field(None, max_length=40)


class BaglamSonHata(_Kapali):
    uc: str | None = Field(None, max_length=200)
    status: int | None = Field(None, ge=0, le=999)
    kod: str | None = Field(None, max_length=60)
    detail: str | None = Field(None, max_length=600)
    gorunen_metin: str | None = Field(None, max_length=600)
    yas_s: int | None = Field(None, ge=0)


class BaglamSeciliEleman(_Kapali):
    ad: str | None = Field(None, max_length=200)
    # Öğenin erişilebilirlik rolü (button, link …); kullanıcı rolü değildir.
    rol: str | None = Field(None, max_length=40)
    devre_disi: bool | None = None
    ipucu: str | None = Field(None, max_length=300)
    kart_basligi: str | None = Field(None, max_length=200)
    test_id: str | None = Field(None, max_length=100)


class Baglam(_Kapali):
    rota_kalibi: str | None = Field(None, max_length=300)
    # Bazı istemciler gerçek yolu gönderir; sunucu kalıba indirger ve `rota_kalibi`'ne yazar.
    rota: str | None = Field(None, max_length=300)
    ekran: str | None = Field(None, max_length=100)
    varlik: BaglamVarlik | None = None
    son_hata: BaglamSonHata | None = None
    secili_eleman: BaglamSeciliEleman | None = None


def _bayt(deger: Any) -> int:
    return len(json.dumps(deger, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


# ------------------------------------------------------------------ rota indirgeme


def _rotalar_dosyasi(rules_dir: Path | None = None) -> Path:
    from tp_core.gateway.config import find_rules_dir

    return find_rules_dir(rules_dir) / "assistant" / "rotalar.json"


@lru_cache(maxsize=4)
def _kaliplar(yol: str) -> tuple[tuple[str, str | None, re.Pattern[str]], ...]:
    try:
        veri = json.loads(Path(yol).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    out = []
    for r in veri.get("rotalar", []):
        kalip = r.get("kalip")
        if not isinstance(kalip, str) or not kalip.startswith("/"):
            continue
        desen = (
            "^" + re.sub(r":[A-Za-z_]\w*", "[^/]+", re.escape(kalip).replace(r"\:", ":")) + "/?$"
        )
        out.append((kalip, r.get("ekran"), re.compile(desen)))
    return tuple(out)


def rota_indirge(
    rota: str | None, *, rules_dir: Path | None = None
) -> tuple[str, str | None] | None:
    """Rota veya kalıp → (`rotalar.json` kalıbı, ekran adı); eşleşme yoksa None. `rules_dir`
    verilmezse `find_rules_dir()`."""
    if not rota:
        return None
    yol = rota.split("?", 1)[0].split("#", 1)[0]
    kaliplar = _kaliplar(str(_rotalar_dosyasi(rules_dir)))
    for kalip, ekran, _ in kaliplar:
        if yol == kalip:
            return kalip, ekran
    for kalip, ekran, desen in kaliplar:
        if desen.match(yol):
            return kalip, ekran
    return None


@lru_cache(maxsize=4)
def _roller(yol: str) -> dict[str, frozenset[str] | None]:
    try:
        veri = json.loads(Path(yol).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, frozenset[str] | None] = {}
    for r in veri.get("rotalar", []):
        kalip, roller = r.get("kalip"), r.get("roller")
        if isinstance(kalip, str):
            out[kalip] = frozenset(map(str, roller)) if isinstance(roller, list) else None
    return out


def rota_rolleri(rota: str | None, *, rules_dir: Path | None = None) -> frozenset[str] | None:
    """Rotanın ekranını açabilen roller (`rotalar.json` `roller`); None → tüm roller/kalıp yok.
    `rules_dir` verilmezse `find_rules_dir()` (kalıp eşleşmesi de aynı dizinden)."""
    eslesme = rota_indirge(rota, rules_dir=rules_dir)
    if eslesme is None:
        return None
    return _roller(str(_rotalar_dosyasi(rules_dir))).get(eslesme[0])


def baglam_dogrula(ham: Any) -> dict[str, Any] | None:
    """İstemci bağlamını doğrular ve normalize eder (sunucuda saklanan biçim).

    `ValueError` → 422 (Pydantic doğrulama hatası olarak döner).
    """
    if ham is None:
        return None
    if not isinstance(ham, dict):
        raise ValueError("baglam bir nesne olmalı")
    if _bayt(ham) > BAGLAM_AZAMI_BAYT:
        raise ValueError(f"baglam en çok {BAGLAM_AZAMI_BAYT} bayt olabilir")
    temiz = {k: v for k, v in ham.items() if k not in YOK_SAYILAN_ALANLAR}
    b = Baglam.model_validate(temiz)
    out = b.model_dump(exclude_none=True, exclude={"rota"})
    eslesme = rota_indirge(b.rota_kalibi or b.rota)
    out.pop("rota_kalibi", None)
    if eslesme is not None:
        out["rota_kalibi"], ekran = eslesme
        if ekran:
            out["ekran"] = ekran
    for alt in ("varlik", "son_hata", "secili_eleman"):
        if alt in out and not out[alt]:
            del out[alt]
    return out or None


# ------------------------------------------------------------------ istek gövdeleri


class SohbetOlustur(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    baslik: str | None = Field(None, max_length=BASLIK_AZAMI)


class SoruGonder(BaseModel):
    """`{soru, baglam, kip, oneri_kural_id}` veya `{ust_mesaj_id}` ("Daha ayrıntılı incele")."""

    model_config = ConfigDict(extra="ignore")

    soru: str | None = Field(None, max_length=SORU_AZAMI)
    baglam: dict[str, Any] | None = None
    kip: Literal["soru", "oneri"] = "soru"
    oneri_kural_id: str | None = Field(None, max_length=80, pattern=KURAL_ID_DESENI)
    ust_mesaj_id: uuid.UUID | None = None

    @field_validator("baglam", mode="before")
    @classmethod
    def _baglam(cls, v: Any) -> dict[str, Any] | None:
        return baglam_dogrula(v)

    @field_validator("soru")
    @classmethod
    def _soru(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class MesajGeriBildirim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deger: Literal[-1, 1]
