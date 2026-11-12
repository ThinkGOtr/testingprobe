"""Yayın (§8.3): önizleme = gönderilen gövde, onay/hash kapısı, idempotency, kısmi başarı."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.cases.helpers import (
    READ,
    SimTransport,
    case_icerik,
    karar_ver,
    latest_cases,
    login,
    onayla,
    rol_ol,
    run_jobs,
)
from tp_core.features.publish import service as publish
from tp_core.gateway.testing import text_response
from tp_core.integrations.jira import JiraSettings, RestJira
from tp_core.integrations.jira_adf import adf_to_text
from tp_core.integrations.testmgmt import JiraTestManagement, get_test_management
from tp_core.models import AuditEvent, ExternalRef, Requirement, TestCase, session_scope
from tp_core.workflow.jobs import JobContext


@pytest.fixture
def yayin_testci(make_user):
    return make_user("tester")


@pytest.fixture
def yayin_analist(make_user):
    return make_user("analyst")


@pytest.fixture
def hazir(
    api: TestClient,
    engine: Engine,
    make_requirement,
    fake_gateway,
    yayin_testci,
    yayin_analist,
):
    """İki case'li TPD-4: ilki onaylı (Testçi kabulü + Analist son onayı), ikincisi taslak;
    Testçi (yayıncı) oturumu açık. Dönüş: (gereksinim, onaylayan analist, a, b)."""
    fake_gateway(
        [text_response({"cases": [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2")]})]
    )
    rid = make_requirement()
    login(api, yayin_testci)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    a, b = latest_cases(api, rid)
    onayla(api, a, yayin_testci, yayin_analist)
    return rid, yayin_analist, a, b


def _ctx(case_ids: list[str], kullanici: str = "testci") -> JobContext:
    return JobContext(
        uuid.uuid4(),
        publish.PUBLISH_JOB,
        {"case_ids": case_ids, "isteyen": {"kullanici_adi": kullanici, "kanal": "portal"}},
        1,
        3,
    )


def _issue(sim: TestClient, key: str) -> dict[str, Any]:
    return sim.get(f"/rest/api/3/issue/{key}", auth=READ).json()["fields"]


def _label_count(jira: RestJira, cid: str) -> int:
    return len(jira.search(f'project = "TPD" AND labels = "tp-{cid}"', max_results=10))


def test_onizleme_islemleri_ve_gonderilen_govdeyle_ayni(
    api: TestClient, engine: Engine, sim: TestClient, jira: RestJira, targets, hazir
) -> None:
    rid, analist, a, b = hazir
    on = api.get("/publish/preview", params={"requirement_id": str(rid)}).json()
    assert on["hedef"] == "jira" and on["proje"] == "TPD"
    assert on["jira_browse_url"].startswith("http")
    islem = {k["case_id"]: k["islem"] for k in on["kalemler"]}
    assert islem == {a["id"]: "create", b["id"]: "blocked_not_approved"}
    kalem = next(k for k in on["kalemler"] if k["case_id"] == a["id"])
    # FakeProvider geçidin canlı yolundan geçer: mod "live" (REPLAY olsa tp-mod-replay).
    assert kalem["labels"] == ["AI-generated", f"tp-{a['id']}", "tp-mod-live"]
    assert kalem["uretim_modu"] == "live"
    assert kalem["onaylayan"] == analist.kullanici_adi

    sonuc = publish.run_publish(_ctx([a["id"]]), engine)
    key = sonuc["sonuclar"][0]["external_key"]
    gonderilen = _issue(sim, key)
    beklenen = kalem["payload"]["jira_issue"]["fields"]
    assert gonderilen["summary"] == beklenen["summary"]
    assert gonderilen["labels"] == [*beklenen["labels"], kalem["payload"]["mod_etiketi"]]
    assert kalem["labels"] == gonderilen["labels"]
    yorumlar = [y.body for y in jira.get_comments(key)]
    assert any(kalem["payload"]["mod_yorumu"] in y for y in yorumlar)
    assert gonderilen["issuetype"]["name"] == beklenen["issuetype"]["name"]
    assert gonderilen["description"] == beklenen["description"]
    metin = adf_to_text(gonderilen["description"])
    assert f"onaylayan: {analist.kullanici_adi}" in metin and a["icerik_hash"] in metin

    on2 = api.get("/publish/preview", params={"requirement_id": str(rid)}).json()
    k2 = next(k for k in on2["kalemler"] if k["case_id"] == a["id"])
    assert k2["islem"] == "skip_existing" and k2["external_key"] == key


def test_onizleme_ve_yayin_testci_ister(api: TestClient, make_user, engine: Engine, hazir) -> None:
    """Önizleme `publish.preview` (admin, analyst, po, tester, engineer); yayın `case.publish`."""
    rid, _, a, _ = hazir
    for rol in ("engineer", "analyst", "po", "admin"):
        rol_ol(api, make_user(rol))
        r = api.get("/publish/preview", params={"requirement_id": str(rid)})
        assert r.status_code == 200, (rol, r.text)
        assert api.post("/publish", json={"case_ids": [a["id"]]}).status_code == 403, rol
    for rol in ("developer", "viewer", "auditor"):
        rol_ol(api, make_user(rol))
        r = api.get("/publish/preview", params={"requirement_id": str(rid)})
        assert r.status_code == 403 and r.json()["kod"] == "yetki_yok", rol
        assert api.post("/publish", json={"case_ids": [a["id"]]}).status_code == 403, rol
    with engine.connect() as c:
        izinler = c.execute(
            text("SELECT ozet->>'izin' FROM audit_event WHERE eylem = 'authz.denied'")
        ).scalars()
        assert set(izinler) == {"case.publish", "publish.preview"}


def test_yayin_yalnizca_son_onaydan_sonra(
    api: TestClient, engine: Engine, jira: RestJira, targets, hazir, yayin_analist
) -> None:
    """Testçi kabulü (ready) yayını açmaz; Analist son onayından sonra yayınlanır."""
    rid, _, _, b = hazir
    b_hazir = karar_ver(api, b, karar="accept").json()
    assert b_hazir["durum"] == "ready"
    on = api.get("/publish/preview", params={"requirement_id": str(rid)}).json()
    assert {k["case_id"]: k["islem"] for k in on["kalemler"]}[b["id"]] == "blocked_not_approved"
    sonuc = publish.run_publish(_ctx([b["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "failed" and "son onayı bekleniyor" in sonuc["hata"]
    assert _label_count(jira, b["id"]) == 0
    rol_ol(api, yayin_analist)
    assert karar_ver(api, b_hazir, karar="approve").json()["durum"] == "approved"
    sonuc = publish.run_publish(_ctx([b["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "created", sonuc


def _son_kayit_edit(case_id: str, user_id: uuid.UUID, *, eski_onay: bool = False) -> None:
    """Approved case'in son kaydı olarak `edit` ekler (append-only tabloya doğrudan; eski akış)."""
    from tp_core.models import Review
    from tp_core.workflow.service import content_hash_of

    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(case_id))
        s.add(
            Review(
                nesne_turu="test_case",
                nesne_id=tc.id,
                user_id=user_id,
                kanal="portal",
                karar="edit",
                onaylanan_hash=content_hash_of(tc),
                eski_onay=eski_onay,  # 0026 göçünün işareti (göç anındaki analist edit'i)
            )
        )


def test_eski_akista_analist_edit_onayi_yayinlanir(
    engine: Engine, jira: RestJira, targets, hazir, make_user
) -> None:
    """012 öncesi analistin `edit`'i (son kayıt) son onay sayılır; onaylayan o analisttir."""
    _, _, a, _ = hazir
    eski_analist = make_user("tester", ad="eski_analist")  # rolü sonradan değişmiş olabilir
    _son_kayit_edit(a["id"], eski_analist.id, eski_onay=True)
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(a["id"]))
        assert publish._engel(s, tc) is None
        assert publish.approver_of(s, tc) == "eski_analist"
    sonuc = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "created", sonuc
    assert sonuc["onaylayan"] == "eski_analist"


def test_isaretsiz_analist_edit_onay_sayilmaz(
    engine: Engine, jira: RestJira, targets, hazir, make_user
) -> None:
    """Analist rolündeki hesabın işaretsiz (`eski_onay=false`) `edit`'i onay değildir."""
    _, _, a, _ = hazir
    _son_kayit_edit(a["id"], make_user("analyst").id)
    sonuc = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "failed" and "Analist son onayı yok" in sonuc["hata"]


def test_testci_edit_son_kayitsa_yayin_son_onay_ister(
    engine: Engine, jira: RestJira, targets, hazir, yayin_testci
) -> None:
    """Testçinin `edit`'i onay değildir: son kayıt oysa yayın kapısı kapalıdır."""
    _, analist, a, _ = hazir
    _son_kayit_edit(a["id"], yayin_testci.id)
    with session_scope() as s:
        assert publish.approver_of(s, s.get(TestCase, uuid.UUID(a["id"]))) == (
            analist.kullanici_adi
        )
    sonuc = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "failed" and "Analist son onayı yok" in sonuc["hata"]
    assert _label_count(jira, a["id"]) == 0


def test_api_ile_yayin_kismi_sonuc_ve_gereksinim_done(
    api: TestClient, engine: Engine, sim: TestClient, jira: RestJira, targets, hazir, worker
) -> None:
    rid, _, a, b = hazir
    r = api.post("/publish", json={"case_ids": [a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["hedef"] == "jira"
    durum = {s["case_id"]: s for s in govde["sonuclar"]}
    assert durum[a["id"]]["durum"] == "created"
    assert durum[b["id"]]["durum"] == "failed" and "Onaylı değil" in durum[b["id"]]["hata"]
    key = durum[a["id"]]["external_key"]
    assert _issue(sim, key)["labels"] == ["AI-generated", f"tp-{a['id']}", "tp-mod-live"]
    assert _label_count(jira, b["id"]) == 0  # onaysız case Jira'ya hiç gitmedi

    cases = {c["id"]: c for c in latest_cases(api, rid)}
    assert cases[a["id"]]["durum"] == "published" and cases[a["id"]]["jira_test_key"] == key
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "cases_ready"  # karar bekleyen case var

    # İkinci case reddedilince tüm onaylılar yayınlanmış olur → gereksinim done.
    r = api.post(
        f"/cases/{b['id']}/decision",
        json={"karar": "reject", "icerik_hash": b["icerik_hash"], "ret_nedeni": "duplicate"},
    )
    assert r.status_code == 200
    r = api.post("/publish", json={"case_ids": [a["id"]]})
    assert r.json()["sonuclar"][0]["durum"] == "exists"
    assert r.json()["tamamlanan_gereksinimler"] == [str(rid)]
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "done"
    assert _label_count(jira, a["id"]) == 1  # ikinci yayın yeni issue açmadı

    # Story yorumu: yayın özeti + denetim zincirinin son hash'i (dış sabitleme).
    yorumlar = jira.get_comments("TPD-4")
    sabit = [y for y in yorumlar if "Denetim zinciri son hash" in y.body]
    assert sabit and key in sabit[0].body
    with session_scope() as s:
        ev = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "publish.anchored")).one()
        assert ev.ozet["zincir_hash"] in sabit[0].body


def test_onaydan_sonra_degisen_icerik_yayinlanmaz(
    engine: Engine, jira: RestJira, targets, hazir
) -> None:
    _, _, a, _ = hazir
    # ORM korumasını atlayan ham yazım (saldırgan/hatalı kod): onaylanan hash artık tutmaz.
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE test_case SET icerik = jsonb_set(icerik, '{title}', '\"Değişti\"'), "
                "icerik_hash = 'baska' WHERE id = :id"
            ),
            {"id": a["id"]},
        )
    sonuc = publish.run_publish(_ctx([a["id"]]), engine)
    assert sonuc["sonuclar"][0]["durum"] == "failed"
    assert "onaydan sonra değişmiş" in sonuc["sonuclar"][0]["hata"]
    assert _label_count(jira, a["id"]) == 0
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(a["id"])).durum == "approved"
        assert s.scalar(select(ExternalRef.id)) is None


def _intent_ve_dis_kayit(targets, a: dict[str, Any]) -> Any:
    """Önceki deneme `intent` yazıp Jira'da issue'yu oluşturdu ama `created` yazamadan çöktü."""
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(a["id"]))
        mapping = publish.case_mapping(s, tc)
        s.add(
            ExternalRef(
                entity_turu="test_case",
                entity_id=tc.id,
                sistem="jira",
                idempotency_key=publish.idempotency_key("jira", tc),
                durum="intent",
            )
        )
    return targets.tm.publish_case(mapping, "TPD-4")


def test_intent_sonrasi_cokme_yeniden_denemede_mukerrer_acmaz(
    engine: Engine, jira: RestJira, targets, hazir
) -> None:
    _, _, a, _ = hazir
    ilk = _intent_ve_dis_kayit(targets, a)
    # Taze intent'in sahibi (bu case'i içeren başka bir yayın işi) hâlâ çalışıyor: beklenir.
    with engine.begin() as c:
        sahip = c.execute(
            text(
                "INSERT INTO job (tur, yuk, durum, kilitleyen, deneme, baslama) VALUES "
                "(:t, CAST(:y AS jsonb), 'running', 'baska-host:1', 1, now()) RETURNING id"
            ),
            {"t": publish.PUBLISH_JOB, "y": json.dumps({"case_ids": [a["id"]]})},
        ).scalar_one()
    taze = publish.run_publish(_ctx([a["id"]]), engine)
    assert taze["sonuclar"][0]["durum"] == "failed" and "sürüyor" in taze["sonuclar"][0]["hata"]
    # Sahip iş öldü (release_orphans/reap_stale bıraktı): 120 sn beklemeden devam edilir.
    with engine.begin() as c:
        c.execute(text("UPDATE job SET durum = 'failed' WHERE id = :j"), {"j": sahip})
    sonuc = publish.run_publish(_ctx([a["id"]]), engine)
    assert sonuc["sonuclar"][0]["durum"] == "created"
    assert sonuc["sonuclar"][0]["external_key"] == ilk.external_key
    assert _label_count(jira, a["id"]) == 1
    with session_scope() as s:
        ref = s.scalars(select(ExternalRef)).one()
        assert ref.durum == "created" and ref.external_key == ilk.external_key


def test_worker_cokmesi_sonrasi_otomatik_yeniden_deneme_tamamlar(
    api: TestClient, engine: Engine, jira: RestJira, targets, hazir, yayin_testci
) -> None:
    """claim → issue oluşturuldu → çöküş → release_orphans → yeniden deneme: created, tek issue."""
    from tp_core.workflow.jobs import release_orphans

    rid, analist, a, b = hazir
    r = api.post(
        f"/cases/{b['id']}/decision",
        json={"karar": "reject", "icerik_hash": b["icerik_hash"], "ret_nedeni": "duplicate"},
    )
    assert r.status_code == 200, r.text
    with session_scope() as s, pytest.raises(publish.ApprovalNotAllowed):  # yayın Testçinindir
        publish.request_publish(s, [a["id"]], analist)
    with session_scope() as s:
        job_id = publish.request_publish(s, [a["id"]], yayin_testci)
    with engine.begin() as c:  # worker işi aldı (claim) ...
        c.execute(
            text(
                "UPDATE job SET durum = 'running', kilitleyen = 'olu-host:1', deneme = 1, "
                "baslama = now() WHERE id = :j"
            ),
            {"j": job_id},
        )
    ilk = _intent_ve_dis_kayit(targets, a)  # ... Jira'ya yazdı ve çöktü.
    with engine.begin() as c:
        assert release_orphans(c, host="olu-host") == 1
    sonuc = run_jobs(engine)
    assert [x.durum for x in sonuc] == ["done"]
    durum = sonuc[0].deger["sonuclar"][0]
    assert durum["durum"] == "created" and durum["external_key"] == ilk.external_key
    assert _label_count(jira, a["id"]) == 1
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(a["id"])).durum == "published"
        assert s.get(Requirement, rid).durum == "done"


def test_kismi_hata_sonra_yeniden_deneme(
    api: TestClient,
    engine: Engine,
    sim: TestClient,
    jira: RestJira,
    targets,
    hazir,
    yayin_testci,
    yayin_analist,
) -> None:
    _, _, a, b = hazir
    onayla(api, b, yayin_testci, yayin_analist)
    # İlk Test issue oluşturma isteği 500 alır (POST yeniden gönderilmez → o case başarısız).
    sim.post(
        "/sim/faults",
        json={"path_prefix": "/rest/api/3/issue", "status": 500, "count": 1, "method": "POST"},
    )
    sonuc = publish.run_publish(_ctx([a["id"], b["id"]]), engine)
    durumlar = [s["durum"] for s in sonuc["sonuclar"]]
    assert durumlar == ["failed", "created"]
    with session_scope() as s:
        ref = s.scalars(
            select(ExternalRef).where(ExternalRef.entity_id == uuid.UUID(a["id"]))
        ).one()
        assert ref.durum == "failed" and ref.hata
    sonuc = publish.run_publish(_ctx([a["id"], b["id"]]), engine)
    assert [s["durum"] for s in sonuc["sonuclar"]] == ["created", "exists"]
    assert _label_count(jira, a["id"]) == 1 and _label_count(jira, b["id"]) == 1
    with session_scope() as s:
        assert (
            s.get(Requirement, s.get(TestCase, uuid.UUID(a["id"])).requirement_id).durum == "done"
        )


def test_serbest_metin_gereksinim_yayini_engellenir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, targets
) -> None:
    fake_gateway([text_response({"cases": [case_icerik()]})])
    rid = make_requirement(jira_key=None, baslik="Serbest", aciklama="Serbest metin gereksinim")
    testci = make_user("tester")
    login(api, testci)
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    (c,) = latest_cases(api, rid)
    onayla(api, c, testci, make_user("analyst"))
    on = api.get("/publish/preview", params={"requirement_id": str(rid)}).json()
    assert on["kalemler"][0]["islem"] == "blocked_no_story" and on["uyarilar"]
    sonuc = publish.run_publish(_ctx([c["id"]]), engine)
    assert sonuc["sonuclar"][0]["durum"] == "failed"
    assert "story" in sonuc["sonuclar"][0]["hata"]


@pytest.fixture
def xray_ortami(monkeypatch: pytest.MonkeyPatch):
    from tp_core.integrations.jira import get_jira_settings

    monkeypatch.setenv("TP_TEST_MGMT", "xray")
    get_jira_settings.cache_clear()
    yield
    monkeypatch.delenv("TP_TEST_MGMT")
    get_jira_settings.cache_clear()


def test_xray_hedefi_onizleme_ve_yayin(
    api: TestClient,
    engine: Engine,
    jira: RestJira,
    sim_transport: SimTransport,
    xray_ortami,
    hazir,
) -> None:
    import httpx

    rid, _, a, _ = hazir
    on = api.get("/publish/preview", params={"requirement_id": str(rid)}).json()
    assert on["hedef"] == "xray"
    kalem = next(k for k in on["kalemler"] if k["case_id"] == a["id"])
    imp = kalem["payload"]["xray_import"]
    assert imp[0]["testtype"] == "Manual"
    assert imp[0]["fields"]["labels"] == ["AI-generated", f"tp-{a['id']}"]
    assert [s["action"] for s in imp[0]["steps"]] == [s["action"] for s in a["icerik"]["steps"]]

    tm = get_test_management(
        JiraSettings(TP_TEST_MGMT="xray"), jira=jira, http=httpx.Client(transport=sim_transport)
    )
    publish.set_targets_factory(lambda: publish.Targets(tm, jira))
    try:
        sonuc = publish.run_publish(_ctx([a["id"]]), engine)
    finally:
        publish.set_targets_factory(None)
    assert sonuc["hedef"] == "xray" and sonuc["sonuclar"][0]["durum"] == "created"
    gonderilen = [
        json.loads(g)
        for m, p, g in sim_transport.istekler
        if m == "POST" and p.endswith("/import/test/bulk")
    ]
    assert gonderilen == [imp]  # önizleme = Xray'e giden gövde (birebir)
    with session_scope() as s:
        assert s.scalars(select(ExternalRef.sistem)).one() == "xray"


def test_jira_test_management_ornegi(jira: RestJira) -> None:
    assert JiraTestManagement(jira, "TPD").name == "jira"


def test_yayin_sse_olaylari(db, engine: Engine, targets, hazir) -> None:
    """Portal 202 bekleme modundan çıkmak için publish.completed / publish.failed dinler."""
    import psycopg

    from tp_core.events.bus import CHANNEL

    rid, _, a, b = hazir
    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as dinleyici:
        dinleyici.execute(f"LISTEN {CHANNEL}")
        publish.run_publish(_ctx([a["id"], b["id"]]), engine)
        olaylar = [json.loads(n.payload) for n in dinleyici.notifies(timeout=1.0)]
    tamam = [o["data"] for o in olaylar if o["event"] == "publish.completed"]
    assert len(tamam) == 1 and tamam[0]["requirement_id"] == str(rid)
    assert {x["case_id"] for x in tamam[0]["sonuclar"]} == {a["id"], b["id"]}


# ------------------------------------------- story değişti → PO onayı sıfırlandı (I)


def _story_degisti(rid: Any) -> str:
    """Senkronun yaptığı gibi: Jira içeriği değişti → `apply_content_change` (gerçek akış)."""
    from tp_core.features.requirements import flow

    with session_scope() as s:
        req = s.get(Requirement, rid, with_for_update=True)
        sonuc = flow.apply_content_change(
            s,
            req,
            req.baslik,
            req.aciklama,
            ["AC1: tamamen farklı kural", *req.kabul_kriterleri[1:]],
            "system",
            sebep="Jira içeriği değişti",
        )
    return sonuc


def test_story_degisince_onayli_case_yayinlanmaz_portal_onizleme_ve_karar(
    api: TestClient, engine: Engine, jira: RestJira, targets, hazir, worker
) -> None:
    rid, _, a, b = hazir
    assert _story_degisti(rid) == "sifirlandi"
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert req.durum == "new" and req.onaylanan_hash is None

    on = api.get("/publish/preview", params={"requirement_id": str(rid)}).json()
    islem = {k["case_id"]: k["islem"] for k in on["kalemler"]}
    assert islem[a["id"]] == "blocked_requirement_changed"
    assert any("PO onaylı" in u for u in on["uyarilar"])

    r = api.post("/publish", json={"case_ids": [a["id"]]})
    assert r.status_code == 200, r.text
    (sonuc,) = r.json()["sonuclar"]
    assert sonuc["durum"] == "failed" and "PO onaylı" in sonuc["hata"]
    assert _label_count(jira, a["id"]) == 0  # Jira'ya hiç gitmedi

    # Eski metnin taslağı da kabul edilemez (cases.decide gereksinimi denetler).
    r = api.post(
        f"/cases/{b['id']}/decision", json={"karar": "accept", "icerik_hash": b["icerik_hash"]}
    )
    assert r.status_code == 409 and "PO onaylı" in r.json()["detail"]
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(b["id"])).durum == "draft"


def test_story_degisince_mcp_yayini_da_reddedilir(
    api: TestClient, engine: Engine, make_user, jira: RestJira, targets, hazir, worker, yayin_testci
) -> None:
    from tests.unit.mcp_server.test_mcp import _cagir, _token

    rid, _, a, _ = hazir
    _story_degisti(rid)
    sonuc = _cagir(
        api, _token(yayin_testci, "publish"), "publish_test_cases", {"case_ids": [a["id"]]}
    )
    (kalem,) = sonuc.structured_content["sonuclar"]
    assert kalem["durum"] == "failed" and "PO onaylı" in kalem["hata"]
    assert _label_count(jira, a["id"]) == 0


def test_yeni_po_onayiyla_uretimde_eski_caseler_superseded(
    api: TestClient, engine: Engine, make_user, fake_gateway, hazir
) -> None:
    """Reset → (yeni metin) PO onayı → üretim: eski onaylı case yeni onaya taşınmaz."""
    from tp_core.workflow.service import SYSTEM, content_hash_of, record_approval, transition

    rid, _, a, b = hazir
    _story_degisti(rid)
    po = make_user("po")
    with session_scope() as s:
        req = s.get(Requirement, rid)
        for once, sonra in (("new", "in_review"), ("in_review", "doc_final")):
            transition(s, req, sonra, SYSTEM, once)
        transition(s, req, "pending_po", SYSTEM, "doc_final")
        record_approval(s, req, po, "po_approve", beklenen_hash=content_hash_of(req))
        transition(s, req, "po_approved", po, "pending_po")
    fake_gateway([text_response({"cases": [case_icerik(title="Yeni kurala göre giriş")]})])
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    durum = {c["id"]: c["durum"] for c in latest_cases(api, rid)}
    assert durum[a["id"]] == "superseded" and durum[b["id"]] == "superseded"
    assert sorted(durum.values()) == ["draft", "superseded", "superseded"]
    with session_scope() as s:
        ev = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.invalidated")).one()
        assert set(map(str, ev.ozet["case_ids"])) == {a["id"], b["id"]}


# ------------------------------- yeniden yayın: Jira'daki eski içerik "created" sayılmaz


def test_kismi_hata_duzeltme_sonrasi_eski_issue_yayinlandi_sayilmaz(
    api: TestClient,
    engine: Engine,
    sim: TestClient,
    jira: RestJira,
    targets,
    hazir,
    yayin_testci,
    yayin_analist,
) -> None:
    rid, _, a, _ = hazir
    # Issue oluşur, story bağlantısı (iki tür de) 400 alır → kısmi başarı (anahtar kayıtlı).
    sim.post(
        "/sim/faults",
        json={"path_prefix": "/rest/api/3/issueLink", "status": 400, "count": 2, "method": "POST"},
    )
    ilk = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
    assert ilk["durum"] == "failed" and ilk["external_key"]
    key = ilk["external_key"]
    eski_baslik = jira.get_issue(key).summary

    # Testçi taslağa alır ve başlığı düzeltir; Analist yeni içeriği onaylar (yeni hash).
    r = api.post(
        f"/cases/{a['id']}/decision", json={"karar": "reopen", "icerik_hash": a["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    yeni = {**a["icerik"], "title": "TAMAMEN YENI BASLIK"}
    out = onayla(api, a, yayin_testci, yayin_analist, icerik=yeni)
    assert out["durum"] == "approved"

    sonuc = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "failed" and sonuc["external_key"] == key
    assert "farklı (eski) içerikle" in sonuc["hata"]
    assert jira.get_issue(key).summary == eski_baslik  # Jira'daki eski içerik
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(a["id"])).durum == "approved"  # yayınlandı sayılmadı
        assert s.get(Requirement, rid).durum == "cases_ready"

    # İnsan Jira'da eski issue'nun tp-<uuid> etiketini kaldırınca onaylı içerik yeni issue'ya gider.
    jira.remove_labels(key, [f"tp-{a['id']}"])
    sonuc = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "created" and sonuc["external_key"] != key
    assert jira.get_issue(sonuc["external_key"]).summary == "TAMAMEN YENI BASLIK"


# ----------------------------------------------------- üretim modu Jira'da görünür


def test_replay_caseleri_jirada_replay_olarak_etiketlenir(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway, jira, targets
) -> None:
    rid = make_requirement()
    testci = make_user("tester")
    login(api, testci)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    cases = latest_cases(api, rid)
    assert {c["mode"] for c in cases} <= {"replay", "replay_miss"}
    c = cases[0]
    onayla(api, c, testci, make_user("analyst"))
    on = api.get("/publish/preview", params={"requirement_id": str(rid)}).json()
    kalem = next(k for k in on["kalemler"] if k["case_id"] == c["id"])
    mod = c["mode"]
    etiket = "tp-mod-" + mod.replace("_", "-")
    assert kalem["uretim_modu"] == mod and etiket in kalem["labels"]

    sonuc = publish.run_publish(_ctx([c["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "created" and sonuc["mode"] == mod
    key = sonuc["external_key"]
    assert etiket in jira.get_issue(key).labels
    beklenen = "REPLAY-MISS" if mod == "replay_miss" else "REPLAY"
    assert any(f"Üretim modu: {beklenen}" in y.body for y in jira.get_comments(key))
    # Story yorumu da modu söyler (canlı AI çıktısı gibi görünmez).
    ozet = [y.body for y in jira.get_comments("TPD-4") if "Denetim zinciri son hash" in y.body]
    assert ozet and f"Üretim modu: {beklenen}" in ozet[-1]
    # Yeniden yayın aynı mod yorumunu ikinci kez yazmaz.
    publish.run_publish(_ctx([c["id"]]), engine)
    assert sum("Üretim modu:" in y.body for y in jira.get_comments(key)) == 1
