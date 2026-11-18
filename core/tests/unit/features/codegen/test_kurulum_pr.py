"""014 müşteri CI kurulum PR'ı ucu (`POST /code/ci-setup`, `codegen.kurulum_pr`).

Sahte forge (LocalForge, `codegen` fikstürü) ile: yetki, parametre doğrulaması (422), önizleme
(forge'a yazmaz), PR açma + idempotentlik (açık PR varken yenisi açılmaz), denetim kaydı, forge
hatası (409) ve `/code/languages` önizlemesinin açık PR'ı göstermesi.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tp_core.features.codegen import kurulum_pr

from .conftest import arka_plan_worker

ANDROID = {"platform": "android", "dil": "kotlin"}
IOS = {"platform": "ios", "dil": "swift"}
IOS_PARAMS = {
    "xcode_proje": "ios/Bayi.xcworkspace",
    "sema": "Bayi",
    "ui_test_hedefi": "BayiUITests",
    "hazirlik_betigi": ".github/tp/hazirlik.sh",
    "node_surumu": "22",
    "izlenen_kok": "src",
    "yapilandirma": "Release",
}


def _giris(api: TestClient, make_user: Any, rol: str) -> Any:
    from .conftest import login

    u = make_user(rol)
    login(api, u)
    return u


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    return _giris(api, make_user, "engineer")


def _denetimler(engine: Engine) -> list[Any]:
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT eylem, aktor, nesne, ozet AS veri FROM audit_event "
                "WHERE eylem LIKE 'musteri_ci.kurulum_pr%' ORDER BY id"
            )
        ).all()


# ------------------------------------------------------------------ parametreler (saf)


def test_parametreler_bos_alanlar_varsayilani_korur_diger_platform_yok_sayilir() -> None:
    p = kurulum_pr.parametreler(
        "android",
        "kotlin",
        {
            "test_paketi": " com.acme.bayi.tp ",
            "hazirlik_betigi": "",
            "node_surumu": None,
            "emulator_api": "33",
            "xcode_proje": "x.xcodeproj",  # iOS alanı: android'de yok sayılır
        },
    )
    assert p.test_paketi == "com.acme.bayi.tp" and p.emulator_api == 33
    assert p.hazirlik_betigi == "" and p.xcode_proje == "" and p.varsayilan_dal == "main"


def test_parametreler_ios_yeni_alanlar() -> None:
    p = kurulum_pr.parametreler("ios", "swift", IOS_PARAMS)
    assert (p.hazirlik_betigi, p.node_surumu, p.izlenen_kok, p.yapilandirma) == (
        ".github/tp/hazirlik.sh",
        "22",
        "src",
        "Release",
    )


@pytest.mark.parametrize(
    ("platform", "dil", "girdi", "parca"),
    [
        ("web", "ts", {}, "müşteri CI hattında değil"),
        ("android", "kotlin", {}, "test paketi gerekli"),
        ("android", "kotlin", {"test_paketi": "a.b", "bilinmez": 1}, "bilinmeyen"),
        ("android", "kotlin", {"test_paketi": "a.b", "emulator_api": "x"}, "sayı olmalı"),
        ("ios", "swift", {**IOS_PARAMS, "hazirlik_betigi": "../x.sh"}, "hazırlık betiği"),
        ("ios", "swift", {**IOS_PARAMS, "node_surumu": "22; rm -rf"}, "Node sürümü"),
    ],
)
def test_parametreler_gecersiz(platform: str, dil: str, girdi: dict[str, Any], parca: str) -> None:
    with pytest.raises(kurulum_pr.KurulumIstekHatasi) as exc:
        kurulum_pr.parametreler(platform, dil, girdi)
    assert parca in str(exc.value)


# ------------------------------------------------------------------ uç


@pytest.mark.parametrize("rol", ["tester", "analyst", "developer", "po"])
def test_yetkisiz_roller_403(api: TestClient, make_user: Any, codegen: Any, rol: str) -> None:
    _giris(api, make_user, rol)
    r = api.post("/code/ci-setup", json={**ANDROID, "onizle": True})
    assert r.status_code == 403, r.text


def test_gecersiz_parametre_422_ve_is_acilmaz(
    api: TestClient, codegen: Any, muhendis: Any, engine: Engine
) -> None:
    r = api.post("/code/ci-setup", json={**ANDROID, "parametreler": {}})
    assert r.status_code == 422, r.text
    g = r.json()
    assert g["kod"] == "kurulum_parametre" and any("test paketi" in h for h in g["hatalar"])
    # Pydantic: web platformu / bilinmeyen alan.
    assert api.post("/code/ci-setup", json={"platform": "web", "dil": "ts"}).status_code == 422
    r = api.post("/code/ci-setup", json={**ANDROID, "parametreler": {"x": 1}})
    assert r.status_code == 422
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM job WHERE tur = :t"), {"t": kurulum_pr.KURULUM_PR_JOB}
        ).scalar_one()
    assert n == 0


def test_onizleme_forgea_yazmaz(
    api: TestClient, codegen: Any, muhendis: Any, engine: Engine
) -> None:
    with arka_plan_worker(engine):
        r = api.post(
            "/code/ci-setup",
            json={**ANDROID, "onizle": True, "parametreler": {"test_paketi": "com.acme.bayi.tp"}},
        )
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["durum"] == "onizleme" and g["hazir"] is True and g["pr"] is None
    assert ".github/workflows/mobil-android-kotlin.yml" in g["dosyalar"]
    assert g["kurulum"]["durum"] == "gerekli" and g["taban"] == "main"
    assert codegen.forge.find_open_pr(g["dal"]) is None
    assert _denetimler(engine) == []


def test_pr_acar_ve_ikinci_istekte_mevcut_pr_doner(
    api: TestClient, codegen: Any, muhendis: Any, engine: Engine
) -> None:
    govde = {**ANDROID, "parametreler": {"test_paketi": "com.acme.bayi.tp"}}
    with arka_plan_worker(engine):
        r1 = api.post("/code/ci-setup", json=govde)
        assert r1.status_code == 200, r1.text
        a = r1.json()
        assert a["durum"] == "acildi" and a["pr_no"] and a["dal"] == "tp/kurulum-android-kotlin"
        assert a["kurulum"]["durum"] == "acik" and a["kurulum"]["number"] == a["pr_no"]
        assert "onaylayan" not in a
        pr = codegen.forge.get_pr(a["pr_no"])
        assert "tp-kurulum" in pr.labels and f"Onaylayan: {muhendis.kullanici_adi}" in pr.body
        dal_dosyalari = codegen.forge.list_files(ref=a["dal"])
        assert ".github/workflows/mobil-android-kotlin.yml" in dal_dosyalari

        # Farklı parametreyle bile ikinci istek yeni commit/PR açmaz: var olan PR döner.
        params2 = {"test_paketi": "com.acme.bayi.tp", "emulator_api": 33}
        govde2 = {**ANDROID, "parametreler": params2}
        r2 = api.post("/code/ci-setup", json=govde2)
        assert r2.status_code == 200, r2.text
        b = r2.json()
        assert b["durum"] == "mevcut" and b["pr_no"] == a["pr_no"] and b["sha"] == pr.head_sha
        assert codegen.forge.head_sha(a["dal"]) == pr.head_sha
    acik = [p for p in codegen.forge.list_prs("open") if p.branch == a["dal"]]
    assert len(acik) == 1

    kayitlar = _denetimler(engine)
    assert [k.eylem for k in kayitlar] == [
        "musteri_ci.kurulum_pr_acildi",
        "musteri_ci.kurulum_pr_mevcut",
    ]
    assert kayitlar[0].aktor == muhendis.kullanici_adi
    assert kayitlar[0].nesne == "kurulum:android/kotlin"
    assert kayitlar[0].veri["pr"] == a["pr_no"]
    assert kayitlar[0].veri["parametreler"]["test_paketi"] == "com.acme.bayi.tp"

    # Dil seçenekleri önizlemesi açık PR'ı gösterir (idempotent gösterim).
    from tp_core.features.codegen import service

    ozet = service._kurulum_ozeti("android", "kotlin")
    assert ozet is not None and ozet["durum"] == "acik" and ozet["number"] == a["pr_no"]


def test_yonetici_de_acabilir_ios_parametreleri(
    api: TestClient, make_user: Any, codegen: Any, engine: Engine
) -> None:
    _giris(api, make_user, "admin")
    with arka_plan_worker(engine):
        r = api.post("/code/ci-setup", json={**IOS, "parametreler": IOS_PARAMS})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["durum"] == "acildi"
    is_akisi = codegen.forge.read_file(".github/workflows/mobil-ios-swift.yml", ref=g["dal"])
    assert ".github/tp/hazirlik.sh" in is_akisi and "Release" in is_akisi
    assert any("Hazırlık betiği yok" in e for e in g["elle_adimlar"])


def test_forge_hatasi_409_ve_denetim(
    api: TestClient, codegen: Any, muhendis: Any, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.integrations.forge import ForgeProtectionError

    def reddet(*_a: Any, **_k: Any) -> str:
        raise ForgeProtectionError("Resource not accessible by integration (workflows izni yok)")

    monkeypatch.setattr(codegen.forge, "commit_files", reddet)
    with arka_plan_worker(engine):
        r = api.post(
            "/code/ci-setup", json={**ANDROID, "parametreler": {"test_paketi": "com.acme.bayi.tp"}}
        )
    assert r.status_code == 409, r.text
    g = r.json()
    assert g["kod"] == "kurulum_pr_basarisiz" and "workflows izni yok" in g["detail"]
    kayit = _denetimler(engine)
    assert [k.eylem for k in kayit] == ["musteri_ci.kurulum_pr_basarisiz"]
    assert kayit[0].veri["tur"] == "ForgeProtectionError"


def test_is_bitmediyse_202(
    api: TestClient, codegen: Any, muhendis: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kurulum_pr, "KURULUM_PR_BEKLEME_S", 0.0)
    r = api.post(
        "/code/ci-setup",
        json={**ANDROID, "onizle": True, "parametreler": {"test_paketi": "com.acme.bayi.tp"}},
    )
    assert r.status_code == 202, r.text
    assert r.json()["durum"] == "suruyor" and r.json()["job_id"]
