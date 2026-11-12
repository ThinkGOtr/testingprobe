"""Ekilmiş hata koşusu (012 §4.6, §4.7; kabul senaryoları 11–14): sahte toolchain + Postgres."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA, FakeToolchain, kosu_yaz, login, run_jobs
from tp_core.features.control_tower import service as kule
from tp_core.features.hata_kosusu import jobs as hk_jobs
from tp_core.features.hata_kosusu import katalog as kat
from tp_core.features.hata_kosusu import service
from tp_core.features.karar_tablosu.hatalar import HataKosusuSuruyor
from tp_core.features.triage import jobs as _triage_jobs  # noqa: F401  (iş kaydı)
from tp_core.models import BugDraft, Failure, HataKosusu, HataKosusuAdim, Run
from tp_core.models.triage_feature import TriageKosu
from tp_core.workflow.service import Principal, WorkflowError

pytestmark = pytest.mark.usefixtures("ci_env")

DOKUZ = {
    "kampanya_bedava_yok",
    "kampanya_esik_7",
    "kampanya_cift_indirim",
    "min_siparis_haric",
    "min_siparis_muafiyet_yok",
    "min_siparis_500",
    "min_siparis_1000",
    "fiyat_p004_31",
    "kampanya_urunu_p002",
}
ASSERTION_HATASI = (
    'Error: expect(locator).toHaveText(expected) failed\n\nExpected: "1"\nReceived: "0"\n'
)


# ------------------------------------------------------------------ sahte toolchain raporu


def rapor(kok: Path, body: dict[str, Any], sonuc: str) -> dict[str, Any]:
    """`sonuc`: yesil | assertion | locator | saglik | appium_yok | derleme."""
    platform = body.get("platform") or "web"
    yesil = sonuc == "yesil"
    ortam_hatasi = sonuc in ("saglik", "appium_yok")
    r = kosu_yaz(
        kok,
        body["run_id"],
        sha=body["sha"],
        durum="passed" if yesil else ("error" if ortam_hatasi else "failed"),
        conclusion="success" if yesil else "failure",
        saglik_ok=not ortam_hatasi,
    )
    testler: list[dict[str, Any]] = [
        {"title": "TPD-1 › 6 adet → 1 bedava", "status": "expected"},
        {"title": "TPD-1 › minimum sipariş 750 dahil", "status": "expected"},
    ]
    if sonuc == "assertion":
        testler[0] = {
            "title": "TPD-1 › 6 adet → 1 bedava",
            "status": "unexpected",
            "error": ASSERTION_HATASI,
            "failure": {"type": "assertion", "expected": "1", "received": "0"},
        }
    elif sonuc == "locator":
        testler[1] = {
            "title": "TPD-1 › minimum sipariş 750 dahil",
            "status": "unexpected",
            "error": "locator.click: Timeout 5000ms exceeded.",
            "failure": {"type": "locator_timeout"},
        }
    elif ortam_hatasi:
        testler = []
    elif sonuc == "derleme":
        r["tsc"] = {"ok": False, "error": "TS2304"}
        r["run"]["status"] = "skipped"
        testler = []
    r["run"]["tests"] = testler
    if platform != "web":
        r["lang"] = "java"
        r["platform"] = platform
        for ad in ("tsc", "eslint", "ast_guard"):
            r.pop(ad, None)
        r.update(
            app={"ok": True},
            deps={"ok": True},
            guard={"ok": True, "mode": "pr"},
            compile={"ok": True},
        )
        if sonuc == "appium_yok":
            r["run"]["saglik"] = {
                "ok": False,
                "api": {"url": "http://demo-api:8000/health", "hata": None},
                "appium": {"url": "http://appium:4723", "hata": "bağlantı reddedildi"},
                "hata": "Uygulama test ortamı sağlık kontrolü başarısız — appium",
            }
            r["run"]["error"] = r["run"]["saglik"]["hata"]
    return r


def kur(
    toolchain: FakeToolchain,
    plan: Callable[[str, str | None], str],
    kanca: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """`plan(platform, fault)` → rapor türü ya da `ulasilamaz` (bağlantı hatası)."""

    def yanit(body: dict[str, Any]) -> httpx.Response:
        if kanca is not None:
            kanca(body)
        tur = plan(body.get("platform") or "web", body.get("fault"))
        if tur == "ulasilamaz":
            raise httpx.ConnectError("bağlantı reddedildi")
        return httpx.Response(200, json=rapor(toolchain.kok, body, tur))

    toolchain.yanit = yanit


def baslat(engine: Engine, user: Principal, platformlar=("web",), hatalar=None) -> uuid.UUID:
    with Session(engine) as s, s.begin():
        return uuid.UUID(service.baslat(s, list(platformlar), hatalar, user)["id"])


def detay(engine: Engine, kid: uuid.UUID) -> dict[str, Any]:
    with Session(engine) as s, s.begin():
        d = service.detay(s, kid)
    assert d is not None
    return d


def adim(d: dict[str, Any], platform: str, asama: str, kod: str | None = None) -> dict[str, Any]:
    return next(
        a
        for a in d["adimlar"]
        if a["platform"] == platform and a["asama"] == asama and a["hata_kodu"] == kod
    )


@pytest.fixture
def muhendis(make_user) -> Principal:
    return make_user("engineer")


# ------------------------------------------------------------------ katalog


def test_katalog_dokuz_kod_analizdeki_ile_ayni() -> None:
    kat.onbellegi_temizle()
    hatalar = kat.katalog()
    assert {h["kod"] for h in hatalar} == DOKUZ and len(hatalar) == 9
    assert all(h["tur"] in ("kod", "veri") and h["ad"] and h["aciklama"] for h in hatalar)
    veri = {h["kod"] for h in hatalar if h["tur"] == "veri"}
    assert veri == {"min_siparis_500", "min_siparis_1000", "fiyat_p004_31", "kampanya_urunu_p002"}


def test_katalog_dogrulama_hatalari() -> None:
    ham = yaml.safe_load(kat.katalog_yolu().read_text(encoding="utf-8"))
    assert len(kat.dogrula(ham)) == 9
    with pytest.raises(kat.KatalogHatasi, match="iki kez"):
        kat.dogrula({**ham, "hatalar": [*ham["hatalar"], ham["hatalar"][0]]})
    with pytest.raises(kat.KatalogHatasi, match="geçersiz hata kodu"):
        kat.dogrula({**ham, "hatalar": [{**ham["hatalar"][0], "kod": "Kötü-Kod"}]})
    with pytest.raises(kat.KatalogHatasi, match="tür"):
        kat.dogrula({**ham, "hatalar": [{**ham["hatalar"][0], "tur": "baska"}]})
    with pytest.raises(kat.KatalogHatasi, match="eksik alan"):
        kat.dogrula({**ham, "hatalar": [{"kod": "x"}]})
    with pytest.raises(kat.KatalogHatasi, match="sürüm"):
        kat.dogrula({**ham, "version": 2})


def test_istek_dogrulama(engine: Engine, muhendis: Principal) -> None:
    with Session(engine) as s, s.begin():
        with pytest.raises(service.GecersizIstek, match="Bilinmeyen platform"):
            service.baslat(s, ["web", "linux"], None, muhendis)
        with pytest.raises(service.GecersizIstek, match="Katalogda olmayan"):
            service.baslat(s, ["web"], ["yok_boyle"], muhendis)
        with pytest.raises(service.GecersizIstek, match="En az bir platform"):
            service.baslat(s, [], None, muhendis)
    # Platformlar sabit sırada (web önce), hatalar katalog sırasında; tekrarlar düşer.
    assert service.platformlari_dogrula(["ios", "web", "ios"]) == ["web", "ios"]
    assert service.hatalari_dogrula(["min_siparis_500", "kampanya_esik_7"]) == [
        "kampanya_esik_7",
        "min_siparis_500",
    ]


# ------------------------------------------------------------------ başlatma


def test_baslatma_adimlari_ve_isi_yazar(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis, ["android", "web"], ["kampanya_esik_7", "min_siparis_500"])
    d = detay(engine, kid)
    assert d["durum"] == "queued" and d["platformlar"] == ["web", "android"]
    assert d["ozet"] is None and d["baslatan"] == muhendis.kullanici_adi
    sira = [(a["sira"], a["platform"], a["asama"], a["hata_kodu"]) for a in d["adimlar"]]
    assert sira == [
        (0, "web", "temel", None),
        (1, "web", "hata", "kampanya_esik_7"),
        (2, "web", "hata", "min_siparis_500"),
        (3, "web", "kapanis", None),
        (4, "android", "temel", None),
        (5, "android", "hata", "kampanya_esik_7"),
        (6, "android", "hata", "min_siparis_500"),
        (7, "android", "kapanis", None),
    ]
    assert all(a["sonuc"] == "bekliyor" and a["run_id"] is None for a in d["adimlar"])
    with engine.connect() as c:
        is_ = c.execute(
            text("SELECT tur, max_deneme, zaman_asimi_s FROM job WHERE idempotency_key = :k"),
            {"k": service.is_anahtari(kid)},
        ).one()
    assert is_.tur == "hata_kosusu.calistir" and is_.max_deneme == 1
    # Süre sınırı tüm koşuyu kapsar: 8 adım × (/check zaman aşımı + pay) + pay.
    assert is_.zaman_asimi_s == service.is_zaman_asimi_s(8)
    assert is_.zaman_asimi_s > 8 * 3000
    from tp_core.workflow.jobs import REGISTRY, uzun_turler

    assert "hata_kosusu.calistir" in uzun_turler() and REGISTRY["hata_kosusu.calistir"]


def test_suren_kosu_varken_ikincisi_409(engine: Engine, muhendis: Principal) -> None:
    baslat(engine, muhendis)
    with Session(engine) as s, s.begin(), pytest.raises(HataKosusuSuruyor):
        service.baslat(s, ["web"], None, muhendis)


# ------------------------------------------------------------------ iş: senaryolar


def test_web_mutlu_yol_senaryo_11(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "assertion" if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_esik_7", "min_siparis_500"])
    run_jobs(engine)
    # Her adım tam suite, CI gövdesiyle; retries=0, repeat_each=1; hata adımında `fault`.
    assert len(toolchain.istekler) == 4
    for b in toolchain.istekler:
        assert b["sha"] == SHA and b["test_files"] == []
        assert (b["retries"], b["repeat_each"], b["ast_guard_mode"]) == (0, 1, "pr")
        assert "lang" not in b and "platform" not in b
    assert [b.get("fault") for b in toolchain.istekler] == [
        None,
        "kampanya_esik_7",
        "min_siparis_500",
        None,
    ]
    assert "fault" not in toolchain.istekler[0]
    d = detay(engine, kid)
    assert d["durum"] == "done" and d["commit"] == SHA and d["bitis"] and d["baslama"]
    assert [a["sonuc"] for a in d["adimlar"]] == ["yesil", "yakalandi", "yakalandi", "yesil"]
    yak = adim(d, "web", "hata", "kampanya_esik_7")
    assert yak["kiran_testler"] == ["TPD-1 › 6 adet → 1 bedava"]
    assert yak["hata_adi"] == "Kampanya eşiği 6 yerine 7" and yak["sure_ms"] is not None
    assert d["ozet"]["oran"] == 1.0 and d["ozet"]["yakalanan"] == 2 and d["ozet"]["kacanlar"] == []
    assert d["uyarilar"] == []
    with Session(engine) as s:
        for a in d["adimlar"]:
            run = s.get(Run, uuid.UUID(a["run_id"]))
            assert run.tetik == "break_verify" and run.kaynak == "local"
            assert run.ortam["hata_kosusu_id"] == str(kid)
            assert run.ortam["hata_kodu"] == a["hata_kodu"]
            assert run.ortam["platform"] == "web" and run.ortam["break_campaign"] is False
            assert run.sonuc == ("passed" if a["asama"] != "hata" else "failed")
            # Koşu detayı CI yoluyla aynı: test sonuçları işlendi, artefakt dizini var.
            assert run.artefaktlar["dizin"].startswith("runs/hk-")
        from tp_core.features.ci.service import run_detail

        rd = run_detail(s, uuid.UUID(yak["run_id"]))
        assert rd["hata_kodu"] == "kampanya_esik_7" and rd["hata_kosusu_id"] == str(kid)


def test_temel_kirmizi_platform_gecersiz(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "assertion")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_esik_7", "min_siparis_500"])
    run_jobs(engine)
    assert len(toolchain.istekler) == 1  # yalnız temel koşu
    d = detay(engine, kid)
    assert d["durum"] == "done"
    assert adim(d, "web", "temel")["sonuc"] == "kirmizi"
    for a in d["adimlar"][1:]:
        assert a["sonuc"] == "gecersiz" and a["neden"].startswith("temel koşu yeşil değil")
        assert a["run_id"] is None
    assert d["ozet"]["oran"] is None and d["ozet"]["gecersiz"] == 2


def test_yakalandi_kacti_gecersiz_senaryo_12(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    sonuclar = {
        "kampanya_esik_7": "assertion",
        "min_siparis_500": "yesil",
        "fiyat_p004_31": "saglik",
        "min_siparis_1000": "locator",
        "kampanya_cift_indirim": "ulasilamaz",
        "min_siparis_haric": "derleme",
    }
    kur(toolchain, lambda p, f: sonuclar[f] if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], list(sonuclar))
    run_jobs(engine)
    d = detay(engine, kid)
    s = {a["hata_kodu"]: a for a in d["adimlar"] if a["asama"] == "hata"}
    assert s["kampanya_esik_7"]["sonuc"] == "yakalandi"
    assert s["min_siparis_500"]["sonuc"] == "kacti"
    assert "yakalanmadı" in s["min_siparis_500"]["neden"]
    assert s["fiyat_p004_31"]["sonuc"] == "gecersiz"
    assert "sağlık kontrolü" in s["fiyat_p004_31"]["neden"]
    # Assertion olmayan kırmızı hata yakalama kanıtı sayılmaz.
    assert s["min_siparis_1000"]["sonuc"] == "gecersiz"
    assert "assertion" in s["min_siparis_1000"]["neden"]
    assert s["min_siparis_1000"]["kiran_testler"] == ["TPD-1 › minimum sipariş 750 dahil"]
    assert s["kampanya_cift_indirim"]["sonuc"] == "gecersiz"
    assert "Toolchain'e ulaşılamadı" in s["kampanya_cift_indirim"]["neden"]
    with Session(engine) as ses:
        run = ses.get(Run, uuid.UUID(s["kampanya_cift_indirim"]["run_id"]))
        assert run.sonuc == "error" and "ulaşılamadı" in run.artefaktlar["hata"]
    assert s["min_siparis_haric"]["sonuc"] == "gecersiz"
    assert "Derleme" in s["min_siparis_haric"]["neden"]
    oz = d["ozet"]
    assert (oz["yakalanan"], oz["kacan"], oz["gecersiz"]) == (1, 1, 4)
    assert oz["oran"] == 0.5
    assert oz["kacanlar"] == [
        {"hata_kodu": "min_siparis_500", "ad": "Minimum sipariş tutarı 500", "platform": "web"}
    ]


def test_cok_platform_sirali_ve_cihaz_kapali_senaryo_13(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    def plan(p: str, f: str | None) -> str:
        if p == "android":
            return "appium_yok"
        if p == "ios":
            return "ulasilamaz"
        return "assertion" if f else "yesil"

    kur(toolchain, plan)
    kid = baslat(engine, muhendis, ["ios", "android", "web"], ["kampanya_esik_7"])
    run_jobs(engine)
    # Sıra: web (3 adım) → android (temel) → ios (temel); uygulama gövdesi CI ile aynı.
    sira = [(b.get("platform") or "web", b.get("fault")) for b in toolchain.istekler]
    assert sira == [
        ("web", None),
        ("web", "kampanya_esik_7"),
        ("web", None),
        ("android", None),
        ("ios", None),
    ]
    assert toolchain.istekler[3]["lang"] == "java"
    d = detay(engine, kid)
    assert d["durum"] == "done"
    temel = adim(d, "android", "temel")
    assert temel["sonuc"] == "gecersiz" and "Cihaz/Appium erişilemiyor" in temel["neden"]
    for a in d["adimlar"]:
        if a["platform"] in ("android", "ios") and a["asama"] != "temel":
            assert a["sonuc"] == "gecersiz" and a["neden"].startswith("temel koşu yeşil değil")
    assert "Cihaz/Appium" in adim(d, "android", "hata", "kampanya_esik_7")["neden"]
    # Oran etkilenmez: geçersiz adımlar paydaya girmez.
    oz = d["ozet"]
    assert oz["oran"] == 1.0 and oz["yakalanan"] == 1 and oz["gecersiz"] == 2
    pl = {p["platform"]: p for p in oz["platformlar"]}
    assert pl["web"]["oran"] == 1.0 and pl["android"]["oran"] is None
    assert [p["platform"] for p in oz["platformlar"]] == ["web", "android", "ios"]
    with Session(engine) as s:
        run = s.get(Run, uuid.UUID(temel["run_id"]))
        assert run.ortam["platform"] == "android" and run.sonuc == "error"


def test_kapanis_kirmizi_uyari(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    sayac = {"n": 0}

    def plan(p: str, f: str | None) -> str:
        sayac["n"] += 1
        if f:
            return "assertion"
        return "yesil" if sayac["n"] == 1 else "locator"

    kur(toolchain, plan)
    kid = baslat(engine, muhendis, ["web"], ["kampanya_esik_7"])
    run_jobs(engine)
    d = detay(engine, kid)
    assert d["durum"] == "done"
    assert adim(d, "web", "kapanis")["sonuc"] == "kirmizi"
    assert len(d["uyarilar"]) == 1 and "kapanış koşusu yeşil değil" in d["uyarilar"][0]


def test_olaylar_her_adimdan_sonra(
    engine: Engine,
    muhendis: Principal,
    toolchain: FakeToolchain,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    olaylar: list[tuple[str, dict[str, Any]]] = []
    gercek = service.publish_tx

    def yakala(conn: Any, ad: str, veri: dict[str, Any]) -> None:
        olaylar.append((ad, dict(veri)))
        gercek(conn, ad, veri)

    monkeypatch.setattr(service, "publish_tx", yakala)
    kur(toolchain, lambda p, f: "assertion" if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_esik_7"])
    run_jobs(engine)
    hk = [v for ad, v in olaylar if ad == "hata_kosusu.ilerleme"]
    assert all(set(v) == {"id", "durum", "platform", "hata_kodu", "asama", "sonuc"} for v in hk)
    assert all(v["id"] == str(kid) for v in hk)
    biten = [(v["asama"], v["hata_kodu"], v["sonuc"]) for v in hk if v["sonuc"] is not None]
    assert biten == [
        ("temel", None, "yesil"),
        ("hata", "kampanya_esik_7", "yakalandi"),
        ("kapanis", None, "yesil"),
    ]
    assert hk[0]["durum"] == "queued" and hk[-1]["durum"] == "done"
    assert [v["durum"] for v in hk].count("running") >= 6  # başlangıç + adım başına 2


# ------------------------------------------------------------------ iptal, kurtarma


def test_kuyruktaki_kosu_hemen_iptal(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis)
    with Session(engine) as s, s.begin():
        assert service.iptal(s, kid, muhendis) == {"id": str(kid), "durum": "cancelled"}
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT durum FROM job WHERE idempotency_key = :k"),
                {"k": service.is_anahtari(kid)},
            ).scalar_one()
            == "cancelled"
        )
    d = detay(engine, kid)
    assert d["durum"] == "cancelled" and d["bitis"] and "iptal" in d["uyarilar"][0]
    with Session(engine) as s, s.begin(), pytest.raises(WorkflowError):
        service.iptal(s, kid, muhendis)
    # İptal edilen koşu yenisini engellemez.
    baslat(engine, muhendis)


def test_suren_kosu_adim_arasinda_iptal(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kimlik: dict[str, uuid.UUID] = {}

    def kanca(body: dict[str, Any]) -> None:
        if body.get("fault") == "kampanya_esik_7":
            with Session(engine) as s, s.begin():
                assert service.iptal(s, kimlik["id"], muhendis)["durum"] == "cancelled"

    kur(toolchain, lambda p, f: "assertion" if f else "yesil", kanca)
    kimlik["id"] = kid = baslat(
        engine, muhendis, ["web", "android"], ["kampanya_esik_7", "min_siparis_500"]
    )
    run_jobs(engine)
    # Koşmakta olan adım biter, sonraki adıma geçilmez.
    assert [b.get("fault") for b in toolchain.istekler] == [None, "kampanya_esik_7"]
    d = detay(engine, kid)
    assert d["durum"] == "cancelled" and d["bitis"]
    assert [a["sonuc"] for a in d["adimlar"]][:3] == ["yesil", "yakalandi", "bekliyor"]
    assert d["ozet"]["yakalanan"] == 1 and d["ozet"]["bekleyen"] == 3


def test_beklenmeyen_hata_kosuyu_failed_yapar(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    def patla(_body: dict[str, Any]) -> None:
        raise RuntimeError("beklenmedik")

    kur(toolchain, lambda p, f: "yesil", patla)
    kid = baslat(engine, muhendis)
    run_jobs(engine)
    d = detay(engine, kid)
    assert d["durum"] == "failed" and d["bitis"]
    assert "Beklenmeyen hata: RuntimeError" in d["uyarilar"][-1]


def test_cokus_sonrasi_worker_acilisi_kurtarir(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis)
    with engine.begin() as c:
        # Worker koşu sürerken öldü / süre aşıldı: iş failed, koşu running'de kaldı.
        c.execute(text("UPDATE hata_kosusu SET durum = 'running' WHERE id = :i"), {"i": kid})
        c.execute(
            text(
                "UPDATE job SET durum = 'failed', son_hata = 'zaman aşımı (900 sn)' "
                "WHERE idempotency_key = :k"
            ),
            {"k": service.is_anahtari(kid)},
        )
    with engine.begin() as c:
        hk_jobs.on_worker_start(c)
    with Session(engine) as s:
        kosu = s.get(HataKosusu, kid)
        assert kosu.durum == "failed" and kosu.bitis is not None
        assert "yarıda kaldı" in kosu.uyarilar[-1] and "zaman aşımı" in kosu.uyarilar[-1]


def test_iptal_edilip_kesilen_kosu_acilista_kapanir(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis)
    with engine.begin() as c:
        c.execute(text("UPDATE hata_kosusu SET durum = 'running' WHERE id = :i"), {"i": kid})
    with Session(engine) as s, s.begin():
        service.iptal(s, kid, muhendis)
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET durum = 'failed' WHERE idempotency_key = :k"),
            {"k": service.is_anahtari(kid)},
        )
        hk_jobs.on_worker_start(c)
    d = detay(engine, kid)
    assert d["durum"] == "cancelled" and d["bitis"] and d["ozet"] is not None


def test_takili_kosu_yeni_baslatmayi_engellemez(engine: Engine, muhendis: Principal) -> None:
    kid = baslat(engine, muhendis)
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET durum = 'failed' WHERE idempotency_key = :k"),
            {"k": service.is_anahtari(kid)},
        )
    yeni = baslat(engine, muhendis)
    assert yeni != kid and detay(engine, kid)["durum"] == "failed"


# ------------------------------------------------------------------ KPI ve triage


def test_kpi_ve_triage_disinda_bug_taslagi_yok_senaryo_14(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    kur(toolchain, lambda p, f: "assertion" if f else "yesil")
    kid = baslat(engine, muhendis, ["web"], ["kampanya_esik_7", "kampanya_bedava_yok"])
    run_jobs(engine, limit=50)
    with Session(engine) as s:
        runs = s.scalars(select(Run).where(Run.ortam["hata_kosusu_id"].astext == str(kid))).all()
        assert len(runs) == 4
        kirmizi = [r for r in runs if r.sonuc == "failed"]
        assert len(kirmizi) == 2
        # Kontrol Kulesi KPI dışlaması (`_kirma_degil`) bu koşuları zaten dışlar.
        sayilan = s.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.id.in_([r.id for r in runs]), kule._kirma_degil())
        )
        assert sayilan == 0
        g = kule.gecme_orani(s, 20)
        assert g["toplam"] == 0 and g["oran"] is None
        # Triage kırmızı koşuyu sınıflandırmadan atlar; failure ve bug taslağı yok.
        for r in kirmizi:
            tk = s.get(TriageKosu, r.id)
            assert tk is not None and tk.durum == "skipped"
            assert "ekilmiş hata koşusu" in tk.neden
        assert s.scalar(select(func.count()).select_from(Failure)) == 0
        assert s.scalar(select(func.count()).select_from(BugDraft)) == 0


def test_triage_uygunlugu_hata_kosusu_kosusunu_atlar(engine: Engine) -> None:
    from tp_core.features.triage.service import uygunluk

    run = Run(
        id=uuid.uuid4(),
        tetik="break_verify",
        kaynak="local",
        sonuc="failed",
        ortam={"hata_kosusu_id": str(uuid.uuid4()), "hata_kodu": "kampanya_esik_7"},
    )
    with Session(engine) as s:
        u = uygunluk(s, run)
    assert u.uygun is False and u.kirma is True


# ------------------------------------------------------------------ özet


def _adim(platform: str, asama: str, sonuc: str, kod: str | None = None) -> HataKosusuAdim:
    return HataKosusuAdim(platform=platform, asama=asama, sonuc=sonuc, hata_kodu=kod, sira=0)


def test_ozet_hesabi() -> None:
    adimlar = [
        _adim("web", "temel", "yesil"),
        _adim("web", "hata", "yakalandi", "kampanya_esik_7"),
        _adim("web", "hata", "yakalandi", "min_siparis_500"),
        _adim("web", "hata", "kacti", "fiyat_p004_31"),
        _adim("web", "hata", "gecersiz", "min_siparis_1000"),
        _adim("web", "kapanis", "yesil"),
        _adim("ios", "temel", "gecersiz"),
        _adim("ios", "hata", "gecersiz", "kampanya_esik_7"),
        _adim("ios", "kapanis", "gecersiz"),
    ]
    oz = service.ozet_hesapla(adimlar, ["web", "ios"])
    assert (oz["yakalanan"], oz["kacan"], oz["gecersiz"], oz["bekleyen"]) == (2, 1, 2, 0)
    assert oz["oran"] == round(2 / 3, 4)
    web, ios = oz["platformlar"]
    assert web == {
        "platform": "web",
        "oran": round(2 / 3, 4),
        "yakalanan": 2,
        "kacan": 1,
        "gecersiz": 1,
        "bekleyen": 0,
        "temel": "yesil",
        "kapanis": "yesil",
    }
    assert ios["oran"] is None and ios["gecersiz"] == 1
    assert oz["kacanlar"] == [
        {"hata_kodu": "fiyat_p004_31", "ad": "P-004 fiyatı 31", "platform": "web"}
    ]
    assert service.ozet_hesapla([], ["web"])["oran"] is None


def test_hata_yakalama_ozeti_kule_sekli(
    engine: Engine, muhendis: Principal, toolchain: FakeToolchain
) -> None:
    with Session(engine) as s:
        assert service.hata_yakalama_ozeti(s) is None
    kur(
        toolchain,
        lambda p, f: {"min_siparis_500": "yesil"}.get(f or "", "assertion" if f else "yesil"),
    )
    kid = baslat(engine, muhendis, ["web"], ["kampanya_esik_7", "min_siparis_500"])
    run_jobs(engine)
    # Süren (sonraki) koşu son tamamlanan koşunun yerini almaz.
    baslat(engine, muhendis)
    with Session(engine) as s:
        hy = service.hata_yakalama_ozeti(s)
    assert hy is not None
    assert set(hy) == {
        "son_kosu",
        "oran",
        "yakalanan",
        "kacan",
        "gecersiz",
        "platformlar",
        "kacanlar",
        "kaynak",
    }
    assert hy["son_kosu"]["id"] == str(kid) and hy["son_kosu"]["durum"] == "done"
    assert hy["son_kosu"]["bitis"]
    assert (hy["oran"], hy["yakalanan"], hy["kacan"], hy["gecersiz"]) == (0.5, 1, 1, 0)
    assert hy["platformlar"] == [
        {"platform": "web", "oran": 0.5, "yakalanan": 1, "kacan": 1, "gecersiz": 0}
    ]
    assert hy["kacanlar"] == [
        {"hata_kodu": "min_siparis_500", "ad": "Minimum sipariş tutarı 500", "platform": "web"}
    ]
    assert "yakalanan 1, kaçan 1" in hy["kaynak"]


# ------------------------------------------------------------------ API ve roller


def test_api_roller_ve_sekiller(api: TestClient, make_user, engine: Engine) -> None:
    login(api, make_user("analyst"))
    r = api.post("/fault-runs", json={"platformlar": ["web"]})
    assert r.status_code == 403
    assert api.get("/fault-runs/catalog").status_code == 200
    login(api, make_user("presenter"))
    r = api.post("/fault-runs", json={"platformlar": ["web"], "hatalar": ["kampanya_esik_7"]})
    assert r.status_code == 202, r.text
    govde = r.json()
    assert set(govde) == {"id", "durum"} and govde["durum"] == "queued"
    r2 = api.post("/fault-runs", json={"platformlar": ["web"]})
    assert r2.status_code == 409 and r2.json()["kod"] == "hata_kosusu_suruyor"
    liste = api.get("/fault-runs", params={"limit": 5}).json()
    assert [k["id"] for k in liste] == [govde["id"]]
    assert set(liste[0]) == {
        "id",
        "durum",
        "platformlar",
        "hatalar",
        "commit",
        "baslatan_id",
        "baslatan",
        "ozet",
        "uyarilar",
        "baslama",
        "bitis",
        "olusturma",
    }
    d = api.get(f"/fault-runs/{govde['id']}").json()
    assert len(d["adimlar"]) == 3
    assert set(d["adimlar"][0]) == {
        "id",
        "platform",
        "hata_kodu",
        "hata_adi",
        "asama",
        "run_id",
        "sonuc",
        "kiran_testler",
        "neden",
        "sure_ms",
        "sira",
    }
    assert api.get(f"/fault-runs/{uuid.uuid4()}").status_code == 404
    kat_ = api.get("/fault-runs/catalog").json()
    assert len(kat_) == 9 and set(kat_[0]) == {"kod", "ad", "tur", "aciklama", "yakalayan_kural"}
    login(api, make_user("engineer"))
    r = api.post(f"/fault-runs/{govde['id']}/cancel")
    assert r.status_code == 200 and r.json()["durum"] == "cancelled"
    assert api.post(f"/fault-runs/{govde['id']}/cancel").status_code == 409
    r = api.post("/fault-runs", json={"platformlar": ["web"], "hatalar": ["yok"]})
    assert r.status_code == 422 and "Katalogda olmayan" in r.json()["detail"]
    r = api.post("/fault-runs", json={"platformlar": ["linux"]})
    assert r.status_code == 422
    r = api.post("/fault-runs", json={"platformlar": ["web"], "hatalar": ["Kötü"]})
    assert r.status_code == 422
    r = api.post("/fault-runs", json={"platformlar": ["web"]})
    assert r.status_code == 202
    login(api, make_user("po"))
    assert api.post(f"/fault-runs/{r.json()['id']}/cancel").status_code == 403


def test_codegen_toolchain_istemcisi_fault_alani() -> None:
    import json

    from tp_core.features.codegen.toolchain import ToolchainClient

    govdeler: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        govdeler.append(json.loads(request.content))
        return httpx.Response(200, json={"conclusion": "success"})

    c = ToolchainClient("http://tc", transport=httpx.MockTransport(handler))
    c.check(SHA, [], repeat_each=1)
    c.check(SHA, [], repeat_each=1, fault="kampanya_esik_7", platform="android")
    c.close()
    # Verilmezse gövdeye yazılmaz: eski toolchain'lerle istek baytları aynı kalır.
    assert "fault" not in govdeler[0]
    assert govdeler[1]["fault"] == "kampanya_esik_7" and govdeler[1]["lang"] == "java"
