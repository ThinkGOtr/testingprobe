"""GitHub koşu artefaktlarının yerel kopyası: alım, idempotens, yedek, zip-slip, saklama, sunum."""

from __future__ import annotations

import io
import json
import re
import stat
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import FIXTURES, SHA, login
from tp_core.features.ci import enqueue_ci, github_artifacts, service, services
from tp_core.features.ci.clients import GitHubCi
from tp_core.integrations.forge_github import GitHubForge, TokenAuth
from tp_core.models import Run, TestResult
from tp_core.models.ci_feature import TestResultEk

REPO = "acme/demo-app"
RUNNER_KOK = "/home/runner/work/demo-app/demo-app/tp-results"
EK = f"{RUNNER_KOK}/artifacts/cart"

RESULTS = {
    "stats": {"expected": 0, "unexpected": 1, "flaky": 0, "skipped": 0, "duration": 1500},
    "suites": [
        {
            "title": "cart.spec.ts",
            "file": "cart.spec.ts",
            "specs": [
                {
                    "title": "sepete ekler",
                    "file": "cart.spec.ts",
                    "line": 4,
                    "tests": [
                        {
                            "projectName": "chromium",
                            "status": "unexpected",
                            "results": [
                                {
                                    "retry": 0,
                                    "status": "failed",
                                    "duration": 1500,
                                    "error": {
                                        "message": "expect(locator).toBeVisible() failed",
                                        "stack": "Error: expect…\n    at cart.spec.ts:9:5",
                                        "location": {"file": "/w/cart.spec.ts", "line": 9},
                                    },
                                    "steps": [
                                        {"title": "Sepeti aç", "duration": 300},
                                        {
                                            "title": "Ürün ekle",
                                            "duration": 1200,
                                            "error": {"message": "görünmüyor"},
                                            "steps": [{"title": "Tıkla", "duration": 10}],
                                        },
                                    ],
                                    "stdout": [{"text": "merhaba\n"}],
                                    "stderr": [],
                                    "attachments": [
                                        {
                                            "name": "screenshot",
                                            "contentType": "image/png",
                                            "path": f"{EK}/test-failed-1.png",
                                        },
                                        {
                                            "name": "trace",
                                            "contentType": "application/zip",
                                            "path": f"{EK}/trace.zip",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ],
    "errors": [],
}


def _zip(dosyalar: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ad, icerik in dosyalar.items():
            zf.writestr(ad, icerik)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


def sonuc_zip(*, rapor: bool = True) -> bytes:
    """`test-local-results` (`.github/CI.md` "Artefakt sözleşmesi": düz kök)."""
    d = {
        "ci-meta.json": json.dumps(
            {
                "kaynak": "github",
                "tetik": "deploy",
                "sha": SHA,
                "event": "repository_dispatch",
                "durum": "failed",
                "exit_code": 1,
                "playwright": "1.64.1",
                "results_kok": RUNNER_KOK,
            }
        ).encode(),
        "junit.xml": (FIXTURES / "junit.xml").read_bytes(),
        "results.json": json.dumps(RESULTS).encode(),
        "allure-results/a-result.json": b"{}",
        "artifacts/cart/test-failed-1.png": b"\x89PNG",
        "artifacts/cart/trace.zip": b"PK",
        "run-checks.log": b"$ npx playwright test\n",
    }
    if rapor:
        d["playwright-report/index.html"] = b"<html><head></head>rapor</html>"
    return _zip(d)


@dataclass
class FakeGh:
    zipler: dict[str, bytes] = field(default_factory=dict)  # artefakt adı → zip
    indirilen: list[str] = field(default_factory=list)
    wid: int = 700

    def handler(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if req.url.host == "blob.example":
            ad = p.strip("/")
            self.indirilen.append(ad)
            return httpx.Response(200, content=self.zipler[ad])
        r = f"/repos/{REPO}/actions"
        if p == f"{r}/workflows/ci.yml/runs":
            return httpx.Response(200, json={"workflow_runs": [self._wr()]})
        if p == f"{r}/runs/{self.wid}/jobs":
            return httpx.Response(200, json={"jobs": [{"name": "test-local", "html_url": "x"}]})
        if p == f"{r}/runs/{self.wid}/artifacts":
            arts = [
                {"id": 50 + i, "name": ad, "size_in_bytes": len(self.zipler[ad]), "expired": False}
                for i, ad in enumerate(sorted(self.zipler))
            ]
            return httpx.Response(200, json={"artifacts": arts})
        if p == f"{r}/runs/{self.wid}":
            return httpx.Response(200, json=self._wr())
        m = re.fullmatch(rf"{r}/artifacts/(\d+)/zip", p)
        if m:
            ad = sorted(self.zipler)[int(m.group(1)) - 50]
            return httpx.Response(302, headers={"location": f"https://blob.example/{ad}"})
        return httpx.Response(404, json={"message": p})

    def _wr(self) -> dict[str, Any]:
        return {
            "id": self.wid,
            "event": "repository_dispatch",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": SHA,
            "html_url": f"https://github.com/{REPO}/actions/runs/{self.wid}",
            "created_at": "2099-01-01T00:00:00Z",
            "run_started_at": "2026-10-31T10:00:00Z",
            "updated_at": "2026-10-31T10:02:00Z",
            "run_attempt": 1,
            "pull_requests": [],
        }


@pytest.fixture
def gh(engine: Engine, artefakt_kok: Path, tmp_path: Path):
    fake = FakeGh()
    forge = GitHubForge(
        REPO,
        TokenAuth("gh-test-token"),
        api_url="https://api.github.test",
        transport=httpx.MockTransport(fake.handler),
    )
    with services.override(
        mode=lambda: "github",
        forge=lambda: forge,
        github=lambda: GitHubCi(forge),
        artifacts_root=lambda: artefakt_kok,
        github_artifacts_root=lambda: tmp_path / "gh-kopya",
    ):
        yield fake


def _al(engine: Engine, gh: FakeGh) -> uuid.UUID:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "push", None)
        s.get(Run, rid).github_run_id = str(gh.wid)
    assert service.github_poll(engine, rid, 0)["durum"] == "failed"
    return rid


def _detay(engine: Engine, rid: uuid.UUID) -> dict[str, Any]:
    with Session(engine) as s:
        return service.run_detail(s, rid, artefakt=True)


def test_raporlar_yerel_kopyadan_sunulur(engine: Engine, gh: FakeGh, tmp_path: Path) -> None:
    gh.zipler = {"test-local-results": sonuc_zip()}
    rid = _al(engine, gh)
    assert gh.indirilen == ["test-local-results"]  # ayrıştırma ve kopya için tek indirme
    d = _detay(engine, rid)
    kok = f"/runs/{rid}/src/e2e/results"
    assert d["github_artefakt"] == {"durum": "indirildi", "hata": None}
    assert d["artefakt_kok"] == f"/api/artifacts/runs/{rid}/"
    assert d["rapor_url"].endswith(f"{kok}/playwright-report/index.html")
    assert d["rapor_url"].startswith("/api/artifacts/")
    assert d["junit_url"] == f"/api/artifacts{kok}/junit.xml"
    assert d["allure_url"] == f"/api/artifacts{kok}/allure-results"  # Allure HTML yok: ham sonuç
    assert d["log_url"] == f"/api/artifacts{kok}/run-checks.log"
    assert d["ci_url"] == f"https://github.com/{REPO}/actions/runs/{gh.wid}"
    # Dosyalar ayrı volume'de, yerel koşu düzeninde; işaret dosyası gizli.
    yerel = tmp_path / "gh-kopya" / "gh" / f"{gh.wid}-1"
    assert (yerel / "src/e2e/results/junit.xml").is_file()
    assert (yerel / github_artifacts.ISARET).is_file()
    with Session(engine) as s:
        assert service.artifact_dir(s, rid) == yerel
    # Test ekleri (ekran görüntüsü, trace) yerel kopyaya eşlenir; adımlar/stack/stdout saklanır.
    t = next(x for x in d["sonuclar"] if x["test_adi"] == "sepete ekler")
    assert {e["ad"]: e["url"] for e in t["ekler"]} == {
        "screenshot": f"/api/artifacts{kok}/artifacts/cart/test-failed-1.png",
        "trace": f"/api/artifacts{kok}/artifacts/cart/trace.zip",
    }
    den = t["denemeler"][0]
    assert den["hata"]["stack"].startswith("Error: expect")
    assert den["hata"]["konum"] == "/w/cart.spec.ts:9"
    assert [a["baslik"] for a in den["adimlar"]] == ["Sepeti aç", "Ürün ekle"]
    assert den["adimlar"][1]["hata"] == "görünmüyor"
    assert den["adimlar"][1]["adimlar"][0]["baslik"] == "Tıkla"
    assert den["stdout"] == "merhaba\n"
    meta = d["github"]["meta"]
    assert (meta["durum"], meta["exit_code"], meta["playwright"]) == ("failed", "1", "1.64.1")


def test_api_yerel_kopyayi_oturumla_sunar(
    engine: Engine, gh: FakeGh, api: TestClient, make_user
) -> None:
    gh.zipler = {"test-local-results": sonuc_zip()}
    rid = _al(engine, gh)
    yol = f"/artifacts/runs/{rid}/src/e2e/results"
    assert api.get(f"{yol}/junit.xml").status_code == 401
    login(api, make_user("analyst"))
    r = api.get(f"{yol}/junit.xml")
    assert r.status_code == 200 and b"<testsuite" in r.content
    html = api.get(f"{yol}/playwright-report/index.html")
    assert html.status_code == 200 and "sandbox" in html.headers["content-security-policy"]
    assert b"localStorage" in html.content  # depo şimi playwright-report için de eklenir
    assert api.get(f"/artifacts/runs/{rid}/.tp-github.json").status_code == 400


def test_yeniden_indirme_yok_ve_geri_doldurma_idempotent(engine: Engine, gh: FakeGh) -> None:
    gh.zipler = {"test-local-results": sonuc_zip()}
    rid = _al(engine, gh)
    toplam = _detay(engine, rid)["toplam"]
    assert gh.indirilen == ["test-local-results"]
    with Session(engine) as s, s.begin():
        out = service.github_artefakt_indir(s, s.get(Run, rid), "operator")
    assert out["durum"] == "mevcut"
    assert gh.indirilen == ["test-local-results"]
    # İş yeniden denemesi (alım tekrar): raporlar diskten okunur, indirme yok.
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        s.query(TestResultEk).filter(
            TestResultEk.test_result_id.in_(select(TestResult.id).where(TestResult.run_id == rid))
        ).delete(synchronize_session=False)
        s.query(TestResult).filter(TestResult.run_id == rid).delete()
        service.github_ingest(s, run, gh._wr())
    assert gh.indirilen == ["test-local-results"]
    d = _detay(engine, rid)
    assert d["toplam"] == toplam and d["github_artefakt"]["durum"] == "mevcut"
    assert d["junit_url"].endswith("/src/e2e/results/junit.xml")


def test_once_alinmis_kosu_geri_doldurulur(engine: Engine, gh: FakeGh, tmp_path: Path) -> None:
    gh.zipler = {"test-local-results": sonuc_zip()}
    rid = _al(engine, gh)
    import shutil

    shutil.rmtree(tmp_path / "gh-kopya" / "gh")
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        run.artefaktlar = {k: v for k, v in run.artefaktlar.items() if k != "github_yerel"}
    assert _detay(engine, rid)["junit_url"] is None  # özellik öncesi alınmış koşu
    with Session(engine) as s, s.begin():
        out = service.github_artefakt_indir(s, s.get(Run, rid), "operator")
    assert out["durum"] == "indirildi"
    assert _detay(engine, rid)["junit_url"].endswith("/src/e2e/results/junit.xml")


def test_rapor_ayri_artefakttan_alinir(engine: Engine, gh: FakeGh) -> None:
    gh.zipler = {
        "test-local-results": sonuc_zip(rapor=False),
        "playwright-report": _zip({"index.html": b"<html>ayri</html>", "data/x.zip": b"PK"}),
    }
    rid = _al(engine, gh)
    assert sorted(gh.indirilen) == ["playwright-report", "test-local-results"]
    assert _detay(engine, rid)["rapor_url"].endswith(
        "/src/e2e/results/playwright-report/index.html"
    )


@pytest.mark.parametrize(
    "kotu",
    [
        _zip({"../../kacis.txt": b"x", "junit.xml": b"<testsuites/>"}),
        _zip({"junit.xml": b"<testsuites/>"}, symlink="artifacts/bag"),
    ],
    ids=["zip-slip", "sembolik-bag"],
)
def test_guvensiz_zip_github_baglantisina_duser(
    engine: Engine, gh: FakeGh, tmp_path: Path, kotu: bytes
) -> None:
    gh.zipler = {"test-local-results": kotu}
    rid = _al(engine, gh)  # alım düşmez
    d = _detay(engine, rid)
    assert d["github_artefakt"]["durum"] == "hata" and d["github_artefakt"]["hata"]
    assert d["rapor_url"] == f"https://github.com/{REPO}/actions/runs/{gh.wid}#artifacts"
    assert d["junit_url"] is None and d["artefakt_kok"] is None
    gh_kok = tmp_path / "gh-kopya" / "gh"
    assert not (tmp_path / "gh-kopya" / "kacis.txt").exists()
    assert not (tmp_path / "kacis.txt").exists()
    assert [p.name for p in gh_kok.iterdir()] == []  # yarım/geçici dizin kalmaz


def test_saklama_eski_kopyalari_siler_ve_isaretler(
    engine: Engine, gh: FakeGh, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TP_GITHUB_ARTIFACTS_KEEP", "1")
    gh.zipler = {"test-local-results": sonuc_zip()}
    r1 = _al(engine, gh)
    gh.wid = 701
    r2 = _al(engine, gh)
    assert not (tmp_path / "gh-kopya" / "gh" / "700-1").exists()
    assert (tmp_path / "gh-kopya" / "gh" / "701-1").is_dir()
    d1, d2 = _detay(engine, r1), _detay(engine, r2)
    assert d1["github_artefakt"]["durum"] == "budandi" and d1["junit_url"] is None
    assert d1["rapor_url"].startswith("https://github.com/")
    assert d2["github_artefakt"]["durum"] == "indirildi"


def test_cli_artefakt_indir(
    engine: Engine, gh: FakeGh, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tp_core.features.ci import __main__ as ci_cli

    gh.zipler = {"test-local-results": sonuc_zip()}
    rid = _al(engine, gh)
    assert ci_cli.main(["artefakt-indir", str(rid)[:13]]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["tamam"] and out["durum"] == "mevcut" and out["run_id"] == str(rid)
    assert gh.indirilen == ["test-local-results"]
    with Session(engine) as s, s.begin():
        yerel = Run(kaynak="local", tetik="push", sonuc="passed", commit=SHA)
        s.add(yerel)
        s.flush()
        yid = yerel.id
    assert ci_cli.main(["artefakt-indir", str(yid)]) == ci_cli.RED_KODU


def test_budama_disk_butcesini_asinca_en_eskiyi_siler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sayı sınırının altında olsa da toplam boyut bütçeyi aşarsa en eski kopyalar silinir."""
    import os
    import time as _time

    from tp_core.features.ci import github_artifacts as ga

    monkeypatch.setattr(ga, "kok", lambda: tmp_path)
    for i, ad in enumerate(("1-1", "2-1", "3-1")):
        d = tmp_path / "gh" / ad
        d.mkdir(parents=True)
        (d / "veri.bin").write_bytes(b"x" * 1000)
        os.utime(d, (_time.time() - 100 + i, _time.time() - 100 + i))
    silinen = ga.budama(en_cok=30, butce=2500)
    assert silinen == ["gh/1-1"]  # en eski; kalan iki kopya 2000 bayt ≤ 2500
    assert sorted(p.name for p in (tmp_path / "gh").iterdir()) == ["2-1", "3-1"]
    # Az önce hazırlanan (koru) bütçeyi aşsa da silinmez.
    assert ga.budama(koru=["gh/2-1"], en_cok=30, butce=500) == ["gh/3-1"]
