"""Onarım dayanıklılığı ve kapıları (inceleme bulguları):

- uygunluk: model etiketi (karar_kaynagi='llm') / öneri yok → 409 (Constitution XI)
- merge: head_sha yok → 422; merge edilmiş PR'a farklı hash → 409
- yerel kontrol: retries=1, kırmızı testler adlarıyla (ilgisiz/etkilenen); etkilenen spec
  koşmadıysa PR yok
- yoklamadan sondaki satır sonu taşıyan data-testid → engel
- worker yarıda kalan onarım → failed (yeniden deneme açılır); forge'da merge edilmiş → uzlaştırma
- iki kardeş hataya eşzamanlı istek → tek onarım
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, select, text

from tests.unit.features.repair.conftest import (
    YESIL_ARIA,
    Ortam,
    gecti,
    kirik_hata,
    run_jobs,
    yesil_kosu,
)
from tp_core.features.repair import jobs as repair_jobs
from tp_core.features.repair import service
from tp_core.models import AuditEvent, Failure, Script, session_scope
from tp_core.workflow.jobs import REGISTRY, claim
from tp_core.workflow.service import GateClosed


@pytest.fixture
def muhendis(api: Any, make_user: Any) -> Any:
    from tests.unit.features.cases.helpers import login

    u = make_user("engineer")
    login(api, u)
    return u


def _script(fid: uuid.UUID) -> Script:
    with session_scope() as s:
        sc = s.scalars(select(Script).where(Script.failure_id == fid)).one()
        s.expunge(sc)
        return sc


def _blok(api: Any, fid: uuid.UUID) -> dict[str, Any]:
    return api.get(f"/failures/{fid}/fix").json()


@pytest.mark.parametrize(
    ("kw", "parca"),
    [
        ({"karar_kaynagi": "llm"}, "Kural önerisi yok"),
        ({"oneri": None}, "Kural önerisi yok"),
    ],
)
def test_model_etiketi_ya_da_onerisiz_hata_onarilmaz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any, kw: dict[str, Any], parca: str
) -> None:
    fid = kirik_hata(engine, **kw)
    r = api.post(f"/failures/{fid}/fix")
    assert r.status_code == 409 and parca in r.json()["detail"]
    assert run_jobs(engine) == [] and ortam.toolchain.istekler == []


def _pr_ac(engine: Engine, ortam: Ortam, api: Any) -> tuple[uuid.UUID, Script]:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    assert api.post(f"/failures/{fid}/fix").status_code == 202
    run_jobs(engine)
    sc = _script(fid)
    assert sc.durum == "pr_open", _blok(api, fid)
    return fid, sc


def test_merge_girdisi_ve_merge_edilmis_pr_hash_kapisi(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    _fid, sc = _pr_ac(engine, ortam, api)
    assert sc.pr_no is not None
    r = api.post(f"/prs/{sc.pr_no}/merge", json={"icerik_hash": sc.icerik_hash})
    assert r.status_code == 422 and "head_sha" in r.json()["detail"]
    with session_scope() as s:
        service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha)
    run_jobs(engine)
    assert _script(sc.failure_id).durum == "merged"  # type: ignore[arg-type]
    # İdempotent tekrar yalnızca aynı hash'le; başka bir hash 409.
    with session_scope() as s:
        assert service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha)
    with session_scope() as s, pytest.raises(GateClosed):
        service.request_merge(s, sc.pr_no, muhendis, "deadbeef", sc.head_sha)
    with session_scope() as s, pytest.raises(GateClosed):
        service.request_merge(s, sc.pr_no, muhendis, None, sc.head_sha)


def _kirmizi_rapor(testler: list[dict[str, Any]]) -> dict[str, Any]:
    rapor = gecti()
    rapor["run"]["tests"] = [*rapor["run"]["tests"], *testler]
    rapor.update(conclusion="failure", summary="Yerel CI başarısız: run", failed_steps=["run"])
    return rapor


def test_ilgisiz_kirmizi_test_adiyla_bildirilir(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    ad = "Bayi girişi (TPD-4) › oturumsuz açılış ve giriş konsola hata yazmaz"
    hata = "Error: expect(page).toHaveURL(expected) failed\nExpected: /katalog\nReceived: /giris"
    ortam.toolchain.kontrol = _kirmizi_rapor(
        [{"title": ad, "file": "tests/login.spec.ts", "status": "unexpected", "error": hata}]
    )
    api.post(f"/failures/{fid}/fix")
    run_jobs(engine)
    blok = _blok(api, fid)
    assert blok["script_durumu"] == "blocked"
    engel = blok["engel"]
    assert engel["adim"] == "yerel_kontrol" and engel["sinif"] == "ilgisiz_kirmizi"
    assert (
        ad in engel["neden"] and "ilgisiz" in engel["neden"] and "yeniden deneyin" in engel["neden"]
    )
    kirmizi = blok["yerel_kontrol"]["kirmizi_testler"]
    assert len(kirmizi) == 1 and kirmizi[0]["test"] == ad
    assert kirmizi[0]["testid_hatasi"] is False and kirmizi[0]["dosya"] == "tests/login.spec.ts"
    # Yeniden deneme aynı script'le geçer (flake).
    ortam.toolchain.kontrol = gecti()
    assert api.post(f"/failures/{fid}/fix").json()["script_id"] == blok["script_id"]
    run_jobs(engine)
    assert _script(fid).durum == "pr_open"


def test_etkilenen_kirmizi_test_insana_ve_flaky_engellemez(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    ortam.toolchain.kontrol = _kirmizi_rapor(
        [{"title": "Sepet › AC1", "file": "tests/cart.spec.ts", "status": "unexpected",
          "error": {"message": "waiting for getByTestId('cart-add')"}}]
    )  # fmt: skip
    api.post(f"/failures/{fid}/fix")
    run_jobs(engine)
    blok = _blok(api, fid)
    assert blok["engel"]["sinif"] == "insan" and "Sepet › AC1" in blok["engel"]["neden"]
    assert blok["yerel_kontrol"]["kirmizi_testler"][0]["testid_hatasi"] is True
    # Yeniden denemede geçen (flaky) test yeşil kontrolü bozmaz; kayda yazılır.
    rapor = gecti()
    rapor["run"]["tests"].append(
        {"title": "Giriş › x", "file": "tests/login.spec.ts", "status": "flaky"}
    )
    ortam.toolchain.kontrol = rapor
    api.post(f"/failures/{fid}/fix")
    run_jobs(engine)
    blok = _blok(api, fid)
    assert blok["script_durumu"] == "pr_open"
    assert blok["yerel_kontrol"]["flaky_testler"][0]["test"] == "Giriş › x"


def test_etkilenen_spec_kosmadiysa_pr_acilmaz(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    ortam.toolchain.kontrol = gecti(dosyalar=["tests/login.spec.ts"])
    api.post(f"/failures/{fid}/fix")
    run_jobs(engine)
    blok = _blok(api, fid)
    assert blok["script_durumu"] == "blocked" and blok["pr"] is None
    assert blok["engel"]["adim"] == "yerel_kontrol" and "eksik" in blok["engel"]["neden"]
    assert blok["yerel_kontrol"]["etkilenen_kosuldu"] is False
    assert "tests/cart.spec.ts" in blok["yerel_kontrol"]["etkilenen_eksik"]
    assert ortam.forge.list_prs("open") == []
    # Raporda dosya bilgisi yoksa da (None) PR açılmaz.
    ortam.toolchain.kontrol = gecti(dosyalar=[])
    api.post(f"/failures/{fid}/fix")
    run_jobs(engine)
    blok = _blok(api, fid)
    assert blok["script_durumu"] == "blocked" and "dosya bilgisi yok" in blok["engel"]["neden"]


def test_yoklama_satir_sonlu_testid_reddedilir(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine, oneri={"locator_key": "catalog.addToCart",
                                    "old_testid": "add-to-cart"})  # fmt: skip
    ortam.toolchain.probe.update(test_id="cart-add\n", test_ids=["cart-add\n"])
    api.post(f"/failures/{fid}/fix")
    run_jobs(engine)
    blok = _blok(api, fid)
    assert blok["engel"]["adim"] == "yoklama" and "geçersiz" in blok["engel"]["neden"]
    assert "/ast-guard" not in ortam.toolchain.yollar()


def test_yarida_kalan_onarim_kurtarilir(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    """Worker iş sürerken öldü: iş `failed` (reap), script `verifying`'de kaldı. Açılış kancası
    script'i `failed` yapar; yeni istek kabul edilir (kardeşler de takılı kalmaz)."""
    from tp_core.workflow.jobs import reap_stale

    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    r = api.post(f"/failures/{fid}/fix").json()
    with engine.begin() as c:
        is_ = claim(c, "olen-worker", list(REGISTRY))
        assert is_ is not None and str(is_.id) == r["job_id"]
        c.execute(text("UPDATE script SET durum = 'verifying' WHERE id = :i"),
                  {"i": r["script_id"]})  # fmt: skip
        c.execute(
            text(
                "UPDATE job SET baslama = now() - interval '7 days', "
                "guncelleme = now() - interval '7 days' WHERE id = :i"
            ),
            {"i": is_.id},
        )
        reap_stale(c)
        durum = c.execute(text("SELECT durum FROM job WHERE id = :i"), {"i": is_.id}).scalar()
    assert durum == "failed"
    # İstek de satır içi kurtarır; burada açılış kancasını sınarız.
    with engine.begin() as c:
        repair_jobs.on_worker_start(c)
    sc = _script(fid)
    assert sc.durum == "failed"
    blok = _blok(api, fid)
    assert blok["engellendi"] is True and blok["engel"]["adim"] == "is"
    r2 = api.post(f"/failures/{fid}/fix")
    assert r2.status_code == 202 and r2.json()["job_id"] and r2.json()["script_id"] == str(sc.id)
    run_jobs(engine)
    assert _script(fid).durum == "pr_open"


def test_istek_takili_onarimi_satir_icinde_kurtarir(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    fid = kirik_hata(engine)
    r = api.post(f"/failures/{fid}/fix").json()
    with engine.begin() as c:
        c.execute(text("UPDATE script SET durum = 'checking' WHERE id = :i"),
                  {"i": r["script_id"]})  # fmt: skip
        c.execute(text("UPDATE job SET durum = 'failed', son_hata = 'zaman aşımı' WHERE id = :i"),
                  {"i": r["job_id"]})  # fmt: skip
    r2 = api.post(f"/failures/{fid}/fix")
    assert r2.status_code == 202 and r2.json()["job_id"], r2.json()
    run_jobs(engine)
    assert _script(fid).durum == "pr_open"


def test_forgeda_merge_edilmis_onarim_uzlastirilir(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    """merge_pr başarılı, DB işlemi commit edilmeden worker düştü: forge'da PR merged, script
    pr_open. Açılış kancası (ya da yeniden merge isteği) uzlaştırır ve push CI'ı kuyruğa alır."""
    fid, sc = _pr_ac(engine, ortam, api)
    assert sc.pr_no is not None
    with session_scope() as s:
        service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha)
    merge_sha = ortam.forge.merge_pr(sc.pr_no, muhendis.kullanici_adi,
                                     expected_head_sha=sc.head_sha)  # fmt: skip
    with engine.begin() as c:  # merge işi düştü
        c.execute(text("UPDATE job SET durum = 'failed' WHERE tur = :t"), {"t": service.MERGE_JOB})
    assert _script(fid).durum == "pr_open"
    with engine.begin() as c:
        repair_jobs.on_worker_start(c)
    sc2 = _script(fid)
    assert sc2.durum == "merged"
    assert ortam.ci and ortam.ci[-1]["sha"] == merge_sha and ortam.ci[-1]["trigger"] == "push"
    with session_scope() as s:
        assert s.get(Failure, fid).oneri_durumu == "merged"  # type: ignore[union-attr]
        oz = s.scalars(
            select(AuditEvent.ozet).where(
                AuditEvent.nesne == f"script:{sc.id}", AuditEvent.eylem == "repair.merged"
            )
        ).one()
        assert oz["uzlastirma"] is True and oz["merge_sha"] == merge_sha


def test_merge_isi_forgeda_zaten_merge_edilmisse_uzlastirir(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    fid, sc = _pr_ac(engine, ortam, api)
    assert sc.pr_no is not None
    with session_scope() as s:
        service.request_merge(s, sc.pr_no, muhendis, sc.icerik_hash, sc.head_sha)
    ortam.forge.merge_pr(sc.pr_no, muhendis.kullanici_adi, expected_head_sha=sc.head_sha)
    assert [x.durum for x in run_jobs(engine)] == ["done"]
    assert _script(fid).durum == "merged"


def test_kardeslere_eszamanli_istek_tek_onarim(
    engine: Engine, ortam: Ortam, api: Any, muhendis: Any
) -> None:
    """Aynı değişikliği öneren iki hataya aynı anda istek: advisory kilit ikinciyi birincinin
    commit'ine kadar bekletir; ikinci yeni iş açmaz."""
    yesil_kosu(engine, aria_dosyasi=YESIL_ARIA, artifacts=ortam.artifacts)
    a = kirik_hata(engine)
    with session_scope() as s:
        run_id = s.get(Failure, a).run_id  # type: ignore[union-attr]
    b = kirik_hata(engine, run_id=run_id)
    sonuc: dict[str, Any] = {}
    s1 = session_scope().__enter__()
    try:
        sonuc["a"] = service.request_fix(s1, a, muhendis)  # kilit tutuluyor (commit yok)

        def ikinci() -> None:
            with session_scope() as s2:
                sonuc["b"] = service.request_fix(s2, b, muhendis)

        t = threading.Thread(target=ikinci)
        t.start()
        t.join(1.0)
        assert t.is_alive(), "ikinci istek kilitte beklemeliydi"
        s1.commit()
    finally:
        s1.close()
    t.join(10)
    assert sonuc["a"]["job_id"] and sonuc["b"]["job_id"] is None
    assert sonuc["b"]["script_id"] == sonuc["a"]["script_id"]
    with session_scope() as s:
        n = s.execute(text("SELECT count(*) FROM job WHERE tur = :t"), {"t": service.FIX_JOB})
        assert n.scalar() == 1
