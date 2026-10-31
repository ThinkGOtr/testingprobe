"""Faz 3 inceleme düzeltmeleri (codegen): uygulama görüldü mü (MCP hataları), onay yeniden denetimi,
GitHub PR senkronu, kırarak doğrulama koşuları, yerel kontrol bağı, idempotent merge, saklama.

Gerçek Postgres + LocalForge + REPLAY golden'ları + sahte MCP/toolchain (conftest).
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text

from tests.unit.features.codegen.conftest import gecti, kirmizi
from tests.unit.features.codegen.test_browser import FakeSession
from tests.unit.features.codegen.test_flow import github_kipi, script_of, uret
from tp_core.features.codegen import service
from tp_core.features.codegen.browser import AracSonucu
from tp_core.models import PullRequest, Requirement, Review, Script, session_scope
from tp_core.models.codegen_feature import ScriptAdim, ScriptKontrol
from tp_core.workflow.service import Principal, WorkflowError, transition

from .conftest import run_jobs

ASSERT_C3 = (
    "Error: expect(locator).toHaveText(expected) failed\n\n"
    'Locator: getByTestId(\'cart-line-free-P-001\')\nExpected: "1"\nReceived: "0"'
)


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Principal:
    u = make_user("engineer")
    from .conftest import login

    login(api, u)
    return u


def _tarayici(codegen: Any, hata: Any) -> None:
    def browser() -> FakeSession:
        s = FakeSession(hata=hata)
        codegen.oturumlar.append(s)
        return s

    service.set_factories(
        gateway=service._factories["gateway"],
        browser=browser,
        toolchain=service._factories["toolchain"],
        forge=service._factories["forge"],
    )


def _story_degistir(rid: uuid.UUID) -> None:
    with session_scope() as s:
        req = s.get(Requirement, rid)
        req.aciklama = (req.aciklama or "") + " (Jira'da değişti)"


def _pr_ac(api: TestClient, engine: Engine, cid: uuid.UUID) -> tuple[Script, Any]:
    sid = uret(api, [cid])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "pr_open", cg.engel_nedeni
    return sc, cg


# ------------------------------------------- Constitution V: ajan uygulamayı gördü mü


def test_uygulama_goruldu_mu_yapilandirilmis_sonuctan() -> None:
    ok = AracSonucu("browser_click", True)
    kotu = AracSonucu("browser_click", False, "does not match any elements")
    f = service._uygulama_goruldu_mu
    assert f("replay", []) is not None
    assert f("replay", [(1, "browser_click", True, kotu)])[0] == "environment"
    engel = f("replay", [(1, "browser_navigate", True, ok), (2, "browser_click", True, kotu)])
    assert engel is not None and engel[0] == "unverified_step" and "Adım 2" in engel[1]
    assert f("replay", [(1, "browser_navigate", True, ok), (2, "browser_click", True, None)])
    assert f("replay", [(1, "browser_navigate", True, ok)]) is None
    # Canlı: model hatayı görüp toparlanabilir; ama başarılı bir eylem şart.
    assert f("live", [(1, "browser_click", True, kotu), (2, "browser_click", True, ok)]) is None
    assert f("live", [(1, "browser_snapshot", True, ok)])[0] == "unverified_step"


def test_replay_her_mcp_cagrisi_hata_donerse_pr_acilmaz(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    _tarayici(codegen, lambda _ad: True)
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "failed" and cg.engel_turu == "environment", cg.engel_nedeni
    assert sc.icerik is None and sc.pr_no is None and codegen.toolchain.checks() == []
    with session_scope() as s:
        adimlar = s.scalars(select(ScriptAdim).where(ScriptAdim.script_id == sc.id)).all()
    assert adimlar and all(a.hata for a in adimlar)
    assert all("başarısız" in a.ozet for a in adimlar)


def test_replay_tek_eylem_hatasi_kayitli_dogrulamayi_gecersiz_kilar(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    _tarayici(codegen, lambda ad: ad == "browser_click")
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "unverified_step", cg.engel_nedeni
    assert "tekrarlanamadı" in cg.engel_nedeni and "browser_click" in cg.engel_nedeni
    assert sc.pr_no is None and codegen.toolchain.checks() == []


# ------------------------------------------ Constitution I: onay PR/merge anında da


def test_story_uretim_sirasinda_degisirse_pr_acilmaz(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    def kontrol_sirasinda_degistir(_body: dict[str, Any]) -> dict[str, Any]:
        _story_degistir(hazir["requirement_id"])
        return gecti()

    codegen.toolchain.kontroller.append(kontrol_sirasinda_degistir)
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "case_changed"
    assert "PR açılmadı" in cg.engel_nedeni and "PO onayı" in cg.engel_nedeni
    assert sc.pr_no is None and codegen.forge.find_open_pr(sc.branch) is None
    assert codegen.ci == []


def test_merge_isteginde_ve_merge_isinde_onay_yeniden_denetlenir(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sc, _ = _pr_ac(api, engine, hazir["cases"][2])
    # Merge kararı verildi, iş kuyrukta; story değişti → iş merge etmez, denetime yazar.
    with session_scope() as s:
        service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha, "kabul")
    _story_degistir(hazir["requirement_id"])
    run_jobs(engine)
    sc2, _ = script_of(sc.id)
    assert sc2.durum == "pr_open"
    assert codegen.forge.get_pr(sc.pr_no).state == "open"
    with session_scope() as s:
        ret = s.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'codegen.merge_refused'")
        ).scalar_one()
    assert ret["engel"] == "case_changed"
    # Yeni merge isteği de reddedilir (409).
    with pytest.raises(WorkflowError, match="PO onayı"), session_scope() as s:
        service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha, "kabul")


# ------------------------------------------------- idempotent merge (paralel istek)


def test_ayni_head_icin_ikinci_merge_istegi_ayni_isi_doner(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sc, _ = _pr_ac(api, engine, hazir["cases"][2])
    with session_scope() as s:
        j1 = service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha, "kabul")
    with session_scope() as s:
        j2 = service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha, "kabul")
    assert j1 == j2
    run_jobs(engine)
    assert script_of(sc.id)[0].durum == "merged"
    with session_scope() as s:  # merge bittikten sonra aynı istek: hata değil, aynı iş
        j3 = service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha, "kabul")
        merge_onaylari = s.scalar(
            select(func.count())
            .select_from(Review)
            .where(Review.nesne_id == sc.id, Review.karar == "merge")
        )
    assert j3 == j1 and merge_onaylari == 1


# ---------------------------------------- kırarak doğrulama: 3 koşu, run kaydı, keep


def test_kirarak_dogrulama_kendi_baslangicini_kosar_ve_kosulari_kaydeder(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sc, cg = _pr_ac(api, engine, hazir["cases"][2])
    yerel = dict(cg.yerel_kontrol)
    assert yerel["tur"] == "local_check" and yerel["tekrar"] == 3
    codegen.toolchain.kirik.append(kirmizi(ASSERT_C3, "assertion", n=1))
    once = len(codegen.toolchain.checks())
    assert api.post(f"/scripts/{sc.id}/break-verify").status_code == 202
    run_jobs(engine)
    sc, cg = script_of(sc.id)
    assert cg.break_durum == "passed"
    istekler = codegen.toolchain.checks()[once:]
    # Bayraksız başlangıç bu doğrulamada koşar (önceki yerel kontrolden ödünç alınmaz).
    assert [i["env"] for i in istekler] == [{}, {"BREAK_CAMPAIGN": "1"}, {}]
    assert all(i["keep"] is True and i["repeat_each"] == 1 for i in istekler)
    assert all(i["keep"] is True for i in codegen.toolchain.checks())
    # "Yerel kontrol" kartı hâlâ repeat-each=3'lük local_check'e bağlı.
    assert (
        cg.yerel_kontrol["tur"] == "local_check" and cg.yerel_kontrol["run_id"] == yerel["run_id"]
    )
    with session_scope() as s:
        kontroller = s.scalars(
            select(ScriptKontrol)
            .where(ScriptKontrol.script_id == sc.id)
            .order_by(ScriptKontrol.zaman)
        ).all()
        turler = [(k.tur, k.sinif) for k in kontroller]
        run_ler = {
            r.id: r
            for r in s.execute(
                text("SELECT id, tetik, ortam, script_id FROM run WHERE script_id = :s"),
                {"s": sc.id},
            )
        }
    assert turler == [
        ("local_check", "gecti"),
        ("break_baseline", "gecti"),
        # Kasıtlı kırmızı defect adayı değildir.
        ("break_red", "kirma_beklenen_kirmizi"),
        ("break_green", "gecti"),
    ]
    # Her kontrol bir `run` satırıdır (portal /kosular/<uuid> bağlantısı çalışır).
    assert all(k.run_id is not None for k in kontroller)
    assert {str(k.run_id) for k in kontroller} == {str(i) for i in run_ler}
    tetikler = sorted(r.tetik for r in run_ler.values())
    assert tetikler == ["break_verify"] * 3 + ["local_check"]
    asamalar = {a["ad"]: a for a in sc.kirma_dogrulama["asamalar"]}
    kirik = run_ler[uuid.UUID(str(asamalar["broken"]["run_id"]))]
    assert kirik.ortam["break_campaign"] is True and asamalar["broken"]["sonuc"] == "failed"
    d = api.get(f"/scripts/{sc.id}").json()
    red = next(k for k in d["kontroller"] if k["tur"] == "break_red")
    assert red["sinif"] == "kirma_beklenen_kirmizi" and "Beklenen kırmızı" in red["aciklama"]
    assert api.get(f"/runs/{asamalar['broken']['run_id']}").status_code == 200


# ------------------------------------------------- defect adayı: hangi doğrulama


def test_defect_adayi_hangi_dogrulamanin_kaldigini_ve_tekrari_soyler(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    codegen.toolchain.kontroller.append(kirmizi(ASSERT_C3, "assertion"))
    sid = uret(api, [hazir["cases"][3]])["script_ids"][0]  # 6 adet sınırı
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "defect_candidate"
    assert 'CartPage.expectFreeQuantity("P-001", 1)' in cg.engel_nedeni
    assert "(3/3 tekrar)" in cg.engel_nedeni
    d = api.get(f"/scripts/{sid}").json()
    (h,) = d["yerel_kontrol"]["basarisiz"]  # üç tekrar tek satır
    assert h["tekrar"] == 3 and h["eslesme"] == 'CartPage.expectFreeQuantity("P-001", 1)'
    assert h["kaynak_metin"]


# --------------------------------------------------- yerel forge'da /check 404


def test_yerel_forgeda_check_404_kontrolu_atlamaz(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    codegen.toolchain.check_status = 404
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "failed" and cg.engel_turu == "environment"
    assert cg.yerel_kontrol["atlandi"] is False and sc.pass_at_1 is None
    assert sc.pr_no is None and codegen.forge.find_open_pr(sc.branch) is None


# ------------------------------------------------ yeniden üretim: yeni dal, eski PR


def test_yeniden_uretim_yeni_dal_ve_eski_yerel_pr_kapanir(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    cid = hazir["cases"][2]
    sc, _ = _pr_ac(api, engine, cid)
    with session_scope() as s:
        transition(s, s.get(Script, sc.id), "closed", "test", "pr_open")
    yeni, _ = _pr_ac(api, engine, cid)
    assert yeni.branch == f"{sc.branch}-2" and yeni.pr_no != sc.pr_no
    main = codegen.forge.head_sha("main")
    with session_scope() as s:
        _, ycg = s.get(Script, yeni.id), service._yukle(s, yeni.id)[1]
        assert ycg.symbols_sha == main
        assert s.get(PullRequest, sc.pr_no).durum == "closed"
    assert codegen.forge.get_pr(sc.pr_no).state == "closed"
    assert codegen.forge.get_pr(yeni.pr_no).state == "open"


# ------------------------------------------- GitHub kipi: arayüzde yapılan merge


def test_github_arayuzu_merge_ve_kapatma_cekirdege_islenir(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = github_kipi(codegen, monkeypatch)
    s1 = uret(api, [hazir["cases"][2]])["script_ids"][0]
    s2 = uret(api, [hazir["cases"][1]])["script_ids"][0]
    run_jobs(engine)
    sc1, _ = script_of(s1)
    sc2, _ = script_of(s2)
    assert sc1.durum == sc2.durum == "pr_open"
    gh.prs[sc1.pr_no] = gh.prs[sc1.pr_no].model_copy(update={"state": "merged"})
    gh.prs[sc2.pr_no] = gh.prs[sc2.pr_no].model_copy(update={"state": "closed"})
    once = len(codegen.ci)
    sonuc = service.sync_prs(engine, gh)
    assert {k: sonuc[k] for k in ("bakilan", "merged", "closed", "hata")} == {
        "bakilan": 2, "merged": 1, "closed": 1, "hata": 0,
    }  # fmt: skip
    sc1, _ = script_of(s1)
    sc2, _ = script_of(s2)
    assert sc1.durum == "merged" and sc1.insan_review_sonucu == "kabul"
    assert sc2.durum == "closed"
    assert codegen.ci[once:] == [{"sha": None, "trigger": "push", "pr_number": None}]
    with session_scope() as s:
        assert s.get(PullRequest, sc1.pr_no).durum == "merged"
        assert s.get(PullRequest, sc2.pr_no).durum == "closed"
        # GitHub'daki insan merge'i dış onay olarak kayıtlı (portal kullanıcısı değil).
        rv = s.scalars(select(Review).where(Review.nesne_id == sc1.id)).one()
        assert rv.karar == "merge" and rv.user_id is None and rv.harici_onaylayan == "github"
        assert rv.kanal == "github"  # 0010: GitHub arayüzü kanalı (portal değil)
        eylem = s.execute(
            text("SELECT aktor FROM audit_event WHERE eylem = 'codegen.merged' AND nesne = :n"),
            {"n": f"script:{sc1.id}"},
        ).scalar_one()
    assert eylem == "github"
    assert service.sync_prs(engine, gh)["bakilan"] == 0  # idempotent


def test_pr_senkronu_yalniz_github_kipinde_planlanir(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.config import get_settings

    monkeypatch.setenv("TP_FORGE", "local")
    get_settings.cache_clear()
    with engine.begin() as conn:
        assert service.plan_pr_sync(conn) is None
    monkeypatch.setenv("TP_FORGE", "github")
    get_settings.cache_clear()
    try:
        with engine.begin() as conn:
            j1 = service.plan_pr_sync(conn)
            j2 = service.plan_pr_sync(conn)
        assert j1 is not None and j1 == j2  # aynı zaman dilimi tek iş
    finally:
        get_settings.cache_clear()


# ------------------------------------------------------ ekran görüntüsü saklama


def test_ekran_goruntusu_saklama(engine: Engine, tmp_path: Any) -> None:
    with session_scope() as s:
        kapali = Script(tur="test", dosya_yolu="e2e/tests/generated/a.spec.ts")
        acik = Script(tur="test", dosya_yolu="e2e/tests/generated/b.spec.ts")
        s.add_all([kapali, acik])
        s.flush()
        s.execute(text("UPDATE script SET durum = 'closed' WHERE id = :k"), {"k": kapali.id})
        s.execute(text("UPDATE script SET durum = 'pr_open' WHERE id = :a"), {"a": acik.id})
        ids = (kapali.id, acik.id)
    kok = tmp_path / "codegen"
    dizinler = {
        "kapali": kok / str(ids[0]),
        "acik": kok / str(ids[1]),
        "yetim": kok / str(uuid.uuid4()),
        "yeni_yetim": kok / str(uuid.uuid4()),
    }
    eski = time.time() - 30 * 86400
    for ad, d in dizinler.items():
        d.mkdir(parents=True)
        (d / "step-1.png").write_bytes(b"\x89PNG")
        if ad != "yeni_yetim":
            os.utime(d, (eski, eski))
    with session_scope() as s:
        assert service.prune_screenshots(s, tmp_path, gun=14) == 2
    assert not dizinler["kapali"].exists() and not dizinler["yetim"].exists()
    assert dizinler["acik"].exists() and dizinler["yeni_yetim"].exists()


# ---------------------------------------------- ajan adımları: insan özeti, gizli


def test_ajan_adimlari_insan_ozeti_ve_parola_gizli(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sc, _ = _pr_ac(api, engine, hazir["cases"][2])
    with session_scope() as s:
        adimlar = s.scalars(
            select(ScriptAdim).where(ScriptAdim.script_id == sc.id).order_by(ScriptAdim.sira)
        ).all()
        for a in adimlar:
            for metin in (a.ozet, a.ham):
                assert "Demo123!" not in metin
                assert "<untrusted" not in metin and "```" not in metin and "tmp/" not in metin
        assert adimlar[0].ozet == "Sayfa açıldı: /giris"
    d = api.get(f"/scripts/{sc.id}").json()
    assert "Demo123!" not in str(d["adimlar"])
    login_satiri = next(m for m in d["eslemeler"] if m["method"] == "login")
    assert "ajan bayisi bayi3" in login_satiri["dogrulama_notu"]


def test_ham_cikti_kirpilmis_sarmal_etiketini_birakmaz() -> None:
    """Geçidin kırptığı özetin sonunda yarım `</untrusted …` kalırsa ham çıktıda görünmez."""
    from tp_core.features.codegen.ozet import ham_cikti

    kirpik = (
        '<untrusted id="87520">### Page - Page URL: /giris - New console entries: '
        '</untrusted id="87520…'
    )
    temiz = ham_cikti(kirpik)
    assert "untrusted" not in temiz and temiz.endswith("New console entries:")
    assert ham_cikti("a <b>kalın</b> ve sonra") == "a <b>kalın</b> ve sonra"
