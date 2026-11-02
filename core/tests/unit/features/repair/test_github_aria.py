"""GitHub kipi son yeşil aria kanıtı: yeşil GitHub koşusunun koşu dizini yoktur; içe aktarımda
artefakttan alınan `run_aria` kopyası (0016) onarımın aria doğrulamasını taşır (add-to-cart →
cart-add). Snapshot'lar gerçek yeşil koşunun artefaktından (ci fikstürü `github_artifact_yesil`)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select

from tests.unit.features.repair.conftest import Ortam, kirik_hata, run_jobs
from tp_core.features.ci import service as ci_service
from tp_core.models import Run, Script, session_scope
from tp_core.models.ci_feature import RunAria

YESIL = Path(__file__).resolve().parents[1] / "ci" / "fixtures" / "github_artifact_yesil"


@pytest.fixture
def muhendis(api: Any, make_user: Any) -> Any:
    from tests.unit.features.cases.helpers import login

    u = make_user("engineer")
    login(api, u)
    return u


def _github_yesil_kosu(*, aria: bool = True) -> uuid.UUID:
    """Kırıktan önceki yeşil GitHub koşusu: `artefaktlar.dizin` yok (yerel koşu dizini yok)."""
    rid = uuid.uuid4()
    with session_scope() as s:
        run = Run(
            id=rid,
            commit="b" * 40,
            kaynak="github",
            github_run_id="41367656002",
            tetik="push",
            sonuc="passed",
            ortam={},
            artefaktlar={"ci_url": "https://github.com/o/r/actions/runs/41367656002"},
        )
        s.add(run)
        s.flush()
        if aria:
            dosyalar = {
                p.relative_to(YESIL).as_posix(): p.read_bytes()
                for p in YESIL.rglob("*")
                if p.is_file()
            }
            assert ci_service.aria_kaydet(s, run, dosyalar)["eklenen"] == 2
    return rid


def _script(fid: uuid.UUID) -> Script:
    with session_scope() as s:
        sc = s.scalars(select(Script).where(Script.failure_id == fid)).one()
        s.expunge(sc)
        return sc


def test_github_yesil_kosunun_db_aria_kopyasi_kanit(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yid = _github_yesil_kosu()
    fid = kirik_hata(engine)
    assert api.post(f"/failures/{fid}/fix").status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    blok = api.get(f"/failures/{fid}/fix").json()
    assert sc.durum == "pr_open", blok
    a = blok["aria"]
    assert (a["kaynak"], a["depo"]) == ("son_yesil_kosu", "run_aria")
    assert a["dosya"] == "katalog.aria.yml"
    assert a["run_id"] == str(yid) and a["gecerli"] is True
    yeni = ortam.forge.read_file("e2e/pages/catalog/locators.ts", sc.head_sha)
    assert 'testId: "cart-add"' in yeni and 'testId: "add-to-cart"' not in yeni


def test_github_yesil_kosuda_aria_kopyasi_yoksa_insana(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yid = _github_yesil_kosu(aria=False)
    fid = kirik_hata(engine)
    api.post(f"/failures/{fid}/fix")
    run_jobs(engine)
    assert _script(fid).durum == "blocked"
    engel = api.get(f"/failures/{fid}/fix").json()["engel"]
    assert engel["adim"] == "aria"
    assert f"son yeşil koşunun ({str(yid)[:8]}) aria snapshot'ı bulunamadı" in engel["neden"]
    assert "/ast-guard" not in ortam.toolchain.yollar()


def test_db_kopyasi_yanlis_elemani_dogrulamaz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    """DB kopyası da aynı doğrulamadan geçer: kart dışında ikinci "Sepete ekle" → çoklu → insan."""
    yid = _github_yesil_kosu()
    with session_scope() as s:
        for r in s.scalars(select(RunAria).where(RunAria.run_id == yid)):
            r.icerik += '- button "Sepete ekle"\n'
    fid = kirik_hata(engine)
    api.post(f"/failures/{fid}/fix")
    run_jobs(engine)
    assert _script(fid).durum == "blocked"
    assert api.get(f"/failures/{fid}/fix").json()["engel"]["adim"] == "aria"
