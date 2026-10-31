"""Faz 3 inceleme düzeltmeleri, 2. tur (codegen).

- main ilerleyince açık bot PR'larının dalı güncellenir (gerçek LocalForge: iki PR, birincisi
  merge, ikincisi güncellenir → yeni head'de CI + yeni onay → merge).
- merge isteği girdi/sıra hataları; merge onayı yazılmadan reddedilen bilinen engeller.
- insan review: değişiklik iste / reddet (sabit ret taksonomisi, Constitution X).
- locator çapraz kontrolü (yanlış elemanı gösteren `browser_generate_locator`), canlı kipte
  "doğrulandı" beyanının deterministik karşılığı, pass@1'in model engellerini sayması.
- kararsız (flaky) sınıfı, Playwright assertion zaman aşımı mesajı, birebir biçim denetimi.
- GitHub kipi: ayna yoksa yerel kontrol atlanmaz; forge'da başka head merge edilirse işaretlenir.
- portal görünümü: PR açıklaması, PR'sız script'te merge kapısı yok, adım 5 gecikme uyarısı.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.codegen.conftest import gecti, kirmizi
from tests.unit.features.codegen.test_browser import FakeSession
from tests.unit.features.codegen.test_checks import golden_case, golden_mapping, symbols
from tests.unit.features.codegen.test_flow import github_kipi, script_of, uret
from tp_core.features.codegen import checks, service, views
from tp_core.features.codegen.browser import AracSonucu
from tp_core.features.codegen.classify import classify
from tp_core.features.codegen.classify import test_error_kind as hata_turu
from tp_core.features.codegen.normalize import find_exact_source
from tp_core.models import PullRequest, Review, Script, session_scope
from tp_core.models.codegen_feature import ScriptAdim
from tp_core.workflow.jobs import process_one
from tp_core.workflow.service import Principal

from .conftest import run_jobs


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Principal:
    u = make_user("engineer")
    from .conftest import login

    login(api, u)
    return u


def _pr_ac(api: TestClient, engine: Engine, cid: uuid.UUID) -> Script:
    sid = uret(api, [cid])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "pr_open", cg.engel_nedeni
    return sc


def _ci_yesil(codegen: Any, sha: str) -> None:
    """Yerel CI'ın (ci şeridi) yeni head üzerindeki `local-ci` sonucunu yazar."""
    (codegen.artifacts / "checks" / f"{sha}.json").write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "name": "local-ci",
                        "status": "completed",
                        "conclusion": "success",
                        "url": None,
                    }
                ]
            }
        )
    )


def _merge_kuyruga(sid: uuid.UUID, user: Principal, not_: str = "Kırma kanıtı yok, kabul.") -> Any:
    with session_scope() as s:
        sc = s.get(Script, sid)
        return service.request_merge(
            s, sc.pr_no, user, service.content_hash_of(sc), sc.head_sha, not_
        )


def _isi_isle(engine: Engine, job_id: Any) -> tuple[str, str | None]:
    while True:
        with engine.begin() as c:
            durum = c.execute(text("SELECT durum, son_hata FROM job WHERE id = :j"),
                              {"j": str(job_id)}).one()  # fmt: skip
        if durum.durum in ("done", "failed", "cancelled"):
            return durum.durum, durum.son_hata
        assert process_one(engine, "test-worker") is not None


def _bekleyen_isler(engine: Engine, tur: str) -> list[Any]:
    with engine.begin() as c:
        return list(
            c.execute(
                text("SELECT id, yuk FROM job WHERE tur = :t AND durum IN ('queued', 'retry')"),
                {"t": tur},
            )
        )


# --------------------------------------------- main ilerledi: diğer PR'ın dalı güncellenir


def test_iki_pr_birinci_merge_ikincinin_dali_guncellenir_ve_yeni_onayla_merge(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][2])
    b = _pr_ac(api, engine, hazir["cases"][1])
    b_eski_head = b.head_sha

    durum, hata = _isi_isle(engine, _merge_kuyruga(a.id, muhendis))
    assert durum == "done", hata
    # A merge edildi: B'nin dalı main'in gerisinde, güncelleme işi kuyrukta; kapı kapalı.
    (is_,) = _bekleyen_isler(engine, service.UPDATE_JOB)
    assert is_.yuk["script_id"] == str(b.id)
    d = api.get(f"/scripts/{b.id}").json()
    assert d["pr"]["dal"]["geride"] is True
    assert any("Dal main'in gerisinde" in e for e in d["merge_engelleri"])
    # Bilinen engel: merge onayı (review) yazılmadan reddedilir.
    r = api.post(
        f"/prs/{b.pr_no}/merge",
        json={
            "icerik_hash": d["pr"]["icerik_hash"],
            "head_sha": d["pr"]["head_sha"],
            "onay_notu": "kabul",
        },
    )
    assert r.status_code == 409 and "gerisinde" in r.json()["detail"]
    with session_scope() as s:
        assert not s.scalars(select(Review).where(Review.nesne_id == b.id)).all()

    # Güncelleme: main dala birleşir, yeni head; PR CI yeni head'de; kırma kanıtı sıfırlanır.
    assert _isi_isle(engine, is_.id)[0] == "done"
    b, bcg = script_of(b.id)
    assert b.head_sha != b_eski_head and b.durum == "pr_open"
    assert bcg.dal["geride"] is False and bcg.dal["onceki_head"] == b_eski_head
    assert bcg.break_durum == "not_started"
    assert codegen.forge.get_pr(b.pr_no).head_sha == b.head_sha
    assert codegen.ci[-1] == {"sha": b.head_sha, "trigger": "pr", "pr_number": b.pr_no}
    with session_scope() as s:
        assert s.get(PullRequest, b.pr_no).head_sha == b.head_sha
    # Eski head'e verilen onay geçmez; yeni head'de CI yeşil olunca yeni onayla merge edilir.
    eski = api.post(
        f"/prs/{b.pr_no}/merge",
        json={"icerik_hash": d["pr"]["icerik_hash"], "head_sha": b_eski_head, "onay_notu": "k"},
    )
    assert eski.status_code == 409 and "incelenenden farklı" in eski.json()["detail"]
    d2 = api.get(f"/scripts/{b.id}").json()
    assert any("local-ci" in e for e in d2["merge_engelleri"])  # yeni head'de CI bekleniyor
    _ci_yesil(codegen, b.head_sha)
    assert api.get(f"/scripts/{b.id}").json()["merge_engelleri"] == []
    durum, hata = _isi_isle(engine, _merge_kuyruga(b.id, muhendis))
    assert durum == "done", hata
    b, _ = script_of(b.id)
    assert b.durum == "merged"
    assert codegen.forge.read_file(a.dosya_yolu, ref="main") == a.icerik
    assert codegen.forge.read_file(b.dosya_yolu, ref="main") == b.icerik


def test_forge_dal_guncel_degil_reddinde_dal_otomatik_guncellenir(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][2])
    b = _pr_ac(api, engine, hazir["cases"][1])
    assert _isi_isle(engine, _merge_kuyruga(a.id, muhendis))[0] == "done"
    # İşaret kaybolmuş gibi (ör. main forge dışında ilerledi): forge reddeder, çekirdek işaretler.
    with engine.begin() as c:
        c.execute(text("DELETE FROM job WHERE tur = :t"), {"t": service.UPDATE_JOB})
        c.execute(text("UPDATE script_codegen SET dal = NULL WHERE script_id = :s"), {"s": b.id})
    durum, hata = _isi_isle(engine, _merge_kuyruga(b.id, muhendis))
    assert durum == "failed" and "main'in gerisinde" in (hata or "")
    _, bcg = script_of(b.id)
    assert bcg.dal["geride"] is True and bcg.dal["guncelleme"] == "queued"
    assert len(_bekleyen_isler(engine, service.UPDATE_JOB)) == 1
    with session_scope() as s:
        ret = s.execute(
            text(
                "SELECT ozet FROM audit_event WHERE eylem = 'codegen.merge_refused' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
    assert ret["dal_geride"] is True and ret["review_id"]


def test_dal_guncelle_ucu(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][2])
    r = api.post(f"/prs/{a.pr_no}/update-branch")
    assert r.status_code == 202, r.text
    run_jobs(engine)
    sc, cg = script_of(a.id)
    assert sc.head_sha == a.head_sha  # dal zaten günceldi: head değişmez, kanıt korunur
    assert cg.dal["guncelleme"] == "done" and cg.dal["geride"] is False


# ------------------------------------------------------------- merge isteği girdi hataları


def test_merge_head_sha_zorunlu_ve_merge_edilmis_pr(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][2])
    r = api.post(f"/prs/{a.pr_no}/merge", json={"onay_notu": "kabul"})
    assert r.status_code == 422 and "head_sha zorunlu" in r.json()["detail"]
    assert _isi_isle(engine, _merge_kuyruga(a.id, muhendis))[0] == "done"
    r = api.post(f"/prs/{a.pr_no}/merge", json={"onay_notu": "kabul"})
    assert r.status_code == 409 and "zaten merge edildi" in r.json()["detail"]
    d = api.get(f"/scripts/{a.id}").json()
    assert d["merge_engelleri"] == []  # merge edilmiş PR'ın kapısı yok


# ------------------------------------------------------- insan review: değişiklik / ret


def test_review_reddet_sabit_taksonomi_ve_pr_kapanir(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][2])
    d = api.get(f"/scripts/{a.id}").json()
    govde = {"karar": "reddet", "icerik_hash": d["pr"]["icerik_hash"],
             "head_sha": d["pr"]["head_sha"], "not": "Yanlış ürün kartı."}  # fmt: skip
    r = api.post(f"/prs/{a.pr_no}/review", json={**govde, "ret_nedeni": "begenmedim"})
    assert r.status_code == 422 and "taksonomi" in r.json()["detail"]
    r = api.post(f"/prs/{a.pr_no}/review", json={**govde, "ret_nedeni": "wrong_element"})
    assert r.status_code == 200, r.text
    assert r.json()["insan_review_sonucu"] == "reddedildi"
    sc, cg = script_of(a.id)
    assert sc.durum == "closed" and sc.insan_review_sonucu == "reddedildi"
    assert cg.engel_turu == "human_rejected" and "wrong_element" in cg.engel_nedeni
    with session_scope() as s:
        rv = s.scalars(select(Review).where(Review.nesne_id == a.id)).one()
        assert rv.karar == "request_changes" and rv.user_id == muhendis.id
        assert rv.sonra["ret_nedeni"] == "wrong_element" and rv.sonra["karar"] == "reddet"
        # Ret nedeni review kolonunda da (Constitution X: ret nedenleri sorgulanabilir ölçüdür).
        assert rv.ret_nedeni == "wrong_element"
    run_jobs(engine)
    assert codegen.forge.get_pr(a.pr_no).state == "closed"
    with session_scope() as s:
        assert s.get(PullRequest, a.pr_no).durum == "closed"
    # Kapanan PR'a merge/review yapılamaz; case için yeniden üretim açılabilir.
    r = api.post(f"/prs/{a.pr_no}/review", json={**govde, "ret_nedeni": "wrong_element"})
    assert r.status_code == 409
    assert uret(api, [hazir["cases"][2]])["durum"] == "started"


def test_review_degisiklik_iste(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][1])
    d = api.get(f"/scripts/{a.id}").json()
    r = api.post(
        f"/prs/{a.pr_no}/review",
        json={"karar": "degisiklik_iste", "ret_nedeni": "missing_ac",
              "icerik_hash": d["pr"]["icerik_hash"], "head_sha": d["pr"]["head_sha"]},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    sc, _ = script_of(a.id)
    assert sc.durum == "closed" and sc.insan_review_sonucu == "degisiklik_istendi"
    with session_scope() as s:
        rv = s.scalars(select(Review).where(Review.nesne_id == a.id)).one()
        assert rv.karar == "request_changes" and rv.ret_nedeni == "missing_ac"


# --------------------------------------------------------------- locator çapraz kontrolü


def test_locator_capraz_kontrol_birim() -> None:
    t = symbols()
    f = service.locator_capraz_kontrol
    iyi = [
        (3, 'button "Giriş yap" (login.submit)', "### Result\ngetByTestId('login-submit')"),
        (8, "P-004 kartında button (catalog.addToCart)",
         "getByTestId('product-card-P-004').getByTestId('add-to-cart')"),
        (9, "P-004 adet (catalog.quantityInput)", "getByTestId('qty-input-P-004')"),
        (10, "ipucusuz", "getByTestId('nav-cart')"),
    ]  # fmt: skip
    assert f(iyi, t) == []
    kotu = [
        (3, 'button "Giriş yap" (login.submit)', "getByTestId('login-password')"),
        (8, "P-004 kartında (catalog.addToCart)", "getByTestId('qty-input-P-004')"),
        (9, "P-004 kartında (catalog.addToCart)",
         "getByTestId('product-card-P-001').getByTestId('add-to-cart')"),
        (13, 'link "Sepet" (nav.cart)', "getByText('Bayi Sipariş Portalı · Örnek')"),
        (14, "ipucusuz", "getByTestId('uydurma-id')"),
        (15, "x (nav.cart)", "REPLAY sapması: kayıtta getByTestId('nav-cart'), bu oturumda …"),
    ]  # fmt: skip
    assert [n for n, _ in f(kotu, t)] == [3, 8, 9, 13, 14, 15]


def test_yanlis_locator_doneni_insana_duser(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    def browser() -> FakeSession:
        s = FakeSession()
        s.yanlis_locator = "getByTestId('login-password')"
        codegen.oturumlar.append(s)
        return s

    service.set_factories(
        gateway=service._factories["gateway"],
        browser=browser,
        toolchain=service._factories["toolchain"],
        forge=service._factories["forge"],
    )
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "unverified_step"
    assert "locator çapraz kontrolü tutmadı" in cg.engel_nedeni
    assert sc.pr_no is None and sc.pass_at_1 is None
    with session_scope() as s:
        adimlar = s.scalars(
            select(ScriptAdim).where(
                ScriptAdim.script_id == sc.id, ScriptAdim.arac == "browser_generate_locator"
            )
        ).all()
    # Kütüphane testId'siyle uyuşmayan her adım hatalı işaretli (login.password tesadüfen uyar).
    assert [a.hata for a in adimlar] == [
        "(login.password)" not in str(a.arguman.get("element")) for a in adimlar
    ]
    # Adım kartı gerçekten dönen locator'ı gösterir.
    assert all("getByTestId('login-password')" in a.ozet for a in adimlar)


def test_canli_dogrulandi_beyani_arac_cagrisiyla_karsilanmali() -> None:
    ok = AracSonucu("browser_click", True)
    cikti = golden_mapping(2)
    adim = len({m["step_id"] for m in cikti["step_mapping"]})
    yeterli = [(i, "browser_click", True, ok) for i in range(adim)]
    assert service.canli_dogrulama_kaniti(cikti, yeterli) is None
    eksik = service.canli_dogrulama_kaniti(cikti, yeterli[:-1])
    assert eksik is not None and "çalıştırılmamış adım" in eksik
    kanitsiz = json.loads(json.dumps(cikti))
    kanitsiz["step_mapping"][0]["evidence_ref"] = "  "
    assert "kanıtı" in (service.canli_dogrulama_kaniti(kanitsiz, yeterli) or "")


# ------------------------------------------------------- pass@1: model engelleri sayılır


@pytest.mark.parametrize(
    ("engel", "beklenen"),
    [("unsourced_value", False), ("unknown_method", False), ("missing_method", None)],
)
def test_pass_at_1_esleme_engeli(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
    engel: str,
    beklenen: bool | None,
) -> None:
    def denetim(*_a: Any, **_k: Any) -> checks.Sonuc:
        return checks.Sonuc([checks.Bulgu(engel, f"{engel} benzetimi")])

    monkeypatch.setattr(service.kontroller, "check_mapping", denetim)
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == engel
    assert sc.pass_at_1 is beklenen


# ---------------------------------------------------------------- sınıflandırma


def _t(status: str, error: str | None = None, tur: str | None = None) -> dict[str, Any]:
    return {"title": "TPD-1 · C3 › 6 adet", "status": status, "error": error,
            "failure": {"type": tur} if tur else None}  # fmt: skip


def _rapor(*testler: dict[str, Any]) -> dict[str, Any]:
    r = gecti()
    r.update(conclusion="failure")
    r["run"].update(status="failed", tests=list(testler))
    return r


ASSERT = (
    "Error: expect(locator).toHaveText(expected) failed\n\n"
    'Locator: getByTestId(\'cart-line-free-P-001\')\nExpected: "0"\nReceived: "1"'
)


def test_kararsiz_tekrar_defect_adayi_degil() -> None:
    s = classify(_rapor(_t("expected"), _t("expected"), _t("unexpected", ASSERT, "assertion")))
    assert s.sinif == "kararsiz" and (s.gecen, s.toplam) == (2, 3)
    assert "Defect adayı sayılmaz" in s.aciklama
    hepsi = _t("unexpected", ASSERT, "assertion")
    assert classify(_rapor(hepsi, hepsi, hepsi)).sinif == "defect_adayi"
    farkli = ASSERT.replace('Received: "1"', 'Received: "2"')
    karisik = classify(_rapor(hepsi, hepsi, _t("unexpected", farkli, "assertion")))
    assert karisik.sinif == "bilinmiyor"  # aynı doğrulamada kararlı kırmızı değil


def test_assertion_zaman_asimi_mesaji_locator_sayilmaz() -> None:
    mesaj = (
        "Error: Timed out 5000ms waiting for expect(locator).toHaveText(expected)\n\n"
        'Locator: getByTestId(\'free-qty\')\nExpected string: "0"\nReceived string: "1"\n'
        'Call log:\n  - Expect "toHaveText" with timeout 5000ms\n'
        "  - waiting for getByTestId('free-qty')\n"
    )
    assert hata_turu(mesaj, None) == "assertion"
    assert hata_turu(mesaj, "other") == "assertion"
    assert hata_turu(mesaj, "test_timeout") == "assertion"
    yerel = (
        "Error: locator.click: Timeout 5000ms exceeded.\nCall log:\n"
        "  - waiting for getByTestId('x')"
    )
    assert hata_turu(yerel, None) == "locator"


def test_kararsiz_akista_insana_flaky(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    r = kirmizi(ASSERT, "assertion")
    r["run"]["tests"] = [_t("expected"), _t("expected"), _t("unexpected", ASSERT, "assertion")]
    codegen.toolchain.kontroller.append(r)
    sid = uret(api, [hazir["cases"][3]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "flaky"
    assert cg.yerel_kontrol["sinif"] == "kararsiz" and sc.pass_at_1 is False


def test_birebir_bicim_denetimi() -> None:
    metin = ["Sepet toplamı 150,00 TL olur."]
    assert find_exact_source("150,00 TL", metin) == metin[0]
    assert find_exact_source("150 TL", metin) is None
    assert find_exact_source("150,00  TL", metin) == metin[0]  # boşluk farkı önemsiz
    assert find_exact_source(150, ["toplam 150,00 TL"]) is not None  # sayı: biçimsiz
    case = golden_case(2)
    m = golden_mapping(2)
    assert checks.check_mapping(m, case, symbols()).ok
    bozuk = json.loads(json.dumps(m))
    for e in bozuk["expects"]:
        if e["method"] == "expectTotal":
            e["args"] = [e["args"][0].replace(",00", "")]
    sonuc = checks.check_mapping(bozuk, case, symbols())
    assert not sonuc.ok and sonuc.engel_turu == "unsourced_value"
    assert "case'teki yazımla aynı değil" in sonuc.ozet()


# --------------------------------------------------------------------- GitHub kipi


def test_github_ayna_yoksa_yerel_kontrol_atlanmaz(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = github_kipi(codegen, monkeypatch)
    codegen.toolchain.check_status = 404  # commit toolchain'in aynasında yok
    sid = uret(api, [hazir["cases"][3]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "failed" and cg.engel_turu == "environment"
    assert "TP_FORGE_REMOTE_URL" in cg.engel_nedeni
    assert gh.prs == {} and sc.pr_no is None and sc.pass_at_1 is None


def test_github_baska_head_merge_edilirse_isaretlenir(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = github_kipi(codegen, monkeypatch)
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, _ = script_of(sid)
    yabanci = "f" * 40
    gh.prs[sc.pr_no] = gh.prs[sc.pr_no].model_copy(update={"state": "merged",
                                                           "head_sha": yabanci})  # fmt: skip
    service.sync_prs(engine, gh)
    sc, _ = script_of(sid)
    assert sc.durum == "merged" and sc.insan_review_sonucu == "kabul_yabanci_head"
    with session_scope() as s:
        ozet = s.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'codegen.merged_foreign_head'")
        ).scalar_one()
    assert ozet["merge_edilen_head"] == yabanci and ozet["uretilen_head"] == sc.head_sha


# ------------------------------------------------------------------- portal görünümü


def test_pr_govdesi_ve_defect_adayinda_kapi_yok(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][2])
    d = api.get(f"/scripts/{a.id}").json()
    assert "Denetim zinciri başı" in d["pr"]["govde"] and str(a.head_sha) not in ("", None)
    assert d["pr"]["dal"] == {"geride": False, "guncelleme": None, "neden": None,
                              "onceki_head": None}  # fmt: skip
    codegen.toolchain.kontroller.append(kirmizi(ASSERT, "assertion"))
    sid = uret(api, [hazir["cases"][3]])["script_ids"][0]
    run_jobs(engine)
    d = api.get(f"/scripts/{sid}").json()
    assert d["durum"] == "blocked" and d["pr"] is None
    assert d["merge_engelleri"] == []


def test_adim5_gecikme_butcesi_uyarisi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(service.ADIM5_BUTCE_ENV, "120")
    sc = Script(durum="verifying", dosya_yolu="x")
    eski = ScriptAdim(
        sira=1, arac="browser_navigate", zaman=datetime.now(UTC) - timedelta(seconds=150)
    )
    yeni = ScriptAdim(
        sira=1, arac="browser_navigate", zaman=datetime.now(UTC) - timedelta(seconds=5)
    )
    uyari = views.gecikme_uyarisi(sc, [eski])
    assert uyari and "REPLAY'e geçmeyi önerin" in uyari
    assert views.gecikme_uyarisi(sc, [yeni]) is None
    sc.durum = "pr_open"
    assert views.gecikme_uyarisi(sc, [eski]) is None


def test_gecikme_butcesi_asilinca_olay_yayinlanir(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    import time as zaman

    monkeypatch.setenv(service.ADIM5_BUTCE_ENV, "10")
    t = {"n": 0.0}

    def monotonic() -> float:
        t["n"] += 4.0  # her çağrı 4 sn: birkaç adım sonra 10 sn bütçesi aşılır
        return t["n"]

    monkeypatch.setattr(zaman, "monotonic", monotonic)
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    with session_scope() as s:
        olaylar = s.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'codegen.latency_budget' "
                 "AND nesne = :n"), {"n": f"script:{sid}"},
        ).scalars().all()  # fmt: skip
    assert len(olaylar) == 1 and olaylar[0]["butce_s"] == 10


# --------------------------------------------------------------- zaman aşımı bütçesi


def test_check_zaman_asimi_ci_zinciriyle_ayni() -> None:
    from tp_core.features.ci.clients import check_timeout_s
    from tp_core.features.codegen import jobs
    from tp_core.features.codegen.toolchain import ToolchainClient

    c = ToolchainClient("http://toolchain:8100")
    try:
        assert c.check_timeout_s == check_timeout_s() >= 3000
    finally:
        c.close()
    assert 3 * check_timeout_s() <= jobs.KIRMA_ZAMAN_ASIMI_S
    assert 2 * check_timeout_s() <= jobs.URETIM_ZAMAN_ASIMI_S


def test_uygulama_koku_github_varsayilani(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    monkeypatch.delenv(service.APP_ROOT_ENV, raising=False)
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(forge="github"))
    assert service.fixtures_path() == "demo-app/e2e/tests/fixtures.ts"
    assert service.e2e_goreli("demo-app/e2e/tests/generated/a.spec.ts") == (
        "tests/generated/a.spec.ts"
    )
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(forge="local"))
    assert service.fixtures_path() == "e2e/tests/fixtures.ts"
    monkeypatch.setenv(service.APP_ROOT_ENV, "/uygulama/")
    assert service.e2e_root() == "uygulama/e2e"
