"""GitHub kipi PR senkronu: locator onarım PR'ları (Faz 4 inceleme düzeltmesi) + REPLAY ön kontrolü.

- Onarım PR'ı (`tur='locator_fix'`, `ScriptCodegen` satırı yok) GitHub arayüzünde merge/kapatılınca
  `sync_prs` çökmez; onarım semantiğiyle işlenir (dış review, hata + kardeşleri `oneri_durumu`,
  `repair.merged`, push CI). Aynı geçişteki codegen PR'ları da işlenir.
- Bozuk tek satır senkronu durdurmaz (`hata` sayılır, `codegen.pr_sync_failed` denetimi).
- REPLAY kipinde main temel durumda değilse (`cart-add`) `/code/generate` erkenden, yapılacak işi
  söyleyerek reddeder.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.codegen.test_flow import github_kipi, script_of, uret
from tp_core.features.codegen import service
from tp_core.models import Failure, PullRequest, Review, Run, Script, TestResult, session_scope
from tp_core.ports import PullRequest as PortPR
from tp_core.workflow.service import Principal

from .conftest import run_jobs

ONERI = {"locator_key": "catalog.addToCart", "old_testid": "add-to-cart", "new_testid": "cart-add"}


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Principal:
    u = make_user("engineer")
    from .conftest import login

    login(api, u)
    return u


def _failure_ek_var() -> bool:
    with session_scope() as s:
        return bool(s.execute(text("SELECT to_regclass('failure_ek') IS NOT NULL")).scalar())


def _hata(s: Any, rid: uuid.UUID, ad: str) -> uuid.UUID:
    fid = uuid.uuid4()
    tr = TestResult(id=uuid.uuid4(), run_id=rid, test_adi=ad, dosya="tests/cart.spec.ts",
                    sonuc="failed", tetik="push", kaynak="local",
                    hata_mesaji="getByTestId('add-to-cart'): 0 eleman")  # fmt: skip
    s.add(tr)
    s.flush()
    s.add(Failure(id=fid, run_id=rid, test_result_id=tr.id, test_adi=ad,
                  hata_imzasi=f"locator:{ad}", sinif="test_maintenance", alt_tur="locator",
                  eslesen_sinyaller=[], karar_kaynagi="rule", oneri_turu="locator_fix",
                  oneri_durumu="pr_open"))  # fmt: skip
    s.flush()
    if _failure_ek_var():
        s.execute(
            text(
                "INSERT INTO failure_ek (project_id, failure_id, anahtar, oneri) "
                "VALUES ((SELECT project_id FROM failure WHERE id = :f), :f, :a, "
                "CAST(:o AS jsonb))"
            ),
            {"f": fid, "a": f"{rid}:{ad}", "o": json.dumps(ONERI)},
        )
    return fid


def onarim_pr(gh: Any, no: int) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """`pr_open` durumda locator onarım script'i + hata + kardeşi + sahte GitHub PR'ı."""
    rid = uuid.uuid4()
    head = uuid.uuid4().hex
    dal = f"tp/repair/{uuid.uuid4()}"
    with session_scope() as s:
        s.add(Run(id=rid, commit="c" * 40, kaynak="local", tetik="push", sonuc="failed",
                  ortam={"saglik": {"ok": True}}))  # fmt: skip
        s.flush()
        fid = _hata(s, rid, "Sepet › kampanya 7 adet")
        kid = _hata(s, rid, "Sepet › AC1")
        sc = Script(tur="locator_fix", dosya_yolu="e2e/pages/catalog/locators.ts", branch=dal,
                    failure_id=fid, icerik="testId: 'cart-add'")  # fmt: skip
        s.add(sc)
        s.flush()
        s.execute(
            text("UPDATE script SET durum = 'pr_open', pr_no = :n, head_sha = :h WHERE id = :i"),
            {"n": no, "h": head, "i": sc.id},
        )
        s.add(PullRequest(number=no, branch=dal, baslik="Locator onarımı", head_sha=head,
                          acan="tp-bot"))  # fmt: skip
        sid = sc.id
    gh.branches[dal] = head
    gh.prs[no] = PortPR(number=no, branch=dal, title="Locator onarımı", body="", head_sha=head,
                        url=f"https://github.com/acme/demo-app/pull/{no}", labels=[])  # fmt: skip
    return sid, fid, kid


def _durum(gh: Any, no: int, state: str) -> None:
    gh.prs[no] = gh.prs[no].model_copy(update={"state": state})


def test_github_arayuzunde_merge_edilen_onarim_pr_i_onarim_semantigiyle_islenir(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = github_kipi(codegen, monkeypatch)
    s1 = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc1, _ = script_of(s1)
    assert sc1.durum == "pr_open"
    rsid, fid, kid = onarim_pr(gh, 9999)
    _durum(gh, sc1.pr_no, "merged")
    _durum(gh, 9999, "merged")
    once = len(codegen.ci)

    sonuc = service.sync_prs(engine, gh)

    assert {k: sonuc[k] for k in ("bakilan", "merged", "closed", "hata")} == {
        "bakilan": 2, "merged": 2, "closed": 0, "hata": 0,
    }  # fmt: skip
    # Aynı geçişteki codegen PR'ı da işlendi.
    assert script_of(s1)[0].durum == "merged"
    # İki merge → iki push CI.
    assert codegen.ci[once:] == [{"sha": None, "trigger": "push", "pr_number": None}] * 2
    with session_scope() as s:
        rsc = s.get(Script, rsid)
        assert rsc.durum == "merged" and rsc.insan_review_sonucu == "kabul"
        assert s.get(PullRequest, PullRequest.anahtar(9999)).durum == "merged"
        assert s.get(PullRequest, PullRequest.anahtar(9999)).merge_eden == "github"
        rv = s.scalars(select(Review).where(Review.nesne_id == rsid)).one()
        assert rv.karar == "merge" and rv.user_id is None
        assert rv.harici_onaylayan == "github" and rv.kanal == "github"
        assert s.get(Failure, fid).oneri_durumu == "merged"
        if _failure_ek_var():
            assert s.get(Failure, kid).oneri_durumu == "merged"  # kardeş de kapandı
        eylemler = (
            s.execute(
                text("SELECT eylem FROM audit_event WHERE nesne = :n ORDER BY id"),
                {"n": f"script:{rsid}"},
            )
            .scalars()
            .all()
        )
    assert "repair.merged" in eylemler and "codegen.merged" not in eylemler
    assert service.sync_prs(engine, gh)["bakilan"] == 0  # idempotent


def test_github_arayuzunde_kapatilan_onarim_pr_i_reddedildi_olur(
    engine: Engine, codegen: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = github_kipi(codegen, monkeypatch)
    rsid, fid, kid = onarim_pr(gh, 9998)
    _durum(gh, 9998, "closed")
    once = len(codegen.ci)
    sonuc = service.sync_prs(engine, gh)
    assert (sonuc["closed"], sonuc["hata"]) == (1, 0)
    assert codegen.ci[once:] == []
    with session_scope() as s:
        assert s.get(Script, rsid).durum == "closed"
        assert s.get(PullRequest, PullRequest.anahtar(9998)).durum == "closed"
        assert s.get(Failure, fid).oneri_durumu == "rejected"
        if _failure_ek_var():
            assert s.get(Failure, kid).oneri_durumu == "rejected"
        assert s.execute(
            text("SELECT count(*) FROM audit_event WHERE eylem = 'repair.pr_closed_external' "
                 "AND nesne = :n"), {"n": f"script:{rsid}"},
        ).scalar_one() == 1  # fmt: skip
    # Kapatılan onarım PR'ı eski-PR senkronuna (codegen semantiği) girmez.
    assert service.sync_prs(engine, gh)["eski_bakilan"] == 0


def test_bozuk_satir_senkronu_durdurmaz(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = github_kipi(codegen, monkeypatch)
    s1 = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc1, _ = script_of(s1)
    # `ScriptCodegen` satırı olmayan bir test script'i (bozuk satır) — merge edilmiş PR'ı var.
    bozuk_sid, _, _ = onarim_pr(gh, 9997)
    with session_scope() as s:
        s.execute(text("UPDATE script SET tur = 'test' WHERE id = :i"), {"i": bozuk_sid})
    _durum(gh, 9997, "merged")
    _durum(gh, sc1.pr_no, "merged")
    sonuc = service.sync_prs(engine, gh)
    assert (sonuc["bakilan"], sonuc["merged"], sonuc["hata"]) == (2, 1, 1)
    assert script_of(s1)[0].durum == "merged"
    with session_scope() as s:
        assert s.execute(
            text("SELECT count(*) FROM audit_event WHERE eylem = 'codegen.pr_sync_failed' "
                 "AND nesne = :n"), {"n": f"script:{bozuk_sid}"},
        ).scalar_one() == 1  # fmt: skip


# ------------------------------------------------- REPLAY: main temel durumda mı?


def test_replay_main_temel_durumda_degilse_uretim_erkenden_reddedilir(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tp_core.features.codegen.service as svc
    import tp_core.integrations.forge_demo as fd

    monkeypatch.setattr(svc, "beklenen_uretim_modu", lambda: "replay")
    monkeypatch.setattr(fd, "testid_state", lambda _forge, _ref="main": "cart-add")
    r = api.post("/code/generate", json={"case_ids": [str(hazir["cases"][2])]})
    assert 400 <= r.status_code < 500, r.text
    assert "make demo-baseline" in r.text and "cart-add" in r.text
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM script WHERE tur = 'test'")).scalar_one() == 0

    # Temel durumda (ya da canlı kipte) engel yok.
    monkeypatch.setattr(fd, "testid_state", lambda _forge, _ref="main": "add-to-cart")
    assert service.replay_temel_durum_engeli() is None
    monkeypatch.setattr(fd, "testid_state", lambda _forge, _ref="main": "cart-add")
    monkeypatch.setattr(svc, "beklenen_uretim_modu", lambda: "live")
    assert service.replay_temel_durum_engeli() is None


def test_replay_on_kontrol_forge_okunamazsa_engellemez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tp_core.features.codegen.service as svc
    import tp_core.integrations.forge_demo as fd

    def patla(_forge: Any, _ref: str = "main") -> str:
        raise RuntimeError("forge yok")

    monkeypatch.setattr(svc, "beklenen_uretim_modu", lambda: "replay")
    monkeypatch.setattr(fd, "testid_state", patla)
    monkeypatch.setattr(svc, "_forge", lambda: object())
    assert service.replay_temel_durum_engeli() is None
    # Sessiz atlama yok: okunamadı uyarısı döner.
    engel, uyari = service.replay_temel_durum_kontrolu()
    assert engel is None and uyari and "okunamadı" in uyari and "forge yok" in uyari


def test_replay_app_kipinde_durum_worker_onbelleginden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub App kipinde core-api forge kuramaz: testid durumu `demo.durum_oku` işinin
    önbelleğe alınan sonucundan okunur (S1, 03-api-kimlik-taramasi)."""
    import tp_core.features.codegen.service as svc
    from tp_core.features.demo import service as demo

    monkeypatch.setattr(svc, "beklenen_uretim_modu", lambda: "replay")
    monkeypatch.setattr(svc, "_worker_algilamali", lambda: True)

    def forge_kurma() -> Any:
        raise AssertionError("App kipinde core-api forge kurmamalı")

    monkeypatch.setattr(svc, "_forge", forge_kurma)
    monkeypatch.setattr(demo, "worker_testid_durumu", lambda: ("cart-add", None))
    assert service.replay_temel_durum_kontrolu() == (service.REPLAY_TEMEL_ENGELI, None)
    monkeypatch.setattr(demo, "worker_testid_durumu", lambda: ("add-to-cart", None))
    assert service.replay_temel_durum_kontrolu() == (None, None)
    monkeypatch.setattr(demo, "worker_testid_durumu", lambda: (None, "iş süresinde bitmedi"))
    engel, uyari = service.replay_temel_durum_kontrolu()
    assert engel is None and uyari and "iş süresinde bitmedi" in uyari


def test_worker_testid_durumu_taze_eski_ve_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    import time as _time

    from tp_core.features.demo import service as demo

    cagri: list[int] = []
    sonuc: dict[str, Any] = {"forge": {"testid": "add-to-cart"}}

    def worker_bolumu() -> dict[str, Any]:
        cagri.append(1)
        return dict(sonuc)

    monkeypatch.setattr(demo, "_worker_forge_bolumu", worker_bolumu)
    demo.durum_onbellegini_temizle()
    try:
        # Önbellek yok → worker'dan okunur ve önbelleğe yazılır.
        assert demo.worker_testid_durumu() == ("add-to-cart", None) and len(cagri) == 1
        # Taze önbellek → worker'a gidilmez.
        assert demo.worker_testid_durumu() == ("add-to-cart", None) and len(cagri) == 1
        # Eski önbellek → yeniden okunur; worker sonucu yoksa açık neden (sessiz atlama yok).
        demo._FORGE_ONBELLEK["zaman"] = _time.monotonic() - demo.REPLAY_DURUM_MAX_YAS_S - 1
        sonuc.clear()
        sonuc.update({"forge": {"hata": demo.DURUM_SURUYOR, "bekliyor": True}, demo._GECICI: True})
        testid, neden = demo.worker_testid_durumu()
        assert testid is None and neden == demo.DURUM_SURUYOR and len(cagri) == 2
        sonuc.clear()
        sonuc.update({"forge": {"testid": "belirsiz"}})
        testid, neden = demo.worker_testid_durumu()
        assert testid is None and neden and "belirsiz" in neden
    finally:
        demo.durum_onbellegini_temizle()


def test_replay_durum_okunamazsa_uretim_baslar_ve_uyari_doner(
    api: TestClient,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tp_core.features.codegen.service as svc

    uyari = svc.REPLAY_DURUM_OKUNAMADI.format(neden="test")
    monkeypatch.setattr(svc, "replay_temel_durum_kontrolu", lambda: (None, uyari))
    r = api.post("/code/generate", json={"case_ids": [str(hazir["cases"][2])]})
    assert r.status_code == 202, r.text
    assert r.json()["replay_uyarisi"] == uyari and uyari in r.json()["mesaj"]
