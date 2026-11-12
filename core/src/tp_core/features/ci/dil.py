"""Üretim dili boyutunun CI / triage / onarım ortak yardımcıları (011 §2.8). Veritabanı yazmaz.

Dil platformdan türetilmez (K1): `web` × `ts | java`, uygulama platformları × `java`. Bu modül
şu sorulara tek yerden yanıt verir:

- **Script'in dili** (`script_dili`): `Script.dil` (0021); boşsa platformun varsayılanı
  (`web → ts`, uygulama → `java`).
- **Koşunun dili** (`kosu_dili`): `run.ortam.dil` → `run.ortam.lang` (009'un Java işareti) →
  platformun varsayılanı. Koşu kaydında dilin yeri `run.ortam.dil`'dir (portal bunu gösterir).
- **Repoda hangi tam hat dillerinin web testi var** (`repodaki_web_dilleri`): paket koşuları
  (gece / push / deploy; script'li push dahil, K-T2) web için her birini ayrı koşuda koşturur.
- **Script'siz PR hangi dilleri koşar** (`degisen_web_dilleri`): değişen web test köklerine
  göre (K-T1); test kökleri dışında bir değişiklik (uygulama kodu) varsa repodaki tüm tam hat
  dilleri (K-T11). LocalForge merge kapısı (`forge.local_required_checks`) aynı kuralı uygular.

Dil kümeleri, Java test kalıbı ve repo/fark dil seçimi (`repodaki_web_dilleri`,
`degisen_web_dilleri`) `codegen/platform.py`'dendir (tek kaynak; forge kapısı da oradan okur).

Web + Java (Playwright for Java + TestNG) hedef projesi `<uygulama kökü>/e2e-java`'dır
(`codegen.service.e2e_java_root`); konvansiyonu `e2e-app` ile aynıdır.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen.platform import degisen_web_dilleri, repodaki_web_dilleri

__all__ = [
    "degisen_web_dilleri",
    "kosu_dili",
    "ortam_dili",
    "repodaki_web_dilleri",
    "script_dili",
    "tam_hat_dili",
    "web_java_mi",
]


def tam_hat_dili(deger: Any) -> str | None:
    """Değer CI'da koşan bir dil mi (`ts` | `java`)? Değilse None. (`platform.gecerli_dil`
    ValueError atan doğrulayıcıdır; bu süzgeç sessizdir.)"""
    return deger if isinstance(deger, str) and deger in platformlar.TAM_HAT_DILLERI else None


def script_dili(script: Any) -> str:
    """Script'in üretim dili (`Script.dil`, 0021); boşsa platformun varsayılanı."""
    return script.dil or platformlar.varsayilan_dil(script.platform)


def ortam_dili(ortam: Mapping[str, Any] | None) -> str | None:
    """`ortam.dil` → `ortam.lang` (009: Java koşusu işareti); yoksa None."""
    o = ortam or {}
    return tam_hat_dili(o.get("dil")) or tam_hat_dili(o.get("lang"))


def kosu_dili(run: Any) -> str:
    """Koşunun dili: `run.ortam.dil` → `run.ortam.lang` → platformun varsayılanı."""
    o = run.ortam or {}
    return ortam_dili(o) or platformlar.varsayilan_dil(o.get("platform"))


def web_java_mi(platform: str | None, dil: str | None) -> bool:
    """Web + Java hattı mı (Playwright for Java + TestNG)?"""
    return not platformlar.uygulama_mi(platform) and platformlar.java_mi(dil)
