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
        "SELECT k.kod FROM kampanya k WHERE k.aktif",
        "SELECT count(*) AS n FROM urun",
        "SELECT ad, lower(ad), count(DISTINCT kod) FROM urun GROUP BY ad",
        "SELECT aktif, max(fiyat) FROM urun GROUP BY 1",
        "SELECT kod, fiyat FROM urun GROUP BY kod, fiyat",
        "SELECT max(fiyat) FROM urun",
        "SELECT min(u.kod) AS ilk FROM urun u WHERE u.aktif",
        "SELECT cast(fiyat AS text) FROM urun WHERE fiyat > 10 AND aktif",
        "SELECT anahtar, CAST(deger AS numeric) FROM ayar WHERE anahtar = 'min_siparis_tutari'",
        "SELECT anahtar, deger::varchar FROM ayar",
        "SELECT CAST(CAST(deger AS numeric) AS text) FROM ayar",
        "SELECT upper(trim(kod)) FROM urun",
    ],
)
def test_kanit_sorgusu_kabul(sql: str) -> None:
    assert validate_select(sql, kanit=True).sql.startswith("SELECT")


# 2. inceleme turu: kayıplı dönüşüm ve bağımsız toplamalar değer uydurur (canlı demoapp_ro'da
# yeniden üretildi; gerçek min_siparis_tutari=750.00, P-001 fiyatı 25.00).
KANIT_KAYIPLI = {
    # "min_siparis_tutari=7"
    "cast_varchar_n": (
        "SELECT anahtar, CAST(deger AS varchar(1)) FROM ayar WHERE anahtar='min_siparis_tutari'"
    ),
    # "min_siparis_tutari=1000"
    "round_negatif": (
        "SELECT anahtar, round(CAST(deger AS numeric), -3) FROM ayar "
        "WHERE anahtar='min_siparis_tutari'"
    ),
    "round_decimal": (
        "SELECT anahtar, ROUND(CAST(deger AS DECIMAL), -3) FROM ayar "
        "WHERE anahtar='min_siparis_tutari'"
    ),
    # "bayi1=0; bayi2=0"
    "round_kredi": "SELECT kullanici_adi, round(kredi_limiti, -5) FROM bayi",
    "round_basamaksiz": "SELECT kod, round(fiyat) FROM urun",
    "round_pozitif": "SELECT kod, round(fiyat, 1) FROM urun",
    "cast_numeric_ps": "SELECT anahtar, CAST(deger AS numeric(5,0)) FROM ayar",
    "cast_int": "SELECT kullanici_adi, CAST(kredi_limiti AS INT) FROM bayi",
    "cast_bigint": "SELECT kullanici_adi, kredi_limiti::bigint FROM bayi",
    "cast_float": "SELECT kod, CAST(fiyat AS double precision) FROM urun",
    "cast_char": "SELECT anahtar, CAST(deger AS char) FROM ayar",
    "cast_tarih": "SELECT kullanici_adi, CAST(olusturma AS date) FROM bayi",
    "length": "SELECT anahtar, length(deger) FROM ayar",
    "abs": "SELECT kod, abs(fiyat) FROM urun",
    "trim_karakter": "SELECT anahtar, trim(both '0' from deger) FROM ayar",
    "sum": "SELECT sum(fiyat) FROM urun",
    "avg": "SELECT avg(fiyat) FROM urun",
    "toplama_icinde_donusum": "SELECT max(round(fiyat, -2)) FROM urun",
    # "P-001=30.00" (farklı satırlar eşlenir)
    "bagimsiz_toplamalar": "SELECT MIN(kod), MAX(fiyat) FROM urun",
    "iki_toplama_gruplu": "SELECT aktif, min(kod), max(fiyat) FROM urun GROUP BY aktif",
    "gruplanmamis_kolon": "SELECT kod, max(fiyat) FROM urun GROUP BY aktif",
    "grupsuz_kolon": "SELECT kod, count(*) FROM urun",
    "donusumlu_grup_disi": "SELECT lower(ad), max(fiyat) FROM urun GROUP BY kod",
    "toplama_ustunde_cast": "SELECT kod, CAST(max(fiyat) AS text) FROM urun GROUP BY kod",
}


@pytest.mark.parametrize("ad", sorted(KANIT_KAYIPLI))
def test_kanit_sorgusu_kayipli_donusum_ve_bagimsiz_toplama_reddedilir(ad: str) -> None:
    with pytest.raises(QueryRejected):
        validate_select(KANIT_KAYIPLI[ad], kanit=True)


# ---------------------------------------------------------------- 1. inceleme turu (kaçaklar)

GUARD_KACAKLARI = {
    # Takma ad kolon listesi kolonları konumla yeniden adlandırır: b.ad = parola_hash.
    "kolon_listesi": "SELECT b.ad FROM bayi AS b(id, kullanici_adi, ad, olusturma)",
    "kolon_listesi_niteliksiz": "SELECT ad FROM bayi AS b(id, kullanici_adi, ad)",
    # Tablo takma adı başka tablonun izinli kolon adı: alt sorguda tüm bayi satırı okunurdu.
    "tum_satir_takma_ad": (
        "SELECT (SELECT CAST(deger AS TEXT) FROM bayi deger LIMIT 1) AS x, "
        "(SELECT count(deger) FROM ayar) AS y FROM urun"
    ),
    "takma_ad_kolon_adi": "SELECT kod FROM urun deger WHERE kod = 'P-001'",
    "takma_ad_baska_tablo": "SELECT kod FROM urun bayi",
    "projeksiyonda_alt_sorgu": "SELECT (SELECT max(fiyat) FROM urun) AS m FROM ayar",
    "lateral": "SELECT kod FROM urun, LATERAL (SELECT 1 AS a) x",
    "lateral_uydurma": (
        "SELECT anahtar, deger FROM urun, LATERAL (SELECT 'min_siparis_tutari' AS anahtar, "
        "'500.00' AS deger FROM ayar) x LIMIT 1"
    ),
    "cross_join_lateral": (
        "SELECT anahtar FROM urun CROSS JOIN LATERAL (SELECT anahtar FROM ayar) x"
    ),
    "values": (
        "SELECT deger FROM urun, (VALUES ('500.00')) AS v(deger) "
        "WHERE kod NOT IN (SELECT anahtar FROM ayar) LIMIT 1"
    ),
    "tablesample": "SELECT kod FROM urun TABLESAMPLE SYSTEM (10)",
    "pencere": "SELECT count(*) OVER () FROM urun",
    "adlandirilmis_pencere": "SELECT count(*) OVER w FROM urun WINDOW w AS ()",
    "join_on_alt_sorgu": (
        "SELECT u.kod FROM urun u JOIN kampanya k ON k.urun_id IN (SELECT id FROM urun)"
    ),
    "order_by_alt_sorgu": "SELECT kod FROM urun ORDER BY (SELECT max(fiyat) FROM urun)",
    # Nitelenmemiş kolon dış kapsama (bağıntı) örtük çözülmez.
    "ortuk_baginti": (
        "SELECT kod FROM urun WHERE kod IN (SELECT anahtar FROM ayar WHERE fiyat > 0)"
    ),
    "tum_satir_dis_kapsam": (
        "SELECT kod FROM urun u WHERE kod IN (SELECT anahtar FROM ayar WHERE CAST(u AS text) <> '')"
    ),
    "kompozit_alan": "SELECT (u).kod FROM urun u",
    "sema_nitelikli_kolon": "SELECT public.urun.ad FROM urun",
}


@pytest.mark.parametrize("ad", sorted(GUARD_KACAKLARI))
def test_guard_kacaklari_reddedilir(ad: str) -> None:
    with pytest.raises(QueryRejected):
        validate_select(GUARD_KACAKLARI[ad])
    with pytest.raises(QueryRejected):
        validate_select(GUARD_KACAKLARI[ad], kanit=True)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT kod FROM urun WHERE id IN "
        "(SELECT k.urun_id FROM kampanya k WHERE k.urun_id = urun.id)",
        "SELECT u.kod FROM urun u WHERE u.id = ANY (SELECT urun_id FROM kampanya)",
        "SELECT kod FROM urun GROUP BY kod HAVING count(id) > (SELECT count(id) FROM kampanya)",
        "SELECT u.kod, k.ad FROM urun u, kampanya k WHERE k.urun_id = u.id",
        "SELECT urun.kod FROM urun urun",
    ],
)
def test_kosulda_alt_sorgu_ve_birlestirme_kabul(sql: str) -> None:
    assert validate_select(sql).sql.startswith("SELECT")


@pytest.mark.parametrize(
    "sql",
    [
        # Gerçek değer 750.00; çapraz birleştirme fiyatı anahtarla eşler (min_siparis_tutari=30.00).
        "SELECT a.anahtar, u.fiyat FROM ayar a, urun u "
        "WHERE a.anahtar = 'min_siparis_tutari' AND u.kod = 'P-004'",
        "SELECT a.anahtar, u.fiyat FROM ayar a JOIN urun u ON TRUE",
        "SELECT k.kod, u.kod FROM kampanya k JOIN urun u ON u.id = k.urun_id WHERE k.aktif",
        # Kolon yeniden adlandırma: aciklama metni "deger" olarak görünürdü.
        "SELECT anahtar, deger FROM ayar AS a(anahtar, aciklama, deger) "
        "WHERE anahtar = 'min_siparis_tutari'",
        "SELECT anahtar FROM ayar WHERE anahtar IN (SELECT kod FROM urun)",
    ],
)
def test_kanit_sorgusu_tek_tablo(sql: str) -> None:
    with pytest.raises(QueryRejected):
        validate_select(sql, kanit=True)
