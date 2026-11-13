"""Gherkin dışa aktarımı (specs/011 F8/K14): anlık görüntü, sözdizimi, birleştirme, kaçış, uç.

Anlık görüntüler golden üretimlerinden (TPD-1, TPD-3, TPD-4, SERBEST) case'ler onaylanmış gibi
kurularak üretilir. Bilinçli bir kural değişikliğinden sonra güncellemek için:
`TP_UPDATE_GOLDEN=1 uv run pytest tests/unit/features/cases/test_gherkin.py`.

Sözdizimi `gherkin-official` ayrıştırıcısıyla (geliştirme bağımlılığı) doğrulanır; taslağın
kayıpsız olduğu, her örnek satırının açılmış hâlinin (pickle) case'in tek başına senaryosuyla
adım adım aynı olmasıyla gösterilir.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from gherkin.parser import Parser
from gherkin.pickles.compiler import Compiler
from gherkin.token_scanner import TokenScanner
from sqlalchemy import Engine

from tp_core.features.cases import gherkin, service
from tp_core.features.cases.gherkin import GherkinCase, plan_scenarios, render_feature, uygun_mu
from tp_core.gateway.testing import text_response
from tp_core.models import Requirement, TestCase, session_scope
from tp_core.workflow.service import SYSTEM, transition

from .helpers import case_icerik, eski_case_icerik, latest_cases, login, run_jobs, uretim_cikti

REPO = Path(__file__).resolve().parents[5]
GOLDEN_GIRDI = REPO / "rules" / "replay" / "case_generation" / "golden"
GOLDEN = Path(__file__).parent / "golden"
GOLDENLER = ("TPD-1", "TPD-3", "TPD-4", "SERBEST")
BASLIK = {
    "TPD-1": "Sepet ve sipariş",
    "TPD-3": "Katalogda ürün arama",
    "TPD-4": "Bayi girişi",
    "SERBEST": "Sepetten ürün kaldırma",
}


def _golden(ad: str) -> dict[str, Any]:
    return json.loads((GOLDEN_GIRDI / f"{ad}.json").read_text(encoding="utf-8"))


def _cid(ad: str, sira: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tp-gherkin-test/{ad}/{sira}"))


def _onayli(ad: str) -> list[GherkinCase]:
    """Golden'ın bütün case'leri onaylanmış gibi; Gherkin kuralı hazır olmayanları eler."""
    cases = _golden(ad)["output"]["cases"]
    return [
        GherkinCase(_cid(ad, i), c) for i, c in enumerate(cases, start=1) if uygun_mu("approved", c)
    ]


def _feature(ad: str, cases: list[GherkinCase] | None = None) -> str:
    g = _golden(ad)
    return render_feature(
        ad,
        BASLIK[ad],
        _onayli(ad) if cases is None else cases,
        g["input_match"]["acceptance_criteria"],
    )


def _ayristir(metin: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    belge = Parser().parse(TokenScanner(metin))
    belge["uri"] = "test.feature"
    return belge, Compiler().compile(belge)


def _pickle_ozeti(p: dict[str, Any]) -> list[tuple[str, str, Any]]:
    out = []
    for s in p["steps"]:
        arg = s.get("argument") or {}
        if "dataTable" in arg:
            ek: Any = [[h["value"] for h in r["cells"]] for r in arg["dataTable"]["rows"]]
        elif "docString" in arg:
            ek = arg["docString"]["content"]
        else:
            ek = None
        out.append((s["type"], s["text"], ek))
    return out


def _tp_etiketi(p: dict[str, Any]) -> str:
    (t,) = [t["name"] for t in p["tags"] if t["name"].startswith("@tp-")]
    return t[len("@tp-") :]


# ------------------------------------------------------------------ anlık görüntü + sözdizimi


@pytest.mark.parametrize("ad", GOLDENLER)
def test_golden_feature(ad: str) -> None:
    metin = _feature(ad)
    hedef = GOLDEN / f"{ad}.feature"
    if os.environ.get("TP_UPDATE_GOLDEN") == "1":
        hedef.parent.mkdir(exist_ok=True)
        hedef.write_text(metin, encoding="utf-8")
    assert metin == hedef.read_text(encoding="utf-8")


@pytest.mark.parametrize("ad", GOLDENLER)
def test_ayristirici_gecerli_ve_her_case_bir_kez(ad: str) -> None:
    cases = _onayli(ad)
    belge, pickles = _ayristir(_feature(ad))
    assert belge["feature"]["language"] == "tr"
    # Her case tam bir pickle (senaryo ya da örnek satırı) olur; kimliği @tp- etiketindedir.
    assert sorted(_tp_etiketi(p) for p in pickles) == sorted(c.id for c in cases)
    for p in pickles:
        assert {s["type"] for s in p["steps"]} >= {"Action", "Outcome"}


@pytest.mark.parametrize("ad", GOLDENLER)
def test_taslak_kayipsiz(ad: str) -> None:
    """Taslaktan açılan her örnek, case'in tek başına yazılmış senaryosuyla adım adım aynıdır."""
    cases = _onayli(ad)
    _, birlesik = _ayristir(_feature(ad))
    birlesik_by = {_tp_etiketi(p): p for p in birlesik}
    for c in cases:
        _, (tekil,) = _ayristir(render_feature(ad, BASLIK[ad], [c]))
        assert _pickle_ozeti(birlesik_by[c.id]) == _pickle_ozeti(tekil), c.icerik["title"]


def test_deterministik() -> None:
    assert _feature("TPD-1") == _feature("TPD-1")
    assert _feature("TPD-1").encode("utf-8") == (GOLDEN / "TPD-1.feature").read_bytes()


# ------------------------------------------------------------------ dahil etme


def test_uygunluk_kurali() -> None:
    hazir = case_icerik()
    assert uygun_mu("approved", hazir) and uygun_mu("published", hazir)
    for durum in ("draft", "rejected", "superseded"):
        assert not uygun_mu(durum, hazir)
    assert not uygun_mu("approved", {**hazir, "readiness": "assumption_dependent"})
    assert not uygun_mu("approved", {**hazir, "readiness": "blocked"})
    # Eski (v2) case hazır sayılır (K9).
    assert uygun_mu("approved", eski_case_icerik())
    assert not uygun_mu("approved", hazir, yalniz_yayinlanan=True)
    assert uygun_mu("published", hazir, yalniz_yayinlanan=True)


def test_tpd3_hazir_olmayanlar_dahil_degil() -> None:
    metin = _feature("TPD-3")
    assert "Arama alanı temizlenince" not in metin  # varsayıma bağlı
    assert "küçük harfle" not in metin  # engelli
    assert "# 3 case · 3 senaryo (0 örnek tablolu senaryo)" in metin


def test_eski_case_yazilir_ve_birlestirilmez() -> None:
    a = GherkinCase("a", eski_case_icerik(title="Eski bir"))
    b = GherkinCase("b", eski_case_icerik(title="Eski iki", steps=[]))
    metin = render_feature("K-1", "Eski", [a, b], ["AC1: x"])
    assert "Senaryo: Eski bir" in metin and "@AC1 @pozitif @tp-a" in metin
    assert "taslağı" not in metin
    _ayristir(metin)


# ------------------------------------------------------------------ birleştirme kuralı


def _bva(n: int, cid: str, **over: Any) -> GherkinCase:
    icerik = case_icerik(
        title=f"{n} adet",
        ref="AC2",
        type="boundary",
        technique=["BVA"],
        covers=[f"BV-{n}"],
        steps=[
            {"id": "S1", "action": "Sepeti aç", "data": None, "expected": "Sepet görünür"},
            {
                "id": "S2",
                "action": f"Adedi {n} yap",
                "data": f"P-001 × {n}",
                "expected": f"Sayaç {n} olur",
            },
        ],
        expected_result=f"Toplam {n * 25},00 TL",
        test_data=[
            {
                "name": "adet",
                "value": str(n),
                "class": f"BV-{n}",
                "synthetic": True,
                "is_attack_payload": False,
            }
        ],
    )
    icerik.update(over)
    return GherkinCase(cid, icerik)


def test_ayni_kalip_taslak_olur() -> None:
    cases = [_bva(5, "a"), _bva(6, "b"), _bva(7, "c")]
    assert len(plan_scenarios(cases)) == 1
    metin = render_feature("K-1", "x", cases)
    assert "Senaryo taslağı: AC2 · sınır değer analizi (BVA) — 3 örnek" in metin
    assert 'Eğer ki adedi <girdi> yaparsa (veri: "P-001 × <girdi>")' in metin
    assert "O zaman sayaç <girdi> olur" in metin
    assert "| teknik | bölüm_id | girdi | sınıf | beklenen" in metin
    _, pickles = _ayristir(metin)
    assert [p["steps"][-1]["text"] for p in pickles] == [
        "toplam 125,00 TL",
        "toplam 150,00 TL",
        "toplam 175,00 TL",
    ]


@pytest.mark.parametrize(
    ("degisiklik", "neden"),
    [
        ({"technique": ["EP"], "covers": ["EP-V1"]}, "birincil teknik farklı"),
        ({"priority": "P3"}, "öncelik farklı"),
        ({"acceptance_criteria_refs": ["AC3"]}, "AC farklı"),
        ({"preconditions": ["Başka ön koşul"]}, "ön koşul farklı"),
        ({"teardown": ["Sepeti boşalt"]}, "temizlik farklı"),
    ],
)
def test_grup_anahtari_farkli_birlestirmez(degisiklik: dict[str, Any], neden: str) -> None:
    plan = plan_scenarios([_bva(5, "a"), _bva(6, "b", **degisiklik)])
    assert len(plan) == 2, neden


def test_eylem_dizisi_farkliysa_birlestirmez() -> None:
    b = _bva(6, "b")
    b.icerik["steps"][1]["action"] = "Ürünü kataloğa dön ve başka bir ürün seçip adedi 6 yap"
    assert len(plan_scenarios([_bva(5, "a"), b])) == 2


def test_ayni_girdili_tekrar_birlestirilmez() -> None:
    a, b = _bva(5, "a"), _bva(5, "b")
    b.icerik["title"] = "Tekrar"
    assert len(plan_scenarios([a, b])) == 2


def test_yer_tutucu_cakismasi_birlestirmez() -> None:
    b = _bva(6, "b")
    b.icerik["steps"][0]["expected"] = "Sepet <girdi> görünür"
    metin = render_feature("K-1", "x", [_bva(5, "a"), b])
    assert "taslağı" not in metin
    # Tekil senaryoda `<` `>` düz metindir (yer tutucu yok).
    _, pickles = _ayristir(metin)
    assert any(s["text"] == "sepet <girdi> görünür" for p in pickles for s in p["steps"])


def test_tirnakli_veri_birlestirmez_ve_docstring_olur() -> None:
    a, b = _bva(5, "a"), _bva(6, "b")
    for c in (a, b):
        c.icerik["steps"][1]["data"] = c.icerik["steps"][1]["data"] + ' "kutu"'
    metin = render_feature("K-1", "x", [a, b])
    assert "taslağı" not in metin
    _, pickles = _ayristir(metin)
    (doc,) = [s for s in pickles[0]["steps"] if "docString" in (s.get("argument") or {})]
    assert doc["argument"]["docString"]["content"] == 'P-001 × 5 "kutu"'


# ------------------------------------------------------------------ kaçış


def test_tablo_hucresi_kacisi() -> None:
    assert gherkin.tablo_hucresi("a|b") == "a\\|b"
    assert gherkin.tablo_hucresi("a\nb\r\nc") == "a\\nb\\nc"
    assert gherkin.tablo_hucresi("c:\\yol") == "c:\\\\yol"


def test_saldiri_verisi_kacisli_ve_isaretli() -> None:
    yuk = '\' OR 1=1 --|\n<script>alert("x")</script>\\'
    c = GherkinCase(
        "s",
        case_icerik(
            title="Saldırı girdisi reddedilir",
            type="negative",
            technique=["EG"],
            covers=["EG-1"],
            test_data=[
                {
                    "name": "kötü niyetli kullanıcı adı",
                    "value": yuk,
                    "class": "EG-1",
                    "synthetic": True,
                    "is_attack_payload": True,
                }
            ],
        ),
    )
    metin = render_feature("K-1", "x", [c])
    satirlar = metin.splitlines()
    i = next(i for i, s in enumerate(satirlar) if "kötü niyetli" in s)
    assert satirlar[i - 1].strip() == "# güvenlik testi girdisi"
    assert "\n<script>" not in metin  # satır sonu kaçışlı, tek satır
    _, (p,) = _ayristir(metin)
    tablo = p["steps"][1]["argument"]["dataTable"]["rows"]
    assert tablo[1]["cells"][1]["value"] == yuk


def test_ozel_karakterler_ve_etiket() -> None:
    c = GherkinCase(
        "x",
        eski_case_icerik(
            title="# başta diyez\nve satır sonu",
            acceptance_criteria_refs=["AC 1"],
            preconditions=["@etiket gibi", "| boru gibi"],
            steps=[
                {
                    "id": "S1",
                    "action": "Not yaz",
                    "data": 'çok\nsatır """ veri',
                    "expected": "# kaydedilir",
                }
            ],
        ),
    )
    metin = render_feature("K #1", "Başlık\nalt", [c], ["AC1: Bir"])
    assert "Senaryo: # başta diyez ve satır sonu" in metin
    assert "@AC1 @pozitif @tp-x" in metin
    belge, (p,) = _ayristir(metin)
    assert belge["feature"]["name"] == "K #1 — Başlık alt"
    adimlar = [(s["type"], s["text"]) for s in p["steps"]]
    assert adimlar[:2] == [("Context", "@etiket gibi"), ("Context", "| boru gibi")]
    assert p["steps"][2]["argument"]["docString"]["content"] == 'çok\nsatır """ veri'
    assert ("Outcome", "# kaydedilir") in adimlar


def test_temizlik_yorum_olarak_sonda() -> None:
    c = GherkinCase("t", case_icerik(teardown=["Çıkış yap", "Kaydı sil"]))
    metin = render_feature("K-1", "x", [c])
    son = metin.rstrip("\n").splitlines()[-2:]
    assert [s.strip() for s in son] == ["# Temizlik: Çıkış yap", "# Temizlik: Kaydı sil"]
    belge, (p,) = _ayristir(metin)
    assert all("Temizlik" not in s["text"] for s in p["steps"])
    assert sum("Temizlik" in y["text"] for y in belge["comments"]) == 2


def test_dosya_adi() -> None:
    assert gherkin.feature_filename("TPD-1") == "TPD-1.feature"
    assert gherkin.feature_filename('a"b/c') == "a_b_c.feature"


# ------------------------------------------------------------------ uç (gerçek Postgres)


@pytest.fixture
def uretilmis(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """TPD-4 için 3 v3 case (hazır, hazır, varsayıma bağlı) + 1 eski case; analist oturumu."""
    neg = {"type": "negative", "technique": ["EP"], "ref": "AC2"}
    cases = [
        case_icerik(),
        case_icerik(title="Hatalı parola mesajı", covers=["EP-I1"], **neg),
        case_icerik(
            title="Kilitli hesap",
            covers=["EP-I2"],
            readiness="assumption_dependent",
            assumption_refs=["A1"],
            **neg,
        ),
    ]
    ozet = {"assumptions": [{"id": "A1", "statement": "Kilit 3 denemede", "owner": ""}]}
    fake_gateway([text_response(uretim_cikti(cases, **ozet))])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    with session_scope() as s:
        service.store_cases(
            s,
            s.get(Requirement, rid),
            [eski_case_icerik(title="Eski biçimli case", ref="AC2")],
            uretim_no=7,
            kanal="portal",
            ai_call_id=None,
            uretim_modu="replay",
        )
    return rid


def _onayla(api: TestClient, c: dict[str, Any]) -> None:
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )
    assert r.status_code == 200, r.text


def test_uc_uygun_case_yoksa_404(api: TestClient, uretilmis) -> None:
    r = api.get(f"/requirements/{uretilmis}/cases.feature")
    assert r.status_code == 404
    assert "onaylı" in r.json()["detail"]


def test_uc_yalniz_onayli_ve_hazir_case(api: TestClient, uretilmis, make_user) -> None:
    rid = uretilmis
    hazir, hatali, varsayim, eski = latest_cases(api, rid)
    for c in (hazir, eski):
        _onayla(api, c)
    r = api.get(f"/requirements/{rid}/cases.feature")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="TPD-4.feature"'
    assert (r.headers["x-tp-case-sayisi"], r.headers["x-tp-senaryo-sayisi"]) == ("2", "2")
    metin = r.text
    assert metin.startswith("# language: tr\n")
    assert f"@tp-{hazir['id']}" in metin and f"@tp-{eski['id']}" in metin
    # Taslak (onaysız) ve varsayıma bağlı case dahil değil.
    assert hatali["id"] not in metin and varsayim["id"] not in metin
    _ayristir(metin)
    # Herkes okuyabilir (okuma yetkisi deseni): PO da indirir.
    login(api, make_user("po"))
    assert r.text == api.get(f"/requirements/{rid}/cases.feature").text


def test_uc_yalniz_yayinlanan(api: TestClient, uretilmis) -> None:
    rid = uretilmis
    hazir, *_ = latest_cases(api, rid)
    _onayla(api, hazir)
    r = api.get(f"/requirements/{rid}/cases.feature", params={"yalniz_yayinlanan": 1})
    assert r.status_code == 404 and "Yayınlanmış case yok" in r.json()["detail"]
    with session_scope() as s:
        transition(s, s.get(TestCase, uuid.UUID(hazir["id"])), "published", SYSTEM, "approved")
    r = api.get(f"/requirements/{rid}/cases.feature", params={"yalniz_yayinlanan": 1})
    assert r.status_code == 200 and f"@tp-{hazir['id']}" in r.text


def test_uc_onaydan_sonra_degisen_icerik_dahil_degil(api: TestClient, uretilmis) -> None:
    rid = uretilmis
    hazir, *_ = latest_cases(api, rid)
    _onayla(api, hazir)
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(hazir["id"]))
        icerik = copy.deepcopy(tc.icerik)
        icerik["title"] = "Onaysız değişiklik"
        tc.icerik = icerik
        tc.icerik_hash = "baska-hash"
    assert api.get(f"/requirements/{rid}/cases.feature").status_code == 404


def test_uc_gereksinim_degistiyse_409(api: TestClient, uretilmis) -> None:
    rid = uretilmis
    hazir, *_ = latest_cases(api, rid)
    _onayla(api, hazir)
    with session_scope() as s:
        s.get(Requirement, rid).baslik = "Story değişti"
    r = api.get(f"/requirements/{rid}/cases.feature")
    assert r.status_code == 409


def test_uc_bilinmeyen_gereksinim_404(api: TestClient, make_user) -> None:
    login(api, make_user("analyst"))
    assert api.get(f"/requirements/{uuid.uuid4()}/cases.feature").status_code == 404


# ------------------------------------------------------------------ doğal adım dili


@pytest.mark.parametrize(
    ("eylem", "beklenen"),
    [
        ("Giriş sayfasını aç", "giriş sayfasını açarsa"),
        ('"Giriş yap" butonuna bas', '"Giriş yap" butonuna basarsa'),
        ("Üst menüden sepete git", "üst menüden sepete giderse"),
        ("Arama alanındaki metni sil", "arama alanındaki metni silerse"),
        ("Ürünü sepete ekle", "ürünü sepete eklerse"),
        ("Fiyatı kontrol et", "fiyatı kontrol ederse"),
        ("Formu kaydet", "formu kaydederse"),
        ("Kuponu al", "kuponu alırsa"),
        ("Satırı kaldır", "satırı kaldırırsa"),
        ("Sepet sayfası açılır", "sepet sayfası açılırsa"),
        ("Enter tuşuyla", "enter tuşuyla"),  # araç eki: fiil değil, değişmez
        ("Kullanıcı adı ve parola", "kullanıcı adı ve parola"),
        ("Adedi <girdi>", "adedi <girdi>"),
        ("Portakal Gazozu kartını aç", "Portakal Gazozu kartını açarsa"),  # özel ad korunur
        ("P-001 kartını aç", "P-001 kartını açarsa"),
        ("IBAN alanını doldur", "IBAN alanını doldurursa"),
        ("Islak zemin uyarısını kapat", "ıslak zemin uyarısını kapatırsa"),
    ],
)
def test_eylem_kosul_kipi_ve_kucuk_harf(eylem: str, beklenen: str) -> None:
    assert gherkin._eylem_metni(eylem) == beklenen


def test_adim_verisi_test_verisinde_ise_yinelenmez() -> None:
    c = GherkinCase(
        "v",
        case_icerik(
            test_data=[
                {
                    "name": "bayi kullanıcısı",
                    "value": "bayi1 / Demo123!",
                    "class": "EP-V1",
                    "synthetic": True,
                    "is_attack_payload": False,
                }
            ],
        ),
    )
    metin = render_feature("K-1", "x", [c])
    assert metin.count("bayi1 / Demo123!") == 1  # yalnız test verisi tablosunda
    assert (
        "Eğer ki kullanıcı adı ve parolayı gir, Giriş'e basarsa (test verisi: bayi kullanıcısı)"
        in metin
    )
    assert "Diyelim ki bayi1 kullanıcısı tanımlı" in metin
    assert "O zaman form görünür" in metin
    _ayristir(metin)


def test_saldiri_verisi_adimda_tekrarlanmaz() -> None:
    yuk = "' OR 1=1 --"
    c = GherkinCase(
        "s2",
        case_icerik(
            steps=[
                {"id": "S1", "action": "Kullanıcı adına yaz", "data": yuk, "expected": "Reddedilir"}
            ],
            test_data=[
                {
                    "name": "kötü niyetli girdi",
                    "value": yuk,
                    "class": "EG-1",
                    "synthetic": True,
                    "is_attack_payload": True,
                }
            ],
        ),
    )
    metin = render_feature("K-1", "x", [c])
    assert metin.count(yuk) == 1
    assert "Eğer ki kullanıcı adına yazarsa (test verisi: kötü niyetli girdi)" in metin
