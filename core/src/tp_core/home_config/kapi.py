"""Proje özellik kapısı (UYGULAMA-PLANI-R1 §8): `web`, `android`, `ios`, `windows`, `ai_agent`.

Home config yokken (`CONFIG_SOURCE=env` ya da hiç yüklenemedi) her özellik açıktır (bugünkü
davranış). Kapalı platform isteği 409 `ozellik_kapali`; kapalı `ai_agent` uçları 404 (ekran yok).
"""

from __future__ import annotations

from fastapi import HTTPException

from tp_core.home_config import durum
from tp_core.workflow.service import WorkflowError

OZELLIK_ADI = {
    "web": "Web",
    "android": "Android",
    "ios": "iOS",
    "windows": "Windows",
    "ai_agent": "AI agent testi",
}


class OzellikKapali(WorkflowError):
    status_code = 409
    kod = "ozellik_kapali"


def ozellik_gerekli(ad: str) -> None:
    if not durum.ozellik_acik(ad):
        raise OzellikKapali(
            f"{OZELLIK_ADI.get(ad, ad)} bu projede kapalı; proje yöneticisi AI Probe'da "
            "proje özelliklerinden açabilir."
        )


def platform_gerekli(platform: str | None) -> None:
    ozellik_gerekli((platform or "web").strip().lower())


def ai_agent_gerekli() -> None:
    """Router bağımlılığı: `ai_agent` kapalıyken Agent Probe uçları yokmuş gibi (404)."""
    if not durum.ozellik_acik("ai_agent"):
        raise HTTPException(404, "Bulunamadı")
