"""013 review turu 3, F2 veri/güvenlik: K22 (case alanlarında gizli değer atıf; düzeltme maskesi),
güvenlik #2 (alt dize taraması/maskesi), #5 (çakışma kâhini freni), mimar #7 (key_terms)."""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.cases.helpers import (
    case_icerik,
    latest_cases,
    login,
    run_jobs,
    uretim_cikti,
)
from tests.unit.features.codegen.test_checks import RULES, golden_case, golden_mapping
from tests.unit.features.codegen.test_render import girdi
from tp_core.audit import content_hash
from tp_core.features.bugs import jql
from tp_core.features.cases.service import (
    DUZ_GIZLI_DUZELTME_METNI,
    MASKELI_DUZELTME_METNI,
    submit_drafts,
)
from tp_core.features.codegen import render
from tp_core.features.testveri import atif, service
from tp_core.gateway.testing import text_response
from tp_core.models import Review, TestCase, session_scope
from tp_core.workflow.service import Principal

from .conftest import DEMO_PAROLA

PAROLA_ATFI = "{veri:ortak.demo_parola}"
ESLEM = {DEMO_PAROLA: "ortak.demo_parola"}


# ----------------------------------------------------------------------------- saf fonksiyonlar


def test_gizli_eslem_yalniz_gizli_kayitlar_belirsiz_eslenmez() -> None:
    kat = {"bayi.bayi1.ad": "Merkez Bayi", "ortak.demo_parola": DEMO_PAROLA, "ortak.pin": "4321"}
    assert atif.gizli_eslem(kat, {"ortak.demo_parola"}) == ESLEM
    # Gizli değer başka (açık) bir kayıtla aynıysa belirsiz: eşlenmez.
    kat["urun.x.ad"] = DEMO_PAROLA
    assert atif.gizli_eslem(kat, {"ortak.demo_parola"}) == {}
    assert atif.gizli_eslem({}, set(), ESLEM) == ESLEM  # takma (sabit demo parolası)


def test_baslikta_yalniz_gizli_deger_eslenir_acik_deger_kalir() -> None:
    """K22 + K18: başlıkta gizli değer atfa döner; açık katalog değeri (bayi1) başlıkta kalır."""
    kat = {"bayi.bayi1.kullanici_adi": "bayi1"}
    case = case_icerik(title=f"bayi1 / {DEMO_PAROLA} ile giriş", tags=["AI-generated", DEMO_PAROLA])
    e = atif.case_esle(case, kat, ESLEM, {"ortak.demo_parola"})
    assert e["title"] == f"bayi1 / {PAROLA_ATFI} ile giriş"
    assert e["tags"] == ["AI-generated", PAROLA_ATFI]
    assert e["steps"][1]["data"] == "{veri:bayi.bayi1.kullanici_adi} / " + PAROLA_ATFI
    # Yapısal alanlara dokunulmaz.
    assert e["type"] == "positive" and e["acceptance_criteria_refs"] == ["AC1"]


def test_case_gorunum_atif_bitisik_maske_yapisal_ve_atif_korunur() -> None:
    case = case_icerik(
        title=f"{DEMO_PAROLA} ile giriş",
        expected_result=f"Yanlış parola {DEMO_PAROLA}x reddedilir; {PAROLA_ATFI} kabul",
    )
    g = atif.case_gorunum(case, ESLEM, [DEMO_PAROLA])
    assert g["title"] == f"{PAROLA_ATFI} ile giriş"
    assert g["steps"][1]["data"] == f"bayi1 / {PAROLA_ATFI}"
    # Bitişik yazım atfa dönemez → `•••` (düz dönmez); mevcut atıf bozulmaz.
    assert g["expected_result"] == f"Yanlış parola •••x reddedilir; {PAROLA_ATFI} kabul"
    assert DEMO_PAROLA not in str(g)
    # Saf: girdi değişmez.
    assert case["title"] == f"{DEMO_PAROLA} ile giriş"
    # Sır atıf metninin parçasıysa atıf yine bozulmaz.
    assert atif.maskele(f"{PAROLA_ATFI} demo_parola", ["demo_parola"]) == f"{PAROLA_ATFI} •••"


def test_maske_ve_duz_gizli_denetimleri() -> None:
    assert atif.maske_iceriyor_mu(case_icerik(title="••• ile giriş"))
    assert not atif.maske_iceriyor_mu(case_icerik())
    bitisik = case_icerik(expected_result=f"{DEMO_PAROLA}1 reddedilir")
    assert atif.gizli_kalan(bitisik, [DEMO_PAROLA])
    assert not atif.gizli_kalan(atif.case_gizli_esle(case_icerik(), ESLEM), [DEMO_PAROLA])


@pytest.mark.parametrize(
    "metin",
    [f"{DEMO_PAROLA}x", f'"{DEMO_PAROLA}"', f"x{DEMO_PAROLA}", f"pw_{DEMO_PAROLA}1"],
)
def test_sizinti_taramasi_ve_maske_bitisik_sirri_yakalar(metin: str) -> None:
    """Güvenlik tur 3 #2: kelime sınırı tarama ve maskeyi devre dışı bırakmaz."""
    assert atif.gizli_geciyor_mu(metin, [DEMO_PAROLA]) == [DEMO_PAROLA]
    assert DEMO_PAROLA not in atif.maskele(metin, [DEMO_PAROLA])
    assert DEMO_PAROLA not in str(atif.maskele_obje({"m": [metin]}, [DEMO_PAROLA]))


def test_render_bitisik_sir_engel_etiket_maskesi_atif_kurali() -> None:
    gizli = {DEMO_PAROLA: "TP_TESTVERI_DEMO_PAROLA"}
    # Negatif case'in "yanlış parola"sı sırrın bitişik hâli: argüman birebir değil → engel.
    eslem = copy.deepcopy(golden_mapping(2))
    for m in eslem["step_mapping"]:
        m["args"] = [f"{a}x" if a == DEMO_PAROLA else a for a in m["args"]]
    with pytest.raises(render.GizliSizinti):
        render.render_test(
            girdi(2, mapping=eslem, gizli_ortam=gizli, gizli_taranacak=(DEMO_PAROLA,)), RULES
        )
    # JSON kaçışlı biçim de engel.
    kacisli = 'Dem"o1'
    eslem = copy.deepcopy(golden_mapping(2))
    for m in eslem["step_mapping"]:
        m["args"] = [kacisli if a == DEMO_PAROLA else a for a in m["args"]]
    with pytest.raises(render.GizliSizinti):
        render.render_test(girdi(2, mapping=eslem, gizli_taranacak=(kacisli,)), RULES)
    # Başlıkta bitişik sır: etiket maskesi `atif.maskele` kuralıyla (alt dize) maskeler.
    case = copy.deepcopy(golden_case(2))
    case["title"] = f"{DEMO_PAROLA}x ile giriş"
    r = render.render_test(
        girdi(2, case=case, gizli_ortam=gizli, gizli_taranacak=(DEMO_PAROLA,)), RULES
    )
    assert DEMO_PAROLA not in r.content and "•••x ile giriş" in r.content
    assert render._maskeli(f"a {DEMO_PAROLA}x", [DEMO_PAROLA]) == atif.maskele(
        f"a {DEMO_PAROLA}x", [DEMO_PAROLA]
    )


def test_key_terms_gizli_liste_replay_girdisini_degistirmez() -> None:
    """Mimar tur 3 #7: metinde sır yoksa terimler (JQL, sıralama girdisi) gizli listeden
    bağımsız; sırrın kısa parçası olan yaygın sözcükler atılmaz, sırrın kendisi atılır."""
    metinler = ["Demo ortamında dem sepet kampanya bedava adet hatası", "emoji test"]
    assert jql.key_terms(metinler, gizliler=[DEMO_PAROLA]) == jql.key_terms(metinler)
    assert "demo" in jql.key_terms(metinler, gizliler=[DEMO_PAROLA])
    sirli = [f"Giriş {DEMO_PAROLA} parolasıyla xdemo123y emo123 başarısız"]
    terimler = jql.key_terms(sirli, gizliler=[DEMO_PAROLA])
    assert terimler == ["giriş", "parolasıyla", "başarısız"]
    sorgu = jql.duplicate_search_jql("TPD", terimler)
    assert sorgu is not None and "demo123" not in sorgu.lower()


# ------------------------------------------------------------------------- case API (K22)


def _uret(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, cases):
    fake_gateway([text_response(uretim_cikti(cases))])
    rid = make_requirement()
    login(api, make_user("tester"))  # 012: case'i Testçi üretir ve düzeltir
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    return rid


def _eski_case_yap(cid: str, **alanlar: Any) -> str:
    """013 öncesi case: saklanan içerikte düz parola (hash ham içerikten)."""
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(cid))
        icerik = case_icerik(**alanlar)
        tc.icerik, tc.icerik_hash = icerik, content_hash(icerik)
        return tc.icerik_hash


def _duzelt(api: TestClient, c: dict[str, Any], icerik: dict[str, Any]):
    return api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "edit", "icerik_hash": c["icerik_hash"], "icerik": icerik},
    )


def test_eski_case_okumada_atif_hash_ve_saklanan_icerik_degismez(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog: int
) -> None:
    rid = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    h = _eski_case_yap(c["id"], title=f"bayi1 / {DEMO_PAROLA} ile giriş")
    (c,) = latest_cases(api, rid)
    assert c["icerik"]["title"] == f"bayi1 / {PAROLA_ATFI} ile giriş"
    assert c["icerik"]["steps"][1]["data"] == f"bayi1 / {PAROLA_ATFI}"
    assert "ortak.demo_parola" in c["veri"] and c["veri"]["ortak.demo_parola"]["deger"] is None
    assert DEMO_PAROLA not in str(c)
    assert c["icerik_hash"] == h  # yalnız görünüm: hash ham içerikten
    tek = api.get(f"/cases/{c['id']}").json()
    assert tek["icerik"] == c["icerik"]
    with session_scope() as s:
        assert (
            s.get(TestCase, uuid.UUID(c["id"])).icerik["title"].endswith(f"{DEMO_PAROLA} ile giriş")
        )
        kullanan = service.anahtar_kullanimi(s, "ortak.demo_parola")
    assert DEMO_PAROLA not in str(kullanan)
    # Okuma görünümü kabulü düşürmez: görülen hash'le Testçi kabulü geçer.
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "accept", "icerik_hash": c["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["icerik"]["title"] == f"bayi1 / {PAROLA_ATFI} ile giriş"


def test_duzeltmede_maske_422_duz_parola_atfa_hash_yeni_icerikten(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog: int
) -> None:
    rid = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    _eski_case_yap(c["id"], title=f"bayi1 / {DEMO_PAROLA} ile giriş")
    (c,) = latest_cases(api, rid)

    # Maskeli içerik geri gelirse 422, açık Türkçe metin; içerik değişmez.
    maskeli = dict(c["icerik"], title="bayi1 / ••• ile giriş", priority="P1")
    r = _duzelt(api, c, maskeli)
    assert r.status_code == 422 and r.json()["detail"] == MASKELI_DUZELTME_METNI
    assert MASKELI_DUZELTME_METNI == "Gizli değer maskeli görünüyor; {veri:…} atfını kullanın"

    # Bitişik (atfa dönemeyen) düz gizli değer 422.
    r = _duzelt(api, c, dict(c["icerik"], expected_result=f"{DEMO_PAROLA}x reddedilir"))
    assert r.status_code == 422 and r.json()["detail"] == DUZ_GIZLI_DUZELTME_METNI

    # Görünümü değiştirmeden göndermek "değişiklik" sayılmaz (atıf ↔ ham düz değer).
    r = _duzelt(api, c, c["icerik"])
    assert r.status_code == 422 and "aynı" in r.json()["detail"]

    # Yalnız öncelik değişir (v3 case: `risk` yok, 011 K18) ve bir alana parola düz yazılır:
    # atfa çevrilerek kaydedilir.
    yeni = dict(c["icerik"], priority="P1", expected_result=f"Katalog açılır ({DEMO_PAROLA})")
    r = _duzelt(api, c, yeni)
    assert r.status_code == 200, r.text
    beklenen = dict(yeni, expected_result=f"Katalog açılır ({PAROLA_ATFI})")
    assert r.json()["icerik"] == beklenen
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        assert tc.icerik == beklenen and DEMO_PAROLA not in str(tc.icerik)
        assert tc.icerik_hash == content_hash(beklenen) == r.json()["icerik_hash"]
        rev = s.scalars(
            select(Review).where(Review.nesne_id == tc.id).order_by(Review.sira.desc())
        ).first()
        # Ölçü görünüme göre: başlıktaki atıf dönüşümü "değişti" sayılmaz.
        assert "title" not in (rev.duzeltme_olculeri or {}).get("degisen_alanlar", [])
        assert "ortak.demo_parola" in rev.duzeltme_olculeri["veri_izi"]


def test_ide_taslak_basligi_da_atfa_eslenir(
    engine: Engine, make_user, make_requirement, katalog: int
) -> None:
    make_requirement()
    testci = make_user("tester")  # 012: IDE taslağını case.generate (Testçi) gönderir
    ide = Principal(testci.id, testci.kullanici_adi, "tester", kanal="ide", kapsam="submit")
    with session_scope() as s:
        sonuc = submit_drafts(s, "TPD-4", [case_icerik(title=f"{DEMO_PAROLA} ile giriş")], ide)
    (e,) = sonuc["eklenen"]
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(e["case_id"]))
        assert tc.icerik["title"] == f"{PAROLA_ATFI} ile giriş"
        assert tc.icerik_hash == content_hash(tc.icerik)


# ------------------------------------------------------------------- çakışma kâhini (#5)


def test_gizli_cakisma_reddi_aktor_basina_frenlenir(
    api: TestClient, make_user, katalog: int
) -> None:
    login(api, make_user("analyst"))
    for i in range(service.GIZLI_CAKISMA_SINIRI):
        r = api.post("/test-data", json={"anahtar": f"bayi.tahmin{i}.ad", "deger": DEMO_PAROLA})
        assert r.status_code == 422 and r.json()["detail"] == service.GIZLI_CAKISMA_METNI
    # Sınır doldu: değerden bağımsız yanıt (doğru ya da yanlış tahmin aynı 429).
    for deger in (DEMO_PAROLA, "Masum değer"):
        r = api.post("/test-data", json={"anahtar": "bayi.tahmin9.ad", "deger": deger})
        assert r.status_code == 429 and r.json()["detail"] == service.COK_DENEME_METNI
    # Başka aktör etkilenmez; sır hiçbir zaman açık değer olarak kaydedilmez.
    login(api, make_user("engineer"))
    r = api.post("/test-data", json={"anahtar": "bayi.baska.ad", "deger": "Masum değer"})
    assert r.status_code == 201, r.text
    assert DEMO_PAROLA not in str(api.get("/test-data").json())
