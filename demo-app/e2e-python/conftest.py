"""Ortak test fikstürleri (TS: tests/fixtures.ts karşılığı).

- Taban adres `BASE_URL` (pytest-playwright `base_url`; `--base-url` verilmezse ortamdan).
- Her test bir e2e bayisiyle koşar: `@pytest.mark.dealer("bayi2")` ile sabitlenmişse o, yoksa
  işçinin bayisi (pytest-xdist `gwN` → bayi1/bayi2; tek süreçte bayi1). Doğrulama ajanının bayisi
  (bayi3) asla. Aynı bayi iki süreçte aynı anda kullanılmasın diye süreçler arası dosya kilidi.
- Veri yalıtımı: `DEMOAPP_TEST_TOKEN` varsa her testten önce `POST /test/reset`; yoksa
  `TP_E2E_NO_RESET=1` ile yalnız sepet (herkese açık API) ve `sifir_veri` testleri atlanır.
- `BREAK_CAMPAIGN=1` / `TP_FAULT=<kod>`: bayi kapsamlı `/test/break` testten önce açılır, test
  sonunda geri alınır (kırarak doğrulama / ekilmiş hata).
- Başarısız testin kanıtı: `results/kanit/<test işlevi>/{ekran.png, sayfa.html}` (trace:
  `--tracing retain-on-failure --output results/artifacts`).
- `oturumlu` işaretli test bayi API ile oturum açmış başlar (TS `signedInTest`).

Hazırlık hatası `KurulumHatasi`dır (AssertionError DEĞİL): kırarak doğrulamada kırmızı sayılmaz.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from altyapi import bayiler, kilit, veri_yalitimi
from altyapi.bayiler import Bayi

if TYPE_CHECKING:  # birim testleri playwright kurulu olmadan da koşar
    from playwright.sync_api import Page

KOK = Path(__file__).resolve().parent
KANIT_DIZINI = Path(os.environ.get("KANIT_DIZINI") or KOK / "results" / "kanit")
_GUVENSIZ = re.compile(r"[^A-Za-z0-9._-]")


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:
    """pytest-playwright taban adresi: `--base-url`, yoksa `BASE_URL`, yoksa yerel önizleme."""
    verilen = request.config.getoption("base_url", default=None)
    return verilen or os.environ.get("BASE_URL") or "http://127.0.0.1:8081"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Yalnız-sepet yalıtımında sipariş geçmişi silinemez: boş veri varsayan testler koşmaz.
    if not os.environ.get("DEMOAPP_TEST_TOKEN") and os.environ.get("TP_E2E_NO_RESET") == "1":
        atla = pytest.mark.skip(reason="TP_E2E_NO_RESET=1: sipariş geçmişi silinemez")
        for item in items:
            if item.get_closest_marker("sifir_veri"):
                item.add_marker(atla)


def _isci_sirasi() -> int:
    isci = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    m = re.fullmatch(r"gw(\d+)", isci)
    return int(m.group(1)) if m else 0


@pytest.fixture
def dealer(request: pytest.FixtureRequest, base_url: str) -> Iterator[Bayi]:
    """Testin bayisi: kilitle alınır, verisi hazırlanır, test sonunda kırılma geri alınır."""
    isaret = request.node.get_closest_marker("dealer")
    sabit = isaret.args[0] if isaret and isaret.args else None
    bayi = bayiler.sec(sabit, _isci_sirasi())
    api = veri_yalitimi.api_koku(base_url)
    kip = veri_yalitimi.kip()
    kirilma = veri_yalitimi.kirilma()
    veri = veri_yalitimi.TestVerisi(api, os.environ.get("DEMOAPP_TEST_TOKEN"))
    k = kilit.BayiKilidi.al(kilit.dizin("demoapp-e2e-python-kilit", f"{base_url}|{api}"),
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
                # Sonraki testin /test/reset'i kırılmayı da kaldırır; geri alma hatası testi
                # kırmızıya çevirmez (TestTabani.java ile aynı).
                try:
                    veri.kir(kirilma, bayi.kullanici_adi, False)
                except veri_yalitimi.KurulumHatasi:
                    pass
    finally:
        k.birak()


@pytest.fixture(autouse=True)
def _bayi_hazirligi(request: pytest.FixtureRequest) -> None:
    """Her tarayıcı testinde bayi alınır (TS `dealer` fikstürü `auto: true`). Birim testleri hariç."""
    if request.node.get_closest_marker("birim"):
        return
    request.getfixturevalue("dealer")
    if request.node.get_closest_marker("oturumlu"):
        request.getfixturevalue("signed_in")


@pytest.fixture
def signed_in(page: Page, dealer: Bayi) -> None:
    """Bayi API üzerinden oturum açar; çerez sayfa bağlamıyla paylaşılır (TS `signedIn`).

    `page.request` izlenir ama bu istek token taşımaz (yalnız seed parolası)."""
    yanit = page.request.post(
        "/api/auth/login", data={"kullanici_adi": dealer.kullanici_adi, "parola": dealer.parola}
    )
    if not yanit.ok:
        raise veri_yalitimi.KurulumHatasi(f"API ile giriş başarısız: {yanit.status}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: Any) -> Iterator[None]:
    outcome = yield
    rapor = outcome.get_result()
    if rapor.when != "call" or not rapor.failed:
        return
    page = getattr(item, "funcargs", {}).get("page")
    if page is None:
        return
    hedef = KANIT_DIZINI / _GUVENSIZ.sub("_", item.name)
    try:
        hedef.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(hedef / "ekran.png"), full_page=True)
        (hedef / "sayfa.html").write_text(page.content(), encoding="utf-8")
    except Exception:  # noqa: BLE001 - kanıt toplanamaması testin sonucunu değiştirmez
        pass
