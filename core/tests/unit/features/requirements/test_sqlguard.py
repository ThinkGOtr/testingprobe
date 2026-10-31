"""db_query SQL koruması: tek SELECT, izin listeli tablo/kolon/fonksiyon (§8.2b)."""

from __future__ import annotations

import pytest

from tp_core.features.requirements.sqlguard import QueryRejected, validate_select

KABUL = [
    "SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'",
    "select u.kod, u.fiyat, k.ad from urun u join kampanya k on k.urun_id = u.id where k.aktif",
    "SELECT count(*) AS n FROM urun ORDER BY n",
    "SELECT kod, CASE WHEN fiyat > 20 THEN 'pahalı' ELSE 'ucuz' END AS sinif FROM urun",
    "SELECT ad FROM public.urun WHERE id IN (SELECT urun_id FROM kampanya)",
    "SELECT kullanici_adi, kredi_limiti FROM bayi ORDER BY kullanici_adi LIMIT 5",
    "SELECT lower(ad), cast(fiyat AS text), coalesce(ad, 'x'), round(fiyat, 1) FROM urun",
]

RET = {
    "dml": "DELETE FROM ayar",
    "update": "UPDATE ayar SET deger = '1'",
    "ddl": "DROP TABLE ayar",
    "cok_ifade": "SELECT 1; DROP TABLE urun",
    "yorumlu_ikinci": "SELECT kod FROM urun; -- \nDELETE FROM urun",
    "cte": "WITH x AS (SELECT kod FROM urun) SELECT kod FROM x",
    "cte_dml": "WITH x AS (DELETE FROM urun RETURNING id) SELECT id FROM x",
    "into": "SELECT kod INTO yedek FROM urun",
    "kilit": "SELECT kod FROM urun FOR UPDATE",
    "kilit_share": "SELECT kod FROM urun FOR SHARE",
    "pg_sleep": "SELECT pg_sleep(10)",
    "current_setting": "SELECT current_setting('statement_timeout')",
    "set_config": "SELECT set_config('statement_timeout', '0', false)",
    "read_file": "SELECT pg_read_file('/etc/passwd')",
    "tablo_fonksiyonu": "SELECT x FROM generate_series(1, 10) AS x",
    "izinsiz_tablo": "SELECT numara FROM siparis",
    "oturum": "SELECT token_hash FROM oturum",
    "parola": "SELECT kullanici_adi, parola_hash FROM bayi",
    "nitelikli_parola": "SELECT b.parola_hash FROM bayi b",
    "yildiz": "SELECT * FROM urun",
    "tablo_yildiz": "SELECT u.* FROM urun u",
    "katalog": "SELECT relname FROM pg_catalog.pg_class",
    "sema": "SELECT ad FROM other.urun",
    "union": "SELECT kod FROM urun UNION SELECT kod FROM kampanya",
    "from_alt_sorgu": "SELECT t.kod FROM (SELECT kod FROM urun) t",
    "bos": "   ",
    "uzun": "SELECT kod FROM urun WHERE kod = '" + "x" * 3000 + "'",
    "bozuk": "SELEC kod FROM",
    "now": "SELECT now()",
    "copy": "COPY urun TO '/tmp/x'",
    "set": "SET statement_timeout = 0",
}


@pytest.mark.parametrize("sql", KABUL)
def test_kabul(sql: str) -> None:
    vq = validate_select(sql)
    assert vq.sql.upper().startswith("SELECT")
    assert set(vq.tables) <= {"urun", "kampanya", "ayar", "bayi"}


@pytest.mark.parametrize("ad", sorted(RET))
def test_ret(ad: str) -> None:
    with pytest.raises(QueryRejected):
        validate_select(RET[ad])


def test_calistirilan_metin_agactan_uretilir() -> None:
    vq = validate_select("SELECT kod /* yorum */ FROM urun -- son")
    assert "yorum" not in vq.sql and "--" not in vq.sql


def test_and_or_baglaclari_kabul() -> None:
    """sqlglot'ta AND/OR `Func` alt sınıfıdır; fonksiyon izin listesine takılmamalı."""
    assert "AND" in validate_select("SELECT kod FROM urun WHERE aktif AND fiyat > 1").sql
    assert "OR" in validate_select("SELECT kod FROM urun WHERE aktif OR fiyat > 1").sql
    with pytest.raises(QueryRejected, match="pg_sleep"):
        validate_select("SELECT kod FROM urun WHERE aktif OR pg_sleep(1) IS NULL")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'x'",
        "SELECT 1",
        "SELECT lower('A')",
    ],
)
def test_tablosuz_sorgu_reddedilir(sql: str) -> None:
    with pytest.raises(QueryRejected, match="tablo"):
        validate_select(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # Takma ad WHERE'de tablo kolonuna çözülür (Postgres): gizli kolon kâhini olurdu.
        "SELECT id AS parola_hash FROM bayi WHERE parola_hash LIKE 'a%'",
        "SELECT id AS parola_hash FROM bayi ORDER BY parola_hash",
        "SELECT id AS x FROM bayi WHERE x > 1",
        "SELECT id AS x FROM bayi GROUP BY x",
        "SELECT count(id) AS n FROM bayi HAVING n > 1",
        "SELECT id AS x FROM bayi ORDER BY x || ''",
        "SELECT ad FROM urun WHERE id IN (SELECT id AS parola_hash FROM bayi)",
    ],
)
def test_takma_ad_yalnizca_ust_duzey_order_by(sql: str) -> None:
    with pytest.raises(QueryRejected):
        validate_select(sql)


def test_takma_ad_order_by_kabul() -> None:
    assert validate_select("SELECT id AS x FROM bayi ORDER BY x DESC").tables == ("bayi",)


KANIT_RET = [
    # Gerçek değer 750.00 iken 500.00 "kanıtı" üretir (canlıda doğrulandı).
    "SELECT anahtar, '500.00' FROM ayar WHERE anahtar = 'min_siparis_tutari'",
    "SELECT anahtar, NULL FROM ayar",
    "SELECT anahtar, TRUE FROM ayar",
    "SELECT anahtar, CAST('500.00' AS numeric) FROM ayar",
    "SELECT anahtar, coalesce(NULL, '500.00') FROM ayar",
    "SELECT anahtar, CASE WHEN deger IS NOT NULL THEN '500.00' END FROM ayar",
    "SELECT anahtar, concat(deger, '0') FROM ayar",
    "SELECT fiyat * 2 FROM urun",
    "SELECT count(*) FROM kampanya WHERE 1 = 0",
    "SELECT kod FROM urun WHERE aktif OR TRUE",
    "SELECT kod FROM urun WHERE 'a' = 'a'",
]


@pytest.mark.parametrize("sql", KANIT_RET)
def test_kanit_sorgusu_deger_uyduramaz(sql: str) -> None:
    with pytest.raises(QueryRejected):
        validate_select(sql, kanit=True)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'",
        "SELECT k.kod, u.kod FROM kampanya k JOIN urun u ON u.id = k.urun_id WHERE k.aktif",
        "SELECT count(*) AS n FROM urun",
        "SELECT count(DISTINCT kod), max(fiyat), lower(ad), round(fiyat, 2) FROM urun "
        "GROUP BY ad, fiyat",
        "SELECT cast(fiyat AS text) FROM urun WHERE fiyat > 10 AND aktif",
    ],
)
def test_kanit_sorgusu_kabul(sql: str) -> None:
    assert validate_select(sql, kanit=True).sql.startswith("SELECT")
