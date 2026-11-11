"""Case onayı sonrası otomatik kod üretimi (specs/013-sprint-otomasyonu §3.2, K4).

Tekli karar (`approve` / `edit`) ve toplu onay, onay yazıldıktan sonra `kuyruga_al`ı çağırır.
Kod üretimi sistem aktörüyle (`OTOMASYON_AKTORU`) başlar; onaylayan kullanıcı `tetikleyen`
olarak iş akışı yüküne ve denetime yazılır. Engineer rol kapısı bilinçli olarak atlanır: kod
üretimi yalnızca onaylı içerikle başlar (Constitution I), PR merge'ü yine insan işidir.

Kural: otomatik kod üretimi **onayı asla geri almaz**. Üretim kendi SAVEPOINT'inde başlar;
reddedilir ya da beklenmedik biçimde patlarsa yalnız o SAVEPOINT geri alınır.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from tp_core.audit.session import _ANAHTAR as _DENETIM_ANAHTARI
from tp_core.audit.session import audit_on_commit
from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen.service import CodegenRejected, start_generation
from tp_core.features.otomasyon import ayarlar
from tp_core.models import TestCase
from tp_core.workflow.service import Principal

log = logging.getLogger(__name__)

OTOMASYON_AKTORU = ayarlar.OTOMASYON_AKTORU

# start_generation'ın "zaten var" sonuçları: yeni üretim gerekmiyor.
ATLANAN_SONUCLAR = frozenset({"suruyor", "pr_acik", "merge_edildi"})

HATA_NEDENI = (
    "Otomatik kod üretimi beklenmedik bir hatayla başlatılamadı; onay geçerli. "
    "Kod üretimi ekranından elle başlatın."
)


class _GeriAl(Exception):
    """`savepoint` içinden yalnız SAVEPOINT'i geri almak için (dışarı sızmaz)."""


@contextmanager
def savepoint(session: Session) -> Iterator[None]:
    """SAVEPOINT + bekleyen denetim kayıtlarının birlikte geri alınması.

    `audit_on_commit` kayıtları oturumda bekler ve SAVEPOINT geri alımında atılmaz
    (`audit/session.py`); burada geri alınan bölümün eklediği kayıtlar da düşürülür.
    Hata yeniden fırlatılır (çağıran yakalar).
    """
    bekleyen = session.info.get(_DENETIM_ANAHTARI)
    once = len(bekleyen) if bekleyen else 0
    sp = session.begin_nested()
    try:
        yield
    except BaseException:
        if sp.is_active:
            sp.rollback()
        liste = session.info.get(_DENETIM_ANAHTARI)
        if liste is not None:
            del liste[once:]
        raise
    else:
        if sp.is_active:
            sp.commit()


def _sonuc(durum: str, neden: str | None = None, script_id: str | None = None) -> dict[str, Any]:
    return {"durum": durum, "neden": neden, "script_id": script_id}


def kuyruga_al(session: Session, tc: TestCase, onaylayan: Principal) -> dict[str, Any]:
    """Onaylanan case için web kod üretimini kuyruğa alır.

    Dönen `durum`: `kuyrukta` (script_id dolu) | `atlandi` (süren üretim / açık ya da merge
    edilmiş PR) | `reddedildi` (kod üretimi kapısı; neden Türkçe) | `kapali` (ayar kapalı) |
    `hata` (beklenmedik; onay geçerli, denetim `codegen.otomatik_hata`).
    """
    if not ayarlar.otomatik_kod(session).acik:
        return _sonuc("kapali", "Otomatik kod üretimi ayarı kapalı")
    if tc.durum != "approved":
        return _sonuc("atlandi", f"case onaylı değil (durum: {tc.durum})")
    try:
        with savepoint(session):
            cevap = start_generation(
                session,
                [tc.id],
                OTOMASYON_AKTORU,
                platform=platformlar.WEB,
                tetik="otomatik",
                tetikleyen=onaylayan.kullanici_adi,
            )
    except CodegenRejected as exc:
        return _sonuc("reddedildi", str(exc))
    except Exception as exc:
        log.exception("otomatik kod üretimi başlatılamadı (case %s)", tc.id)
        audit_on_commit(
            session,
            OTOMASYON_AKTORU.kullanici_adi,
            "codegen.otomatik_hata",
            f"test_case:{tc.id}",
            {"tetikleyen": onaylayan.kullanici_adi, "hata": type(exc).__name__,
             "mesaj": str(exc)[:500]},
        )  # fmt: skip
        return _sonuc("hata", HATA_NEDENI)
    ilk = (cevap.get("sonuclar") or [{}])[0]
    durum = ilk.get("durum")
    if durum == "basladi":
        return _sonuc("kuyrukta", None, ilk.get("script_id"))
    if durum in ATLANAN_SONUCLAR:
        return _sonuc("atlandi", ilk.get("neden"), ilk.get("script_id"))
    return _sonuc("reddedildi", ilk.get("neden") or cevap.get("mesaj"))
