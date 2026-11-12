"""Oracle kontrolü, onay kapısı, işler, olaylar, metrik ve uçlar — gerçek Postgres (012 §4.3, §4.7).

Model çağrısı yoktur: REPLAY golden'ları ya da sahte sağlayıcı (`olgu_modeli`).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tp_core.audit import content_hash
from tp_core.features.cases import service as cases_service
from tp_core.features.oracle import service
from tp_core.features.oracle.tablolar import gecerli_tablolar
from tp_core.gateway.errors import ProviderPermanentError
from tp_core.gateway.testing import text_response
from tp_core.models import (
    AiCall,
    AuditEvent,
    CaseOracleKontrol,
    KararTablosu,
    Review,
    TestCase,
    session_scope,
)
from tp_core.workflow.jobs import JobContext

from ..cases.helpers import latest_cases, login, run_jobs
from . import tpd1
from .helpers import (
    BASIT,
    basit_case,
    kayit_yaz,
    olgu_modeli,
    tablo_degistir,
    tablo_ekle,
    uyumsuz_ayrinti,
)

UZUN_GEREKCE = "PO ile görüşüldü; tablo güncellenecek, case doğru."


def _karar(api: TestClient, c: dict[str, Any], **govde: Any):
    return api.post(f"/cases/{c['id']}/decision", json={"icerik_hash": c["icerik_hash"], **govde})


def _kayitlar(cid: str) -> list[CaseOracleKontrol]:
    with session_scope() as s:
        rows = s.scalars(
            select(CaseOracleKontrol).where(CaseOracleKontrol.test_case_id == uuid.UUID(cid))
        ).all()
        s.expunge_all()
        return list(rows)


def _denetim(eylem: str) -> list[AuditEvent]:
    with session_scope() as s:
        rows = s.scalars(select(AuditEvent).where(AuditEvent.eylem == eylem)).all()
        s.expunge_all()
        return list(rows)


def _kuyruktaki(engine: Engine, tur: str) -> int:
    with engine.connect() as c:
        return int(
            c.exec_driver_sql(
                "SELECT count(*) FROM job WHERE tur = %s AND durum = 'queued'", (tur,)
            ).scalar_one()
        )


@pytest.fixture
def kur(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """Basit tablolu (AC1) gereksinim + sahte model; case'ler tablo onayından ÖNCE üretilir."""

    def _kur(cases: list[dict], *, tablo_once: bool = False, olgu_sayisi: int = 0):
        provider = fake_gateway(
            [text_response({"cases": cases})] + [olgu_modeli] * max(olgu_sayisi, 0)
        )
        rid = make_requirement()
        analist, po = make_user("analyst"), make_user("po")
        tid = tablo_ekle(rid, BASIT, analist, po) if tablo_once else None
        login(api, analist)
        assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
        run_jobs(engine, limit=50)
        if tid is None:
            tid = tablo_ekle(rid, BASIT, analist, po)
        return {"rid": rid, "analist": analist, "po": po, "tid": tid, "provider": provider}

    return _kur


# ------------------------------------------------------------------ uçtan uca REPLAY (TPD-1)


def test_tpd1_replay_akisi_golden_sonuclari(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    """Demo ana yolu: PO onaylı TPD-1 (AC2 özgün) → case'ler f2-kod-hatasi senaryo golden'ından,
    tablolar Ş1 taslak golden'ından (story: 7 adette 1 bedava)."""
    beyan = tpd1.taslak_golden()["input_match"]
    rid = make_requirement(
        jira_key="TPD-1",
        baslik="Sepet ve sipariş",
        aciklama=beyan["contains"][0],
        acs=beyan["acceptance_criteria"],
    )
    analist, po = make_user("analyst"), make_user("po")
    for n in sorted(tpd1.TABLOLAR):
        tablo_ekle(rid, tpd1.TABLOLAR[n], analist, po)
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine, limit=100)
    cases = latest_cases(api, rid)
    assert len(cases) == 10
    assert next(c for c in cases if c["sira_no"] == 3)["icerik"]["title"] == (
        "6 adet kampanyalı üründe bedava ürün verilmez"
    )
    sonuclar = {c["sira_no"]: (c["oracle"] or {}).get("sonuc") for c in cases}
    assert sonuclar == tpd1.BEKLENEN_SONUC_ANA_YOL
    c2 = next(c for c in cases if c["sira_no"] == 2)
    assert c2["oracle"]["kontrol_suruyor"] is False and c2["oracle"]["istisna"] is None
    # Birim fiyat case'te yok: 7 adette yalnız bedava adet karşılaştırılır (indirim dışarıda).
    assert {k["column"] for k in c2["oracle"]["karsilastirmalar"]} == {"bedava_adet"}
    assert "karşılaştırılamadı" in c2["oracle"]["ozet"]
    assert {(k["column"], k["case_degeri"]) for k in c2["oracle"]["karsilastirilamayan"]} == {
        ("indirim", "25.00")
    }
    assert all(k["uyumlu"] for k in c2["oracle"]["karsilastirmalar"])
    assert {k["tablo_ad"] for k in c2["oracle"]["karsilastirmalar"]} == {tpd1.T1["ad"]}
    with session_scope() as s:
        modlar = s.scalars(select(AiCall.mod).where(AiCall.amac == "case_facts")).all()
        assert sorted(modlar) == ["replay"] * len(tpd1.OLGULAR)
        rows = s.scalars(select(CaseOracleKontrol)).all()
        assert len(rows) == 10 and all(r.ai_icerik for r in rows)
        assert {r.uretim_modu for r in rows if r.sonuc == "uyumlu"} == {"replay"}
        assert all(r.ai_call_id is None for r in rows if r.sonuc == "kapsam_disi")
    m = api.get(f"/requirements/{rid}/case-metrics").json()["beklenti_dogrulugu"]
    assert {k: v for k, v in m.items() if k != "kaynak"} == {
        "oran": 1.0,
        "uyumlu": 7,
        "uyumsuz": 0,
        "kapsam_disi": 3,
        "kontrol_edilemedi": 0,
        "istisna": 0,
        "kapsam_orani": 0.7,
    }
    assert "karar tablo" in m["kaynak"]
    # Uyumlu yüksek riskli case serbestçe onaylanır; uyarı yok.
    r = _karar(api, c2, karar="approve")
    assert r.status_code == 200, r.text
    assert not any("tablo" in u for u in r.json()["uyarilar"])
    # Düzeltilmiş (golden'ı olmayan) içerik REPLAY-MISS → nötr → kontrol_edilemedi (asla uyumlu).
    c3 = next(c for c in cases if c["sira_no"] == 3)
    yeni = {**c3["icerik"], "expected_result": c3["icerik"]["expected_result"] + "."}
    r = api.post(f"/cases/{c3['id']}/oracle-check", json={"icerik": yeni})
    assert r.status_code == 202, r.text
    run_jobs(engine)
    o = api.get(f"/cases/{c3['id']}/oracle", params={"icerik_hash": r.json()["icerik_hash"]})
    assert o.json()["oracle"]["sonuc"] == "kontrol_edilemedi"
    # Yüksek riskli, kontrol edilemedi: onay + uyarı (V2), uyarı kayıtlı.
    r = _karar(api, c3, karar="edit", icerik=yeni)
    assert r.status_code == 200, r.text
    assert any("kontrol edilemedi" in u for u in r.json()["uyarilar"])


# ------------------------------------------------------------------ onay kapısı matrisi

DURUMLAR = [
    "uyumlu",
    "kapsam_disi",
    "uyumsuz",
    "uyumsuz_istisna",
    "kontrol_edilemedi",
    "kayit_yok",
    "bayat_kayit",
    "tablo_yok",
]


def _beklenen(durum: str, risk: str) -> tuple[int, str | None, bool]:
    """(HTTP durum, hata kodu, oracle uyarısı var mı) — §4.3 tablosu."""
    yuksek = risk == "high"
    if durum == "uyumsuz":
        return (422, "oracle_uyumsuz", False) if yuksek else (200, None, True)
    if durum == "kontrol_edilemedi":
        return 200, None, yuksek
    if durum in ("kayit_yok", "bayat_kayit"):
        return (409, "oracle_bekleniyor", False) if yuksek else (200, None, False)
    return 200, None, False


@pytest.mark.parametrize("risk", ["high", "medium", "low"])
@pytest.mark.parametrize("durum", DURUMLAR)
def test_onay_kapisi_matrisi(api: TestClient, engine: Engine, kur, durum: str, risk: str) -> None:
    case = basit_case(toplam="40,00", risk=risk)
    if durum in ("kapsam_disi", "tablo_yok"):
        case["acceptance_criteria_refs"] = ["AC2"]  # tablo AC1'i kapsar
    k = kur([case])
    c = latest_cases(api, k["rid"])[0]
    cid = uuid.UUID(c["id"])
    govde: dict[str, Any] = {}
    if durum == "uyumlu":
        kayit_yaz(cid, "uyumlu")
    elif durum == "kapsam_disi":
        kayit_yaz(cid, "kapsam_disi")
    elif durum in ("uyumsuz", "uyumsuz_istisna"):
        kayit_yaz(cid, "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
        if durum == "uyumsuz_istisna":
            govde["oracle_istisna_gerekce"] = UZUN_GEREKCE
    elif durum == "kontrol_edilemedi":
        kayit_yaz(cid, "kontrol_edilemedi")
    elif durum == "bayat_kayit":
        kayit_yaz(cid, "uyumlu", hashler={str(k["tid"]): "sha256:eski"})
    onceki_is = _kuyruktaki(engine, service.CHECK_CASE_JOB)
    r = _karar(api, c, karar="approve", **govde)
    kod, hata, uyari = _beklenen(durum, risk)
    assert r.status_code == kod, r.text
    if hata:
        assert r.json()["kod"] == hata
        assert latest_cases(api, k["rid"])[0]["durum"] == "draft"
    else:
        out = r.json()
        assert out["durum"] == "approved"
        oracle_uyarilari = [u for u in out["uyarilar"] if "tablo" in u]
        assert bool(oracle_uyarilari) is uyari, out["uyarilar"]
        with session_scope() as s:
            rv = s.scalars(select(Review).where(Review.nesne_id == cid)).one()
            assert bool((rv.duzeltme_olculeri or {}).get("oracle_uyarilari")) is uyari
    if hata == "oracle_bekleniyor":
        # V3: kontrol ayrı işlemde kuyruğa alındı (istek geri alınsa da iş kaldı).
        assert _kuyruktaki(engine, service.CHECK_CASE_JOB) == onceki_is + 1
    if durum == "uyumsuz_istisna":
        row = _kayitlar(c["id"])[0]
        assert row.istisna_gerekce == UZUN_GEREKCE and row.istisna_veren_id is not None
        assert row.istisna_zamani is not None
        assert len(_denetim("oracle.exception")) == 1
        assert latest_cases(api, k["rid"])[0]["oracle"]["istisna"]["gerekce"] == UZUN_GEREKCE
    else:
        assert _denetim("oracle.exception") == []
    assert bool(_denetim("oracle.warning")) is uyari


def test_istisna_gerekcesi_en_az_20_karakter(api: TestClient, kur) -> None:
    k = kur([basit_case(toplam="40,00")])
    c = latest_cases(api, k["rid"])[0]
    kayit_yaz(uuid.UUID(c["id"]), "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
    r = _karar(api, c, karar="approve", oracle_istisna_gerekce="  kısa gerekçe     ")
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_karar"
    assert "20" in r.json()["detail"]
    assert _kayitlar(c["id"])[0].istisna_gerekce is None
    r = _karar(api, c, karar="approve", oracle_istisna_gerekce="x" * 2001)
    assert r.status_code == 422  # gövde sınırı
    r = _karar(api, c, karar="approve", oracle_istisna_gerekce=UZUN_GEREKCE)
    assert r.status_code == 200, r.text
    ev = _denetim("oracle.exception")[0]
    assert ev.ozet["gerekce"] == UZUN_GEREKCE and ev.aktor == k["analist"].kullanici_adi
    assert ev.ozet["uyusmayan"][0]["column"] == "toplam"
    m = api.get(f"/requirements/{k['rid']}/case-metrics").json()["beklenti_dogrulugu"]
    assert m["istisna"] == 1 and m["uyumsuz"] == 1 and m["oran"] == 0.0


# ------------------------------------------------------------------ üretim kancası + düzeltme yolu


def test_uretim_kontrol_eder_duzeltme_onerilen_icerikle(
    api: TestClient, engine: Engine, kur, monkeypatch: pytest.MonkeyPatch
) -> None:
    olaylar: list[tuple[str, dict]] = []
    gercek = service.publish_tx

    def yakala(conn: Any, ad: str, veri: dict) -> None:
        olaylar.append((ad, dict(veri)))
        gercek(conn, ad, veri)

    monkeypatch.setattr(service, "publish_tx", yakala)
    k = kur([basit_case(toplam="40,00")], tablo_once=True, olgu_sayisi=5)
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["sonuc"] == "uyumsuz"
    assert c["oracle"]["karsilastirmalar"] == [
        {
            "tablo_id": str(k["tid"]),
            "tablo_ad": "Basit toplam",
            "satir_id": "R1",
            "column": "toplam",
            "alan": "expected_result",
            "alinti": "40,00 TL",
            "case_degeri": "40.00",
            "tablo_degeri": "30",
            "uyumlu": False,
        }
    ]
    assert "uyuşmuyor" in c["oracle"]["ozet"]
    assert olaylar == [
        (
            "oracle.checked",
            {
                "case_id": uuid.UUID(c["id"]),
                "requirement_id": k["rid"],
                "icerik_hash": c["icerik_hash"],
                "sonuc": "uyumsuz",
            },
        )
    ]
    assert len(_denetim("oracle.checked")) == 1
    # Kontrol case içeriğini değiştirmez (bağımsızlık kuralı 3).
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        assert tc.icerik_hash == content_hash(basit_case(toplam="40,00")) == c["icerik_hash"]
    # Yüksek risk + uyuşmazlık: 422.
    r = _karar(api, c, karar="approve")
    assert r.status_code == 422 and r.json()["kod"] == "oracle_uyumsuz"
    # Önerilen düzeltme kontrol edilmeden edit: 409 (V3).
    duzgun = basit_case(toplam="30,00")
    r = _karar(api, c, karar="edit", icerik=duzgun)
    assert r.status_code == 409 and r.json()["kod"] == "oracle_bekleniyor"
    # Şemaya uymayan önerilen içerik: 422.
    r = api.post(f"/cases/{c['id']}/oracle-check", json={"icerik": {**duzgun, "tags": ["x"]}})
    assert r.status_code == 422
    r = api.post(f"/cases/{c['id']}/oracle-check", json={"icerik": duzgun})
    assert r.status_code == 202 and r.json()["icerik_hash"] == content_hash(duzgun)
    run_jobs(engine)
    o = api.get(f"/cases/{c['id']}/oracle", params={"icerik_hash": content_hash(duzgun)}).json()
    assert o["guncel_icerik"] is False and o["oracle"]["sonuc"] == "uyumlu"
    assert [t["ad"] for t in o["kapsayan_tablolar"]] == ["Basit toplam"]
    # Önerilen içerik kaydı case'e dokunmadı.
    assert latest_cases(api, k["rid"])[0]["icerik_hash"] == c["icerik_hash"]
    r = _karar(api, c, karar="edit", icerik=duzgun)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["durum"] == "approved" and out["oracle"]["sonuc"] == "uyumlu"
    rows = {row.icerik_hash: row for row in _kayitlar(c["id"])}
    assert rows[c["icerik_hash"]].ai_icerik is True  # AI içeriği
    assert rows[content_hash(duzgun)].ai_icerik is False  # insan düzeltmesi
    m = api.get(f"/requirements/{k['rid']}/case-metrics").json()["beklenti_dogrulugu"]
    assert (m["uyumlu"], m["uyumsuz"], m["oran"], m["kapsam_orani"]) == (0, 1, 0.0, 1.0)


def test_tablo_degisince_kayit_bayatlar_ve_yeniden_hesaplanir(
    api: TestClient, engine: Engine, kur
) -> None:
    k = kur([basit_case(toplam="30,00")], tablo_once=True, olgu_sayisi=5)
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["sonuc"] == "uyumlu"
    tablo_degistir(
        k["tid"],
        {
            **BASIT,
            "satirlar": [{"id": "R1", "kosul": "adet >= 1", "cikti": {"toplam": "adet * 11"}}],
        },
        k["analist"],
        k["po"],
    )
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["kontrol_suruyor"] is True and c["oracle"]["sonuc"] is None
    r = _karar(api, c, karar="approve")
    assert r.status_code == 409 and r.json()["kod"] == "oracle_bekleniyor"
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["sonuc"] == "uyumsuz"  # case 30, tablo 33
    assert len(_kayitlar(c["id"])) == 1  # aynı (case, hash) satırı güncellendi


def _tablo_onay_isi(rid: Any) -> None:
    """Gerçek onay ucu gibi: tablo onayı `oracle.check_requirement` açar."""
    with session_scope() as s:
        service.gereksinim_kontrolu_kuyruga_al(s, rid, "tablo_onaylandi")


B_TABLO = {
    **BASIT,
    "satirlar": [{"id": "R1", "kosul": "adet >= 1", "cikti": {"toplam": "adet * 11"}}],
}


def test_tablo_onceki_icerigine_donunce_kayit_yeniden_hesaplanir(
    api: TestClient, engine: Engine, kur
) -> None:
    """A → B → A: tablo daha önce kontrol edilmiş içeriğe dönünce kontrol yeniden koşar.

    İzole yığında bulundu: iş anahtarı (case, hash, tablo özeti) A'ya dönüşte ilk A işiyle
    çakışıyordu; satır B'de kalıyor, case'in `oracle`'ı boş ve metrik eksik sayıyordu."""
    k = kur([basit_case(toplam="30,00")], tablo_once=True, olgu_sayisi=10)
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["sonuc"] == "uyumlu"
    tablo_degistir(k["tid"], B_TABLO, k["analist"], k["po"])
    _tablo_onay_isi(k["rid"])
    run_jobs(engine)
    assert latest_cases(api, k["rid"])[0]["oracle"]["sonuc"] == "uyumsuz"
    tablo_degistir(k["tid"], BASIT, k["analist"], k["po"])
    _tablo_onay_isi(k["rid"])
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["sonuc"] == "uyumlu", c["oracle"]
    m = api.get(f"/requirements/{k['rid']}/case-metrics").json()["beklenti_dogrulugu"]
    assert (m["uyumlu"], m["uyumsuz"]) == (1, 0)
    # Değişiklik yokken tekrar: geçerli kayıt için iş açılmaz.
    _tablo_onay_isi(k["rid"])
    assert len(run_jobs(engine)) == 1


def test_kapi_tablo_onceki_icerigine_donunce_kalici_409_vermez(
    api: TestClient, engine: Engine, kur
) -> None:
    """Kapının 409 işi de A → B → A'da yeniden açılır (önceden ilk A işiyle çakışıp kalıcı
    `oracle_bekleniyor` veriyordu)."""
    k = kur([basit_case(toplam="30,00")], olgu_sayisi=10)  # tablo onayı kontrol işi açmaz
    c = latest_cases(api, k["rid"])[0]
    for icerik in (B_TABLO, BASIT):
        r = _karar(api, c, karar="approve")
        assert r.status_code == 409 and r.json()["kod"] == "oracle_bekleniyor", r.text
        run_jobs(engine)
        tablo_degistir(k["tid"], icerik, k["analist"], k["po"])
    r = _karar(api, c, karar="approve")
    assert r.status_code == 409, r.text
    run_jobs(engine)
    r = _karar(api, c, karar="approve")
    assert r.status_code == 200, r.text
    assert r.json()["oracle"]["sonuc"] == "uyumlu"


def test_bayat_ve_kesismeyen_tablo_kullanilmaz(api: TestClient, kur) -> None:
    k = kur([basit_case()])
    with session_scope() as s:
        assert [t.id for t in gecerli_tablolar(s, k["rid"], ["AC1"])] == [k["tid"]]
        assert gecerli_tablolar(s, k["rid"], ["AC2"]) == []
        assert [t.id for t in gecerli_tablolar(s, k["rid"])] == [k["tid"]]
        s.get(KararTablosu, k["tid"]).gereksinim_hash = "sha256:eski-gereksinim"
    with session_scope() as s:
        assert gecerli_tablolar(s, k["rid"], ["AC1"]) == []  # gereksinim değişti: bayat
    c = latest_cases(api, k["rid"])[0]
    # Tablosuz üretimde kontrol işi açılmaz; kapsayan tablo da kalmadı: `oracle` yok.
    assert c["oracle"] is None and _kayitlar(c["id"]) == []
    assert _karar(api, c, karar="approve").status_code == 200


def test_gereksinim_isi_taslak_ve_onayli_icin_ai_icerigini_de_kontrol_eder(
    api: TestClient, engine: Engine, kur
) -> None:
    cases = [basit_case(toplam="30,00", risk="low"), basit_case(adet=2, toplam="20,00", risk="low")]
    cases.append(basit_case(adet=4, toplam="40,00", risk="low"))
    k = kur(cases, olgu_sayisi=10)
    c1, c2, c3 = sorted(latest_cases(api, k["rid"]), key=lambda c: c["sira_no"])
    duzgun = basit_case(adet=5, toplam="50,00", risk="low")
    assert _karar(api, c1, karar="edit", icerik=duzgun).status_code == 200
    assert _karar(api, c3, karar="reject", ret_nedeni="duplicate").status_code == 200
    with session_scope() as s:
        service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "tablo_onaylandi")
    run_jobs(engine)
    h1 = {r.icerik_hash: r for r in _kayitlar(c1["id"])}
    assert h1[content_hash(duzgun)].sonuc == "uyumlu" and not h1[content_hash(duzgun)].ai_icerik
    assert h1[c1["icerik_hash"]].sonuc == "uyumlu" and h1[c1["icerik_hash"]].ai_icerik
    assert _kayitlar(c2["id"])[0].sonuc == "uyumlu"
    # Reddedilen case kontrol edilmez (tablosuz üretimde de kayıt açılmamıştı).
    assert _kayitlar(c3["id"]) == []
    # İkinci kez: geçerli kayıtlar için iş açılmaz.
    with session_scope() as s:
        service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "tekrar")
    sonuc = run_jobs(engine)
    assert len(sonuc) == 1


def test_model_hatasi_son_denemede_kontrol_edilemedi(api: TestClient, engine: Engine, kur) -> None:
    k = kur([basit_case(toplam="30,00")])
    c = latest_cases(api, k["rid"])[0]

    class Bozuk:
        rules_dir = tpd1.RULES

        def call(self, *a: Any, **kw: Any) -> Any:
            raise ProviderPermanentError("sağlayıcı reddetti")

    yuk = {"case_id": c["id"], "icerik_hash": c["icerik_hash"]}
    ctx = JobContext(uuid.uuid4(), service.CHECK_CASE_JOB, yuk, deneme=1, max_deneme=3)
    with pytest.raises(ProviderPermanentError):
        service.run_check_case(ctx, engine, Bozuk())  # type: ignore[arg-type]
    son = JobContext(uuid.uuid4(), service.CHECK_CASE_JOB, yuk, deneme=3, max_deneme=3)
    assert service.run_check_case(son, engine, Bozuk())["sonuc"] == "kontrol_edilemedi"  # type: ignore[arg-type]
    ev = _denetim("oracle.checked")[-1]
    assert "ProviderPermanentError" in ev.ozet["cagri_hatasi"]
    # Yüksek risk + kontrol edilemedi: uyarıyla onay (V2).
    r = _karar(api, c, karar="approve")
    assert r.status_code == 200 and any("kontrol edilemedi" in u for u in r.json()["uyarilar"])


def test_icerik_degistiyse_eski_is_atlanir(api: TestClient, engine: Engine, kur) -> None:
    k = kur([basit_case(toplam="30,00", risk="low")])
    c = latest_cases(api, k["rid"])[0]
    yuk = {"case_id": c["id"], "icerik_hash": "sha256:baska"}
    ctx = JobContext(uuid.uuid4(), service.CHECK_CASE_JOB, yuk, deneme=1, max_deneme=3)
    assert service.run_check_case(ctx, engine)["atlandi"] is True
    yuk = {"case_id": c["id"], "icerik_hash": "sha256:baska", "icerik": basit_case()}
    from tp_core.workflow.jobs import PermanentJobError

    with pytest.raises(PermanentJobError):
        service.run_check_case(
            JobContext(uuid.uuid4(), service.CHECK_CASE_JOB, yuk, deneme=1, max_deneme=3), engine
        )


# ------------------------------------------------------------------ uçlar ve roller


def test_uclar_ve_roller(api: TestClient, engine: Engine, kur, make_user) -> None:
    k = kur([basit_case(toplam="30,00", risk="low")])
    c = latest_cases(api, k["rid"])[0]
    o = api.get(f"/cases/{c['id']}/oracle").json()
    assert o["case_id"] == c["id"] and o["guncel_icerik"] is True
    assert o["oracle"] == {
        "sonuc": None,
        "icerik_hash": c["icerik_hash"],
        "ozet": "Tablo kontrolü sürüyor.",
        "karsilastirmalar": [],
        "karsilastirilamayan": [],
        "istisna": None,
        "kontrol_suruyor": True,
    }
    r = api.post(f"/cases/{c['id']}/oracle-check")
    assert r.status_code == 202 and r.json()["icerik_hash"] == c["icerik_hash"]
    assert api.get(f"/cases/{uuid.uuid4()}/oracle").status_code == 404
    for rol in ("po", "tester", "engineer"):
        api.cookies.clear()
        login(api, make_user(rol))
        assert api.get(f"/cases/{c['id']}/oracle").status_code == 200
        r = api.post(f"/cases/{c['id']}/oracle-check", json={})
        assert r.status_code == 403, (rol, r.text)
    api.cookies.clear()
    assert api.get(f"/cases/{c['id']}/oracle").status_code == 401


# ------------------------------------------------------------------ bağımsızlık


def test_uretim_girdisi_tablo_icerigi_tasimaz(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    """Bağımsızlık kuralı 1: onaylı tablo varken de case üretim girdisi tablo içeriği taşımaz."""
    gizli = {
        "ad": "GIZLI-TABLO-ADI-7731",
        "ac_refs": ["AC1", "AC2"],
        "aciklama": "GIZLI-ACIKLAMA-1199",
        "girdiler": [{"ad": "gizli_girdi_x", "tur": "sayi", "aciklama": "GIZLI-KOLON-ACIKLAMA"}],
        "ciktilar": [{"ad": "gizli_cikti_y", "tur": "sayi"}],
        "satirlar": [
            {
                "id": "R1",
                "kosul": "gizli_girdi_x >= 913",
                "cikti": {"gizli_cikti_y": "gizli_girdi_x * 77"},
            }
        ],
    }
    provider = fake_gateway([text_response({"cases": [basit_case(risk="low")]}), olgu_modeli])
    rid = make_requirement()
    analist, po = make_user("analyst"), make_user("po")
    tablo_ekle(rid, gizli, analist, po)
    with session_scope() as s:
        req = cases_service.get_requirement(s, rid)
        assert gecerli_tablolar(s, rid)  # tablo gerçekten onaylı ve geçerli
        mesajlar = cases_service.generation_messages(req, cases_service._onaylanan_sorular(s, rid))
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    gonderilen = str(provider.requests[0].messages) + str(provider.requests[0].system)
    for metin in (str([m.content for m in mesajlar]), gonderilen):
        for parca in (
            "GIZLI-TABLO-ADI-7731",
            "GIZLI-ACIKLAMA-1199",
            "GIZLI-KOLON-ACIKLAMA",
            "gizli_girdi_x",
            "gizli_cikti_y",
            "913",
            "* 77",
        ):
            assert parca not in metin, parca
