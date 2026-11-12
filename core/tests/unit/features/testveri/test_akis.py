"""Akış kancaları: üretim/IDE eşlemesi, düzeltmede bilinmeyen atıf, serileştirme, yayın (Y4)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.cases.helpers import case_icerik, latest_cases, login, run_jobs
from tp_core.audit import content_hash
from tp_core.features.cases.service import submit_drafts
from tp_core.features.publish import service as publish
from tp_core.features.testveri import service
from tp_core.gateway.testing import text_response
from tp_core.integrations.testmgmt import CaseContent, case_description_text
from tp_core.models import TestCase, session_scope
from tp_core.models.otomasyon_feature import TestVerisi
from tp_core.workflow.service import Principal

from .conftest import DEMO_PAROLA

PAROLA_ATFI = "{veri:ortak.demo_parola}"
BAYI_ATFI = "{veri:bayi.bayi1.kullanici_adi}"


def _uret(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, cases):
    fake_gateway([text_response({"cases": cases})])
    rid = make_requirement()
    analist = make_user("analyst")
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    return rid, analist


def test_katalog_bossa_eslesme_yok(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    assert c["icerik"] == case_icerik() and c["icerik_hash"] == content_hash(case_icerik())
    assert c["veri"] == {}


def test_case_uretimi_eslenir_hash_eslenmis_icerikten(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    ham = case_icerik()
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [ham])
    (c,) = latest_cases(api, rid)
    adim = c["icerik"]["steps"][1]
    assert c["icerik"]["preconditions"] == [f"{BAYI_ATFI} kullanıcısı tanımlı"]
    assert adim["data"] == f"{BAYI_ATFI} / {PAROLA_ATFI}"
    assert DEMO_PAROLA not in str(c["icerik"])
    assert c["icerik"]["title"] == ham["title"]  # başlık değer kalır
    assert c["icerik_hash"] == content_hash(c["icerik"]) != content_hash(ham)
    # Serileştirme: atıf → değer (gizli → null), sürüm, var.
    assert c["veri"] == {
        "bayi.bayi1.kullanici_adi": {"deger": "bayi1", "gizli": False, "surum": 1, "var": True},
        "ortak.demo_parola": {"deger": None, "gizli": True, "surum": 1, "var": True},
    }  # K18: `etiket.*` (ör. "Katalog") eşlenmez, metinde değer kalır
    assert "Katalog" in str(c["icerik"]["steps"])
    # Çözüm bugünkü metne döner; veri_izi değer özetidir (gizli için de).
    with session_scope() as s:
        cozulmus, izi = service.case_coz(s, c["icerik"])
    assert cozulmus == ham
    assert izi == {
        "bayi.bayi1.kullanici_adi": service.deger_ozeti("bayi1"),
        "ortak.demo_parola": service.deger_ozeti(DEMO_PAROLA),
    }
    assert all(len(v) == 12 for v in izi.values())


def test_ayni_icerik_yeniden_uretimde_tekrar_sayilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    """Katalogdan önce yazılmış (eşlenmemiş) onaylı case'in aynısı yeni taslak olarak düşmez."""
    with session_scope() as s:
        for k in s.scalars(select(TestVerisi)):
            k.silindi = True  # katalog "yokken" üret
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    assert c["veri"] == {}
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    with session_scope() as s:
        for k in s.scalars(select(TestVerisi)):
            k.silindi = False
    fake_gateway([text_response({"cases": [case_icerik()]})])
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.deger["case_sayisi"] == 0 and is_.deger["tekrar"] == [1]


def test_ide_taslaklari_da_eslenir(engine: Engine, make_user, make_requirement, katalog) -> None:
    make_requirement()
    analist = make_user("analyst")
    ide = Principal(analist.id, analist.kullanici_adi, "analyst", kanal="ide", kapsam="submit")
    with session_scope() as s:
        sonuc = submit_drafts(s, "TPD-4", [case_icerik()], ide)
    (e,) = sonuc["eklenen"]
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(e["case_id"]))
        assert tc.icerik["steps"][1]["data"] == f"{BAYI_ATFI} / {PAROLA_ATFI}"
        assert tc.icerik_hash == content_hash(tc.icerik)


def test_parola_sirri_yoksa_parola_eslenmez(
    api: TestClient,
    engine: Engine,
    make_user,
    make_requirement,
    fake_gateway,
    katalog,
    monkeypatch,
) -> None:
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI)
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    assert c["icerik"]["steps"][1]["data"] == f"{BAYI_ATFI} / {DEMO_PAROLA}"


def _duzelt(api: TestClient, c: dict[str, Any], icerik: dict[str, Any]):
    return api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "edit", "icerik_hash": c["icerik_hash"], "icerik": icerik},
    )


def test_duzeltmede_bilinmeyen_atif_422_duz_deger_kalir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    yeni = dict(c["icerik"], expected_result="{veri:bayi.yok.ad} kataloğu açılır")
    r = _duzelt(api, c, yeni)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Katalogda olmayan test verisi anahtarı: bayi.yok.ad")

    # Bilinen atıf eklenebilir; analistin yazdığı düz değer eşlenmez.
    yeni = dict(
        c["icerik"], expected_result="{veri:bayi.bayi1.ad} kataloğu açılır; Sahil Bayi değil"
    )
    r = _duzelt(api, c, yeni)
    assert r.status_code == 200, r.text
    (c2,) = latest_cases(api, rid)
    assert c2["icerik"]["expected_result"] == yeni["expected_result"]
    assert c2["veri"]["bayi.bayi1.ad"]["deger"] == "Merkez Bayi"


def test_katalog_degisince_onay_dusmez_veri_guncel(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )
    assert r.status_code == 200
    k = next(x for x in api.get("/test-data").json() if x["anahtar"] == "bayi.bayi1.kullanici_adi")
    r = api.put(f"/test-data/{k['id']}", json={"deger": "bayi1x", "beklenen_surum": 1})
    assert r.status_code == 200
    (c2,) = latest_cases(api, rid)
    assert c2["durum"] == "approved" and c2["icerik_hash"] == c["icerik_hash"]
    # K10 case yarısı: onay anındaki veri izine göre değişen anahtar.
    assert c2["veri_onaydan_sonra_degisen"] == ["bayi.bayi1.kullanici_adi"]
    assert c2["veri"]["bayi.bayi1.kullanici_adi"] == {
        "deger": "bayi1x",
        "gizli": False,
        "surum": 2,
        "var": True,
    }


def test_yayinda_gizli_atif_korunur_digerleri_cozulur(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        mapping = publish.case_mapping(s, tc)
    assert mapping["steps"][1]["data"] == f"bayi1 / {PAROLA_ATFI}"
    assert mapping["preconditions"] == ["bayi1 kullanıcısı tanımlı"]
    metin = case_description_text(CaseContent.from_mapping(mapping), "TPD-4")
    assert PAROLA_ATFI in metin and DEMO_PAROLA not in metin and BAYI_ATFI not in metin
    # Önizleme (gönderilen gövdeyle aynı) da gizliyi açmaz.
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )
    assert r.status_code == 200
    on = api.get("/publish/preview", params={"requirement_id": str(rid)})
    assert on.status_code == 200 and DEMO_PAROLA not in on.text


def test_yayinda_duz_gizli_deger_tum_alanlarda_maskelenir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    """K19: başlıkta / etiketlerde / analistin düz yazdığı parola yayına `•••` gider."""
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        icerik = dict(tc.icerik)
        icerik["title"] = f"bayi1 / {DEMO_PAROLA} ile giriş"
        icerik["tags"] = [DEMO_PAROLA]
        icerik["expected_result"] = f"Parola {DEMO_PAROLA} kabul edilir"
        tc.icerik = icerik
    with session_scope() as s:
        mapping = publish.case_mapping(s, s.get(TestCase, uuid.UUID(c["id"])))
    assert DEMO_PAROLA not in str(mapping)
    assert mapping["title"] == "bayi1 / ••• ile giriş" and mapping["tags"] == ["•••"]
    assert mapping["expected_result"] == "Parola ••• kabul edilir"
    assert mapping["steps"][1]["data"] == f"bayi1 / {PAROLA_ATFI}"  # atıf yine atıf


def test_gizliyle_ayni_degerli_kayit_reddedilir_aciklama_temizlenir(
    api: TestClient, make_user, katalog
) -> None:
    login(api, make_user("analyst"))
    r = api.post("/test-data", json={"anahtar": "ortak.kopya", "deger": DEMO_PAROLA})
    assert r.status_code == 422 and "gizli" in r.json()["detail"]
    liste = {x["anahtar"]: x for x in api.get("/test-data").json()}
    k = liste["bayi.bayi1.ad"]
    r = api.put(f"/test-data/{k['id']}", json={"deger": DEMO_PAROLA, "beklenen_surum": 1})
    assert r.status_code == 422
    # Boş açıklama açıklamayı temizler; yanıt kullanım sayısını taşır.
    r = api.put(f"/test-data/{k['id']}", json={"aciklama": "", "beklenen_surum": 1})
    assert r.status_code == 200, r.text
    assert r.json()["aciklama"] == "" and r.json()["surum"] == 2
    assert r.json()["kullanim"] == 0


def test_eslemeden_sonra_silinen_anahtar_atfi_duz_icerige_doner(
    engine: Engine, make_requirement, katalog, monkeypatch
) -> None:
    """Silme yarışı: eşleme kataloğu okunduktan sonra silinen anahtara atıf yazılmaz."""
    from tp_core.features.cases import service as cases_service
    from tp_core.models import Requirement

    gercek = service.eslem_katalogu

    def eslem_sonra_sil(s):  # eşleme kataloğu okunur, ardından kayıt silinir
        kat = gercek(s)
        k = s.scalars(
            select(TestVerisi).where(TestVerisi.anahtar == "bayi.bayi1.kullanici_adi")
        ).one()
        k.silindi = True
        s.flush()
        return kat

    monkeypatch.setattr(service, "eslem_katalogu", eslem_sonra_sil)
    rid = make_requirement()
    with session_scope() as s:
        req = s.get(Requirement, rid)
        (tc,), _ = cases_service.store_cases(
            s, req, [case_icerik()], uretim_no=1, kanal="portal", ai_call_id=None, uretim_modu=None
        )
        assert "bayi.bayi1.kullanici_adi" not in str(tc.icerik)
        assert tc.icerik == case_icerik() and tc.icerik_hash == content_hash(case_icerik())


def test_onay_veri_izi_yazilir_degisen_anahtar_listelenir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog
) -> None:
    """K10 case yarısı: approve/edit anında atıflanan anahtarların değer özeti review'a yazılır;
    yalnız onaylı case'te güncel özetle farklı olanlar `veri_onaydan_sonra_degisen`'de."""
    from tp_core.models import Review

    ikinci = case_icerik(title="Hatalı parola mesajı", ref="AC2", type="negative")
    rid, _ = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik(), ikinci])
    a, b = latest_cases(api, rid)
    assert a["veri_onaydan_sonra_degisen"] == [] and b["veri_onaydan_sonra_degisen"] == []
    r = api.post(
        f"/cases/{a['id']}/decision", json={"karar": "approve", "icerik_hash": a["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["veri_onaydan_sonra_degisen"] == []
    yeni = dict(b["icerik"], expected_result="{veri:bayi.bayi1.ad} kataloğu açılır")
    assert _duzelt(api, b, yeni).status_code == 200
    with session_scope() as s:
        izler = {
            str(rv.nesne_id): rv.duzeltme_olculeri["veri_izi"]
            for rv in s.scalars(select(Review).where(Review.nesne_turu == "test_case"))
        }
    assert set(izler[a["id"]]) == {"bayi.bayi1.kullanici_adi", "ortak.demo_parola"}
    assert DEMO_PAROLA not in str(izler)
    assert "bayi.bayi1.ad" in izler[b["id"]]

    kayitlar = {x["anahtar"]: x for x in api.get("/test-data").json()}
    k = kayitlar["bayi.bayi1.ad"]
    r = api.put(f"/test-data/{k['id']}", json={"deger": "Merkez Bayi 2", "beklenen_surum": 1})
    assert r.status_code == 200, r.text
    son = {x["id"]: x for x in latest_cases(api, rid)}
    assert son[a["id"]]["veri_onaydan_sonra_degisen"] == []
    assert son[b["id"]]["veri_onaydan_sonra_degisen"] == ["bayi.bayi1.ad"]
    # Açıklama değişimi "veri değişti" saymaz.
    k = kayitlar["bayi.bayi1.kullanici_adi"]
    r = api.put(f"/test-data/{k['id']}", json={"aciklama": "yeni açıklama", "beklenen_surum": 1})
    assert r.status_code == 200, r.text
    assert latest_cases(api, rid)[0]["veri_onaydan_sonra_degisen"] == []

    # Taslağa alınan case uyarı taşımaz (onaylı değil); yeniden onay izi tazeler.
    r = api.post(
        f"/cases/{b['id']}/decision",
        json={"karar": "reopen", "icerik_hash": son[b["id"]]["icerik_hash"]},
    )
    assert r.status_code == 200, r.text
    b2 = next(x for x in latest_cases(api, rid) if x["id"] == b["id"])
    assert b2["veri_onaydan_sonra_degisen"] == []
    r = api.post(
        f"/cases/{b['id']}/decision", json={"karar": "approve", "icerik_hash": b2["icerik_hash"]}
    )
    assert r.status_code == 200 and r.json()["veri_onaydan_sonra_degisen"] == []
