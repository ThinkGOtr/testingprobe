"""`product_search` / `product_read`: MANIFEST birebir, satır sınırı, yol güvenliği.

AI-ASISTAN-PLANI §5.1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tp_core.features.assistant.paket import MANIFEST_ADI, uret
from tp_core.features.assistant.tools.product import (
    MAX_LINES,
    MAX_SEARCH_RESULTS,
    TOOL_SPECS,
    ProductToolError,
    UrunBilgisi,
)


@pytest.fixture
def paket(tmp_path: Path) -> Path:
    kaynak = tmp_path / "repo"
    dosyalar = {
        "README.md": "# Testing Probe\nAsistan paneli.\n",
        "docs/ONBOARDING.md": "Kurulum adımları\nmake up\n",
        "core/src/tp_core/uzun.py": "".join(f"satir_{i} = {i}\n" for i in range(1, 1001)),
        "core/src/tp_core/worker/__init__.py": '"""Worker."""\nASISTAN = "kuyruk"\n',
        "review-portal/src/App.tsx": "// Asistan düğmesi\nexport const App = () => null;\n",
        "review-portal/src/bos.css": "",
    }
    for yol, metin in dosyalar.items():
        p = kaynak / yol
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(metin, encoding="utf-8")
    cikti = tmp_path / "tp-bilgi"
    assert not uret(kaynak, cikti, commit="abc", ortam_degerleri=[]).bulgular
    return cikti


@pytest.fixture
def bilgi(paket: Path) -> UrunBilgisi:
    return UrunBilgisi(paket)


def _gecerli_dizin(paket: Path) -> Path:
    return paket / json.loads((paket / MANIFEST_ADI).read_text("utf-8"))["dizin"]


def test_tool_specs() -> None:
    assert [s.name for s in TOOL_SPECS] == ["product_search", "product_read"]


def test_read_satir_numarali(bilgi: UrunBilgisi) -> None:
    out = bilgi.product_read({"path": "core/src/tp_core/worker/__init__.py"})
    assert out.splitlines() == [
        "core/src/tp_core/worker/__init__.py (satır 1-2 / 2)",
        '1| """Worker."""',
        '2| ASISTAN = "kuyruk"',
    ]


def test_read_400_satir_siniri_ve_aralik(bilgi: UrunBilgisi) -> None:
    out = bilgi.product_read({"path": "core/src/tp_core/uzun.py"}).splitlines()
    assert out[0] == f"core/src/tp_core/uzun.py (satır 1-{MAX_LINES} / 1000)"
    assert len(out) == MAX_LINES + 1
    out = bilgi.product_read(
        {"path": "core/src/tp_core/uzun.py", "start_line": 990, "end_line": 2000}
    )
    assert out.splitlines()[0] == "core/src/tp_core/uzun.py (satır 990-1000 / 1000)"
    with pytest.raises(ProductToolError):
        bilgi.product_read({"path": "core/src/tp_core/uzun.py", "start_line": 1001})
    with pytest.raises(ProductToolError):
        bilgi.product_read({"path": "core/src/tp_core/uzun.py", "start_line": 0})
    with pytest.raises(ProductToolError):
        bilgi.product_read({"path": "core/src/tp_core/uzun.py", "start_line": 5, "end_line": 2})
    assert (
        bilgi.product_read({"path": "review-portal/src/bos.css"})
        == "review-portal/src/bos.css (boş dosya)"
    )


def test_bos_yol_liste_ve_dizin_listesi(bilgi: UrunBilgisi) -> None:
    liste = bilgi.product_read({"path": ""}).splitlines()
    assert "README.md" in liste and "core/src/tp_core/uzun.py" in liste
    assert bilgi.product_read({"path": "review-portal/"}).splitlines() == [
        "review-portal/src/App.tsx",
        "review-portal/src/bos.css",
    ]
    assert "dosya yok" in bilgi.product_read({"path": "yok/"})


@pytest.mark.parametrize(
    "yol",
    [
        "../repo/README.md",
        "core/../README.md",
        "./README.md",
        "core//src/tp_core/uzun.py",
        "/etc/passwd",
        "README.md\x00.py",
        "core\\src\\tp_core\\uzun.py",
        "readme.md",  # büyük/küçük harf birebir
        "README.MD",
        "core/src/tp_core",  # dizin (manifest anahtarı değil)
        "docs/AI-ASISTAN-PLANI.md",  # manifest dışı
        "MANIFEST.json",
        "../../etc/passwd/",
    ],
)
def test_read_guvenlik_reddi(bilgi: UrunBilgisi, yol: str) -> None:
    with pytest.raises(ProductToolError):
        bilgi.product_read({"path": yol})


def test_read_symlink_ile_degistirilmis_dosya_okunmaz(paket: Path, tmp_path: Path) -> None:
    dizin = _gecerli_dizin(paket)
    hedef = dizin / "README.md"
    disari = tmp_path / "disari.txt"
    disari.write_text(hedef.read_text("utf-8"), encoding="utf-8")  # sha256 bile tutsa
    hedef.unlink()
    os.symlink(disari, hedef)
    with pytest.raises(ProductToolError):
        UrunBilgisi(paket).product_read({"path": "README.md"})


def test_read_symlink_ara_dizin_okunmaz(paket: Path, tmp_path: Path) -> None:
    dizin = _gecerli_dizin(paket)
    gercek = tmp_path / "baska"
    (dizin / "docs").rename(gercek)
    os.symlink(gercek, dizin / "docs")
    with pytest.raises(ProductToolError):
        UrunBilgisi(paket).product_read({"path": "docs/ONBOARDING.md"})


def test_read_icerik_degismisse_reddedilir(paket: Path) -> None:
    (_gecerli_dizin(paket) / "README.md").write_text("# Testing Probf\nAsistan paneli.\n", "utf-8")
    with pytest.raises(ProductToolError, match="doğrulanamadı"):
        UrunBilgisi(paket).product_read({"path": "README.md"})


def test_manifest_dizin_kacisi_reddedilir(paket: Path) -> None:
    m = json.loads((paket / MANIFEST_ADI).read_text("utf-8"))
    m["dizin"] = "../.."
    (paket / MANIFEST_ADI).write_text(json.dumps(m), "utf-8")
    with pytest.raises(ProductToolError):
        UrunBilgisi(paket).product_read({"path": "README.md"})


def test_paket_yoksa_anlasilir_hata(tmp_path: Path) -> None:
    with pytest.raises(ProductToolError, match="paketi yok"):
        UrunBilgisi(tmp_path / "yok").product_search({"query": "x"})


def test_search_sabit_metin_ve_kapsam(bilgi: UrunBilgisi) -> None:
    out = bilgi.product_search({"query": "asistan"}).splitlines()
    assert out == [
        "README.md:2: Asistan paneli.",
        'core/src/tp_core/worker/__init__.py:2: ASISTAN = "kuyruk"',
        "review-portal/src/App.tsx:1: // Asistan düğmesi",
    ]
    assert bilgi.product_search({"query": "asistan", "kapsam": "portal"}).splitlines() == [
        "review-portal/src/App.tsx:1: // Asistan düğmesi"
    ]
    assert bilgi.product_search({"query": "asistan", "kapsam": "docs"}).splitlines() == [
        "README.md:2: Asistan paneli."
    ]
    # regex özel karakterleri sabit metindir
    assert bilgi.product_search({"query": ".*"}) == "eşleşme yok"


def test_search_50_sonuc_siniri(bilgi: UrunBilgisi) -> None:
    out = bilgi.product_search({"query": "satir_", "kapsam": "core"}).splitlines()
    assert len(out) == MAX_SEARCH_RESULTS + 1
    assert out[-1].startswith(f"… {1000 - MAX_SEARCH_RESULTS} sonuç daha")


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"query": ""},
        {"query": "  "},
        {"query": 5},
        {"query": "x" * 201},
        {"query": "a", "kapsam": "hepsi"},
    ],
)
def test_search_gecersiz_arguman(bilgi: UrunBilgisi, args: dict) -> None:
    with pytest.raises(ProductToolError):
        bilgi.product_search(args)


def test_paket_yenilenince_yeni_icerik_okunur(paket: Path, tmp_path: Path) -> None:
    bilgi = UrunBilgisi(paket)
    assert "Asistan paneli." in bilgi.product_read({"path": "README.md"})
    kaynak = tmp_path / "repo"
    (kaynak / "README.md").write_text("# Testing Probe\nYeni sürüm notu.\n", encoding="utf-8")
    assert not uret(kaynak, paket, commit="def", ortam_degerleri=[]).bulgular
    assert "Yeni sürüm notu." in bilgi.product_read({"path": "README.md"})


def test_tablo(bilgi: UrunBilgisi) -> None:
    assert set(bilgi.tablo()) == {"product_search", "product_read"}
