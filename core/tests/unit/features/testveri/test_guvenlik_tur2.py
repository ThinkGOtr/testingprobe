"""013 review turu 2, E3 veri/güvenlik düzeltmeleri (güvenlik #1–#11, mimar #1/#5/#8, QA #11,
PO #5, frontend #4 backend kısmı)."""

from __future__ import annotations

import copy
import hashlib
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.cases.helpers import case_icerik, latest_cases, login, run_jobs
from tests.unit.features.codegen.test_checks import RULES, golden_mapping
from tests.unit.features.codegen.test_render import girdi
from tp_core.features.bugs import jql
from tp_core.features.cases.service import requirement_for_ide
from tp_core.features.codegen import render
from tp_core.features.testveri import atif, service
from tp_core.gateway.testing import text_response
from tp_core.models import session_scope

from .conftest import DEMO_PAROLA

PAROLA_ATFI = "{veri:ortak.demo_parola}"


# ----------------------------------------------------------------------------- saf fonksiyonlar


def test_qa11_tekillik_suzgecten_once_tum_katalogla() -> None:
    """Ürün adı bir arayüz etiketiyle aynıysa belirsizdir: eşlenmez (etiket atfa dönmez)."""
    kat = {"urun.p_009.ad": "Sepetim", "etiket.sepetim": "Sepetim", "urun.p_009.kod": "P-009"}
    case = {"steps": [{"action": "Sepetim sayfasına git", "data": "P-009", "expected": "x"}]}
    e = atif.case_esle(case, kat)
    assert e["steps"][0]["action"] == "Sepetim sayfasına git"
    assert e["steps"][0]["data"] == "{veri:urun.p_009.kod}"


def test_takma_deger_atfa_esler_cakisan_katalog_degerini_ezmez() -> None:
    case = {"steps": [{"action": "giriş", "data": "bayi1 / Demo123!", "expected": "ok"}]}
    e = atif.case_esle(case, {"bayi.bayi1.kullanici_adi": "bayi1"}, {DEMO_PAROLA: "ortak.p"})
    assert e["steps"][0]["data"] == "{veri:bayi.bayi1.kullanici_adi} / {veri:ortak.p}"
    # Takma değer katalogda başka bir anahtarın değeriyse eşlenmez (belirsiz).
    e = atif.case_esle(case, {"urun.x.ad": DEMO_PAROLA}, {DEMO_PAROLA: "ortak.p"})
    assert "{veri:ortak.p}" not in str(e)


def test_maskeleme_kelime_siniri_en_az_uzunluk_ve_yapisal_alanlar() -> None:
    # Güvenlik #10: kısa değer ve kelime içi geçiş maskelenmez; yapısal alanlar korunur.
    assert atif.maskele("ab 1234 x1234y", ["ab", "1234"]) == "ab ••• x1234y"
    assert atif.maskele("bayi1/Demo123! ok", [DEMO_PAROLA]) == "bayi1/••• ok"
    obj = {
        "id": "aa-1234-bb",
        "case_hash": "1234",
        "durum": "open",
        "veri_izi": {"k": "1234"},
        "baslik": "pin 1234",
        "liste": [{"script_id": "1234", "metin": "1234"}],
    }
    m = atif.maskele_obje(obj, ["1234", "open"])
    assert m["id"] == "aa-1234-bb" and m["case_hash"] == "1234" and m["durum"] == "open"
    assert m["veri_izi"] == {"k": "1234"}
    assert m["baslik"] == "pin •••"
    assert m["liste"] == [{"script_id": "1234", "metin": "•••"}]
    assert atif.gizli_geciyor_mu('login("bayi1", "Demo123!")', [DEMO_PAROLA]) == [DEMO_PAROLA]
    assert atif.gizli_geciyor_mu("x", ["ab"]) == []


def test_bug_arama_terimleri_sirrin_parcasini_icermez() -> None:
    """Güvenlik #1: parola (katlanmış) Jira aramasına / JQL'e girmez."""
    terimler = jql.key_terms(["Giriş Demo123! parolasıyla başarısız"], gizliler=[DEMO_PAROLA])
    assert "demo123" not in terimler and "parolasıyla" in terimler
    sorgu = jql.duplicate_search_jql("TPD", terimler)
    assert sorgu is not None and "demo123" not in sorgu.lower()


# ------------------------------------------------------------------------------------ özet


def test_veri_izi_tuzlu_ozet_eski_duz_ozet_iceride_yorumlanir(
    engine: Engine, katalog: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    duz = hashlib.sha256(DEMO_PAROLA.encode()).hexdigest()[:12]
    with session_scope() as s:
        _, iz = service.case_coz(s, {"steps": [{"action": "a", "data": PAROLA_ATFI}]})
        ozet = iz["ortak.demo_parola"]
        assert ozet.startswith("h1:") and duz not in ozet
        # Anahtar farklıysa özet farklı (tuz sunucu sırrından).
        monkeypatch.setenv("TP_SESSION_SECRET", "baska-bir-oturum-sirri-" + "y" * 20)
        assert service.deger_ozeti(DEMO_PAROLA, gizli=True) != ozet
        # Sunucu sırrı yoksa gizli değer hiç özetlenmez; açık değer anahtarsız (h0).
        monkeypatch.delenv("TP_SESSION_SECRET")
        monkeypatch.setattr(service, "_ozet_anahtari", lambda: None)
        assert service.deger_ozeti(DEMO_PAROLA, gizli=True) is None
        assert str(service.deger_ozeti("bayi1")).startswith("h0:")
        # Eski (düz sha256[:12]) iz: değer aynıysa "değişmedi", API'de null döner.
        eski = {"ortak.demo_parola": duz, "bayi.bayi1.kullanici_adi": "0" * 12}
        assert service.degisen_anahtarlar(s, eski) == ["bayi.bayi1.kullanici_adi"]
        assert service.api_veri_izi(eski) == {
            "ortak.demo_parola": None,
            "bayi.bayi1.kullanici_adi": None,
        }
        assert service.izler_ayni(s, {"ortak.demo_parola": duz}, {"ortak.demo_parola": "h1:x"})


# ----------------------------------------------------------------------------- katalog CRUD


def test_grup_bos_metinle_varsayilana_doner(api: TestClient, make_user) -> None:
    login(api, make_user("analyst"))
    r = api.post("/test-data", json={"anahtar": "bayi.bayi9.ad", "deger": "Dokuz", "grup": "Özel"})
    assert r.status_code == 201 and r.json()["grup"] == "Özel"
    k = r.json()
    r = api.put(f"/test-data/{k['id']}", json={"grup": "", "beklenen_surum": 1})
    assert r.status_code == 200, r.text
    assert r.json()["grup"] == "bayi" and r.json()["surum"] == 2
    r = api.put(f"/test-data/{k['id']}", json={"grup": None, "beklenen_surum": 2})
    assert r.status_code == 422  # zaten varsayılan: değişiklik yok


def test_gizliyle_ayni_deger_genel_metin_ve_denetim(
    api: TestClient, engine: Engine, make_user, katalog: int
) -> None:
    login(api, make_user("analyst"))
    r = api.post("/test-data", json={"anahtar": "ortak.deneme", "deger": DEMO_PAROLA})
    assert r.status_code == 422
    detay = r.json()["detail"]
    assert detay == service.GIZLI_CAKISMA_METNI and "ortak.demo_parola" not in detay
    with engine.connect() as c:
        ozetler = list(
            c.execute(
                text("SELECT ozet FROM audit_event WHERE eylem = 'testveri.gizli_cakisma_reddi'")
            ).scalars()
        )
    assert ozetler == [{"anahtar": "ortak.deneme"}]
    assert DEMO_PAROLA not in str(ozetler)


# ----------------------------------------------------------------------------- IDE kanalı


def test_ide_blogu_katalogdan_gizli_atifla(
    engine: Engine, make_requirement, katalog: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Güvenlik #3 / PO #5: sır tanımlıyken de çözülmüş parola IDE'ye dönmez; kip replay olsa da
    blok katalogdan (yeni kayıt görünür)."""
    from tp_core.features.cases import testdata

    monkeypatch.setattr(testdata, "model_kipi", lambda: "replay")
    make_requirement()
    with session_scope() as s:
        service.olustur(s, {"anahtar": "ortak.yeni_not", "deger": "Katalogdan-77"}, "analist")
    with session_scope() as s:
        girdi_ = requirement_for_ide(s, "TPD-4")["girdi"]
    assert DEMO_PAROLA not in girdi_ and PAROLA_ATFI in girdi_
    assert "Katalogdan-77" in girdi_


# ------------------------------------------------------------------- case API maskeleme


def test_case_api_ve_kullanim_basligi_maskeli(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog: int
) -> None:
    """Güvenlik #7: başlıktaki (eşlenmeyen) parola API'de düz dönmez; onay hash'i değişmez."""
    ham = case_icerik()
    ham["title"] = f"bayi1 / {DEMO_PAROLA} ile giriş"
    fake_gateway([text_response({"cases": [ham]})])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    (c,) = latest_cases(api, rid)
    assert c["icerik"]["title"] == "bayi1 / ••• ile giriş"
    with session_scope() as s:
        from tp_core.models import TestCase

        tc = s.get(TestCase, uuid.UUID(c["id"]))
        assert DEMO_PAROLA in tc.icerik["title"]  # saklanan içerik ham (hash ondan)
        assert c["icerik_hash"] == tc.icerik_hash
        kullanan = service.anahtar_kullanimi(s, "ortak.demo_parola")
    assert kullanan and DEMO_PAROLA not in str(kullanan)


# ------------------------------------------------------------------------- render taraması


def test_render_bilinen_gizli_duz_gecerse_engel() -> None:
    """Güvenlik #4/#5: sırrı tanımsız ya da iç içe geçen gizli değer → fail-closed."""
    with pytest.raises(render.GizliSizinti) as e:
        render.render_test(girdi(2, gizli_taranacak=(DEMO_PAROLA,)), RULES)
    assert DEMO_PAROLA not in str(e.value)
    # Sır tanımlı: ortam okuması basılır, tarama temiz.
    r = render.render_test(
        girdi(
            2,
            gizli_ortam={DEMO_PAROLA: "TP_TESTVERI_DEMO_PAROLA"},
            gizli_taranacak=(DEMO_PAROLA,),
        ),
        RULES,
    )
    assert DEMO_PAROLA not in r.content
    # Değer dizi içinde / metnin parçası (eşleme argümanı birebir değil) → yine engel.
    for donustur in (lambda v: [v], lambda v: f"bayi1/{v} "):
        eslem = copy.deepcopy(golden_mapping(2))
        for m in eslem["step_mapping"]:
            m["args"] = [donustur(a) if a == DEMO_PAROLA else a for a in m["args"]]
        with pytest.raises(render.GizliSizinti):
            render.render_test(
                girdi(
                    2,
                    mapping=eslem,
                    gizli_ortam={DEMO_PAROLA: "TP_TESTVERI_DEMO_PAROLA"},
                    gizli_taranacak=(DEMO_PAROLA,),
                ),
                RULES,
            )


def test_sir_tanimsiz_duz_parolali_case_pr_acmaz(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    make_requirement: Any,
    make_user: Any,
    katalog: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Güvenlik #5: katalogdan önce yazılmış (atıfsız, düz "Demo123!") onaylı case + sır
    tanımsız → render taraması `test_verisi` engeli; commit/PR yok."""
    from tests.unit.features.codegen.conftest import golden_cases, tpd1_acs
    from tp_core.audit import content_hash
    from tp_core.models import Requirement, Script, TestCase, case_id
    from tp_core.models.codegen_feature import ScriptCodegen
    from tp_core.workflow.service import SYSTEM, content_hash_of, record_approval, transition

    rid = make_requirement(
        "TPD-1",
        "Kampanyalı sepet ve sipariş onayı",
        "Bayi, katalogdan ürünleri sepete ekleyip kampanya indirimiyle siparişini "
        "onaylayabilmelidir.",
        tpd1_acs(),
    )
    analist = make_user("analyst")
    ham = golden_cases()[1]
    assert DEMO_PAROLA in str(ham)
    with session_scope() as s:
        req = s.get(Requirement, rid)
        transition(s, req, "generating", SYSTEM, "po_approved")
        transition(s, req, "cases_ready", SYSTEM, "generating")
        tc = TestCase(
            id=case_id(req, 2, 1),
            requirement_id=rid,
            sira_no=2,
            uretim_no=1,
            icerik=ham,
            icerik_hash=content_hash(ham),
            uretim_modu="replay",
        )
        s.add(tc)
        s.flush()
        record_approval(s, tc, analist, "approve", beklenen_hash=content_hash_of(tc))
        transition(s, tc, "approved", analist, "draft")
        cid = tc.id
    monkeypatch.delenv(service.DEMO_PAROLA_SIRRI)
    login(api, make_user("engineer"))
    r = api.post("/code/generate", json={"case_ids": [str(cid)]})
    assert r.status_code == 202, r.text
    sid = r.json()["script_ids"][0]
    run_jobs(engine)
    with session_scope() as s:
        sc, cg = s.get(Script, uuid.UUID(sid)), s.get(ScriptCodegen, uuid.UUID(sid))
        assert sc.durum == "failed" and cg.engel_turu == "test_verisi", cg.engel_nedeni
        assert DEMO_PAROLA not in (cg.engel_nedeni or "")
    assert codegen.forge.find_open_pr(f"tp/case-{cid}") is None
