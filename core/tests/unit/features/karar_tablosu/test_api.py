"""012 Ş1: karar tablosu ve metamorfik ilişki uçları — roller, geçişler (yasak olanlar dahil),
iyimser eşzamanlılık, doğrulama hataları, bayatlama, oracle kancası ve okuma yardımcıları.
Gerçek Postgres + gerçek API (TestClient); model çağrısı yok."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.unit.features.cases.helpers import login
from tp_core.features.karar_tablosu import service
from tp_core.models import KararTablosu, Requirement, session_scope
from tp_core.workflow.service import Principal

MakeUser = Callable[..., Principal]

KAMPANYA = {
    "ad": "Kampanya: 7 adette 1 bedava",
    "ac_refs": ["AC2"],
    "girdiler": [
        {"ad": "adet", "tur": "sayi"},
        {"ad": "birim_fiyat", "tur": "sayi", "birim": "TL"},
    ],
    "ciktilar": [
        {"ad": "bedava_adet", "tur": "sayi"},
        {"ad": "indirim", "tur": "sayi", "birim": "TL", "tolerans": "0.01"},
    ],
    "satirlar": [
        {
            "id": "R1",
            "kosul": "adet >= 7",
            "cikti": {"bedava_adet": "adet // 7", "indirim": "(adet // 7) * birim_fiyat"},
        },
        {"id": "R2", "kosul": "dogru", "cikti": {"bedava_adet": "0", "indirim": "0"}},
    ],
}
MINIMUM = {
    "ad": "Minimum sipariş",
    "ac_refs": ["AC3"],
    "girdiler": [{"ad": "tutar", "tur": "sayi"}],
    "ciktilar": [{"ad": "uyari", "tur": "mantiksal"}],
    "satirlar": [{"id": "R1", "kosul": "tutar < 750", "cikti": {"uyari": "dogru"}}],
}
ILISKI = {
    "ad": "Adet iki katı",
    "ac_refs": ["AC2"],
    "on_kosul": "adet >= 7 ve adet % 7 == 0",
    "donusum": {"adet": "adet * 2"},
    "iliski": {"bedava_adet": "bedava_adet * 2"},
}


class Roller:
    """Rol başına ayrı oturumlu istemci (aynı uygulama)."""

    def __init__(self, api: TestClient, make_user: MakeUser) -> None:
        self.api = api
        self.users = {rol: make_user(rol) for rol in ("analyst", "po", "tester", "engineer")}
        self._aktif: str | None = None

    def __call__(self, rol: str) -> TestClient:
        if self._aktif != rol:
            self.api.cookies.clear()
            login(self.api, self.users[rol])
            self._aktif = rol
        return self.api


@pytest.fixture
def rol(api: TestClient, make_user: MakeUser) -> Roller:
    return Roller(api, make_user)


def _tablo(rol: Roller, rid: uuid.UUID, icerik: dict[str, Any] | None = None) -> dict[str, Any]:
    r = rol("analyst").post(f"/requirements/{rid}/decision-tables", json={})
    assert r.status_code == 201, r.text
    t = r.json()
    if icerik is not None:
        r = rol("analyst").put(
            f"/decision-tables/{t['id']}", json={"icerik": icerik, "icerik_hash": t["icerik_hash"]}
        )
        assert r.status_code == 200, r.text
        t = r.json()
    return t


def _onayli(rol: Roller, rid: uuid.UUID, icerik: dict[str, Any]) -> dict[str, Any]:
    t = _tablo(rol, rid, icerik)
    assert rol("analyst").post(f"/decision-tables/{t['id']}/submit").status_code == 200
    r = rol("po").post(
        f"/decision-tables/{t['id']}/approve", json={"icerik_hash": t["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _isler(tur: str) -> list[Any]:
    with session_scope() as s:
        return list(
            s.execute(
                text("SELECT yuk, idempotency_key FROM job WHERE tur = :t ORDER BY olusturma"),
                {"t": tur},
            ).all()
        )


# ---------------------------------------------------------------------- tam akış ve roller


def test_tam_akis_analist_duzenler_po_onaylar(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid)
    assert t["durum"] == "draft" and t["sira_no"] == 1 and t["ai_generated"] is False
    assert t["icerik"] == service.bos_tablo() and t["bayat"] is False
    assert t["onaylayan"] is None and t["son_karar"] is None

    r = rol("analyst").put(
        f"/decision-tables/{t['id']}", json={"icerik": KAMPANYA, "icerik_hash": t["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["icerik"] == KAMPANYA

    r = rol("analyst").post(f"/decision-tables/{t['id']}/submit", json={})
    assert r.status_code == 200 and r.json()["durum"] == "pending_po"

    r = rol("po").post(
        f"/decision-tables/{t['id']}/approve", json={"icerik_hash": t["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["durum"] == "approved" and t["onaylanan_hash"] == t["icerik_hash"]
    assert t["onaylayan"] == rol.users["po"].kullanici_adi and t["onay_zamani"]
    assert t["son_karar"]["karar"] == "approve"

    liste = rol("tester").get(f"/requirements/{rid}/decision-tables").json()
    assert [x["id"] for x in liste["tablolar"]] == [t["id"]]
    assert liste["iliskiler"] == [] and liste["son_taslak"] is None
    with session_scope() as s:
        kt = s.get(KararTablosu, uuid.UUID(t["id"]))
        req = s.get(Requirement, rid)
        assert kt.gereksinim_hash == service.content_hash_of(req)
        eylemler = [
            e
            for (e,) in s.execute(
                text("SELECT eylem FROM audit_event WHERE nesne = :n ORDER BY id"),
                {"n": f"karar_tablosu:{t['id']}"},
            ).all()
        ]
    for fiil in ("created", "updated", "submitted", "approved"):
        assert f"karar_tablosu.{fiil}" in eylemler


@pytest.mark.parametrize("yetkisiz", ["tester", "engineer", "po"])
def test_analist_uclari_baska_role_403(rol: Roller, make_requirement, yetkisiz: str) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    c = rol(yetkisiz)
    assert c.post(f"/requirements/{rid}/decision-tables", json={}).status_code == 403
    assert c.post(f"/requirements/{rid}/decision-tables/draft").status_code == 403
    assert c.post(f"/requirements/{rid}/relations", json={"icerik": ILISKI}).status_code == 403
    govde = {"icerik": KAMPANYA, "icerik_hash": t["icerik_hash"]}
    assert c.put(f"/decision-tables/{t['id']}", json=govde).status_code == 403
    for eylem in ("submit", "withdraw", "reopen"):
        assert c.post(f"/decision-tables/{t['id']}/{eylem}").status_code == 403


@pytest.mark.parametrize("yetkisiz", ["analyst", "tester", "engineer"])
def test_po_uclari_baska_role_403(rol: Roller, make_requirement, yetkisiz: str) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    rol("analyst").post(f"/decision-tables/{t['id']}/submit")
    c = rol(yetkisiz)
    govde = {"icerik_hash": t["icerik_hash"], "gerekce": "neden"}
    assert c.post(f"/decision-tables/{t['id']}/approve", json=govde).status_code == 403
    assert c.post(f"/decision-tables/{t['id']}/request-changes", json=govde).status_code == 403


def test_okuma_ve_deneme_herkese_acik(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    for r_ in ("tester", "engineer", "po"):
        c = rol(r_)
        assert c.get(f"/requirements/{rid}/decision-tables").status_code == 200
        r = c.post(
            f"/decision-tables/{t['id']}/evaluate",
            json={"girdiler": {"adet": 7, "birim_fiyat": "25,00 TL"}},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {
            "satir_id": "R1",
            "ciktilar": {"bedava_adet": "1", "indirim": "25.00"},
            "eksik_girdiler": [],
            "hata": None,
        }
    # Kaydedilmemiş içerikle önizleme; kayıt değişmez.
    r = rol("tester").post(
        f"/decision-tables/{t['id']}/evaluate",
        json={"girdiler": {"tutar": 500}, "icerik": MINIMUM},
    )
    assert r.json()["ciktilar"] == {"uyari": True}
    eksik = rol("tester").post(f"/decision-tables/{t['id']}/evaluate", json={"girdiler": {}})
    assert eksik.json()["eksik_girdiler"] == ["adet", "birim_fiyat"]
    assert (
        rol("tester")
        .get(f"/requirements/{rid}/decision-tables")
        .json()["tablolar"][0]["icerik_hash"]
        == t["icerik_hash"]
    )


def test_oturumsuz_401(api: TestClient, make_requirement) -> None:
    rid = make_requirement()
    assert api.get(f"/requirements/{rid}/decision-tables").status_code == 401


# ---------------------------------------------------------------------- geçişler


def test_geri_cek_degisiklik_iste_yeniden_ac(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    tid = t["id"]
    rol("analyst").post(f"/decision-tables/{tid}/submit")
    r = rol("analyst").post(f"/decision-tables/{tid}/withdraw")
    assert r.status_code == 200 and r.json()["durum"] == "draft"

    rol("analyst").post(f"/decision-tables/{tid}/submit")
    r = rol("po").post(
        f"/decision-tables/{tid}/request-changes", json={"icerik_hash": t["icerik_hash"]}
    )
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_karar"
    r = rol("po").post(
        f"/decision-tables/{tid}/request-changes",
        json={"icerik_hash": t["icerik_hash"], "gerekce": "  R2 eşiği AC2'yle uyuşmuyor  "},
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["durum"] == "draft" and t["onaylayan"] is None
    assert t["son_karar"]["karar"] == "request_changes"
    assert t["son_karar"]["gerekce"] == "R2 eşiği AC2'yle uyuşmuyor"
    assert t["son_karar"]["kullanici"] == rol.users["po"].kullanici_adi

    t = _onayli_mevcut(rol, tid, t["icerik_hash"])
    r = rol("analyst").post(f"/decision-tables/{tid}/reopen")
    assert r.status_code == 200
    t = r.json()
    assert t["durum"] == "draft" and t["onaylanan_hash"] is None and t["onaylayan"] is None


def _onayli_mevcut(rol: Roller, tid: str, h: str) -> dict[str, Any]:
    assert rol("analyst").post(f"/decision-tables/{tid}/submit").status_code == 200
    r = rol("po").post(f"/decision-tables/{tid}/approve", json={"icerik_hash": h})
    assert r.status_code == 200, r.text
    return r.json()


def test_yasak_gecisler_409(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    tid, h = t["id"], t["icerik_hash"]
    # draft: onay / değişiklik isteği / geri çekme / yeniden açma yok
    r = rol("po").post(f"/decision-tables/{tid}/approve", json={"icerik_hash": h})
    assert r.status_code == 409 and r.json()["kod"] == "eszamanli_gecis"
    r = rol("po").post(
        f"/decision-tables/{tid}/request-changes", json={"icerik_hash": h, "gerekce": "x"}
    )
    assert r.status_code == 409
    assert rol("analyst").post(f"/decision-tables/{tid}/withdraw").status_code == 409
    assert rol("analyst").post(f"/decision-tables/{tid}/reopen").status_code == 409
    # Başarısız onay denemesi review kaydı bırakmaz (işlem geri alınır).
    with session_scope() as s:
        n = s.scalar(text("SELECT count(*) FROM review WHERE nesne_id = :i"), {"i": tid})
    assert n == 0
    # pending_po: içerik değişmez, yeniden gönderilmez, yeniden açılmaz
    rol("analyst").post(f"/decision-tables/{tid}/submit")
    r = rol("analyst").put(f"/decision-tables/{tid}", json={"icerik": MINIMUM, "icerik_hash": h})
    assert r.status_code == 409 and r.json()["kod"] == "cakisma"
    assert rol("analyst").post(f"/decision-tables/{tid}/submit").status_code == 409
    assert rol("analyst").post(f"/decision-tables/{tid}/reopen").status_code == 409
    # approved: gönder / geri çek yok, içerik değişmez
    rol("po").post(f"/decision-tables/{tid}/approve", json={"icerik_hash": h})
    assert rol("analyst").post(f"/decision-tables/{tid}/submit").status_code == 409
    assert rol("analyst").post(f"/decision-tables/{tid}/withdraw").status_code == 409
    r = rol("analyst").put(f"/decision-tables/{tid}", json={"icerik": MINIMUM, "icerik_hash": h})
    assert r.status_code == 409
    r = rol("po").post(f"/decision-tables/{tid}/approve", json={"icerik_hash": h})
    assert r.status_code == 409


def test_onay_gorulen_hash_ister(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    rol("analyst").post(f"/decision-tables/{t['id']}/submit")
    r = rol("po").post(f"/decision-tables/{t['id']}/approve", json={"icerik_hash": "eski"})
    assert r.status_code == 409 and r.json()["kod"] == "onay_hash_uyusmuyor"
    r = rol("po").post(f"/decision-tables/{t['id']}/approve", json={})
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_karar"


def test_bilinmeyen_kayit_404(rol: Roller, make_requirement) -> None:
    yok = uuid.uuid4()
    assert rol("analyst").post(f"/decision-tables/{yok}/submit").status_code == 404
    assert rol("analyst").post(f"/relations/{yok}/withdraw").status_code == 404
    assert rol("analyst").post(f"/requirements/{yok}/decision-tables", json={}).status_code == 404
    assert rol("tester").get(f"/requirements/{yok}/decision-tables").status_code == 404


# ---------------------------------------------------------------------- içerik ve eşzamanlılık


def test_eski_hashle_guncelleme_409(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid)
    ilk = t["icerik_hash"]
    r = rol("analyst").put(
        f"/decision-tables/{t['id']}", json={"icerik": KAMPANYA, "icerik_hash": ilk}
    )
    assert r.status_code == 200
    r = rol("analyst").put(
        f"/decision-tables/{t['id']}", json={"icerik": MINIMUM, "icerik_hash": ilk}
    )
    assert r.status_code == 409 and r.json()["kod"] == "onay_hash_uyusmuyor"
    r = rol("analyst").put(f"/decision-tables/{t['id']}", json={"icerik": MINIMUM})
    assert r.status_code == 422


def test_gecersiz_icerik_hata_listesiyle_422(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid)
    bozuk = {
        **KAMPANYA,
        "satirlar": [
            {"id": "R1", "kosul": "adet >= ", "cikti": {"bedava_adet": "0", "indirim": "0"}},
            {"id": "R2", "kosul": "dogru", "cikti": {"bedava_adet": '"yedi"'}},
        ],
    }
    r = rol("analyst").put(
        f"/decision-tables/{t['id']}", json={"icerik": bozuk, "icerik_hash": t["icerik_hash"]}
    )
    assert r.status_code == 422
    govde = r.json()
    assert govde["kod"] == "karar_tablosu_gecersiz"
    assert isinstance(govde["hatalar"], list) and len(govde["hatalar"]) >= 2
    assert any("R1" in h and "koşul" in h for h in govde["hatalar"])
    assert any("çıktı eksik: indirim" in h for h in govde["hatalar"])
    # İçerik değişmedi.
    liste = rol("analyst").get(f"/requirements/{rid}/decision-tables").json()
    assert liste["tablolar"][0]["icerik_hash"] == t["icerik_hash"]
    r = rol("analyst").post(f"/requirements/{rid}/decision-tables", json={"icerik": {"ad": ""}})
    assert r.status_code == 422 and r.json()["hatalar"]


def test_eksik_tablo_gonderilemez(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid)
    r = rol("analyst").post(f"/decision-tables/{t['id']}/submit")
    assert r.status_code == 422
    assert r.json()["kod"] == "karar_tablosu_gecersiz"
    assert set(r.json()["hatalar"]) == {
        "ac_refs: en az bir kabul kriteri olmalı",
        "girdiler: en az bir girdi olmalı",
        "ciktilar: en az bir çıktı olmalı",
        "satirlar: en az bir satır olmalı",
    }
    r = rol("analyst").post(f"/decision-tables/{t['id']}/submit", json={"icerik_hash": "eski"})
    assert r.status_code == 409


def test_onaysiz_gereksinimde_tablo_acilmaz(rol: Roller, make_requirement) -> None:
    rid = make_requirement(po_onayli=False)
    r = rol("analyst").post(f"/requirements/{rid}/decision-tables", json={})
    assert r.status_code == 409 and "PO onaylı" in r.json()["detail"]
    assert rol("analyst").post(f"/requirements/{rid}/decision-tables/draft").status_code == 409
    r = rol("analyst").post(f"/requirements/{rid}/relations", json={"icerik": ILISKI})
    assert r.status_code == 409


def test_sira_no_artar_ve_yeniden_kullanilmaz(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    a = _tablo(rol, rid)
    b = _tablo(rol, rid)
    with session_scope() as s:
        service.gecersiz_kil(s, s.get(KararTablosu, uuid.UUID(b["id"])), "test")
    c = _tablo(rol, rid)
    assert (a["sira_no"], b["sira_no"], c["sira_no"]) == (1, 2, 3)
    liste = rol("analyst").get(f"/requirements/{rid}/decision-tables").json()
    assert [t["sira_no"] for t in liste["tablolar"]] == [1, 3]
    tumu = rol("analyst").get(f"/requirements/{rid}/decision-tables?tumu=true").json()
    assert [t["durum"] for t in tumu["tablolar"]] == ["draft", "superseded", "draft"]


# ------------------------------------------------------------ bayatlama, okuma yardımcıları


def _gereksinimi_degistir(rid: uuid.UUID) -> None:
    with session_scope() as s:
        req = s.get(Requirement, rid)
        req.aciklama = (req.aciklama or "") + " (değişti)"


def test_gereksinim_degisince_tablo_bayat(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _onayli(rol, rid, KAMPANYA)
    taslak = _tablo(rol, rid, MINIMUM)
    with session_scope() as s:
        assert [x.id for x in service.gecerli_tablolar(s, rid)] == [uuid.UUID(t["id"])]
    _gereksinimi_degistir(rid)
    liste = rol("tester").get(f"/requirements/{rid}/decision-tables").json()
    durum = {x["id"]: (x["durum"], x["bayat"]) for x in liste["tablolar"]}
    assert durum == {t["id"]: ("approved", True), taslak["id"]: ("draft", False)}
    with session_scope() as s:
        assert service.gecerli_tablolar(s, rid) == []
        kt = s.get(KararTablosu, uuid.UUID(t["id"]))
        assert service.bayat_mi(kt, s.get(Requirement, rid)) is True
    # Değişen (onayı güncel olmayan) gereksinimde düzenleme ve onay da yapılmaz.
    r = rol("analyst").put(
        f"/decision-tables/{taslak['id']}",
        json={"icerik": KAMPANYA, "icerik_hash": taslak["icerik_hash"]},
    )
    assert r.status_code == 409


def test_gecerli_tablolar_ac_suzgeci_ve_sira(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t1 = _onayli(rol, rid, KAMPANYA)
    t2 = _onayli(rol, rid, MINIMUM)
    _tablo(rol, rid, {**KAMPANYA, "ac_refs": ["AC2", "AC3"]})  # taslak: hiçbir zaman dönmez
    t4 = _onayli(rol, rid, {**MINIMUM, "ac_refs": ["AC1", "AC3"]})
    rol("analyst").post(f"/decision-tables/{t4['id']}/reopen")
    with session_scope() as s:
        ids = lambda xs: [str(x.id) for x in xs]  # noqa: E731
        assert ids(service.gecerli_tablolar(s, rid)) == [t1["id"], t2["id"]]
        assert ids(service.gecerli_tablolar(s, rid, ["AC3"])) == [t2["id"]]
        assert ids(service.gecerli_tablolar(s, rid, ("AC2", "AC3"))) == [t1["id"], t2["id"]]
        assert ids(service.gecerli_tablolar(s, rid, ["AC9"])) == []
        assert ids(service.gecerli_tablolar(s, rid, [])) == []
        assert service.gecerli_tablolar(s, uuid.uuid4()) == []


def test_onay_ve_yeniden_acma_oracle_isini_kuyruga_ekler(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _onayli(rol, rid, KAMPANYA)
    isler = _isler(service.ORACLE_JOB)
    assert len(isler) == 1
    yuk, anahtar = isler[0]
    assert yuk == {"requirement_id": str(rid), "neden": "tablo_onaylandi"}
    assert anahtar.startswith(f"oracle.check_requirement:{rid}:{t['id']}:tablo_onaylandi:")
    rol("analyst").post(f"/decision-tables/{t['id']}/reopen")
    isler = _isler(service.ORACLE_JOB)
    assert len(isler) == 2
    assert isler[1][0] == {"requirement_id": str(rid), "neden": "tablo_degisti"}
    assert isler[1][1].startswith(f"oracle.check_requirement:{rid}:{t['id']}:tablo_degisti:")
    # Birleştirme: aynı içeriğin yeniden onayı ve ikinci yeniden açma da iş açar (anahtar olay
    # başına tekil; önceki `…:acik` / `…:<hash>` anahtarı bunları yutuyordu).
    h = rol("analyst").post(f"/decision-tables/{t['id']}/submit").json()["icerik_hash"]
    r = rol("po").post(f"/decision-tables/{t['id']}/approve", json={"icerik_hash": h})
    assert r.status_code == 200, r.text
    rol("analyst").post(f"/decision-tables/{t['id']}/reopen")
    isler = _isler(service.ORACLE_JOB)
    assert [y["neden"] for y, _ in isler] == [
        "tablo_onaylandi",
        "tablo_degisti",
        "tablo_onaylandi",
        "tablo_degisti",
    ]
    assert len({a for _, a in isler}) == 4
    # Geri çekme / değişiklik isteği / ilişki onayı kontrolü tetiklemez.
    n = _tablo(rol, rid, MINIMUM)
    rol("analyst").post(f"/decision-tables/{n['id']}/submit")
    rol("analyst").post(f"/decision-tables/{n['id']}/withdraw")
    assert len(_isler(service.ORACLE_JOB)) == 4


# ---------------------------------------------------------------------- metamorfik ilişki


def test_iliski_akisi_ve_tablo_bagi(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    t = _tablo(rol, rid, KAMPANYA)
    r = rol("analyst").post(
        f"/requirements/{rid}/relations",
        json={"icerik": {**ILISKI, "tablo_ref": "T9"}, "karar_tablosu_id": t["id"]},
    )
    assert r.status_code == 201, r.text
    i = r.json()
    assert i["tur"] == "metamorfik_iliski" and i["sira_no"] == 1
    assert i["karar_tablosu_id"] == t["id"]
    assert i["icerik"]["tablo_ref"] == "T1"  # yetkili bağdan yazılır

    # Bağlı tablonun kolonlarında olmayan ad → 422, hata listesi
    bozuk = {**ILISKI, "iliski": {"ara_tutar": "ara_tutar * 2"}}
    r = rol("analyst").put(
        f"/relations/{i['id']}", json={"icerik": bozuk, "icerik_hash": i["icerik_hash"]}
    )
    assert r.status_code == 422 and r.json()["kod"] == "iliski_gecersiz"
    assert any("ara_tutar" in h for h in r.json()["hatalar"])
    # Bağ kaldırılınca aynı içerik (yalnız sözdizimi denetlenir) geçerlidir.
    r = rol("analyst").put(
        f"/relations/{i['id']}",
        json={"icerik": bozuk, "icerik_hash": i["icerik_hash"], "karar_tablosu_id": None},
    )
    assert r.status_code == 200, r.text
    i = r.json()
    assert i["karar_tablosu_id"] is None and "tablo_ref" not in i["icerik"]
    # Alan gönderilmezse bağ korunur.
    r = rol("analyst").put(
        f"/relations/{i['id']}",
        json={"icerik": ILISKI, "icerik_hash": i["icerik_hash"], "karar_tablosu_id": t["id"]},
    )
    i = r.json()
    r = rol("analyst").put(
        f"/relations/{i['id']}", json={"icerik": ILISKI, "icerik_hash": i["icerik_hash"]}
    )
    assert r.json()["karar_tablosu_id"] == t["id"]
    i = r.json()

    assert rol("analyst").post(f"/relations/{i['id']}/submit").status_code == 200
    r = rol("po").post(f"/relations/{i['id']}/approve", json={"icerik_hash": i["icerik_hash"]})
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "approved"
    assert r.json()["onaylayan"] == rol.users["po"].kullanici_adi
    with session_scope() as s:
        assert [str(x.id) for x in service.gecerli_iliskiler(s, rid)] == [i["id"]]
    assert _isler(service.ORACLE_JOB) == []  # ilişki onayı tablo kontrolü değildir
    r = rol("analyst").post(f"/relations/{i['id']}/reopen")
    assert r.json()["durum"] == "draft"
    rol("analyst").post(f"/relations/{i['id']}/submit")
    r = rol("po").post(
        f"/relations/{i['id']}/request-changes",
        json={"icerik_hash": i["icerik_hash"], "gerekce": "AC2 dışı"},
    )
    assert r.json()["durum"] == "draft" and r.json()["son_karar"]["gerekce"] == "AC2 dışı"
    rol("analyst").post(f"/relations/{i['id']}/submit")
    assert rol("analyst").post(f"/relations/{i['id']}/withdraw").json()["durum"] == "draft"

    liste = rol("tester").get(f"/requirements/{rid}/decision-tables").json()
    assert [x["id"] for x in liste["iliskiler"]] == [i["id"]]


def test_iliski_dogrulama_ve_baska_gereksinimin_tablosu(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    diger = make_requirement(jira_key="TPD-77")
    yabanci = _tablo(rol, diger, KAMPANYA)
    r = rol("analyst").post(
        f"/requirements/{rid}/relations",
        json={"icerik": ILISKI, "karar_tablosu_id": yabanci["id"]},
    )
    assert r.status_code == 422 and r.json()["kod"] == "iliski_gecersiz"
    r = rol("analyst").post(
        f"/requirements/{rid}/relations", json={"icerik": {**ILISKI, "on_kosul": "adet >"}}
    )
    assert r.status_code == 422 and any("on_kosul" in h for h in r.json()["hatalar"])
    r = rol("analyst").post(f"/requirements/{rid}/relations", json={"icerik": {"ad": "x"}})
    assert r.status_code == 422 and len(r.json()["hatalar"]) >= 1
    # AC'siz ilişki taslak olarak kaydedilir ama PO'ya gönderilemez.
    r = rol("analyst").post(
        f"/requirements/{rid}/relations", json={"icerik": {**ILISKI, "ac_refs": []}}
    )
    assert r.status_code == 201
    r = rol("analyst").post(f"/relations/{r.json()['id']}/submit")
    assert r.status_code == 422 and r.json()["hatalar"] == [
        "ac_refs: en az bir kabul kriteri olmalı"
    ]


def test_iliski_bayatlar(rol: Roller, make_requirement) -> None:
    rid = make_requirement()
    r = rol("analyst").post(f"/requirements/{rid}/relations", json={"icerik": ILISKI})
    i = r.json()
    rol("analyst").post(f"/relations/{i['id']}/submit")
    rol("po").post(f"/relations/{i['id']}/approve", json={"icerik_hash": i["icerik_hash"]})
    _gereksinimi_degistir(rid)
    liste = rol("tester").get(f"/requirements/{rid}/decision-tables").json()
    assert liste["iliskiler"][0]["bayat"] is True
    with session_scope() as s:
        assert service.gecerli_iliskiler(s, rid) == []
        assert s.scalars(select(KararTablosu)).all() == []
