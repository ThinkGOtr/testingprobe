"""Çoklu DB salt okuma bağlantısı: tanım çözümü, lehçe başına oturum (sahte bağlantı), şema keşfi,
sabit SQL çevirisi, sorgu muhafızının lehçe davranışı ve geriye uyum."""

from __future__ import annotations

from typing import Any

import pytest

from tp_core.features.requirements import datatools
from tp_core.features.requirements.datatools import DataToolError, DataTools, DemoDb
from tp_core.features.requirements.sqlguard import QueryRejected, validate_select
from tp_core.veri import ro_baglanti as rb
from tp_core.veri.ro_baglanti import BaglantiHatasi, BaglantiTanimi, cozumle, url_coz

# ------------------------------------------------------------------ tanım çözümü


@pytest.mark.parametrize(
    ("url", "tur", "port"),
    [
        ("postgresql://u:p@h:5433/db", "postgresql", 5433),
        ("postgres://u:p@h/db", "postgresql", None),
        ("postgresql+psycopg://u:p@h/db", "postgresql", None),
        ("mysql://u:p@h:3307/db", "mysql", 3307),
        ("mysql+pymysql://u:p@h/db", "mysql", None),
        ("mariadb://u:p@h/db", "mysql", None),
        ("mssql://u:p@h:1434/db", "mssql", 1434),
        ("mssql+pytds://u:p@h/db", "mssql", None),
        ("sqlserver://u:p@h/db", "mssql", None),
        ("oracle://u:p@h:1522/FREEPDB1", "oracle", 1522),
        ("oracle+oracledb://u:p@h/FREEPDB1", "oracle", None),
    ],
)
def test_url_onekten_tur(url: str, tur: str, port: int | None) -> None:
    t = url_coz(url)
    assert (t.tur, t.port, t.kullanici, t.parola, t.host) == (tur, port, "u", "p", "h")
    assert t.etkin_port == (port or rb.VARSAYILAN_PORT[tur])


def test_url_desteklenmeyen_onek() -> None:
    with pytest.raises(BaglantiHatasi, match="Desteklenmeyen"):
        url_coz("sqlite:///x.db")


def test_pg_ham_url_aynen_korunur() -> None:
    """Geriye uyum: PG bağlantı dizesi (sslmode vb.) psycopg'e eskisi gibi gider."""
    t = url_coz("postgresql+psycopg://demoapp_ro:g%40zli@db:5432/demo?sslmode=require")
    assert t.ham_url == "postgresql://demoapp_ro:g%40zli@db:5432/demo?sslmode=require"
    assert t.parola == "g@zli"
    assert t.secenekler == {"sslmode": "require"}


def test_url_kodlu_parola_ve_oracle_servis() -> None:
    t = url_coz("oracle://ro:a%2Fb%3Ac@h/?service_name=FREEPDB1")
    assert t.parola == "a/b:c" and t.veritabani == "FREEPDB1"


def test_cozumle_url_ayri_alanlarin_onune_gecer() -> None:
    t = cozumle(url="mysql://u:p@h/db", tur="oracle", host="x", ad="y", kullanici="z")
    assert t is not None and t.tur == "mysql"


def test_cozumle_ayri_alanlar_ve_varsayilan_port() -> None:
    t = cozumle(tur="mssql", host=" sql1 ", ad="demo", kullanici="ro", parola="s")
    assert t == BaglantiTanimi("mssql", "sql1", None, "demo", "ro", "s")
    assert t.etkin_port == 1433 and t.lehce == "tsql" and t.etiket == "Microsoft SQL Server"
    assert cozumle(tur="MariaDB", host="h", ad="d", kullanici="u").tur == "mysql"


def test_cozumle_hicbiri_yok() -> None:
    assert cozumle() is None
    assert cozumle(url="  ", tur="") is None


@pytest.mark.parametrize(
    ("alanlar", "mesaj"),
    [
        ({"tur": "sqlite", "host": "h", "ad": "d", "kullanici": "u"}, "Desteklenmeyen"),
        ({"tur": "mysql", "ad": "d", "kullanici": "u"}, "TP_RO_DB_HOST"),
        ({"tur": "mysql", "host": "h", "kullanici": "u"}, "TP_RO_DB_NAME"),
        ({"tur": "mysql", "host": "h", "ad": "d"}, "TP_RO_DB_USER"),
        ({"tur": "mysql", "host": "h", "ad": "d", "kullanici": "u", "port": "x"}, "sayı"),
        ({"tur": "mysql", "host": "h", "ad": "d", "kullanici": "u", "port": 70000}, "1–65535"),
    ],
)
def test_cozumle_gecersiz(alanlar: dict[str, Any], mesaj: str) -> None:
    with pytest.raises(BaglantiHatasi, match=mesaj):
        cozumle(**alanlar)


def test_parola_repr_ve_maskede_gorunmez() -> None:
    t = cozumle(tur="oracle", host="h", ad="d", kullanici="u", parola="Cok-Gizli-1")
    assert "Cok-Gizli-1" not in repr(t)
    assert t.maskele("ORA-01017: Cok-Gizli-1 reddedildi") == "ORA-01017: *** reddedildi"
    assert "s3cr3t" not in rb.maskele("bağlanılamadı: mysql://ro:s3cr3t@h/db")
    assert "s3cr3t" not in rb.maskele("Login failed; Password=s3cr3t;")


# ------------------------------------------------------------------ sahte bağlantı (lehçe başına)


class _SahteImlec:
    def __init__(self, conn: _SahteBaglanti) -> None:
        self.conn = conn
        self.description: list[Any] | None = None
        self._satirlar: list[tuple[Any, ...]] = []

    def execute(self, sql: str) -> None:
        self.conn.ifadeler.append(sql)
        if self.conn.hata is not None and not sql.startswith(("SET", "START")):
            raise self.conn.hata
        self.description = [(k,) for k in self.conn.kolonlar]
        self._satirlar = list(self.conn.satirlar)

    def fetchmany(self, n: int) -> list[tuple[Any, ...]]:
        return self._satirlar[:n]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._satirlar)


class _SahteBaglanti:
    def __init__(self) -> None:
        self.ifadeler: list[str] = []
        self.kolonlar: list[str] = ["anahtar", "deger"]
        self.satirlar: list[tuple[Any, ...]] = [("min_siparis_tutari", "750.00")]
        self.hata: BaseException | None = None
        self.geri_alindi = self.kapandi = False

    def cursor(self) -> _SahteImlec:
        return _SahteImlec(self)

    def rollback(self) -> None:
        self.geri_alindi = True

    def close(self) -> None:
        self.kapandi = True


class _SahteHata(Exception):
    pass


@pytest.fixture
def sahte(monkeypatch: pytest.MonkeyPatch) -> dict[str, _SahteBaglanti]:
    """Her türün `baglan`ını sahte bağlantıyla değiştirir; `hazirla` (oturum güvencesi), hata
    sınıflandırması ve kolon adı gerçek sürücü kodudur (yalnız sürücü modülü değil)."""
    acilan: dict[str, _SahteBaglanti] = {}
    for tur, s in list(rb.SURUCULER.items()):

        def baglan(t: BaglantiTanimi, _c: float, _z: int, _tur: str = tur) -> _SahteBaglanti:
            acilan[_tur] = _SahteBaglanti()
            return acilan[_tur]

        hazirla = s.hazirla
        if tur == "postgresql":
            # psycopg'in `conn.read_only` özelliği sahte bağlantıda yok; SET LOCAL yine gerçek.
            hazirla = rb._pg_hazirla
        monkeypatch.setitem(
            rb.SURUCULER,
            tur,
            rb._Surucu(
                baglan,
                hazirla,
                s.hata_turu,
                lambda: (_SahteHata,),
                kolon_adi=(lambda d: d[0]) if tur == "postgresql" else s.kolon_adi,
            ),
        )
    return acilan


OTURUM_IFADELERI = {
    "postgresql": ["SET LOCAL statement_timeout = 5000"],
    "mysql": ["SET SESSION MAX_EXECUTION_TIME = 5000", "START TRANSACTION READ ONLY"],
    "mssql": ["SET LOCK_TIMEOUT 5000"],
    "oracle": ["SET TRANSACTION READ ONLY"],
}
URLLER = {
    "postgresql": "postgresql://ro:p@h/demo",
    "mysql": "mysql://ro:p@h/demo",
    "mssql": "mssql://ro:p@h/demo",
    "oracle": "oracle://ro:p@h/FREEPDB1",
}


@pytest.mark.parametrize("tur", rb.TURLER)
def test_oturum_salt_okuma_ve_geri_alma(tur: str, sahte: dict[str, _SahteBaglanti]) -> None:
    db = DemoDb(URLLER[tur])
    res = db.query("SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'")
    conn = sahte[tur]
    # 1. katman: oturum salt okuma + zaman aşımı, sorgudan ÖNCE; sonunda geri alınır, kapanır.
    assert conn.ifadeler[: len(OTURUM_IFADELERI[tur])] == OTURUM_IFADELERI[tur]
    assert conn.geri_alindi and conn.kapandi
    assert res.rows == [("min_siparis_tutari", "750.00")]
    assert res.columns == ["anahtar", "deger"]
    # 2. katman: çalıştırılan metin muhafızın hedef lehçede ürettiği metin.
    assert conn.ifadeler[-1] == res.sql


@pytest.mark.parametrize("tur", rb.TURLER)
def test_muhafiz_yazmayi_baglanmadan_reddeder(tur: str, sahte: dict[str, _SahteBaglanti]) -> None:
    db = DemoDb(URLLER[tur])
    for sql in (
        "DELETE FROM ayar",
        "UPDATE ayar SET deger = '1'",
        "SELECT kod FROM urun; DROP TABLE urun",
        "SELECT parola_hash FROM bayi",
    ):
        with pytest.raises(QueryRejected):
            db.query(sql)
    assert tur not in sahte  # bağlantı hiç açılmadı


@pytest.mark.parametrize(
    ("tur", "sql", "beklenen"),
    [
        ("mysql", "SELECT `kod` FROM `urun` LIMIT 3", "SELECT `kod` FROM `urun` LIMIT 3"),
        ("mssql", "SELECT TOP 3 [kod] FROM dbo.urun", "SELECT TOP 3 [kod] FROM dbo.urun"),
        ("mssql", "SELECT kod FROM urun LIMIT 3", "SELECT TOP 3 kod FROM urun"),
        ("oracle", "SELECT kod FROM urun FETCH FIRST 3 ROWS ONLY", None),
        ("oracle", "SELECT kod FROM urun LIMIT 3", "SELECT kod FROM urun FETCH FIRST 3 ROWS ONLY"),
    ],
)
def test_hedef_lehcede_uretim(
    tur: str, sql: str, beklenen: str | None, sahte: dict[str, _SahteBaglanti]
) -> None:
    res = DemoDb(URLLER[tur]).query(sql)
    assert res.sql == (beklenen or sql)


@pytest.mark.parametrize(
    ("tur", "hata", "metin"),
    [
        ("mysql", _SahteHata(3024, "Query execution was interrupted"), "zaman aşımı"),
        ("mysql", _SahteHata(1969, "max_statement_time exceeded"), "zaman aşımı"),
        ("mysql", _SahteHata(1142, "SELECT command denied"), "Yetki yok"),
        ("oracle", _SahteHata("DPY-4024: call timeout of 5000 ms exceeded"), "zaman aşımı"),
        ("oracle", _SahteHata("ORA-01031: insufficient privileges"), "Yetki yok"),
        ("oracle", _SahteHata("ORA-00904: invalid identifier"), "Sorgu hatası"),
        ("mysql", _SahteHata(1064, "syntax"), "Sorgu hatası"),
    ],
)
def test_hata_siniflandirma(
    tur: str,
    hata: BaseException,
    metin: str,
    sahte: dict[str, _SahteBaglanti],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orijinal = rb.SURUCULER[tur].baglan

    def baglan(t: BaglantiTanimi, c: float, z: int) -> _SahteBaglanti:
        conn = orijinal(t, c, z)
        conn.hata = hata
        return conn

    monkeypatch.setattr(rb.SURUCULER[tur], "baglan", baglan)
    with pytest.raises(DataToolError, match=metin):
        DemoDb(URLLER[tur]).query("SELECT kod FROM urun")
    assert sahte[tur].geri_alindi and sahte[tur].kapandi


def test_mssql_zaman_asimi_ve_yetki() -> None:
    import pytds.tds_base as tb

    assert rb._mssql_hata_turu(tb.TimeoutError("timeout")) == rb.ZAMAN
    e = tb.OperationalError("The SELECT permission was denied")
    e.msg_no = 229
    assert rb._mssql_hata_turu(e) == rb.YETKI
    assert rb._mssql_hata_turu(tb.ProgrammingError("x")) is None


def test_baglanti_hatasi_maskeli(monkeypatch: pytest.MonkeyPatch) -> None:
    def baglan(t: BaglantiTanimi, _c: float, _z: int) -> Any:
        raise _SahteHata(f"Access denied for user 'ro' (password: {t.parola})")

    monkeypatch.setitem(
        rb.SURUCULER,
        "mysql",
        rb._Surucu(baglan, rb._mysql_hazirla, rb._mysql_hata_turu, lambda: (_SahteHata,)),
    )
    with pytest.raises(DataToolError) as ei:
        DemoDb("mysql://ro:Pa55-Gizli@h/demo").query("SELECT kod FROM urun")
    assert "Pa55-Gizli" not in str(ei.value) and "***" in str(ei.value)


def test_yapilandirilmamis_ve_gecersiz() -> None:
    with pytest.raises(DataToolError, match="DEMOAPP_RO_DATABASE_URL"):
        DemoDb(None).query("SELECT kod FROM urun")
    with pytest.raises(DataToolError, match="Desteklenmeyen"):
        DemoDb("sqlite:///x").query("SELECT kod FROM urun")
    with pytest.raises(DataToolError, match="eksik"):
        DemoDb.yapilandirma_hatasi("Veri erişimi yapılandırması eksik").schema()


# ------------------------------------------------------------------ şema keşfi


@pytest.mark.parametrize("tur", rb.TURLER)
def test_sema_sorgusu_izin_listesi(tur: str, sahte: dict[str, _SahteBaglanti]) -> None:
    db = DemoDb(URLLER[tur])
    satirlar: list[tuple[Any, ...]] = [
        ("bayi", "kullanici_adi", "varchar"),
        ("bayi", "parola_hash", "varchar"),  # izin listesinde yok: süzülür
        ("urun", "fiyat", "numeric"),
    ]
    if tur == "oracle":
        satirlar = [
            ("BAYI", "KULLANICI_ADI", "VARCHAR2", "APP"),
            ("BAYI", "PAROLA_HASH", "VARCHAR2", "APP"),
            ("URUN", "FIYAT", "NUMBER", "APP"),
            ("URUN", "KOD", "VARCHAR2", "BASKA"),  # aynı ad başka şemada: ilk sahip kalır
        ]

    orijinal = rb.SURUCULER[tur].baglan

    def baglan(t: BaglantiTanimi, c: float, z: int) -> _SahteBaglanti:
        conn = orijinal(t, c, z)
        conn.satirlar = satirlar
        return conn

    rb.SURUCULER[tur].baglan = baglan
    sema = db.schema()
    sql = sahte[tur].ifadeler[-1]
    if tur == "oracle":
        assert "all_tab_columns" in sql and "'URUN'" in sql
        assert sema["urun"] == [("fiyat", "number")]
    else:
        assert "information_schema.columns" in sql and "'urun'" in sql
        assert sema["urun"] == [("fiyat", "numeric")]
    assert sema["bayi"] == [("kullanici_adi", "varchar" if tur != "oracle" else "varchar2")]
    assert set(sema) == {"urun", "kampanya", "ayar", "bayi"}
    kapsam = {
        "postgresql": "table_schema = 'public'",
        "mysql": "DATABASE()",
        "mssql": "SCHEMA_NAME()",
        "oracle": "CURRENT_SCHEMA",
    }[tur]
    assert kapsam in sql, sql


def test_sema_adi_enjeksiyona_kapali() -> None:
    with pytest.raises(ValueError):
        rb.sema_sorgusu("mysql", ["urun') OR ('1"])


def test_db_schema_ilk_satir_lehce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DemoDb, "schema", lambda self: {"urun": [("kod", "varchar")]})
    for tur, beklenen in (
        ("postgresql", "SQL lehçesi: PostgreSQL (postgres)"),
        ("mysql", "SQL lehçesi: MySQL / MariaDB (mysql)"),
        ("mssql", "SQL lehçesi: Microsoft SQL Server (tsql)"),
        ("oracle", "SQL lehçesi: Oracle (oracle)"),
    ):
        cikti = DataTools(DemoDb(URLLER[tur])).db_schema({})
        satirlar = [x for x in cikti.splitlines() if x.startswith(("SQL lehçesi", "urun("))]
        assert satirlar == [beklenen, "urun(kod varchar)"], cikti


# ------------------------------------------------------------------ sabit SQL


def test_sabit_sql_pg_aynen() -> None:
    from tp_core.features.cases.testdata import SORGULAR

    for sql in SORGULAR.values():
        assert rb.sabit_sql(sql, "postgresql") == sql


@pytest.mark.parametrize("tur", ["mysql", "mssql", "oracle"])
def test_sabit_sql_hedef_lehcede_gecerli_ve_muhafizdan_gecer(tur: str) -> None:
    from tp_core.features.cases.testdata import SORGULAR

    for ad, sql in SORGULAR.items():
        cevrilen = rb.sabit_sql(sql, tur)
        vq = validate_select(cevrilen, lehce=rb.SQLGLOT_LEHCE[tur])
        if ad in ("urun", "kampanya") and tur in ("mssql", "oracle"):
            # bit / NUMBER(1): çıplak mantıksal kolon karşılaştırmaya döner.
            assert "aktif = 1" in vq.sql, vq.sql
        if tur in ("mssql", "oracle"):
            assert "WHERE aktif ORDER" not in vq.sql


def test_testdata_sabit_sorgulari_hedef_lehceye_cevrilir(
    sahte: dict[str, _SahteBaglanti],
) -> None:
    db = DemoDb(URLLER["oracle"])
    db.query(
        "SELECT kod, ad, fiyat FROM urun WHERE aktif ORDER BY sira, kod", kaynak_lehce="postgres"
    )
    assert sahte["oracle"].ifadeler[-1] == (
        "SELECT kod, ad, fiyat FROM urun WHERE aktif = 1 ORDER BY sira, kod"
    )


# ------------------------------------------------------------------ muhafız (lehçe)


@pytest.mark.parametrize(
    ("lehce", "sql"),
    [
        ("mysql", "SELECT SLEEP(5) FROM urun"),
        ("mysql", "SELECT kod FROM urun INTO OUTFILE '/tmp/x'"),
        ("mysql", "SELECT kod FROM urun LOCK IN SHARE MODE"),
        ("mysql", "SELECT @a := kod FROM urun"),
        ("mysql", "SELECT @@version FROM urun"),
        ("mysql", "SELECT kod FROM baska_db.urun"),
        ("mysql", "SELECT kod FROM urun WHERE kod = 'a' UNION SELECT parola_hash FROM bayi"),
        ("tsql", "SELECT TOP 5 kod INTO yeni FROM urun"),
        ("tsql", "SELECT * FROM OPENROWSET('SQLNCLI', 'srv', 'SELECT 1')"),
        ("tsql", "SELECT @@version FROM urun"),
        ("tsql", "SELECT kod FROM sys.urun"),
        ("tsql", "WAITFOR DELAY '00:00:05'"),
        ("tsql", "EXEC xp_cmdshell 'dir'"),
        ("oracle", "SELECT kod FROM urun@uzak"),
        ("oracle", "SELECT DBMS_PIPE.RECEIVE_MESSAGE('a', 5) FROM urun"),
        ("oracle", "SELECT kod FROM urun FOR UPDATE"),
        ("oracle", "SELECT kod FROM app.urun"),
        ("oracle", "SELECT kod FROM urun WHERE ROWNUM <= 5"),
        ("oracle", "BEGIN NULL; END;"),
    ],
)
def test_muhafiz_lehceye_ozgu_saldirilar(lehce: str, sql: str) -> None:
    with pytest.raises(QueryRejected):
        validate_select(sql, lehce=lehce)


def test_mysql_calistirilabilir_yorum_atilir() -> None:
    vq = validate_select(
        "SELECT kod FROM urun WHERE kod = 'a' /*! UNION SELECT parola_hash FROM bayi */",
        lehce="mysql",
    )
    assert vq.sql == "SELECT kod FROM urun WHERE kod = 'a'"


def test_muhafiz_bilinmeyen_lehce() -> None:
    with pytest.raises(QueryRejected, match="lehçe"):
        validate_select("SELECT kod FROM urun", lehce="sqlite")


@pytest.mark.parametrize("lehce", ["mysql", "tsql", "oracle"])
def test_kanit_kurallari_lehcede_de(lehce: str) -> None:
    ok = validate_select(
        "SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'",
        kanit=True,
        lehce=lehce,
    )
    assert ok.tables == ("ayar",)
    with pytest.raises(QueryRejected):
        validate_select("SELECT anahtar, '500.00' FROM ayar", kanit=True, lehce=lehce)


def test_dogrulayici_lehceyi_kullanir(sahte: dict[str, _SahteBaglanti]) -> None:
    from tp_core.features.requirements.verifier import EvidenceVerifier

    db = DemoDb(URLLER["mssql"])
    v = EvidenceVerifier(forge=None, sha="0" * 40, db=db, repo="demo-app")  # type: ignore[arg-type]
    ok, neden = v.check_data(
        {
            "query": "SELECT TOP 1 anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'",
            "result_digest": "min_siparis_tutari=750.00",
        }
    )
    assert ok, neden
    assert sahte["mssql"].ifadeler[-1].startswith("SELECT TOP 1 ")


def test_oracle_kolon_adi() -> None:
    assert rb._ora_kolon(("ANAHTAR",)) == "anahtar"
    assert rb._ora_kolon(("Karisik",)) == "Karisik"


def test_zaman_asimi_metni_degismedi(sahte: dict[str, _SahteBaglanti]) -> None:
    """PG kullanıcıları için metin aynı: 'Sorgu zaman aşımına uğradı (5 sn)'."""
    import psycopg

    def baglan(t: BaglantiTanimi, c: float, z: int) -> _SahteBaglanti:
        conn = _SahteBaglanti()
        conn.hata = psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        return conn

    rb.SURUCULER["postgresql"] = rb._Surucu(
        baglan,
        rb._pg_hazirla,
        rb._pg_hata_turu,
        lambda: (psycopg.Error,),
        kolon_adi=lambda d: d[0],
    )
    with pytest.raises(DataToolError, match=r"^Sorgu zaman aşımına uğradı \(5 sn\)$"):
        DemoDb(URLLER["postgresql"]).query("SELECT kod FROM urun")
    assert datatools.STATEMENT_TIMEOUT_MS == 5000
