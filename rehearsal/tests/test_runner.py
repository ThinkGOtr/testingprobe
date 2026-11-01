"""Adım çalıştırıcı: PASS/FAIL/ATLANDI/UYARI, bütçe, bekleme ve zaman aşımı."""

from __future__ import annotations

import pytest

from tp_rehearsal.runner import (
    ATLANDI,
    FAIL,
    PASS,
    UYARI,
    Adim,
    Basarisiz,
    Calistirici,
    ZamanAsimi,
)


def _adim(no, fn, butce=10.0):
    return Adim(no, f"adım {no}", "analist", "1", butce, fn)


def test_basarisiz_adimdan_sonrakiler_atlanir(baglam):
    b = baglam()
    calisan = []

    def iyi(b):
        calisan.append("iyi")
        b.kontrol("bir", True)

    def kotu(b):
        b.kontrol("iki", False, "beklenen değil")

    s = Calistirici([_adim("A", iyi), _adim("B", kotu), _adim("C", iyi)], b).calistir()
    assert [x.durum for x in s] == [PASS, FAIL, ATLANDI]
    assert s[1].hata == "iki: beklenen değil"
    assert s[1].kontroller[-1].sonuc == FAIL
    assert calisan == ["iyi"]


def test_devam_kipinde_sonrakiler_kosar(baglam):
    b = baglam()

    def kotu(b):
        raise Basarisiz("x")

    s = Calistirici([_adim("A", kotu), _adim("B", lambda b: None)], b, devam=True).calistir()
    assert [x.durum for x in s] == [FAIL, PASS]


def test_beklenmeyen_istisna_fail_ve_iz(baglam):
    def patla(b):
        raise KeyError("yok")

    s = Calistirici([_adim("A", patla)], baglam()).calistir()
    assert s[0].durum == FAIL and s[0].hata.startswith("KeyError")
    assert "Traceback" in (s[0].ayrinti or "")


def test_kritik_olmayan_kontrol_uyari(baglam):
    def f(b):
        b.kontrol("yumuşak", False, "ayrıntı", kritik=False)
        b.kanit["x"] = 1

    s = Calistirici([_adim("A", f)], baglam()).calistir()
    assert s[0].durum == UYARI
    assert s[0].kanit == {"x": 1}


def test_butce_asimi_fail_ya_da_uyari(baglam, saat):
    def yavas(b):
        saat.t += 15

    s = Calistirici([_adim("A", yavas, butce=10)], baglam()).calistir()
    assert s[0].durum == FAIL and "bütçe" in s[0].hata
    s = Calistirici([_adim("A", yavas, butce=10)], baglam(), butce_uyari=True).calistir()
    assert s[0].durum == UYARI and s[0].sure_s == 15


def test_secili_adimlar(baglam):
    s = Calistirici(
        [_adim("A", lambda b: None), _adim("B", lambda b: None)], baglam(), secili={"B"}
    ).calistir()
    assert [x.no for x in s] == ["B"]


def test_kanit_ve_kontroller_adim_basina_sifirlanir(baglam):
    def a(b):
        b.kanit["a"] = 1
        b.kontrol("a", True)

    def bb(b):
        b.kontrol("b", True)

    s = Calistirici([_adim("A", a), _adim("B", bb)], baglam()).calistir()
    assert s[1].kanit == {} and [k.ad for k in s[1].kontroller] == ["b"]


def test_bekle_kosul_saglaninca_degeri_doner(baglam, saat):
    b = baglam()
    sayac = {"n": 0}

    def kosul():
        sayac["n"] += 1
        return {"tamam": True} if sayac["n"] >= 3 else None

    assert b.bekle("x", kosul, 60, aralik_s=2) == {"tamam": True}
    assert saat.t == 4


def test_bekle_zaman_asimi_ve_carpan(baglam, saat):
    b = baglam()
    b.bekleme_carpani = 2
    with pytest.raises(ZamanAsimi, match="zaman aşımı \\(20 sn\\): olmayacak"):
        b.bekle("olmayacak", lambda: None, 10, aralik_s=5)
    assert saat.t == 20


def test_denetim_kipinde_bekleme_kisa(baglam, saat):
    b = baglam(kip="denetim")
    with pytest.raises(ZamanAsimi):
        b.bekle("x", lambda: None, 600, aralik_s=1)
    assert saat.t <= 10
