"""Ürün yorumları: bot imi, rol @bahsetmeleri, boş anahtarlar ve idempotency işaretleri."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tp_core.features.bugs.services import add_adf_comment
from tp_core.integrations import jira_notify
from tp_core.integrations.jira import PO_APPROVED_LABEL, JiraSettings, RestJira
from tp_core.integrations.jira_adf import (
    BOT_PREFIX,
    adf_to_text,
    bot_header,
    doc,
    has_bot_header,
    paragraph,
    strip_bot_header,
    unique_mentions,
    with_bot_header,
)

SIM_SRC = Path(__file__).resolve().parents[4] / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402

BASE = "http://jira-sim:8090"
GOKHAN = "712020:00000000-0000-4000-8000-00000000000a"
CENGIZHAN = "712020:00000000-0000-4000-8000-00000000000b"
FATIH = "712020:00000000-0000-4000-8000-00000000000c"


class SimTransport(httpx.BaseTransport):
    def __init__(self, sim: TestClient) -> None:
        self.sim = sim
        self.bodies: list[Any] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        content = request.read()
        if request.method == "POST" and request.url.path.endswith("/comment"):
            import json

            self.bodies.append(json.loads(content)["body"])
        r = self.sim.request(
            request.method, str(request.url), headers=dict(request.headers), content=content
        )
        return httpx.Response(r.status_code, headers=dict(r.headers), content=r.content)


@pytest.fixture
def transport() -> Iterator[SimTransport]:
    with TestClient(create_app(data_path="", base_url=BASE), base_url=BASE) as client:
        yield SimTransport(client)


@pytest.fixture
def jira(transport: SimTransport) -> RestJira:
    return RestJira(
        BASE,
        ("reader@sim.local", "t"),
        ("writer@sim.local", "t"),
        http=httpx.Client(transport=transport),
        sleep=lambda _s: None,
    )


@pytest.fixture
def roller(monkeypatch: pytest.MonkeyPatch) -> JiraSettings:
    """Demo eşlemesi: Analist + PO = Cengizhan, Mühendis = Gokhan, Testçi = Fatih."""
    ayar = JiraSettings(
        jira_hesap_analist=CENGIZHAN,
        jira_hesap_po=CENGIZHAN,
        jira_hesap_muhendis=GOKHAN,
        jira_hesap_testci=FATIH,
    )
    monkeypatch.setattr("tp_core.integrations.jira.get_jira_settings", lambda: ayar)
    return ayar


def _mentions(adf: dict[str, Any]) -> list[str]:
    return [n["attrs"]["id"] for n in adf["content"][0]["content"] if n["type"] == "mention"]


# ------------------------------------------------------------------ ADF yardımcıları


def test_bot_header_mentions_and_validation() -> None:
    h = bot_header([CENGIZHAN, "", CENGIZHAN, "kötü id <x>", FATIH])
    assert h["content"][0] == {"type": "text", "text": BOT_PREFIX}
    assert [n["attrs"]["id"] for n in h["content"] if n["type"] == "mention"] == [
        CENGIZHAN,
        FATIH,
    ]
    assert unique_mentions(["", " ", "a@b.c", "x"]) == ["x"]  # e-posta accountId değildir
    assert bot_header()["content"] == [{"type": "text", "text": BOT_PREFIX}]


def test_with_bot_header_is_idempotent_and_keeps_body() -> None:
    govde = doc([paragraph("Kayıt: tp-marker-1")])
    bir = with_bot_header(govde, [FATIH])
    assert has_bot_header(bir) and not has_bot_header(govde)
    assert with_bot_header(bir, [GOKHAN]) is bir  # ikinci im/bahsetme eklenmez
    metin = adf_to_text(bir)
    assert metin == f"{BOT_PREFIX} @{FATIH}\n\nKayıt: tp-marker-1"
    assert strip_bot_header(metin) == "Kayıt: tp-marker-1"
    assert strip_bot_header("Testing Probe: eski yorum") == "Testing Probe: eski yorum"


def test_role_mentions_empty_keys_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    bos = JiraSettings()
    assert jira_notify.role_mentions(jira_notify.BUG, bos) == []
    kismi = JiraSettings(jira_hesap_testci=FATIH, jira_hesap_muhendis="  ")
    assert jira_notify.role_mentions(jira_notify.BUG, kismi) == [FATIH]
    # Aynı kişi iki rolde (Analist + PO) tek bahsetme; bilinmeyen rol yok sayılır.
    ayni = JiraSettings(jira_hesap_po=CENGIZHAN, jira_hesap_analist=CENGIZHAN)
    assert jira_notify.role_mentions((*jira_notify.PO_SORU, "admin"), ayni) == [CENGIZHAN]
    # Ortam değişkeni adları sözleşmedeki gibi.
    monkeypatch.setenv("JIRA_HESAP_TESTCI", FATIH)
    monkeypatch.setenv("JIRA_HESAP_MUHENDIS", GOKHAN)
    assert jira_notify.role_mentions(jira_notify.BUG, JiraSettings()) == [GOKHAN, FATIH]


def test_comment_kind_role_map() -> None:
    assert jira_notify.PO_SORU == ("po", "analist")
    assert jira_notify.YAYIN == ("testci",)
    assert jira_notify.BUG == ("muhendis", "testci")
    assert jira_notify.PO_ETIKET_KALDIRILDI == ("po",)
    assert jira_notify.DOKUMAN_DUZELTME == ("po",)


# ------------------------------------------------------------------ yazım yolu


class _DuzJira:
    """Yalnızca `JiraPort.add_comment(key, body)` sunan sahte istemci (bahsetme parametresi yok)."""

    def __init__(self) -> None:
        self.yorumlar: list[tuple[str, str]] = []

    def add_comment(self, key: str, body: str) -> str:
        self.yorumlar.append((key, body))
        return "1"


def test_post_comment_without_mentions_keeps_port_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tp_core.integrations.jira.get_jira_settings", lambda: JiraSettings())
    sahte = _DuzJira()
    assert jira_notify.post_comment(sahte, "TPD-1", "gövde", jira_notify.PO_SORU) == "1"
    assert sahte.yorumlar == [("TPD-1", "gövde")]


def test_rest_comment_has_prefix_and_mentions(
    jira: RestJira, transport: SimTransport, roller: JiraSettings
) -> None:
    marker = "Kayıt: tp:jira:comment:po_request:abc"
    jira_notify.post_comment(jira, "TPD-1", f"Soru yorumu\n{marker}", jira_notify.PO_SORU)
    gonderilen = transport.bodies[-1]
    assert gonderilen["content"][0]["content"][0]["text"] == BOT_PREFIX
    assert _mentions(gonderilen) == [CENGIZHAN]  # PO = Analist → tek bahsetme
    assert gonderilen["content"][0]["content"][2] == {
        "type": "mention",
        "attrs": {"id": CENGIZHAN},
    }
    # Idempotency: işaret okunan gövdede aynen bulunur (find_existing yeniden yazmaz).
    yorumlar = jira.get_comments("TPD-1")
    assert len(yorumlar) == 1
    assert marker in yorumlar[0].body
    assert yorumlar[0].body.startswith(BOT_PREFIX)
    assert strip_bot_header(yorumlar[0].body).startswith("Soru yorumu")
    # Bahsetme yalnızca bildirimdir: onay etiketi eklenmez.
    assert PO_APPROVED_LABEL not in jira.get_issue("TPD-1").labels


def test_publish_and_bug_mentions(
    jira: RestJira, transport: SimTransport, roller: JiraSettings
) -> None:
    jira_notify.post_comment(jira, "TPD-2", "Testing Probe: 2 case yayınlandı", jira_notify.YAYIN)
    assert _mentions(transport.bodies[-1]) == [FATIH]
    yayin = jira.get_comments("TPD-2")[-1].body
    # Yayın kurtarma araması imden sonraki metne bakar (publish._pin_chain).
    assert strip_bot_header(yayin).startswith("Testing Probe:")

    add_adf_comment(
        jira,
        "TPD-2",
        doc([paragraph("Testing Probe: Bu hata yeniden gözlendi (tp-x).")]),
        mentions=jira_notify.role_mentions(jira_notify.BUG),
    )
    assert _mentions(transport.bodies[-1]) == [GOKHAN, FATIH]
    assert "tp-x" in jira.get_comments("TPD-2")[-1].body


def test_empty_keys_comment_only_prefix(jira: RestJira, transport: SimTransport) -> None:
    jira.add_comment("TPD-3", "metin")
    assert transport.bodies[-1]["content"][0]["content"] == [{"type": "text", "text": BOT_PREFIX}]
    # Zaten imli ADF gövdesine ikinci im eklenmez.
    jira.add_comment_adf("TPD-3", with_bot_header(doc([paragraph("x")])))
    ilk_paragraflar = [b for b in transport.bodies[-1]["content"] if has_bot_header(doc([b]))]
    assert len(ilk_paragraflar) == 1


def test_add_adf_comment_fake_without_mentions_param() -> None:
    class _AdfJira:
        def __init__(self) -> None:
            self.govdeler: list[dict[str, Any]] = []

        def add_comment_adf(self, key: str, body: dict[str, Any]) -> str:
            self.govdeler.append(body)
            return "9"

    sahte = _AdfJira()
    assert add_adf_comment(sahte, "TPD-1", doc([paragraph("x")])) == "9"
    assert len(sahte.govdeler) == 1
