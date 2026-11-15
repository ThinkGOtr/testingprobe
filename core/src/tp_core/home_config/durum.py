"""Çalışan süreçte (core-api, core-worker) Home etkin config'i: yenileme, uygulama, sorgu.

`CONFIG_SOURCE=env` iken `baslat()` hiçbir şey yapmaz ve tüm sorgular bugünkü davranışı verir
(`ozellikler()` → `None` = hepsi açık; `baglanti_kipi()` → `token`).

`CONFIG_SOURCE=home` iken açılışta bir kez (kısa zaman aşımıyla) ve sonra `TP_CONFIG_YENILEME_S`
(varsayılan 60) saniyede bir `GET /v1/config/effective` çağrılır (ETag; değişmediyse 304).

Uygulama kuralı — iki sınıf anahtar:

- **Çalışma anında etkiyen** (`CALISMA_ANINDA`): okuyucusu değeri her çağrıda `os.environ`dan ya
  da önbelleği temizlenen ayar nesnesinden okuyan, sır OLMAYAN, yalnız çekirdek süreçlerini
  etkileyen anahtarlar. Hemen `os.environ`a yazılır, ayar önbellekleri temizlenir. Home anahtarı
  geri çekerse açılıştaki değer geri gelir.
- **Yeniden başlatmada uygulanan**: diğer her şey — sırlar (`env_secrets`), başka konteynerlerin
  okuduğu değerler (toolchain, test-runner, app-mcp, playwright-mcp, demo uygulaması), süreç
  bağlantısını kuran ayarlar (TP_FORGE, JIRA_BASE_URL, model sağlayıcısı …). Bunlar VM açılış
  betiğinin ürettiği env dosyasıyla (`bin/up.sh` → `python3 -m tp_core.home_config`) gelir;
  çalışırken değişirse yalnız adı `bekleyen` listesine yazılır (durum + log).

Proje özellikleri, bağlantı kipleri ve organizasyon/proje adları çalışma anında etkir.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from tp_core.home_config import yukleyici as y

log = logging.getLogger("tp_core.home_config")

YENILEME_ENV = "TP_CONFIG_YENILEME_S"
VARSAYILAN_YENILEME_S = 60.0
VARSAYILAN_LKG_DIZINI = "/var/lib/tp-config"

CALISMA_ANINDA: frozenset[str] = frozenset(
    {
        # Yönetişim / kota (çağrı anında os.environ)
        "TP_DENETIM_KAPISI",
        "TP_DENETIM_GUNLUK_SINIR",
        "TP_REVIEW_GUNLUK_SINIR",
        # Asistan (çağrı anında os.environ)
        "TP_ASISTAN_ONERI",
        "TP_ASISTAN_OTOMATIK_DERIN",
        "TP_ASISTAN_VERI_ROLLERI",
        "TP_ASISTAN_DENETIM_ENGEL",
        "TP_ASISTAN_DENETIM_UYARI",
        # Kontrol Kulesi, kazanç, koşu (çağrı anında os.environ)
        "TP_CT_SON_KOSU",
        "TP_CT_FLAKY_GUN",
        "TP_CT_TREND_GUN",
        "TP_MANUAL_BASELINE_S",
        "TP_CI_GITHUB_TIMEOUT_S",
        "TP_CI_NIGHTLY_SAAT",
        "TP_CODEGEN_SCREENSHOT_DAYS",
        "TP_GITHUB_ARTIFACTS_KEEP",
        # Gereksinim akışı (RequirementsSettings; önbellek temizlenir)
        "TP_CONSISTENCY_MAX_ROUNDS",
        "TP_PO_POLL_S",
        # PO / rol hesapları (JiraSettings, Settings; önbellek temizlenir)
        "JIRA_PO_ACCOUNT_IDS",
        "TP_PO_JIRA_USERS",
        "JIRA_HESAP_ANALIST",
        "JIRA_HESAP_PO",
        "JIRA_HESAP_MUHENDIS",
        "JIRA_HESAP_TESTCI",
        "TP_JIRA_BOT_ACCOUNT_IDS",
        # Forge zorunlu check'leri (GitHubForge her kuruluşta okur)
        "TP_PLATFORMS",
        "TP_WEB_DILLERI",
        "TP_REQUIRED_CHECKS",
    }
)


def _onbellekleri_temizle() -> None:
    """Değeri `lru_cache`li ayar nesnelerinden okunan anahtarlar için."""
    from tp_core.config import get_settings
    from tp_core.features.requirements.settings import get_requirements_settings
    from tp_core.integrations.jira import get_jira_settings

    for f in (get_settings, get_jira_settings, get_requirements_settings):
        f.cache_clear()


@dataclass
class _Yapi:
    http: y.Http | None = None
    id_token: Callable[[str], str] | None = None
    temizle: Callable[[], None] = _onbellekleri_temizle


@dataclass
class Durum:
    kaynak: str = "env"  # env | home | lkg
    cfg: y.EtkinConfig | None = None
    son_deneme: float | None = None
    son_basari: float | None = None
    hata: str | None = None
    uygulanan: list[str] = field(default_factory=list)
    bekleyen: list[str] = field(default_factory=list)
    reddedilen: list[str] = field(default_factory=list)


_YAPI = _Yapi()
_DURUM = Durum()
_KILIT = threading.RLock()
_YUKLEYICI: y.Yukleyici | None = None
_BASLANGIC_ENV: dict[str, str] = {}
_ILK_SIR_REFLERI: dict[str, str] | None = None
# Bizim yazdığımız çalışma anı anahtarlarının açılıştaki değeri (None = yoktu).
_ORIJINAL: dict[str, str | None] = {}
_DUR = threading.Event()
_IPLIK: threading.Thread | None = None


def configure(*, http: y.Http | None = None, id_token: Callable[[str], str] | None = None,
              temizle: Callable[[], None] | None = None) -> None:  # fmt: skip
    """Testler: sahte Home taşıyıcısı, ID token sağlayıcı, önbellek temizleyici."""
    if http is not None:
        _YAPI.http = http
    if id_token is not None:
        _YAPI.id_token = id_token
    if temizle is not None:
        _YAPI.temizle = temizle


def reset() -> None:
    """Testler: durumu sıfırlar, yazılan anahtarları geri alır, yenileyiciyi durdurur."""
    global _YAPI, _DURUM, _YUKLEYICI, _ILK_SIR_REFLERI, _IPLIK
    durdur()
    with _KILIT:
        for k, v in _ORIJINAL.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _ORIJINAL.clear()
        _BASLANGIC_ENV.clear()
        _YAPI = _Yapi()
        _DURUM = Durum()
        _YUKLEYICI = None
        _ILK_SIR_REFLERI = None
        _IPLIK = None


def _id_token(audience: str) -> str:
    if _YAPI.id_token is not None:
        return _YAPI.id_token(audience)
    from tp_core.auth import aiprobe

    try:
        return aiprobe.token_saglayici()(audience)
    except aiprobe.HomeUlasilamaz as exc:
        raise y.Ulasilamaz("servis kimliği alınamadı") from exc


def _lkg_yolu(servis: str) -> str:
    acik = y.ayar(os.environ, y.LKG_ENV)
    if acik:
        return acik
    return os.path.join(VARSAYILAN_LKG_DIZINI, f"lkg-{servis}.json")


def _yukleyici(servis: str) -> y.Yukleyici | None:
    global _YUKLEYICI
    if _YUKLEYICI is not None:
        return _YUKLEYICI
    proje = y.ayar(os.environ, y.PROJE_ENV)
    url, audience = y.home_adresi(os.environ)
    if not proje or not url:
        log.error(
            "CONFIG_SOURCE=home ama TP_HOME_PROJECT / AIPROBE_HOME_RUN_URL eksik: env ile "
            "çalışılıyor"
        )
        return None
    istemci = y.HomeConfigIstemcisi(
        url, proje, _id_token, audience=audience, http=_YAPI.http or y.urllib_http
    )
    _YUKLEYICI = y.Yukleyici(istemci, _lkg_yolu(servis))
    return _YUKLEYICI


def yenile(servis: str = "core") -> Durum:
    """Bir tur: çek → uygula. Hata fırlatmaz; durumu döner."""
    global _ILK_SIR_REFLERI
    if y.kaynak() != "home":
        return _DURUM
    with _KILIT:
        if not _BASLANGIC_ENV:
            _BASLANGIC_ENV.update(os.environ)
        yk = _yukleyici(servis)
        _DURUM.son_deneme = time.time()
        if yk is None:
            _DURUM.hata = "yapılandırma eksik"
            return _DURUM
        sonuc = yk.yukle()
        _DURUM.hata = sonuc.hata
        _DURUM.kaynak = sonuc.kaynak
        if sonuc.cfg is None:
            return _DURUM
        if sonuc.kaynak == "home":
            _DURUM.son_basari = _DURUM.son_deneme
        cfg = sonuc.cfg
        if _DURUM.cfg is not None and dict(_DURUM.cfg.ham) == dict(cfg.ham):
            return _DURUM
        _DURUM.cfg = cfg
        if _ILK_SIR_REFLERI is None:
            _ILK_SIR_REFLERI = {str(k): str(v) for k, v in cfg.env_secrets.items()}
        _uygula(cfg)
        return _DURUM


def _uygula(cfg: y.EtkinConfig) -> None:
    gorunum = y.env_gorunumu(cfg)  # yalnız sır olmayan `env`
    _DURUM.reddedilen = sorted(gorunum.reddedilen)
    degisen: list[str] = []
    for k in sorted(CALISMA_ANINDA):
        hedef = gorunum.degerler.get(k)
        if hedef is None:
            if k not in _ORIJINAL:
                continue  # hiç yazmadık
            hedef = _ORIJINAL[k]  # Home anahtarı geri çekti: açılış değeri
        if k not in _ORIJINAL:
            _ORIJINAL[k] = os.environ.get(k)
        if os.environ.get(k) != hedef:
            if hedef is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = hedef
            degisen.append(k)
    bekleyen = {
        k
        for k, v in gorunum.degerler.items()
        if k not in CALISMA_ANINDA and k in _BASLANGIC_ENV and _BASLANGIC_ENV[k] != v
    }
    for k, ref in cfg.env_secrets.items():
        if (_ILK_SIR_REFLERI or {}).get(str(k)) != str(ref):
            bekleyen.add(str(k))
    _DURUM.uygulanan = sorted(set(_DURUM.uygulanan) | set(degisen))
    _DURUM.bekleyen = sorted(bekleyen)
    if degisen:
        try:
            _YAPI.temizle()
        except Exception:
            log.warning("ayar önbellekleri temizlenemedi", exc_info=True)
        log.info("home config: çalışma anında uygulandı: %s", ", ".join(degisen))
    if bekleyen:
        log.warning(
            "home config: yeniden başlatmada uygulanacak değişiklikler: %s",
            ", ".join(sorted(bekleyen)),
        )


def _dongu(servis: str, aralik: float) -> None:
    while not _DUR.wait(aralik):
        try:
            yenile(servis)
        except Exception:
            log.exception("home config yenilemesi başarısız")


def baslat(servis: str) -> None:
    """Süreç açılışında: ilk yükleme (eşzamanlı) + arka plan yenileyici. env kipinde no-op."""
    global _IPLIK
    if y.kaynak() != "home":
        return
    yenile(servis)
    try:
        aralik = max(10.0, float(y.ayar(os.environ, YENILEME_ENV) or VARSAYILAN_YENILEME_S))
    except ValueError:
        aralik = VARSAYILAN_YENILEME_S
    with _KILIT:
        if _IPLIK is not None and _IPLIK.is_alive():
            return
        _DUR.clear()
        _IPLIK = threading.Thread(
            target=_dongu, args=(servis, aralik), name="home-config", daemon=True
        )
        _IPLIK.start()
    log.info("home config: kaynak=%s, yenileme %d sn", _DURUM.kaynak, int(aralik))


def durdur() -> None:
    _DUR.set()
    ip = _IPLIK
    if ip is not None and ip.is_alive() and ip is not threading.current_thread():
        ip.join(timeout=2)


# ------------------------------------------------------------------ sorgular


def etkin() -> y.EtkinConfig | None:
    """Home'dan (ya da LKG'den) gelen config; env kipinde ya da hiç yüklenemediyse `None`."""
    if y.kaynak() != "home":
        return None
    return _DURUM.cfg


def ozellikler() -> dict[str, bool] | None:
    """Proje özellikleri; `None` = Home config yok → bugünkü davranış (hepsi açık)."""
    cfg = etkin()
    return None if cfg is None else cfg.ozellikler


def ozellik_acik(ad: str) -> bool:
    o = ozellikler()
    return True if o is None else bool(o.get(ad, False))


def baglanti_kipi(tur: str) -> str:
    cfg = etkin()
    return "token" if cfg is None else cfg.baglanti_kipi(tur)


def baglanti_public(tur: str) -> Mapping[str, Any]:
    cfg = etkin()
    return {} if cfg is None else cfg.baglanti_public(tur)


def org_proje() -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    cfg = etkin()
    return None if cfg is None else (cfg.org, cfg.proje)


def ozet() -> dict[str, Any]:
    """Durum özeti (değer yok, yalnız ad ve zaman)."""
    d = _DURUM
    cfg = d.cfg
    return {
        "kaynak": y.kaynak() if y.kaynak() == "env" else d.kaynak,
        "proje": (cfg.proje.get("pid") if cfg else None),
        "etag": cfg.etag if cfg else None,
        "son_deneme": d.son_deneme,
        "son_basari": d.son_basari,
        "hata": d.hata,
        "uygulanan": list(d.uygulanan),
        "bekleyen": list(d.bekleyen),
        "reddedilen": list(d.reddedilen),
    }
