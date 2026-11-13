"""Koşu artefaktlarının oturumlu, yolu doğrulanmış sunumu (`GET /artifacts/runs/<run_id>/...`).

Artefaktlar test kodunun çıktısıdır (güvenilmeyen). Kurallar:

- Yalnızca koşunun kendi dizini (`TP_ARTIFACTS_PATH/runs/<dizin>`; GitHub koşusunda core'un yerel
  kopyası `TP_GITHUB_ARTIFACTS_PATH/gh/<id>-<deneme>`, bkz. `github_artifacts`) altındaki izinli
  alt ağaçlar:
  `src/**/results/**` (JUnit, JSON, HTML raporu, allure-results, trace/ekran görüntüsü),
  Java (Appium + TestNG) koşusunun rapor dizinleri `src/**/target/{allure-report,allure-results,
  extent-report}/**`, `run.json`, `runner.log`. Kaynak kod, derleme çıktısı (`target/classes` …)
  ve diğer dosyalar sunulmaz.
- Yol öğeleri: boş, `.`/`..`, NUL, ters bölü, gizli dosya (`.` ile başlayan) reddedilir; gerçek yol
  (symlink çözülerek) koşu dizininin içinde kalmalıdır.
- HTML/SVG/XML: `Content-Security-Policy: sandbox allow-scripts allow-popups` — rapor sayfası
  opak kökende çalışır, core-api oturumuyla istek yapamaz (aynı kökenli XSS'e karşı). Bunun bedeli:
  rapor içindeki ek dosyalar (ekran görüntüsü, trace) çerezsiz yüklenemez; koşu detayındaki
  ek bağlantıları (üst düzey gezinti) kullanılır.
- Tüm yanıtlarda `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`; bilinmeyen
  türler `application/octet-stream` + `Content-Disposition: attachment`.
- Dizin isteği JSON listesi döner (allure-results gibi).
- **İmzalı rapor bağlantısı** (`/artifacts/k/<bitiş>.<imza>/runs/<run_id>/...`): sandbox'lı rapor
  opak kökendedir, çerez gitmez; rapor içindeki ekran görüntüsü / error-context bu yüzden
  yüklenemiyordu. `serialize_runs` HTML raporu için oturum sırrıyla (HMAC-SHA256) imzalı, tek koşuya
  bağlı, kısa ömürlü (`TP_ARTIFACT_LINK_TTL_S`, varsayılan 2 saat) bir yol önü üretir; raporun
  göreli istekleri aynı önü taşır. İzinli alt ağaç ve yol doğrulaması aynıdır; HTML yine sandbox'lı
  (portal oturumuna erişemez). Yalnızca HTML/SVG/XML OLMAYAN yanıtlar
  `Access-Control-Allow-Origin: *` alır (kimlik bilgisi yok) — rapor `fetch` ile ekleri okuyabilsin.
  Playwright trace görüntüleyici service worker ister; opak kökende çalışmaz (trace.zip koşu
  detayındaki bağlantıdan indirilir).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import itertools
import mimetypes
import os
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

MAX_LISTE = 2000
_OGE_RE = re.compile(r"^[^\x00-\x1f\\/]{1,255}$")
_SANDBOX = "sandbox allow-scripts allow-popups allow-downloads; frame-ancestors 'none'"
_SATIR_ICI = {
    "application/json",
    "application/xml",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "image/svg+xml",
    "video/webm",
}
_SANDBOX_TURLER = {"text/html", "image/svg+xml", "application/xml", "text/xml"}
_EK_TURLER = {".log": "text/plain", ".md": "text/plain", ".webm": "video/webm"}


# Opak kökende (sandbox, allow-same-origin YOK) `window.localStorage` okumak SecurityError atar;
# Allure 3 raporu açılışta tercihlerini oradan okuduğu için boş sayfa kalıyordu. Rapora, sandbox'ı
# gevşetmeden, sayfa ömrü kadar yaşayan bellek içi bir depo verilir (veri hiçbir yere gitmez).
DEPO_SIMI = (
    "<script>(function(){function m(){var d={};return{getItem:function(k){return Object.prototype"
    ".hasOwnProperty.call(d,k)?d[k]:null},setItem:function(k,v){d[k]=String(v)},removeItem:"
    "function(k){delete d[k]},clear:function(){d={}},"
    "key:function(i){return Object.keys(d)[i]||null},"
    "get length(){return Object.keys(d).length}}}['localStorage','sessionStorage'].forEach("
    "function(n){try{window[n].getItem('x')}catch(e){try{Object.defineProperty(window,n,{value:m(),"
    "configurable:true})}catch(_){}}})})();</script>"
)


def depo_simi_gerekir_mi(yol: Path) -> bool:
    """Statik Allure raporu (`allure-report/index.html`) ve Playwright HTML raporu
    (`results/html/index.html`; GitHub koşusunun yerel kopyasında `playwright-report/index.html`)
    bellek içi depo şimi ister. Şim yalnızca depo erişilemiyorsa
    devreye girer; nginx de aynısını eklerse ikinci kopya etkisizdir."""
    if yol.name != "index.html":
        return False
    return yol.parent.name in ("allure-report", "playwright-report") or (
        yol.parent.name == "html" and yol.parent.parent.name == "results"
    )


# ------------------------------------------------------------------ imzalı rapor bağlantısı

_TOKEN_RE = re.compile(r"^(\d{1,12})\.([A-Za-z0-9_-]{43})$")


def _imza_anahtari() -> bytes | None:
    from tp_core.config import get_settings

    sir = get_settings().session_secret
    if sir is None or not sir.get_secret_value():
        return None
    return hashlib.sha256(b"tp-artefakt-baglantisi:" + sir.get_secret_value().encode()).digest()


def link_ttl_s() -> int:
    try:
        return max(60, int(float((os.environ.get("TP_ARTIFACT_LINK_TTL_S") or "").strip() or 7200)))
    except ValueError:
        return 7200


def _imza(anahtar: bytes, run_id: uuid.UUID, bitis: int) -> str:
    mac = hmac.new(anahtar, f"{run_id}:{bitis}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def link_token(run_id: uuid.UUID, simdi: float) -> str | None:
    """`<bitiş>.<imza>`; oturum sırrı yoksa None (imzalı bağlantı üretilmez)."""
    anahtar = _imza_anahtari()
    if anahtar is None:
        return None
    bitis = int(simdi) + link_ttl_s()
    return f"{bitis}.{_imza(anahtar, run_id, bitis)}"


def token_gecerli_mi(run_id: uuid.UUID, token: str, simdi: float) -> bool:
    m = _TOKEN_RE.fullmatch(token or "")
    anahtar = _imza_anahtari()
    if m is None or anahtar is None:
        return False
    bitis = int(m.group(1))
    if bitis < simdi or bitis > simdi + link_ttl_s() + 60:
        return False
    return hmac.compare_digest(_imza(anahtar, run_id, bitis), m.group(2))


def imzali_onek(run_id: uuid.UUID, simdi: float) -> str | None:
    tok = link_token(run_id, simdi)
    return f"/api/artifacts/k/{tok}/runs/{run_id}/" if tok else None


def depo_simi_ekle(html: bytes) -> bytes:
    sim = DEPO_SIMI.encode()
    i = html.lower().find(b"<head>")
    if i >= 0:
        return html[: i + 6] + sim + html[i + 6 :]
    return sim + html


class YolHatasi(ValueError):
    pass


# Java koşusunda raporlar Maven `target/` altındadır (`results/` yok). `target/`'ın tamamı değil,
# yalnızca rapor dizinleri sunulur (derlenmiş sınıflar, Surefire dökümleri vb. dışarıda kalır).
_TARGET_RAPOR_DIZINLERI = frozenset({"allure-report", "allure-results", "extent-report"})
# Extent raporu 50. başarısız testten sonra kanıtı göreli `../kanit/tekrar-N/<Sınıf>.<metot>/`
# bağlantısıyla gösterir (O-1). `target/kanit/` altında YALNIZ görüntüler sunulur: aynı dizindeki
# `trace.zip` / `sayfa.html` hassas veri (oturum, form içeriği) taşıyabilir.
_TARGET_KANIT_DIZINI = "kanit"
_KANIT_GORUNTU_EKLERI = frozenset({".png", ".jpg", ".jpeg"})


def izinli_mi(parcalar: tuple[str, ...]) -> bool:
    if parcalar in (("run.json",), ("runner.log",)):
        return True
    if len(parcalar) < 3 or parcalar[0] != "src":
        return False
    if "results" in parcalar[1:]:
        return True
    if any(
        a == "target" and b in _TARGET_RAPOR_DIZINLERI for a, b in itertools.pairwise(parcalar[1:])
    ):
        return True
    # Kanıt: dosya `target/kanit/` altında (dizinin kendisi değil) ve görüntü.
    return PurePosixPath(parcalar[-1]).suffix.lower() in _KANIT_GORUNTU_EKLERI and any(
        a == "target" and b == _TARGET_KANIT_DIZINI for a, b in itertools.pairwise(parcalar[1:-1])
    )


def coz(kok: Path, istek: str) -> Path:
    """`istek`'i (koşu dizinine göre) doğrular ve gerçek yolu döndürür; uygun değilse YolHatasi."""
    if not istek or len(istek) > 2048 or "\\" in istek or "\x00" in istek:
        raise YolHatasi("geçersiz yol")
    p = PurePosixPath(istek)
    if p.is_absolute():
        raise YolHatasi("geçersiz yol")
    parcalar = tuple(x for x in p.parts if x != "")
    if not parcalar:
        raise YolHatasi("geçersiz yol")
    for oge in parcalar:
        if oge in (".", "..") or oge.startswith(".") or not _OGE_RE.fullmatch(oge):
            raise YolHatasi("geçersiz yol")
    if not izinli_mi(parcalar):
        raise YolHatasi("bu yol sunulmaz")
    try:
        kok_gercek = kok.resolve(strict=True)
        hedef = (kok / Path(*parcalar)).resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise FileNotFoundError(istek) from exc
    if kok_gercek not in hedef.parents:
        raise YolHatasi("yol koşu dizini dışında")
    return hedef


def icerik_turu(yol: Path) -> str:
    tur = _EK_TURLER.get(yol.suffix.lower()) or mimetypes.guess_type(yol.name)[0]
    return tur or "application/octet-stream"


def basliklar(tur: str, ad: str, *, imzali: bool = False) -> dict[str, str]:
    h = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    if imzali:
        h["Referrer-Policy"] = "no-referrer"
        if tur not in _SANDBOX_TURLER:
            # Kimlik bilgisiz CORS: sandbox'lı rapor (köken `null`) ekleri `fetch` ile okuyabilir.
            h["Access-Control-Allow-Origin"] = "*"
    if tur in _SANDBOX_TURLER:
        h["Content-Security-Policy"] = _SANDBOX
    else:
        h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if tur not in _SATIR_ICI:
        guvenli = re.sub(r"[^A-Za-z0-9._-]", "_", ad)[:100] or "dosya"
        h["Content-Disposition"] = f'attachment; filename="{guvenli}"'
    return h


def listele(dizin: Path, kok: Path) -> list[dict[str, Any]]:
    kok_gercek = kok.resolve()
    out: list[dict[str, Any]] = []
    for alt in sorted(dizin.iterdir(), key=lambda p: p.name)[:MAX_LISTE]:
        if alt.name.startswith("."):
            continue
        try:
            gercek = alt.resolve()
        except OSError:
            continue
        if kok_gercek not in gercek.parents:
            continue
        out.append(
            {
                "ad": alt.name,
                "dizin": alt.is_dir(),
                "boyut": alt.stat().st_size if alt.is_file() else None,
            }
        )
    return out
