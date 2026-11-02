"""GitHub kipi hata bağlamı: `test-local-results` artefaktındaki error-context.md → aria snapshot.

Fikstür (`fixtures/github_artifact/`) gerçek bir GitHub koşusunun artefakt düzenidir (küçültülmüş):
artefakt kökü runner'daki `demo-app/e2e/results/` dizininin içidir (`results.json`,
`artifacts/<test>/error-context.md`); `results.json`'daki ek yolları runner'daki mutlak yoldur
(`/home/runner/work/<repo>/<repo>/demo-app/e2e/results/artifacts/...`).
"""

from __future__ import annotations

import io
import unicodedata
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import FIXTURES, SHA
from tests.unit.features.ci.test_github import REPO, FakeGitHub
from tp_core.features.ci import enqueue_ci, service, services
from tp_core.features.ci.clients import GitHubCi, _zip_dosyalari
from tp_core.features.ci.parse import (
    MAX_ERROR_CONTEXT,
    ArtefaktEkleri,
    aria_ayikla,
    parse_reports,
)
from tp_core.integrations.forge_github import GitHubForge, TokenAuth
from tp_core.models import Run, TestResult
from tp_core.models.ci_feature import TestResultEk

ARTEFAKT = FIXTURES / "github_artifact"
AC1 = "Sepet (TPD-1) › AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar"
LOCATORS = "locators.ts rol/ad sözleşmesi › menü, katalog, sepet ve sipariş sayfaları"


def _artefakt_dosyalari(onek: str = "") -> dict[str, bytes]:
    """Artefakt zip'indeki gibi: kök `results/` içi, yol ayırıcı `/`."""
    return {onek + p.relative_to(ARTEFAKT).as_posix(): p.read_bytes() for p in _dosyalar()}


def _dosyalar() -> list[Path]:
    return sorted(p for p in ARTEFAKT.rglob("*") if p.is_file())


def _ekler(dosyalar: dict[str, bytes]) -> ArtefaktEkleri:
    return ArtefaktEkleri({k: v for k, v in dosyalar.items() if k.endswith("/error-context.md")})


def _ayristir(dosyalar: dict[str, bytes]) -> dict[str, dict | None]:
    results = next(v for k, v in dosyalar.items() if k.endswith("results.json"))
    ayr = parse_reports(None, results, ekler=_ekler(dosyalar))
    return {t.test_adi: t.hata_baglami for t in ayr.testler}


# ------------------------------------------------------------------------------- ayrıştırma


def test_gercek_artefakt_duzeninden_aria_snapshot_okunur() -> None:
    hb = _ayristir(_artefakt_dosyalari())
    ac1 = hb[AC1]
    assert ac1 is not None
    assert (ac1["aria_snapshot_scope"], ac1["deneme"], ac1["kaynak"]) == (
        "page",
        0,
        "error-context.md",
    )
    # Locator kuralının aradığı satır (rol + ad): niyetteki eleman sayfada var.
    assert '- button "Sepete ekle"' in ac1["aria_snapshot"]
    assert not ac1["aria_snapshot"].startswith("```")
    # expect hatası: Playwright YAML'ı başlıksız hata ayrıntısının altına koyar.
    loc = hb[LOCATORS]
    assert loc is not None and loc["aria_snapshot_scope"] == "error_details"
    assert 'button "Sepete ekle"' in loc["aria_snapshot"]
    # Geçen testin hata bağlamı yoktur.
    gecen = [ad for ad, b in hb.items() if ad not in (AC1, LOCATORS)]
    assert gecen and all(hb[ad] is None for ad in gecen)


@pytest.mark.parametrize("onek", ["", "tp-results/", "demo-app/e2e/results/"])
def test_artefakt_koku_oneki_ne_olursa_olsun_eslesir(onek: str) -> None:
    hb = _ayristir(_artefakt_dosyalari(onek))
    assert hb[AC1] is not None and hb[LOCATORS] is not None


def test_nfd_dizin_adi_nfc_ek_yoluyla_eslesir() -> None:
    dosyalar = {unicodedata.normalize("NFD", k): v for k, v in _artefakt_dosyalari().items()}
    assert any(k != unicodedata.normalize("NFC", k) for k in dosyalar)
    assert _ayristir(dosyalar)[AC1] is not None


def test_ilk_deneme_eki_yoksa_yeniden_denemeninki_kullanilir() -> None:
    dosyalar = {
        k: v
        for k, v in _artefakt_dosyalari().items()
        if not k.endswith("error-context.md") or "-retry1/" in k
    }
    hb = _ayristir(dosyalar)[AC1]
    assert hb is not None and hb["deneme"] == 1


def test_kokteki_tek_dosya_ve_kacis_yollari_eslesmez() -> None:
    ham = (
        ARTEFAKT
        / "artifacts"
        / "cart-Sepet-TPD-1-AC1-Sepet-5f8e1-ekler-ve-sepet-sayacı-artar-chromium"
        / "error-context.md"
    ).read_bytes()
    ekler = ArtefaktEkleri(
        {"error-context.md": ham, "../x/error-context.md": ham, "/abs/error-context.md": ham}
    )
    yol = "/home/runner/work/r/r/demo-app/e2e/results/artifacts/t/error-context.md"
    assert ekler.bul(yol) is None
    assert ekler.bul(None) is None and ekler.bul("") is None


def test_aria_ayikla_sinirlar() -> None:
    assert aria_ayikla(None) == (None, None)
    assert aria_ayikla(b"# Error details\n\nyok\n") == (None, None)
    assert aria_ayikla(b"x" * (MAX_ERROR_CONTEXT + 1)) == (None, None)
    aria, kapsam = aria_ayikla(b'# Page snapshot\n\n```yaml\n- button "A"\x1b[31m\n```\n')
    assert (aria, kapsam) == ('- button "A"', "page")


# ---------------------------------------------------------------------------- zip okuma


def _zip(dosyalar: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ad, icerik in dosyalar.items():
            zf.writestr(ad, icerik)
    return buf.getvalue()


def test_zip_ekleri_her_kopyasi_ayri_ve_buyuk_ek_atlanir() -> None:
    veri = _zip(
        {
            **_artefakt_dosyalari(),
            "artifacts/buyuk/error-context.md": b"x" * (MAX_ERROR_CONTEXT + 1),
            "artifacts/t/trace.zip": b"PK",
        }
    )
    out = _zip_dosyalari(veri, ("results.json",), ("error-context.md",))
    ekler = sorted(k for k in out if k.endswith("error-context.md"))
    assert len(ekler) == 4 and "artifacts/buyuk/error-context.md" not in out
    assert "results.json" in out and "artifacts/t/trace.zip" not in out
    # Ek adı verilmezse (geriye uyum) error-context okunmaz.
    assert not any(k.endswith("error-context.md") for k in _zip_dosyalari(veri, ("results.json",)))


# ------------------------------------------------------------------- GitHub içe aktarımı


class ArtefaktliGitHub(FakeGitHub):
    """Sonuç artefaktı gerçek GitHub düzeninde (fikstür) dönen sahte GitHub."""

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "blob.example" and req.url.path.endswith("/sonuc.zip"):
            self.istekler.append(req)
            return httpx.Response(200, content=_zip(_artefakt_dosyalari()))
        return super().handler(req)


@pytest.fixture
def agh(engine: Engine, artefakt_kok):
    fake = ArtefaktliGitHub()
    forge = GitHubForge(
        REPO,
        TokenAuth("gh-test-token"),
        api_url="https://api.github.test",
        transport=httpx.MockTransport(fake.handler),
    )
    with services.override(
        mode=lambda: "github",
        forge=lambda: forge,
        github=lambda: GitHubCi(forge),
        artifacts_root=lambda: artefakt_kok,
    ):
        yield fake


def _baglamlar(engine: Engine, rid) -> dict[str, dict | None]:
    with Session(engine) as s:
        return {
            tr.test_adi: ek.hata_baglami
            for tr, ek in s.execute(
                select(TestResult, TestResultEk)
                .join(TestResultEk, TestResultEk.test_result_id == TestResult.id)
                .where(TestResult.run_id == rid)
            )
        }


def test_github_ingest_hata_baglamini_test_result_ek_e_yazar(
    engine: Engine, agh: ArtefaktliGitHub
) -> None:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "push", None)
    agh.wr(300, "push", conclusion="failure")
    assert service.github_poll(engine, rid, 0)["durum"] == "failed"
    b = _baglamlar(engine, rid)
    assert b[AC1] and b[AC1]["aria_snapshot_scope"] == "page"
    assert '- button "Sepete ekle"' in b[AC1]["aria_snapshot"]
    assert b[LOCATORS] and b[LOCATORS]["aria_snapshot_scope"] == "error_details"
    assert sum(1 for v in b.values() if v) == 2


def test_onceden_alinmis_kosu_geri_doldurulur(engine: Engine, agh: ArtefaktliGitHub) -> None:
    """0015 öncesi içe aktarılan koşu: satırlar var, hata bağlamı boş → artefakttan doldurulur."""
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "push", None)
    agh.wr(301, "push", conclusion="failure")
    service.github_poll(engine, rid, 0)
    with Session(engine) as s, s.begin():
        for ek in s.scalars(select(TestResultEk)):
            ek.hata_baglami = None
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        assert run is not None
        sonuc = service.github_hata_baglami_doldur(s, run)
    assert (sonuc["bulunan"], sonuc["guncellenen"]) == (2, 2)
    b = _baglamlar(engine, rid)
    assert b[AC1] and b[LOCATORS]
    # İdempotent: dolu satırlar yeniden yazılmaz.
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        assert service.github_hata_baglami_doldur(s, run)["guncellenen"] == 0


def test_yerel_kosu_geri_doldurulamaz(engine: Engine, agh: ArtefaktliGitHub) -> None:
    with Session(engine) as s, s.begin():
        run = Run(kaynak="local", tetik="push", sonuc="failed", commit=SHA)
        s.add(run)
        s.flush()
        with pytest.raises(service.CiError):
            service.github_hata_baglami_doldur(s, run)
