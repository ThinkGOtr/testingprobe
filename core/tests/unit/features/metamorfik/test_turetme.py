"""012 Ş6: ilişki tabanlı ek case türetme servisi ve uçları (ANALIZ §4.5, §6; senaryo 15–16).

Gerçek Postgres; oracle kontrol kayıtları (Ş2'nin ürettiği) testte doğrudan yazılır. Model çağrısı
yoktur.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text

from tests.unit.features.cases.helpers import login
from tests.unit.features.metamorfik.ornek import ILISKI, TABLO, ayrintilar, case_icerik, grup
from tp_core.audit import content_hash
from tp_core.features.cases import service as cases_service
from tp_core.features.cases.schema import content_errors
from tp_core.features.karar_tablosu.hatalar import IliskiGecersiz
from tp_core.features.metamorfik import service
from tp_core.features.metamorfik.iliskiler import gecerli_iliskiler
from tp_core.models import (
    CaseOracleKontrol,
    KararTablosu,
    MetamorfikIliski,
    MetamorfikTuretme,
    Requirement,
    TestCase,
    case_id,
    session_scope,
)
from tp_core.workflow.service import SYSTEM, Principal, content_hash_of, record_approval, transition

ACS = [
    "AC1: Sepet satır tutarı adet ile birim fiyatın çarpımıdır.",
    "AC2: P-001'den 7 alana 1 bedava verilir.",
]


@dataclass
class Kurulum:
    rid: uuid.UUID
    kaynaklar: list[uuid.UUID]
    iliski_id: uuid.UUID
    tablo_id: uuid.UUID
    analist: Principal
    po: Principal


def _iliski_ekle(
    s: Any, req: Requirement, tablo: KararTablosu, icerik: dict, sira: int, onay: str | None
) -> MetamorfikIliski:
    n = MetamorfikIliski(
        requirement_id=req.id,
        karar_tablosu_id=tablo.id,
        sira_no=sira,
        icerik=icerik,
        icerik_hash=content_hash(icerik),
    )
    s.add(n)
    s.flush()
    if onay in ("pending_po", "approved"):
        transition(s, n, "pending_po", SYSTEM, "draft")
    return n


def _onayla(s: Any, n: MetamorfikIliski, req: Requirement, po: Principal) -> None:
    record_approval(s, n, po, "approve", beklenen_hash=content_hash_of(n))
    transition(s, n, "approved", po, "pending_po")
    n.gereksinim_hash = content_hash_of(req)


@pytest.fixture
def kur(engine: Engine, make_user: Callable[..., Principal], make_requirement: Callable[..., Any]):
    def _kur(
        *,
        iliski: dict | None = None,
        iliski_durum: str = "approved",
        kaynak_sayisi: int = 1,
        oracle: bool = True,
        icerik: dict | None = None,
        hazir: bool = True,
    ) -> Kurulum:
        analist, po = make_user("analyst"), make_user("po")
        rid = make_requirement(
            jira_key=f"TPD-{uuid.uuid4().int % 90000 + 100}",
            baslik="Sepet tutarı",
            aciklama="Bayi sepetinde satır tutarı ve kampanya",
            acs=ACS,
        )
        with session_scope() as s:
            req = s.get(Requirement, rid)
            if hazir:
                transition(s, req, "generating", SYSTEM, "po_approved")
                transition(s, req, "cases_ready", SYSTEM, "generating")
            icerikler = []
            for i in range(kaynak_sayisi):
                c = copy.deepcopy(icerik or case_icerik())
                c["title"] = c["title"] + (f" #{i + 1}" if i else "")
                icerikler.append(c)
            eklenen, tekrar = cases_service.store_cases(
                s, req, icerikler, uretim_no=1, kanal="portal", ai_call_id=None,
                uretim_modu="replay",
            )  # fmt: skip
            assert not tekrar
            tablo = KararTablosu(
                requirement_id=rid, sira_no=1, icerik=TABLO, icerik_hash=content_hash(TABLO)
            )
            s.add(tablo)
            s.flush()
            n = _iliski_ekle(s, req, tablo, iliski or ILISKI, 1, iliski_durum)
            if iliski_durum == "approved":
                _onayla(s, n, req, po)
            if oracle:
                for tc in eklenen:
                    s.add(
                        CaseOracleKontrol(
                            test_case_id=tc.id,
                            icerik_hash=tc.icerik_hash,
                            sonuc="uyumlu",
                            ayrintilar=ayrintilar(grup(tablo_id=str(tablo.id))),
                            tablo_hashleri={str(tablo.id): tablo.icerik_hash},
                            ai_icerik=True,
                            uretim_modu="replay",
                        )
                    )
            return Kurulum(rid, [tc.id for tc in eklenen], n.id, tablo.id, analist, po)

    return _kur


def _turet(k: Kurulum, case_ids: list[uuid.UUID] | None = None, **kw: Any) -> dict[str, Any]:
    with session_scope() as s:
        return service.turet(s, k.rid, kw.get("iliski_id", k.iliski_id), case_ids, k.analist)


def _case_sayisi(engine: Engine, rid: uuid.UUID) -> int:
    with engine.connect() as c:
        return c.execute(
            select(func.count()).select_from(TestCase).where(TestCase.requirement_id == rid)
        ).scalar_one()


def _turetmeler(k: Kurulum) -> list[MetamorfikTuretme]:
    with session_scope() as s:
        return list(
            s.scalars(select(MetamorfikTuretme).where(MetamorfikTuretme.iliski_id == k.iliski_id))
        )


# ---------------------------------------------------------------------- senaryo 15


def test_adet_iki_kati_turetilir(kur: Callable[..., Kurulum]) -> None:
    k = kur()
    with session_scope() as s:
        kaynak = s.get(TestCase, k.kaynaklar[0])
        once = (copy.deepcopy(kaynak.icerik), kaynak.icerik_hash, kaynak.durum, kaynak.guncelleme)

    sonuc = _turet(k)

    assert sonuc["atlanan"] == []
    [t] = sonuc["turetilen"]
    assert t["kaynak_case_id"] == str(k.kaynaklar[0])
    assert t["baslik"] == "Kampanyasız üründe satır tutarı (P-004) (ilişki: Adet iki katı)"
    with session_scope() as s:
        req = s.get(Requirement, k.rid)
        yeni = s.get(TestCase, uuid.UUID(t["case_id"]))
        assert yeni.id == case_id(req, 2, 1)
        assert (yeni.durum, yeni.uretim_no, yeni.sira_no) == ("draft", 1, 2)
        assert (yeni.kanal, yeni.uretim_modu) == ("portal", "replay")
        assert yeni.ai_generated is False and yeni.ai_call_id is None
        assert yeni.icerik_hash == content_hash(yeni.icerik)
        assert yeni.icerik["steps"][1]["data"] == "50"
        assert yeni.icerik["steps"][1]["expected"] == "Sepette 50 adet P-004 görünür"
        assert yeni.icerik["steps"][2]["expected"] == "Satır tutarı 1.500,00 TL görünür"
        assert yeni.icerik["expected_result"] == "Ara toplam 1.500,00 TL olarak gösterilir"
        assert yeni.icerik["preconditions"][1] == "P-004 birim fiyatı 30,00 TL"
        assert "metamorfik" in yeni.icerik["tags"]
        assert content_errors(yeni.icerik, req.kabul_kriterleri) == []
        # Kaynak case'e dokunulmaz.
        kaynak = s.get(TestCase, k.kaynaklar[0])
        assert (kaynak.icerik, kaynak.icerik_hash, kaynak.durum, kaynak.guncelleme) == once
    [satir] = _turetmeler(k)
    assert (satir.sonuc, satir.neden) == ("turetildi", None)
    assert satir.turetilen_case_id == uuid.UUID(t["case_id"])
    assert satir.kaynak_case_id == k.kaynaklar[0]
    assert satir.olusturan_id == k.analist.id


def test_olay_denetim_ve_oracle_isi(
    kur: Callable[..., Kurulum], engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    k = kur()
    olaylar: list[tuple[str, dict]] = []
    monkeypatch.setattr(service, "publish_tx", lambda _c, ad, veri: olaylar.append((ad, veri)))
    [t] = _turet(k)["turetilen"]
    yeni_id = uuid.UUID(t["case_id"])
    assert olaylar == [
        (
            "case.generated",
            {
                "id": yeni_id,
                "requirement_id": k.rid,
                "title": t["baslik"],
                "kanal": "portal",
                "mode": "replay",
                "metamorfik": True,
            },
        )
    ]
    with engine.connect() as c:
        isler = c.execute(
            text("SELECT yuk, idempotency_key FROM job WHERE tur = 'oracle.check_requirement'")
        ).all()
        denetim = c.execute(
            text("SELECT aktor, nesne, ozet FROM audit_event WHERE eylem = 'metamorfik.derived'")
        ).all()
    assert len(isler) == 1
    assert isler[0].yuk == {"requirement_id": str(k.rid), "neden": "metamorfik"}
    assert str(k.iliski_id) in isler[0].idempotency_key
    assert str(yeni_id) in isler[0].idempotency_key
    assert len(denetim) == 1
    assert denetim[0].aktor == k.analist.kullanici_adi
    assert denetim[0].nesne == f"metamorfik_iliski:{k.iliski_id}"
    assert denetim[0].ozet["turetilen"][0]["case_id"] == str(yeni_id)


# ---------------------------------------------------------------------- senaryo 16


def test_on_kosul_saglanmazsa_case_yazilmaz(
    kur: Callable[..., Kurulum], engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    k = kur(iliski={**ILISKI, "on_kosul": "adet >= 500"})
    olaylar: list[Any] = []
    monkeypatch.setattr(service, "publish_tx", lambda *a: olaylar.append(a))
    sonuc = _turet(k)
    assert sonuc["turetilen"] == []
    [a] = sonuc["atlanan"]
    assert (a["kaynak_case_id"], a["sonuc"]) == (str(k.kaynaklar[0]), "iliski_gecersiz")
    assert "Ön koşul" in a["neden"]
    assert _case_sayisi(engine, k.rid) == 1
    [satir] = _turetmeler(k)
    assert (satir.sonuc, satir.turetilen_case_id) == ("iliski_gecersiz", None)
    assert olaylar == []
    with engine.connect() as c:
        assert not c.execute(text("SELECT 1 FROM job WHERE tur='oracle.check_requirement'")).all()
        # Denetim kaydı denemeyi yine tutar.
        assert (
            c.execute(
                text("SELECT count(*) FROM audit_event WHERE eylem = 'metamorfik.derived'")
            ).scalar_one()
            == 1
        )


# ---------------------------------------------------------------------- atlamalar


def test_oracle_kaydi_yoksa_olgu_yok_sonra_yeniden_denenir(
    kur: Callable[..., Kurulum], engine: Engine
) -> None:
    k = kur(oracle=False)
    [a] = _turet(k)["atlanan"]
    assert a["sonuc"] == "olgu_yok"
    [ilk] = _turetmeler(k)
    assert _case_sayisi(engine, k.rid) == 1
    # Kontrol sonradan gelir: aynı çift yeniden değerlendirilir, satır güncellenir.
    with session_scope() as s:
        tc = s.get(TestCase, k.kaynaklar[0])
        s.add(
            CaseOracleKontrol(
                test_case_id=tc.id,
                icerik_hash=tc.icerik_hash,
                sonuc="uyumlu",
                ayrintilar=ayrintilar(grup(tablo_id=str(k.tablo_id))),
            )
        )
    sonuc = _turet(k)
    assert len(sonuc["turetilen"]) == 1 and sonuc["atlanan"] == []
    [satir] = _turetmeler(k)
    assert satir.id == ilk.id and satir.sonuc == "turetildi" and satir.neden is None


def test_eski_icerigin_kontrolu_ve_baska_tablonun_grubu_sayilmaz(
    kur: Callable[..., Kurulum],
) -> None:
    k = kur(oracle=False)
    with session_scope() as s:
        tc = s.get(TestCase, k.kaynaklar[0])
        s.add(
            CaseOracleKontrol(
                test_case_id=tc.id,
                icerik_hash="eski-icerik-hash",
                sonuc="uyumlu",
                ayrintilar=ayrintilar(grup(tablo_id=str(k.tablo_id))),
            )
        )
        s.add(
            CaseOracleKontrol(
                test_case_id=tc.id,
                icerik_hash=tc.icerik_hash,
                sonuc="uyumlu",
                ayrintilar=ayrintilar(grup(tablo_id=str(uuid.uuid4()))),
            )
        )
    [a] = _turet(k)["atlanan"]
    assert a["sonuc"] == "olgu_yok"
    assert "doğrulanmış olgu yok" in a["neden"]


def test_belirsiz_alinti(kur: Callable[..., Kurulum], engine: Engine) -> None:
    icerik = case_icerik()
    icerik["steps"][1]["data"] = "25, ardından 125"
    icerik["steps"][1]["expected"] = "Sepette 25 adet P-004 görünür (25 TL kargo)"
    k = kur(icerik=icerik)
    # steps[1].expected'te aynı "25" alıntısı hem adet (→ 50) hem kargo (değişmez) olgusunun.
    with session_scope() as s:
        kontrol = s.scalars(
            select(CaseOracleKontrol).where(CaseOracleKontrol.test_case_id == k.kaynaklar[0])
        ).one()
        a = copy.deepcopy(kontrol.ayrintilar)
        a["gruplar"][0]["girdiler"].append(
            {"column": "kargo", "value": "25", "field": "steps[1].expected", "quote": "25"}
        )
        kontrol.ayrintilar = a
    [at] = _turet(k)["atlanan"]
    assert at["sonuc"] == "belirsiz_alinti"
    assert _case_sayisi(engine, k.rid) == 1
    assert _turetmeler(k)[0].sonuc == "belirsiz_alinti"


def test_turetilen_icerik_denetimden_gecmeli(kur: Callable[..., Kurulum], engine: Engine) -> None:
    icerik = case_icerik()
    icerik["tags"] = ["sepet"]  # şema "AI-generated" etiketini ister; kaynak zaten bozuk
    k = kur(icerik=icerik)
    [a] = _turet(k)["atlanan"]
    assert a["sonuc"] == "iliski_gecersiz"
    assert "içerik denetiminden geçmedi" in a["neden"]
    assert _case_sayisi(engine, k.rid) == 1


# ---------------------------------------------------------------------- idempotentlik ve sıra


def test_ayni_cift_ikinci_kez_turetilmez(kur: Callable[..., Kurulum], engine: Engine) -> None:
    k = kur()
    ilk = _turet(k)
    ikinci = _turet(k)
    assert ikinci["turetilen"] == []
    [a] = ikinci["atlanan"]
    assert (a["kaynak_case_id"], a["sonuc"]) == (str(k.kaynaklar[0]), "zaten_turetildi")
    assert ilk["turetilen"][0]["case_id"] in a["neden"]
    assert _case_sayisi(engine, k.rid) == 2
    assert len(_turetmeler(k)) == 1
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM job WHERE tur = 'oracle.check_requirement'")
            ).scalar_one()
            == 1
        )


def test_sira_no_ve_varsayilan_kaynaklar(kur: Callable[..., Kurulum]) -> None:
    k = kur(kaynak_sayisi=2)
    sonuc = _turet(k)
    assert [t["kaynak_case_id"] for t in sonuc["turetilen"]] == [str(c) for c in k.kaynaklar]
    with session_scope() as s:
        req = s.get(Requirement, k.rid)
        siralar = [s.get(TestCase, uuid.UUID(t["case_id"])).sira_no for t in sonuc["turetilen"]]
        assert siralar == [3, 4]
        assert [t["case_id"] for t in sonuc["turetilen"]] == [
            str(case_id(req, 3, 1)),
            str(case_id(req, 4, 1)),
        ]
    # Türetilmiş case'ler varsayılan kaynak olmaz (zincirleme ×2 ×2 yok); kaynaklar zaten türetildi.
    tekrar = _turet(k)
    assert tekrar["turetilen"] == []
    assert sorted(a["kaynak_case_id"] for a in tekrar["atlanan"]) == sorted(
        str(c) for c in k.kaynaklar
    )


def test_secili_case_ve_ac_kapsami(
    kur: Callable[..., Kurulum], make_requirement: Callable[..., Any]
) -> None:
    k = kur(kaynak_sayisi=2)
    sonuc = _turet(k, [k.kaynaklar[1]])
    assert [t["kaynak_case_id"] for t in sonuc["turetilen"]] == [str(k.kaynaklar[1])]
    with pytest.raises(cases_service.CaseNotFound):
        _turet(k, [uuid.uuid4()])
    # AC'si ilişkiyle kesişmeyen case.
    with session_scope() as s:
        tc = s.get(TestCase, k.kaynaklar[0])
        tc.icerik = {**tc.icerik, "acceptance_criteria_refs": ["AC2"]}
        tc.icerik_hash = content_hash(tc.icerik)
    with pytest.raises(IliskiGecersiz, match="kabul kriterlerine"):
        _turet(k, [k.kaynaklar[0]])
    # Varsayılan seçimde de AC2'li case kaynak olmaz.
    assert _turet(k) == {
        "turetilen": [],
        "atlanan": [
            {
                "kaynak_case_id": str(k.kaynaklar[1]),
                "sonuc": "zaten_turetildi",
                "neden": f"Bu ilişkiyle zaten türetildi: {sonuc['turetilen'][0]['case_id']}",
            }
        ],
    }


# ---------------------------------------------------------------------- ilişki geçerliliği


@pytest.mark.parametrize("durum", ["draft", "pending_po"])
def test_onaysiz_iliski(kur: Callable[..., Kurulum], engine: Engine, durum: str) -> None:
    k = kur(iliski_durum=durum)
    with pytest.raises(IliskiGecersiz, match="PO onaylı değil") as h:
        _turet(k)
    assert h.value.status_code == 422 and h.value.kod == "iliski_gecersiz"
    assert _case_sayisi(engine, k.rid) == 1
    assert _turetmeler(k) == []


def test_bayat_iliski(kur: Callable[..., Kurulum], engine: Engine) -> None:
    k = kur()
    with session_scope() as s:
        s.get(MetamorfikIliski, k.iliski_id).gereksinim_hash = "onceki-gereksinim-hash"
    with session_scope() as s:
        assert gecerli_iliskiler(s, k.rid) == []
    with pytest.raises(IliskiGecersiz, match="bayat"):
        _turet(k)
    assert _case_sayisi(engine, k.rid) == 1


def test_baska_gereksinimin_iliskisi(kur: Callable[..., Kurulum]) -> None:
    k1, k2 = kur(), kur()
    with pytest.raises(service.IliskiBulunamadi) as h:
        _turet(k1, iliski_id=k2.iliski_id)
    assert h.value.status_code == 404


def test_gereksinim_case_hazir_degilse(kur: Callable[..., Kurulum]) -> None:
    k = kur(hazir=False)
    with pytest.raises(cases_service.RequirementChanged):
        _turet(k)


def test_gecerli_iliskiler(kur: Callable[..., Kurulum]) -> None:
    k = kur()
    with session_scope() as s:
        req = s.get(Requirement, k.rid)
        tablo = s.get(KararTablosu, k.tablo_id)
        _iliski_ekle(s, req, tablo, {**ILISKI, "ad": "Taslak"}, 2, "draft")
        bekleyen = _iliski_ekle(s, req, tablo, {**ILISKI, "ad": "İkinci"}, 3, "pending_po")
        _onayla(s, bekleyen, req, k.po)
    with session_scope() as s:
        assert [n.icerik["ad"] for n in gecerli_iliskiler(s, k.rid)] == ["Adet iki katı", "İkinci"]
        assert gecerli_iliskiler(s, uuid.uuid4()) == []


# ---------------------------------------------------------------------- API ve roller


def test_api_roller_ve_yanit(
    kur: Callable[..., Kurulum], api: TestClient, make_user: Callable[..., Principal]
) -> None:
    k = kur()
    yol = f"/requirements/{k.rid}/metamorphic-cases"
    govde = {"iliski_id": str(k.iliski_id)}
    for rol in ("po", "tester", "engineer"):
        login(api, make_user(rol))
        assert api.post(yol, json=govde).status_code == 403
    login(api, k.analist)
    r = api.post(yol, json=govde)
    assert r.status_code == 200, r.text
    veri = r.json()
    assert set(veri) == {"turetilen", "atlanan"}
    [t] = veri["turetilen"]
    assert set(t) == {"case_id", "kaynak_case_id", "baslik"}
    r = api.post(yol, json=govde)
    assert r.json()["atlanan"] == [
        {
            "kaynak_case_id": str(k.kaynaklar[0]),
            "sonuc": "zaten_turetildi",
            "neden": f"Bu ilişkiyle zaten türetildi: {t['case_id']}",
        }
    ]
    # Türetilen case portal listesinde taslak ve AI üretimi değil.
    [c] = [
        c
        for c in api.get("/cases", params={"requirement_id": str(k.rid)}).json()
        if c["id"] == t["case_id"]
    ]
    assert (c["durum"], c["ai_generated"], c["sira_no"]) == ("draft", False, 2)

    login(api, make_user("tester"))
    r = api.get(f"/requirements/{k.rid}/metamorphic-derivations")
    assert r.status_code == 200, r.text
    [satir] = r.json()
    assert satir["sonuc"] == "turetildi"
    assert satir["turetilen_case_id"] == t["case_id"]
    assert satir["kaynak_case_id"] == str(k.kaynaklar[0])
    assert satir["iliski_id"] == str(k.iliski_id)
    assert api.get(f"/requirements/{uuid.uuid4()}/metamorphic-derivations").status_code == 404


def test_api_hata_kodlari(kur: Callable[..., Kurulum], api: TestClient) -> None:
    k = kur(iliski_durum="pending_po")
    login(api, k.analist)
    yol = f"/requirements/{k.rid}/metamorphic-cases"
    r = api.post(yol, json={"iliski_id": str(k.iliski_id)})
    assert r.status_code == 422
    assert "iliski_gecersiz" in r.text
    r = api.post(yol, json={"iliski_id": str(uuid.uuid4())})
    assert r.status_code == 404
    r = api.post(yol, json={"iliski_id": str(k.iliski_id), "case_ids": []})
    assert r.status_code == 422
