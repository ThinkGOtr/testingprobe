"""013 review turu 4: başlık atfı `veri`/kullanımda (F2×F3), kısa sır kuralı (case görünümü,
düzeltme denetimi, render taraması), düzeltme yolundaki gizli değer kâhini (sıra + fren)."""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.cases.helpers import case_icerik, latest_cases
from tests.unit.features.codegen.test_checks import RULES, golden_case, golden_mapping
from tests.unit.features.codegen.test_render import girdi
from tp_core.features.cases.service import DUZ_GIZLI_DUZELTME_METNI
from tp_core.features.codegen import render
from tp_core.features.testveri import atif, service
from tp_core.models import TestCase, session_scope

from .conftest import DEMO_PAROLA
from .test_guvenlik_tur3 import PAROLA_ATFI, _duzelt, _eski_case_yap, _uret

PIN = "1234"
PIN_SIRRI = "TP_TESTVERI_PIN"


# ----------------------------------------------------------------------------- saf fonksiyonlar


def test_kisa_sir_ilgisiz_metni_bozmaz_uzun_bitisik_sir_yakalanir() -> None:
    case = case_icerik(
        title="SKU-12345 siparişi",
        expected_result=f"PIN {PIN} kabul; {DEMO_PAROLA}x reddedilir",
        tags=["SKU-12345"],
    )
    g = atif.case_gorunum(case, {PIN: "ortak.pin"}, [PIN, DEMO_PAROLA])
    assert g["title"] == "SKU-12345 siparişi" and g["tags"] == ["SKU-12345"]
    # Kelime sınırındaki kısa sır atfa döner; bitişik uzun sır API'de düz dönmez (K19).
    assert g["expected_result"] == "PIN {veri:ortak.pin} kabul; •••x reddedilir"
    assert not atif.maske_iceriyor_mu(atif.case_gorunum(case_icerik(title="SKU-12345"), {}, [PIN]))
    assert not atif.gizli_kalan(case_icerik(title="SKU-12345", tags=["0123456789"]), [PIN])
    assert atif.gizli_kalan(case_icerik(expected_result=f"{DEMO_PAROLA}x"), [DEMO_PAROLA])
    # Render taraması: kısa sır kelime sınırlı, uzun sır alt dize.
    assert atif.gizli_geciyor_mu("SKU-12345 / tel 0123456789", [PIN]) == []
    assert atif.gizli_geciyor_mu(f"pin: {PIN}", [PIN]) == [PIN]
    assert atif.gizli_geciyor_mu(f"{DEMO_PAROLA}x", [DEMO_PAROLA]) == [DEMO_PAROLA]
    # Case dışı metin maskesi (PR/log/bug) tam alt dize kalır.
    assert atif.maskele("SKU-12345", [PIN]) == "SKU-•••5"


def test_render_kisa_sirda_durmaz_uzun_bitisik_sirda_durur() -> None:
    case = copy.deepcopy(golden_case(2))
    case["title"] = "SKU-12345 siparişi ile giriş"
    # Kısa sır ilgisiz metinde geçiyor: tarama kod üretimini durdurmaz (etiket maskesi case dışı
    # metin kuralıyla alt dize kalır).
    r = render.render_test(girdi(2, case=case, gizli_taranacak=(PIN,)), RULES)
    assert "siparişi ile giriş" in r.content
    # Bitişik uzun sır (kod argümanında "Demo123!x") taramada yine yakalanır: kod üretimi durur.
    eslem = copy.deepcopy(golden_mapping(2))
    for m in eslem["step_mapping"]:
        m["args"] = [f"{a}x" if a == DEMO_PAROLA else a for a in m["args"]]
    with pytest.raises(render.GizliSizinti):
        render.render_test(
            girdi(
                2,
                mapping=eslem,
                gizli_ortam={DEMO_PAROLA: "TP_TESTVERI_DEMO_PAROLA"},
                gizli_taranacak=(DEMO_PAROLA, PIN),
            ),
            RULES,
        )


# --------------------------------------------------------------------------------- case API


@pytest.fixture
def pin(engine: Engine, katalog: int, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(PIN_SIRRI, PIN)
    with session_scope() as s:
        service.olustur(s, {"anahtar": "ortak.pin", "gizli": True, "sir_adi": PIN_SIRRI}, "test")
    return PIN


def test_kisa_sirli_case_gorunumde_bozulmaz_duzeltilebilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, pin: str
) -> None:
    rid = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    _eski_case_yap(c["id"], title="SKU-12345 siparişi", expected_result="Sipariş SKU-12345 oluşur")
    (c,) = latest_cases(api, rid)
    assert c["icerik"]["title"] == "SKU-12345 siparişi"
    assert c["icerik"]["expected_result"] == "Sipariş SKU-12345 oluşur"
    assert "•••" not in str(c["icerik"])
    r = _duzelt(api, c, dict(c["icerik"], risk="high"))
    assert r.status_code == 200, r.text
    assert r.json()["icerik"]["title"] == "SKU-12345 siparişi"


def test_baslik_atfi_veri_ve_kullanimda(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog: int
) -> None:
    """F2×F3: yalnız başlıkta duran gizli atıf `veri`de var; silme korumasında sayılır."""
    rid = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    _eski_case_yap(
        c["id"],
        title=f"{PAROLA_ATFI} ile giriş",
        steps=[{"id": "S1", "action": "Giriş yap", "data": "bayi1", "expected": "Katalog açılır"}],
    )
    (c,) = latest_cases(api, rid)
    assert atif.case_atiflari(c["icerik"]) == []  # içerik alanlarında atıf yok
    assert c["veri"]["ortak.demo_parola"] == {"deger": None, "gizli": True, "surum": 1, "var": True}
    with session_scope() as s:
        assert [k["case_id"] for k in service.anahtar_kullanimi(s, "ortak.demo_parola")] == [
            c["id"]
        ]
    kayit = next(k for k in api.get("/test-data").json() if k["anahtar"] == "ortak.demo_parola")
    r = api.delete(f"/test-data/{kayit['id']}", params={"beklenen_surum": kayit["surum"]})
    assert r.status_code == 409 and r.json()["kullanan"][0]["case_id"] == c["id"]


def _duzeltme_olaylari() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [
            dict(o)
            for (o,) in s.execute(
                text("SELECT ozet FROM audit_event WHERE eylem = 'testveri.gizli_duzeltme'")
            )
        ]


def test_duzeltme_kahini_once_sema_sonra_gizli(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog: int
) -> None:
    rid = _uret(api, engine, make_user, make_requirement, fake_gateway, [case_icerik()])
    (c,) = latest_cases(api, rid)
    yanitlar = []
    for aday in (f"x{DEMO_PAROLA}x", "xYanlis1x", DEMO_PAROLA, "Yanlis1"):
        govde = dict(c["icerik"], expected_result=f"{aday} reddedilir", acceptance_criteria_refs=[])
        r = _duzelt(api, c, govde)
        assert r.status_code == 422
        yanitlar.append(r.json())
    # Şema hatalı gövdede yanıt adaydan bağımsız; gizli değer işlemi yapılmaz, iz/fren yok.
    assert all(y == yanitlar[0] for y in yanitlar)
    assert yanitlar[0]["detail"].startswith("Düzenlenen case şemaya uymuyor")
    assert _duzeltme_olaylari() == []
    with session_scope() as s:
        assert DEMO_PAROLA not in str(s.get(TestCase, uuid.UUID(c["id"])).icerik)


def test_duzeltme_gizli_donusum_ve_red_denetime_ve_frene_sayilir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, katalog: int
) -> None:
    sinir = service.GIZLI_CAKISMA_SINIRI
    cases = [case_icerik(title=f"Giriş senaryosu {i}") for i in range(sinir + 1)]
    rid = _uret(api, engine, make_user, make_requirement, fake_gateway, cases)
    caseler = latest_cases(api, rid)
    assert len(caseler) == sinir + 1
    # 1) düz parola atfa çevrilir (kaydedilir, frene sayılır); 2) bitişik → DUZ_GIZLI reddi.
    r = _duzelt(api, caseler[0], dict(caseler[0]["icerik"], expected_result=f"{DEMO_PAROLA} ok"))
    assert r.status_code == 200, r.text
    assert r.json()["icerik"]["expected_result"] == f"{PAROLA_ATFI} ok"
    for c in caseler[1:sinir]:
        r = _duzelt(api, c, dict(c["icerik"], expected_result=f"{DEMO_PAROLA}x ok"))
        assert r.status_code == 422 and r.json()["detail"] == DUZ_GIZLI_DUZELTME_METNI
    olaylar = _duzeltme_olaylari()
    assert len(olaylar) == sinir
    assert olaylar[0] == {"case_id": caseler[0]["id"], "anahtar": ["ortak.demo_parola"]}
    assert DEMO_PAROLA not in str(olaylar)
    # Fren doldu: gizli değer içermeyen düzeltme de değerden bağımsız 429.
    son = caseler[sinir]
    for deger in (DEMO_PAROLA, "Masum sonuç"):
        r = _duzelt(api, son, dict(son["icerik"], expected_result=deger))
        assert r.status_code == 429 and r.json()["detail"] == service.COK_DENEME_METNI
    # Katalog yolu da aynı kovayı paylaşır.
    r = api.post("/test-data", json={"anahtar": "bayi.yeni.ad", "deger": "Masum değer"})
    assert r.status_code == 429
