"""GitHub kipi koşusu: yerel koşu dizini / run.json yok; hata anı aria snapshot'ı içe aktarımda
`test_result_ek.hata_baglami`'na yazılır ve locator kuralı (kural 3) bunu kullanır.

Girdi, gerçek bir GitHub `test-local-results` artefaktının küçültülmüş kopyasından
(`tests/unit/features/ci/fixtures/github_artifact`) ci ayrıştırıcısı + `record_results` ile
kurulur: GitHub içe aktarımıyla aynı yol.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tp_core.features.ci.parse import ArtefaktEkleri, parse_reports
from tp_core.features.ci.service import record_results
from tp_core.features.triage import classify_run, service
from tp_core.models import Failure, Run
from tp_core.models.ci_feature import TestResultEk
from tp_core.models.triage_feature import FailureEk, TriageKosu

from .conftest import SHA, FakeToolchain

pytestmark = pytest.mark.usefixtures("triage_env")

ARTEFAKT = Path(__file__).resolve().parents[1] / "ci" / "fixtures" / "github_artifact"
AC1 = "Sepet (TPD-1) › AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar"


def _github_kosusu(engine: Engine, *, baglam: bool = True) -> uuid.UUID:
    dosyalar = {p.relative_to(ARTEFAKT).as_posix(): p.read_bytes() for p in ARTEFAKT.rglob("*")
                if p.is_file()}  # fmt: skip
    ekler = ArtefaktEkleri({k: v for k, v in dosyalar.items() if k.endswith("error-context.md")})
    ayr = parse_reports(None, dosyalar["results.json"], ekler=ekler if baglam else None)
    # Yalnızca locator testi: diğer kırmızılar bu testin konusu değil (LLM'e düşerler).
    ayr.testler = [t for t in ayr.testler if t.test_adi == AC1 or t.sonuc == "passed"]
    rid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        run = Run(
            id=rid,
            commit=SHA,
            github_run_id="41368127209",
            kaynak="github",
            tetik="push",
            sonuc="failed",
            ortam={},
            artefaktlar={"ci_url": "https://github.com/o/r/actions/runs/41368127209"},
        )
        s.add(run)
        s.flush()
        record_results(s, run, ayr)
    return rid


def _failure(engine: Engine, rid: uuid.UUID) -> tuple[Failure, FailureEk]:
    with Session(engine) as s:
        [(f, ek)] = s.execute(
            select(Failure, FailureEk)
            .join(FailureEk, FailureEk.failure_id == Failure.id)
            .where(Failure.run_id == rid)
        ).all()
        return f, ek


def test_github_kosusu_locator_kirilmasi_kuralla_test_maintenance(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    rid = _github_kosusu(engine)
    with Session(engine) as s:
        hb = s.scalars(select(TestResultEk.hata_baglami)).all()
        assert sum(1 for x in hb if x) == 1
    classify_run(engine, rid)
    f, ek = _failure(engine, rid)
    assert (f.sinif, f.alt_tur, f.karar_kaynagi) == ("test_maintenance", "locator", "rule")
    assert ek.kural == "test_maintenance/locator" and ek.oneri_yok_nedeni is None
    o = ek.oneri
    assert o is not None
    assert (o["locator_key"], o["old_testid"], o["new_testid"]) == (
        "catalog.addToCart",
        "add-to-cart",
        "cart-add",
    )
    # Kapsam hata metnindeki ürün kartından; sayfa yolu sembol tablosundaki locator dosyasından.
    assert o["scope_test_id"] == "product-card-P-002" and o["url_path"] == "/katalog"
    assert any('button "Sepete ekle"' in x for x in o["aria_satirlari"])
    kodlar = [x["kod"] for x in f.eslesen_sinyaller]
    assert {"locator_0_eleman", "niyet_sembol_tablosu", "aria_rol_ad_var"} <= set(kodlar)
    assert ("probe", (SHA, "button", "Sepete ekle", "/katalog", "product-card-P-002")) in (
        toolchain.cagrilar
    )


def test_triage_sifirla_ve_yeniden_siniflandir(engine: Engine) -> None:
    """Operatör aracı: eski (bağlamsız) sonuç silinir, koşu yeniden sınıflandırılır."""
    rid = _github_kosusu(engine)
    classify_run(engine, rid)
    assert classify_run(engine, rid)["durum"] == "zaten_yapildi"
    with Session(engine) as s, s.begin():
        assert service.triage_sifirla(s, rid, "test")["silinen_failure"] == 1
    with Session(engine) as s:
        assert s.get(TriageKosu, rid) is None
        assert s.scalar(select(Failure.id).where(Failure.run_id == rid)) is None
    classify_run(engine, rid)
    f, _ek = _failure(engine, rid)
    assert (f.sinif, f.alt_tur) == ("test_maintenance", "locator")


def test_triage_sifirla_bug_taslagina_bagliysa_reddeder(engine: Engine) -> None:
    from tp_core.models import BugDraft

    rid = _github_kosusu(engine)
    classify_run(engine, rid)
    f, _ek = _failure(engine, rid)
    with Session(engine) as s, s.begin():
        s.add(BugDraft(failure_id=f.id, icerik={}, icerik_hash="h"))
    with Session(engine) as s, s.begin(), pytest.raises(service.YenidenTriageReddi):
        service.triage_sifirla(s, rid, "test")
    with Session(engine) as s:
        assert s.get(TriageKosu, rid) is not None
