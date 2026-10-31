"""Ajan adımlarının insan için özeti (portal "Ajan adımları", SSE `agent.step`, ekran görüntüsü alt
metni).

- `insan_ozeti`: araç adı + (maskeli) argümanlar + yapılandırılmış sonuçtan tek satırlık Türkçe
  açıklama ("Sepete gitti — /sepet", "Yazıldı: Adet = "7""). Araç çıktısının kendisi değildir.
- `adim_ozeti` / `ham_cikti`: araç çıktısının temizlenmiş hali ("Ham çıktı" açılır bölümü):
  güvenilmeyen-veri sarmalı, kod çitleri, Playwright MCP'nin `[Snapshot](…yml)` bağlantıları ve
  `/tmp/...` yolları atılır; gizli değerler (`gizli`) `***` olur.

Modele giden metin bunlardan etkilenmez (orada sarmal kalır); bu yalnızca kayıt/görünüm içindir.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from tp_core.features.codegen.browser import gizle, parola_alani, sayfa_adresi

_SARMAL_RE = re.compile(r"</?untrusted\b[^>]*>")
# Geçit özeti kırptığında sarmal etiketi yarım kalabilir (`… </untrusted id="87520…`): sondaki
# kapanmamış etiket parçası atılır.
_YARIM_ETIKET_RE = re.compile(r"</?[A-Za-z][^<>]*$")
_KOD_BLOK_RE = re.compile(r"```[a-z]*\n?")
_SNAPSHOT_LINK_RE = re.compile(r"\[Snapshot\]\([^)]*\)", re.I)
_MD_LINK_YOL_RE = re.compile(r"\[[^\]]*\]\((?:\.\./|/)[^)]*\)")
_TMP_YOL_RE = re.compile(r"(?<![\w])(?:\.\./)*/?(?:tmp|var/folders|private/tmp)/\S+")
MAX_OZET = 300
MAX_HAM = 4000


def ham_cikti(ham: str | None, gizli: Iterable[str] = (), sinir: int = MAX_HAM) -> str:
    """Araç çıktısının görüntülenebilir hali (tek satıra indirgenmiş, kırpılmış)."""
    metin = _KOD_BLOK_RE.sub("", _SARMAL_RE.sub("", ham or ""))
    metin = _YARIM_ETIKET_RE.sub("", metin.rstrip())
    metin = _SNAPSHOT_LINK_RE.sub("", metin)
    metin = _MD_LINK_YOL_RE.sub("", metin)
    metin = _TMP_YOL_RE.sub("", metin)
    metin = gizle(metin, set(gizli))
    return " ".join(metin.split())[:sinir]


def adim_ozeti(ham: str | None, sinir: int = MAX_OZET, gizli: Iterable[str] = ()) -> str:
    """Geriye uyumlu kısa ham özet (eski `script_adim.ozet` biçimi)."""
    return ham_cikti(ham, gizli, sinir)


def _kisa(deger: Any, limit: int = 60) -> str:
    metin = " ".join(str(deger if deger is not None else "").split())
    return metin if len(metin) <= limit else metin[: limit - 1] + "…"


def _yol(url: Any) -> str:
    return sayfa_adresi(f"URL {url}") or _kisa(url)


def insan_ozeti(
    tool: str,
    args: Mapping[str, Any],
    *,
    izinli: bool = True,
    ok: bool | None = True,
    hata: str | None = None,
    url: str | None = None,
) -> str:
    """Tek satırlık Türkçe adım açıklaması (argümanlar maskelenmiş olmalı)."""
    if not izinli:
        return f"İzinsiz araç reddedildi: {_kisa(tool, 60)} (çalıştırılmadı)"
    eleman = _kisa(args.get("element") or args.get("target") or args.get("ref") or "", 60)
    sonra = f" — {url}" if url else ""
    if tool == "browser_navigate":
        metin = f"Sayfa açıldı: {_yol(args.get('url'))}"
    elif tool == "browser_snapshot":
        metin = "Sayfa yapısı okundu" + (f" ({url})" if url else "")
    elif tool == "browser_click":
        metin = f"Tıklandı: {eleman or 'öğe'}{sonra}"
    elif tool == "browser_type":
        deger = "***" if parola_alani(args) else _kisa(args.get("text"), 40)
        metin = f'Yazıldı: {eleman or "alan"} = "{deger}"'
    elif tool == "browser_select_option":
        degerler = args.get("values") or args.get("value") or []
        if isinstance(degerler, list | tuple):
            degerler = ", ".join(str(v) for v in degerler)
        metin = f"Seçildi: {eleman or 'liste'} = {_kisa(degerler, 40)}"
    elif tool == "browser_wait_for":
        if args.get("text") or args.get("textGone"):
            metin = f'Beklendi: "{_kisa(args.get("text") or args.get("textGone"), 50)}"'
        else:
            metin = f"Beklendi: {_kisa(args.get('time'), 10)} sn"
    elif tool == "browser_generate_locator":
        metin = f"Locator üretildi: {eleman or 'öğe'}"
    else:
        metin = _kisa(tool, 60)
    if ok is False:
        metin += f" — başarısız: {_kisa(hata or 'araç hatası', 120)}"
    return metin[:MAX_OZET]
