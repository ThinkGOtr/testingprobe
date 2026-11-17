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

Hedef–sır bağı (A1): Home `env_unset` listesi ve yerel kural (`yukleyici.BAGLI_SIRLAR`: hedefi
Home'dan gelen, kendisi Home'dan gelmeyen sır) adları os.environ'dan HEMEN silinir; liste
daralınca geri konur.

Reddedilme (Config R1 N4): Home 403/404 dönerse (proje silindi, ürün projeden çıkarıldı, erişim
geri alındı) LKG'ye düşülmez. Home'dan gelen değer ve sır adları (`env` ∪ `env_secrets`, son
bilinen config'ten) os.environ'dan kaldırılır, çalışma anında yazdıklarımız açılış değerine döner,
proje özellikleri KAPALI sayılır (fail-closed) ve durum `kaynak=reddedildi` olarak raporlanır.
Kaldırılan adlar Home yeniden kabul etse bile ancak yeniden başlatmada geri gelir (`bekleyen`).

Çok proje (TP-COK-PROJE-PLANI §3.1): yukarıdaki süreç ortamı kuralları yalnız **varsayılan
projeye** (`TP_HOME_PROJECT`) uygulanır. Kurulumun diğer projeleri (`tp_proje` aktif satırları +
`TP_HOME_PROJECTS`) kendi `Yukleyici`'si, ETag'i ve LKG dosyasıyla aynı döngüde yenilenir; değerleri
ve (Secret Manager'dan bellekte, `SIR_TTL_S` ömürlü çözülen) sırları süreç ortamına HİÇ yazılmaz,
yalnız `tp_core.proje.ayar` üzerinden okunur (`ayar_cozucu`/`ayar_surumu`, `baslat` bağlar). Home
bir projeyi reddederse (403/404) o projenin özellikleri kapalı, ayarları boştur (fail-closed) ve
`_kurulum` zincirine `config.proje_reddedildi` (aktif=false önerisi) yazılır; satır silinmez.
Sorgular (`etkin`, `ozellikler`, `ozellik_acik`, `baglanti_kipi`, `baglanti_public`,
`org_proje`) `pid` almazsa bağlamdaki projeye, bağlam yoksa varsayılan projeye bakar.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from tp_core.home_config import yukleyici as y
from tp_core.proje.baglam import KURULUM, baglamla, varsa

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
    sir_cozucu: Callable[[str], str] | None = None
    projeler: Callable[[], list[str]] | None = None
    kaydet: Callable[[str, str], None] | None = None
    denetim: Callable[[str, dict[str, Any]], None] | None = None


@dataclass
class Durum:
    kaynak: str = "env"  # env | home | lkg | reddedildi
    cfg: y.EtkinConfig | None = None
    son_deneme: float | None = None
    son_basari: float | None = None
    hata: str | None = None
    uygulanan: list[str] = field(default_factory=list)
    bekleyen: list[str] = field(default_factory=list)
    reddedilen: list[str] = field(default_factory=list)
    kaldirilan: list[str] = field(default_factory=list)
    geri_cekilen: list[str] = field(default_factory=list)


_YAPI = _Yapi()
_DURUM = Durum()
_KILIT = threading.RLock()
_YUKLEYICI: y.Yukleyici | None = None
_BASLANGIC_ENV: dict[str, str] = {}
_ILK_SIR_REFLERI: dict[str, str] | None = None
# Bizim yazdığımız çalışma anı anahtarlarının açılıştaki değeri (None = yoktu).
_ORIJINAL: dict[str, str | None] = {}
# A1: `env_unset` / bağlı sır kuralıyla os.environ'dan sildiğimiz adların önceki değeri.
_SILINEN: dict[str, str] = {}
# N4: Home reddedince os.environ'dan kaldırdığımız Home kaynaklı adlar (değer tutulmaz).
_GERI_CEKILEN: set[str] = set()
_DUR = threading.Event()
_IPLIK: threading.Thread | None = None

# ------------------------------------------------------------- çok proje durumu (§3.1)

# Ek projelerin sırları bellekte en çok bu kadar tutulur; sonra yeniden çözülür (döndürme).
SIR_TTL_S = 3600.0
# Keşif (§5.2 b): Home'un reddettiği pid için yeniden deneme aralığı.
KESIF_RED_S = 600.0
EK_PROJELER_ENV = "TP_HOME_PROJECTS"
_PID_DOSYA = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class _EkProje:
    """Varsayılan dışındaki bir projenin config durumu (süreç ortamına yazılmaz)."""

    pid: str
    yukleyici: y.Yukleyici | None
    durum: Durum = field(default_factory=Durum)
    gorunum: dict[str, str] | None = None
    sir_zamani: float | None = None
    reddedildi_bildirildi: bool = False


# pid → `proje.ayar` görünümü (legacy env adı → değer). Varsayılan projede sırlar yoktur (süreç
# ortamından okunur); ek projelerde çözülmüş sırlar dahildir. None = reddedildi / yüklenemedi.
_GORUNUM: dict[str, dict[str, str] | None] = {}
_EK: dict[str, _EkProje] = {}
_KESIF_RED: dict[str, float] = {}
# pid → görünüm değişim sayacı (`ayar_surumu`: etag aynı kalsa da sır döndürmesi önbellek kırar).
_SAYAC: dict[str, int] = {}
_BAGLI: list[bool] = [False]


def configure(*, http: y.Http | None = None, id_token: Callable[[str], str] | None = None,
              temizle: Callable[[], None] | None = None,
              sir_cozucu: Callable[[str], str] | None = None,
              projeler: Callable[[], list[str]] | None = None,
              kaydet: Callable[[str, str], None] | None = None,
              denetim: Callable[[str, dict[str, Any]], None] | None = None) -> None:  # fmt: skip
    """Testler: sahte Home taşıyıcısı, ID token sağlayıcı, önbellek temizleyici; çok projede sır
    çözücü (ek projeler), kurulu proje listesi, proje kaydı (`pid, kaynak`) ve denetim yazıcısı."""
    if http is not None:
        _YAPI.http = http
    if id_token is not None:
        _YAPI.id_token = id_token
    if temizle is not None:
        _YAPI.temizle = temizle
    if sir_cozucu is not None:
        _YAPI.sir_cozucu = sir_cozucu
    if projeler is not None:
        _YAPI.projeler = projeler
    if kaydet is not None:
        _YAPI.kaydet = kaydet
    if denetim is not None:
        _YAPI.denetim = denetim


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
        for k, v in _SILINEN.items():
            os.environ[k] = v
        _SILINEN.clear()
        _GERI_CEKILEN.clear()
        _BASLANGIC_ENV.clear()
        _YAPI = _Yapi()
        _DURUM = Durum()
        _YUKLEYICI = None
        _ILK_SIR_REFLERI = None
        _IPLIK = None
        _GORUNUM.clear()
        _EK.clear()
        _KESIF_RED.clear()
        _SAYAC.clear()
    from tp_core.proje import ayar as proje_ayar

    if _BAGLI[0]:
        proje_ayar._kaynak_coz()
        _BAGLI[0] = False


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
    """Bir tur: varsayılan proje (çek → uygula) + kurulumun diğer projeleri. Hata fırlatmaz;
    varsayılan projenin durumunu döner."""
    d = _varsayilani_yenile(servis)
    if y.kaynak() == "home":
        for pid in _ek_pidler():
            try:
                yenile_proje(pid, servis)
            except Exception:
                log.exception("home config: proje yenilemesi başarısız (%s)", pid)
    return d


def _varsayilani_yenile(servis: str) -> Durum:
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
        if sonuc.kaynak == "reddedildi":
            _reddedildi(sonuc.geri_cekilen)
            _gorunumu_ayarla(_varsayilan_pid() or "", None)
            return _DURUM
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
    # Yalnız sır olmayan `env`; taban = süreç açılışındaki env (açılış betiğinin ürettiği .env).
    gorunum = y.env_gorunumu(cfg, taban=_BASLANGIC_ENV)
    # `proje.ayar` görünümü (sırlar süreç ortamından; A1 ile silinenler zaten yok).
    _gorunumu_ayarla(_varsayilan_pid() or "", gorunum.degerler)
    _DURUM.reddedilen = sorted(gorunum.reddedilen)
    degisen: list[str] = _sirlari_kaldir(gorunum.kaldirilan)
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
    # Reddedilmede kaldırılan adlar ancak yeniden başlatmada geri gelir.
    bekleyen |= {
        k
        for k in _GERI_CEKILEN
        if k not in CALISMA_ANINDA and (k in cfg.env or k in cfg.env_secrets)
    }
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


def _reddedildi(geri_cekilen: y.EtkinConfig | None) -> None:
    """N4: Home 403/404. Home'dan gelen değer ve sırların adları os.environ'dan kaldırılır,
    çalışma anında yazdıklarımız açılış değerine döner, config bırakılır (özellikler kapalı).
    Korunan (Deployment) adlara dokunulmaz; A1 ile silinmiş bağlı sırlar silinmiş kalır."""
    adlar: set[str] = set(_ILK_SIR_REFLERI or {})
    for cfg in (_DURUM.cfg, geri_cekilen):
        if cfg is not None:
            adlar |= {str(k) for k in cfg.env} | {str(k) for k in cfg.env_secrets}
    adlar = {k for k in adlar if y.gecerli_anahtar(k)}
    degisen: list[str] = []
    for k, v in sorted(_ORIJINAL.items()):
        if os.environ.get(k) != v:
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
            degisen.append(k)
    _ORIJINAL.clear()
    for k in sorted(adlar):
        if k in os.environ:
            os.environ.pop(k, None)
            degisen.append(k)
    _GERI_CEKILEN.update(adlar)
    _DURUM.cfg = None
    _DURUM.uygulanan = []
    _DURUM.bekleyen = []
    _DURUM.geri_cekilen = sorted(_GERI_CEKILEN)
    if degisen:
        try:
            _YAPI.temizle()
        except Exception:
            log.warning("ayar önbellekleri temizlenemedi", exc_info=True)
    log.error(
        "home config: Home erişimi reddetti (%s); Home kaynaklı %d ad kaldırıldı, proje "
        "özellikleri kapalı: %s",
        _DURUM.hata,
        len(adlar),
        ", ".join(sorted(adlar)),
    )


def _reddedildi_mi() -> bool:
    return y.kaynak() == "home" and _DURUM.kaynak == "reddedildi"


def _sirlari_kaldir(kaldirilan: list[str]) -> list[str]:
    """A1 çalışma anı: hedefi Home'dan gelen, kendisi Home'dan gelmeyen bağlı sırlar (Home
    `env_unset` ∪ yerel kural) os.environ'dan HEMEN silinir (yeniden başlatma beklenmez; güvenli
    yön). Liste daralırsa silinen değer geri konur (Home artık o sırrın kullanımına izin
    veriyor)."""
    degisen: list[str] = []
    hedef = set(kaldirilan)
    for k in sorted(hedef):
        if k in os.environ:
            _SILINEN.setdefault(k, os.environ[k])
            os.environ.pop(k, None)
            degisen.append(k)
    for k in sorted(set(_SILINEN) - hedef):
        os.environ[k] = _SILINEN.pop(k)
        degisen.append(k)
    _DURUM.kaldirilan = sorted(hedef)
    return degisen


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
    ayar_kaynagini_bagla()
    projeleri_kaydet()
    yenile(servis)
    try:
        aralik = max(10.0, float(y.ayar(os.environ, YENILEME_ENV) or VARSAYILAN_YENILEME_S))
    except ValueError:
        aralik = VARSAYILAN_YENILEME_S
    with _KILIT:
        if _IPLIK is not None and _IPLIK.is_alive():
            return
        _DUR.clear()
        # Kurulum geneli döngü: proje bağlamı taşımaz (her proje kendi yükleyicisiyle).
        _IPLIK = threading.Thread(
            target=baglamla(_dongu), args=(servis, aralik), name="home-config", daemon=True
        )
        _IPLIK.start()
    log.info("home config: kaynak=%s, yenileme %d sn", _DURUM.kaynak, int(aralik))


def cli_yukle(servis: str = "core-worker") -> Durum:
    """Tek seferlik CLI süreçleri (`python -m tp_core.*`) için: Home etkin config'ini bir kez
    yükler (Home'a ulaşılamazsa LKG), arka plan yenileyici AÇMAZ. Servis süreçlerinin `baslat`
    ile kullandığı mekanizmanın aynısı; `servis` LKG dosya adını belirler (konteynerin servis
    süreciyle aynı LKG paylaşılır). env kipinde no-op. Hata fırlatmaz: yüklenemezse durum
    `cfg=None` kalır (tüketiciler — ör. `GitHubForge.from_env` — açık hata verir)."""
    if y.kaynak() != "home":
        return _DURUM
    try:
        ayar_kaynagini_bagla()
        yenile(servis)
    except Exception:
        log.exception("home config: CLI yüklemesi başarısız")
    if _DURUM.cfg is None:
        log.warning("home config: CLI için yüklenemedi (kaynak=%s)", _DURUM.kaynak)
    return _DURUM


def durdur() -> None:
    _DUR.set()
    ip = _IPLIK
    if ip is not None and ip.is_alive() and ip is not threading.current_thread():
        ip.join(timeout=2)


# ------------------------------------------------------------------ çok proje


def _varsayilan_pid() -> str | None:
    return y.ayar(os.environ, y.PROJE_ENV) or None


def _hedef(pid: str | None) -> str | None:
    """Sorgunun projesi: verilen → bağlamdaki → varsayılan (`TP_HOME_PROJECT`)."""
    if pid:
        return pid
    b = varsa()
    if b is not None and b.pid != KURULUM:
        return b.pid
    return _varsayilan_pid()


def _varsayilan_mi(pid: str | None) -> bool:
    v = _varsayilan_pid()
    return pid is None or v is None or pid == v


def _gorunumu_ayarla(pid: str, degerler: Mapping[str, str] | None) -> None:
    if not pid:
        return
    yeni = None if degerler is None else dict(degerler)
    with _KILIT:
        if _GORUNUM.get(pid, ...) != yeni:
            _SAYAC[pid] = _SAYAC.get(pid, 0) + 1
        _GORUNUM[pid] = yeni


def ek_projeler_env() -> list[str]:
    """`TP_HOME_PROJECTS` (virgüllü; Deployment) ∪ `TP_HOME_PROJECT`; geçersiz adlar atlanır."""
    adlar = [p.strip() for p in y.ayar(os.environ, EK_PROJELER_ENV).split(",")]
    v = _varsayilan_pid()
    out = [v] if v else []
    for p in adlar:
        if p and _PID_DOSYA.match(p) and p not in out:
            out.append(p)
    return out


def _kurulu_db() -> list[str]:
    from tp_core.db import get_engine
    from tp_core.proje import kurulu_projeler

    with get_engine().connect() as c:
        return kurulu_projeler(c)


def _ek_pidler() -> list[str]:
    """Varsayılan dışında yenilenecek projeler: env listesi ∪ `tp_proje` aktif ∪ yüklenmiş."""
    adaylar = list(ek_projeler_env())
    try:
        adaylar += (_YAPI.projeler or _kurulu_db)()
    except Exception:
        log.warning("home config: kurulu proje listesi okunamadı; bilinenlerle sürülüyor")
    adaylar += list(_EK)
    v = _varsayilan_pid()
    out: list[str] = []
    for p in adaylar:
        if p and p != v and p not in out and _PID_DOSYA.match(p):
            out.append(p)
    return out


def _ek_lkg_yolu(servis: str, pid: str) -> str | None:
    if not _PID_DOSYA.match(pid):
        return None
    acik = y.ayar(os.environ, y.LKG_ENV)
    if acik:
        kok, uzanti = os.path.splitext(acik)
        return f"{kok}-{pid}{uzanti or '.json'}"
    return os.path.join(VARSAYILAN_LKG_DIZINI, f"lkg-{servis}-{pid}.json")


def _sir_cozucu() -> Callable[[str], str]:
    if _YAPI.sir_cozucu is not None:
        return _YAPI.sir_cozucu
    http = _YAPI.http or y.urllib_http
    return y.SecretManagerCozucu(
        y.MetadataKimligi(http).erisim_tokeni,
        http,
        sir_projesi=y.ayar(os.environ, y.SIR_PROJESI_ENV) or None,
    )


def _ek_yukleyici(pid: str, servis: str) -> y.Yukleyici | None:
    url, audience = y.home_adresi(os.environ)
    if not url:
        return None
    istemci = y.HomeConfigIstemcisi(
        url, pid, _id_token, audience=audience, http=_YAPI.http or y.urllib_http
    )
    return y.Yukleyici(istemci, _ek_lkg_yolu(servis, pid))


def _denetle(eylem: str, ozet: dict[str, Any]) -> None:
    """`_kurulum` zincirine kurulum geneli olay (hata yanıtı/yenilemeyi engellemez)."""
    try:
        if _YAPI.denetim is not None:
            _YAPI.denetim(eylem, ozet)
            return
        from tp_core.audit import append_audit
        from tp_core.db import get_engine

        with get_engine().begin() as c:
            append_audit(
                c, "home-config", eylem, f"proje:{ozet.get('pid')}", ozet, project_id=KURULUM
            )
    except Exception:
        log.warning("home config: denetim kaydı yazılamadı (%s)", eylem, exc_info=True)


def yenile_proje(pid: str, servis: str = "core") -> Durum:
    """Varsayılan dışındaki bir projenin config'ini yeniler (varsayılan için `yenile`). Değerler
    süreç ortamına yazılmaz; `proje.ayar` görünümü ve sırları bellekte güncellenir."""
    if y.kaynak() != "home" or _varsayilan_mi(pid):
        return _DURUM if _varsayilan_mi(pid) else Durum()
    with _KILIT:
        ek = _EK.get(pid)
        if ek is None:
            ek = _EK[pid] = _EkProje(pid, _ek_yukleyici(pid, servis))
    d = ek.durum
    d.son_deneme = time.time()
    if ek.yukleyici is None:
        d.hata = "yapılandırma eksik"
        return d
    sonuc = ek.yukleyici.yukle()
    d.hata, d.kaynak = sonuc.hata, sonuc.kaynak
    if sonuc.kaynak == "reddedildi":
        d.cfg = None
        ek.sir_zamani = None
        _gorunumu_ayarla(pid, None)
        if not ek.reddedildi_bildirildi:
            ek.reddedildi_bildirildi = True
            log.error("home config: Home %s projesini reddetti; özellikler kapalı", pid)
            _denetle(
                "config.proje_reddedildi",
                {"pid": pid, "hata": sonuc.hata, "oneri": "tp_proje.aktif=false"},
            )
        return d
    if sonuc.cfg is None:
        if sonuc.kaynak == "env":  # Home yok, LKG yok: proje yapılandırılmamış (fail-closed)
            d.cfg = None
            _gorunumu_ayarla(pid, None)
        return d
    ek.reddedildi_bildirildi = False
    if sonuc.kaynak == "home":
        d.son_basari = d.son_deneme
    cfg = sonuc.cfg
    taze_sir = ek.sir_zamani is None or time.monotonic() - ek.sir_zamani >= SIR_TTL_S
    if d.cfg is not None and dict(d.cfg.ham) == dict(cfg.ham) and not taze_sir:
        return d
    onceki = dict(_GORUNUM.get(pid) or {})
    gorunum = y.env_gorunumu(
        cfg, _sir_cozucu(), sir_projesi=y.ayar(os.environ, y.SIR_PROJESI_ENV) or None
    )
    degerler = dict(gorunum.degerler)
    for ad in gorunum.cozulemeyen:  # geçici Secret Manager hatası: son çözülen değer kalır
        if ad in onceki and ad not in gorunum.kaldirilan:
            degerler[ad] = onceki[ad]
    d.cfg = cfg
    d.reddedilen = sorted(gorunum.reddedilen)
    d.kaldirilan = sorted(gorunum.kaldirilan)
    d.uygulanan = sorted(degerler)
    ek.sir_zamani = time.monotonic()
    _gorunumu_ayarla(pid, degerler)
    return d


def kesfet(pid: str, servis: str = "core") -> bool:
    """§5.2 (b): kişinin `/v1/projects` listesinde olup kurulumda kayıtlı olmayan pid. Home etkin
    config'i 200 dönerse proje `tp_proje`'ye `kaynak='kesif'` ile kaydedilir (True). Reddedilen
    pid `KESIF_RED_S` boyunca yeniden sorulmaz. Yalnız `CONFIG_SOURCE=home`."""
    if y.kaynak() != "home" or not _PID_DOSYA.match(pid):
        return False
    if _varsayilan_mi(pid):
        return True
    with _KILIT:
        red = _KESIF_RED.get(pid)
        if red is not None and time.monotonic() - red < KESIF_RED_S:
            return False
    d = yenile_proje(pid, servis)
    if d.cfg is None or d.kaynak not in ("home", "lkg"):
        with _KILIT:
            _KESIF_RED[pid] = time.monotonic()
            _EK.pop(pid, None)
            _GORUNUM.pop(pid, None)
        return False
    try:
        if _YAPI.kaydet is not None:
            _YAPI.kaydet(pid, "kesif")
        else:
            _proje_kaydet_db(pid, d.cfg, "kesif")
    except Exception:
        log.warning("home config: keşfedilen proje kaydedilemedi (%s)", pid, exc_info=True)
        return False
    log.info("home config: proje keşfedildi ve kaydedildi: %s", pid)
    return True


def _proje_kaydet_db(pid: str, cfg: y.EtkinConfig | None, kaynak: str) -> None:
    from tp_core.db import get_engine
    from tp_core.proje import proje_kaydet

    proje = cfg.proje if cfg is not None else {}
    kod = str(proje.get("code")) if proje.get("code") else None
    ad = str(proje.get("name")) if proje.get("name") else None
    with get_engine().begin() as c:
        proje_kaydet(c, pid, kod=kod, ad=ad, kaynak=kaynak)  # type: ignore[arg-type]


def projeleri_kaydet() -> None:
    """Açılış: `TP_HOME_PROJECT` + `TP_HOME_PROJECTS` → `tp_proje` (`kaynak='env'`, idempotent)."""
    for pid in ek_projeler_env():
        try:
            if _YAPI.kaydet is not None:
                _YAPI.kaydet(pid, "env")
            else:
                _proje_kaydet_db(pid, etkin(pid), "env")
        except Exception:
            log.warning("home config: proje kaydı yazılamadı (%s)", pid, exc_info=True)


def ayar_cozucu(pid: str) -> Mapping[str, str] | None:
    """`proje.ayar` kaynağı: projenin legacy env görünümü. Varsayılan proje: Home'un sır olmayan
    değerleri (sırlar ve Home'da olmayanlar süreç ortamından). Ek proje: değerler + çözülmüş
    sırlar; hiç yüklenmemişse bir kez eşzamanlı yüklenir. None = reddedildi / yapılandırılmamış."""
    if y.kaynak() != "home":
        return None
    if not _varsayilan_mi(pid) and pid not in _EK and _PID_DOSYA.match(pid):
        try:
            yenile_proje(pid)
        except Exception:
            log.exception("home config: proje ilk yüklemesi başarısız (%s)", pid)
    return _GORUNUM.get(pid)


def ayar_surumu(pid: str) -> str:
    """`proje.ayar.surum`: etag + yerel değişim sayacı (sır döndürmesi de önbellek kırar)."""
    cfg = etkin(pid)
    if y.kaynak() != "home":
        return "env"
    durum_adi = _DURUM.kaynak if _varsayilan_mi(pid) else _ek_durum(pid).kaynak
    taban = (cfg.etag or "etagsiz") if cfg is not None else durum_adi
    return f"{taban}#{_SAYAC.get(pid, 0)}"


def ayar_kaynagini_bagla() -> None:
    """`proje.ayar`'ı Home etkin config'ine bağlar (yalnız `CONFIG_SOURCE=home`)."""
    if y.kaynak() != "home":
        return
    from tp_core.proje import ayar as proje_ayar

    proje_ayar.kaynak_bagla(ayar_cozucu, ayar_surumu)
    _BAGLI[0] = True


def _ek_durum(pid: str) -> Durum:
    ek = _EK.get(pid)
    return ek.durum if ek is not None else Durum(kaynak="yok")


# ------------------------------------------------------------------ sorgular


def etkin(pid: str | None = None) -> y.EtkinConfig | None:
    """Projenin Home'dan (ya da LKG'den) gelen config'i; env kipinde ya da yüklenemediyse `None`.
    `pid` yoksa bağlamdaki, o da yoksa varsayılan proje."""
    if y.kaynak() != "home":
        return None
    hedef = _hedef(pid)
    if _varsayilan_mi(hedef):
        return _DURUM.cfg
    assert hedef is not None
    if hedef not in _EK:
        ayar_cozucu(hedef)  # ilk erişimde bir kez yükle
    ek = _EK.get(hedef)
    return None if ek is None else ek.durum.cfg


def ozellikler(pid: str | None = None) -> dict[str, bool] | None:
    """Proje özellikleri; `None` = Home config yok → bugünkü davranış (hepsi açık). Home
    reddettiyse (N4) hepsi kapalı. Varsayılan dışındaki proje yüklenemediyse de hepsi kapalı
    (fail-closed: yeni proje Bayi Portalı'nın env değerlerine düşmez)."""
    if y.kaynak() != "home":
        return None
    hedef = _hedef(pid)
    if _varsayilan_mi(hedef):
        if _reddedildi_mi():
            return {o: False for o in y.OZELLIKLER}
        cfg = _DURUM.cfg
        return None if cfg is None else cfg.ozellikler
    cfg = etkin(hedef)
    return {o: False for o in y.OZELLIKLER} if cfg is None else cfg.ozellikler


def ozellik_acik(ad: str, pid: str | None = None) -> bool:
    o = ozellikler(pid)
    return True if o is None else bool(o.get(ad, False))


def baglanti_kipi(tur: str, pid: str | None = None) -> str:
    cfg = etkin(pid)
    return "token" if cfg is None else cfg.baglanti_kipi(tur)


def baglanti_public(tur: str, pid: str | None = None) -> Mapping[str, Any]:
    cfg = etkin(pid)
    return {} if cfg is None else cfg.baglanti_public(tur)


def org_proje(pid: str | None = None) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    cfg = etkin(pid)
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
        "kaldirilan": list(d.kaldirilan),
        "geri_cekilen": list(d.geri_cekilen),
        "projeler": {
            pid: {
                "kaynak": ek.durum.kaynak,
                "etag": ek.durum.cfg.etag if ek.durum.cfg else None,
                "son_basari": ek.durum.son_basari,
                "hata": ek.durum.hata,
                "kaldirilan": list(ek.durum.kaldirilan),
            }
            for pid, ek in sorted(_EK.items())
        },
    }
