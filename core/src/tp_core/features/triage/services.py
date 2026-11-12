"""Triage şeridinin dış bağımlılık fabrikaları (testler `override` ile değiştirir; kod yolu aynı).

- `toolchain()`: toolchain-worker istemcisi (`/symbols`, `/locator-probe`).
- `gateway(engine)`: model geçidi (yalnızca core-worker'da çağrılır; kural eşleşmezse).
- `artifacts_root()`: `TP_ARTIFACTS_PATH` (core-worker salt okur).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Engine

from tp_core.config import get_settings

_overrides: dict[str, Callable[..., Any]] = {}

SYMBOLS_TIMEOUT_S = 120.0
PROBE_TIMEOUT_S = 90.0


class ToolchainHatasi(RuntimeError):
    def __init__(self, mesaj: str, status: int | None = None) -> None:
        super().__init__(mesaj)
        self.status = status


class TriageToolchain:
    """toolchain-worker HTTP API'si (MIMARI-SOZLESME §2): `/symbols` ve `/locator-probe`."""

    def __init__(
        self, base_url: str, *, token: str = "", transport: httpx.BaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else None
        self._transport = transport

    def _post(self, yol: str, govde: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            with httpx.Client(
                transport=self._transport, timeout=timeout, headers=self._headers
            ) as c:
                r = c.post(f"{self.base_url}{yol}", json=govde)
        except httpx.HTTPError as exc:
            raise ToolchainHatasi(f"toolchain-worker'a ulaşılamadı: {type(exc).__name__}") from exc
        try:
            veri = r.json()
        except ValueError:
            veri = None
        if r.status_code >= 400:
            detay = veri.get("detail") if isinstance(veri, dict) else None
            raise ToolchainHatasi(
                f"toolchain-worker {yol} HTTP {r.status_code}: {detay or r.text[:200]}",
                r.status_code,
            )
        if not isinstance(veri, dict):
            raise ToolchainHatasi(f"toolchain-worker {yol}: yanıt nesne değil", r.status_code)
        return veri

    def symbols(
        self, sha: str, *, platform: str | None = None, lang: str | None = None
    ) -> dict[str, Any]:
        """`platform` (android | ios | windows) → Java sembol tablosu (009 §2.5); web/None → TS.
        `lang="java"` + web → web + Java (`e2e-java`) sembol tablosu (011 §2.6)."""
        govde: dict[str, Any] = {"sha": sha}
        if lang == "java" and (platform or "web") == "web":
            govde["lang"] = "java"
            govde["platform"] = "web"
        elif platform and platform != "web":
            govde["platform"] = platform
        return self._post("/symbols", govde, SYMBOLS_TIMEOUT_S)

    def locator_probe(
        self, sha: str, role: str, name: str, url_path: str, scope_test_id: str | None
    ) -> dict[str, Any]:
        govde: dict[str, Any] = {"sha": sha, "role": role, "name": name, "url_path": url_path}
        if scope_test_id:
            govde["scope_test_id"] = scope_test_id
        return self._post("/locator-probe", govde, PROBE_TIMEOUT_S)


def toolchain() -> Any:
    f = _overrides.get("toolchain")
    if f is not None:
        return f()
    s = get_settings()
    return TriageToolchain(s.toolchain_url, token=s.toolchain_token)


def gateway(engine: Engine) -> Any:
    f = _overrides.get("gateway")
    if f is not None:
        return f(engine)
    from tp_core.audit import PgCallRecorder
    from tp_core.gateway import build_gateway

    return build_gateway(PgCallRecorder(engine), engine=engine)


def artifacts_root() -> Path:
    f = _overrides.get("artifacts_root")
    if f is not None:
        return Path(f())
    return Path(get_settings().artifacts_path)


def sweep_s() -> float:
    """Süpürme aralığı (`TP_TRIAGE_SWEEP_S`, 30 sn; 0 = kapalı)."""
    f = _overrides.get("sweep_s")
    if f is not None:
        return float(f())
    try:
        return max(float((os.environ.get("TP_TRIAGE_SWEEP_S") or "30").strip()), 0.0)
    except ValueError:
        return 30.0


def kirma_triage() -> bool:
    """Kasıtlı kırılma (`BREAK_CAMPAIGN`) koşularının kırmızısı triage'a girer mi?

    Varsayılan evet (`TP_TRIAGE_KIRMA=1`): kırma koşusunun kampanya kırmızısı `product_defect` +
    `kasitli_kirilma` olarak sınıflandırılır (hata yakalama kanıtı); bug taslağı ayrıca
    `kirma_taslak` ile yönetilir (varsayılan kapalı). `0` yalnızca kod üretimi kanıtı sayar.
    """
    f = _overrides.get("kirma_triage")
    if f is not None:
        return bool(f())
    return (os.environ.get("TP_TRIAGE_KIRMA") or "1").strip() not in ("0", "false", "hayir")


def kirma_taslak() -> bool:
    """Kasıtlı kırılma koşusunun `product_defect`'i için bug taslağı istenir mi?

    Varsayılan EVET (`TP_TRIAGE_KIRMA_TASLAK=1`): bağlayıcı tasarım (TEKNİK-TASARIM §2 "Demoda iki
    kırılma senaryosu", DEMO-VERISI "Faz 4: kırma koşusu") kırma kırmızısının triage → mükerrer
    kontrolü → taslak → testçi onayı yolunu gösterir; taslak Jira'ya ancak testçi kararıyla yazılır
    (insan kapısı). Sahnede bu taslak bilerek karara bırakılır (yol haritası adım 13 saymaz).
    `0` bu taslakları kapatır: failure yine `product_defect` + `kasitli_kirilma` sinyaliyle
    kaydedilir (hata yakalama kanıtı), `oneri_turu='none'` + `jira_yazilmaz` olur ve bugs
    şeridinden taslak istenmez.
    """
    f = _overrides.get("kirma_taslak")
    if f is not None:
        return bool(f())
    return (os.environ.get("TP_TRIAGE_KIRMA_TASLAK") or "1").strip().lower() not in (
        "0",
        "false",
        "hayir",
    )


@contextmanager
def override(**fabrikalar: Callable[..., Any]) -> Iterator[None]:
    eski = dict(_overrides)
    _overrides.update(fabrikalar)
    try:
        yield
    finally:
        _overrides.clear()
        _overrides.update(eski)
