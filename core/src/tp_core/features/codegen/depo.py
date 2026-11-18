"""Platform başına depo yardımcıları (platform-depo ANALIZ §3.2, Şerit T2).

T1 sözleşmesinin (`proje_ortami.ProjeOrtami(pid, platform, depo=)`, `proje_ortami.depo_anahtari`,
`proje_ortami.proje_depolari`, `istemciler.forge(platform)`, `istemciler.forge_depo(depo,
platform)`, `istemciler.ci(platform)`, `istemciler.ci_depo(depo, platform)`) üstünde
ince katman: codegen / ci / repair / bugs / hata_kosusu aynı kuralı buradan okur.

Kurallar:

- **Depo kimliği** (`depo`): `''` = projenin varsayılan deposu (web ve depo girilmemiş platformlar);
  ayrı platform deposunda `sahip/ad` (küçük harf). Script'e (`script.depo`), PR kaydına
  (`pull_request.depo`) ve koşuya (`run.ortam.depo`) yazılır; PR numarası yalnız (depo, numara)
  ile tekildir.
- **Kayıtlı depo yetkilidir:** dala commit edilmiş / PR'ı açılmış script'in işlemleri (merge, dal
  güncelleme, senkron, CI) `script.depo`'nun forge'uyla yapılır; config sonradan değişse de.
  Henüz commit'i olmayan işler (dil algılama, üretim başlangıcı) platformun güncel deposunu
  kullanır.
- **Geriye uyum:** hiçbir platform deposu girilmemişse her şey bugünküyle aynıdır (depo `''`,
  dal `main`, forge önbelleği değişmez).
- Uygulama kodu okuma (gereksinim tutarlılığı, asistan) her zaman varsayılan depodadır (ANALIZ §4).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from tp_core.features.codegen import platform as platformlar
from tp_core.proje import ayar as _ayar

if TYPE_CHECKING:
    from tp_core.ports import ForgePort

VARSAYILAN = ""
ANA_DAL = "main"
# GitHub `sahip/ad` (küçük harf; depo_anahtari biçimi). API `?depo=` girdisi bununla doğrulanır.
DEPO_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,99})/[a-z0-9._-]{1,100}")


def uygulama_platformu(platform: str | None) -> str | None:
    """Ayrı depo alabilen platform (android | ios | windows) ya da None (web / bilinmeyen)."""
    return platform if platform in platformlar.UYGULAMA_PLATFORMLARI else None


def depo_anahtari(platform: str | None) -> str:
    """Platformun GÜNCEL deposu (bağlamdaki proje): ayrı depo tanımlıysa `sahip/ad`, değilse `''`.
    Web her zaman varsayılan depodadır."""
    p = uygulama_platformu(platform)
    if p is None:
        return VARSAYILAN
    from tp_core.integrations import proje_ortami

    return normalize(proje_ortami.depo_anahtari(p))


def normalize(depo: str | None) -> str:
    """Kayıtlı/istek deposunu karşılaştırılabilir biçime getirir (`''` | küçük harf `sahip/ad`)."""
    return (depo or "").strip().strip("/").lower()


def gecerli_mi(depo: str) -> bool:
    """API girdisi: `''` (varsayılan) ya da `sahip/ad`."""
    return depo == VARSAYILAN or DEPO_RE.fullmatch(depo) is not None


def gorunum(platform: str | None = None, depo: str | None = None) -> Mapping[str, str]:
    """Platformun config görünümü (`ProjeOrtami(pid, platform)`; ayrı depoda platform kaplaması:
    `GITHUB_REPO`, `TP_FORGE_CHECK_REF`, `TP_REQUIRED_CHECKS`, `TP_PLATFORMS` … o deponun).
    `depo` verilirse KAYITLI deponun görünümü (config sonradan değişse de; `''` = varsayılan)."""
    from tp_core.integrations.proje_ortami import ProjeOrtami

    if depo is None:
        return ProjeOrtami(None, uygulama_platformu(platform))
    return ProjeOrtami(None, uygulama_platformu(platform), depo=normalize(depo))


def platform_forge(platform: str | None) -> ForgePort:
    """Platformun güncel deposunun forge'u (proje + depo önbellekli)."""
    from tp_core.proje import istemciler

    return istemciler.forge(uygulama_platformu(platform))


def depo_forge(depo: str | None, platform: str | None = None) -> ForgePort:
    """Kayıtlı deponun forge'u: `''` → varsayılan depo; `sahip/ad` → o depo (config'te artık
    platformu yoksa da kayıttaki adla kurulur; token erişemezse forge hatası çağırana gider).
    `platform`: depoya düşen platform ipucu (zorunlu check'ler)."""
    from tp_core.proje import istemciler

    d = normalize(depo)
    return istemciler.forge_depo(d, uygulama_platformu(platform)) if d else istemciler.forge()


def depo_ci(depo: str | None, platform: str | None = None) -> object | None:
    """Kayıtlı deponun GitHub Actions istemcisi (`TP_FORGE=github` değilse None)."""
    from tp_core.proje import istemciler

    d = normalize(depo)
    return istemciler.ci_depo(d, uygulama_platformu(platform)) if d else istemciler.ci()


def ana_dal(platform: str | None, depo: str | None = None) -> str:
    """Üretim tabanı / PR hedefi dalı. Varsayılan depoda `main` (bugünkü davranış: codegen dalları
    ve PR'lar `main`'e); ayrı depoda o deponun `TP_FORGE_CHECK_REF_<P>`'si (yoksa `main`).
    `depo` verilirse KAYITLI deponun dalı (varsayılan depoysa `main`)."""
    if depo is not None:
        if not normalize(depo):
            return ANA_DAL
        return _ref(gorunum(platform, depo).get("TP_FORGE_CHECK_REF"))
    if not depo_anahtari(platform):
        return ANA_DAL
    return _ref(gorunum(platform).get("TP_FORGE_CHECK_REF"))


def kontrol_ref(platform: str | None = None) -> str:
    """Salt okuma işlerinin dalı (dil algılama, hata koşusu head'i; ANALIZ §1.3 "sabit main"):
    platform görünümünün `TP_FORGE_CHECK_REF`'i (varsayılan `main`)."""
    return _ref(gorunum(platform).get("TP_FORGE_CHECK_REF"))


def _ref(deger: str | None) -> str:
    d = (deger or "").strip()
    return d or ANA_DAL


def depo_adi(depo: str | None) -> str:
    """Gösterim adı (`sahip/ad`): ayrı depoda kendisi, varsayılanda projenin `GITHUB_REPO`'su
    (LocalForge'da boş olabilir)."""
    from tp_core.integrations.proje_ortami import platform_deposu_adi

    return platform_deposu_adi(normalize(depo))


def etkin_uygulama_platformlari() -> tuple[str, ...]:
    """Projenin HAM `TP_PLATFORMS`'undaki uygulama platformları (zorunlu check süzgeci yok; ios
    dahil). Varsayılan depo görünümü ayrı depolara taşınan platformları çıkardığı için ham proje
    ayarı okunur."""
    out: list[str] = []
    for parca in (_ayar.ayar("TP_PLATFORMS") or "").split(","):
        ad = parca.strip().lower()
        if ad in platformlar.UYGULAMA_PLATFORMLARI and ad not in out:
            out.append(ad)
    return tuple(out)


def ayri_depolu_platformlar() -> list[tuple[str, str]]:
    """Etkin ve ayrı depoya bağlı uygulama platformları: [(platform, depo)] (gece koşusu). Biçimi
    bozuk platform deposu atlanır (uyarı; `proje_depolari(hatali_atla=True)`)."""
    from tp_core.integrations.proje_ortami import proje_depolari

    etkin = set(etkin_uygulama_platformlari())
    out: list[tuple[str, str]] = []
    for d, ps in proje_depolari(hatali_atla=True).items():
        if not d:
            continue
        out.extend((p, d) for p in ps if p in etkin)
    return sorted(out, key=lambda x: platformlar.UYGULAMA_PLATFORMLARI.index(x[0]))
