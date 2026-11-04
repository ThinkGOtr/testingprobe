"""Asistan sorusunun deterministik sınıflandırması (AI-ASISTAN-PLANI §5.4, §10.2; constitution XI).

Modelsiz kararlar burada; hepsi saf fonksiyondur (DB yok):

- `normalize`: sözlük ve terim eşleşmesinin ortak normalizasyonu — Türkçe küçük harf (I→ı, İ→i),
  boşluklar teke indirilir (`rules/assistant/*.yaml` başlık yorumlarıyla ve kural testiyle aynı).
- `urune_ozgu`: soru ürüne özgü mü (§5.4) — bağlamda ana sayfa dışı varlık/rota **veya** soruda
  `[A-Z]+-\\d+` anahtarı **veya** `urun-terimleri.yaml` terimi (kelime başında önek eşleşmesi)
  **veya** model bir ürün/probe/uygulama aracı çağırdı. Ürüne özgü soruda yalnız `genel_bilgi`
  kaynaklı cevap en fazla "Kısmen" gösterilir (§7.3).
- `ne_demek_sorusu`: sözlük dalının soru sınıfı ("ne demek / neden"; §10.2 adım 2).
- `durum_sorusu`, `kuyruk_sorusu`: şablon dalının soru sınıfları (§10.2 adım 3).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

TERIM_DOSYASI: Final = "urun-terimleri.yaml"
# ASCII: `\d` Unicode rakamlarını da kabul ederdi (Jira anahtar atlatma, §13 Güvenlik).
ANAHTAR_DESENI: Final = re.compile(r"[A-Z]+-[0-9]+")
JIRA_ANAHTARI: Final = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]+-[0-9]+)(?![0-9])")
ANA_SAYFA: Final = "/"

# Modelin çağırdığı her asistan aracı ürüne/Probe'a/test edilen uygulamaya özgüdür (§5.4: "model
# bir ürün/probe/uygulama aracı çağırdı"). Liste `tools.ARAC_ADLARI` ile aynı; burada sabit tutulur
# ki sınıflandırıcı araç paketini içe aktarmasın.
URUN_ARACLARI: Final = frozenset(
    {
        "product_search",
        "product_read",
        "probe_get",
        "probe_list",
        "probe_jobs",
        "probe_audit",
        "probe_my_queue",
        "jira_issue",
        "ci_log",
        "search_code",
        "get_file_contents",
        "db_schema",
        "db_query",
    }
)

# Sözlük dalı: "Bu hata ne demek?", "Neden oldu?", "Ne anlama geliyor?" …
_NE_DEMEK: Final = (
    "ne demek",
    "ne anlama",
    "anlamı ne",
    "anlami ne",
    "nedir",
    "neden",
    "niye",
    "niçin",
    "nicin",
    "ne oldu",
    "hata ne",
    "bu hata",
    "bu ne",
    "neyi ifade",
    # Ekrandaki hata çoğu zaman "mesaj/uyarı/bildirim" diye anılır ("Bu mesaj ne?").
    "bu mesaj",
    "mesaj ne",
    "bu uyarı",
    "bu uyari",
    "uyarı ne",
    "uyari ne",
    "bu bildirim",
    "bildirim ne",
)
# Şablon dalı (anahtarla birlikte): "TPD-3 neden bekliyor?", "TPD-3'ün durumu ne?", "nerede?" …
_DURUM: Final = (
    "neden",
    "niye",
    "niçin",
    "nicin",
    "durum",
    "nerede",
    "hangi aşama",
    "hangi asama",
    "bekliyor",
    "ne zaman",
    "takıl",
    "geçmiyor",
    "ilerlemiyor",
)
# "Bugün ne yapmalıyım?" sınıfı → `probe_my_queue`.
_KUYRUK: Final = (
    "bugün ne yap",
    "bugun ne yap",
    "ne yapmalıyım",
    "ne yapmaliyim",
    "ne yapmam gerek",
    "bekleyen işlerim",
    "bekleyen islerim",
    "işlerim neler",
    "islerim neler",
    "beni bekleyen",
    "sıramda ne",
    "kuyruğumda",
)


def normalize(metin: str | None) -> str:
    """Türkçe küçük harf (I→ı, İ→i) ve tek boşluk."""
    if not metin:
        return ""
    return " ".join(metin.replace("I", "ı").replace("İ", "i").lower().split())


def _icerir(metin: str, parcalar: Iterable[str]) -> bool:
    return any(p in metin for p in parcalar)


# ------------------------------------------------------------------ ürün terimleri


@lru_cache(maxsize=4)
def _terimler(yol: str) -> tuple[str, ...]:
    try:
        veri = yaml.safe_load(Path(yol).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ()
    return tuple(normalize(str(t)) for t in veri.get("terimler") or [] if str(t).strip())


def urun_terimleri(rules_dir: Path | None = None) -> tuple[str, ...]:
    from tp_core.gateway.config import find_rules_dir

    return _terimler(str(find_rules_dir(rules_dir) / "assistant" / TERIM_DOSYASI))


def terim_eslesir(soru: str | None, terimler: Iterable[str]) -> bool:
    """Terim kelime başında başlamalı (önek eşleşmesi: "gereksinim" → "gereksinimleri")."""
    metin = normalize(soru)
    return any(re.search(r"(?<!\w)" + re.escape(t), metin) for t in terimler if t)


def baglam_urune_ozgu(baglam: Mapping[str, Any] | None) -> bool:
    """Bağlamda varlık ya da ana sayfa dışı rota var mı."""
    if not isinstance(baglam, Mapping):
        return False
    varlik = baglam.get("varlik")
    if isinstance(varlik, Mapping) and any(varlik.get(k) for k in ("id", "anahtar", "tur")):
        return True
    rota = baglam.get("rota_kalibi")
    return isinstance(rota, str) and bool(rota) and rota != ANA_SAYFA


def urune_ozgu(
    soru: str | None,
    baglam: Mapping[str, Any] | None = None,
    *,
    terimler: Iterable[str] | None = None,
    araclar: Iterable[str] = (),
) -> bool:
    """§5.4 deterministik "ürüne özgü soru" kararı."""
    if baglam_urune_ozgu(baglam):
        return True
    if soru and ANAHTAR_DESENI.search(soru):
        return True
    if terim_eslesir(soru, urun_terimleri() if terimler is None else terimler):
        return True
    return any(a in URUN_ARACLARI for a in araclar)


# ------------------------------------------------------------------ dal sınıfları


def ne_demek_sorusu(soru: str | None) -> bool:
    return _icerir(normalize(soru), _NE_DEMEK)


def jira_anahtarlari(soru: str | None) -> list[str]:
    """Sorudaki Jira biçimli anahtarlar (sırayla, tekil)."""
    gorulen: list[str] = []
    for m in JIRA_ANAHTARI.finditer(soru or ""):
        if m.group(1) not in gorulen:
            gorulen.append(m.group(1))
    return gorulen


def durum_sorusu(soru: str | None) -> str | None:
    """Şablon: sorudaki tek Jira anahtarı + "neden/durum/nerede" sınıfı → anahtar; değilse None.

    Birden çok anahtar varsa şablon kullanılmaz (karşılaştırma sorusu modele kalır).
    """
    anahtarlar = jira_anahtarlari(soru)
    if len(anahtarlar) != 1:
        return None
    return anahtarlar[0] if _icerir(normalize(soru), _DURUM) else None


def kuyruk_sorusu(soru: str | None) -> bool:
    return _icerir(normalize(soru), _KUYRUK)
