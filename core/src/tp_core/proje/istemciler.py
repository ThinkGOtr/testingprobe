"""Proje başına entegrasyon istemcileri (TP-COK-PROJE-PLANI §4.1).

Fabrikalar (`get_jira`, `get_xray_client`, `get_forge`, `GitHubCi`) bağlamdaki projenin config'iyle
kurulur (`JiraSettings.proje_icin`, `integrations.proje_ortami.ProjeOrtami`); önbellek anahtarı
`(pid, ayar.surum(pid))` (config etag'i değişince yeniden kurulur). İmzalar donuk (Şerit 0).

Platform depoları (platform-depo ANALIZ §3.2.1): `forge(platform)` / `ci(platform)` platformun
deposunun istemcisidir; önbellek türü depo kimliğini taşır (`forge@sahip/ad`), böylece aynı depoyu
paylaşan platformlar tek istemciyi paylaşır ve platformlar birbirinin deposuna yazmaz. Kayıtlı
depo kimliğiyle (`script.depo`, `pull_request.depo`) `forge_depo(depo)` / `ci_depo(depo)`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from tp_core.proje import ayar as _ayar

if TYPE_CHECKING:
    from tp_core.features.ci.clients import GitHubCi
    from tp_core.integrations.jira import RestJira
    from tp_core.integrations.xray import XrayClient
    from tp_core.ports import ForgePort


_KILIT = threading.Lock()
_ONBELLEK: dict[tuple[str, str, str], Any] = {}


def _onbellekli[T](tur: str, kur: Callable[[], T]) -> T:
    pid = _ayar._pid(None)
    anahtar = (pid, _ayar.surum(pid), tur)
    with _KILIT:
        if anahtar in _ONBELLEK:
            return _ONBELLEK[anahtar]  # type: ignore[no-any-return]
    nesne = kur()
    with _KILIT:
        # eski sürümlerin kayıtlarını at (aynı pid + tür)
        for k in [k for k in _ONBELLEK if k[0] == pid and k[2] == tur and k != anahtar]:
            del _ONBELLEK[k]
        return _ONBELLEK.setdefault(anahtar, nesne)  # type: ignore[no-any-return]


def jira() -> RestJira:
    """Bağlamdaki projenin Jira istemcisi (projenin Jira ayarları ve bağlantı kipi; OAuth'ta
    projenin Home erişim token'ı)."""
    from tp_core.integrations.jira import get_jira

    # Fabrikalar argümansız bağlamdaki projeyi kullanır (`get_jira_settings()`, `ProjeOrtami()`);
    # kurulum `_onbellekli` içinde aynı bağlamda koşar.
    return _onbellekli("jira", get_jira)


def xray() -> XrayClient | None:
    """`TP_TEST_MGMT=xray` değilse None."""
    if (_ayar.ayar("TP_TEST_MGMT") or "jira").strip().lower() != "xray":
        return None
    from tp_core.integrations.xray import get_xray_client

    return _onbellekli("xray", get_xray_client)


def _tur(ad: str, depo: str) -> str:
    """Önbellek türü: varsayılan depoda bugünkü ad (`forge`), ayrı depoda `forge@sahip/ad`."""
    return f"{ad}@{depo}" if depo else ad


def _depo_forge(depo: str, platform: str | None) -> ForgePort:
    from tp_core.integrations.forge import get_forge

    if not depo:
        return _onbellekli("forge", get_forge)
    from tp_core.integrations.proje_ortami import ProjeOrtami

    return _onbellekli(
        _tur("forge", depo), lambda: get_forge(ProjeOrtami(platform=platform, depo=depo))
    )


def forge(platform: str | None = None) -> ForgePort:
    """`TP_FORGE`'a göre LocalForge | GitHubForge (demo sarmalayıcıları çağıranda kalır): proje
    ayarları + proje forge yolları (`forge_yollari`) + projenin GitHub bağlantısı. `platform`
    verilirse o platformun deposu (`proje_ortami.depo_anahtari`; ayrı depo yoksa varsayılan)."""
    from tp_core.integrations.proje_ortami import depo_anahtari

    return _depo_forge(depo_anahtari(platform), platform)


def forge_depo(depo: str, platform: str | None = None) -> ForgePort:
    """Kayıtlı depo kimliğinin (`script.depo` / `pull_request.depo`; `''` = varsayılan depo)
    forge'u. Config'te artık o depo yoksa forge kayıttaki adla kurulur (açık PR doğru depodan
    senkronlanır); `platform` o durumda zorunlu check'lerin platform ipucudur."""
    from tp_core.integrations.proje_ortami import ProjeOrtami

    d = ProjeOrtami(platform=platform, depo=depo).depo  # normalleştirir; taban adı = ''
    return _depo_forge(d, platform)


def _ci(depo: str, platform: str | None) -> GitHubCi | None:
    if (_ayar.ayar("TP_FORGE") or "local").strip().lower() != "github":
        return None
    from tp_core.features.ci.clients import GitHubCi

    return _onbellekli(_tur("ci", depo), lambda: GitHubCi(_depo_forge(depo, platform)))


def ci(platform: str | None = None) -> GitHubCi | None:
    """GitHub Actions istemcisi (`platform` verilirse o platformun deposunun); `TP_FORGE=github`
    değilse None."""
    from tp_core.integrations.proje_ortami import depo_anahtari

    return _ci(depo_anahtari(platform), platform)


def ci_depo(depo: str, platform: str | None = None) -> GitHubCi | None:
    """Kayıtlı depo kimliğinin (`run.ortam.depo`, `pull_request.depo`) Actions istemcisi."""
    from tp_core.integrations.proje_ortami import ProjeOrtami

    return _ci(ProjeOrtami(platform=platform, depo=depo).depo, platform)


def toolchain_proje_blogu(platform: str | None = None) -> dict[str, Any]:
    """Toolchain isteklerinin `proje` bloğu (§4.4; `integrations.toolchain_blogu`). Varsayılan
    projede yalnız `pid` (+ Home config'inin env'den farklı verdiği alanlar); diğer projelerde
    depo/ayna yolu, uzak depo ve uygulama bloğu her zaman. `platform` ayrı depodaysa o deponun
    ayna yolu, türetilmiş uzak adresi, Java test kökü ve uygulama yolları her zaman gider."""
    from tp_core.integrations.toolchain_blogu import proje_blogu

    return proje_blogu(platform=platform)


def sifirla(pid: str | None = None) -> None:
    """Önbelleği temizler (`pid` verilirse yalnız o proje): test ve config değişimi."""
    with _KILIT:
        if pid is None:
            _ONBELLEK.clear()
        else:
            for k in [k for k in _ONBELLEK if k[0] == pid]:
                del _ONBELLEK[k]
