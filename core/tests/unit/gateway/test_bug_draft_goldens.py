"""bug_draft golden'larının yeniden üretim adımları demo-app kurallarıyla gerçekten hatayı gösterir.

Her golden'ın adımları (giriş yapan bayi, ürün adı + adet) demo-app'in saf fiyat fonksiyonlarına
(`pricing.sepet_hesapla`, seed'deki minimum tutar ve kredi limitleri) karşı koşulur. Adımları
izleyen testçi hatayı görebilmelidir: beklenen sonuç başka bir kural yüzünden zaten doğru çıkıyorsa
(ör. minimum sipariş tutarı onayı zaten engelliyorsa) Jira bug'ı yeniden üretilemez.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.unit.gateway.demo_sources import (
    DEMO_API_SRC,
    PRODUCTS,
    cart,
    demo_module,
    golden_ref,
    goldens,
    scenario_goldens,
    seed_setting,
)
from tp_core.gateway import VERIFY_AGENT_DEALER

BUG_DRAFTS = [*goldens("bug_draft"), *scenario_goldens("bug_draft")]
SEED = (DEMO_API_SRC / "demoapp_api" / "seed.py").read_text(encoding="utf-8")


def _seed_dealers() -> dict[str, Decimal]:
    rows = re.findall(
        r'"kullanici_adi":\s*"(\w+)",[^}]*"kredi_limiti":\s*Decimal\("([\d.]+)"\)', SEED
    )
    assert rows, "seed.py içinde bayi yok"
    return {name: Decimal(limit) for name, limit in rows}


def _seed_products() -> dict[str, str]:
    rows = re.findall(r'"kod":\s*"(P-\d{3})",\s*"ad":\s*"([^"]+)"', SEED)
    assert rows, "seed.py içinde ürün yok"
    return {name: code for code, name in rows}


DEALERS = _seed_dealers()
PRODUCT_CODES = _seed_products()


def _repro(output: dict[str, Any]) -> tuple[str, list[tuple[str, int]]]:
    text = "\n".join(output["steps"])
    login = re.search(r"\b(bayi\d+) / ", text)
    assert login, f"giriş adımı yok: {text}"
    lines = [
        (PRODUCT_CODES[name], int(qty))
        for name, qty in re.findall(r'"([^"]+)" için (\d+) adet', text)
    ]
    assert lines, f"sepete ekleme adımı yok: {text}"
    return login.group(1), lines


def _ids(items: list[tuple[str, Path, Any]]) -> list[str]:
    return [golden_ref(path) for _, path, _ in items]


def test_seed_parsing_matches_demo_data() -> None:
    # e2e bayileri; seed'de ayrıca doğrulama ajanının bayisi (bayi3) vardır, bug adımları onu anmaz.
    assert {"bayi1": Decimal("2000.00"), "bayi2": Decimal("500.00")}.items() <= DEALERS.items()
    assert DEALERS.get(VERIFY_AGENT_DEALER) is not None
    assert PRODUCT_CODES["Şeftalili Soğuk Çay 1L"] == "P-004"


@pytest.mark.parametrize(("purpose", "path", "golden"), BUG_DRAFTS, ids=_ids(BUG_DRAFTS))
def test_bug_draft_steps_reproduce_the_bug(
    purpose: str, path: Path, golden: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = golden["output"]
    dealer, lines = _repro(out)
    money = demo_module("money")
    min_tl = money.format_tl(Decimal(seed_setting("min_siparis_tutari")))
    if "Kredi limiti aşıldı" in out["expected"]:
        result = cart(lines)
        limit = DEALERS[dealer]
        assert result.toplam > limit, f"toplam {result.toplam} limit {limit} altında: hata görünmez"
        # Başka bir kural onayı zaten engellerse "sipariş onaylanamaz" beklentisi tesadüfen
        # doğru olur ve kredi limiti hatası gözlenemez.
        assert result.uyarilar == [], [u.mesaj for u in result.uyarilar]
        assert result.onaylanabilir is True
        assert f"Minimum sipariş tutarı {min_tl}" not in " ".join(out["steps"])
        stated = re.search(r"toplam ([\d.]+,\d{2} TL)", " ".join(out["steps"]))
        if stated:
            assert stated.group(1) == money.format_tl(result.toplam)
    elif "bedava adet" in out["expected"]:
        _check_campaign(out, lines, monkeypatch)
    else:
        pytest.fail(f"{path.stem}: yeniden üretim kontrolü tanımlanmamış bug türü")


def _amounts(text: str) -> dict[str, str]:
    """ "bedava adet N", "indirim X TL", "toplam X TL" değerleri (metinde geçenler)."""
    out = {}
    for name, pattern in (
        ("bedava", r"bedava adet (\d+)"),
        ("indirim", r"indirim ([\d.]+,\d{2} TL)"),
        ("toplam", r"toplam ([\d.]+,\d{2} TL)"),
    ):
        m = re.search(pattern, text)
        if m:
            out[name] = m.group(1)
    return out


def _check_campaign(
    out: dict[str, Any], lines: list[tuple[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beklenen: TPD-1 AC2'nin özgün kuralı (7 adette 1 bedava = adet // 7). Gerçekleşen: bugünkü
    kod (`adet // 6`) ya da ortam satırı kırılmayı söylüyorsa BREAK_CAMPAIGN (bedava 0)."""
    money = demo_module("money")
    ((code, qty),) = lines
    price, campaign = PRODUCTS[code]
    assert campaign, f"{code} kampanyalı değil"
    doc_free = qty // 7
    doc = {
        "bedava": str(doc_free),
        "indirim": money.format_tl(price * doc_free),
        "toplam": money.format_tl(price * (qty - doc_free)),
    }
    expected = _amounts(out["expected"])
    assert expected.get("bedava") is not None, out["expected"]
    assert expected == {k: doc[k] for k in expected}, (expected, doc)

    broken = "BREAK_CAMPAIGN" in out["environment"] and "açık" in out["environment"]
    if broken:
        monkeypatch.setenv("BREAK_CAMPAIGN", "1")
    else:
        monkeypatch.delenv("BREAK_CAMPAIGN", raising=False)
    result = cart(lines)
    real = {
        "bedava": str(result.satirlar[0].bedava_adet),
        "indirim": money.format_tl(result.indirim),
        "toplam": money.format_tl(result.toplam),
    }
    actual = _amounts(out["actual"])
    assert actual.get("bedava") is not None, out["actual"]
    assert actual == {k: real[k] for k in actual}, (actual, real)
    # Hata gerçekten görünür: aynı adımlarda beklenen ≠ gerçekleşen.
    assert expected["bedava"] != actual["bedava"]


def test_old_credit_limit_steps_would_not_reproduce() -> None:
    """Kontrolün kendisi: 20 × P-004 (600 TL) minimum tutara takılır, kredi hatası görünmez."""
    result = cart([("P-004", 20)])
    assert result.toplam > DEALERS["bayi2"]
    assert result.onaylanabilir is False and result.uyarilar
