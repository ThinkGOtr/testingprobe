"""Uygulama (Java/Appium; 009 mobil-masaüstü) kimlik onarımı: triage'ın hata anı sayfa kaynağı
önerisi → Java sembol tablosu (`platform`) → Kimlikler.java'da yalnızca sabit değeri → Java repair
koruması (`platform`) → cihazda tam paket (`platform`) → bot PR. Web akışı değişmez (test_flow)."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, select, text

from tests.unit.features.repair.conftest import REPO, TOOLCHAIN, git, run_jobs
from tp_core.config import get_settings
from tp_core.features.repair import locators, service
from tp_core.features.repair.toolchain import RepairToolchain
from tp_core.integrations.forge_local import LocalForge
from tp_core.models import Failure, Run, Script, TestResult, session_scope

KIMLIKLER = "e2e-app/src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java"
KIMLIKLER_G = "src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java"
SINIF = "com.antreklabs.bayi.uretilen.TPD1C3_0a1b2c3dTest"
MESAJ = (
    "org.openqa.selenium.TimeoutException: Expected condition failed: öğe tıklanabilir olmadı: "
    "kimlik 'product-card-P-001' içinde 'add-to-cart' (tried for 10 second(s))"
)
SAYFA = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <android.view.ViewGroup resource-id="product-card-P-001">
    <android.widget.Button resource-id="cart-add" text="Sepete ekle"/>
  </android.view.ViewGroup>
</hierarchy>"""
SEMBOLLER: dict[str, Any] = {
    "schema_version": 1,
    "lang": "java",
    "page_objects": [
        {
            "class": "KatalogEkrani",
            "file": "src/test/java/com/antreklabs/bayi/ekranlar/KatalogEkrani.java",
            "methods": [],
            "locators": {
                "Katalog.SEPETE_EKLE": {
                    "testId": "add-to-cart",
                    "role": "",
                    "name": "",
                    "intent": "Ürün kartında sepete ekleme butonu.",
                    "prefix": False,
                    "file": KIMLIKLER_G,
                },
                "Katalog.URUN_KARTI_ONEK": {
                    "testId": "product-card-",
                    "role": "",
                    "name": "",
                    "intent": "Tek bir ürünün kartı.",
                    "prefix": True,
                    "file": KIMLIKLER_G,
                },
            },
        }
    ],
    "errors": [],
}
ONERI: dict[str, Any] = {
    "locator_key": "Katalog.SEPETE_EKLE",
    "old_testid": "add-to-cart",
    "new_testid": "cart-add",
    "dosya": KIMLIKLER_G,
    "scope_test_id": "product-card-P-001",
    "platform": "android",
    "kaynak": "sayfa_kaynagi",
    "probe": {"olculen": "hata_ani_sayfa_kaynagi", "matches": 1, "test_id": "cart-add"},
    "sayfa_kaynagi": {
        "rel": "target/kanit/TPD1C3_0a1b2c3dTest.senaryo/sayfa-kaynagi.xml",
        "eski_var": False,
        "aday_sayisi": 1,
    },
}


def java_gecti(dosyalar: list[str]) -> dict[str, Any]:
    return {
        "conclusion": "success",
        "summary": "Yerel CI geçti",
        "lang": "java",
        "platform": "android",
        "saglik": {"ok": True},
        "app": {"ok": True},
        "deps": {"ok": True},
        "guard": {"ok": True, "mode": "repair"},
        "compile": {"ok": True},
        "run": {
            "run_id": f"run-{uuid.uuid4().hex[:6]}",
            "status": "passed",
            "saglik": {"ok": True},
            "tests": [{"title": "senaryo", "file": d, "status": "expected"} for d in dosyalar],
        },
        "test_counts": {"toplam": len(dosyalar), "expected": len(dosyalar)},
    }


@pytest.fixture(scope="session")
def app_bare(tmp_path_factory: pytest.TempPathFactory) -> Path:
    kok = tmp_path_factory.mktemp("repair-java-forge")
    work = kok / "work"
    shutil.copytree(
        REPO / "demo-app" / "e2e-app" / "src",
        work / "e2e-app" / "src",
    )
    git("init", "-q", "-b", "main", str(work))
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "demo-app e2e-app", cwd=work)
    bare = kok / "demo-app.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("push", "-q", str(bare), "main", cwd=work)
    return bare


class JavaToolchain:
    def __init__(self) -> None:
        self.istekler: list[tuple[str, dict[str, Any]]] = []
        self.ast: dict[str, Any] = {"ok": True, "violations": [], "mode": "repair"}
        # Cihaz koşusu tüm Java testlerini raporlar; biri yol biçiminde (Ş8 ikisini de verebilir).
        kok = REPO / "demo-app" / "e2e-app"
        self.dosyalar = sorted(
            locators.java_sinif_adi(p.relative_to(kok).as_posix())
            for p in (kok / "src" / "test" / "java").rglob("*.java")
            if p.name.endswith(("Test.java", "Testi.java"))
        )
        self.dosyalar[0] = "src/test/java/" + self.dosyalar[0].replace(".", "/") + ".java"

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.istekler.append((request.url.path, body))
        yol = request.url.path
        if yol == "/symbols":
            assert body.get("platform") == "android"
            return httpx.Response(200, json={"sha": body["sha"], **SEMBOLLER})
        if yol == "/ast-guard":
            return httpx.Response(200, json={**self.ast, "head_sha": body["head_sha"]})
        if yol == "/check":
            return httpx.Response(200, json={**java_gecti(self.dosyalar), "sha": body["sha"]})
        return httpx.Response(404, json={"detail": "yok"})


@pytest.fixture
def jortam(
    engine: Engine, app_bare: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    bare = tmp_path / "forge" / "demo-app.git"
    shutil.copytree(app_bare, bare)
    artifacts = tmp_path / "artifacts"
    (artifacts / "checks").mkdir(parents=True)
    monkeypatch.setenv("TP_ARTIFACTS_PATH", str(artifacts))
    monkeypatch.setenv("TP_FORGE", "local")
    monkeypatch.delenv("TP_FORGE_APP_ROOT", raising=False)
    get_settings.cache_clear()
    tc = JavaToolchain()
    forge = LocalForge(bare, artifacts)
    service.set_factories(
        forge=lambda: forge,
        toolchain=lambda: RepairToolchain(
            TOOLCHAIN, transport=httpx.MockTransport(tc.handler), check_timeout_s=30
        ),
        artifacts_root=lambda: artifacts,
    )
    import tp_core.features.ci as ci_mod

    monkeypatch.setattr(ci_mod, "enqueue_ci", lambda *a, **k: uuid.uuid4())
    yield {"tc": tc, "forge": forge, "artifacts": artifacts}
    service.reset_factories()
    get_settings.cache_clear()


def java_hata(
    engine: Engine,
    artifacts: Path,
    *,
    oneri: dict[str, Any] | None = None,
    sayfa: str | None = SAYFA,
) -> uuid.UUID:
    rid, fid = uuid.uuid4(), uuid.uuid4()
    dizin = f"runs/kirik-{rid.hex[:8]}"
    if sayfa is not None:
        p = artifacts / dizin / ONERI["sayfa_kaynagi"]["rel"]
        p.parent.mkdir(parents=True)
        p.write_text(sayfa, encoding="utf-8")
    with session_scope() as s:
        s.add(
            Run(
                id=rid,
                commit="c" * 40,
                kaynak="local",
                tetik="push",
                sonuc="failed",
                ortam={"saglik": {"ok": True}, "platform": "android"},
                artefaktlar={"dizin": dizin},
            )
        )
        s.flush()
        tr = TestResult(
            id=uuid.uuid4(),
            run_id=rid,
            test_adi="senaryo",
            dosya=SINIF,
            sonuc="failed",
            tetik="push",
            kaynak="local",
            hata_mesaji=MESAJ,
        )
        s.add(tr)
        s.flush()
        s.add(
            Failure(
                id=fid,
                run_id=rid,
                test_result_id=tr.id,
                test_adi="senaryo",
                hata_imzasi="locator_timeout · senaryo add-to-cart",
                sinif="test_maintenance",
                alt_tur="locator",
                eslesen_sinyaller=[{"kod": "locator_0_eleman", "aciklama": "0", "kaynak": "x"}],
                karar_kaynagi="rule",
                oneri_turu="locator_fix",
                oneri_durumu="proposed",
            )
        )
        s.flush()
        s.execute(
            text(
                "INSERT INTO failure_ek (failure_id, anahtar, oneri) "
                "VALUES (:f, :a, CAST(:o AS jsonb))"
            ),
            {"f": fid, "a": f"{rid}:{fid}", "o": json.dumps(oneri or ONERI)},
        )
    return fid


def _script(fid: uuid.UUID) -> Script:
    with session_scope() as s:
        sc = s.scalars(select(Script).where(Script.failure_id == fid)).one()
        s.expunge(sc)
        return sc


@pytest.fixture
def muhendis(api: Any, make_user: Any) -> Any:
    from tests.unit.features.cases.helpers import login

    u = make_user("engineer")
    login(api, u)
    return u


def test_java_mutlu_yol_yalnizca_kimlik_degeri(
    engine: Engine, jortam: dict[str, Any], api: Any, muhendis: Any
) -> None:
    fid = java_hata(engine, jortam["artifacts"])
    forge: LocalForge = jortam["forge"]
    main_once = forge.head_sha("main")
    r = api.post(f"/failures/{fid}/fix")
    assert r.status_code == 202, r.text
    assert [x.durum for x in run_jobs(engine)] == ["done"]
    sc = _script(fid)
    assert sc.durum == "pr_open", api.get(f"/failures/{fid}/fix").json().get("engel")
    assert sc.platform == "android" and sc.dosya_yolu == KIMLIKLER
    assert forge.changed_paths(main_once, sc.head_sha) == [KIMLIKLER]
    eski = forge.read_file(KIMLIKLER, main_once)
    yeni = forge.read_file(KIMLIKLER, sc.head_sha)
    assert yeni == eski.replace('SEPETE_EKLE = "add-to-cart";', 'SEPETE_EKLE = "cart-add";')
    pr = forge.get_pr(sc.pr_no)
    assert "Kimlikler.java" in pr.body and "sayfa kaynağı" in pr.body
    istek = dict(jortam["tc"].istekler)
    assert istek["/ast-guard"]["platform"] == "android"
    assert istek["/ast-guard"]["mode"] == "repair"
    assert istek["/check"]["platform"] == "android"
    assert istek["/check"]["ast_guard_mode"] == "repair"
    assert "/locator-probe" not in istek
    with session_scope() as s:
        kontrol = s.scalars(select(Run).where(Run.script_id == sc.id)).one()
        assert kontrol.ortam["platform"] == "android" and kontrol.sonuc == "passed"
    durum = api.get(f"/failures/{fid}/fix").json()
    assert durum["yerel_kontrol"]["etkilenen_kosuldu"] is True


def test_java_sayfa_kaynagi_oneriyle_celisirse_insana(
    engine: Engine, jortam: dict[str, Any], api: Any, muhendis: Any
) -> None:
    baska = SAYFA.replace("cart-add", "sepet-add-btn")
    fid = java_hata(engine, jortam["artifacts"], sayfa=baska)
    assert api.post(f"/failures/{fid}/fix").status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum in ("blocked", "failed") and sc.pr_no is None


def test_java_oneri_kaynagi_sayfa_kaynagi_degilse_insana(
    engine: Engine, jortam: dict[str, Any], api: Any, muhendis: Any
) -> None:
    fid = java_hata(engine, jortam["artifacts"], oneri={**ONERI, "kaynak": "locator_probe"})
    assert api.post(f"/failures/{fid}/fix").status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum in ("blocked", "failed") and sc.pr_no is None


def test_java_ast_ihlali_pr_acmaz(
    engine: Engine, jortam: dict[str, Any], api: Any, muhendis: Any
) -> None:
    jortam["tc"].ast = {
        "ok": False,
        "violations": [{"code": "non_testid_change", "message": "x"}],
        "mode": "repair",
    }
    fid = java_hata(engine, jortam["artifacts"])
    assert api.post(f"/failures/{fid}/fix").status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum in ("blocked", "failed") and sc.pr_no is None


# ----------------------------------------------------------------------------- saf yama


KAYNAK = """package com.antreklabs.bayi.ekranlar;

public final class Kimlikler {
  private Kimlikler() {}

  /** Katalog. */
  public static final class Katalog {
    // eski: public static final String SEPETE_EKLE = "x";
    /** Kart. */
    public static final String URUN_KARTI_ONEK = "product-card-";
    /** Sepete ekle. */
    public static final String SEPETE_EKLE = "add-to-cart";
  }

  /** Sepet. */
  public static final class Sepet {
    /** Toplam. */
    public static final String TOPLAM = "cart-total";
    public static final String SEPETE_EKLE = "add-to-cart";
  }
}
"""


def test_patch_kimlik_yalnizca_o_sabit() -> None:
    sonuc = locators.patch_kimlik(KAYNAK, "Katalog.SEPETE_EKLE", "add-to-cart", "cart-add")
    farkli = [
        (a, b) for a, b in zip(KAYNAK.splitlines(), sonuc.splitlines(), strict=True) if a != b
    ]
    assert farkli == [
        (
            '    public static final String SEPETE_EKLE = "add-to-cart";',
            '    public static final String SEPETE_EKLE = "cart-add";',
        )
    ]
    # Sepet grubundaki aynı adlı sabit dokunulmaz.
    assert sonuc.count('"add-to-cart"') == 1


@pytest.mark.parametrize(
    ("anahtar", "eski", "yeni", "hata"),
    [
        ("Katalog.URUN_KARTI_ONEK", "product-card-", "kart-", "önek"),
        ("Katalog.SEPETE_EKLE", "add-to-cart", "cart-total", "başka bir kimliğin"),
        ("Katalog.SEPETE_EKLE", "add-to-cart", "product-card-X", "öneki"),
        ("Katalog.SEPETE_EKLE", "yanlis", "cart-add", "değeri"),
        ("Katalog.YOK", "add-to-cart", "cart-add", "bulunamadı"),
        ("SEPETE_EKLE", "add-to-cart", "cart-add", "Grup.SABIT"),
        ("Katalog.SEPETE_EKLE", "add-to-cart", 'a"b', "geçersiz"),
        ("Katalog.SEPETE_EKLE", "add-to-cart", "add-to-cart", "aynı"),
    ],
)
def test_patch_kimlik_reddeder(anahtar: str, eski: str, yeni: str, hata: str) -> None:
    with pytest.raises(locators.PatchError, match=hata):
        locators.patch_kimlik(KAYNAK, anahtar, eski, yeni)


def test_patch_kimlik_unicode_kacisi_ve_kacisli_literal_reddedilir() -> None:
    with pytest.raises(locators.PatchError, match="Unicode"):
        locators.patch_kimlik(
            KAYNAK.replace("/** Toplam. */", "/** \\u0041 */"),
            "Katalog.SEPETE_EKLE",
            "add-to-cart",
            "cart-add",
        )
    kacisli = KAYNAK.replace(
        'SEPETE_EKLE = "add-to-cart";\n  }', 'SEPETE_EKLE = "add\\-to-cart";\n  }'
    )
    with pytest.raises(locators.PatchError):
        locators.patch_kimlik(kacisli, "Katalog.SEPETE_EKLE", "add-to-cart", "cart-add")


def test_java_sinif_adi_ve_etkilenen() -> None:
    assert locators.java_sinif_adi("e2e-app/src/test/java/com/x/YTest.java") == "com.x.YTest"
    assert locators.java_sinif_adi("com.x.YTest") == "com.x.YTest"
    loc = locators.find_locators(SEMBOLLER, "add-to-cart")[0]
    assert (loc.tam_ad, loc.sinif) == ("Katalog.SEPETE_EKLE", "KatalogEkrani")
    dosyalar = {
        "e2e-app/src/test/java/a/ATest.java": 'katalogEkrani().sepeteEkle("P-001", 1);',
        "e2e-app/src/test/java/a/BTest.java": 'girisEkrani().girisYap("a", "b");',
    }
    assert locators.etkilenen_java_testler(dosyalar, loc) == ["e2e-app/src/test/java/a/ATest.java"]
