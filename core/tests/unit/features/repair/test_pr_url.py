"""Onarım PR'ının tarayıcı adresi (portal hata detayındaki PR bağlantısı)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tp_core.config import get_settings
from tp_core.features.repair.views import pr_web_url


@pytest.fixture(autouse=True)
def _temiz_ayar(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TP_DATABASE_URL", "postgresql+psycopg://u:p@localhost/x")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_github_kipinde_pr_adresi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_FORGE", "github")
    monkeypatch.setenv("GITHUB_REPO", "ThinkGOtr/testingprobe-demo-app")
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    assert pr_web_url(14) == "https://github.com/ThinkGOtr/testingprobe-demo-app/pull/14"


def test_enterprise_web_koku_api_adresinden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_FORGE", "github")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.ornek.com/api/v3")
    assert pr_web_url(3) == "https://ghe.ornek.com/org/repo/pull/3"


def test_yerel_forgeda_adres_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_FORGE", "local")
    assert pr_web_url(14) is None
