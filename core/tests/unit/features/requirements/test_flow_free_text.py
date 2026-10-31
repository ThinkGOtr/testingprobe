"""Serbest metin yolu, uydurma kanıtın elenmesi, tur sınırı ve hata yolları."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.features.requirements.settings import get_requirements_settings
from tp_core.gateway import FINAL_TOOL
from tp_core.gateway.testing import text_response, tool_response
from tp_core.models import ConsistencyFinding, Review, new_session
from tp_core.models.requirements_feature import ConsistencyFindingEk

from .conftest import fake_gateway, login, run_jobs

pytestmark = pytest.mark.usefixtures("wired")

SERBEST = {
    "baslik": "Sepetten ürün çıkarma",
    "aciklama": (
        "Bayi sepetteki bir ürün satırını kaldırabilmeli; toplamlar ve kampanya indirimi yeniden "
        "hesaplanmalıdır."
    ),
    "ac": [
        'Satırdaki "Kaldır" butonuna basıldığında ürün sepetten çıkar ve sepet sayacı azalır.',
        "Kaldırma sonrası kampanya indirimi her 7 adette 1 bedava kuralıyla yeniden hesaplanır.",
        "Sepet tutarı 500,00 TL altına düşerse minimum tutar uyarısı gösterilir.",
    ],
}


@pytest.fixture
def analist(api: TestClient, make_user) -> Any:
    u = make_user("analyst")
    login(api, u)
    return u


def _findings(api: TestClient, rid: str) -> list[dict[str, Any]]:
    r = api.get(f"/requirements/{rid}/findings")
    assert r.status_code == 200, r.text
    return r.json()


def test_serbest_metin_senaryosu_replay(
    api: TestClient, analist: Any, engine: Engine, make_user
) -> None:
    r = api.post("/requirements/free-text", json=SERBEST)
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["kaynak"] == "free_text" and g["jira_key"] is None and g["durum"] == "new"
    assert [a["metin"] for a in g["kabul_kriterleri"]] == SERBEST["ac"]
    rid = g["id"]

    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "findings_open", d
    # Senaryodaki metin golden beyanına uyar → REPLAY (asla "live" değil).
    assert d["on_inceleme"]["mode"] == "replay"
    assert d["on_inceleme"]["jira_comment_id"] is None
    bulgular = _findings(api, rid)
    assert {f["type"] for f in bulgular} == {"doc_vs_code", "doc_vs_data", "missing_in_doc"}
    assert all(f["mode"] == "replay" and f["kanit_dogrulandi"] for f in bulgular)

    for f in bulgular:
        r = api.post(
            f"/findings/{f['id']}/decision",
            json={"karar": "fix_doc", "icerik_hash": f["icerik_hash"]},
        )
        assert r.status_code == 200, r.text
    assert api.post(f"/requirements/{rid}/apply-doc-fixes").status_code == 202
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "pending_po", d
    assert d["kontrol_turu"] == 2 and d["son_kontrol"]["mode"] == "replay"  # SERBEST-r2
    assert "her 6 adette" in d["kabul_kriterleri"][1]["metin"]
    assert "750,00 TL" in d["kabul_kriterleri"][2]["metin"]
    assert d["po"] == {
        "durum": "pending",
        "onaylayan": None,
        "zaman": None,
        "kanal": "portal",
        "onaylanan_hash": None,
    }

    # PO teyidi: yalnızca po rolü, görülen içerik hash'iyle.
    onay_yolu = f"/requirements/{rid}/po-approve"
    assert api.post(onay_yolu, json={"icerik_hash": d["icerik_hash"]}).status_code == 403
    p = make_user("po")
    login(api, p)
    assert api.post(f"/requirements/{rid}/po-approve", json={}).status_code == 422
    assert api.post(onay_yolu, json={"icerik_hash": "x" * 64}).status_code == 409
    r = api.post(f"/requirements/{rid}/po-approve", json={"icerik_hash": d["icerik_hash"]})
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "po_approved"
    assert r.json()["po"]["onaylayan"] == p.kullanici_adi and r.json()["po"]["kanal"] == "portal"
    with new_session() as s:
        onay = s.scalars(select(Review).where(Review.nesne_turu == "requirement")).one()
        assert onay.user_id == p.id and onay.onaylanan_hash == d["icerik_hash"]
    with engine.connect() as c:
        modlar = set(c.execute(text("SELECT DISTINCT mod FROM ai_call")).scalars())
    assert modlar == {"replay"}


def test_uydurma_kanit_elenir_ve_gosterilmez(
    api: TestClient, analist: Any, engine: Engine, wired: dict[str, Any]
) -> None:
    gercek = {
        "id": "F1",
        "type": "doc_vs_data",
        "doc_ref": "AC1",
        "claim": "Minimum 500,00 TL",
        "observed": "ayar 750.00",
        "evidence": [
            {
                "kind": "data",
                "query": "SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'",
                "result_digest": "min_siparis_tutari=750.00",
            }
        ],
        "severity": "warning",
        "suggested_doc_text": "AC1: Minimum sipariş tutarı 750,00 TL'dir.",
    }
    uydurma = {
        "id": "F2",
        "type": "doc_vs_code",
        "doc_ref": "AC1",
        "claim": "x",
        "observed": "Kod 10 adette 3 bedava veriyor",
        "evidence": [
            {
                "kind": "code",
                "repo": "demo-app",
                "path": "api/src/demoapp_api/campaign.py",
                "line": 23,
                "snippet": "return adet // 3",
            }
        ],
        "severity": "blocking",
        "suggested_doc_text": None,
    }
    make, provider = fake_gateway(
        [
            text_response({"questions": [], "verdict": "ready", "summary": "Soru yok."}),
            tool_response(("db_query", {"sql": gercek["evidence"][0]["query"]})),
            tool_response(("get_file_contents", {"path": "api/src/demoapp_api/campaign.py"})),
            tool_response((FINAL_TOOL, {"findings": [gercek, uydurma], "notes": "test"})),
        ]
    )
    wired["gateway"] = make
    r = api.post(
        "/requirements/free-text",
        json={"baslik": "Minimum tutar", "aciklama": "", "ac": ["Minimum sipariş 500,00 TL."]},
    )
    rid = r.json()["id"]
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    assert not provider.script

    # Ajan araç sonucu modele güvenilmeyen blokta ve özetle gitti.
    arac_sonucu = provider.requests[2].messages[-1]["content"][0]["content"]
    assert "result_digest: min_siparis_tutari=750.00" in arac_sonucu
    assert '<untrusted kind="data"' in arac_sonucu

    resp = api.get(f"/requirements/{rid}/findings")
    gorunen = resp.json()
    assert [f["bulgu_no"] for f in gorunen] == ["F1"]
    assert resp.headers["X-Elenen-Bulgu-Sayisi"] == "1"
    d = api.get(f"/requirements/{rid}").json()
    assert d["bulgu_sayaclari"] == {"dogrulanan": 1, "elenen": 1, "acik": 1}
    assert d["son_kontrol"]["elenen"] == 1 and d["son_kontrol"]["mode"] == "live"
    # Uydurma (engelleyici) bulgu elendiği için engelleyici yok → son hal, PO bekleniyor.
    assert d["durum"] == "pending_po"
    with new_session() as s:
        elenen = s.scalars(
            select(ConsistencyFinding).where(ConsistencyFinding.kanit_dogrulandi.is_(False))
        ).one()
        assert elenen.durum == "discarded"
        ek = s.get(ConsistencyFindingEk, elenen.id)
        assert "alıntı" in ek.dogrulama[0]["neden"]
        f_id = s.scalars(
            select(ConsistencyFinding.id).where(ConsistencyFinding.kanit_dogrulandi.is_(True))
        ).one()
    # Elenen bulguya karar verilemez (404); doğrulanmışa durum gereği (pending_po) 409.
    r = api.post(
        f"/findings/{elenen.id}/decision", json={"karar": "code_defect", "icerik_hash": "x"}
    )
    assert r.status_code == 404
    f = next(x for x in gorunen if x["id"] == str(f_id))
    r = api.post(
        f"/findings/{f_id}/decision", json={"karar": "fix_doc", "icerik_hash": f["icerik_hash"]}
    )
    assert r.status_code == 409


def test_bilincli_fark_ve_tur_siniri(
    api: TestClient,
    analist: Any,
    engine: Engine,
    wired: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TP_CONSISTENCY_MAX_ROUNDS", "1")
    get_requirements_settings.cache_clear()
    bulgu = {
        "id": "F1",
        "type": "internal_contradiction",
        "doc_ref": "AC1 ↔ AC2",
        "claim": "AC1 ile AC2 çelişiyor",
        "observed": "İkisi aynı anda doğru olamaz",
        "evidence": [],
        "severity": "blocking",
        "suggested_doc_text": "AC2: Kampanyalı siparişlerde de minimum aranır.",
    }
    make, _ = fake_gateway(
        [
            text_response({"questions": [], "verdict": "ready", "summary": "-"}),
            tool_response((FINAL_TOOL, {"findings": [bulgu, {**bulgu, "id": "F2"}], "notes": ""})),
        ]
    )
    wired["gateway"] = make
    rid = api.post(
        "/requirements/free-text",
        json={
            "baslik": "Çelişki",
            "ac": ["Tüm siparişlerde minimum aranır.", "Kampanyalıda aranmaz."],
        },
    ).json()["id"]
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "findings_open" and d["insan_karari_gerekli"] is True
    r = api.post(f"/requirements/{rid}/review")
    assert r.status_code == 409 and "sınır" in r.json()["detail"]

    f1, f2 = _findings(api, rid)
    r = api.post(
        f"/findings/{f1['id']}/decision",
        json={"karar": "accept_difference", "icerik_hash": f1["icerik_hash"], "gerekce": "  "},
    )
    assert r.status_code == 422
    r = api.post(
        f"/findings/{f1['id']}/decision",
        json={
            "karar": "accept_difference",
            "icerik_hash": f1["icerik_hash"],
            "gerekce": "İş birimi bilinçli olarak böyle istedi",
        },
    )
    assert r.status_code == 200 and r.json()["durum"] == "resolved"
    assert api.get(f"/requirements/{rid}").json()["durum"] == "findings_open"
    # Son engelleyici fix_doc → tur sınırında düzeltme yazılır ama AI denetimi tekrar koşmaz.
    r = api.post(
        f"/findings/{f2['id']}/decision",
        json={"karar": "fix_doc", "icerik_hash": f2["icerik_hash"]},
    )
    assert r.status_code == 200
    # Karar değiştirilebilir (decided → open → decided) ve yeni hash istenir.
    eski_hash = f2["icerik_hash"]
    r2 = api.post(
        f"/findings/{f2['id']}/decision",
        json={
            "karar": "fix_doc",
            "icerik_hash": r.json()["icerik_hash"],
            "metin": "AC2: Yeni metin.",
        },
    )
    assert r2.status_code == 200 and r2.json()["karar_metni"] == "AC2: Yeni metin."
    assert r2.json()["icerik_hash"] != eski_hash
    assert api.post(f"/requirements/{rid}/apply-doc-fixes").status_code == 202
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "pending_po" and d["kontrol_turu"] == 1
    assert d["kabul_kriterleri"][1]["metin"] == "Yeni metin."


def test_kod_hatasi_karari_son_engelleyiciyse_belge_son_hale_gelir(
    api: TestClient, analist: Any, engine: Engine, wired: dict[str, Any]
) -> None:
    bulgu = {
        "id": "F1",
        "type": "missing_in_code",
        "doc_ref": "AC1",
        "claim": "Kredi limiti uyarısı",
        "observed": "Kodda yok",
        "evidence": [
            {
                "kind": "code",
                "repo": "demo-app",
                "path": "api/src/demoapp_api/pricing.py",
                "line": 97,
                "snippet": (
                    "uyarilar.append(Uyari(UYARI_MIN_SIPARIS, min_siparis_mesaji(min_tutar)))"
                ),
            }
        ],
        "severity": "blocking",
        "suggested_doc_text": None,
    }
    make, _ = fake_gateway(
        [
            text_response({"questions": [], "verdict": "ready", "summary": "-"}),
            tool_response((FINAL_TOOL, {"findings": [bulgu], "notes": ""})),
        ]
    )
    wired["gateway"] = make
    rid = api.post(
        "/requirements/free-text", json={"baslik": "Kredi", "ac": ["Limit aşılırsa uyarı."]}
    ).json()["id"]
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    (f,) = _findings(api, rid)
    # fix_doc önerisi yok ve metin verilmedi → 422.
    yol = f"/findings/{f['id']}/decision"
    r = api.post(yol, json={"karar": "fix_doc", "icerik_hash": f["icerik_hash"]})
    assert r.status_code == 422
    r = api.post(yol, json={"karar": "code_defect", "icerik_hash": f["icerik_hash"]})
    assert r.status_code == 200 and r.json()["bug_draft_id"]
    assert api.get(f"/requirements/{rid}").json()["durum"] == "pending_po"
    # Uygulanacak düzeltme yok → 409.
    assert api.post(f"/requirements/{rid}/apply-doc-fixes").status_code == 409


def test_replay_yoksa_gereksinim_failed(
    api: TestClient, analist: Any, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_REPLAY_STRICT", "1")  # prova kipi: eşleşmeyen golden'a düşmez
    rid = api.post(
        "/requirements/free-text", json={"baslik": "Başka bir şey", "ac": ["Bir şey olur."]}
    ).json()["id"]
    api.post(f"/requirements/{rid}/review")
    sonuclar = run_jobs(engine)
    assert sonuclar[0].durum == "failed"
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "failed"
    with engine.connect() as c:
        sebep = c.execute(
            text(
                "SELECT ozet->>'sebep' FROM audit_event WHERE eylem = 'requirement.transition' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
        wf = c.execute(text("SELECT durum FROM workflow_instance")).scalar_one()
    assert "REPLAY" in sebep
    assert wf == "failed"
    # Başarısız gereksinim yeniden incelemeye alınabilir.
    assert api.post(f"/requirements/{rid}/review").status_code == 202


def test_tum_bulgular_elenirse_belge_otomatik_son_hal_olmaz(
    api: TestClient, analist: Any, engine: Engine, wired: dict[str, Any]
) -> None:
    """Dönen bulguların hiçbiri doğrulanamadıysa (ör. başka bir girdinin REPLAY çıktısı ya da
    halüsinasyon) bu "belge tutarlı" kanıtı değildir: fail-closed, analist açıkça son hale alır."""
    uydurma = {
        "id": "F1",
        "type": "doc_vs_code",
        "doc_ref": "AC1",
        "claim": "x",
        "observed": "Kod 10 adette 3 bedava veriyor",
        "evidence": [
            {
                "kind": "code",
                "repo": "demo-app",
                "path": "api/src/demoapp_api/campaign.py",
                "line": 23,
                "snippet": "return adet // 3",
            }
        ],
        "severity": "blocking",
        "suggested_doc_text": None,
    }
    make, _ = fake_gateway(
        [
            text_response({"questions": [], "verdict": "ready", "summary": "-"}),
            tool_response(
                (FINAL_TOOL, {"findings": [uydurma, {**uydurma, "id": "F2"}], "notes": ""})
            ),
        ]
    )
    wired["gateway"] = make
    rid = api.post(
        "/requirements/free-text", json={"baslik": "Kampanya", "ac": ["7 adette 1 bedava."]}
    ).json()["id"]
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "findings_open", d
    assert d["bulgu_sayaclari"] == {"dogrulanan": 0, "elenen": 2, "acik": 0}
    assert "hiçbiri doğrulanamadı" in d["denetim_guvenilmez"]
    assert d["insan_karari_gerekli"] is True
    assert any("güvenilir değil" in u for u in d["uyarilar"])
    assert d["po"]["durum"] == "not_requested"
    # Analist açık eylemle son hale alır; kayıt uyarıyı taşır.
    r = api.post(f"/requirements/{rid}/apply-doc-fixes")
    assert r.status_code == 202 and r.json()["durum"] == "done"
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "pending_po" and d["denetim_guvenilmez"] is None
    with engine.connect() as c:
        sebep = c.execute(
            text(
                "SELECT ozet->>'sebep' FROM audit_event WHERE eylem = 'requirement.doc_final' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
        aktor = c.execute(
            text(
                "SELECT aktor FROM audit_event WHERE eylem = 'requirement.doc_final' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
    assert "denetim uyarısına rağmen" in sebep and aktor == analist.kullanici_adi


def test_onceki_karar_belge_degisirse_devralinmaz(
    api: TestClient, analist: Any, engine: Engine, wired: dict[str, Any]
) -> None:
    """Devralma deterministik: AC metni değiştiyse aynı tür/kanıt olsa da analist yeniden karar
    verir (önceki karar başka bir metne aitti)."""
    kredi = {
        "id": "F1",
        "type": "missing_in_code",
        "doc_ref": "AC2",
        "claim": "Kredi limiti uyarısı",
        "observed": "Kodda yok",
        "evidence": [
            {
                "kind": "code",
                "repo": "demo-app",
                "path": "api/src/demoapp_api/pricing.py",
                "line": 97,
                "snippet": (
                    "uyarilar.append(Uyari(UYARI_MIN_SIPARIS, min_siparis_mesaji(min_tutar)))"
                ),
            }
        ],
        "severity": "blocking",
        "suggested_doc_text": None,
    }
    celiski = {
        "id": "F2",
        "type": "internal_contradiction",
        "doc_ref": "AC1",
        "claim": "c",
        "observed": "o",
        "evidence": [],
        "severity": "blocking",
        "suggested_doc_text": "AC1: Yeni birinci kriter.",
    }
    tur2_kredi = {**kredi, "id": "F1", "severity": "warning"}
    make, _ = fake_gateway(
        [
            text_response({"questions": [], "verdict": "ready", "summary": "-"}),
            tool_response((FINAL_TOOL, {"findings": [kredi, celiski], "notes": ""})),
            # Tur 2: AC2 aynı (devralınır); tur 3 için AC2 değişmiş belgede (devralınmaz).
            tool_response((FINAL_TOOL, {"findings": [tur2_kredi], "notes": ""})),
        ]
    )
    wired["gateway"] = make
    rid = api.post(
        "/requirements/free-text",
        json={"baslik": "Kredi", "ac": ["Birinci kriter.", "Limit aşılırsa uyarı."]},
    ).json()["id"]
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    f = {x["bulgu_no"]: x for x in _findings(api, rid)}
    r = api.post(
        f"/findings/{f['F1']['id']}/decision",
        json={"karar": "code_defect", "icerik_hash": f["F1"]["icerik_hash"]},
    )
    bug_id = r.json()["bug_draft_id"]
    api.post(
        f"/findings/{f['F2']['id']}/decision",
        json={"karar": "fix_doc", "icerik_hash": f["F2"]["icerik_hash"]},
    )
    api.post(f"/requirements/{rid}/apply-doc-fixes")
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "pending_po" and d["kontrol_turu"] == 2
    (t2,) = [x for x in _findings(api, rid) if x["kontrol_turu"] == 2]
    assert t2["durum"] == "stale" and t2["onceki_karar"]["karar"] == "code_defect"
    assert t2["bug_draft_id"] == bug_id and t2["karar"] == "code_defect"

    with new_session() as s:
        from tp_core.features.requirements import flow

        cf = s.get(ConsistencyFinding, t2["id"])
        onceki = flow.previous_decision(s, cf, "AC2: Limit aşılırsa uyarı.")
        assert onceki is not None and str(onceki.id) == f["F1"]["id"]
        assert flow.previous_decision(s, cf, "AC2: Limit aşılırsa HATA.") is None


def test_po_cevaplari_sorulara_eslenir_ve_mod_canli_varsayilmaz(engine: Engine) -> None:
    from tp_core.features.requirements import serialize
    from tp_core.models import Requirement, RequirementReview

    sorular = [
        {"id": "Q1", "type": "conflict", "text": "AC3 ile AC6?", "ac_ref": "AC6"},
        {"id": "Q2", "type": "ambiguity", "text": "AC2?", "ac_ref": "AC2"},
        {"id": "Q3", "type": "missing_ac", "text": "Taban?", "ac_ref": None},
    ]
    cevaplar = [
        {
            "id": "1",
            "metin": "Q1: kampanyalı siparişte minimum aranmaz. Q2: 6 adette 1. Onaylıyorum.",
        },
        {"id": "2", "metin": "Teşekkürler, onaylıyorum."},
        {"id": "3", "metin": "q2 - ek not"},
    ]
    eslesme = serialize.map_po_answers(sorular, cevaplar)
    assert eslesme == {
        "Q1": "kampanyalı siparişte minimum aranmaz.",
        "Q2": "6 adette 1. Onaylıyorum. / ek not",
    }
    with new_session() as s:
        req = Requirement(
            kaynak="free_text",
            baslik="x",
            aciklama="",
            kabul_kriterleri=["AC1: a"],
            kaynak_hash="h",
            po_cevaplari=cevaplar,
        )
        s.add(req)
        s.flush()
        s.add(RequirementReview(requirement_id=req.id, sorular=sorular, verdict="needs_po"))
        s.flush()
        on = serialize._on_inceleme(s, req)
        assert on is not None
        assert on["mode"] is None  # üretim modu bilinmiyorsa asla "live" denmez
        assert [q["cevap"] for q in on["questions"]] == [
            eslesme["Q1"],
            eslesme["Q2"],
            None,
        ]
        cf = ConsistencyFinding(
            requirement_id=req.id,
            kontrol_turu=1,
            tur="ambiguous",
            doc_ref="AC1",
            kanitlar=[],
            severity="warning",
        )
        s.add(cf)
        s.flush()
        assert serialize.one_finding(s, cf)["mode"] is None
        s.rollback()
