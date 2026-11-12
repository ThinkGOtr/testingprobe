"""Jira durum tetiği (specs/013-sprint-otomasyonu §3.4, K14, K15): ilk tur durumda olanları yalnız
işaretler; sonradan "QA To Do"ya GİREN story çekilir ve ön incelemeye girer; çift tetik yok; tur
başına en çok 10 tetik; içerik değişip `new`'e dönen tetikli story yeniden incelenir; PO onaylı ve
case'siz story girince case üretimi başlar; ayar kapalıyken Jira'ya gidilmez; tek issue hatası turu
durdurmaz; uçtan uca zincir case'lere kadar. Gerçek Postgres, süreç içi jira-sim, REPLAY geçidi."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.features.cases import jobs as _case_jobs  # noqa: F401 — cases.generate işleyicisi
from tp_core.features.otomasyon import ayarlar, jira_tetik
from tp_core.features.requirements import flow
from tp_core.integrations.jira import JiraUnavailable, RestJira
from tp_core.models import Requirement, new_session, session_scope
from tp_core.ports import JiraIssue

from ...requirements.conftest import PoActions, login, run_jobs

pytestmark = pytest.mark.usefixtures("wired")

QA = "QA To Do"


def _tasi(jira: RestJira, key: str, durum: str = QA) -> None:
    gecis = next(t for t in jira.transitions(key) if t["to"]["name"] == durum)
    jira.transition(key, gecis["id"])


def _req(key: str) -> Requirement | None:
    with new_session() as s:
        return s.scalars(select(Requirement).where(Requirement.jira_key == key)).first()


def _ayar(**deger: Any) -> None:
    with session_scope() as s:
        ayarlar.yaz(s, ayarlar.JIRA_TETIK, deger, "test")


def _isler(engine: Engine, tur: str) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text(
                    "SELECT id, durum, yuk, sonuc, run_after FROM job WHERE tur = :t "
                    "ORDER BY olusturma"
                ),
                {"t": tur},
            )
        )


def _denetim(engine: Engine, eylem: str) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT aktor, nesne, ozet FROM audit_event WHERE eylem = :e ORDER BY id"),
                {"e": eylem},
            )
        )


# ------------------------------------------------------------------------------ JQL


def test_durum_adi_tirnak_kacisi() -> None:
    assert jira_tetik.jql_dizesi("QA To Do") == '"QA To Do"'
    assert jira_tetik.jql_dizesi('QA "Hazır" \\ x') == r'"QA \"Hazır\" \\ x"'
    assert jira_tetik.jql_dizesi("a\nb") == '"a b"'
    assert (
        jira_tetik.tetik_jql("TPD", 'QA" OR project = X')
        == r'project = TPD AND issuetype = Story AND status = "QA\" OR project = X" '
        "ORDER BY key ASC"
    )
    with pytest.raises(flow.FlowInputError):
        jira_tetik.tetik_jql("TPD OR 1=1", QA)


class _SahteJira:
    def __init__(self, issues: list[JiraIssue] | None = None, hata: Exception | None = None):
        self.issues = issues or []
        self.hata = hata
        self.jql: list[str] = []

    def search(self, jql: str, max_results: int = 50) -> list[JiraIssue]:
        self.jql.append(jql)
        if self.hata:
            raise self.hata
        return list(self.issues)


def test_ayarlanan_durum_adi_kacisli_sorguya_girer(engine: Engine) -> None:
    _ayar(durum='QA "Hazır"')
    sahte = _SahteJira()
    ozet = jira_tetik.tur(engine, sahte)
    assert sahte.jql == [
        r'project = TPD AND issuetype = Story AND status = "QA \"Hazır\"" ORDER BY key ASC'
    ]
    assert ozet["bulunan"] == 0 and ozet["hata"] is None


# ------------------------------------------------------------------------- tetik turu


def _taban(engine: Engine) -> dict[str, Any]:
    """İlk tur: başlangıç işareti kurulur (o anda durumda olanlar yalnız işaretlenir)."""
    ozet = jira_tetik.tur(engine)
    assert ozet["taban"] is True and ozet["tetiklenen"] == 0, ozet
    return ozet


def _sonuc(ozet: dict[str, Any], key: str) -> dict[str, Any]:
    return next(r for r in ozet["sonuclar"] if r["jira_key"] == key)


def test_ilk_tur_durumda_olanlari_yalniz_isaretler(engine: Engine, jira: RestJira) -> None:
    _tasi(jira, "TPD-4")
    ozet = jira_tetik.tur(engine)
    assert ozet["taban"] is True and ozet["bulunan"] == 1 and ozet["tetiklenen"] == 0
    assert _sonuc(ozet, "TPD-4")["sonuc"] == "isaretlendi"
    req = _req("TPD-4")
    assert req is not None and req.durum == "new" and req.jira_durumu == QA
    assert req.qa_tetik_zamani is None
    assert _isler(engine, flow.JOB_REVIEW) == []
    # İkinci tur: hâlâ durumda; giriş değil → tetik yok, yazma yok.
    ozet2 = jira_tetik.tur(engine)
    assert ozet2["taban"] is False and ozet2["tetiklenen"] == 0
    assert _sonuc(ozet2, "TPD-4")["sonuc"] == "durumda"
    assert _req("TPD-4").guncelleme == req.guncelleme
    assert _denetim(engine, "requirements.jira_tetik") == []


def test_sonradan_giren_tetiklenir_ikinci_turda_cift_tetik_yok(
    engine: Engine, jira: RestJira
) -> None:
    _taban(engine)
    _tasi(jira, "TPD-4")
    ozet = jira_tetik.tur(engine)
    assert ozet["acik"] is True and ozet["durum"] == QA and ozet["taban"] is False
    assert ozet["bulunan"] == 1 and ozet["tetiklenen"] == 1 and ozet["hata"] is None
    assert ozet["tetiklenenler"] == ["TPD-4"]
    assert ozet["sonuclar"] == [
        {"jira_key": "TPD-4", "sonuc": "tetiklendi", "neden": jira_tetik.TETIKLENDI_NEDENI}
    ]
    req = _req("TPD-4")
    assert req is not None and req.durum == "in_review"
    assert req.jira_durumu == QA and req.qa_tetik_zamani is not None
    assert _req("TPD-1") is None  # yalnız durumdaki story çekilir
    [d] = _denetim(engine, "requirements.jira_tetik")
    assert d.aktor == "jira-tetik" and d.ozet["jira_key"] == "TPD-4" and d.ozet["durum"] == QA
    assert d.ozet["sonuc"] == "tetiklendi"
    [olusturma] = _denetim(engine, "requirement.created")
    assert olusturma.aktor == "jira-tetik"
    with engine.connect() as c:
        wf = c.execute(
            text("SELECT baslatan FROM workflow_instance WHERE nesne_id = :r"), {"r": req.id}
        ).scalar_one()
    assert wf == "otomasyon"
    ilk_zaman = req.qa_tetik_zamani

    # İkinci tur: çift tetik yok (in_review). İnceleme bitip pending_po'ya geçince de yok.
    ozet2 = jira_tetik.tur(engine)
    assert ozet2["tetiklenen"] == 0 and _sonuc(ozet2, "TPD-4")["sonuc"] == "durumda"
    run_jobs(engine)
    assert _req("TPD-4").durum == "pending_po"
    assert jira_tetik.tur(engine)["tetiklenen"] == 0
    assert len(_denetim(engine, "requirements.jira_tetik")) == 1
    assert _req("TPD-4").qa_tetik_zamani == ilk_zaman


def test_durumdan_cikan_temizlenir_geri_gelen_yeniden_giris_sayilir(
    engine: Engine, jira: RestJira
) -> None:
    _taban(engine)
    _tasi(jira, "TPD-4")
    assert jira_tetik.tur(engine)["tetiklenenler"] == ["TPD-4"]
    run_jobs(engine)
    assert _req("TPD-4").durum == "pending_po"
    _tasi(jira, "TPD-4", "To Do")
    assert jira_tetik.tur(engine)["bulunan"] == 0
    assert _req("TPD-4").jira_durumu is None
    _tasi(jira, "TPD-4")
    ozet = jira_tetik.tur(engine)
    # pending_po'daki story akışa alınır (PO onayı gelince case üretimi), ön inceleme yinelenmez.
    assert _sonuc(ozet, "TPD-4")["sonuc"] == "akisa_alindi" and ozet["tetiklenen"] == 0
    assert _req("TPD-4").durum == "pending_po" and _req("TPD-4").jira_durumu == QA


def test_akisa_alindi_nedeni_otomatik_case_ayarina_gore(engine: Engine, jira: RestJira) -> None:
    """PO #7: `otomatik_case` kapalıyken neden elle başlatmayı söyler."""
    _taban(engine)
    _tasi(jira, "TPD-4")
    jira_tetik.tur(engine)
    run_jobs(engine)
    assert _req("TPD-4").durum == "pending_po"
    _ayar(otomatik_case=False)
    _tasi(jira, "TPD-4", "To Do")
    jira_tetik.tur(engine)
    _tasi(jira, "TPD-4")
    r = _sonuc(jira_tetik.tur(engine), "TPD-4")
    assert r == {"jira_key": "TPD-4", "sonuc": "akisa_alindi",
                 "neden": jira_tetik.AKISA_ALINDI_ELLE_NEDENI}  # fmt: skip
    assert "elle başlatın" in r["neden"]
    assert _denetim(engine, "requirements.jira_tetik")[-1].ozet["neden"] == r["neden"]


def test_elle_cekilip_new_kalan_story_girince_tetiklenir(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira
) -> None:
    _taban(engine)
    login(api, make_user("analyst"))
    assert api.post("/requirements/sync").status_code == 200
    assert _req("TPD-3").durum == "new"
    _tasi(jira, "TPD-3")
    assert jira_tetik.tur(engine)["tetiklenenler"] == ["TPD-3"]
    assert _req("TPD-3").durum == "in_review"


def _story(no: int) -> JiraIssue:
    return JiraIssue(
        key=f"TPD-{100 + no}",
        issue_type="Story",
        summary=f"Story {no}",
        description=f"Açıklama {no}",
        acceptance_criteria=[f"AC1: koşul {no}"],
        status=QA,
    )


def test_tur_basina_en_cok_10_tetik_kalan_sonraki_tura(engine: Engine) -> None:
    _taban(engine)
    sahte = _SahteJira([_story(i) for i in range(12)])
    ozet = jira_tetik.tur(engine, sahte)
    assert ozet["tetiklenen"] == jira_tetik.TETIK_SINIRI == 10 and ozet["ertelenen"] == 2
    ertelenen = [r["jira_key"] for r in ozet["sonuclar"] if r["sonuc"] == "ertelendi"]
    assert ertelenen == ["TPD-110", "TPD-111"]
    assert all(_req(k) is None for k in ertelenen)  # ertelenen hiç yazılmaz
    ozet2 = jira_tetik.tur(engine, sahte)
    assert ozet2["tetiklenenler"] == ["TPD-110", "TPD-111"] and ozet2["ertelenen"] == 0
    assert _req("TPD-111").durum == "in_review"


def test_durumdaki_tetikli_storylerin_icerik_degisimi_tur_sinirina_tabi(engine: Engine) -> None:
    """Mimar #4: durumda kalan tetikli story'nin tutarlılık denetimini yeniden koşturan içerik
    çekimi de tur bütçesinden düşer; iş başlatmayan çekim (`mesgul`) düşmez."""
    from tp_core.models.guard import allow_state_write

    _taban(engine)
    hikayeler = [_story(i) for i in range(12)]
    sahte = _SahteJira(hikayeler)
    jira_tetik.tur(engine, sahte)
    assert jira_tetik.tur(engine, sahte)["tetiklenen"] == 2  # 12 story de tetikli (in_review)
    sahte.issues = [
        h.model_copy(update={"description": h.description + " (güncel)"}) for h in hikayeler
    ]
    # in_review: çekim `mesgul` (iş başlatmaz) → bütçe harcanmaz, hiçbiri ertelenmez.
    ozet = jira_tetik.tur(engine, sahte)
    assert ozet["ertelenen"] == 0 and ozet["tetiklenen"] == 0, ozet["sonuclar"]
    with allow_state_write(), session_scope() as s:
        for r in s.scalars(select(Requirement).where(Requirement.jira_key.like("TPD-1__"))):
            r.durum = "pending_po"
    ozet = jira_tetik.tur(engine, sahte)
    assert ozet["tetiklenen"] == 0 and ozet["ertelenen"] == 2, ozet["sonuclar"]
    yeniden = [r for r in ozet["sonuclar"] if r["sonuc"] == "guncellendi"]
    assert len(yeniden) == jira_tetik.TETIK_SINIRI
    assert all("yeniden koşuyor" in r["neden"] for r in yeniden)
    ozet = jira_tetik.tur(engine, sahte)  # kalan 2 sonraki turda
    assert ozet["ertelenen"] == 0
    assert sum(r["sonuc"] == "guncellendi" for r in ozet["sonuclar"]) == 2


def test_tetik_yeniden_acilinca_taban_yeniden_kurulur(engine: Engine, jira: RestJira) -> None:
    _taban(engine)
    _ayar(acik=False)
    _tasi(jira, "TPD-4")  # tetik kapalıyken duruma girdi
    _ayar(acik=True)
    with new_session() as s:
        assert ayarlar.tetik_tabani(s) is None
    ozet = jira_tetik.tur(engine)
    assert ozet["taban"] is True and _sonuc(ozet, "TPD-4")["sonuc"] == "isaretlendi"
    assert _req("TPD-4").durum == "new"
    # Durum adı değişince de taban yeniden kurulur.
    jira_tetik.tur(engine)
    _ayar(durum="QA Hazır")
    with new_session() as s:
        assert ayarlar.tetik_tabani(s) is None
    # Aralık değişimi tabanı korur.
    _ayar(durum=QA)
    jira_tetik.tur(engine)
    _ayar(aralik_s=120)
    with new_session() as s:
        assert ayarlar.tetik_tabani(s)["durum"] == QA


def test_taban_turunda_kalici_hatali_story_tetigi_kilitlemez(
    engine: Engine, jira: RestJira, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mimar #2: taban turunda bir story kalıcı hata verse de işaret yazılır (hatalı story
    `bekleyen_isaret`te); sonradan giren story tetiklenir; hatalı story "giren" sayılmaz, yalnız
    işaretleme yeniden denenir ve başarılı olunca listeden düşer. Hata denetime bir kez yazılır."""
    _tasi(jira, "TPD-3")
    asil = flow.upsert_issue

    def bozuk(session: Any, issue: Any, actor: Any) -> str:
        if issue.key == "TPD-3":
            raise RuntimeError("iç ayrıntı: postgres://gizli")
        return asil(session, issue, actor)

    monkeypatch.setattr(flow, "upsert_issue", bozuk)
    ozet = jira_tetik.tur(engine)
    assert ozet["taban"] is True and ozet["hata"] == "1 story işlenemedi"
    assert _sonuc(ozet, "TPD-3") == {
        "jira_key": "TPD-3", "sonuc": "hata", "neden": jira_tetik.STORY_HATASI,
    }  # fmt: skip
    with new_session() as s:
        taban = ayarlar.tetik_tabani(s)
    assert taban is not None and taban["bekleyen_isaret"] == ["TPD-3"]
    # Sonraki tur taban turu değil: giren TPD-4 tetiklenir; TPD-3 yine hatalı ama tetiklenmez.
    _tasi(jira, "TPD-4")
    ozet = jira_tetik.tur(engine)
    assert ozet["taban"] is False and ozet["tetiklenenler"] == ["TPD-4"]
    assert _sonuc(ozet, "TPD-3")["sonuc"] == "hata"
    hatalar = [d for d in _denetim(engine, "requirements.jira_tetik") if d.ozet["sonuc"] == "hata"]
    assert len(hatalar) == 1 and hatalar[0].ozet["jira_key"] == "TPD-3"
    assert "gizli" not in str(hatalar[0].ozet)
    # Hata giderilince yalnız işaretlenir (tetik yok) ve bekleyen listeden düşer.
    monkeypatch.setattr(flow, "upsert_issue", asil)
    ozet = jira_tetik.tur(engine)
    assert _sonuc(ozet, "TPD-3")["sonuc"] == "isaretlendi" and ozet["tetiklenen"] == 0
    assert _req("TPD-3").durum == "new" and _req("TPD-3").qa_tetik_zamani is None
    with new_session() as s:
        assert "bekleyen_isaret" not in ayarlar.tetik_tabani(s)
    assert _sonuc(jira_tetik.tur(engine), "TPD-3")["sonuc"] == "durumda"


def test_ayar_kapali_jiraya_gidilmez(engine: Engine, jira: RestJira) -> None:
    _tasi(jira, "TPD-4")
    _ayar(acik=False)
    sahte = _SahteJira()
    ozet = jira_tetik.tur(engine, sahte)
    assert ozet["acik"] is False and ozet["tetiklenen"] == 0 and sahte.jql == []
    assert jira_tetik.tur(engine)["bulunan"] == 0
    assert _req("TPD-4") is None


def test_jira_erisilemezse_tur_bos_gecer_hata_metni_sabit(engine: Engine) -> None:
    ozet = jira_tetik.tur(engine, _SahteJira(hata=JiraUnavailable("10.0.0.5:8443 reddetti")))
    assert ozet["bulunan"] == 0 and ozet["hata"] == "Jira'ya erişilemedi"
    with new_session() as s:
        assert ayarlar.tetik_tabani(s) is None


def test_bir_issue_hatasi_digerini_durdurmaz(
    engine: Engine, jira: RestJira, monkeypatch: pytest.MonkeyPatch
) -> None:
    _taban(engine)
    _tasi(jira, "TPD-3")
    _tasi(jira, "TPD-4")
    asil = flow.upsert_issue

    def bozuk(session: Any, issue: Any, actor: Any) -> str:
        if issue.key == "TPD-3":
            raise RuntimeError("bozuk kayıt")
        return asil(session, issue, actor)

    monkeypatch.setattr(flow, "upsert_issue", bozuk)
    ozet = jira_tetik.tur(engine)
    assert ozet["bulunan"] == 2 and ozet["tetiklenenler"] == ["TPD-4"]
    assert _sonuc(ozet, "TPD-3")["sonuc"] == "hata"
    assert "bozuk kayıt" not in str(ozet)  # istisna ayrıntısı yalnız log'da
    assert ozet["hata"] == "1 story işlenemedi"
    assert _req("TPD-3") is None and _req("TPD-4").durum == "in_review"
    monkeypatch.setattr(flow, "upsert_issue", asil)
    assert jira_tetik.tur(engine)["tetiklenenler"] == ["TPD-3"]  # sonraki turda girer


def test_durumu_tutmayan_issue_atlanir(engine: Engine) -> None:
    issue = JiraIssue(key="TPD-9", issue_type="Story", summary="x", status="Done")
    ozet = jira_tetik.tur(engine, _SahteJira([issue]))
    assert ozet["bulunan"] == 0 and _req("TPD-9") is None


# ------------------------------------------------------------------- K14 varsayılan


def test_acik_varsayilani_simde_acik_gercek_jirada_kapali(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with new_session() as s:
        assert ayarlar.jira_tetik(s).acik is True  # test ortamı jira-sim
        monkeypatch.setattr(ayarlar, "jira_sim_mi", lambda: False)
        assert ayarlar.jira_tetik(s).acik is False
        assert ayarlar.hepsi(s)["jira_tetik"]["acik"] is False
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM otomasyon_ayari")).scalar_one() == 0
    sahte = _SahteJira()
    assert jira_tetik.tur(engine, sahte)["acik"] is False and sahte.jql == []
    # Kısmi yazım birbirini ezmez; hesaplanmış `acik` satıra dondurulmaz (backend #3b).
    _ayar(aralik_s=90)
    _ayar(otomatik_case=False)
    with new_session() as s:
        a = ayarlar.jira_tetik(s)
    assert (a.acik, a.aralik_s, a.otomatik_case) == (False, 90, False)
    with engine.connect() as c:
        deger = c.execute(
            text("SELECT deger FROM otomasyon_ayari WHERE anahtar = 'jira_tetik'")
        ).scalar_one()
    assert deger == {"aralik_s": 90, "otomatik_case": False}
    monkeypatch.undo()  # sim yeniden doğrulandı: varsayılan açık geri gelir
    with new_session() as s:
        assert ayarlar.jira_tetik(s).acik is True


# ------------------------------------------------------------------ worker işi + API


def test_sim_dogrulamasi_host_adina_dayanmaz_ve_onbelleklenir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Güvenlik #6: host adı sim olsa da `/health` doğrulaması yoksa varsayılan kapalı; doğrulama
    önbellekli (her okumada ağ çağrısı yok)."""
    cagri: list[int] = []

    def dogrula() -> bool:
        cagri.append(1)
        return False

    ayarlar.sim_onbellegini_temizle()
    monkeypatch.setattr(ayarlar, "_sim_dogrula", dogrula)
    try:
        with new_session() as s:
            assert ayarlar.jira_tetik(s).acik is False
            assert ayarlar.hepsi(s)["jira_tetik"]["acik"] is False
            assert ayarlar.jira_tetik(s).acik is False
        assert cagri == [1]

        def patlar() -> bool:
            raise RuntimeError("ağ yok")

        ayarlar.sim_onbellegini_temizle()
        monkeypatch.setattr(ayarlar, "_sim_dogrula", patlar)
        assert ayarlar.jira_sim_mi() is False
    finally:
        ayarlar.sim_onbellegini_temizle()
    monkeypatch.undo()
    assert ayarlar.jira_sim_mi() is True  # süreç içi jira-sim kendini tanıtır


def test_is_kendini_yeniden_planlar_ve_api_son_turu_gosterir(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira
) -> None:
    from tp_core.features.requirements import jobs

    _taban(engine)
    with engine.begin() as c:
        jobs.on_worker_start(c)
        assert jira_tetik.ensure(c) is None  # tek bekleyen iş
    _tasi(jira, "TPD-4")
    sonuclar = run_jobs(engine, limit=1)  # po_poll ya da tetik; tetik koşana kadar işle
    for _ in range(3):
        if any(i.durum == "done" for i in _isler(engine, jira_tetik.JOB_JIRA_TETIK)):
            break
        sonuclar += run_jobs(engine, limit=1)
    isler = _isler(engine, jira_tetik.JOB_JIRA_TETIK)
    bitti = [i for i in isler if i.durum == "done"]
    assert len(bitti) == 1, sonuclar
    assert bitti[0].sonuc["tetiklenen"] == 1
    bekleyen = [i for i in isler if i.durum == "queued"]
    assert len(bekleyen) == 1
    assert bekleyen[0].run_after > flow.now() + timedelta(seconds=50)  # aralik_s = 60

    login(api, make_user("tester"))
    r = api.get("/automation/jira-trigger")
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["acik"] is True and g["durum"] == QA and g["aralik_s"] == 60
    assert g["taban_kurulu"] is True
    st = g["son_tur"]
    assert st["bulunan"] == 1 and st["tetiklenen"] == 1 and st["ertelenen"] == 0
    assert st["hata"] is None and st["zaman"] and st["taban"] is False
    assert st["sonuclar"] == [
        {"jira_key": "TPD-4", "sonuc": "tetiklendi", "neden": jira_tetik.TETIKLENDI_NEDENI}
    ]
    assert [t["jira_key"] for t in g["son_tetiklenenler"]] == ["TPD-4"]
    assert g["son_tetiklenenler"][0]["zaman"]
    assert g["son_tetiklenenler"][0]["sonuc"] == "tetiklendi"
    assert g["son_tetiklenenler"][0]["neden"] == jira_tetik.TETIKLENDI_NEDENI


def test_api_oturumsuz_401(api: TestClient) -> None:
    assert api.get("/automation/jira-trigger").status_code == 401


def test_api_taban_kurulu_ilk_turdan_once_false(api: TestClient, engine: Engine, make_user) -> None:
    login(api, make_user("tester"))
    assert api.get("/automation/jira-trigger").json()["taban_kurulu"] is False
    _taban(engine)
    assert api.get("/automation/jira-trigger").json()["taban_kurulu"] is True
    _ayar(durum="QA Hazır")  # durum değişti: işaret silinir
    assert api.get("/automation/jira-trigger").json()["taban_kurulu"] is False


def test_ayar_kapaliyken_is_yalniz_yeniden_planlar(engine: Engine) -> None:
    from tp_core.features.requirements import jobs
    from tp_core.workflow.jobs import JobContext

    _ayar(acik=False, aralik_s=300)
    sonuc = jobs.jira_tetik_turu(JobContext(job_id=None, tur="x", yuk={}, deneme=1, max_deneme=1))
    assert sonuc["acik"] is False and sonuc["bulunan"] == 0
    [bekleyen] = _isler(engine, jira_tetik.JOB_JIRA_TETIK)
    assert bekleyen.durum == "queued"
    assert bekleyen.run_after > flow.now() + timedelta(seconds=290)


def test_zaman_asiminda_kopan_zinciri_po_sorgusu_kurar(engine: Engine) -> None:
    from tp_core.features.requirements import jobs
    from tp_core.workflow.jobs import JobContext

    assert _isler(engine, jira_tetik.JOB_JIRA_TETIK) == []
    jobs.po_poll(JobContext(job_id=None, tur="x", yuk={}, deneme=1, max_deneme=1))
    [bekleyen] = _isler(engine, jira_tetik.JOB_JIRA_TETIK)
    assert bekleyen.durum == "queued"


def test_ayar_api_durum_yalniz_engineer_ve_yeniden_planlama(
    api: TestClient, make_user: Any, engine: Engine
) -> None:
    with engine.begin() as c:
        jira_tetik.ensure(c, gecikme_s=3000)
    login(api, make_user("analyst"))
    r = api.put("/automation-settings/jira_tetik", json={"durum": "QA Hazır"})
    assert r.status_code == 403 and "mühendis" in r.json()["detail"]
    r = api.put("/automation-settings/jira_tetik", json={"aralik_s": 120})
    assert r.status_code == 200, r.text
    [bekleyen] = _isler(engine, jira_tetik.JOB_JIRA_TETIK)
    assert bekleyen.run_after < flow.now() + timedelta(seconds=125)  # min(3000 sn, 120 sn)

    login(api, make_user("engineer"))
    r = api.put("/automation-settings/jira_tetik", json={"durum": "QA Hazır"})
    assert r.status_code == 200 and r.json()["jira_tetik"]["durum"] == "QA Hazır"
    [bekleyen] = _isler(engine, jira_tetik.JOB_JIRA_TETIK)
    assert bekleyen.run_after <= flow.now()  # durum değişti: hemen yeni taban turu


# ------------------------------------------------------------------ otomatik case üretimi


def _tetikle_ve_po_onayla(engine: Engine, jira: RestJira, po: PoActions) -> str:
    _taban(engine)
    _tasi(jira, "TPD-4")
    assert jira_tetik.tur(engine)["tetiklenenler"] == ["TPD-4"]
    run_jobs(engine)
    req = _req("TPD-4")
    assert req.durum == "pending_po"
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][str(req.id)] == "onaylandi"
    return str(req.id)


def _akis(api: TestClient, rid: str) -> Any:
    r = api.get(f"/requirements/{rid}")
    assert r.status_code == 200, r.text
    liste = {g["id"]: g for g in api.get("/requirements").json()}
    assert liste[rid]["otomatik_akis"] == r.json()["otomatik_akis"]
    return r.json()["otomatik_akis"]


def test_uctan_uca_qa_to_do_tetik_on_inceleme_po_onayi_otomatik_case(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira, po: PoActions
) -> None:
    """Story QA To Do'ya girer → tetik → ön inceleme → PO onayı (jira-sim etiketi) → otomatik
    case işi → case'ler oluşur; gereksinim rozeti her adımda doğru."""
    login(api, make_user("tester"))
    _taban(engine)
    _tasi(jira, "TPD-4")
    jira_tetik.tur(engine)
    rid = str(_req("TPD-4").id)
    a = _akis(api, rid)
    assert a["durum"] == "suruyor" and a["tetik_zamani"] and a["neden"] == "Ön inceleme sürüyor"
    run_jobs(engine)
    assert _akis(api, rid) == {**a, "neden": "PO onayı bekleniyor"}
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][rid] == "onaylandi"
    assert _akis(api, rid) == {**a, "neden": "Otomatik case üretimi kuyrukta"}
    [is_] = _isler(engine, jira_tetik.JOB_OTOMATIK_CASE)
    assert is_.yuk["requirement_id"] == rid and is_.durum == "queued"
    run_jobs(engine)
    [is_] = _isler(engine, jira_tetik.JOB_OTOMATIK_CASE)
    assert is_.durum == "done" and is_.sonuc["durum"] == "baslatildi", is_.sonuc
    assert _req("TPD-4").durum == "cases_ready"
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM test_case WHERE requirement_id = :r AND durum = 'draft'"),
            {"r": rid},
        ).scalar_one()
    assert n > 0
    assert _akis(api, rid)["durum"] == "tamam"
    [d] = _denetim(engine, "requirements.otomatik_case")
    assert d.ozet["sonuc"] == "baslatildi" and d.aktor == "jira-tetik"
    from tp_core.features.cases.service import WORKFLOW_TUR

    with engine.connect() as c:
        baslatan = c.execute(
            text("SELECT baslatan FROM workflow_instance WHERE nesne_id = :r AND tur = :t"),
            {"r": rid, "t": WORKFLOW_TUR},
        ).scalar_one()
    assert baslatan == "otomasyon"


def test_icerik_degisip_newe_donen_tetikli_story_yeniden_incelenir(
    engine: Engine, jira: RestJira, po: PoActions
) -> None:
    rid = _tetikle_ve_po_onayla(engine, jira, po)
    run_jobs(engine)
    assert _req("TPD-4").durum == "cases_ready"
    assert jira_tetik.tur(engine)["tetiklenen"] == 0  # içerik aynı: yazma yok
    po.set_description("TPD-4", "Yeni açıklama", ["AC1: yeni koşul"])
    ozet = jira_tetik.tur(engine)
    assert _sonuc(ozet, "TPD-4")["sonuc"] == "yeniden_tetiklendi" and ozet["tetiklenen"] == 1
    req = _req("TPD-4")
    assert req.durum == "in_review" and str(req.id) == rid
    assert _sonuc(jira_tetik.tur(engine), "TPD-4")["sonuc"] == "durumda"  # çift tetik yok
    sonuclar = [d.ozet["sonuc"] for d in _denetim(engine, "requirements.jira_tetik")]
    assert sonuclar == ["tetiklendi", "yeniden_tetiklendi"]


def test_po_onayli_casesiz_story_girince_case_uretimi_hemen_baslar(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira, po: PoActions
) -> None:
    _taban(engine)
    login(api, make_user("analyst"))
    api.post("/requirements/sync")
    req = _req("TPD-4")
    assert api.post(f"/requirements/{req.id}/review").status_code == 202
    run_jobs(engine)
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][str(req.id)] == "onaylandi"
    assert _req("TPD-4").durum == "po_approved" and _req("TPD-4").qa_tetik_zamani is None
    assert _isler(engine, jira_tetik.JOB_OTOMATIK_CASE) == []  # elle akış: otomatik case yok

    _tasi(jira, "TPD-4")
    ozet = jira_tetik.tur(engine)
    assert _sonuc(ozet, "TPD-4")["sonuc"] == "case_uretimi" and ozet["tetiklenen"] == 1
    [is_] = _isler(engine, jira_tetik.JOB_OTOMATIK_CASE)
    assert is_.yuk["tetik_zamani"]
    # Mimar #3 / PO #4: kuyruktaki iş bu akışın işi sayılır; rozet "durdu" demez.
    a = _akis(api, str(req.id))
    assert a["durum"] == "suruyor" and a["neden"] == "Otomatik case üretimi kuyrukta", a
    run_jobs(engine)
    assert _req("TPD-4").durum == "cases_ready"
    # Etkin case'i olan story yeniden girerse dokunulmaz; neden kalıcı (denetim + API).
    _tasi(jira, "TPD-4", "To Do")
    jira_tetik.tur(engine)
    _tasi(jira, "TPD-4")
    assert _sonuc(jira_tetik.tur(engine), "TPD-4")["sonuc"] == "dokunulmadi"
    son = _denetim(engine, "requirements.jira_tetik")[-1].ozet
    assert son["sonuc"] == "dokunulmadi" and son["neden"] == "Gereksinim durumu: cases_ready"
    assert _sonuc(jira_tetik.tur(engine), "TPD-4")["sonuc"] == "durumda"
    g = api.get("/automation/jira-trigger").json()
    [t] = [t for t in g["son_tetiklenenler"] if t["jira_key"] == "TPD-4"]  # story başına tek
    assert t["sonuc"] == "dokunulmadi" and t["neden"] == "Gereksinim durumu: cases_ready"


def test_otomatik_case_kapaliyken_kuyruga_girmez_rozet_durdu(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira, po: PoActions
) -> None:
    _ayar(otomatik_case=False)
    rid = _tetikle_ve_po_onayla(engine, jira, po)
    assert _isler(engine, jira_tetik.JOB_OTOMATIK_CASE) == []
    assert _req("TPD-4").durum == "po_approved"
    login(api, make_user("tester"))
    a = _akis(api, rid)
    assert a["durum"] == "durdu" and "kapalı" in a["neden"]


def test_elle_cekilmis_gereksinimde_otomatik_case_yok(
    api: TestClient, make_user: Any, engine: Engine, po: PoActions
) -> None:
    login(api, make_user("analyst"))
    api.post("/requirements/sync")
    req = _req("TPD-4")
    assert api.post(f"/requirements/{req.id}/review").status_code == 202
    run_jobs(engine)
    assert _req("TPD-4").durum == "pending_po"
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][str(req.id)] == "onaylandi"
    assert _req("TPD-4").qa_tetik_zamani is None
    assert _isler(engine, jira_tetik.JOB_OTOMATIK_CASE) == []
    run_jobs(engine)
    assert _req("TPD-4").durum == "po_approved"  # analist elle başlatır
    assert _akis(api, str(req.id)) is None


def test_kapi_reddederse_denetim_ve_gereksinim_oldugu_gibi(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira, po: PoActions
) -> None:
    rid = _tetikle_ve_po_onayla(engine, jira, po)
    # Onay işten önce Jira'da geri çekildi (poll henüz görmedi): kapı fail-closed reddeder.
    po.remove_label("TPD-4")
    run_jobs(engine)
    [is_] = _isler(engine, jira_tetik.JOB_OTOMATIK_CASE)
    assert is_.durum == "done" and is_.sonuc["durum"] == "reddedildi"
    [d] = _denetim(engine, "requirements.otomatik_case")
    assert d.ozet["sonuc"] == "reddedildi" and d.ozet["neden"]
    assert _req("TPD-4").durum == "po_approved"
    login(api, make_user("tester"))
    a = _akis(api, rid)
    assert a["durum"] == "durdu" and a["neden"].startswith("Case üretimi reddedildi")


def test_gecici_jira_kesintisi_kalici_ret_sayilmaz(
    engine: Engine, jira: RestJira, po: PoActions, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = _tetikle_ve_po_onayla(engine, jira, po)

    def kesik(_req: Any) -> bool:
        raise JiraUnavailable("bağlantı yok")

    monkeypatch.setattr(flow, "po_label_current", kesik)
    yuk = {"requirement_id": rid}
    with pytest.raises(flow.WorkflowError):
        jira_tetik.otomatik_case_baslat(yuk, son_deneme=False)
    assert _denetim(engine, "requirements.otomatik_case") == []
    assert _req("TPD-4").durum == "po_approved"
    # Worker: ilk deneme retry (kalıcı ret yok).
    run_jobs(engine, limit=1)
    [is_] = _isler(engine, jira_tetik.JOB_OTOMATIK_CASE)
    assert is_.durum == "retry", is_
    # Son deneme: reddedildi + denetim.
    assert jira_tetik.otomatik_case_baslat(yuk, son_deneme=True)["durum"] == "reddedildi"
    [d] = _denetim(engine, "requirements.otomatik_case")
    assert d.ozet["sonuc"] == "reddedildi"
    # Jira geri gelince yeniden deneme case üretimini başlatır.
    monkeypatch.undo()
    assert jira_tetik.otomatik_case_baslat(yuk, son_deneme=False)["durum"] == "baslatildi"


def test_savepoint_geri_aliminda_denetim_kaydi_dusurulur(
    engine: Engine, jira: RestJira, po: PoActions, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.cases import service as cases_service

    rid = _tetikle_ve_po_onayla(engine, jira, po)
    asil = cases_service.start_generation

    def yarida(session: Any, requirement_id: Any, user: Any) -> Any:
        from tp_core.audit.session import audit_on_commit

        audit_on_commit(session, "x", "test.geri_alinan", "y", {})
        raise flow.FlowError("kapı kapalı")

    monkeypatch.setattr(cases_service, "start_generation", yarida)
    assert jira_tetik.otomatik_case_baslat({"requirement_id": rid})["durum"] == "reddedildi"
    assert _denetim(engine, "test.geri_alinan") == []
    assert len(_denetim(engine, "requirements.otomatik_case")) == 1
    monkeypatch.setattr(cases_service, "start_generation", asil)


# ------------------------------------------------------------------------ demo kontrolü


def test_demo_jira_status(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.demo import service as demo_service

    _taban(engine)
    login(api, make_user("analyst"))
    assert api.post("/demo/jira-status", json={"jira_key": "TPD-2", "durum": QA}).status_code == 403
    login(api, make_user("presenter"))
    r = api.post("/demo/jira-status", json={"jira_key": "TPD-2", "durum": QA})
    assert r.status_code == 200, r.text
    assert r.json() == {"jira_key": "TPD-2", "onceki": "To Do", "durum": QA, "degisti": True}
    assert jira.get_issue("TPD-2").status == QA
    again = api.post("/demo/jira-status", json={"jira_key": "TPD-2", "durum": "qa to do"})
    assert again.status_code == 200 and again.json()["degisti"] is False
    assert (
        api.post("/demo/jira-status", json={"jira_key": "TPD-2", "durum": "Yok"}).status_code == 409
    )
    assert (
        api.post("/demo/jira-status", json={"jira_key": "TPD-999", "durum": QA}).status_code == 404
    )
    assert api.post("/demo/jira-status", json={"jira_key": "x y", "durum": QA}).status_code == 404
    [d] = _denetim(engine, "demo.jira_status")
    assert d.nesne == "jira:TPD-2" and d.ozet == {"onceki": "To Do", "durum": QA}
    # Tetik onu çeker.
    assert jira_tetik.tur(engine)["tetiklenenler"] == ["TPD-2"]

    # Sim host adı ama uç kendini jira-sim olarak tanıtmıyor (tünel/proxy): 409.
    monkeypatch.setattr(jira, "simulator_mu", lambda: False)
    r = api.post("/demo/jira-status", json={"jira_key": "TPD-1", "durum": QA})
    assert r.status_code == 409 and "jira-sim" in r.json()["detail"]
    monkeypatch.undo()
    assert jira.simulator_mu() is True

    # Gerçek Jira: istek gönderilmeden 409.
    monkeypatch.setattr(demo_service, "_jira_sim_mi", lambda: False)
    r = api.post("/demo/jira-status", json={"jira_key": "TPD-1", "durum": QA})
    assert r.status_code == 409 and "jira-sim" in r.json()["detail"]
    assert jira.get_issue("TPD-1").status == "To Do"


# ------------------------------------------------- sim önbelleği, K23 demo ortamı, ortam


def test_sim_onbellegi_olumsuz_sonucu_kisa_tutar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend #3a: hata/olumsuz doğrulama `SIM_NEGATIF_S`, olumlu `SIM_ONBELLEK_S` tutulur."""
    saat = [1000.0]
    monkeypatch.setattr(ayarlar.time, "monotonic", lambda: saat[0])
    sonuc = [False]
    cagri: list[int] = []

    def dogrula() -> bool:
        cagri.append(1)
        if sonuc[0] is None:
            raise RuntimeError("ağ yok")
        return sonuc[0]

    monkeypatch.setattr(ayarlar, "_sim_dogrula", dogrula)
    ayarlar.sim_onbellegini_temizle()
    try:
        assert ayarlar.jira_sim_mi() is False
        saat[0] += ayarlar.SIM_NEGATIF_S - 1
        assert ayarlar.jira_sim_mi() is False and len(cagri) == 1
        sonuc[0] = True
        saat[0] += 2  # olumsuz sonuç süresi doldu: yeniden doğrulanır
        assert ayarlar.jira_sim_mi() is True and len(cagri) == 2
        sonuc[0] = None
        saat[0] += ayarlar.SIM_ONBELLEK_S - 1
        assert ayarlar.jira_sim_mi() is True and len(cagri) == 2
        saat[0] += 2
        assert ayarlar.jira_sim_mi() is False and len(cagri) == 3  # hata → kısa olumsuz
    finally:
        ayarlar.sim_onbellegini_temizle()


def _model_kipi_kaydi(engine: Engine, mod: str) -> None:
    from tp_core.audit import append_audit

    with engine.begin() as c:
        append_audit(c, "system", "worker.model_mode", "core-worker", {"mod": mod})


def test_k23_gercek_ortamda_seed_ve_reset_otomatik_koda_dokunmaz(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.demo import service as demo_service
    from tp_core.seed import seed_otomasyon_demo

    monkeypatch.setattr(ayarlar, "jira_sim_mi", lambda: False)
    _model_kipi_kaydi(engine, "live")
    assert seed_otomasyon_demo() == {"otomatik_kod_uretimi": "gercek_ortam"}
    assert demo_service._otomasyon_demo_ayarlari() == {"otomatik_kod_uretimi": "gercek_ortam"}
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM otomasyon_ayari")).scalar_one() == 0
    assert _denetim(engine, "otomasyon.ayar") == []
    # Gerçek Jira ama model kipi REPLAY (worker bildirimi): demo ortamı → kapatılır.
    _model_kipi_kaydi(engine, "replay")
    assert seed_otomasyon_demo() == {"otomatik_kod_uretimi": "yazildi"}
    with new_session() as s:
        assert ayarlar.otomatik_kod(s).acik is False


def test_model_kipi_worker_bildiriminden_yoksa_acik_yapilandirmadan(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.config import get_settings
    from tp_core.features.demo.service import MODEL_DURUMU_EYLEM

    assert ayarlar._MODEL_KIPI_EYLEMI == MODEL_DURUMU_EYLEM
    monkeypatch.setattr(get_settings(), "model_mode", "auto")
    with new_session() as s:
        assert ayarlar.model_kipi(s) is None  # auto core-api'de çözülemez
    monkeypatch.setattr(get_settings(), "model_mode", "replay")
    with new_session() as s:
        assert ayarlar.model_kipi(s) == "replay"
    _model_kipi_kaydi(engine, "live")
    with new_session() as s:
        assert ayarlar.model_kipi(s) == "live"  # worker bildirimi önce gelir


def test_ayar_ucu_ortam_bilgisi_doner(
    api: TestClient, engine: Engine, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K23: `GET /automation-settings` → `ortam` (portalın REPLAY uyarısı); ayar değildir."""
    login(api, make_user("tester"))
    _model_kipi_kaydi(engine, "replay")
    g = api.get("/automation-settings").json()
    assert g["replay"] is True and g["model_kipi"] == "replay"
    assert g["ortam"] == {
        "model_kipi": "replay", "replay": True, "jira_sim": True, "demo_ortami": True
    }  # fmt: skip
    _model_kipi_kaydi(engine, "live")
    monkeypatch.setattr(ayarlar, "jira_sim_mi", lambda: False)
    g = api.get("/automation-settings").json()
    assert g["replay"] is False and g["model_kipi"] == "live"
    assert g["ortam"] == {
        "model_kipi": "live", "replay": False, "jira_sim": False, "demo_ortami": False
    }  # fmt: skip
    login(api, make_user("engineer"))
    assert api.put("/automation-settings/ortam", json={"replay": False}).status_code == 404


def test_gereksinim_ozeti_jira_durumunu_tasir(
    engine: Engine, jira: RestJira, api: TestClient, make_user
) -> None:
    """QA #4 / frontend #5: `GET /requirements` öğesi `jira_durumu` taşır (portal demo ipucu)."""
    _tasi(jira, "TPD-4")
    _taban(engine)
    login(api, make_user("analyst"))
    g = {r["jira_key"]: r for r in api.get("/requirements").json()}
    assert g["TPD-4"]["jira_durumu"] == QA
    assert all("jira_durumu" in r for r in g.values())
