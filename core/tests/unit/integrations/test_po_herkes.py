"""JIRA_PO_ACCOUNT_IDS=* : etiketi koyan herkes PO sayılır; bot hesabı yine hariç."""

from datetime import UTC, datetime

from tp_core.integrations.jira import LabelChange, authorized_po_approvals


def _ch(author, ids=()):
    return LabelChange(
        label="tp-po-approved",
        author=author,
        author_ids=list(ids),
        at=datetime(2026, 11, 14, tzinfo=UTC),
    )


def test_herkes_po_kabul_eder_bot_haric():
    changes = [_ch("a@x.com", ["acc-1"]), _ch("bot@x.com", ["bot-acc"]), _ch("")]
    out = authorized_po_approvals(changes, ["*"], ["bot-acc"])
    assert [c.author for c in out] == ["a@x.com"]


def test_liste_varsa_yalniz_listedekiler():
    changes = [_ch("a@x.com", ["acc-1"]), _ch("b@x.com", ["acc-2"])]
    out = authorized_po_approvals(changes, ["acc-2"], [])
    assert [c.author for c in out] == ["b@x.com"]
