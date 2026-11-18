"""Müşteri CI hattının durum akışı (TASARIM test-dilleri §3.3, §3.4). Saf; veritabanı/ağ yok.

    kurulum_gerekli ──(kurulum PR'ı birleşti)──► uretildi
    uretildi ──► pr_acildi ──► ci_bekleniyor ──► ci_kosuyor ──► yesil | kirmizi | derleme_hatasi
                                                                 | sonuc_yok
    (yeni commit / yeniden deneme: son durumlardan ci_bekleniyor'a dönülür; her durumdan iptal)

- **yesil**: check `success` ve tp-results'ta en az bir test, başarısız yok. Merge için yeterlidir
  (kullanıcı kararı 2); "kırarak doğrulanmadı" bilgisi yine gösterilir.
- **kirmizi**: JUnit okundu, en az bir test başarısız (triage türü: test hatası).
- **derleme_hatasi**: check başarısız ve JUnit yok (iş adımı kırmızı) → triage türü `derleme`,
  log kesiti (`sonuc.derleme_kesiti`).
- **sonuc_yok**: check başarılı ama tp-results yok/boş (yanlış-yeşil koruması: merge edilmez).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class HatDurumu(StrEnum):
    KURULUM_GEREKLI = "kurulum_gerekli"
    URETILDI = "uretildi"
    PR_ACILDI = "pr_acildi"
    CI_BEKLENIYOR = "ci_bekleniyor"
    CI_KOSUYOR = "ci_kosuyor"
    YESIL = "yesil"
    KIRMIZI = "kirmizi"
    DERLEME_HATASI = "derleme_hatasi"
    SONUC_YOK = "sonuc_yok"
    IPTAL = "iptal"


D = HatDurumu
SONUC_DURUMLARI: frozenset[HatDurumu] = frozenset(
    {D.YESIL, D.KIRMIZI, D.DERLEME_HATASI, D.SONUC_YOK}
)
_YENIDEN = frozenset({D.CI_BEKLENIYOR, D.CI_KOSUYOR, *SONUC_DURUMLARI})
GECISLER: dict[HatDurumu, frozenset[HatDurumu]] = {
    D.KURULUM_GEREKLI: frozenset({D.URETILDI, D.IPTAL}),
    D.URETILDI: frozenset({D.PR_ACILDI, D.KURULUM_GEREKLI, D.IPTAL}),
    D.PR_ACILDI: frozenset({D.CI_BEKLENIYOR, *_YENIDEN, D.IPTAL}),
    D.CI_BEKLENIYOR: frozenset({*_YENIDEN, D.IPTAL}),
    D.CI_KOSUYOR: frozenset({*_YENIDEN, D.IPTAL}),
    # Son durumlar: yeni commit/yeniden deneme yeniden bekleme başlatır.
    **{s: frozenset({*_YENIDEN, D.IPTAL}) for s in SONUC_DURUMLARI},
    D.IPTAL: frozenset(),
}

# Portal etiketi (Türkçe, kısa).
ETIKETLER: dict[HatDurumu, str] = {
    D.KURULUM_GEREKLI: "Kurulum gerekli",
    D.URETILDI: "Üretildi",
    D.PR_ACILDI: "PR açıldı",
    D.CI_BEKLENIYOR: "Müşteri CI bekleniyor",
    D.CI_KOSUYOR: "Müşteri CI koşuyor",
    D.YESIL: "Müşteri CI yeşil",
    D.KIRMIZI: "Test başarısız",
    D.DERLEME_HATASI: "Derleme hatası",
    D.SONUC_YOK: "Sonuç artefaktı yok",
    D.IPTAL: "İptal",
}


class GecersizGecis(ValueError):
    pass


def durum(deger: Any) -> HatDurumu:
    try:
        return HatDurumu(deger)
    except ValueError:
        raise GecersizGecis(f"bilinmeyen hat durumu: {deger!r}") from None


def gecis_var_mi(mevcut: Any, yeni: Any) -> bool:
    try:
        return durum(yeni) in GECISLER[durum(mevcut)] or durum(mevcut) == durum(yeni)
    except GecersizGecis:
        return False


def gecis(mevcut: Any, yeni: Any) -> HatDurumu:
    """`mevcut` → `yeni` geçişini doğrular (aynı duruma geçiş idempotent); geçersizse
    `GecersizGecis`."""
    m, y = durum(mevcut), durum(yeni)
    if m != y and y not in GECISLER[m]:
        raise GecersizGecis(f"geçersiz hat geçişi: {m} → {y}")
    return y


# GitHub check `conclusion` değerleri.
_BASARILI = frozenset({"success"})
_BASARISIZ = frozenset({"failure", "timed_out", "startup_failure", "action_required"})
_IPTAL = frozenset({"cancelled", "stale"})


def check_durumu(status: Any, conclusion: Any) -> HatDurumu:
    """GitHub check'inin ham durumu → hat durumu (artefakt okunmadan; ara durum).

    `completed` olmayan check `ci_kosuyor` (queued → `ci_bekleniyor`). Tamamlanmışta artefakt
    okunmadan son karar verilmez: başarılı → `sonuc_yok` (tp-results okunana kadar), başarısız →
    `derleme_hatasi` (JUnit okununca `kirmizi`'ya iner), iptal/atlandı → `ci_bekleniyor`
    (yeniden deneme beklenir)."""
    if status in ("queued", "requested", "waiting", "pending"):
        return D.CI_BEKLENIYOR
    if status != "completed":
        return D.CI_KOSUYOR
    if conclusion in _BASARILI:
        return D.SONUC_YOK
    if conclusion in _BASARISIZ:
        return D.DERLEME_HATASI
    return D.CI_BEKLENIYOR


def sonuctan_durum(conclusion: Any, sayac: dict[str, int] | None) -> HatDurumu:
    """Tamamlanmış check + tp-results ayrıştırması (sayac: `parse.sayilar` biçimi; artefakt
    yok/okunamadıysa None) → son hat durumu.

    Kural: başarısız test varsa `kirmizi` (check sonucu ne olursa olsun); test yoksa check
    başarısızsa `derleme_hatasi`, başarılıysa `sonuc_yok`; testler geçti ama check kırmızıysa
    (ör. tp-results sonrası adım düştü) `kirmizi` değil `derleme_hatasi` (iş kırmızı, test yeşil
    — kanıt eksik); her şey yeşilse `yesil`."""
    s = sayac or {}
    toplam = int(s.get("toplam") or 0)
    gecen = int(s.get("gecen") or 0) + int(s.get("flaky") or 0)
    basarisiz = int(s.get("basarisiz") or 0)
    if basarisiz > 0:
        return D.KIRMIZI
    if toplam == 0 or gecen == 0:  # test yok ya da hepsi atlandı: kanıt yok
        if conclusion in _BASARISIZ:
            return D.DERLEME_HATASI
        return D.SONUC_YOK if conclusion in _BASARILI else D.CI_BEKLENIYOR
    if conclusion in _BASARILI:
        return D.YESIL
    if conclusion in _BASARISIZ:
        return D.DERLEME_HATASI
    return D.CI_BEKLENIYOR


def merge_kapisi(d: Any) -> tuple[bool, str]:
    """Merge kapısı (kullanıcı kararı 2): yalnız `yesil` geçer; neden metni portal/PR içindir."""
    try:
        h = durum(d)
    except GecersizGecis:
        return False, "bilinmeyen hat durumu"
    if h == D.YESIL:
        return True, "müşteri CI yeşil (kırarak doğrulanmadı)"
    return False, ETIKETLER[h]


def triage_turu(d: Any) -> str | None:
    """Hata durumunun triage türü: `derleme_hatasi` → `derleme`, `kirmizi` → `test`,
    `sonuc_yok` → `sonuc_yok`; diğerleri None."""
    try:
        h = durum(d)
    except GecersizGecis:
        return None
    return {D.DERLEME_HATASI: "derleme", D.KIRMIZI: "test", D.SONUC_YOK: "sonuc_yok"}.get(h)
