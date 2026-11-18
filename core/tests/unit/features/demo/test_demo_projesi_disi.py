"""TP3-1: demo projesi olmayan projede `/demo/status` 404 değil "demo yok" durumu döner."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tp_core.features.demo import api
from tp_core.workflow.service import Principal


def test_baska_projede_durum_demo_yok_doner(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(ortam="test", demo_mode=True))
    monkeypatch.setattr(api, "varsayilan_pid", lambda: "varsayilan")
    user = Principal(id=None, kullanici_adi="u", rol="admin", project_id="baska-proje")
    d = api.status(user)
    assert d["demo_modu"] is False and d["demo_projesi"] is False
    assert "forge" not in d


def test_baska_projede_yazan_uclar_yine_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "varsayilan_pid", lambda: "varsayilan")
    user = Principal(id=None, kullanici_adi="u", rol="admin", project_id="baska-proje")
    with pytest.raises(HTTPException) as e:
        api.demo_okuru(user)
    assert e.value.status_code == 404
