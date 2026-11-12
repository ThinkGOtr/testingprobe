"""Katalog: CRUD + sürüm + 409'lar + roller + gizli değer, tohum, `testdata.block()` (013 §3.3)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.cases.helpers import case_icerik, latest_cases, login, run_jobs
from tp_core.features.cases import testdata
from tp_core.features.testveri import service
from tp_core.gateway.testing import text_response
from tp_core.models import session_scope
from tp_core.models.otomasyon_feature import TestVerisi, TestVerisiSurum

from .conftest import DEMO_PAROLA, seed_sorgu


def _denetim(engine: Engine, eylem: str) -> list[dict[str, Any]]:
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT ozet FROM audit_event WHERE eylem = :e ORDER BY id"), {"e": eylem}
            ).scalars()
        )


# ------------------------------------------------------------------------- CRUD + roller


def test_crud_surum_ve_denetim(api: TestClient, engine: Engine, make_user) -> None:
    login(api, make_user("analyst"))
    r = api.post(
        "/test-data",
        json={"anahtar": "bayi.bayi9.kullanici_adi", "deger": "bayi9", "aciklama": "Yeni bayi"},
    )
    assert r.status_code == 201, r.text
    k = r.json()
    assert k["surum"] == 1 and k["grup"] == "bayi" and k["deger"] == "bayi9"
    assert k["gizli"] is False and k["sir_tanimli"] is False and k["kullanim"] == 0

    # Anahtar çakışması 409; geçersiz anahtar 422.
    assert api.post("/test-data", json={"anahtar": k["anahtar"], "deger": "x"}).status_code == 409
    r = api.post("/test-data", json={"anahtar": "Buyuk Harf", "deger": "x"})
    assert r.status_code == 422 and "Anahtar" in r.json()["detail"]

    # Güncelleme: beklenen sürüm uyuşmazlığı 409; doğru sürümle +1.
    r = api.put(f"/test-data/{k['id']}", json={"deger": "bayi99", "beklenen_surum": 7})
    assert r.status_code == 409 and "sürüm" in r.json()["detail"]
    r = api.put(f"/test-data/{k['id']}", json={"deger": "bayi99", "beklenen_surum": 1})
    assert r.status_code == 200, r.text
    assert r.json()["surum"] == 2 and r.json()["deger"] == "bayi99"
    r = api.put(f"/test-data/{k['id']}", json={"deger": "bayi99", "beklenen_surum": 2})
    assert r.status_code == 422  # değişiklik yok

    # Silme: sürüm zorunlu ve eşleşmeli; yumuşak silme.
    assert api.delete(f"/test-data/{k['id']}", params={"beklenen_surum": 1}).status_code == 409
    r = api.delete(f"/test-data/{k['id']}", params={"beklenen_surum": 2})
    assert r.status_code == 200 and r.json() == {
        "id": k["id"],
        "anahtar": k["anahtar"],
        "silindi": True,
        "surum": 3,
    }
    assert all(x["id"] != k["id"] for x in api.get("/test-data").json())
    with session_scope() as s:
        assert s.get(TestVerisi, __import__("uuid").UUID(k["id"])).silindi is True

    gecmis = api.get(f"/test-data/{k['id']}/history").json()
    assert [(g["surum"], g["islem"], g["deger"]) for g in gecmis] == [
        (3, "sil", "bayi99"),
        (2, "guncelle", "bayi99"),
        (1, "olustur", "bayi9"),
    ]
    assert [o["anahtar"] for o in _denetim(engine, "testveri.olustur")] == [k["anahtar"]]
    (g,) = _denetim(engine, "testveri.guncelle")
    assert g["deger"] == "bayi99" and g["onceki_deger"] == "bayi9" and g["surum"] == 2
    assert len(_denetim(engine, "testveri.sil")) == 1

    # Silinmiş anahtar yeniden oluşturulunca aynı kayıt yeni sürümle etkinleşir.
    r = api.post("/test-data", json={"anahtar": k["anahtar"], "deger": "bayi7"})
    assert r.status_code == 201 and r.json()["id"] == k["id"] and r.json()["surum"] == 4


@pytest.mark.parametrize("rol", ["tester", "po", "presenter"])
def test_duzenleme_yalniz_analist_ve_muhendis(api: TestClient, make_user, rol: str) -> None:
    login(api, make_user("engineer"))
    k = api.post("/test-data", json={"anahtar": "ayar.x", "deger": "1"}).json()
    login(api, make_user(rol))
    assert api.get("/test-data").status_code == 200
    assert api.get(f"/test-data/{k['id']}/history").status_code == 200
    assert api.post("/test-data", json={"anahtar": "ayar.y", "deger": "1"}).status_code == 403
    r = api.put(f"/test-data/{k['id']}", json={"deger": "2", "beklenen_surum": 1})
    assert r.status_code == 403
    assert api.delete(f"/test-data/{k['id']}", params={"beklenen_surum": 1}).status_code == 403


def test_oturumsuz_okuma_yok(api: TestClient) -> None:
    assert api.get("/test-data").status_code == 401


def test_gizli_kayit_degeri_donmez(
    api: TestClient, engine: Engine, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(api, make_user("analyst"))
    # Gizli kayıtta değer yazılamaz; sır adı TP_TESTVERI_ önekli olmalı (başka süreç sırrı değil).
    r = api.post(
        "/test-data",
        json={"anahtar": "ortak.p", "gizli": True, "deger": "x", "sir_adi": "TP_TESTVERI_P"},
    )
    assert r.status_code == 422
    for sir in ("ANTHROPIC_API_KEY", "TP_SESSION_SECRET", "tp_testveri_p", None):
        r = api.post("/test-data", json={"anahtar": "ortak.p", "gizli": True, "sir_adi": sir})
        assert r.status_code == 422, sir
    govde = {"anahtar": "ortak.d", "deger": "x", "sir_adi": "TP_TESTVERI_P"}
    r = api.post("/test-data", json=govde)
    assert r.status_code == 422  # gizli olmayan kayıtta sır adı yok

    r = api.post(
        "/test-data", json={"anahtar": "ortak.p", "gizli": True, "sir_adi": "TP_TESTVERI_P"}
    )
    assert r.status_code == 201, r.text
    k = r.json()
    assert k["deger"] is None and k["sir_tanimli"] is False
    monkeypatch.setenv("TP_TESTVERI_P", "Cok-Gizli-1")
    (liste,) = [x for x in api.get("/test-data").json() if x["id"] == k["id"]]
    assert liste["sir_tanimli"] is True and liste["deger"] is None
    assert (
        api.put(f"/test-data/{k['id']}", json={"deger": "acik", "beklenen_surum": 1}).status_code
        == 422
    )
    r = api.put(f"/test-data/{k['id']}", json={"sir_adi": "TP_TESTVERI_Q", "beklenen_surum": 1})
    assert r.status_code == 200 and r.json()["sir_tanimli"] is False
    gecmis = api.get(f"/test-data/{k['id']}/history").json()
    assert all(g["deger"] is None and g["gizli"] for g in gecmis)
    # Sır değeri hiçbir yanıta / denetime / sürüm kaydına yazılmadı.
    with engine.connect() as c:
        dokum = str(c.execute(text("SELECT array_agg(ozet::text) FROM audit_event")).scalar())
        dokum += str(c.execute(text("SELECT array_agg(deger) FROM test_verisi_surum")).scalar())
    assert "Cok-Gizli-1" not in dokum and "Cok-Gizli-1" not in api.get("/test-data").text


def test_silme_atif_yapan_etkin_case_varsa_409_listeli(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    fake_gateway([text_response({"cases": [case_icerik()]})])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    (c,) = latest_cases(api, rid)
    liste = {x["anahtar"]: x for x in api.get("/test-data").json()}
    bayi = liste["bayi.bayi1.kullanici_adi"]
    assert bayi["kullanim"] == 1 and liste["urun.p_002.kod"]["kullanim"] == 0
    r = api.delete(f"/test-data/{bayi['id']}", params={"beklenen_surum": bayi["surum"]})
    assert r.status_code == 409, r.text
    govde = r.json()
    assert govde["kod"] == "cakisma" and "atıf" in govde["detail"]
    assert govde["kullanan"] == [
        {"case_id": c["id"], "case_ref": "TPD-4-C1", "requirement_id": str(rid),
         "baslik": c["icerik"]["title"], "durum": "draft"}
    ]  # fmt: skip
    assert _denetim(engine, "testveri.sil") == []
    # Kullanılmayan kayıt silinebilir.
    p2 = liste["urun.p_002.kod"]
    assert api.delete(f"/test-data/{p2['id']}", params={"beklenen_surum": 1}).status_code == 200


# --------------------------------------------------------------------------- tohum + blok


def test_tohumla_idempotent_ve_anahtar_semasi(engine: Engine, parola_sirri: str) -> None:
    with session_scope() as s:
        n = service.tohumla(s, seed_sorgu)
    with session_scope() as s:
        assert service.tohumla(s, seed_sorgu) == 0
        kat = service.katalog(s)
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "ortak.demo_parola")).one()
        surumler = s.scalars(select(TestVerisiSurum)).all()
    assert n == len(kat) + 1 == len(surumler)
    assert kat["bayi.bayi1.kullanici_adi"] == "bayi1"
    assert kat["bayi.bayi1.ad"] == "Merkez Bayi"
    assert kat["bayi.bayi2.kredi_limiti"] == "500,00 TL"
    assert kat["urun.p_004.ad"] == "Şeftalili Soğuk Çay 1L"
    assert kat["urun.p_001.fiyat"] == "25,00 TL"
    assert kat["kampanya.k_6al1.kod"] == "K-6AL1" and kat["kampanya.k_6al1.ad"] == "6 al 1 bedava"
    assert kat["ayar.min_siparis_tutari"] == "750.00"
    assert kat["etiket.siparisi_onayla"] == "Siparişi onayla"
    assert DEMO_PAROLA not in kat.values()
    assert k.gizli and k.deger is None and k.sir_adi == "TP_TESTVERI_DEMO_PAROLA"
    assert len(_denetim(engine, "testveri.tohumla")) == 1


def test_tohum_demo_db_yoksa_sabitlerle_sinirli_sonra_tamamlanir(engine: Engine) -> None:
    def bozuk(_sql: str) -> Any:
        raise RuntimeError("demo db yok")

    with session_scope() as s:
        n = service.tohumla(s, bozuk)
    with session_scope() as s:
        anahtarlar = service.anahtarlar(s)
    assert n == 1 + len(testdata.UI_ETIKETLERI)
    assert all(a.startswith(("ortak.", "etiket.")) for a in anahtarlar)
    # Worker açılışı (demo DB okunur) eksikleri ekler; analistin değişikliğine dokunmaz.
    with session_scope() as s:
        k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "etiket.katalog")).one()
        service.guncelle(s, k.id, {"deger": "Ürünler"}, 1, "analist")
    with session_scope() as s:
        assert service.tohumla(s, seed_sorgu) > 10
        assert service.katalog(s)["etiket.katalog"] == "Ürünler"


def test_on_worker_start_tohumlar(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.features.testveri import jobs

    testdata.set_query_factory(lambda: seed_sorgu)
    try:
        with engine.begin() as conn:
            jobs.on_worker_start(conn)
        with engine.begin() as conn:
            jobs.on_worker_start(conn)
    finally:
        testdata.set_query_factory(None)
    with session_scope() as s:
        assert "bayi.bayi2.ad" in service.katalog(s)
    assert len(_denetim(engine, "testveri.tohumla")) == 1


def _kip(monkeypatch: pytest.MonkeyPatch, kip: str) -> None:
    monkeypatch.setattr(testdata, "model_kipi", lambda: kip)


def test_block_katalogdan_ayni_metin(
    engine: Engine, katalog, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Katalog demo DB'yle aynıyken her kipte blok birebir aynı (replay anahtarları korunur)."""
    testdata.set_query_factory(lambda: seed_sorgu)
    try:
        eski = testdata.block()
        with session_scope() as s:
            assert service.blok_metni(s) == testdata.build_text(seed_sorgu)
            for kip in ("replay", "live", "record"):
                _kip(monkeypatch, kip)
                with caplog.at_level(logging.WARNING):
                    assert testdata.block(s) == eski
        assert "kurulamadı" not in caplog.text
    finally:
        testdata.set_query_factory(None)


def test_block_k17_live_katalogdan_replay_demo_dbden(
    engine: Engine, katalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K17: live/record'da değişen değer ve yeni kayıtlar modele gider; replay'de DB bloğu."""
    testdata.set_query_factory(lambda: seed_sorgu)
    try:
        eski = testdata.block()
        with session_scope() as s:
            k = s.scalars(select(TestVerisi).where(TestVerisi.anahtar == "urun.p_001.fiyat")).one()
            service.guncelle(s, k.id, {"deger": "26,00 TL"}, 1, "analist")
            for anahtar, deger in (
                ("bayi.bayi9.kullanici_adi", "bayi9"),
                ("bayi.bayi9.ad", "Dağ Bayi"),
                ("bayi.bayi9.kredi_limiti", "2.000,00 TL"),
                ("urun.p_009.kod", "P-009"),  # eksik alanlı ürün: "Diğer" bölümüne
                ("musteri.vergi_no", "1234567890"),
                ("ayar.yeni_esik", "10"),
            ):
                service.olustur(s, {"anahtar": anahtar, "deger": deger}, "analist")
        with session_scope() as s:
            _kip(monkeypatch, "replay")
            assert testdata.block(s) == eski
            for kip in ("live", "record"):
                _kip(monkeypatch, kip)
                blok = testdata.block(s)
                assert blok != eski
                assert '- P-001 · "Portakal Gazozu 1L" · 26,00 TL' in blok
                assert "25,00 TL" not in blok.split("Uygulama ayarları")[0]
                assert '- bayi9 / Demo123! — bayi adı "Dağ Bayi", kredi limiti 2.000,00 TL' in blok
                assert "- yeni_esik = 10" in blok
                assert "Diğer test verileri (anahtar = değer):" in blok
                assert "- urun.p_009.kod = P-009" in blok
                assert "- musteri.vergi_no = 1234567890" in blok
            # Biçim kuralları aynı: bölüm sırası ve son satırlar.
            metin = service.blok_metni(s)
            assert metin is not None
            assert metin.splitlines()[:2] == testdata.build_text(seed_sorgu).splitlines()[:2]
            assert metin.endswith("Tutar biçimi: 1.250,00 TL (tr-TR, iki ondalık).")
    finally:
        testdata.set_query_factory(None)


def test_block_live_katalog_kurulamazsa_demo_db(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_scope() as s:
        service.tohumla(s, seed_sorgu)
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI, raising=False)
    _kip(monkeypatch, "live")
    testdata.set_query_factory(lambda: seed_sorgu)
    try:
        with session_scope() as s:
            assert testdata.block(s) == testdata.block()
    finally:
        testdata.set_query_factory(None)


def test_block_parola_sirri_yoksa_eski_yol(engine: Engine, monkeypatch) -> None:
    with session_scope() as s:
        service.tohumla(s, seed_sorgu)
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI, raising=False)
    testdata.set_query_factory(lambda: seed_sorgu)
    try:
        with session_scope() as s:
            assert service.blok_metni(s) is None
            assert testdata.block(s) == testdata.block()
    finally:
        testdata.set_query_factory(None)
