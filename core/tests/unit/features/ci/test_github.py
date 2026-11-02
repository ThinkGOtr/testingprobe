"""GitHub kipi: aynı kod yolu; GitHub REST MockTransport + gerçek GitHubForge kimlik yardımcısı."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import FIXTURES, SHA, run_jobs
from tp_core.features.ci import enqueue_ci, service, services
from tp_core.features.ci.clients import GitHubCi, GitHubCiError
from tp_core.integrations.forge_github import GitHubForge, TokenAuth
from tp_core.models import ExternalRef, Job, Run, TestResult

REPO = "acme/demo-app"


def _zip(dosyalar: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ad, icerik in dosyalar.items():
            zf.writestr(ad, icerik)
    return buf.getvalue()


@dataclass
class FakeGitHub:
    runs: list[dict[str, Any]] = field(default_factory=list)
    istekler: list[httpx.Request] = field(default_factory=list)
    dispatchler: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    blob_auth: list[str | None] = field(default_factory=list)
    yorumlar: list[tuple[int, str]] = field(default_factory=list)
    yorum_hatasi: int | None = None  # PR yorumu ucunun döneceği hata kodu (None: 201)

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.istekler.append(req)
        p = req.url.path
        if req.url.host == "blob.example":
            self.blob_auth.append(req.headers.get("authorization"))
            if p.endswith("/sonuc.zip"):
                return httpx.Response(
                    200,
                    content=_zip(
                        {
                            "results/junit.xml": (FIXTURES / "junit.xml").read_bytes(),
                            "results/results.json": (FIXTURES / "results.json").read_bytes(),
                            "results/ci-meta.json": json.dumps(
                                {
                                    "kaynak": "github",
                                    "tetik": "pr",
                                    "sha": SHA,
                                    "event": "pull_request",
                                }
                            ).encode(),
                        }
                    ),
                )
            return httpx.Response(
                200,
                content=_zip(
                    {
                        "demo-app/results/sauce/saucectl-report.json": json.dumps(
                            {
                                "jobs": [
                                    {"url": "https://app.eu-central-1.saucelabs.com/tests/abc123"},
                                    {"url": "javascript:alert(1)"},
                                ]
                            }
                        ).encode()
                    }
                ),
            )
        assert req.headers["authorization"] == "Bearer gh-test-token"
        if p.startswith(f"/repos/{REPO}/issues/") and p.endswith("/comments"):
            if self.yorum_hatasi is not None:
                return httpx.Response(self.yorum_hatasi, json={"message": "yorum reddedildi"})
            self.yorumlar.append((int(p.split("/")[5]), json.loads(req.content)["body"]))
            return httpx.Response(201, json={"id": len(self.yorumlar)})
        if p == f"/repos/{REPO}/dispatches":
            self.dispatchler.append(("repository_dispatch", json.loads(req.content)))
            return httpx.Response(204)
        if p == f"/repos/{REPO}/actions/workflows/ci.yml/dispatches":
            self.dispatchler.append(("workflow_dispatch", json.loads(req.content)))
            return httpx.Response(204)
        if p == f"/repos/{REPO}/actions/workflows/ci.yml/runs":
            q = req.url.params
            secilen = [
                r
                for r in self.runs
                if (not q.get("event") or r["event"] == q["event"])
                and (not q.get("head_sha") or r["head_sha"] == q["head_sha"])
            ]
            return httpx.Response(200, json={"total_count": len(secilen), "workflow_runs": secilen})
        if p.startswith(f"/repos/{REPO}/actions/runs/"):
            parca = p.split("/")
            wid = int(parca[6])
            wr = next(r for r in self.runs if r["id"] == wid)
            if p.endswith("/jobs"):
                return httpx.Response(
                    200,
                    json={
                        "jobs": [
                            {
                                "name": "test-local",
                                "conclusion": wr.get("conclusion"),
                                "html_url": "https://github.com/j/1",
                            },
                            {
                                "name": "sauce",
                                "conclusion": "success",
                                "html_url": "https://github.com/j/2",
                            },
                        ]
                    },
                )
            if p.endswith("/artifacts"):
                return httpx.Response(
                    200,
                    json={
                        "artifacts": [
                            {
                                "id": 11,
                                "name": "test-local-results",
                                "size_in_bytes": 1000,
                                "expired": False,
                            },
                            {
                                "id": 12,
                                "name": "sauce-results",
                                "size_in_bytes": 100,
                                "expired": False,
                            },
                        ]
                    },
                )
            return httpx.Response(200, json=wr)
        if p == f"/repos/{REPO}/actions/artifacts/11/zip":
            return httpx.Response(302, headers={"location": "https://blob.example/sonuc.zip"})
        if p == f"/repos/{REPO}/actions/artifacts/12/zip":
            return httpx.Response(302, headers={"location": "https://blob.example/sauce.zip"})
        if p == f"/repos/{REPO}/commits/main":
            return httpx.Response(200, json={"sha": SHA})
        return httpx.Response(404, json={"message": f"yok: {p}"})

    def wr(
        self,
        wid: int,
        event: str,
        status: str = "completed",
        conclusion: str | None = "failure",
        **kw,
    ):
        r = {
            "id": wid,
            "event": event,
            "status": status,
            "conclusion": conclusion if status == "completed" else None,
            "head_sha": kw.pop("head_sha", SHA),
            "html_url": f"https://github.com/{REPO}/actions/runs/{wid}",
            "created_at": kw.pop("created_at", datetime.now(UTC).isoformat()),
            "run_started_at": "2026-10-31T10:00:00Z",
            "updated_at": "2026-10-31T10:02:30Z",
            "run_attempt": 1,
            "pull_requests": kw.pop("pull_requests", []),
            **kw,
        }
        self.runs = [x for x in self.runs if x["id"] != wid] + [r]
        return r


@pytest.fixture
def gh(engine: Engine, artefakt_kok, monkeypatch: pytest.MonkeyPatch):
    fake = FakeGitHub()
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
    ):
        yield fake


def _run(engine: Engine, rid: uuid.UUID) -> Run:
    with Session(engine) as s:
        return s.get(Run, rid)


def test_pr_kosusu_github_dan_alinir(engine: Engine, gh: FakeGitHub) -> None:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 5)
    assert _run(engine, rid).kaynak == "github"
    run_jobs(engine)  # ci.run → ci.github_poll(0): koşu henüz yok → yeniden planlandı
    with Session(engine) as s:
        assert (
            s.scalar(select(Job).where(Job.idempotency_key == f"ci.github_poll:{rid}:1"))
            is not None
        )
    assert _run(engine, rid).sonuc == "queued"
    # Başka PR'ın koşusu seçilmez; doğru PR koşusu sürüyor.
    gh.wr(100, "pull_request", status="in_progress", pull_requests=[{"number": 99}])
    gh.wr(101, "pull_request", status="in_progress", pull_requests=[{"number": 5}])
    assert service.github_poll(engine, rid, 1)["durum"] == "bekleniyor"
    run = _run(engine, rid)
    assert (run.sonuc, run.github_run_id) == ("running", "101")
    gh.wr(101, "pull_request", conclusion="failure", pull_requests=[{"number": 5}])
    assert service.github_poll(engine, rid, 2)["durum"] == "failed"
    run = _run(engine, rid)
    assert run.sonuc == "failed" and run.sure_ms == 150000
    a = run.artefaktlar
    assert a["ci_url"] == f"https://github.com/{REPO}/actions/runs/101"
    assert a["sauce"]["url"] == "https://app.eu-central-1.saucelabs.com/tests/abc123"
    assert a["sauce"]["urls"] == ["https://app.eu-central-1.saucelabs.com/tests/abc123"]
    assert a["github"]["meta"]["event"] == "pull_request"
    # Blob depolamasına yönlendirmede GitHub token'ı gönderilmez.
    assert gh.blob_auth and all(x is None for x in gh.blob_auth)
    with Session(engine) as s:
        rows = s.scalars(select(TestResult).where(TestResult.run_id == rid)).all()
        assert len(rows) == 9 and {r.kaynak for r in rows} == {"github"}
        detay = service.run_detail(s, rid)
    assert detay["sauce_url"].startswith("https://app.eu-central-1.saucelabs.com/")
    assert detay["rapor_url"] == f"https://github.com/{REPO}/actions/runs/101#artifacts"
    assert detay["artefakt_kok"] is None  # GitHub koşusunun yerel artefaktı yok
    # §8.5: sonuç + Sauce video/log bağlantısı PR yorumuna bir kez yazılır.
    assert len(gh.yorumlar) == 1
    pr, govde = gh.yorumlar[0]
    assert pr == 5
    assert service.PR_YORUM_ISARETI in govde and "CI sonucu: kaldı" in govde
    assert "test-local: failure" in govde
    assert f"https://github.com/{REPO}/actions/runs/101" in govde
    assert "Sauce Labs job'u: success" in govde
    assert "https://app.eu-central-1.saucelabs.com/tests/abc123" in govde
    assert "javascript:" not in govde
    # Tekrar yoklama (iş yeniden denemesi) ikinci yorum yazmaz.
    assert service.github_poll(engine, rid, 3)["durum"] == "atlandi"
    assert service.post_pr_comment(engine, rid) == "zaten"
    assert len(gh.yorumlar) == 1
    with Session(engine) as s:
        ref = s.scalar(
            select(ExternalRef).where(ExternalRef.idempotency_key == f"github:pr_comment:{rid}")
        )
        assert (ref.durum, ref.external_key) == ("created", "pr:5")


def test_pr_yorumu_hatasi_kosuyu_geri_almaz_ve_yeniden_denenir(
    engine: Engine, gh: FakeGitHub
) -> None:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 5)
    gh.wr(101, "pull_request", conclusion="success", pull_requests=[{"number": 5}])
    gh.yorum_hatasi = 422
    with pytest.raises(GitHubCiError, match="PR yorumu"):
        service.github_poll(engine, rid, 0)
    run = _run(engine, rid)
    assert run.sonuc == "passed"  # alım commit edildi
    assert gh.yorumlar == []
    # İş yeniden denenir: koşu bitmiş, yalnızca yorum yazılır.
    gh.yorum_hatasi = None
    assert service.github_poll(engine, rid, 0)["pr_yorumu"] == "yazildi"
    assert len(gh.yorumlar) == 1 and "CI sonucu: geçti" in gh.yorumlar[0][1]


def test_pr_disi_github_kosusu_yorum_yazmaz(engine: Engine, gh: FakeGitHub) -> None:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "push", None)
    gh.wr(102, "push", conclusion="success")
    assert service.github_poll(engine, rid, 0)["durum"] == "passed"
    assert gh.yorumlar == []


def test_deploy_repository_dispatch_bir_kez(engine: Engine, gh: FakeGitHub) -> None:
    with Session(engine) as s, s.begin():
        sonuc = service.trigger_manual(s, "deploy", "sunucu")
    rid = sonuc["run_id"]
    assert sonuc["kaynak"] == "github" and "repository_dispatch" in sonuc["mesaj"]
    run_jobs(engine)
    assert gh.dispatchler == [
        (
            "repository_dispatch",
            {"event_type": "deploy", "client_payload": {"tetik": "deploy", "tp_run_id": str(rid)}},
        )
    ]
    # Önceden oluşmuş (eski) deploy koşusu seçilmez; yenisi seçilir.
    eski = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    gh.wr(200, "repository_dispatch", conclusion="success", created_at=eski)
    gh.wr(201, "repository_dispatch", conclusion="success")
    assert service.github_poll(engine, rid, 1)["durum"] == "passed"
    assert len(gh.dispatchler) == 1  # yeniden yoklama dispatch'i tekrarlamaz
    assert _run(engine, rid).github_run_id == "201"
    with Session(engine) as s:
        ref = s.scalar(select(ExternalRef).where(ExternalRef.entity_id == rid))
        assert (ref.sistem, ref.durum) == ("github", "created")


def test_elle_gece_workflow_dispatch(engine: Engine, gh: FakeGitHub) -> None:
    with Session(engine) as s, s.begin():
        rid = service.trigger_manual(s, "nightly", "sunucu")["run_id"]
    run_jobs(engine)
    assert gh.dispatchler == [
        ("workflow_dispatch", {"ref": "main", "inputs": {"tetik": "nightly"}})
    ]
    gh.wr(300, "schedule", conclusion="success")  # zamanlanmış koşu elle tetiğe eşlenmez
    assert service.github_poll(engine, rid, 1)["durum"] == "bekleniyor"
    gh.wr(301, "workflow_dispatch", conclusion="success")
    assert service.github_poll(engine, rid, 2)["durum"] == "passed"


def test_cron_bekleyen_gece_kosusu_elle_tetiklenince_dispatch_edilir(
    engine: Engine, gh: FakeGitHub
) -> None:
    # Sistem gece koşusu GitHub cron'unu bekliyor (dispatch yok); sunucu elle tetikleyince aynı
    # kayıt tetiklemeye yükseltilir ve workflow_dispatch gider (yeni koşu açılmaz).
    rid = uuid.UUID(service.nightly_job(engine, "2026-11-02")["run_id"])
    run_jobs(engine)
    assert gh.dispatchler == []
    with Session(engine) as s, s.begin():
        sonuc = service.trigger_manual(s, "nightly", "sunucu")
    assert (sonuc["run_id"], sonuc["durum"]) == (rid, "queued")
    run_jobs(engine)
    assert gh.dispatchler == [
        ("workflow_dispatch", {"ref": "main", "inputs": {"tetik": "nightly"}})
    ]
    assert _run(engine, rid).ortam["dispatch"] == "nightly"
    with Session(engine) as s, s.begin():
        assert service.trigger_manual(s, "nightly", "sunucu")["durum"] == "zaten_kuyrukta"
    # Kayıt saatler önce açılmış olsa da süre sınırı ve eşleme dispatch anından sayılır.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE run SET olusturma = olusturma - interval '3 hours' WHERE id = :i"),
            {"i": rid},
        )
    gh.wr(301, "workflow_dispatch", conclusion="success")
    assert service.github_poll(engine, rid, 1)["durum"] == "passed"
    assert _run(engine, rid).github_run_id == "301"


def test_github_kosusu_bulunamazsa_sure_sonunda_error(engine: Engine, gh: FakeGitHub) -> None:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "push")
    run_jobs(engine)
    with services.override(now=lambda: datetime.now(UTC) + timedelta(hours=3)):
        assert service.github_poll(engine, rid, 5)["durum"] == "error"
    run = _run(engine, rid)
    assert run.sonuc == "error" and "bulunamadı" in run.artefaktlar["hata"]


def test_ayni_github_kosusu_iki_kayda_alinmaz(engine: Engine, gh: FakeGitHub) -> None:
    gh.wr(400, "push", conclusion="success")
    with Session(engine) as s, s.begin():
        r1 = enqueue_ci(s, SHA, "push")
    run_jobs(engine)  # ilk yoklamada tamamlanmış koşu bulunur ve alınır
    assert (_run(engine, r1).sonuc, _run(engine, r1).github_run_id) == ("passed", "400")
    with Session(engine) as s, s.begin():
        r2 = enqueue_ci(s, SHA, "push")
    run_jobs(engine)
    assert service.github_poll(engine, r2, 1)["durum"] == "bekleniyor"


def test_dispatch_sonrasi_arama_hatasi_tekrar_dispatch_etmez(
    engine: Engine, gh: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresyon: workflow_runs 5xx → iş yeniden denenir; deploy ikinci kez tetiklenmez."""
    with Session(engine) as s, s.begin():
        rid = service.trigger_manual(s, "deploy", "sunucu")["run_id"]
    asil = GitHubCi.workflow_runs
    sayac = {"n": 0}

    def bozuk(self, *a, **k):
        sayac["n"] += 1
        if sayac["n"] == 1:
            raise GitHubCiError("GitHub workflow koşuları: HTTP 502")
        return asil(self, *a, **k)

    monkeypatch.setattr(GitHubCi, "workflow_runs", bozuk)
    with pytest.raises(GitHubCiError):
        service.github_poll(engine, rid, 0)
    with Session(engine) as s:
        ref = s.scalar(select(ExternalRef).where(ExternalRef.entity_id == rid))
        assert ref.durum == "created"  # arama hatası dispatch kaydını geri almadı
    assert service.github_poll(engine, rid, 0)["durum"] == "bekleniyor"
    assert len(gh.dispatchler) == 1


def test_dispatch_cagrisi_kesin_hata_verirse_yeniden_dener(
    engine: Engine, gh: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as s, s.begin():
        rid = service.trigger_manual(s, "deploy", "sunucu")["run_id"]
    asil = GitHubCi.repository_dispatch

    def bozuk(self, *a, **k):
        raise GitHubCiError("GitHub repository_dispatch: HTTP 503")

    monkeypatch.setattr(GitHubCi, "repository_dispatch", bozuk)
    with pytest.raises(GitHubCiError):
        service.github_poll(engine, rid, 0)
    with Session(engine) as s:
        ref = s.scalar(select(ExternalRef).where(ExternalRef.entity_id == rid))
        assert (ref.durum, ref.hata is not None) == ("intent", True)
    monkeypatch.setattr(GitHubCi, "repository_dispatch", asil)
    service.github_poll(engine, rid, 0)
    assert len(gh.dispatchler) == 1  # ilk çağrı ulaşmadı; tek gerçek dispatch
    with Session(engine) as s:
        ref = s.scalar(select(ExternalRef).where(ExternalRef.entity_id == rid))
        assert (ref.durum, ref.hata) == ("created", None)
        assert s.get(Run, rid).ortam["dispatch_deneme"] == 2


def test_dispatch_yaniti_belirsizse_kor_tekrar_yok(
    engine: Engine, gh: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Çağrı GitHub'a ulaşıp yanıt kaybolduysa: önce koşu aranır, bekleme süresince tekrar yok."""
    with Session(engine) as s, s.begin():
        rid = service.trigger_manual(s, "deploy", "sunucu")["run_id"]
    asil = GitHubCi.repository_dispatch

    def ulasti_ama_zaman_asimi(self, *a, **k):
        asil(self, *a, **k)
        try:
            raise httpx.ReadTimeout("okuma zaman aşımı")
        except httpx.ReadTimeout as exc:
            raise GitHubCiError("GitHub repository_dispatch: ReadTimeout") from exc

    monkeypatch.setattr(GitHubCi, "repository_dispatch", ulasti_ama_zaman_asimi)
    with pytest.raises(GitHubCiError):
        service.github_poll(engine, rid, 0)
    with Session(engine) as s:
        ref = s.scalar(select(ExternalRef).where(ExternalRef.entity_id == rid))
        assert (ref.durum, ref.hata) == ("intent", None)
    # Koşu henüz görünmüyor, bekleme süresi dolmadı → yeniden dispatch yok.
    assert service.github_poll(engine, rid, 0)["durum"] == "bekleniyor"
    assert len(gh.dispatchler) == 1
    # Koşu göründü → dispatch "created" olarak kurtarılır, yine tekrar yok.
    gh.wr(501, "repository_dispatch", conclusion="success")
    assert service.github_poll(engine, rid, 1)["durum"] == "passed"
    assert len(gh.dispatchler) == 1
    with Session(engine) as s:
        ref = s.scalar(select(ExternalRef).where(ExternalRef.entity_id == rid))
        assert ref.durum == "created"


def test_dispatch_yaniti_belirsiz_ve_kosu_yoksa_sure_sonunda_yeniden(
    engine: Engine, gh: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as s, s.begin():
        rid = service.trigger_manual(s, "deploy", "sunucu")["run_id"]

    def kayip(self, *a, **k):
        raise GitHubCiError("GitHub repository_dispatch") from httpx.ConnectTimeout("t")

    asil = GitHubCi.repository_dispatch
    monkeypatch.setattr(GitHubCi, "repository_dispatch", kayip)
    with pytest.raises(GitHubCiError):
        service.github_poll(engine, rid, 0)
    monkeypatch.setattr(GitHubCi, "repository_dispatch", asil)
    with services.override(now=lambda: datetime.now(UTC) + timedelta(seconds=400)):
        service.github_poll(engine, rid, 0)
    assert len(gh.dispatchler) == 1  # ilki hiç ulaşmadı; süre dolunca bir kez gönderildi
