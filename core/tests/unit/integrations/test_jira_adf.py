from __future__ import annotations

import pytest

from tp_core.integrations.jira_adf import (
    NOT_APPLICABLE,
    TEMPLATE_AC_HEADING,
    TEMPLATE_SECTIONS,
    adf_to_text,
    build_description,
    bullet_list,
    normalize_ac,
    paragraph,
    parse_description,
    table,
    template_doc,
    template_section,
    text_to_adf,
)


def test_text_to_adf_paragraphs_headings_lists_hardbreak() -> None:
    adf = text_to_adf("Birinci satır\nikinci satır\n\n### Başlık\n- a\n- b\n\n1. x\n2. y")
    assert adf["type"] == "doc" and adf["version"] == 1
    kinds = [n["type"] for n in adf["content"]]
    assert kinds == ["paragraph", "heading", "bulletList", "orderedList"]
    p = adf["content"][0]["content"]
    assert [n["type"] for n in p] == ["text", "hardBreak", "text"]
    assert adf["content"][1]["attrs"]["level"] == 3
    assert len(adf["content"][2]["content"]) == 2


def test_adf_to_text() -> None:
    adf = text_to_adf("Bir\niki\n\n### Başlık\n- a\n- b\n\nSon")
    assert adf_to_text(adf) == "Bir\niki\n\nBaşlık\n\n- a\n- b\n\nSon"
    assert adf_to_text(None) == ""
    assert adf_to_text("düz metin") == "düz metin"


def test_adf_to_text_handles_tables_mentions_and_unknown_nodes() -> None:
    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "mention", "attrs": {"id": "1", "text": "@PO"}},
                    {"type": "text", "text": " bakar mısın", "marks": [{"type": "strong"}]},
                ],
            },
            table(["A", "B"], [["1", "2"]]),
            {
                "type": "panel",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Not"}]}],
            },
            {"type": "rule"},
        ],
    }
    assert adf_to_text(doc) == "@PO bakar mısın\n\nA | B\n1 | 2\n\nNot"


def test_parse_description_with_heading_and_bullets() -> None:
    adf = text_to_adf(
        "Bayi siparişi onaylar.\n\n### Kabul Kriterleri\n- AC1: Birinci.\n- AC2: İkinci (7 adet)."
    )
    desc, acs = parse_description(adf)
    assert desc == "Bayi siparişi onaylar."
    assert acs == ["AC1: Birinci.", "AC2: İkinci (7 adet)."]


def test_parse_description_paragraph_lines_without_heading() -> None:
    adf = text_to_adf("Açıklama\n\nAC1: bir\nAC2 - iki\nac3) üç")
    desc, acs = parse_description(adf)
    assert desc == "Açıklama"
    assert acs == ["AC1: bir", "AC2: iki", "AC3: üç"]


def test_parse_description_heading_as_paragraph_and_trailing_section() -> None:
    adf = text_to_adf(
        "Giriş\n\nKabul Kriterleri:\n\n1. AC1: Bir\n2. AC2: İki\n\n### Notlar\nEk bilgi"
    )
    desc, acs = parse_description(adf)
    assert acs == ["AC1: Bir", "AC2: İki"]
    assert desc == "Giriş\n\nNotlar\n\nEk bilgi"


def test_parse_description_no_ac() -> None:
    desc, acs = parse_description(text_to_adf("Sadece açıklama."))
    assert (desc, acs) == ("Sadece açıklama.", [])
    assert parse_description(None) == ("", [])


def test_build_description_roundtrip() -> None:
    acs = ["AC1: Bir.", "AC2: İki."]
    adf = build_description("Açıklama paragrafı.\nikinci satır", acs)
    kinds = [n["type"] for n in adf["content"]]
    assert kinds == ["paragraph", "heading", "bulletList"]
    assert adf["content"][1]["content"][0]["text"] == "Kabul Kriterleri"
    assert parse_description(adf) == ("Açıklama paragrafı.\nikinci satır", acs)


def test_build_description_numbers_unprefixed_acs_and_skips_blank() -> None:
    adf = build_description("", ["İlk kriter", " ", "AC7: Yedi"])
    _, acs = parse_description(adf)
    assert acs == ["AC1: İlk kriter", "AC7: Yedi"]
    assert build_description("x", [])["content"][-1]["type"] == "paragraph"


def test_normalize_ac() -> None:
    assert normalize_ac("ac 2 : metin ", 9) == "AC2: metin"
    assert normalize_ac("metin", 4) == "AC4: metin"


# --------------------------------------------------- numaralı liste: veri kaybı yok


def test_year_at_line_start_roundtrips_unchanged() -> None:
    text = "1990. yılda kuruldu."
    adf = text_to_adf(text)
    assert [n["type"] for n in adf["content"]] == ["paragraph"]
    assert adf_to_text(adf) == text
    assert parse_description(text) == (text, [])


def test_list_starting_at_three_roundtrips_unchanged() -> None:
    text = "3. adım\n4. adım"
    adf = text_to_adf(text)
    assert [n["type"] for n in adf["content"]] == ["paragraph"]
    assert adf_to_text(adf) == text


def test_ordered_list_starts_at_one_and_continues_consecutively() -> None:
    adf = text_to_adf("1. bir\n2. iki\n3. üç")
    assert [n["type"] for n in adf["content"]] == ["orderedList"]
    assert adf["content"][0]["attrs"] == {"order": 1}
    assert adf_to_text(adf) == "1. bir\n2. iki\n3. üç"
    # Ardışık olmayan numara listeyi bitirir; numarası korunur.
    broken = text_to_adf("1. bir\n5. beş")
    assert [n["type"] for n in broken["content"]] == ["orderedList", "paragraph"]
    assert "5. beş" in adf_to_text(broken)


def test_adf_ordered_list_with_order_attr_keeps_numbers() -> None:
    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "orderedList",
                "attrs": {"order": 3},
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "adım"}]}
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "sonra"}]}
                        ],
                    },
                ],
            }
        ],
    }
    assert adf_to_text(doc) == "3. adım\n4. sonra"
    # Metne çevrilip tekrar yazıldığında numara kaybolmaz.
    assert adf_to_text(text_to_adf(adf_to_text(doc))) == "3. adım\n4. sonra"


# ------------------------------------------- başlık altındaki öneksiz kabul kriterleri


def test_unprefixed_bullets_under_heading_are_acs() -> None:
    desc, acs = parse_description("Kabul kriterleri:\n- Sepete eklenebilir\n- Stok kontrol edilir")
    assert desc == ""
    assert acs == ["AC1: Sepete eklenebilir", "AC2: Stok kontrol edilir"]


def test_unprefixed_acs_under_adf_heading_with_description() -> None:
    adf = text_to_adf(
        "Bayi sepete ürün ekler.\n\n## Acceptance Criteria\n"
        "1. Sepete eklenebilir\n2. AC5: Stok kontrol edilir\n\n"
        "Paragraf kriteri\n\n### Notlar\nKapsam dışı"
    )
    desc, acs = parse_description(adf)
    assert acs == ["AC1: Sepete eklenebilir", "AC5: Stok kontrol edilir", "AC6: Paragraf kriteri"]
    assert desc == "Bayi sepete ürün ekler.\n\nNotlar\n\nKapsam dışı"


def test_multiline_item_under_heading_is_one_ac() -> None:
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Kabul Kriterleri"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Uyarı gösterilir"},
                                    {"type": "hardBreak"},
                                    {"type": "text", "text": "ve buton pasif olur"},
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    assert parse_description(adf) == ("", ["AC1: Uyarı gösterilir ve buton pasif olur"])


# ------------------------------------------------------------------ görev şablonu


def test_template_section_recognizes_headings_with_emoji_and_language() -> None:
    assert template_section("🎯 Objective (Amaç)") == "objective"
    assert template_section("🎯Objective (Amaç)") == "objective"  # emoji'den sonra boşluksuz
    assert template_section("Kapsam") == "scope"
    assert template_section("🔗 Dependencies & Integration") == "dependencies"
    assert template_section("ℹ️ Other Information & Assets (Diğer Bilgiler & Kaynaklar)") == "other"
    assert template_section("🔑 Acceptance Criteria (Kabul Kriterleri)") == "acceptance_criteria"
    assert template_section("🧪 QA Checklist:") == "qa_checklist"
    assert template_section("Kapsam dışı işler şunlardır") is None
    assert template_section("Objective\nikinci satır") is None


def test_template_doc_orders_sections_and_fills_missing_with_not_applicable() -> None:
    d = template_doc(
        {"scope": "- a\n- b", "objective": "Amaç.", "qa_checklist": [bullet_list(["x"])]},
        preamble=[paragraph("im")],
        trailer=[paragraph("kimlik")],
    )
    headings = [n["content"][0]["text"] for n in d["content"] if n["type"] == "heading"]
    assert headings == [title for _, title, _ in TEMPLATE_SECTIONS]
    assert all(n["attrs"]["level"] == 3 for n in d["content"] if n["type"] == "heading")
    assert d["content"][0] == paragraph("im") and d["content"][-1] == paragraph("kimlik")
    text = adf_to_text(d)
    assert text.count(NOT_APPLICABLE) == 4  # user_flow, dependencies, other, acceptance_criteria
    assert parse_description(d)[1] == []  # AC bölümündeki "Not applicable" AC değildir


def test_not_applicable_under_ac_heading_is_not_an_ac() -> None:
    """Elle yazılmış şablonda boş AC bölümü "Not applicable" diyebilir; sahte AC1 olmamalı."""
    text = "🔑 Acceptance Criteria (Kabul Kriterleri)\n\nNot applicable\n\n🧪 QA Checklist\n\n- x"
    assert parse_description(text)[1] == []


def test_template_story_round_trip_keeps_sections_and_ac_position() -> None:
    story = template_doc(
        {
            "objective": "Bayi siparişini onaylayabilmelidir.",
            "scope": "- Sepet\n- Kampanya",
            "acceptance_criteria": [bullet_list(["AC1: Sepet sayacı artar.", "AC2: İndirim."])],
            "qa_checklist": "- Sepet sayacı kontrolü",
        }
    )
    desc, acs = parse_description(story)
    assert acs == ["AC1: Sepet sayacı artar.", "AC2: İndirim."]
    assert "Bayi siparişini onaylayabilmelidir." in desc and "AC1" not in desc
    assert "🧪 QA Checklist" in desc  # AC bölümünden sonraki bölüm açıklamada kalır

    rebuilt = build_description(desc, [acs[0], "AC2: Düzeltilmiş indirim."])
    assert parse_description(rebuilt) == (desc, [acs[0], "AC2: Düzeltilmiş indirim."])
    titles = [n["content"][0]["text"] for n in rebuilt["content"] if n["type"] == "heading"]
    assert titles == [title for _, title, _ in TEMPLATE_SECTIONS]  # AC yerinde, QA'dan önce
    assert TEMPLATE_AC_HEADING in titles


def test_plain_paragraph_template_headings_end_ac_section_and_round_trip() -> None:
    """Gerçek Jira story'sinde başlıklar çoğu zaman düz satırdır; QA Checklist AC değildir."""
    text = (
        "🎯Objective (Amaç)\n\nAmaç metni.\n\n🔑 Acceptance Criteria\n\n"
        "The system must generate X\n\n🧪 QA Checklist\n\nVerify X"
    )
    desc, acs = parse_description(text)
    assert acs == ["AC1: The system must generate X"]
    assert desc == "🎯Objective (Amaç)\n\nAmaç metni.\n\n🧪 QA Checklist\n\nVerify X"
    # Başlık metni olduğu gibi korunur (içerik hash'i değişmez).
    assert parse_description(build_description(desc, acs)) == (desc, acs)


def test_non_template_description_build_is_unchanged() -> None:
    d = build_description("Açıklama.", ["AC1: x"])
    assert [n["type"] for n in d["content"]] == ["paragraph", "heading", "bulletList"]
    assert d["content"][1]["content"][0]["text"] == "Kabul Kriterleri"


def test_ac_line_in_qa_checklist_of_template_story_is_not_an_ac() -> None:
    """Şablonda AC yalnızca AC bölümündedir; checklist'teki "AC1: …" maddesi yerinde kalır."""
    story = template_doc(
        {
            "objective": "Amaç.",
            "acceptance_criteria": [bullet_list(["AC1: a"])],
            "qa_checklist": "- AC1: a doğrulanır",
        }
    )
    desc, acs = parse_description(story)
    assert acs == ["AC1: a"]
    assert desc.endswith("🧪 QA Checklist\n\n- AC1: a doğrulanır")
    assert parse_description(build_description(desc, acs)) == (desc, acs)


def test_template_story_without_acs_keeps_ac_section_on_write_back() -> None:
    desc, acs = parse_description(template_doc({"objective": "Amaç."}))
    assert acs == []
    titles = [
        n["content"][0]["text"]
        for n in build_description(desc, acs)["content"]
        if n["type"] == "heading"
    ]
    assert TEMPLATE_AC_HEADING in titles
    assert parse_description(build_description(desc, acs)) == (desc, acs)


def test_heading_variants_are_recognized() -> None:
    assert template_section("KULLANICI AKIŞI") == "user_flow"  # Türkçe büyük harf
    assert template_section("Dependencies and Integration") == "dependencies"
    assert template_section("Bağımlılıklar & Entegrasyon") == "dependencies"
    assert template_section("QA Kontrol Listesi") == "qa_checklist"
    # Metni olmayan ADF emoji düğümü kısa adıyla gelir.
    text = ":key: Acceptance Criteria\n\n- AC1: x\n\n:test_tube: QA Checklist\n\n- y"
    assert parse_description(text)[1] == ["AC1: x"]


@pytest.mark.parametrize("marker", ["Yok", "N/A", "—", "Uygulanamaz", "- Not applicable."])
def test_empty_markers_under_ac_heading_are_not_acs(marker: str) -> None:
    text = f"🎯 Objective\n\nAmaç.\n\n🔑 Acceptance Criteria\n\n{marker}\n\n🧪 QA Checklist\n\n- x"
    assert parse_description(text)[1] == []


def test_single_section_word_does_not_switch_to_template_mode() -> None:
    """Tek "Kapsam" satırı şablon sayılmaz: eski biçimle yazılır, AC başlığı "Kabul Kriterleri"."""
    desc, acs = parse_description("Açıklama.\n\nKapsam\n\nAC1: x")
    assert acs == ["AC1: x"]
    d = build_description(desc, acs)
    assert [n["type"] for n in d["content"]] == ["paragraph", "paragraph", "heading", "bulletList"]
    assert d["content"][2]["content"][0]["text"] == "Kabul Kriterleri"
