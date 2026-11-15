"""Oturumun/token'ın seçili projesi ve o projedeki roller (TP-COK-PROJE-PLANI §2.2, §6.1).

Proje kipi (`aiprobe.proje_kipi()`: AI Probe kimliği + `TP_HOME_PROJECT`) kapalıyken her şey
bugünkü gibidir: tek proje `varsayilan_pid()`, rol `app_user.rol`.

Açıkken:

- Portal oturumunun projesi `oturum.project_id` (seçim; `PUT /proje`), yoksa kişinin kayıtlı
  seçimi (`app_user.secili_proje`), yoksa `TP_HOME_PROJECT`.
- Roller = kişinin o projedeki TP rolleri (`/v1/projects?uid=`, `acr` süzgeciyle). Etkin rol
  hesabı bu kümede değilse proje kapsamlı uçlar 403 `proje_rolu_yok` döner (iptal değil: kişi
  başka projede çalışabilir; portal proje seçtirir).
- `X-TP-Proje` başlığı (portal her istekte gönderir) oturum projesinden farklıysa 409
  `proje_degisti` (GET dahil; ikinci sekme eski projeye yazamaz). SSE başlık taşıyamadığından
  `/events` için `?proje=` sorgu parametresi de kabul edilir.
- Oturum ve kullanıcı geneli uçlar (`/auth/*`, `/projeler`, `/proje`) bu iki denetimden muaftır:
  rolsüz projede de `/auth/me` okunabilir ve proje değiştirilebilir.
"""

from __future__ import annotations

from typing import Any, Final

from tp_core.api.errors import proje_degisti, proje_rolu_yok
from tp_core.auth import aiprobe
from tp_core.models import AppUser
from tp_core.proje import varsayilan_pid

BASLIK: Final = "X-TP-Proje"
SORGU: Final = "proje"
MUAF_ONEKLER: Final = ("/auth/",)
MUAF_YOLLAR: Final = frozenset({"/projeler", "/proje"})
SORGU_YOLLARI: Final = frozenset({"/events"})

# Rol kodu → görünen ad (TR `yetki.ROL_ETIKETLERI` ile aynı; EN ortak değiştirici için).
ROL_ETIKETLERI_EN: Final[dict[str, str]] = {
    "admin": "System Administrator",
    "auditor": "Auditor",
    "analyst": "Analyst",
    "po": "PO",
    "tester": "Tester",
    "engineer": "Automation Engineer",
    "developer": "Developer",
    "viewer": "Viewer",
}


def muaf_mi(yol: str) -> bool:
    return yol in MUAF_YOLLAR or yol.startswith(MUAF_ONEKLER)


def oturum_projesi(user: AppUser, oturum_pid: str | None, harici: bool) -> str:
    """Portal oturumunun projesi. Proje kipi kapalıysa ya da oturum yerel (bağsız hesap) ise
    varsayılan proje."""
    if not aiprobe.proje_kipi() or not harici:
        return varsayilan_pid()
    return oturum_pid or user.secili_proje or varsayilan_pid()


def proje_rolleri(uid: str | None, pid: str, acr: str | None, etkin_rol: str) -> frozenset[str]:
    """Seçili projedeki kullanılabilir TP rolleri (`acr` süzgeciyle). Proje kipi kapalıysa ya da
    oturum yerelse yalnız etkin rol. Home'a ulaşılamaz ve son bilinen liste eskiyse boş (bu
    durumda oturum kontrolü zaten erişimi kapatır)."""
    if uid is None or not aiprobe.proje_kipi():
        return frozenset({etkin_rol})
    try:
        ham = aiprobe.proje_rolleri(uid, pid)
    except aiprobe.HomeUlasilamaz:
        return frozenset()
    if ham is None:
        return frozenset({etkin_rol})
    return frozenset(aiprobe.tp_rolleri(ham, acr))


def istek_projesi(yol: str, basliklar: Any, sorgu: Any) -> str | None:
    """İstemcinin gösterdiği proje: `X-TP-Proje`, yoksa (yalnız SSE) `?proje=`."""
    deger = basliklar.get(BASLIK)
    if not deger and yol in SORGU_YOLLARI:
        deger = sorgu.get(SORGU)
    deger = (deger or "").strip()
    return deger or None


def denetle(
    yol: str, istenen: str | None, pid: str, etkin_rol: str, roller: frozenset[str]
) -> None:
    """Proje kapsamlı uçlar için: başlık uyuşmazlığı 409, seçili projede etkin rol yoksa 403."""
    if muaf_mi(yol):
        return
    if istenen is not None and istenen != pid:
        raise proje_degisti()
    if etkin_rol not in roller:
        raise proje_rolu_yok()
