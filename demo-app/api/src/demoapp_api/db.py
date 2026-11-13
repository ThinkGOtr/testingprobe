"""Veritabanı bağlantısı ve şema kurulumu.

`DEMOAPP_DATABASE_URL` Postgres (compose) ya da SQLite (CI / test-runner `webServer`) olabilir.
Engine tembel oluşturulur; DB yokken uygulama yine açılır, `/health` 503 döner ve şema ilk
istekte yeniden denenir.
"""

import logging
import os
import threading
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from demoapp_api.models import Base

log = logging.getLogger("demoapp_api.db")

# Salt okuma rolü (tutarlılık denetimi). bayi'de yalnızca parola özeti dışındaki kolonlar açılır.
RO_ROLE = "demoapp_ro"
RO_TABLES = ("urun", "kampanya", "ayar")
RO_BAYI_COLUMNS = ("id", "kullanici_adi", "ad", "kredi_limiti", "olusturma")


def _sqlite_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - sürücü kancası
        # pysqlite'ın kendi BEGIN yönetimini kapat; aşağıda BEGIN IMMEDIATE kullanılır
        # (paralel test işçilerinde "database is locked" yükseltme kilitlenmesini önler).
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        if ":memory:" not in url:
            cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):  # pragma: no cover - sürücü kancası
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = os.environ.get("DEMOAPP_DATABASE_URL")
    if not url:
        raise RuntimeError("DEMOAPP_DATABASE_URL tanımlı değil")
    if url.startswith("sqlite"):
        return _sqlite_engine(url)
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=4,
        connect_args={"connect_timeout": 2},
    )


@lru_cache(maxsize=1)
def _sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def check_db() -> str:
    """'ok' ya da 'error: <neden>' döner; asla istisna fırlatmaz."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return f"error: {reason[:200]}"


def grant_readonly(conn) -> bool:
    """Postgres'te salt okuma rolüne izin listeli tablolarda SELECT verir. Sipariş/sepet/oturum
    tablolarına izin verilmez. Rol yoksa (ör. eski volume) sessizce atlar; True = verildi."""
    if conn.dialect.name != "postgresql":
        return False
    exists = conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": RO_ROLE}
    ).scalar()
    if not exists:
        log.warning("%s rolü yok; salt okuma yetkileri verilmedi", RO_ROLE)
        return False
    # GRANT/REVOKE tanımlayıcıları bağlama parametresi alamaz; buradaki tüm adlar modül sabitidir
    # (kullanıcı girdisi yok), bu yüzden semgrep'in avoid-sqlalchemy-text kuralı bilerek susturulur.
    komutlar = (
        f"GRANT SELECT ON {', '.join(RO_TABLES)} TO {RO_ROLE}",
        f"REVOKE ALL ON bayi FROM {RO_ROLE}",
        f"GRANT SELECT ({', '.join(RO_BAYI_COLUMNS)}) ON bayi TO {RO_ROLE}",
    )
    for komut in komutlar:
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        conn.execute(text(komut))
    return True


# `create_all` var olan tabloya kolon eklemez (migrasyon yok); sonradan eklenen kolonlar burada.
# (tablo, kolon, DDL tipi) — adlar modül sabitidir, kullanıcı girdisi değildir.
SONRADAN_EKLENEN_KOLONLAR = (("test_kirilma", "hata", "VARCHAR(40)"),)


def kolonlari_tamamla(engine: Engine) -> list[str]:
    """Eski şemayla kurulmuş veritabanına eksik kolonları ekler (SQLite + Postgres, idempotent).

    Eklenen "tablo.kolon" adlarını döndürür. Kolonlar null kabul eder: var olan satırlar ve eski
    sürümle yazan süreçler bozulmaz. Salt okuma rolünün yetkileri tablo/kolon listesiyle verilir
    (`grant_readonly`); `test_kirilma` o listede olmadığından yetkiler değişmez."""
    eklenen: list[str] = []
    for tablo, kolon, tip in SONRADAN_EKLENEN_KOLONLAR:
        if kolon in {c["name"] for c in inspect(engine).get_columns(tablo)}:
            continue
        # Postgres: eşzamanlı açılan iki süreç için IF NOT EXISTS; SQLite bu sözdizimini bilmez.
        kosul = "IF NOT EXISTS " if engine.dialect.name == "postgresql" else ""
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        komut = text(f"ALTER TABLE {tablo} ADD COLUMN {kosul}{kolon} {tip}")
        try:
            with engine.begin() as conn:
                conn.execute(komut)
        except DBAPIError:
            # Başka bir süreç aynı anda eklemiş olabilir (SQLite: "duplicate column name").
            if kolon not in {c["name"] for c in inspect(engine).get_columns(tablo)}:
                raise
        else:
            eklenen.append(f"{tablo}.{kolon}")
    return eklenen


_init_lock = threading.Lock()
_initialized = False


def init_db() -> None:
    """Şema + yetkiler + deterministik tohum verisi. Tekrar çağrılması güvenlidir."""
    from demoapp_api import seed  # döngüsel içe aktarmayı önler

    engine = get_engine()
    Base.metadata.create_all(engine)
    kolonlari_tamamla(engine)
    with engine.begin() as conn:
        grant_readonly(conn)
    with session_scope() as s:
        seed.seed(s)


def ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if not _initialized:
            init_db()
            _initialized = True


def reset_initialized() -> None:
    """Testler için: bir sonraki istekte şemayı yeniden kur."""
    global _initialized
    with _init_lock:
        _initialized = False


class _Scope:
    def __init__(self) -> None:
        self.session = _sessionmaker()()

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()


def session_scope() -> _Scope:
    return _Scope()


def get_session() -> Iterator[Session]:
    """FastAPI bağımlılığı: istek başına bir oturum; başarıda commit, hatada rollback."""
    ensure_initialized()
    with session_scope() as s:
        yield s


def clear_caches() -> None:
    _sessionmaker.cache_clear()
    get_engine.cache_clear()
    reset_initialized()
