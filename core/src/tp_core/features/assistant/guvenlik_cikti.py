"""Asistan çıktısında kanarya ve istem sızıntısı denetimi (specs/013 §6.3; K5a).

- **Kanarya**: worker süreci başına bir kez `TP-CANARY-` + 8 hex (`secrets.token_hex(4)`) üretilir
  (`kanarya()`); `sistem_eki()` bunu geçidin bundle sistem isteminin sonuna eklediği yorum
  satırıdır (`run_agent(..., sistem_eki=...)`). Replay anahtarı bundan etkilenmez (geçit eki yalnız
  canlı isteğin `system` metnine ekler). Sağlayıcının prompt önbelleği ise sistem metninin
  tamamını önek sayar: kanarya her süreçte değiştiğinden önbellek süreç başına bir kez soğuk
  başlar (aynı süreçteki istekler isabet eder).
- **Sızıntı taraması** (`sizinti_var`): `sonislem.isle` sonrası cevabın **bütün dizge değerleri**
  (`gorunur_dizgeler`; bloklar, notlar, kaynak alıntı/ref, yönlendirme etiketi, öneri ve Jira
  taslakları dahil, özyinelemeli) taranır: herhangi bir kanarya (`tp canary` + 8 hex; yalnız bu
  sürecinki değil, başka sürecin ya da eski bir kanaryanın sızması da sızıntıdır), bu sürecin
  kanaryasının yalnız hex kısmı ya da `rules/assistant/istem-izleri.yaml`'daki parmak izi
  cümlelerinden biri. İz eşleşmesi normalize edilmiş metinde yapılır (Türkçe küçük harf, aksan
  katlama, noktalama → boşluk).
- Sızıntıda cevap `istem_sizintisi_cevabi()` ile değiştirilir (`sizinti: true`; portal güven
  rozetini göstermez); olay (`kanarya` | `istem_sizintisi`, ciddi) çağıranda (`flow.cevapla`)
  yazılır. Eşleşen metin hiçbir yere yazılmaz.

Parmak izi dosyası yoksa liste boştur (kanarya denetimi yine çalışır); bozuksa uyarı loglanır ve
liste yine boştur. Dosya biçimi: `izler: [cümle, …]` (ya da düz liste). Normalize edildiğinde
`IZ_EN_KISA`'dan kısa cümle yok sayılır (tek kelimelik iz masum cevaplarda yanlış pozitif üretir).
"""

from __future__ import annotations

import logging
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

log = logging.getLogger(__name__)
KANARYA_ONEKI: Final = "TP-CANARY-"
IZ_DOSYASI: Final = "istem-izleri.yaml"
IZ_EN_KISA: Final = 20
SIZINTI_METNI: Final = (
    "Bu cevap gösterilemedi. Sorunuzu ekran, kayıt ya da koşu adıyla yeniden sorabilirsiniz; "
    "neler yapabildiğimi görmek için 'Ne yapabilirsin?' yazın."
)

SizintiTuru = Literal["kanarya", "istem_sizintisi"]

# Model öneki küçük harfe çevirse ya da ayırıcıyı değiştirse de yakalansın. Kelime sınırı ve
# 8 hex şart: "HTTP canary uç noktası", "smtp-canary testi" gibi masum metinler tetiklemez.
_KANARYA_DESENI: Final = re.compile(r"\btp[\s_-]*canary[\s_-]*[0-9a-f]{8}\b", re.IGNORECASE)
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
    dosya = Path(yol)
    if not dosya.is_file():
        return ()
    try:
        veri = yaml.safe_load(dosya.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        # Önbellekli: bozuk dosya süreç başına bir kez loglanır (değer/metin yazılmaz).
        log.warning("asistan: istem izleri yüklenemedi (%s)", type(exc).__name__)
        return ()
    if isinstance(veri, Mapping):
        veri = veri.get("izler")
    if not isinstance(veri, list):
        log.warning("asistan: istem izleri dosyası beklenen biçimde değil")
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


def gorunur_dizgeler(deger: Any) -> Iterator[str]:
    """Cevabın bütün dizge değerleri, özyinelemeli (sözlük anahtarları hariç). Sızıntı taramasının
    tek kaynağı: kullanıcıya ulaşan her alan (bloklar, notlar, `kaynaklar[].alinti/ref`,
    `yonlendirmeler[].etiket`, öneri ve Jira taslakları) kapsanır; yeni alan eklense de taranır."""
    if isinstance(deger, str):
        if deger:
            yield deger
    elif isinstance(deger, Mapping):
        for v in deger.values():
            yield from gorunur_dizgeler(v)
    elif isinstance(deger, list | tuple):
        for v in deger:
            yield from gorunur_dizgeler(v)


def sizinti_var(
    cevap: Mapping[str, Any], kanarya: str | None, izler: Iterable[str]
) -> SizintiTuru | None:
    """Cevabın dizgelerinde kanarya (herhangi bir `TP-CANARY-` değeri) ya da istem izi var mı.

    `kanarya` bu sürecin değeridir; önek deseni zaten her kanaryayı kapsar, ama değerin kendisi
    (öneki atılarak yalnız hex kısmı yazılmışsa) da aranır. `izler` normalize edilmiş olmalıdır
    (`izleri_yukle`)."""
    parcalar = list(gorunur_dizgeler(cevap))
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
    """§6.3 yerine geçen cevap: tek paragraf (ortak metin), `sizinti=true` (portal güven rozetini
    göstermez), `eylem_reddi=false`, `guven=dusuk`; kaynak/öneri yok."""
    out = sonislem.bos_cevap()
    out["cevap_bloklari"] = [{"tur": "paragraf", "metin": SIZINTI_METNI, "maddeler": []}]
    out["guven"] = "dusuk"
    out["guven_gosterimi"] = sonislem.guven_gosterimi(
        "dusuk", [], urune_ozgu=False, toparlama=False
    )
    out["eylem_reddi"] = False
    out["sizinti"] = True
    return out
