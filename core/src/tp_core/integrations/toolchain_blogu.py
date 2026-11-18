"""Toolchain isteklerinin `proje` bloğu ve app-mcp oturum başlığı (TP-COK-PROJE-PLANI §4.4, K2).

toolchain süreç ayarı kurulum geneli (D) kalır; projeye özgü değerler istek gövdesinde gider:

    {"pid", "forge_path", "mirror_path", "remote_url", "base_url", "demo_api_url", "probe_user",
     "probe_password", "run_dealers", "run_dealer_passwords", "e2e_root", "e2e_app_root",
     "e2e_java_root", "base_ref", "app_paths",
     "app": {"android"|"ios"|"windows": {"app_id", "path", "activity", "args", "workdir"}}}

Toolchain'de (`toolchain_common/proje.py`) blokta olmayan alan toolchain'in env değerine düşer;
`app.<platform>` verildiyse o platformun uygulama ayarları yalnız bloktan gelir. Cihaz uçları
(Appium, Windows VM) paylaşımlı havuzdur, blokta yoktur.

- **Varsayılan proje:** yalnız `pid` + proje config'inin süreç ortamından **farklı** verdiği alanlar
  (Home kaynağı yokken blok `{"pid"}` → toolchain bugünkü gibi env ile koşar).
- **Diğer projeler:** depo ve ayna yolu (`forge_yollari`), `remote_url` (tanımsızsa "" = uzak
  çekme kapalı) ve üç platformun `app` bloğu her zaman gider (Bayi Portalı'nın deposu/uygulaması
  sızmaz); diğer alanlar tanımlıysa gider. Eksik ortam ayarı (ör. `base_url`) için 409
  `proje_ayari_eksik` kararı çağıran özelliğindir (§4.5, `eksik_alanlar`).

**Uzak depo (ayna) token'ı — `remote_token`:** projenin GitHub bağlantısı Home'da `app` kipindeyse
(GitHub App; `TP_FORGE_REMOTE_TOKEN` Home `env_unset` ile kalkar) core-worker projenin kısa ömürlü
kurulum token'ını `POST /v1/connections/access-token {project: pid, type: github}` ile basar ve
blokta gönderir (toolchain ayna çekmesinde env token'ının yerine kullanır, test-runner'a iletmez).
Token yalnız bağlantı token'ı alma yetkisi olan süreçte (`TP_BAGLANTI_TOKENI=1`, core-worker)
basılır; core-api'de ya da Home erişilemezse alan gönderilmez (uyarı loglanır). Token kipinde alan
yoktur (bugünkü davranış: toolchain env'i). Blokta `remote_url` varsa token yalnız o adres https
ve GitHub host'undaysa gönderilir: izinli host'lar `TP_GITHUB_HOSTS` (D, virgüllü; varsayılan
`github.com`). Proje config'i aynayı başka host'a çevirirse token oraya gitmez; toolchain de aynı
kuralı (env adresi ve env token'ı dahil) uygular (`toolchain_common/proje.py:token_gonderilir_mi`).

Proje config adları toolchain'in env adlarıdır (`BASE_URL`, `DEMO_API_URL`, `TP_PROBE_USER`,
`TP_PROBE_PASSWORD`, `TP_RUN_DEALERS`, `TP_RUN_DEALER_PASSWORDS` (sır; JSON
`{"<kullanıcı>": "<parola>"}` → blok `run_dealer_passwords`; bozuk JSON gönderilmez, değer
loglanmaz), `TP_E2E_ROOT`, `TP_E2E_APP_ROOT`, `TP_E2E_JAVA_ROOT`,
`TP_APP_PATHS`, `TP_FORGE_REMOTE_URL`, `TP_APP_{ID,PATH,ACTIVITY,ARGS,WORKDIR}_<PLATFORM>`).

**Platform deposu** (`proje_blogu(platform=...)`, platform-depo ANALIZ §3.2.9): platform ayrı
GitHub deposundaysa (`ProjeOrtami(pid, platform).ayri_depo`) varsayılan proje dahil şu alanlar her
zaman gider: `forge_path` / `mirror_path` (`forge_yollari.*(pid, depo)`), `remote_url` (türetilmiş;
taban ayna kapalıysa ""), `e2e_app_root` (`TP_E2E_APP_ROOT_<P>`, yoksa taban) ve `app_paths`
(`TP_APP_PATHS_<P>`, devralmaz; boş liste). Ayna token'ı aynı host kuralıyla gider.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any
from urllib.parse import urlsplit

from tp_core.integrations import forge_yollari, proje_ortami
from tp_core.integrations.proje_ortami import APP_ALANLARI, PLATFORMLAR, pid_coz
from tp_core.proje import ayar as _ayar
from tp_core.proje.baglam import varsayilan_pid

log = logging.getLogger(__name__)

APP_MCP_BASLIGI = "X-TP-App"
GITHUB_HOSTS_ENV = "TP_GITHUB_HOSTS"  # D: ayna token'ının gönderilebileceği host'lar (virgüllü)
VARSAYILAN_GITHUB_HOSTS = ("github.com",)

# blok alanı → proje config adı (metin alanları)
METIN_ALANLARI: dict[str, str] = {
    "base_url": "BASE_URL",
    "demo_api_url": "DEMO_API_URL",
    "probe_user": "TP_PROBE_USER",
    "e2e_root": "TP_E2E_ROOT",
    "e2e_app_root": "TP_E2E_APP_ROOT",
    "e2e_java_root": "TP_E2E_JAVA_ROOT",
}
APP_PATHS_ENV = "TP_APP_PATHS"
ORTAM_ALANLARI = ("base_url", "demo_api_url")  # koşu için gerekli ortam adresleri


def _deger(ad: str, pid: str, varsayilan: bool, *, sir: bool = False) -> str | None:
    """Projenin değeri; varsayılan projede süreç ortamıyla aynıysa None (toolchain env'i)."""
    d = _ayar.sir(ad, pid=pid) if sir else _ayar.ayar(ad, pid=pid)
    if d is None:
        return None
    d = d.strip()
    if varsayilan and d == (os.environ.get(ad) or "").strip():
        return None
    return d


def _app(pid: str, varsayilan: bool) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for platform in PLATFORMLAR:
        alanlar = {
            alan: d
            for alan, onek in APP_ALANLARI.items()
            if (d := _deger(f"{onek}_{platform.upper()}", pid, varsayilan))
        }
        if alanlar or not varsayilan:
            out[platform] = alanlar
    return out


def _liste(deger: str) -> list[str]:
    return [b.strip() for b in deger.split(",") if b.strip()]


def proje_blogu(pid: str | None = None, platform: str | None = None) -> dict[str, Any]:
    """Bağlamdaki (ya da verilen) projenin toolchain bloğu (`platform` verilirse o platformun
    deposuyla)."""
    p = pid_coz(pid)
    blok = _taban_blok(p)
    gorunum = proje_ortami.ProjeOrtami(p, platform)
    if gorunum.ayri_depo:
        blok["forge_path"] = str(forge_yollari.depo_yolu(p, gorunum.depo))
        blok["mirror_path"] = str(forge_yollari.ayna_yolu(p, gorunum.depo))
        blok["remote_url"] = (gorunum.get("TP_FORGE_REMOTE_URL") or "").strip()
        if kok := (gorunum.get("TP_E2E_APP_ROOT") or "").strip():
            blok["e2e_app_root"] = kok
        else:
            blok.pop("e2e_app_root", None)
        blok["app_paths"] = _liste(gorunum.get(APP_PATHS_ENV) or "")
        # 014: ayrı depoda dil kökleri kaplamadan (`<kok_ayari>` ← `<kok_ayari>_<P>` ?? taban).
        kokler = dict(blok.get("dil_kokleri") or {})
        for ad in _dil_kok_adlari():
            if ad.endswith(("_ANDROID", "_IOS", "_WINDOWS")):
                continue
            if d := (gorunum.get(ad) or "").strip():
                kokler[ad] = d
        if kokler:
            blok["dil_kokleri"] = kokler
        # Ayrı deponun varsayılan dalı (merge-base tabanı); toolchain yoksa "main" kullanır.
        if dal := (gorunum.get("TP_FORGE_CHECK_REF") or "").strip():
            blok["base_ref"] = dal
    _ortam_alanlari(blok, p)
    if token := _uzak_token(p):
        # Blokta adres yoksa (varsayılan proje, env'le aynı) toolchain kendi env adresini kullanır
        # ve aynı host kuralını orada uygular.
        if "remote_url" not in blok or github_adresi_mi(blok["remote_url"]):
            blok["remote_token"] = token
        else:
            log.warning(
                "ayna token'ı gönderilmedi (%s): ayna adresi izinli GitHub host'unda değil", p
            )
    return blok


def _ortam_alanlari(blok: dict[str, Any], p: str) -> None:
    """Test ortamı bağlamında (`proje.ortam.ortam_icinde`) bloğa ortam kimliği eklenir; toolchain
    Canlı (`tur=prod`) ortamda uygulamanın test verisi uçlarını (DEMOAPP_TEST_TOKEN) ve kırma
    koşularını kapatır. Ortam parolayı (A1 ile) kaldırdıysa toolchain env parolasına düşmesin
    diye boş parola gider (Deployment parolası ortamın adresine gönderilmez)."""
    from tp_core.proje.ortam import mevcut_ortam

    o = mevcut_ortam()
    if o is None or o.pid != p:
        return
    blok["ortam"] = {"eid": o.eid, "ad": o.ad, "tur": o.tur}
    if "probe_password" not in blok and _ayar.sir("TP_PROBE_PASSWORD", pid=p) is None:
        blok["probe_password"] = ""
    if "run_dealer_passwords" not in blok and _ayar.sir("TP_RUN_DEALER_PASSWORDS", pid=p) is None:
        blok["run_dealer_passwords"] = {}


def _taban_blok(p: str) -> dict[str, Any]:
    """Varsayılan deponun bloğu (token hariç)."""
    varsayilan = p == varsayilan_pid()
    blok: dict[str, Any] = {"pid": p}
    if not varsayilan:
        blok["forge_path"] = str(forge_yollari.depo_yolu(p))
        blok["mirror_path"] = str(forge_yollari.ayna_yolu(p))
        blok["remote_url"] = (_ayar.ayar("TP_FORGE_REMOTE_URL", pid=p) or "").strip()
    elif (uzak := _deger("TP_FORGE_REMOTE_URL", p, varsayilan)) is not None:
        blok["remote_url"] = uzak
    for alan, ad in METIN_ALANLARI.items():
        if d := _deger(ad, p, varsayilan):
            blok[alan] = d.rstrip("/") if alan.endswith("_url") else d
    if parola := _deger("TP_PROBE_PASSWORD", p, varsayilan, sir=True):
        blok["probe_password"] = parola
    if bayiler := _deger("TP_RUN_DEALERS", p, varsayilan):
        blok["run_dealers"] = _liste(bayiler)
    if parolalar := _kosu_parolalari(p, varsayilan):
        blok["run_dealer_passwords"] = parolalar
    if (yollar := _deger(APP_PATHS_ENV, p, varsayilan)) is not None:
        blok["app_paths"] = _liste(yollar)
    if app := _app(p, varsayilan):
        blok["app"] = app
    if kokler := _dil_kokleri(p, varsayilan):
        blok["dil_kokleri"] = kokler
    return blok


def _kosu_parolalari(p: str, varsayilan: bool) -> dict[str, str] | None:
    """Koşu hesabı başına parola (`TP_RUN_DEALER_PASSWORDS`, sır). Varsayılan projede süreç
    ortamıyla aynıysa None (toolchain env'i). Bozuk değer gönderilmez (hesaplar ortak parolayla
    girer); uyarıda değer yoktur."""
    ham = _deger("TP_RUN_DEALER_PASSWORDS", p, varsayilan, sir=True)
    if not ham:
        return None
    try:
        v = json.loads(ham)
    except ValueError:
        v = None
    if not isinstance(v, dict) or not all(
        isinstance(k, str) and k.strip() and isinstance(x, str) and x for k, x in v.items()
    ):
        log.warning("TP_RUN_DEALER_PASSWORDS yok sayıldı (%s): JSON {kullanıcı: parola} değil", p)
        return None
    return {k.strip(): x for k, x in v.items()}


def _dil_kok_adlari() -> tuple[str, ...]:
    """014: ts/java dışı dil köklerinin env adları (taban + matristeki `_<P>` kaplamaları)."""
    from tp_core.features.codegen import platform as platformlar

    adlar: list[str] = []
    for c in platformlar.CATILAR.values():
        if c.dil in (platformlar.TS, platformlar.JAVA):
            continue
        adlar.append(c.kok_ayari)
        if ad_p := platformlar.kok_ayari_platform(c.kok_ayari, c.platform):
            adlar.append(ad_p)
    return tuple(dict.fromkeys(adlar))


def _dil_kokleri(p: str, varsayilan: bool) -> dict[str, str]:
    """014 (plan.md §3.1): projenin dil kökleri (toolchain `ProjeBlogu.dil_kokleri`); varsayılan
    projede yalnız süreç ortamından farklı olanlar."""
    return {ad: d for ad in _dil_kok_adlari() if (d := _deger(ad, p, varsayilan))}


def github_hostlari() -> frozenset[str]:
    """Ayna token'ının gönderilebileceği host'lar (`TP_GITHUB_HOSTS`, yoksa `github.com`)."""
    ham = os.environ.get(GITHUB_HOSTS_ENV) or ""
    hostlar = {h.strip().lower().rstrip(".") for h in ham.split(",") if h.strip()}
    return frozenset(hostlar or VARSAYILAN_GITHUB_HOSTS)


def github_adresi_mi(adres: str | None) -> bool:
    """`adres` https ve host'u izinli GitHub host'u mu (kullanıcı bilgisi / port olmadan)?"""
    if not adres:
        return False
    try:
        parca = urlsplit(adres.strip())
        port = parca.port
    except ValueError:
        return False
    host = (parca.hostname or "").lower().rstrip(".")
    return (
        parca.scheme == "https"
        and not parca.username
        and port in (None, 443)
        and host in github_hostlari()
    )


def _uzak_token(pid: str) -> str | None:
    """GitHub App kipinde projenin kurulum token'ı (ayna okuması için); token kipinde None."""
    from tp_core.home_config import baglanti

    if proje_ortami.baglanti_kipi("github", pid) != "app" or not baglanti.yetkili_surec():
        return None
    try:
        return proje_ortami.token_al("github", pid).access_token
    except baglanti.BaglantiHatasi as exc:
        log.warning("toolchain ayna token'ı alınamadı (%s): %s", pid, exc)
        return None


def eksik_alanlar(blok: dict[str, Any]) -> list[str]:
    """Varsayılan dışı projede koşu için tanımsız ortam alanları (§4.5: 409 `proje_ayari_eksik`).

    `BASE_URL`/`DEMO_API_URL` web uygulamasının adresleridir: yalnız `web` özelliği açık projede
    zorunludur (yalnız mobil / AI agent projesinin koşusu 409 almaz; web koşusu o projede zaten
    `platform_gerekli("web")` ile kapalıdır)."""
    pid = blok.get("pid")
    if pid == varsayilan_pid():
        return []
    from tp_core.home_config import durum

    if not durum.ozellik_acik("web", pid=pid):
        return []
    return [METIN_ALANLARI[a] for a in ORTAM_ALANLARI if not blok.get(a)]


def ortam_denetle(blok: dict[str, Any]) -> dict[str, Any]:
    """Koşu isteklerinde (`/check`, `/locator-probe`) eksik ortam ayarı → 409 `proje_ayari_eksik`.

    Blokta olmayan alan toolchain'de env değerine (varsayılan projenin uygulamasına) düşeceği
    için varsayılan dışı projede koşu başlatılmaz. Bloğu aynen döner."""
    if eksik := eksik_alanlar(blok):
        from tp_core.api.errors import ProjeAyariEksik

        raise ProjeAyariEksik(
            f"Projenin test ortamı ayarı eksik ({', '.join(eksik)}); Home'da proje ayarlarından "
            "tanımlayın"
        )
    return blok


def ortam_gerekli(pid: str | None = None) -> None:
    """API girişinde erken denetim (iş kuyruğa girmeden): koşu başlatan uçlar varsayılan dışı
    projede ortam ayarı eksikse 409 `proje_ayari_eksik` verir (`ortam_denetle`)."""
    p = pid_coz(pid)
    if p == varsayilan_pid():
        return
    blok: dict[str, Any] = {"pid": p}
    for alan in ORTAM_ALANLARI:
        blok[alan] = (_ayar.ayar(METIN_ALANLARI[alan], pid=p) or "").strip()
    ortam_denetle(blok)


def app_mcp_basligi(pid: str | None = None) -> dict[str, str]:
    """app-mcp `initialize` isteğinin oturum başlığı (`X-TP-App`: base64url JSON `app` bloğu).

    Başlığı yalnız core kurar (ajan MCP bağlantısının başlığını seçemez); boş = env uygulaması.
    """
    app = proje_blogu(pid).get("app") or {}
    if not app:
        return {}
    ham = json.dumps(app, separators=(",", ":"), sort_keys=True).encode()
    return {APP_MCP_BASLIGI: base64.urlsafe_b64encode(ham).decode().rstrip("=")}
