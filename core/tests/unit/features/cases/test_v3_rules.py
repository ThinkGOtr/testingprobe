"""Case şeması v3 deterministik kuralları (specs/011 §4.2): saf birim testleri (veritabanı yok)."""

from __future__ import annotations

import pytest

from tp_core.features.cases import metrics
from tp_core.features.cases.schema import (
    case_schema,
    consistency_problems,
    content_errors,
    coverage_matrix,
    is_legacy,
    normalize_ozet,
    readiness_of,
    set_problems,
    summary_schema,
    validate_case,
    validate_summary,
)

from .helpers import case_icerik, eski_case_icerik, ozet_icerik

ACS = ["AC1: Geçerli bilgilerle giriş yapılır", "AC2: Hatalı parolada mesaj gösterilir"]


def _ozet(**over):
    """İki AC'li örnek özet: bir ana akış, bir geçersiz bölüm, bir sınır değer."""
    ozet = ozet_icerik(
        open_questions=[{"id": "Q1", "question": "Kilit süresi nedir?", "owner": "PO"}],
        assumptions=[{"id": "A1", "statement": "Parola büyük/küçük harf duyarlı", "owner": ""}],
        coverage_items=[
            {"id": "UC-MF", "ac_ref": "AC1", "definition": "Ana akış: giriş", "valid": True},
            {"id": "EP-I1", "ac_ref": "AC2", "definition": "Hatalı parola", "valid": False},
            {"id": "BV-1", "ac_ref": "AC2", "definition": "Boş parola", "valid": False},
        ],
        negative_coverage=[
            {
                "item": "EP-I1",
                "decision": "tested",
                "rationale": "AC2 doğrudan ister; kilit süresi Q1 yanıtlanınca eklenir",
            },
            {"item": "BV-1", "decision": "out_of_scope", "rationale": "Form boş parolayı engeller"},
        ],
    )
    ozet.update(over)
    return ozet


def _negatif(**over):
    alanlar = {
        "title": "Hatalı parola mesajı",
        "type": "negative",
        "technique": ["EP"],
        "covers": ["EP-I1"],
        **over,
    }
    return case_icerik(ref="AC2", **alanlar)


# --------------------------------------------------------------------------- şema


def test_case_semasi_defs_tasir_ve_v3_case_gecerli() -> None:
    sema = case_schema()
    assert "coverage_item_id" in sema["$defs"]
    assert validate_case(case_icerik()) == []
    # `$ref` çözülür: desen dışı kapsam öğesi kimliği şema hatasıdır (çözümleme hatası değil).
    hatalar = validate_case(case_icerik(covers=["XX-1"]))
    assert hatalar and hatalar[0].startswith("covers/0")


@pytest.mark.parametrize(
    "eksik", ["technique", "covers", "priority", "readiness", "test_data", "teardown"]
)
def test_v3_alani_eksik_case_tam_semada_reddedilir(eksik: str) -> None:
    icerik = case_icerik()
    del icerik[eksik]
    assert any(eksik in h for h in validate_case(icerik))


def test_eski_case_legacy_dogrulama() -> None:
    eski = eski_case_icerik()
    assert is_legacy(eski) and readiness_of(eski) == "ready"
    assert not is_legacy(case_icerik()) and readiness_of(case_icerik(readiness="blocked")) == (
        "blocked"
    )
    # Tam şemada eski case eksiktir; legacy doğrulamada geçerlidir.
    assert validate_case(eski) and validate_case(eski, legacy=True) == []
    # Legacy'de de v2 kuralları sürer: zorunlu alan, boş beklenen sonuç, bilinmeyen alan.
    eksik = eski_case_icerik()
    del eksik["expected_result"]
    assert any("expected_result" in h for h in validate_case(eksik, legacy=True))
    assert validate_case(eski_case_icerik(expected_result=""), legacy=True)
    bos_adim = eski_case_icerik(steps=[{"id": "S1", "action": "a", "data": None, "expected": ""}])
    assert validate_case(bos_adim, legacy=True)
    assert validate_case(eski_case_icerik(ekstra=1), legacy=True)
    # v3 alanı varsa legacy'de de şemasına göre doğrulanır.
    assert validate_case(eski_case_icerik(priority="P2"), legacy=True) == []
    assert any(
        h.startswith("priority")
        for h in validate_case(eski_case_icerik(priority="P9"), legacy=True)
    )


def test_content_errors_legacy_ve_v3() -> None:
    assert content_errors(eski_case_icerik(), ACS, legacy=True) == []
    assert any("AC9" in h for h in content_errors(eski_case_icerik(ref="AC9"), ACS, legacy=True))
    # Tam v3: şema + AC + tutarlılık (özete karşı).
    assert content_errors(case_icerik(), ACS, ozet=_ozet()) == []
    hatalar = content_errors(case_icerik(covers=["UC-AF1"]), ACS, ozet=_ozet())
    assert hatalar == ["covers: tanımlı olmayan kapsam öğesi: UC-AF1"]
    # Eski biçim tam doğrulamada reddedilir (IDE taslağı her zaman tam v3 ister).
    assert content_errors(eski_case_icerik(), ACS)


def test_ozet_semasi_ve_normalize() -> None:
    assert "cases" not in summary_schema()["properties"]
    assert validate_summary(_ozet()) == []
    assert validate_summary({}) == []  # hiçbir liste zorunlu değil
    assert validate_summary({"cases": []})  # bilinmeyen anahtar
    assert validate_summary({"coverage_items": [{"id": "ZZ", "ac_ref": None}]})
    cift = validate_summary(
        {
            "open_questions": [
                {"id": "Q1", "question": "a", "owner": ""},
                {"id": "Q1", "question": "b", "owner": ""},
            ]
        }
    )
    assert cift == ["open_questions: yinelenen kimlik: Q1"]
    tam = normalize_ozet({"assumptions": [{"id": "A1", "statement": "x", "owner": ""}], "cases": 1})
    assert set(tam) == set(ozet_icerik()) and tam["config_matrix"] == {
        "parameters": [],
        "constraints": [],
    }


# ------------------------------------------------------------------- tutarlılık (case)


def test_tutarli_case_ve_eski_case_sorunsuz() -> None:
    assert consistency_problems(case_icerik(), _ozet()) == []
    assert consistency_problems(_negatif(), _ozet()) == []
    assert consistency_problems(eski_case_icerik(), None) == []
    assert consistency_problems(eski_case_icerik(), _ozet()) == []


def test_kural1_covers_tanimli_olmali_ozet_yoksa_atlanir() -> None:
    case = case_icerik(covers=["UC-MF", "UC-AF1"])
    assert consistency_problems(case, _ozet()) == ["covers: tanımlı olmayan kapsam öğesi: UC-AF1"]
    assert consistency_problems(case, None) == []


def test_kural2_teknik_ve_covers_oneki() -> None:
    (sorun,) = consistency_problems(case_icerik(technique=["UC", "BVA"]), _ozet())
    assert "BVA" in sorun and "BV-" in sorun
    assert (
        consistency_problems(
            case_icerik(technique=["UC", "BVA"], covers=["UC-MF", "BV-1"]), _ozet()
        )
        == []
    )


def test_kural3_atiflar_tanimli_olmali() -> None:
    case = case_icerik(readiness="assumption_dependent", assumption_refs=["A1", "A7"])
    assert consistency_problems(case, _ozet()) == ["assumption_refs: tanımlı olmayan varsayım: A7"]
    bloklu = case_icerik(readiness="blocked", open_question_refs=["Q9"], expected_result="")
    assert consistency_problems(bloklu, _ozet()) == [
        "open_question_refs: tanımlı olmayan açık soru: Q9"
    ]
    # Özet yoksa atıf çözülemez: tanımsız sayılır.
    assert consistency_problems(
        case_icerik(readiness="assumption_dependent", assumption_refs=["A1"]), None
    ) == ["assumption_refs: tanımlı olmayan varsayım: A1"]


def test_kural4_readiness() -> None:
    oz = _ozet()
    # ready: atıf yok, beklenenler dolu.
    assert any(
        "'ready'" in s for s in consistency_problems(case_icerik(assumption_refs=["A1"]), oz)
    )
    assert any(
        s.startswith("expected_result")
        for s in consistency_problems(case_icerik(expected_result="  "), oz)
    )
    adimlar = [{"id": "S1", "action": "a", "data": None, "expected": ""}]
    assert any("S1" in s for s in consistency_problems(case_icerik(steps=adimlar), oz))
    # assumption_dependent: varsayım atıfı dolu, beklenenler dolu.
    assert any(
        "assumption_dependent" in s
        for s in consistency_problems(case_icerik(readiness="assumption_dependent"), oz)
    )
    assert (
        consistency_problems(
            case_icerik(readiness="assumption_dependent", assumption_refs=["A1"]), oz
        )
        == []
    )
    # blocked: açık soru atıfı dolu, beklenen sonuç boş; adım beklenenleri boş olabilir.
    bloklu = case_icerik(
        readiness="blocked", open_question_refs=["Q1"], expected_result="", steps=adimlar
    )
    assert consistency_problems(bloklu, oz) == []
    assert any(
        "boş olmalı" in s
        for s in consistency_problems({**bloklu, "expected_result": "Hesap kilitlenir"}, oz)
    )
    assert any(
        "open_question_refs boş" in s
        for s in consistency_problems({**bloklu, "open_question_refs": []}, oz)
    )


def test_kural5_ve_6_test_verisi() -> None:
    oz = _ozet()
    veri = {
        "name": "sql_payload",
        "value": "' OR 1=1 --",
        "class": None,
        "synthetic": True,
        "is_attack_payload": True,
    }
    assert consistency_problems(_negatif(test_data=[veri]), oz) == []
    (sorun,) = consistency_problems(_negatif(test_data=[{**veri, "synthetic": False}]), oz)
    assert "sentetik" in sorun
    # Saldırı metni adımda (veri alanında, büyük/küçük harf ve boşluk farkıyla) yinelenmiş.
    adimlar = [
        {"id": "S1", "action": "Parolayı gir", "data": "'  or 1=1 --", "expected": "Mesaj çıkar"}
    ]
    (sorun,) = consistency_problems(_negatif(test_data=[veri], steps=adimlar), oz)
    assert "steps[S1].data" in sorun and "sql_payload" in sorun
    (sorun,) = consistency_problems(
        _negatif(test_data=[veri], title="Giriş ' OR 1=1 -- ile reddedilir"), oz
    )
    assert "title" in sorun
    # Saldırı verisi olmayan değer adımda geçebilir.
    normal = {**veri, "name": "parola", "value": "Demo123!", "is_attack_payload": False}
    assert consistency_problems(case_icerik(test_data=[normal]), oz) == []


# --------------------------------------------------------------------- set ve matris


def test_set_kurallari() -> None:
    cases = [case_icerik(), _negatif()]
    assert set_problems(cases, _ozet(), ACS) == []
    # Geçersiz öğenin kararı yok / birden çok.
    sorunlar = set_problems(cases, _ozet(negative_coverage=_ozet()["negative_coverage"][:1]), ACS)
    assert len(sorunlar) == 2 and all(s.startswith("BV-1") for s in sorunlar)
    assert "negatif kapsam kararı yok" in sorunlar[0] and "hiçbir case kapsamıyor" in sorunlar[1]
    cift = [*_ozet()["negative_coverage"], _ozet()["negative_coverage"][0]]
    assert any(
        "2 negatif kapsam kararı" in s
        for s in set_problems(cases, _ozet(negative_coverage=cift), ACS)
    )
    # `tested` kararlı öğeyi hiçbir case kapsamıyor.
    (s,) = set_problems([case_icerik(), case_icerik(title="B", ref="AC2")], _ozet(), ACS)
    assert s.startswith("EP-I1") and "tested" in s
    # Kapsanmayan geçerli öğe ve AC gerekçesiz; `not_covered` ile gerekçelenir.
    sorunlar = set_problems([_negatif()], _ozet(), ACS)
    assert [s.split(":")[0] for s in sorunlar] == ["UC-MF", "AC1"]
    gerekceli = _ozet(
        not_covered=[
            {"item": "UC-MF", "reason": "Case sınırı"},
            {"item": "ac 1", "reason": "Case sınırı"},
        ]
    )
    assert set_problems([_negatif()], gerekceli, ACS) == []
    # Tanımsız öğeye karar.
    fazla = [
        *_ozet()["negative_coverage"],
        {"item": "EG-9", "decision": "tested", "rationale": "x"},
    ]
    assert "negative_coverage: tanımlı olmayan kapsam öğesi: EG-9" in set_problems(
        cases, _ozet(negative_coverage=fazla), ACS
    )


def test_kapsam_matrisi_ve_oranlar() -> None:
    cases = [case_icerik(), _negatif(), eski_case_icerik(title="Eski", ref="AC2")]
    sonuc = coverage_matrix(cases, _ozet(not_covered=[{"item": "BV-1", "reason": "Sığmadı"}]), ACS)
    satir = {s["item"]: s for s in sonuc["satirlar"]}
    assert list(satir) == ["AC1", "AC2", "UC-MF", "EP-I1", "BV-1"]
    assert satir["AC1"] == {
        "item": "AC1",
        "tur": "ac",
        "tanim": "Geçerli bilgilerle giriş yapılır",
        "valid": None,
        "ac_ref": "AC1",
        "karar": None,
        "covered_by": [1],
        "covered_by_ready": [1],
        "gerekce": None,
    }
    assert satir["AC2"]["covered_by"] == [2, 3]  # eski case AC satırına sayılır
    assert satir["AC2"]["covered_by_ready"] == [2, 3]  # eski (v2) case hazır sayılır (K9)
    assert satir["EP-I1"] == {
        "item": "EP-I1",
        "tur": "oge",
        "tanim": "Hatalı parola",
        "valid": False,
        "ac_ref": "AC2",
        "karar": "tested",
        "covered_by": [2],
        "covered_by_ready": [2],
        "gerekce": "AC2 doğrudan ister; kilit süresi Q1 yanıtlanınca eklenir",
    }
    assert satir["BV-1"]["covered_by"] == [] and satir["BV-1"]["gerekce"] == "Sığmadı"
    assert satir["BV-1"]["karar"] == "out_of_scope"
    assert sonuc["oranlar"] == {
        "gereksinim_kapsami": {"kapsanan": 2, "toplam": 2, "oran": 1.0},
        "oge_kapsami": {"kapsanan": 2, "toplam": 3, "oran": 0.6667},
        "negatif_karar_kapsami": {"kapsanan": 2, "toplam": 2, "oran": 1.0},
        "hazir_gereksinim_kapsami": {"kapsanan": 2, "toplam": 2, "oran": 1.0},
        "hazir_oge_kapsami": {"kapsanan": 2, "toplam": 3, "oran": 0.6667},
    }


def test_kapsam_matrisi_hazir_olmayan_kapsami_tamamlamaz() -> None:
    """Varsayıma bağlı / soru bekleyen case satırı kapsar (`covered_by`) ama hazır kapsam
    (`covered_by_ready`, `hazir_*` oranları) yalnız `ready` case'lerle sayılır."""
    cases = [
        case_icerik(),
        _negatif(readiness="blocked", open_question_refs=["Q1"], expected_result=""),
    ]
    oz = _ozet(open_questions=[{"id": "Q1", "question": "?", "owner": "PO"}])
    sonuc = coverage_matrix(cases, oz, ACS)
    satir = {s["item"]: s for s in sonuc["satirlar"]}
    assert satir["EP-I1"]["covered_by"] == [2] and satir["EP-I1"]["covered_by_ready"] == []
    assert satir["AC2"]["covered_by_ready"] == []
    assert sonuc["oranlar"]["gereksinim_kapsami"]["oran"] == 1.0
    assert sonuc["oranlar"]["hazir_gereksinim_kapsami"] == {
        "kapsanan": 1,
        "toplam": 2,
        "oran": 0.5,
    }
    assert sonuc["oranlar"]["hazir_oge_kapsami"]["kapsanan"] == 1  # yalnız UC-MF


def test_kapsam_matrisi_ozetsiz_ve_acsiz() -> None:
    sonuc = coverage_matrix([eski_case_icerik()], None, ACS)
    assert [s["item"] for s in sonuc["satirlar"]] == ["AC1", "AC2"]
    assert sonuc["oranlar"]["gereksinim_kapsami"] == {"kapsanan": 1, "toplam": 2, "oran": 0.5}
    assert sonuc["oranlar"]["oge_kapsami"] == {"kapsanan": 0, "toplam": 0, "oran": None}
    assert coverage_matrix([], None, [])["oranlar"]["gereksinim_kapsami"]["oran"] is None


# --------------------------------------------------------------------- düzeltme ölçüsü


def test_olcu_alanlari_eski_casete_degismez() -> None:
    alanlar = metrics.fields(eski_case_icerik())
    assert set(alanlar) == {
        "title",
        "type",
        "risk",
        "acceptance_criteria_refs",
        "preconditions",
        "expected_result",
        "tags",
        *(f"steps[{i}].{a}" for i in (1, 2) for a in ("action", "data", "expected")),
    }
    assert set(metrics.display_fields(eski_case_icerik())) == set(alanlar)


def test_olcu_ve_fark_v3_alanlarini_kapsar() -> None:
    once = _negatif(
        test_data=[
            {
                "name": "parola",
                "value": "Yanlis1!",
                "class": "EP-I1",
                "synthetic": True,
                "is_attack_payload": False,
            }
        ]
    )
    assert {"technique", "covers", "priority", "readiness", "teardown"} <= set(metrics.fields(once))
    assert metrics.fields(once)["test_data[1].synthetic"] == "true"
    sonra = {
        **once,
        "priority": "P1",
        "readiness": "assumption_dependent",
        "assumption_refs": ["A1"],
        "teardown": ["Oturumu kapat"],
        "test_data": [{**once["test_data"][0], "value": "Yanlis2!"}],
    }
    olcu = metrics.edit_metrics(once, sonra)
    assert olcu["degisen_alanlar"] == [
        "assumption_refs",
        "priority",
        "readiness",
        "teardown",
        "test_data[1].value",
    ]
    fark = {f["alan"]: f for f in metrics.field_diff(once, sonra)}
    assert fark["priority"] == {
        "alan": "priority",
        "etiket": "Öncelik",
        "once": "P2",
        "sonra": "P1",
    }
    assert fark["readiness"]["etiket"] == "Hazır olma durumu"
    assert fark["test_data[1].value"]["etiket"] == "Test verisi 1 — değer"
    assert fark["teardown"]["sonra"] == "Oturumu kapat"
    # Liste sırası fark sayılmaz (teknik / kapsam öğeleri küme gibidir).
    cift = case_icerik(technique=["UC", "EP"], covers=["UC-MF", "EP-I1"])
    ters = case_icerik(technique=["EP", "UC"], covers=["EP-I1", "UC-MF"])
    assert (
        metrics.edit_metrics(cift, ters)["mesafe"] == 0.0 and metrics.field_diff(cift, ters) == []
    )
    # Eski case v3'e yükseltilirse eklenen alanlar farkta görünür.
    yukseltme = metrics.field_diff(eski_case_icerik(), case_icerik())
    assert {"technique", "covers", "readiness"} <= {f["alan"] for f in yukseltme}


# ------------------------------------------------- D3: kenar durumlar (AÇIK NOKTA, set kuralları)


def test_acik_nokta_yalniz_atifli_ve_hazir_olmayan_casete() -> None:
    from tp_core.features.cases.schema import consistency_problems

    beklenen = "Hata gösterilir (mesaj metni: AÇIK NOKTA)"
    hazir = _negatif(expected_result=beklenen)
    assert any("'ready' case 'AÇIK NOKTA'" in p for p in consistency_problems(hazir, _ozet()))
    varsayimli = _negatif(
        expected_result=beklenen.replace("AÇIK", "Açık"),
        readiness="assumption_dependent",
        assumption_refs=["A1"],
    )
    assert consistency_problems(varsayimli, _ozet()) == []


def test_kontrol_listesi_teknigi_cl_onekiyle() -> None:
    from tp_core.features.cases.schema import TEKNIK_ONEKI, consistency_problems

    assert TEKNIK_ONEKI["CL"] == "CL-"
    oz = _ozet()
    oz["coverage_items"].append(
        {"id": "CL-1", "ac_ref": "AC1", "definition": "Hata mesajı alanla ilişkili", "valid": True}
    )
    case = case_icerik(technique=["UC", "CL"], covers=["UC-MF", "CL-1"])
    assert consistency_problems(case, oz) == []


def test_set_kurallari_kenar_durumlari() -> None:
    from tp_core.features.cases.schema import readiness_warnings

    # out_of_scope kararlı öğeyi kapsayan case.
    kapsayan = [case_icerik(), _negatif(covers=["EP-I1", "BV-1"], technique=["EP", "BVA"])]
    assert any(
        "'out_of_scope' ama case kapsıyor" in p for p in set_problems(kapsayan, _ozet(), ACS)
    )
    # İki geçersiz bölüm (EP-I) tek case'te: uyarı; sınır öğesi sayılmaz.
    oz = _ozet()
    oz["coverage_items"].append(
        {"id": "EP-I2", "ac_ref": "AC2", "definition": "Boş parola", "valid": False}
    )
    oz["negative_coverage"].append({"item": "EP-I2", "decision": "tested", "rationale": "x"})
    iki = [case_icerik(), _negatif(covers=["EP-I1", "EP-I2"])]
    assert any("birden çok geçersiz eşdeğerlik bölümü" in p for p in set_problems(iki, oz, ACS))
    # tested kararlı öğeyi yalnız blocked case kapsıyor: tutarsızlık değil, hazır olma uyarısı.
    engelli = [
        case_icerik(),
        _negatif(readiness="blocked", open_question_refs=["Q1"], expected_result=""),
    ]
    assert not any("blocked" in p for p in set_problems(engelli, _ozet(), ACS))
    assert [u.split(":")[0] for u in readiness_warnings(engelli, _ozet())] == ["EP-I1"]
    assert readiness_warnings([case_icerik(), _negatif()], _ozet()) == []


def test_korunan_onayli_caseler_ac_kapsamina_sayilir() -> None:
    """Üretimde korunan (önceki üretimin onaylı) case AC2'yi kapsıyorsa yeni üretim için
    "AC2 kapsanmıyor" denmez (yanlış uyarı yok)."""
    yeni = [case_icerik()]
    oz = _ozet(not_covered=[{"item": "EP-I1", "reason": "önceki üretimde"}])
    assert any(p.startswith("AC2:") for p in set_problems(yeni, oz, ACS))
    korunan = [_negatif()]
    assert not any(p.startswith("AC2:") for p in set_problems(yeni, oz, ACS, korunan=korunan))


def test_ozet_birlesiminde_ayni_ogenin_soru_kayitlari_ayri_kalir() -> None:
    """Aynı AC iki açık soru yüzünden kapsanmamışsa iki `not_covered` kaydı birleşimde ezilmez."""
    from tp_core.features.cases import ozet as ozet_modulu

    kayitlar = [
        {"item": "AC1", "reason": "a", "question_ref": "Q1"},
        {"item": "AC1", "reason": "b", "question_ref": "Q2"},
        {"item": "AC2", "reason": "c", "question_ref": None},
    ]
    birlesik = ozet_modulu.merge([{"not_covered": kayitlar}])
    assert birlesik["not_covered"] == kayitlar
