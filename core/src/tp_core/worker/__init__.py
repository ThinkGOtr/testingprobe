"""core-worker: Postgres kuyruğundan (`job`, FOR UPDATE SKIP LOCKED) iş alır ve kayıtlı
işleyicilere dağıtır. İşleyiciler `@tp_core.workflow.jobs.job_handler` ile kaydolur;
`tp_core.features.<ad>.jobs` modülleri başlangıçta otomatik yüklenir.

Yeniden deneme/geri çekilme, zaman aşımı ve idempotency kuralları `tp_core.workflow.jobs`'tadır.

Açılışta (ilk başarılı DB turunda) aynı konteynerin önceki sürecinden kalan `running` işler
bırakılır (`release_orphans`): önceki sürecin kimliği `TP_WORKER_STATE_FILE` dosyasından okunur
ve yalnızca onun işleri beklemeden bırakılır; aynı hostname'deki diğer işler ancak nabızları
kesildiyse bırakılır (ölçeklenmiş kopyanın canlı işlerine dokunulmaz). Ardından özellik
modüllerinin `on_worker_start` kancaları koşar; DB hazır değilken başarısız olan kanca sonraki
turlarda başarılı olana dek yeniden denenir (Docker yeniden başlatma yarışı).

İki yürütme yuvası (şerit): uzun işler (`ci.run`, `repair.fix`, kod üretimi, demo kırılması …;
`uzun_serit_turleri()`) ayrı bir iş parçacığında, geri kalan her şey ana döngüde koşar. Böylece
20 dakikalık bir CI koşusu ya da onarımın tam yerel kontrolü PO etiket sorgusunu
(`requirements.po_poll`) ve triage taramasını bekletmez. Uzun şerit kendi içinde sıralıdır
(toolchain `/check` zaten tek kilitli). `TP_WORKER_UZUN_SERIT=0` eski tek yuvalı davranışa döner;
o durumda uzun bir iş süresince diğer işler (PO onayı alımı dahil) iş bitene kadar gecikir.

Asistan şeridi (AI-ASISTAN-PLANI §10.1): `serit="asistan"` ile kaydolan türler
(`assistant.answer`) `TP_WORKER_ASISTAN_SERIT=1` (varsayılan) iken `uzun` boş olsa da
`TP_WORKER_ASISTAN_PARALEL` (varsayılan 3) iş parçacığında koşar; her biri
`process_one(turler=asistan)` çağırır, işler `FOR UPDATE SKIP LOCKED` ile tekil alınır, bloke bir
asistan işi diğerlerini durdurmaz. Genel şeridin `haric`'i diğer şeritlerin tür birleşimidir; hiç
ek şerit yoksa `_genel_haric` None kalır (eski davranış). Ayrı bir zamanlayıcı iş parçacığı her
`KALP_ATISI_ARALIGI_S` (30 sn) `asistan_durum`'u yazar (asistan işi şeridi 120 sn'ye kadar bloke
edebildiği için şerit döngüsünden bağımsız). Asistan şeridi her turda (en sık
`UZLASTIRMA_ARALIGI_S`'de bir) işi bitmiş ya da olmayan açık mesajları `error/zaman_asimi` yapar.
`TP_WORKER_ASISTAN_SERIT=0` iken şerit ve kalp atışı yoktur → asistan `worker_yok` görünür;
asistan türleri yine genel şeridin `haric`'indedir (genel şeritte zaman aşımı süreci kapatırdı).

Bir iş `zaman_asimi_s` içinde bitmezse iş `retry`/`failed` yazılır ve süreç
`ZAMAN_ASIMI_CIKIS_KODU` ile çıkar (asılı iş parçacığı öldürülemez; compose yeniden başlatır).
Asistan şeridinde zaman aşımı süreci kapatmaz: iş `failed`, mesaj uzlaştırmayla
`error/zaman_asimi` olur; asılı iş parçacığı en geç bir sonraki geçit turunda `should_stop`
(mesaj artık `running` değil) ile durur ve geç gelen sonucu yazamaz (`durum='running'` koşulu).
Asılı iş parçacığı durana dek şeritte bir yuva sayılır: koşan + asılı iş parçacığı sayısı
`asistan_paralel()`'e ulaştıysa şerit yeni iş almaz (gerçek eşzamanlı model çağrısı ≤ PARALEL).

Canlılık: ana döngü (ve iş beklerken yürütücü) `TP_WORKER_LIVENESS_FILE` dosyasının zamanını
tazeler; `tp_core.worker.healthcheck` dosya `CANLILIK_ESIGI_S`'den eskiyse sağlıksız der.

Veritabanına ulaşılamazken tek satırlık uyarı yazılır ve bekleme üstel artar
(1 → 2 → 4 … ≤ `DB_BEKLEME_UST_S` sn); bağlantı dönünce bir kez bilgi yazılır.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any

import psycopg
from sqlalchemy.exc import InterfaceError, OperationalError

from tp_core.db import get_engine
from tp_core.workflow import jobs
from tp_core.workflow.jobs import (
    ASISTAN_SERIT,
    HEARTBEAT_S,
    REGISTRY,
    ClaimedJob,
    HandlerSpec,
    JobContext,
    Sonuc,
    discover,
    process_one,
    reap_stale,
    release_orphans,
    serit_turleri,
    uzun_turler,
    worker_id,
)

log = logging.getLogger("tp_core.worker")

GECISLER: dict[str, frozenset[str]] = jobs.JOB_GECISLERI
HANDLERS: Mapping[str, HandlerSpec] = REGISTRY
REAP_ARALIGI_S = 30.0
DB_BEKLEME_UST_S = 30.0
ZAMAN_ASIMI_CIKIS_KODU = 70
CANLILIK_ESIGI_S = 120.0
# Açılışta başka bir sürecin (aynı hostname) işini "ölü" saymak için nabzın bu kadar eski olması
# gerekir (nabız `HEARTBEAT_S`'de bir yazılır).
SAHIPSIZ_NABIZ_S = 2 * HEARTBEAT_S
# Başarısız açılış kancasının yeniden deneme aralığı (log selini önler).
KANCA_TEKRAR_S = 10.0
# Asistan durum satırı (`asistan_durum`) kalp atışı; API 2 dk'dan eskisini "worker yok" sayar.
KALP_ATISI_ARALIGI_S = 30.0
# Asistan şeridi uzlaştırması en sık bu aralıkta bir (paralel iş parçacıkları aynı sorguyu
# saniyede birkaç kez koşmasın); zaman aşımından hemen sonra beklemeden koşar.
UZLASTIRMA_ARALIGI_S = 5.0


def canlilik_dosyasi() -> Path:
    return Path(
        os.environ.get("TP_WORKER_LIVENESS_FILE")
        or os.path.join(tempfile.gettempdir(), "tp-worker-canli")
    )


def durum_dosyasi() -> Path:
    """Bu konteynerdeki son worker sürecinin kimliğini (`kilitleyen`) tutan dosya."""
    return Path(
        os.environ.get("TP_WORKER_STATE_FILE")
        or os.path.join(tempfile.gettempdir(), "tp-worker-surec")
    )


def onceki_surec() -> str | None:
    with contextlib.suppress(OSError, UnicodeDecodeError):
        return durum_dosyasi().read_text().strip() or None
    return None


def surec_kaydet(kimlik: str) -> None:
    try:
        durum_dosyasi().write_text(kimlik + "\n")
    except OSError as exc:
        log.warning("worker süreç kimliği yazılamadı (%s); sonraki açılış nabza düşer", exc)


def canli() -> None:
    """Canlılık işaretini tazeler (yazılamazsa sessiz: sağlık kontrolü DB'ye düşer)."""
    with contextlib.suppress(OSError):
        canlilik_dosyasi().write_text(f"{time.time():.3f}\n")


class ZamanAsimiCikisi(RuntimeError):
    """Bir iş süresini aştı; işleyici iş parçacığı asılı — süreç yeniden başlamalı."""


DB_HATALARI: tuple[type[BaseException], ...] = (
    OperationalError,
    InterfaceError,
    psycopg.OperationalError,
    psycopg.InterfaceError,
)

Handler = Callable[[JobContext], Any]

__all__ = ["GECISLER", "HANDLERS", "GecersizGecis", "Sonuc", "calistir", "gecis", "main", "run"]


class GecersizGecis(ValueError):
    pass


def gecis(mevcut: str, hedef: str) -> str:
    if hedef not in GECISLER.get(mevcut, frozenset()):
        raise GecersizGecis(f"{mevcut} -> {hedef}")
    return hedef


def calistir(
    tur: str,
    yuk: Mapping[str, Any] | None,
    handlers: Mapping[str, Handler] | None = None,
    *,
    deneme: int = 1,
) -> Sonuc:
    """Tek bir denemeyi DB'siz yürütür (test ve teşhis için). `handlers` verilirse düz
    çağrılabilirler tek denemelik işleyici sayılır; verilmezse kayıtlı işleyiciler kullanılır."""
    kayit: Mapping[str, HandlerSpec] = (
        REGISTRY
        if handlers is None
        else {t: HandlerSpec(t, fn, max_deneme=1) for t, fn in handlers.items()}
    )
    return jobs.execute(ClaimedJob(uuid.uuid4(), tur, yuk, deneme, None, None), kayit)


_son_reap = 0.0
_sahipsizler_birakildi = False
# Henüz başarıyla koşmamış `on_worker_start` kancalarının modülleri (main doldurur).
_bekleyen_kancalar: list[str] = []
_kanca_sonraki = 0.0
# Ana (genel) döngünün almayacağı türler: uzun/asistan şeridi açıkken `run()` doldurur.
_genel_haric: list[str] | None = None
_son_uzlastirma = 0.0
_uzlastirma_kilidi = threading.Lock()
# Asistan şeridinin gerçek eşzamanlılığı: işleyicisi koşan (`_asistan_aktif`) + zaman aşımından
# sonra asılı kalan (`_asistan_asili`) iş parçacıkları toplamı `asistan_paralel()`'i geçmez.
# Asılı olan iş `failed` yazıldığı için `budget.global_bekleyen`'de sayılmaz; burada sayılır.
_asistan_kilidi = threading.Lock()
_asistan_aktif = 0
_asistan_asili: list[threading.Thread] = []


def uzun_serit_turleri() -> frozenset[str]:
    """Ayrı yuvada koşacak türler (boş = tek yuva). Yapılandırma + `serit="uzun"` kayıtları."""
    from tp_core.config import get_settings

    ayar = get_settings()
    if not ayar.worker_uzun_serit:
        return frozenset()
    return uzun_turler(ayar.worker_uzun_turler.split(","))


def asistan_serit_turleri() -> frozenset[str]:
    """Asistan şeridinde koşacak türler (boş = şerit yok): `TP_WORKER_ASISTAN_SERIT` açıkken
    `serit="asistan"` kayıtları."""
    from tp_core.features.assistant.durum import asistan_serit_acik

    if not asistan_serit_acik():
        return frozenset()
    return serit_turleri(ASISTAN_SERIT)


def asistan_paralel() -> int:
    """Asistan şeridi iş parçacığı sayısı (`TP_WORKER_ASISTAN_PARALEL`, varsayılan 3). Global
    bekleyen sınırı (2 × bu) aynı fonksiyonla hesaplanır (`features.assistant.budget`)."""
    from tp_core.features.assistant.budget import paralel

    return paralel()


def tek_tur() -> bool:
    """İlk turda önceki süreçten kalan işleri bırakır ve açılış kancalarını koşar (başarısız
    kancalar sonraki turlarda yeniden denenir); gerekirse zaman aşımına uğramış işleri toplar,
    sonra bir iş işler; iş yoksa False."""
    global _son_reap, _sahipsizler_birakildi
    engine = get_engine()
    if not _sahipsizler_birakildi:
        kendi = worker_id()
        with engine.begin() as conn:
            n = release_orphans(conn, haric=kendi, onceki=onceki_surec(), taze_s=SAHIPSIZ_NABIZ_S)
        surec_kaydet(kendi)
        _sahipsizler_birakildi = True
        if n:
            log.warning("önceki worker sürecinden kalan %d iş bırakıldı (retry/failed)", n)
    if _bekleyen_kancalar:
        kancalari_dene()
    if time.monotonic() - _son_reap >= REAP_ARALIGI_S:
        with engine.begin() as conn:
            n = reap_stale(conn)
        _son_reap = time.monotonic()
        if n:
            log.warning("%d zaman aşımına uğramış iş yeniden kuyruğa alındı", n)
    sonuc = process_one(engine, canli=canli, haric=_genel_haric)
    if sonuc is not None and sonuc.zaman_asimi:
        raise ZamanAsimiCikisi(sonuc.hata or "iş zaman aşımına uğradı")
    return sonuc is not None


def _kisa_hata(exc: BaseException) -> str:
    kok = getattr(exc, "orig", None) or exc
    satirlar = str(kok).strip().splitlines()
    return (satirlar[0] if satirlar else type(kok).__name__)[:200]


def uzun_tur(turler: Collection[str]) -> bool:
    """Uzun şeritten bir iş işler (yalnızca `turler`); iş yoksa False."""
    sonuc = process_one(get_engine(), canli=canli, turler=sorted(turler))
    if sonuc is not None and sonuc.zaman_asimi:
        raise ZamanAsimiCikisi(sonuc.hata or "iş zaman aşımına uğradı")
    return sonuc is not None


def uzlastir_gerekirse(*, zorla: bool = False) -> int:
    """Asistan mesaj uzlaştırması (`features.assistant.durum.uzlastir`); paralel iş parçacıkları
    arasında `UZLASTIRMA_ARALIGI_S`'de bir koşar (`zorla` beklemez). Kapanan mesaj sayısı."""
    global _son_uzlastirma
    from tp_core.features.assistant.durum import uzlastir

    with _uzlastirma_kilidi:
        if not zorla and time.monotonic() - _son_uzlastirma < UZLASTIRMA_ARALIGI_S:
            return 0
        _son_uzlastirma = time.monotonic()
    with get_engine().begin() as conn:
        return len(uzlastir(conn))


def asistan_tur(turler: Collection[str]) -> bool:
    """Asistan şeridinden bir iş işler (yalnızca `turler`); iş yoksa False.

    Zaman aşımı süreci kapatmaz: iş `failed` yazılmıştır; mesaj hemen uzlaştırılır
    (`error/zaman_asimi`) ve asılı iş parçacığı `should_stop` ile kendiliğinden durur. Asılı
    iş parçacığı durana dek bir yuva tutar: koşan + asılı `asistan_paralel()`'e ulaştıysa yeni
    iş alınmaz (False; döngü `aralik` bekler).
    """
    global _asistan_aktif
    uzlastir_gerekirse()
    with _asistan_kilidi:
        _asistan_asili[:] = [t for t in _asistan_asili if t.is_alive()]
        if _asistan_aktif + len(_asistan_asili) >= asistan_paralel():
            return False
        _asistan_aktif += 1
    sonuc = None
    try:
        sonuc = process_one(get_engine(), canli=canli, turler=sorted(turler))
    finally:
        with _asistan_kilidi:
            _asistan_aktif -= 1
            if sonuc is not None and sonuc.asili is not None:
                _asistan_asili.append(sonuc.asili)
    if sonuc is not None and sonuc.zaman_asimi:
        log.error("asistan işi zaman aşımına uğradı; süreç sürüyor: %s", sonuc.hata)
        uzlastir_gerekirse(zorla=True)
    return sonuc is not None


def _kalp_atisi_dongusu(dur: threading.Event) -> None:
    """`asistan_durum` kalp atışı: hemen, sonra her `KALP_ATISI_ARALIGI_S`'de bir; DB hatası
    döngüyü durdurmaz (tek satır uyarı)."""
    from tp_core.features.assistant.durum import kalp_atisi_yaz

    while not dur.is_set():
        try:
            kalp_atisi_yaz(get_engine())
        except DB_HATALARI as exc:
            log.warning("asistan kalp atışı yazılamadı: DB erişilemiyor: %s", _kisa_hata(exc))
        except Exception as exc:
            log.warning("asistan kalp atışı yazılamadı (%s)", type(exc).__name__)
        if dur.wait(KALP_ATISI_ARALIGI_S):
            return


def run(dur: threading.Event, aralik: float = 1.0, *, uzun: Collection[str] | None = None) -> int:
    """Kuyruk döngüsü; çıkış kodu döndürür (0 = durduruldu, `ZAMAN_ASIMI_CIKIS_KODU`).

    `uzun` boş değilse bu türler ayrı bir iş parçacığında (uzun şerit) koşar, ana döngü onları
    almaz. Genel ya da uzun şeritte zaman aşımı tüm süreci `ZAMAN_ASIMI_CIKIS_KODU` ile durdurur.
    Asistan şeridi (`asistan_serit_turleri()`) `uzun`'dan bağımsızdır: `asistan_paralel()` iş
    parçacığı + kalp atışı zamanlayıcısı; zaman aşımı süreci durdurmaz.
    """
    global _genel_haric
    log.info("worker başladı; işleyiciler: %s", ", ".join(sorted(REGISTRY)))
    asistan = asistan_serit_turleri()
    # Şerit kapalıyken de asistan türleri genel şeritte koşmaz: orada zaman aşımı tüm süreci
    # kapatırdı. Bekleyen asistan işleri kuyrukta kalır (asistan `worker_yok` görünür).
    tum_asistan = serit_turleri(ASISTAN_SERIT)
    kapali_asistan = tum_asistan - asistan
    uzun_k = frozenset(uzun or ()) - tum_asistan
    if not uzun_k and not asistan:
        if not kapali_asistan:
            return _dongu(dur, aralik, lambda: tek_tur(), "genel")
        _genel_haric = sorted(kapali_asistan)
        try:
            return _dongu(dur, aralik, lambda: tek_tur(), "genel")
        finally:
            _genel_haric = None
    _genel_haric = sorted(uzun_k | tum_asistan)
    kodlar: list[int] = []
    iplikler: list[threading.Thread] = []

    if uzun_k:
        log.info("uzun şerit ayrı yuvada: %s", ", ".join(sorted(uzun_k)))

        def serit() -> None:
            kod = _dongu(dur, aralik, lambda: uzun_tur(uzun_k), "uzun")
            if kod:
                kodlar.append(kod)
            dur.set()  # uzun şerit zaman aşımıyla çıktıysa ana döngü de durur

        iplikler.append(threading.Thread(target=serit, name="serit-uzun", daemon=True))

    if asistan:
        n = asistan_paralel()
        log.info("asistan şeridi %d iş parçacığında: %s", n, ", ".join(sorted(asistan)))
        for i in range(1, n + 1):
            iplikler.append(
                threading.Thread(
                    target=_dongu,
                    args=(dur, aralik, lambda: asistan_tur(asistan), f"asistan-{i}"),
                    name=f"serit-asistan-{i}",
                    daemon=True,
                )
            )
        iplikler.append(
            threading.Thread(
                target=_kalp_atisi_dongusu, args=(dur,), name="asistan-kalp-atisi", daemon=True
            )
        )

    for t in iplikler:
        t.start()
    try:
        kod = _dongu(dur, aralik, lambda: tek_tur(), "genel")
    finally:
        dur.set()
        _genel_haric = None
    # Bir şerit bir işin ortasındaysa beklenmez: süreç çıkınca iş sahipsiz kalır ve sonraki
    # açılışta `release_orphans` ile bırakılır (tek yuvalı çıkışla aynı sonuç).
    son = time.monotonic() + 5
    for t in iplikler:
        t.join(timeout=max(0.0, son - time.monotonic()))
        if t.is_alive():
            log.warning("%s bir işin ortasında; iş sonraki açılışta bırakılacak", t.name)
    return kod or (kodlar[0] if kodlar else 0)


def _dongu(dur: threading.Event, aralik: float, adim: Callable[[], bool], ad: str) -> int:
    db_bekleme: float | None = None  # None = bağlantı sağlıklı
    while not dur.is_set():
        canli()
        try:
            calisti = adim()
        except ZamanAsimiCikisi as exc:
            log.error("worker yeniden başlatılmak üzere çıkıyor (%s şeridi): %s", ad, exc)
            return ZAMAN_ASIMI_CIKIS_KODU
        except DB_HATALARI as exc:
            db_bekleme = aralik if db_bekleme is None else min(db_bekleme * 2, DB_BEKLEME_UST_S)
            db_bekleme = max(db_bekleme, aralik)
            log.warning("DB erişilemiyor: %s; %.0f sn sonra tekrar", _kisa_hata(exc), db_bekleme)
            dur.wait(db_bekleme)
            continue
        except Exception:
            log.exception("kuyruk turu başarısız (%s şeridi); yeniden denenecek", ad)
            dur.wait(aralik)
            continue
        if db_bekleme is not None:
            log.info("DB bağlantısı yeniden kuruldu")
            db_bekleme = None
        if not calisti:
            dur.wait(aralik)
    log.info("worker durdu" if ad == "genel" else f"{ad} şeridi durdu")
    return 0


def _kanca(ad: str) -> Callable[..., Any] | None:
    import importlib

    kanca = getattr(importlib.import_module(ad), "on_worker_start", None)
    return kanca if callable(kanca) else None


def acilis_kancalari(moduller: list[str]) -> list[str]:
    """Özellik `jobs` modüllerindeki `on_worker_start(conn)` kancalarını çağırır; başarıyla
    koşan modülleri döndürür.

    Ör. kendini yeniden planlayan periyodik işler (PO etiket sorgusu) kuyruk silinse de worker
    açılışında yeniden başlar. Kanca hatası worker'ı düşürmez (loglanır; DB erişilemiyorsa tek
    satır uyarı); her kanca kendi işleminde koşar.
    """
    calisan: list[str] = []
    for ad in moduller:
        kanca = _kanca(ad)
        if kanca is None:
            continue
        try:
            with get_engine().begin() as conn:
                kanca(conn)
            calisan.append(ad)
        except DB_HATALARI as exc:
            log.warning("%s.on_worker_start: DB erişilemiyor: %s", ad, _kisa_hata(exc))
        except Exception:
            log.exception("%s.on_worker_start başarısız", ad)
    return calisan


def kancalari_planla(moduller: list[str]) -> list[str]:
    """`on_worker_start` kancası olan modülleri ilk DB turunda koşmak üzere sıraya alır."""
    global _bekleyen_kancalar, _kanca_sonraki
    _bekleyen_kancalar = [ad for ad in moduller if _kanca(ad) is not None]
    _kanca_sonraki = 0.0
    return list(_bekleyen_kancalar)


def kancalari_dene() -> None:
    """Bekleyen açılış kancalarını (aralık dolduysa) dener; başaranları listeden düşer."""
    global _bekleyen_kancalar, _kanca_sonraki
    if not _bekleyen_kancalar or time.monotonic() < _kanca_sonraki:
        return
    basarili = set(acilis_kancalari(_bekleyen_kancalar))
    _bekleyen_kancalar = [ad for ad in _bekleyen_kancalar if ad not in basarili]
    if _bekleyen_kancalar:
        _kanca_sonraki = time.monotonic() + KANCA_TEKRAR_S
        log.warning(
            "açılış kancası bekliyor (%s); %.0f sn sonra yeniden denenecek",
            ", ".join(_bekleyen_kancalar),
            KANCA_TEKRAR_S,
        )
    elif basarili:
        log.info("açılış kancaları koştu: %s", ", ".join(sorted(basarili)))


def main() -> None:
    from tp_core.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    yuklenen = discover()
    if yuklenen:
        log.info("özellik işleyici modülleri: %s", ", ".join(yuklenen))
    # Kancalar ilk başarılı DB turunda koşar (DB henüz hazır değilse yeniden denenir).
    kancalari_planla(yuklenen)
    dur = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: dur.set())
    kod = run(dur, get_settings().worker_poll_interval_s, uzun=uzun_serit_turleri())
    if kod:
        # Asılı işleyici iş parçacığı normal çıkışı bekletebilir; süreç hemen sonlanır.
        logging.shutdown()
        os._exit(kod)
