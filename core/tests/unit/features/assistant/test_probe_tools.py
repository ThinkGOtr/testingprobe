"""`probe_*` araçları: servis fonksiyonları, uç-düzeyi rol kısıtı, alan izin listesi, maskeleme.

AI-ASISTAN-PLANI §5.2, §13 (şablon rol kısıtı: Testçi analiste özel alanı göremez).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tp_core.audit import append_audit
from tp_core.features.assistant.tools import AracBaglami, AracHatasi, AracSarmalayici, probe
from tp_core.gateway.masking import PiiMasker
from tp_core.models import (
    BugDraft,
    Job,
    Requirement,
    Review,
    Run,
    TestCase,
    WorkflowInstance,
    session_scope,
)
from tp_core.models.guard import allow_state_write

SAHTE_TOKEN = "gh" + "p_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6"


def _baglam(rol: str, *, maske: bool = True) -> AracBaglami:
    from tp_core.models import new_session

    return AracBaglami(
        kullanici_id=uuid.uuid4(),
        rol=rol,
        oturum=PiiMasker(enabled=maske).new_session(),
        db=new_session,
    )


def _sar(baglam: AracBaglami) -> AracSarmalayici:
    return AracSarmalayici(baglam, yeni=probe.ARACLAR)


@pytest.fixture
def veri(engine: Engine, make_user: Any) -> dict[str, Any]:
    """TPD-3 (PO onayı bekliyor, PO cevabında e-posta), taslak case, bug taslağı, hatalı koşu."""
    analist = make_user("analyst")
    with session_scope() as s, allow_state_write():
        req = Requirement(
            kaynak="jira",
            jira_key="TPD-3",
            baslik=f"Sepet kampanyası (eski token {SAHTE_TOKEN})",
            aciklama="Bayi sepete ürün ekler.",
            kabul_kriterleri=["AC1: Sepete eklenir"],
            kaynak_hash="h",
            durum="pending_po",
            po_cevaplari=[{"metin": "Q1: evet, iletişim po.kisi@ornek.com"}],
        )
        serbest = Requirement(
            kaynak="free_text", baslik="Serbest", kaynak_hash="h2", durum="findings_open"
        )
        s.add_all([req, serbest])
        s.flush()
        tc = TestCase(
            id=uuid.uuid4(),
            requirement_id=req.id,
            sira_no=1,
            icerik={"title": "Sepete ekleme", "type": "positive", "risk": "high", "steps": []},
            icerik_hash="c1",
        )
        bug = BugDraft(icerik={"ozet": "İndirim yanlış"}, icerik_hash="b1", jira_key="TPD-9")
        run = Run(tetik="manual", sonuc="error", artefaktlar={"hata": "runner çöktü"})
        s.add_all([tc, bug, run])
        s.flush()
        wf = WorkflowInstance(
            tur="case_generation", baslatan="analist", nesne_turu="requirement", nesne_id=req.id
        )
        s.add(wf)
        s.flush()
        s.add(
            Job(
                tur="cases.generate",
                durum="failed",
                workflow_id=wf.id,
                son_hata=f"Model hatası\nTraceback… {SAHTE_TOKEN}",
            )
        )
        s.add(Job(tur="requirements.review", durum="done", yuk={"requirement_id": str(req.id)}))
        s.add(
            Review(
                nesne_turu="test_case",
                nesne_id=tc.id,
                user_id=analist.id,
                karar="reject",
                ret_nedeni="duplicate",
                onaylanan_hash="c1",
            )
        )
        append_audit(
            s.connection(),
            "analist1",
            "requirement.transition",
            f"requirement:{req.id}",
            {"from": "doc_final", "to": "pending_po", "token": SAHTE_TOKEN},
        )
        return {"req": req.id, "serbest": serbest.id, "case": tc.id, "bug": bug.id, "run": run.id}


# ------------------------------------------------------------------ probe_get


def test_probe_get_anahtarla_kapi_sorumlu_rota_ve_po_cevabi(veri: dict[str, Any]) -> None:
    baglam = _baglam("po")
    cikti = _sar(baglam)("probe_get", {"tur": "requirement", "id_or_key": "TPD-3"})
    assert cikti.startswith("[kanit:k1]\n<untrusted")
    assert "bekleyen_kapi: PO onayı bekleniyor" in cikti
    assert "sorumlu_rol: po (Ürün sahibi (PO))" in cikti
    assert f"ekran_rotasi: /gereksinimler/{veri['req']}" in cikti
    assert "jira_key: TPD-3" in cikti
    # PII'li PO cevabı maskeli gider; alıntı aynı oturumla açılınca doğrulanır.
    assert "po.kisi@ornek.com" not in cikti
    assert "po.kisi@ornek.com" in baglam.oturum.unmask(cikti)
    # Sır temizlenir; alan izin listesi dışı alanlar (URL, hash) gitmez.
    assert SAHTE_TOKEN not in cikti
    for yasak in ("jira_url", "icerik_hash", "kaynak_hash", "onaylanan_hash", "http"):
        assert yasak not in cikti


def test_sablon_rol_kisiti_analist_testciye_ozel_alani_goremez(veri: dict[str, Any]) -> None:
    """Yayın önizlemesi `case.publish` (Testçi; specs/012-rol-yetki §4.1) izni ister."""
    analist = _sar(_baglam("analyst"))("probe_get", {"tur": "requirement", "id_or_key": "TPD-3"})
    testci = _sar(_baglam("tester"))("probe_get", {"tur": "requirement", "id_or_key": "TPD-3"})
    assert "yayin_onizleme" in testci
    assert "yayin_onizleme" not in analist
    # Ortak kısım aynı.
    assert "bekleyen_kapi: PO onayı bekleniyor" in analist


def test_probe_get_case_script_run_bug(veri: dict[str, Any]) -> None:
    sar = _sar(_baglam("engineer", maske=False))
    case = sar("probe_get", {"tur": "case", "id_or_key": str(veri["case"])})
    assert "icerik.title: Sepete ekleme" in case
    assert f"ekran_rotasi: /gereksinimler/{veri['req']}/caseler" in case
    assert "sorumlu_rol: tester (Testçi)" in case  # taslak case: Testçi kararı
    kosu = sar("probe_get", {"tur": "run", "id_or_key": str(veri["run"])})
    assert "bekleyen_kapi: Testler koşmadı: CI ortam hatası incelenmeli" in kosu
    assert "son_hata: runner çöktü" in kosu
    bug = sar("probe_get", {"tur": "bug_draft", "id_or_key": "TPD-9"})
    assert "sorumlu_rol: tester (Testçi)" in bug and "icerik.ozet: İndirim yanlış" in bug


def test_probe_get_bulunamadi_ve_gecersiz(veri: dict[str, Any]) -> None:
    sar = _sar(_baglam("analyst"))
    with pytest.raises(AracHatasi, match="bulunamadı"):
        sar("probe_get", {"tur": "requirement", "id_or_key": "TPD-404"})
    with pytest.raises(AracHatasi, match="bulunamadı"):
        sar("probe_get", {"tur": "run", "id_or_key": str(uuid.uuid4())})
    with pytest.raises(AracHatasi, match="'tur'"):
        sar("probe_get", {"tur": "kullanici", "id_or_key": "x"})
    with pytest.raises(AracHatasi, match="bilinmeyen argüman"):
        sar("probe_get", {"tur": "requirement", "id_or_key": "TPD-3", "rol": "analyst"})
    assert len(sar.havuz) == 0


# ------------------------------------------------------------------ probe_list


def test_probe_list_durum_filtresi(veri: dict[str, Any]) -> None:
    sar = _sar(_baglam("tester", maske=False))
    cikti = sar("probe_list", {"tur": "requirement", "durum": "pending_po", "limit": 5})
    assert "1 kayıt" in cikti and "TPD-3" in cikti and "Serbest" not in cikti
    hepsi = sar("probe_list", {"tur": "requirement"})
    assert "2 kayıt" in hepsi
    with pytest.raises(AracHatasi, match="'durum'"):
        sar("probe_list", {"tur": "requirement", "durum": "yok"})
    assert "error" in sar("probe_list", {"tur": "run", "durum": "error"})


# ------------------------------------------------------------------ probe_jobs / probe_audit


def test_probe_jobs_akis_ve_yuk_ile_bulunur_hata_kisadir(veri: dict[str, Any]) -> None:
    cikti = _sar(_baglam("analyst"))("probe_jobs", {"varlik_id": str(veri["req"])})
    assert "cases.generate | failed" in cikti and "hata: Model hatası" in cikti
    assert "requirements.review | done" in cikti
    assert "Traceback" not in cikti and SAHTE_TOKEN not in cikti


def test_probe_audit_gecis_karar_ozet(veri: dict[str, Any]) -> None:
    # `audit.read_own` (Testçi): yalnız kendi olayları — bu kullanıcının olayı yok.
    kendi = _sar(_baglam("tester"))("probe_audit", {"varlik_id": str(veri["req"])})
    assert "kayıt yok" in kendi and "requirement.transition" not in kendi
    sar = _sar(_baglam("admin"))  # `audit.read_all`
    izi = sar("probe_audit", {"varlik_id": str(veri["req"])})
    assert "requirement.transition" in izi and "to=pending_po" in izi
    assert SAHTE_TOKEN not in izi and "token=" not in izi
    karar = sar("probe_audit", {"varlik_id": str(veri["case"]), "limit": 3})
    assert "reject | kanal: portal, ret nedeni: duplicate" in karar
    with pytest.raises(AracHatasi, match="bulunamadı"):
        sar("probe_audit", {"varlik_id": str(uuid.uuid4())})
    with pytest.raises(AracHatasi, match="UUID"):
        sar("probe_audit", {"varlik_id": "TPD-3"})


# ------------------------------------------------------------------ probe_my_queue


@pytest.mark.parametrize(
    ("rol", "beklenen", "olmayan"),
    [
        ("po", "PO onayı bekleniyor (Jira'da etiketle)", "Case kararı"),
        ("analyst", "Tutarlılık bulguları analist kararı bekliyor", "PO onayı bekleniyor"),
        ("tester", "Bug taslağı kararı bekleniyor", "PO onayı"),
        ("engineer", "CI ortam hatası", "Bug taslağı"),
        ("admin", "Automation Engineer inceliyor", "Case kararı"),
    ],
)
def test_probe_my_queue_rolden(veri: dict[str, Any], rol: str, beklenen: str, olmayan: str) -> None:
    cikti = _sar(_baglam(rol, maske=False))("probe_my_queue", {})
    assert beklenen in cikti and olmayan not in cikti


def test_bekleyen_isler_sayimi(veri: dict[str, Any], session: Session) -> None:
    toplam, isler = probe.bekleyen_isler(session, "analyst")
    assert toplam == len(isler) == 1  # serbest gereksinim (bulgular)
    assert {i.tur for i in isler} == {"requirement"}
    # Taslak case Testçi kararını bekler (specs/012-rol-yetki §5).
    _, testci = probe.bekleyen_isler(session, "tester")
    assert "case" in {i.tur for i in testci}


# ------------------------------------------------------------------ uç-düzeyi rol hizası


def _api_rotalari(rotalar: Any) -> Iterator[Any]:
    from fastapi.routing import APIRoute

    for r in rotalar:
        if isinstance(r, APIRoute):
            yield r
        elif getattr(r, "original_router", None) is not None:  # dahil edilmiş router
            yield from _api_rotalari(r.original_router.routes)


def _route_rolleri() -> dict[str, frozenset[str] | None]:
    from tp_core.api.main import create_app
    from tp_core.auth import yetki

    out: dict[str, frozenset[str] | None] = {}
    for r in _api_rotalari(create_app().routes):
        if "GET" not in r.methods:
            continue
        roller: frozenset[str] | None = None
        for dep in r.dependant.dependencies:
            cagri = dep.call
            izinler = (
                (cagri.izin_adi,)
                if hasattr(cagri, "izin_adi")
                else tuple(getattr(cagri, "izin_adlari", ()))
            )
            if izinler:
                kume = frozenset().union(*(yetki.roller_icin(i) for i in izinler))
                roller = None if kume == yetki.ROLLER else kume
        out[f"GET {r.path}"] = roller
    return out


def test_uc_rolleri_routerla_ayni(db: Any) -> None:
    rotalar = _route_rolleri()
    for uc, roller in probe.UC_ROLLERI.items():
        assert uc in rotalar, uc
        assert rotalar[uc] == roller, uc


def test_kirpma_sinirindaki_yarim_token_maskelenir() -> None:
    """Kırpma işaretinden önce temizlik: sınırda yarım kalan token düz geçmez."""
    token = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    metin = "runner hata " + "z" * (probe.METIN_UST - 25) + " " + token
    cikti = probe._kirp(metin)
    assert cikti.endswith("…") and "***" in cikti and token[:6] not in cikti
    assert probe._kirp("kısa " + token) == "kısa " + token  # kırpılmayan metin aynen (sarmalayıcı)
