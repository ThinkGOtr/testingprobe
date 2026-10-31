"""Postgres iş kuyruğu: işleyici kaydı, kuyruğa ekleme, sahiplenme, yeniden deneme.

Kullanım (özellik şeritleri)::

    from tp_core.workflow.jobs import JobContext, job_handler

    @job_handler("requirements.review", max_deneme=1)
    def review(ctx: JobContext) -> dict | None:
        ...  # kendi oturumunu açar; dönen sözlük job.sonuc'a yazılır

`tp_core.features.<ad>.jobs` modülleri worker başlarken otomatik içe aktarılır (`discover()`).

İş durumları: queued → running → done | retry | failed;  retry → running;  queued|retry → cancelled.
- `deneme` başlatılan deneme sayısıdır. Hata olursa `deneme < max_deneme` ise `retry` +
  `run_after = now + backoff_s * 2^(deneme-1)` (≤ `max_backoff_s`), değilse `failed`.
- `PermanentJobError` yeniden denenmez. Ajan işleri `max_deneme=1` ile kaydedilir (§8.1).
- Etkin politika (`max_deneme`, `zaman_asimi_s`): satırdaki değer, yoksa işleyicinin kaydı, yoksa
  varsayılan. `enqueue()` işleyici bu süreçte kayıtlıysa politikayı satıra yazar; kayıtlı değilse
  (ör. core-api) NULL bırakır ve worker kayıttan çözer.
- Sahiplenme `FOR UPDATE SKIP LOCKED`. Çalışan iş `HEARTBEAT_S` aralıkla `guncelleme`'yi tazeler.
- Zaman aşımı yürütücünün içinde uygulanır: işleyici ayrı bir iş parçacığında koşar ve
  `process_one` en fazla `zaman_asimi_s` bekler. Süre dolarsa iş `retry`/`failed` yazılır, nabız
  durur ve sonuç `zaman_asimi=True` döner; asılı iş parçacığı öldürülemediği için worker süreci
  çıkar (compose `restart: unless-stopped` temiz bir süreç başlatır). Tek worker'da da asılı bir
  iş kuyruğu kilitleyemez.
  `reap_stale()` süresi (`zaman_asimi_s`) dolan ya da nabzı `NABIZ_ZAMAN_ASIMI_S` boyunca gelmeyen
  `running` işleri (başka/çökmüş worker'lar), deneme hakkı varsa `retry`'a, yoksa `failed`'a
  (bitis=now) alır. `release_orphans()` worker açılışında aynı makinenin önceki sürecinden kalan
  işleri aynı kuralla bırakır (konteyner yeniden başlatma / OOM). `kilitleyen` =
  `hostname:pid:açılış-kimliği`; açılış önceki sürecin kimliğini bilir ve yalnızca onu (ya da
  nabzı kesilmiş işleri) bırakır — aynı hostname'i paylaşan canlı kopyanın işine dokunmaz.
- Bir iş akışına bağlı iş `failed` olduğunda (işleyici hatası, bilinmeyen tür, zaman aşımı, nabız
  kaybı, sahipsiz iş) `workflow_instance` aynı işlemde `running → failed` olur (`sebep` = son
  hata; denetimli ve `workflow_instance.state` olayıyla) — iş akışı "insana düşer".
- `idempotency_key` verilirse aynı anahtarla ikinci ekleme yeni iş açmaz, mevcut işi döndürür.
  Karar işlem kapsamlı bir advisory lock altında verilir (eşzamanlı çağrılar yarışmaz).
"""

from __future__ import annotations

import contextvars
import importlib
import importlib.util
import json
import logging
import os
import pkgutil
import socket
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, text

from tp_core.audit.canonical import normalize
from tp_core.audit.chain import append_audit
from tp_core.gateway.errors import BudgetExceeded

log = logging.getLogger("tp_core.worker")

DEFAULT_MAX_DENEME = 3
DEFAULT_ZAMAN_ASIMI_S = 900
HEARTBEAT_S = 15.0
NABIZ_ZAMAN_ASIMI_S = 60.0
NOTIFY_CHANNEL = "tp_jobs"
# İki argümanlı advisory lock ad alanı (denetim zincirinin tek argümanlı kilidiyle çakışmaz).
IDEMPOTENCY_LOCK_NS = 7_310_002

JOB_GECISLERI: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"done", "failed", "retry"}),
    "retry": frozenset({"running", "cancelled"}),
    "done": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class PermanentJobError(Exception):
    """Yeniden denenmemesi gereken hata (ör. doğrulama, insan kararı gerekli)."""


@dataclass(frozen=True)
class JobContext:
    job_id: uuid.UUID
    tur: str
    yuk: Mapping[str, Any] | None
    deneme: int
    max_deneme: int
    workflow_id: uuid.UUID | None = None

    @property
    def son_deneme(self) -> bool:
        return self.deneme >= self.max_deneme


Handler = Callable[[JobContext], Any]


@dataclass(frozen=True)
class HandlerSpec:
    tur: str
    fn: Handler
    max_deneme: int = DEFAULT_MAX_DENEME
    backoff_s: float = 5.0
    max_backoff_s: float = 300.0
    zaman_asimi_s: int = DEFAULT_ZAMAN_ASIMI_S

    def backoff(self, deneme: int) -> float:
        return min(self.backoff_s * (2 ** max(deneme - 1, 0)), self.max_backoff_s)


REGISTRY: dict[str, HandlerSpec] = {}


def job_handler(
    tur: str,
    *,
    max_deneme: int = DEFAULT_MAX_DENEME,
    backoff_s: float = 5.0,
    max_backoff_s: float = 300.0,
    zaman_asimi_s: int = DEFAULT_ZAMAN_ASIMI_S,
    registry: dict[str, HandlerSpec] | None = None,
) -> Callable[[Handler], Handler]:
    if max_deneme < 1:
        raise ValueError("max_deneme en az 1 olmalı")
    if zaman_asimi_s < 1:
        raise ValueError("zaman_asimi_s en az 1 olmalı")
    hedef = REGISTRY if registry is None else registry

    def kaydet(fn: Handler) -> Handler:
        mevcut = hedef.get(tur)
        if mevcut is not None and mevcut.fn is not fn:
            raise ValueError(f"iş türü iki kez kaydedildi: {tur}")
        hedef[tur] = HandlerSpec(tur, fn, max_deneme, backoff_s, max_backoff_s, zaman_asimi_s)
        return fn

    return kaydet


@job_handler("noop", max_deneme=1)
def noop(_ctx: JobContext) -> None:
    return None


def discover(package: str = "tp_core.features") -> list[str]:
    """`<package>.<ad>.jobs` modüllerini içe aktarır (işleyiciler kendini kaydeder).

    İçe aktarma hatası yutulmaz: bozuk bir özellik worker'ı başlatmaz (sessiz eksik işleyici yok).
    """
    try:
        paket = importlib.import_module(package)
    except ModuleNotFoundError:
        return []
    yuklenen: list[str] = []
    for mod in pkgutil.iter_modules(getattr(paket, "__path__", [])):
        if not mod.ispkg:
            continue
        ad = f"{package}.{mod.name}.jobs"
        if importlib.util.find_spec(ad) is None:
            continue
        importlib.import_module(ad)
        yuklenen.append(ad)
    return yuklenen


# ------------------------------------------------------------------------ kuyruk işlemleri


def enqueue(
    conn: Connection,
    tur: str,
    yuk: Mapping[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
    run_after: datetime | None = None,
    max_deneme: int | None = None,
    workflow_id: uuid.UUID | None = None,
    zaman_asimi_s: int | None = None,
    registry: Mapping[str, HandlerSpec] | None = None,
) -> uuid.UUID:
    """İşi kuyruğa ekler (çağıranın işleminde); idempotency anahtarı varsa mevcut işi döndürür.

    `max_deneme`/`zaman_asimi_s` verilmezse ve işleyici bu süreçte kayıtlıysa kayıttaki politika
    satıra yazılır (satır etkin politikayı taşır).
    """
    if max_deneme is not None and max_deneme < 1:
        raise ValueError("max_deneme en az 1 olmalı")
    if zaman_asimi_s is not None and zaman_asimi_s < 1:
        raise ValueError("zaman_asimi_s en az 1 olmalı")
    spec = (REGISTRY if registry is None else registry).get(tur)
    if spec is not None:
        max_deneme = max_deneme if max_deneme is not None else spec.max_deneme
        zaman_asimi_s = zaman_asimi_s if zaman_asimi_s is not None else spec.zaman_asimi_s
    if idempotency_key is not None:
        idempotency_lock(conn, idempotency_key)
    params = {
        "tur": tur,
        "yuk": None if yuk is None else json.dumps(normalize(dict(yuk)), ensure_ascii=False),
        "key": idempotency_key,
        "ra": run_after,
        "md": max_deneme,
        "wf": workflow_id,
        "za": zaman_asimi_s,
    }
    yeni = conn.execute(
        text(
            "INSERT INTO job (tur, yuk, idempotency_key, run_after, max_deneme, workflow_id, "
            "zaman_asimi_s) VALUES (:tur, CAST(:yuk AS jsonb), :key, COALESCE(:ra, now()), :md, "
            ":wf, :za) "
            "ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING "
            "RETURNING id"
        ),
        params,
    ).scalar_one_or_none()
    if yeni is None:
        return conn.execute(
            text("SELECT id FROM job WHERE idempotency_key = :key"), {"key": idempotency_key}
        ).scalar_one()
    conn.execute(text("SELECT pg_notify(:c, :t)"), {"c": NOTIFY_CHANNEL, "t": tur})
    return yeni


def idempotency_lock(conn: Connection, key: str) -> None:
    """Aynı idempotency anahtarı için işlem sonuna kadar süren kilit (yeniden girilebilir)."""
    conn.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:k))"),
        {"ns": IDEMPOTENCY_LOCK_NS, "k": key},
    )


def cancel(conn: Connection, job_id: uuid.UUID) -> bool:
    return (
        conn.execute(
            text(
                "UPDATE job SET durum = 'cancelled', guncelleme = now(), bitis = now() "
                "WHERE id = :id AND durum IN ('queued', 'retry')"
            ),
            {"id": job_id},
        ).rowcount
        == 1
    )


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    tur: str
    yuk: Mapping[str, Any] | None
    deneme: int
    max_deneme: int | None
    workflow_id: uuid.UUID | None
    zaman_asimi_s: int | None = None


# Süreç başına açılış kimliği: konteynerler aynı hostname'i (compose `hostname: core-worker`) ve
# PID 1'i paylaşabilir; `kilitleyen` yalnızca hostname:pid olsaydı ölçeklenen ikinci kopya
# birincinin canlı işlerini "önceki süreç" sanıp bırakırdı.
ACILIS_KIMLIGI = uuid.uuid4().hex[:12]


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{ACILIS_KIMLIGI}"


def claim(conn: Connection, worker: str, turler: list[str] | None = None) -> ClaimedJob | None:
    """Zamanı gelmiş en eski işi `running` yapar (SKIP LOCKED); `turler` ile süzülebilir."""
    filtre = "AND tur = ANY(:turler)" if turler is not None else ""
    row = conn.execute(
        text(
            "UPDATE job SET durum = 'running', deneme = deneme + 1, baslama = now(), "
            "guncelleme = now(), kilitleyen = :w "
            "WHERE id = (SELECT id FROM job WHERE durum IN ('queued', 'retry') "
            f"AND run_after <= now() {filtre} ORDER BY run_after, olusturma LIMIT 1 "
            "FOR UPDATE SKIP LOCKED) "
            "RETURNING id, tur, yuk, deneme, max_deneme, workflow_id, zaman_asimi_s"
        ),
        {"w": worker, "turler": turler},
    ).first()
    if row is None:
        return None
    return ClaimedJob(
        row.id, row.tur, row.yuk, row.deneme, row.max_deneme, row.workflow_id, row.zaman_asimi_s
    )


def complete(conn: Connection, job_id: uuid.UUID, worker: str, sonuc: Any = None) -> bool:
    return (
        conn.execute(
            text(
                "UPDATE job SET durum = 'done', sonuc = CAST(:s AS jsonb), son_hata = NULL, "
                "bitis = now(), guncelleme = now() "
                "WHERE id = :id AND durum = 'running' AND kilitleyen = :w"
            ),
            {
                "id": job_id,
                "w": worker,
                "s": None if sonuc is None else json.dumps(normalize(sonuc), ensure_ascii=False),
            },
        ).rowcount
        == 1
    )


def fail(
    conn: Connection,
    job_id: uuid.UUID,
    worker: str,
    hata: str,
    *,
    retry_in_s: float | None,
) -> str | None:
    """Başarısız denemeyi kaydeder. `retry_in_s` None ise kalıcı `failed`; değilse `retry`."""
    durum = "failed" if retry_in_s is None else "retry"
    sonuc = conn.execute(
        text(
            "UPDATE job SET durum = :d, son_hata = :h, guncelleme = now(), "
            "run_after = CASE WHEN :d = 'retry' THEN now() + make_interval(secs => :r) "
            "ELSE run_after END, "
            "bitis = CASE WHEN :d = 'failed' THEN now() ELSE NULL END "
            "WHERE id = :id AND durum = 'running' AND kilitleyen = :w RETURNING durum"
        ),
        {"d": durum, "h": hata[:4000], "r": retry_in_s or 0.0, "id": job_id, "w": worker},
    ).scalar_one_or_none()
    return sonuc


def heartbeat(conn: Connection, job_id: uuid.UUID, worker: str) -> bool:
    """Çalışan işin nabzı: `guncelleme = now()`. İş artık bu worker'da değilse False."""
    return (
        conn.execute(
            text(
                "UPDATE job SET guncelleme = now() "
                "WHERE id = :id AND durum = 'running' AND kilitleyen = :w"
            ),
            {"id": job_id, "w": worker},
        ).rowcount
        == 1
    )


def _etkin(row: Any, kayit: Mapping[str, HandlerSpec], default_max_deneme: int) -> tuple[int, int]:
    spec = kayit.get(row.tur)
    md = row.max_deneme or (spec.max_deneme if spec else default_max_deneme)
    za = row.zaman_asimi_s or (spec.zaman_asimi_s if spec else DEFAULT_ZAMAN_ASIMI_S)
    return md, za


def _birak(
    conn: Connection, job_id: uuid.UUID, deneme: int, max_deneme: int, hata: str
) -> str | None:
    """`running` işi bırakır: deneme hakkı varsa `retry` (hemen), yoksa `failed` (bitis=now).

    Yazılan durumu döndürür (iş artık `running` değilse None)."""
    durum = "retry" if deneme < max_deneme else "failed"
    return conn.execute(
        text(
            "UPDATE job SET durum = :d, son_hata = :h, run_after = now(), guncelleme = now(), "
            "kilitleyen = NULL, bitis = CASE WHEN :d = 'failed' THEN now() ELSE NULL END "
            "WHERE id = :id AND durum = 'running' RETURNING durum"
        ),
        {"d": durum, "h": hata, "id": job_id},
    ).scalar_one_or_none()


def fail_workflows(conn: Connection, basarisizlar: Mapping[uuid.UUID, str]) -> int:
    """`running` iş akışlarını `failed` yapar (çağıranın işleminde; denetim + olay).

    `basarisizlar`: workflow_id → sebep (işin son hatası). Zaten `running` olmayan (duraklamış,
    insan bekleyen, bitmiş) akışlara dokunmaz. Durum yalnızca `transition()` ile değişir; ORM
    oturumu verilen bağlantının işlemine katılır, commit dış işlemi bitirmez.
    """
    if not basarisizlar:
        return 0
    from sqlalchemy.orm import Session

    from tp_core.models import WorkflowInstance
    from tp_core.workflow.service import SYSTEM, transition

    n = 0
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        for wf_id in sorted(basarisizlar, key=str):  # sabit kilit sırası
            wf = session.get(WorkflowInstance, wf_id, with_for_update=True)
            if wf is None or wf.durum != "running":
                continue
            transition(session, wf, "failed", SYSTEM, "running", sebep=basarisizlar[wf_id][:500])
            n += 1
        session.commit()
    return n


def reap_stale(
    conn: Connection,
    default_max_deneme: int = DEFAULT_MAX_DENEME,
    registry: Mapping[str, HandlerSpec] | None = None,
    *,
    nabiz_zaman_asimi_s: float = NABIZ_ZAMAN_ASIMI_S,
) -> int:
    """Süresi dolan veya nabzı kesilen `running` işleri yeniden denemeye/başarısıza alır.

    Etkin `max_deneme`/`zaman_asimi_s` satırdan, yoksa işleyici kaydından çözülür: ajan işleri
    (`max_deneme=1`) zaman aşımında yeniden denenmez, `failed` olur (§8.1).
    """
    kayit = REGISTRY if registry is None else registry
    rows = conn.execute(
        text(
            "SELECT id, tur, deneme, max_deneme, zaman_asimi_s, workflow_id, "
            "EXTRACT(EPOCH FROM now() - baslama) AS gecen, "
            "EXTRACT(EPOCH FROM now() - guncelleme) AS sessiz "
            "FROM job WHERE durum = 'running' FOR UPDATE SKIP LOCKED"
        )
    ).all()
    n = 0
    akislar: dict[uuid.UUID, str] = {}
    for row in rows:
        md, za = _etkin(row, kayit, default_max_deneme)
        if row.gecen is not None and float(row.gecen) > za:
            hata = "zaman aşımı: iş süresini aştı"
        elif float(row.sessiz) > nabiz_zaman_asimi_s:
            hata = "zaman aşımı: worker yanıt vermedi (nabız kesildi)"
        else:
            continue
        sonuc = _birak(conn, row.id, row.deneme, md, hata)
        _birakma_logu(conn, row, sonuc, hata)
        if sonuc == "failed" and row.workflow_id:
            akislar[row.workflow_id] = hata
        n += 1
    fail_workflows(conn, akislar)
    return n


def _birakma_logu(conn: Connection, row: Any, sonuc: str, hata: str) -> None:
    """Bırakılan işin kimliği, türü, denemesi ve iş akışının nesnesi (operatör hangi gereksinimin
    takıldığını logdan görebilsin)."""
    nesne = None
    if row.workflow_id:
        nesne = conn.execute(
            text("SELECT nesne_turu, nesne_id FROM workflow_instance WHERE id = :w"),
            {"w": row.workflow_id},
        ).first()
    log.warning(
        "iş bırakıldı: job=%s tur=%s deneme=%s sonuc=%s workflow=%s nesne=%s:%s neden=%s",
        row.id,
        row.tur,
        row.deneme,
        sonuc,
        row.workflow_id,
        nesne.nesne_turu if nesne else None,
        nesne.nesne_id if nesne else None,
        hata,
    )


def release_orphans(
    conn: Connection,
    host: str | None = None,
    default_max_deneme: int = DEFAULT_MAX_DENEME,
    registry: Mapping[str, HandlerSpec] | None = None,
    *,
    haric: str | None = None,
    onceki: str | None = None,
    taze_s: float | None = None,
) -> int:
    """Bu makinenin (konteyner) önceki worker sürecinden kalan `running` işleri bırakır.

    Kural `reap_stale` ile aynıdır (ajan işleri `failed`, diğerleri `retry`).

    - `taze_s` None (varsayılan): `host`'un `haric` dışındaki tüm `running` işleri bırakılır
      (teşhis / testler; sahibin öldüğü bilinir).
    - Worker açılışı `taze_s` verir: kilitleyeni tam olarak `onceki` (aynı konteynerin önceki
      süreci, durum dosyasından) olan işler beklemeden bırakılır; aynı hostname'deki diğer işler
      yalnızca nabzı `taze_s`'den eskiyse bırakılır. Böylece aynı hostname'i paylaşan canlı bir
      kopyanın (ör. `--scale core-worker=2`) nabız atan işlerine dokunulmaz.
    """
    kayit = REGISTRY if registry is None else registry
    makine = host or socket.gethostname()
    kosul = "durum = 'running' AND kilitleyen LIKE :p AND kilitleyen IS DISTINCT FROM :haric"
    if taze_s is not None:
        kosul += " AND (kilitleyen = :onceki OR guncelleme < now() - make_interval(secs => :taze))"
    rows = conn.execute(
        text(
            "SELECT id, tur, deneme, max_deneme, zaman_asimi_s, workflow_id FROM job "
            f"WHERE {kosul} FOR UPDATE SKIP LOCKED"
        ),
        {
            "p": makine.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + ":%",
            "haric": haric,
            "onceki": onceki,
            "taze": float(taze_s or 0.0),
        },
    ).all()
    akislar: dict[uuid.UUID, str] = {}
    hata = "worker yeniden başladı; iş yarıda kaldı"
    for row in rows:
        md, _ = _etkin(row, kayit, default_max_deneme)
        sonuc = _birak(conn, row.id, row.deneme, md, hata)
        _birakma_logu(conn, row, sonuc, hata)
        if sonuc == "failed" and row.workflow_id:
            akislar[row.workflow_id] = hata
    fail_workflows(conn, akislar)
    return len(rows)


def start_workflow(
    conn: Connection,
    tur: str,
    baslatan: str,
    *,
    yuk: Mapping[str, Any] | None = None,
    job_tur: str | None = None,
    nesne_turu: str | None = None,
    nesne_id: uuid.UUID | None = None,
    baglam: Mapping[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """`workflow_instance` (running) açar ve ilk işini kuyruğa ekler: (workflow_id, job_id).

    İşin yüküne `workflow_id` eklenir; bütçe ve `ai_call.workflow_id` bu kimliğe bağlanır.
    Aynı `idempotency_key` ile tekrar çağrı mevcut iş akışını döndürür.
    """
    if idempotency_key is not None:
        # Kilit işlem sonuna kadar tutulur: eşzamanlı ikinci çağrı birincinin commit'ini bekler,
        # sonra mevcut işi görür (iki workflow_instance açılmaz).
        idempotency_lock(conn, idempotency_key)
        mevcut = conn.execute(
            text("SELECT workflow_id, id FROM job WHERE idempotency_key = :k"),
            {"k": idempotency_key},
        ).first()
        if mevcut is not None:
            if mevcut.workflow_id is None:
                raise ValueError(
                    f"idempotency anahtarı {idempotency_key!r} bir iş akışına bağlı olmayan "
                    "işe ait; yeni iş akışı açılmadı"
                )
            return mevcut.workflow_id, mevcut.id
    wf_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO workflow_instance (id, tur, baslatan, nesne_turu, nesne_id, baglam) "
            "VALUES (:id, :tur, :b, :nt, :ni, CAST(:bg AS jsonb))"
        ),
        {
            "id": wf_id,
            "tur": tur,
            "b": baslatan,
            "nt": nesne_turu,
            "ni": nesne_id,
            "bg": json.dumps(normalize(dict(baglam or {})), ensure_ascii=False),
        },
    )
    job_yuk = {**dict(yuk or {}), "workflow_id": str(wf_id)}
    job_id = enqueue(
        conn, job_tur or tur, job_yuk, idempotency_key=idempotency_key, workflow_id=wf_id
    )
    sahip = conn.execute(text("SELECT workflow_id FROM job WHERE id = :j"), {"j": job_id})
    if sahip.scalar_one() != wf_id:  # kilit altında olamaz; savunma amaçlı
        raise RuntimeError("iş akışı işi başka bir iş akışına bağlandı")
    conn.execute(
        text("UPDATE workflow_instance SET job_id = :j WHERE id = :id"), {"j": job_id, "id": wf_id}
    )
    append_audit(
        conn,
        baslatan,
        "workflow.started",
        f"workflow_instance:{wf_id}",
        {"tur": tur, "job_id": job_id, "nesne_turu": nesne_turu, "nesne_id": nesne_id},
    )
    return wf_id, job_id


# ------------------------------------------------------------------------- yürütme


@dataclass(frozen=True)
class Sonuc:
    durum: str  # done | retry | failed
    deneme_artisi: int
    hata: str | None = None
    retry_in_s: float | None = None
    deger: Any = None
    butce_asildi: bool = False  # model geçidi tavanı: yeniden denenmez, iş akışı duraklar
    # İşleyici `zaman_asimi_s` içinde bitmedi; iş parçacığı hâlâ asılı olabilir → süreç çıkmalı.
    zaman_asimi: bool = False


def execute(job: ClaimedJob, registry: Mapping[str, HandlerSpec] | None = None) -> Sonuc:
    """Sahiplenilmiş işi yürütür; sonucu döndürür (DB'ye dokunmaz)."""
    kayit = REGISTRY if registry is None else registry
    spec = kayit.get(job.tur)
    if spec is None:
        return Sonuc("failed", 1, f"bilinmeyen iş türü: {job.tur}")
    max_deneme = job.max_deneme or spec.max_deneme
    ctx = JobContext(job.id, job.tur, job.yuk, job.deneme, max_deneme, job.workflow_id)
    try:
        deger = spec.fn(ctx)
    except PermanentJobError as exc:
        return Sonuc("failed", 1, _hata_metni(exc))
    except BudgetExceeded as exc:
        # Yeniden denemek yalnızca aynı tavana çarpar; karar insanındır (TEKNIK-TASARIM §8.8).
        return Sonuc("failed", 1, _hata_metni(exc), butce_asildi=True)
    except Exception as exc:
        if job.deneme < max_deneme:
            return Sonuc("retry", 1, _hata_metni(exc), spec.backoff(job.deneme))
        return Sonuc("failed", 1, _hata_metni(exc))
    return Sonuc("done", 0, deger=deger)


def _hata_metni(exc: BaseException) -> str:
    metin = str(exc).strip()
    return metin or type(exc).__name__


def _nabiz_dongusu(engine: Engine, job_id: uuid.UUID, worker: str, dur: threading.Event) -> None:
    """İş sürerken `HEARTBEAT_S` aralıkla nabız yazar; DB hatası işi durdurmaz (yalnızca log)."""
    while not dur.wait(HEARTBEAT_S):
        try:
            with engine.begin() as conn:
                if not heartbeat(conn, job_id, worker):
                    log.warning("iş %s artık bu worker'da değil (geri alınmış)", job_id)
                    return
        except Exception as exc:
            log.warning("iş %s nabzı yazılamadı: %s", job_id, str(exc).splitlines()[0][:200])


def _akisi_duraklat(engine: Engine, wf_id: uuid.UUID, neden: str) -> None:
    from sqlalchemy.orm import Session

    from tp_core.workflow.budget import pause_for_budget

    with Session(engine) as session, session.begin():
        if pause_for_budget(session, wf_id, neden):
            log.warning("iş akışı %s bütçe aşımıyla duraklatıldı: %s", wf_id, neden)


CANLILIK_ARALIGI_S = 5.0


def etkin_zaman_asimi(job: ClaimedJob, registry: Mapping[str, HandlerSpec] | None = None) -> int:
    spec = (REGISTRY if registry is None else registry).get(job.tur)
    return job.zaman_asimi_s or (spec.zaman_asimi_s if spec else DEFAULT_ZAMAN_ASIMI_S)


def execute_with_timeout(
    job: ClaimedJob,
    registry: Mapping[str, HandlerSpec] | None = None,
    *,
    zaman_asimi_s: float | None = None,
    canli: Callable[[], None] | None = None,
) -> Sonuc:
    """`execute`'u ayrı bir iş parçacığında en fazla `zaman_asimi_s` saniye bekler.

    Süre dolarsa `zaman_asimi=True` olan bir sonuç döner (deneme hakkı varsa `retry`, yoksa
    `failed`; ajan işleri `max_deneme=1` → `failed`). Asılı iş parçacığı durdurulamaz: çağıran
    süreç (worker) bu sonuçtan sonra çıkmalıdır. `canli` bekleme sırasında düzenli çağrılır
    (worker canlılık işareti).
    """
    kayit = REGISTRY if registry is None else registry
    sure = float(zaman_asimi_s if zaman_asimi_s is not None else etkin_zaman_asimi(job, kayit))
    kutu: list[Sonuc] = []
    baglam = contextvars.copy_context()

    def hedef() -> None:
        try:
            kutu.append(baglam.run(execute, job, kayit))
        except BaseException as exc:  # SystemExit vb. iş parçacığını sessizce öldürmesin
            kutu.append(Sonuc("failed", 1, _hata_metni(exc)))

    t = threading.Thread(target=hedef, name=f"is-{job.id}", daemon=True)
    t.start()
    bitis = time.monotonic() + sure
    while t.is_alive():
        kalan = bitis - time.monotonic()
        if kalan <= 0:
            break
        t.join(min(kalan, CANLILIK_ARALIGI_S))
        if canli is not None:
            canli()
    if not t.is_alive() and kutu:
        return kutu[0]
    spec = kayit.get(job.tur)
    md = job.max_deneme or (spec.max_deneme if spec else DEFAULT_MAX_DENEME)
    hata = f"zaman aşımı: iş {sure:g} sn içinde bitmedi"
    if job.deneme < md and spec is not None:
        return Sonuc("retry", 1, hata, spec.backoff(job.deneme), zaman_asimi=True)
    return Sonuc("failed", 1, hata, zaman_asimi=True)


def process_one(
    engine: Engine,
    worker: str | None = None,
    registry: Mapping[str, HandlerSpec] | None = None,
    *,
    canli: Callable[[], None] | None = None,
) -> Sonuc | None:
    """Bir iş sahiplenir, `zaman_asimi_s` sınırıyla yürütür, sonucu yazar. İş yoksa None.

    İş `failed` biterse bağlı iş akışı aynı işlemde `failed` olur (bütçe aşımında `paused`).
    Sonuç `zaman_asimi=True` ise işleyici iş parçacığı asılı kalmıştır; çağıran çıkmalıdır.
    """
    w = worker or worker_id()
    with engine.begin() as conn:
        job = claim(conn, w)
    if job is None:
        return None
    dur = threading.Event()
    nabiz = threading.Thread(
        target=_nabiz_dongusu, args=(engine, job.id, w, dur), name=f"nabiz-{job.id}", daemon=True
    )
    nabiz.start()
    try:
        sonuc = execute_with_timeout(job, registry, canli=canli)
    finally:
        dur.set()
        nabiz.join(timeout=5)
    with engine.begin() as conn:
        if sonuc.durum == "done":
            yazildi = complete(conn, job.id, w, sonuc.deger)
        else:
            yazilan = fail(conn, job.id, w, sonuc.hata or "", retry_in_s=sonuc.retry_in_s)
            yazildi = yazilan is not None
            if yazilan == "failed" and job.workflow_id is not None and not sonuc.butce_asildi:
                fail_workflows(conn, {job.workflow_id: sonuc.hata or "iş başarısız"})
    if yazildi and sonuc.butce_asildi and job.workflow_id is not None:
        _akisi_duraklat(engine, job.workflow_id, sonuc.hata or "bütçe aşıldı")
    if not yazildi:
        log.warning("iş %s sonucu yazılamadı (zaman aşımıyla geri alınmış olabilir)", job.id)
    elif sonuc.hata:
        log.warning("iş %s (%s) %s: %s", job.id, job.tur, sonuc.durum, sonuc.hata)
    else:
        log.info("iş %s (%s) tamamlandı", job.id, job.tur)
    return sonuc
