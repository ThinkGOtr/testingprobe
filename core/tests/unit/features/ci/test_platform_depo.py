"""CI şeridi, platform başına depo (platform-depo ANALIZ §3.2 madde 8/11, Şerit T2).

- Koşunun deposu script'in kayıtlı deposudur (`run.ortam.depo`); aynı commit/PR numarası başka
  depoda ayrı koşudur (biri ötekini yutmaz).
- Gece koşusu ayrı depolu her etkin platformda ayrı tetiklenir: `run.ortam.platform` +
  `run.ortam.depo` yazılır (portal platform bazlı gece özeti); tetik anahtarı `@<depo>` ekli.
- `/runs` yanıtında `depo` / `depo_adi`; `depo` süzgeci.
- Koşunun forge / Actions istemcisi koşunun deposundan seçilir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA
from tp_core.features.ci import enqueue_ci, service, services
from tp_core.features.codegen import depo as depolar
from tp_core.models import Run, Script
from tp_core.models.ci_feature import CiTetik

MOBIL = "acme/mobil-android"


def _script(engine: Engine, platform: str, depo: str) -> uuid.UUID:
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(
            Script(
                id=sid,
                tur="test",
                dosya_yolu="e2e-app/src/test/java/XTest.java",
                platform=platform,
                depo=depo,
            )
        )
    return sid


def test_kosu_deposu_scriptin_kayitli_deposu(engine: Engine) -> None:
    # Aynı platform, aynı commit, aynı PR numarası; yalnız depo farklı → ayrı koşu.
    web = _script(engine, "android", "")
    mobil = _script(engine, "android", MOBIL)
    with Session(engine) as s, s.begin():
        r_web = enqueue_ci(s, SHA, "pr", 12, script_id=web)
        r_mobil = enqueue_ci(s, SHA, "pr", 12, script_id=mobil)
    assert r_web != r_mobil
    with Session(engine) as s:
        assert s.get(Run, r_web).ortam["depo"] == ""
        assert s.get(Run, r_mobil).ortam["depo"] == MOBIL
        assert service.kosu_deposu(s.get(Run, r_mobil)) == MOBIL
        # Eski kayıt (ortam.depo yok) → varsayılan depo.
        eski = Run(id=uuid.uuid4(), commit=SHA, kaynak="local", tetik="push", ortam={})
        assert service.kosu_deposu(eski) == ""


def test_ayni_depoda_ikinci_istek_etkin_kosuyu_doner(engine: Engine) -> None:
    mobil = _script(engine, "android", MOBIL)
    with Session(engine) as s, s.begin():
        a = enqueue_ci(s, SHA, "pr", 3, script_id=mobil)
        b = enqueue_ci(s, SHA, "pr", 3, script_id=mobil)
    assert a == b


def test_gece_kosusu_platform_depolarinda_ayri_tetiklenir(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TP_CI_NIGHTLY_SAAT", raising=False)
    monkeypatch.setattr(
        depolar, "ayri_depolu_platformlar", lambda: [("android", MOBIL), ("ios", "acme/ios")]
    )
    with services.override(now=lambda: datetime(2026, 10, 31, 23, 0, 5, tzinfo=UTC)):
        r1 = service.nightly_job(engine, "2026-11-01")
        r2 = service.nightly_job(engine, "2026-11-01")
    assert r1["yeni"] is True and r2["yeni"] is False
    assert [(k["platform"], k["depo"], k["yeni"]) for k in r1["platform_kosulari"]] == [
        ("android", MOBIL, True),
        ("ios", "acme/ios", True),
    ]
    assert all(k["yeni"] is False for k in r2["platform_kosulari"])  # idempotent
    with Session(engine) as s:
        runs = s.scalars(select(Run).where(Run.tetik == "nightly")).all()
        assert sorted((r.ortam["platform"], r.ortam["depo"]) for r in runs) == [
            ("android", MOBIL),
            ("ios", "acme/ios"),
            ("web", ""),
        ]
        anahtarlar = set(s.scalars(select(CiTetik.anahtar).where(CiTetik.tetik == "nightly")))
    assert anahtarlar == {
        "nightly:2026-11-01",
        f"nightly:2026-11-01:android@{MOBIL}",
        "nightly:2026-11-01:ios@acme/ios",
    }


def test_gece_platform_kosusu_acilamasa_da_varsayilan_kosu_acilir(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bozuk() -> list[tuple[str, str]]:
        raise RuntimeError("config okunamadı")

    monkeypatch.setattr(depolar, "ayri_depolu_platformlar", bozuk)
    with services.override(now=lambda: datetime(2026, 10, 31, 23, 0, 5, tzinfo=UTC)):
        r = service.nightly_job(engine, "2026-11-01")
    assert r["yeni"] is True and "platform_kosulari" not in r


def test_runs_listesi_depo_alanlari_ve_suzgec(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(depolar, "depo_adi", lambda d: d or "acme/demo-app")
    web = _script(engine, "web", "")
    mobil = _script(engine, "android", MOBIL)
    with Session(engine) as s, s.begin():
        enqueue_ci(s, SHA, "pr", 5, script_id=web)
        enqueue_ci(s, SHA, "pr", 5, script_id=mobil)
    with Session(engine) as s:
        hepsi = service.list_runs(s, pr_no=5, artefakt=True)
        assert sorted((k["platform"], k["depo"], k["depo_adi"]) for k in hepsi) == [
            ("android", MOBIL, MOBIL),
            ("web", "", "acme/demo-app"),
        ]
        yalniz = service.list_runs(s, pr_no=5, depo=MOBIL, artefakt=True)
        assert [k["depo"] for k in yalniz] == [MOBIL]


def test_kosunun_forge_ve_actions_istemcisi_deposundan(monkeypatch: pytest.MonkeyPatch) -> None:
    cagrilar: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        services.istemciler,
        "forge_depo",
        lambda depo, platform=None: cagrilar.append(("forge_depo", (depo, platform))) or "F",
    )
    monkeypatch.setattr(
        services.istemciler,
        "ci_depo",
        lambda depo, platform=None: cagrilar.append(("ci_depo", (depo, platform))) or "G",
    )
    run = Run(
        id=uuid.uuid4(),
        commit=SHA,
        kaynak="github",
        tetik="nightly",
        ortam={"platform": "android", "depo": MOBIL},
    )
    assert service.kosu_forge(run) == "F"
    assert service.kosu_github(run) == "G"
    assert cagrilar == [("forge_depo", (MOBIL, "android")), ("ci_depo", (MOBIL, "android"))]
