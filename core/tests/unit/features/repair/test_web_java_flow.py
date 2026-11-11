"""Web + Java (Playwright for Java; 011 üretim dili §2.8) locator onarımı: triage'ın hata anı DOM'u
önerisi (web yöntemi) → web + Java sembol tablosu (`lang=java, platform=web`) → `e2e-java`
Kimlikler.java'da yalnızca sabit değeri (Java yöntemi) → Java repair koruması → tam paket
`{lang: java, platform: web}` → bot PR. Appium (test_java_flow) ve TS (test_flow) akışları
değişmez."""

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
from tests.unit.features.repair.test_java_flow import (
    KIMLIKLER_G,
    SEMBOLLER,
    SINIF,
    JavaToolchain,
    java_gecti,
)
from tp_core.config import get_settings
from tp_core.features.repair import service
from tp_core.features.repair.prbody import pr_govdesi
from tp_core.features.repair.toolchain import RepairToolchain
from tp_core.integrations.forge_local import LocalForge
from tp_core.models import Failure, Run, Script, TestResult, session_scope

KIMLIKLER_W = f"e2e-java/{KIMLIKLER_G}"
MESAJ = (
    "com.microsoft.playwright.TimeoutError: Timeout 10000ms exceeded.\n"
    'waiting for getByTestId("product-card-P-001").getByTestId("add-to-cart")'
)
DOM_REL = "src/e2e-java/target/kanit/TPD1C3_0a1b2c3dTest.senaryo/sayfa.html"
DOM = """<html><body><article data-testid="product-card-P-001">
<button data-testid="cart-add">Sepete ekle</button></article></body></html>"""
ONERI: dict[str, Any] = {
    "locator_key": "Katalog.SEPETE_EKLE",
    "old_testid": "add-to-cart",
    "new_testid": "cart-add",
    "dosya": KIMLIKLER_G,
    "scope_test_id": "product-card-P-001",
    "platform": "web",
    "dil": "java",
    "kaynak": "hata_ani_dom",
    "url_path": "/katalog",
    "probe": {"olculen": "hata_ani_dom", "matches": 1, "test_id": "cart-add"},
    "dom": {"kaynak": "sayfa.html", "rel": DOM_REL, "eski_var": False, "aday_sayisi": 1},
}


class WebJavaToolchain(JavaToolchain):
    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.istekler.append((request.url.path, body))
        yol = request.url.path
        if yol == "/symbols":
            assert (body.get("lang"), body.get("platform")) == ("java", "web")
            return httpx.Response(200, json={"sha": body["sha"], **SEMBOLLER})
        if yol == "/ast-guard":
            return httpx.Response(200, json={**self.ast, "head_sha": body["head_sha"]})
        if yol == "/check":
            return httpx.Response(
                200, json={**java_gecti(self.dosyalar), "platform": "web", "sha": body["sha"]}
            )
        return httpx.Response(404, json={"detail": "yok"})


@pytest.fixture(scope="session")
def web_java_bare(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """e2e-java (Ş4) henüz bu worktree'de yok: aynı konvansiyonlu e2e-app kaynağı `e2e-java/`
    altına kopyalanır (paketler, `ekranlar/Kimlikler.java`, `uretilen/`, `testler/` aynı)."""
    kok = tmp_path_factory.mktemp("repair-web-java-forge")
    work = kok / "work"
    shutil.copytree(REPO / "demo-app" / "e2e-app" / "src", work / "e2e-java" / "src")
    git("init", "-q", "-b", "main", str(work))
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "e2e-java", cwd=work)
    bare = kok / "demo-app.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("push", "-q", str(bare), "main", cwd=work)
    return bare


@pytest.fixture
def wortam(
    engine: Engine, web_java_bare: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    bare = tmp_path / "forge" / "demo-app.git"
    shutil.copytree(web_java_bare, bare)
    artifacts = tmp_path / "artifacts"
    (artifacts / "checks").mkdir(parents=True)
    monkeypatch.setenv("TP_ARTIFACTS_PATH", str(artifacts))
    monkeypatch.setenv("TP_FORGE", "local")
    monkeypatch.delenv("TP_FORGE_APP_ROOT", raising=False)
    get_settings.cache_clear()
    tc = WebJavaToolchain()
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


def web_java_hata(
    artifacts: Path, *, oneri: dict[str, Any] | None = None, dom: str | None = DOM
) -> uuid.UUID:
    rid, fid = uuid.uuid4(), uuid.uuid4()
    dizin = f"runs/kirik-{rid.hex[:8]}"
    if dom is not None:
        p = artifacts / dizin / DOM_REL
        p.parent.mkdir(parents=True)
        p.write_text(dom, encoding="utf-8")
    with session_scope() as s:
        s.add(Run(id=rid, commit="c" * 40, kaynak="local", tetik="push", sonuc="failed",
                  ortam={"saglik": {"ok": True}, "platform": "web", "dil": "java"},
                  artefaktlar={"dizin": dizin}))  # fmt: skip
        s.flush()
        tr = TestResult(
            id=uuid.uuid4(), run_id=rid, test_adi="senaryo", dosya=SINIF, sonuc="failed",
            tetik="push", kaynak="local", hata_mesaji=MESAJ,
        )  # fmt: skip
        s.add(tr)
        s.flush()
        s.add(
            Failure(
                id=fid, run_id=rid, test_result_id=tr.id, test_adi="senaryo",
                hata_imzasi="locator_timeout · senaryo add-to-cart", sinif="test_maintenance",
                alt_tur="locator",
                eslesen_sinyaller=[{"kod": "locator_0_eleman", "aciklama": "0", "kaynak": "x"}],
                karar_kaynagi="rule", oneri_turu="locator_fix", oneri_durumu="proposed",
            )
        )  # fmt: skip
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


def test_web_java_mutlu_yol_kimlikler_e2e_java(
    engine: Engine, wortam: dict[str, Any], api: Any, muhendis: Any
) -> None:
    fid = web_java_hata(wortam["artifacts"])
    forge: LocalForge = wortam["forge"]
    main_once = forge.head_sha("main")
    r = api.post(f"/failures/{fid}/fix")
    assert r.status_code == 202, r.text
    assert [x.durum for x in run_jobs(engine)] == ["done"]
    sc = _script(fid)
    assert sc.durum == "pr_open", api.get(f"/failures/{fid}/fix").json().get("engel")
    assert sc.platform == "web" and sc.dosya_yolu == KIMLIKLER_W
    assert forge.changed_paths(main_once, sc.head_sha) == [KIMLIKLER_W]
    eski = forge.read_file(KIMLIKLER_W, main_once)
    yeni = forge.read_file(KIMLIKLER_W, sc.head_sha)
    assert yeni == eski.replace('SEPETE_EKLE = "add-to-cart";', 'SEPETE_EKLE = "cart-add";')
    pr = forge.get_pr(sc.pr_no)
    assert "Playwright for Java" in pr.body and "hata anı DOM'u" in pr.body
    istek = dict(wortam["tc"].istekler)
    for uc in ("/ast-guard", "/check"):
        assert (istek[uc]["lang"], istek[uc]["platform"]) == ("java", "web"), uc
    assert istek["/check"]["ast_guard_mode"] == "repair"
    assert "/locator-probe" not in istek and "/aria-match" not in istek
    with session_scope() as s:
        kontrol = s.scalars(select(Run).where(Run.script_id == sc.id)).one()
        assert (kontrol.ortam["platform"], kontrol.ortam["dil"]) == ("web", "java")
        assert kontrol.sonuc == "passed"
        # Web'de check adı dile bakmaz: koşunun kontrolü `local-ci`.
        assert kontrol.artefaktlar["checks"]["yol"].startswith("checks/")
    durum = api.get(f"/failures/{fid}/fix").json()
    assert durum["yerel_kontrol"]["etkilenen_kosuldu"] is True


def test_web_java_dom_oneriyle_celisirse_insana(
    engine: Engine, wortam: dict[str, Any], api: Any, muhendis: Any
) -> None:
    fid = web_java_hata(wortam["artifacts"], dom=DOM.replace("cart-add", "sepet-ekle-btn"))
    assert api.post(f"/failures/{fid}/fix").status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum in ("blocked", "failed") and sc.pr_no is None


def test_web_java_dom_onerisi_degilse_turkce_gerekceyle_insana(
    engine: Engine, wortam: dict[str, Any], api: Any, muhendis: Any
) -> None:
    """TS yolunun rol + ad yoklaması Java kimliklerinde yapılamaz: DOM'dan gelmeyen öneri
    (ör. eski kayıt / LLM) insana gider, PR açılmaz."""
    fid = web_java_hata(wortam["artifacts"], oneri={**ONERI, "kaynak": "locator_probe"})
    assert api.post(f"/failures/{fid}/fix").status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum in ("blocked", "failed") and sc.pr_no is None
    engel = api.get(f"/failures/{fid}/fix").json().get("engel") or {}
    assert "Playwright for Java" in str(engel.get("neden")) and "insan" in str(engel.get("neden"))
    assert not any(y == "/check" for y, _ in wortam["tc"].istekler)


def test_pr_govdesi_web_java_ve_appium_ayri() -> None:
    w = pr_govdesi({"platform": "web", "dil": "java"})
    a = pr_govdesi({"platform": "android"})
    t = pr_govdesi({"platform": "web"})
    assert "Playwright for Java" in w and "Aday (hata anı DOM'u)" in w
    assert "Uygulama (android)" in a and "Aday (hata anı sayfa kaynağı)" in a
    assert "locators.ts" in t and "çalışan uygulamada yoklama" in t
