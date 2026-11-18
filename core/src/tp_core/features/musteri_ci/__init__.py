"""Müşteri CI hattı (`musteri_ci`; TASARIM test-dilleri §3.3, §3.4; şerit Ş5).

TP Kotlin/Espresso ve Swift/XCUITest testlerini üretir, statik korumadan geçirir, PR açar;
derleme ve koşu müşterinin GitHub Actions'ındadır. Bu paket dil şeritlerinin (Ş3, Ş4)
kullandığı ortak çekirdektir:

    from tp_core.features import musteri_ci as mci

    mci.musteri_ci_mi("android", "kotlin")            # True
    mci.is_adi("ios", "swift")                         # "mobil-ios-swift" (= check adı)
    mci.pr_govdesi_notu(p, d)                          # PR gövdesi "kırarak doğrulanmadı" bölümü
    mci.dogrulama_bilgisi(p, d)                        # portal rozeti
    plan = mci.kurulum_plani(params, forge.list_files(), iskelet={...})   # önizleme
    mci.kurulum_pr_ac(forge, plan, onaylayan="kullanici@…")              # insan onaylı
    g = mci.hat_durumu(forge, gh, sha, p, d, kimlik=…)                    # check + tp-results
    mci.merge_kapisi(g.durum)                          # yalnız yesil geçer

Modüller: `sozlesme` (hedefler, ad/yol, rozet), `durum` (durum akışı), `sonuc` (tp-results
alımı), `kurulum` (kurulum PR'ı), `akis` (check + artefakt → durum), `portal` (Ş7 alan
şekilleri: `musteri_ci`, `kurulum`, `hat`, `merge_kabul_gerekli`).
"""

from tp_core.features.musteri_ci.akis import HatGuncellemesi, check_bul, hat_durumu
from tp_core.features.musteri_ci.durum import (
    ETIKETLER,
    GECISLER,
    SONUC_DURUMLARI,
    GecersizGecis,
    HatDurumu,
    check_durumu,
    gecis,
    gecis_var_mi,
    merge_kapisi,
    sonuctan_durum,
    triage_turu,
)
from tp_core.features.musteri_ci.kurulum import (
    KURULUM_DAL_ONEKI,
    KURULUM_ETIKETI,
    KurulumEksigi,
    KurulumOnayiYok,
    KurulumParametreleri,
    KurulumPlani,
    eksikleri_bul,
    kurulum_plani,
    kurulum_pr_ac,
    sablon_isle,
    sablon_metni,
)
from tp_core.features.musteri_ci.portal import (
    PORTAL_DURUMU,
    hat_adi,
    merge_kabul_gerekli,
    portal_kurulum,
    portal_musteri_ci,
)
from tp_core.features.musteri_ci.sonuc import (
    KimlikDonusturucu,
    MusteriCiSonucu,
    derleme_kesiti,
    tp_results_al,
    tp_results_ayristir,
    tp_results_sec,
    tp_results_zip_ayristir,
)
from tp_core.features.musteri_ci.sozlesme import (
    CI_META_AD,
    HAT,
    HEDEFLER,
    KIRARAK_DOGRULANMADI,
    TP_RESULTS_ARTIFACT,
    MusteriCiHatasi,
    MusteriCiHedefi,
    dogrulama_bilgisi,
    hedef,
    hedef_is_adindan,
    is_adi,
    is_adlari,
    musteri_ci_mi,
    pr_govdesi_notu,
    sonuc_koku,
)

__all__ = [
    "CI_META_AD",
    "ETIKETLER",
    "GECISLER",
    "HAT",
    "HEDEFLER",
    "KIRARAK_DOGRULANMADI",
    "KURULUM_DAL_ONEKI",
    "KURULUM_ETIKETI",
    "PORTAL_DURUMU",
    "SONUC_DURUMLARI",
    "TP_RESULTS_ARTIFACT",
    "GecersizGecis",
    "HatDurumu",
    "HatGuncellemesi",
    "KimlikDonusturucu",
    "KurulumEksigi",
    "KurulumOnayiYok",
    "KurulumParametreleri",
    "KurulumPlani",
    "MusteriCiHatasi",
    "MusteriCiHedefi",
    "MusteriCiSonucu",
    "check_bul",
    "check_durumu",
    "derleme_kesiti",
    "dogrulama_bilgisi",
    "eksikleri_bul",
    "gecis",
    "gecis_var_mi",
    "hat_adi",
    "hat_durumu",
    "hedef",
    "hedef_is_adindan",
    "is_adi",
    "is_adlari",
    "kurulum_plani",
    "kurulum_pr_ac",
    "merge_kabul_gerekli",
    "merge_kapisi",
    "musteri_ci_mi",
    "portal_kurulum",
    "portal_musteri_ci",
    "pr_govdesi_notu",
    "sablon_isle",
    "sablon_metni",
    "sonuc_koku",
    "sonuctan_durum",
    "tp_results_al",
    "tp_results_ayristir",
    "tp_results_sec",
    "tp_results_zip_ayristir",
    "triage_turu",
]
