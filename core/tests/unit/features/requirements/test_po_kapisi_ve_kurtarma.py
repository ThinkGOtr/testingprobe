"""PO kapısının Jira etiketiyle sürekli bağlı kalması (geri çekilme, bayat etiket), takılı iş
kurtarma (sahipsiz iş, zaman aşımı), başarısız turdan yeniden başlatmada tur sınırı ve PO sorgu
işlerinin temizliği. Gerçek Postgres, süreç içi jira-sim, REPLAY geçidi ve worker iş yürütücüsü.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.features.cases import jobs as _case_jobs  # noqa: F401 — cases.generate işleyicisi
from tp_core.features.requirements import flow
from tp_core.features.requirements.settings import get_requirements_settings
from tp_core.gateway import FINAL_TOOL
from tp_core.gateway.testing import text_response, tool_response
from tp_core.integrations.jira import RestJira
from tp_core.models import Requirement, TestCase, new_session
from tp_core.workflow.jobs import (
    claim,
    fail,
    fail_workflows,
    process_one,
    reap_stale,
    release_orphans,
)

from .conftest import PoActions, fake_gateway, login, run_jobs

pytestmark = pytest.mark.usefixtures("wired")


@pytest.fixture
def analist(api: TestClient, make_user) -> Any:
    u = make_user("analyst")
    login(api, u)
    return u


def _req_id(api: TestClient, key: str) -> str:
    return next(r["id"] for r in api.get("/requirements").json() if r["jira_key"] == key)


def _durum(api: TestClient, rid: str) -> dict[str, Any]:
    return api.get(f"/requirements/{rid}").json()


def _po_onayli_tpd4(api: TestClient, engine: Engine, po: PoActions) -> str:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine)
    assert _durum(api, rid)["durum"] == "pending_po"
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][rid] == "onaylandi"
    return rid


# ------------------------------------------------------------- PO etiketi zamanı


def test_incelemeden_once_konan_etiket_onay_sayilmaz(
    api: TestClient, analist: Any, engine: Engine, jira: RestJira, po: PoActions
) -> None:
    """TPD-4 temiz (verdict ready, bulgu yok): önceden duran tp-po-approved insan kapısını
    sessizce geçirmemeli. Etiket ancak belge son hal olduktan sonra konursa onaydır."""
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    po.add_label("TPD-4")  # PO soruları/son hali görmeden
    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine)
    d = _durum(api, rid)
    assert d["durum"] == "pending_po" and d["po"]["durum"] == "pending"
    # Son hal işi: soru yorumu yazıldı, bayat onay etiketi kaldırıldı, bekleme etiketi kondu.
    etiketler = jira.get_issue("TPD-4").labels
    assert "tp-po-approved" not in etiketler and "tp-po-pending" in etiketler
    assert flow.run_po_poll(engine)["kontrol"][rid] == "bekliyor"
    assert _durum(api, rid)["durum"] == "pending_po"

    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][rid] == "onaylandi"
    d = _durum(api, rid)
    assert d["durum"] == "po_approved" and d["po"]["onaylayan"] == "po@sim.local"


def test_son_halden_once_konan_etiket_poll_ile_kaldirilir(
    api: TestClient, analist: Any, engine: Engine, jira: RestJira, po: PoActions
) -> None:
    """Son hal işi henüz koşmadan (ör. Jira'ya erişilemedi) poll önceden duran etiketi görürse
    onay kaydetmez; etiketi kaldırır ve bekleme etiketini koyar."""
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    po.add_label("TPD-4")
    api.post(f"/requirements/{rid}/review")
    # Yalnızca ön inceleme + tutarlılık işlerini koş; son hal (po_request) işi koşmasın.
    for _ in range(2):
        process_one(engine, worker="test-worker:1")
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET durum = 'cancelled' WHERE tur = :t AND durum = 'queued'"),
            {"t": flow.JOB_PO_REQUEST},
        )
    assert _durum(api, rid)["durum"] == "pending_po"
    assert "tp-po-approved" in jira.get_issue("TPD-4").labels
    assert flow.run_po_poll(engine)["kontrol"][rid] == "bayat_etiket_kaldirildi"
    etiketler = jira.get_issue("TPD-4").labels
    assert "tp-po-approved" not in etiketler and "tp-po-pending" in etiketler
    assert _durum(api, rid)["durum"] == "pending_po"


# ----------------------------------------------------- geri çekilme: case sonrası


def test_case_uretiminden_sonra_geri_cekilen_onay_kapiyi_kapatir(
    api: TestClient, analist: Any, engine: Engine, po: PoActions
) -> None:
    """Canlıda bulunan hata: PO etiketi cases_ready'de kaldırıldığında gereksinim onaylı kalıyor
    ve onaylı case yayınlanabiliyordu. Artık poll geri çekilmeyi görür: gereksinim new, onaylanan
    hash silinir; yayın kapısı (gereksinim + güncel PO onayı) onaylı case'i yayınlamaz."""
    from tp_core.features.publish.service import _engel

    rid = _po_onayli_tpd4(api, engine, po)
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202, r.text
    run_jobs(engine)
    assert _durum(api, rid)["durum"] == "cases_ready"
    cases = api.get("/cases", params={"requirement_id": rid}).json()
    assert cases
    c0 = cases[0]
    r = api.post(
        f"/cases/{c0['id']}/decision", json={"karar": "approve", "icerik_hash": c0["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    # Etiket yerindeyken poll onayı korur.
    assert flow.run_po_poll(engine)["kontrol"][rid] == "onayli"

    po.remove_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][rid] == "geri_cekildi:new"
    d = _durum(api, rid)
    assert d["durum"] == "new" and d["po"]["durum"] == "not_requested"
    with new_session() as s:
        req = s.get(Requirement, rid)
        assert req.onaylanan_hash is None and req.po_onaylayan is None
        tcs = list(s.scalars(select(TestCase).where(TestCase.requirement_id == req.id)))
        onayli = [tc for tc in tcs if tc.durum == "approved"]
        assert len(onayli) == 1
        assert all(_engel(s, tc) for tc in tcs)  # hiçbiri yayınlanamaz
    # Yeniden case üretimi de kapalı (PO onayı yok).
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 409
    with engine.connect() as c:
        ozet = c.execute(
            text(
                "SELECT ozet FROM audit_event WHERE eylem = 'requirement.po_withdrawn' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
    assert ozet["onceki_durum"] == "cases_ready"
    assert len(ozet["yayinlanmamis_case_ids"]) == len(tcs) and ozet["yayinlanmis_case_ids"] == []


def test_uretim_surerken_geri_cekilen_onay(
    api: TestClient, analist: Any, engine: Engine, po: PoActions
) -> None:
    """Etiket, üretim başladıktan sonra (iş kuyruktayken) kalkarsa bir sonraki poll gereksinimi
    (generating → failed → new) geri alır; üretim işi sonuç yazmaz. (Başlatma anında etiket
    yoksa generate-cases zaten 409 döner — aşağıdaki eşzamanlı denetim testi.)"""
    rid = _po_onayli_tpd4(api, engine, po)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    po.remove_label("TPD-4")
    assert _durum(api, rid)["durum"] == "generating"
    assert flow.run_po_poll(engine)["kontrol"][rid] == "geri_cekildi:new"
    run_jobs(engine)
    assert _durum(api, rid)["durum"] == "new"
    assert api.get("/cases", params={"requirement_id": rid}).json() == []


# ------------------------------------------------------------------- kurtarma


def test_sahipsiz_tutarlilik_isi_gereksinimi_kilitlemez(
    api: TestClient, analist: Any, engine: Engine
) -> None:
    """Worker iş ortasında öldü (claim → release_orphans). Eskiden gereksinim in_review'da
    sonsuza dek kalıyordu ve yeniden inceleme 409 dönüyordu."""
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-1")
    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine, limit=1)  # ön inceleme; tutarlılık işi kuyrukta
    with engine.begin() as c:
        alinan = claim(c, "host-a:2", [flow.JOB_CONSISTENCY])
    assert alinan is not None
    with engine.begin() as c:
        assert release_orphans(c, host="host-a") == 1
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT durum FROM job WHERE id = :i"), {"i": alinan.id}).scalar_one()
            == "failed"
        )
    assert _durum(api, rid)["durum"] == "in_review"
    # Analist yeniden başlatabilir: takılı iş tespit edilir, gereksinim önce failed olur.
    r = api.post(f"/requirements/{rid}/review")
    assert r.status_code == 202, r.text
    with engine.connect() as c:
        eylemler = list(
            c.execute(
                text("SELECT eylem FROM audit_event WHERE nesne = :n ORDER BY id"),
                {"n": f"requirement:{rid}"},
            ).scalars()
        )
    assert "requirement.recovered" in eylemler
    run_jobs(engine)
    assert _durum(api, rid)["durum"] == "findings_open"


def test_zaman_asimi_sonrasi_supurme_gereksinimi_failed_yapar(
    api: TestClient, analist: Any, engine: Engine
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-1")
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine, limit=1)
    with engine.begin() as c:
        alinan = claim(c, "host-b:1", [flow.JOB_CONSISTENCY])
        c.execute(
            text("UPDATE job SET baslama = now() - interval '2 hours' WHERE id = :i"),
            {"i": alinan.id},
        )
    with engine.begin() as c:
        assert reap_stale(c) == 1
    assert _durum(api, rid)["durum"] == "in_review"
    sonuc = flow.run_po_poll(engine)
    assert sonuc["kurtarilan"] == [rid]
    d = _durum(api, rid)
    assert d["durum"] == "failed"
    # Kurtarma, sorgunun kendini planlamasını gerektirdi (in_review izlenir); artık izlenecek yok.
    assert api.post(f"/requirements/{rid}/review").status_code == 202


def test_takili_generating_kurtarilir(
    api: TestClient, analist: Any, engine: Engine, po: PoActions
) -> None:
    rid = _po_onayli_tpd4(api, engine, po)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    with engine.begin() as c:
        alinan = claim(c, "host-c:1", ["cases.generate"])
        assert alinan is not None
        fail(c, alinan.id, "host-c:1", "zaman aşımı: iş süresini aştı", retry_in_s=None)
        fail_workflows(c, {alinan.workflow_id: "zaman aşımı"})
    assert _durum(api, rid)["durum"] == "generating"
    assert flow.run_po_poll(engine)["kurtarilan"] == [rid]
    assert _durum(api, rid)["durum"] == "failed"


def test_etkin_isi_olan_gereksinim_kurtarilmaz(
    api: TestClient, analist: Any, engine: Engine
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-1")
    api.post(f"/requirements/{rid}/review")
    assert flow.sweep_stuck(engine) == []
    with new_session() as s:
        assert not flow.stuck(s, s.get(Requirement, rid).id)
    assert _durum(api, rid)["durum"] == "in_review"


# ----------------------------------------------------------- tur sınırı (failed)


def test_basarisiz_turdan_yeniden_baslatma_tur_sayacini_sifirlamaz(
    api: TestClient,
    analist: Any,
    engine: Engine,
    wired: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TP_CONSISTENCY_MAX_ROUNDS", "2")
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
    # Tur 1 bulgu döner; tur 2'de model çağrısı kalıcı hata verir (senaryo biter).
    make, provider = fake_gateway(
        [
            text_response({"questions": [], "verdict": "ready", "summary": "-"}),
            tool_response((FINAL_TOOL, {"findings": [bulgu], "notes": ""})),
        ]
    )
    wired["gateway"] = make
    rid = api.post(
        "/requirements/free-text",
        json={"baslik": "Çelişki", "ac": ["Tüm siparişlerde minimum aranır.", "Kampanyalıda yok."]},
    ).json()["id"]
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    (f,) = api.get(f"/requirements/{rid}/findings").json()
    r = api.post(
        f"/findings/{f['id']}/decision", json={"karar": "fix_doc", "icerik_hash": f["icerik_hash"]}
    )
    assert r.status_code == 200
    assert api.post(f"/requirements/{rid}/apply-doc-fixes").status_code == 202
    run_jobs(engine)
    d = _durum(api, rid)
    assert d["durum"] == "failed" and d["kontrol_turu"] == 2

    # Yeniden başlatma: aynı (2.) tur yeniden koşar; tur hakkı yenilenmez (eskiden 1'e dönüyordu).
    provider.script.append(tool_response((FINAL_TOOL, {"findings": [bulgu], "notes": ""})))
    r = api.post(f"/requirements/{rid}/review")
    assert r.status_code == 202, r.text
    assert "tur 2" in r.json()["mesaj"]
    assert _durum(api, rid)["kontrol_turu"] == 2
    run_jobs(engine)
    d = _durum(api, rid)
    assert d["durum"] == "findings_open" and d["kontrol_turu"] == 2
    assert d["insan_karari_gerekli"] is True
    r = api.post(f"/requirements/{rid}/review")
    assert r.status_code == 409 and "sınır" in r.json()["detail"]


# --------------------------------------------------------------- PO sorgu işleri


def test_po_sorgu_isleri_birikmez(api: TestClient, analist: Any, engine: Engine) -> None:
    with engine.begin() as c:
        for _ in range(5):
            c.execute(
                text(
                    "INSERT INTO job (tur, yuk, durum, deneme, bitis, guncelleme) "
                    "VALUES (:t, '{}'::jsonb, 'done', 1, now() - interval '2 hours', "
                    "now() - interval '2 hours')"
                ),
                {"t": flow.JOB_PO_POLL},
            )
        c.execute(
            text(
                "INSERT INTO job (tur, yuk, durum, deneme, bitis) "
                "VALUES (:t, '{}'::jsonb, 'done', 1, now())"
            ),
            {"t": flow.JOB_PO_POLL},
        )
    sonuc = flow.run_po_poll(engine)
    assert sonuc["silinen_eski_is"] == 5
    with engine.connect() as c:
        kalan = c.execute(
            text("SELECT count(*) FROM job WHERE tur = :t AND durum = 'done'"),
            {"t": flow.JOB_PO_POLL},
        ).scalar_one()
    assert kalan == 1


def test_po_etiketi_eszamanli_denetim(
    api: TestClient, analist: Any, engine: Engine, po: PoActions
) -> None:
    """Case üretimi başlatan kodun poll'u beklemeden kullanabileceği eşzamanlı denetim."""
    rid = _po_onayli_tpd4(api, engine, po)
    with new_session() as s:
        assert flow.po_label_current(s.get(Requirement, rid)) is True
    po.remove_label("TPD-4")
    with new_session() as s:
        assert flow.po_label_current(s.get(Requirement, rid)) is False


def test_etiket_kalktiktan_sonra_poll_beklenmeden_uretim_ve_ide_reddedilir(
    api: TestClient, analist: Any, engine: Engine, po: PoActions
) -> None:
    """Etiket kaldırıldı, poll henüz koşmadı (gereksinim hâlâ po_approved): case üretimi ve IDE
    taslağı eşzamanlı Jira denetimiyle 409 alır; gereksinim po_approved'da kalır."""
    from tp_core.features.cases import service as cases_service
    from tp_core.workflow.service import GateClosed, Principal

    rid = _po_onayli_tpd4(api, engine, po)
    po.remove_label("TPD-4")
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 409, r.text
    assert "tp-po-approved" in r.json()["detail"]
    assert _durum(api, rid)["durum"] == "po_approved"
    ide = Principal(
        id=analist.id,
        kullanici_adi=analist.kullanici_adi,
        rol="analyst",
        kanal="ide",
        kapsam="submit",
    )
    with new_session() as s, pytest.raises(GateClosed):
        cases_service.submit_drafts(s, "TPD-4", [{"title": "x"}], ide)
    # Etiket geri gelince kapı yeniden açılır (aynı PO onayı, aynı hash).
    po.add_label("TPD-4")
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
