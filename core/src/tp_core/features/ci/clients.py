"""CI şeridinin dış istemcileri: toolchain-worker `/check` ve GitHub Actions REST.

İkisi de httpx'tir ve testlerde `transport=` (MockTransport) ile değiştirilir; kod yolu aynıdır.

**GitHub kimliği:** yeni kimlik kodu yazılmaz; `GitHubForge`'un kimlik doğrulamalı istek
yardımcısı (`request`: App/token, 401'de bir kez yenileme) kullanılır. Böylece kimlik bilgisi
yalnızca core-worker'daki forge ortamından gelir (GITHUB_TOKEN / GH_APP_*; Constitution: yazma
kimliği yalnızca core-worker). Artefakt indirmeleri GitHub'ın blob depolamasına yönlendirilir;
httpx çapraz-köken yönlendirmede `Authorization` başlığını düşürür.
"""

from __future__ import annotations

import fnmatch
import io
import os
import zipfile
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from tp_core.features.ci.parse import MAX_ERROR_CONTEXT, MAX_RAPOR_BAYT

# toolchain /check en kötü zinciri (MIMARI-SOZLESME §2): /check kilidi bekleme + git + statik
# adımlar (tsc, eslint, AST koruması) + test-runner kilidi bekleme + koşu. Varsayılanlar
# toolchain_common/settings.py ile aynıdır; aynı ortam değişkenleri verilirse onlar kullanılır.
TOOLCHAIN_ZINCIRI = (
    ("TP_CHECK_QUEUE_WAIT_S", 900.0),
    ("TP_GIT_TIMEOUT_S", 60.0),
    ("TP_TSC_TIMEOUT_S", 180.0),
    ("TP_ESLINT_TIMEOUT_S", 240.0),
    ("TP_AST_GUARD_TIMEOUT_S", 60.0),
    ("TP_RUN_QUEUE_WAIT_S", 600.0),
    ("TP_RUN_TIMEOUT_S", 900.0),
)
CHECK_PAYI_S = 180.0  # sağlık yoklaması, rapor yazımı, ağ


def _ortam_float(ad: str, varsayilan: float) -> float:
    try:
        return max(float((os.environ.get(ad) or "").strip() or varsayilan), 0.0)
    except ValueError:
        return varsayilan


def check_timeout_s() -> float:
    """İstemci zaman aşımı toolchain'in en kötü kuyruk zincirinden uzun olmalıdır: aksi halde
    istemci vazgeçer, ilk kontrol sürerken yeniden deneme ikinci tam koşuyu kuyruğa alır.
    `TP_CI_CHECK_TIMEOUT_S` verilirse o kullanılır (alt sınır yine zincirdir)."""
    zincir = sum(_ortam_float(ad, v) for ad, v in TOOLCHAIN_ZINCIRI) + CHECK_PAYI_S
    return max(_ortam_float("TP_CI_CHECK_TIMEOUT_S", 0.0), zincir)


# Geriye uyum (içe aktaranlar için): modül yüklenirken hesaplanan değer.
CHECK_TIMEOUT_S = check_timeout_s()
WORKFLOW_FILE = "ci.yml"
RESULTS_ARTIFACT = "test-local-results"
SAUCE_ARTIFACT = "sauce-results"
MAX_ZIP_BAYT = 200 * 1024 * 1024
# Rapor dışı küçük ekler (error-context.md): dosya başına ve toplam sınır (zip bombasına karşı).
MAX_EK_TOPLAM_BAYT = 32 * 1024 * 1024
MAX_EK_DOSYA = 2000


class ToolchainError(RuntimeError):
    """toolchain-worker isteği başarısız. `gecici=True` → yeniden denenebilir."""

    def __init__(self, mesaj: str, *, gecici: bool, status: int | None = None) -> None:
        super().__init__(mesaj)
        self.gecici = gecici
        self.status = status


class ToolchainClient:
    """toolchain-worker HTTP API'si (MIMARI-SOZLESME §2)."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
        token: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = check_timeout_s() if timeout is None else timeout
        self._headers = {"Authorization": f"Bearer {token}"} if token else None

    def check(self, body: Mapping[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(
                transport=self._transport, timeout=self._timeout, headers=self._headers
            ) as c:
                resp = c.post(f"{self.base_url}/check", json=dict(body))
        except httpx.HTTPError as exc:
            raise ToolchainError(
                f"toolchain-worker'a ulaşılamadı: {type(exc).__name__}", gecici=True
            ) from exc
        try:
            data = resp.json()
        except ValueError:
            data = None
        if resp.status_code >= 400:
            detay = data.get("detail") if isinstance(data, dict) else None
            mesaj = f"toolchain-worker /check HTTP {resp.status_code}: {detay or resp.text[:300]}"
            # 409: başka kontrol sürüyor; 5xx/503: forge/servis geçici. 404/422: kalıcı.
            gecici = resp.status_code in (409, 429) or resp.status_code >= 500
            raise ToolchainError(mesaj, gecici=gecici, status=resp.status_code)
        if not isinstance(data, dict):
            raise ToolchainError("toolchain-worker /check yanıtı nesne değil", gecici=False)
        return data


class GitHubCiError(RuntimeError):
    pass


def dosya_sec(
    girdiler: Iterable[tuple[str, int, Callable[[], bytes]]],
    adlar: tuple[str, ...],
    ekler: tuple[str, ...] = (),
) -> dict[str, bytes]:
    """(göreli yol, boyut, okuyucu) girdilerinden adı (yolun son öğesi) `adlar`'da olanları okur.

    `ekler`: test başına çok sayıda olabilen küçük ek dosyalarının ad kalıpları (`fnmatch`;
    `error-context.md`, `*aria*.yml`); her biri
    `MAX_ERROR_CONTEXT`, toplamı `MAX_EK_TOPLAM_BAYT`, sayısı `MAX_EK_DOSYA` ile sınırlıdır.
    Aynı ada sahip her kopya (farklı test dizinleri) ayrı anahtar olarak döner. Zip ve yerel kopya
    (diskteki açılmış artefakt) aynı seçimi kullanır: anahtarlar iki kaynakta da aynıdır.
    """
    out: dict[str, bytes] = {}
    ek_toplam = 0
    ek_sayi = 0
    for yol, boyut, oku in girdiler:
        ad = yol.rsplit("/", 1)[-1]
        if ad not in adlar and any(fnmatch.fnmatchcase(ad, k) for k in ekler):
            if (
                boyut > MAX_ERROR_CONTEXT
                or ek_sayi >= MAX_EK_DOSYA
                or ek_toplam + boyut > MAX_EK_TOPLAM_BAYT
                or yol in out
            ):
                continue
            icerik = oku()
            ek_toplam += len(icerik)
            ek_sayi += 1
            out[yol] = icerik
            continue
        if ad not in adlar or boyut > MAX_RAPOR_BAYT or yol in out:
            continue
        # Aynı ad birden çok yerde olabilir (results/ ve demo-app/e2e/results/): ilk bulunan.
        out[yol] = oku()
    return out


def _zip_dosyalari(
    veri: bytes, adlar: tuple[str, ...], ekler: tuple[str, ...] = ()
) -> dict[str, bytes]:
    """Zip içinden `dosya_sec` kurallarıyla dosya okur (sınırlı boyut)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(veri))
    except zipfile.BadZipFile as exc:
        raise GitHubCiError(f"artefakt zip'i bozuk: {exc}") from exc
    with zf:
        girdiler = (
            (info.filename, info.file_size, lambda info=info: zf.read(info))
            for info in zf.infolist()
            if not info.is_dir()
        )
        return dosya_sec(girdiler, adlar, ekler)


class GitHubCi:
    """GitHub Actions okuma + dispatch. `forge`: `GitHubForge` (kimlik yardımcısı)."""

    def __init__(self, forge: Any) -> None:
        self.forge = forge
        self.repo: str = forge.repo

    def _istek(self, method: str, path: str, ne: str, **kw: Any) -> httpx.Response:
        try:
            return self.forge.request(method, path, ne, **kw)
        except Exception as exc:  # ForgeError ailesi + httpx
            raise GitHubCiError(f"GitHub {ne}: {exc}") from exc

    @property
    def _r(self) -> str:
        return f"/repos/{self.repo}"

    def workflow_runs(
        self, *, head_sha: str | None = None, event: str | None = None, per_page: int = 30
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": per_page}
        if head_sha:
            params["head_sha"] = head_sha
        if event:
            params["event"] = event
        data = self._istek(
            "GET",
            f"{self._r}/actions/workflows/{quote(WORKFLOW_FILE, safe='')}/runs",
            "workflow koşuları",
            params=params,
        ).json()
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        return [r for r in runs or [] if isinstance(r, dict)]

    def workflow_run(self, run_id: int | str) -> dict[str, Any]:
        return self._istek("GET", f"{self._r}/actions/runs/{int(run_id)}", "workflow koşusu").json()

    def jobs(self, run_id: int | str) -> list[dict[str, Any]]:
        data = self._istek(
            "GET",
            f"{self._r}/actions/runs/{int(run_id)}/jobs",
            "koşu işleri",
            params={"per_page": 100},
        ).json()
        return [j for j in (data.get("jobs") or []) if isinstance(j, dict)]

    def artifacts(self, run_id: int | str) -> list[dict[str, Any]]:
        data = self._istek(
            "GET",
            f"{self._r}/actions/runs/{int(run_id)}/artifacts",
            "artefaktlar",
            params={"per_page": 100},
        ).json()
        return [a for a in (data.get("artifacts") or []) if isinstance(a, dict)]

    def artifact_zip(self, artifact: Mapping[str, Any]) -> bytes:
        """Artefakt zip'inin baytları (`MAX_ZIP_BAYT` sınırlı; süresi dolmuşsa hata)."""
        if artifact.get("expired"):
            raise GitHubCiError(f"artefakt süresi dolmuş: {artifact.get('name')}")
        boyut = int(artifact.get("size_in_bytes") or 0)
        if boyut > MAX_ZIP_BAYT:
            raise GitHubCiError(f"artefakt çok büyük: {artifact.get('name')} ({boyut} bayt)")
        resp = self._istek(
            "GET",
            f"{self._r}/actions/artifacts/{int(artifact['id'])}/zip",
            "artefakt indirme",
            follow_redirects=True,
        )
        if len(resp.content) > MAX_ZIP_BAYT:
            raise GitHubCiError(f"artefakt çok büyük: {artifact.get('name')} (> {MAX_ZIP_BAYT})")
        return resp.content

    def artifact_files(
        self, artifact: Mapping[str, Any], adlar: tuple[str, ...], ekler: tuple[str, ...] = ()
    ) -> dict[str, bytes]:
        return _zip_dosyalari(self.artifact_zip(artifact), adlar, ekler)

    def repository_dispatch(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self._istek(
            "POST",
            f"{self._r}/dispatches",
            "repository_dispatch",
            json={"event_type": event_type, "client_payload": dict(payload)},
        )

    def workflow_dispatch(self, ref: str, inputs: Mapping[str, str]) -> None:
        self._istek(
            "POST",
            f"{self._r}/actions/workflows/{quote(WORKFLOW_FILE, safe='')}/dispatches",
            "workflow_dispatch",
            json={"ref": ref, "inputs": dict(inputs)},
        )


def parse_gh_time(deger: Any) -> datetime | None:
    if not isinstance(deger, str) or not deger:
        return None
    try:
        return datetime.fromisoformat(deger.replace("Z", "+00:00"))
    except ValueError:
        return None
