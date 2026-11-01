"""Locator onarım akışı: POST /failures/{id}/fix → yoklama → aria → yama → AST → tam yerel kontrol
→ bot PR → insan merge → push CI. Ortam hataları onarılmaz; 0/çoklu eşleşme, AST ihlali, kırmızı
kontrol ve aria kanıtı yokluğu PR açmadan insana düşer."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, select

from tests.unit.features.repair.conftest import (
    SOZLESME_KATALOG,
    YESIL_ARIA,
    Ortam,
    gecti,
    kirik_hata,
    run_jobs,
    yesil_kosu,
)
from tp_core.features.repair import service, views
from tp_core.integrations.forge import REPAIR_LABEL
from tp_core.models import AuditEvent, Failure, PullRequest, Run, Script, session_scope
from tp_core.workflow.service import GateClosed, WorkflowError

LOCATORS = "e2e/pages/catalog/locators.ts"


def _eylemler(engine: Engine, nesne: str) -> list[str]:
    with session_scope() as s:
        return list(
            s.scalars(
                select(AuditEvent.eylem).where(AuditEvent.nesne == nesne).order_by(AuditEvent.id)
            )
        )


def _script(fid: uuid.UUID) -> Script:
    with session_scope() as s:
        sc = s.scalars(select(Script).where(Script.failure_id == fid)).one()
        s.expunge(sc)
        return sc


def _fix(api: Any, fid: uuid.UUID) -> Any:
    return api.post(f"/failures/{fid}/fix")


@pytest.fixture
def muhendis(api: Any, make_user: Any) -> Any:
    from tests.unit.features.cases.helpers import login

    u = make_user("engineer")
    login(api, u)
    return u


def test_mutlu_yol_pr_ve_insan_merge(engine: Engine, ortam: Ortam, api: Any, muhendis: Any) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    main_once = ortam.forge.head_sha("main")

    r = _fix(api, fid)
    assert r.status_code == 202, r.text
    assert r.json()["durum"] == "queued"
    # İdempotent: süren onarım için ikinci istek yeni iş açmaz.
    r2 = _fix(api, fid)
    assert r2.status_code == 202 and r2.json()["job_id"] is None
    assert r2.json()["script_id"] == r.json()["script_id"]

    sonuc = run_jobs(engine)
    assert [x.durum for x in sonuc] == ["done"], sonuc
    sc = _script(fid)
    assert sc.durum == "pr_open" and sc.tur == "locator_fix" and sc.pr_no is not None
    assert sc.branch == f"tp/repair-{fid}"
    assert sc.dosya_yolu == LOCATORS and sc.uretim_modu is None

    # Forge: yalnızca locators.ts değişti, yalnızca addToCart testId'si.
    pr = ortam.forge.get_pr(sc.pr_no)
    assert REPAIR_LABEL in pr.labels and pr.head_sha == sc.head_sha
    assert ortam.forge.changed_paths(main_once, sc.head_sha) == [LOCATORS]
    yeni = ortam.forge.read_file(LOCATORS, sc.head_sha)
    eski = ortam.forge.read_file(LOCATORS, main_once)
    assert yeni == eski.replace('testId: "add-to-cart"', 'testId: "cart-add"')
    assert "AI üretimi: **hayır**" in pr.body and "add-to-cart" in pr.body
    assert "son_yesil_kosu" in pr.body and "Denetim zinciri başı" in pr.body

    # toolchain çağrıları: yoklama kapsamla, AST repair modunda base=main, tam paket kontrol.
    istek = dict(ortam.toolchain.istekler)
    assert istek["/locator-probe"]["scope_test_id"] == "product-card-P-001"
    assert istek["/locator-probe"]["url_path"] == "/katalog"
    assert istek["/ast-guard"] == {
        "base_sha": main_once,
        "head_sha": sc.head_sha,
        "mode": "repair",
    }
    assert istek["/check"]["test_files"] == [] and istek["/check"]["ast_guard_mode"] == "repair"
    assert istek["/check"]["base_sha"] == main_once
    assert istek["/check"]["retries"] == 1  # CI ile aynı yeniden deneme politikası

    with session_scope() as s:
        f = s.get(Failure, fid)
        assert f is not None and f.oneri_durumu == "pr_open"
        kontrol = s.scalars(select(Run).where(Run.script_id == sc.id)).one()
        assert kontrol.tetik == "local_check" and kontrol.sonuc == "passed"
        assert s.get(PullRequest, sc.pr_no) is not None
    eylemler = _eylemler(engine, f"script:{sc.id}")
    for e in ("repair.requested", "repair.proposed", "repair.checked", "repair.pr_opened"):
        assert e in eylemler

    durum = api.get(f"/failures/{fid}/fix").json()
    assert durum["durum"] == "pr_open" and durum["eski_test_id"] == "add-to-cart"
    assert durum["yeni_test_id"] == "cart-add" and durum["anahtar"] == "catalog.addToCart"
    assert durum["ai_uretimi"] is False and durum["pr"]["number"] == sc.pr_no
    assert any("AST" in d for d in durum["dogrulama"])
    # Yama portalda görünür: tek satırlık birleşik fark, yalnızca testId.
    yama = durum["yama"]
    assert yama and f"--- a/{LOCATORS}" in yama and f"+++ b/{LOCATORS}" in yama
    eksi = [x for x in yama.splitlines() if x.startswith("-") and not x.startswith("---")]
    arti = [x for x in yama.splitlines() if x.startswith("+") and not x.startswith("+++")]
    assert len(eksi) == len(arti) == 1 and "add-to-cart" in eksi[0] and "cart-add" in arti[0]
    assert durum["yerel_kontrol"]["etkilenen_kosuldu"] is True

    # İnsan merge: içerik hash'i + head bağlı.
    with session_scope() as s, pytest.raises(GateClosed):
        service.request_merge(s, sc.pr_no, muhendis, "yanlis-hash", sc.head_sha)
    with session_scope() as s, pytest.raises(WorkflowError, match="head"):
        service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, "0" * 40)
    with session_scope() as s:
        service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha)
    assert [x.durum for x in run_jobs(engine)] == ["done"]
    sc2 = _script(fid)
    assert sc2.durum == "merged" and sc2.insan_review_sonucu == "kabul"
    assert 'testId: "cart-add"' in ortam.forge.read_file(LOCATORS, "main")
    assert ortam.ci and ortam.ci[-1]["trigger"] == "push"
    with session_scope() as s:
        assert s.get(Failure, fid).oneri_durumu == "merged"  # type: ignore[union-attr]
    assert "repair.merged" in _eylemler(engine, f"script:{sc.id}")
    # Merge edilmiş onarım yeniden istenemez.
    assert _fix(api, fid).status_code == 409


def test_triage_onerisi_kullanilir_ve_sozlesme_testi_yedegi(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Aria dosyası yok; son yeşil koşuda locators.spec sözleşme testleri geçmiş. Yedek yalnızca
    # açıkça istenirse kullanılır ve locator'ı GERÇEKTEN sınayan testi (katalog) gösterir.
    monkeypatch.setenv(service.ARIA_FALLBACK_ENV, "sozlesme")
    yid = yesil_kosu(engine, sozlesme=True)
    fid = kirik_hata(
        engine,
        mesaj="locator.click: Timeout",  # metinden çıkarılamaz: öneri kullanılmalı
        oneri={
            "locator_key": "catalog.addToCart",
            "old_testid": "add-to-cart",
            "new_testid": "cart-add",
            "scope_test_id": "product-card-P-002",
            "url_path": "/katalog",
            "son_yesil_run_id": str(yid),
        },
    )
    assert _fix(api, fid).status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum == "pr_open", views.oneri_blogu
    istek = dict(ortam.toolchain.istekler)
    assert istek["/locator-probe"]["scope_test_id"] == "product-card-P-002"
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["aria"]["kaynak"] == "sozlesme_testi"
    assert blok["aria"]["test"] == SOZLESME_KATALOG  # giriş sayfası testi değil
    assert "menü, katalog" in blok["aria"]["neden"] and "catalog.addToCart" in blok["aria"]["neden"]
    pr = ortam.forge.get_pr(sc.pr_no)  # type: ignore[arg-type]
    assert "giriş sayfası" not in pr.body


def test_sozlesme_yedegi_varsayilan_kapali(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, sozlesme=True)  # aria dosyası yok
    fid = kirik_hata(engine)
    _fix(api, fid)
    run_jobs(engine)
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["script_durumu"] == "blocked" and blok["engel"]["adim"] == "aria"
    assert "aria snapshot" in blok["engel"]["neden"]


def test_sozlesme_yedegi_kapsayan_test_yoksa_kapali_basarisiz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Son yeşilde yalnızca giriş sayfası sözleşme testi geçti: catalog.addToCart'ı sınamaz →
    yedek kanıt sayılmaz, PR açılmaz."""
    from tp_core.models import TestResult

    monkeypatch.setenv(service.ARIA_FALLBACK_ENV, "sozlesme")
    yid = yesil_kosu(engine)
    with session_scope() as s:
        s.add(TestResult(run_id=yid, test_adi="locators.ts rol/ad sözleşmesi › giriş sayfası",
                         dosya="tests/locators.spec.ts", sonuc="passed", tetik="push",
                         kaynak="local"))  # fmt: skip
    fid = kirik_hata(engine)
    _fix(api, fid)
    run_jobs(engine)
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["script_durumu"] == "blocked" and blok["engel"]["adim"] == "aria"
    assert "sınayan sözleşme testi geçmemiş" in blok["engel"]["neden"]
    assert "/ast-guard" not in ortam.toolchain.yollar()


def test_snapshot_varsa_ama_dogrulamiyorsa_yedek_kullanilmaz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(service.ARIA_FALLBACK_ENV, "sozlesme")
    yesil_kosu(engine, sozlesme=True, aria_dosyasi='- main:\n  - heading "Katalog"\n',
               artifacts=ortam.artifacts)  # fmt: skip
    fid = kirik_hata(engine)
    _fix(api, fid)
    run_jobs(engine)
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["script_durumu"] == "blocked" and blok["engel"]["adim"] == "aria"
    assert blok["aria"].get("kaynak") != "sozlesme_testi"


def test_triage_onerisi_yoklamayla_celisirse_insana(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine, oneri={"old_testid": "add-to-cart", "new_testid": "baska-id"})
    _fix(api, fid)
    run_jobs(engine)
    assert _script(fid).durum == "blocked"


@pytest.mark.parametrize(
    ("degisiklik", "adim"),
    [
        ({"matches": 0, "test_id": None, "test_ids": []}, "yoklama"),
        ({"matches": 2, "test_id": None, "test_ids": ["cart-add", "cart-add"]}, "yoklama"),
        ({"sha_eslesmesi": "farkli", "oneri_uretilebilir": False}, "yoklama"),
        ({"test_id": "nav-cart", "test_ids": ["nav-cart"]}, "yoklama"),
        ({"test_id": "add-to-cart", "test_ids": ["add-to-cart"]}, "yoklama"),
    ],
)
def test_yoklama_tek_eslesme_vermezse_pr_yok(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any, degisiklik: dict[str, Any], adim: str
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    ortam.toolchain.probe.update(degisiklik)
    main_once = ortam.forge.head_sha("main")
    assert _fix(api, fid).status_code == 202
    assert [x.durum for x in run_jobs(engine)] == ["done"]
    sc = _script(fid)
    assert sc.durum == "blocked" and sc.pr_no is None
    assert ortam.forge.list_prs("open") == []
    assert ortam.forge.head_sha("main") == main_once
    assert "/check" not in ortam.toolchain.yollar()
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["engel"]["adim"] == adim
    # Engellenen deneme triage önerisini silmez; engel ayrı gösterilir.
    assert blok["engellendi"] is True and blok["durum"] == "failed"
    assert (blok["eski_test_id"], blok["yeni_test_id"]) == ("add-to-cart", "cart-add")
    assert blok["anahtar"] == "catalog.addToCart"
    with session_scope() as s:
        assert s.get(Failure, fid).oneri_durumu == "proposed"  # type: ignore[union-attr]
    # Yeniden deneme AYNI script'i kullanır (her deneme yeni satır açmaz).
    ortam.toolchain.probe.update(matches=1, test_id="cart-add", test_ids=["cart-add"],
                                 sha_eslesmesi="eslesiyor", oneri_uretilebilir=True)  # fmt: skip
    r = _fix(api, fid)
    assert r.status_code == 202 and r.json()["script_id"] == str(sc.id)
    assert r.json()["deneme"] == 2 and r.json()["job_id"]
    # Kuyruktaki deneme sürerken ikinci istek yeni iş açmaz.
    r2 = _fix(api, fid)
    assert r2.status_code == 202 and r2.json()["job_id"] is None
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["engel"] is None and blok["engellendi"] is False
    assert [x.durum for x in run_jobs(engine)] == ["done"]
    sc2 = _script(fid)  # tek satır
    assert sc2.id == sc.id and sc2.durum == "pr_open"
    assert "repair.retry" in _eylemler(engine, f"script:{sc.id}")


def test_aria_kaniti_yoksa_pr_yok(engine: Engine, ortam: Ortam, api: Any, muhendis: Any) -> None:
    fid = kirik_hata(engine)  # yeşil koşu yok, ajan snapshot'ı yok
    _fix(api, fid)
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum == "blocked"
    engel = api.get(f"/failures/{fid}/fix").json()["engel"]
    assert engel["adim"] == "aria"
    # Sunucuya ne yapacağı söylenir (make reset → make break yolu).
    assert "yeşil koşu yok" in engel["neden"] and "push CI" in engel["neden"]
    assert "/ast-guard" not in ortam.toolchain.yollar()


def test_aria_yanlis_eleman_icin_gecersiz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    # Son yeşil snapshot'ta "Sepete ekle" kart dışında da var → çoklu → öneri yok.
    yesil_kosu(
        engine, aria_dosyasi=YESIL_ARIA + '  - button "Sepete ekle"\n', artifacts=ortam.artifacts
    )
    fid = kirik_hata(engine)
    _fix(api, fid)
    run_jobs(engine)
    assert _script(fid).durum == "blocked"


def test_ast_korumasi_ihlali_pr_acmaz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    ortam.toolchain.ast = {
        "ok": False,
        "violations": [{"rule": "file_not_allowed", "file": "e2e/tests/cart.spec.ts"}],
    }
    _fix(api, fid)
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum == "blocked" and sc.pr_no is None
    assert "/check" not in ortam.toolchain.yollar()
    assert api.get(f"/failures/{fid}/fix").json()["engel"]["adim"] == "ast_guard"


def test_kirmizi_yerel_kontrol_pr_acmaz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    rapor = gecti()
    rapor.update(conclusion="failure", summary="Yerel CI başarısız: run", failed_steps=["run"])
    rapor["run"]["status"] = "failed"
    ortam.toolchain.kontrol = rapor
    _fix(api, fid)
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum == "blocked" and ortam.forge.list_prs("open") == []
    with session_scope() as s:
        assert s.scalars(select(Run).where(Run.script_id == sc.id)).one().sonuc == "failed"


def test_kontrolde_saglik_basarisizsa_ortam(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    rapor = gecti()
    rapor.update(conclusion="failure", saglik={"ok": False, "hata": "web 502"})
    ortam.toolchain.kontrol = rapor
    _fix(api, fid)
    run_jobs(engine)
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["script_durumu"] == "blocked" and blok["engel"]["sinif"] == "environment"


@pytest.mark.parametrize(
    ("kw", "parca"),
    [
        ({"sinif": "environment", "alt_tur": None}, "Ortam"),
        ({"saglik_ok": False}, "Ortam"),
        ({"sinif": "product_defect", "alt_tur": "assertion"}, "product_defect"),
    ],
)
def test_ortam_ve_defect_onarilmaz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any, kw: dict[str, Any], parca: str
) -> None:
    fid = kirik_hata(engine, **kw)
    r = _fix(api, fid)
    assert r.status_code == 409 and parca in r.json()["detail"]
    assert run_jobs(engine) == []
    assert ortam.toolchain.istekler == []
    assert "repair.refused" in _eylemler(engine, f"failure:{fid}")


def test_rol_ve_bulunamayan(engine: Engine, ortam: Ortam, api: Any, make_user: Any) -> None:
    from tests.unit.features.cases.helpers import login

    fid = kirik_hata(engine)
    login(api, make_user("tester"))
    assert _fix(api, fid).status_code == 403
    login(api, make_user("engineer"))
    assert _fix(api, uuid.uuid4()).status_code == 404
    assert api.get(f"/failures/{fid}/fix").status_code == 404


def test_ajan_snapshotu_son_yesil_kanit(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    """Yeşil koşu aria dosyası yok; insan onaylı (merge edilmiş) kod üretiminin ajan snapshot'ı
    rol + adı her kartta tek elemanla gösteriyor → kanıt `ajan_snapshot`."""
    from sqlalchemy import text

    sid = uuid.uuid4()
    with session_scope() as s:
        s.add(Script(id=sid, tur="test", dosya_yolu="e2e/tests/generated/x.spec.ts"))
    with engine.begin() as c:
        c.execute(text("UPDATE script SET durum = 'merged' WHERE id = :i"), {"i": sid})
        c.execute(
            text(
                "INSERT INTO script_adim (script_id, sira, arac, ham) "
                "VALUES (:i, 1, 'browser_snapshot', :h)"
            ),
            {"i": sid, "h": "### Page snapshot\n```yaml\n" + YESIL_ARIA + "```\n"},
        )
    fid = kirik_hata(engine)
    _fix(api, fid)
    run_jobs(engine)
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["script_durumu"] == "pr_open", blok
    assert blok["aria"]["kaynak"] == "ajan_snapshot"
    assert blok["aria"]["ref"] == f"script:{sid}#adim-1"


def test_ayni_locator_degisikligi_tek_onarim(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    """`make break` aynı testId yüzünden birçok testi kırar: tek onarım PR'ı hepsini kapatır;
    kardeş hata için ikinci PR açılmaz, merge sonrası kardeşlerin öneri durumu da `merged`."""
    import json as _json

    from sqlalchemy import text

    from tp_core.models import TestResult

    yid = yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    # Önceki bir kırık koşu (aynı değişiklik; onarılmadan kalmış öneri).
    eski = kirik_hata(engine)
    oneri = {
        "locator_key": "catalog.addToCart",
        "old_testid": "add-to-cart",
        "new_testid": "cart-add",
        "scope_test_id": "product-card-P-001",
        "url_path": "/katalog",
        "son_yesil_run_id": str(yid),
    }
    fid = kirik_hata(engine, oneri=oneri)
    kid = uuid.uuid4()
    with session_scope() as s:
        f = s.get(Failure, fid)
        assert f is not None
        tr = TestResult(id=uuid.uuid4(), run_id=f.run_id, test_adi="Sepet › AC1",
                        dosya="tests/cart.spec.ts", sonuc="failed", tetik="push",
                        kaynak="local", hata_mesaji=f.hata_imzasi)  # fmt: skip
        s.add(tr)
        s.flush()
        s.add(Failure(id=kid, run_id=f.run_id, test_result_id=tr.id, test_adi=tr.test_adi,
                      hata_imzasi="locator:AC1", sinif="test_maintenance", alt_tur="locator",
                      eslesen_sinyaller=[], karar_kaynagi="rule", oneri_turu="locator_fix",
                      oneri_durumu="proposed"))  # fmt: skip
        s.flush()
        s.execute(
            text(
                "INSERT INTO failure_ek (failure_id, anahtar, oneri) "
                "VALUES (:f, :a, CAST(:o AS jsonb))"
            ),
            {"f": kid, "a": f"{f.run_id}:k", "o": _json.dumps(oneri)},
        )
    assert _fix(api, fid).status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum == "pr_open"
    # Kardeş için ikinci onarım açılmaz: aynı PR döner.
    r = _fix(api, kid)
    assert r.status_code == 202 and r.json()["job_id"] is None
    assert r.json()["pr_no"] == sc.pr_no and r.json()["paylasilan"] is True
    # Kardeşin bloğu paylaşılan onarımı gösterir: PR, AST, yerel kontrol, yama, taşıyan hata.
    blok = api.get(f"/failures/{kid}/fix").json()
    assert blok["paylasilan"] is True and blok["paylasilan_failure_id"] == str(fid)
    assert blok["pr"]["number"] == sc.pr_no and blok["ast_guard"]["ok"] is True
    assert blok["yerel_kontrol"]["sonuc"] == "success" and blok["yama"]
    assert str(fid)[:8] in blok["paylasilan_mesaj"]
    # Önceki koşudaki aynı öneri de paylaşılan (açık) onarımı görür; ikinci PR açılmaz.
    assert _fix(api, eski).json()["pr_no"] == sc.pr_no
    with session_scope() as s:
        assert s.get(Failure, kid).oneri_durumu == "pr_open"  # type: ignore[union-attr]
        service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha)
    run_jobs(engine)
    with session_scope() as s:
        assert s.get(Failure, kid).oneri_durumu == "merged"  # type: ignore[union-attr]
        # Eski koşunun önerisi de eskidi: "Onarım PR'ı aç" artık sunulmaz.
        assert s.get(Failure, eski).oneri_durumu == "merged"  # type: ignore[union-attr]
    r = _fix(api, kid)
    assert r.status_code == 409 and "zaten onarıldı" in r.json()["detail"]
    blok = api.get(f"/failures/{eski}/fix").json()
    assert blok["durum"] == "merged" and blok["pr"]["number"] == sc.pr_no
    # Merge'ten SONRA yeniden kırılma (yeni koşu): eski merge onu "onarılmış" saymaz.
    yeni = kirik_hata(engine)
    with session_scope() as s:
        assert s.get(Failure, yeni).oneri_durumu == "proposed"  # type: ignore[union-attr]
    assert api.get(f"/failures/{yeni}/fix").status_code == 404
    assert _fix(api, yeni).json()["durum"] == "queued"


def test_yesil_kosunun_sayfa_aria_dosyasi_kanit(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    """Yeşil koşuda locators.spec.ts sayfa başına `<sayfa>.aria.yml` yazar (Playwright çıktı
    dizininde, iç içe). Onarım katalog sayfasınınkini (url_path /katalog) kanıt olarak kullanır;
    giriş sayfasının snapshot'ı rol + adı içermese de engel olmaz."""
    yid = yesil_kosu(engine)
    with session_scope() as s:
        dizin = s.get(Run, yid).artefaktlar["dizin"]  # type: ignore[union-attr]
    cikti = ortam.artifacts / dizin / "src/e2e/results/artifacts"
    (cikti / "locators-giris-chromium").mkdir(parents=True)
    (cikti / "locators-giris-chromium" / "giris.aria.yml").write_text(
        '- main:\n  - button "Giriş yap"\n', encoding="utf-8"
    )
    (cikti / "locators-katalog-chromium").mkdir(parents=True)
    (cikti / "locators-katalog-chromium" / "katalog.aria.yml").write_text(
        YESIL_ARIA, encoding="utf-8"
    )
    fid = kirik_hata(engine)
    _fix(api, fid)
    run_jobs(engine)
    blok = api.get(f"/failures/{fid}/fix").json()
    assert blok["script_durumu"] == "pr_open", blok
    assert blok["aria"]["kaynak"] == "son_yesil_kosu"
    assert blok["aria"]["dosya"] == "katalog.aria.yml" and blok["aria"]["run_id"] == str(yid)
    assert blok["aria"]["kapsayici_sayisi"] == 2
