"""Test dili kapısı (014 Ş8): `rules/diller.yaml`, `tp_core.gateway.dil_kapisi`, `--dil` alt küme
koşusu ve dil başına vaka kaynakları."""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from tests.unit.gateway.build_eval_sets import build_sets, vaka_kaynaklari
from tests.unit.gateway.demo_sources import RULES
from tp_core.gateway import dil_kapisi as dk
from tp_core.gateway import evaluation
from tp_core.gateway.errors import GatewayConfigError
from tp_core.gateway.eval_live import (
    DIL_ALT_KUMESI,
    BundlePlan,
    BundleRun,
    _dil_kanitlari,
    _tag,
    dil_plani,
)
from tp_core.gateway.eval_set import CaseResult, load_set
from tp_core.gateway.evaluation import prompt_versions

BUGUN = dt.date(2026, 11, 20)


@pytest.fixture
def kopya(tmp_path: Path) -> Path:
    """Kapının okuduğu kural dosyalarının geçici kopyası (prompt'lar, diller, iki set)."""
    hedef = tmp_path / "rules"
    shutil.copytree(RULES / "prompts", hedef / "prompts")
    (hedef / "evaluation" / "results").mkdir(parents=True)
    for ad in ("verify-and-map.json", "verify-and-map-app.json"):
        shutil.copy(RULES / "evaluation" / ad, hedef / "evaluation" / ad)
    shutil.copy(RULES / dk.DILLER_FILE, hedef / dk.DILLER_FILE)
    # Kanıt akışı testleri kanıtsız "yakında" çiftlerden başlar: gerçek tablodaki kısmi kanıt
    # (canlı eval raporu; kopyada results/ boş) temizlenir. Gerçek tablo ayrıca denetlenir.
    # Satır biçimi (`p/d: {hat: …, durum: yakinda, kanit: {…}}`) ve baştaki açıklama korunur.
    path = hedef / dk.DILLER_FILE
    metin = re.sub(r"(durum: yakinda), kanit: \{[^}]*\}", r"\1", path.read_text(encoding="utf-8"))
    path.write_text(metin, encoding="utf-8")
    return hedef


def _ciftleri_yaz(rules: Path, **ciftler: dict) -> None:
    path = rules / dk.DILLER_FILE
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for anahtar, kayit in ciftler.items():
        data["ciftler"][anahtar.replace("__", "/")] = kayit
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _python_vakasi_ekle(rules: Path, *, ids: tuple[str, ...] = ("tpd-4-c1-python",)) -> None:
    """Kopyadaki web setinin python vakalarını verilenlerle değiştirir (Ş1'in gerçek vakaları
    entegrasyonda sete girdi; kanıt akışı testleri kendi kimlikleriyle çalışır)."""
    path = rules / "evaluation" / "verify-and-map.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    sablon = next(c for c in data["cases"] if c.get("dil") == "ts")
    data["cases"] = [c for c in data["cases"] if c.get("dil") != "python"]
    for vid in ids:
        data["cases"].append({**sablon, "id": vid, "dil": "python"})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _rapor(rules: Path, sonuc: dict[str, bool], **over) -> Path:
    surum = prompt_versions(rules)["verify-and-map"]
    rapor = {
        "bundle": "verify-and-map",
        "version": surum,
        "date": BUGUN.isoformat(),
        "mode": "live",
        "tamamlandi": True,
        "cases": [{"id": k, "ok": v} for k, v in sonuc.items()],
        **over,
    }
    path = rules / "evaluation" / "results" / f"verify-and-map-v{surum}-python-{BUGUN}.json"
    path.write_text(json.dumps(rapor), encoding="utf-8")
    return path


# --- Depodaki kapı ----------------------------------------------------------------------------


def test_depodaki_dil_kapisi_gecerli_ve_check_gecer() -> None:
    """CI kapısı: `python -m tp_core.gateway.dil_kapisi --check` depoda yeşil."""
    assert dk.denetle(RULES) == []
    assert dk.main(["--rules-dir", str(RULES), "--check"]) == 0


def test_depoda_ts_java_devralindi_acik_digerleri_yakinda() -> None:
    """Kullanıcı kararı 3: ts/java devralındı-açık; web C#/Python dahil değerlendirilmemiş her
    çift `yakinda` (seçilemez)."""
    sts = dk.durumlar(RULES)
    acik = {c for c, s in sts.items() if s.kullanilabilir}
    assert acik == set(dk.DEVRALINABILIR)
    assert all(sts[c].devralindi for c in acik)
    for cift in (("web", "python"), ("web", "csharp")):
        assert sts[cift].durum == "yakinda"
        assert not dk.kullanilabilir_mi(RULES, *cift)
        assert sts[cift].neden == dk.YAKINDA_NEDENI
    assert sts[("android", "kotlin")].hat == sts[("ios", "swift")].hat == "musteri_ci"
    assert len(sts) == 13 and {d for _, d in sts} == set(dk.DILLER)


def test_matris_esitligi_cift_ve_hat() -> None:
    tablo, _ = dk.matris()
    sts = dk.durumlar(RULES)
    assert set(tablo) == set(sts)
    assert all(tablo[c] == s.hat for c, s in sts.items())


def test_home_ozeti_bicimi() -> None:
    oz = dk.home_ozeti(RULES)
    assert oz["version"] == 1 and oz["kaynak"] == "rules/diller.yaml"
    assert oz["platformlar"]["web"]["ts"] == {"durum": "acik", "hat": "tam"}
    assert oz["platformlar"]["ios"]["swift"] == {"durum": "yakinda", "hat": "musteri_ci"}
    assert set(oz["platformlar"]) == set(dk.PLATFORMLAR)


# --- Şema ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kayit", "hata"),
    [
        ({"hat": "tam", "durum": "acik"}, "kanıtsız"),
        ({"hat": "tam", "durum": "acik", "kanit": "devralindi"}, "devralindi"),
        (
            {"hat": "tam", "durum": "acik", "kanit": {"eval": "x.json", "tarih": "2026-11-20"}},
            "kabul",
        ),
        ({"hat": "tam", "durum": "hazir"}, "durum"),
        ({"hat": "uzak", "durum": "yakinda"}, "hat"),
        ({"hat": "tam", "durum": "yakinda", "kanit": {"eval": "x.json"}}, "tarih"),
        ({"hat": "tam", "durum": "yakinda", "renk": "mavi"}, "bilinmeyen alan"),
    ],
)
def test_web_python_gecersiz_kayitlar(kopya: Path, kayit: dict, hata: str) -> None:
    _ciftleri_yaz(kopya, web__python=kayit)
    with pytest.raises(GatewayConfigError, match=hata):
        dk.durumlar(kopya)
    assert not dk.kullanilabilir_mi(kopya, "web", "python")  # okunamayan kapı kapalıdır
    assert dk.main(["--rules-dir", str(kopya), "--check"]) == 2


def test_devralindi_yalniz_acik_durumda(kopya: Path) -> None:
    _ciftleri_yaz(kopya, web__ts={"hat": "tam", "durum": "yakinda", "kanit": "devralindi"})
    with pytest.raises(GatewayConfigError, match="yalnız 'acik'"):
        dk.durumlar(kopya)


def test_bilinmeyen_cift_ve_matris_disi(kopya: Path) -> None:
    _ciftleri_yaz(kopya, web__kotlin={"hat": "tam", "durum": "yakinda"})
    assert any("web/kotlin" in s for s in dk.denetle(kopya))
    _ciftleri_yaz(kopya, web__rust={"hat": "tam", "durum": "yakinda"})
    with pytest.raises(GatewayConfigError, match="anahtar"):
        dk.durumlar(kopya)
    assert not dk.kullanilabilir_mi(RULES, "web", "rust")


def test_hat_matrisle_uyusmazsa_kapi_kapanir(kopya: Path) -> None:
    _ciftleri_yaz(kopya, android__kotlin={"hat": "tam", "durum": "yakinda"})
    assert any("android/kotlin: hat" in s for s in dk.denetle(kopya))


def test_dosya_yoksa_kapi_kapali(tmp_path: Path) -> None:
    assert not dk.kullanilabilir_mi(tmp_path, "web", "ts")
    assert dk.denetle(tmp_path)


# --- Kanıt akışı ------------------------------------------------------------------------------


def test_eval_kaniti_sonra_kabul_cifti_acar(kopya: Path) -> None:
    _python_vakasi_ekle(kopya)
    rapor = _rapor(kopya, {"tpd-4-c1-python": True})
    st = dk.eval_kaniti_yaz(kopya, "web", "python", rapor, tarih=BUGUN, out=lambda _: None)
    assert st.durum == "yakinda"  # kabul bekliyor
    assert st.kanit == {"eval": str(rapor.relative_to(kopya)), "tarih": "2026-11-20"}
    assert dk.denetle(kopya) == []  # kısmi kanıt da derin denetimden geçer
    st = dk.kabul_yaz(kopya, "web", "python", "https://ci/run/1", out=lambda _: None)
    assert st.durum == "acik" and dk.kullanilabilir_mi(kopya, "web", "python")
    assert dk.denetle(kopya) == []
    # Başlık yorumları korunur, diğer çiftler değişmez.
    metin = (kopya / dk.DILLER_FILE).read_text(encoding="utf-8")
    assert metin.startswith("# Test dili kapısı")
    assert "  web/ts: {hat: tam, durum: acik, kanit: devralindi}" in metin


def test_kabul_once_gelirse_cift_yakinda_kalir(kopya: Path) -> None:
    st = dk.kabul_yaz(kopya, "windows", "csharp", "kabul-42", out=lambda _: None)
    assert st.durum == "yakinda" and st.kanit == {"kabul": "kabul-42"}


def test_gecmeyen_ya_da_eksik_vakali_rapor_kanit_olmaz(kopya: Path) -> None:
    _python_vakasi_ekle(kopya, ids=("tpd-4-c1-python", "tpd-4-c2-python"))
    rapor = _rapor(kopya, {"tpd-4-c1-python": True, "tpd-4-c2-python": False})
    with pytest.raises(GatewayConfigError, match="geçmeyen"):
        dk.eval_kaniti_yaz(kopya, "web", "python", rapor, out=lambda _: None)
    rapor = _rapor(kopya, {"tpd-4-c1-python": True})
    with pytest.raises(GatewayConfigError, match="raporda olmayan"):
        dk.eval_kaniti_yaz(kopya, "web", "python", rapor, out=lambda _: None)
    rapor = _rapor(kopya, {"tpd-4-c1-python": True, "tpd-4-c2-python": True}, mode="replay")
    with pytest.raises(GatewayConfigError, match="canlı değil"):
        dk.eval_kaniti_yaz(kopya, "web", "python", rapor, out=lambda _: None)


def test_vakasiz_cift_kanit_alamaz(kopya: Path) -> None:
    _python_vakasi_ekle(kopya, ids=())
    rapor = _rapor(kopya, {})
    with pytest.raises(GatewayConfigError, match="vakası yok"):
        dk.eval_kaniti_yaz(kopya, "web", "python", rapor, out=lambda _: None)


def test_devralinmis_cifte_kanit_yazilmaz(kopya: Path) -> None:
    with pytest.raises(GatewayConfigError, match="devralınmış"):
        dk.kabul_yaz(kopya, "web", "ts", "x", out=lambda _: None)


def test_prompt_surumu_yukselince_kanit_bayatlar(kopya: Path) -> None:
    _python_vakasi_ekle(kopya)
    rapor = _rapor(kopya, {"tpd-4-c1-python": True})
    dk.eval_kaniti_yaz(kopya, "web", "python", rapor, tarih=BUGUN, out=lambda _: None)
    dk.kabul_yaz(kopya, "web", "python", "run-1", out=lambda _: None)
    prompt = kopya / "prompts" / "verify-and-map.md"
    eski = prompt_versions(kopya)["verify-and-map"]
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace(f"version: {eski}\n", f"version: {eski + 1}\n"),
        encoding="utf-8",
    )
    sorun = dk.denetle(kopya)
    assert any("kanıt bayat" in s for s in sorun)
    assert dk.denetle(kopya, "java") == []  # --dil java: python kanıtı denetlenmez
    assert dk.main(["--rules-dir", str(kopya), "--check", "--dil", "python"]) == 1


def test_elle_acik_yazilmis_sahte_kanit_check_ten_gecmez(kopya: Path) -> None:
    _ciftleri_yaz(
        kopya,
        web__python={
            "hat": "tam",
            "durum": "acik",
            "kanit": {"eval": "evaluation/results/yok.json", "tarih": "2026-11-20", "kabul": "x"},
        },
    )
    assert dk.kullanilabilir_mi(kopya, "web", "python")  # çalışma zamanı yapısal
    assert any("kanıt raporu yok" in s for s in dk.denetle(kopya))


def test_kabul_cli(kopya: Path) -> None:
    assert dk.main(["--rules-dir", str(kopya), "--kabul", "ios/swift", "--ref", "run-9"]) == 0
    assert dk.durum(kopya, "ios", "swift").kanit == {"kabul": "run-9"}


def test_evaluation_dil_filtresi(capsys: pytest.CaptureFixture[str]) -> None:
    assert evaluation.main(["--rules-dir", str(RULES), "--dil", "python"]) == 0
    out = capsys.readouterr().out
    assert "dil web/python\ttam\tyakinda" in out
    assert "verify-and-map@v" in out and "verify-and-map-app@v" in out
    assert "triage@" not in out


# --- Ajan girdisi ve prompt'lar ---------------------------------------------------------------


def test_ajan_dil_girdisi() -> None:
    satir = dk.ajan_dil_girdisi("python", "ts")
    assert "language): python (Python)" in satir and "tablosunun dili: ts (TypeScript)" in satir
    with pytest.raises(GatewayConfigError):
        dk.ajan_dil_girdisi("rust", "ts")


def test_prompt_lar_dilden_bagimsiz() -> None:
    web = (RULES / "prompts" / "verify-and-map.md").read_text(encoding="utf-8")
    app = (RULES / "prompts" / "verify-and-map-app.md").read_text(encoding="utf-8")
    for metin in (web, app):
        assert "`language`" in metin
        assert "exactly as written in the symbol table" in metin
    for java_sabiti in ("Java class", "Java method", "Java types", "Java literal", "Java test"):
        assert java_sabiti not in app
    assert prompt_versions(RULES)["verify-and-map"] == 4
    assert prompt_versions(RULES)["verify-and-map-app"] == 2


# --- Vaka dizini ------------------------------------------------------------------------------


def test_vakalar_dil_ve_platform_tasir() -> None:
    sets = build_sets()
    for bundle in ("verify-and-map", "verify-and-map-app"):
        kaynak = vaka_kaynaklari(bundle)
        assert [s["id"] for _, s in kaynak] == [c["id"] for c in sets[bundle]["cases"]]
        for case in sets[bundle]["cases"]:
            assert case["dil"] in dk.DILLER
            assert dk.ajan_paketi(case["platform"]) == bundle
            assert "Hedef test dili (language): " + case["dil"] in case["messages"][-1]["content"]
            if bundle == "verify-and-map-app":
                assert case["tool_env"] == f"app:{case['platform']}"
    # 014 entegrasyonu: dil şeritlerinin vakaları (Ş1 python, Ş2 csharp, Ş3 kotlin, Ş4 swift).
    assert {c["dil"] for c in sets["verify-and-map"]["cases"]} == {"ts", "python", "csharp"}
    assert {c["dil"] for c in sets["verify-and-map-app"]["cases"]} == {
        "java",
        "python",
        "csharp",
        "kotlin",
        "swift",
    }
    app = sets["verify-and-map-app"]["cases"][0]["messages"][-1]["content"]
    assert "Ekran nesnesi sembol tablosu (Java):" in app


def test_bilinmeyen_dil_dizini_reddedilir(tmp_path: Path) -> None:
    (tmp_path / "evaluation" / "vakalar" / "verify-and-map" / "rust").mkdir(parents=True)
    with pytest.raises(ValueError, match="bilinmeyen dil"):
        vaka_kaynaklari("verify-and-map", tmp_path)


def test_yanlis_pakette_platform_reddedilir(tmp_path: Path) -> None:
    d = tmp_path / "evaluation" / "vakalar" / "verify-and-map-app" / "python"
    d.mkdir(parents=True)
    (d / "x.json").write_text(json.dumps({"id": "x", "platform": "web"}), encoding="utf-8")
    with pytest.raises(ValueError, match="paketinde değil"):
        vaka_kaynaklari("verify-and-map-app", tmp_path)


# --- eval_live --dil -------------------------------------------------------------------------


def _plan(bundle: str) -> BundlePlan:
    data = load_set(RULES, bundle)
    return BundlePlan(bundle, int(data["version"]), data=data, purposes=[data["purpose"]])


def test_dil_plani_yalniz_ajan_paketleri_ve_dilin_vakalari() -> None:
    plans = dil_plani([_plan("triage"), _plan("verify-and-map"), _plan("verify-and-map-app")], "ts")
    assert [p.bundle for p in plans] == ["verify-and-map", "verify-and-map-app"]
    web, app = plans
    assert web.data[DIL_ALT_KUMESI] == "ts" and {c["dil"] for c in web.data["cases"]} == {"ts"}
    assert app.data is None and "'ts' vakası yok" in app.skip_reason
    assert _tag(web.data, web.purposes[0]) == "ts"
    assert _tag(load_set(RULES, "verify-and-map"), "verify_and_map") is None


def test_dil_kanitlari_yalniz_tum_vakalari_gecen_cift(kopya: Path) -> None:
    _python_vakasi_ekle(kopya, ids=("p1", "p2"))
    data = {
        **load_set(kopya, "verify-and-map"),
        DIL_ALT_KUMESI: "python",
    }
    data["cases"] = [c for c in data["cases"] if c.get("dil") == "python"]
    run = BundleRun("verify-and-map", results=[CaseResult("p1", True), CaseResult("p2", False)])
    run.report = _rapor(kopya, {"p1": True, "p2": False})
    satirlar: list[str] = []
    _dil_kanitlari(kopya, data, run, BUGUN, satirlar.append)
    assert "web/python: kanıt yazılmadı" in satirlar[0]
    assert dk.durum(kopya, "web", "python").kanit is None
    run.results[1] = CaseResult("p2", True)
    run.report = _rapor(kopya, {"p1": True, "p2": True})
    _dil_kanitlari(kopya, data, run, BUGUN, satirlar.append)
    assert dk.durum(kopya, "web", "python").kanit["tarih"] == "2026-11-20"
