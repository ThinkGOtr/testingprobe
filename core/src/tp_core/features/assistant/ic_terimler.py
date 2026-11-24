"""İç durum/tip kodlarının kullanıcıya görünen Türkçe etiketleri (asistan; B6.1 F-B6-01/02).

Asistanın araç çıktısı (`probe_get`) eskiden ham kodları taşıyordu (`sinif: product_defect`,
`karar_kaynagi: rule`, `kural: karar_tablosu`, `oneri_turu: bug_draft`, `oneri_durumu: merged`).
Model bunları cevaba aynen yazıyor ("öneri türü bug_draft, durumu merged") ve `merged`'i
"birleştirildi" diye yanlış okuyordu (bug taslağında `merged` = bug Jira'ya yazıldı ya da mevcut
kayda bağlandı; onarımda = PR birleştirildi).

İki katman:

1. **Araç çıktısı** (`etiketle`): değer kodu yerine portalın etiketi yazılır (portal
   `review-portal/src/lib/etiketler.ts` ve `HataDetay.tsx` ile aynı dil). Model kodu hiç görmez;
   alıntı ("Alıntıyı göster") da okunur olur. `merged` gibi bağlama bağlı kodlar kaydın kendi
   türüne göre açılır.
2. **Cevap metni** (`kullanici_metni`, son işlem): model ürün kodundan/belgeden okuduğu bir kodu
   yine de yazarsa, alt çizgili bilinen iç kodlar ve alan adları etikete çevrilir ("product_defect
   (Ürün hatası)" → "Ürün hatası"). Alıntılar ve `kod` blokları değişmez (kaynak doğrulaması
   birebir alıntıya dayanır).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

# --- değer etiketleri (portal: lib/etiketler.ts) -------------------------------------------

HATA_SINIFI: Final = {
    "environment": "Ortam",
    "flaky": "Flaky (kararsız test)",
    "test_maintenance": "Test bakımı",
    "product_defect": "Ürün hatası",
    "test_data": "Test verisi",
    "unknown": "Belirsiz",
}
# Portal: HataDetay.kararKaynagiMetni.
KARAR_KAYNAGI: Final = {
    "rule": "otomatik kural",
    "llm": "AI (kural eşleşmedi)",
    "human": "insan sınıflandırması",
}
KURAL_ALT_ADI: Final = {
    "locator": "locator değişikliği",
    "timing": "zamanlama",
    "data": "test verisi",
    "beklenti": "test beklentisi onaylı karar tablosundan farklı",
}
ONERI_TURU: Final = {
    "locator_fix": "locator onarımı",
    "bug_draft": "bug taslağı",
    "none": "öneri yok",
}
# `failure.oneri_durumu` öneri türüne göre okunur (bugs.service._oneri_durumu_yaz).
ONERI_DURUMU: Final[dict[str, dict[str, str]]] = {
    "bug_draft": {
        "none": "bug taslağı yok",
        "proposed": "bug taslağı Test Uzmanı kararını bekliyor",
        "pr_open": "bug taslağı işlemde",
        "merged": "karar verildi; bug Jira'ya yazıldı (yeni kayıt ya da mevcut kayda bağlandı)",
        "rejected": "bug taslağı reddedildi",
    },
    "locator_fix": {
        "none": "onarım yok",
        "proposed": "onarım önerildi",
        "pr_open": "onarım PR'ı açık",
        "merged": "onarım PR'ı birleştirildi",
        "rejected": "onarım reddedildi",
    },
    "none": {
        "none": "öneri yok",
        "proposed": "önerildi",
        "pr_open": "PR açık",
        "merged": "tamamlandı",
        "rejected": "reddedildi",
    },
}
BUG_DURUMU: Final = {
    "draft": "Onay bekliyor",
    "approved": "Onaylandı, Jira'ya yazılıyor",
    "dismissed": "Reddedildi",
    "published": "Jira'da",
}
BUG_KARARI: Final = {"new": "yeni Jira kaydı", "link": "mevcut Jira kaydına bağla"}
KOSU_SONUCU: Final = {
    "queued": "Sırada",
    "running": "Koşuyor",
    "passed": "Geçti",
    "failed": "Başarısız",
    "error": "Hata (testler koşmadı)",
    "zaman_asimi": "Zaman aşımı",
    "flaky": "Flaky",
    "skipped": "Atlandı",
}
TETIK: Final = {
    "pr": "PR",
    "push": "Push (main)",
    "nightly": "Gece",
    "deploy": "Deploy",
    "break_verify": "Kırarak doğrula",
    "local_check": "Yerel kontrol",
    "manual": "Elle",
    "sauce": "Sauce Labs",
}
KOSU_KAYNAGI: Final = {"local": "Yerel Chromium", "github": "GitHub Actions", "sauce": "Sauce Labs"}
SCRIPT_DURUMU: Final = {
    "pending": "Sırada",
    "verifying": "Ajan doğruluyor",
    "checking": "Yerel kontrol",
    "blocked": "İnsana düştü",
    "pr_open": "PR açık",
    "merged": "Birleştirildi",
    "closed": "Kapatıldı",
    "failed": "Başarısız",
    "unverified": "Doğrulanmamış",
}


def kural_etiketi(kural: Any) -> str | None:
    """`kural` kodu → okunur ad (portal `kuralAdi`; `karar_tablosu` 012 Ş3)."""
    if not isinstance(kural, str) or not kural:
        return None
    if kural == "karar_tablosu":
        return "onaylı karar tablosu kuralı"
    sinif, _, alt = kural.partition("/")
    etiket = HATA_SINIFI.get(sinif)
    if etiket is None:
        return kural.replace("_", " ")
    if not alt:
        return f"{etiket} kuralı"
    return f"{etiket} kuralı · {KURAL_ALT_ADI.get(alt, alt.replace('_', ' '))}"


def _oneri_durumu(deger: Any, kayit: Mapping[str, Any]) -> Any:
    tur = kayit.get("oneri_turu")
    tablo = ONERI_DURUMU.get(tur if isinstance(tur, str) else "none") or ONERI_DURUMU["none"]
    return tablo.get(deger, deger) if isinstance(deger, str) else deger


def _tablo(tablo: Mapping[str, str]) -> Any:
    return lambda deger, _kayit: tablo.get(deger, deger) if isinstance(deger, str) else deger


# Tür → alan → çevirici (değer, kaydın seçili alanları) → etiket.
_CEVIRICILER: Final[dict[str, dict[str, Any]]] = {
    "failure": {
        "sinif": _tablo(HATA_SINIFI),
        "karar_kaynagi": _tablo(KARAR_KAYNAGI),
        "kural": lambda d, _k: kural_etiketi(d) or d,
        "alt_tur": _tablo(KURAL_ALT_ADI),
        "oneri_turu": _tablo(ONERI_TURU),
        "oneri_durumu": _oneri_durumu,
        "tetik": _tablo(TETIK),
    },
    "bug_draft": {
        "durum": _tablo(BUG_DURUMU),
        "karar": _tablo(BUG_KARARI),
    },
    "run": {
        "sonuc": _tablo(KOSU_SONUCU),
        "tetik": _tablo(TETIK),
        "kaynak": _tablo(KOSU_KAYNAGI),
    },
    "script": {"durum": _tablo(SCRIPT_DURUMU)},
}


def etiketle(tur: str, alanlar: Mapping[str, Any]) -> dict[str, Any]:
    """Araç çıktısının seçili alanlarında iç kodları portal etiketine çevirir (kopya)."""
    ceviriciler = _CEVIRICILER.get(tur) or {}
    out = dict(alanlar)
    for alan, cevir in ceviriciler.items():
        if alan in out and out[alan] not in (None, ""):
            out[alan] = cevir(out[alan], alanlar)
    return out


# --- cevap metni güvenlik ağı ----------------------------------------------------------------

# Alt çizgili, ürüne özgü iç kodlar (tek anlamlı; düz İngilizce sözcükler — "merged", "rule" —
# burada yoktur, onlar araç çıktısında zaten etiketlenir).
IC_KODLAR: Final = {
    "product_defect": "Ürün hatası",
    "test_maintenance": "Test bakımı",
    "test_data": "Test verisi",
    "bug_draft": "bug taslağı",
    "locator_fix": "locator onarımı",
    "karar_tablosu": "onaylı karar tablosu kuralı",
    "pr_open": "PR açık",
    "break_verify": "kırarak doğrulama",
    "local_check": "yerel kontrol",
    "oneri_durumu": "öneri durumu",
    "oneri_turu": "öneri türü",
    "karar_kaynagi": "karar kaynağı",
    "eslesen_sinyaller": "eşleşen sinyaller",
    "bekleyen_kapi": "bekleyen adım",
    "sorumlu_rol": "sorumlu rol",
    "ekran_rotasi": "ekran",
    "alt_tur": "alt tür",
}
_TIRNAK: Final = "\"'`“”‘’"
_KOD_ADLARI: Final = "|".join(sorted(IC_KODLAR, key=len, reverse=True))
_KOD: Final = re.compile(
    rf"[{_TIRNAK}]?(?<![\w/.])({_KOD_ADLARI})(?![\w/])(?!\.\w)"
    rf"[{_TIRNAK}]?(\s*\(([^()\n]{{1,80}})\))?"
)


def _tr_kucuk(metin: str) -> str:
    return metin.replace("I", "ı").replace("İ", "i").lower()


def _kod_yerine(m: re.Match[str]) -> str:
    etiket = IC_KODLAR[m.group(1)]
    parantez = m.group(3)
    if parantez is None:
        return etiket
    # "product_defect (ürün hatası adayı)" → "ürün hatası adayı": parantez zaten etiketi söylüyor.
    if _tr_kucuk(etiket) in _tr_kucuk(parantez):
        return parantez.strip()
    return f"{etiket} ({parantez.strip()})"


def kullanici_metni(metin: str) -> str:
    """Cevap metnindeki bilinen iç kodları etikete çevirir (kod blokları için çağrılmaz)."""
    if not metin or "_" not in metin:
        return metin
    return _KOD.sub(_kod_yerine, metin)
