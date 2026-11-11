"""Case üretimi: sunucu tarafı PO kapısı, iş kuyruğu, geçit (REPLAY/FakeProvider), kayıt."""

from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.audit import content_hash, verify_chain
from tp_core.gateway.testing import text_response
from tp_core.models import AiCall, Requirement, Review, TestCase, case_id, session_scope

from .helpers import (
    TPD3_INJECTION,
    TPD4,
    case_icerik,
    latest_cases,
    login,
    onayla,
    rol_ol,
    run_jobs,
)


def _durum(rid: uuid.UUID) -> str:
    with session_scope() as s:
        return s.get(Requirement, rid).durum


def test_po_onayi_olmadan_uretim_409(api: TestClient, make_user, make_requirement) -> None:
    rid = make_requirement(po_onayli=False)
    login(api, make_user("tester"))
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 409
    assert "PO onaylı" in r.json()["detail"]
    assert _durum(rid) == "pending_po"


def test_yalnizca_testci_uretim_baslatir(api: TestClient, make_user, make_requirement) -> None:
    rid = make_requirement()
    for rol in ("engineer", "analyst", "po"):
        rol_ol(api, make_user(rol))
        assert api.post(f"/requirements/{rid}/generate-cases").status_code == 403, rol


def test_ac_missing_uretime_gitmez(api: TestClient, make_user, make_requirement) -> None:
    rid = make_requirement(acs=[], ac_missing=True)
    login(api, make_user("tester"))
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 422
    assert "ac_missing" in r.json()["detail"]
    assert _durum(rid) == "po_approved"


def test_po_onayindan_sonra_degisen_icerik_kapida_reddedilir(
    api: TestClient, make_user, make_requirement
) -> None:
    rid = make_requirement()
    with session_scope() as s:
        s.get(Requirement, rid).aciklama = "PO'nun görmediği yeni metin"
    login(api, make_user("tester"))
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 409
    assert _durum(rid) == "po_approved"


def test_replay_ile_uctan_uca_uretim(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    rid = make_requirement()
    login(api, make_user("tester"))
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202, r.text
    govde = r.json()
    assert govde["durum"] == "started" and govde["uretim_no"] == 1
    assert _durum(rid) == "generating"

    sonuc = run_jobs(engine)
    assert [s.durum for s in sonuc] == ["done"]
    assert _durum(rid) == "cases_ready"

    cases = latest_cases(api, rid)
    golden = json.loads(
        (replay_gateway.rules_dir / "replay/case_generation/golden/TPD-4.json").read_text()
    )["output"]["cases"]
    assert [c["icerik"] for c in cases] == golden
    with session_scope() as s:
        req = s.get(Requirement, rid)
        for i, c in enumerate(cases, start=1):
            assert c["id"] == str(case_id(req, i, 1))  # uuid5(jira_key + sıra + üretim)
            assert c["durum"] == "draft" and c["kanal"] == "portal" and c["ai_generated"]
            assert c["icerik_hash"] == content_hash(c["icerik"])
            # Girdi golden'ın input_match beyanıyla eşleşir → REPLAY (asla "live").
            assert c["mode"] == "replay"
            assert c["karar"] is None and c["onaylanan_hash"] is None
        ai = s.scalars(select(AiCall)).all()
        assert {a.mod for a in ai} == {"replay"} and {a.amac for a in ai} == {"case_generation"}
        assert s.scalar(select(Review.id).where(Review.nesne_turu == "test_case")) is None
        wf = s.execute(text("SELECT durum FROM workflow_instance")).scalars().all()
        assert wf == ["done"]
        girdi = json.dumps(ai[0].maskeli_girdi, ensure_ascii=False)
        assert '<untrusted kind=\\"jira\\" source=\\"jira:TPD-4\\"' in girdi
    with engine.connect() as c:
        assert verify_chain(c).ok


def test_replay_miss_duzgun_etiketlenir(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    """REPLAY-MISS (case_generation/on_miss.json `raise`): başka dokümanın case'leri taslak
    olmaz; iskalama ai_call'a `replay_miss` olarak yazılır, iş yeniden denenmeden biter ve
    gereksinim Türkçe nedenle `failed` olur (canlı gibi gösterilmez)."""
    rid = make_requirement(acs=[*TPD4["acs"], "AC3: Yeni madde"])
    login(api, make_user("tester"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "failed" and "REPLAY-MISS" in (is_.hata or "")
    assert latest_cases(api, rid) == []
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "failed"
        modlar = set(s.scalars(select(AiCall.mod)))
    assert modlar == {"replay_miss"}


def test_tpd3_enjeksiyonu_hicbir_durumu_degistirmez(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway
) -> None:
    # docs/DEMO-VERISI.md TPD-3 (golden input_match ile birebir: REPLAY çıktısı gelir).
    rid = make_requirement(
        jira_key="TPD-3",
        baslik="Ürün arama",
        aciklama=f"Bayi, katalogda ürün adına göre arama yapabilmelidir. {TPD3_INJECTION}",
        acs=[
            "AC1: Bayi katalogda ürün adının bir bölümünü yazdığında yalnızca eşleşen ürünler "
            "listelenir.",
            'AC2: Eşleşen ürün yoksa "Ürün bulunamadı" mesajı gösterilir.',
        ],
    )
    login(api, make_user("tester"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    cases = latest_cases(api, rid)
    assert cases and {c["durum"] for c in cases} == {"draft"}
    with session_scope() as s:
        assert s.scalar(select(Review.id).where(Review.nesne_turu == "test_case")) is None
        girdi = s.scalars(select(AiCall.maskeli_girdi)).first()
    metin = json.loads(json.dumps(girdi))[0]["content"]
    blok_bas = metin.index('<untrusted kind="jira" source="jira:TPD-3"')
    assert blok_bas < metin.index(TPD3_INJECTION) < metin.index("</untrusted")


def test_fake_provider_po_cevaplari_ayri_blok_ve_tekrar_eleme(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    a, b = case_icerik(), case_icerik(title="Hatalı parola mesajı", ref="AC2")
    provider = fake_gateway([text_response({"cases": [a, b, dict(a)]})])
    rid = make_requirement(po_cevaplari=[{"soru": "Kilit var mı?", "cevap": "Hayır"}])
    login(api, make_user("tester"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    sonuc = run_jobs(engine)
    assert sonuc[0].deger["tekrar"] == [3]
    cases = latest_cases(api, rid)
    assert [c["sira_no"] for c in cases] == [1, 2]
    assert {c["mode"] for c in cases} == {"live"}  # sahte sağlayıcı geçidin canlı yolundan
    istek = provider.requests[0].messages[0]["content"]
    assert 'source="jira:TPD-4:po"' in istek and "Kilit var mı?" in istek
    assert istek.index('source="jira:TPD-4"') < istek.index("Kilit var mı?")
    assert cases[0]["ai_sure_ms"] >= 0 and cases[0]["maliyet_usd"] >= 0


def test_yeniden_uretim_taslaklari_superseded_onaylilari_korur(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    a, b = case_icerik(), case_icerik(title="Hatalı parola mesajı", ref="AC2")
    c = case_icerik(title="Boş parola", ref="AC2", type="negative")
    fake_gateway([text_response({"cases": [a, b]}), text_response({"cases": [a, c]})])
    rid = make_requirement()
    testci = make_user("tester")
    login(api, testci)
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    ilk = latest_cases(api, rid)
    onayla(api, ilk[0], testci, make_user("analyst"))

    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202 and r.json()["uretim_no"] == 2
    sonuc = run_jobs(engine)
    assert sonuc[0].deger["tekrar"] == [1]  # onaylı içerik yeniden eklenmez
    durum = {(x["uretim_no"], x["icerik"]["title"]): x["durum"] for x in latest_cases(api, rid)}
    assert durum == {
        (1, a["title"]): "approved",
        (1, b["title"]): "superseded",
        (2, c["title"]): "draft",
    }


def test_basarisiz_uretim_gereksinimi_failed_yapar(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    fake_gateway([text_response("bozuk")] * 6)
    rid = make_requirement()
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    sonuc = run_jobs(engine)
    assert sonuc[-1].durum == "retry"
    # İlk deneme retry'a düşer; son denemede gereksinim failed olur (yeniden başlatılabilir).
    with engine.begin() as c:
        c.execute(text("UPDATE job SET run_after = now() WHERE durum = 'retry'"))
    run_jobs(engine)
    assert _durum(rid) == "failed"
    with session_scope() as s:
        assert s.scalar(select(TestCase.id)) is None


def test_is_kuyruktayken_icerik_degisirse_uretim_failed(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    provider = fake_gateway([text_response({"cases": [case_icerik()]})])
    rid = make_requirement()
    login(api, make_user("tester"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    with session_scope() as s:
        s.get(Requirement, rid).aciklama = "Kuyruktayken değişen metin"
    sonuc = run_jobs(engine)
    assert [x.durum for x in sonuc] == ["failed"]
    assert _durum(rid) == "failed"  # geçiş geri alınmadı (işlem dışı yazıldı)
    assert provider.requests == []  # PO'nun görmediği metin modele hiç gitmedi
    with session_scope() as s:
        assert s.scalar(select(TestCase.id)) is None


def test_ayni_ciktiyla_yeniden_uretim_taslaklari_silmez(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    """REPLAY'de yeniden üretim hep aynı çıktıyı verir: taslak sayısı korunmalı (sıfır değil)."""
    a, b = case_icerik(), case_icerik(title="Hatalı parola mesajı", ref="AC2")
    fake_gateway([text_response({"cases": [a, b]}), text_response({"cases": [a, b]})])
    rid = make_requirement()
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    assert [c["durum"] for c in latest_cases(api, rid)] == ["draft", "draft"]

    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202 and r.json()["uretim_no"] == 2
    (sonuc,) = run_jobs(engine)
    assert sonuc.deger["tekrar"] == [] and sonuc.deger["case_sayisi"] == 2
    assert sonuc.deger["superseded"] == 2
    durum = {(x["uretim_no"], x["icerik"]["title"]): x["durum"] for x in latest_cases(api, rid)}
    assert durum == {
        (1, a["title"]): "superseded",
        (1, b["title"]): "superseded",
        (2, a["title"]): "draft",
        (2, b["title"]): "draft",
    }
    assert _durum(rid) == "cases_ready"


def test_bilinmeyen_ac_ve_kapsam_deterministik_denetlenir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    """Model AC9'a atıf yapar ve AC2'yi kapsamaz: kayıt + uyarı; düz onay reddedilir."""
    fake_gateway(
        [text_response({"cases": [case_icerik(), case_icerik(title="Uydurma", ref="AC9")]})]
    )
    rid = make_requirement()
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    (sonuc,) = run_jobs(engine)
    assert sonuc.deger["bilinmeyen_ac"] == {"2": ["AC9"]}
    assert sonuc.deger["kapsanmayan_ac"] == ["AC2"]
    metrik = api.get(f"/requirements/{rid}/case-metrics").json()
    assert metrik["kapsanmayan_ac"] == ["AC2"]
    ok, uydurma = latest_cases(api, rid)
    assert uydurma["uyarilar"] and "AC9" in uydurma["uyarilar"][0]

    r = api.post(
        f"/cases/{uydurma['id']}/decision",
        json={"karar": "accept", "icerik_hash": uydurma["icerik_hash"]},
    )
    assert r.status_code == 422 and "AC9" in r.json()["detail"]
    # Düzeltilince (gerçek AC) onaylanabilir; kapsam da tamamlanır.
    duzeltilmis = {**uydurma["icerik"], "acceptance_criteria_refs": ["AC2"]}
    r = api.post(
        f"/cases/{uydurma['id']}/decision",
        json={"karar": "edit", "icerik_hash": uydurma["icerik_hash"], "icerik": duzeltilmis},
    )
    assert r.status_code == 200, r.text
    assert api.get(f"/requirements/{rid}/case-metrics").json()["kapsanmayan_ac"] == []
    assert ok["uyarilar"] == []


def test_son_denemede_is_disi_cokme_gereksinimi_generatingde_birakmaz(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    """claim → worker öldü (deneme=2=max) → release_orphans → generate-cases yine 202."""
    from tp_core.features.cases.jobs import on_worker_start
    from tp_core.workflow.jobs import release_orphans

    fake_gateway([text_response({"cases": [case_icerik()]})])
    rid = make_requirement()
    login(api, make_user("tester"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE job SET durum = 'running', kilitleyen = 'olu-host:1', deneme = 2, "
                "baslama = now() WHERE tur = 'cases.generate'"
            )
        )
        assert release_orphans(c, host="olu-host") == 1
        assert c.execute(text("SELECT durum FROM job")).scalar_one() == "failed"
    assert _durum(rid) == "generating"  # platform gereksinime dokunmaz

    # Worker açılış taraması takılı gereksinimi failed'a alır ...
    with engine.begin() as c:
        on_worker_start(c)
    assert _durum(rid) == "failed"
    # ... ve yeniden başlatma çalışır.
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202, r.text
    run_jobs(engine)
    assert _durum(rid) == "cases_ready"


def test_takili_generating_yeniden_baslatmada_kurtarilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    fake_gateway([text_response({"cases": [case_icerik()]})])
    rid = make_requirement()
    login(api, make_user("tester"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    # İş kuyruktayken yeniden başlatma reddedilir (iş sürüyor).
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 409
    with engine.begin() as c:
        c.execute(text("UPDATE job SET durum = 'failed', son_hata = 'zaman aşımı'"))
    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202, r.text
    assert r.json()["uretim_no"] == 1
    run_jobs(engine)
    assert _durum(rid) == "cases_ready"


def test_duzeltilip_onaylanan_ai_case_yeniden_uretimde_tekrar_sayilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    """Düzeltilen case'in AI özgün içeriği yeniden üretilince kopya taslak düşmez (TPD-4 C1)."""
    a, b = case_icerik(), case_icerik(title="Hatalı parola mesajı", ref="AC2")
    fake_gateway([text_response({"cases": [a, b]}), text_response({"cases": [a, b]})])
    rid = make_requirement()
    testci, analist = make_user("tester"), make_user("analyst")
    login(api, testci)
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)
    c1, c2 = latest_cases(api, rid)
    duzeltilmis = {**c1["icerik"], "expected_result": "Ürün kataloğu ve bayi adı görünür"}
    onayla(api, c1, testci, analist, icerik=duzeltilmis)
    onayla(api, c2, testci, analist)

    r = api.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 202 and r.json()["uretim_no"] == 2
    (sonuc,) = run_jobs(engine)
    # Aynı model çıktısı: düzeltilen C1'in özgünü de, düzeltilmeyen C2 de tekrar.
    assert sonuc.deger["tekrar"] == [1, 2] and sonuc.deger["case_sayisi"] == 0
    durum = {(x["uretim_no"], x["sira_no"]): x["durum"] for x in latest_cases(api, rid)}
    assert durum == {(1, 1): "approved", (1, 2): "approved"}


def test_case_metrics_baz_deger_ve_replay_suresi_uyarisi(
    api: TestClient, engine: Engine, make_user, make_requirement, replay_gateway, monkeypatch
) -> None:
    from tp_core.features.cases.service import AI_SURE_REPLAY_UYARISI, MANUEL_BAZ_YOK_UYARISI

    rid = make_requirement()
    login(api, make_user("tester"))
    api.post(f"/requirements/{rid}/generate-cases")
    run_jobs(engine)

    monkeypatch.delenv("TP_MANUAL_BASELINE_S", raising=False)
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m["manuel_baz_ms"] is None and m["ai_cagri_modlari"] == {"replay": 1}
    assert MANUEL_BAZ_YOK_UYARISI in m["uyarilar"] and AI_SURE_REPLAY_UYARISI in m["uyarilar"]
    assert "Demo-A kazanç gösterilemez" in MANUEL_BAZ_YOK_UYARISI

    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "1800")
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    # Varsayılan ölçüm değildir: manuel_baz_ms boş, değer yalnızca ikincil alanda.
    assert m["manuel_baz_ms"] is None and m["manuel_baz_kaynagi"] == "varsayilan"
    assert m["manuel_baz"]["varsayilan_ms"] == 1_800_000
    assert MANUEL_BAZ_YOK_UYARISI not in m["uyarilar"]
