"""tp-results alımı: zip/yerel kopya ayrıştırma, Gradle/xcresult yolları, derleme kesiti."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.features.musteri_ci.yardimci import (
    JUNIT_GECEN,
    JUNIT_KIRMIZI,
    SHA,
    SahteGh,
    meta,
    tp_results_gh,
    zip_yap,
)
from tp_core.features import musteri_ci as mci
from tp_core.features.ci import github_artifacts, parse, services
from tp_core.features.ci.parse import TestSatiri as Satir

GRADLE = "app/build/outputs/androidTest-results/connected"


# ------------------------------------------------------------------ parse.py yol yardımcıları


def test_gradle_yolu():
    assert parse.gradle_rapor_dizini() == GRADLE
    assert parse.gradle_rapor_dizini("uygulama") == (
        "uygulama/build/outputs/androidTest-results/connected"
    )
    assert parse.gradle_androidtest_yolu_mu(f"{GRADLE}/TEST-Pixel-app-.xml")
    assert parse.gradle_androidtest_yolu_mu(f"{GRADLE}/debug/emu/TEST-x.xml")
    assert parse.gradle_androidtest_yolu_mu("androidTest-results/connected/TEST-x.xml")
    assert not parse.gradle_androidtest_yolu_mu(f"{GRADLE}/rapor.xml")
    assert not parse.gradle_androidtest_yolu_mu("app/build/test-results/TEST-x.xml")
    assert not parse.gradle_androidtest_yolu_mu(f"../{GRADLE}/TEST-x.xml")
    assert not parse.gradle_androidtest_yolu_mu(f"/{GRADLE}/TEST-x.xml")


def test_xcresult_yollari():
    assert parse.xcresult_junit_yolu_mu("junit/xcresult-junit.xml")
    assert not parse.xcresult_junit_yolu_mu("junit/baska.xml")
    assert parse.xcresult_paketi_mi("TestResults.xcresult/Info.plist")
    assert not parse.xcresult_paketi_mi("junit/xcresult-junit.xml")


def test_musteri_ci_junit_yolu():
    assert parse.musteri_ci_junit_yolu_mu("junit/TEST-a.xml")
    assert parse.musteri_ci_junit_yolu_mu(f"{GRADLE}/TEST-a.xml")
    assert parse.musteri_ci_junit_yolu_mu("xcresult-junit.xml")
    assert not parse.musteri_ci_junit_yolu_mu("TestResults.xcresult/junit/a.xml")
    assert not parse.musteri_ci_junit_yolu_mu("junit/a.json")
    assert not parse.musteri_ci_junit_yolu_mu("ekler/a.xml")
    assert not parse.musteri_ci_junit_yolu_mu("junit/../a.xml")
    assert not parse.musteri_ci_junit_yolu_mu("")


# ------------------------------------------------------------------ ayrıştırma


def test_android_gecen_ve_gradle_kopyasi_tekillesir():
    z = zip_yap(
        {
            "ci-meta.json": meta(),
            "junit/TEST-emu.xml": JUNIT_GECEN,
            f"{GRADLE}/TEST-emu.xml": JUNIT_GECEN,  # aynı raporun özgün kopyası
            "ekler/emu/ekran.png": b"\x89PNG",
            "derleme.log": b"BUILD SUCCESSFUL in 1m\n",
        }
    )
    s = mci.tp_results_zip_ayristir(z, "android", "kotlin", beklenen_sha=SHA)
    assert s.junit_dosyalari == ["junit/TEST-emu.xml"]
    assert s.sayac == {"toplam": 2, "gecen": 2, "basarisiz": 0, "flaky": 0, "atlanan": 0}
    assert s.meta["sha"] == SHA and s.meta["platform"] == "android"
    assert s.ekler == ["ekler/emu/ekran.png"]
    assert s.uyarilar == []
    assert mci.sonuctan_durum("success", s.sayac) == mci.HatDurumu.YESIL


def test_yalniz_gradle_ozgun_yolu_kabul():
    s = mci.tp_results_ayristir(
        {"ci-meta.json": meta(), f"{GRADLE}/TEST-emu.xml": JUNIT_KIRMIZI}, "android", "kotlin"
    )
    assert s.sayac["basarisiz"] == 1
    t = s.ayristirma.testler[0]
    assert t.sonuc == "failed" and "NoMatchingViewException" in t.hata_mesaji


def test_junit_yok_derleme_hatasi_kesiti():
    log = (
        b"2026-11-18T10:00:00.1234567Z > Task :app:compileDebugAndroidTestKotlin FAILED\n"
        b"e: file:///w/app/src/androidTest/GirisTest.kt:12:5 Unresolved reference: girisYap\n"
        b"\n"
        b"FAILURE: Build failed with an exception.\n"
        b"* What went wrong:\n"
        b"Execution failed for task ':app:compileDebugAndroidTestKotlin'.\n"
    )
    s = mci.tp_results_zip_ayristir(
        zip_yap({"ci-meta.json": meta(durum="derleme_hatasi"), "derleme.log": log}),
        "android",
        "kotlin",
    )
    assert s.ayristirma is None and s.sayac is None
    assert "tp-results içinde JUnit raporu yok." in s.uyarilar
    assert "Unresolved reference: girisYap" in s.derleme_kesiti
    assert "FAILURE: Build failed" in s.derleme_kesiti
    assert "2026-11-18T" not in s.derleme_kesiti
    assert mci.sonuctan_durum("failure", s.sayac) == mci.HatDurumu.DERLEME_HATASI


def test_meta_uyumsuzlugu_uyari():
    s = mci.tp_results_ayristir(
        {
            "ci-meta.json": meta(platform="ios", dil="swift", sha="b" * 40),
            "junit/a.xml": JUNIT_GECEN,
        },
        "android",
        "kotlin",
        beklenen_sha=SHA,
    )
    u = " ".join(s.uyarilar)
    assert "platform='ios'" in u and "dil='swift'" in u and "başka commit" in u


def test_meta_yok_ya_da_bozuk():
    s = mci.tp_results_ayristir({"junit/a.xml": JUNIT_GECEN}, "android", "kotlin")
    assert "ci-meta.json yok." in s.uyarilar
    s = mci.tp_results_ayristir(
        {"ci-meta.json": b"[1]", "junit/a.xml": JUNIT_GECEN}, "android", "kotlin"
    )
    assert "ci-meta.json nesne değil." in s.uyarilar
    s = mci.tp_results_ayristir(
        {"ci-meta.json": b"{", "junit/a.xml": JUNIT_GECEN}, "android", "kotlin"
    )
    assert "ci-meta.json okunamadı." in s.uyarilar


def test_guvensiz_junit_uyari_olur():
    dtd = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><testsuite/>'
    s = mci.tp_results_ayristir(
        {"ci-meta.json": meta(), "junit/kotu.xml": dtd, "junit/iyi.xml": JUNIT_GECEN},
        "android",
        "kotlin",
    )
    assert s.junit_dosyalari == ["junit/iyi.xml"]
    assert any("DTD" in u for u in s.uyarilar)
    s = mci.tp_results_ayristir({"junit/kotu.xml": b"<bozuk"}, "android", "kotlin")
    assert s.ayristirma is None
    assert any("ayrıştırılamadı" in u for u in s.uyarilar)


def test_zip_slip_yollari_yok_sayilir():
    z = zip_yap(
        {"../junit/x.xml": JUNIT_KIRMIZI, "junit/a.xml": JUNIT_GECEN, "ci-meta.json": meta()}
    )
    s = mci.tp_results_zip_ayristir(z, "android", "kotlin")
    assert s.junit_dosyalari == ["junit/a.xml"]
    assert s.sayac["basarisiz"] == 0


def test_bozuk_zip():
    with pytest.raises(parse.RaporHatasi):
        mci.tp_results_zip_ayristir(b"zip degil", "android", "kotlin")


def test_kimlik_donusturucu_ve_hatasi():
    def kimlik(t: Satir) -> Satir:
        if "Sepet" in (t.dosya or ""):
            raise ValueError("bilinmeyen sınıf")
        sinif = (t.dosya or "").rsplit(".", 1)[-1]
        return Satir(
            **{**t.__dict__, "dosya": f"uretilen/{sinif}.kt", "test_adi": f"{sinif} › {t.test_adi}"}
        )

    s = mci.tp_results_ayristir({"junit/a.xml": JUNIT_GECEN}, "android", "kotlin", kimlik=kimlik)
    adlar = {(t.dosya, t.test_adi) for t in s.ayristirma.testler}
    assert ("uretilen/GirisTest.kt", "GirisTest › senaryo") in adlar
    assert ("com.acme.tp.uretilen.SepetTest", "senaryo") in adlar  # dönüşmeyen olduğu gibi
    assert any("dönüştürülemedi" in u for u in s.uyarilar)


def test_musteri_ci_olmayan_cift_reddedilir():
    with pytest.raises(mci.MusteriCiHatasi):
        mci.tp_results_ayristir({}, "web", "ts")


def test_derleme_kesiti_swift_ve_son_satirlar():
    log = (
        "Build settings...\n"
        "/w/UITests/GirisTests.swift:14:9: error: cannot find 'ekran' in scope\n"
        "** TEST FAILED **\n"
    )
    k = mci.derleme_kesiti(log, "swift")
    assert "cannot find 'ekran'" in k and "** TEST FAILED **" in k
    k = mci.derleme_kesiti("\n".join(f"satir {i}" for i in range(100)), "kotlin", en_cok_satir=5)
    assert k.splitlines() == [f"satir {i}" for i in range(95, 100)]
    assert mci.derleme_kesiti(None, "kotlin") is None
    assert mci.derleme_kesiti(b"\x1b[31m\n", "kotlin") is None


# ------------------------------------------------------------------ indirme + yerel kopya


@pytest.fixture
def gh_kok(tmp_path: Path):
    services._overrides["github_artifacts_root"] = lambda: tmp_path
    yield tmp_path
    services._overrides.pop("github_artifacts_root", None)


def test_tp_results_sec():
    arts = [
        {"id": 1, "name": "tp-results", "expired": True},
        {"id": 2, "name": "baska"},
        {"id": 3, "name": "tp-results"},
    ]
    assert mci.tp_results_sec(arts)["id"] == 3
    assert mci.tp_results_sec(arts[:2]) is None


def test_tp_results_al_yerel_kopya(gh_kok: Path):
    gh = tp_results_gh(
        {"ci-meta.json": meta(), "junit/TEST-a.xml": JUNIT_GECEN, "ekler/a.png": b"x"}
    )
    s = mci.tp_results_al(gh, {"id": 99, "head_sha": SHA, "run_attempt": 2}, "android", "kotlin")
    assert s.sayac["gecen"] == 2
    assert gh.indirilen == [11]  # yerel kopya için ikinci indirme yok
    assert s.yerel["durum"] == "indirildi" and s.yerel["dizin"] == "gh/99-2"
    kok = "src/android-kotlin/results"
    assert s.yerel["yollar"]["meta"] == f"{kok}/ci-meta.json"
    assert s.yerel["yollar"]["junit_dizini"] == f"{kok}/junit"
    assert s.yerel["yollar"]["ekler"] == f"{kok}/ekler"
    assert (gh_kok / "gh/99-2" / kok / "junit/TEST-a.xml").read_bytes() == JUNIT_GECEN
    # ikinci alım: mevcut kopya
    s2 = mci.tp_results_al(gh, {"id": 99, "head_sha": SHA, "run_attempt": 2}, "android", "kotlin")
    assert s2.yerel["durum"] == "mevcut"
    assert github_artifacts.disk_dosyalari(
        gh_kok / "gh/99-2", ("ci-meta.json",), sonuc_kok=kok
    ) == {"ci-meta.json": meta()}


def test_tp_results_al_artefakt_yok_ve_hata(gh_kok: Path):
    s = mci.tp_results_al(SahteGh(), {"id": 5}, "ios", "swift")
    assert s.ayristirma is None and "'tp-results' artefaktı yok" in s.uyarilar[0]
    s = mci.tp_results_al(SahteGh(hata=RuntimeError("401")), {"id": 5}, "ios", "swift")
    assert "artefakt listesi alınamadı" in s.uyarilar[0]
    gh = SahteGh(artefaktlar=[{"id": 4, "name": "tp-results"}], zipler={4: b"bozuk"})
    s = mci.tp_results_al(gh, {"id": 5}, "ios", "swift")
    assert "okunamadı" in s.uyarilar[0]


def test_tp_results_al_yerel_kopyasiz(gh_kok: Path):
    gh = tp_results_gh({"junit/xcresult-junit.xml": JUNIT_GECEN})
    s = mci.tp_results_al(gh, {"id": 8}, "ios", "swift", yerel_kopya=False)
    assert s.yerel is None and s.sayac["toplam"] == 2
    assert not (gh_kok / "gh").exists()
