"""Eylem reddinde deterministik ekran bağlantısı (AI-ASISTAN-PLANI §2 S7, §7.1, §7.3; ilke XI).

Asistan eylem yapmaz; eylem isteğinin cevabı, eylemin yapıldığı ekrana bir bağlantı taşır. Model
geçerli bir `yonlendirmeler` vermediyse son işlem (`sonislem.isle`) bağlantıyı buradan seçer —
modelsiz, `rules/assistant/eylem-rotalari.yaml` kuralıyla (seçim sırası dosya başlığında):

1. Sorudaki eylem ifadesi → kaydın `rota`'sı; `:id` ekran bağlamındaki varlıktan, olmazsa bu mesajın
   araç sonuçlarındaki tek kayıt rotasından (`probe_get` `ekran_rotasi`), olmazsa (gereksinim
   ekranında) sorudaki tek Jira anahtarının Testing Probe kaydından, olmazsa kaydın `liste`'si.
   Model yalnız bu kaydın liste ekranını verdiyse kayıt ekranı onun yerine geçer (`sonislem`).
2. Eşleşme yoksa kullanıcının bulunduğu ekran (bağlamdaki `rota_kalibi` + varlık).

Dönen rota henüz bir öneridir: `sonislem` aynı `rotalar.json` doğrulamasından ve rol süzgecinden
geçirir (rolün açamadığı ekran bağlantı olmaz).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from tp_core.features.assistant import siniflandir, sozluk

EYLEM_DOSYASI: Final = "eylem-rotalari.yaml"
# Araç sonucundaki kayıt rotası: `ekran_rotasi: /gereksinimler/<uuid>` (probe_get) ya da liste
# satırının son sütunu (`- <id> | durum | TPD-3 · başlık | /gereksinimler/<uuid>`).
_ROTA_PARCASI: Final = re.compile(r"(?<![\w/.:])(/[a-z][a-z0-9-]*(?:/[A-Za-z0-9-]+)+)")
_EKRAN_ROTASI: Final = "ekran_rotasi:"
# Rota çıkarımına girdi olan araçlar (Probe kayıtları; kullanıcının rolüyle süzülmüş).
_KAYIT_ARACLARI: Final = frozenset({"probe_get", "probe_list", "probe_my_queue"})
# Eylemin yapılmadığı bağlam ekranları: bağlantı değeri yok.
_EKRANSIZ: Final = frozenset({"", "/", "/giris"})


@dataclass(frozen=True)
class EylemRotasi:
    id: str
    ifadeler: tuple[tuple[str, ...], ...]
    rota: str
    liste: str | None


@lru_cache(maxsize=4)
def _yukle(yol: str) -> tuple[EylemRotasi, ...]:
    try:
        veri = yaml.safe_load(Path(yol).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ()
    out = []
    for k in veri.get("eylemler") or []:
        out.append(
            EylemRotasi(
                id=str(k["id"]),
                ifadeler=tuple(
                    tuple(siniflandir.normalize(str(i)).split()) for i in k.get("ifadeler") or []
                ),
                rota=str(k["rota"]),
                liste=k.get("liste") or None,
            )
        )
    return tuple(out)


def kayitlar(rules_dir: Path | None = None) -> tuple[EylemRotasi, ...]:
    from tp_core.gateway.config import find_rules_dir

    return _yukle(str(find_rules_dir(rules_dir) / "assistant" / EYLEM_DOSYASI))


def _ifade_eslesir(metin: str, kokler: tuple[str, ...]) -> bool:
    return bool(kokler) and all(re.search(r"(?<!\w)" + re.escape(k), metin) for k in kokler)


def eslesen(soru: str | None, *, rules_dir: Path | None = None) -> EylemRotasi | None:
    """Sorudaki eylem ifadesine uyan ilk kayıt (dosya sırası)."""
    metin = siniflandir.normalize(soru)
    if not metin:
        return None
    for k in kayitlar(rules_dir):
        if any(_ifade_eslesir(metin, i) for i in k.ifadeler):
            return k
    return None


def _kanit_rotalari(kanitlar: Iterable[Any], anahtarlar: list[str]) -> list[str]:
    """Araç sonuçlarındaki somut kayıt rotaları (sırayla, tekil).

    Soruda Jira anahtarı varsa yalnız o anahtarın satırları (liste satırı ya da anahtarın geçtiği
    `probe_get` sonucunun `ekran_rotasi`'si); yoksa yalnız `ekran_rotasi` satırları (tek kayıt).
    """
    out: list[str] = []
    for k in kanitlar:
        if getattr(k, "arac", None) not in _KAYIT_ARACLARI:
            continue
        metin = str(getattr(k, "metin", "") or "")
        kanitta_anahtar = any(a in metin for a in anahtarlar)
        for satir in metin.splitlines():
            ekran = satir.strip().startswith(_EKRAN_ROTASI)
            if anahtarlar:
                if not (any(a in satir for a in anahtarlar) or (ekran and kanitta_anahtar)):
                    continue
            elif not ekran:
                continue
            for r in _ROTA_PARCASI.findall(satir):
                if r not in out:
                    out.append(r)
    return out


def _kimlik(rota: str, tur: str, rota_varliklari: Mapping[str, str | None]) -> str | None:
    """Somut rotadaki `:id` (rotanın kalıbı `tur` varlığının ekranıysa)."""
    from tp_core.features.assistant.schemas import rota_indirge

    eslesme = rota_indirge(rota)
    if eslesme is None or rota_varliklari.get(eslesme[0]) != tur:
        return None
    for kalip_parca, parca in zip(eslesme[0].split("/"), rota.split("/"), strict=False):
        if kalip_parca == ":id":
            return parca
    return None


def _doldur(
    kalip: str,
    baglam: Mapping[str, Any] | None,
    kanitlar: Iterable[Any],
    soru: str | None,
    rules_dir: Path | None,
    gereksinim_kimligi: Callable[[str], str | None] | None = None,
) -> str | None:
    if ":id" not in kalip:
        return kalip
    rota = sozluk.rota_doldur(kalip, baglam, rules_dir=rules_dir)
    if rota:
        return rota
    rota_varliklari = sozluk.rota_varliklari(rules_dir)
    tur = rota_varliklari.get(kalip)
    if tur is None:
        return None
    anahtarlar = siniflandir.jira_anahtarlari(soru)
    kimlikler = {
        kimlik
        for r in _kanit_rotalari(kanitlar, anahtarlar)
        if (kimlik := _kimlik(r, tur, rota_varliklari))
    }
    if not kimlikler and tur == "requirement" and gereksinim_kimligi and len(anahtarlar) == 1:
        # Araç çağrılmadıysa soruda tek Jira anahtarı → Testing Probe'daki gereksinimi.
        kimlik = gereksinim_kimligi(anahtarlar[0])
        kimlikler = {kimlik} if kimlik else set()
    if len(kimlikler) != 1:  # yok ya da belirsiz: tahmin yok
        return None
    return sozluk.rota_doldur(kalip, {"varlik": {"tur": tur, "id": kimlikler.pop()}})


def ekran_rotasi(
    soru: str | None,
    baglam: Mapping[str, Any] | None,
    kanitlar: Iterable[Any] = (),
    *,
    rules_dir: Path | None = None,
    gereksinim_kimligi: Callable[[str], str | None] | None = None,
) -> str | None:
    """Eylem isteğinin ekranı (somut iç rota) ya da None. Doğrulama/rol süzgeci çağırandadır."""
    kayit = eslesen(soru, rules_dir=rules_dir)
    if kayit is not None:
        rota = (
            _doldur(kayit.rota, baglam, kanitlar, soru, rules_dir, gereksinim_kimligi)
            or kayit.liste
        )
        if rota:
            return rota
    kalip = baglam.get("rota_kalibi") if isinstance(baglam, Mapping) else None
    if isinstance(kalip, str) and kalip not in _EKRANSIZ:
        return sozluk.rota_doldur(kalip, baglam, rules_dir=rules_dir)
    return None
