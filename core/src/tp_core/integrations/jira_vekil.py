"""core-api'nin Jira OAuth kipinde Jira işlemlerini core-worker'a devretmesi (`jira.vekil` işi).

Atlassian OAuth (3LO) bağlantı token'ı okuma ile yazmayı ayırmaz; bu yüzden yalnız yazma kimliği
taşıyan süreç (`TP_BAGLANTI_TOKENI=1`, compose'da yalnız core-worker) alabilir
(`home_config.baglanti`, security-check 8). core-api bu kipte Jira istemcisi kuramaz; eskiden
kapı denetimi (`flow.po_label_current`) ve benzeri eşzamanlı Jira çağrıları
`JiraConfigError` → 409 "Jira'dan doğrulanamadı" dönüyordu.

Çözüm GitHub App kipindeki forge devriyle (`demo.durum_oku`, `codegen.dil_algila`) aynıdır: API
işi kuyruğa alır, sonucu en çok `bekleme_s` bekler. İş `anlik` şeridinde koşar: uzun model/CI
işleri (genel/uzun şerit) bu kısa Jira çağrılarını bekletmez.

Güvenlik: worker yalnız `ISLEMLER`'deki adlandırılmış işlemleri yürütür (serbest yöntem çağrısı
yok); her işlem yükünü kendisi doğrular. Yetki denetimi API ucunda yapılmıştır; aktör yükte taşınır
(denetim kaydı). Token core-api'ye hiç gelmez.
"""

from __future__ import annotations

import importlib
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

from tp_core.integrations.jira import JiraError

log = logging.getLogger(__name__)

VEKIL_JOB = "jira.vekil"
BEKLEME_S = 20.0  # portal nginx /api/ zaman aşımı 30 sn
YOKLAMA_S = 0.2
ZAMAN_ASIMI_S = 90  # worker tarafı iş sınırı (Jira istemci zaman aşımı + yeniden deneme payı)

# işlem adı → "modül:fonksiyon" (fonksiyon `(yuk: Mapping) -> JSON` imzalı, worker'da koşar)
ISLEMLER: dict[str, str] = {
    "po_etiketi": "tp_core.features.requirements.flow:vekil_po_etiketi",
    "ice_aktar": "tp_core.features.requirements.flow:vekil_ice_aktar",
    "bug_hedef": "tp_core.features.bugs.service:vekil_bug_hedef",
    "acik_soru_gonder": "tp_core.features.cases.acik_sorular:vekil_gonder",
    "acik_soru_yanitlar": "tp_core.features.cases.acik_sorular:vekil_yanitlar",
}


class JiraVekilHatasi(JiraError):
    """Worker'daki Jira işlemi başarısız ya da süresinde bitmedi (çağıran fail-closed davranır)."""


def _is_kurali_hatasi(veri: Mapping[str, Any]) -> Exception:
    """Worker'da yükselen iş kuralı hatası (`WorkflowError` ailesi) API'de aynı durum kodu ve
    makine koduyla yeniden yükseltilir (ör. 409 `kapi_kapali`)."""
    from tp_core.workflow.service import WorkflowError

    class VekilIsKuraliHatasi(WorkflowError):
        pass

    exc = VekilIsKuraliHatasi(str(veri.get("mesaj") or "İşlem reddedildi"))
    status, kod = veri.get("status_code"), veri.get("kod")
    exc.status_code = status if isinstance(status, int) else 409
    exc.kod = kod if isinstance(kod, str) else None
    return exc


def gerekli() -> bool:
    """Bu süreç Jira'yı kendisi çağıramıyor mu: Jira OAuth kipi + bağlantı token'ı alamayan süreç
    (core-api). Token kipinde core-api okuma kimliğiyle doğrudan okur (bugünkü davranış)."""
    from tp_core.home_config import baglanti
    from tp_core.integrations.jira import oauth_kipi

    if baglanti.yetkili_surec():
        return False
    try:
        return oauth_kipi()
    except Exception:  # config okunamadı: doğrudan yol kendi hatasını raporlar
        log.warning("jira vekili: bağlantı kipi okunamadı", exc_info=True)
        return False


def yazma_gerekli() -> bool:
    """Bu süreç Jira'ya YAZAMIYOR mu: `gerekli()` (OAuth kipi) ya da token kipinde yazma kimliği
    (`JIRA_WRITE_EMAIL/TOKEN`) bu süreçte yok (compose: yalnız core-worker'da; simülatörde sim
    kullanıcısı vardır). Yazan eşzamanlı uçlar (açık soruları PO'ya gönder) bu durumda devreder."""
    if gerekli():
        return True
    from tp_core.home_config import baglanti

    if baglanti.yetkili_surec():
        return False
    from tp_core.integrations.jira import SIM_WRITE, _creds, get_jira_settings

    try:
        s = get_jira_settings()
        return (
            _creds(s.jira_write_email, s.jira_write_token, SIM_WRITE, s.is_simulator, "write")
            is None
        )
    except Exception:  # ayar okunamadı: doğrudan yol kendi hatasını raporlar
        log.warning("jira vekili: yazma kimliği denetlenemedi", exc_info=True)
        return False


def aktor_yuk(user: Any) -> dict[str, Any]:
    """`Principal` → iş yükü (yetki API'de denetlendi; worker yalnız denetim/izlerde kullanır)."""
    return {
        "id": str(user.id) if getattr(user, "id", None) else None,
        "kullanici_adi": user.kullanici_adi,
        "rol": user.rol,
        "kanal": getattr(user, "kanal", "portal"),
        "kapsam": getattr(user, "kapsam", None),
        "project_id": getattr(user, "project_id", None),
        "roller": sorted(getattr(user, "roller", ()) or ()),
    }


def aktor(yuk: Mapping[str, Any]) -> Any:
    from tp_core.workflow.service import Principal

    a = yuk.get("aktor")
    if not isinstance(a, Mapping) or not a.get("kullanici_adi") or not a.get("rol"):
        raise ValueError("jira vekili: aktör eksik")
    return Principal(
        uuid.UUID(str(a["id"])) if a.get("id") else None,
        str(a["kullanici_adi"]),
        str(a["rol"]),
        str(a.get("kanal") or "portal"),
        a.get("kapsam"),
        a.get("project_id"),
        frozenset(str(r) for r in a.get("roller") or ()),
    )


def calistir(islem: str, yuk: Mapping[str, Any], *, bekleme_s: float | None = None) -> Any:
    """İşlemi core-worker'da (`jira.vekil`) yürütür ve sonucunu döner (core-api tarafı).

    İş başarısızsa ya da `bekleme_s` içinde bitmezse `JiraVekilHatasi`; süresi dolan iş hâlâ
    kuyruktaysa iptal edilir (geç yürütülüp kullanıcıya görünmeyen yan etki bırakmasın)."""
    from tp_core.db import get_engine
    from tp_core.features.publish.service import job_status
    from tp_core.models import session_scope
    from tp_core.workflow.jobs import cancel, enqueue

    if islem not in ISLEMLER:
        raise ValueError(f"bilinmeyen jira vekil işlemi: {islem}")
    with session_scope() as s:
        job_id = enqueue(
            s.connection(),
            VEKIL_JOB,
            {"islem": islem, "yuk": dict(yuk)},
            max_deneme=1,
            zaman_asimi_s=ZAMAN_ASIMI_S,
        )
    engine = get_engine()
    bitis = time.monotonic() + (BEKLEME_S if bekleme_s is None else bekleme_s)
    while True:
        durum, sonuc, hata = job_status(engine, job_id)
        if durum in ("done", "failed", "cancelled") or time.monotonic() >= bitis:
            break
        time.sleep(YOKLAMA_S)
    if durum == "done" and isinstance(sonuc, Mapping):
        if isinstance(sonuc.get("is_kurali"), Mapping):
            raise _is_kurali_hatasi(sonuc["is_kurali"])
        return sonuc.get("deger")
    if durum in ("queued", "retry"):
        with engine.begin() as c:
            cancel(c, job_id)
    log.warning("jira vekil işi %s (%s): %s %s", job_id, islem, durum, hata)
    if durum in ("queued", "retry", "running"):
        raise JiraVekilHatasi("Jira işlemi arka plan servisinde süresinde tamamlanmadı")
    raise JiraVekilHatasi(f"Jira işlemi arka plan servisinde başarısız: {hata or durum}")


def isle(yuk: Mapping[str, Any] | None) -> dict[str, Any]:
    """`jira.vekil` işi (core-worker): adlandırılmış işlemi yürütür; sonuç `{"deger": …}`."""
    if not isinstance(yuk, Mapping):
        raise ValueError("jira vekili: yük eksik")
    islem = str(yuk.get("islem") or "")
    hedef = ISLEMLER.get(islem)
    if hedef is None:
        raise ValueError(f"bilinmeyen jira vekil işlemi: {islem!r}")
    ic = yuk.get("yuk")
    if not isinstance(ic, Mapping):
        raise ValueError("jira vekili: işlem yükü eksik")
    from tp_core.workflow.service import WorkflowError

    modul, ad = hedef.split(":")
    fn = getattr(importlib.import_module(modul), ad)
    try:
        return {"deger": fn(ic)}
    except WorkflowError as exc:  # iş kuralı reddi: iş başarılı biter, API aynı hatayı döner
        return {
            "is_kurali": {
                "mesaj": str(exc),
                "status_code": exc.status_code,
                "kod": exc.kod,
            }
        }
