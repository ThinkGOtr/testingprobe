"""014 test dilleri entegrasyonu: şerit eklentilerinin Ş0 kancalarına bağlandığını doğrular.

- C# çekirdek / triage eklentisi keşifte (`EKLENTI`), çatısı `CATILAR` satırıyla aynı;
- CI raporunda C# / Python test kimliği test-runner özetinin biçimine çevrilir;
- eşleme denetimi C# fikstür adlarını (sınıf adı) kabul eder;
- müşteri CI dil kancaları (Kotlin kimlik dönüşümü, Swift kurulum iskeleti);
- script yanıtının `musteri_ci` özeti yalnız müşteri CI çiftinde hesaplanır.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from tp_core.features.ci import parse
from tp_core.features.codegen import diller
from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen.diller import csharp
from tp_core.features.musteri_ci import dil_kancalari
from tp_core.features.musteri_ci.kurulum import KurulumParametreleri
from tp_core.features.triage import diller as triage_diller

RULES = Path(__file__).resolve().parents[4] / "rules"
CID = uuid.UUID("3f9b1c2e-0000-4000-8000-000000000000")


def test_eklentiler_kayitli_ve_hatasiz() -> None:
    assert set(diller.adlar()) == {"ts", "java", "python", "csharp", "kotlin", "swift"}
    assert diller.hatalar() == {}
    assert {"python", "csharp", "kotlin", "swift"} <= set(triage_diller.kayit())
    assert triage_diller.hatalar() == {}


def test_csharp_catisi_catilar_ile_ayni() -> None:
    for p in ("web", "windows"):
        c = platformlar.CATILAR[(p, "csharp")]
        assert c == csharp.cati(p)
        assert platformlar.etkin_hat(p, "csharp") == "tam"
    e = diller.eklenti("csharp")
    assert e is not None
    yol = e.uretilen_yol(platformlar.CATILAR[("web", "csharp")], "", "TPD-1", 2, CID)
    assert yol == "e2e-csharp/Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    assert e.eslemeyi_donustur({"a": 1}) == {"a": 1}


def test_csharp_triage_eklentisi_uretilen_kimligi() -> None:
    e = triage_diller.eklenti("csharp")
    assert e is not None
    assert e.test_kimligi("TPD1WebC2_3f9b1c2eTests › Senaryo", None) == "3f9b1c2e"
    assert e.test_kimligi("x", "e2e-csharp/Tests/Generated/TPD1WindowsC3_abcdef12Tests.cs") == (
        "abcdef12"
    )
    assert e.test_kimligi("GirisTests › Senaryo", "Tests/GirisTests.cs") is None
    assert e.test_dosyasi_mi("Tests/Generated/XTests.cs") and not e.test_dosyasi_mi("a.java")


def _satir(dosya: str, ad: str) -> parse.TestSatiri:
    return parse.TestSatiri(test_adi=ad, dosya=dosya, sonuc="passed", sure_ms=1)


def test_ci_dil_ayristirmasi_csharp_ve_python_kimligi() -> None:
    ayr = parse.Ayristirma(
        testler=[_satir("Antreklabs.Bayi.Tests.Generated.TPD1WebC2_3f9b1c2eTests", "Senaryo")],
        uyarilar=["JSON rapor (results.json) bulunamadı", "başka"],
        istatistik={},
        raporlar={},
    )
    out = parse.dil_ayristirmasi(ayr, "csharp")
    t = out.testler[0]
    assert (t.dosya, t.test_adi) == (
        "Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs",
        "TPD1WebC2_3f9b1c2eTests › Senaryo",
    )
    assert out.uyarilar == ["başka"]
    py = parse.dil_ayristirmasi(
        parse.Ayristirma([_satir("tests.generated.test_tpd_1_c2_3f9b1c2e", "test_x")], [], {}, {}),
        "python",
    )
    assert (py.testler[0].dosya, py.testler[0].test_adi) == (
        "tests/generated/test_tpd_1_c2_3f9b1c2e.py",
        "test_tpd_1_c2_3f9b1c2e › test_x",
    )
    # Kancası olmayan dilde kimlik değişmez.
    assert parse.dil_ayristirmasi(ayr, "rust").testler[0].dosya == ayr.testler[0].dosya


def test_eslemede_csharp_fikstur_adi_sinif_adidir() -> None:
    from tp_core.features.codegen import checks

    tablo = checks.SymbolTable(
        {"page_objects": [{"class": "LoginPage", "methods": [
            {"name": "LoginAsync", "kind": "action", "params": []}]}]}
    )  # fmt: skip
    esleme = {"step_mapping": [{"step_id": "1", "po": "LoginPage", "method": "LoginAsync",
                                "args": []}], "expects": []}  # fmt: skip
    case = {"steps": [{"id": "1", "action": "giriş"}], "expected": []}
    bulgular = checks.check_mapping(esleme, case, tablo, fixtures={"LoginPage"}).bulgular
    assert any(
        "fikstürü" in b.mesaj
        for b in checks.check_mapping(esleme, case, tablo, fixtures={"BaskaPage"}).bulgular
    )
    assert not [b for b in bulgular if "fikstürü" in b.mesaj]


def test_musteri_ci_dil_kancalari() -> None:
    assert dil_kancalari.varsayilan_kimlik("ios", "swift") is None
    donustur = dil_kancalari.varsayilan_kimlik("android", "kotlin")
    assert donustur is not None
    s = donustur(_satir("com.antreklabs.bayisiparis.tp.uretilen.TPD1AndroidC2_3f9b1c2eTest",
                        "senaryo"))  # fmt: skip
    assert s.dosya.endswith("/com/antreklabs/bayisiparis/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt")
    iskelet = dil_kancalari.varsayilan_iskelet(KurulumParametreleri("ios", "swift"), RULES)
    assert iskelet and all(y.endswith((".swift", ".gitkeep")) for y in iskelet)
    # Kotlin: test paketi verilmeden iskelet önerilmez (paket adı iskeletin parçası).
    assert (
        dil_kancalari.varsayilan_iskelet(KurulumParametreleri("android", "kotlin"), RULES) is None
    )
    if dil_kancalari.kotlin_iskelet_kaynagi() is not None:
        k = dil_kancalari.varsayilan_iskelet(
            KurulumParametreleri("android", "kotlin", test_paketi="com.acme.bayi.tp"), RULES
        )
        assert k and any(y.endswith("com/acme/bayi/tp/ekranlar/Kimlikler.kt") for y in k)
        assert all("com.antreklabs.bayisiparis" not in v for v in k.values())


def test_script_musteri_ci_ozeti_yalniz_musteri_ci_ciftinde() -> None:
    from tp_core.features.codegen import views

    web = SimpleNamespace(platform="web", dil="csharp", head_sha="a" * 40, pr_no=3, depo="", id=1)
    assert views._musteri_ci_ozeti(web) is None  # type: ignore[arg-type]
    pr_yok = SimpleNamespace(platform="android", dil="kotlin", head_sha=None, pr_no=None, depo="",
                             id=2)  # fmt: skip
    assert views._musteri_ci_ozeti(pr_yok) is None  # type: ignore[arg-type]


def test_triage_kisa_turleri_sinyal_sozlugune_eslenir() -> None:
    n = triage_diller.normal_tur
    assert n("locator", "waiting for get_by_test_id('x') Timeout 5000ms") == "locator_timeout"
    assert n("locator", "element(s) not found") == "locator_not_found"
    assert n("timeout", "x") == "locator_timeout"
    assert n("environment", "Connection refused") == "navigation"
    assert n("environment", "KurulumHatasi", veri_mi=True) == "test_data"
    assert n("assertion") == "assertion" and n("derleme") == "derleme" and n(None) is None
    assert n("bilinmeyen") == "other"
