"""Asistan çıktısında kanarya ve istem sızıntısı denetimi (specs/013 §6.3; K5a).

- **Kanarya**: worker süreci başına bir kez `TP-CANARY-` + 8 hex (`secrets.token_hex(4)`) üretilir
  (`kanarya()`); `sistem_eki()` bunu geçidin bundle sistem isteminin sonuna eklediği yorum
  satırıdır (`run_agent(..., sistem_eki=...)`). Replay anahtarı ve önbellek öneki bundan
  etkilenmez (geçit eki yalnız canlı isteğin `system` metnine ekler).
- **Sızıntı taraması** (`sizinti_var`): `sonislem.isle` sonrası **görünür** cevap metninde
  (bloklar, maddeler, notlar, öneri başlık/neden/taslak) herhangi bir `TP-CANARY-` öneki (yalnız
  bu sürecinki değil: başka sürecin ya da eski bir kanaryanın sızması da sızıntıdır) ya da
  `rules/assistant/istem-izleri.yaml`'daki parmak izi cümlelerinden biri aranır. Eşleşme
  normalize edilmiş metinde yapılır (Türkçe küçük harf, aksan katlama, noktalama → boşluk).
- Sızıntıda cevap `istem_sizintisi_cevabi()` ile değiştirilir; olay (`kanarya` |
  `istem_sizintisi`, ciddi) çağıranda (`flow.cevapla`) yazılır. Eşleşen metin hiçbir yere
  yazılmaz.

Parmak izi dosyası yoksa ya da okunamazsa liste boştur (kanarya denetimi yine çalışır). Dosya
biçimi: `izler: [cümle, …]` (ya da düz liste). Normalize edildiğinde `IZ_EN_KISA`'dan kısa cümle
yok sayılır (tek kelimelik iz masum cevaplarda yanlış pozitif üretir).
"""

from __future__ import annotations

import re
import secrets
import threading
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from tp_core.features.assistant import siniflandir, sonislem

KANARYA_ONEKI: Final = "TP-CANARY-"
IZ_DOSYASI: Final = "istem-izleri.yaml"
IZ_EN_KISA: Final = 20
SIZINTI_METNI: Final = (
    "Bu cevabı gösteremiyorum; iç talimatlarımı paylaşamam. Neler yapabildiğimi özetleyebilirim."
)

SizintiTuru = Literal["kanarya", "istem_sizintisi"]

# Model öneki küçük harfe çevirse ya da ayırıcıyı değiştirse de yakalansın.
_KANARYA_DESENI: Final = re.compile(r"tp[\s_\-]*canary", re.IGNORECASE)
_NOKTALAMA: Final = re.compile(r"[^\w]+")

_kilit = threading.Lock()
_kanarya: str | None = None


def kanarya() -> str:
    """Süreç başına tek kanarya (`TP-CANARY-` + 8 hex); ilk çağrıda üretilir."""
    global _kanarya
    if _kanarya is None:
        with _kilit:
            if _kanarya is None:
                _kanarya = KANARYA_ONEKI + secrets.token_hex(4)
    return _kanarya


def sistem_eki() -> str:
    """Geçidin sistem isteminin sonuna eklediği satır (`run_agent(sistem_eki=...)`)."""
    return f"<!-- iz: {kanarya()} -->"


def normalize(metin: str | None) -> str:
    """Türkçe küçük harf, aksan/nokta katlama (ı→i, ç→c, İ→i …), noktalama → boşluk, tek boşluk.

    İz ve cevap aynı biçimde katlanır: model büyük harfle (`.upper()` "i"yi "I" yapar), aksansız
    ya da farklı noktalamayla yazsa da eşleşir."""
    kucuk = siniflandir.normalize(metin)
    ayrik = unicodedata.normalize("NFKD", kucuk)
    katli = "".join(c for c in ayrik if not unicodedata.combining(c)).replace("ı", "i")
    return " ".join(_NOKTALAMA.sub(" ", katli.casefold()).split())


@lru_cache(maxsize=4)
def _izler(yol: str) -> tuple[str, ...]:
    try:
        veri = yaml.safe_load(Path(yol).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ()
    if isinstance(veri, Mapping):
        veri = veri.get("izler")
    if not isinstance(veri, list):
        return ()
    out: list[str] = []
    for ham in veri:
        iz = normalize(str(ham)) if isinstance(ham, str) else ""
        if len(iz) >= IZ_EN_KISA and iz not in out:
            out.append(iz)
    return tuple(out)


def izleri_yukle(rules_dir: Path | None = None) -> tuple[str, ...]:
    """Normalize edilmiş parmak izi cümleleri (önbellekli); dosya yoksa boş."""
    from tp_core.gateway.config import find_rules_dir

    try:
        kok = find_rules_dir(rules_dir)
    except Exception:
        return ()
    return _izler(str(kok / "assistant" / IZ_DOSYASI))


def _gorunur_metinler(cevap: Mapping[str, Any]) -> Iterator[str]:
    for blok in cevap.get("cevap_bloklari") or []:
        if isinstance(blok, Mapping):
            yield str(blok.get("metin") or "")
            yield from (str(m) for m in blok.get("maddeler") or [] if isinstance(m, str))
    yield from (str(n) for n in cevap.get("notlar") or [] if isinstance(n, str))
    for oneri in cevap.get("oneriler") or []:
        if not isinstance(oneri, Mapping):
            continue
        yield str(oneri.get("baslik") or "")
        yield str(oneri.get("neden") or "")
        eylem = oneri.get("eylem")
        taslak = eylem.get("taslak") if isinstance(eylem, Mapping) else None
        if isinstance(taslak, Mapping):
            yield str(taslak.get("ozet") or "")
            yield str(taslak.get("aciklama") or "")


def sizinti_var(
    cevap: Mapping[str, Any], kanarya: str | None, izler: Iterable[str]
) -> SizintiTuru | None:
    """Görünür cevap metninde kanarya (herhangi bir `TP-CANARY-`) ya da istem izi var mı.

    `kanarya` bu sürecin değeridir; önek deseni zaten her kanaryayı kapsar, ama değerin kendisi
    (öneki atılarak yalnız hex kısmı yazılmışsa) da aranır. `izler` normalize edilmiş olmalıdır
    (`izleri_yukle`)."""
    parcalar = [p for p in _gorunur_metinler(cevap) if p]
    if not parcalar:
        return None
    ham = "\n".join(parcalar)
    if _KANARYA_DESENI.search(ham):
        return "kanarya"
    if kanarya:
        hex_kismi = kanarya.removeprefix(KANARYA_ONEKI).casefold()
        desen = rf"(?<![0-9a-f]){re.escape(hex_kismi)}(?![0-9a-f])"
        if hex_kismi and re.search(desen, ham.casefold()):
            return "kanarya"
    metin = normalize(ham)
    if any(iz and iz in metin for iz in izler):
        return "istem_sizintisi"
    return None


def istem_sizintisi_cevabi() -> dict[str, Any]:
    """§6.3 yerine geçen cevap: tek paragraf, `eylem_reddi=false`, `guven=dusuk`; kaynak/öneri
    yok."""
    out = sonislem.bos_cevap()
    out["cevap_bloklari"] = [{"tur": "paragraf", "metin": SIZINTI_METNI, "maddeler": []}]
    out["guven"] = "dusuk"
    out["guven_gosterimi"] = sonislem.guven_gosterimi(
        "dusuk", [], urune_ozgu=False, toparlama=False
    )
    out["eylem_reddi"] = False
    return out
