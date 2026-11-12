"""Değer çıkarma girdisi (bağımsızlık kuralı 2) ve `case_facts` REPLAY golden'ları — DB'siz."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tp_core.features.oracle import cikarma
from tp_core.features.oracle import dogrulama as d
from tp_core.gateway import Gateway, ReplayStore, load_model_table, load_schema
from tp_core.gateway.eval_set import check_output, load_set, run_set
from tp_core.gateway.matching import untrusted_blocks
from tp_core.gateway.testing import InMemoryCallRecorder

from . import tpd1

RULES = tpd1.RULES


def _mesaj(n: int = 2) -> str:
    case = tpd1.tpd1_cases()[n - 1]
    msgs = cikarma.facts_messages(case, cikarma.case_ref("TPD-1", n), tpd1.kolon_girdisi())
    assert len(msgs) == 1 and msgs[0].role == "user"
    return str(msgs[0].content)


def test_cikarma_girdisi_yalniz_kolon_tanimlarini_tasir() -> None:
    """Bağımsızlık kuralı 2: satır koşulu, çıktı ifadesi, tolerans, tablo açıklaması gitmez."""
    metin = _mesaj()
    for tablo in tpd1.TABLOLAR.values():
        kolon_adlari = {k["ad"] for k in tablo["girdiler"] + tablo["ciktilar"]}
        for satir in tablo["satirlar"]:
            sabit = ("dogru", "yanlis")  # sabitler ve yalın sayılar case metninde de geçer
            if satir["kosul"] not in kolon_adlari and satir["kosul"] not in sabit:
                assert satir["kosul"] not in metin  # yalın kolon adı koşulu ad olarak görünür
            for ifade in satir["cikti"].values():
                if ifade not in sabit and not ifade.isdigit():
                    assert ifade not in metin, ifade
            assert f'"{satir["id"]}"' not in metin
        assert tablo["aciklama"] not in metin
        assert "tolerans" not in metin and "satirlar" not in metin and "kosul" not in metin
        for kolon in tablo["girdiler"] + tablo["ciktilar"]:
            assert f'"ad": "{kolon["ad"]}"' in metin  # kolon adı görünür
    bloklar = untrusted_blocks([{"role": "user", "content": metin}])
    assert [b.source for b in bloklar] == ["case:TPD-1-C2", "karar-tablosu:kolonlar"]
    kolonlar = json.loads(bloklar[1].body)
    assert [t["ref"] for t in kolonlar] == ["T1", "T2"]
    assert set(kolonlar[0]) == {"ref", "id", "ad", "girdiler", "ciktilar"}
    for t in kolonlar:
        for k in t["girdiler"] + t["ciktilar"]:
            assert set(k) <= {"ad", "tur", "birim", "aciklama"}


def test_replay_anahtari_case_duzeyinde() -> None:
    assert cikarma.replay_key_for("TPD-1", 2) == {"name": "TPD-1-C2", "jira_key": "TPD-1"}
    assert cikarma.replay_key_for(None, 3) == {"name": "SERBEST-C3", "jira_key": "SERBEST"}


def test_golden_dosyalari_kurucunun_ciktisi() -> None:
    """Golden'lar `tpd1.py`'den üretilir: `python -m tests.unit.features.oracle.tpd1`."""
    beklenen = tpd1.build_goldens()
    kok = tpd1.golden_dir()
    var = {str(p.relative_to(kok).with_suffix("")) for p in kok.rglob("*.json")}
    assert var == set(beklenen)
    assert "f2-kod-hatasi/TPD-1-C3" in var  # demo ana yolunun C3'ü senaryo golden'ı
    for ad, data in beklenen.items():
        stored = (tpd1.golden_dir() / f"{ad}.json").read_text(encoding="utf-8")
        assert stored == tpd1.dump(data), f"{ad} bayat; yeniden üretin"


def _store() -> ReplayStore:
    return ReplayStore(RULES / "replay")


@pytest.mark.parametrize(
    ("n", "senaryo"),
    [*((n, None) for n in sorted(tpd1.OLGULAR)), *((n, tpd1.SENARYO) for n in range(1, 11))],
)
def test_golden_tpd1_girdisiyle_eslesir_ve_sonuc_verir(n: int, senaryo: str | None) -> None:
    """Ana golden'lar (fix_doc + değişmeyen case'ler) ve demo ana yolu (f2-kod-hatasi: C3 senaryo
    golden'ından, diğerleri ana golden'dan) story tablolarıyla beklenen sonucu verir."""
    case = tpd1.tpd1_cases(senaryo)[n - 1]
    tablolar = [d.Tablo(tpd1.tablo_id(k), f"T{k}", t["ad"], t) for k, t in tpd1.TABLOLAR.items()]
    kapsayan = [
        t for t in tablolar if set(t.icerik["ac_refs"]) & set(case["acceptance_criteria_refs"])
    ]
    beklenen = tpd1.BEKLENEN_SONUC_ANA_YOL if senaryo else tpd1.BEKLENEN_SONUC_FIX_DOC
    if not kapsayan:
        assert beklenen[n] == "kapsam_disi"  # model çağrılmaz
        return
    msgs = cikarma.facts_messages(
        case,
        cikarma.case_ref("TPD-1", n),
        [t for t in tpd1.kolon_girdisi() if t["ref"] in {x.ref for x in kapsayan}],
    )
    record, mode, _ = _store().lookup(
        "case_facts", "-", f"TPD-1-C{n}", [m.model_dump(mode="json") for m in msgs]
    )
    assert mode == "replay"
    if senaryo and n in tpd1.SENARYO_OLGULARI:
        assert record["golden"] == f"{senaryo}/TPD-1-C{n}"
    sonuc, ayr = d.degerlendir(case, kapsayan, record["output"])
    assert sonuc == beklenen[n]
    assert ayr["atilan_olgular"] == 0


def test_duzeltilmis_case_replay_miss_notr_cikti() -> None:
    """Case metni golden'ın beyanından farklıysa olgular dönmez: `groups: []`."""
    case = tpd1.tpd1_cases()[1]
    case = {**case, "expected_result": case["expected_result"].replace("150,00", "175,00")}
    msgs = cikarma.facts_messages(case, cikarma.case_ref("TPD-1", 2), tpd1.kolon_girdisi())
    record, mode, _ = _store().lookup(
        "case_facts", "-", "TPD-1-C2", [m.model_dump(mode="json") for m in msgs]
    )
    assert mode == "replay_miss"
    assert record["output"] == {"groups": []}
    tablolar = [d.Tablo(tpd1.tablo_id(1), "T1", "k", tpd1.T1)]
    assert d.degerlendir(case, tablolar, record["output"])[0] == d.KONTROL_EDILEMEDI


def test_golden_olmayan_case_notr() -> None:
    case = tpd1.tpd1_cases()[0]  # C1 (AC1) golden'ı yok
    msgs = cikarma.facts_messages(case, cikarma.case_ref("TPD-1", 1), tpd1.kolon_girdisi())
    record, mode, _ = _store().lookup(
        "case_facts", "-", "TPD-1-C1", [m.model_dump(mode="json") for m in msgs]
    )
    assert mode == "replay_miss" and record["output"] == {"groups": []}


def test_on_miss_notr_ve_sema_uyumlu() -> None:
    from jsonschema import Draft202012Validator

    on_miss = json.loads((RULES / "replay" / "case_facts" / "on_miss.json").read_text("utf-8"))
    assert on_miss["output"] == {"groups": []} and "policy" not in on_miss
    schema = load_schema(RULES, "case_facts")
    assert not list(Draft202012Validator(schema).iter_errors(on_miss["output"]))


def test_degerlendirme_seti_golden_ile_gecer(tmp_path: Path) -> None:
    data = load_set(RULES, "case-facts")
    for case in data["cases"]:
        record, mode, _ = _store().lookup(
            "case_facts", "-", case["replay_key"]["name"], case["messages"]
        )
        assert mode == "replay"
        assert check_output("case_facts", case["expect"], record["output"]) == [], case["id"]
    gw = Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(RULES),
        rules_dir=RULES,
        replay_store=_store(),
    )
    for r in run_set(gw, RULES, data):
        assert r.mode == "replay" and r.ok, (r.id, r.failures, r.error)


def test_degerlendirme_denetimi_eksik_olguyu_yakalar() -> None:
    data = load_set(RULES, "case-facts")
    case = data["cases"][0]
    assert check_output("case_facts", case["expect"], {"groups": []})
    yabanci = {"groups": [{"table_ref": "T9", "inputs": [], "expected": []}]}
    assert any("beyan dışı" in f for f in check_output("case_facts", case["expect"], yabanci))
