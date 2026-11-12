"""012 Ş1: AI karar tablosu taslağı (`karar_tablosu.draft`) — sahte sağlayıcıyla geçerli/geçersiz
öğeler, eski AI taslaklarının geçersiz kılınması, `tablo_ref` çözümü; REPLAY golden'ı (TPD-1) ve
bağımsızlık (girdide kod, veri, case ve mevcut tablo yok). Canlı model çağrısı yapılmaz."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.cases.helpers import case_icerik, login, run_jobs
from tests.unit.gateway.demo_sources import load_golden
from tp_core.audit import content_hash
from tp_core.features.karar_tablosu import ifade, service
from tp_core.gateway.testing import text_response
from tp_core.models import (
    KararTablosu,
    MetamorfikIliski,
    TestCase,
    WorkflowInstance,
    session_scope,
)
from tp_core.workflow.service import Principal, content_hash_of, record_approval, transition

MakeUser = Callable[..., Principal]

F2 = load_golden("case_generation", "f2-kod-hatasi/TPD-1")["input_match"]
TPD1 = {
    "jira_key": "TPD-1",
    "baslik": "Kampanyalı sepet ve sipariş onayı",
    "aciklama": F2["contains"][0],
    "acs": F2["acceptance_criteria"],
}


def _kolon(ad: str, tur: str = "sayi", **kw: Any) -> dict[str, Any]:
    return {"ad": ad, "tur": tur, "birim": None, "aciklama": None, **kw}


def _cikti(ad: str, tur: str = "sayi", tolerans: str | None = None) -> dict[str, Any]:
    return {**_kolon(ad, tur), "tolerans": tolerans}


def _tablo(ad: str, ac: str, cikti_ad: str, ifade_: str) -> dict[str, Any]:
    return {
        "ad": ad,
        "ac_refs": [ac],
        "aciklama": "",
        "girdiler": [_kolon("adet")],
        "ciktilar": [_cikti(cikti_ad)],
        "satirlar": [
            {
                "id": "R1",
                "kosul": "adet >= 7",
                "ciktilar": [{"ad": cikti_ad, "ifade": ifade_}],
                "aciklama": None,
            },
            {
                "id": "R2",
                "kosul": "dogru",
                "ciktilar": [{"ad": cikti_ad, "ifade": "0"}],
                "aciklama": "kalan",
            },
        ],
    }


def _iliski(ad: str, tablo_ref: str | None, cikti_ad: str = "bedava") -> dict[str, Any]:
    return {
        "ad": ad,
        "ac_refs": ["AC2"],
        "tablo_ref": tablo_ref,
        "on_kosul": "adet % 7 == 0",
        "donusum": [{"ad": "adet", "ifade": "adet * 2"}],
        "iliski": [{"ad": cikti_ad, "ifade": f"{cikti_ad} * 2"}],
        "aciklama": None,
    }


GECERLI_1 = _tablo("Kampanya", "AC2", "bedava", "adet // 7")
GECERLI_2 = _tablo("İndirim", "AC2", "indirim", "(adet // 7) * 25")
# Satırda tanımsız çıktı ve tür hatası: doğrulamadan geçmez, yazılmaz.
GECERSIZ = {
    **_tablo("Bozuk", "AC3", "uyari", "adet > 7"),
    "ciktilar": [_cikti("uyari")],
}
CIKTI = {
    "tables": [GECERLI_1, GECERSIZ, GECERLI_2],
    "relations": [
        _iliski("T3'e bağlı", "T3", "indirim"),
        _iliski("Geçersiz tabloya bağlı", "T2", "uyari"),
        _iliski("Yok olan tabloya bağlı", "T7"),
        _iliski("Bağsız", None),
    ],
    "notes": "AC3 belirsiz",
}


def _baslat(api: TestClient, make_user: MakeUser, rid: uuid.UUID) -> dict[str, Any]:
    login(api, make_user("analyst"))
    r = api.post(f"/requirements/{rid}/decision-tables/draft")
    assert r.status_code == 202, r.text
    return r.json()


def _nesneler(rid: uuid.UUID, model: Any) -> list[Any]:
    with session_scope() as s:
        out = s.scalars(
            select(model).where(model.requirement_id == rid).order_by(model.sira_no)
        ).all()
        s.expunge_all()
        return list(out)


def test_taslak_gecerli_ogeleri_yazar_gecersizleri_raporlar(
    api: TestClient, engine: Engine, make_user: MakeUser, make_requirement, fake_gateway
) -> None:
    provider = fake_gateway([text_response(CIKTI)])
    rid = make_requirement()
    is_ = _baslat(api, make_user, rid)
    assert is_["durum"] == "started" and is_["job_id"] and is_["workflow_id"]
    sonuc = run_jobs(engine)
    assert [x.durum for x in sonuc] == ["done"], sonuc
    ozet = sonuc[0].deger
    assert len(provider.requests) == 1

    tablolar = _nesneler(rid, KararTablosu)
    assert [t.icerik["ad"] for t in tablolar] == ["Kampanya", "İndirim"]
    assert [t.sira_no for t in tablolar] == [1, 2]
    for t in tablolar:
        assert t.durum == "draft" and t.ai_generated is True and t.uretim_modu == "live"
        assert t.ai_call_id is not None and str(t.ai_call_id) == ozet["ai_call_id"]
        assert t.icerik_hash == content_hash(t.icerik) and ifade.dogrula(t.icerik) == []
    # Model biçimi ([{ad, ifade}], null alanlar) içerik biçimine çevrildi.
    assert tablolar[0].icerik["satirlar"][0] == {
        "id": "R1",
        "kosul": "adet >= 7",
        "cikti": {"bedava": "adet // 7"},
    }
    assert tablolar[0].icerik["girdiler"] == [{"ad": "adet", "tur": "sayi"}]
    assert "aciklama" not in tablolar[0].icerik

    iliskiler = _nesneler(rid, MetamorfikIliski)
    assert [i.icerik["ad"] for i in iliskiler] == ["T3'e bağlı", "Bağsız"]
    bagli, bagsiz = iliskiler
    # Çıktıdaki T3 (üçüncü öğe) yazılan ikinci tabloya (sira_no 2) çözülür.
    assert bagli.karar_tablosu_id == tablolar[1].id and bagli.icerik["tablo_ref"] == "T2"
    assert bagsiz.karar_tablosu_id is None and "tablo_ref" not in bagsiz.icerik
    assert bagli.icerik["donusum"] == {"adet": "adet * 2"}
    assert all(i.ai_generated and i.durum == "draft" for i in iliskiler)

    assert ozet["tablolar"] == [str(t.id) for t in tablolar]
    assert ozet["iliskiler"] == [str(i.id) for i in iliskiler]
    assert ozet["notes"] == "AC3 belirsiz" and ozet["mode"] == "live"
    atilan = {(a["tur"], a["ref"]): a for a in ozet["atilan"]}
    assert set(atilan) == {
        ("karar_tablosu", "T2"),
        ("metamorfik_iliski", "I2"),
        ("metamorfik_iliski", "I3"),
    }
    assert any("mantıksal" in h or "sayı" in h for h in atilan[("karar_tablosu", "T2")]["hatalar"])
    assert "T2" in atilan[("metamorfik_iliski", "I2")]["hatalar"][0]
    assert "T7" in atilan[("metamorfik_iliski", "I3")]["hatalar"][0]

    with session_scope() as s:
        wf = s.get(WorkflowInstance, uuid.UUID(is_["workflow_id"]))
        assert wf.durum == "done"
        eylemler = {e for (e,) in s.execute(text("SELECT eylem FROM audit_event")).all()}
    assert {
        "karar_tablosu.ai_draft",
        "metamorfik_iliski.ai_draft",
        "karar_tablosu.draft_requested",
    } <= eylemler

    liste = api.get(f"/requirements/{rid}/decision-tables").json()
    assert [t["ai_generated"] for t in liste["tablolar"]] == [True, True]
    assert liste["tablolar"][0]["uretim_modu"] == "live"
    assert liste["son_taslak"]["durum"] == "done"
    assert liste["son_taslak"]["sonuc"]["atilan"] == ozet["atilan"]
    assert liste["son_taslak"]["job_id"] == is_["job_id"]


def test_yeni_taslak_onceki_ai_taslaklarini_gecersiz_kilar(
    api: TestClient, engine: Engine, make_user: MakeUser, make_requirement, fake_gateway
) -> None:
    ikinci = {
        "tables": [_tablo("Yeni", "AC2", "bedava", "adet // 7")],
        "relations": [],
        "notes": "",
    }
    fake_gateway([text_response(CIKTI), text_response(ikinci)])
    rid = make_requirement()
    _baslat(api, make_user, rid)
    run_jobs(engine)
    eski = _nesneler(rid, KararTablosu)
    eski_iliski = _nesneler(rid, MetamorfikIliski)
    # İlk AI tablosu PO onaylı; elle açılan taslak AI'ın değildir: ikisi de kalır.
    po = make_user("po")
    analist = make_user("analyst")
    with session_scope() as s:
        t = s.get(KararTablosu, eski[0].id)
        transition(s, t, "pending_po", analist, "draft")
        record_approval(s, t, po, "approve", beklenen_hash=content_hash_of(t))
        t.gereksinim_hash = "sha256:gereksinim"  # 0022 onay_hash_ck
        transition(s, t, "approved", po, "pending_po")
    login(api, analist)
    elle = api.post(f"/requirements/{rid}/decision-tables", json={}).json()

    r = api.post(f"/requirements/{rid}/decision-tables/draft")
    assert r.status_code == 202
    sonuc = run_jobs(engine)
    ozet = sonuc[-1].deger
    assert ozet["gecersiz_kilinan"] == {"karar_tablosu": 1, "metamorfik_iliski": 2}

    durum = {t.id: t.durum for t in _nesneler(rid, KararTablosu)}
    assert durum[eski[0].id] == "approved"
    assert durum[eski[1].id] == "superseded"
    assert durum[uuid.UUID(elle["id"])] == "draft"
    assert {i.durum for i in _nesneler(rid, MetamorfikIliski)} == {"superseded"}
    assert len(eski_iliski) == 2
    yeni = [t for t in _nesneler(rid, KararTablosu) if t.icerik["ad"] == "Yeni"]
    assert len(yeni) == 1 and yeni[0].sira_no == 4  # sira_no yeniden kullanılmaz
    liste = api.get(f"/requirements/{rid}/decision-tables").json()
    assert sorted(t["sira_no"] for t in liste["tablolar"]) == [1, 3, 4]
    # Geçersiz kılınan taslaklar onaylı değildi: kontrol işi yalnız ilk onaydandır.
    with session_scope() as s:
        n = s.scalar(text("SELECT count(*) FROM job WHERE tur = 'oracle.check_requirement'"))
    assert n == 0  # onay doğrudan servisle (API'siz) verildi; kanca onay ucundadır


def test_suren_taslak_isi_tekrar_baslatilmaz(
    api: TestClient, engine: Engine, make_user: MakeUser, make_requirement, fake_gateway
) -> None:
    fake_gateway([text_response(CIKTI)])
    rid = make_requirement()
    ilk = _baslat(api, make_user, rid)
    ikinci = api.post(f"/requirements/{rid}/decision-tables/draft").json()
    assert ikinci["job_id"] == ilk["job_id"] and "süren" in ikinci["mesaj"]
    run_jobs(engine)
    ucuncu = api.post(f"/requirements/{rid}/decision-tables/draft").json()
    assert ucuncu["job_id"] != ilk["job_id"]


def test_gereksinim_taslak_sirasinda_degisirse_yazilmaz(
    api: TestClient, engine: Engine, make_user: MakeUser, make_requirement, fake_gateway
) -> None:
    rid = make_requirement()

    def degistir_ve_cevapla(_request: Any) -> Any:
        from tp_core.models import Requirement

        with session_scope() as s:
            req = s.get(Requirement, rid)
            req.aciklama = "değişti"
        return text_response(CIKTI)

    fake_gateway([degistir_ve_cevapla])
    _baslat(api, make_user, rid)
    sonuc = run_jobs(engine)
    assert sonuc[-1].durum == "failed"
    assert _nesneler(rid, KararTablosu) == []


def _tpd1(make_requirement) -> uuid.UUID:
    return make_requirement(TPD1["jira_key"], TPD1["baslik"], TPD1["aciklama"], TPD1["acs"])


def test_replay_golden_tpd1(
    api: TestClient, engine: Engine, make_user: MakeUser, make_requirement, replay_gateway
) -> None:
    rid = _tpd1(make_requirement)
    _baslat(api, make_user, rid)
    sonuc = run_jobs(engine)
    ozet = sonuc[0].deger
    assert sonuc[0].durum == "done" and ozet["mode"] == "replay" and ozet["atilan"] == []
    with session_scope() as s:
        mod, ek = s.execute(
            text("SELECT mod, ek FROM ai_call WHERE amac = 'decision_table_draft'")
        ).one()
    assert mod == "replay" and ek["replay_kokeni"] == "golden_matched"

    kampanya, minimum = _nesneler(rid, KararTablosu)
    assert kampanya.icerik["ac_refs"] == ["AC2"] and minimum.icerik["ac_refs"] == ["AC3", "AC6"]
    for t in (kampanya, minimum):
        assert ifade.gonderim_hatalari(t.icerik) == []  # PO'ya gönderilebilir

    def kampanya_ciktisi(adet: int, ara_toplam: str) -> dict[str, Any]:
        return ifade.degerlendir(
            kampanya.icerik, {"adet": adet, "ara_toplam": ara_toplam}
        ).as_dict()["ciktilar"]

    # Story: 7 adette 1 bedava (6 öde + 1 bedava), birim fiyat 25,00 TL. Kod `// 6` uygular;
    # tablo story'yi izler (review V9: girdi ara toplam, çıktılar bedava adet/indirim/toplam).
    assert kampanya_ciktisi(6, "150,00 TL") == {
        "bedava_adet": "0",
        "indirim": "0",
        "toplam": "150.00",
    }
    assert kampanya_ciktisi(7, "175,00 TL") == {
        "bedava_adet": "1",
        "indirim": "25.00",
        "toplam": "150.00",
    }
    assert kampanya_ciktisi(14, "350,00 TL") == {
        "bedava_adet": "2",
        "indirim": "50.00",
        "toplam": "300.00",
    }

    def uyari(kampanyali: bool, tutar: str) -> Any:
        girdi = {"kampanyali_sepet": kampanyali, "sepet_tutari": tutar}
        return ifade.degerlendir(minimum.icerik, girdi).ciktilar["minimum_uyarisi"]

    # PO onaylı (F3 fix_doc sonrası) metin: kampanyasız siparişte minimum 750,00 TL. AI taslağı
    # sınırı bilerek yanlış yorumlar (`<= 750`: tam 750,00 TL'de de uyarı) ve PO'ya soru bırakır;
    # demo hikâyesinde PO sınır örneklerinde yakalar (review 2 u2 N2).
    assert uyari(False, "749,99 TL") is True
    assert uyari(False, "750,00 TL") is True  # AI'ın sınır hatası
    assert uyari(False, "750,01 TL") is False
    assert uyari(True, "100,00 TL") is False
    assert "PO sorusu" in load_golden("decision_table_draft", "TPD-1")["output"]["notes"]

    (iliski,) = _nesneler(rid, MetamorfikIliski)
    assert iliski.karar_tablosu_id == kampanya.id and iliski.icerik["tablo_ref"] == "T1"
    sonuc_ = ifade.iliski_uygula(
        iliski.icerik,
        {"adet": 7, "ara_toplam": 175},
        {"bedava_adet": 1, "indirim": 25, "toplam": 150},
    )
    assert sonuc_.gecerli and sonuc_.girdiler["adet"] == 14 and sonuc_.ciktilar["bedava_adet"] == 2
    assert sonuc_.ciktilar["indirim"] == 50 and sonuc_.ciktilar["toplam"] == 300
    assert "AC3" in ozet["notes"]


def test_replay_miss_bos_taslak_ve_mevcutlara_dokunmaz(
    api: TestClient, engine: Engine, make_user: MakeUser, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()  # TPD-4: bu amaç için golden yok → nötr yedek
    with session_scope() as s:
        icerik = service.bos_tablo("Önceki AI taslağı")
        s.add(
            KararTablosu(
                requirement_id=rid,
                sira_no=1,
                icerik=icerik,
                icerik_hash=content_hash(icerik),
                ai_generated=True,
            )
        )
    _baslat(api, make_user, rid)
    sonuc = run_jobs(engine)
    ozet = sonuc[0].deger
    assert sonuc[0].durum == "done" and ozet["mode"] == "replay_miss"
    assert ozet["tablolar"] == [] and ozet["iliskiler"] == []
    assert ozet["gecersiz_kilinan"] == {"karar_tablosu": 0, "metamorfik_iliski": 0}
    assert "REPLAY-MISS" in ozet["notes"]
    assert [t.durum for t in _nesneler(rid, KararTablosu)] == ["draft"]


def test_bagimsizlik_taslak_girdisi_kod_veri_case_tablo_tasimaz(
    api: TestClient, engine: Engine, make_user: MakeUser, make_requirement, fake_gateway
) -> None:
    """§4.1 bağımsızlık: taslak yalnız PO onaylı story bloğunu ve PO cevaplarını görür."""
    provider = fake_gateway([text_response({"tables": [], "relations": [], "notes": ""})])
    rid = make_requirement(po_cevaplari=[{"soru": "Eşik dahil mi?", "cevap": "Hayır, altında"}])
    # Aynı gereksinimde case ve tablo var: girdide görünmemeli.
    with session_scope() as s:
        tc_icerik = case_icerik(title="GIZLI-CASE-BASLIGI 7 adet sepette")
        s.add(
            TestCase(
                id=uuid.uuid4(),
                requirement_id=rid,
                sira_no=1,
                uretim_no=1,
                kanal="portal",
                icerik=tc_icerik,
                icerik_hash=content_hash(tc_icerik),
                ai_generated=True,
            )
        )
        tablo = {**service.bos_tablo("GIZLI-TABLO-ADI"), "aciklama": "adet // 6"}
        s.add(
            KararTablosu(
                requirement_id=rid, sira_no=1, icerik=tablo, icerik_hash=content_hash(tablo)
            )
        )
    _baslat(api, make_user, rid)
    assert run_jobs(engine)[0].durum == "done"

    (istek,) = provider.requests
    metin = json.dumps([istek.system, *[m["content"] for m in istek.messages]], ensure_ascii=False)
    icerik = istek.messages[0]["content"]
    assert len(istek.messages) == 1
    kaynaklar = set(re.findall(r'<untrusted kind="[^"]+" source="([^"]+)"', icerik))
    assert kaynaklar == {"jira:TPD-4", "jira:TPD-4:po"}
    assert "Eşik dahil mi?" in icerik and "Hayır, altında" in icerik
    for yasak in (
        "GIZLI-CASE-BASLIGI",
        "GIZLI-TABLO-ADI",
        "adet // 6",
        "testdata:",
        'kind="code"',
        'kind="data"',
        "campaign.py",
        "pricing.py",
        "min_siparis_tutari",
        "bayi1 / Demo123!",
        "P-001",
    ):
        assert yasak not in metin, yasak
    # Kurucu doğrudan da aynı: case/tablo/test verisi parametresi yoktur.
    with session_scope() as s:
        from tp_core.models import Requirement

        msgs = service.taslak_mesajlari(s.get(Requirement, rid))
    assert "testdata" not in msgs[0].content and "GIZLI" not in msgs[0].content
