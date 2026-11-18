"""`github_artifacts` genellemesi (artefakt adı + sonuç kökü); web varsayılanı değişmez."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.features.musteri_ci.yardimci import JUNIT_GECEN, SahteGh, zip_yap
from tp_core.features.ci import github_artifacts as ga
from tp_core.features.ci import services


@pytest.fixture
def kok(tmp_path: Path):
    services._overrides["github_artifacts_root"] = lambda: tmp_path
    yield tmp_path
    services._overrides.pop("github_artifacts_root", None)


def _gh(ad: str) -> SahteGh:
    return SahteGh(
        artefaktlar=[{"id": 1, "name": ad}],
        zipler={1: zip_yap({"junit.xml": JUNIT_GECEN, "ci-meta.json": b"{}"})},
    )


def test_web_varsayilani_degismez(kok: Path):
    r = ga.hazirla(_gh("test-local-results"), _gh("test-local-results").artefaktlar, "gh/1-1")
    assert r["durum"] == "indirildi"
    assert r["yollar"] == {
        "junit": "src/e2e/results/junit.xml",
        "meta": "src/e2e/results/ci-meta.json",
    }
    assert r["indirilen"] == ["test-local-results"]


def test_web_tp_results_adini_almaz(kok: Path):
    gh = _gh("tp-results")
    r = ga.hazirla(gh, gh.artefaktlar, "gh/2-1")
    assert r["durum"] == "yok"
    assert "'test-local-results' / 'playwright-report'" in r["hata"]


def test_musteri_ci_koku(kok: Path):
    gh = _gh("tp-results")
    r = ga.hazirla(
        gh,
        gh.artefaktlar,
        "gh/3-1",
        sonuc_adi="tp-results",
        sonuc_kok="src/ios-swift/results",
        rapor_adi=None,
    )
    assert r["durum"] == "indirildi" and r["indirilen"] == ["tp-results"]
    assert r["yollar"]["junit"] == "src/ios-swift/results/junit.xml"
    assert (kok / "gh/3-1/src/ios-swift/results/junit.xml").is_file()
    assert ga.yollari_bul(kok / "gh/3-1", "src/ios-swift/results")["meta"].endswith("ci-meta.json")


def test_gecersiz_kok_reddedilir(kok: Path):
    gh = _gh("tp-results")
    for kotu in ("src/../x/results", "/etc", "src/ios-swift", "src/a/b/results"):
        r = ga.hazirla(gh, gh.artefaktlar, "gh/4-1", sonuc_adi="tp-results", sonuc_kok=kotu)
        assert r["durum"] == "hata"
        with pytest.raises(ValueError):
            ga.yollari_bul(kok, kotu)
    assert gh.indirilen == []


def test_artefakt_sunumu_kokleri_izinli():
    """Yerel kopya kökleri sunumun izinli alt ağacında (`src/**/results/**`)."""
    from tp_core.features.ci import artifacts

    kaynak = Path(artifacts.__file__).read_text(encoding="utf-8")
    assert "src/**/results/**" in kaynak
    for kok_ in ("src/android-kotlin/results", "src/ios-swift/results"):
        assert ga.SONUC_KOK_RE.fullmatch(kok_)
