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

**Dil (011 §2.6):** `lang` üretilen kodun dilidir (`ts` | `java`; `csharp` | `python` toolchain'e
hiç gitmez). Verilmezse platformun varsayılanı kullanılır (yukarıdaki davranış). `lang="java"` +
web: `/symbols` ve `/check` gövdesi `{lang: "java", platform: "web"}` taşır (kök
`TP_E2E_JAVA_ROOT`); check adı `platform.check_adi`'dır (`local-ci-web-java`, K-T1).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from tp_core.features.codegen import platform as platformlar


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


@dataclass(frozen=True)
class _Hedef:
    """İsteğin (platform, dil) hedefi: araç/ortam platforma, kod/derleme yolu dile bakar."""

    platform: str
    java: bool
    govde: dict[str, Any]  # `/symbols` gövdesine eklenecek alanlar
    anahtar: tuple[str, ...]  # sembol önbelleği anahtar eki


def _hedef(platform: str | None, lang: str | None) -> _Hedef:
    p = platform or platformlar.WEB
    dil = platformlar.dil(p, lang)
    if dil not in platformlar.TAM_HAT_DILLERI or (lang is not None and lang != dil):
        # `csharp` / `python` toolchain'e hiç gitmez (011 §2.6).
        raise ToolchainError(None, f"toolchain yalnızca ts | java dillerini işler: {lang!r}")
    if not platformlar.gecerli_cift(p, dil):
        raise ToolchainError(None, f"geçersiz platform/dil çifti: {p} + {dil}")
    if not platformlar.java_mi(dil):
        return _Hedef(p, False, {}, ())
    if platformlar.uygulama_mi(p):
        # Java tablosu Android/iOS/Windows için aynıdır (ekran nesneleri platformdan bağımsız).
        return _Hedef(p, True, {"platform": p}, ("java",))
    return _Hedef(p, True, {"lang": "java", "platform": p}, ("java", "web"))


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

    def symbols(
        self, sha: str, *, platform: str | None = None, lang: str | None = None
    ) -> dict[str, Any]:
        """Sembol tablosu. `lang` üretilen kodun dilidir (yoksa platformun varsayılanı: web → ts,
        uygulama → java). İstek gövdesi: ts `{sha}`; uygulama Java `{sha, platform}` (009, baytlar
        değişmez); web + Java `{sha, lang: "java", platform: "web"}` (011 §2.6; e2e-java tablosu).
        Önbellek anahtarı tabloları ayırır: TS, uygulama Java'sı (platformlar ortak), web Java'sı.
        """
        yol = _hedef(platform, lang)
        anahtar = (self.base_url, sha, *yol.anahtar)
        with _LOCK:
            if anahtar in _SYMBOL_CACHE:
                _SYMBOL_CACHE.move_to_end(anahtar)
                return _SYMBOL_CACHE[anahtar]
        tablo = self._post("/symbols", {"sha": sha, **yol.govde}, SYMBOLS_TIMEOUT_S)
        if "page_objects" not in tablo:
            raise ToolchainError(200, "sembol tablosu page_objects içermiyor")
        if yol.java and tablo.get("lang") not in (None, "java"):
            raise ToolchainError(200, f"Java sembol tablosu beklenirken lang={tablo.get('lang')}")
        if not yol.java and tablo.get("lang") not in (None, "ts"):
            raise ToolchainError(200, f"TS sembol tablosu beklenirken lang={tablo.get('lang')}")
        with _LOCK:
            _SYMBOL_CACHE[anahtar] = tablo
            if tablo.get("sha") and tablo["sha"] != sha:
                _SYMBOL_CACHE[(self.base_url, str(tablo["sha"]), *yol.anahtar)] = tablo
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
        lang: str | None = None,
    ) -> dict[str, Any]:
        """`keep=True`: koşu dizini test-runner temizliğinde silinmez (`.keep`; kırarak doğrulama
        ve defect adayı kanıtı, MIMARI-SOZLESME §2). `platform` (`android|ios|windows`): Java
        yolu; `test_files` e2e-app köküne göre (`src/test/java/…/<Ad>Test.java`). `lang="java"` +
        web (011 §2.6): gövde `{lang: "java", platform: "web"}`, `test_files` e2e-java köküne
        göre. `lang` yoksa platformun varsayılanı (web → ts: gövde değişmez)."""
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
        yol = _hedef(platform, lang)
        if yol.java:
            # Java yolu açıkça (`lang`) + sürücü/ortam (`platform`: Appium platformu ya da `web`).
            body["lang"] = "java"
            body["platform"] = yol.platform
        return self._post("/check", body, self.check_timeout_s)
