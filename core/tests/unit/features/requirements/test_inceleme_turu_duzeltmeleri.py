"""Faz 2 inceleme turu bulgularının regresyon testleri (gereksinim akışı).

- Aynı düzeltmenin A→B→A sonrasında yeniden uygulanması (bayat idempotency kaydı).
- Bulgu listesi/sayaçlarının güncel inceleme döngüsüyle sınırlanması.
- Golden'ı olmayan story'nin dürüst REPLAY-MISS yoluna düşmesi; başarısızlık nedeninin detayda
  görünmesi.
- PO soru yorumu işinin kalıcı hatadan kurtarılması; yorumdan önce konan etiketin sayılmaması;
  bayat etiket kaldırılırken PO'nun yeni etiketiyle yarış (TOCTOU) ve PO'ya bildirim.
- PO yorumundaki ön inceleme özetinin düzeltmelerden sonra "özgün metne göre" etiketlenmesi.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.features.requirements import flow
from tp_core.features.requirements.content import DocFix, merge_fixes, requirement_hash
from tp_core.features.requirements.settings import get_requirements_settings
from tp_core.integrations.jira import RestJira
from tp_core.integrations.jira_adf import build_description
from tp_core.models import ExternalRef, new_session
from tp_core.workflow.jobs import process_one

from .conftest import PoActions, login, run_jobs

pytestmark = pytest.mark.usefixtures("wired")


@pytest.fixture
def analist(api: TestClient, make_user) -> Any:
    u = make_user("analyst")
    login(api, u)
    return u


def _req_id(api: TestClient, key: str) -> str:
    return next(r["id"] for r in api.get("/requirements").json() if r["jira_key"] == key)


def _detay(api: TestClient, rid: str) -> dict[str, Any]:
    r = api.get(f"/requirements/{rid}")
    assert r.status_code == 200, r.text
    return r.json()


def _jira_hash(jira: RestJira, key: str) -> str:
    it = jira.get_issue(key)
    return requirement_hash(it.summary, it.description, list(it.acceptance_criteria))


# ------------------------------------------------------------- A→B→A yeniden uygulama


def test_ayni_duzeltme_geri_alinan_storyye_yeniden_yazilir(
    api: TestClient, analist: Any, engine: Engine, jira: RestJira, po: PoActions
) -> None:
    """TPD-1 düzeltilir (A→B), story Jira'da geri alınır (B→A), aynı düzeltme yeniden uygulanır:
    eski `created` kaydı yazımı atlatıp gereksinimi kalıcı `failed`'a sokmamalı."""
    api.post("/requirements/sync")
    rid = uuid.UUID(_req_id(api, "TPD-1"))
    it = jira.get_issue("TPD-1")
    seed_desc, seed_acs = it.description, list(it.acceptance_criteria)
    a = _jira_hash(jira, "TPD-1")
    ac2 = "AC2: Kampanyalı üründen her 6 adette 1 adet bedava verilir."
    merge = merge_fixes(seed_desc, seed_acs, [DocFix("F2 (tur 1)", "AC2", ac2)])
    b = requirement_hash(it.summary, merge.aciklama, merge.kabul_kriterleri)
    assert a != b

    ilk_akis = uuid.uuid4()
    flow.write_fix_to_jira(engine, rid, "TPD-1", it.summary, a, b, merge, is_kimligi=ilk_akis)
    assert _jira_hash(jira, "TPD-1") == b

    # PO story'yi özgün metne geri alır (A).
    po.set_description("TPD-1", seed_desc, seed_acs)
    assert _jira_hash(jira, "TPD-1") == a

    # Yeni düzeltme akışı: yeni anahtar → yazılır.
    flow.write_fix_to_jira(engine, rid, "TPD-1", it.summary, a, b, merge, is_kimligi=uuid.uuid4())
    assert _jira_hash(jira, "TPD-1") == b

    # Derinlemesine savunma: aynı akış (aynı anahtar) yeniden denenirken story yine geri alınmışsa
    # `created` kaydı Jira'da ölçülür; etki yoksa yeniden yazılır (FlowError değil).
    po.set_description("TPD-1", seed_desc, seed_acs)
    flow.write_fix_to_jira(engine, rid, "TPD-1", it.summary, a, b, merge, is_kimligi=ilk_akis)
    assert _jira_hash(jira, "TPD-1") == b
    with new_session() as s:
        refs = list(
            s.scalars(
                select(ExternalRef).where(
                    ExternalRef.idempotency_key.like(f"jira:update_description:{rid}:%")
                )
            )
        )
    assert len(refs) == 2 and all(r.durum == "created" for r in refs)
    with engine.connect() as c:
        bayat = c.execute(
            text("SELECT count(*) FROM audit_event WHERE eylem = 'external_ref.stale'")
        ).scalar_one()
    assert bayat == 1
    # Her akışın özet yorumu ayrıdır (aynı akış ikinci kez yorum yazmaz).
    ozet = [c for c in jira.get_comments("TPD-1") if "doküman düzeltmesi" in c.body]
    assert len(ozet) == 2


# ------------------------------------------------------------ güncel döngü kapsamı


def test_bulgu_listesi_guncel_dongu_ile_sinirli(
    api: TestClient,
    analist: Any,
    engine: Engine,
    jira: RestJira,
    po: PoActions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TP_CONSISTENCY_MAX_ROUNDS", "1")
    get_requirements_settings.cache_clear()
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-1")
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    ilk = {f["bulgu_no"]: f for f in api.get(f"/requirements/{rid}/findings").json()}
    assert set(ilk) == {"F1", "F2", "F3", "F4"}
    # Jira yorumundaki etiketle aynı biçim (portal kartı ↔ Jira yorumu eşlemesi).
    assert ilk["F2"]["bulgu_etiketi"] == "F2 (tur 1)"
    r = api.post(
        f"/findings/{ilk['F4']['id']}/decision",
        json={"karar": "code_defect", "icerik_hash": ilk["F4"]["icerik_hash"]},
    )
    assert r.status_code == 200, r.text

    # Story Jira'da değişir; tur sınırı dolu → gereksinim baştan incelenecek (`new`).
    it = jira.get_issue("TPD-1")
    seed_desc, seed_acs = it.description, list(it.acceptance_criteria)
    po.set_description("TPD-1", seed_desc + " Güncellendi.", seed_acs)
    assert api.post("/requirements/sync").json()["sonuc"]["TPD-1"] == "sifirlandi"
    d = _detay(api, rid)
    assert d["durum"] == "new"
    # Önceki döngünün bulguları varsayılan listede yok; geçmiş `tumu=true`'da.
    r = api.get(f"/requirements/{rid}/findings")
    assert r.json() == [] and r.headers["X-Elenen-Bulgu-Sayisi"] == "0"
    assert d["bulgu_sayaclari"] == {"dogrulanan": 0, "elenen": 0, "acik": 0}
    assert len(api.get(f"/requirements/{rid}/findings", params={"tumu": True}).json()) == 4

    # Özgün metne dönülür ve yeniden incelenir (golden eşleşir): tek döngünün bulguları.
    po.set_description("TPD-1", seed_desc, seed_acs)
    api.post("/requirements/sync")
    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine)
    yeni = api.get(f"/requirements/{rid}/findings").json()
    numaralar = [f["bulgu_no"] for f in yeni]
    assert sorted(numaralar) == ["F1", "F2", "F3", "F4"], numaralar  # tekrar eden numara yok
    assert all(f["id"] not in {x["id"] for x in ilk.values()} for f in yeni)
    # F4: aynı fark önceki döngüde "kod hatalı" kararıyla kapanmıştı → karar devralındı.
    f4 = next(f for f in yeni if f["bulgu_no"] == "F4")
    assert f4["durum"] == "stale" and f4["onceki_karar"]["karar"] == "code_defect"
    d = _detay(api, rid)
    assert d["bulgu_sayaclari"] == {"dogrulanan": 4, "elenen": 0, "acik": 3}
    assert len(api.get(f"/requirements/{rid}/findings", params={"tumu": True}).json()) == 8


# ------------------------------------------------- golden'sız story ve hata nedeni


def _yeni_story(jira: RestJira, ozet: str, aciklama: str, acs: list[str]) -> str:
    return jira.create_issue(
        "TPD", "Story", ozet, "", fields={"description": build_description(aciklama, acs)}
    )


def test_goldeni_olmayan_story_replay_miss_yoluna_duser(
    api: TestClient,
    analist: Any,
    engine: Engine,
    jira: RestJira,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _yeni_story(
        jira,
        "Sepete not ekleme",
        "Bayi sepete sipariş notu ekleyebilmelidir.",
        ["AC1: Not en fazla 200 karakterdir.", "AC2: Not sipariş özetinde görünür."],
    )
    api.post("/requirements/sync")
    rid = _req_id(api, key)
    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine)
    d = _detay(api, rid)
    # ReplayNotFound ile nedensiz `failed` değil: nötr yedek, dürüst REPLAY-MISS etiketi.
    assert d["durum"] == "findings_open", d
    assert d["on_inceleme"]["mode"] == "replay_miss"
    assert d["on_inceleme"]["questions"] == []
    assert d["son_kontrol"]["mode"] == "replay_miss"
    assert d["insan_karari_gerekli"] is True and "REPLAY-MISS" in d["denetim_guvenilmez"]
    assert d["son_hata"] is None
    with engine.connect() as c:
        modlar = set(c.execute(text("SELECT mod FROM ai_call")).scalars())
    assert modlar == {"replay_miss"}

    # Prova kipinde (TP_REPLAY_STRICT=1) eşleşmeyen girdi hata verir: neden ve öneri görünür.
    monkeypatch.setenv("TP_REPLAY_STRICT", "1")
    assert api.post(f"/requirements/{rid}/review").status_code == 202
    run_jobs(engine)
    d = _detay(api, rid)
    assert d["durum"] == "failed"
    hata = d["son_hata"]
    assert hata is not None and "REPLAY" in hata["neden"]
    assert hata["job_tur"] == flow.JOB_CONSISTENCY
    assert hata["yeniden_denemek_ise_yarar"] is False
    assert "yeniden denemek sonucu değiştirmez" in hata["oneri"]
    assert any(u.startswith("Son işlem başarısız") for u in d["uyarilar"])


def test_takili_is_hatasi_yeniden_denenebilir_olarak_gosterilir(
    api: TestClient, analist: Any, engine: Engine
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    api.post(f"/requirements/{rid}/review")
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE job SET durum = 'failed', son_hata = 'worker yeniden başladı; iş yarıda "
                "kaldı' WHERE tur = :t"
            ),
            {"t": flow.JOB_REVIEW},
        )
    flow.sweep_stuck(engine)
    d = _detay(api, rid)
    assert d["durum"] == "failed"
    assert "yarıda kaldı" in d["son_hata"]["neden"]
    assert d["son_hata"]["yeniden_denemek_ise_yarar"] is True
    assert d["son_hata"]["job_tur"] == flow.JOB_REVIEW


# ------------------------------------------------------ PO soru yorumu ve etiket


def _po_istegini_kalici_basarisiz_yap(engine: Engine) -> None:
    for _ in range(10):
        with engine.begin() as c:
            kalan = c.execute(
                text(
                    "UPDATE job SET run_after = now() WHERE tur = :t "
                    "AND durum IN ('queued', 'retry') RETURNING id"
                ),
                {"t": flow.JOB_PO_REQUEST},
            ).all()
        if not kalan:
            return
        process_one(engine, worker="test-worker:1")
    raise AssertionError("po_request işi bitmedi")


def test_po_istegi_kalici_hatadan_kurtarilir(
    api: TestClient,
    analist: Any,
    engine: Engine,
    jira: RestJira,
    po: PoActions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tp_core.integrations.jira import JiraError

    gercek = jira.add_comment

    def erisilemez(key: str, body: str) -> str:
        raise JiraError("Jira'ya erişilemedi (test)")

    monkeypatch.setattr(jira, "add_comment", erisilemez)
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    _po_istegini_kalici_basarisiz_yap(engine)
    d = _detay(api, rid)
    assert d["durum"] == "pending_po"
    assert d["po_istegi"]["durum"] == "basarisiz" and "erişilemedi" in d["po_istegi"]["hata"]
    assert any("soru yorumu Jira'ya yazılamadı" in u for u in d["uyarilar"])
    assert not [c for c in jira.get_comments("TPD-4") if "ön inceleme" in c.body]

    # PO soruları görmeden (yorum yazılmadan, ama son halden sonra) etiket koyar: onay sayılmaz.
    time.sleep(0.01)
    po.add_label("TPD-4")
    monkeypatch.setattr(jira, "add_comment", gercek)
    sonuc = flow.run_po_poll(engine)["kontrol"][rid]
    assert sonuc == "bayat_etiket_kaldirildi"
    assert "tp-po-approved" not in jira.get_issue("TPD-4").labels
    bildirim = [c for c in jira.get_comments("TPD-4") if "etiketi kaldırıldı" in c.body]
    assert len(bildirim) == 1 and "henüz yazılmadan" in bildirim[0].body
    assert _detay(api, rid)["durum"] == "pending_po"

    # PO sorgusu soru yorumu işini yeniden kuyruğa aldı: yorum ve bekleme etiketi yazılır.
    run_jobs(engine)
    yorumlar = [c for c in jira.get_comments("TPD-4") if "ön inceleme" in c.body]
    assert len(yorumlar) == 1
    d = _detay(api, rid)
    assert d["po_istegi"] == {
        "durum": "yazildi",
        "jira_comment_id": yorumlar[0].id,
        "hata": None,
    }
    assert "tp-po-pending" in jira.get_issue("TPD-4").labels
    with engine.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM audit_event "
                    "WHERE eylem = 'requirement.po_request_requeued'"
                )
            ).scalar_one()
            == 1
        )

    # Yorumdan sonra konan etiket onaydır.
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][rid] == "onaylandi"


def test_bayat_etiket_kaldirilirken_yeni_onay_yarisi_poya_bildirilir(
    api: TestClient,
    analist: Any,
    engine: Engine,
    jira: RestJira,
    po: PoActions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Okuma (taze onay yok) ile kaldırma arasında PO etiketi yeniden koyar: bot etiketi geri
    koyamaz; kaldırma sonrası geçmiş yeniden okunur ve PO'dan etiketi yeniden eklemesi istenir."""
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    po.add_label("TPD-4")  # incelemeden önce: bayat
    api.post(f"/requirements/{rid}/review")
    gercek = jira.remove_labels
    yarista: list[bool] = []

    def yarisli_kaldir(key: str, labels: Any) -> None:
        if "tp-po-approved" in labels and not yarista:
            yarista.append(True)
            time.sleep(0.01)
            po.remove_label(key)
            po.add_label(key)  # PO soru yorumunu görüp onaylıyor (aynı anda)
        gercek(key, labels)

    monkeypatch.setattr(jira, "remove_labels", yarisli_kaldir)
    run_jobs(engine)
    assert yarista
    assert "tp-po-approved" not in jira.get_issue("TPD-4").labels
    bildirim = [c for c in jira.get_comments("TPD-4") if "etiketi kaldırıldı" in c.body]
    assert len(bildirim) == 1 and "zamanlama çakışması" in bildirim[0].body
    with engine.connect() as c:
        ozet = c.execute(
            text(
                "SELECT ozet->>'sonuc' FROM audit_event "
                "WHERE eylem = 'requirement.po_label_removed' ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
    assert ozet == "yarista_kaldirildi"
    assert _detay(api, rid)["durum"] == "pending_po"


# ------------------------------------------------------------- PO yorum metni


def test_po_yorumu_degisen_maddelerde_ozeti_ozgun_metne_gore_etiketler() -> None:
    sorular = [
        {"id": "Q1", "type": "conflict", "ac_ref": "AC3", "text": "AC3 ile AC6 çelişiyor"},
        {"id": "Q2", "type": "ambiguity", "ac_ref": "AC4", "text": "Limit neye göre?"},
    ]
    govde = flow.review_comment(
        "TPD-1",
        "needs_po",
        sorular,
        "replay",
        "tip",
        "tp-x",
        degisen={"AC3", "AC2"},
        ozet="AC3 ile AC6 çelişiyor",
    )
    assert (
        "AI özeti (özgün metne göre, doküman düzeltmelerinden önce yazıldı; AC2, AC3 sonradan "
        "değişti; model çıktısı, karar dayanağı değildir): AC3 ile AC6 çelişiyor"
    ) in govde
    assert "bu yorumdan önce konmuş etiket onay sayılmaz" in govde
    sade = flow.review_comment("TPD-1", "needs_po", sorular, "replay", "tip", "tp-x", ozet="Özet")
    assert "AI özeti (model çıktısı, karar dayanağı değildir): Özet" in sade
