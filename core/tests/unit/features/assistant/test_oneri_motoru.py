"""Öneri motoru — gerçek Postgres'te olgular, tohum vakaları, rol filtresi, bastırma ve
`oneri_gecerli_mi` (AI-ASISTAN-PLANI §13 "Öneri (§17)", "Yan etkisizlik").
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.unit.conftest import Db
from tp_core.config import get_settings
from tp_core.features.assistant import oneri
from tp_core.features.assistant.oneri import JiraBaglantisi
from tp_core.workflow.service import Principal

from .oneri_tohum import VAKALAR, Ekran, Tohum

ROLLER = oneri.ROLLER
SIM = JiraBaglantisi(proje="TPD", gezinme_koku=None, olusturma_adresi=None, simulator=True)
MakeUser = Callable[..., Principal]


@pytest.fixture(autouse=True)
def _ortam(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TP_DAILY_BUDGET_USD", "10")
    monkeypatch.delenv("TP_ASISTAN_ONERI", raising=False)
    get_settings.cache_clear()
    oneri.ONBELLEK.temizle()
    yield
    get_settings.cache_clear()
    oneri.ONBELLEK.temizle()


@pytest.fixture
def tohum(engine: Engine) -> Tohum:
    return Tohum(engine)


def _hesapla(engine: Engine, kisi: Principal, e: Ekran, **kw: Any) -> dict[str, Any]:
    with Session(engine) as s:
        return oneri.oneriler(
            s, kisi, e.rota, e.varlik_tur, e.varlik_id, simdi=e.simdi, jira=SIM, **kw
        )


def _idler(sonuc: dict[str, Any]) -> list[str]:
    return [c["kural_id"] for c in sonuc["oneriler"]]


def _simdi() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ her kural: olumlu + olumsuz


def test_her_kuralin_tohum_vakasi_var() -> None:
    assert set(VAKALAR) == {k.id for k in oneri.kural_seti().kurallar}
    for kid, (rol, _, _) in VAKALAR.items():
        k = oneri.kural_seti().kural(kid)
        assert k is not None and rol in k.roller, kid


@pytest.mark.parametrize("kural_id", sorted(VAKALAR))
def test_kural_olumlu_ve_olumsuz_vaka(
    kural_id: str, engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    rol, olumlu, olumsuz = VAKALAR[kural_id]
    kisi = make_user(rol)
    e = olumlu(tohum, _simdi())
    sonuc = _hesapla(engine, kisi, e)
    assert sonuc["ekranda_kural_var"] is True
    assert kural_id in _idler(sonuc), (kural_id, sonuc)
    kart = next(c for c in sonuc["oneriler"] if c["kural_id"] == kural_id)
    for alan in ("baslik", "neden", "aciklama"):
        assert kart[alan] and "{" not in kart[alan] and "}" not in kart[alan], (kural_id, alan)
    assert kart["eylem"]["tur"] == oneri.kural_seti().kural(kural_id).eylem_turu  # type: ignore[union-attr]
    assert "Kampanya" not in str(kart)  # varlığın serbest metin başlığı karta girmez

    e = olumsuz(tohum, _simdi())
    assert kural_id not in _idler(_hesapla(engine, kisi, e)), kural_id


@pytest.mark.parametrize("rol", ROLLER)
def test_rol_filtresi_yalniz_kendi_rolunun_kurallari(
    rol: str, engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    """Tüm olumlu tohumlarda bu rol yalnız kendi rolünün kurallarını görür; kendi kuralı görünür."""
    kisi = make_user(rol)
    ks = oneri.kural_seti()
    for kid, (_, olumlu, _) in VAKALAR.items():
        e = olumlu(tohum, _simdi())
        try:
            sonuc = _hesapla(engine, kisi, e)
        except (oneri.EkranBulunamadi, oneri.VarlikBulunamadi):
            # Rolüne kapalı ekran ya da rolün okuma izni olmayan varlık (specs/012-rol-yetki §4.2)
            continue
        for gelen in _idler(sonuc):
            k = ks.kural(gelen)
            assert k is not None and rol in k.roller, (rol, gelen)
        hedef = ks.kural(kid)
        assert hedef is not None
        assert (kid in _idler(sonuc)) is (rol in hedef.roller), (rol, kid)
        assert sonuc["ekranda_kural_var"] is oneri.ekranda_kural_var(hedef.ekran, rol)


def test_oneriler_oncelik_sirasiyla(engine: Engine, tohum: Tohum, make_user: MakeUser) -> None:
    """Aynı ekranda birden çok kural azalan öncelikle sıralanır."""
    fid = tohum.hata("test_data")
    tohum.bug_taslagi("draft", failure_id=fid)
    e = Ekran(f"/hatalar/{fid}", "failure", fid, _simdi())
    kisi = make_user("tester")
    sonuc = _hesapla(engine, kisi, e)
    assert _idler(sonuc) == ["hata-test-verisi-task"]  # bug kuralı product_defect ister
    req = tohum.gereksinim("failed", ac_missing=True)
    sonuc = _hesapla(
        engine, make_user("analyst"), Ekran(f"/gereksinimler/{req}", None, None, _simdi())
    )
    assert _idler(sonuc) == ["gereksinim-ac-eksik-jira", "gereksinim-basarisiz"]
    assert [c["oncelik"] for c in sonuc["oneriler"]] == [85, 70]


# ------------------------------------------------------------------ olgular


def test_olgular_gereksinim(engine: Engine, tohum: Tohum, make_user: MakeUser) -> None:
    req = tohum.gereksinim("findings_open", ac_missing=True)
    tohum.bulgu(req)
    tohum.bulgu(req, durum="open", kanit=False)  # doğrulanmamış kanıt sayılmaz
    tohum.bulgu(req, durum="decided")
    tohum.case(req, "draft")
    tohum.case(req, "approved")
    tohum.case(req, "approved")
    tohum.case(req, "superseded")
    with Session(engine) as s:
        o = oneri.olgular(s, make_user("tester"), "requirement", req)
    assert o["durum"] == "findings_open" and o["po_kanal"] == "jira" and o["ac_eksik"] is True
    assert o["acik_bulgu_sayisi"] == 1
    assert (o["inceleme_bekleyen_case"], o["onayli_case"]) == (1, 2)
    assert oneri.JIRA_ANAHTARI.match(o["jira_key"])
    assert "po_bekleme_saat" not in o  # pending_po değil
    # Varlık türüne uymayan olgu dönmez.
    assert not set(o) & {"hata_sinifi", "ci_sonuc", "butce_orani", "kirarak_dogrulama"}


def test_po_bekleme_denetim_izinden(engine: Engine, tohum: Tohum, make_user: MakeUser) -> None:
    req = tohum.gereksinim("pending_po", kaynak="free_text", jira_key=None)
    with Session(engine) as s:  # ne denetim ne inceleme kaydı → olgu yok, kural eşleşmez
        assert "po_bekleme_saat" not in oneri.olgular(s, make_user("po"), "requirement", req)
    tohum.pending_po_denetimi(req)
    simdi = _simdi() + timedelta(hours=25, minutes=5)
    with Session(engine) as s:
        o = oneri.olgular(s, make_user("po"), "requirement", req, simdi=simdi)
    assert o["po_bekleme_saat"] == 25 and o["po_kanal"] == "portal" and "jira_key" not in o
    sonuc = _hesapla(
        engine, make_user("analyst"), Ekran(f"/gereksinimler/{req}", None, None, simdi)
    )
    kart = next(c for c in sonuc["oneriler"] if c["kural_id"] == "gereksinim-po-bekliyor-portal")
    assert kart["baslik"] == "PO onayı 1 gündür bekliyor; onay portalda"


def test_olgular_script_kosu_hata_bug_genel(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    kisi = make_user("engineer")
    sid = tohum.script("pr_open", "weak")
    onarim = tohum.script("pr_open", None)
    rid = tohum.kosu("error")
    with Session(engine) as s:
        assert oneri.olgular(s, kisi, "script", sid) == {
            "durum": "pr_open",
            "kirarak_dogrulama": "weak",
            "defect_adayi": False,
        }
        assert oneri.olgular(s, kisi, "script", onarim) == {"durum": "pr_open"}
        assert oneri.olgular(s, kisi, "run", rid) == {"ci_sonuc": "error"}
    fid = tohum.hata("product_defect")
    eski = tohum.bug_taslagi("published", failure_id=fid)
    yeni = tohum.bug_taslagi("draft", failure_id=fid)
    bid = tohum.bug_taslagi("draft", jira_key="TPD-42")
    with Session(engine) as s:
        o = oneri.olgular(s, kisi, "failure", fid)
        assert o["bug_taslagi_var"] is True and o["bug_taslagi_id"] == str(yeni) != str(eski)
        assert o["hata_sinifi"] == "product_defect" and o["onarim_durumu"] == "none"
        assert o["flaky_tekrar"] == 0
        assert oneri.olgular(s, kisi, "bug_draft", bid) == {
            "durum": "draft",
            "bulgu_kaynakli": False,
            "jira_key": "TPD-42",
        }
        g = oneri.olgular(s, kisi, None, None)
    assert g == {"butce_orani": 0.0}  # bitmiş koşu yok → son_kosu_saat olgusu yok


def test_script_insana_dustu_defect_adayi_ve_rota(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    """Kural 15: "Yeniden üret" Kod listesinde (rota /kod); defect adayı (engel ya da yerel sınıf)
    ve üretim kaydı olmayan script'te önerilmez (Kod.tsx düğme koşuluyla aynı)."""
    kisi = make_user("engineer")
    locator = tohum.script("blocked", "not_started", engel_turu="locator")
    sonuc = _hesapla(engine, kisi, Ekran(f"/kod/{locator}", "script", locator, _simdi()))
    kart = next(c for c in sonuc["oneriler"] if c["kural_id"] == "script-insana-dustu")
    assert kart["eylem"]["rota"] == "/kod"
    yerel = tohum.script("blocked", "not_started", yerel_kontrol={"sinif": "defect_adayi"})
    atlandi = tohum.script(
        "blocked", "not_started", yerel_kontrol={"sinif": "defect_adayi", "atlandi": True}
    )
    onarim = tohum.script("blocked", None)
    with Session(engine) as s:
        assert oneri.olgular(s, kisi, "script", yerel)["defect_adayi"] is True
        assert oneri.olgular(s, kisi, "script", atlandi)["defect_adayi"] is False
    for sid in (yerel, onarim):
        e = Ekran(f"/kod/{sid}", "script", sid, _simdi())
        assert "script-insana-dustu" not in _idler(_hesapla(engine, kisi, e)), sid


def test_son_kosu_ic_tetikleri_saymaz(engine: Engine, tohum: Tohum, make_user: MakeUser) -> None:
    eski = _simdi() - timedelta(hours=40)
    tohum.kosu("passed", tetik="nightly", bitis=eski)
    tohum.kosu("passed", tetik="break_verify", bitis=_simdi())
    tohum.kosu("passed", tetik="local_check", bitis=_simdi())
    with Session(engine) as s:
        assert oneri.olgular(s, make_user("admin"), None, None)["son_kosu_saat"] == 40
    e = Ekran("/kosular", None, None, _simdi())
    # Koşu tetiklemek `run.trigger_scheduled` (engineer) izni ister (specs/012-rol-yetki).
    sonuc = _hesapla(engine, make_user("engineer"), e)
    assert _idler(sonuc) == ["guncel-kosu-yok"]
    assert sonuc["oneriler"][0]["neden"].startswith("Son koşu 1 gün önce")
    assert sonuc["oneriler"][0]["eylem"] == {"tur": "rota", "rota": "/kosular"}


def test_butce_yuzdesi_ve_varliksiz_ekran(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    tohum.harcama("8.54")
    sonuc = _hesapla(engine, make_user("admin"), Ekran("/kontrol-kulesi", None, None, _simdi()))
    assert [c["baslik"] for c in sonuc["oneriler"]] == ["Model bütçesinin %85 kadarı kullanıldı"]


def test_varlik_yoksa_ve_ekran_kapaliysa_hata(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    kisi = make_user("analyst")
    with Session(engine) as s:
        with pytest.raises(oneri.VarlikBulunamadi):
            oneri.oneriler(s, kisi, f"/gereksinimler/{uuid.uuid4()}", None, None, jira=SIM)
        with pytest.raises(oneri.VarlikBulunamadi):  # var olan ama başka türde kimlik
            sid = tohum.script()
            oneri.oneriler(s, kisi, f"/gereksinimler/{sid}", None, None, jira=SIM)
        with pytest.raises(oneri.EkranBulunamadi):  # `demo.read` Developer'da yok
            oneri.oneriler(s, make_user("developer"), "/demo", None, None, jira=SIM)
        with pytest.raises(oneri.VarlikBulunamadi):
            oneri.olgular(s, Principal(uuid.uuid4(), "x", "bilinmeyen"), None, None)


def test_kuralsiz_ekranda_bos_ve_dugme_gizli(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    req = tohum.gereksinim("findings_open")
    tohum.bulgu(req)
    sonuc = _hesapla(
        engine, make_user("admin"), Ekran(f"/gereksinimler/{req}", None, None, _simdi())
    )
    assert sonuc["ekranda_kural_var"] is False and sonuc["oneriler"] == []
    sonuc = _hesapla(engine, make_user("analyst"), Ekran("/denetim", None, None, _simdi()))
    assert sonuc["ekranda_kural_var"] is False and sonuc["rota_kalibi"] == "/denetim"


# ------------------------------------------------------------------ bastırma (Gizle / Yaptım)


def _yaz(engine: Engine, kisi: Principal, kural_id: str, deger: int, **kw: Any) -> dict[str, Any]:
    with Session(engine) as s, s.begin():
        return oneri.geri_bildirim_yaz(s, kisi, kural_id, deger, **kw)


def test_gizle_yalniz_o_kullaniciya_ve_ayni_durumda(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    a, b = make_user("tester"), make_user("tester")
    bid = tohum.bug_taslagi("draft")
    e = Ekran(f"/bug-taslaklari/{bid}", "bug_draft", bid, _simdi())
    kayit = _yaz(engine, a, "bug-taslagi-karari", -1, varlik_id=bid)
    assert kayit["varlik_durum"] == "draft"
    assert _idler(_hesapla(engine, a, e)) == []
    assert _hesapla(engine, a, e)["bastirilan"] == []  # gizleme "yaptım" bilgisi değildir
    assert _idler(_hesapla(engine, b, e)) == ["bug-taslagi-karari"]
    # "Faydalı" bastırmaz.
    _yaz(engine, b, "bug-taslagi-karari", 1, varlik_id=bid)
    assert _idler(_hesapla(engine, b, e)) == ["bug-taslagi-karari"]


def test_gizlenen_oneri_durum_degisince_geri_gelir(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    from tp_core.models import Failure, Script
    from tp_core.models.guard import allow_state_write

    a = make_user("tester")
    fid = tohum.hata("test_data")
    e = Ekran(f"/hatalar/{fid}", "failure", fid, _simdi())
    _yaz(engine, a, "hata-test-verisi-task", -1, varlik_id=fid)
    assert _idler(_hesapla(engine, a, e)) == []
    with Session(engine) as s, s.begin():
        s.get(Failure, fid).oneri_durumu = "proposed"  # type: ignore[union-attr]
    # Kural yine eşleşir ama varlık durumu değişti → yeniden görünür.
    assert _idler(_hesapla(engine, a, e)) == ["hata-test-verisi-task"]

    m = make_user("engineer")
    sid = tohum.script("pr_open", "not_started")
    e = Ekran(f"/kod/{sid}", "script", sid, _simdi())
    _yaz(engine, m, "script-kirarak-dogrula", -1, varlik_id=sid)
    for durum in ("checking", "pr_open"):  # ara durumdan aynı duruma dönüş: hâlâ gizli
        with allow_state_write(), Session(engine) as s, s.begin():
            s.get(Script, sid).durum = durum  # type: ignore[union-attr]
    assert _idler(_hesapla(engine, m, e)) == []


def test_yaptim_tum_rollerde_bastirir_ve_kisiyi_gosterir(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    analist, diger = make_user("analyst", ad="ayse"), make_user("analyst")
    req = tohum.gereksinim("pending_po", po_bekleme=30)
    simdi = _simdi()
    e = Ekran(f"/gereksinimler/{req}", "requirement", req, simdi)
    assert "gereksinim-po-hatirlatma-jira" in _idler(_hesapla(engine, diger, e))
    _yaz(
        engine,
        analist,
        "gereksinim-po-hatirlatma-jira",
        2,
        varlik_id=req,
        jira_anahtari="TPD-12",
        simdi=simdi,
    )
    sonuc = _hesapla(engine, diger, e)
    assert "gereksinim-po-hatirlatma-jira" not in _idler(sonuc)
    (b,) = sonuc["bastirilan"]
    assert b["kural_id"] == "gereksinim-po-hatirlatma-jira"
    assert (b["kisi"], b["jira_anahtari"]) == ("ayse", "TPD-12")
    assert b["baslik"].startswith("PO onayı 1 gündür")
    # tekrar_saat (24) dolunca hatırlatma yeniden gösterilir.
    sonra = Ekran(e.rota, e.varlik_tur, e.varlik_id, _simdi() + timedelta(hours=60))
    sonuc = _hesapla(engine, diger, sonra)
    assert "gereksinim-po-hatirlatma-jira" in _idler(sonuc) and sonuc["bastirilan"] == []


def test_yaptim_tekrar_saatsiz_kuralda_ayni_durumda_kalici(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    kisi = make_user("engineer")
    rid = tohum.kosu("error")
    e = Ekran(f"/kosular/{rid}", "run", rid, _simdi())
    _yaz(engine, kisi, "kosu-ortam-hatasi-task", 2, varlik_id=rid)
    gec = Ekran(e.rota, e.varlik_tur, e.varlik_id, _simdi() + timedelta(days=30))
    sonuc = _hesapla(engine, make_user("engineer"), gec)
    assert _idler(sonuc) == [] and sonuc["bastirilan"][0]["jira_anahtari"] is None


def test_varliksiz_kuralda_yaptim_ertesi_gun_duser(
    engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    sunucu = make_user("admin")
    tohum.harcama("9")
    # "Bugün" harcama satırının DB saatinden alınır: Python saati UTC gece yarısını geçmiş olsa
    # da gün anahtarı ve günlük harcama aynı güne düşer (sınırda kırılmasın).
    with engine.connect() as c:
        bugun = c.execute(text("SELECT max(olusturma) FROM ai_call")).scalar_one()
    with Session(engine) as s, s.begin():
        k = oneri.geri_bildirim_yaz(s, sunucu, "butce-uyarisi", 2, simdi=bugun)
    assert (
        k["varlik_durum"] == f"gun:{bugun.astimezone(UTC).date().isoformat()}"
        and k["varlik_id"] is None
    )
    e = Ekran("/kontrol-kulesi", None, None, bugun)
    sonuc = _hesapla(engine, make_user("admin"), e)
    assert _idler(sonuc) == [] and sonuc["bastirilan"][0]["kural_id"] == "butce-uyarisi"
    # Ertesi gün (UTC) aynı uyarı yeniden görünür. Harcama "bugün"e yazıldığından olguyu
    # sabitleyen kural seti kopyasıyla değil, doğrudan bastırma anahtarıyla doğrulanır.
    ks = oneri.kural_seti()
    with Session(engine) as s:
        ekran = oneri.ekran_coz(sunucu, "/kontrol-kulesi", None, None)
        kural = ks.kural("butce-uyarisi")
        assert kural is not None
        ertesi = bugun + timedelta(days=1)
        durum = oneri.varlik_durumu(None, {}, ertesi)
        _, yapildi = oneri._bastirmalar(s, sunucu, [kural], ekran, durum, ertesi)
    assert yapildi == {}


def test_geri_bildirim_dogrulamalari(engine: Engine, tohum: Tohum, make_user: MakeUser) -> None:
    analist = make_user("analyst")
    req = tohum.gereksinim("failed")
    with Session(engine) as s:
        with pytest.raises(oneri.KuralBulunamadi):
            oneri.geri_bildirim_yaz(s, analist, "yok-boyle", -1, req)
        with pytest.raises(oneri.GecersizGeriBildirim):
            oneri.geri_bildirim_yaz(s, analist, "gereksinim-basarisiz", 0, req)
        with pytest.raises(oneri.GecersizGeriBildirim):  # varlık kimliği zorunlu
            oneri.geri_bildirim_yaz(s, analist, "gereksinim-basarisiz", -1, None)
        with pytest.raises(oneri.VarlikBulunamadi):
            oneri.geri_bildirim_yaz(s, analist, "gereksinim-basarisiz", -1, uuid.uuid4())
        with pytest.raises(oneri.VarlikBulunamadi):  # kuralın rolü dışında
            oneri.geri_bildirim_yaz(s, make_user("tester"), "gereksinim-basarisiz", -1, req)
        for kotu in ("tpd-12", "TPD-12 ", "TPD-١٢", "https://x/browse/TPD-1"):
            with pytest.raises(oneri.GecersizGeriBildirim):
                oneri.geri_bildirim_yaz(
                    s, analist, "gereksinim-basarisiz", 2, req, jira_anahtari=kotu
                )
        with pytest.raises(oneri.GecersizGeriBildirim):  # anahtar yalnız "Yaptım" ile
            oneri.geri_bildirim_yaz(
                s, analist, "gereksinim-basarisiz", 1, req, jira_anahtari="TPD-1"
            )


# ------------------------------------------------------------------ oneri_gecerli_mi (E1)


def test_oneri_gecerli_mi_yeniden_hesaplar(
    engine: Engine, tohum: Tohum, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    analist = make_user("analyst")
    req = tohum.gereksinim("failed")
    baglam = {
        "rota_kalibi": "/gereksinimler/:id",
        "ekran": "Gereksinim detay",
        "varlik": {"tur": "requirement", "id": str(req), "anahtar": "TPD-1"},
        "rol": "po",  # bağlamdaki rol yok sayılır
    }
    with Session(engine) as s:
        assert oneri.oneri_gecerli_mi(s, analist, "gereksinim-basarisiz", baglam)
        b = oneri.oneri_baglami(s, analist, "gereksinim-basarisiz", baglam)
        assert b is not None and b["baslik"] == "Son işlem başarısız; nedenini sorun"
        assert set(b) == {"kural_id", "baslik", "neden", "aciklama"}
        # Somut rota da olur.
        assert oneri.oneri_gecerli_mi(
            s, analist, "gereksinim-basarisiz", {"rota": f"/gereksinimler/{req}"}
        )
        # Rol dışı, bilinmeyen kural, farklı ekran, eksik/olmayan varlık, bozuk bağlam → geçersiz.
        assert not oneri.oneri_gecerli_mi(s, make_user("po"), "gereksinim-basarisiz", baglam)
        assert not oneri.oneri_gecerli_mi(s, analist, "yok-boyle", baglam)
        assert not oneri.oneri_gecerli_mi(
            s,
            analist,
            "gereksinim-basarisiz",
            {**baglam, "rota_kalibi": "/gereksinimler/:id/caseler"},
        )
        assert not oneri.oneri_gecerli_mi(
            s,
            analist,
            "gereksinim-basarisiz",
            {**baglam, "varlik": {"tur": "requirement", "id": str(uuid.uuid4())}},
        )
        assert not oneri.oneri_gecerli_mi(s, analist, "gereksinim-basarisiz", None)
        assert not oneri.oneri_gecerli_mi(s, analist, "gereksinim-basarisiz", {"rota": "/ayarlar"})
    # Koşul artık sağlanmıyor → geçersiz (409 oneri_gecersiz).
    from tp_core.models import Requirement
    from tp_core.models.guard import allow_state_write

    with allow_state_write(), Session(engine) as s, s.begin():
        s.get(Requirement, req).durum = "in_review"  # type: ignore[union-attr]
    with Session(engine) as s:
        assert not oneri.oneri_gecerli_mi(s, analist, "gereksinim-basarisiz", baglam)
    # Gizlenmiş öneri hâlâ sorulabilir; bayrak kapalıyken geçersiz.
    with allow_state_write(), Session(engine) as s, s.begin():
        s.get(Requirement, req).durum = "failed"  # type: ignore[union-attr]
    _yaz(engine, analist, "gereksinim-basarisiz", -1, varlik_id=req)
    with Session(engine) as s:
        assert oneri.oneri_gecerli_mi(s, analist, "gereksinim-basarisiz", baglam)
        monkeypatch.setenv("TP_ASISTAN_ONERI", "0")
        assert not oneri.oneri_gecerli_mi(s, analist, "gereksinim-basarisiz", baglam)


# ------------------------------------------------------------------ yan etkisizlik


_OZET = "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {} x"


def _tablo_ozeti(db: Db) -> dict[str, tuple[int, str]]:
    sahip = db.engine("tp_owner")
    try:
        with sahip.connect() as c:
            tablolar = c.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")
            ).scalars()
            out = {}
            for t in list(tablolar):
                sayi, ozet = c.execute(text(_OZET.format(f'"{t}"'))).one()
                out[t] = (int(sayi), str(ozet))
            return out
    finally:
        sahip.dispose()


def test_oneri_hesaplama_hicbir_tabloyu_degistirmez(
    db: Db, engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    kisiler = {rol: make_user(rol) for rol in ROLLER}
    ekranlar = [olumlu(tohum, _simdi()) for _, olumlu, _ in VAKALAR.values()]
    once = _tablo_ozeti(db)
    for e in ekranlar:
        for kisi in kisiler.values():
            with contextlib.suppress(oneri.EkranBulunamadi, oneri.VarlikBulunamadi):
                _hesapla(engine, kisi, e)
    sonra = _tablo_ozeti(db)
    assert once == sonra  # ai_call, tool_call, job, asistan_* dahil: modelsiz ve salt okuma
