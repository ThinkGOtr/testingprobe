"""Elle Sauce Labs turu (`tetik=sauce`): demo deposunun `sauce-demo.yml` iş akışına dispatch, tek
koşu (dil kardeşi yok), `sauce-results` artefaktından JUnit + platform satırları."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.unit.conftest import *  # noqa: F403
from tests.unit.features.ci.helpers import artefakt_kok, ci_env, run_jobs  # noqa: F401
from tests.unit.features.ci.test_github import REPO, FakeGitHub, _run, _zip
from tp_core.features.ci import service, services
from tp_core.models import Run, TestResult

JOB_A = "https://app.eu-central-1.saucelabs.com/tests/0123456789abcdef0123456789abcdef"
JOB_B = "https://app.eu-central-1.saucelabs.com/tests/fedcba9876543210fedcba9876543210"

SAUCE_JSON = {
    "schema_version": 2,
    "durum": "failed",
    "neden": None,
    "job_url": JOB_A,
    "platformlar": [
        {
            "platform": "web",
            "etiket": "Windows 11 · Edge",
            "durum": "passed",
            "toplam": 1,
            "gecen": 1,
            "basarisiz": 0,
            "atlanan": 0,
            "isler": [
                {"ad": "Windows-11-Edge", "url": JOB_A, "durum": "passed"},
                {"ad": "kötü", "url": "javascript:alert(1)"},
            ],
        },
        {
            "platform": "android",
            "etiket": "<script>",
            "durum": "failed",
            "toplam": 2,
            "gecen": True,
            "basarisiz": -3,
            "isler": [{"ad": "GirisTesti.dogruBilgilerleGiris", "url": JOB_B, "durum": "failed"}],
        },
        {"platform": "windows-wpf", "etiket": "x", "durum": "passed", "isler": []},
    ],
}
JUNIT = (
    '<testsuites><testsuite name="Windows 11 · Edge"><testcase name="[Windows 11 · Edge] sipariş" '
    'classname="order.spec.ts" time="3.2"/></testsuite><testsuite name="Android · emülatör">'
    '<testcase name="[Android · emülatör] dogruBilgilerleGiris" classname="com.x.GirisTesti" '
    'time="9">'
    '<failure message="öğe yok"/></testcase></testsuite></testsuites>'
)


@dataclass
class SauceGitHub(FakeGitHub):
    """`sauce-demo.yml` uçlarını ci.yml uçlarına eşler; `sauce-results` zip'i tur çıktısıdır."""

    sauce_istekleri: list[str] = field(default_factory=list)
    ci_istekleri: list[str] = field(default_factory=list)

    def handler(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        m = re.search(r"/actions/workflows/([a-z0-9-]+\.yml)/", p)
        if m and m.group(1) != "ci.yml":
            self.sauce_istekleri.append(p)
            req = httpx.Request(
                req.method,
                req.url.copy_with(path=p.replace(m.group(1), "ci.yml")),
                headers=req.headers,
                content=req.content,
            )
        elif "/actions/workflows/ci.yml/" in p:
            self.ci_istekleri.append(p)
        if req.url.host == "blob.example" and p.endswith("/sauce.zip"):
            return httpx.Response(
                200,
                content=_zip(
                    {"sauce.json": json.dumps(SAUCE_JSON).encode(), "junit.xml": JUNIT.encode()}
                ),
            )
        return super().handler(req)


@pytest.fixture
def sgh(engine, artefakt_kok):  # noqa: F811
    from tp_core.features.ci.clients import GitHubCi
    from tp_core.integrations.forge_github import GitHubForge, TokenAuth

    fake = SauceGitHub()
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


def test_sauce_turu_kendi_is_akisina_dispatch_ve_alim(engine, sgh: SauceGitHub) -> None:
    with Session(engine) as s, s.begin():
        sonuc = service.trigger_manual(s, "sauce", "muhendis")
    rid = sonuc["run_id"]
    assert sonuc["tetik"] == "sauce" and sonuc["test_ortami"] is None
    assert "Sauce Labs turu başlatıldı" in sonuc["mesaj"]
    run_jobs(engine)
    assert sgh.dispatchler == [
        ("workflow_dispatch", {"ref": "main", "inputs": {"tetik": "sauce", "istek_id": str(rid)}})
    ]
    assert any("sauce-demo.yml/dispatches" in p for p in sgh.sauce_istekleri)
    with Session(engine) as s:
        # Tek koşu: dil sabit ts, kardeş (Java) koşusu açılmaz.
        assert s.scalars(select(Run)).all() == [s.get(Run, rid)]
        assert (s.get(Run, rid).ortam or {}).get("dil") == "ts"
    sgh.wr(901, "workflow_dispatch", conclusion="failure", name=f"sauce-demo sauce [{rid}]")
    assert service.github_poll(engine, rid, 1)["durum"] == "failed"
    run = _run(engine, rid)
    assert run.tetik == "sauce" and run.github_run_id == "901"
    sauce = run.artefaktlar["sauce"]
    assert sauce["url"] == JOB_A and sauce["durum"] == "failed"
    assert not any("results.json" in u for u in run.artefaktlar["uyarilar"])
    pl = sauce["platformlar"]
    assert [(p["platform"], p["etiket"], p["durum"]) for p in pl] == [
        ("web", "Windows 11 · Edge", "passed"),
        ("android", "android", "failed"),  # güvensiz etiket → platform adı
    ]
    assert pl[0]["isler"] == [{"ad": "Windows-11-Edge", "url": JOB_A, "durum": "passed"}]
    assert pl[1]["gecen"] == 0 and pl[1]["basarisiz"] == 0 and pl[1]["toplam"] == 2
    with Session(engine) as s:
        testler = {
            t.test_adi: t.sonuc
            for t in s.scalars(select(TestResult).where(TestResult.run_id == rid))
        }
    assert testler == {
        "[Windows 11 · Edge] sipariş": "passed",
        "[Android · emülatör] dogruBilgilerleGiris": "failed",
    }


def test_sauce_turu_ikinci_tiklamada_yeni_kosu_acmaz(engine, sgh: SauceGitHub) -> None:
    with Session(engine) as s, s.begin():
        ilk = service.trigger_manual(s, "sauce", "muhendis")
    with Session(engine) as s, s.begin():
        ikinci = service.trigger_manual(s, "sauce", "muhendis")
    assert ikinci["durum"] == "zaten_kuyrukta" and ikinci["run_id"] == ilk["run_id"]


def test_sauce_turu_yerel_kipte_reddedilir(engine, ci_env) -> None:  # noqa: F811
    with (
        services.override(mode=lambda: "local"),
        Session(engine) as s,
        s.begin(),
        pytest.raises(service.CiError, match="GitHub kipinde"),
    ):
        service.trigger_manual(s, "sauce", "muhendis")


def test_sauce_is_akisi_check_ve_artefakt_adi() -> None:
    run = Run(tetik="sauce", ortam={"platform": "web", "dil": "ts"})
    assert service.gh_is_akisi(run) == {"workflow": "sauce-demo.yml"}
    assert service.gh_sonuc_artefakti(run) == "sauce-results"
    assert service.gh_check_adi(run) == "sauce"
    assert service.java_kosusu_mu(run) is False


def test_sauce_platformlari_guvenilmeyen_girdi() -> None:
    assert service.sauce_platformlari(None) == []
    assert service.sauce_platformlari([{"platform": "web"}] * 20)[0]["durum"] == "error"
    assert len(service.sauce_platformlari([{"platform": "web"}] * 20)) == 8
    p = service.sauce_platformlari(
        [{"platform": "ios", "etiket": "iOS · simülatör", "durum": "atlandi", "isler": "x"}]
    )
    assert p == [
        {
            "platform": "ios",
            "etiket": "iOS · simülatör",
            "durum": "atlandi",
            "neden": None,
            "toplam": 0,
            "gecen": 0,
            "basarisiz": 0,
            "atlanan": 0,
            "isler": [],
        }
    ]


def test_api_tetik_izni() -> None:
    from tp_core.features.ci import api

    assert api.tetik_izni("sauce") == "run.trigger_scheduled"
    assert api.tetik_izni("manual") == "run.trigger_manual"
    assert REPO  # aynı sahte depo


def test_ios_duman_kosusu_mobil_ios_kapsam_duman(engine, sgh: SauceGitHub) -> None:
    """Koşular › "iOS duman koşusu başlat": elle iOS koşusu, mobil-ios.yml `kapsam=duman`."""
    with Session(engine) as s, s.begin():
        sonuc = service.trigger_manual(s, "manual", "muhendis", platform="ios", kapsam="duman")
    rid = sonuc["run_id"]
    assert sonuc["kapsam"] == "duman" and "iOS duman koşusu" in sonuc["mesaj"]
    run_jobs(engine)
    assert sgh.dispatchler == [
        (
            "workflow_dispatch",
            {"ref": "main", "inputs": {"tetik": "manual", "istek_id": str(rid), "kapsam": "duman"}},
        )
    ]
    assert any("mobil-ios.yml/dispatches" in p for p in sgh.sauce_istekleri)
    with Session(engine) as s:
        o = s.get(Run, rid).ortam or {}
    assert o.get("platform") == "ios" and o.get("kapsam") == "duman"


def test_elle_web_kosusu_kapsam_gondermez(engine, sgh: SauceGitHub) -> None:
    with Session(engine) as s, s.begin():
        rid = service.trigger_manual(s, "manual", "muhendis")["run_id"]
    run_jobs(engine)
    assert sgh.dispatchler == [
        ("workflow_dispatch", {"ref": "main", "inputs": {"tetik": "manual", "istek_id": str(rid)}})
    ]


@pytest.mark.parametrize(
    ("tetik", "platform", "kapsam"),
    [
        ("nightly", "ios", "duman"),  # gece her zaman tam
        ("deploy", "ios", "duman"),
        ("manual", "android", "duman"),  # yalnız iOS
        ("manual", None, "duman"),
        ("manual", "ios", None),  # platform tek başına yok
        ("manual", "ios", "tam"),
    ],
)
def test_duman_kapsami_yalniz_elle_ios(engine, sgh: SauceGitHub, tetik, platform, kapsam) -> None:
    with Session(engine) as s, s.begin(), pytest.raises(service.CiError):
        service.trigger_manual(s, tetik, "muhendis", platform=platform, kapsam=kapsam)
