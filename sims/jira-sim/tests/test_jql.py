from __future__ import annotations

import pytest

from jira_sim import jql


def doc(key: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "key": [key, "1"],
        "project": ["TPD", "Testing Probe Demo"],
        "labels": [],
        "summary": "",
        "description": "",
        "text": "",
        "status": ["To Do"],
        "statuscategory": ["To Do", "new"],
        "issuetype": ["Story"],
        "reporter": [],
        "created": "2026-10-01T00:00:00.000+0000",
        "updated": "2026-10-01T00:00:00.000+0000",
    }
    base.update(kw)
    return base


def match(q: str, d: dict[str, object]) -> bool:
    return jql.parse(q).predicate(d)


def test_equality_in_and_case_insensitive() -> None:
    d = doc("TPD-1", labels=["tp-demo", "AI-generated"])
    assert match("project = TPD", d)
    assert match('project = "tpd"', d)
    assert match("key = TPD-1", d)
    assert match("issuekey in (TPD-2, TPD-1)", d)
    assert not match("key not in (TPD-1)", d)
    assert match("labels = ai-generated", d)
    assert match("labels in (x, tp-demo)", d)
    assert match("labels != x", d)
    assert match("issuetype = Story AND status = 'To Do'", d)
    assert match("type = Story", d)


def test_status_category_and_boolean_logic() -> None:
    done = doc("TPD-7", statuscategory=["Done", "done"], issuetype=["Bug"])
    todo = doc("TPD-5", issuetype=["Bug"])
    q = "issuetype = Bug AND statusCategory != Done"
    assert match(q, todo) and not match(q, done)
    assert match("statusCategory = Done OR key = TPD-5", todo)
    assert match("NOT (statusCategory = Done)", todo)
    assert match("(key = TPD-7 OR key = TPD-5) AND issuetype = Bug", done)


def test_text_search_stems_and_turkish_case() -> None:
    d = doc("TPD-5", text="Kampanya İndirimi sepette yanlış hesaplanıyor")
    assert match('text ~ "kampanya indirim"', d)
    assert match('text ~ "KAMPANYA hesaplama"', d)
    assert match('text ~ "indirimi"', d)
    assert not match('text ~ "kampanya teslimat"', d)
    assert match('text ~ "kamp*"', d)
    assert match('text ~ "\\"sepette yanlış\\""', d)
    assert not match('text ~ "\\"yanlış sepette\\""', d)
    assert match('text !~ "teslimat"', d)


def test_summary_search() -> None:
    d = doc("TPD-1", summary="Kampanyalı sepet ve sipariş onayı")
    assert match('summary ~ "sipariş onay"', d)
    assert not match('summary ~ "fatura"', d)


def test_empty_checks() -> None:
    assert match("labels is EMPTY", doc("TPD-5"))
    assert match("labels is not EMPTY", doc("TPD-1", labels=["a"]))


def test_order_by() -> None:
    a = doc("TPD-2", updated="2026-10-03")
    b = doc("TPD-10", updated="2026-10-01")
    c = doc("TPD-1", updated="2026-10-02")
    q = jql.parse("project = TPD ORDER BY key ASC")
    assert [d["key"][0] for d in jql.sort_docs([a, b, c], q.order)] == ["TPD-1", "TPD-2", "TPD-10"]
    q = jql.parse("ORDER BY updated DESC")
    assert [d["key"][0] for d in jql.sort_docs([a, b, c], q.order)] == ["TPD-2", "TPD-1", "TPD-10"]
    # varsayılan: anahtar azalan
    assert [d["key"][0] for d in jql.sort_docs([a, b, c], [])] == ["TPD-10", "TPD-2", "TPD-1"]


def test_empty_query_matches_all() -> None:
    assert match("", doc("TPD-1"))


@pytest.mark.parametrize(
    "q",
    [
        "foo = bar",
        "project ~ TPD",
        "summary = x",
        "project = ",
        "key in (TPD-1",
        "project = TPD AND",
        "assignee = currentUser()",
        "project = TPD ORDER updated",
        "project = TPD extra",
        "labels in (currentUser())",
    ],
)
def test_errors(q: str) -> None:
    with pytest.raises(jql.JqlError):
        jql.parse(q)
