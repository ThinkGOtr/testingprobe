"""Müşteri CI hat durum akışı."""

from __future__ import annotations

import itertools

import pytest

from tp_core.features import musteri_ci as mci

D = mci.HatDurumu


def test_mutlu_yol_gecisleri():
    yol = [D.URETILDI, D.PR_ACILDI, D.CI_BEKLENIYOR, D.CI_KOSUYOR, D.YESIL]
    for a, b in itertools.pairwise(yol):
        assert mci.gecis(a, b) == b
    # yeni commit: son durumdan yeniden bekleme
    assert mci.gecis(D.KIRMIZI, D.CI_BEKLENIYOR) == D.CI_BEKLENIYOR
    assert mci.gecis("derleme_hatasi", "ci_kosuyor") == D.CI_KOSUYOR
    assert mci.gecis(D.KURULUM_GEREKLI, D.URETILDI) == D.URETILDI
    assert mci.gecis(D.YESIL, D.YESIL) == D.YESIL  # idempotent


def test_gecersiz_gecisler():
    for a, b in (
        (D.URETILDI, D.YESIL),
        (D.IPTAL, D.CI_BEKLENIYOR),
        (D.KURULUM_GEREKLI, D.PR_ACILDI),
    ):
        assert not mci.gecis_var_mi(a, b)
        with pytest.raises(mci.GecersizGecis):
            mci.gecis(a, b)
    with pytest.raises(mci.GecersizGecis):
        mci.gecis("yok", D.YESIL)
    assert not mci.gecis_var_mi("yok", "yesil")


def test_her_durumun_gecis_ve_etiketi_var():
    assert set(mci.GECISLER) == set(D)
    assert set(mci.ETIKETLER) == set(D)
    for d in D:
        if d != D.IPTAL:
            assert D.IPTAL in mci.GECISLER[d]


@pytest.mark.parametrize(
    ("status", "conclusion", "beklenen"),
    [
        ("queued", None, D.CI_BEKLENIYOR),
        ("in_progress", None, D.CI_KOSUYOR),
        ("completed", "success", D.SONUC_YOK),
        ("completed", "failure", D.DERLEME_HATASI),
        ("completed", "timed_out", D.DERLEME_HATASI),
        ("completed", "cancelled", D.CI_BEKLENIYOR),
        ("completed", "skipped", D.CI_BEKLENIYOR),
    ],
)
def test_check_durumu(status, conclusion, beklenen):
    assert mci.check_durumu(status, conclusion) == beklenen


def _s(toplam=0, gecen=0, basarisiz=0, flaky=0, atlanan=0):
    return {
        "toplam": toplam,
        "gecen": gecen,
        "basarisiz": basarisiz,
        "flaky": flaky,
        "atlanan": atlanan,
    }


@pytest.mark.parametrize(
    ("conclusion", "sayac", "beklenen"),
    [
        ("success", _s(2, 2), D.YESIL),
        ("success", _s(2, 1, flaky=1), D.YESIL),
        ("failure", _s(2, 1, 1), D.KIRMIZI),
        ("success", _s(2, 1, 1), D.KIRMIZI),  # check yeşil ama test kırmızı: kırmızı
        ("failure", None, D.DERLEME_HATASI),
        ("failure", _s(), D.DERLEME_HATASI),
        ("success", None, D.SONUC_YOK),  # yanlış-yeşil koruması
        ("success", _s(1, 0, atlanan=1), D.SONUC_YOK),  # hepsi atlandı: kanıt yok
        ("failure", _s(2, 2), D.DERLEME_HATASI),  # testler yeşil, iş kırmızı
        ("cancelled", None, D.CI_BEKLENIYOR),
        ("cancelled", _s(1, 0, 1), D.KIRMIZI),
    ],
)
def test_sonuctan_durum(conclusion, sayac, beklenen):
    assert mci.sonuctan_durum(conclusion, sayac) == beklenen


def test_merge_kapisi_yalniz_yesil():
    gecer, neden = mci.merge_kapisi(D.YESIL)
    assert gecer and "kırarak doğrulanmadı" in neden
    for d in D:
        if d != D.YESIL:
            assert mci.merge_kapisi(d)[0] is False
    assert mci.merge_kapisi("bilinmeyen") == (False, "bilinmeyen hat durumu")


def test_triage_turu():
    assert mci.triage_turu(D.DERLEME_HATASI) == "derleme"
    assert mci.triage_turu("kirmizi") == "test"
    assert mci.triage_turu(D.SONUC_YOK) == "sonuc_yok"
    assert mci.triage_turu(D.YESIL) is None
    assert mci.triage_turu("bilinmeyen") is None
