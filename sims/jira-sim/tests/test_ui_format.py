"""Arayüz biçimlendirmesi: yerel saat ve numaralı liste dönüşümü."""

from __future__ import annotations

import itertools

from fastapi.testclient import TestClient

from jira_sim.adf import adf_to_html, text_to_adf
from jira_sim.ui import _fmt_time, adf_to_editable
from tests.conftest import WRITER


def test_fmt_time_converts_utc_to_istanbul() -> None:
    assert _fmt_time("2026-10-30T19:11:00.000+0000") == "30.10.2026 22:11"
    assert _fmt_time("2026-10-30T22:30:00.000+0000") == "31.10.2026 01:30"  # gün değişir
    assert _fmt_time("2026-10-30T22:11:00+03:00") == "30.10.2026 22:11"
    assert _fmt_time("") == ""
    assert _fmt_time(None) == ""
    assert _fmt_time("bozuk") == "bozuk"


def test_comment_time_shown_in_local_time(client: TestClient) -> None:
    client.post(
        "/rest/api/3/issue/TPD-1/comment", json={"body": text_to_adf("merhaba")}, auth=WRITER
    )
    created = client.get("/rest/api/3/issue/TPD-1/comment", auth=WRITER).json()["comments"][0][
        "created"
    ]
    assert created.endswith("+0000")
    page = client.get("/browse/TPD-1").text
    assert _fmt_time(created) in page
    # Seed oluşturma zamanı 09:00 UTC → 12:00 İstanbul
    assert "01.10.2026 12:00" in page


def _types(doc: dict) -> list[str]:
    return [n["type"] for n in doc["content"]]


def test_year_at_line_start_is_not_a_list() -> None:
    doc = text_to_adf("1990. yılda kuruldu.")
    assert _types(doc) == ["paragraph"]
    assert doc["content"][0]["content"][0]["text"] == "1990. yılda kuruldu."


def test_list_starting_at_three_stays_text() -> None:
    doc = text_to_adf("3. adım\n4. adım")
    assert _types(doc) == ["paragraph"]
    assert "3. adım" in str(adf_to_html(doc))


def test_ordered_list_needs_consecutive_numbers() -> None:
    doc = text_to_adf("1. bir\n2. iki\n5. beş")
    assert _types(doc) == ["orderedList", "paragraph"]
    assert doc["content"][0]["attrs"] == {"order": 1}
    assert len(doc["content"][0]["content"]) == 2


def test_ordered_list_order_attr_rendered() -> None:
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
                            {"type": "paragraph", "content": [{"type": "text", "text": "a"}]}
                        ],
                    }
                ],
            }
        ],
    }
    assert '<ol start="3">' in str(adf_to_html(doc))
    assert adf_to_editable(doc) == "3. a"


def _heading_levels(html: str) -> list[int]:
    import re

    return [int(n) for n in re.findall(r"<h([1-6])[\s>]", html)]


def test_adf_headings_follow_section_heading_without_skipping() -> None:
    # Kabul kriterleri ADF'de seviye 3 başlıktır; h2 bölümün altında h4 olursa axe
    # "heading-order" ihlali verir.
    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "A"}]},
            {"type": "heading", "attrs": {"level": 5}, "content": [{"type": "text", "text": "B"}]},
            {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "C"}]},
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "D"}]},
        ],
    }
    assert _heading_levels(str(adf_to_html(doc))) == [3, 4, 3, 4]


def test_issue_page_heading_order_is_sequential(client: TestClient) -> None:
    desc = text_to_adf("Açıklama\n\n### Kabul kriterleri\n\n- AC1: x")
    assert any(n["type"] == "heading" for n in desc["content"])
    r = client.put("/rest/api/3/issue/TPD-3", json={"fields": {"description": desc}}, auth=WRITER)
    assert r.status_code == 204
    client.post(
        "/rest/api/3/issue/TPD-3/comment",
        json={"body": text_to_adf("### Not\n\nmetin")},
        auth=WRITER,
    )
    levels = _heading_levels(client.get("/browse/TPD-3").text)
    assert levels[0] == 1
    for prev, cur in itertools.pairwise(levels):
        assert cur <= prev + 1, levels


def _pre_review(n: int) -> dict:
    return text_to_adf(
        f"[AI-generated] Testing Probe ön inceleme — TPD-3 için PO teyidi\n\nTur {n}"
    )


def test_earlier_pre_review_comments_marked_superseded(client: TestClient) -> None:
    for n in (1, 2, 3):
        client.post("/rest/api/3/issue/TPD-3/comment", json={"body": _pre_review(n)}, auth=WRITER)
    client.post(
        "/rest/api/3/issue/TPD-3/comment", json={"body": text_to_adf("PO cevabı")}, auth=WRITER
    )
    page = client.get("/browse/TPD-3").text
    assert page.count('data-testid="comment-superseded"') == 2
    assert page.count("(önceki tur)") == 2
    # En güncel tur katlanmadan görünür; eski turlar silinmez (iz kaydı).
    son = page.split('data-testid="comment-superseded"')[-1]
    assert "Tur 3" in son.split("</details>", 1)[1]
    assert "Tur 1" in page and "Tur 2" in page
    # API yorumları değiştirmez.
    api = client.get("/rest/api/3/issue/TPD-3/comment", auth=WRITER).json()
    assert len(api["comments"]) >= 4


def test_single_pre_review_comment_not_superseded(client: TestClient) -> None:
    client.post("/rest/api/3/issue/TPD-3/comment", json={"body": _pre_review(1)}, auth=WRITER)
    page = client.get("/browse/TPD-3").text
    assert "(önceki tur)" not in page
