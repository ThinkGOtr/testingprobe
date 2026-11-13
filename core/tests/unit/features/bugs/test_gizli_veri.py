"""Canlı UI bulgusu: bug taslağında demo parolası düz metin ("bayi1 / Demo123! ile giriş yap").

Gizli işaretli test verisi kaydı (sır ortamda tanımsız olsa da) okumada ve Jira'ya giden metinde
`{veri:ortak.demo_parola}` atfına çevrilir; atfa dönemeyen bitişik geçiş `•••` olur. Saklanan
içerik ve `icerik_hash` değişmez.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.unit.features.bugs.helpers import seed_finding_draft
from tests.unit.features.cases.helpers import login
from tp_core.features.bugs import content
from tp_core.features.bugs.context import BugContext, finding_context
from tp_core.features.testveri import atif
from tp_core.features.testveri import service as tv
from tp_core.models import BugDraft, session_scope
from tp_core.models.otomasyon_feature import TestVerisi

PAROLA = "Demo123!"
ATIF = "{veri:ortak.demo_parola}"


def test_gizle_obje_atif_bitisik_maske_yapisal_alan_korunur() -> None:
    eslem = {PAROLA: "ortak.demo_parola"}
    obj = {
        "steps": ["1. bayi1 / Demo123! ile giriş yap", "2. Demo123!x yaz"],
        "summary": "Giriş",
        "finding_id": "Demo123!-id",
        "evidence": [{"kind": "data", "ref": "parola=Demo123!"}],
    }
    out = atif.gizle_obje(obj, eslem, [PAROLA])
    assert out["steps"][0] == f"1. bayi1 / {ATIF} ile giriş yap"
    assert out["steps"][1] == "2. •••x yaz"
    assert out["finding_id"] == "Demo123!-id"
    assert out["evidence"][0]["ref"] == f"parola={ATIF}"
    # Eşlem yoksa yalnız maske; hiçbiri yoksa nesne aynen döner.
    assert atif.gizle_obje("a Demo123! b", {}, [PAROLA]) == "a ••• b"
    assert atif.gizle_obje(obj, {}, []) is obj


def test_content_maskele_eslem_ile_atfa_cevirir() -> None:
    ctx = BugContext(
        kaynak="finding", gizli_degerler=[PAROLA], gizli_eslem={PAROLA: "ortak.demo_parola"}
    )
    out = content.maskele({"steps": ["bayi1 / Demo123! ile giriş yap"]}, ctx)
    assert out == {"steps": [f"bayi1 / {ATIF} ile giriş yap"]}


def _sirsiz_gizli_parola_kaydi() -> None:
    """Katalogdaki gibi: gizli işaretli, sırrı ortamda tanımsız (`sır tanımsız` etiketi)."""
    with session_scope() as s:
        s.add(
            TestVerisi(
                anahtar=tv.DEMO_PAROLA_ANAHTARI,
                grup="ortak",
                gizli=True,
                sir_adi=tv.DEMO_PAROLA_SIRRI,
                guncelleyen="test",
            )
        )


def _duz_parolali_taslak() -> dict[str, Any]:
    ids = seed_finding_draft("F4")
    with session_scope() as s:
        b = s.get(BugDraft, ids["draft_id"])
        assert b is not None
        b.icerik = {**b.icerik, "steps": ["1. bayi1 / Demo123! ile giriş yap", "2. Sepete git"]}
        ids["hash"] = b.icerik_hash
    return ids


@pytest.mark.usefixtures("db")
def test_okumada_eski_kayit_maskelenir_sir_tanimsiz_olsa_da(
    api: TestClient, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(tv.DEMO_PAROLA_SIRRI, raising=False)
    _sirsiz_gizli_parola_kaydi()
    ids = _duz_parolali_taslak()
    login(api, make_user("tester"))
    for yol in ("/bug-drafts", f"/bug-drafts/{ids['draft_id']}/detail"):
        r = api.get(yol)
        assert r.status_code == 200, r.text
        assert PAROLA not in r.text, yol
        assert ATIF in r.text, yol
    with session_scope() as s:
        b = s.get(BugDraft, ids["draft_id"])
        assert b is not None
        # Yalnız görünüm: saklanan içerik ve hash değişmez (onay kapısı bozulmaz).
        assert PAROLA in b.icerik["steps"][0] and b.icerik_hash == ids["hash"]
        # Yayın (Jira'ya giden metin) aynı dönüşümü kullanır.
        assert tv.gizle(s, b.icerik)["steps"][0] == f"1. bayi1 / {ATIF} ile giriş yap"


@pytest.mark.usefixtures("db")
def test_bulgu_baglami_gizli_degerleri_tasir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tutarlılık bulgusu yolu da (önceden yalnız başarısızlık yolu) gizli değerleri bilir."""
    monkeypatch.delenv(tv.DEMO_PAROLA_SIRRI, raising=False)
    _sirsiz_gizli_parola_kaydi()
    ids = seed_finding_draft("F4")
    with session_scope() as s:
        ctx = finding_context(s, ids["finding_id"])
    assert PAROLA in ctx.gizli_degerler
    assert ctx.gizli_eslem.get(PAROLA) == tv.DEMO_PAROLA_ANAHTARI
