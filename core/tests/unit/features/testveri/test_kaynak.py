"""Test verisi kaynakları: kayıt üretimi, ön tanımlı (demo) kaynaklar, yenileme kuralları, API,
gerçek PostgreSQL'e karşı şema keşifli muhafız, demo dışı projenin genel bloğu."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.cases.helpers import login, run_jobs
from tp_core.features.cases import testdata
from tp_core.features.requirements.sqlguard import QueryRejected, validate_select
from tp_core.features.testveri import jobs as _isler  # noqa: F401  (iş kaydı)
from tp_core.features.testveri import kaynak, service
from tp_core.models import session_scope
from tp_core.models.otomasyon_feature import TestVerisi, TestVerisiKaynagi, TestVerisiSurum
from tp_core.proje import proje_icinde

from .conftest import SEED_ROWS, seed_sorgu

# ------------------------------------------------------------------ saf: kayıt üretimi


def _eski_tohum(veri: dict[str, list[tuple[Any, ...]]]) -> list[dict[str, str]]:
    """0049 öncesi `tohum_kayitlari`'nın veritabanı kısmı (birebir karşılaştırma için)."""
    out: list[dict[str, str]] = []

    def ekle(a: str, d: str, g: str, ac: str) -> None:
        out.append({"anahtar": a, "deger": d, "grup": g, "aciklama": ac})

    for kullanici, ad, limit in veri["bayi"]:
        b = f"bayi.{service.slug(kullanici)}"
        ekle(f"{b}.kullanici_adi", str(kullanici), "bayi", "Test kullanıcısının kullanıcı adı")
        ekle(f"{b}.ad", str(ad), "bayi", "Bayi adı")
        ekle(f"{b}.kredi_limiti", testdata.tl(limit), "bayi", "Kredi limiti")
    for kod, ad, fiyat in veri["urun"]:
        u = f"urun.{service.slug(kod)}"
        ekle(f"{u}.kod", str(kod), "urun", "Ürün kodu")
        ekle(f"{u}.ad", str(ad), "urun", "Ürün adı")
        ekle(f"{u}.fiyat", testdata.tl(fiyat), "urun", "Birim fiyat")
    for kod, ad, urun in veri["kampanya"]:
        k = f"kampanya.{service.slug(kod)}"
        ekle(f"{k}.kod", str(kod), "kampanya", f"Kampanya kodu; ürün: {urun}")
        ekle(f"{k}.ad", str(ad), "kampanya", "Kampanya adı")
    for anahtar, deger in veri["ayar"]:
        ekle(f"ayar.{service.slug(anahtar)}", str(deger), "ayar", f"Uygulama ayarı ({anahtar})")
    return out


def test_on_tanimli_kaynaklar_eski_tohumla_birebir() -> None:
    """Demo tohumu kaynak mekanizmasıyla aynı anahtarlar, değerler ve açıklamalar (sırası dahil)."""
    calistir = kaynak.satir_calistirici(seed_sorgu)
    yeni: list[dict[str, str]] = []
    for t in kaynak.on_tanimli_kaynaklar():
        kolonlar, satirlar = calistir(t.sorgu)
        kayitlar, uyarilar = kaynak.kayitlari_uret(t, kolonlar, satirlar)
        assert uyarilar == []
        yeni += kayitlar
    assert yeni == _eski_tohum(SEED_ROWS)
    # Tam tohum: kaynak kayıtları + sabitler (parola sırrı, etiketler) aynı sırada.
    tum = service.tohum_kayitlari(seed_sorgu)
    assert [r["anahtar"] for r in tum[: len(yeni)]] == [r["anahtar"] for r in yeni]
    assert tum[len(yeni)]["anahtar"] == service.DEMO_PAROLA_ANAHTARI
    assert all(r["grup"] == "etiket" for r in tum[len(yeni) + 1 :])


def test_on_tanimli_sorgular_demo_muhafizindan_gecer() -> None:
    for t in kaynak.on_tanimli_kaynaklar():
        validate_select(t.sorgu)  # demo izin listesi (ALLOWED_COLUMNS)


def test_kayit_uretimi_kurallari() -> None:
    t = kaynak.tanim_dogrula(
        {
            "grup": "musteri",
            "sorgu": "SELECT no, ad, bakiye FROM musteri",
            "anahtar_kolonu": "no",
            "deger_kolonlari": [
                {"kolon": "AD", "aciklama": "Müşteri {no} adı"},
                {"kolon": "bakiye", "bicim": "tutar"},
            ],
        }
    )
    assert [k.alan for k in t.deger_kolonlari] == ["ad", "bakiye"]
    kayitlar, uyarilar = kaynak.kayitlari_uret(
        t,
        ["NO", "AD", "BAKIYE"],
        [
            ("M-01", "Ayşe Demo", Decimal("1250")),
            ("m 01", "Çakışan", Decimal("1")),  # aynı slug → atlanır
            (None, "Anahtarsız", Decimal("1")),
            ("M-02", None, Decimal("3.5")),  # boş değer atlanır, diğeri yazılır
            ("M-03", "{veri:x.y}", Decimal("0")),
        ],
    )
    assert kayitlar[:2] == [
        {"anahtar": "musteri.m_01.ad", "deger": "Ayşe Demo", "grup": "musteri",
         "aciklama": "Müşteri M-01 adı"},
        {"anahtar": "musteri.m_01.bakiye", "deger": "1.250,00 TL", "grup": "musteri",
         "aciklama": ""},
    ]  # fmt: skip
    assert {r["anahtar"] for r in kayitlar} == {
        "musteri.m_01.ad",
        "musteri.m_01.bakiye",
        "musteri.m_02.bakiye",
        "musteri.m_03.bakiye",
    }
    assert len(uyarilar) == 4 and all("{" not in u for u in uyarilar)
    with pytest.raises(kaynak.KaynakHatasi, match="olmayan kolon"):
        kaynak.kayitlari_uret(t, ["no", "ad"], [])


@pytest.mark.parametrize(
    ("girdi", "mesaj"),
    [
        ({"grup": "Buyuk"}, "Grup adı"),
        ({"sorgu": "DELETE FROM musteri"}, "SELECT"),
        ({"sorgu": "SELECT 1; SELECT 2"}, "Tek bir SELECT"),
        ({"deger_kolonlari": []}, "En az bir"),
        ({"deger_kolonlari": [{"kolon": "ad", "alan": ""}, {"kolon": "no"}]}, "tek değer"),
        ({"deger_kolonlari": [{"kolon": "ad"}, {"kolon": "ad"}]}, "tekil"),
        ({"deger_kolonlari": [{"kolon": "ad", "bicim": "para"}]}, "Biçim"),
    ],
)
def test_tanim_dogrulama(girdi: dict[str, Any], mesaj: str) -> None:
    taban = {
        "grup": "musteri",
        "sorgu": "SELECT no, ad FROM musteri",
        "anahtar_kolonu": "no",
        "deger_kolonlari": [{"kolon": "ad"}],
    }
    with pytest.raises(service.TestVerisiGecersiz, match=mesaj):
        kaynak.tanim_dogrula({**taban, **girdi})


def test_muhafiz_izinli_sema_ve_hassas_kolonlar() -> None:
    izin = {"musteri": frozenset({"no", "ad", "sifre_hash", "api_token"})}
    assert validate_select("SELECT no, ad FROM musteri", izinli=izin).tables == ("musteri",)
    for sql in (
        "SELECT sifre_hash FROM musteri",
        "SELECT api_token FROM musteri",
        "SELECT no AS parola FROM musteri",
        "SELECT kullanici_adi FROM bayi",
        "SELECT no FROM musteri UNION SELECT no FROM musteri",
    ):
        with pytest.raises(QueryRejected):
            validate_select(sql, izinli=izin)


# ------------------------------------------------------------------ DB: tohum + yenileme


def test_tohum_kaynaklari_ve_baglanti(engine: Engine, parola_sirri: str) -> None:
    with session_scope() as s:
        n = service.tohumla(s, seed_sorgu)
    with session_scope() as s:
        kaynaklar = kaynak.etkin_kaynaklar(s)
        assert [k.grup for k in kaynaklar] == ["bayi", "urun", "kampanya", "ayar"]
        assert all(k.on_tanimli and k.guncelleyen == service.TOHUM_AKTOR for k in kaynaklar)
        idler = {k.grup: k.id for k in kaynaklar}
        kayitlar = service.etkin_kayitlar(s)
        assert n == len(kayitlar)
        for k in kayitlar:
            beklenen = idler.get(k.grup) if k.grup in idler else None
            assert k.kaynak_id == beklenen, k.anahtar
        assert service.blok_metni(s) == testdata.build_text(seed_sorgu)
    # İkinci tohum hiçbir şey eklemez; silinmiş kaynak yeniden açılmaz.
    with session_scope() as s:
        k = s.scalars(select(TestVerisiKaynagi).where(TestVerisiKaynagi.grup == "ayar")).one()
        kaynak.sil(s, k.id, k.surum, "analist")
    with session_scope() as s:
        assert service.tohumla(s, seed_sorgu) == 0
        assert [k.grup for k in kaynak.etkin_kaynaklar(s)] == ["bayi", "urun", "kampanya"]
        ayar = s.scalars(select(TestVerisi).where(TestVerisi.grup == "ayar")).one()
        assert ayar.kaynak_id is None and not ayar.silindi


def test_tohum_eski_kurulumdaki_sahipsiz_kayitlari_baglar(
    engine: Engine, parola_sirri: str
) -> None:
    with session_scope() as s:
        service.tohumla(s, seed_sorgu)
    with engine.begin() as c:  # 0049 öncesi kurulum: kaynak yok, kayıtlar sahipsiz
        c.execute(text("UPDATE test_verisi SET kaynak_id = NULL WHERE project_id = 'test-a'"))
        c.execute(
            text("UPDATE test_verisi_kaynagi SET silindi = false WHERE project_id = 'test-a'")
        )
    with session_scope() as s:
        assert service.tohumla(s, seed_sorgu) == 0
        sahipli = [k for k in service.etkin_kayitlar(s) if k.kaynak_id is not None]
        assert len(sahipli) == len(_eski_tohum(SEED_ROWS))


def _calistirici(satirlar: dict[str, list[tuple[Any, ...]]]) -> kaynak.Calistirici:
    def calistir(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        ad = {v: k for k, v in testdata.SORGULAR.items()}.get(sql, "diger")
        return kaynak.projeksiyon_adlari(sql), list(satirlar.get(ad, []))

    return calistir


def test_yenile_ekler_surumler_isaretler(engine: Engine, parola_sirri: str) -> None:
    with session_scope() as s:
        service.tohumla(s, seed_sorgu)
    veri = {k: list(v) for k, v in SEED_ROWS.items()}
    veri["urun"] = [
        ("P-001", "Portakal Gazozu 1L", Decimal("27.50")),  # fiyat değişti
        ("P-002", "Limonata 330ml", Decimal("15.00")),
        # P-003 kaynakta yok
        ("P-004", "Şeftalili Soğuk Çay 1L", Decimal("30.00")),
        ("P-005", "Ayran 250ml", Decimal("12.00")),  # yeni
        ("P-006", "Demo123!", Decimal("1.00")),  # ad gizli değerle aynı: yalnız ad atlanır
    ]
    with session_scope() as s:  # analist bir kaydı siler: yenileme onu geri açmaz
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "urun.p_002.ad")).one()
        service.sil(s, k.id, k.surum, "analist")
    with session_scope() as s:
        sonuc = kaynak.yenile(s, "analist", calistir=_calistirici(veri))
    urun = next(r for r in sonuc["kaynaklar"] if r["grup"] == "urun")
    assert urun["eklenen"] == 5 and urun["guncellenen"] == 1 and urun["kaynakta_yok"] == 3
    assert urun["atlanan"] == 2  # silinmiş urun.p_002.ad + gizli değerle aynı ad
    assert all(r["hata"] is None for r in sonuc["kaynaklar"])
    with session_scope() as s:
        fiyat = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "urun.p_001.fiyat")).one()
        assert (fiyat.deger, fiyat.surum, fiyat.guncelleyen) == ("27,50 TL", 2, "analist")
        surumler = s.scalars(
            select(TestVerisiSurum.islem).where(TestVerisiSurum.test_verisi_id == fiyat.id)
        ).all()
        assert sorted(surumler) == ["guncelle", "olustur"]
        yok = s.scalars(select(TestVerisi.anahtar).where(TestVerisi.kaynakta_yok.is_(True))).all()
        assert sorted(yok) == ["urun.p_003.ad", "urun.p_003.fiyat", "urun.p_003.kod"]
        assert "urun.p_006.ad" not in service.anahtarlar(s)
        assert s.scalars(
            select(TestVerisi.silindi).where(TestVerisi.anahtar == "urun.p_002.ad")
        ).one()
        # Kaynakta olmayan ürün bloklarda yer almaz (silinmez, çözülür).
        assert "P-003" not in (service.blok_metni(s) or "")
        assert service.cozum_degerleri(s)[0]["urun.p_003.kod"] == "P-003"
        k = s.scalars(select(TestVerisiKaynagi).where(TestVerisiKaynagi.grup == "urun")).one()
        assert k.son_durum["guncellenen"] == 1 and k.son_yenileme is not None
    with engine.connect() as c:
        ozet = c.execute(
            text(
                "SELECT ozet FROM audit_event WHERE audit_event.project_id = 'test-a' AND "
                "eylem = 'testveri.guncelle' ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
    assert ozet["onceki_deger"] == "25,00 TL" and ozet["kaynak"] is True
    # Ürün geri gelir: işaret kalkar; aynı veriyle ikinci yenileme değişiklik yapmaz.
    with session_scope() as s:
        sonuc = kaynak.yenile(s, "analist", calistir=_calistirici(SEED_ROWS))
        urun = next(r for r in sonuc["kaynaklar"] if r["grup"] == "urun")
        assert urun["geri_gelen"] == 3 and urun["eklenen"] == 0
    with session_scope() as s:
        sonuc = kaynak.yenile(s, "analist", calistir=_calistirici(SEED_ROWS))
        assert sonuc["toplam"]["guncellenen"] == 0 and sonuc["toplam"]["eklenen"] == 0


def test_yenile_kaynak_hatasi_digerlerini_durdurmaz(engine: Engine, parola_sirri: str) -> None:
    with session_scope() as s:
        service.tohumla(s, seed_sorgu)

    def calistir(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        if "FROM urun WHERE" in sql:
            raise kaynak.KaynakHatasi("Sorgu reddedildi: deneme")
        return _calistirici(SEED_ROWS)(sql)

    with session_scope() as s:
        sonuc = kaynak.yenile(s, "analist", calistir=calistir)
    hatalar = {r["grup"]: r["hata"] for r in sonuc["kaynaklar"]}
    assert hatalar["urun"] == "Sorgu reddedildi: deneme"
    assert hatalar["bayi"] is None and sonuc["toplam"]["hata"] == 1
    with session_scope() as s:
        assert not s.scalars(select(TestVerisi).where(TestVerisi.kaynakta_yok.is_(True))).all()


# ------------------------------------------------------------------ API + işler


@pytest.fixture
def sahte_db() -> Iterator[dict[str, list[tuple[Any, ...]]]]:
    veri: dict[str, list[tuple[Any, ...]]] = {
        "diger": [("M-01", "Ayşe Demo", Decimal("10"))],
        **{k: list(v) for k, v in SEED_ROWS.items()},
    }
    kaynak.set_calistirici_fabrikasi(lambda: _calistirici(veri))
    try:
        yield veri
    finally:
        kaynak.set_calistirici_fabrikasi(None)


def test_api_crud_onizleme_yenileme(
    api: TestClient, engine: Engine, make_user: Any, sahte_db: Any
) -> None:
    login(api, make_user("analyst"))
    govde = {
        "grup": "musteri",
        "sorgu": "SELECT no, ad, bakiye FROM musteri ORDER BY no",
        "anahtar_kolonu": "no",
        "deger_kolonlari": [{"kolon": "ad"}, {"kolon": "bakiye", "bicim": "tutar"}],
        "aciklama": "Müşteriler",
    }
    r = api.post("/test-data-sources/preview", json=govde)
    assert r.status_code == 202, r.text
    run_jobs(engine)
    on = api.get(f"/test-data-sources/jobs/{r.json()['job_id']}").json()
    assert on["durum"] == "tamam" and on["tur"] == "onizle"
    assert on["sonuc"]["kolonlar"] == ["no", "ad", "bakiye"]
    assert on["sonuc"]["satirlar"] == [["M-01", "Ayşe Demo", "10"]]
    assert on["sonuc"]["kayitlar"] == [
        {"anahtar": "musteri.m_01.ad", "deger": "Ayşe Demo", "durum": "yeni"},
        {"anahtar": "musteri.m_01.bakiye", "deger": "10,00 TL", "durum": "yeni"},
    ]
    with session_scope() as s:
        assert not service.anahtarlar(s)  # önizleme kataloğu değiştirmez

    r = api.post("/test-data-sources", json=govde)
    assert r.status_code == 201, r.text
    k = r.json()
    assert k["surum"] == 1 and k["on_tanimli"] is False and k["kayit_sayisi"] == 0
    assert api.post("/test-data-sources", json=govde).status_code == 409
    r = api.post("/test-data-sources", json={**govde, "grup": "x", "sorgu": "DROP TABLE x"})
    assert r.status_code == 422

    r = api.post("/test-data-sources/refresh", json={"kaynak_id": k["id"]})
    assert r.status_code == 202
    run_jobs(engine)
    is_ = api.get(f"/test-data-sources/jobs/{r.json()['job_id']}").json()
    assert is_["durum"] == "tamam" and is_["sonuc"]["toplam"]["eklenen"] == 2
    liste = api.get("/test-data-sources").json()
    assert liste[0]["kayit_sayisi"] == 2 and liste[0]["son_durum"]["eklenen"] == 2
    kayitlar = {x["anahtar"]: x for x in api.get("/test-data").json()}
    assert kayitlar["musteri.m_01.bakiye"]["kaynak_id"] == k["id"]
    assert kayitlar["musteri.m_01.bakiye"]["kaynakta_yok"] is False

    # Düzenleme: iyimser kilit; grup değişmez.
    r = api.put(f"/test-data-sources/{k['id']}", json={"aciklama": "Y", "beklenen_surum": 9})
    assert r.status_code == 409
    r = api.put(f"/test-data-sources/{k['id']}", json={"grup": "baska", "beklenen_surum": 1})
    assert r.status_code == 422
    r = api.put(
        f"/test-data-sources/{k['id']}",
        json={"deger_kolonlari": [{"kolon": "ad"}], "beklenen_surum": 1},
    )
    assert r.status_code == 200 and r.json()["surum"] == 2
    # Silme: kayıtlar kalır, elle kayıt olur.
    r = api.delete(f"/test-data-sources/{k['id']}", params={"beklenen_surum": 2})
    assert r.status_code == 200 and r.json()["silindi"] is True
    kayitlar = {x["anahtar"]: x for x in api.get("/test-data").json()}
    assert kayitlar["musteri.m_01.ad"]["kaynak_id"] is None
    assert api.get("/test-data-sources").json() == []


def test_api_yetki(api: TestClient, make_user: Any) -> None:
    login(api, make_user("po"))
    assert api.get("/test-data-sources").status_code == 200
    govde = {
        "grup": "m",
        "sorgu": "SELECT a FROM t",
        "anahtar_kolonu": "a",
        "deger_kolonlari": [{"kolon": "a"}],
    }
    assert api.post("/test-data-sources", json=govde).status_code == 403
    assert api.post("/test-data-sources/refresh", json={}).status_code == 403
    assert api.post("/test-data-sources/preview", json=govde).status_code == 403
    assert api.get(f"/test-data-sources/jobs/{uuid.uuid4()}").status_code == 404


def test_onizleme_hatasi_sonucta(
    api: TestClient, engine: Engine, make_user: Any, sahte_db: Any
) -> None:
    def hatali() -> kaynak.Calistirici:
        def calistir(_sql: str) -> Any:
            raise kaynak.KaynakHatasi("Sorgu reddedildi: İzin verilmeyen ya da bilinmeyen kolon: x")

        return calistir

    kaynak.set_calistirici_fabrikasi(hatali)
    login(api, make_user("engineer"))
    r = api.post(
        "/test-data-sources/preview",
        json={
            "grup": "m",
            "sorgu": "SELECT x FROM t",
            "anahtar_kolonu": "x",
            "deger_kolonlari": [{"kolon": "x"}],
        },
    )
    run_jobs(engine)
    is_ = api.get(f"/test-data-sources/jobs/{r.json()['job_id']}").json()
    assert is_["durum"] == "tamam" and "bilinmeyen kolon" in is_["sonuc"]["hata"]


# ------------------------------------------------------------------ gerçek PostgreSQL kaynağı


@pytest.fixture
def musteri_db(db: Any, proje_ayar: Any) -> Iterator[str]:
    """Farklı şemalı proje veritabanı + yalnız SELECT yetkili rol (Home `env.db.*` benzeri)."""
    ad = f"musteri_{uuid.uuid4().hex[:8]}"
    rol = f"ro_{uuid.uuid4().hex[:8]}"
    parola = uuid.uuid4().hex
    srv = db.srv
    with srv.super_conn() as c:
        c.execute(f'CREATE DATABASE "{ad}"')
        c.execute(f"CREATE ROLE {rol} LOGIN PASSWORD '{parola}'")
    with srv.super_conn(ad) as c:
        c.execute(
            "CREATE TABLE musteri (no text PRIMARY KEY, ad text, sehir text, "
            "kredi numeric(12,2), sifre_hash text)"
        )
        c.execute(
            "INSERT INTO musteri VALUES ('M-01', 'Ayşe Demo', 'İzmir', 1500, 'x'), "
            "('M-02', 'Ali Test', 'Ankara', 250.5, 'y')"
        )
        c.execute(f'GRANT CONNECT ON DATABASE "{ad}" TO {rol}')
        c.execute(f"GRANT SELECT ON musteri TO {rol}")
    url = f"postgresql://{rol}:{parola}@127.0.0.1:{srv.port}/{ad}"
    proje_ayar(DEMOAPP_RO_DATABASE_URL=url)
    from tp_core.features.requirements.settings import get_requirements_settings

    get_requirements_settings.cache_clear()
    try:
        yield ad
    finally:
        get_requirements_settings.cache_clear()
        with srv.super_conn() as c, contextlib.suppress(Exception):
            c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')
            c.execute(f"DROP ROLE IF EXISTS {rol}")


def test_gercek_db_sema_kesfi_ve_muhafiz(engine: Engine, musteri_db: str) -> None:
    calistir = kaynak.db_calistirici()
    kolonlar, satirlar = calistir("SELECT no, ad, kredi FROM musteri ORDER BY no")
    assert kolonlar == ["no", "ad", "kredi"] and satirlar[0][:2] == ("M-01", "Ayşe Demo")
    for sql, mesaj in (
        ("SELECT no, sifre_hash FROM musteri", "kolon"),
        ("SELECT no FROM yok_tablo", "Tablo bulunamadı"),
        ("SELECT no FROM musteri; DELETE FROM musteri", "Tek bir SELECT"),
    ):
        with pytest.raises(kaynak.KaynakHatasi, match=mesaj):
            calistir(sql)
    with session_scope() as s:
        k = kaynak.olustur(
            s,
            {
                "grup": "musteri",
                "sorgu": "SELECT no, ad, kredi FROM musteri ORDER BY no",
                "anahtar_kolonu": "no",
                "deger_kolonlari": [{"kolon": "ad"}, {"kolon": "kredi", "bicim": "tutar"}],
            },
            "analist",
        )
        kid = k.id
    with session_scope() as s:
        sonuc = kaynak.yenile(s, "analist", kaynak_id=kid)
    assert sonuc["toplam"]["eklenen"] == 4, sonuc
    with session_scope() as s:
        assert service.katalog(s)["musteri.m_02.kredi"] == "250,50 TL"


# ------------------------------------------------------------------ demo dışı proje: genel blok


def test_genel_blok_bicimi_ve_sinir() -> None:
    metin = service.genel_blok_satirlari(
        [
            ("musteri.m_01.ad", "musteri", "Ayşe  Demo\nX", False),
            ("ortak.parola", "ortak", None, True),
            ("musteri.m_02.ad", "musteri", "Ali", False),
        ]
    )
    assert metin.splitlines() == [
        service.GENEL_BASLIK,
        "[musteri]",
        "- musteri.m_01.ad = Ayşe Demo X",
        "- musteri.m_02.ad = Ali",
        "[ortak]",
        "- ortak.parola = {veri:ortak.parola} (gizli)",
    ]
    cok = [(f"g.k{i}", "g", "v", False) for i in range(10)]
    sinirli = service.genel_blok_satirlari(cok, max_kayit=4)
    assert sinirli.count("\n- g.") == 4 and sinirli.endswith(
        "6 kayıt daha katalogda (burada gösterilmedi)."
    )
    assert service.genel_blok_satirlari([]).endswith("- Katalogda test verisi yok.")


def test_demo_disi_projede_blok_katalogdan_genel(
    engine: Engine, iki_proje: tuple[str, str], parola_sirri: str, monkeypatch: Any
) -> None:
    a, b = iki_proje
    with proje_icinde(a, kaynak="test"), session_scope() as s:
        service.tohumla(s, seed_sorgu)
    with proje_icinde(b, kaynak="test"):
        with session_scope() as s:
            service.olustur(s, {"anahtar": "musteri.m_01.ad", "deger": "Ayşe Demo"}, "analist")
            service.olustur(
                s,
                {"anahtar": "ortak.parola", "gizli": True, "sir_adi": "TP_TESTVERI_PAROLA_B"},
                "analist",
            )
        for kip in ("replay", "live"):
            monkeypatch.setattr(testdata, "model_kipi", lambda k=kip: k)
            blok = testdata.block()
            assert 'source="testdata:katalog"' in blok or "testdata:katalog" in blok
            assert "- musteri.m_01.ad = Ayşe Demo" in blok
            assert "{veri:ortak.parola} (gizli)" in blok
            for demo in ("bayi1", "P-001", "Demo123!", "Sepete ekle", "Tutar biçimi"):
                assert demo not in blok
        with session_scope() as s:
            assert "musteri.m_01.ad" in testdata.ide_block(s)
    # Demo projesi: bugünkü blok (bayt bayt).
    with proje_icinde(a, kaynak="test"):
        monkeypatch.setattr(testdata, "model_kipi", lambda: "live")
        with session_scope() as s:
            assert service.blok_metni(s) == testdata.build_text(seed_sorgu)


def test_demo_disi_projede_tohum_yok(engine: Engine, iki_proje: tuple[str, str]) -> None:
    from tp_core.features.testveri.jobs import on_worker_start

    _, b = iki_proje
    with proje_icinde(b, kaynak="test"), engine.begin() as c:
        on_worker_start(c)
    with proje_icinde(b, kaynak="test"), session_scope() as s:
        assert not service.anahtarlar(s) and not kaynak.etkin_kaynaklar(s)


def test_katalog_genel_eval_vakalari(tmp_path: Any) -> None:
    """Demo dışı canlı değerlendirme vakaları (ayrı kural kopyası; ana setlere girmez)."""
    from tests.unit.gateway import build_eval_sets as b

    blok = b.katalog_genel_blogu()
    assert "testdata:katalog" in blok and "- tarife.d1.ucret = 95,00 TL" in blok
    assert "{veri:kullanici.gise1.parola} (gizli)" in blok
    assert not any(d in blok for d in b.DEMO_SIZINTISI)
    yollar = b.katalog_genel_kural_kopyasi(tmp_path / "rules")
    assert [p.name for p in yollar] == ["case-generation.json", "design-model.json"]
