"""Check + tp-results → hat durumu (yalnız okuma)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.unit.features.musteri_ci.yardimci import (
    JUNIT_GECEN,
    JUNIT_KIRMIZI,
    SHA,
    SahteGh,
    meta,
    tp_results_gh,
)
from tp_core.features import musteri_ci as mci

D = mci.HatDurumu


@dataclass
class Forge:
    checkler: list[Any] = field(default_factory=list)
    hata: Exception | None = None

    def check_runs(self, sha):
        if self.hata:
            raise self.hata
        return self.checkler


def _c(
    ad="mobil-android-kotlin",
    status="completed",
    conclusion="success",
    run=42,
    job=9,
    bas="2026-11-18T10:00:00Z",
):
    return {
        "name": ad,
        "status": status,
        "conclusion": conclusion,
        "html_url": "https://github.com/acme/app/runs/1",
        "workflow_run_id": run,
        "job_id": job,
        "started_at": bas,
    }


def test_check_bul_en_yeni():
    eski = _c(conclusion="failure", bas="2026-11-18T09:00:00Z")
    yeni = _c(conclusion="success", bas="2026-11-18T10:00:00Z")
    assert mci.check_bul([yeni, eski, _c(ad="mobil-android")], "android", "kotlin") is yeni
    assert mci.check_bul([_c(ad="mobil-android")], "android", "kotlin") is None


def test_check_yok_bekleniyor():
    g = mci.hat_durumu(Forge(), SahteGh(), SHA, "android", "kotlin")
    assert g.durum == D.CI_BEKLENIYOR and g.check is None
    assert g.merge[0] is False
    assert g.dogrulama["rozet"]["kod"] == "kirarak_dogrulanmadi"
    g = mci.hat_durumu(Forge(hata=RuntimeError("ağ")), SahteGh(), SHA, "android", "kotlin")
    assert g.durum == D.CI_BEKLENIYOR and "okunamadı" in g.uyarilar[0]


def test_kosuyor_artefakt_okunmaz():
    gh = SahteGh()
    g = mci.hat_durumu(
        Forge([_c(status="in_progress", conclusion=None)]), gh, SHA, "android", "kotlin"
    )
    assert g.durum == D.CI_KOSUYOR and gh.indirilen == []


def test_yesil(tmp_path):
    from tp_core.features.ci import services

    services._overrides["github_artifacts_root"] = lambda: tmp_path
    try:
        gh = tp_results_gh({"ci-meta.json": meta(), "junit/TEST-a.xml": JUNIT_GECEN})
        g = mci.hat_durumu(Forge([_c()]), gh, SHA, "android", "kotlin", mevcut=D.CI_KOSUYOR)
    finally:
        services._overrides.pop("github_artifacts_root", None)
    assert g.durum == D.YESIL and g.merge == (True, "müşteri CI yeşil (kırarak doğrulanmadı)")
    o = g.ozet()
    assert o["durum"] == "yesil" and o["sayac"]["gecen"] == 2
    assert o["check"]["workflow_run_id"] == 42
    assert o["yerel"]["durum"] == "indirildi" and "indirilen" not in o["yerel"]
    assert o["uyarilar"] == []
    import json

    json.dumps(o)  # JSON'a yazılabilir


def test_kirmizi(tmp_path):
    gh = tp_results_gh({"ci-meta.json": meta(), "junit/TEST-a.xml": JUNIT_KIRMIZI})
    from tp_core.features.ci import services

    services._overrides["github_artifacts_root"] = lambda: tmp_path
    try:
        g = mci.hat_durumu(Forge([_c(conclusion="failure")]), gh, SHA, "android", "kotlin")
    finally:
        services._overrides.pop("github_artifacts_root", None)
    assert g.durum == D.KIRMIZI and mci.triage_turu(g.durum) == "test"


def test_derleme_hatasi_log_okuyucuya_duser():
    istenen: list[int] = []

    def log_oku(job_id: int) -> str:
        istenen.append(job_id)
        return "e: GirisTest.kt:3:1 Unresolved reference: x\nFAILURE: Build failed\n"

    g = mci.hat_durumu(
        Forge([_c(conclusion="failure")]), SahteGh(), SHA, "android", "kotlin", log_oku=log_oku
    )
    assert g.durum == D.DERLEME_HATASI and istenen == [9]
    assert "Unresolved reference" in g.sonuc.derleme_kesiti
    assert any("artefaktı yok" in u for u in g.ozet()["uyarilar"])


def test_basarili_check_sonuc_yok_ve_gecersiz_gecis_uyarisi():
    g = mci.hat_durumu(Forge([_c()]), SahteGh(), SHA, "android", "kotlin", mevcut=D.IPTAL)
    assert g.durum == D.SONUC_YOK and g.merge[0] is False
    assert any("geçersiz hat geçişi" in u for u in g.uyarilar)


def test_run_kimligi_yok():
    g = mci.hat_durumu(
        Forge([_c(run=None, conclusion="failure")]), SahteGh(), SHA, "android", "kotlin"
    )
    assert g.durum == D.DERLEME_HATASI
    assert any("koşu kimliği yok" in u for u in g.uyarilar)
