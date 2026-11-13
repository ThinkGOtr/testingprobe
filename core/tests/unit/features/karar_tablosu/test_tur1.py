"""012 review turu 1 (tablo şeridi) düzeltmeleri: ilişkinin tablo sürümüne bağlanması, sınır
örnekleri ucu, `evaluate` gövde sınırları, öz onay denetimi, düzenlenmiş AI taslağının korunması,
sınıflandırılmış iş hatası, v3 ileri uyumluluğu. Gerçek Postgres; model çağrısı yok."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.cases.helpers import login, run_jobs
from tests.unit.features.karar_tablosu.test_api import ILISKI, KAMPANYA, Roller
from tests.unit.features.karar_tablosu.test_taslak import CIKTI, _baslat, _nesneler
from tp_core.features.karar_tablosu import jobs as kt_jobs
from tp_core.features.karar_tablosu import service
from tp_core.gateway.testing import text_response
from tp_core.models import KararTablosu, MetamorfikIliski, Requirement, session_scope
from tp_core.workflow.jobs import JobContext, PermanentJobError
from tp_core.workflow.service import Principal

MakeUser = Callable[..., Principal]


@pytest.fixture
def rol(api: TestClient, make_user: MakeUser) -> Roller:
    return Roller(api, make_user)


def _tablo(rol: Roller, rid: uuid.UUID, icerik: dict[str, Any]) -> dict[str, Any]:
    t = rol("analyst").post(f"/requirements/{rid}/decision-tables", json={}).json()
    r = rol("analyst").put(
        f"/decision-tables/{t['id']}", json={"icerik": icerik, "icerik_hash": t["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _onayla(rol: Roller, yol: str, nesne: dict[str, Any]) -> dict[str, Any]:
    assert rol("analyst").post(f"/{yol}/{nesne['id']}/submit").status_code == 200
    r = rol("po").post(f"/{yol}/{nesne['id']}/approve", json={"icerik_hash": nesne["icerik_hash"]})
    assert r.status_code == 200, r.text
    return r.json()


def _iliski(rol: Roller, rid: uuid.UUID, tablo_id: str | None) -> dict[str, Any]:
    govde: dict[str, Any] = {"icerik": ILISKI}
    if tablo_id:
        govde["karar_tablosu_id"] = tablo_id
    r = rol("analyst").post(f"/requirements/{rid}/relations", json=govde)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------- ilişki ↔ tablo sürümü


def test_iliski_tablonun_onaylandigi_surume_baglidir(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _onayla(rol, "decision-tables", _tablo(rol, rid, KAMPANYA))
    i = _onayla(rol, "relations", _iliski(rol, rid, t["id"]))
    with session_scope() as s:
        n = s.get(MetamorfikIliski, uuid.UUID(i["id"]))
        assert service.iliski_tablo_kaydi(s, n) == {
            "id": t["id"],
            "onaylanan_hash": t["onaylanan_hash"],
        }
        assert [str(x.id) for x in service.gecerli_iliskiler(s, rid)] == [i["id"]]

    # Karşı örnek: tablo yeniden açılır, içeriği değişir ve yeniden onaylanır → ilişki bayat.
    rol("analyst").post(f"/decision-tables/{t['id']}/reopen")
    degisik = copy.deepcopy(KAMPANYA)
    degisik["satirlar"][0]["kosul"] = "adet >= 6"
    r = rol("analyst").put(
        f"/decision-tables/{t['id']}", json={"icerik": degisik, "icerik_hash": t["icerik_hash"]}
    )
    t2 = _onayla(rol, "decision-tables", r.json())
    assert t2["onaylanan_hash"] != t["onaylanan_hash"]
    [oge] = rol("tester").get(f"/requirements/{rid}/decision-tables").json()["iliskiler"]
    assert oge["bayat"] is True and "değişmiş" in oge["tablo_engeli"]
    with session_scope() as s:
        assert service.gecerli_iliskiler(s, rid) == []

    # Aynı ilişki yeniden onaylanınca yeni tablo sürümüne bağlanır.
    rol("analyst").post(f"/relations/{i['id']}/reopen")
    i2 = _onayla(rol, "relations", {**i, "icerik_hash": oge["icerik_hash"]})
    assert i2["bayat"] is False and i2["tablo_engeli"] is None
    with session_scope() as s:
        assert [str(x.id) for x in service.gecerli_iliskiler(s, rid)] == [i["id"]]


def test_tablo_yeniden_acilinca_iliski_gecersiz(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _onayla(rol, "decision-tables", _tablo(rol, rid, KAMPANYA))
    _onayla(rol, "relations", _iliski(rol, rid, t["id"]))
    rol("analyst").post(f"/decision-tables/{t['id']}/reopen")
    [oge] = rol("tester").get(f"/requirements/{rid}/decision-tables").json()["iliskiler"]
    assert oge["bayat"] is True and "PO onaylı değil" in oge["tablo_engeli"]
    with session_scope() as s:
        assert service.gecerli_iliskiler(s, rid) == []
    # Aynı içerik yeniden onaylanınca (aynı onaylanan hash) ilişki yeniden geçerli olur.
    _onayla(rol, "decision-tables", t)
    with session_scope() as s:
        assert len(service.gecerli_iliskiler(s, rid)) == 1


def test_tablosuz_iliski_gonderilemez(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    i = _iliski(rol, rid, None)
    r = rol("analyst").post(f"/relations/{i['id']}/submit")
    assert r.status_code == 422 and r.json()["kod"] == "iliski_gecersiz"
    assert any("karar_tablosu_id" in h for h in r.json()["hatalar"])


def test_onaysiz_tabloya_bagli_iliski_onaylanamaz(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    i = _iliski(rol, rid, t["id"])
    assert rol("analyst").post(f"/relations/{i['id']}/submit").status_code == 200
    r = rol("po").post(f"/relations/{i['id']}/approve", json={"icerik_hash": i["icerik_hash"]})
    assert r.status_code == 422 and r.json()["kod"] == "iliski_gecersiz"
    with session_scope() as s:
        assert s.get(MetamorfikIliski, uuid.UUID(i["id"])).durum == "pending_po"


# ---------------------------------------------------------------------- sınır örnekleri ucu


def test_ornekler_ucu_herkese_acik(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    r = rol("tester").get(f"/decision-tables/{t['id']}/ornekler")
    assert r.status_code == 200, r.text
    veri = r.json()
    assert set(veri) == {"ornekler", "uyarilar"}
    adetler = sorted({int(o["girdiler"]["adet"]) for o in veri["ornekler"]})
    assert adetler == [6, 7, 8, 13, 14, 15]
    yedi = next(o for o in veri["ornekler"] if o["girdiler"]["adet"] == "7")
    assert yedi["satir_id"] == "R1" and yedi["ciktilar"]["bedava_adet"] == "1"
    assert rol("tester").get(f"/decision-tables/{uuid.uuid4()}/ornekler").status_code == 404


def test_gonderim_denetimi_sinir_uyarilarini_yazar(
    rol: Roller, make_requirement, engine: Engine
) -> None:
    rid = make_requirement()
    t = copy.deepcopy(KAMPANYA)
    t["satirlar"].insert(1, {"id": "R3", "kosul": "adet >= 14", "cikti": t["satirlar"][0]["cikti"]})
    tablo = _tablo(rol, rid, t)
    assert rol("analyst").post(f"/decision-tables/{tablo['id']}/submit").status_code == 200
    with engine.connect() as c:
        ozet = c.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'karar_tablosu.submitted'")
        ).scalar_one()
    assert "golgede" in ozet["sinir_uyarilari"]


# ---------------------------------------------------------------------- evaluate gövde sınırları


@pytest.mark.parametrize(
    "girdiler",
    [
        {"adet": "7" * 301},
        {f"g{i}": 1 for i in range(25)},
        {"a" * 41: 1},
        {"adet": {"ic": 1}},
        {"adet": [1, 2]},
    ],
)
def test_evaluate_govde_sinirlari(rol: Roller, make_requirement, girdiler: dict) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    r = rol("tester").post(f"/decision-tables/{t['id']}/evaluate", json={"girdiler": girdiler})
    assert r.status_code == 422, r.text


def test_evaluate_sinir_icinde_calisir(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    r = rol("tester").post(
        f"/decision-tables/{t['id']}/evaluate",
        json={"girdiler": {"adet": "7" * 3, "birim_fiyat": "25,00 TL", "fazla": None}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["satir_id"] == "R1"


# ---------------------------------------------------------------------- tolerans (API)


def test_tolerans_tavani_api_422(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = rol("analyst").post(f"/requirements/{rid}/decision-tables", json={}).json()
    kotu = copy.deepcopy(KAMPANYA)
    kotu["ciktilar"][0]["tolerans"] = "1"
    r = rol("analyst").put(
        f"/decision-tables/{t['id']}", json={"icerik": kotu, "icerik_hash": t["icerik_hash"]}
    )
    assert r.status_code == 422 and r.json()["kod"] == "karar_tablosu_gecersiz"
    assert any("ciktilar[0].tolerans" in h for h in r.json()["hatalar"])


# ---------------------------------------------------------------------- öz onay ve son düzenleyen


def _onay_ozeti(engine: Engine, nid: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT ozet FROM audit_event WHERE eylem = 'karar_tablosu.approved' "
                "AND nesne = :n ORDER BY id DESC LIMIT 1"
            ),
            {"n": f"karar_tablosu:{nid}"},
        ).scalar_one()


def test_oz_onay_denetime_yazilir(make_user: MakeUser, make_requirement, engine: Engine) -> None:
    rid = make_requirement()
    analist, po = make_user("analyst"), make_user("po")
    # Çoklu rol: aynı kişi (po) analist olarak düzenler, sonra PO olarak onaylar.
    po_analist = Principal(po.id, po.kullanici_adi, "analyst")
    with session_scope() as s:
        t = service.tablo_olustur(s, rid, analist)
        tid = t.id
        t = service.tablo_guncelle(s, tid, po_analist, KAMPANYA, t.icerik_hash)
        service.gonder(s, service.TABLO, tid, analist)
    with session_scope() as s:
        son = service.son_duzenleyen(s, s.get(KararTablosu, tid))
        assert son == {
            "kullanici_adi": po.kullanici_adi,
            "kullanici_id": str(po.id),
            "eylem": "updated",
        }
        service.onayla(s, service.TABLO, tid, po, s.get(KararTablosu, tid).icerik_hash)
    ozet = _onay_ozeti(engine, tid)
    assert ozet["oz_onay"] is True
    assert ozet["son_duzenleyen"] == po.kullanici_adi
    assert ozet["son_duzenleyen_id"] == str(po.id)


def test_baskasinin_duzenledigi_onay_oz_onay_degil(
    make_user: MakeUser, make_requirement, engine: Engine
) -> None:
    rid = make_requirement()
    analist, po = make_user("analyst"), make_user("po")
    with session_scope() as s:
        t = service.tablo_olustur(s, rid, analist, KAMPANYA)
        tid = t.id
        service.gonder(s, service.TABLO, tid, analist)
    with session_scope() as s:
        service.onayla(s, service.TABLO, tid, po, s.get(KararTablosu, tid).icerik_hash)
    ozet = _onay_ozeti(engine, tid)
    assert "oz_onay" not in ozet
    assert ozet["son_duzenleyen"] == analist.kullanici_adi


# ---------------------------------------------------------------------- AI taslağı


def test_yeni_ai_taslagi_duzenlenmis_taslagi_korur(
    api: TestClient, engine: Engine, make_user: MakeUser, make_requirement, fake_gateway
) -> None:
    fake_gateway([text_response(CIKTI), text_response(CIKTI)])
    rid = make_requirement()
    _baslat(api, make_user, rid)
    run_jobs(engine)
    [ilk, ikinci] = _nesneler(rid, KararTablosu)
    # Analist ilk AI tablosunu düzenler (API ile); ikincisine dokunmaz.
    login(api, make_user("analyst"))
    icerik = copy.deepcopy(ilk.icerik)
    icerik["aciklama"] = "Analist düzeltti"
    r = api.put(
        f"/decision-tables/{ilk.id}", json={"icerik": icerik, "icerik_hash": ilk.icerik_hash}
    )
    assert r.status_code == 200, r.text

    assert api.post(f"/requirements/{rid}/decision-tables/draft").status_code == 202
    ozet = run_jobs(engine)[-1].deger
    assert ozet["korunan"]["karar_tablosu"] == 1
    assert ozet["gecersiz_kilinan"]["karar_tablosu"] == 1
    durum = {t.id: t.durum for t in _nesneler(rid, KararTablosu)}
    assert durum[ilk.id] == "draft" and durum[ikinci.id] == "superseded"


def test_taslak_hatasi_siniflandirilir() -> None:
    assert service.taslak_hatasi(None) is None
    ham = "psycopg.OperationalError: connection to 10.0.0.5 failed (parola=xyz)"
    assert service.taslak_hatasi(ham) == {
        "kod": "ic_hata",
        "mesaj": service.TASLAK_HATALARI["ic_hata"],
    }
    mesaj = service.TASLAK_HATALARI["gereksinim_degisti"]
    assert service.taslak_hatasi(mesaj) == {"kod": "gereksinim_degisti", "mesaj": mesaj}


def test_is_hatasi_denetime_ham_kullaniciya_sinifli(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, make_requirement
) -> None:
    rid = make_requirement()
    ctx = JobContext(uuid.uuid4(), service.DRAFT_JOB, {"requirement_id": str(rid)}, 1, 2, None)

    def patla(*_a: Any, **_k: Any) -> Any:
        raise ValueError("iç ayrıntı: /srv/tp/gizli.py satır 42")

    monkeypatch.setattr(kt_jobs, "taslak_calistir", patla)
    with pytest.raises(RuntimeError) as h:
        kt_jobs.karar_tablosu_taslagi(ctx)
    assert str(h.value) == service.TASLAK_HATALARI["ic_hata"]
    assert "gizli" not in str(h.value)

    def kalici(*_a: Any, **_k: Any) -> Any:
        raise PermanentJobError("gereksinim silinmiş")

    monkeypatch.setattr(kt_jobs, "taslak_calistir", kalici)
    with pytest.raises(PermanentJobError, match="yeniden başlatın"):
        kt_jobs.karar_tablosu_taslagi(ctx)
    with engine.connect() as c:
        kayitlar = (
            c.execute(
                text(
                    "SELECT ozet FROM audit_event WHERE eylem = 'karar_tablosu.draft_failed' "
                    "ORDER BY id"
                )
            )
            .scalars()
            .all()
        )
    assert [k["kod"] for k in kayitlar] == ["ic_hata", "gereksinim_degisti"]
    assert "gizli.py" in kayitlar[0]["hata"]  # ayrıntı yalnız denetimde


def test_son_taslak_ham_hatayi_gostermez(rol: Roller, make_requirement, make_user) -> None:
    rid = make_requirement()
    with session_scope() as s:
        s.execute(
            text(
                "INSERT INTO job (id, tur, yuk, durum, son_hata) "
                "VALUES (:j, :t, '{}', 'failed', :h)"
            ),
            {"j": uuid.uuid4(), "t": service.DRAFT_JOB, "h": "Traceback: /srv/gizli"},
        )
    with session_scope() as s:
        wid = uuid.uuid4()
        jid = s.scalar(text("SELECT id FROM job WHERE tur = :t"), {"t": service.DRAFT_JOB})
        s.execute(
            text(
                "INSERT INTO workflow_instance (id, tur, durum, baslatan, nesne_turu, nesne_id, "
                "job_id) VALUES (:w, :t, 'failed', 'test', 'requirement', :r, :j)"
            ),
            {"w": wid, "t": service.WORKFLOW_TUR, "r": rid, "j": jid},
        )
    son = rol("tester").get(f"/requirements/{rid}/decision-tables").json()["son_taslak"]
    assert son["hata"] == service.TASLAK_HATALARI["ic_hata"]
    assert son["hata_kodu"] == "ic_hata"


# ---------------------------------------------------------------------- v3 ileri uyumluluk


def test_onayli_gereksinim_durumlari_makineyle_sinirli() -> None:
    from tp_core.workflow.states import MACHINES

    durumlar = MACHINES["requirement"].states
    assert {"po_approved", "generating", "cases_ready", "done", "failed"} <= (
        service.ONAYLI_GEREKSINIM
    )
    assert durumlar >= service.ONAYLI_GEREKSINIM
    assert ("modeling" in service.ONAYLI_GEREKSINIM) == ("modeling" in durumlar)


def test_taslak_girdisi_v3_acik_soru_yanitlarini_tasir(make_requirement) -> None:
    rid = make_requirement()
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert service.acik_soru_yanitlari(s, req) == ""  # yanıtlı soru yokken boş
        [m] = service.taslak_mesajlari(req, (), "Q1 — Soru: tam 750'de?\nPO yanıtı: uyarı yok")
        assert "PO'nun açık soru yanıtları" in m.content and "tam 750'de?" in m.content
        assert ":po-acik-soru" in m.content
        [bos] = service.taslak_mesajlari(req, ())
        assert "açık soru" not in bos.content


def test_yanitli_acik_soru_taslak_mesajinda_gorunur(make_requirement) -> None:
    """012 ANALIZ §14.6: v3'ün yanıtlanmış açık sorusu (`acik_soru`, güncel PO onaylı içerik)
    karar tablosu taslağının model girdisine girer; bekleyen soru girmez."""
    from tp_core.features.cases.acik_sorular import generation_input
    from tp_core.models.acik_soru import AcikSoru

    rid = make_requirement()
    with session_scope() as s:
        req = s.get(Requirement, rid)
        h = req.onaylanan_hash or ""
        ortak = {"requirement_id": rid, "gereksinim_hash": h, "gonderen": "tester"}
        s.add(
            AcikSoru(
                tur="soru",
                etiket="Q1",
                kaynak_id="Q1",
                metin="Tam 750,00 TL'de minimum uyarısı gösterilir mi?",
                metin_hash="h-q1",
                durum="yanitlandi",
                yanit="Hayır: uyarı yalnız 750,00 TL'nin altında.",
                yanit_yazari="po",
                **ortak,
            )
        )
        s.add(
            AcikSoru(
                tur="soru",
                etiket="Q2",
                kaynak_id="Q2",
                metin="BEKLEYEN-SORU-METNI",
                metin_hash="h-q2",
                **ortak,
            )
        )
        s.flush()
        metin = service.acik_soru_yanitlari(s, req)
        assert metin == generation_input(s, req)
        [m] = service.taslak_mesajlari(req, service._onaylanan_sorular(s, rid), metin)
    assert "Tam 750,00 TL'de minimum uyarısı gösterilir mi?" in m.content
    assert "Hayır: uyarı yalnız 750,00 TL'nin altında." in m.content
    assert ":po-acik-soru" in m.content
    assert "BEKLEYEN-SORU-METNI" not in m.content
