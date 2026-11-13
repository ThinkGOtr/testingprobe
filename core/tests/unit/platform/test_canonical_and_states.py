"""DB'siz birim testleri: kanonik JSON/hash, durum makinesi tabloları, olay yükü."""

from __future__ import annotations

import json
import uuid
from collections import deque
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tp_core.audit.canonical import (
    GENESIS_HASH,
    canonical_json,
    chain_hash,
    content_hash,
    normalize,
    sha256_hex,
)
from tp_core.events.bus import MAX_PAYLOAD, build_payload, parse_payload
from tp_core.workflow.states import (
    APPROVER_ROLES,
    APPROVING,
    CONTENT_FIELDS,
    KARARLAR,
    MACHINES,
)

# ------------------------------------------------------------------ kanonik JSON


def test_kanonik_json_anahtar_sirasi_ve_bosluk() -> None:
    assert (
        canonical_json({"b": 1, "a": [1, {"d": 2, "c": "ş"}]}) == '{"a":[1,{"c":"ş","d":2}],"b":1}'
    )


def test_kanonik_json_turleri() -> None:
    u = uuid.UUID("12345678-1234-5678-1234-567812345678")
    ist = timezone(timedelta(hours=3))
    t = datetime(2026, 10, 30, 15, 0, 0, 123, tzinfo=ist)
    assert normalize({"u": u, "t": t, "d": Decimal("1.50"), "x": (1, 2)}) == {
        "u": str(u),
        "t": "2026-10-30T12:00:00.000123+00:00",
        "d": "1.50",
        "x": [1, 2],
    }


@pytest.mark.parametrize(
    "deger", [float("nan"), float("inf"), datetime(2026, 1, 1), {1: "a"}, b"x"]
)
def test_kanonik_json_gecersiz_degerleri_reddeder(deger: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        canonical_json({"v": deger})


def test_content_hash_icerige_duyarli_siraya_duyarsiz() -> None:
    a = content_hash({"title": "T", "steps": [1, 2]})
    assert a == content_hash({"steps": [1, 2], "title": "T"})
    assert a != content_hash({"title": "T", "steps": [2, 1]})
    assert a == sha256_hex('{"steps":[1,2],"title":"T"}')


def test_chain_hash_tanimi() -> None:
    satir = {"id": 1, "eylem": "x"}
    assert chain_hash(GENESIS_HASH, satir) == sha256_hex(GENESIS_HASH + '{"eylem":"x","id":1}')
    assert chain_hash("a" * 64, satir) != chain_hash(GENESIS_HASH, satir)


# ------------------------------------------------------------- durum makineleri


@pytest.mark.parametrize("ad", sorted(MACHINES))
def test_makine_tutarli(ad: str) -> None:
    m = MACHINES[ad]
    assert m.entity == ad
    assert m.initial in m.transitions
    # her hedef durumun kendi satırı var (son durumlar boş küme)
    for hedefler in m.transitions.values():
        assert hedefler <= set(m.transitions)
    for anahtar in list(m.gates) + list(m.guards):
        assert m.allowed(*anahtar), anahtar
    assert m.approval_targets <= m.states
    # her durum başlangıçtan erişilebilir
    erisilen, kuyruk = {m.initial}, deque([m.initial])
    while kuyruk:
        for h in m.transitions[kuyruk.popleft()]:
            if h not in erisilen:
                erisilen.add(h)
                kuyruk.append(h)
    assert erisilen == m.states


def test_kapilar_ve_onaylar() -> None:
    # Constitution I: case, bug ve merge geçişleri insan kapısından geçer.
    # 012: Testçi kabulü (draft → ready) ve Analist son onayı (ready → approved) ayrı kapılar.
    assert ("draft", "ready") in MACHINES["test_case"].gates
    assert ("ready", "approved") in MACHINES["test_case"].gates
    assert ("approved", "published") in MACHINES["test_case"].gates
    assert not MACHINES["test_case"].allowed("draft", "approved")
    assert MACHINES["test_case"].gates[("approved", "published")].kararlar == {"approve"}
    assert ("draft", "approved") in MACHINES["bug_draft"].gates
    assert ("approved", "published") in MACHINES["bug_draft"].gates
    assert ("pr_open", "merged") in MACHINES["script"].gates
    assert ("pending_po", "po_approved") in MACHINES["requirement"].gates
    assert ("open", "decided") in MACHINES["consistency_finding"].gates
    # yayın, onay adımını atlayamaz
    assert not MACHINES["test_case"].allowed("draft", "published")
    assert not MACHINES["bug_draft"].allowed("draft", "published")
    assert not MACHINES["requirement"].allowed("pending_po", "generating")
    for tur, kararlar in APPROVING.items():
        assert kararlar <= KARARLAR[tur]
        assert tur in APPROVER_ROLES
        assert tur in CONTENT_FIELDS


def test_son_durumlar_cikissiz() -> None:
    assert MACHINES["test_case"].transitions["published"] == frozenset()
    assert MACHINES["bug_draft"].transitions["published"] == frozenset()
    assert MACHINES["script"].transitions["merged"] == frozenset()


def test_karar_rolleri_izin_katalogundan() -> None:
    """Durum makinesindeki karar rolleri auth/yetki.py kataloğuyla aynı (ANALIZ §4.3)."""
    from tp_core.auth.yetki import KARAR_IZNI, roller_icin
    from tp_core.workflow.service import karar_rolleri
    from tp_core.workflow.states import TEST_CASE_KARAR_IZNI

    assert set(TEST_CASE_KARAR_IZNI) == KARARLAR["test_case"]
    for karar, izin_adi in TEST_CASE_KARAR_IZNI.items():
        assert karar_rolleri("test_case", karar) == roller_icin(izin_adi)
    assert karar_rolleri("test_case", "accept") == {"tester"}
    assert karar_rolleri("test_case", "approve") == {"analyst"}
    assert APPROVER_ROLES["test_case"] == roller_icin("case.decide") | roller_icin("case.approve")
    for tur in ("bug_draft", "script", "consistency_finding"):
        assert APPROVER_ROLES[tur] == roller_icin(KARAR_IZNI[tur]), tur
    # PO teyidi yalnız Jira kanalından (K6); portal kümesi kataloğa bağlanmaz.
    assert APPROVER_ROLES["requirement"] == {"po"}


# ------------------------------------------------------------------- olay yükü


def test_olay_yuku_gidis_donus() -> None:
    yuk = parse_payload(build_payload("case.generated", {"id": uuid.UUID(int=1), "n": 3}))
    assert yuk["event"] == "case.generated"
    assert yuk["data"] == {"id": str(uuid.UUID(int=1)), "n": 3}
    datetime.fromisoformat(yuk["ts"]).astimezone(UTC)


@pytest.mark.parametrize(
    "ad", ["", "case", "Case.generated", "case..x", "case.gen-erated", "a b.c"]
)
def test_gecersiz_olay_adi(ad: str) -> None:
    with pytest.raises(ValueError):
        build_payload(ad, {})


def test_buyuk_yuk_kisaltilir() -> None:
    yuk = build_payload("agent.step", {"id": "x1", "snapshot": "a" * 20_000})
    assert len(yuk.encode()) <= MAX_PAYLOAD
    assert json.loads(yuk)["data"] == {"id": "x1", "truncated": True}
