"""Entegrasyon istemcilerinin proje başına config görünümü (TP-COK-PROJE-PLANI §3.3, §4).

Adaptör fabrikaları (`get_forge(env)`, `LocalForge.from_env(env)`, `GitHubForge.from_env(env)`,
`GitHubCiOkuyucu.kur(env)`) tarihsel olarak bir ad → değer haritası alır. `ProjeOrtami(pid)` bu
haritanın proje başına sürümüdür; fabrikalar `env` verilmezse `os.environ` yerine bunu kullanır:

- **Proje anahtarları** (`PROJE_ANAHTARLARI` T/A/P + `EK_PROJE_ANAHTARLARI`): `proje.ayar(ad,
  pid=pid)` — proje etkin config'i; varsayılan projede `os.environ`'a düşer (geriye uyum), diğer
  projelerde **düşmez** (Bayi Portalı'nın değeri başka projeye sızmaz; tanımsız = yok).
- **Forge yolları** (`TP_FORGE_PATH`, `TP_FORGE_PRS_PATH`, `TP_FORGE_MIRROR_PATH`):
  `forge_yollari` (varsayılan projede eski yollar).
- **Diğer adlar** (D: kurulum — zaman aşımları, artefakt yolu, GH_APP_ID …): `os.environ`.

**Platform depoları** (`ProjeOrtami(pid, platform)`; platform-depo ANALIZ §2.3–2.4):
android/ios/windows için `GITHUB_REPO_<P>` dolu ve varsayılan depodan (`GITHUB_REPO`) farklıysa
o platformun görünümü ayrı deponun görünümüdür (platform kaplaması `_depo_kaplamasi`); değilse
görünüm bugünküyle birebir. Depo kimliği `depo_anahtari(platform)`: `''` = varsayılan depo, aksi
hâlde küçük harfli `sahip/ad`. Aynı `GITHUB_REPO_<X>` = aynı depo (görünüm platformdan değil
depodan türetilir; istemci önbelleği türü `forge@sahip/ad`). `TP_FORGE=local` kipinde platform
depoları yok sayılır (uyarı).

Bağlantı kipi ve Home erişim token'ı da proje başınadır (§4.2; Config R1 `home_config.baglanti`):
`baglanti_kipi(tur, pid)`, `token_al(tur, pid)`, `gecersiz_kil(tur, pid)` ve istemci kimlik
sarmalayıcıları `ProjeJiraAuth` / `ProjeGitHubAuth` (`baglanti.token_al(tur, pid)`,
`durum.etkin(pid)`).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Generator, Iterator, Mapping
from typing import TYPE_CHECKING, Any

import httpx

from tp_core.home_config import baglanti
from tp_core.integrations import forge_yollari
from tp_core.proje import ayar as _ayar
from tp_core.proje.ayar import PROJE_ANAHTARLARI
from tp_core.proje.baglam import varsayilan_pid

if TYPE_CHECKING:
    from tp_core.home_config.baglanti import ErisimTokeni

log = logging.getLogger(__name__)

PLATFORMLAR = ("android", "ios", "windows")
APP_ALANLARI = {
    "app_id": "TP_APP_ID",
    "path": "TP_APP_PATH",
    "activity": "TP_APP_ACTIVITY",
    "args": "TP_APP_ARGS",
    "workdir": "TP_APP_WORKDIR",
}

# Şerit 3'ün eklediği T (proje) adları: toolchain `proje` bloğunun kaynakları (§4.4) ve forge
# kipinin proje ayarları. Şerit 0/2 `PROJE_ANAHTARLARI`'na katılmalı (statik test için).
EK_PROJE_ANAHTARLARI: frozenset[str] = frozenset(
    {
        "BASE_URL",
        "DEMO_API_URL",
        "TP_PROBE_USER",
        "TP_RUN_DEALERS",
        "TP_E2E_ROOT",
        # Java test kökleri ve uygulama yolları (Home `repo.e2e_app_root`, `repo.e2e_java_root`,
        # `repo.app_paths`; toolchain bloğu `e2e_app_root`, `e2e_java_root`, `app_paths`).
        "TP_E2E_APP_ROOT",
        "TP_E2E_JAVA_ROOT",
        "TP_APP_PATHS",
        *(f"{a}_{p.upper()}" for a in APP_ALANLARI.values() for p in PLATFORMLAR),
    }
)

# Platform deposu kaplaması (§2.4): taban ad → (platform son ekli ad, devralır mı). Devralan
# alanlar (dal, Java test kökü) platform değeri yoksa tabanın değerini alır; depo kimliğine bağlı
# alanlar (uygulama kökü, uygulama yolları, zorunlu check'ler) DEVRALMAZ: taban değerleri web
# deposunundur (ör. `test-local,ast-guard,semgrep` mobil depoda hiç oluşmaz → merge kilidi).
DEPO_ALANLARI: dict[str, bool] = {
    "TP_FORGE_CHECK_REF": True,
    "TP_E2E_APP_ROOT": True,
    "TP_FORGE_APP_ROOT": False,
    "TP_APP_PATHS": False,
    "TP_REQUIRED_CHECKS": False,
    # 014 test dilleri: uygulama dil kökleri, taban + `_<P>` (Home `tp.repos.<p>.test_root_<dil>`).
    "TP_E2E_APP_PYTHON_ROOT": True,
    "TP_E2E_APP_CSHARP_ROOT": True,
    "TP_ANDROID_KOTLIN_ROOT": True,
    "TP_IOS_SWIFT_ROOT": True,
}
DEPO_ENV = "GITHUB_REPO"
# Platform deposu kaplamasının elle verdiği adlar (görünümde her zaman tanımlı).
_KAPLAMA_ADLARI: frozenset[str] = frozenset(
    {
        DEPO_ENV,
        *DEPO_ALANLARI,
        "TP_PLATFORMS",
        "TP_WEB_DILLERI",
        "TP_FORGE_REMOTE_URL",
        "TP_FORGE_REPO_NAME",
        "TP_FORGE_MIRROR_PATH",
        "TP_FORGE_PATH",
    }
)
_DEPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
VARSAYILAN_FORGE_WEB_URL = "https://github.com"


FORGE_YOLLARI: dict[str, Callable[[str], Any]] = {
    "TP_FORGE_PATH": forge_yollari.depo_yolu,
    "TP_FORGE_PRS_PATH": forge_yollari.pr_dosyasi,
    "TP_FORGE_MIRROR_PATH": forge_yollari.ayna_yolu,
}


def proje_anahtari_mi(ad: str) -> bool:
    return ad in PROJE_ANAHTARLARI or ad in EK_PROJE_ANAHTARLARI


def pid_coz(pid: str | None = None) -> str:
    """`pid` verilmezse bağlamdaki proje (bağlam ve config kaynağı yoksa varsayılan)."""
    return _ayar._pid(pid)


def _depo_normal(depo: str) -> str:
    """`sahip/ad` → küçük harfli depo kimliği (biçim dışıysa `GecersizPlatformDeposu`)."""
    from tp_core.integrations.forge import GecersizPlatformDeposu

    d = depo.strip()
    if not _DEPO_RE.fullmatch(d) or d.split("/", 1)[1] in (".", ".."):
        raise GecersizPlatformDeposu(f"platform deposu sahip/ad biçiminde olmalı: {depo!r}")
    return d.lower()


_LOCAL_UYARILDI: set[tuple[str, str]] = set()


def _forge_turu(pid: str) -> str:
    return (_ayar.ayar("TP_FORGE", pid=pid) or "local").strip().lower()


def _platform_ham(platform: str, pid: str) -> str:
    """`GITHUB_REPO_<P>` (yalnız ayrı depo iken anlamlı; boş = varsayılan depo)."""
    return (_ayar.ayar(f"{DEPO_ENV}_{platform.upper()}", pid=pid) or "").strip()


def depo_anahtari(platform: str | None, pid: str | None = None) -> str:
    """Platformun depo kimliği: `''` = varsayılan depo (web, ayrı depo seçilmemiş platform,
    `TP_FORGE=local`), aksi hâlde küçük harfli `sahip/ad` (`GITHUB_REPO_<P>`). PR/script kaydına
    (`depo`) ve istemci önbellek anahtarına bu yazılır."""
    p = (platform or "").strip().lower()
    if p not in PLATFORMLAR:
        return ""
    proje = pid_coz(pid)
    ham = _platform_ham(p, proje)
    if not ham:
        return ""
    if _forge_turu(proje) != "github":
        if (proje, p) not in _LOCAL_UYARILDI:
            _LOCAL_UYARILDI.add((proje, p))
            log.warning(
                "%s_%s yok sayıldı (%s): TP_FORGE=local kipinde platform depoları kullanılmaz",
                DEPO_ENV,
                p.upper(),
                proje,
            )
        return ""
    anahtar = _depo_normal(ham)
    taban = (_ayar.ayar(DEPO_ENV, pid=proje) or "").strip().lower()
    return "" if anahtar == taban else anahtar


def proje_depolari(
    pid: str | None = None, *, hatali_atla: bool = False
) -> dict[str, tuple[str, ...]]:
    """Projenin depoları → o depoya düşen uygulama platformları (`''` = varsayılan depo; web her
    zaman varsayılan depodadır ve listede yer almaz). Sıra `PLATFORMLAR` sırasıdır.

    `hatali_atla`: biçimi bozuk `GITHUB_REPO_<P>` olan platform listeye girmez (uyarı); yoksa
    `GecersizPlatformDeposu` yükselir. Görünümler atlar: bir platformun bozuk deposu web ya da
    başka platformun forge'unu düşürmez (o platformun kendi görünümü hatayı verir)."""
    from tp_core.integrations.forge import GecersizPlatformDeposu

    proje = pid_coz(pid)
    out: dict[str, list[str]] = {"": []}
    for p in PLATFORMLAR:
        try:
            d = depo_anahtari(p, proje)
        except GecersizPlatformDeposu as exc:
            if not hatali_atla:
                raise
            log.warning("platform deposu yok sayıldı (%s, %s): %s", proje, p, exc)
            continue
        out.setdefault(d, []).append(p)
    return {d: tuple(ps) for d, ps in out.items()}


def depoya_dusen_platformlar(depo: str, pid: str | None = None) -> tuple[str, ...]:
    """Depoya düşen uygulama platformları (depo kimliği `depo_anahtari` biçiminde)."""
    return proje_depolari(pid).get((depo or "").strip().lower(), ())


def platform_deposu_adi(depo: str, pid: str | None = None) -> str:
    """Gösterim adı (`depo_adi`): `''` → varsayılan depo `GITHUB_REPO` (yoksa ''), aksi hâlde
    config'teki yazımıyla `GITHUB_REPO_<P>` (config'te artık yoksa kayıtlı kimlik)."""
    proje = pid_coz(pid)
    d = (depo or "").strip().lower()
    if not d:
        return (_ayar.ayar(DEPO_ENV, pid=proje) or "").strip()
    for p in PLATFORMLAR:
        ham = _platform_ham(p, proje)
        if ham and ham.lower() == d:
            return ham
    return d


def _secili_platformlar(deger: str | None, haric: set[str]) -> str:
    """`TP_PLATFORMS` değerinden ayrı depoya taşınan platformları çıkarır (biçim korunur)."""
    if not haric:
        return deger or ""
    parcalar = [x.strip() for x in (deger or "").split(",") if x.strip()]
    return ",".join(x for x in parcalar if x.lower() not in haric)


class ProjeOrtami(Mapping[str, str]):
    """Bir projenin legacy ad → değer görünümü (salt okunur).

    `platform` verilirse o platformun deposunun görünümü (`depo_anahtari`); `depo` verilirse
    kayıtlı depo kimliğinin görünümü (config'te artık olmasa da: `platform` o zaman depoya düşen
    platform ipucudur, ör. açık PR'ın script platformu). İkisi de yoksa varsayılan depo."""

    def __init__(
        self, pid: str | None = None, platform: str | None = None, *, depo: str | None = None
    ) -> None:
        self.pid = pid_coz(pid)
        self.varsayilan = self.pid == varsayilan_pid()
        self.platform = (platform or "").strip().lower() or None
        if depo is None:
            self.depo = depo_anahtari(self.platform, self.pid)
        else:
            d = depo.strip()
            self.depo = _depo_normal(d) if d else ""
            taban = (_ayar.ayar(DEPO_ENV, pid=self.pid) or "").strip().lower()
            if self.depo == taban:
                self.depo = ""
        self._kaplama: dict[str, str] | None = None

    @property
    def ayri_depo(self) -> bool:
        """Görünüm varsayılan depodan ayrı bir platform deposunun mu?"""
        return bool(self.depo)

    def _depo_kaplamasi(self) -> dict[str, str]:
        """§2.4 platform kaplaması (ayrı depoda) ya da varsayılan depoda `TP_PLATFORMS` süzgeci."""
        if self._kaplama is not None:
            return self._kaplama
        pid = self.pid
        # Kendi deposu __init__'te doğrulandı; başka platformun bozuk deposu bu görünümü düşürmez.
        depolar = proje_depolari(pid, hatali_atla=True)
        k: dict[str, str] = {}
        if not self.depo:
            # Ayrı depoya taşınan platformların check'i web PR'ında beklenmez.
            tasinan = {p for d, ps in depolar.items() if d for p in ps}
            if tasinan:
                k["TP_PLATFORMS"] = _secili_platformlar(
                    _ayar.ayar("TP_PLATFORMS", pid=pid), tasinan
                )
            self._kaplama = k
            return k
        platformlar = depolar.get(self.depo) or ((self.platform,) if self.platform else ())
        platformlar = tuple(p for p in platformlar if p in PLATFORMLAR)
        # İstenen platform önce: aynı depoyu paylaşan platformların değeri farklıysa onunki.
        sira = sorted(platformlar, key=lambda p: p != self.platform)

        def platform_degeri(ad: str) -> str | None:
            for p in sira:
                d = (_ayar.ayar(f"{ad}_{p.upper()}", pid=pid) or "").strip()
                if d:
                    return d
            return None

        k[DEPO_ENV] = platform_deposu_adi(self.depo, pid)
        for ad, devralir in DEPO_ALANLARI.items():
            if ad == "TP_REQUIRED_CHECKS":
                continue
            deger = platform_degeri(ad)
            if deger is None:
                deger = (_ayar.ayar(ad, pid=pid) or "") if devralir else ""
            k[ad] = deger
        k["TP_REQUIRED_CHECKS"] = self._zorunlu_checkler(sira)
        k["TP_PLATFORMS"] = ",".join(platformlar)
        k["TP_WEB_DILLERI"] = ""  # web bu depoda değil
        k["TP_FORGE_REPO_NAME"] = k[DEPO_ENV].rsplit("/", 1)[-1]
        k["TP_FORGE_REMOTE_URL"] = self._ayna_adresi(k[DEPO_ENV])
        k["TP_FORGE_MIRROR_PATH"] = str(forge_yollari.ayna_yolu(pid, self.depo))
        k["TP_FORGE_PATH"] = str(forge_yollari.depo_yolu(pid, self.depo))
        self._kaplama = k
        return k

    def _zorunlu_checkler(self, platformlar: list[str]) -> str:
        """Ayrı deponun zorunlu check'leri: platformların `TP_REQUIRED_CHECKS_<P>` birleşimi;
        hiçbiri girilmemişse depoya düşen platformların iş akışı check'leri (`mobil-android`,
        `mobil-ios`, `masaustu-windows`). Taban liste devralınmaz (§2.2 merge kilidi)."""
        from tp_core.integrations.forge import GITHUB_PLATFORM_CHECKS

        adlar: list[str] = []
        for p in platformlar:
            for parca in (_ayar.ayar(f"TP_REQUIRED_CHECKS_{p.upper()}", pid=self.pid) or "").split(
                ","
            ):
                if (ad := parca.strip()) and ad not in adlar:
                    adlar.append(ad)
        if not adlar:
            # Ayrı depoda TP'nin açtığı her PR test kökünü değiştirir: platform iş akışı (ios'un
            # `paths` süzgeci dahil) tetiklenir. Boş liste ise web varsayılanına düşerdi.
            adlar = [GITHUB_PLATFORM_CHECKS[p] for p in platformlar]
        return ",".join(adlar)

    def _ayna_adresi(self, depo: str) -> str:
        """Ayrı deponun ayna adresi: taban ayna kapalıysa (`TP_FORGE_REMOTE_URL` boş) '';
        değilse `<TP_FORGE_WEB_URL>/<sahip/ad>.git` (kullanıcı girdisi değil, türetilir: ayna
        token'ı yalnız izinli GitHub host'una gider — `toolchain_blogu.github_adresi_mi`)."""
        if not (_ayar.ayar("TP_FORGE_REMOTE_URL", pid=self.pid) or "").strip():
            return ""
        web = (_ayar.ayar("TP_FORGE_WEB_URL", pid=self.pid) or "").strip().rstrip("/")
        return f"{web or VARSAYILAN_FORGE_WEB_URL}/{depo}.git"

    def get(self, ad: str, default: Any = None) -> Any:  # type: ignore[override]
        try:
            return self[ad]
        except KeyError:
            return default

    def __getitem__(self, ad: str) -> str:
        if ad in _KAPLAMA_ADLARI and (self.depo or ad == "TP_PLATFORMS"):
            kaplama = self._depo_kaplamasi()
            if ad in kaplama:
                return kaplama[ad]
        if ad in FORGE_YOLLARI:
            if self.varsayilan and ad not in os.environ:
                raise KeyError(ad)  # eski davranış: adaptör kendi varsayılanını kullanır
            return str(FORGE_YOLLARI[ad](self.pid))
        if proje_anahtari_mi(ad):
            deger = _ayar.ayar(ad, pid=self.pid)
            if deger is None:
                raise KeyError(ad)
            return deger
        return os.environ[ad]

    def _adlar(self) -> set[str]:
        adlar = {a for a in os.environ if not proje_anahtari_mi(a)}
        adlar |= {a for a in PROJE_ANAHTARLARI | EK_PROJE_ANAHTARLARI if a in self}
        adlar |= {a for a in FORGE_YOLLARI if a in self}
        adlar |= set(self._depo_kaplamasi())
        return adlar

    def __contains__(self, ad: object) -> bool:
        if not isinstance(ad, str):
            return False
        try:
            self[ad]
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._adlar()))

    def __len__(self) -> int:
        return len(self._adlar())

    def __repr__(self) -> str:  # değerler (sırlar) loglara düşmesin
        if self.depo:
            return f"ProjeOrtami(pid={self.pid!r}, depo={self.depo!r})"
        return f"ProjeOrtami(pid={self.pid!r})"


# ------------------------------------------------------------ bağlantı kipi ve Home token'ı


def _cfg(pid: str) -> Any:
    """Projenin Home etkin config'i (yoksa None)."""
    from tp_core.home_config import durum

    return durum.etkin(pid=pid)


def baglanti_kipi(tur: str, pid: str | None = None) -> str:
    """`token` | `oauth` | `app` (Home etkin config'i yoksa `token`)."""
    cfg = _cfg(pid_coz(pid))
    return "token" if cfg is None else str(cfg.baglanti_kipi(tur))


def baglanti_public(tur: str, pid: str | None = None) -> Mapping[str, Any]:
    cfg = _cfg(pid_coz(pid))
    return {} if cfg is None else cfg.baglanti_public(tur)


def token_al(tur: str, pid: str | None = None) -> ErisimTokeni:
    """Home'dan projenin bağlantı token'ı (`POST /v1/connections/access-token {project: pid}`)."""
    return baglanti.token_al(tur, pid=pid_coz(pid))


def gecersiz_kil(tur: str, pid: str | None = None) -> None:
    baglanti.gecersiz_kil(tur, pid=pid_coz(pid))


class ProjeJiraAuth(baglanti.HomeJiraAuth):
    """Jira OAuth (3LO) Bearer, projenin bağlantısından; 401'de bir kez yeniler."""

    def __init__(self, pid: str) -> None:
        super().__init__(lambda: token_al("jira", pid))
        self.pid = pid

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._saglayici().access_token}"
        yanit = yield request
        if yanit.status_code == 401:
            gecersiz_kil("jira", self.pid)
            request.headers["Authorization"] = f"Bearer {self._saglayici().access_token}"
            yield request


class ProjeGitHubAuth(baglanti.HomeGitHubAuth):
    """`GitHubAuth` protokolü: projenin GitHub App kurulum token'ı Home'dan."""

    def __init__(self, pid: str) -> None:
        super().__init__(lambda: token_al("github", pid))
        self.pid = pid

    def invalidate(self) -> None:
        gecersiz_kil("github", self.pid)
