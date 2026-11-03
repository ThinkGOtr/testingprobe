"""Ortak araç sarmalayıcısı, tek maskeleme oturumu ve kanıt havuzu (AI-ASISTAN-PLANI §5.0, §13).

DB gerekmez: yeni araçlar sahte, mevcut araçlar gerçek `DataTools` + sahte `DemoDb`.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest

from tp_core.features.assistant.maskeleme import maskeleyici, mesaj_oturumu
from tp_core.features.assistant.tools import (
    ARAC_ADLARI,
    AracBaglami,
    AracHatasi,
    AracSarmalayici,
    AracSonucu,
    arac_seti,
    tool_specs,
    veri_rolleri,
)
from tp_core.features.assistant.tools.base import KanitHavuzu, sir_temizle
from tp_core.features.requirements.datatools import DataTools, QueryResult
from tp_core.gateway import wrap_tool_result
from tp_core.gateway.core import ASSISTANT_TOOLS, FORBIDDEN_TOOLS
from tp_core.gateway.masking import PiiMasker

# Repo public: gerçek biçimli sahte token çalışma anında birleştirilir (push koruması).
SAHTE_TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
CALISMA_ANI_SIRRI = "calisma-" + "ani-" + "sirri-42"


def _baglam(enabled: bool = True, rol: str = "analyst") -> AracBaglami:
    oturum = PiiMasker(enabled=enabled).new_session()
    return AracBaglami(
        kullanici_id=uuid.uuid4(),
        rol=rol,
        oturum=oturum,
        db=lambda: pytest.fail("bu testte DB kullanılmaz"),  # type: ignore[arg-type,return-value]
        sir_degerleri=(CALISMA_ANI_SIRRI,),
    )


def _sabit(metin: str, **kw: Any):
    def arac(_baglam: AracBaglami, **_arg: Any) -> AracSonucu:
        return AracSonucu(metin, **kw)

    return arac


class SahteDemoDb:
    def __init__(self, satirlar: list[tuple[Any, ...]]) -> None:
        self.satirlar = satirlar

    def schema(self) -> dict[str, list[tuple[str, str]]]:
        return {"bayi": [("ad", "text"), ("eposta", "text")]}

    def query(self, sql: str) -> QueryResult:
        return QueryResult(sql=sql, columns=["ad", "eposta"], rows=self.satirlar, truncated=False)


# ------------------------------------------------------------------ tek maskeleme oturumu


def test_tek_oturum_farkli_epostalar_farkli_yer_tutucu_ve_cevapta_dogru_acilir() -> None:
    baglam = _baglam()
    oturum = baglam.oturum
    soru, _ = oturum.mask_text("ayse@ornek.com neden bekliyor?")
    sar = AracSarmalayici(
        baglam,
        yeni={
            "probe_get": _sabit("sorumlu: mehmet@ornek.com"),
            "probe_list": _sabit("ilk: ayse@ornek.com, ikinci: zeynep@ornek.com"),
        },
    )
    bir = sar("probe_get", {})
    iki = sar("probe_list", {})
    assert "<<PII_EMAIL_1>>" in soru
    assert "<<PII_EMAIL_2>>" in bir and "mehmet" not in bir
    # Aynı değer aynı yer tutucu (sorudaki ayse), yeni değer yeni yer tutucu.
    assert "<<PII_EMAIL_1>>" in iki and "<<PII_EMAIL_3>>" in iki
    assert "ayse@" not in iki and "zeynep@" not in iki
    cevap = "Sorumlu <<PII_EMAIL_2>>; ilk kayıt <<PII_EMAIL_1>>, sonra <<PII_EMAIL_3>>."
    assert oturum.unmask(cevap) == (
        "Sorumlu mehmet@ornek.com; ilk kayıt ayse@ornek.com, sonra zeynep@ornek.com."
    )


def test_pii_iceren_probe_verisi_alintisi_maskeleme_acikken_dogrulanir() -> None:
    baglam = _baglam()
    sar = AracSarmalayici(baglam, yeni={"probe_get": _sabit("PO cevabı: ali@ornek.com onayladı")})
    cikti = sar("probe_get", {})
    assert cikti.startswith("[kanit:k1]\n<untrusted")
    kanit = sar.havuz.al("k1", "probe_verisi")
    assert kanit is not None and kanit.metin == cikti
    # Geçit son çıktının maskesini açtığından alıntı ham değer taşır; doğrulama aynı oturumla.
    alinti = "ali@ornek.com onayladı"
    assert alinti not in kanit.metin
    assert alinti in baglam.oturum.unmask(kanit.metin)
    # Kimliğin türü kaynak türüyle uyuşmalı.
    assert sar.havuz.al("k1", "jira") is None


def test_maskeleme_kapaliyken_metin_degismez() -> None:
    baglam = _baglam(enabled=False)
    sar = AracSarmalayici(baglam, yeni={"probe_get": _sabit("ali@ornek.com")})
    assert "ali@ornek.com" in sar("probe_get", {})


# ------------------------------------------------------------------ çift sarma / maske yok


def test_mevcut_arac_cift_sarilmaz_ve_ikinci_kez_maskelenmez() -> None:
    baglam = _baglam()
    veri = DataTools(SahteDemoDb([("Bayi 1", "bayi1@ornek.com")]), session=baglam.oturum)
    sar = AracSarmalayici(
        baglam,
        mevcut={"db_query": veri.db_query, "db_schema": veri.db_schema},
        mevcut_turleri={"db_query": "uygulama_verisi", "db_schema": "uygulama_verisi"},
    )
    cikti = sar("db_query", {"sql": "SELECT ad, eposta FROM bayi"})
    assert cikti.count("<untrusted") == 1
    assert cikti.startswith("[kanit:k1]\nquery: ")
    assert "<<PII_EMAIL_1>>" in cikti and "< <PII" not in cikti
    kanit = sar.havuz.al("k1", "uygulama_verisi")
    assert kanit is not None
    assert kanit.sql == "SELECT ad, eposta FROM bayi"
    assert kanit.result_digest and kanit.result_digest in cikti
    sema = sar("db_schema", {})
    assert sema.count("<untrusted") == 1 and sema.startswith("[kanit:k2]\n")


def test_yeni_arac_tek_kez_sarilir_ve_kimlikler_sirali() -> None:
    sar = AracSarmalayici(
        _baglam(),
        yeni={"ci_log": _sabit("satır", kanit_turu="ci_log", tur="ci_log", kaynak="run-1")},
    )
    bir, iki = sar("ci_log", {}), sar("ci_log", {})
    assert bir.count("<untrusted") == 1 and 'kind="ci_log"' in bir
    assert 'source="tool:ci_log:run-1:k1"' in bir
    assert iki.startswith("[kanit:k2]\n")
    assert [k.kimlik for k in sar.havuz] == ["k1", "k2"]


# ------------------------------------------------------------------ kanıt havuzu


def test_kanit_havuzunda_ham_sonuc_yok() -> None:
    baglam = _baglam()
    ham = f"iletişim: veli@ornek.com, token {SAHTE_TOKEN}, sır {CALISMA_ANI_SIRRI}"
    veri = DataTools(SahteDemoDb([("X", "deniz@ornek.com")]), session=baglam.oturum)
    sar = AracSarmalayici(
        baglam,
        yeni={"probe_get": _sabit(ham, meta={"tur": "requirement"})},
        mevcut={"db_query": veri.db_query},
        mevcut_turleri={"db_query": "uygulama_verisi"},
    )
    sar("probe_get", {})
    sar("db_query", {"sql": "SELECT ad, eposta FROM bayi"})
    assert len(sar.havuz) == 2
    for kanit in sar.havuz:
        dokum = repr(dataclasses.asdict(kanit))
        for ham_deger in ("veli@ornek.com", "deniz@ornek.com", SAHTE_TOKEN, CALISMA_ANI_SIRRI):
            assert ham_deger not in dokum
    sar.havuz.temizle()
    assert len(sar.havuz) == 0


def test_havuz_kimligi_ve_sha() -> None:
    havuz = KanitHavuzu()
    k = havuz.ekle("probe_get", "probe_verisi", lambda kimlik: f"[kanit:{kimlik}]\nx")
    assert k.kimlik == "k1" and len(k.sha256) == 64
    assert havuz.al(" k1 ") is k and havuz.al("k9") is None


# ------------------------------------------------------------------ sır temizleme ve hatalar


def test_sirlar_yeni_ve_mevcut_arac_sonucundan_temizlenir() -> None:
    baglam = _baglam(enabled=False)
    sar = AracSarmalayici(
        baglam,
        yeni={"probe_get": _sabit(f"log: {SAHTE_TOKEN} {CALISMA_ANI_SIRRI}")},
        mevcut={
            "search_code": lambda _a: wrap_tool_result("search_code", f"a.ts:1: {SAHTE_TOKEN}")
        },
    )
    for cikti in (sar("probe_get", {}), sar("search_code", {"query": "x"})):
        assert SAHTE_TOKEN not in cikti and CALISMA_ANI_SIRRI not in cikti
        assert "***" in cikti


def test_kisa_bilinen_deger_de_temizlenir() -> None:
    assert sir_temizle("parola: Kisa1!", ("Kisa1!",)) == "parola: ***"


def test_guvenli_hata_mesaji_temizlenir_beklenmeyen_hata_sizdirmaz() -> None:
    baglam = _baglam()

    def guvenli(_b: AracBaglami, **_a: Any) -> AracSonucu:
        raise AracHatasi(f"bulunamadı: kim@ornek.com {SAHTE_TOKEN}")

    def beklenmeyen(_b: AracBaglami, **_a: Any) -> AracSonucu:
        raise RuntimeError(f"bağlantı dizesi postgres://u:{CALISMA_ANI_SIRRI}@db/x")

    sar = AracSarmalayici(baglam, yeni={"probe_get": guvenli, "probe_list": beklenmeyen})
    with pytest.raises(AracHatasi) as e1:
        sar("probe_get", {})
    assert SAHTE_TOKEN not in str(e1.value) and "kim@ornek.com" not in str(e1.value)
    with pytest.raises(AracHatasi) as e2:
        sar("probe_list", {})
    assert str(e2.value) == "araç çalıştırılamadı (RuntimeError)"
    with pytest.raises(AracHatasi, match="bilinmeyen araç"):
        sar("browser_run_code", {})
    assert len(sar.havuz) == 0


# ------------------------------------------------------------------ kayıt defteri


def test_kayit_defteri_gecit_izin_listesiyle_ayni() -> None:
    assert frozenset(ARAC_ADLARI) == ASSISTANT_TOOLS
    assert not frozenset(ARAC_ADLARI) & FORBIDDEN_TOOLS
    assert [s.name for s in tool_specs()] == list(ARAC_ADLARI)


def test_arac_seti_tum_rollere_ayni_liste_veri_rol_kisiti_uygulamada() -> None:
    veri_cagrildi: list[str] = []

    class SahteVeri:
        def db_schema(self, _a: dict[str, Any]) -> str:
            veri_cagrildi.append("db_schema")
            return wrap_tool_result("db_schema", "bayi(ad text)")

        def db_query(self, _a: dict[str, Any]) -> str:
            return wrap_tool_result("db_query", "x")

    class SahteKod:
        def search_code(self, _a: dict[str, Any]) -> str:
            return wrap_tool_result("search_code", "a.ts:1: x")

        def get_file_contents(self, _a: dict[str, Any]) -> str:
            return wrap_tool_result("get_file_contents", "a.ts")

    setler = {
        rol: arac_seti(
            _baglam(rol=rol),
            urun=object(),
            kod=SahteKod(),
            veri=SahteVeri(),
            veri_rol_listesi=frozenset({"analyst"}),
        )
        for rol in ("analyst", "tester")
    }
    assert setler["analyst"].adlar == setler["tester"].adlar == frozenset(ARAC_ADLARI)
    assert setler["analyst"].execute("db_schema", {}).startswith("[kanit:k1]")
    with pytest.raises(AracHatasi, match="rolünüze açık değil"):
        setler["tester"].execute("db_schema", {})
    assert veri_cagrildi == ["db_schema"]
    assert setler["tester"].execute("search_code", {"query": "x"}).startswith("[kanit:k1]")


def test_veri_rolleri_ortamdan() -> None:
    assert veri_rolleri({}) is None
    assert veri_rolleri({"TP_ASISTAN_VERI_ROLLERI": " analyst, po ,"}) == {"analyst", "po"}


def test_maskeleyici_ortamdan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_PII_MASKING", "1")
    assert maskeleyici().enabled is True
    monkeypatch.setenv("TP_PII_MASKING", "0")
    assert mesaj_oturumu().enabled is False
