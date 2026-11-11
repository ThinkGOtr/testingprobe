"""Asistan rol politikası (spec 013 §4; K3, K6, K9, K10).

DB gerekmez: araç seti sahte ürün/kod/veri nesneleriyle kurulur.
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from tp_core.features.assistant import flow, rol_politikasi
from tp_core.features.assistant.paket import secilir_mi
from tp_core.features.assistant.rol_politikasi import (
    POLITIKA_ROLLERI,
    RolPolitikasiHatasi,
    etiket,
    izinli_araclar,
    politika_coz,
    politika_rolu,
    rol_eki,
)
from tp_core.features.assistant.tools import (
    ARAC_ADLARI,
    AracBaglami,
    AracHatasi,
    AracSonucu,
    arac_seti,
    izinli_arac_adlari,
    musteri_verisi_kurulumu,
)
from tp_core.gateway import wrap_tool_result
from tp_core.gateway.config import find_rules_dir
from tp_core.gateway.core import ASSISTANT_TOOLS
from tp_core.gateway.masking import PiiMasker

POLITIKA_YOLU = find_rules_dir() / "assistant" / "rol-politikasi.yaml"
TUM = frozenset(ARAC_ADLARI)
PO_ARACLARI = frozenset(
    {
        "product_search",
        "product_read",
        "probe_get",
        "probe_list",
        "probe_jobs",
        "probe_audit",
        "probe_my_queue",
        "jira_issue",
    }
)
SISTEM_ARACLARI = PO_ARACLARI - {"jira_issue"}
DAR_ARACLAR = frozenset({"product_search", "product_read", "probe_get", "probe_list"})
VERI = frozenset({"db_schema", "db_query"})

# §4 tablosu birebir.
BEKLENEN: dict[str, frozenset[str]] = {
    "analist": TUM,
    "testci": TUM,
    "automation_engineer": TUM,
    "developer": TUM,
    "sunucu": TUM,
    "po": PO_ARACLARI,
    "denetci": PO_ARACLARI,
    "sistem_yoneticisi": SISTEM_ARACLARI,
    "erisim_yoneticisi": DAR_ARACLAR,
    "goruntuleyici": DAR_ARACLAR,
}


def _ham() -> dict[str, Any]:
    veri = yaml.safe_load(POLITIKA_YOLU.read_text(encoding="utf-8"))
    assert isinstance(veri, dict)
    return veri


# ------------------------------------------------------------------ dosya ve yükleyici


def test_dosya_gecerli_ve_dokuz_rol_artı_sunucu() -> None:
    p = politika_coz(_ham())
    assert p.surum == 1
    assert set(POLITIKA_ROLLERI) <= set(p.roller)
    assert set(p.roller) == set(POLITIKA_ROLLERI) | {"sunucu"}
    assert dict(p.esleme) == {
        "analyst": "analist",
        "po": "po",
        "tester": "testci",
        "engineer": "automation_engineer",
        "presenter": "sunucu",
    }


@pytest.mark.parametrize(("rol", "araclar"), sorted(BEKLENEN.items()))
def test_politika_rolunun_arac_kumesi(rol: str, araclar: frozenset[str]) -> None:
    assert izinli_araclar(rol) == araclar
    assert araclar <= ASSISTANT_TOOLS


@pytest.mark.parametrize(
    ("portal", "politika"),
    [
        ("analyst", "analist"),
        ("po", "po"),
        ("tester", "testci"),
        ("engineer", "automation_engineer"),
        ("presenter", "sunucu"),
        ("bilinmeyen", "goruntuleyici"),
        ("", "goruntuleyici"),
        ("ANALYST", "goruntuleyici"),
        ("admin", "goruntuleyici"),
        # 012 geçişi: politika rolü doğrudan verilebilir.
        ("denetci", "denetci"),
        ("developer", "developer"),
        ("sistem_yoneticisi", "sistem_yoneticisi"),
    ],
)
def test_portal_rol_eslemesi(portal: str, politika: str) -> None:
    assert politika_rolu(portal) == politika
    assert izinli_araclar(portal) == BEKLENEN[politika]


def test_bilinmeyen_rol_en_dar_ve_none() -> None:
    assert politika_rolu(None) == "goruntuleyici"
    assert izinli_araclar("x") == DAR_ARACLAR
    assert not izinli_araclar("x") & VERI


def test_etiket_ve_ek() -> None:
    assert etiket("analyst") == "Analist"
    assert etiket("po") == "Ürün sahibi (PO)"
    assert etiket("tester") == "Testçi"
    assert etiket("presenter") == "Sunucu (sunum yapan)"
    assert etiket("bilinmeyen") == "Görüntüleyici"
    p = politika_coz(_ham())
    for kural in p.roller.values():
        assert kural.etiket and kural.ek
        assert len(kural.ek) <= 400, kural.ad
    assert "<PO belirleyecek>" in rol_eki("analyst")
    assert "Yayın önizleme" in rol_eki("tester")
    assert "role+name > label > data-testid > CSS/XPath" in rol_eki("engineer")
    assert rol_eki("engineer") == rol_eki("developer")
    assert "Jira" in rol_eki("po")


def _bozuk(degistir: Any) -> dict[str, Any]:
    veri = copy.deepcopy(_ham())
    degistir(veri)
    return veri


@pytest.mark.parametrize(
    ("degistir", "mesaj"),
    [
        (lambda v: v.update(fazla=1), "üst anahtar"),
        (lambda v: v.pop("esleme"), "üst anahtar"),
        (lambda v: v.update(surum=2), "surum"),
        (lambda v: v.update(surum=True), "surum"),
        (lambda v: v["roller"]["po"]["araclar"].append("shell_exec"), "bilinmeyen araç"),
        (lambda v: v["roller"]["po"]["araclar"].append("jira_issue"), "yinelenen"),
        (lambda v: v["roller"]["po"].update(araclar=[]), "araclar"),
        (lambda v: v["roller"]["po"].update(araclar="hepsi"), "araclar"),
        (lambda v: v["roller"]["po"].update(gizli=True), "anahtarları"),
        (lambda v: v["roller"]["po"].pop("etiket"), "anahtarları"),
        (lambda v: v["roller"]["po"].update(ek="x" * 600), "aşıyor"),
        (lambda v: v["roller"].pop("denetci"), "eksik"),
        (lambda v: v["esleme"].update(yeni="yok_rol"), "tanımsız"),
        (lambda v: v.update(roller=[]), "roller"),
    ],
)
def test_bozuk_politika_yuklemede_hata(degistir: Any, mesaj: str) -> None:
    with pytest.raises(RolPolitikasiHatasi, match=mesaj):
        politika_coz(_bozuk(degistir))


def test_dosya_yoksa_hata(tmp_path: Path) -> None:
    (tmp_path / "assistant").mkdir()
    with pytest.raises(RolPolitikasiHatasi, match="okunamadı"):
        rol_politikasi.politika_yukle(tmp_path)


def test_yukleme_onbellekli() -> None:
    assert rol_politikasi.politika_yukle() is rol_politikasi.politika_yukle()


def test_sinyal_ve_istem_izi_bilgi_paketine_girmez() -> None:
    assert secilir_mi("rules/assistant/rol-politikasi.yaml")
    assert not secilir_mi("rules/assistant/sinyaller.yaml")
    assert not secilir_mi("rules/assistant/istem-izleri.yaml")


# ------------------------------------------------------------------ araç seti


class SahteKod:
    def search_code(self, _a: dict[str, Any]) -> str:
        return wrap_tool_result("search_code", "a.ts:1: x")

    def get_file_contents(self, _a: dict[str, Any]) -> str:
        return wrap_tool_result("get_file_contents", "a.ts")


class SahteVeri:
    def __init__(self) -> None:
        self.cagri: list[str] = []

    def db_schema(self, _a: dict[str, Any]) -> str:
        self.cagri.append("db_schema")
        return wrap_tool_result("db_schema", "bayi(ad text)")

    def db_query(self, _a: dict[str, Any]) -> str:
        self.cagri.append("db_query")
        return "query: SELECT 1\nresult_digest: x\n" + wrap_tool_result("db_query", "1")


def _baglam(rol: str) -> AracBaglami:
    return AracBaglami(
        kullanici_id=uuid.uuid4(),
        rol=rol,
        oturum=PiiMasker(enabled=False).new_session(),
        db=lambda: pytest.fail("bu testte DB kullanılmaz"),  # type: ignore[arg-type,return-value]
    )


def _set(rol: str, veri: SahteVeri | None = None, cagrilan: list[str] | None = None, **kw: Any):
    def sahte(ad: str):
        def arac(_b: AracBaglami, **_arg: Any) -> AracSonucu:
            if cagrilan is not None:
                cagrilan.append(ad)
            return AracSonucu(f"{ad} sonucu")

        return arac

    kw.setdefault("musteri_verisi", False)
    kw.setdefault("veri_rol_listesi", None)
    return arac_seti(
        _baglam(rol),
        urun=object(),
        kod=SahteKod(),
        veri=veri or SahteVeri(),
        yeni_araclar={ad: sahte(ad) for ad in ("jira_issue", "ci_log", "probe_jobs")},
        **kw,
    )


@pytest.fixture(autouse=True)
def _temiz_ortam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_ASISTAN_VERI_ROLLERI", raising=False)
    monkeypatch.delenv("TP_ASISTAN_MUSTERI_VERISI", raising=False)


@pytest.mark.parametrize(
    ("rol", "politika"),
    [
        ("analyst", "analist"),
        ("po", "po"),
        ("tester", "testci"),
        ("engineer", "automation_engineer"),
        ("presenter", "sunucu"),
        ("bilinmeyen", "goruntuleyici"),
        *[(r, r) for r in POLITIKA_ROLLERI],
    ],
)
def test_specs_rolun_izinli_araclarina_suzulur(rol: str, politika: str) -> None:
    s = _set(rol)
    assert s.adlar == BEKLENEN[politika]
    # Sıra korunur (ARAC_ADLARI sırası).
    assert [x.name for x in s.specs] == [a for a in ARAC_ADLARI if a in BEKLENEN[politika]]
    # Yürütücü 13 adı tanır (sağlamlık denetimi), izinsizleri reddeder.
    assert s.execute.adlar == TUM


@pytest.mark.parametrize("ad", ["search_code", "get_file_contents", "db_query", "ci_log"])
def test_yurutucu_izinsiz_cagriyi_reddeder_alttaki_arac_calismaz(ad: str) -> None:
    veri = SahteVeri()
    cagrilan: list[str] = []
    s = _set("po", veri=veri, cagrilan=cagrilan)
    with pytest.raises(AracHatasi, match=rf"^{ad} rolünüze açık değil$"):
        s.execute(ad, {"query": "x", "sql": "SELECT 1", "path": "a.ts"})
    assert veri.cagri == [] and cagrilan == []
    assert len(s.havuz) == 0
    # İzinli araç aynı sette çalışır (iş düşmez).
    assert s.execute("jira_issue", {"anahtar": "TPD-3"}).startswith("[kanit:k1]")


def test_goruntuleyici_probe_jobs_reddedilir() -> None:
    cagrilan: list[str] = []
    s = _set("bilinmeyen", cagrilan=cagrilan)
    with pytest.raises(AracHatasi, match="probe_jobs rolünüze açık değil"):
        s.execute("probe_jobs", {})
    assert cagrilan == []


def test_tam_rol_veri_araclarini_calistirir() -> None:
    veri = SahteVeri()
    s = _set("engineer", veri=veri)
    assert s.execute("db_schema", {}).startswith("[kanit:k1]")
    assert veri.cagri == ["db_schema"]


# ------------------------------------------------------------------ VERI_ROLLERI ve K6


@pytest.mark.parametrize(
    ("liste", "rol", "acik"),
    [
        (frozenset({"analyst"}), "analyst", True),
        (frozenset({"analist"}), "analyst", True),  # politika adıyla
        (frozenset({"analyst"}), "tester", False),
        (frozenset({"testci", "developer"}), "tester", True),
        (frozenset({"developer"}), "developer", True),
        (frozenset({"engineer"}), "automation_engineer", False),
        (frozenset(), "analyst", False),  # açık boş küme → herkese kapalı
        # Ek daraltma politikayı genişletemez.
        (frozenset({"po", "goruntuleyici"}), "po", False),
        (frozenset({"goruntuleyici"}), "bilinmeyen", False),
    ],
)
def test_veri_rolleri_ek_daraltma(liste: frozenset[str], rol: str, acik: bool) -> None:
    izinli = izinli_arac_adlari(rol, veri_rol_listesi=liste)
    assert (izinli >= VERI) is acik
    assert not (VERI & izinli) if not acik else True
    s = _set(rol, veri_rol_listesi=liste)
    assert (s.adlar >= VERI) is acik


def test_veri_rolleri_ortamdan_portal_ya_da_politika_adi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_ASISTAN_VERI_ROLLERI", "analist, engineer")
    s = {
        r: arac_seti(_baglam(r), urun=object(), kod=SahteKod(), veri=SahteVeri())
        for r in ("analyst", "engineer", "tester")
    }
    assert s["analyst"].adlar >= VERI
    assert s["engineer"].adlar >= VERI
    assert not VERI & s["tester"].adlar
    with pytest.raises(AracHatasi, match="db_query rolünüze açık değil"):
        s["tester"].execute("db_query", {"sql": "SELECT 1"})


def test_musteri_verisi_varsayilan_kapali() -> None:
    assert musteri_verisi_kurulumu({}) is False
    assert musteri_verisi_kurulumu({"TP_ASISTAN_MUSTERI_VERISI": "1"}) is True
    assert musteri_verisi_kurulumu({"TP_ASISTAN_MUSTERI_VERISI": "0"}) is False


def test_k6_musteri_verisinde_veri_rolleri_bossa_db_hic_kimseye(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TP_ASISTAN_MUSTERI_VERISI", "1")
    for rol in ("analyst", "engineer", "tester", "presenter", "developer"):
        veri = SahteVeri()
        s = arac_seti(_baglam(rol), urun=object(), kod=SahteKod(), veri=veri)
        assert not VERI & s.adlar, rol
        assert {"search_code", "get_file_contents"} <= s.adlar
        with pytest.raises(AracHatasi, match="rolünüze açık değil"):
            s.execute("db_schema", {})
        assert veri.cagri == []
    # Müşteri verisinde liste verilirse listedeki roller açılır.
    monkeypatch.setenv("TP_ASISTAN_VERI_ROLLERI", "engineer")
    s = arac_seti(_baglam("engineer"), urun=object(), kod=SahteKod(), veri=SahteVeri())
    assert s.adlar >= VERI
    s = arac_seti(_baglam("analyst"), urun=object(), kod=SahteKod(), veri=SahteVeri())
    assert not VERI & s.adlar


def test_musteri_verisi_degilken_db_politikaya_bagli() -> None:
    assert _set("analyst").adlar >= VERI
    assert not VERI & _set("po").adlar


# ------------------------------------------------------------------ prompt rol satırı


def _mesaj(rol: str) -> flow.Mesaj:
    return flow.Mesaj(
        id=uuid.uuid4(),
        sohbet_id=uuid.uuid4(),
        kullanici_id=uuid.uuid4(),
        kullanici_adi="k",
        rol=rol,
        sira=1,
        icerik="Bu ekran ne yapar?",
        baglam=None,
        kip="soru",
        tetik="kullanici",
        amac=None,
        ust_mesaj_id=None,
        job_id=None,
        oneri_kural_id=None,
    )


@pytest.mark.parametrize(
    ("rol", "beklenen"),
    [
        ("analyst", "Analist"),
        ("po", "Ürün sahibi (PO)"),
        ("tester", "Testçi"),
        ("engineer", "Otomasyon mühendisi"),
        ("presenter", "Sunucu (sunum yapan)"),
        ("bilinmeyen", "Görüntüleyici"),
    ],
)
def test_ilk_mesaj_rol_satiri_ve_ek(rol: str, beklenen: str) -> None:
    [msg] = flow.ilk_mesaj(_mesaj(rol), ekran=None, kural_onerileri=None, gecmis=None)
    icerik = str(msg.content)
    satirlar = icerik.split("\n\n")
    assert satirlar[0] == f"Kullanıcının rolü: {beklenen}"
    assert satirlar[1] == f"Rol uzantısı: {rol_eki(rol)}"
    assert satirlar[2] == "kip=soru"
    # Rol eki sunucu metnidir: güvenilmeyen blok içinde değildir.
    assert "<untrusted" not in satirlar[1]
    assert icerik.endswith("Soru: Bu ekran ne yapar?")


# ------------------------------------------------------------------ şablon dalı (entegrasyon)


def test_sablon_rolun_izinli_olmayan_aracini_cagirmaz() -> None:
    """Şablon cevapları aracı doğrudan çağırır; politika dışı araçta şablon atlanır."""
    import uuid

    from tp_core.features.assistant.maskeleme import mesaj_oturumu
    from tp_core.features.assistant.sablon import sablon_cevabi
    from tp_core.features.assistant.tools import arac_baglami
    from tp_core.gateway.masking import PiiMasker

    def db_yok():  # araç çağrılırsa test düşer
        raise AssertionError("şablon politika dışı aracı çağırdı")

    for rol in ("erisim_yoneticisi", "goruntuleyici"):
        b = arac_baglami(
            uuid.uuid4(),
            rol,
            mesaj_oturumu(PiiMasker(enabled=False)),
            db=db_yok,
            sir_degerleri=(),
        )
        assert sablon_cevabi(b, "Bugün ne yapmalıyım?") is None
