"""Arayüz biçimlendirmesi: yerel saat ve numaralı liste dönüşümü."""

from __future__ import annotations

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
