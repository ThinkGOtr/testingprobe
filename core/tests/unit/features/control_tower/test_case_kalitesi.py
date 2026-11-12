"""Kontrol Kulesi "Case kalitesi" (specs/011 K21): kapsam (pay/payda toplamı), P8 review dağılımı,
P9 kod/model kararları, tekrar oranı, readiness/teknik, asistan içerik kontrolü, sürüm kırılımı.
AI yok; satırlar doğrudan yazılır. Gerçek Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.cases.helpers import case_icerik, eski_case_icerik, ozet_icerik
from tests.unit.features.ci.helpers import login
from tp_core.features.control_tower import case_kalitesi as ck
from tp_core.models import (
    AiCall,
    CaseSetAudit,
    CaseSetReview,
    CaseUretim,
    Requirement,
    TestCase,
)
from tp_core.models.guard import allow_state_write

SIMDI = datetime.now(UTC)


def _zaman(dk: int) -> datetime:
    return SIMDI - timedelta(minutes=100 - dk)


def _ai_call(s: Session, surum: str) -> uuid.UUID:
    cid = uuid.uuid4()
    s.add(
        AiCall(
            id=cid,
            amac="case_generation",
            saglayici="anthropic",
            model="m",
            mod="replay",
            surum=surum,
        )
    )
    s.flush()
    return cid


def _req(s: Session, key: str, acs: list[str]) -> uuid.UUID:
    req = Requirement(
        kaynak="jira",
        jira_key=key,
        baslik=f"{key} başlık",
        kaynak_hash="h",
        kabul_kriterleri=acs,
        durum="cases_ready",
    )
    s.add(req)
    s.flush()
    return req.id


def _cases(s: Session, rid: uuid.UUID, icerikler: list[tuple[dict, str]], uretim_no: int = 1):
    for i, (icerik, durum) in enumerate(icerikler, start=1):
        s.add(
            TestCase(
                id=uuid.uuid4(),
                requirement_id=rid,
                sira_no=i,
                uretim_no=uretim_no,
                icerik=icerik,
                icerik_hash=f"{rid}-{i}",
                durum=durum,
            )
        )
    s.flush()


def _review(
    s: Session, rid: uuid.UUID, skor: int | None, dk: int, *, durum: str = "tamamlandi", **icerik
) -> uuid.UUID:
    r = CaseSetReview(
        id=uuid.uuid4(),
        requirement_id=rid,
        uretim_no=1,
        set_hash="eski",
        durum=durum,
        skor=skor,
        icerik=icerik,
        olusturma=_zaman(dk),
    )
    s.add(r)
    s.flush()
    return r.id


def _audit(
    s: Session,
    rid: uuid.UUID,
    dk: int,
    *,
    durum: str = "tamamlandi",
    karar: str | None = None,
    model_karari: str | None = None,
    review_id: uuid.UUID | None = None,
) -> None:
    s.add(
        CaseSetAudit(
            id=uuid.uuid4(),
            requirement_id=rid,
            set_hash="eski",
            durum=durum,
            karar=karar,
            model_karari=model_karari,
            review_id=review_id,
            olusturma=_zaman(dk),
        )
    )
    s.flush()


def _asistan_denetim(engine: Engine, kullanici_id: uuid.UUID, kararlar: list[tuple[str, str]]):
    sohbet, mesaj = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO asistan_sohbet (id, kullanici_id) VALUES (:i, :k)"),
            {"i": sohbet, "k": kullanici_id},
        )
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, durum) "
                "VALUES (:i, :s, :k, 1, 'user', 'done')"
            ),
            {"i": mesaj, "s": sohbet, "k": kullanici_id},
        )
        for karar, yon in kararlar:
            c.execute(
                text(
                    "INSERT INTO asistan_denetim (mesaj_id, yon, puan, karar, kaynak) "
                    "VALUES (:m, :y, 10, :k, 'sim')"
                ),
                {"m": mesaj, "y": yon, "k": karar},
            )


@pytest.fixture
def kurulum(engine: Engine, make_user) -> dict[str, uuid.UUID]:
    """İki gereksinim, üç sürüm (v3, v2, IDE taslağı), review/denetim geçmişi, asistan denetimi."""
    c1 = case_icerik("A", "AC1", technique=["EP", "BVA"])
    c2 = case_icerik(
        "B",
        "AC1",
        technique=["EP"],
        covers=["EP-I1"],
        readiness="assumption_dependent",
        assumption_refs=["A1"],
    )
    c3 = case_icerik("C", "AC1", technique=["DT"], readiness="blocked", open_question_refs=["Q1"])
    c4 = eski_case_icerik("D", "AC1")
    c5 = case_icerik("E", "AC2", technique=["PW"])  # superseded: sayılmaz
    ozet1 = ozet_icerik(
        [c1, c2, c3],
        negative_coverage=[{"item": "EP-I1", "decision": "test", "rationale": "risk yüksek"}],
    )
    r2_case = case_icerik("F", "AC1")
    with Session(engine) as s, s.begin(), allow_state_write():
        r1 = _req(
            s,
            "TPD-1",
            ["AC1: Geçerli girişte katalog açılır.", "AC2: Hatalı parolada hata gösterilir."],
        )
        r2 = _req(s, "TPD-2", ["AC1: Geçerli girişte katalog açılır."])
        v3 = _ai_call(s, "case-generation@v3")
        v2 = _ai_call(s, "case-generation@v2")
        s.add(CaseUretim(requirement_id=r1, uretim_no=1, ai_call_id=v3, ozet=ozet1))
        s.add(CaseUretim(requirement_id=r1, uretim_no=2, kanal="ide", ozet={}))
        s.add(
            CaseUretim(requirement_id=r2, uretim_no=1, ai_call_id=v2, ozet=ozet_icerik([r2_case]))
        )
        _cases(
            s,
            r1,
            [(c1, "draft"), (c2, "approved"), (c3, "draft"), (c4, "draft"), (c5, "superseded")],
        )
        _cases(s, r2, [(r2_case, "approved")])
        # R1: eski tamamlanmış (6/12), güncel tamamlanmış (11/12, 1 öneri), en yeni hata.
        _review(s, r1, 6, 1, case_haritasi={"1": {}, "2": {}})
        rv1 = _review(
            s,
            r1,
            11,
            2,
            case_haritasi={"1": {}, "2": {}, "3": {}},
            remove_or_merge=[{"case_refs": [1, 2], "action": "merge", "reason": "aynı"}],
        )
        _review(s, r1, None, 3, durum="hata")
        _review(s, r2, 5, 1, case_haritasi={"1": {}}, remove_or_merge=[])
        # R1: tamamlanmış DÜZELTME (model KABUL) + daha yeni hata; R2: KABUL + daha yeni bekliyor.
        _audit(s, r1, 4, karar="DÜZELTME_GEREKLİ", model_karari="KABUL", review_id=rv1)
        _audit(s, r1, 5, durum="hata")
        _audit(s, r2, 4, karar="KABUL", model_karari="KABUL")
        _audit(s, r2, 5, durum="bekliyor")
    u = make_user("analyst")
    _asistan_denetim(
        engine, u.id, [("gec", "soru"), ("gec", "cevap"), ("uyar", "cevap"), ("engelle", "soru")]
    )
    return {"r1": r1, "r2": r2}


def _hesap(engine: Engine, rid: uuid.UUID | None = None) -> dict[str, Any]:
    with Session(engine) as s:
        return ck.case_kalitesi(s, rid)


def test_bos_db_sifir_ve_null(engine: Engine) -> None:
    k = _hesap(engine)
    assert k["kapsam"] == {
        "gereksinim": None,
        "oge": None,
        "negatif_karar": None,
        "hazir_gereksinim": None,
        "hazir_oge": None,
        "n_gereksinim": 0,
        "kapsam_yontemi": "toplam",
    }
    assert k["review"]["n"] == 0 and k["review"]["ortalama"] is None
    assert [d["n"] for d in k["review"]["dagilim"]] == [0, 0, 0, 0]
    assert [d["aralik"] for d in k["review"]["dagilim"]] == ["0–49", "50–69", "70–84", "85–100"]
    sifir = {"KABUL": 0, "DUZELTME_GEREKLI": 0, "ENGELLE": 0}
    assert k["denetim"] == {"n": 0, "kod": sifir, "model": sifir, "hata": 0, "bekliyor": 0}
    assert k["tekrar"]["oran"] is None and k["tekrar"]["oneri"] == 0
    assert k["readiness"] == {"ready": 0, "assumption_dependent": 0, "blocked": 0, "legacy": 0}
    assert k["teknik"] == {}
    ic = k["icerik_kontrolu"]
    assert (ic["n"], ic["gec"], ic["uyar"], ic["engelle"]) == (0, 0, 0, 0)
    assert ic["engel_orani"] is None and ic["uyari_orani"] is None
    assert k["surumler"] == [] and k["hedefler"] == []
    assert set(k["kaynaklar"]) >= {"kapsam", "review", "denetim", "tekrar", "surumler"}
    assert any("hedef" in u for u in k["uyarilar"])


def test_proje_geneli(engine: Engine, kurulum: dict[str, uuid.UUID]) -> None:
    k = _hesap(engine)
    # R1: AC 1/2, öğe 2/2 (UC-MF, EP-I1), negatif 1/1; R2: AC 1/1, öğe 1/1, negatif 0/0.
    assert k["kapsam"]["gereksinim"] == round(2 / 3, 4)
    assert k["kapsam"]["oge"] == 1.0 and k["kapsam"]["negatif_karar"] == 1.0
    assert k["kapsam"]["n_gereksinim"] == 2 and k["kapsam"]["kapsam_yontemi"] == "toplam"
    assert k["kapsam"]["hazir_gereksinim"] is None and k["kapsam"]["hazir_oge"] is None
    assert any("Hazır kapsam" in u for u in k["uyarilar"])

    # Readiness / teknik: güncel case'ler (superseded hariç); eski case legacy.
    assert k["readiness"] == {"ready": 2, "assumption_dependent": 1, "blocked": 1, "legacy": 1}
    assert k["teknik"] == {"BVA": 1, "DT": 1, "EP": 2, "UC": 1}

    # Review: gereksinim başına en güncel tamamlanmış (R1 11/12 = 91.7, R2 5/12 = 41.7).
    r = k["review"]
    assert r["n"] == 2 and r["ortalama"] == 66.7 and r["ortalama_skor"] == 8.0
    assert {d["aralik"]: d["n"] for d in r["dagilim"]} == {
        "0–49": 1,
        "50–69": 0,
        "70–84": 0,
        "85–100": 1,
    }
    assert r["bayat"] == 2  # kayıtların set_hash'i güncel setinki değil

    # Denetim: kod (karar) ve model (model_karari) ayrı; hata/bekliyor en güncel kayda göre.
    d = k["denetim"]
    assert d["n"] == 2
    assert d["kod"] == {"KABUL": 1, "DUZELTME_GEREKLI": 1, "ENGELLE": 0}
    assert d["model"] == {"KABUL": 2, "DUZELTME_GEREKLI": 0, "ENGELLE": 0}
    assert (d["hata"], d["bekliyor"]) == (1, 1)

    # Tekrar: 1 öneri / 4 değerlendirilen case.
    assert k["tekrar"] == {"oneri": 1, "case": 4, "etkilenen_case": 2, "oran": 0.25}

    # İçerik kontrolü: 4 satır, 1 engel, 1 uyarı.
    ic = k["icerik_kontrolu"]
    assert (ic["n"], ic["gec"], ic["uyar"], ic["engelle"]) == (4, 2, 1, 1)
    assert ic["engel_orani"] == 0.25 and ic["uyari_orani"] == 0.25
    assert ic["yon"] == {"cevap": 2, "soru": 2}


def test_surum_kirilimi(engine: Engine, kurulum: dict[str, uuid.UUID]) -> None:
    surumler = {s["surum"]: s for s in _hesap(engine)["surumler"]}
    assert set(surumler) == {"case-generation@v2", "case-generation@v3", ck.IDE_SURUM}
    v3 = surumler["case-generation@v3"]
    assert (v3["uretim"], v3["case"], v3["review_ortalama"]) == (1, 5, 91.7)
    assert (v3["kabul"], v3["duzeltme"], v3["engel"], v3["tekrar_orani"]) == (0, 1, 0, 0.3333)
    v2 = surumler["case-generation@v2"]
    assert (v2["uretim"], v2["case"], v2["review_ortalama"]) == (1, 1, 41.7)
    assert (v2["kabul"], v2["duzeltme"], v2["tekrar_orani"]) == (1, 0, 0.0)
    ide = surumler[ck.IDE_SURUM]
    assert (ide["uretim"], ide["case"], ide["review_ortalama"], ide["tekrar_orani"]) == (
        1,
        0,
        None,
        None,
    )


def test_requirement_id_filtresi(engine: Engine, kurulum: dict[str, uuid.UUID]) -> None:
    k = _hesap(engine, kurulum["r2"])
    assert k["requirement_id"] == str(kurulum["r2"])
    assert k["kapsam"]["gereksinim"] == 1.0 and k["kapsam"]["n_gereksinim"] == 1
    assert k["kapsam"]["negatif_karar"] is None  # geçersiz öğe yok: payda 0
    assert k["review"]["n"] == 1 and k["review"]["ortalama"] == 41.7
    assert k["denetim"]["kod"]["KABUL"] == 1 and k["denetim"]["bekliyor"] == 1
    assert k["denetim"]["hata"] == 0
    assert k["readiness"] == {"ready": 1, "assumption_dependent": 0, "blocked": 0, "legacy": 0}
    assert [s["surum"] for s in k["surumler"]] == ["case-generation@v2"]
    # Asistan denetimi gereksinime bağlı değil: proje geneli + uyarı.
    assert k["icerik_kontrolu"]["n"] == 4
    assert any("İçerik kontrolü" in u for u in k["uyarilar"])


def test_hazir_kapsam_oranlar_anahtarindan_ve_matristen() -> None:
    oranlar = {
        "gereksinim_kapsami": {"kapsanan": 1, "toplam": 2, "oran": 0.5},
        "hazir_gereksinim_kapsami": {"kapsanan": 1, "toplam": 2, "oran": 0.5},
        "hazir_oge_kapsami": {"kapsanan": 0, "toplam": 1, "oran": 0.0},
    }
    h = ck._hazir_oranlari(oranlar, [])
    assert h == {
        "hazir_gereksinim": oranlar["hazir_gereksinim_kapsami"],
        "hazir_oge": oranlar["hazir_oge_kapsami"],
    }
    matris = [
        {"tur": "ac", "covered_by_ready": [1]},
        {"tur": "ac", "covered_by_ready": []},
        {"tur": "oge", "covered_by_ready": [2]},
    ]
    assert ck._hazir_oranlari({}, matris) == {
        "hazir_gereksinim": {"kapsanan": 1, "toplam": 2},
        "hazir_oge": {"kapsanan": 1, "toplam": 1},
    }
    assert ck._hazir_oranlari({}, [{"tur": "ac", "covered_by": [1]}]) == {}


def test_toplayici_pay_payda_yoksa_ortalama() -> None:
    t = ck._Toplayici()
    t.ekle({"kapsanan": 1, "toplam": 4})
    t.ekle({"kapsanan": 3, "toplam": 4})
    t.ekle(None)
    assert t.sonuc() == 0.5 and not t.payda_yok
    o = ck._Toplayici()
    o.ekle({"oran": 0.2})
    o.ekle(0.6)
    assert o.sonuc() == 0.4 and o.payda_yok
    assert ck._Toplayici().sonuc() is None


def test_api_ucu(api: TestClient, make_user, engine: Engine, kurulum: dict[str, uuid.UUID]) -> None:
    login(api, make_user("analyst"))
    r = api.get("/control-tower/case-quality")
    assert r.status_code == 200, r.text
    k = r.json()
    assert set(k) >= {
        "kapsam",
        "review",
        "denetim",
        "tekrar",
        "readiness",
        "teknik",
        "icerik_kontrolu",
        "surumler",
        "hedefler",
        "kaynaklar",
        "uyarilar",
    }
    assert k["denetim"]["kod"]["DUZELTME_GEREKLI"] == 1
    r = api.get("/control-tower/case-quality", params={"requirement_id": str(kurulum["r1"])})
    assert r.status_code == 200 and r.json()["kapsam"]["gereksinim"] == 0.5
    assert (
        api.get(
            "/control-tower/case-quality", params={"requirement_id": str(uuid.uuid4())}
        ).status_code
        == 404
    )


def test_api_girissiz_401(api: TestClient) -> None:
    assert api.get("/control-tower/case-quality").status_code == 401
