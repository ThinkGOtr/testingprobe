"""Case üretim girdisi: test verisi bloğu (demoapp_ro), PO cevapları + soruları (§5, §8.2)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.unit.features.requirements.conftest import demoapp_ro_url  # noqa: F401 (fikstür)
from tp_core.features.cases import service, testdata
from tp_core.features.requirements.datatools import DemoDb
from tp_core.gateway.testing import text_response
from tp_core.models import Requirement, RequirementReview, session_scope

from .helpers import case_icerik, login, run_jobs

GOLDEN = Path(__file__).resolve().parents[5] / "rules" / "replay" / "case_generation" / "golden"


@pytest.fixture
def demo_sorgu(demoapp_ro_url: str):  # noqa: F811
    db = DemoDb(demoapp_ro_url)
    testdata.set_query_factory(lambda: lambda sql: db.query(sql).rows)
    yield
    testdata.set_query_factory(None)


def test_tl_bicimi() -> None:
    assert testdata.tl("25") == "25,00 TL"
    assert testdata.tl("1250.5") == "1.250,50 TL"
    assert testdata.tl("750.00") == "750,00 TL"


def test_test_verisi_blogu_demoapp_ro_dan_deterministik(demo_sorgu) -> None:
    blok = testdata.block()
    assert blok.startswith('<untrusted kind="data" source="testdata:demo-app"')
    assert blok == testdata.block()  # aynı veri → aynı metin
    for parca in (
        'bayi1 / Demo123! — bayi adı "Merkez Bayi", kredi limiti 2.000,00 TL',
        "bayi2 / Demo123!",
        "500,00 TL",
        'P-001 · "Portakal Gazozu 1L" · 25,00 TL',
        'P-004 · "Şeftalili Soğuk Çay 1L" · 30,00 TL',
        "6 al 1 bedava",
        "min_siparis_tutari = 750.00 (750,00 TL)",
        '"Siparişi onayla"',
        '"Sepete ekle"',
    ):
        assert parca in blok, parca
    assert "parola_hash" not in blok


def test_golden_literalleri_test_verisi_blogunda(demo_sorgu) -> None:
    """Golden case'lerdeki kimlik, bayi adı, ürün, birim fiyat ve etiketler girdide bulunur."""
    blok = testdata.block()
    for ad in ("TPD-1.json", "SERBEST.json"):
        yol = GOLDEN / ad
        if not yol.is_file():
            continue
        metin = json.dumps(
            json.loads(yol.read_text(encoding="utf-8"))["output"], ensure_ascii=False
        )
        for kullanici in set(re.findall(r"\bbayi\d\b", metin)):
            assert f"{kullanici} / " in blok
        if "Demo123!" in metin:
            assert "Demo123!" in blok
        for bayi in set(re.findall(r"(Merkez Bayi|Sahil Bayi)", metin)):
            assert bayi in blok, bayi
        for kod in set(re.findall(r"\bP-\d{3}\b", metin)):
            assert f"{kod} · " in blok, kod
        for etiket in ("Siparişi onayla", "Sepete ekle"):
            if etiket in metin:
                assert etiket in blok
        # Birim fiyatlar ve limitler blokta; toplamlar bunlardan + AC'den hesaplanır.
        assert "25,00 TL" in blok and "750,00 TL" in blok


def test_veritabani_yoksa_blok_sabit_bilgiyle_doner() -> None:
    testdata.set_query_factory(lambda: None)
    try:
        blok = testdata.block()
    finally:
        testdata.set_query_factory(None)
    assert "Veritabanı okunamadı" in blok and "Demo123!" in blok and "Siparişi onayla" in blok


def test_po_cevaplari_sorulariyla_okunur_kimlik_ve_zaman_gitmez() -> None:
    sorular = [
        {
            "id": "Q1",
            "type": "conflict",
            "text": "Kampanyalı siparişte minimum aranır mı?",
            "ac_ref": "AC6",
        },
        {
            "id": "Q3",
            "type": "missing_ac",
            "text": "Kredi limiti hangi tutara göre?",
            "ac_ref": "AC4",
        },
    ]
    cevaplar = [
        {
            "id": "20005",
            "metin": "Q1: kampanyalı siparişte minimum aranmaz. Q3: indirim düşülmüş toplam.",
            "yazar": "po@sim.local",
            "zaman": "2026-10-30T23:01:02+00:00",
        }
    ]
    metin = service._po_cevaplari_metni(cevaplar, sorular)
    assert "Q1 (AC6): Kampanyalı siparişte minimum aranır mı?" in metin
    assert "Q3 (AC4): Kredi limiti hangi tutara göre?" in metin
    assert "Cevap (po@sim.local): Q1: kampanyalı" in metin
    assert "20005" not in metin and "2026-10-30" not in metin and "{" not in metin
    assert metin.index("Q1 (AC6)") < metin.index("Cevap")


def test_uretim_girdisi_soru_cevap_ve_test_verisi_bloklarini_tasir(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    provider = fake_gateway(
        [text_response({"cases": [case_icerik(), case_icerik(title="Hatalı", ref="AC2")]})]
    )
    rid = make_requirement(
        po_cevaplari=[{"id": "9", "metin": "Kilit yok", "yazar": "po@x", "zaman": "2026-01-01"}]
    )
    with session_scope() as s:
        s.add(
            RequirementReview(
                requirement_id=rid,
                sorular=[
                    {
                        "id": "Q1",
                        "type": "ambiguity",
                        "text": "Hesap kilitlenir mi?",
                        "ac_ref": "AC2",
                    }
                ],
                verdict="needs_po",
            )
        )
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    istek = provider.requests[0].messages[0]["content"]
    po_blok = istek[istek.index('source="jira:TPD-4:po"') :]
    assert "Q1 (AC2): Hesap kilitlenir mi?" in po_blok and "Cevap (po@x): Kilit yok" in po_blok
    assert '"id"' not in po_blok.split("</untrusted")[0]
    assert 'source="testdata:demo-app"' in istek
    # Story bloğu (replay eşleşmesinin okuduğu tek kaynak) en başta, değişmeden.
    assert istek.index('source="jira:TPD-4"') < istek.index('source="testdata:demo-app"')
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "cases_ready"
