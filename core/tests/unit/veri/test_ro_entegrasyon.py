"""Çoklu DB gerçek entegrasyon: PostgreSQL ve MySQL (yerel docker, demo-app şeması + tohum verisi).

İsteğe bağlı: `TP_DBTEST_DOCKER=1` ile koşar (MySQL kabı ~30 sn açılır; varsayılan paket bunu
beklemesin). Kap adları `tp-dbtest-<tür>-<rastgele>`; test bitince silinir. İmajlar yerelde yoksa
çekilir (PG: platform testlerinin sabitlenmiş imajı, MySQL: `mysql:8.4`).

Kanıtlanan:
- iki katman: muhafız yazmayı reddeder; muhafız atlansa bile (yazma yetkili kullanıcı, ham
  oturum) oturum salt okunurdur ve satır yazılmaz;
- salt okuma kullanıcısı izin listesi dışındaki kolonu okuyamaz (`yetki`);
- sorgu zaman aşımı, şema keşfi (izin listesi süzgeci), satır sınırı;
- TP'nin sabit SQL'i (test verisi bloğu) iki veritabanında AYNI metni üretir;
- kanıt doğrulayıcı MySQL'de çalışır.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.unit.conftest import PG_IMAGE, _bos_port
from tp_core.features.cases import testdata
from tp_core.features.requirements import datatools
from tp_core.features.requirements.datatools import DataToolError, DataTools, DemoDb
from tp_core.features.requirements.sqlguard import QueryRejected
from tp_core.veri import ro_baglanti as rb

pytestmark = pytest.mark.skipif(
    os.environ.get("TP_DBTEST_DOCKER") != "1" or shutil.which("docker") is None,
    reason="TP_DBTEST_DOCKER=1 ve docker gerekli (gerçek PG + MySQL entegrasyonu)",
)

REPO = Path(__file__).resolve().parents[4]
DEMO_API_SRC = REPO / "demo-app" / "api" / "src"
MYSQL_IMAGE = "mysql:8.4"
GOLDEN_SQL = "SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'"


@dataclass
class Sunucu:
    tur: str
    ro_url: str  # salt okuma kullanıcısı (izin listesi)
    yazar_url: str  # yazma yetkili kullanıcı (1. katmanı tek başına sınamak için)
    yonetici_url: str  # SQLAlchemy (doğrulama sorguları)


def _kap(ad: str, args: list[str]) -> None:
    subprocess.run(["docker", "run", "-d", "--rm", "--name", ad, *args], check=True,
                   capture_output=True)  # fmt: skip


def _bekle(dene: Callable[[], None], sure_s: float = 120) -> None:
    son: Exception | None = None
    bitis = time.monotonic() + sure_s
    while time.monotonic() < bitis:
        try:
            dene()
            return
        except Exception as exc:  # sunucu henüz hazır değil
            son = exc
            time.sleep(1)
    raise RuntimeError(f"veritabanı hazır olmadı: {son}")


def _demo_tohumla(url: str) -> None:
    if str(DEMO_API_SRC) not in sys.path:
        sys.path.insert(0, str(DEMO_API_SRC))
    from demoapp_api import seed as demo_seed
    from demoapp_api.models import Base as DemoBase
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    eng = create_engine(url)
    DemoBase.metadata.create_all(eng)
    with Session(eng) as s:
        demo_seed.seed(s)
        s.commit()
    eng.dispose()


@pytest.fixture(scope="module")
def pg_sunucu() -> Iterator[Sunucu]:
    ad = f"tp-dbtest-pg-{uuid.uuid4().hex[:8]}"
    port, sp, rp, wp = _bos_port(), secrets.token_hex(8), secrets.token_hex(8), secrets.token_hex(8)
    _kap(ad, ["-e", f"POSTGRES_PASSWORD={sp}", "-p", f"127.0.0.1:{port}:5432",
              "--tmpfs", "/var/lib/postgresql/data", PG_IMAGE])  # fmt: skip
    try:
        import psycopg

        sup = f"postgresql://postgres:{sp}@127.0.0.1:{port}/postgres"
        _bekle(lambda: psycopg.connect(sup, connect_timeout=2).close())
        with psycopg.connect(sup, autocommit=True) as c:
            c.execute("CREATE DATABASE demo")
            c.execute(f"CREATE ROLE demoapp_ro LOGIN PASSWORD '{rp}'")
            c.execute(f"CREATE ROLE yazar LOGIN PASSWORD '{wp}'")
        _demo_tohumla(f"postgresql+psycopg://postgres:{sp}@127.0.0.1:{port}/demo")
        with psycopg.connect(f"postgresql://postgres:{sp}@127.0.0.1:{port}/demo",
                             autocommit=True) as c:  # fmt: skip
            c.execute("GRANT SELECT ON urun, kampanya, ayar TO demoapp_ro")
            c.execute(
                "GRANT SELECT (id, kullanici_adi, ad, kredi_limiti, olusturma) ON bayi "
                "TO demoapp_ro"
            )
            c.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO yazar")
        yield Sunucu(
            "postgresql",
            f"postgresql+psycopg://demoapp_ro:{rp}@127.0.0.1:{port}/demo",
            f"postgresql://yazar:{wp}@127.0.0.1:{port}/demo",
            f"postgresql+psycopg://postgres:{sp}@127.0.0.1:{port}/demo",
        )
    finally:
        subprocess.run(["docker", "rm", "-f", ad], capture_output=True)


@pytest.fixture(scope="module")
def mysql_sunucu() -> Iterator[Sunucu]:
    ad = f"tp-dbtest-mysql-{uuid.uuid4().hex[:8]}"
    port, sp, rp, wp = _bos_port(), secrets.token_hex(8), secrets.token_hex(8), secrets.token_hex(8)
    _kap(ad, ["-e", f"MYSQL_ROOT_PASSWORD={sp}", "-e", "MYSQL_DATABASE=demo",
              "-p", f"127.0.0.1:{port}:3306", "--tmpfs", "/var/lib/mysql", MYSQL_IMAGE,
              "--character-set-server=utf8mb4"])  # fmt: skip
    try:
        import pymysql

        def baglan(**kw: Any) -> Any:
            return pymysql.connect(host="127.0.0.1", port=port, user="root", password=sp,
                                   autocommit=True, connect_timeout=2, **kw)  # fmt: skip

        _bekle(lambda: baglan(database="demo").close(), sure_s=180)
        _demo_tohumla(f"mysql+pymysql://root:{sp}@127.0.0.1:{port}/demo?charset=utf8mb4")
        c = baglan(database="demo")
        with c.cursor() as cur:
            cur.execute(f"CREATE USER 'demoapp_ro'@'%' IDENTIFIED BY '{rp}'")
            cur.execute(f"CREATE USER 'yazar'@'%' IDENTIFIED BY '{wp}'")
            for t in ("urun", "kampanya", "ayar"):
                cur.execute(f"GRANT SELECT ON demo.{t} TO 'demoapp_ro'@'%'")
            cur.execute(
                "GRANT SELECT (id, kullanici_adi, ad, kredi_limiti, olusturma) ON demo.bayi "
                "TO 'demoapp_ro'@'%'"
            )
            cur.execute("GRANT ALL ON demo.* TO 'yazar'@'%'")
        c.close()
        yield Sunucu(
            "mysql",
            f"mysql://demoapp_ro:{rp}@127.0.0.1:{port}/demo",
            f"mysql://yazar:{wp}@127.0.0.1:{port}/demo",
            f"mysql+pymysql://root:{sp}@127.0.0.1:{port}/demo",
        )
    finally:
        subprocess.run(["docker", "rm", "-f", ad], capture_output=True)


@pytest.fixture(params=["postgresql", "mysql"])
def sunucu(request: pytest.FixtureRequest) -> Sunucu:
    return request.getfixturevalue("pg_sunucu" if request.param == "postgresql" else "mysql_sunucu")


def test_golden_sorgu_ve_ozet(sunucu: Sunucu) -> None:
    db = DemoDb(sunucu.ro_url)
    assert db.tur == sunucu.tur
    res = db.query(GOLDEN_SQL)
    assert res.columns == ["anahtar", "deger"]
    assert res.rows == [("min_siparis_tutari", "750.00")]
    assert "min_siparis_tutari=750.00" in DataTools(db).db_query({"sql": GOLDEN_SQL})


def test_sema_kesfi_izin_listesi(sunucu: Sunucu) -> None:
    sema = DemoDb(sunucu.ro_url).schema()
    assert set(sema) == {"urun", "kampanya", "ayar", "bayi"}
    assert {k for k, _ in sema["urun"]} == {"id", "kod", "ad", "fiyat", "sira", "aktif"}
    assert "parola_hash" not in {k for k, _ in sema["bayi"]}
    lehce = DataTools(DemoDb(sunucu.ro_url)).db_schema({})
    assert f"SQL lehçesi: {rb.ETIKETLER[sunucu.tur]}" in lehce


def test_satir_siniri(sunucu: Sunucu) -> None:
    res = DemoDb(sunucu.ro_url).query("SELECT a.kod, b.kod FROM urun a, urun b, urun c, urun d")
    assert len(res.rows) == 100 and res.truncated


def test_muhafiz_yazmayi_reddeder(sunucu: Sunucu) -> None:
    db = DemoDb(sunucu.yazar_url)
    for sql in ("DELETE FROM ayar", "INSERT INTO ayar (anahtar, deger) VALUES ('x', 'y')",
                "SELECT kod FROM urun; DELETE FROM ayar"):  # fmt: skip
        with pytest.raises(QueryRejected):
            db.query(sql)


def test_oturum_salt_okuma_muhafiz_atlansa_bile(sunucu: Sunucu) -> None:
    """1. katman tek başına: yazma YETKİLİ kullanıcıyla ham oturumda bile yazılamaz."""
    tanim = rb.url_coz(sunucu.yazar_url)
    for sql in (
        "INSERT INTO ayar (anahtar, deger, aciklama) VALUES ('sizinti', '1', '')",
        "UPDATE ayar SET deger = '1' WHERE anahtar = 'min_siparis_tutari'",
        "DELETE FROM ayar",
    ):
        with rb.oturum(tanim) as o, pytest.raises(rb.SorguHatasi):
            o.calistir(sql)
    res = DemoDb(sunucu.ro_url).query("SELECT anahtar, deger FROM ayar ORDER BY anahtar")
    assert ("min_siparis_tutari", "750.00") in res.rows
    assert all(r[0] != "sizinti" for r in res.rows)


def test_ro_kullanici_gizli_kolonu_okuyamaz(sunucu: Sunucu) -> None:
    tanim = rb.url_coz(sunucu.ro_url)
    with rb.oturum(tanim) as o, pytest.raises(rb.SorguHatasi) as ei:
        o.calistir("SELECT parola_hash FROM bayi")
    assert ei.value.tur == rb.YETKI


def test_zaman_asimi(sunucu: Sunucu, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(datatools, "STATEMENT_TIMEOUT_MS", 1)
    # MySQL düz çapraz birleştirmenin count(*)'unu satır sayılarından hesaplar: koşul şart.
    agir = (
        "SELECT count(*) FROM "
        + ", ".join(f"urun t{i}" for i in range(13))
        + " WHERE t0.ad <> t1.ad AND t11.ad <> t12.ad"
    )
    with pytest.raises(DataToolError, match="zaman aşımı"):
        DemoDb(sunucu.ro_url).query(agir)


def test_hatali_parola_maskeli(sunucu: Sunucu) -> None:
    tanim = rb.url_coz(sunucu.ro_url)
    url = sunucu.ro_url.replace(tanim.parola, "Yanlis-Parola-77")
    with pytest.raises(DataToolError) as ei:
        DemoDb(url).query(GOLDEN_SQL)
    assert "Yanlis-Parola-77" not in str(ei.value)


def test_sabit_sql_iki_veritabaninda_ayni_blok(pg_sunucu: Sunucu, mysql_sunucu: Sunucu) -> None:
    metinler = {}
    for s in (pg_sunucu, mysql_sunucu):
        db = DemoDb(s.ro_url)
        metinler[s.tur] = testdata.build_text(lambda sql, db=db: db.query(
            sql, kaynak_lehce="postgres").rows)  # fmt: skip
    assert testdata.VERITABANI_YOK not in metinler["postgresql"]
    assert "min_siparis_tutari = 750.00" in metinler["postgresql"]
    assert metinler["mysql"] == metinler["postgresql"]


def test_dogrulayici_mysql(mysql_sunucu: Sunucu) -> None:
    from tp_core.features.requirements.verifier import EvidenceVerifier

    v = EvidenceVerifier(forge=None, sha="0" * 40, db=DemoDb(mysql_sunucu.ro_url), repo="demo-app")  # type: ignore[arg-type]
    ok, neden = v.check_data({"query": GOLDEN_SQL, "result_digest": "min_siparis_tutari=750.00"})
    assert ok, neden
    bozuk, _ = v.check_data({"query": GOLDEN_SQL, "result_digest": "min_siparis_tutari=500.00"})
    assert not bozuk
