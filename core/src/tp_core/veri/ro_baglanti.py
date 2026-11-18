"""Salt okuma test verisi bağlantısı: tanım çözümü + lehçe başına sürücü (çoklu DB sözleşmesi).

Desteklenen türler ve sürücüler (core imajında derleme gerektirmez):

| tür          | sürücü                     | sqlglot lehçesi | varsayılan port |
|--------------|----------------------------|-----------------|-----------------|
| `postgresql` | psycopg                    | `postgres`      | 5432            |
| `mysql`      | PyMySQL (saf Python)       | `mysql`         | 3306            |
| `mssql`      | python-tds (saf Python)    | `tsql`          | 1433            |
| `oracle`     | python-oracledb (thin kip) | `oracle`        | 1521            |

Tanım çözümü (`cozumle`) tek yerdedir: `DEMOAPP_RO_DATABASE_URL` doluysa ondan (tür önekten
çıkar; bugünkü kurulumlar değişmeden çalışır), değilse ayrı alanlardan (`TP_RO_DB_TYPE`, `_HOST`,
`_PORT`, `_NAME`, `_USER`, `_PASSWORD`). Parola hiçbir zaman `repr`/log/hata metnine girmez.

Güvenlik iki katmandır; bu modül birinci katmanı (oturum) uygular, ikincisi (sorgu muhafızı:
tek SELECT, izin listesi) `features.requirements.sqlguard`'dadır ve hedef lehçede ayrıştırır:

- PostgreSQL: `conn.read_only` (BEGIN READ ONLY) + `SET LOCAL statement_timeout`.
- MySQL/MariaDB: `SET SESSION MAX_EXECUTION_TIME` (MariaDB: `max_statement_time`) +
  `START TRANSACTION READ ONLY`; okuma zaman aşımı yedek sınırdır.
- Oracle: `SET TRANSACTION READ ONLY` + `call_timeout`.
- SQL Server: oturum düzeyinde salt okuma işlemi yoktur; `ApplicationIntent=ReadOnly`
  (`readonly=True`), yalnız SELECT yetkili kullanıcı (Home "Bağlantıyı test et" denetler),
  `SET LOCK_TIMEOUT`, sorgu zaman aşımı ve her oturumun sonunda koşulsuz `ROLLBACK`.

Her oturum işlem içindedir (autocommit kapalı) ve sonunda geri alınır.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

TURLER: tuple[str, ...] = ("postgresql", "mysql", "mssql", "oracle")
ETIKETLER: dict[str, str] = {
    "postgresql": "PostgreSQL",
    "mysql": "MySQL / MariaDB",
    "mssql": "Microsoft SQL Server",
    "oracle": "Oracle",
}
SQLGLOT_LEHCE: dict[str, str] = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "mssql": "tsql",
    "oracle": "oracle",
}
VARSAYILAN_PORT: dict[str, int] = {"postgresql": 5432, "mysql": 3306, "mssql": 1433, "oracle": 1521}

# Bağlantı dizesi önekleri (SQLAlchemy biçimleri dahil: `postgresql+psycopg://` …).
_ONEK_TUR: dict[str, str] = {
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "mysql": "mysql",
    "mariadb": "mysql",
    "mssql": "mssql",
    "sqlserver": "mssql",
    "oracle": "oracle",
}

# Yalnız yapılandırma eksikliğinde gösterilen ad (eski metin korunur).
YAPILANDIRMA_YOK = "Veri erişimi yapılandırılmamış (DEMOAPP_RO_DATABASE_URL tanımlı değil)"

ZAMAN = "zaman_asimi"
YETKI = "yetki"


class BaglantiHatasi(RuntimeError):
    """Bağlantı tanımı geçersiz ya da veritabanına bağlanılamadı (metin maskelidir)."""


class SorguHatasi(RuntimeError):
    """Sorgu çalıştırılamadı. `tur`: `zaman_asimi` | `yetki` | None (metin maskelidir)."""

    def __init__(self, mesaj: str, tur: str | None = None) -> None:
        super().__init__(mesaj)
        self.tur = tur


@dataclass(frozen=True)
class BaglantiTanimi:
    """Çözülmüş bağlantı. `ham_url`: PostgreSQL bağlantı dizesi olduğu gibi (sslmode vb.
    korunur)."""

    tur: str
    host: str = ""
    port: int | None = None
    veritabani: str = ""
    kullanici: str = ""
    parola: str = field(default="", repr=False)
    ham_url: str | None = field(default=None, repr=False)
    secenekler: Mapping[str, str] = field(default_factory=dict)

    @property
    def lehce(self) -> str:
        return SQLGLOT_LEHCE[self.tur]

    @property
    def etiket(self) -> str:
        return ETIKETLER[self.tur]

    @property
    def etkin_port(self) -> int:
        return self.port or VARSAYILAN_PORT[self.tur]

    def maskele(self, metin: str) -> str:
        """Hata metninden parola ve bağlantı dizesindeki kimlik bilgisini çıkarır."""
        return maskele(metin, self.parola)


_URL_KIMLIK = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^@/\s]*@")
_PAROLA_ALANI = re.compile(r"(?i)(password|pwd)\s*=\s*('[^']*'|\"[^\"]*\"|[^\s;]+)")


def maskele(metin: str, *sirlar: str | None) -> str:
    out = str(metin)
    for s in sirlar:
        if s:
            out = out.replace(s, "***")
    out = _URL_KIMLIK.sub(r"\1***@", out)
    return _PAROLA_ALANI.sub(r"\1=***", out)


def tur_onekten(url: str) -> str | None:
    """`postgresql+psycopg://…` → `postgresql`; desteklenmeyen önek → None."""
    sema = url.split("://", 1)[0].lower() if "://" in url else ""
    return _ONEK_TUR.get(sema.split("+", 1)[0])


def url_coz(url: str) -> BaglantiTanimi:
    tur = tur_onekten(url)
    if tur is None:
        raise BaglantiHatasi(
            "Desteklenmeyen bağlantı dizesi öneki (postgresql://, mysql://, mariadb://, mssql://, "
            "sqlserver://, oracle://)"
        )
    p = urlsplit(url)
    try:
        port = p.port
    except ValueError as exc:
        raise BaglantiHatasi("Bağlantı dizesinde geçersiz port") from exc
    secenekler = dict(parse_qsl(p.query))
    ad = unquote(p.path.lstrip("/"))
    if tur == "oracle" and not ad:
        ad = secenekler.pop("service_name", "")
    ham = None
    if tur == "postgresql":
        sema = url.split("://", 1)[0]
        ham = "postgresql://" + url[len(sema) + 3 :]
    return BaglantiTanimi(
        tur=tur,
        host=p.hostname or "",
        port=port,
        veritabani=ad,
        kullanici=unquote(p.username or ""),
        parola=unquote(p.password or ""),
        ham_url=ham,
        secenekler=secenekler,
    )


def cozumle(
    *,
    url: str | None = None,
    tur: str | None = None,
    host: str | None = None,
    port: int | str | None = None,
    ad: str | None = None,
    kullanici: str | None = None,
    parola: str | None = None,
) -> BaglantiTanimi | None:
    """Bağlantı dizesi doluysa o (ayrı alanların önüne geçer); değilse ayrı alanlar; ikisi de
    yoksa None (veri erişimi yapılandırılmamış)."""
    if url and url.strip():
        return url_coz(url.strip())
    t = (tur or "").strip().lower()
    if not t:
        return None
    t = _ONEK_TUR.get(t, t)
    if t not in TURLER:
        raise BaglantiHatasi(f"Desteklenmeyen veritabanı türü: {tur}")
    p: int | None = None
    if port not in (None, ""):
        try:
            p = int(str(port).strip())
        except ValueError as exc:
            raise BaglantiHatasi("TP_RO_DB_PORT_NO sayı olmalı") from exc
        if not 1 <= p <= 65535:
            raise BaglantiHatasi("TP_RO_DB_PORT_NO 1–65535 aralığında olmalı")
    eksik = [
        n
        for n, v in (("TP_RO_DB_HOST", host), ("TP_RO_DB_NAME", ad), ("TP_RO_DB_USER", kullanici))
        if not (v or "").strip()
    ]
    if eksik:
        raise BaglantiHatasi("Veritabanı bağlantısı eksik: " + ", ".join(eksik))
    return BaglantiTanimi(
        tur=t,
        host=(host or "").strip(),
        port=p,
        veritabani=(ad or "").strip(),
        kullanici=(kullanici or "").strip(),
        parola=parola or "",
    )


# ------------------------------------------------------------------ oturum


Satir = tuple[Any, ...]


@dataclass
class _Surucu:
    """Bir türün sürücü işlemleri (testlerde sahte bağlantıyla değiştirilir)."""

    baglan: Callable[[BaglantiTanimi, float, int], Any]
    hazirla: Callable[[Any, Any, int], None]
    hata_turu: Callable[[BaseException], str | None]
    hata_siniflari: Callable[[], tuple[type[BaseException], ...]]
    kolon_adi: Callable[[Any], str] = field(default=lambda d: str(d[0]))


class RoOturum:
    """Tek salt okuma işlemi. `calistir` sorguyu çalıştırır; `kapat` geri alır ve kapatır."""

    def __init__(self, tanim: BaglantiTanimi, surucu: _Surucu, conn: Any, timeout_ms: int) -> None:
        self.tanim = tanim
        self._s = surucu
        self._conn = conn
        self._cur = conn.cursor()
        surucu.hazirla(conn, self._cur, timeout_ms)

    @property
    def lehce(self) -> str:
        return self.tanim.lehce

    def calistir(self, sql: str, *, en_fazla: int | None = None) -> tuple[list[str], list[Satir]]:
        """Parametresiz çalıştırır (metin olduğu gibi gider). `en_fazla` verilirse o kadar satır."""
        try:
            self._cur.execute(sql)
            kolonlar = [self._s.kolon_adi(d) for d in self._cur.description or []]
            ham = self._cur.fetchmany(en_fazla) if en_fazla is not None else self._cur.fetchall()
        except self._s.hata_siniflari() as exc:
            raise SorguHatasi(self.tanim.maskele(ilk_satir(exc)), self._s.hata_turu(exc)) from exc
        return kolonlar, [tuple(r) for r in ham]

    def kapat(self) -> None:
        try:
            self._conn.rollback()
        except Exception:  # bağlantı kopmuşsa geri alma zaten olmuştur
            pass
        finally:
            with suppress(Exception):
                self._conn.close()


def ilk_satir(exc: BaseException) -> str:
    metin = str(exc).strip()
    return metin.splitlines()[0][:200] if metin else type(exc).__name__


@contextmanager
def oturum(
    tanim: BaglantiTanimi, *, connect_timeout_s: float = 3, timeout_ms: int = 5000
) -> Iterator[RoOturum]:
    surucu = surucu_al(tanim.tur)
    try:
        conn = surucu.baglan(tanim, connect_timeout_s, timeout_ms)
    except (*surucu.hata_siniflari(), OSError) as exc:
        raise BaglantiHatasi(
            f"Veritabanına bağlanılamadı: {tanim.maskele(ilk_satir(exc))}"
        ) from exc
    try:
        o = RoOturum(tanim, surucu, conn, timeout_ms)
    except (*surucu.hata_siniflari(), OSError) as exc:
        with suppress(Exception):
            conn.close()
        raise BaglantiHatasi(
            f"Salt okuma oturumu kurulamadı: {tanim.maskele(ilk_satir(exc))}"
        ) from exc
    try:
        yield o
    finally:
        o.kapat()


# ------------------------------------------------------------------ PostgreSQL


def _pg_baglan(t: BaglantiTanimi, connect_timeout_s: float, _timeout_ms: int) -> Any:
    import psycopg

    zaman = max(1, int(connect_timeout_s))
    if t.ham_url:
        conn = psycopg.connect(t.ham_url, connect_timeout=zaman, autocommit=False)
    else:
        conn = psycopg.connect(
            host=t.host,
            port=t.etkin_port,
            dbname=t.veritabani,
            user=t.kullanici,
            password=t.parola,
            connect_timeout=zaman,
            autocommit=False,
        )
    conn.read_only = True  # BEGIN READ ONLY
    return conn


def _pg_hazirla(_conn: Any, cur: Any, timeout_ms: int) -> None:
    cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")


def _pg_hata_turu(exc: BaseException) -> str | None:
    import psycopg

    if isinstance(exc, psycopg.errors.QueryCanceled):
        return ZAMAN
    if isinstance(exc, psycopg.errors.InsufficientPrivilege):
        return YETKI
    return None


def _pg_siniflar() -> tuple[type[BaseException], ...]:
    import psycopg

    return (psycopg.Error,)


# ------------------------------------------------------------------ MySQL / MariaDB

_MYSQL_ZAMAN = frozenset({3024, 1317, 1969, 2013})  # MAX_EXECUTION_TIME, kesildi, MariaDB, okuma
_MYSQL_YETKI = frozenset({1142, 1143, 1044, 1227})


def _mysql_baglan(t: BaglantiTanimi, connect_timeout_s: float, timeout_ms: int) -> Any:
    import pymysql

    ssl = None
    if t.secenekler.get("ssl", "").lower() in ("1", "true", "required") or t.secenekler.get(
        "ssl_mode", ""
    ).lower() in ("required", "verify_ca", "verify_identity"):
        ssl = {"ssl": {}}
    return pymysql.connect(
        host=t.host,
        port=t.etkin_port,
        user=t.kullanici,
        password=t.parola,
        database=t.veritabani,
        connect_timeout=max(1, int(connect_timeout_s)),
        read_timeout=max(1, int(timeout_ms / 1000) + 5),
        write_timeout=max(1, int(timeout_ms / 1000) + 5),
        autocommit=False,
        charset="utf8mb4",
        ssl=ssl,
    )


def _mysql_hazirla(_conn: Any, cur: Any, timeout_ms: int) -> None:
    import pymysql

    try:
        cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_ms)}")
    except pymysql.err.MySQLError:
        # MariaDB: değişken adı ve birimi farklı (saniye).
        cur.execute(f"SET SESSION max_statement_time = {max(timeout_ms / 1000, 0.001):.3f}")
    cur.execute("START TRANSACTION READ ONLY")


def _mysql_hata_turu(exc: BaseException) -> str | None:
    kod = exc.args[0] if getattr(exc, "args", None) else None
    if kod in _MYSQL_ZAMAN:
        return ZAMAN
    if kod in _MYSQL_YETKI:
        return YETKI
    return None


def _mysql_siniflar() -> tuple[type[BaseException], ...]:
    import pymysql

    return (pymysql.err.MySQLError,)


# ------------------------------------------------------------------ SQL Server

_MSSQL_YETKI = frozenset({229, 230, 262, 297, 300})


def _mssql_baglan(t: BaglantiTanimi, connect_timeout_s: float, timeout_ms: int) -> Any:
    import pytds

    return pytds.connect(
        server=t.host,
        port=t.etkin_port,
        database=t.veritabani,
        user=t.kullanici,
        password=t.parola,
        login_timeout=max(1, int(connect_timeout_s)),
        timeout=max(1.0, timeout_ms / 1000),
        readonly=True,  # ApplicationIntent=ReadOnly
        autocommit=False,
        appname="testing-probe-ro",
    )


def _mssql_hazirla(_conn: Any, cur: Any, timeout_ms: int) -> None:
    cur.execute(f"SET LOCK_TIMEOUT {int(timeout_ms)}")


def _mssql_hata_turu(exc: BaseException) -> str | None:
    import pytds.tds_base as tb

    if isinstance(exc, tb.TimeoutError | TimeoutError):
        return ZAMAN
    if getattr(exc, "msg_no", None) in _MSSQL_YETKI or getattr(exc, "number", None) in _MSSQL_YETKI:
        return YETKI
    return None


def _mssql_siniflar() -> tuple[type[BaseException], ...]:
    import pytds.tds_base as tb

    return (tb.Error, TimeoutError)


# ------------------------------------------------------------------ Oracle

_ORA_ZAMAN = ("DPY-4024", "ORA-03156", "ORA-01013")
_ORA_YETKI = ("ORA-01031", "ORA-00942", "ORA-01720")


def _ora_ondalik(cursor: Any, meta: Any) -> Any:
    """Ölçekli NUMBER → ölçeğe yuvarlanmış Decimal (float değil; NUMBER sondaki sıfırları
    saklamaz, `750` yerine diğer lehçelerdeki gibi `750.00` — özet karşılaştırması tutarlı)."""
    import decimal

    import oracledb

    olcek = meta.scale or 0
    if meta.type_code is oracledb.DB_TYPE_NUMBER and olcek > 0:
        birim = decimal.Decimal(1).scaleb(-olcek)
        return cursor.var(
            decimal.Decimal,
            arraysize=cursor.arraysize,
            outconverter=lambda v: v.quantize(birim) if v is not None else v,
        )
    return None


def _ora_baglan(t: BaglantiTanimi, connect_timeout_s: float, timeout_ms: int) -> Any:
    import oracledb

    conn = oracledb.connect(
        user=t.kullanici,
        password=t.parola,
        host=t.host,
        port=t.etkin_port,
        service_name=t.veritabani,
        tcp_connect_timeout=float(connect_timeout_s),
    )
    conn.call_timeout = int(timeout_ms)
    conn.outputtypehandler = _ora_ondalik
    return conn


def _ora_hazirla(_conn: Any, cur: Any, _timeout_ms: int) -> None:
    cur.execute("SET TRANSACTION READ ONLY")


def _ora_hata_turu(exc: BaseException) -> str | None:
    metin = str(exc)
    if any(k in metin for k in _ORA_ZAMAN):
        return ZAMAN
    if any(k in metin for k in _ORA_YETKI):
        return YETKI
    return None


def _ora_siniflar() -> tuple[type[BaseException], ...]:
    import oracledb

    return (oracledb.Error,)


def _ora_kolon(d: Any) -> str:
    # Oracle tırnaksız adları büyük harfle döndürür; diğer lehçelerle aynı görünsün.
    ad = str(d[0])
    return ad.lower() if ad.isupper() else ad


SURUCULER: dict[str, _Surucu] = {
    "postgresql": _Surucu(
        _pg_baglan, _pg_hazirla, _pg_hata_turu, _pg_siniflar, kolon_adi=lambda d: str(d.name)
    ),
    "mysql": _Surucu(_mysql_baglan, _mysql_hazirla, _mysql_hata_turu, _mysql_siniflar),
    "mssql": _Surucu(_mssql_baglan, _mssql_hazirla, _mssql_hata_turu, _mssql_siniflar),
    "oracle": _Surucu(_ora_baglan, _ora_hazirla, _ora_hata_turu, _ora_siniflar, _ora_kolon),
}


def surucu_al(tur: str) -> _Surucu:
    try:
        return SURUCULER[tur]
    except KeyError as exc:
        raise BaglantiHatasi(f"Desteklenmeyen veritabanı türü: {tur}") from exc


# ------------------------------------------------------------------ şema keşfi + sabit SQL

_AD = re.compile(r"^[a-z_][a-z0-9_]*$")


def _liste(adlar: Sequence[str], buyuk: bool = False) -> str:
    for a in adlar:
        if not _AD.match(a):  # yalnız modül sabitleri; yine de enjeksiyona kapalı
            raise ValueError(f"geçersiz tablo adı: {a}")
    return ", ".join(f"'{a.upper() if buyuk else a}'" for a in adlar)


def sema_sorgusu(tur: str, tablolar: Sequence[str]) -> str:
    """İzinli tabloların (tablo, kolon, tür) satırları; sıralı. Ad listesi sabittir."""
    if tur == "postgresql":
        return (
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            f"WHERE table_schema = 'public' AND table_name IN ({_liste(tablolar)}) "
            "ORDER BY table_name, ordinal_position"
        )
    if tur == "mysql":
        return (
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            f"WHERE table_schema = DATABASE() AND LOWER(table_name) IN ({_liste(tablolar)}) "
            "ORDER BY table_name, ordinal_position"
        )
    if tur == "mssql":
        return (
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            f"WHERE table_schema = SCHEMA_NAME() AND LOWER(table_name) IN ({_liste(tablolar)}) "
            "ORDER BY table_name, ordinal_position"
        )
    if tur == "oracle":
        # Erişilebilen tablolar (salt okuma kullanıcısı tabloların sahibi olmayabilir); aynı ad
        # birden çok şemada varsa önce kullanıcının geçerli şeması.
        return (
            "SELECT table_name, column_name, data_type, owner FROM all_tab_columns "
            f"WHERE table_name IN ({_liste(tablolar, buyuk=True)}) "
            "ORDER BY CASE WHEN owner = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') "
            "THEN 0 ELSE 1 END, owner, table_name, column_id"
        )
    raise BaglantiHatasi(f"Desteklenmeyen veritabanı türü: {tur}")


def sema_satirlari(tur: str, satirlar: Sequence[Sequence[Any]]) -> list[tuple[str, str, str]]:
    """Sürücü satırlarını (tablo, kolon, tür) küçük harfe indirger; Oracle'da ilk sahip kalır."""
    out: list[tuple[str, str, str]] = []
    sahip: dict[str, Any] = {}
    for r in satirlar:
        tablo, kolon, tip = str(r[0]).lower(), str(r[1]).lower(), str(r[2]).lower()
        if tur == "oracle":
            s = r[3] if len(r) > 3 else None
            if sahip.setdefault(tablo, s) != s:
                continue
        out.append((tablo, kolon, tip))
    return out


def sabit_sql(sql_pg: str, tur: str) -> str:
    """TP'nin PostgreSQL ile yazılmış sabit SQL'ini hedef lehçeye çevirir (PG'de aynen döner).

    Mantıksal kolon koşulları (`WHERE aktif`) SQL Server ve Oracle'da (bit / NUMBER(1)) `= 1`
    karşılaştırmasına dönüşür; NULL sıralaması PostgreSQL'inkiyle aynı tutulur."""
    if tur == "postgresql":
        return sql_pg
    import sqlglot
    from sqlglot import exp

    agac = sqlglot.parse_one(sql_pg, read="postgres")
    if tur in ("mssql", "oracle"):

        def _kosul(n: exp.Expression) -> exp.Expression:
            ust = n.parent
            kosul_ici = isinstance(ust, exp.Where | exp.And | exp.Or | exp.Not)
            if isinstance(n, exp.Column) and kosul_ici:
                return exp.EQ(this=n.copy(), expression=exp.Literal.number(1))
            if isinstance(n, exp.Boolean):
                return exp.Literal.number(1 if n.this else 0)
            return n

        agac = agac.transform(_kosul)
    return agac.sql(dialect=SQLGLOT_LEHCE[tur])
