"""Trace DOM: Playwright snapshot başvurularının çözümü ve `trace_dom` sinyalinin dürüstlüğü.

Regresyon: `trace_oku` eskiden yalnızca son frame-snapshot'ın `html`'ini gezerdi; gerçek
izlerde bu çoğu zaman `[[1, 10]]` gibi bir başvurudur → 0 testId → "'cart-add' yok" sahte kanıtı.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from tp_core.features.triage import evidence as ev
from tp_core.features.triage.rules import Girdi
from tp_core.features.triage.service import _trace_dom_degerlendir, llm_ciktisi_dogrula

DATA = Path(__file__).parent / "data"


def _son_snapshot_html(zip_yolu: Path, uye: str) -> Any:
    with zipfile.ZipFile(zip_yolu) as zf:
        son = None
        for satir in zf.read(uye).splitlines():
            olay = json.loads(satir)
            if olay.get("type") == "frame-snapshot":
                son = olay["snapshot"]["html"]
    return son


def test_gercek_pw_1_64_trace_basvurulari_cozulur(tmp_path: Path) -> None:
    shutil.copy(DATA / "pw_1_64_trace_locator.zip", tmp_path / "t.zip")
    # Fikstürün son snapshot'ı gerçekten yalnızca bir başvuru (eski kodu kıran durum).
    son = _son_snapshot_html(tmp_path / "t.zip", "trace.trace")
    assert ev._basvuru_mu(son), son
    oz = ev.trace_oku(tmp_path, "t.zip")
    assert oz.okundu and oz.dom_cozuldu and not oz.dom_kismi
    assert oz.snapshot_sayisi == 7 and oz.dom_kaynagi == "basarisiz_eylem"
    assert oz.test_id_var_mi("cart-add")
    assert not oz.test_id_var_mi("add-to-cart")
    assert oz.test_id_var_mi("product-card-P-001")
    assert oz.dom_kullanilabilir and oz.ozet()["dom_test_id_sayisi"] >= 3
    buton = next(e for e in oz.elemanlar if e["test_id"] == "cart-add")
    assert buton["etiket"] == "button"


def test_gercek_test_runner_trace_coklu_uye(tmp_path: Path) -> None:
    """test-runner'ın ürettiği `0-trace/1-trace/test.trace` düzeni."""
    shutil.copy(DATA / "pw_1_64_test_trace_locator.zip", tmp_path / "t.zip")
    assert ev._basvuru_mu(_son_snapshot_html(tmp_path / "t.zip", "1-trace.trace"))
    oz = ev.trace_oku(tmp_path, "t.zip")
    assert oz.test_id_var_mi("cart-add") and not oz.test_id_var_mi("add-to-cart")


def _zip(satirlar: list[dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("trace.trace", "\n".join(json.dumps(s) for s in satirlar))
    return buf.getvalue()


def _snap(html: Any, call: str | None = None) -> dict[str, Any]:
    return {
        "type": "frame-snapshot",
        "snapshot": {
            "frameId": "f1",
            "frameUrl": "http://demo-app-web:8080/katalog",
            "callId": call,
            "isMainFrame": True,
            "html": html,
        },
    }


TAM = [
    "HTML",
    {},
    ["BODY", {}, ["BUTTON", {"data-testid": "cart-add"}, "Sepete ekle"]],
]


def test_son_snapshot_basvuru_ise_onceki_snapshot_cozulur(tmp_path: Path) -> None:
    # post-order düğümler: "Sepete ekle"(0), BUTTON(1), BODY(2), HTML(3)
    (tmp_path / "t.zip").write_bytes(_zip([_snap(TAM), _snap([[1, 3]])]))
    oz = ev.trace_oku(tmp_path, "t.zip")
    assert oz.dom_kaynagi == "son_snapshot"
    assert oz.elemanlar == [{"etiket": "button", "test_id": "cart-add", "metin": "Sepete ekle"}]


def test_basarisiz_eylemin_snapshotu_secilir(tmp_path: Path) -> None:
    sonraki = ["HTML", {}, ["BODY", {}, ["P", {"data-testid": "baska"}, "x"]]]
    satirlar = [
        {"type": "before", "callId": "c1", "method": "click", "params": {"selector": "x"}},
        _snap(TAM, "c1"),
        {"type": "after", "callId": "c1", "error": {"message": "Timeout"}},
        _snap(sonraki, "c2"),
    ]
    (tmp_path / "t.zip").write_bytes(_zip(satirlar))
    oz = ev.trace_oku(tmp_path, "t.zip")
    assert oz.dom_kaynagi == "basarisiz_eylem" and oz.test_id_var_mi("cart-add")
    assert not oz.test_id_var_mi("baska")


def test_gecersiz_ve_dongusel_basvurular_guvenli(tmp_path: Path) -> None:
    satirlar = [_snap(["HTML", {}, [[0, 0]], [[5, 1]], [[1, 999]]]), _snap([[1, 999]])]
    (tmp_path / "t.zip").write_bytes(_zip(satirlar))
    oz = ev.trace_oku(tmp_path, "t.zip")
    assert oz.okundu and oz.dom_kismi and oz.elemanlar == []
    assert not oz.dom_kullanilabilir


# ------------------------------------------------------------------ trace_dom değerlendirmesi


def _oz(elemanlar: list[str], okundu: bool = True) -> ev.TraceOzeti:
    oz = ev.TraceOzeti(okundu=okundu, dom_kaynagi="basarisiz_eylem")
    oz.elemanlar = [{"etiket": "button", "test_id": t, "metin": ""} for t in elemanlar]
    return oz


def test_trace_dom_yalnizca_eski_yok_yeni_var_ise_destekler() -> None:
    d = _trace_dom_degerlendir(_oz(["cart-add"]), "add-to-cart", "cart-add")
    assert d["destekliyor"] and d["durum"] == "destekliyor"
    assert "'add-to-cart' yok, 'cart-add' var" in d["aciklama"]


def test_trace_dom_okunamadiysa_yok_demez() -> None:
    d = _trace_dom_degerlendir(_oz([]), "add-to-cart", "cart-add")
    assert not d["destekliyor"] and d["durum"] == "okunamadi"
    assert d["eski_var"] is None and d["yeni_var"] is None
    assert "okunamadı" in d["aciklama"] and "'cart-add' yok" not in d["aciklama"]
    d2 = _trace_dom_degerlendir(_oz([], okundu=False), "add-to-cart", "cart-add")
    assert d2["durum"] == "okunamadi" and not d2["destekliyor"]


def test_trace_dom_celisen_ve_belirsiz_destekleme_degil() -> None:
    d = _trace_dom_degerlendir(_oz(["add-to-cart"]), "add-to-cart", "cart-add")
    assert d["durum"] == "celisiyor" and not d["destekliyor"]
    d = _trace_dom_degerlendir(_oz(["product-card-P-001"]), "add-to-cart", "cart-add")
    assert d["durum"] == "belirsiz" and not d["destekliyor"]
    assert "trace anında görülmedi" in d["aciklama"]


# -------------------------------------------------------------- LLM çıktısı son doğrulaması


def test_llm_environment_saglik_ok_ve_ag_yokken_reddedilir() -> None:
    g = Girdi("t", hata_turu="assertion", mesaj="expect(x).toHaveText", saglik={"ok": True})
    sinif, alt, duz = llm_ciktisi_dogrula(g, "environment", None)
    assert (sinif, alt) == ("unknown", None)
    assert [d["kod"] for d in duz] == ["llm_ortam_reddedildi"]


def test_llm_environment_ag_sinyali_varsa_kabul() -> None:
    g = Girdi("t", mesaj="page.goto: net::ERR_CONNECTION_REFUSED", saglik={"ok": True})
    assert llm_ciktisi_dogrula(g, "environment", None) == ("environment", None, [])
    # sağlık bilgisi yoksa (ok true değil) kısıt uygulanmaz
    assert llm_ciktisi_dogrula(Girdi("t"), "environment", None)[0] == "environment"


def test_llm_test_maintenance_alt_tur_enum() -> None:
    g = Girdi("t", saglik={"ok": True})
    for alt in ("locator", "wait", "flow"):
        assert llm_ciktisi_dogrula(g, "test_maintenance", alt) == ("test_maintenance", alt, [])
    for alt in ("selector-rot", None, "LOCATOR"):
        sinif, a, duz = llm_ciktisi_dogrula(g, "test_maintenance", alt)
        assert (sinif, a) == ("unknown", None)
        assert [d["kod"] for d in duz] == ["llm_alt_tur_gecersiz"]
    # başka sınıflarda alt tür atılır
    assert llm_ciktisi_dogrula(g, "product_defect", "locator") == ("product_defect", None, [])
    assert llm_ciktisi_dogrula(g, "uydurma", None)[0] == "unknown"
