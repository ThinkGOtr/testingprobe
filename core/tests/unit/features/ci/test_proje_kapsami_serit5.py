"""Şerit 5 proje kapsamı (TP-COK-PROJE-PLANI §3.3, §4.3, §4.4, §5.2): ayarlar bağlamdaki projeden,
açılış kancaları proje başına, toolchain `proje` bloğu, demo yalnız varsayılan projede.

DB'siz; şeridin `conftest`'i testleri `test-a` (varsayılan proje) bağlamında koşturur.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from tp_core.features.bugs import services as bug_services
from tp_core.features.ci import projeler
from tp_core.features.ci import service as ci_service
from tp_core.features.ci import services as ci_services
from tp_core.features.codegen.browser import AgentConfig
from tp_core.features.control_tower import service as ct_service
from tp_core.features.demo.api import varsayilan_projede
from tp_core.features.repair import views as repair_views
from tp_core.features.triage import services as triage_services
from tp_core.proje import mevcut_pid, proje_icinde, varsa
from tp_core.workflow.service import Principal

B = "test-b"


def _kullanici() -> Principal:
    return Principal(id=uuid.uuid4(), kullanici_adi="ali", rol="admin")


# ------------------------------------------------------------------ ayarlar proje başına


def test_ci_ayarlari_bagaldaki_projeden(proje_ayar: Any) -> None:
    proje_ayar(TP_FORGE="github", TP_CI_NIGHTLY_SAAT="03:30", TP_CI_NIGHTLY_GEC_S="60")
    proje_ayar(pid=B, TP_FORGE="local", TP_CI_NIGHTLY_SAAT="kapali")
    assert ci_services.mode() == "github"
    assert ci_service.nightly_saati() is not None
    assert ci_service.nightly_saati().hour == 3  # type: ignore[union-attr]
    assert ci_service.nightly_gecikme_siniri().total_seconds() == 60
    with proje_icinde(B, kaynak="test"):
        assert ci_services.mode() == "local"
        assert ci_service.nightly_saati() is None


def test_kosu_zaman_asimi_proje_ayari(proje_ayar: Any) -> None:
    proje_ayar(TP_CI_KOSU_ZAMAN_ASIMI_S="kapali")
    proje_ayar(pid=B, TP_CI_KOSU_ZAMAN_ASIMI_S="1200")
    assert ci_service.kosu_zaman_asimi_s() is None
    with proje_icinde(B, kaynak="test"):
        assert ci_service.kosu_zaman_asimi_s() == 1200


def test_triage_ve_kule_ayarlari(proje_ayar: Any) -> None:
    proje_ayar(pid=B, TP_TRIAGE_KIRMA="0", TP_TRIAGE_KIRMA_TASLAK="0", TP_CT_REVIEW_MIN_S="9")
    with proje_icinde(B, kaynak="test"):
        assert triage_services.kirma_triage() is False
        assert triage_services.kirma_taslak() is False
        assert ct_service._review_tabani_ms() == 9000


def test_kod_ve_pr_baglantilari_projenin_deposundan(proje_ayar: Any) -> None:
    proje_ayar(TP_FORGE="github", GITHUB_REPO="org/a")
    proje_ayar(pid=B, TP_FORGE="github", GITHUB_REPO="org/b")
    assert bug_services.code_url("x.ts", 3, "abc") == "https://github.com/org/a/blob/abc/x.ts#L3"
    assert repair_views.pr_web_url(7) == "https://github.com/org/a/pull/7"
    with proje_icinde(B, kaynak="test"):
        assert bug_services.code_url("x.ts", 3, "abc") == (
            "https://github.com/org/b/blob/abc/x.ts#L3"
        )
        assert repair_views.pr_web_url(7) == "https://github.com/org/b/pull/7"


def test_ajan_bayisi_proje_ayari(proje_ayar: Any) -> None:
    proje_ayar(pid=B, TP_DEMO_WEB_URL="http://b-web/", TP_AGENT_DEALER="bayi9")
    with proje_icinde(B, kaynak="test"):
        cfg = AgentConfig.from_env()
    assert (cfg.demo_web_url, cfg.agent_dealer) == ("http://b-web", "bayi9")
    # Açık eşlem (test/araç) ayara bakmaz.
    assert AgentConfig.from_env({"TP_AGENT_DEALER": "x"}).agent_dealer == "x"


# ------------------------------------------------------------------ açılış kancaları


def test_her_projede_baglam_varsa_tek_proje() -> None:
    gorulen: list[str] = []
    projeler.her_projede(None, lambda _c: gorulen.append(mevcut_pid()))  # type: ignore[arg-type]
    assert gorulen == ["test-a"]


def test_her_projede_baglamsizsa_aktif_projeler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(projeler, "kurulu_projeler", lambda _c: ["p1", "p2"])
    gorulen: list[tuple[str, str]] = []

    def kanca(_c: Any) -> None:
        b = varsa()
        assert b is not None
        gorulen.append((b.pid, b.kaynak))

    import contextvars

    contextvars.Context().run(projeler.her_projede, None, kanca)
    assert gorulen == [("p1", "sistem"), ("p2", "sistem")]


def test_her_projede_kayit_yoksa_varsayilan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(projeler, "kurulu_projeler", lambda _c: [])
    import contextvars

    gorulen: list[str] = []
    contextvars.Context().run(projeler.her_projede, None, lambda _c: gorulen.append(mevcut_pid()))
    assert gorulen == ["test-a"]


# ------------------------------------------------------------------ toolchain `proje` bloğu


def test_toolchain_blogu_yalniz_varsayilan_disi_projede(proje_ayar: Any) -> None:
    from tp_core.api.errors import ProjeAyariEksik

    assert projeler.toolchain_projesi({"sha": "x"}) == {"sha": "x"}  # varsayılan: bayt aynı
    # Varsayılan dışı projede ortam ayarı yoksa koşu 409 (toolchain env'e düşmez).
    with proje_icinde(B, kaynak="test"), pytest.raises(ProjeAyariEksik):
        projeler.toolchain_projesi({"sha": "x"})
    with proje_icinde(B, kaynak="test"):  # sembol/AST uçları ortam gerektirmez
        assert projeler.toolchain_govdesi("/symbols", {"sha": "x"})["proje"]["pid"] == B
    proje_ayar(pid=B, BASE_URL="http://b.test", DEMO_API_URL="http://b-api.test")
    with proje_icinde(B, kaynak="test"):
        govde = projeler.toolchain_projesi({"sha": "x"})
    assert govde["proje"]["pid"] == B
    assert govde["proje"]["base_url"] == "http://b.test"


# ------------------------------------------------------------------ demo yalnız varsayılan


def test_demo_varsayilan_proje_disinda_404() -> None:
    varsayilan_projede(_kullanici())  # test-a = varsayılan: geçer
    with proje_icinde(B, kaynak="test"), pytest.raises(HTTPException) as hata:
        varsayilan_projede(_kullanici())
    assert hata.value.status_code == 404
