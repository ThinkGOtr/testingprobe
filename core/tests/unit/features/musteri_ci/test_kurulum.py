"""Tek seferlik, insan onaylı kurulum PR'ı ve CI şablonları."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from tp_core.features import musteri_ci as mci
from tp_core.features.musteri_ci import kurulum

ANDROID = mci.KurulumParametreleri("android", "kotlin", test_paketi="com.acme.bayi.tp")
IOS = mci.KurulumParametreleri(
    "ios",
    "swift",
    uygulama_koku="ios",
    xcode_proje="Bayi.xcworkspace",
    sema="Bayi",
    ui_test_hedefi="BayiUITests",
    runs_on="xcode-27",
)
SABLONLAR = Path(__file__).resolve().parents[5] / "rules" / "ci-sablonlari"

PBX_ESITLENMIS = """
		AAA /* BayiUITests */ = {
			isa = PBXNativeTarget;
			buildPhases = ( B1 /* Sources */, );
			fileSystemSynchronizedGroups = ( C1 /* BayiUITests */, );
			name = BayiUITests;
			productType = "com.apple.product-type.bundle.ui-testing";
		};
		BBB /* Bayi */ = {
			isa = PBXNativeTarget;
			name = Bayi;
			productType = "com.apple.product-type.application";
		};
"""
PBX_KLASIK = PBX_ESITLENMIS.replace("fileSystemSynchronizedGroups = ( C1 /* BayiUITests */, );", "")


def test_sablon_dosyalari_var():
    for h in mci.HEDEFLER.values():
        assert (SABLONLAR / h.sablon).is_file()
        for y in h.yardimcilar:
            assert (SABLONLAR / y).is_file()
        assert mci.sablon_metni(h.sablon) == (SABLONLAR / h.sablon).read_text(encoding="utf-8")
    with pytest.raises(mci.MusteriCiHatasi):
        mci.sablon_metni("../models.yaml")


@pytest.mark.parametrize("p", [ANDROID, IOS])
def test_sablon_isle_job_adi_check_adi(p):
    h = mci.hedef(p.platform, p.dil)
    metin = mci.sablon_isle(h, p)
    assert "__TP_" not in metin
    y = yaml.safe_load(metin)
    assert y["name"] == h.is_adi
    assert set(y["jobs"]) == {"changes", h.is_adi}
    job = y["jobs"][h.is_adi]
    assert job["name"] == h.is_adi
    adimlar = job["steps"]
    yukle = [a for a in adimlar if "upload-artifact" in str(a.get("uses", ""))]
    assert len(yukle) == 1
    assert yukle[0]["with"]["name"] == mci.TP_RESULTS_ARTIFACT
    assert yukle[0]["if"].startswith("always()")
    topla = next(a for a in adimlar if a.get("name") == "tp-results topla")
    assert topla["if"].startswith("always()")
    assert "ci-meta.json" in topla["run"]
    # Tüm aksiyonlar SHA ile sabitlenmiş.
    for j in y["jobs"].values():
        for a in j["steps"]:
            if "uses" in a:
                assert len(a["uses"].split("@", 1)[1]) == 40, a["uses"]
    assert y["permissions"] == {"contents": "read"}


def test_android_sablon_degerleri():
    y = yaml.safe_load(mci.sablon_isle(mci.hedef("android", "kotlin"), ANDROID))
    assert y["env"]["TP_TEST_PAKETI"] == "com.acme.bayi.tp"
    assert y[True]["push"]["branches"] == ["main"]  # YAML 1.1: `on` → True
    emu = next(
        a
        for a in y["jobs"]["mobil-android-kotlin"]["steps"]
        if "emulator-runner" in str(a.get("uses"))
    )
    assert emu["with"]["api-level"] == 34
    filtre = y["jobs"]["changes"]["steps"][0]["with"]["filters"]
    assert "'**'" in filtre


def test_ios_sablon_degerleri():
    y = yaml.safe_load(mci.sablon_isle(mci.hedef("ios", "swift"), IOS))
    job = y["jobs"]["mobil-ios-swift"]
    assert job["runs-on"] == "xcode-27"
    assert y["env"]["TP_XCODE_BAYRAGI"] == "-workspace"
    assert y["env"]["TP_UI_TEST_HEDEFI"] == "BayiUITests"
    kos = next(a for a in job["steps"] if a.get("id") == "kos")
    assert "-only-testing" in kos["run"] and kos["working-directory"] == "ios"
    assert "'ios/**'" in y["jobs"]["changes"]["steps"][0]["with"]["filters"]
    y2 = yaml.safe_load(
        mci.sablon_isle(mci.hedef("ios", "swift"), replace(IOS, xcode_proje="Bayi.xcodeproj"))
    )
    assert y2["env"]["TP_XCODE_BAYRAGI"] == "-project"


@pytest.mark.parametrize(
    "degisim",
    [
        {"test_paketi": ""},
        {"test_paketi": "com.acme; rm -rf /"},
        {"varsayilan_dal": "main\n  evil: 1"},
        {"varsayilan_dal": "a/../b"},
        {"uygulama_koku": "../disari"},
        {"uygulama_koku": "/mutlak"},
        {"gradle_modulu": "app:x"},
        {"emulator_api": 99},
    ],
)
def test_android_parametre_enjeksiyonu_reddedilir(degisim):
    p = replace(ANDROID, **degisim)
    assert kurulum.parametre_hatalari(p)
    with pytest.raises(mci.MusteriCiHatasi):
        mci.sablon_isle(mci.hedef("android", "kotlin"), p)


@pytest.mark.parametrize(
    "degisim",
    [
        {"xcode_proje": "Bayi"},
        {"xcode_proje": "../x.xcodeproj"},
        {"sema": 'a"; echo'},
        {"sema": "$(id)"},
        {"ui_test_hedefi": ""},
        {"runs_on": "macos 15"},
        {"simulator": "iPhone`x`"},
    ],
)
def test_ios_parametre_enjeksiyonu_reddedilir(degisim):
    assert kurulum.parametre_hatalari(replace(IOS, **degisim))


def test_hedef_parametre_uyusmazligi():
    with pytest.raises(mci.MusteriCiHatasi):
        mci.sablon_isle(mci.hedef("ios", "swift"), ANDROID)


def test_ui_test_hedefi_durumu():
    assert kurulum.ui_test_hedefi_durumu(PBX_ESITLENMIS, "BayiUITests") == "esitlenmis"
    assert kurulum.ui_test_hedefi_durumu(PBX_KLASIK, "BayiUITests") == "klasik"
    assert kurulum.ui_test_hedefi_durumu(PBX_ESITLENMIS, "Bayi") == "yok"  # uygulama hedefi
    assert kurulum.ui_test_hedefi_durumu("", "BayiUITests") == "yok"


def test_android_plan_bos_depo():
    iskelet = {"app/src/androidTest/java/com/acme/bayi/tp/Ekran.kt": "class Ekran"}
    plan = mci.kurulum_plani(ANDROID, ["gradlew", "app/build.gradle.kts"], iskelet=iskelet)
    assert plan.hazir and plan.gerekli
    assert set(plan.dosyalar) == {".github/workflows/mobil-android-kotlin.yml", *iskelet}
    assert plan.dal == "tp/kurulum-android-kotlin"
    assert any("zorunlu" in a for a in plan.elle_adimlar)
    assert "mobil-android-kotlin" in plan.govde and "Kırarak doğrulanmadı" in plan.govde
    assert "Elle yapılacak adımlar" in plan.govde


def test_android_plan_gradlew_yok_elle_adim():
    plan = mci.kurulum_plani(ANDROID, [])
    kodlar = {e.kod for e in plan.eksikler}
    assert "gradle_projesi" in kodlar
    assert any("gradlew" in a for a in plan.elle_adimlar)


def test_kurulu_depo_gereksiz():
    dosyalar = ["gradlew", ".github/workflows/mobil-android-kotlin.yml", "a/Ekran.kt"]
    plan = mci.kurulum_plani(ANDROID, dosyalar, iskelet={"a/Ekran.kt": "x"})
    assert plan.dosyalar == {} and plan.elle_adimlar == () and not plan.gerekli


def test_ios_plan_hedef_durumlari():
    depo = ["ios/Bayi.xcodeproj/project.pbxproj", "ios/Pods/Pods.xcodeproj/project.pbxproj"]
    okunan: list[str] = []

    def oku(metin):
        def _oku(y):
            okunan.append(y)
            return metin

        return _oku

    plan = mci.kurulum_plani(IOS, depo, oku=oku(PBX_ESITLENMIS))
    assert okunan == ["ios/Bayi.xcodeproj/project.pbxproj"]
    assert set(plan.dosyalar) == {
        ".github/workflows/mobil-ios-swift.yml",
        ".github/tp/xcresult_junit.py",
    }
    assert plan.dosyalar[".github/tp/xcresult_junit.py"] == (
        SABLONLAR / "xcresult_junit.py"
    ).read_text(encoding="utf-8")
    assert not any(e.kod in ("ui_test_hedefi", "esitlenmis_klasor") for e in plan.eksikler)
    plan = mci.kurulum_plani(IOS, depo, oku=oku(PBX_KLASIK))
    assert any(e.kod == "esitlenmis_klasor" and not e.otomatik for e in plan.eksikler)
    plan = mci.kurulum_plani(IOS, depo, oku=oku("yok"))
    e = next(e for e in plan.eksikler if e.kod == "ui_test_hedefi")
    assert not e.otomatik and "pbxproj" in e.aciklama
    # TP pbxproj'a asla yazmaz.
    assert not any(y.endswith("project.pbxproj") for y in plan.dosyalar)
    plan = mci.kurulum_plani(IOS, [])
    assert any(e.kod == "xcode_projesi" for e in plan.eksikler)


def test_parametre_eksik_plan_hazir_degil():
    plan = mci.kurulum_plani(replace(ANDROID, test_paketi=""), ["gradlew"])
    assert not plan.hazir and plan.dosyalar == {}
    with pytest.raises(mci.MusteriCiHatasi):
        mci.kurulum_pr_ac(SahteForge(), plan, onaylayan="po@acme")


@dataclass
class _Pr:
    number: int
    url: str = "https://github.com/acme/app/pull/1"
    head_sha: str = "c" * 40


@dataclass
class SahteForge:
    base_branch: str = "main"
    acik: _Pr | None = None
    cagrilar: list[tuple[str, Any]] = field(default_factory=list)

    def find_open_pr(self, dal):
        self.cagrilar.append(("find_open_pr", dal))
        return self.acik

    def commit_files(self, dal, dosyalar, mesaj, base="main"):
        self.cagrilar.append(("commit_files", (dal, sorted(dosyalar), base)))
        return "d" * 40

    def open_pr(self, dal, baslik, govde, labels=()):
        self.cagrilar.append(("open_pr", (dal, baslik, govde, tuple(labels))))
        return _Pr(number=7)


def test_kurulum_pr_onaysiz_acilmaz():
    plan = mci.kurulum_plani(ANDROID, ["gradlew"])
    f = SahteForge()
    for onay in (None, "", "   "):
        with pytest.raises(mci.KurulumOnayiYok):
            mci.kurulum_pr_ac(f, plan, onaylayan=onay)
    assert f.cagrilar == []


def test_kurulum_pr_acilir():
    plan = mci.kurulum_plani(ANDROID, ["gradlew"])
    f = SahteForge(base_branch="develop")
    r = mci.kurulum_pr_ac(f, plan, onaylayan="po@acme")
    assert r["durum"] == "acildi" and r["pr_no"] == 7 and r["sha"] == "d" * 40
    assert r["onaylayan"] == "po@acme"
    adlar = [c[0] for c in f.cagrilar]
    assert adlar == ["find_open_pr", "commit_files", "open_pr"]
    assert f.cagrilar[1][1] == (
        "tp/kurulum-android-kotlin",
        [".github/workflows/mobil-android-kotlin.yml"],
        "develop",
    )
    _dal, _baslik, govde, etiketler = f.cagrilar[2][1]
    assert "Onaylayan: po@acme" in govde and etiketler == (mci.KURULUM_ETIKETI,)


def test_kurulum_pr_tek_seferlik_mevcut():
    plan = mci.kurulum_plani(ANDROID, ["gradlew"])
    f = SahteForge(acik=_Pr(number=3))
    r = mci.kurulum_pr_ac(f, plan, onaylayan="po@acme")
    assert r["durum"] == "mevcut" and r["pr_no"] == 3
    assert [c[0] for c in f.cagrilar] == ["find_open_pr"]


def test_kurulum_gereksiz_forgea_dokunmaz():
    plan = mci.kurulum_plani(ANDROID, ["gradlew", ".github/workflows/mobil-android-kotlin.yml"])
    f = SahteForge()
    assert mci.kurulum_pr_ac(f, plan, onaylayan="po@acme")["durum"] == "gereksiz"
    assert f.cagrilar == []


# ------------------------------------------------- hazırlık betiği (Expo/RN; kabul 2026-11-18)

EXPO_ANDROID = replace(
    ANDROID,
    uygulama_koku="mobil/android",
    hazirlik_betigi=".github/tp/hazirlik.sh",
    node_surumu="22",
    izlenen_kok="mobil",
)


def _adim(job: dict[str, Any], ad_onek: str) -> dict[str, Any]:
    return next(a for a in job["steps"] if str(a.get("name", "")).startswith(ad_onek))


@pytest.mark.parametrize(
    "p",
    [
        EXPO_ANDROID,
        replace(IOS, hazirlik_betigi=".github/tp/h.sh", node_surumu="22", yapilandirma="Release"),
    ],
)
def test_hazirlik_betigi_sablonda(p):
    h = mci.hedef(p.platform, p.dil)
    y = yaml.safe_load(mci.sablon_isle(h, p))
    assert y["env"]["TP_HAZIRLIK_BETIGI"] == p.hazirlik_betigi
    assert y["env"]["TP_NODE_SURUMU"] == "22"
    job = y["jobs"][h.is_adi]
    adlar = [a.get("name") for a in job["steps"]]
    hz = adlar.index("Hazırlık (müşterinin betiği; isteğe bağlı)")
    sonraki = "Derle (uygulama + androidTest APK)" if p.platform == "android" else "Simülatör"
    assert adlar.index("Node (hazırlık betiği için; isteğe bağlı)") < hz < adlar.index(sonraki)
    assert "TP_HAZIRLIK_BETIGI != ''" in _adim(job, "Hazırlık")["if"]
    filtre = y["jobs"]["changes"]["steps"][0]["with"]["filters"]
    assert "'.github/tp/**'" in filtre


def test_hazirlik_betigi_bos_adim_atlanir():
    y = yaml.safe_load(mci.sablon_isle(mci.hedef("android", "kotlin"), ANDROID))
    assert y["env"]["TP_HAZIRLIK_BETIGI"] == "" and y["env"]["TP_NODE_SURUMU"] == ""


def test_izlenen_kok_uretilen_projeden_bagimsiz():
    y = yaml.safe_load(mci.sablon_isle(mci.hedef("android", "kotlin"), EXPO_ANDROID))
    filtre = y["jobs"]["changes"]["steps"][0]["with"]["filters"]
    # Üretilen android/ depoda yok: PR'daki test değişikliği kaynak kökünden yakalanmalı.
    assert "'mobil/**'" in filtre and "mobil/android/**" not in filtre


def test_ios_yapilandirma():
    y = yaml.safe_load(
        mci.sablon_isle(mci.hedef("ios", "swift"), replace(IOS, yapilandirma="Release"))
    )
    assert y["env"]["TP_YAPILANDIRMA"] == "Release"
    kos = next(a for a in y["jobs"]["mobil-ios-swift"]["steps"] if a.get("id") == "kos")
    assert "-configuration" in kos["run"]


def test_hazirlik_plan_yerel_proje_aranmaz():
    plan = mci.kurulum_plani(EXPO_ANDROID, [])
    kodlar = {e.kod for e in plan.eksikler}
    assert "gradle_projesi" not in kodlar and "hazirlik_betigi" in kodlar
    plan = mci.kurulum_plani(EXPO_ANDROID, [".github/tp/hazirlik.sh"])
    assert {e.kod for e in plan.eksikler} == {"is_akisi"}
    ios = replace(IOS, hazirlik_betigi=".github/tp/h.sh")
    kodlar = {e.kod for e in mci.kurulum_plani(ios, [".github/tp/h.sh"]).eksikler}
    assert not kodlar & {"xcode_projesi", "ui_test_hedefi", "esitlenmis_klasor"}


@pytest.mark.parametrize(
    "degisim",
    [
        {"hazirlik_betigi": "../x.sh"},
        {"hazirlik_betigi": "/abs/x.sh"},
        {"hazirlik_betigi": "a b.sh"},
        {"hazirlik_betigi": "x.py"},
        {"hazirlik_betigi": "./x.sh"},
        {"hazirlik_betigi": 'x.sh"\n  evil: 1'},
        {"node_surumu": "22; id"},
        {"izlenen_kok": "../x"},
        {"yapilandirma": "$(id)"},
    ],
)
def test_hazirlik_parametre_enjeksiyonu_reddedilir(degisim):
    temel = IOS if "yapilandirma" in degisim else ANDROID
    assert kurulum.parametre_hatalari(replace(temel, **degisim))
