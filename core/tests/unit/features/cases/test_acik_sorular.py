"""Açık soru döngüsü (specs/011 K16, D6): PO'ya gönderim → PO yanıtı → case düzeltme.

Jira yalnız süreç içi jira-sim'dir (gerçek Jira'ya yazılmaz); PO yanıtı sim'e PO hesabıyla yorum
olarak yazılır.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.features.cases import acik_sorular, service
from tp_core.features.requirements import services
from tp_core.gateway.testing import text_response
from tp_core.integrations.jira import RestJira
from tp_core.integrations.jira_adf import text_to_adf
from tp_core.models import AuditEvent, ExternalRef, Requirement, new_session, session_scope
from tp_core.models.acik_soru import AcikSoru

from .helpers import case_icerik, latest_cases, login, run_jobs, uretim_cikti

PO_AUTH = ("po@sim.local", "po-test-parola")
WRITER = ("writer@sim.local", "x")
READ = ("reader@sim.local", "x")
SORU = "Kaç hatalı denemede hesap kilitlenir?"
VARSAYIM = "Parola büyük/küçük harf duyarlıdır"
OZET = {
    "open_questions": [{"id": "Q1", "question": SORU, "owner": "PO"}],
    "assumptions": [{"id": "A1", "statement": VARSAYIM, "owner": ""}],
    "coverage_items": [
        {"id": "UC-MF", "ac_ref": "AC1", "definition": "Ana akış", "valid": True},
        {"id": "EP-I1", "ac_ref": "AC2", "definition": "Hatalı parola", "valid": False},
        {"id": "EP-I2", "ac_ref": "AC2", "definition": "Kilitli hesap", "valid": False},
    ],
    "negative_coverage": [
        {"item": "EP-I1", "decision": "tested", "rationale": "AC2"},
        {"item": "EP-I2", "decision": "tested", "rationale": "Kilit kuralı"},
    ],
}


def _cases() -> list[dict[str, Any]]:
    neg = {"type": "negative", "technique": ["EP"]}
    return [
        case_icerik(),
        case_icerik(
            title="Hatalı parola mesajı",
            ref="AC2",
            covers=["EP-I1"],
            readiness="assumption_dependent",
            assumption_refs=["A1"],
            **neg,
        ),
        case_icerik(
            title="Kilitli hesapla giriş",
            ref="AC2",
            covers=["EP-I2"],
            readiness="blocked",
            open_question_refs=["Q1"],
            expected_result="",
            **neg,
        ),
    ]


@pytest.fixture
def ortam(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, jira: RestJira
) -> Iterator[uuid.UUID]:
    fake_gateway([text_response(uretim_cikti(_cases(), **OZET))])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    with services.override(jira=lambda: jira, po_accounts=lambda: {"po@sim.local"}):
        yield rid


def _yorumlar(sim: TestClient, key: str = "TPD-4") -> list[str]:
    from tp_core.integrations.jira_adf import adf_to_text

    r = sim.get(f"/rest/api/3/issue/{key}/comment", auth=READ)
    return [adf_to_text(c["body"]) for c in r.json()["comments"]]


def _po_yorumu(sim: TestClient, metin: str, auth: tuple[str, str] = PO_AUTH) -> None:
    r = sim.post("/rest/api/3/issue/TPD-4/comment", json={"body": text_to_adf(metin)}, auth=auth)
    assert r.status_code == 201, r.text


def test_liste_gonderilmedi_ve_bekleyen_caseler(api: TestClient, ortam: uuid.UUID) -> None:
    r = api.get(f"/requirements/{ortam}/open-questions")
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["jira_key"] == "TPD-4" and g["gonderilebilir"] is True
    assert g["sayim"] == {"gonderilmedi": 2, "gonderildi": 0, "yanitlandi": 0}
    soru, varsayim = g["sorular"]
    assert (soru["tur"], soru["kaynak_id"], soru["metin"], soru["sahip"]) == (
        "soru",
        "Q1",
        SORU,
        "PO",
    )
    assert soru["etiket"] is None and soru["durum"] == "gonderilmedi" and soru["yanit"] is None
    assert [c["title"] for c in soru["bekleyen_caseler"]] == ["Kilitli hesapla giriş"]
    assert soru["bekleyen_caseler"][0]["readiness"] == "blocked"
    assert varsayim["tur"] == "varsayim" and varsayim["metin"] == VARSAYIM
    assert [c["title"] for c in varsayim["bekleyen_caseler"]] == ["Hatalı parola mesajı"]


def test_gonderim_tek_yorum_idempotent_ve_yetki(
    api: TestClient, ortam: uuid.UUID, sim: TestClient, make_user
) -> None:
    once = len(_yorumlar(sim))
    r = api.post(f"/requirements/{ortam}/open-questions/send")
    assert r.status_code == 200, r.text
    g = r.json()
    soru, varsayim = g["sorular"]
    assert (soru["etiket"], soru["durum"]) == ("CQ1", "gonderildi")
    assert soru["gonderim"]["jira_comment_id"] and soru["gonderim"]["gonderen"].startswith(
        "analyst"
    )
    assert varsayim["durum"] == "gonderilmedi"  # varsayımlar yalnız istenirse
    yorumlar = _yorumlar(sim)
    assert len(yorumlar) == once + 1
    govde = yorumlar[-1]
    assert govde.startswith("🤖 AI Testing Probe:")
    assert f"- CQ1 {SORU} — bekleyen case'ler: #3 Kilitli hesapla giriş" in govde
    assert "'CQ1: …'" in govde and "Kayıt: tp-" in govde and VARSAYIM not in govde

    # Aynı soru ikinci kez gönderilmez (409; Jira'ya yeni yorum yazılmaz).
    r = api.post(f"/requirements/{ortam}/open-questions/send")
    assert r.status_code == 409 and "Gönderilecek açık soru yok" in r.json()["detail"]
    assert len(_yorumlar(sim)) == once + 1

    # Varsayımlar istenince yalnız gönderilmemiş olan (CA1) gider.
    r = api.post(f"/requirements/{ortam}/open-questions/send", json={"varsayimlar": True})
    assert r.status_code == 200, r.text
    assert r.json()["sorular"][1]["etiket"] == "CA1"
    son = _yorumlar(sim)[-1]
    assert "- CA1 " + VARSAYIM in son and "CQ1" not in son.split("Yanıtlarınızı")[0]
    with session_scope() as s:
        assert s.scalars(select(ExternalRef.durum).where(ExternalRef.entity_id == ortam)).all()
        assert sorted(s.scalars(select(AcikSoru.etiket))) == ["CA1", "CQ1"]
        eylemler = s.scalars(
            select(AuditEvent.eylem).where(AuditEvent.eylem == "acik_soru.gonderildi")
        ).all()
        assert len(eylemler) == 2

    # Yalnız analist gönderir; diğer roller listeyi okuyabilir.
    login(api, make_user("tester"))
    assert api.post(f"/requirements/{ortam}/open-questions/send").status_code == 403
    assert api.post(f"/requirements/{ortam}/open-questions/refresh").status_code == 403
    assert api.get(f"/requirements/{ortam}/open-questions").status_code == 200


def test_po_yaniti_soruya_baglanir_ve_case_duzeltilir(
    api: TestClient, ortam: uuid.UUID, sim: TestClient
) -> None:
    assert api.post(f"/requirements/{ortam}/open-questions/send").status_code == 200
    # PO dışı hesabın "yanıtı" sayılmaz; PO yanıtı kimlikle bağlanır.
    _po_yorumu(sim, "CQ1: 3 denemede", auth=WRITER)
    _po_yorumu(sim, "Teşekkürler.\nCQ1: 5 hatalı denemede hesap 15 dakika kilitlenir.\nQ1: eski")
    r = api.post(f"/requirements/{ortam}/open-questions/refresh")
    assert r.status_code == 200, r.text
    soru = r.json()["sorular"][0]
    assert soru["durum"] == "yanitlandi"
    assert soru["yanit"]["metin"] == "5 hatalı denemede hesap 15 dakika kilitlenir."
    assert soru["yanit"]["yazar"] and soru["yanit"]["zaman"]
    assert soru["oneri"]["eylem"] == "duzelt_veya_yeniden_uret"
    assert r.json()["sayim"]["yanitlandi"] == 1

    _, varsayim, engelli = latest_cases(api, ortam)
    assert engelli["acik_sorular"] == OZET["open_questions"]  # mevcut alan değişmez
    q = engelli["po_sorulari"]["Q1"]
    assert (q["tur"], q["po_etiketi"], q["po_durumu"]) == ("soru", "CQ1", "yanitlandi")
    assert q["po_yaniti"]["metin"].startswith("5 hatalı denemede")
    assert engelli["po_yanit_onerisi"]["etiketler"] == ["CQ1"]
    assert varsayim["po_sorulari"]["A1"]["po_durumu"] == "gonderilmedi"
    assert varsayim["po_yanit_onerisi"] is None

    # Düzeltme: soru atfı kaldırılır, beklenen sonuç yanıttan yazılır → denetim kaydı kaynağı.
    tam = {
        **engelli["icerik"],
        "readiness": "ready",
        "open_question_refs": [],
        "expected_result": "5. hatalı denemede hesap 15 dakika kilitlenir",
    }
    r = api.post(
        f"/cases/{engelli['id']}/decision",
        json={"icerik_hash": engelli["icerik_hash"], "karar": "edit", "icerik": tam},
    )
    assert r.status_code == 200, r.text
    assert r.json()["po_yanit_onerisi"] is None
    with session_scope() as s:
        kayit = s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "case.po_yaniti_kaynak")
        ).one()
        assert kayit.nesne == f"test_case:{engelli['id']}"
        assert kayit.ozet["kaynak"] == "PO yanıtı CQ1"
        # Değişmez zincire metin girmez: etiket + özet (metin acik_soru satırında).
        (bilgi,) = kayit.ozet["sorular"]
        assert bilgi["etiket"] == "CQ1" and len(bilgi["yanit_hash"]) == 64
        assert "yanit" not in bilgi and "soru" not in bilgi
        assert "5 hatalı denemede" not in str(kayit.ozet)


def test_duzeltmeyle_kapanan_soru_yetim_sayilmaz(
    api: TestClient, ortam: uuid.UUID, sim: TestClient
) -> None:
    """Tur 3 inceleme #1: PO yanıtı + atfı kaldıran düzeltme doğru kapanıştır. Soru birleşik
    özette kalır ama artık hiçbir yerde anılmaz; liste "yeniden üret" önermez, kapsam özeti ve
    Kontrol Kulesi onu yetim saymaz."""
    from tp_core.features.control_tower.case_kalitesi import case_kalitesi

    def _durum() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        soru = api.get(f"/requirements/{ortam}/open-questions").json()["sorular"][0]
        ozet = api.get(f"/requirements/{ortam}/case-summary").json()
        with session_scope() as s:
            kule = case_kalitesi(s, ortam)["yetim_soru"]
            durum = service._coverage_state(s, s.get(Requirement, ortam))["acik_sorular"]
        return soru, ozet, {**kule, "durum": durum}

    assert api.post(f"/requirements/{ortam}/open-questions/send").status_code == 200
    _po_yorumu(sim, "CQ1: 5 hatalı denemede hesap 15 dakika kilitlenir.")
    assert api.post(f"/requirements/{ortam}/open-questions/refresh").status_code == 200
    soru, _, kule = _durum()
    assert soru["kapandi"] is False and soru["oneri"]["eylem"] == "duzelt_veya_yeniden_uret"
    assert kule["yetim"] == 0 and kule["durum"] == {"toplam": 1, "yetim": []}

    _, _, engelli = latest_cases(api, ortam)
    tam = {
        **engelli["icerik"],
        "readiness": "ready",
        "open_question_refs": [],
        "expected_result": "5. hatalı denemede hesap 15 dakika kilitlenir",
    }
    r = api.post(
        f"/cases/{engelli['id']}/decision",
        json={"icerik_hash": engelli["icerik_hash"], "karar": "edit", "icerik": tam},
    )
    assert r.status_code == 200, r.text

    soru, ozet, kule = _durum()
    assert soru["durum"] == "yanitlandi" and soru["bekleyen_caseler"] == []
    assert soru["kapandi"] is True and soru["oneri"] is None  # "yeniden_uret" değil
    assert not [u for u in ozet["uyarilar"] if "Q1" in u and "yetim" in u], ozet["uyarilar"]
    assert kule["durum"] == {"toplam": 1, "yetim": []}
    assert (kule["yetim"], kule["yetim_gereksinim"]) == (0, 0)


def test_periyodik_okuma_ve_gonderimden_onceki_yorum_sayilmaz(
    api: TestClient, ortam: uuid.UUID, sim: TestClient, jira: RestJira
) -> None:
    _po_yorumu(sim, "CQ1: gönderimden önce yazıldı")
    assert api.post(f"/requirements/{ortam}/open-questions/send").status_code == 200
    assert acik_sorular.poll(jira, frozenset({"po@sim.local"})) == 0
    _po_yorumu(sim, "cq1 - 5 deneme")
    assert acik_sorular.poll(jira, frozenset({"po@sim.local"})) == 1
    assert acik_sorular.poll(jira, frozenset({"po@sim.local"})) == 0  # yanıtlanan yeniden okunmaz
    soru = api.get(f"/requirements/{ortam}/open-questions").json()["sorular"][0]
    assert soru["yanit"]["metin"] == "5 deneme"


def test_uretim_girdisi_yanit_yoksa_ayni(
    api: TestClient, ortam: uuid.UUID, sim: TestClient
) -> None:
    with session_scope() as s:
        req = s.get(Requirement, ortam)
        assert acik_sorular.generation_input(s, req) == ""
        bos = service.generation_messages(req, [], test_verisi="TV")
        assert service.generation_messages(req, [], test_verisi="TV", acik_soru_yanitlari="") == bos
    assert api.post(f"/requirements/{ortam}/open-questions/send").status_code == 200
    _po_yorumu(sim, "CQ1: 5 denemede kilitlenir")
    assert api.post(f"/requirements/{ortam}/open-questions/refresh").status_code == 200
    with session_scope() as s:
        req = s.get(Requirement, ortam)
        metin = acik_sorular.generation_input(s, req)
        assert metin.startswith(f"CQ1 — Soru: {SORU}\nPO yanıtı (")
        assert metin.endswith("): 5 denemede kilitlenir")
        (mesaj,) = service.generation_messages(req, [], test_verisi="TV", acik_soru_yanitlari=metin)
        icerik = mesaj.content
        assert "PO'nun açık soru yanıtları" in icerik and "jira:TPD-4:po-acik-soru" in icerik
        assert icerik.index("po-acik-soru") < icerik.index("TV")
        # Story değişip yeniden onaylanırsa eski yanıt kaynak sayılmaz.
        baska = SimpleNamespace(id=req.id, onaylanan_hash="baska-icerik")
        assert acik_sorular.generation_input(s, baska) == ""  # type: ignore[arg-type]


def test_jira_story_si_yoksa_gonderilemez(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    fake_gateway([text_response(uretim_cikti(_cases(), **OZET))])
    rid = make_requirement(jira_key=None)
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    g = api.get(f"/requirements/{rid}/open-questions").json()
    assert g["gonderilebilir"] is False and "Jira story" in g["gonderim_engeli"]
    r = api.post(f"/requirements/{rid}/open-questions/send")
    assert r.status_code == 409 and "Jira story" in r.json()["detail"]


def test_yanit_ayristirma() -> None:
    assert acik_sorular.parse_answers("CQ1: a\nCQ2) b CA1 - doğru") == {
        "CQ1": "a",
        "CQ2": "b",
        "CA1": "doğru",
    }
    assert acik_sorular.parse_answers("Q1: ön inceleme; XCQ1: yok") == {}
    assert acik_sorular.parse_answers("cq3: x\nCQ3: y") == {"CQ3": "x / y"}


YETIM = "Arama sonuçları hangi sırayla listelenir?"


@pytest.fixture
def yetimli(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, jira: RestJira
) -> Iterator[uuid.UUID]:
    """Q2 hiçbir case'te ya da kararda anılmıyor (yetim; 011 tur 2 #1)."""
    sorular = [*OZET["open_questions"], {"id": "Q2", "question": YETIM, "owner": "PO"}]
    fake_gateway([text_response(uretim_cikti(_cases(), **{**OZET, "open_questions": sorular}))])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    with services.override(jira=lambda: jira, po_accounts=lambda: {"po@sim.local"}):
        yield rid


def test_yanitlanan_yetim_soru_yeniden_uretim_onerir(
    api: TestClient, yetimli: uuid.UUID, sim: TestClient
) -> None:
    assert api.post(f"/requirements/{yetimli}/open-questions/send").status_code == 200
    _po_yorumu(sim, "CQ2: Fiyata göre artan.")
    sorular = api.post(f"/requirements/{yetimli}/open-questions/refresh").json()["sorular"]
    yetim = next(s for s in sorular if s["kaynak_id"] == "Q2")
    assert yetim["durum"] == "yanitlandi" and yetim["bekleyen_caseler"] == []
    assert yetim["oneri"]["eylem"] == "yeniden_uret" and yetim["oneri"]["case_ids"] == []
    assert "yeniden üretin" in yetim["oneri"]["mesaj"]
    # Bağlı soru yanıtlanmadıkça önerisi yok.
    assert next(s for s in sorular if s["kaynak_id"] == "Q1")["oneri"] is None


def test_jira_cagrisi_gereksinim_kilidi_altinda_yapilmaz(
    api: TestClient, ortam: uuid.UUID, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tur 2 güvenlik #4: yorum yazılırken gereksinim satırı başka işlemce kilitlenebilir."""
    from tp_core.integrations import jira_notify

    asil = jira_notify.post_comment
    kilitlenebildi: list[bool] = []

    def yaz(*a: Any, **kw: Any) -> Any:
        with engine.connect() as c:
            c.execute(
                text("SELECT id FROM requirement WHERE id = :i FOR UPDATE NOWAIT"), {"i": ortam}
            )
            kilitlenebildi.append(True)
            c.rollback()
        return asil(*a, **kw)

    monkeypatch.setattr(jira_notify, "post_comment", yaz)
    r = api.post(f"/requirements/{ortam}/open-questions/send")
    assert r.status_code == 200, r.text
    assert kilitlenebildi == [True]
    assert r.json()["sorular"][0]["durum"] == "gonderildi"


def test_jira_hatasinda_satir_bekler_ve_ayni_etiketle_yeniden_gonderilir(
    api: TestClient, ortam: uuid.UUID, sim: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.integrations import jira_notify

    asil = jira_notify.post_comment

    def bozuk(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("Jira erişilemiyor")

    monkeypatch.setattr(jira_notify, "post_comment", bozuk)
    with pytest.raises(RuntimeError):
        api.post(f"/requirements/{ortam}/open-questions/send")
    soru = api.get(f"/requirements/{ortam}/open-questions").json()["sorular"][0]
    assert (soru["etiket"], soru["durum"]) == ("CQ1", "gonderilmedi")
    assert soru["gonderim_belirsiz"] is True  # tur 3 #11: portal ipucu
    monkeypatch.setattr(jira_notify, "post_comment", asil)
    once = len(_yorumlar(sim))
    r = api.post(f"/requirements/{ortam}/open-questions/send")
    assert r.status_code == 200, r.text
    assert (r.json()["sorular"][0]["etiket"], r.json()["sorular"][0]["durum"]) == (
        "CQ1",
        "gonderildi",
    )
    assert len(_yorumlar(sim)) == once + 1
    assert r.json()["sorular"][0]["gonderim_belirsiz"] is False


def test_yorum_boyutu_sinirli_sigmayan_soru_sonraki_gonderime_kalir(
    api: TestClient, yetimli: uuid.UUID, sim: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tur 2 güvenlik #9: yorum boyutu sınırlı; sığmayan soru satırsız kalır, sonra gider."""
    monkeypatch.setattr(acik_sorular, "YORUM_SINIRI", 120)
    r = api.post(f"/requirements/{yetimli}/open-questions/send")
    assert r.status_code == 200, r.text
    durumlar = {s["kaynak_id"]: (s["etiket"], s["durum"]) for s in r.json()["sorular"]}
    assert durumlar["Q1"] == ("CQ1", "gonderildi") and durumlar["Q2"] == (None, "gonderilmedi")
    assert "+1 soru daha portalda bekliyor" in _yorumlar(sim)[-1]
    r = api.post(f"/requirements/{yetimli}/open-questions/send")
    assert r.status_code == 200, r.text
    etiketler = {s["kaynak_id"]: s["etiket"] for s in r.json()["sorular"]}
    assert (etiketler["Q1"], etiketler["Q2"]) == ("CQ1", "CQ2")
    # Model üretimi uzun metin satırda kırpılır.
    uzun = SimpleNamespace(etiket="CQ9", sahip="PO", tur="soru", metin="x" * 5000)
    tc = SimpleNamespace(sira_no=1, icerik={"title": "t" * 500})
    satir = acik_sorular._soru_satiri(uzun, [tc] * 9)  # type: ignore[arg-type]
    assert len(satir) < 1200 and satir.endswith("+4 case")


def test_idempotency_anahtari_soru_metnine_baglidir() -> None:
    """Tur 2 güvenlik #5: aynı etiket farklı soru metniyle farklı anahtar (ve işaret) verir."""
    rid = uuid.uuid4()
    a = SimpleNamespace(etiket="CQ1", metin_hash="h1")
    b = SimpleNamespace(etiket="CQ1", metin_hash="h2")
    k1 = acik_sorular.idempotency_key(rid, "onay", [a])  # type: ignore[list-item]
    k2 = acik_sorular.idempotency_key(rid, "onay", [b])  # type: ignore[list-item]
    assert k1 != k2 and ":CQ1:" in k1
    assert k1 == acik_sorular.idempotency_key(rid, "onay", [a])  # type: ignore[list-item]


def _analist() -> Any:
    from tp_core.workflow.service import Principal

    return Principal(id=None, kullanici_adi="analyst-b", rol="analyst")


def test_eszamanli_gonderim_tek_yorum_yazar(
    api: TestClient, ortam: uuid.UUID, sim: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tur 3 güvenlik #1: A'nın Jira çağrısı sürerken gelen aynı gönderim (çift tık, iki analist)
    `intent` kaydını belirsiz sayıp yorumu ikinci kez yazamaz; 409 alır."""
    from tp_core.integrations import jira_notify

    asil = jira_notify.post_comment
    cagri: list[int] = []
    ikinci: list[Exception] = []

    def yaz(*a: Any, **kw: Any) -> Any:
        cagri.append(1)
        if len(cagri) == 1:  # A Jira çağrısındayken B aynı seti gönderir
            try:
                with new_session() as s:
                    acik_sorular.send(s, ortam, _analist())
            except Exception as exc:  # beklenen 409 toplanır
                ikinci.append(exc)
        return asil(*a, **kw)

    monkeypatch.setattr(jira_notify, "post_comment", yaz)
    once = len(_yorumlar(sim))
    r = api.post(f"/requirements/{ortam}/open-questions/send")
    assert r.status_code == 200, r.text
    assert len(cagri) == 1 and len(_yorumlar(sim)) == once + 1
    assert len(ikinci) == 1 and isinstance(ikinci[0], acik_sorular.GonderimSuruyor)
    assert ikinci[0].status_code == 409  # type: ignore[attr-defined]
    assert r.json()["sorular"][0]["durum"] == "gonderildi"
    with session_scope() as s:
        assert (
            len(
                s.scalars(
                    select(AuditEvent.id).where(AuditEvent.eylem == "acik_soru.gonderildi")
                ).all()
            )
            == 1
        )


def test_gec_gelen_esit_gonderim_denetimi_ciftlemez(
    api: TestClient, ortam: uuid.UUID, sim: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tur 3 güvenlik #1: A yorumu yazdıktan sonra (aşama 3'ten önce) gelen B aynı yorumu bulur,
    satırları o işaretler; A satırları atlar ve denetim kaydı bir kez düşer."""
    from tp_core.integrations import jira_notify

    asil_yaz = jira_notify.post_comment
    asil_zaman = acik_sorular._yorum_zamani
    cagri: list[int] = []
    b_sonuc: list[dict[str, Any]] = []
    b_basladi: list[int] = []

    def yaz(*a: Any, **kw: Any) -> Any:
        cagri.append(1)
        return asil_yaz(*a, **kw)

    def zaman(*a: Any, **kw: Any) -> Any:
        if not b_basladi:
            b_basladi.append(1)
            with new_session() as s:
                b_sonuc.append(acik_sorular.send(s, ortam, _analist()))
                s.commit()
        return asil_zaman(*a, **kw)

    monkeypatch.setattr(jira_notify, "post_comment", yaz)
    monkeypatch.setattr(acik_sorular, "_yorum_zamani", zaman)
    once = len(_yorumlar(sim))
    r = api.post(f"/requirements/{ortam}/open-questions/send")
    assert r.status_code == 200, r.text
    assert len(cagri) == 1 and len(_yorumlar(sim)) == once + 1
    assert b_sonuc[0]["sorular"][0]["durum"] == "gonderildi"
    with session_scope() as s:
        kayitlar = s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "acik_soru.gonderildi")
        ).all()
        assert len(kayitlar) == 1


def test_yanit_okuma_gereksinim_basina_commit_eder(
    api: TestClient,
    ortam: uuid.UUID,
    sim: TestClient,
    jira: RestJira,
    engine: Engine,
    make_requirement,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tur 3 güvenlik #10: bir gereksinimin satır kilitleri sonraki gereksinimin Jira okuması
    boyunca tutulmaz (gereksinim başına commit)."""
    from tp_core.features.requirements import flow

    assert api.post(f"/requirements/{ortam}/open-questions/send").status_code == 200
    _po_yorumu(sim, "CQ1: 5 deneme")
    ikinci = make_requirement(jira_key="TPD-1")
    with session_scope() as s:
        s.add(
            AcikSoru(
                requirement_id=ikinci,
                tur="soru",
                etiket="CQ1",
                kaynak_id="Q1",
                metin="Başka soru",
                metin_hash="h",
                durum="gonderildi",
                gereksinim_hash="",
                gonderen="analyst",
            )
        )
    asil = flow._po_cevaplari
    kilitsiz: list[bool] = []

    def oku(*a: Any, **kw: Any) -> Any:
        with engine.connect() as c:  # okuyucu hiçbir açık soru satırını kilitli tutmuyor
            c.execute(text("SELECT id FROM acik_soru FOR UPDATE NOWAIT")).all()
            kilitsiz.append(True)
            c.rollback()
        return asil(*a, **kw)

    monkeypatch.setattr(flow, "_po_cevaplari", oku)
    assert acik_sorular.poll(jira, frozenset({"po@sim.local"})) == 1
    assert kilitsiz == [True, True]
