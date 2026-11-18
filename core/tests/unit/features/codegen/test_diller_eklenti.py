"""014 Ş0: (platform, dil) matrisi, dil eklentisi keşfi ve dağıtımı (specs/014-test-dilleri/plan.md).

ts/java eklentileri bugünkü render işlevlerini çağırır (çıktı bayt eşit); yeni diller yalnız
eklenti dosyasıyla gelir. Değerlendirme kapısı yeni çiftleri varsayılan olarak kapatır.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tp_core.features.codegen import diller, render
from tp_core.features.codegen import platform as p
from tp_core.features.codegen import service
from tp_core.features.triage import diller as triage_diller

from .test_render_dil import RULES, girdi, java_web_girdi

SOZLESME = (
    Path(__file__).resolve().parents[5] / "toolchain" / "tests" / "data" / "core_sozlesme.json"
)


def test_matris_tek_kaynak() -> None:
    assert len(p.CATILAR) == 13
    for (pl, d), c in p.CATILAR.items():
        assert (c.platform, c.dil) == (pl, d)
        assert c.hat in p.HATLAR
        assert c.ajan == ("verify_and_map" if pl == "web" else "verify_and_map_app")
        assert p.gecerli_cift(pl, d)
    assert {k for k, c in p.CATILAR.items() if c.hat == "musteri_ci"} == {
        ("android", "kotlin"),
        ("ios", "swift"),
    }
    assert p.CATILAR[("android", "kotlin")].gh_is_akisi == "mobil-android-kotlin"
    assert p.CATILAR[("ios", "swift")].gh_is_akisi == "mobil-ios-swift"
    assert p.CATILAR[("web", "python")].sablon == "playwright_pytest.py.j2"
    # Kaplama kuralı `<kok_ayari>_<P>` (Home Ş6 adları).
    assert p.kok_ayari_platform("TP_E2E_APP_PYTHON_ROOT", "android") == (
        "TP_E2E_APP_PYTHON_ROOT_ANDROID"
    )
    assert p.kok_ayari_platform("TP_ANDROID_KOTLIN_ROOT", "android") == (
        "TP_ANDROID_KOTLIN_ROOT_ANDROID"
    )
    assert p.kok_ayari_platform("TP_E2E_PYTHON_ROOT", "web") is None


def test_check_adlari_toolchain_sozlesmesi_ile_ayni() -> None:
    veri = json.loads(SOZLESME.read_text(encoding="utf-8"))
    for kayit in veri["dil_check_adlari"]:
        assert p.check_adi(kayit["platform"], kayit["lang"]) == kayit["check"]
    # ts/java adları değişmez (K-T1).
    assert p.check_adi("web", "ts") == "local-ci"
    assert p.check_adi("web", "java") == "local-ci-web-java"
    assert p.check_adi("windows", "java") == "local-ci-windows"


def test_eklenti_kesfi_ts_ve_java_kayitli() -> None:
    assert {"ts", "java"} <= set(diller.adlar())
    assert diller.hatalar() == {}
    for ad in ("ts", "java"):
        assert isinstance(diller.eklenti(ad), diller.DilEklentisi)
    assert triage_diller.hatalar() == {}


def _eklentisiz(monkeypatch: pytest.MonkeyPatch, *adlar: str) -> None:
    """014 entegrasyonu: tüm dil eklentileri yüklü; "eklenti yok" davranışı kayıttan çıkarılarak
    sınanır."""
    kayit = {k: v for k, v in diller.kayit().items() if k not in adlar}
    monkeypatch.setattr(diller, "_KAYIT", kayit)


def test_render_dil_eklentiye_dagitir_ve_bayt_esit(monkeypatch: pytest.MonkeyPatch) -> None:
    ts = render.render_dil(girdi(), dil="ts", platform="web", rules=RULES)
    assert ts.content == render.render_test(girdi(), RULES).content
    jw = render.render_dil(java_web_girdi(), dil="java", platform="web", rules=RULES)
    assert jw.content == render.render_java_test(java_web_girdi(), "web", RULES).content
    with pytest.raises(render.RenderError, match="üretim yok"):
        render.render_dil(girdi(), dil="swift", platform="web", rules=RULES)
    _eklentisiz(monkeypatch, "kotlin", "csharp")
    with pytest.raises(render.RenderError, match="eklentisi yüklü değil"):
        render.render_dil(girdi(), dil="kotlin", platform="android", rules=RULES)
    # 014 karar 3a: eklentisiz web C# için 011 doğrulanmamış yolu da yok.
    with pytest.raises(render.RenderError, match="eklentisi yüklü değil"):
        render.render_dil(girdi(), dil="csharp", platform="web", rules=RULES)


def test_sahte_eklenti_render_ve_yol(monkeypatch: pytest.MonkeyPatch) -> None:
    gorulen: dict[str, Any] = {}

    class Sahte:
        ad = "kotlin"
        proje_dosyasi = "build.gradle.kts"
        algila_kaliplari = (
            diller.AlgilaKalibi(frozenset({"android"}), "TP_ANDROID_KOTLIN_ROOT", ""),
        )

        def render(self, inp: Any, cati: p.Cati, rules: Path, **kw: Any) -> Any:
            gorulen.update(cati=cati, **kw)
            return "ok"

        def uretilen_yol(self, cati: p.Cati, kok: str, story: Any, sira: int, cid: Any) -> str:
            return f"{kok}/{cati.uretilen_alt_yol}/X{sira}Test.kt"

        def test_dosyasi_mi(self, yol: str) -> bool:
            return yol.endswith("Test.kt")

    monkeypatch.setattr(diller, "_KAYIT", {**diller.kayit(), "kotlin": Sahte()})
    assert (
        render.render_dil(
            girdi(), dil="kotlin", platform="android", rules=RULES, sembol_tablosu={"a": 1}
        )
        == "ok"
    )
    assert gorulen["cati"].hat == "musteri_ci" and gorulen["sembol_tablosu"] == {"a": 1}
    monkeypatch.setattr(service, "app_root", lambda platform=None: "demo-app")
    monkeypatch.setattr(service, "ayar", lambda ad, *a, **k: None)
    monkeypatch.setattr(service.depolar, "depo_anahtari", lambda platform: "")
    cid = uuid.UUID(int=1)
    assert service.baslangic_dosya_yolu("kotlin", "android", "TPD-1", 3, cid) == (
        "demo-app/app/src/androidTest/java/com/antreklabs/bayisiparis/tp/uretilen/X3Test.kt"
    )
    assert service.toolchain_hedefi("android", "kotlin") == {
        "lang": "kotlin",
        "platform": "android",
    }
    assert service.proje_dosyasi("kotlin", "android") == (
        "demo-app/app/src/androidTest/java/build.gradle.kts"
    )


def test_dil_koku_ayar_ve_kaplama(monkeypatch: pytest.MonkeyPatch) -> None:
    deger = {"TP_E2E_APP_PYTHON_ROOT_IOS": "mobil/py", "TP_E2E_PYTHON_ROOT": "x/e2e-py"}
    monkeypatch.setattr(service, "ayar", lambda ad, *a, **k: deger.get(ad))
    monkeypatch.setattr(service, "app_root", lambda platform=None: "demo-app")
    monkeypatch.setattr(service.depolar, "depo_anahtari", lambda platform: "")
    assert service.dil_koku("web", "python") == "x/e2e-py"
    assert service.dil_koku("ios", "python") == "mobil/py"
    assert service.dil_koku("android", "python") == "demo-app/e2e-app-python"


def test_kapi_engeli_yeni_ciftleri_kapatir(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ş8 kapısı yoksa (ya da diller.yaml'da yakinda) yeni çiftler "Değerlendirme sürüyor".
    monkeypatch.setattr(p, "cift_durumu", lambda pl, d, *a: "acik" if d in ("ts", "java") else "x")
    assert service.kapi_engeli("web", "ts") is None
    assert service.kapi_engeli("android", "java") is None
    assert service.kapi_engeli("android", "kotlin") == "Değerlendirme sürüyor"
    # Kapı açık ama çekirdek eklentisi yok: yine kapalı (eklentisiz C#/Python web 011 yolu hariç).
    monkeypatch.setattr(p, "cift_durumu", lambda *a, **k: "acik")
    _eklentisiz(monkeypatch, "kotlin", "csharp", "python")
    assert service.kapi_engeli("android", "kotlin") == "Değerlendirme sürüyor"
    assert service.kapi_engeli("web", "csharp") is None
    assert p.etkin_hat("web", "csharp") == "dogrulanmamis"
    assert p.etkin_hat("android", "kotlin") == "musteri_ci"
    assert p.repoya_yazar_mi("kotlin", "android") and not p.repoya_yazar_mi("csharp", "web")
    assert not p.kirarak_dogrulama_var_mi("ios", "swift")


def test_dil_durumlari_yedegi(tmp_path: Path) -> None:
    (tmp_path / "diller.yaml").write_text(
        "version: 1\nciftler:\n  web/python: {durum: acik}\n  web/ts: {durum: yakinda}\n",
        encoding="utf-8",
    )
    d = p.dil_durumlari(tmp_path)
    assert d["web/python"] == "acik" and d["web/ts"] == "yakinda"
    assert d["android/kotlin"] == "yakinda"
    bos = p.dil_durumlari(tmp_path / "yok")
    assert bos["web/ts"] == "acik" and bos["ios/swift"] == "yakinda"


def test_ajan_mesajina_dil_satiri(monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.features.codegen import checks as kontroller

    tablo = kontroller.SymbolTable({"page_objects": [], "lang": "java"})
    kayit: list[tuple[str, str]] = []
    sahte = SimpleNamespace(ajan_dil_girdisi=lambda d, t: kayit.append((d, t)) or f"DIL {d}/{t}")
    import sys

    monkeypatch.setitem(sys.modules, "tp_core.gateway.dil_kapisi", sahte)
    import tp_core.gateway as gw

    monkeypatch.setattr(gw, "dil_kapisi", sahte, raising=False)
    m = service.app_mapping_messages(
        {"steps": []}, "R", tablo, platform="android", agent_dealer="b", dil="python",
        tablo_dili="java",
    )  # fmt: skip
    assert "Ekran nesnesi sembol tablosu (Java):" in m[0].content
    assert "DIL python/java" in m[0].content
    eski = service.mapping_messages(
        {"steps": []}, "R", tablo, agent_dealer="b", demo_web_url="http://x"
    )
    assert "DIL" not in eski[0].content  # dil verilmezse satır yok (geriye uyum)


def test_yerel_kapi_dil_koku_check_ister() -> None:
    from tp_core.integrations import forge

    zorunlu, neden = forge.local_required_checks(
        ("local-ci",), [], ["e2e-python/tests/generated/test_x.py"]
    )
    assert "local-ci-web-python" in zorunlu and neden is None
    zorunlu, neden = forge.local_required_checks(
        ("local-ci",), [], ["e2e-app-python/tests/generated/test_x.py"]
    )
    assert neden is not None and "e2e-app-python/" in neden


def test_kapi_engeli_kabul_kipi(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TP_DIL_KABUL_KIPI` yalnız `dil_kapisi.kabul_kipinde_acik_mi` doğruysa kapıyı geçer;
    değişken yokken kabul kipi hiç sorulmaz."""
    from tp_core.gateway import dil_kapisi

    monkeypatch.setattr(p, "cift_durumu", lambda *a, **k: "yakinda")
    sorulan: list[tuple] = []

    def sahte(rules, platform, dil, **kw):
        sorulan.append((platform, dil, kw["kip_degeri"], kw["forge"]))
        return (platform, dil) == ("web", "python")

    monkeypatch.setattr(dil_kapisi, "kabul_kipinde_acik_mi", sahte)
    monkeypatch.setattr(service, "ayar", lambda k: "local" if k == "TP_FORGE" else None)
    monkeypatch.setattr(
        service, "get_settings", lambda: SimpleNamespace(ortam="dev", demo_mode=True)
    )
    monkeypatch.delenv("TP_DIL_KABUL_KIPI", raising=False)
    assert service.kapi_engeli("web", "python") == "Değerlendirme sürüyor"
    assert sorulan == []
    monkeypatch.setenv("TP_DIL_KABUL_KIPI", "web/python")
    assert service.kapi_engeli("web", "python") is None
    assert service.kapi_engeli("web", "csharp") == "Değerlendirme sürüyor"
    assert sorulan[0] == ("web", "python", "web/python", "local")
