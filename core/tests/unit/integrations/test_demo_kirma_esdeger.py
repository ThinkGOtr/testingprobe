"""Demo kırması eşdeğerliği: mobil/masaüstü kimlik sözleşmesi denetimleri TP'nin bilinçli web
kırmasını (forge_demo OLD_TESTID → NEW_TESTID) ihlal saymaz, gerçek sözleşme kaymasını yakalar.

Demo deposunda "Buton kimliğini değiştir" merge edilince web e2e kırmızıya döner (amaçlanan);
mobil-android (APK derleme adımındaki kimlik-kontrol.mjs) ve masaustu-windows (e2e-app
SozlesmeBirimTesti) web kaynağını okuduğu için onlar da kırmızıya dönüyordu.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tp_core.integrations.forge_demo import NEW_TESTID, OLD_TESTID

REPO = Path(__file__).resolve().parents[4]
DEMO = REPO / "demo-app"
BEKLENEN = {NEW_TESTID: OLD_TESTID}


def test_kimlikler_json_esdegeri_forge_demo_ile_ayni() -> None:
    belge = json.loads((DEMO / "kimlikler.json").read_text(encoding="utf-8"))
    assert belge["demo_kirma_esdegerleri"] == BEKLENEN
    ids = {k["id"] for k in belge["kimlikler"]}
    assert OLD_TESTID in ids and NEW_TESTID not in ids  # sözleşme kanonik (baseline) kimlikte


def test_kimlik_kontrol_mjs_sabiti_forge_demo_ile_ayni() -> None:
    metin = (DEMO / "mobile" / "scripts" / "kimlik-kontrol.mjs").read_text(encoding="utf-8")
    m = re.search(r"const DEMO_KIRMA_ESDEGER = (\{[^}]*\});", metin)
    assert m, "DEMO_KIRMA_ESDEGER sabiti yok"
    assert json.loads(m.group(1)) == BEKLENEN


def test_java_sozlesme_testleri_esdegeri_okur() -> None:
    for yol in (
        "e2e-app/src/test/java/com/antreklabs/bayi/birim/SozlesmeBirimTesti.java",
        "e2e-java/src/test/java/com/antreklabs/bayi/birim/SozlesmeBirimTesti.java",
    ):
        metin = (DEMO / yol).read_text(encoding="utf-8")
        assert "demo_kirma_esdegerleri" in metin, yol
        assert "demoEsdegerleri()" in metin, yol


@pytest.fixture()
def demo_kopya(tmp_path: Path) -> Path:
    hedef = tmp_path / "demo-app"
    for alt in (
        "web/src",
        "e2e/pages",
        "mobile/src",
        "mobile/scripts",
        "desktop/src",
        "desktop/scripts",
    ):
        shutil.copytree(DEMO / alt, hedef / alt)
    shutil.copy2(DEMO / "kimlikler.json", hedef / "kimlikler.json")
    return hedef


def _kir(kok: Path, alt: str) -> None:
    """forge_demo'nun yaptığı gibi tırnaklı OLD_TESTID → NEW_TESTID (yalnız `alt` altında)."""
    degisen = 0
    for f in (kok / alt).rglob("*.ts*"):
        metin = f.read_text(encoding="utf-8")
        yeni = metin.replace(f'"{OLD_TESTID}"', f'"{NEW_TESTID}"')
        if yeni != metin:
            f.write_text(yeni, encoding="utf-8")
            degisen += 1
    assert degisen, f"{alt} altında {OLD_TESTID} yok"


def _mjs(kok: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(kok / "mobile" / "scripts" / "kimlik-kontrol.mjs")],
        capture_output=True,
        text=True,
        check=False,
    )


def _py(kok: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(kok / "desktop" / "scripts" / "kimlik-kontrol.py")],
        capture_output=True,
        text=True,
        check=False,
    )


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node yok")


@needs_node
def test_mobil_kontrol_kirma_ve_onarimda_yesil_bilgi_satiriyla(demo_kopya: Path) -> None:
    assert _mjs(demo_kopya).returncode == 0
    _kir(demo_kopya, "web/src")  # demo kırması merge edildi
    r = _mjs(demo_kopya)
    assert r.returncode == 0, r.stderr
    assert "demo kırması algılandı" in r.stdout
    _kir(demo_kopya, "e2e/pages")  # TS locator onarımı merge edildi
    r = _mjs(demo_kopya)
    assert r.returncode == 0, r.stderr


@needs_node
def test_mobil_kontrol_gercek_kaymayi_yakalar(demo_kopya: Path) -> None:
    _kir(demo_kopya, "web/src")
    layout = demo_kopya / "web/src/components/Layout.tsx"
    metin = layout.read_text(encoding="utf-8")
    assert 'data-testid="cart-count"' in metin
    layout.write_text(
        metin.replace('data-testid="cart-count"', 'data-testid="cart-num"'), encoding="utf-8"
    )
    r = _mjs(demo_kopya)
    assert r.returncode == 1
    assert "cart-num" in r.stderr


@needs_node
def test_mobil_kontrol_iki_bicim_birlikte_ihlal(demo_kopya: Path) -> None:
    sayfa = demo_kopya / "web/src/pages/CatalogPage.tsx"
    metin = sayfa.read_text(encoding="utf-8")
    sayfa.write_text(
        metin + f'\nconst X = () => <i data-testid="{NEW_TESTID}" />;\n', encoding="utf-8"
    )
    r = _mjs(demo_kopya)
    assert r.returncode == 1
    assert "birlikte" in r.stderr


@needs_node
def test_mobil_uygulama_yeni_kimligi_kullanamaz(demo_kopya: Path) -> None:
    """Eşdeğerlik yalnız web tarafındadır; mobil uygulama kanonik kimlikte kalmalı."""
    hedef = next(
        f
        for f in (demo_kopya / "mobile/src").rglob("*.tsx")
        if f'"{OLD_TESTID}"' in f.read_text("utf-8")
    )
    hedef.write_text(
        hedef.read_text("utf-8").replace(f'"{OLD_TESTID}"', f'"{NEW_TESTID}"'), encoding="utf-8"
    )
    assert _mjs(demo_kopya).returncode == 1


def test_masaustu_kontrol_kirmada_yesil_kaymada_kirmizi(demo_kopya: Path) -> None:
    assert _py(demo_kopya).returncode == 0
    _kir(demo_kopya, "web/src")
    r = _py(demo_kopya)
    assert r.returncode == 0, r.stdout
    assert "demo kırması algılandı" in r.stdout
    layout = demo_kopya / "web/src/components/Layout.tsx"
    layout.write_text(
        layout.read_text("utf-8").replace('data-testid="cart-count"', 'data-testid="cart-num"'),
        encoding="utf-8",
    )
    assert _py(demo_kopya).returncode == 1
