"""Kanıt okuma güvenliği: zip-slip, zip bombası, sembolik bağ, koşu dizini dışı yol, locator."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from tp_core.features.triage import evidence as ev

from .conftest import ARIA_KATALOG, trace_zip


def test_locator_test_idleri_bicimleri() -> None:
    assert ev.locator_test_idleri(
        "getByTestId('product-card-P-001').getByTestId('add-to-cart')"
    ) == ["product-card-P-001", "add-to-cart"]
    assert ev.locator_test_idleri('internal:testid=[data-testid="cart-total"s]') == ["cart-total"]
    assert ev.locator_test_idleri("locator('[data-testid=\"x-1\"]')") == ["x-1"]
    assert ev.locator_test_idleri("getByRole('button')") == []
    assert ev.locator_test_idleri(None) == []


def test_aria_eslesmeleri_rol_ve_ad() -> None:
    satirlar = ev.aria_eslesmeleri(ARIA_KATALOG, "button", "Sepete ekle")
    assert len(satirlar) == 2 and satirlar[0].startswith('- button "Sepete ekle"')
    assert ev.aria_eslesmeleri(ARIA_KATALOG, "button", "Sepete") == []
    assert ev.aria_eslesmeleri(ARIA_KATALOG, "link", "Sepet") == ['- link "Sepet"']
    assert ev.aria_eslesmeleri(None, "button", "x") == []


def test_kanit_yolu_kosu_dizini_disina_cikamaz() -> None:
    assert ev.kanit_yolu("runs/a", "runs/a/src/e2e/results/x/trace.zip") == (
        "src/e2e/results/x/trace.zip"
    )
    assert ev.kanit_yolu("runs/a", "runs/b/src/trace.zip") is None
    assert ev.kanit_yolu("runs/a", "runs/a/../b/trace.zip") is None
    assert ev.kanit_yolu("runs/a", "/etc/passwd") is None
    assert ev.kanit_yolu("runs/a", None) is None


def test_trace_oku_url_ve_dom_test_idleri(tmp_path: Path) -> None:
    (tmp_path / "t.zip").write_bytes(
        trace_zip(
            "http://demo-app-web:8080/katalog?x=1",
            [("BUTTON", "cart-add", "Sepete ekle"), ("ARTICLE", "product-card-P-001", "")],
        )
    )
    oz = ev.trace_oku(tmp_path, "t.zip")
    assert oz.okundu and oz.hata is None
    assert oz.son_url_yolu == "/katalog"
    assert oz.test_id_var_mi("cart-add") and not oz.test_id_var_mi("add-to-cart")
    assert {"etiket": "button", "test_id": "cart-add", "metin": "Sepete ekle"} in oz.elemanlar


def test_trace_zip_slip_uyesi_okunmaz_ve_diske_yazilmaz(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.trace", json.dumps({"type": "frame-snapshot"}))
        zf.writestr("/abs.trace", "{}")
        zf.writestr("sub/inner.trace", "{}")
    (tmp_path / "t.zip").write_bytes(buf.getvalue())
    oz = ev.trace_oku(tmp_path, "t.zip")
    assert not oz.okundu and oz.olay_sayisi == 0
    assert not (tmp_path.parent / "evil.trace").exists()


def test_trace_zip_bombasi_reddedilir(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("trace.trace", b"\n" * (5 * 1024 * 1024))  # oran >> 200
    (tmp_path / "t.zip").write_bytes(buf.getvalue())
    oz = ev.trace_oku(tmp_path, "t.zip")
    assert not oz.okundu and oz.hata and "sınır" in oz.hata


def test_trace_gecersiz_zip_ve_yok(tmp_path: Path) -> None:
    (tmp_path / "t.zip").write_bytes(b"PK-sahte")
    assert ev.trace_oku(tmp_path, "t.zip").hata == "trace.zip geçerli bir zip değil"
    assert ev.trace_oku(tmp_path, "yok.zip").hata == "trace dosyası yok"
    assert ev.trace_oku(tmp_path, None).hata == "trace yok"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink yok")
def test_sembolik_bag_ve_kok_disi_okunmaz(tmp_path: Path) -> None:
    kosu = tmp_path / "runs" / "a"
    kosu.mkdir(parents=True)
    gizli = tmp_path / "gizli.json"
    gizli.write_text('{"sir": 1}')
    (kosu / "run.json").symlink_to(gizli)
    with pytest.raises(ev.KanitHatasi, match="sembolik"):
        ev.kosu_raporu(kosu)
    with pytest.raises(ev.KanitHatasi, match="dışında"):
        ev.guvenli_oku(gizli, kosu, 100)


def test_boyut_siniri(tmp_path: Path) -> None:
    (tmp_path / "b.bin").write_bytes(b"x" * 101)
    with pytest.raises(ev.KanitHatasi, match="boyut"):
        ev.guvenli_oku(tmp_path / "b.bin", tmp_path, 100)
    assert ev.guvenli_oku(tmp_path / "yok", tmp_path, 100) is None


def test_aria_oku_error_context(tmp_path: Path) -> None:
    (tmp_path / "e.md").write_text(
        "# KTest info\n\n# Page snapshot\n\n```yaml\n" + ARIA_KATALOG + "\n```\n"
    )
    aria, kapsam = ev.aria_oku(tmp_path, "e.md")
    assert kapsam == "page" and aria is not None and '- button "Sepete ekle"' in aria
    assert ev.aria_oku(tmp_path, None) == (None, None)


def test_kosu_dizini_bicimi(tmp_path: Path) -> None:
    assert ev.kosu_dizini(tmp_path, "runs/ci-1") == tmp_path / "runs/ci-1"
    assert ev.kosu_dizini(tmp_path, "runs/../x") is None
    assert ev.kosu_dizini(tmp_path, None) is None
