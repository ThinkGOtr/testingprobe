"""Uygulama testlerinin ortak fikstürleri (Java: altyapi/TestTabani.java karşılığı).

Her cihaz testi için, sırasıyla:
  1. bayi seçilir (`@pytest.mark.dealer("bayi2")` ya da işçi bayisi) ve süreçler arası kilitle
     alınır;
  2. bayinin verisi sıfırlanır (`/test/reset`) ya da yalnız sepeti boşaltılır
     (`TP_E2E_NO_RESET=1`; `sifir_veri` testleri atlanır);
  3. `TP_FAULT=<kod>` ise ekilmiş hata, yoksa `BREAK_CAMPAIGN=1` ise kampanya kırılması açılır;
  4. uygulama sıfırdan başlatılır (yeni Appium oturumu, fikstür `driver`);
  5. `oturumlu` işaretli testte arayüzden giriş yapılır.
Test bitince: başarısızsa kanıt (`results/kanit/<test>/{ekran.png, sayfa-kaynagi.xml}`), oturum
kapanır, kırılma geri alınır, kilit bırakılır.

Platform `TP_PLATFORM` (ya da `PLATFORM`): başka bir platformun işaretini taşıyan test seçilmez
(üretilen test `@pytest.mark.<platform>` taşır; işaretsiz elle yazılmış testler her platformda
koşar). Hazırlık hatası `KurulumHatasi`dır, kırarak doğrulamada kırmızı sayılmaz.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from altyapi import bayiler, kilit, veri_yalitimi
from altyapi.ayarlar import PLATFORMLAR, Ayarlar
from altyapi.bayiler import Bayi

KOK = Path(__file__).resolve().parent
_GUVENSIZ = re.compile(r"[^A-Za-z0-9._-]")


def _etkin_platform() -> str | None:
    deger = (os.environ.get("TP_PLATFORM") or os.environ.get("PLATFORM") or "").strip().lower()
    return deger or None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    platform = _etkin_platform()
    secilen: list[pytest.Item] = []
    elenen: list[pytest.Item] = []
    for item in items:
        isaretler = {p for p in PLATFORMLAR if item.get_closest_marker(p)}
        if platform and isaretler and platform not in isaretler:
            elenen.append(item)
        else:
            secilen.append(item)
    if elenen:
        config.hook.pytest_deselected(items=elenen)
        items[:] = secilen
    if not os.environ.get("DEMOAPP_TEST_TOKEN") and os.environ.get("TP_E2E_NO_RESET") == "1":
        atla = pytest.mark.skip(reason="TP_E2E_NO_RESET=1: sipariş geçmişi silinemez")
        for item in items:
            if item.get_closest_marker("sifir_veri"):
                item.add_marker(atla)


def _isci_sirasi() -> int:
    m = re.fullmatch(r"gw(\d+)", os.environ.get("PYTEST_XDIST_WORKER", "gw0"))
    return int(m.group(1)) if m else 0


@pytest.fixture
def ayarlar() -> Ayarlar:
    return Ayarlar.oku()


@pytest.fixture
def dealer(request: pytest.FixtureRequest) -> Iterator[Bayi]:
    """Testin bayisi: kilitle alınır, verisi hazırlanır, test sonunda kırılma geri alınır."""
    isaret = request.node.get_closest_marker("dealer")
    sabit = isaret.args[0] if isaret and isaret.args else None
    bayi = bayiler.sec(sabit, _isci_sirasi())
    # Uygulama testlerinde /test/* kökü DEMO_API_URL (varsayılan: yerel web vekili).
    api = veri_yalitimi.api_koku(os.environ.get("BASE_URL") or "http://127.0.0.1:8081")
    kip = veri_yalitimi.kip()
    kirilma = veri_yalitimi.kirilma()
    veri = veri_yalitimi.TestVerisi(api, os.environ.get("DEMOAPP_TEST_TOKEN"))
    k = kilit.BayiKilidi.al(kilit.dizin("demoapp-e2e-app-python-kilit", f"app|{api}"),
                           bayi.kullanici_adi)  # fmt: skip
    try:
        if kip == "sifirlama":
            veri.sifirla(bayi.kullanici_adi)
            if kirilma:
                veri.kir(kirilma, bayi.kullanici_adi, True)
        else:
            veri.sepeti_bosalt(bayi.kullanici_adi, bayi.parola)
        try:
            yield bayi
        finally:
            if kip == "sifirlama" and kirilma:
                try:  # sonraki testin /test/reset'i kırılmayı da kaldırır
                    veri.kir(kirilma, bayi.kullanici_adi, False)
                except veri_yalitimi.KurulumHatasi:
                    pass
    finally:
        k.birak()


@pytest.fixture
def driver(request: pytest.FixtureRequest, dealer: Bayi, ayarlar: Ayarlar) -> Iterator[Any]:
    """Yeni Appium oturumu (uygulama sıfırdan başlar); `oturumlu` testte arayüzden giriş."""
    from altyapi import kimlik as kimlikmod
    from altyapi import oturum, surucu
    from altyapi.bekle import Bekle

    strateji = kimlikmod.strateji(ayarlar.platform, ayarlar.kimlik_stratejisi)
    d = surucu.olustur(ayarlar)
    oturum.kaydet(d, oturum.Oturum(ayarlar.platform, strateji, Bekle(ayarlar.bekleme_s)))
    request.node._tp_surucu = d  # kanıt kancası için
    try:
        if request.node.get_closest_marker("oturumlu"):
            from ekranlar.giris_ekrani import GirisEkrani
            from ekranlar.kimlikler import MENU

            giris = GirisEkrani(d)
            giris.ac()
            giris.giris_yap(dealer.kullanici_adi, dealer.parola)
            bayi_adi = MENU["BAYI_ADI"]["testId"]
            oturum.oturum(d).bekle.kosul(
                f"arayüzden giriş tamamlanmadı (kimlik '{bayi_adi}')",
                lambda: True if d.find_elements(*kimlikmod.bul(strateji, bayi_adi)) else None,
            )
        yield d
    finally:
        try:
            d.quit()
        except Exception:  # noqa: BLE001 - oturum kapatılamadı; sonuç değişmez
            pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: Any) -> Iterator[None]:
    outcome = yield
    rapor = outcome.get_result()
    if rapor.when != "call" or not rapor.failed:
        return
    d = getattr(item, "_tp_surucu", None)
    if d is None:
        return
    kok = Path(os.environ.get("KANIT_DIZINI") or KOK / "results" / "kanit")
    hedef = kok / _GUVENSIZ.sub("_", item.name)
    hatalar: list[str] = []
    try:
        hedef.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    try:
        (hedef / "ekran.png").write_bytes(d.get_screenshot_as_png())
    except Exception as exc:  # noqa: BLE001
        hatalar.append(f"ekran görüntüsü: {type(exc).__name__}")
    try:
        (hedef / "sayfa-kaynagi.xml").write_text(d.page_source, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        hatalar.append(f"sayfa kaynağı: {type(exc).__name__}")
    if hatalar:
        (hedef / "kanit-hatasi.txt").write_text("\n".join(hatalar) + "\n", encoding="utf-8")
