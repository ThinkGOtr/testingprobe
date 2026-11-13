"""Öneri motoru — veritabanısız birimler (AI-ASISTAN-PLANI §17.2–17.4, §13 "Öneri" ve "Güvenlik").

Kural yükleyici (kapalı küme, bozuk dosya reddi), koşul değerlendirici, güvenli yer tutucu
doldurma, "Jira'yı aç" bağlantısı (`JIRA_CREATE_URL` doğrulaması), rota indirgeme, kapsam matrisi,
rol hizalama ve önbellek.
"""

from __future__ import annotations

import copy
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.gateway.demo_sources import RULES
from tp_core.features.assistant import oneri
from tp_core.features.assistant.oneri import (
    Ekran,
    JiraBaglantisi,
    Kosul,
    KuralHatasi,
    create_url_dogrula,
    kosul_saglanir,
    yer_doldur,
)
from tp_core.workflow.service import Principal

ROLLER = oneri.ROLLER


def _ks() -> oneri.KuralSeti:
    return oneri.kural_seti()


def _kisi(rol: str) -> Principal:
    return Principal(uuid.uuid4(), f"{rol}_x", rol)


# ------------------------------------------------------------------ yükleyici


def test_kural_seti_yuklenir_ve_28_kural() -> None:
    ks = _ks()
    # §17.3'ün 26 kuralı + 011 `script-dogrulanmamis` + 012 `case-son-onay-bekliyor`.
    assert len(ks.kurallar) == 28
    assert len({k.id for k in ks.kurallar}) == 28
    assert set(ks.taslaklar) == {
        "po-hatirlatma",
        "ac-eksik",
        "flaky-task",
        "ortam-hatasi-task",
        "test-verisi-task",
    }
    # Her kuralın yer tutucuları yalnız kendi varlığında hesaplanan olgulardan.
    for k in ks.kurallar:
        for metin in (k.baslik, k.neden, k.aciklama):
            assert set(oneri._YER_TUTUCU.findall(metin)) <= k.yer_tutucular, k.id


def test_olgu_sozlesmesi_kod_ve_kural_dosyasi_ayni() -> None:
    """`oneriler.yaml` olgu listesi = hesaplanan olgular; her varlık kapsamı kodda hesaplanır."""
    ks = _ks()
    assert set(ks.olgular) == set(oneri.OLGU_HESAPLAYICILARI)
    for ad, o in ks.olgular.items():
        assert set(o["varliklar"]) <= oneri.OLGU_HESAPLAYICILARI[ad], ad
        assert set(o.get("turevler") or {}) <= set(oneri.TUREVLER), ad
        if o.get("yer_tutucu"):
            assert o["tur"] not in oneri.SERBEST_METIN_TURLERI, ad


def _bozuk_dizin(
    tmp_path: Path, degistir: Callable[[dict[str, Any], dict[str, Any]], None]
) -> Path:
    hedef = tmp_path / "assistant"
    shutil.copytree(RULES / "assistant", hedef)
    kural = yaml.safe_load((hedef / "oneriler.yaml").read_text(encoding="utf-8"))
    taslak = yaml.safe_load((hedef / "jira-taslaklari.yaml").read_text(encoding="utf-8"))
    degistir(kural, taslak)
    (hedef / "oneriler.yaml").write_text(yaml.safe_dump(kural, allow_unicode=True), "utf-8")
    (hedef / "jira-taslaklari.yaml").write_text(yaml.safe_dump(taslak, allow_unicode=True), "utf-8")
    return hedef


def _kural(doc: dict[str, Any], kid: str) -> dict[str, Any]:
    return next(k for k in doc["kurallar"] if k["id"] == kid)


def _taslak(doc: dict[str, Any], tid: str) -> dict[str, Any]:
    return next(t for t in doc["taslaklar"] if t["id"] == tid)


@pytest.mark.parametrize(
    ("degistir", "beklenen"),
    [
        (
            lambda k, t: _kural(k, "hata-flaky-task")["kosul"].update(flaky_tekrar_gt=3),
            "bilinmeyen operatör flaky_tekrar_gt",
        ),
        (
            lambda k, t: _kural(k, "hata-flaky-task")["kosul"].update(ifade="flaky_tekrar > 3"),
            "bilinmeyen operatör ifade",
        ),
        (
            lambda k, t: _kural(k, "gereksinim-basarisiz").update(baslik="{baslik} başarısız"),
            "geçersiz yer tutucu {baslik}",
        ),
        (
            lambda k, t: _kural(k, "kosu-ortam-hatasi-bilgi").update(
                baslik="{basarisiz_adimlar} düştü"
            ),
            "geçersiz yer tutucu {basarisiz_adimlar}",
        ),
        (
            lambda k, t: k["olgular"]["basarisiz_adimlar"].update(yer_tutucu=True),
            "serbest metin/kimlik olgusu yer tutucu olamaz",
        ),
        (
            lambda k, t: k["olgular"].update(hata_mesaji={"tur": "enum", "varliklar": ["failure"]}),
            "hesaplanmayan olgu tanımı",
        ),
        (
            lambda k, t: _kural(k, "hata-flaky-task")["eylem"].update(sablon="yok-boyle"),
            "bilinmeyen şablon yok-boyle",
        ),
        (
            lambda k, t: _kural(k, "guncel-kosu-yok")["eylem"].update(rota="/ayarlar"),
            "eylem rotası /ayarlar",
        ),
        (
            lambda k, t: _kural(k, "gereksinim-po-hatirlatma-jira")["kosul"].pop("jira_key_var"),
            "jira_yorum bilinen anahtar ister",
        ),
        (
            lambda k, t: _kural(k, "gereksinim-basarisiz")["kosul"].update(flaky_tekrar_gte=1),
            "flaky_tekrar olgusu requirement için hesaplanmaz",
        ),
        (
            lambda k, t: _taslak(t, "flaky-task").update(aciklama="{po_bekleme_gun} gün"),
            "geçersiz yer tutucu {po_bekleme_gun}",
        ),
        (
            lambda k, t: _kural(k, "gereksinim-basarisiz").update(baslik="{{jira_key}}"),
            "biçimsiz süslü parantez",
        ),
    ],
)
def test_yukleyici_bozuk_kurali_reddeder(
    tmp_path: Path, degistir: Callable[..., None], beklenen: str
) -> None:
    with pytest.raises(KuralHatasi) as exc:
        oneri.kural_seti_yukle(_bozuk_dizin(tmp_path, degistir))
    assert beklenen in str(exc.value)


# ------------------------------------------------------------------ koşul


@pytest.mark.parametrize(
    ("kosullar", "olgu", "beklenen"),
    [
        ([Kosul("durum", "_in", ("pending_po",))], {"durum": "pending_po"}, True),
        ([Kosul("durum", "_in", ("pending_po",))], {"durum": "new"}, False),
        ([Kosul("durum", "_in", ("pending_po",))], {}, False),
        ([Kosul("ac_eksik", "_esit", True)], {"ac_eksik": True}, True),
        # bool ile sayı karışmaz (Python'da True == 1).
        ([Kosul("ac_eksik", "_esit", True)], {"ac_eksik": 1}, False),
        ([Kosul("inceleme_bekleyen_case", "_esit", 0)], {"inceleme_bekleyen_case": False}, False),
        ([Kosul("inceleme_bekleyen_case", "_esit", 0)], {"inceleme_bekleyen_case": 0}, True),
        ([Kosul("flaky_tekrar", "_gte", 3)], {"flaky_tekrar": 3}, True),
        ([Kosul("flaky_tekrar", "_gte", 3)], {"flaky_tekrar": 2}, False),
        ([Kosul("flaky_tekrar", "_gte", 3)], {"flaky_tekrar": "9"}, False),
        ([Kosul("flaky_tekrar", "_lte", 0)], {"flaky_tekrar": True}, False),
        ([Kosul("butce_orani", "_gte", 0.8)], {"butce_orani": 0.8}, True),
        ([Kosul("jira_key", "_var", True)], {"jira_key": "TPD-3"}, True),
        ([Kosul("jira_key", "_var", True)], {"jira_key": ""}, False),
        ([Kosul("jira_key", "_yok", True)], {}, True),
        ([Kosul("basarisiz_adimlar", "_var", True)], {"basarisiz_adimlar": []}, False),
        ([Kosul("bulgu_kaynakli", "_var", True)], {"bulgu_kaynakli": False}, False),
        # VE: biri tutmazsa kural eşleşmez.
        (
            [Kosul("durum", "_in", ("pending_po",)), Kosul("po_bekleme_saat", "_gte", 24)],
            {"durum": "pending_po"},
            False,
        ),
    ],
)
def test_kosul_degerlendirici(kosullar: list[Kosul], olgu: dict[str, Any], beklenen: bool) -> None:
    assert kosul_saglanir(kosullar, olgu) is beklenen


# ------------------------------------------------------------------ metin


def test_yer_doldur_tek_gecisli_degerdeki_suslu_parantez_acilmaz() -> None:
    degerler = {"jira_key": "{po_bekleme_gun}", "po_bekleme_gun": "3"}
    assert yer_doldur("{jira_key} / {po_bekleme_gun}", degerler) == "{po_bekleme_gun} / 3"
    # Bilinmeyen/eksik ad boş metin; str.format biçim dili ve öznitelik erişimi yok.
    assert yer_doldur("a{yok}b", {}) == "ab"
    assert yer_doldur("{jira_key.__class__} {0}", degerler) == "{jira_key.__class__} {0}"


def test_yer_degerleri_yalniz_sayi_ve_anahtar_tasir() -> None:
    izinli = {"jira_key", "po_bekleme_gun", "butce_yuzde", "flaky_tekrar"}
    olgu = {
        "jira_key": "TPD-3",
        "po_bekleme_saat": 30,
        "butce_orani": 0.854,
        "flaky_tekrar": 3,
    }
    assert oneri.yer_degerleri(olgu, izinli) == {
        "jira_key": "TPD-3",
        "po_bekleme_gun": "1",
        "butce_yuzde": "85",
        "flaky_tekrar": "3",
    }
    # Anahtar biçimine uymayan metin (serbest metin) değere giremez.
    assert oneri.yer_degerleri({"jira_key": "<b>x</b> {y}"}, {"jira_key"}) == {"jira_key": ""}
    assert oneri.yer_degerleri({"po_bekleme_saat": 49}, {"po_bekleme_gun"}) == {
        "po_bekleme_gun": "2"
    }


# ------------------------------------------------------------------ Jira bağlantısı


@pytest.mark.parametrize(
    ("deger", "gezinme", "simulator", "beklenen"),
    [
        (None, "https://x.atlassian.net", False, None),
        (
            "https://x.atlassian.net/secure/CreateIssue.jspa?pid=1",
            "https://x.atlassian.net",
            False,
            "https://x.atlassian.net/secure/CreateIssue.jspa?pid=1",
        ),
        ("https://kotu.example/create", "https://x.atlassian.net", False, None),  # farklı köken
        ("https://x.atlassian.net:8443/c", "https://x.atlassian.net", False, None),  # port farklı
        ("http://x.atlassian.net/c", "http://x.atlassian.net", False, None),  # https değil
        ("javascript:alert(1)", "https://x.atlassian.net", False, None),
        ("https://kul:parola@x.atlassian.net/c", "https://x.atlassian.net", False, None),
        ("https://x.atlassian.net/c", None, False, None),  # gezinme kökü yok
        (
            "http://127.0.0.1:8090/olustur",
            "http://127.0.0.1:8090",
            True,
            "http://127.0.0.1:8090/olustur",
        ),
        ("http://127.0.0.1:8090/olustur", "http://127.0.0.1:8090", False, None),
        ("http://jira-sim:8090/olustur", "http://jira-sim:8090", True, None),
    ],
)
def test_create_url_dogrulamasi(
    deger: str | None, gezinme: str | None, simulator: bool, beklenen: str | None
) -> None:
    assert create_url_dogrula(deger, gezinme, simulator) == beklenen


def test_create_url_reddi_uyari_yazar_ama_degeri_yazmaz(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        assert create_url_dogrula("https://kotu.example/gizli-yol", "https://a.b", False) is None
    assert "JIRA_CREATE_URL yok sayıldı" in caplog.text
    assert "gizli-yol" not in caplog.text


def test_jira_baglantisi_ayarlardan(monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.integrations.jira import get_jira_settings

    def kur(**env: str) -> JiraBaglantisi:
        for ad in ("JIRA_BASE_URL", "JIRA_BROWSE_URL", "JIRA_CREATE_URL", "JIRA_PROJECT"):
            monkeypatch.delenv(ad, raising=False)
        for ad, v in env.items():
            monkeypatch.setenv(ad, v)
        get_jira_settings.cache_clear()
        oneri.jira_baglantisi.cache_clear()
        return oneri.jira_baglantisi()

    try:
        # Simülatör, JIRA_BROWSE_URL yok: tarayıcıdan açılmayan iç adres → bağlantı yok.
        b = kur()
        assert b.simulator and b.kayit_adresi("TPD-3") is None and b.yeni_kayit_adresi() is None
        # Simülatör + gezinme adresi: kayıt bağlantısı var, yeni kayıt sayfası yok.
        b = kur(JIRA_BROWSE_URL="http://127.0.0.1:8090/")
        assert b.kayit_adresi("TPD-3") == "http://127.0.0.1:8090/browse/TPD-3"
        assert b.yeni_kayit_adresi() is None
        # Gerçek Jira: taban adres gezinme kökü; yeni kayıt CreateIssue sayfası.
        b = kur(JIRA_BASE_URL="https://ornek.atlassian.net", JIRA_PROJECT="ABC")
        assert not b.simulator and b.proje == "ABC"
        assert b.kayit_adresi("ABC-1") == "https://ornek.atlassian.net/browse/ABC-1"
        assert b.yeni_kayit_adresi() == (
            "https://ornek.atlassian.net/secure/CreateIssue!default.jspa"
        )
        # Gezinme kökü de şema/kullanıcı bilgisiyle doğrulanır: http(s) dışı ya da kimlikli
        # adres bağlantı üretmez (portala `javascript:` href'i gitmez).
        for kotu_kok in ("javascript:alert(1)//x", "data:text/html,x", "https://u:p@ornek.net"):
            k = kur(JIRA_BROWSE_URL=kotu_kok, JIRA_BASE_URL="https://ornek.atlassian.net")
            assert k.kayit_adresi("ABC-1") is None and k.yeni_kayit_adresi() is None, kotu_kok
        b = kur(JIRA_BASE_URL="https://ornek.atlassian.net", JIRA_PROJECT="ABC")
        # Bilinmeyen/biçimsiz anahtar → bağlantı yok (Jira anahtar atlatma).
        for kotu in ("tpd-3", "TPD-3/../x", "TPD-3?expand=x", "TPD-٣", "", None):
            assert b.kayit_adresi(kotu) is None, kotu
        # Geçerli JIRA_CREATE_URL kullanılır; farklı kökenli olan yok sayılır.
        b = kur(
            JIRA_BASE_URL="https://ornek.atlassian.net",
            JIRA_CREATE_URL="https://ornek.atlassian.net/secure/CreateIssue.jspa?pid=10000",
        )
        assert b.yeni_kayit_adresi() == (
            "https://ornek.atlassian.net/secure/CreateIssue.jspa?pid=10000"
        )
        b = kur(
            JIRA_BASE_URL="https://ornek.atlassian.net",
            JIRA_CREATE_URL="https://evil.example/secure/CreateIssue.jspa",
        )
        assert b.yeni_kayit_adresi() == (
            "https://ornek.atlassian.net/secure/CreateIssue!default.jspa"
        )
    finally:
        monkeypatch.undo()
        get_jira_settings.cache_clear()
        oneri.jira_baglantisi.cache_clear()


def _kural_ks(kid: str) -> oneri.Kural:
    k = _ks().kural(kid)
    assert k is not None
    return k


def _ekran(kalip: str, varlik: str | None = None) -> Ekran:
    r = _ks().rota(kalip)
    assert r is not None
    return Ekran(r, varlik, uuid.uuid4() if varlik else None)


SIM = JiraBaglantisi(proje="TPD", gezinme_koku=None, olusturma_adresi=None, simulator=True)
GERCEK = JiraBaglantisi(
    proje="ABC",
    gezinme_koku="https://ornek.atlassian.net",
    olusturma_adresi=None,
    simulator=False,
)


def test_jira_taslak_karti_simulatorde_baglantisiz_ve_metin_url_icermez() -> None:
    k = _kural_ks("hata-flaky-task")
    kart = oneri.kart_kur(
        k, _ekran("/hatalar/:id", "failure"), {"flaky_tekrar": 4}, kurallar=_ks(), jira=SIM
    )
    assert kart is not None
    e = kart["eylem"]
    assert e["tur"] == "jira_taslak" and "baglanti" not in e
    assert e["baglanti_yok_nedeni"] == oneri.SIM_BAGLANTI_YOK
    assert e["taslak"]["proje"] == "TPD" and e["taslak"]["tur"] == "Task"
    assert "4 kez" in e["taslak"]["aciklama"] and "4 kez" in kart["baslik"]
    assert e["adim_notu"] == "Proje: TPD, Tür: Task seçin; metni yapıştırın."
    assert e["not"] == oneri.UYARI_NOTU
    assert "http" not in str(e["taslak"])

    kart = oneri.kart_kur(
        k, _ekran("/hatalar/:id", "failure"), {"flaky_tekrar": 4}, kurallar=_ks(), jira=GERCEK
    )
    assert kart is not None
    assert kart["eylem"]["baglanti"].endswith("/secure/CreateIssue!default.jspa")
    assert "http" not in str(kart["eylem"]["taslak"])  # taslak metni URL'e konmaz


def test_jira_yorum_karti_kayit_baglantisi_ve_eksik_olgu_bos() -> None:
    k = _kural_ks("gereksinim-po-hatirlatma-jira")
    ekran = _ekran("/gereksinimler/:id", "requirement")
    kart = oneri.kart_kur(k, ekran, {"jira_key": "ABC-7"}, kurallar=_ks(), jira=GERCEK)
    assert kart is not None
    e = kart["eylem"]
    assert e["tur"] == "jira_yorum" and e["anahtar"] == "ABC-7"
    assert e["baglanti"] == "https://ornek.atlassian.net/browse/ABC-7"
    assert e["taslak"]["tur"] == "yorum" and e["taslak"]["ozet"] == ""
    # po_bekleme_saat olgusu yok → türev boş metin (şablonda eksik alan boş kalır).
    assert "ABC-7 kaydının PO onayı  gündür" in e["taslak"]["aciklama"]
    # Anahtar yoksa jira_yorum kartı kurulmaz.
    assert oneri.kart_kur(k, ekran, {}, kurallar=_ks(), jira=GERCEK) is None


def test_rota_karti_kimligi_doldurur_ve_kimlik_olgusu_yoksa_kurulmaz() -> None:
    ks = _ks()
    ekran = _ekran("/gereksinimler/:id", "requirement")
    kart = oneri.kart_kur(
        _kural_ks("gereksinim-bulgu-karari"), ekran, {"acik_bulgu_sayisi": 2}, kurallar=ks, jira=SIM
    )
    assert kart is not None
    assert kart["eylem"] == {
        "tur": "rota",
        "rota": f"/gereksinimler/{ekran.varlik_id}",
        "capa": "bulgular",
    }
    assert kart["baslik"] == "2 tutarlılık bulgusu kararınızı bekliyor"
    k = _kural_ks("hata-bug-taslagi-karari")
    hata = _ekran("/hatalar/:id", "failure")
    taslak = str(uuid.uuid4())
    kart = oneri.kart_kur(k, hata, {"bug_taslagi_id": taslak}, kurallar=ks, jira=SIM)
    assert kart is not None and kart["eylem"]["rota"] == f"/bug-taslaklari/{taslak}"
    assert oneri.kart_kur(k, hata, {}, kurallar=ks, jira=SIM) is None


# ------------------------------------------------------------------ rota ve ekran


@pytest.mark.parametrize(
    ("rota", "kalip", "yol_id"),
    [
        ("/gereksinimler/:id", "/gereksinimler/:id", None),
        ("/gereksinimler/abc", "/gereksinimler/:id", "abc"),
        ("/gereksinimler/abc/caseler?x=1#y", "/gereksinimler/:id/caseler", "abc"),
        ("/kosular/", "/kosular", None),
        ("/", "/", None),
    ],
)
def test_rota_indirgeme(rota: str, kalip: str, yol_id: str | None) -> None:
    r, i = oneri.rota_indirge(rota)
    assert (r.kalip, i) == (kalip, yol_id)


@pytest.mark.parametrize("rota", ["", "gereksinimler", "/ayarlar", "/gereksinimler/a/b/c", "//x"])
def test_rota_disi_ekran_reddedilir(rota: str) -> None:
    with pytest.raises(oneri.EkranBulunamadi):
        oneri.rota_indirge(rota)


def test_ekran_coz_rol_ve_varlik_denetimi() -> None:
    vid = uuid.uuid4()
    e = oneri.ekran_coz(_kisi("analyst"), f"/gereksinimler/{vid}", None, None)
    assert (e.rota.kalip, e.varlik_tur, e.varlik_id) == ("/gereksinimler/:id", "requirement", vid)
    e = oneri.ekran_coz(_kisi("analyst"), "/gereksinimler/:id", "requirement", str(vid))
    assert e.varlik_id == vid
    # Varlıksız ekranda istemcinin varlık parametreleri yok sayılır.
    e = oneri.ekran_coz(_kisi("admin"), "/kosular", "run", str(vid))
    assert (e.varlik_tur, e.varlik_id) == (None, None)
    with pytest.raises(oneri.EkranBulunamadi):  # rolüne kapalı ekran
        oneri.ekran_coz(_kisi("po"), "/claude-code", None, None)
    with pytest.raises(oneri.VarlikBulunamadi):  # tür uyuşmazlığı
        oneri.ekran_coz(_kisi("analyst"), f"/gereksinimler/{vid}", "script", None)
    with pytest.raises(oneri.VarlikBulunamadi):  # yol ve parametre farklı varlık
        oneri.ekran_coz(_kisi("analyst"), f"/gereksinimler/{vid}", None, str(uuid.uuid4()))
    with pytest.raises(oneri.VarlikBulunamadi):  # kimliksiz varlık ekranı
        oneri.ekran_coz(_kisi("analyst"), "/gereksinimler/:id", None, None)
    with pytest.raises(oneri.VarlikBulunamadi):  # geçersiz kimlik
        oneri.ekran_coz(_kisi("analyst"), "/gereksinimler/TPD-3", None, None)


# ------------------------------------------------------------------ kapsam ve rol hizalama


def test_sayfa_rolleri_izin_katalogundan() -> None:
    """Uçsuz sayfaların rolleri portal sayfa izinleriyle aynı (specs/012-rol-yetki §4)."""
    from tp_core.auth.yetki import roller_icin

    rotalar = {r.kalip: r for r in _ks().rotalar}
    for kalip, izin_adi in (
        ("/claude-code", "claude_code.read"),
        ("/yol-haritasi", "demo.read"),
        ("/demo", "demo.manage"),
    ):
        acan = {rol for rol in ROLLER if rotalar[kalip].acabilir(rol)}
        assert acan == set(roller_icin(izin_adi)), kalip


def test_kapsam_matrisi_ekranda_kural_var_bilincli_bos_ile_tamamlanir() -> None:
    """Her (rota × rol): kural varsa düğme görünür, yoksa `bos_ekranlar`'da bilinçli kayıt var."""
    ks = _ks()
    for r in ks.rotalar:
        if r.kalip == "/giris":
            continue
        for rol in ROLLER:
            var = oneri.ekranda_kural_var(r.kalip, rol)
            bos = (r.kalip, rol) in ks.bos_ekranlar
            if not r.acabilir(rol):
                assert not var and not bos, (r.kalip, rol)
                continue
            assert var != bos, (r.kalip, rol, var, bos)


def test_rol_hizalama_rota_eylemi_ucun_require_role_ve_onay_rolleri_alt_kumesi() -> None:
    """Rota eylemli her kuralın rolleri, FastAPI ucundaki `require_role` ∩ `APPROVER_ROLES`'un alt
    kümesi; o uca yetkisi olmayan rol aynı ekranda yalnız `bilgi`/Jira kartı görür."""
    from tests.unit.gateway.test_rules_asistan import _uc_rolleri
    from tp_core.workflow.states import APPROVER_ROLES

    uclar = _uc_rolleri()
    assert uclar["POST /requirements/{req_id}/po-approve"] == {"po"}
    rota_kurallari = [k for k in _ks().kurallar if k.eylem_turu == "rota"]
    assert len(rota_kurallari) == 13
    for k in rota_kurallari:
        uc = k.eylem["yetki"]["uc"]
        assert uc in uclar, (k.id, uc)
        izinli = set(uclar[uc])
        if "onay_varligi" in k.eylem["yetki"]:
            izinli &= APPROVER_ROLES[k.eylem["yetki"]["onay_varligi"]]
        assert set(k.roller) <= izinli, (k.id, uc, sorted(izinli))
        # Ucu kullanamayan roller bu ekranda rota kartı almaz.
        for rol in set(ROLLER) - izinli:
            for diger in _ks().ekran_kurallari(k.ekran, rol):
                if diger.eylem_turu == "rota":
                    assert rol in uclar[diger.eylem["yetki"]["uc"]], (diger.id, rol)


# ------------------------------------------------------------------ önbellek ve bayrak


def test_onbellek_sure_dolunca_dusurur() -> None:
    saat = [100.0]
    ob = oneri.Onbellek(sure_s=10, saat=lambda: saat[0])
    ob.koy(("a",), {"x": 1})
    saat[0] = 109.9
    assert ob.al(("a",)) == {"x": 1}
    saat[0] = 110.0
    assert ob.al(("a",)) is None
    ob.koy(("b",), {})
    ob.temizle()
    assert ob.al(("b",)) is None


def test_onbellek_kullaniciya_ozel_temizlik() -> None:
    """`temizle(kullanici_id)` yalnız o kullanıcının kayıtlarını siler ("Gizle" kapsamı)."""
    ob = oneri.Onbellek(sure_s=10)
    ob.koy(("u1", "tester", "/a"), {"x": 1})
    ob.koy(("u1", "tester", "/b"), {"x": 2})
    ob.koy(("u2", "tester", "/a"), {"x": 3})
    ob.temizle("u1")
    assert ob.al(("u1", "tester", "/a")) is None and ob.al(("u1", "tester", "/b")) is None
    assert ob.al(("u2", "tester", "/a")) == {"x": 3}


def test_onbellek_portal_olay_yenilemesinden_kisa() -> None:
    """SSE olayından `olayGecikmeMs` sonra yapılan tek `zorla` yenilemesi önbellekten eski rozet
    almamalı: önbellek ömrü portal gecikmesinden kısa."""
    import re

    assert oneri.ONBELLEK.sure_s == oneri.ONBELLEK_SURE_S
    kaynak = (
        Path(__file__).resolve().parents[5] / "review-portal/src/components/asistan/OneriVerisi.ts"
    )
    if not kaynak.exists():
        pytest.skip("review-portal kaynağı yok")
    m = re.search(r"olayGecikmeMs:\s*(\d+)", kaynak.read_text(encoding="utf-8"))
    assert m is not None
    assert int(m.group(1)) > oneri.ONBELLEK_SURE_S * 1000


@pytest.mark.parametrize(("deger", "beklenen"), [("1", True), ("0", False), ("false", False)])
def test_oneri_bayragi(monkeypatch: pytest.MonkeyPatch, deger: str, beklenen: bool) -> None:
    monkeypatch.setenv("TP_ASISTAN_ONERI", deger)
    assert oneri.oneri_etkin() is beklenen


def test_varsayilan_bayrak_acik(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_ASISTAN_ONERI", raising=False)
    assert oneri.oneri_etkin()


def test_kural_seti_kopyasi_degistirilemez() -> None:
    """Kural nesneleri donmuş: istek sırasında yanlışlıkla değiştirilemez."""
    k = copy.copy(_kural_ks("butce-uyarisi"))
    with pytest.raises(AttributeError):
        k.oncelik = 1  # type: ignore[misc]
