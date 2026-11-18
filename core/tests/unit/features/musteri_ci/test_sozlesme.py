"""Müşteri CI sözleşmesi: hedefler, adlar, sonuç kökü, "kırarak doğrulanmadı" bilgisi."""

from __future__ import annotations

import pytest

from tp_core.features import musteri_ci as mci
from tp_core.features.ci import github_artifacts


def test_hedefler_kotlin_swift():
    assert mci.musteri_ci_mi("android", "kotlin")
    assert mci.musteri_ci_mi("ios", "swift")
    for p, d in (("web", "ts"), ("android", "java"), ("ios", "kotlin"), (None, None), ([], 1)):
        assert not mci.musteri_ci_mi(p, d)
    with pytest.raises(mci.MusteriCiHatasi):
        mci.hedef("android", "java")


def test_is_adi_check_adi_ve_is_akisi():
    a = mci.hedef("android", "kotlin")
    assert mci.is_adi("android", "kotlin") == "mobil-android-kotlin"
    assert a.is_akisi_yolu == ".github/workflows/mobil-android-kotlin.yml"
    assert mci.is_adi("ios", "swift") == "mobil-ios-swift"
    assert mci.hedef("ios", "swift").yardimcilar == ("xcresult_junit.py",)
    assert set(mci.is_adlari()) == {"mobil-android-kotlin", "mobil-ios-swift"}
    assert mci.hedef_is_adindan("mobil-ios-swift").dil == "swift"
    assert mci.hedef_is_adindan("mobil-ios") is None
    # İş akışı dosya adı = job adı (şablon iş adı = check adı).
    for h in mci.HEDEFLER.values():
        assert h.is_akisi == f"{h.is_adi}.yml"


def test_mevcut_github_checkleriyle_cakismaz():
    from tp_core.integrations.forge import GITHUB_PLATFORM_CHECKS, WEB_JAVA_CHECK

    mevcut = {*GITHUB_PLATFORM_CHECKS.values(), WEB_JAVA_CHECK, "test-local"}
    assert not mevcut & set(mci.is_adlari())


def test_sonuc_koku_ve_github_artifacts_ayni():
    for p, d in (("android", "kotlin"), ("ios", "swift")):
        assert mci.sonuc_koku(p, d) == f"src/{p}-{d}/results"
        assert github_artifacts.sonuc_koku(p, d) == mci.sonuc_koku(p, d)
        assert mci.hedef(p, d).sonuc_kok == mci.sonuc_koku(p, d)
    for kotu in (("../x", "kotlin"), ("android", "a/b"), ("Android", "kotlin"), ("", "x")):
        with pytest.raises(mci.MusteriCiHatasi):
            mci.sonuc_koku(*kotu)
        with pytest.raises(ValueError):
            github_artifacts.sonuc_koku(*kotu)
    assert github_artifacts.sonuc_koku() == github_artifacts.SONUC_KOK


def test_dogrulama_bilgisi_rozet():
    b = mci.dogrulama_bilgisi("ios", "swift")
    assert b["hat"] == "musteri_ci"
    assert b["kirarak_dogrulama"] is False
    assert b["check"] == "mobil-ios-swift"
    assert b["rozet"]["kod"] == "kirarak_dogrulanmadi"
    assert b["rozet"]["etiket"] == "Kırarak doğrulanmadı"
    b["rozet"]["etiket"] = "x"  # kopya döner: sabit bozulmaz
    assert mci.KIRARAK_DOGRULANMADI["etiket"] == "Kırarak doğrulanmadı"
    assert mci.dogrulama_bilgisi("web", "ts") is None


def test_pr_govdesi_notu():
    n = mci.pr_govdesi_notu("android", "kotlin")
    assert "Kırarak doğrulanmadı" in n
    assert "mobil-android-kotlin" in n
    assert ".github/workflows/mobil-android-kotlin.yml" in n
    assert mci.pr_govdesi_notu("web", "java") == ""


def test_s0_catilari_ile_uyum():
    """Ş0'ın `CATILAR` tablosu geldiğinde musteri_ci çiftleri ve iş akışı adları aynı olmalı."""
    from tp_core.features.codegen import platform as platformlar

    catilar = getattr(platformlar, "CATILAR", None)
    if catilar is None:
        pytest.skip("Ş0 CATILAR henüz yok (entegrasyonda koşar)")
    musteri = {k for k, c in catilar.items() if getattr(c, "hat", None) == mci.HAT}
    assert musteri == set(mci.HEDEFLER)
    for k in musteri:
        gh = getattr(catilar[k], "gh_is_akisi", None)
        if gh is not None:
            assert gh == mci.HEDEFLER[k].is_adi
