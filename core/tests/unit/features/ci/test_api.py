"""CI HTTP uçları: /ci/trigger, /runs, /runs/{id}, /artifacts/runs/... (oturum, rol, yol)."""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA, FakeToolchain, login, run_jobs
from tp_core.features.ci import enqueue_ci

pytestmark = pytest.mark.usefixtures("ci_env")


def _kosu(engine: Engine) -> uuid.UUID:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 3)
    run_jobs(engine)
    return rid


def test_trigger_yalniz_sunucu_ve_tekrari_kuyrukta(api: TestClient, make_user, engine) -> None:
    analist = make_user("analyst")
    login(api, analist)
    r = api.post("/ci/trigger", json={"tetik": "deploy"})
    assert r.status_code == 403
    api.post("/auth/logout")
    login(api, make_user("presenter"))
    assert api.post("/ci/trigger", json={"tetik": "push"}).status_code == 422
    r = api.post("/ci/trigger", json={"tetik": "deploy"})
    assert r.status_code == 202, r.text
    b = r.json()
    assert b["durum"] == "queued" and b["kaynak"] == "local" and b["job_id"] and b["run_id"]
    r2 = api.post("/ci/trigger", json={"tetik": "deploy"})
    assert r2.json()["durum"] == "zaten_kuyrukta" and r2.json()["run_id"] == b["run_id"]
    r3 = api.post("/ci/trigger", json={"tetik": "nightly"})
    assert r3.json()["run_id"] != b["run_id"]


def test_runs_listesi_ve_detay(
    api: TestClient, make_user, engine: Engine, toolchain: FakeToolchain
) -> None:
    rid = _kosu(engine)
    assert api.get("/runs").status_code == 401
    login(api, make_user("analyst"))
    liste = api.get("/runs").json()
    k = next(x for x in liste if x["id"] == str(rid))
    assert (k["tetik"], k["kaynak"], k["durum"], k["pr_no"]) == ("pr", "local", "failed", 3)
    assert (k["toplam"], k["gecen"], k["basarisiz"], k["flaky"], k["atlanan"]) == (9, 4, 3, 1, 1)
    # HTML raporu imzalı, süreli yoldan (sandbox'lı raporun çerezsiz alt istekleri için).
    assert re.fullmatch(
        rf"/api/artifacts/k/\d+\.[A-Za-z0-9_-]{{43}}/runs/{rid}/src/e2e/results/html/index\.html",
        k["rapor_url"],
    )
    assert k["junit_url"] == f"/api/artifacts/runs/{rid}/src/e2e/results/junit.xml"
    # Okunur Allure raporu birincil; ham allure-results ikincil bağlantı.
    assert k["allure_url"] == f"/api/artifacts/runs/{rid}/src/e2e/results/allure-report/index.html"
    assert k["allure_rapor"] is True
    assert k["allure_sonuclari_url"] == f"/api/artifacts/runs/{rid}/src/e2e/results/allure-results"
    rapor = api.get(k["allure_url"].removeprefix("/api"))
    assert rapor.status_code == 200 and "sandbox" in rapor.headers["content-security-policy"]
    assert "allow-same-origin" not in rapor.headers["content-security-policy"]
    # Opak kökende localStorage SecurityError atar: rapora bellek içi depo şimi eklenir.
    assert rapor.text.startswith("<html><script>(function(){function m()") is False
    assert "Object.defineProperty(window,n" in rapor.text and rapor.text.endswith("allure</html>")
    assert k["break_campaign"] is False and k["saglik_hatasi"] is None
    assert api.get("/runs", params={"tetik": "nightly"}).json() == []
    assert len(api.get("/runs", params={"kaynak": "local"}).json()) == 1
    assert api.get("/runs", params={"tetik": "yok"}).status_code == 422

    d = api.get(f"/runs/{rid}").json()
    t = {x["test_adi"]: x for x in d["sonuclar"]}
    alti = t["TPD-1 › 6 adet → bedava yok"]
    assert alti["durum"] == "failed" and alti["retry"] == 1
    # Faz 4: kırmızı koşu triage'a gider; worker işledikten sonra failure_id + sınıf dolar.
    if alti["failure_id"] is not None:
        assert alti["triage_sinifi"] is not None
        assert alti["failure_id"] in {h["id"] for h in d["hatalar"]}
    assert [e["url"] for e in alti["ekler"]] == [
        f"/api/artifacts/runs/{rid}/src/e2e/results/artifacts/kampanya-6/test-failed-1.png",
        f"/api/artifacts/runs/{rid}/src/e2e/results/artifacts/kampanya-6/trace.zip",
    ]
    zaman = t["Sipariş › onay numarası"]
    assert (zaman["durum"], zaman["ham_durum"]) == ("failed", "timedout")
    assert t["Erişilebilirlik @a11y › katalog sayfası"]["a11y"]["ihlal"] == 2
    assert d["adimlar"]["tsc"]["ok"] is True
    assert api.get(f"/runs/{uuid.uuid4()}").status_code == 404


def test_artefakt_ucu_oturumlu_ve_yol_dogrulamali(
    api: TestClient, make_user, engine: Engine, artefakt_kok: Path
) -> None:
    rid = _kosu(engine)
    temel = f"/artifacts/runs/{rid}"
    assert api.get(f"{temel}/src/e2e/results/junit.xml").status_code == 401
    login(api, make_user("tester"))
    r = api.get(f"{temel}/src/e2e/results/junit.xml")
    assert r.status_code == 200 and b"<testsuites" in r.content
    assert r.headers["x-content-type-options"] == "nosniff"
    html = api.get(f"{temel}/src/e2e/results/html/index.html")
    assert html.status_code == 200
    assert "sandbox" in html.headers["content-security-policy"]
    zip_ = api.get(f"{temel}/src/e2e/results/artifacts/kampanya-6/trace.zip")
    assert zip_.headers["content-disposition"].startswith("attachment")
    liste = api.get(f"{temel}/src/e2e/results/allure-results").json()
    assert [d["ad"] for d in liste["dosyalar"]] == ["x-result.json"]
    assert api.get(f"{temel}/runner.log").status_code == 200
    # Kaynak kod, gizli dosya, üst dizin, mutlak yol: reddedilir.
    assert api.get(f"{temel}/src/e2e/tests/gizli.spec.ts").status_code == 400
    assert api.get(f"{temel}/src/e2e/results/%2e%2e/tests/gizli.spec.ts").status_code in (400, 404)
    assert api.get(f"{temel}/src/e2e/results/..%2F..%2Frun.json").status_code in (400, 404)
    assert api.get(f"{temel}/src/e2e/results/yok.xml").status_code == 404
    # Koşu dizininden dışarı işaret eden symlink.
    dizin = artefakt_kok / "runs" / f"ci-{rid}-1" / "src" / "e2e" / "results"
    (artefakt_kok / "gizli.txt").write_text("sır")
    os.symlink(artefakt_kok / "gizli.txt", dizin / "kacak.txt")
    assert api.get(f"{temel}/src/e2e/results/kacak.txt").status_code == 400
    assert api.get(f"/artifacts/runs/{uuid.uuid4()}/run.json").status_code == 404


def test_imzali_rapor_baglantisi_cerezsiz_ve_sinirli(
    api: TestClient, make_user, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sandbox'lı Playwright raporu (köken `null`, çerez yok) ekran görüntüsünü ve ekleri imzalı
    önekle yükler; imza tek koşuya bağlı ve süreli, izinli alt ağaç aynıdır."""
    from tp_core.features.ci import artifacts

    rid = _kosu(engine)
    diger = _kosu_baska(engine)
    login(api, make_user("tester"))
    rapor = next(x for x in api.get("/runs").json() if x["id"] == str(rid))["rapor_url"]
    onek = rapor.removeprefix("/api").removesuffix("src/e2e/results/html/index.html")
    api.cookies.clear()  # rapor opak kökende: çerez gönderilmez
    html = api.get(rapor.removeprefix("/api"))
    assert html.status_code == 200
    assert html.headers["content-security-policy"].startswith("sandbox ")
    assert "access-control-allow-origin" not in html.headers  # HTML'e CORS yok
    assert html.headers["referrer-policy"] == "no-referrer"
    assert (
        "Object.defineProperty(window,n" in html.text
    )  # nginx regex'i bu yolu görmez: şim core'da
    png = api.get(f"{onek}src/e2e/results/artifacts/kampanya-6/test-failed-1.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in png.headers
    # İzinli alt ağaç dışı yine reddedilir.
    assert api.get(f"{onek}src/e2e/tests/gizli.spec.ts").status_code == 400
    # İmza başka koşuda geçmez; bozuk / süresi dolmuş imza 403.
    tok = onek.split("/")[3]
    assert api.get(f"/artifacts/k/{tok}/runs/{diger}/run.json").status_code == 403
    bozuk = tok[:-2] + ("AA" if not tok.endswith("AA") else "BB")
    assert api.get(f"/artifacts/k/{bozuk}/runs/{rid}/run.json").status_code == 403
    assert api.get(f"/artifacts/k/yok/runs/{rid}/run.json").status_code == 403
    eski = artifacts.link_token(uuid.UUID(str(rid)), time.time() - 3 * 7200)
    assert api.get(f"/artifacts/k/{eski}/runs/{rid}/run.json").status_code == 403
    # Oturum sırrı yoksa imzalı bağlantı üretilmez (oturumlu yol).
    monkeypatch.setattr(artifacts, "_imza_anahtari", lambda: None)
    with Session(engine) as s:
        from tp_core.features.ci import service

        k = service.list_runs(s)
    assert next(x for x in k if x["id"] == str(rid))["rapor_url"] == (
        f"/api/artifacts/runs/{rid}/src/e2e/results/html/index.html"
    )


def _kosu_baska(engine: Engine) -> uuid.UUID:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 4)
    run_jobs(engine)
    return rid
