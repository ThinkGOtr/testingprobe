"""Platform testleri gerçek Postgres'e karşı koşar.

Oturum başına tek kullanımlık bir `postgres:16-alpine` konteyneri (benzersiz ad, yalnızca
127.0.0.1'de rastgele port) başlatılır; compose'daki gibi `tp_owner`/`tp_app` rolleri kurulur,
`tp_template` veritabanı `alembic upgrade head` ile migrate edilir. Testler bu şablondan kopyalanan
veritabanlarını kullanır ve konteyner oturum sonunda silinir.

Docker yoksa testler atlanır; `TP_TEST_REQUIRE_DB=1` ise atlamak yerine hata verir.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from tp_core import db as tp_db
from tp_core.config import get_settings

PG_IMAGE = (
    "postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab"
)
CORE_DIR = Path(__file__).resolve().parents[2]
SESSION_SECRET = "test-session-secret-" + "x" * 32


def _bos_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _atla_veya_hata(neden: str) -> None:
    if os.environ.get("TP_TEST_REQUIRE_DB") == "1":
        pytest.fail(neden)
    pytest.skip(neden)


@dataclass
class PgServer:
    port: int
    super_pw: str
    owner_pw: str
    app_pw: str

    def url(self, user: str, dbname: str, driver: str = "postgresql+psycopg") -> str:
        pw = {"postgres": self.super_pw, "tp_owner": self.owner_pw, "tp_app": self.app_pw}[user]
        return f"{driver}://{user}:{pw}@127.0.0.1:{self.port}/{dbname}"

    def super_conn(self, dbname: str = "postgres") -> psycopg.Connection:
        return psycopg.connect(self.url("postgres", dbname, "postgresql"), autocommit=True)

    def create_db(self, prefix: str = "tp") -> str:
        ad = f"{prefix}_{uuid.uuid4().hex[:10]}"
        with self.super_conn() as c:
            c.execute(f'CREATE DATABASE "{ad}" TEMPLATE tp_template OWNER tp_owner')
            c.execute(f'REVOKE CONNECT, TEMPORARY ON DATABASE "{ad}" FROM PUBLIC')
            c.execute(f'GRANT CONNECT ON DATABASE "{ad}" TO tp_app')
        return ad

    def create_empty_db(self) -> str:
        ad = f"tp_empty_{uuid.uuid4().hex[:10]}"
        with self.super_conn() as c:
            c.execute(f'CREATE DATABASE "{ad}" OWNER tp_owner')
            c.execute(f'GRANT CONNECT ON DATABASE "{ad}" TO tp_app')
        return ad


def alembic_config() -> Config:
    # Dosyasız Config: env.py fileConfig ile pytest log yapılandırmasını ezmesin.
    cfg = Config()
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))
    return cfg


def run_alembic(url: str, hedef: str, yon: str = "upgrade") -> None:
    eski = os.environ.get("TP_DATABASE_URL")
    os.environ["TP_DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        getattr(command, yon)(alembic_config(), hedef)
    finally:
        if eski is None:
            os.environ.pop("TP_DATABASE_URL", None)
        else:
            os.environ["TP_DATABASE_URL"] = eski
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def pg() -> Iterator[PgServer]:
    if shutil.which("docker") is None:
        _atla_veya_hata("docker bulunamadı")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        _atla_veya_hata("docker çalışmıyor")
    ad = f"tp-test-pg-{uuid.uuid4().hex[:8]}"
    srv = PgServer(_bos_port(), secrets.token_hex(12), secrets.token_hex(12), secrets.token_hex(12))
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", ad,
            "-e", f"POSTGRES_PASSWORD={srv.super_pw}",
            "-p", f"127.0.0.1:{srv.port}:5432",
            "--tmpfs", "/var/lib/postgresql/data",
            PG_IMAGE,
            "-c", "fsync=off", "-c", "synchronous_commit=off", "-c", "full_page_writes=off",
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    try:
        son_hata: Exception | None = None
        for _ in range(120):
            try:
                with srv.super_conn() as c:
                    c.execute("SELECT 1")
                break
            except psycopg.OperationalError as exc:
                son_hata = exc
                time.sleep(0.5)
        else:
            raise RuntimeError(f"test postgres hazır olmadı: {son_hata}")
        with srv.super_conn() as c:
            c.execute(f"CREATE ROLE tp_owner LOGIN PASSWORD '{srv.owner_pw}'")
            c.execute(f"CREATE ROLE tp_app LOGIN PASSWORD '{srv.app_pw}'")
            c.execute("CREATE DATABASE tp_template OWNER tp_owner")
            c.execute("REVOKE CONNECT, TEMPORARY ON DATABASE tp_template FROM PUBLIC")
            c.execute("GRANT CONNECT ON DATABASE tp_template TO tp_app")
        run_alembic(srv.url("tp_owner", "tp_template"), "head")
        yield srv
    finally:
        subprocess.run(["docker", "rm", "-f", ad], capture_output=True)


@dataclass
class Db:
    name: str
    app_url: str
    owner_url: str
    srv: PgServer

    def engine(self, user: str = "tp_app") -> Engine:
        url = self.app_url if user == "tp_app" else self.owner_url
        return create_engine(url, pool_size=5, max_overflow=10)


def _uygula_env(db: Db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_DATABASE_URL", db.app_url)
    monkeypatch.setenv("TP_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("SEED_USER_PASSWORD", "seed-parola-123")
    get_settings.cache_clear()
    tp_db.get_engine.cache_clear()


@pytest.fixture
def db(pg: PgServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[Db]:
    """Test başına şablondan kopyalanmış temiz veritabanı; varsayılan motor ona bağlanır."""
    ad = pg.create_db()
    d = Db(ad, pg.url("tp_app", ad), pg.url("tp_owner", ad), pg)
    _uygula_env(d, monkeypatch)
    try:
        yield d
    finally:
        with contextlib.suppress(Exception):
            tp_db.get_engine().dispose()
        get_settings.cache_clear()
        tp_db.get_engine.cache_clear()
        with pg.super_conn() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')


@pytest.fixture
def engine(db: Db) -> Engine:
    return tp_db.get_engine()


# ------------------------------------------------------------------ yardımcılar

PAROLA = "Parola-123!"


@pytest.fixture
def make_user(engine: Engine):
    from tp_core.auth.passwords import hash_password
    from tp_core.workflow.service import Principal

    hashler: dict[str, str] = {}

    def _make(rol: str = "analyst", ad: str | None = None, parola: str = PAROLA) -> Principal:
        ad = ad or f"{rol}_{uuid.uuid4().hex[:6]}"
        uid = uuid.uuid4()
        if parola not in hashler:
            hashler[parola] = hash_password(parola)
        with engine.begin() as c:
            c.exec_driver_sql(
                "INSERT INTO app_user (id, kullanici_adi, rol, parola_hash) "
                "VALUES (%s, %s, %s, %s)",
                (uid, ad, rol, hashler[parola]),
            )
        return Principal(uid, ad, rol)

    return _make


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        yield s
        s.rollback()


@pytest.fixture
def sunucu(db: Db) -> Iterator[str]:
    """Gerçek uvicorn üstünde core-api (SSE ve eşzamanlılık testleri için)."""
    from tp_core.api.main import create_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        t.join(timeout=10)


@pytest.fixture(autouse=True)
def _canli_model_anahtari_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Geliştiricinin kabuğundaki `ANTHROPIC_API_KEY` hiçbir birim testinde görünmez (plan §13):
    hiçbir test yanlışlıkla canlı model yoluna giremez. Anahtar isteyen test kendi sahte değerini
    `monkeypatch.setenv` ile verir (bu fikstür ondan önce çalışır)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _kural_yeniden_isteme_kapali(monkeypatch: pytest.MonkeyPatch) -> None:
    """Birim testleri bilerek tutarsız sahte model çıktısı kullanır (uyarı / onay engeli akışları);
    kural ihlalinde yeniden isteme (011) senaryoyu tüketmesin. Mekanizmanın kendisi
    `test_kural_yeniden_isteme.py`'de açıkça açılarak sınanır."""
    monkeypatch.setenv("TP_KURAL_YENIDEN_ISTEME", "off")


@pytest.fixture(autouse=True)
def _red_tekrar_suzgeci_temiz() -> None:
    """`authz.denied` tekrar süzgeci süreç içidir: her test temiz başlar (aynı kullanıcı/yol)."""
    from tp_core.auth.yetki import red_onbellegini_temizle

    red_onbellegini_temizle()


@pytest.fixture(autouse=True)
def _jira_sim_onbellegi_temiz() -> None:
    """`ayarlar.jira_sim_mi` sonucu süreç içinde önbelleklenir (olumsuz sonuç `SIM_NEGATIF_S`):
    önceki bir testin Jira'sız ortamı sonraki testin tetik varsayılanını (`acik`) etkilemesin
    (dev birleştirmesinde test sırası değişince görüldü)."""
    from tp_core.features.otomasyon.ayarlar import sim_onbellegini_temizle

    sim_onbellegini_temizle()


# ------------------------------------------------- çok proje (TP-COK-PROJE-PLANI §2.4, §7 Ş0)

PROJE_A = "test-a"
PROJE_B = "test-b"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "sql_denetimi_yok: proje kapsamı SQL yakalama denetimini bu testte kapat"
    )


def _projeleri_kaydet(request: pytest.FixtureRequest, pidler: tuple[str, ...]) -> None:
    """DB'li testte projeleri `tp_proje`'ye kaydeder (DB'siz testte etkisiz)."""
    if "db" not in request.fixturenames:
        return
    from tp_core.proje import proje_kaydet

    eng: Engine = request.getfixturevalue("engine")
    with eng.begin() as c:
        for pid in pidler:
            proje_kaydet(c, pid, kod=pid.upper(), ad=f"Test {pid}", kaynak="env")


@pytest.fixture
def proje(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """`test-a` projesinin bağlamı (kaynak `test`); `TP_HOME_PROJECT=test-a` olduğundan
    `ayar()` env'e düşer. DB'li testte proje `tp_proje`'ye de kaydedilir."""
    from tp_core.proje import proje_icinde

    monkeypatch.setenv("TP_HOME_PROJECT", PROJE_A)
    _projeleri_kaydet(request, (PROJE_A,))
    with proje_icinde(PROJE_A, kaynak="test") as b:
        yield b


@pytest.fixture
def iki_proje(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """`("test-a", "test-b")`; varsayılan proje A. Bağlam kurmaz: test her proje için
    `proje_icinde(pid, kaynak="test")` ile aynı tohumu yazar ve okur."""
    monkeypatch.setenv("TP_HOME_PROJECT", PROJE_A)
    _projeleri_kaydet(request, (PROJE_A, PROJE_B))
    return (PROJE_A, PROJE_B)


@pytest.fixture
def proje_ayar() -> Iterator[Any]:
    """`proje_ayar(JIRA_PROJECT="X")` bağlamdaki (yoksa varsayılan) projeye ayar enjekte eder;
    `proje_ayar(pid="test-b", ...)` başka projeye. `None` değer ayarı kaldırır. Test sonunda
    temizlenir; istemci önbelleği sıfırlanır."""
    from tp_core.proje import ayar, istemciler

    def _ayarla(pid: str | None = None, **degerler: str | None) -> None:
        ayar._ust_ayarla(pid if pid is not None else ayar._pid(None), degerler)
        istemciler.sifirla()

    yield _ayarla
    ayar._ust_temizle()
    istemciler.sifirla()


_FLUSH_SURUYOR: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "tp_test_flush_suruyor", default=False
)


@pytest.fixture(autouse=True)
def sql_denetimi(request: pytest.FixtureRequest) -> Iterator[list[str]]:
    """DB'li testlerde: proje bağlamı varken kapsamlı tabloya dokunan ve `project_id` içermeyen
    her SQL testi düşürür. ORM flush DML'i (yüklenmiş nesnenin PK ile UPDATE/DELETE'i; yükleme
    zaten korumalı) ve `tum_projeler=True` kaçışı muaf. `@pytest.mark.sql_denetimi_yok` kapatır."""
    ihlaller: list[str] = []
    if "db" not in request.fixturenames or request.node.get_closest_marker("sql_denetimi_yok"):
        yield ihlaller
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session as _Session

    from tp_core.proje import varsa
    from tp_core.proje.orm import TUM_PROJELER, kapsamli_tablolar

    tablolar = kapsamli_tablolar()
    if not tablolar:
        yield ihlaller
        return
    adlar = "|".join(sorted(map(re.escape, tablolar), key=len, reverse=True))
    desen = re.compile(rf"\b(?:FROM|JOIN|INTO|UPDATE)\s+\"?(?:{adlar})\b", re.IGNORECASE)

    def _sql(conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: bool) -> None:
        if varsa() is None or _FLUSH_SURUYOR.get():
            return
        if ctx is not None and ctx.execution_options.get(TUM_PROJELER):
            return
        if desen.search(statement) and "project_id" not in statement:
            ihlaller.append(" ".join(statement.split())[:200])

    def _flush_bas(*_a: Any) -> None:
        _FLUSH_SURUYOR.set(True)

    def _flush_bitti(*_a: Any) -> None:
        _FLUSH_SURUYOR.set(False)

    dinleyiciler = [
        (Engine, "before_cursor_execute", _sql),
        (_Session, "before_flush", _flush_bas),
        (_Session, "after_flush_postexec", _flush_bitti),
        (_Session, "after_rollback", _flush_bitti),
    ]
    for hedef, ad, fn in dinleyiciler:
        event.listen(hedef, ad, fn)
    try:
        yield ihlaller
    finally:
        for hedef, ad, fn in dinleyiciler:
            event.remove(hedef, ad, fn)
        _FLUSH_SURUYOR.set(False)
    if ihlaller:
        pytest.fail("project_id içermeyen proje kapsamlı SQL:\n" + "\n".join(ihlaller))
