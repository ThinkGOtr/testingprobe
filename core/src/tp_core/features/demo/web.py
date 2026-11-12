"""Çalışan demo-app-web'in forge `main`'i yansıtması (TEKNIK-TASARIM §10 Kırılma, §13 adım 7–8).

**Sorun:** toolchain `/check` testleri compose'da ÇALIŞAN demo-app-web'e karşı koşar ve ilk adımı
(`app`) çalışan uygulamanın commit'ini istenen commit'le karşılaştırır; uygulama ağacı (`web`,
`api`) farklıysa koşu yapılmaz (core: `ortam`). `demo/break-locator` merge edilince main'in `web/`
ağacı değişir; uygulama yeniden derlenmeden kuyruğa alınan CI kırmızı değil **ortam** olur ve
locator onarım yolu hiç başlamaz. core-worker imaj derleyemez (Docker soketi yok, olmamalı).

**Mekanizma (bu şerit):**

1. Yenileme isteği — `WebYenileyici`:
   - `istek` (varsayılan, `TP_DEMO_WEB_REFRESH=istek`): core-worker forge volume'üne
     `/forge/demo-web-refresh.json` ({istek_id, eylem, sha, zaman, isteyen}) yazar. Host'taki
     `scripts/demo-web-sync.sh` (tek sefer ya da `--watch`) isteği okur, `forge_demo archive
     --ref <sha> --path web` arşivinden imajı derler (`DEMO_APP_BUILD_SHA`/`DEMO_APP_WEB_TREE`
     derleme argümanlarıyla `/build.json`), servisi yeniden oluşturur ve `/forge/demo-app-web.sha`
     dosyasını yazar. `scripts/demo-break.sh` / `demo-reset.sh` bunu kendiliğinden çağırır.
   - `toolchain` (`TP_DEMO_WEB_REFRESH=toolchain`): toolchain-worker `POST /demo/web-sync {sha,
     eylem}` (entegrasyon isteği: web'i forge'dan derleyip paylaşılan volume'den sunmak).
   - `kapali`: yenileme istenmez.
   GitHub kipinde de `istek` kullanılır: CI uygulamayı GitHub runner'ında checkout'tan kendisi
   başlatır, ama locator onarımının `/locator-probe` ve `/check` ölçümü compose'da ÇALIŞAN
   demo-app-web'e karşıdır; `scripts/demo-web-sync.sh` GitHub kipinde web arşivini
   toolchain-worker'ın salt okunur aynasından (`TP_FORGE_REMOTE_URL`) alır.
2. CI kapısı — `demo.await_web` işi: çalışan uygulama main'i yansıtana kadar (önce demo-app-web
   `GET /build.json`, yoksa `/forge/demo-app-web.sha`; sha eşit ya da `web`/`api` ağaçları aynı)
   `TP_DEMO_WEB_POLL_S` (5 sn) aralıkla bekler, sonra `enqueue_ci(main, "push")`. Süre
   (`TP_DEMO_WEB_WAIT_S`, 900 sn) dolarsa CI kuyruğa ALINMAZ (ortam koşusu üretmemek için);
   denetim `demo.web_timeout` + SSE `demo.web_timeout` ve Türkçe yönerge.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from tp_core.ports import ForgePort

REFRESH_ENV = "TP_DEMO_WEB_REFRESH"
SHA_FILE_ENV = "TP_DEMO_WEB_SHA_FILE"
REQUEST_FILE_ENV = "TP_DEMO_WEB_REQUEST_FILE"
VARSAYILAN_SHA_FILE = "/forge/demo-app-web.sha"
VARSAYILAN_ISTEK_FILE = "/forge/demo-web-refresh.json"
UYGULAMA_YOLLARI = ("web", "api")
YONERGE = (
    "Demo uygulaması forge main'den yeniden derlenmeli: host'ta `scripts/demo-web-sync.sh` "
    "(ya da `make break` / `make demo-baseline`) çalıştırın. GitHub kipinde güncel main için: "
    "`scripts/demo-web-sync.sh --main` (TP_FORGE_REMOTE_URL aynası gerekir)."
)


def _ortam(ad: str, varsayilan: str) -> str:
    return (os.environ.get(ad) or "").strip() or varsayilan


def sha_dosyasi() -> Path:
    return Path(_ortam(SHA_FILE_ENV, _ortam("TP_APP_BUILD_SHA_FILE", VARSAYILAN_SHA_FILE)))


def istek_dosyasi() -> Path:
    return Path(_ortam(REQUEST_FILE_ENV, VARSAYILAN_ISTEK_FILE))


def web_url() -> str:
    return _ortam("TP_DEMO_WEB_URL", "http://demo-app-web:8080").rstrip("/")


def _sha_mi(deger: Any) -> bool:
    return (
        isinstance(deger, str)
        and 7 <= len(deger) <= 64
        and all(c in "0123456789abcdef" for c in deger)
    )


@dataclass
class CalisanUygulama:
    sha: str | None
    kaynak: str  # build_json | dosya | yok
    web_tree: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"sha": self.sha, "kaynak": self.kaynak, "web_tree": self.web_tree}


def build_json(transport: httpx.BaseTransport | None = None) -> dict[str, Any] | None:
    """Çalışan demo-app-web'in `/build.json`'u (demo-app şeridi); yoksa/okunamazsa None."""
    try:
        with httpx.Client(transport=transport, timeout=3.0) as c:
            r = c.get(f"{web_url()}/build.json")
        if r.status_code != 200:
            return None
        veri = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    return veri if isinstance(veri, dict) else None


def calisan_uygulama(transport: httpx.BaseTransport | None = None) -> CalisanUygulama:
    """Önce çalışan konteynerin kendi beyanı (`/build.json`), yoksa betiklerin yazdığı dosya."""
    bj = build_json(transport)
    if bj and _sha_mi(bj.get("sha")):
        tree = bj.get("web_tree") if _sha_mi(bj.get("web_tree")) else None
        return CalisanUygulama(str(bj["sha"]), "build_json", tree)
    try:
        ham = sha_dosyasi().read_text(encoding="utf-8")[:200]
        ilk = (ham.strip().splitlines() or [""])[0].strip()
    except OSError:
        ilk = ""
    if _sha_mi(ilk):
        return CalisanUygulama(ilk, "dosya")
    return CalisanUygulama(None, "yok")


def sha_dosyasindaki() -> str | None:
    """`/forge/demo-app-web.sha` (toolchain `/check` `app` adımı ve `/locator-probe` bunu okur)."""
    try:
        ham = sha_dosyasi().read_text(encoding="utf-8")[:200]
    except OSError:
        return None
    ilk = (ham.strip().splitlines() or [""])[0].strip()
    return ilk if _sha_mi(ilk) else None


def uygulama_eslesiyor(
    forge: ForgePort, hedef_sha: str, uygulama_sha: str | None
) -> tuple[bool, str]:
    """Çalışan uygulama `hedef_sha`'nın uygulama ağaçlarını (web, api) mı taşıyor?"""
    if not uygulama_sha:
        return False, "çalışan uygulamanın commit'i bilinmiyor"
    if uygulama_sha == hedef_sha or hedef_sha.startswith(uygulama_sha):
        return True, "aynı commit"
    try:
        yollar = forge.changed_paths(uygulama_sha, hedef_sha)
    except Exception as exc:  # bilinmeyen sha vb.
        return False, f"karşılaştırılamadı: {exc}"[:200]
    if yollar is None:  # GitHub: fark listesi kesilmiş olabilir
        return False, "karşılaştırılamadı: fark listesi eksik"
    from tp_core.integrations.forge_demo import app_path

    # GitHub kipinde uygulama `demo-app/` altındadır: `demo-app/web/...` uygulama yoludur.
    kokler = {k: app_path(forge, k) for k in UYGULAMA_YOLLARI}
    farkli = sorted(
        {k for y in yollar for k, kok in kokler.items() if y == kok or y.startswith(kok + "/")}
    )
    if farkli:
        return False, f"uygulama kodu farklı ({', '.join(farkli)})"
    return True, "uygulama ağaçları aynı (yalnızca e2e/diğer yollar farklı)"


# -------------------------------------------------------------------- yenileyiciler


class WebYenileyici(Protocol):
    yontem: str

    def iste(self, sha: str, eylem: str, isteyen: str) -> dict[str, Any]: ...


class IstekDosyasi:
    """Forge volume'üne istek dosyası yazar; host betiği (`scripts/demo-web-sync.sh`) uygular."""

    yontem = "istek"

    def __init__(self, yol: Path | None = None) -> None:
        self.yol = yol or istek_dosyasi()

    def iste(self, sha: str, eylem: str, isteyen: str) -> dict[str, Any]:
        istek = {
            "istek_id": uuid.uuid4().hex,
            "eylem": eylem,
            "sha": sha,
            "zaman": datetime.now(UTC).isoformat(),
            "isteyen": isteyen,
        }
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        fd, gecici = tempfile.mkstemp(prefix=".demo-web-", dir=str(self.yol.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(istek, f, ensure_ascii=False)
            os.chmod(gecici, 0o644)
            os.replace(gecici, self.yol)
        except BaseException:
            Path(gecici).unlink(missing_ok=True)
            raise
        return {
            "yontem": self.yontem,
            "durum": "bekleniyor",
            "istek": istek,
            "dosya": str(self.yol),
            "yonerge": YONERGE,
        }


class ToolchainYenileyici:
    """toolchain-worker `POST /demo/web-sync` (entegrasyon isteği; uç yoksa hata döner)."""

    yontem = "toolchain"

    def __init__(
        self, base_url: str, token: str = "", transport: httpx.BaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def iste(self, sha: str, eylem: str, isteyen: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        try:
            with httpx.Client(transport=self.transport, timeout=600.0, headers=headers) as c:
                r = c.post(f"{self.base_url}/demo/web-sync", json={"sha": sha, "eylem": eylem})
            veri = r.json() if r.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            return {"yontem": self.yontem, "durum": "hata", "hata": str(exc)[:300]}
        if r.status_code >= 400:
            detay = veri.get("detail") if isinstance(veri, Mapping) else None
            return {
                "yontem": self.yontem,
                "durum": "hata",
                "hata": f"HTTP {r.status_code}: {detay or ''}"[:300],
                "yonerge": YONERGE,
            }
        return {"yontem": self.yontem, "durum": "istendi", "yanit": veri}


class Kapali:
    yontem = "kapali"

    def iste(self, sha: str, eylem: str, isteyen: str) -> dict[str, Any]:
        return {"yontem": self.yontem, "durum": "atlandi"}


def varsayilan_yenileyici() -> WebYenileyici:
    secim = _ortam(REFRESH_ENV, "istek").lower()
    if secim == "toolchain":
        from tp_core.config import get_settings

        s = get_settings()
        return ToolchainYenileyici(s.toolchain_url, s.toolchain_token)
    if secim in ("kapali", "none", "0"):
        return Kapali()
    return IstekDosyasi()


def bekleyen_istek() -> dict[str, Any] | None:
    try:
        veri = json.loads(istek_dosyasi().read_text(encoding="utf-8")[:10_000])
    except (OSError, ValueError):
        return None
    return veri if isinstance(veri, dict) else None


def uygulanan_istek_id() -> str | None:
    """`scripts/demo-web-sync.sh`'in son uyguladığı isteğin kimliği (`demo-web-refresh.done`)."""
    try:
        deger = istek_dosyasi().with_suffix(".done").read_text(encoding="utf-8")[:200].strip()
    except OSError:
        return None
    return deger or None


def uygulanmamis_istek(sha: str, en_erken: datetime) -> dict[str, Any] | None:
    """`sha` için `en_erken`den sonra yazılmış ve host betiğince henüz uygulanmamış istek.

    Uygulama aynı commit'i zaten yansıtsa bile betik konteyneri yeniden oluşturur; bu sırada
    koşan CI sağlık kontrolünde düşer (ortam koşusu). CI kapısı bu isteği bekler.
    """
    istek = bekleyen_istek()
    if not istek or istek.get("sha") != sha:
        return None
    try:
        zaman = datetime.fromisoformat(str(istek.get("zaman")))
    except ValueError:
        return None
    if zaman.tzinfo is None:
        zaman = zaman.replace(tzinfo=UTC)
    if zaman < en_erken:
        return None
    if istek.get("istek_id") and istek.get("istek_id") == uygulanan_istek_id():
        return None
    return istek
