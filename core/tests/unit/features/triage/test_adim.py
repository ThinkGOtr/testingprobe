"""Başarısız doğrulamanın case alanları (`triage.adim`; review tur 1 O6). Saf; DB yok.

Üretilen testler gerçek şablonlarla (`render_test`, `render_java_test`) demo ana yolunun C3
eşlemesinden (verify_and_map golden'ı) render edilir; satır numaraları render çıktısından bulunur.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest

from tp_core.features.codegen.render import RenderInput, render_java_test, render_test
from tp_core.features.triage.adim import cagri_argumanlari, hata_alanlari
from tp_core.gateway import find_rules_dir

RULES = find_rules_dir()
SENARYO = RULES / "replay"
C3: dict[str, Any] = json.loads(
    (SENARYO / "case_generation/golden/f2-kod-hatasi/TPD-1.json").read_text(encoding="utf-8")
)["output"]["cases"][2]
ESLEME: dict[str, Any] = json.loads(
    (SENARYO / "verify_and_map/golden/f2-kod-hatasi/TPD-1-C3.json").read_text(encoding="utf-8")
)["output"]
S4 = "steps[3].expected"


def _kaynak(java: bool = False, case: dict[str, Any] | None = None) -> str:
    inp = RenderInput(
        case_id=uuid.UUID(int=3),
        case=case or C3,
        sira_no=3,
        story_key="TPD-1",
        test_key=None,
        case_hash="h",
        mode="replay",
        bundle_hash=None,
        mapping=ESLEME,
        dealers={},
    )
    r = render_java_test(inp, "android", RULES) if java else render_test(inp, RULES)
    return r.content


def _satir(kaynak: str, parca: str) -> int:
    [n] = [i for i, s in enumerate(kaynak.splitlines(), start=1) if parca in s]
    return n


@pytest.mark.parametrize("java", [False, True], ids=["playwright", "java"])
def test_beklenen_sonuc_dogrulamasi_degerin_gectigi_alanlar(java: bool) -> None:
    """C3 `expectFreeQuantity("P-001", 0)` kırmızı (beklenen 0): 0 yalnız S4'ün beklenen
    metninde ve case'in beklenen sonucunda geçer."""
    k = _kaynak(java)
    satir = _satir(k, "expectFreeQuantity(")
    alanlar = hata_alanlari(C3, kaynak=k, satir=satir, java=java, beklenen='"0"')
    assert alanlar == frozenset({S4, "expected_result"})
    # Toplam (150,00 TL) da yalnız S4 + beklenen sonuçta.
    satir = _satir(k, "expectTotal(")
    assert hata_alanlari(C3, kaynak=k, satir=satir, java=java, beklenen="150,00 TL") == (
        frozenset({S4, "expected_result"})
    )


def test_deger_birden_cok_adimda_geciyorsa_belirsiz() -> None:
    """`expectLineQuantity("P-001", 6)`: 6 hem S3'te ("Sepet sayacı 6 olur") hem S4'te geçer;
    hangi adımın doğrulandığı bilinemez → None (inceltme yok)."""
    k = _kaynak()
    satir = _satir(k, "expectLineQuantity(")
    assert hata_alanlari(C3, kaynak=k, satir=satir, beklenen='"6"') is None


def test_eylem_satiri_kendi_adimina_aittir() -> None:
    """S3'ün eylem çağrısında kırmızı (ör. sepete ekleme kendi doğrulamasında düştü) → S3."""
    k = _kaynak()
    satir = _satir(k, "addToCart(")
    assert hata_alanlari(C3, kaynak=k, satir=satir, beklenen='"1"') == frozenset(
        {"steps[2].expected"}
    )


def test_beklenen_deger_argumanlarda_yoksa_belirsiz() -> None:
    k = _kaynak()
    satir = _satir(k, "expectFreeQuantity(")
    assert hata_alanlari(C3, kaynak=k, satir=satir, beklenen='"7"') is None
    assert hata_alanlari(C3, kaynak=k, satir=satir, beklenen=None) is None


@pytest.mark.parametrize("satir", [0, 1, 9, 10_000, None])
def test_cagri_satiri_degilse_belirsiz(satir: int | None) -> None:
    """Yorum, tanım ya da kaynak dışı satır → None."""
    assert hata_alanlari(C3, kaynak=_kaynak(), satir=satir, beklenen='"0"') is None


def test_kaynak_ya_da_icerik_yoksa_belirsiz() -> None:
    assert hata_alanlari(C3, kaynak=None, satir=21, beklenen='"0"') is None
    assert hata_alanlari(None, kaynak=_kaynak(), satir=21, beklenen='"0"') is None


@pytest.mark.parametrize(
    ("yol", "beklenen"),
    [
        (["S4 — Sepeti kontrol et"], frozenset({S4})),
        (["S4: Sepeti kontrol et", "expect.toHaveText"], frozenset({S4})),
        (["S2 — Giriş", "S4"], frozenset({S4})),  # en derindeki adım
        (["S9 — case'te yok"], None),
    ],
)
def test_playwright_adim_basligi(yol: list[str], beklenen: frozenset[str] | None) -> None:
    """Elle yazılmış testte `test.step("S4 — …")` başlığı adımı belirler (kaynak gerekmez)."""
    assert hata_alanlari(C3, adim_yolu=yol, beklenen='"0"') == beklenen


def test_adimsiz_baslik_kaynaga_duser() -> None:
    k = _kaynak()
    alanlar = hata_alanlari(
        C3,
        adim_yolu=['Expect "toHaveText"'],
        kaynak=k,
        satir=_satir(k, "expectFreeQuantity("),
        beklenen='"0"',
    )
    assert alanlar == frozenset({S4, "expected_result"})


@pytest.mark.parametrize(
    ("satir", "java", "args"),
    [
        ('    await cartPage.expectTotal("150,00 TL");', False, ["150,00 TL"]),
        ('    await a.b("x, \\"y\\"", 6, -2.5, true);', False,
         ['x, "y"', Decimal(6), Decimal("-2.5"), True]),
        ("    await a.b();", False, []),
        ("    await a.b(degisken);", False, None),
        ('    sepetEkrani().dogrulaToplam("150,00 TL");', True, ["150,00 TL"]),
        ("    a().b(9000000000L, 2.5, false);", True, [Decimal(9000000000), Decimal("2.5"), False]),
        ('    a().b("kapanmamış);', True, None),
        ("    // S1 — Giriş", False, None),
    ],
)  # fmt: skip
def test_cagri_argumanlari(satir: str, java: bool, args: list[Any] | None) -> None:
    assert cagri_argumanlari(satir, java=java) == args
