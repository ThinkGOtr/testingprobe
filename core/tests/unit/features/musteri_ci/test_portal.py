"""Ş7 portal alan şekilleri."""

from __future__ import annotations

from dataclasses import dataclass, replace

from tests.unit.features.musteri_ci.yardimci import JUNIT_KIRMIZI, SHA, meta
from tp_core.features import musteri_ci as mci

D = mci.HatDurumu
ANDROID = mci.KurulumParametreleri("android", "kotlin", test_paketi="com.acme.tp")
ALANLAR = {"check_adi", "durum", "head_sha", "run_url", "tamamlanma", "sonuc", "artefakt", "neden"}


def _g(durum, check=None, sonuc=None):
    return mci.HatGuncellemesi(
        durum=durum,
        check=check,
        sonuc=sonuc,
        merge=mci.merge_kapisi(durum),
        dogrulama=mci.dogrulama_bilgisi("android", "kotlin"),
    )


def test_hat_ve_merge_kabul():
    assert mci.hat_adi("ios", "swift") == "musteri_ci"
    assert mci.hat_adi("web", "ts") is None
    assert mci.merge_kabul_gerekli("android", "kotlin") == []
    assert mci.merge_kabul_gerekli("web", "java") is None


def test_portal_durumu_tum_durumlar():
    assert set(mci.PORTAL_DURUMU) == set(D)
    assert set(mci.PORTAL_DURUMU.values()) <= {
        "bekliyor",
        "kosuyor",
        "gecti",
        "kaldi",
        "derleme_hatasi",
    }


def test_bekliyor():
    p = mci.portal_musteri_ci(_g(D.CI_BEKLENIYOR), SHA)
    assert set(p) >= ALANLAR
    assert p["durum"] == "bekliyor" and p["artefakt"] == "bekliyor"
    assert p["check_adi"] == "mobil-android-kotlin" and p["head_sha"] == SHA
    assert p["sonuc"] is None and p["neden"] is None


def test_kaldi_sonuclu():
    s = mci.tp_results_ayristir(
        {"ci-meta.json": meta(), "junit/a.xml": JUNIT_KIRMIZI}, "android", "kotlin"
    )
    c = {
        "ad": "mobil-android-kotlin",
        "status": "completed",
        "conclusion": "failure",
        "url": "https://x/run",
        "completed_at": "2026-11-18T10:00:00Z",
    }
    p = mci.portal_musteri_ci(_g(D.KIRMIZI, c, s))
    assert p["durum"] == "kaldi" and p["artefakt"] == "alindi"
    assert p["sonuc"] == {"toplam": 1, "gecen": 0, "kalan": 1, "atlanan": 0}
    assert p["run_url"] == "https://x/run" and p["tamamlanma"] == "2026-11-18T10:00:00Z"
    assert p["head_sha"] == SHA and p["neden"] == "Test başarısız"


def test_sonuc_yok_artefakt_yok():
    c = {"ad": "mobil-android-kotlin", "status": "completed", "conclusion": "success"}
    p = mci.portal_musteri_ci(_g(D.SONUC_YOK, c, None))
    assert p["durum"] == "kaldi" and p["artefakt"] == "yok" and p["neden"] == "Sonuç artefaktı yok"


@dataclass
class _Pr:
    number: int
    state: str
    url: str = "https://github.com/acme/app/pull/4"
    title: str = "TP kurulumu"


def test_portal_kurulum():
    plan = mci.kurulum_plani(ANDROID, ["gradlew"])
    k = mci.portal_kurulum(plan)
    assert k["durum"] == "gerekli" and k["number"] is None
    assert k["eksikler"] and k["elle_adimlar"]
    for state, beklenen in (("open", "acik"), ("merged", "birlesti"), ("closed", "kapali")):
        k = mci.portal_kurulum(plan, _Pr(4, state))
        assert k["durum"] == beklenen and k["number"] == 4 and k["baslik"] == "TP kurulumu"
    k = mci.portal_kurulum(plan, {"durum": "acildi", "pr_no": 9, "url": "u"})
    assert k["durum"] == "acik" and k["number"] == 9 and k["baslik"] == plan.baslik
    kurulu = mci.kurulum_plani(ANDROID, ["gradlew", ".github/workflows/mobil-android-kotlin.yml"])
    assert mci.portal_kurulum(kurulu) is None
    assert mci.portal_kurulum(replace(kurulu)) is None
