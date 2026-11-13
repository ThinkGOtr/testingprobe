"""Uçtan uca Jira yolu (§2 adım 1–3): senkron → ön inceleme + tutarlılık (REPLAY) → kanıt
doğrulama → analist kararları → düzeltmelerin Jira'ya yazılması + yeniden kontrol → PO etiketi.

Gerçek HTTP API (TestClient), gerçek worker iş yürütücüsü (`process_one`), süreç içi jira-sim,
demo-app/'dan kurulan LocalForge ve demoapp_ro veritabanı kullanılır.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text

from tp_core.features.requirements import flow
from tp_core.gateway import FINAL_TOOL
from tp_core.gateway.testing import tool_response
from tp_core.integrations.jira import RestJira
from tp_core.integrations.jira_adf import BOT_PREFIX, strip_bot_header
from tp_core.models import BugDraft, ExternalRef, Requirement, Review, new_session

from .conftest import PO_AUTH, PoActions, fake_gateway, login, run_jobs

pytestmark = pytest.mark.usefixtures("wired")


def _req_id(api: TestClient, key: str) -> str:
    return next(r["id"] for r in api.get("/requirements").json() if r["jira_key"] == key)


def _findings(api: TestClient, rid: str) -> dict[str, dict[str, Any]]:
    r = api.get(f"/requirements/{rid}/findings")
    assert r.status_code == 200, r.text
    return {f["bulgu_no"]: f for f in r.json()}


def _decide(api: TestClient, f: dict[str, Any], karar: str, **kw: Any) -> Any:
    return api.post(
        f"/findings/{f['id']}/decision",
        json={"karar": karar, "icerik_hash": f["icerik_hash"], **kw},
    )


def _eylemler(engine: Engine) -> list[str]:
    with engine.connect() as c:
        return list(c.execute(text("SELECT eylem FROM audit_event ORDER BY id")).scalars())


@pytest.fixture
def analist(api: TestClient, make_user) -> Any:
    u = make_user("analyst")
    login(api, u)
    return u


def test_senkron_story_listesi_ve_idempotent(api: TestClient, analist: Any) -> None:
    r = api.post("/requirements/sync")
    assert r.status_code == 200, r.text
    assert r.json()["sonuc"] == {k: "yeni" for k in ("TPD-1", "TPD-2", "TPD-3", "TPD-4")}
    liste = {g["jira_key"]: g for g in api.get("/requirements").json()}
    assert liste["TPD-2"]["ac_missing"] is True and liste["TPD-1"]["ac_missing"] is False
    assert [a["ref"] for a in liste["TPD-1"]["kabul_kriterleri"]] == [f"AC{i}" for i in range(1, 7)]
    assert liste["TPD-1"]["durum"] == "new" and liste["TPD-1"]["po"]["durum"] == "not_requested"
    d = api.get(f"/requirements/{liste['TPD-1']['id']}").json()
    assert d["icerik_hash"] == d["kaynak_hash"]
    assert d["jira_url"].endswith("/browse/TPD-1")
    assert api.post("/requirements/sync").json()["sonuc"]["TPD-1"] == "degismedi"


def test_yetkiler(api: TestClient, make_user) -> None:
    assert api.get("/requirements").status_code == 401
    login(api, make_user("po"))
    assert api.post("/requirements/sync").status_code == 403
    assert api.post("/requirements/free-text", json={"baslik": "x"}).status_code == 403


def _adf_yorumlar(sim: TestClient, key: str) -> list[dict[str, Any]]:
    r = sim.get(f"/rest/api/3/issue/{key}/comment", auth=PO_AUTH)
    assert r.status_code == 200, r.text
    return [c["body"] for c in r.json()["comments"]]


def _adf_metin(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("text") or "") + "".join(
            _adf_metin(c) for c in node.get("content") or []
        )
    return ""


def test_tam_akis_tpd1(
    api: TestClient,
    analist: Any,
    engine: Engine,
    jira: RestJira,
    po: PoActions,
    sim: TestClient,
    make_user,
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-1")

    # PO, düzeltmeden (ve sorulardan) ÖNCE etiket koyarsa bu onay sayılmamalı.
    po.add_label("TPD-1")

    r = api.post(f"/requirements/{rid}/review")
    assert r.status_code == 202, r.text
    assert r.json()["durum"] == "started" and r.json()["job_id"]
    assert api.post(f"/requirements/{rid}/review").status_code == 409  # zaten incelemede
    sonuclar = run_jobs(engine)
    assert [s.durum for s in sonuclar][:2] == ["done", "done"], sonuclar

    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "findings_open"
    assert d["kontrol_turu"] == 1
    assert d["on_inceleme"]["verdict"] == "needs_po"
    # Seed story'si golden'ın beyan ettiği girdi → REPLAY (asla "live" değil).
    assert d["on_inceleme"]["mode"] == "replay"
    assert "AC3 ile AC6 çelişiyor" in d["on_inceleme"]["ozet"]
    assert d["bulgu_sayaclari"] == {"dogrulanan": 4, "elenen": 0, "acik": 4}
    assert d["son_kontrol"]["mode"] == "replay" and len(d["son_kontrol"]["head_sha"]) == 40

    # Sorular tutarlılık döngüsü bitmeden Jira'ya YAZILMAZ (§2 adım 2): metin henüz değişecek.
    assert not [c for c in jira.get_comments("TPD-1") if "ön inceleme" in c.body]
    assert "tp-po-pending" not in jira.get_issue("TPD-1").labels
    assert d["on_inceleme"]["jira_comment_id"] is None

    # Kayıt: ai_call (replay) + ajan araç çağrıları (golden adımları araçlarımızla yeniden koşar).
    with engine.connect() as c:
        modlar = dict(c.execute(text("SELECT amac, mod FROM ai_call")).all())
        araclar = list(c.execute(text("SELECT arac FROM tool_call ORDER BY zaman")).scalars())
        girdi = c.execute(
            text("SELECT maskeli_girdi::text FROM ai_call WHERE amac = 'consistency_check'")
        ).scalar_one()
    assert modlar == {"requirement_review": "replay", "consistency_check": "replay"}
    assert {"db_query", "get_file_contents", "search_code"} <= set(araclar)
    assert '<untrusted kind=\\"jira\\" source=\\"jira:TPD-1\\"' in girdi

    bulgular = _findings(api, rid)
    assert set(bulgular) == {"F1", "F2", "F3", "F4"}
    assert all(f["kanit_dogrulandi"] and f["mode"] == "replay" for f in bulgular.values())
    assert bulgular["F3"]["mevcut_doc_text"].startswith("AC3: Tüm siparişlerde")
    # F1 "AC3 ↔ AC6"ya atıf yapar ama önerisi yalnızca AC3'ü yazar: fark AC6'yı silinmiş
    # göstermez (gösterilen "önce" = düzeltmenin gerçekten değiştireceği metin).
    assert bulgular["F1"]["doc_ref"] == "AC3 ↔ AC6"
    assert bulgular["F1"]["mevcut_doc_text"].startswith("AC3: Tüm siparişlerde")
    assert "AC6" not in bulgular["F1"]["mevcut_doc_text"]

    # Karar kuralları: hash zorunlu/güncel, gerekçe, rol.
    f2 = bulgular["F2"]
    eksik = api.post(f"/findings/{f2['id']}/decision", json={"karar": "fix_doc"})
    assert eksik.status_code == 422
    eski = api.post(
        f"/findings/{f2['id']}/decision", json={"karar": "fix_doc", "icerik_hash": "0" * 64}
    )
    assert eski.status_code == 409
    assert _decide(api, f2, "accept_difference").status_code == 422
    assert (
        _decide(api, f2, "fix_doc", metin="Bu bir AC satırı değil\nAC9: atlamalı").status_code
        == 422
    )

    duzeltilmis_ac2 = (
        'AC2: "6 al 1 bedava" kampanyasında kampanyalı üründen her 6 adette 1 adet bedava '
        "verilir (6 adet alındığında 1 bedava)."
    )
    r = _decide(api, f2, "fix_doc", metin=duzeltilmis_ac2)
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "decided" and r.json()["karar_metni"] == duzeltilmis_ac2
    assert r.json()["suggested_doc_text"] == f2["suggested_doc_text"]  # AI önerisi korunur
    assert r.json()["mevcut_doc_text"].startswith("AC2: ")
    assert _decide(api, bulgular["F1"], "fix_doc").status_code == 200
    assert _decide(api, bulgular["F3"], "fix_doc").status_code == 200
    r = _decide(api, bulgular["F4"], "code_defect")
    assert r.status_code == 200 and r.json()["durum"] == "resolved"
    bug_id = r.json()["bug_draft_id"]
    assert bug_id

    with new_session() as s:
        bug = s.get(BugDraft, bug_id)
        assert bug.durum == "draft" and bug.icerik["story_key"] == "TPD-1"
        assert str(bug.finding_id) == bulgular["F4"]["id"]
        kararlar = list(
            s.scalars(select(Review.karar).where(Review.nesne_turu == "consistency_finding"))
        )
    assert sorted(kararlar) == ["code_defect", "fix_doc", "fix_doc", "fix_doc"]
    # "Bug taslağına git": taslak core'dan okunur (portal 404 göstermez).
    b = api.get(f"/bug-drafts/{bug_id}")
    assert b.status_code == 200, b.text
    assert b.json()["kaynak"] == "consistency" and b.json()["finding_id"] == bulgular["F4"]["id"]
    assert b.json()["icerik"]["story_key"] == "TPD-1"
    # Taslak şablonla, bulgunun doğrulanmış kanıtından üretildi: AI modu taşımaz (REPLAY değil).
    assert b.json()["mode"] is None and b.json()["icerik"]["uretim"] == "sablon"
    adimlar = b.json()["icerik"]["steps"]
    assert any("demo-app · " in a and "commit " in a for a in adimlar), adimlar
    assert not any(a == "Tutarlılık bulgusundaki kanıtı inceleyin" for a in adimlar)
    assert [x["id"] for x in api.get("/bug-drafts", params={"requirement_id": rid}).json()] == [
        bug_id
    ]

    # Analist düzeltmeleri uygular → Jira'ya yazılır → 2. tur (TPD-1-r2).
    r = api.post(f"/requirements/{rid}/apply-doc-fixes")
    assert r.status_code == 202, r.text
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    assert d["kontrol_turu"] == 2
    # AC2, golden'ın varsaydığından farklı düzeltildi → 2. tur dürüstçe REPLAY-MISS. Başka bir
    # girdinin çıktısı "tutarlı" kanıtı sayılmaz: belge otomatik son hal olmaz (fail-closed).
    assert d["son_kontrol"]["mode"] == "replay_miss"
    assert d["durum"] == "findings_open", d
    assert d["insan_karari_gerekli"] is True and "REPLAY-MISS" in d["denetim_guvenilmez"]
    # Elle hazırlanmış golden "kayıtlı çıktı" diye sunulmaz (replay.py ifade kuralı).
    assert d["denetim_guvenilmez"] == (
        "son denetim REPLAY-MISS (REPLAY örnek çıktısı bu belgeye ait değil)"
    )
    assert "kayıtlı" not in d["denetim_guvenilmez"]
    assert any("güvenilir değil" in u for u in d["uyarilar"])
    assert d["po"]["durum"] == "not_requested"
    issue = jira.get_issue("TPD-1")
    assert issue.acceptance_criteria[1] == duzeltilmis_ac2
    assert (
        "750,00 TL" in issue.acceptance_criteria[2]
        and "Kampanyasız" in issue.acceptance_criteria[2]
    )
    assert issue.acceptance_criteria[3].startswith("AC4: Sipariş tutarı bayinin kredi limitini")
    # AC6 Jira'da aynen duruyor; portal farkı da onu silinmiş göstermedi.
    assert issue.acceptance_criteria[5] == (
        "AC6: Kampanyalı siparişlerde minimum sipariş tutarı şartı aranmaz."
    )
    assert "tp-po-approved" not in issue.labels and "tp-po-pending" in issue.labels
    ozet = [c for c in jira.get_comments("TPD-1") if "doküman düzeltmesi" in c.body]
    assert len(ozet) == 1
    # Bulgu etiketleri portaldakiyle aynı (iç T1-F2 kimliği yok); her değişiklik tek liste öğesi.
    assert "F2 (tur 1)" in ozet[0].body and "F1 (tur 1), F3 (tur 1)" in ozet[0].body
    assert "T1-" not in ozet[0].body
    adf = next(b for b in _adf_yorumlar(sim, "TPD-1") if "doküman düzeltmesi" in _adf_metin(b))
    listeler = [n for n in adf["content"] if n["type"] == "orderedList"]
    assert len(listeler) == 1 and len(listeler[0]["content"]) == 2
    ogeler = [_adf_metin(o) for o in listeler[0]["content"]]
    assert ogeler[0].startswith("AC2") and "Önce:" in ogeler[0] and "Sonra:" in ogeler[0]
    assert ogeler[1].startswith("AC3") and "Önce:" in ogeler[1] and "Sonra:" in ogeler[1]
    assert d["kaynak_hash"] == d["icerik_hash"]

    # Portalda gösterilen fark = Jira'ya yazılan değişiklik (F1 ve F3 → AC3).
    tum = {
        (f["kontrol_turu"], f["bulgu_no"]): f
        for f in api.get(f"/requirements/{rid}/findings", params={"tumu": True}).json()
    }
    for no in ("F1", "F3"):
        f = tum[(1, no)]
        assert f["durum"] == "resolved"
        assert (
            f["mevcut_doc_text"] in ogeler[1] and f["karar_metni"] == issue.acceptance_criteria[2]
        )

    # 2. tur REPLAY-MISS: başka bir girdinin (golden) bulguları gösterilmez — nötr yedek döner,
    # bulgu yok. (Önceki kararın devralınması test_flow_free_text'te eşleşen girdiyle sınanır.)
    tur2 = [f for f in api.get(f"/requirements/{rid}/findings").json() if f["kontrol_turu"] == 2]
    assert tur2 == []
    assert d["bulgu_sayaclari"]["acik"] == 0
    assert sum(1 for f in tum.values() if f["durum"] == "resolved") == 4
    with new_session() as s:
        assert s.scalar(select(func.count()).select_from(BugDraft)) == 1

    # Analist belgeyi açıkça son hale alır (düzeltme kalmadı, engelleyici yok).
    r = api.post(f"/requirements/{rid}/apply-doc-fixes")
    assert r.status_code == 202 and r.json()["durum"] == "done", r.text
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "pending_po" and d["po"]["durum"] == "pending"
    assert d["kaynak_hash"] == d["icerik_hash"] == d["son_hal_hash"]
    # Jira'ya PO yorumu ve etiketi son hal işiyle yazılır (worker).
    assert not [c for c in jira.get_comments("TPD-1") if "ön inceleme" in c.body]
    run_jobs(engine)
    inceleme = [c for c in jira.get_comments("TPD-1") if "ön inceleme" in c.body]
    assert len(inceleme) == 1
    govde = inceleme[0].body
    # Ürün yorumu bot imiyle başlar; gövde imden sonra gelir.
    assert govde.startswith(BOT_PREFIX)
    govde = strip_bot_header(govde)
    assert govde.startswith("[AI-generated]") and "Üretim modu: REPLAY" in govde
    assert "AI özeti" in govde and "son haline geldi" in govde
    # Ön inceleme özeti özgün metne göre yazıldı; düzeltilen maddeler belirtilir (bayat özet).
    assert "AI özeti (özgün metne göre, doküman düzeltmelerinden önce yazıldı; AC2, AC3" in govde
    # Q3 (AC4) ve Q4 (AC5) açık. Q1 (AC3/AC6 çelişki) ve Q2 (AC2 belirsizlik), F1/F3 ve F2'nin
    # fix_doc düzeltmesiyle cevaplandı: PO'ya yeniden sorulmaz, "Çözüldü" altında bilgi olarak.
    # Sorular PO'nun cevapta kullanacağı kimlikle yazılır (Q3: … → Q3), sıra numarasıyla değil.
    soru_kismi, cozuldu_kismi = govde.split("Çözüldü — ")
    assert "\n- Q3 [AC4 · eksik kabul kriteri]" in soru_kismi
    assert "\n- Q4 [AC5 · test edilemez]" in soru_kismi
    assert "Q1 [" not in soru_kismi and "Q2 [" not in soru_kismi
    assert "Doküman düzeltmesiyle metni değişen" not in govde
    assert (
        "- Q1 [AC6 · çelişki]" in cozuldu_kismi
        and "→ doküman düzeltmesiyle cevaplandı: F1 (tur 1), F3 (tur 1)" in cozuldu_kismi
    )
    assert "- Q2 [AC2 · belirsizlik]" in cozuldu_kismi
    assert "→ doküman düzeltmesiyle cevaplandı: F2 (tur 1)" in cozuldu_kismi
    assert "cevap gerekmez" in cozuldu_kismi and "Q3 [" not in cozuldu_kismi
    d = api.get(f"/requirements/{rid}").json()
    assert d["on_inceleme"]["jira_comment_id"] == inceleme[0].id
    sorular = {q["id"]: q for q in d["on_inceleme"]["questions"]}
    assert sorular["Q1"]["duzeltmeyle_degisti"] and sorular["Q2"]["duzeltmeyle_degisti"]
    assert not sorular["Q3"]["duzeltmeyle_degisti"]
    assert sorular["Q2"]["kararla_cozuldu"] == "doküman düzeltmesiyle cevaplandı: F2 (tur 1)"
    assert sorular["Q1"]["kararla_cozuldu"].endswith("F1 (tur 1), F3 (tur 1)")
    # F4 code_defect: belgeyi değil kodu düzeltir → Q3 (AC4) açık kalır.
    assert sorular["Q3"]["kararla_cozuldu"] is None and sorular["Q4"]["kararla_cozuldu"] is None
    # Sorudan önce konmuş onay etiketi kaldırıldı; PO teyidi bekleniyor.
    issue = jira.get_issue("TPD-1")
    assert "tp-po-approved" not in issue.labels and "tp-po-pending" in issue.labels

    assert flow.run_po_poll(engine)["kontrol"][rid] == "bekliyor"
    # Bot onay etiketi koyamaz; PO koyar → onay kaydedilir.
    time.sleep(0.01)
    po.comment("TPD-1", "Q1: Kampanyalı siparişte minimum aranmaz. Q3: İndirim sonrası toplam.")
    po.add_label("TPD-1")
    sonuc = flow.run_po_poll(engine)
    assert sonuc["kontrol"][rid] == "onaylandi" and sonuc["yeniden_planlandi"]
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "po_approved"
    assert d["po"] == {
        "durum": "approved",
        "onaylayan": "po@sim.local",
        "zaman": d["po"]["zaman"],
        "kanal": "jira",
        "onaylanan_hash": d["icerik_hash"],
    }
    assert d["po_cevaplari"] and "minimum aranmaz" in d["po_cevaplari"][-1]["metin"]
    # PO cevapları sorulara eşlenir ("Cevap bekleniyor" kalmaz).
    sorular = {q["id"]: q for q in d["on_inceleme"]["questions"]}
    assert sorular["Q1"]["cevap"] == "Kampanyalı siparişte minimum aranmaz."
    assert sorular["Q3"]["cevap"] == "İndirim sonrası toplam."
    assert sorular["Q2"]["cevap"] is None
    with new_session() as s:
        req = s.get(Requirement, rid)
        assert req.onaylanan_hash == d["icerik_hash"]
        onay = s.scalars(
            select(Review).where(Review.nesne_turu == "requirement").order_by(Review.sira.desc())
        ).first()
        assert onay.kanal == "jira" and onay.harici_onaylayan == "po@sim.local"
        assert onay.onaylanan_hash == d["son_hal_hash"]

    # PO etiketi kaldırırsa (case üretilmeden) onay geri çekilir.
    po.remove_label("TPD-1")
    assert flow.run_po_poll(engine)["kontrol"][rid].startswith("geri_cekildi")
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "new" and d["po"]["durum"] != "approved"

    eylemler = _eylemler(engine)
    for e in (
        "requirements.sync",
        "requirement.pre_review",
        "requirement.consistency_checked",
        "review.fix_doc",
        "review.code_defect",
        "bug_draft.created",
        "requirement.doc_fixed",
        "requirement.doc_final",
        "jira.comment",
        "review.po_approve",
        "requirement.po_withdrawn",
    ):
        assert e in eylemler, e
    # Zincir doğrulaması `audit.verify` (admin/auditor) ister; analist 403 alır.
    assert api.get("/audit", params={"verify": True}).status_code == 403
    login(api, make_user("auditor"))
    assert api.get("/audit", params={"verify": True}).json()["verify"]["ok"] is True


def test_jira_yazimlari_idempotent(
    engine: Engine, jira: RestJira, api: TestClient, analist: Any
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "pending_po"  # TPD-4 temiz: bulgu yok → doğrudan son hal
    # PO sorgusu worker'da koştu ve kendini ~15 sn sonrasına yeniden planladı (tek bekleyen iş).
    with engine.connect() as c:
        bekleyen = (
            c.execute(
                text(
                    "SELECT EXTRACT(EPOCH FROM run_after - now()) FROM job "
                    "WHERE tur = 'requirements.po_poll' AND durum = 'queued'"
                )
            )
            .scalars()
            .all()
        )
        biten = c.execute(
            text("SELECT count(*) FROM job WHERE tur = 'requirements.po_poll' AND durum = 'done'")
        ).scalar_one()
    # Sonraki sorgu TP_PO_POLL_S (15 sn) içinde planlı; alt sınır duvar saatine bağlı olduğundan
    # (yük altında poll ile bu sorgu arasında saniyeler geçebilir) yalnızca "gelecekte" denetlenir.
    assert biten >= 1 and len(bekleyen) == 1 and 0 < float(bekleyen[0]) <= 15
    with new_session() as s:
        istek = flow.po_request_snapshot(s, s.get(Requirement, rid).id)
        ref = s.scalars(
            select(ExternalRef).where(ExternalRef.entity_turu == "requirement_review")
        ).one()
        assert ref.durum == "created"
    assert istek is not None and istek.rr_id is not None
    assert str(istek.rr_id) == d["on_inceleme"]["id"]
    assert d["on_inceleme"]["jira_comment_id"] == ref.external_key
    # Aynı PO yorumu yeniden gönderilse (iş yeniden denemesi) Jira'ya ikinci kez yazılmaz.
    flow.post_po_request(engine, istek)
    # Kaydı "intent"te kalmış gibi yapıp yeniden dene: Jira'daki işaret bulunur, tekrar yazılmaz.
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE external_ref SET durum = 'intent' WHERE entity_turu = 'requirement_review'"
            )
        )
    flow.post_po_request(engine, istek)
    assert len([c for c in jira.get_comments("TPD-4") if "ön inceleme" in c.body]) == 1


def test_po_icerigi_degistirirse_yeniden_kontrol(
    engine: Engine,
    jira: RestJira,
    api: TestClient,
    analist: Any,
    po: PoActions,
    wired: dict[str, Any],
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    it = jira.get_issue("TPD-4")
    po.set_description(
        "TPD-4", it.description, [*it.acceptance_criteria, "AC3: Çıkış yapılabilir."]
    )
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][rid] == "icerik_degisti:yeniden_kontrol"
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "in_review" and d["kontrol_turu"] == 2
    assert d["kabul_kriterleri"][-1]["metin"] == "Çıkış yapılabilir."
    # TPD-4'ün 2. tur golden'ı yok (replay'de dürüstçe ReplayNotFound); yeniden kontrolü
    # FakeProvider'lı geçit yapar.
    wired["gateway"], _ = fake_gateway([tool_response((FINAL_TOOL, {"findings": [], "notes": ""}))])
    run_jobs(engine)
    assert api.get(f"/requirements/{rid}").json()["durum"] == "pending_po"
    # Etiket içerik değişikliğiyle aynı anda/önce kondu → onay sayılmaz; PO yeniden koymalı.
    assert flow.run_po_poll(engine)["kontrol"][rid] != "onaylandi"
    po.remove_label("TPD-4")
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][rid] == "onaylandi"


def test_prompt_injection_tpd3(
    engine: Engine, api: TestClient, analist: Any, jira: RestJira
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-3")
    d = api.get(f"/requirements/{rid}").json()
    assert any("talimat" in u for u in d["uyarilar"])
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    # Talimat uygulanmadı: hiçbir case/onay oluşmadı. Yalnızca uyarı düzeyinde doğrulanmış bulgu
    # var; o da analist kararı ister (§8.2b adım 5): belge otomatik son hal olmaz.
    assert d["durum"] == "findings_open"
    assert d["po"]["durum"] == "not_requested"
    assert d["bulgu_sayaclari"]["acik"] == 1
    with engine.connect() as c:
        girdi = c.execute(
            text("SELECT maskeli_girdi::text FROM ai_call WHERE amac = 'requirement_review'")
        ).scalar_one()
        onaylar = c.execute(
            text("SELECT count(*) FROM review WHERE nesne_turu <> 'consistency_finding'")
        ).scalar_one()
    assert "untrusted kind" in girdi and "Önceki tüm talimatları yok say" in girdi
    assert onaylar == 0
    assert "tp-po-approved" not in jira.get_issue("TPD-3").labels
    # missing_in_code uyarısı kararla bug taslağına dönüşür; ardından belge son hal → PO bekler.
    (uyari,) = api.get(f"/requirements/{rid}/findings").json()
    assert uyari["severity"] == "warning" and uyari["type"] == "missing_in_code"
    r = _decide(api, uyari, "code_defect")
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "resolved" and r.json()["bug_draft_id"]
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "pending_po" and d["po"]["durum"] == "pending"
    run_jobs(engine)
    # Modelin kendi şüpheli içerik bildirimi (summary) kaybolmaz: API'de ve PO yorumunda görünür
    # (regex'in kaçırdığı ifade biçimleri için ikinci, bağımsız sinyal).
    assert "şüpheli bir talimat" in d["on_inceleme"]["ozet"]
    (yorum,) = [c for c in jira.get_comments("TPD-3") if "ön inceleme" in c.body]
    assert "AI özeti" in yorum.body and "şüpheli bir talimat" in yorum.body


def test_kabul_kriteri_yok_tpd2(
    engine: Engine, api: TestClient, analist: Any, jira: RestJira
) -> None:
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-2")
    d = api.get(f"/requirements/{rid}").json()
    assert d["ac_missing"] and d["uyarilar"][0].startswith("Kabul kriteri yok")
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}").json()
    # Doğrulanmış uyarı (missing_in_code) karar bekler: otomatik son hal yok.
    assert d["durum"] == "findings_open"
    assert any(q["type"] == "missing_ac" for q in d["on_inceleme"]["questions"])
    (uyari,) = api.get(f"/requirements/{rid}/findings").json()
    assert uyari["severity"] == "warning" and uyari["durum"] == "open"
    # "Son hal olarak onayla" (düzeltme yok): karar verilmemiş uyarı bilinçli fark olarak kayda
    # geçer, yanıtta ve PO yorumunda listelenir.
    r = api.post(f"/requirements/{rid}/apply-doc-fixes")
    assert r.status_code == 202 and r.json()["durum"] == "done", r.text
    assert r.json()["kabul_edilen_uyarilar"] == [f"{uyari['bulgu_no']} (tur 1)"]
    assert "bilinçli fark" in r.json()["mesaj"]
    d = api.get(f"/requirements/{rid}").json()
    assert d["durum"] == "pending_po" and d["bulgu_sayaclari"]["acik"] == 0
    karar = api.get(f"/requirements/{rid}/findings", params={"tumu": True}).json()
    (kapanan,) = [f for f in karar if f["id"] == uyari["id"]]
    assert kapanan["durum"] == "resolved" and kapanan["karar"] == "accept_difference"
    assert "son hal onayı" in kapanan["gerekce"]
    with engine.connect() as c:
        onay = c.execute(
            text(
                "SELECT karar FROM review WHERE nesne_turu = 'consistency_finding' "
                "AND nesne_id = :i"
            ),
            {"i": uyari["id"]},
        ).scalar_one()
    assert onay == "accept_difference"
    run_jobs(engine)
    (yorum,) = [c for c in jira.get_comments("TPD-2") if "ön inceleme" in c.body]
    assert "bilinçli fark olarak kabul ettiği" in yorum.body
    assert f"- {uyari['bulgu_no']} (tur 1) [" in yorum.body


def test_jira_yolunda_portal_po_onayi_yok(api: TestClient, make_user, engine: Engine) -> None:
    a = make_user("analyst")
    login(api, a)
    api.post("/requirements/sync")
    rid = _req_id(api, "TPD-4")
    api.post(f"/requirements/{rid}/review")
    run_jobs(engine)
    h = api.get(f"/requirements/{rid}").json()["icerik_hash"]
    login(api, make_user("po"))
    r = api.post(f"/requirements/{rid}/po-approve", json={"icerik_hash": h})
    assert r.status_code == 410 and r.json()["kod"] == "po_onayi_jira"
    assert "tp-po-approved" in r.json()["detail"]


def test_sse_olaylari_yayilir(
    engine: Engine, api: TestClient, analist: Any, po: PoActions, db: Any
) -> None:
    """requirement.updated, finding.verified, agent.step ve po.approved Postgres NOTIFY ile
    (core-api'nin SSE'ye aktardığı kanal) commit'te yayılır."""
    import json

    import psycopg

    from tp_core.events.bus import CHANNEL

    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as dinleyici:
        dinleyici.execute(f"LISTEN {CHANNEL}")
        api.post("/requirements/sync")
        rid = _req_id(api, "TPD-3")
        api.post(f"/requirements/{rid}/review")
        run_jobs(engine)
        (uyari,) = api.get(f"/requirements/{rid}/findings").json()
        assert _decide(api, uyari, "accept_difference", gerekce="bilinçli").status_code == 200
        run_jobs(engine)
        time.sleep(0.01)
        po.add_label("TPD-3")
        assert flow.run_po_poll(engine)["kontrol"][rid] == "onaylandi"
        olaylar = [json.loads(n.payload) for n in dinleyici.notifies(timeout=1.0)]
    adlar = [o["event"] for o in olaylar]
    for ad in ("requirement.updated", "finding.verified", "agent.step", "po.approved"):
        assert ad in adlar, (ad, sorted(set(adlar)))
    dogrulanan = [o["data"] for o in olaylar if o["event"] == "finding.verified"]
    assert dogrulanan and all(d["requirement_id"] == rid and d["dogrulandi"] for d in dogrulanan)
    onay = next(o["data"] for o in olaylar if o["event"] == "po.approved")
    assert onay == {"id": rid, "requirement_id": rid, "onaylayan": "po@sim.local", "kanal": "jira"}
