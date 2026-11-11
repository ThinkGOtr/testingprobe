"""toolchain-worker HTTP istemcisi (MIMARI-SOZLESME §2): `/symbols` ve `/check`.

toolchain-worker kod çalıştırmaz (sembol tablosu ts-morph ile ayrıştırılır); `/check` aynı
sırayla `deps → tsc → eslint → ast-guard → test-runner /run` koşturur (CI ile aynı mekanizma,
AI yok) ve kırılmasız koşuda `TP_ARTIFACTS_PATH/checks/<sha>.json`'a `local-ci` sonucunu yazar.

Sembol tablosu commit'e bağlıdır (commit'ler değişmez): süreç içinde (sha, platform) başına
önbellek.

**Platform (009 §2.1):** `platform` verilirse (`android` | `ios` | `windows`) istek gövdesine
eklenir; toolchain-worker Java yolunu seçer (`/symbols`: `java-araclar symbols` ile e2e-app ekran
nesneleri; `/check`: `app → deps → guard → compile → run`, `test_files` e2e-app köküne göre).
`web` ya da `None` gövdeye hiç yazılmaz (mevcut TS yolu, istek baytları değişmez).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

import httpx


def varsayilan_check_timeout_s() -> float:
    """/check istemci zaman aşımı: CI şeridiyle aynı hesap (toolchain'in en kötü zinciri:
    kontrol kuyruğu + git + tsc + eslint + AST + koşu kuyruğu + koşu + pay;
    `TP_CI_CHECK_TIMEOUT_S`).
    İstemci toolchain'den önce vazgeçerse ilk kontrol sürerken ikinci tam koşu kuyruğa girer."""
    from tp_core.features.ci.clients import check_timeout_s as ci_check_timeout_s

    return float(ci_check_timeout_s())


# Geriye uyum: modül yüklenirken hesaplanan değer (istemci her örnekte yeniden hesaplar).
CHECK_TIMEOUT_S = varsayilan_check_timeout_s()
SYMBOLS_TIMEOUT_S = 120.0
_CACHE_MAX = 32


class ToolchainError(RuntimeError):
    def __init__(self, status: int | None, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


_SYMBOL_CACHE: OrderedDict[tuple[str, ...], dict[str, Any]] = OrderedDict()
_LOCK = threading.Lock()


def clear_symbol_cache() -> None:
    with _LOCK:
        _SYMBOL_CACHE.clear()


class ToolchainClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        check_timeout_s: float | None = None,
        token: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._http = httpx.Client(base_url=self.base_url, transport=transport, headers=headers)
        self.check_timeout_s = (
            check_timeout_s if check_timeout_s is not None else varsayilan_check_timeout_s()
        )

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            resp = self._http.post(path, json=body, timeout=timeout)
        except httpx.HTTPError as exc:
            raise ToolchainError(None, f"toolchain-worker'a ulaşılamadı: {exc}") from exc
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not resp.is_success:
            detail = data.get("detail") if isinstance(data, dict) else None
            raise ToolchainError(
                resp.status_code,
                f"toolchain-worker {path} HTTP {resp.status_code}: {detail or resp.text[:300]}",
            )
        if not isinstance(data, dict):
            raise ToolchainError(resp.status_code, f"toolchain-worker {path}: geçersiz yanıt")
        return data

    def symbols(self, sha: str, *, platform: str | None = None) -> dict[str, Any]:
        uygulama = bool(platform) and platform != "web"
        # Java tablosu Android/iOS/Windows için aynıdır (ekran nesneleri platformdan bağımsız).
        dil = ("java",) if uygulama else ()
        anahtar = (self.base_url, sha, *dil)
        with _LOCK:
            if anahtar in _SYMBOL_CACHE:
                _SYMBOL_CACHE.move_to_end(anahtar)
                return _SYMBOL_CACHE[anahtar]
        govde: dict[str, Any] = {"sha": sha}
        if uygulama:
            govde["platform"] = platform
        tablo = self._post("/symbols", govde, SYMBOLS_TIMEOUT_S)
        if "page_objects" not in tablo:
            raise ToolchainError(200, "sembol tablosu page_objects içermiyor")
        if uygulama and tablo.get("lang") not in (None, "java"):
            raise ToolchainError(200, f"Java sembol tablosu beklenirken lang={tablo.get('lang')}")
        with _LOCK:
            _SYMBOL_CACHE[anahtar] = tablo
            if tablo.get("sha") and tablo["sha"] != sha:
                _SYMBOL_CACHE[(self.base_url, str(tablo["sha"]), *dil)] = tablo
            while len(_SYMBOL_CACHE) > _CACHE_MAX:
                _SYMBOL_CACHE.popitem(last=False)
        return tablo

    def check(
        self,
        sha: str,
        test_files: Sequence[str],
        *,
        repeat_each: int = 3,
        retries: int = 0,
        break_campaign: bool = False,
        run_id: str | None = None,
        keep: bool = False,
        platform: str | None = None,
        fault: str | None = None,
    ) -> dict[str, Any]:
        """`keep=True`: koşu dizini test-runner temizliğinde silinmez (`.keep`; kırarak doğrulama
        ve defect adayı kanıtı, MIMARI-SOZLESME §2). `platform` (`android|ios|windows`): Java
        yolu; `test_files` e2e-app köküne göre (`src/test/java/…/<Ad>Test.java`). `fault`: ekilmiş
        hata kodu (012 §4.6; test süreci her testten önce bayiye uygular); None ise gövdeye
        yazılmaz (eski toolchain'lerle istek baytları aynı kalır)."""
        body: dict[str, Any] = {
            "sha": sha,
            "test_files": list(test_files),
            "repeat_each": repeat_each,
            "retries": retries,
            "env": {"BREAK_CAMPAIGN": "1"} if break_campaign else {},
            "keep": bool(keep),
        }
        if run_id:
            body["run_id"] = run_id
        if fault is not None:
            body["fault"] = fault
        if platform and platform != "web":
            # Ş8 sözleşmesi: Java yolu açıkça (`lang`) + Appium sürücüsü (`platform`).
            body["lang"] = "java"
            body["platform"] = platform
        return self._post("/check", body, self.check_timeout_s)
