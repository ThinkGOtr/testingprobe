"""GitHub kipinde tutarlılık denetimi `demo-app/` altındaki kodu göreli yollarla görür."""

from __future__ import annotations

import pytest

from tp_core.features.requirements.approot import AppRootForge, app_root_view


class _Forge:
    def __init__(self) -> None:
        self.files = {
            "demo-app/api/src/demoapp_api/campaign.py": "x = 1\nbedava = 6\n",
            "demo-app/web/src/App.tsx": "bedava\n",
            ".github/workflows/ci.yml": "bedava\n",
        }

    def read_file(self, path: str, ref: str = "main") -> str:
        return self.files[path]

    def list_files(self, prefix: str = "", ref: str = "main") -> list[str]:
        return sorted(p for p in self.files if p.startswith(prefix))

    def search_code(self, query: str, ref: str = "main") -> list[tuple[str, int, str]]:
        return [
            (p, no, line)
            for p, text in sorted(self.files.items())
            for no, line in enumerate(text.splitlines(), 1)
            if query in line
        ]

    def head_sha(self, ref: str = "main") -> str:
        return "abc"


def test_okuma_koke_yonlenir_ve_onekli_yol_da_kabul_edilir() -> None:
    f = AppRootForge(_Forge(), "demo-app")
    assert f.read_file("api/src/demoapp_api/campaign.py").startswith("x = 1")
    assert f.read_file("demo-app/api/src/demoapp_api/campaign.py").startswith("x = 1")


def test_liste_ve_arama_koku_atar_ve_kok_disini_gizler() -> None:
    f = AppRootForge(_Forge(), "demo-app")
    assert f.list_files() == ["api/src/demoapp_api/campaign.py", "web/src/App.tsx"]
    assert f.list_files("api/") == ["api/src/demoapp_api/campaign.py"]
    assert f.search_code("bedava") == [
        ("api/src/demoapp_api/campaign.py", 2, "bedava = 6"),
        ("web/src/App.tsx", 1, "bedava"),
    ]


def test_diger_cagrilar_alttaki_forge_a_gider() -> None:
    assert AppRootForge(_Forge(), "demo-app").head_sha("main") == "abc"


@pytest.mark.parametrize(("kok", "sarili"), [("", False), ("demo-app", True)])
def test_gorunum_yalniz_kok_tanimliysa_sarar(
    monkeypatch: pytest.MonkeyPatch, kok: str, sarili: bool
) -> None:
    monkeypatch.setenv("TP_FORGE_APP_ROOT", kok)
    forge = _Forge()
    assert isinstance(app_root_view(forge), AppRootForge) is sarili
