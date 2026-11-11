"""Kontrol Kulesi: story başına manuel baz değer, varsayılana düşme, kapsam ve toplam kazanç.

Gerçek Postgres; değerler API'den (analist/PO) girilir. Ölçülmeyen story kazanca girmez, sayısı
uydurulmaz; varsayılan değer her yerde "varsayilan" diye etiketlenir.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import login
from tp_core.audit import record_ai_call
from tp_core.features.control_tower import service as ct
from tp_core.models import TestCase
from tp_core.models.guard import allow_state_write

pytestmark = pytest.mark.usefixtures("ci_env")

# story → canlı (ölçülmüş) case üretimi süresi, ms. Review yok: taban 0 → review 0 ms (ölçüldü).
AI_MS = {"TPD-1": 600_000, "TPD-2": 1_200_000, "TPD-3": 300_000, "TPD-4": 900_000}


@pytest.fixture
def dort_story(
    engine: Engine, make_requirement_case, monkeypatch: pytest.MonkeyPatch
) -> dict[str, uuid.UUID]:
    monkeypatch.setenv("TP_CT_REVIEW_MIN_S", "0")
    monkeypatch.delenv("TP_MANUAL_BASELINE_S", raising=False)
    for key, sure in AI_MS.items():
        case_id = make_requirement_case(jira_key=key, title=f"{key} case")
        with Session(engine) as s, s.begin(), allow_state_write():
            call_id = record_ai_call(
                s.connection(),
                {"amac": "case_generation", "saglayici": "anthropic", "model": "m",
                 "mod": "live", "maliyet": Decimal("0.1"), "sure_ms": sure},
            )  # fmt: skip
            s.execute(update(TestCase).where(TestCase.id == case_id).values(ai_call_id=call_id))
    return dict(make_requirement_case.reqs)


def _kule(engine: Engine) -> dict:
    with Session(engine) as s:
        return ct.control_tower(s)


def test_olcum_varsayilan_olculmedi_ve_kazanc(
    api: TestClient,
    engine: Engine,
    make_user,
    dort_story: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login(api, make_user("po"))
    r = api.put(
        f"/requirements/{dort_story['TPD-1']}/baseline",
        json={"deger_s": 3600, "not": "F0 ölçümü – İsmail"},
    )
    assert r.status_code == 200, r.text
    login(api, make_user("po"))
    r = api.put(
        f"/requirements/{dort_story['TPD-2']}/baseline",
        json={"deger_s": 2400, "not": "F0 ölçümü – İsmail"},
    )
    assert r.status_code == 200, r.text

    # 1) Varsayılan yok: yalnızca ölçülen 2 story kazanca girer.
    k = _kule(engine)
    ai = k["ai_katkisi"]
    h = {x["story_key"]: x for x in k["hazirlik"]}
    assert {x: h[x]["manuel_baz_kaynagi"] for x in h} == {
        "TPD-1": "olcum",
        "TPD-2": "olcum",
        "TPD-3": None,
        "TPD-4": None,
    }
    assert h["TPD-1"]["manuel_baz_ms"] == 3_600_000 and h["TPD-1"]["toplam_ms"] == 600_000
    assert h["TPD-1"]["kazanc_orani"] == round(1 - 600 / 3600, 4)
    assert h["TPD-1"]["manuel_baz"]["not"] == "F0 ölçümü – İsmail"
    assert h["TPD-3"]["manuel_baz_ms"] is None and h["TPD-3"]["kazanc_orani"] is None
    assert ai["baz_kapsami"] == {
        "story": 4,
        "olcum": 2,
        "varsayilan": 0,
        "olculmedi": 2,
        "metin": "4 story'den 2'sinde ölçüm var, 2'sinde ölçülmedi",
    }
    # 1 − (600 + 1200) / (3600 + 2400)
    assert (ai["kazanc_orani"], ai["kazanc_story_sayisi"]) == (0.7, 2)
    assert ai["manuel_baz_ms"] == 3_000_000 and ai["manuel_baz_yontemi"] == "story_ortalamasi"
    assert ai["manuel_baz_varsayilan_ms"] is None and ai["baz_deger_olculmedi"] is False
    assert any(u.startswith("4 story'den 2'sinde ölçüm var") for u in k["uyarilar"])
    assert not any("varsayılan (TP_MANUAL_BASELINE_S) kullanıldı" in u for u in k["uyarilar"])
    for kpi in ("manuel_baz", "kazanc_orani", "baz_kapsami", "hazirlik_suresi"):
        assert k["kaynaklar"][kpi]

    # 2) Varsayılan verilince ölçülmeyenler "varsayilan" etiketiyle girer.
    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "1800")
    k = _kule(engine)
    ai = k["ai_katkisi"]
    h = {x["story_key"]: x for x in k["hazirlik"]}
    assert h["TPD-3"]["manuel_baz_kaynagi"] == "varsayilan"
    assert h["TPD-3"]["manuel_baz"]["etiket"] == "varsayılan"
    assert h["TPD-1"]["manuel_baz_kaynagi"] == "olcum"  # ölçüm varsayılanı ezer
    assert (ai["baz_kapsami"]["olcum"], ai["baz_kapsami"]["varsayilan"]) == (2, 2)
    assert ai["baz_kapsami"]["olculmedi"] == 0
    # Varsayılan baz kazanca girmez: yalnızca ölçülmüş 2 story → 1 − (600 + 1200) / (3600 + 2400)
    assert (ai["kazanc_orani"], ai["kazanc_story_sayisi"]) == (0.7, 2)
    assert h["TPD-3"]["kazanc_orani"] is None and h["TPD-3"]["toplam_ms"] == 300_000
    assert h["TPD-1"]["toplam_yontemi"] == "ai_arti_review"
    assert h["TPD-1"]["kazanca_girer"] is True and h["TPD-3"]["kazanca_girer"] is False
    # Varsayılan sayı olarak gösterilmez ve ortalamaya girmez: yalnızca ölçülmüş 2 story.
    assert h["TPD-3"]["manuel_baz_ms"] is None
    assert h["TPD-3"]["manuel_baz"]["varsayilan_ms"] == 1_800_000
    assert ai["manuel_baz_ms"] == round((3600 + 2400) * 1000 / 2)
    assert ai["manuel_baz_varsayilan_ms"] == 1_800_000
    assert any(
        "2 story'de story'ye özel ölçüm yok" in u and "kazanca girmez" in u for u in k["uyarilar"]
    )

    # 3) Ölçüm silinince story varsayılana düşer (geçmiş kalır).
    assert api.delete(f"/requirements/{dort_story['TPD-2']}/baseline").status_code == 200
    ai = _kule(engine)["ai_katkisi"]
    assert ai["baz_kapsami"]["metin"] == (
        "4 story'den 1'inde ölçüm var, 3'ünde ölçüm yok (yalnız varsayılan TP_MANUAL_BASELINE_S; "
        "ölçüm sayılmaz)"
    )


def test_hicbir_story_olculmediyse_sayi_yok(
    engine: Engine, dort_story: dict[str, uuid.UUID]
) -> None:
    k = _kule(engine)
    ai = k["ai_katkisi"]
    assert ai["manuel_baz_ms"] is None and ai["baz_deger_olculmedi"] is True
    assert ai["kazanc_orani"] is None and ai["kazanc_story_sayisi"] == 0
    assert ai["baz_kapsami"]["olculmedi"] == 4
    assert ct.BAZ_YOK in k["uyarilar"]
    assert all(x["kazanc_orani"] is None and x["manuel_baz_ms"] is None for x in k["hazirlik"])


def test_replay_hazirlik_suresi_yalniz_review(
    api: TestClient,
    engine: Engine,
    make_user,
    make_requirement_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REPLAY: AI süresi ölçülmez, hazırlık süresi yalnız review (etiketli; DEMO-VERISI)."""
    monkeypatch.setenv("TP_CT_REVIEW_MIN_S", "0")
    monkeypatch.delenv("TP_MANUAL_BASELINE_S", raising=False)
    case_id = make_requirement_case(jira_key="TPD-1", title="TPD-1 case")
    with Session(engine) as s, s.begin(), allow_state_write():
        call_id = record_ai_call(
            s.connection(),
            {"amac": "case_generation", "saglayici": "replay", "model": "golden-elle",
             "mod": "replay", "maliyet": Decimal("0"), "sure_ms": 0},
        )  # fmt: skip
        s.execute(update(TestCase).where(TestCase.id == case_id).values(ai_call_id=call_id))
    rid = make_requirement_case.reqs["TPD-1"]
    h = _kule(engine)["hazirlik"][0]
    assert h["ai_olculmedi"] is True and h["review_olculmedi"] is False
    assert h["toplam_yontemi"] == "yalniz_review" and h["toplam_ms"] == h["review_sure_ms"]
    assert h["kazanc_orani"] is None  # ölçüm yok → kazanç yok
    login(api, make_user("po"))
    r = api.put(f"/requirements/{rid}/baseline", json={"deger_s": 3600, "not": "F0 ölçümü"})
    assert r.status_code == 200, r.text
    k = _kule(engine)
    h = k["hazirlik"][0]
    assert h["manuel_baz_kaynagi"] == "olcum"
    t = h["toplam_ms"]
    beklenen = round(1 - t / 3_600_000, 4) if t else None  # 0 ms hazırlık ölçüm değildir
    # Story satırında etiketli (REPLAY: yalnız review) oran kalır...
    assert h["kazanc_orani"] == beklenen and h["kazanca_girer"] is False
    # ...ama sunumdaki review tıklamaları toplam (başlık) kazanca girmez.
    ai = k["ai_katkisi"]
    assert ai["kazanc_orani"] is None and ai["kazanc_story_sayisi"] == 0
    assert ai["kazanc_replay_haric"] == (1 if t else 0)
    if t:
        assert ai["kazanc_notu"] == ct.KAZANC_REPLAY.format(n=1)
        assert ct.KAZANC_REPLAY.format(n=1) in k["uyarilar"]
        assert "verimlilik iddiası değildir" in ai["kazanc_notu"]


def test_replay_review_uzunsa_bile_baslik_kazanci_yok(
    api: TestClient,
    engine: Engine,
    make_user,
    make_requirement_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ölçülmüş baz + REPLAY review süresi (≈ %98) başlık kazancı üretmez; canlı story üretir."""
    monkeypatch.setenv("TP_CT_REVIEW_MIN_S", "0")
    monkeypatch.delenv("TP_MANUAL_BASELINE_S", raising=False)
    for key, mod, sure in (("TPD-1", "replay", 0), ("TPD-2", "live", 600_000)):
        case_id = make_requirement_case(jira_key=key, title=f"{key} case")
        with Session(engine) as s, s.begin(), allow_state_write():
            call_id = record_ai_call(
                s.connection(),
                {"amac": "case_generation", "saglayici": "x", "model": "m", "mod": mod,
                 "maliyet": Decimal("0"), "sure_ms": sure},
            )  # fmt: skip
            s.execute(update(TestCase).where(TestCase.id == case_id).values(ai_call_id=call_id))
    from tp_core.features.cases import service as cases

    gercek = cases.requirement_metrics
    monkeypatch.setattr(
        cases,
        "requirement_metrics",
        lambda session, rid: {**gercek(session, rid), "review_sure_ms": 54_000},
    )
    login(api, make_user("po"))
    for key in ("TPD-1", "TPD-2"):
        r = api.put(
            f"/requirements/{make_requirement_case.reqs[key]}/baseline",
            json={"deger_s": 2700, "not": "F0 ölçümü – İsmail"},
        )
        assert r.status_code == 200, r.text
    k = _kule(engine)
    h = {x["story_key"]: x for x in k["hazirlik"]}
    assert h["TPD-1"]["toplam_yontemi"] == "yalniz_review"
    assert h["TPD-1"]["kazanc_orani"] == round(1 - 54 / 2700, 4)  # %98: yalnız satırda, etiketli
    ai = k["ai_katkisi"]
    # Başlık yalnızca canlı (AI + review) story'den: 1 − 654 / 2700
    assert (ai["kazanc_orani"], ai["kazanc_story_sayisi"]) == (round(1 - 654 / 2700, 4), 1)
    assert ai["kazanc_replay_haric"] == 1 and ai["kazanc_notu"] is None
    assert ct.KAZANC_REPLAY.format(n=1) in k["uyarilar"]
