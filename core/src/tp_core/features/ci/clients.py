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
import logging
import os
import time
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from tp_core.features.ci.parse import MAX_ERROR_CONTEXT, MAX_RAPOR_BAYT

log = logging.getLogger("tp_core.ci")

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
# Uygulama platformu → iş akışı dosyası (009 §2.7; `forge.GITHUB_PLATFORM_WORKFLOWS` ile aynı).
# Web + Java (011 §2.8): `web-java.yml` (`forge.WEB_JAVA_WORKFLOW` ile aynı).
# Bilinen dosyalar dışında bir yol API'ye gitmez (yol enjeksiyonu yok).
IZINLI_IS_AKISLARI = frozenset(
    {WORKFLOW_FILE, "mobil-android.yml", "mobil-ios.yml", "masaustu-windows.yml", "web-java.yml"}
)


def _is_akisi(workflow: str) -> str:
    if workflow not in IZINLI_IS_AKISLARI:
        raise GitHubCiError(f"bilinmeyen iş akışı: {workflow!r}")
    return workflow


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


MAX_SUREFIRE_TOPLAM_BAYT = 200 * 1024 * 1024


def surefire_dosyalari(veri: bytes) -> tuple[dict[str, bytes], list[str]]:
    """Uygulama iş akışı artefakt zip'inden cihaz koşusunun Surefire raporları
    (`…/surefire-reports/TEST-*.xml`; `birim-raporlari/` dışarıda). Rapor sınırı dosya başına
    `MAX_RAPOR_BAYT`, toplam `MAX_SUREFIRE_TOPLAM_BAYT`, sayı `MAX_SUREFIRE_DOSYA`; atlanan her
    dosya uyarıdır (sessizce düşen rapor koşuyu yeşil/eksik göstermesin)."""
    from tp_core.features.ci.parse import MAX_SUREFIRE_DOSYA, surefire_yolu_mu, temiz

    try:
        zf = zipfile.ZipFile(io.BytesIO(veri))
    except zipfile.BadZipFile as exc:
        raise GitHubCiError(f"artefakt zip'i bozuk: {exc}") from exc
    out: dict[str, bytes] = {}
    uyarilar: list[str] = []
    toplam = 0
    with zf:
        for info in zf.infolist():
            if info.is_dir() or not surefire_yolu_mu(info.filename):
                continue
            ad = temiz(info.filename.rsplit("/", 1)[-1], 120)
            if len(out) >= MAX_SUREFIRE_DOSYA:
                uyarilar.append(f"{ad}: Surefire rapor sayısı sınırı ({MAX_SUREFIRE_DOSYA}) aşıldı")
                continue
            if (
                info.file_size > MAX_RAPOR_BAYT
                or toplam + info.file_size > MAX_SUREFIRE_TOPLAM_BAYT
            ):
                uyarilar.append(
                    f"{ad}: Surefire raporu çok büyük ({info.file_size} bayt), okunmadı"
                )
                continue
            icerik = zf.read(info)
            toplam += len(icerik)
            out[info.filename] = icerik
    return out, uyarilar


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
        self,
        *,
        head_sha: str | None = None,
        event: str | None = None,
        per_page: int = 30,
        workflow: str = WORKFLOW_FILE,
    ) -> list[dict[str, Any]]:
        """`workflow`: iş akışı dosyası (web `ci.yml`; uygulama platformu `mobil-android.yml` …)."""
        params: dict[str, Any] = {"per_page": per_page}
        if head_sha:
            params["head_sha"] = head_sha
        if event:
            params["event"] = event
        data = self._istek(
            "GET",
            f"{self._r}/actions/workflows/{quote(_is_akisi(workflow), safe='')}/runs",
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

    def workflow_dispatch(
        self, ref: str, inputs: Mapping[str, str], *, workflow: str = WORKFLOW_FILE
    ) -> None:
        self._istek(
            "POST",
            f"{self._r}/actions/workflows/{quote(_is_akisi(workflow), safe='')}/dispatches",
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


# ------------------------------------------------------------- asistan: yalnız-okuma CI logu

LOG_KUYRUK_BAYT = 256 * 1024  # yalnızca logun son 256 KB'ı tutulur (halka tampon)
LOG_EN_COK_BAYT = 20 * 1024 * 1024  # akıştan en çok bu kadar okunur (Content-Length'e güvenilmez)
LOG_SURE_S = 10.0
ACTIONS_READ_TOKEN_ENV = "GITHUB_ACTIONS_READ_TOKEN"


@dataclass(frozen=True)
class LogKuyrugu:
    """Akıştan okunan logun kuyruğu.

    `kirpildi`: baştan bayt atıldı (ilk satır yarım olabilir). `kesildi`: akış sonuna
    varılmadan durduruldu (`boyut` = 20 MB, `sure` = süre doldu); kuyruk o ana kadarki sondur.
    """

    veri: bytes
    okunan: int
    kirpildi: bool
    kesildi: str | None = None


class GitHubCiOkuyucu:
    """Asistanın `ci_log` aracına verilen dar GitHub Actions okuyucusu (AI-ASISTAN-PLANI §5.7).

    Yalnız `jobs` ve `job_logs`; `GitHubCi`'nin dispatch/indirme yöntemleri yoktur. Kimlik: ayrı
    `actions:read` token'ı (`GITHUB_ACTIONS_READ_TOKEN`) varsa o, yoksa okuma token'ı
    (`GITHUB_READ_TOKEN`), o da yoksa mevcut forge kimliği.
    `forge`: `request` ve akışlı `akis` yöntemleri olan `GitHubForge`.
    """

    def __init__(self, forge: Any, *, saat: Callable[[], float] = time.monotonic) -> None:
        self._forge = forge
        self._repo: str = forge.repo
        self._saat = saat

    @classmethod
    def kur(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> GitHubCiOkuyucu:
        env = os.environ if env is None else env
        # En az yetki: ayrı actions:read token'ı, yoksa okuma token'ı; ikisi de yoksa forge kimliği.
        token = (env.get(ACTIONS_READ_TOKEN_ENV) or env.get("GITHUB_READ_TOKEN") or "").strip()
        if token:
            from tp_core.integrations.forge_github import DEFAULT_API_URL, GitHubForge, TokenAuth

            forge = GitHubForge(
                (env.get("GITHUB_REPO") or "").strip(),
                TokenAuth(token),
                api_url=env.get("GITHUB_API_URL") or DEFAULT_API_URL,
                transport=transport,
            )
            return cls(forge)
        from tp_core.features.ci import services

        # Okuma token'ı yok: forge kimliği (GitHub App ya da GITHUB_TOKEN; yazma yetkili olabilir).
        # Okuyucu yalnız GET gönderir, yine de en az yetki sapması görünür olsun (değer yazılmaz).
        log.warning(
            "ci_log: %s/GITHUB_READ_TOKEN boş; GitHub iş logu forge kimliğiyle okunuyor "
            "(yalnız actions:read token'ı önerilir)",
            ACTIONS_READ_TOKEN_ENV,
        )
        return cls(services.forge())

    @property
    def _r(self) -> str:
        return f"/repos/{self._repo}"

    def jobs(
        self, github_run_id: int | str, *, timeout: float = LOG_SURE_S
    ) -> list[dict[str, Any]]:
        """Koşunun (GitHub koşu kimliği; Probe UUID'si değil) son denemesindeki job'lar."""
        try:
            data = self._forge.request(
                "GET",
                f"{self._r}/actions/runs/{int(github_run_id)}/jobs",
                "koşu işleri",
                params={"filter": "latest", "per_page": 100},
                timeout=timeout,
            ).json()
        except Exception as exc:  # ForgeError ailesi + httpx
            raise GitHubCiError(f"GitHub koşu işleri: {type(exc).__name__}") from exc
        jobs = data.get("jobs") if isinstance(data, dict) else None
        return [j for j in jobs or [] if isinstance(j, dict)]

    def job_logs(
        self,
        job_id: int | str,
        *,
        sure_s: float = LOG_SURE_S,
        kuyruk_bayt: int = LOG_KUYRUK_BAYT,
        en_cok_bayt: int = LOG_EN_COK_BAYT,
    ) -> LogKuyrugu:
        """`GET /actions/jobs/{id}/logs` akışla okunur; yalnızca son `kuyruk_bayt` tutulur.

        Toplam `en_cok_bayt` ya da `sure_s` aşılınca okuma durur (Content-Length'siz sonsuz
        akışa karşı); o ana kadarki kuyruk döner. Kurulum token'ı alımı da süreye dahildir.
        """
        bitis = self._saat() + max(0.1, float(sure_s))
        tampon = bytearray()
        okunan = 0
        kirpildi = False
        kesildi: str | None = None
        try:
            with self._forge.akis(
                f"{self._r}/actions/jobs/{int(job_id)}/logs",
                "job logu",
                timeout=max(0.1, min(float(sure_s), bitis - self._saat())),
            ) as resp:
                for parca in resp.iter_bytes():
                    okunan += len(parca)
                    tampon.extend(parca)
                    if len(tampon) > kuyruk_bayt:
                        del tampon[: len(tampon) - kuyruk_bayt]
                        kirpildi = True
                    if okunan >= en_cok_bayt:
                        kesildi = "boyut"
                        break
                    if self._saat() >= bitis:
                        kesildi = "sure"
                        break
        except Exception as exc:  # ForgeError ailesi + httpx (zaman aşımı dahil)
            raise GitHubCiError(f"GitHub job logu: {type(exc).__name__}") from exc
        return LogKuyrugu(bytes(tampon), okunan, kirpildi, kesildi)
