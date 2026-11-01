"""Adım çalıştırıcı: süre ölçümü, bütçe, PASS/FAIL, bekleme yardımcıları.

Her adım bir fonksiyondur: `prova` kipinde sunucunun yapacağı eylemi yapar (API çağrısı ya da
`make` hedefi), ardından beklenen durumu doğrular. `denetim` kipinde eylem yapılmaz, yalnızca
doğrulama koşar (tamamlanmış bir demonun son durumunu okur; yığını değiştirmez).

Doğrulama başarısızlığı `Basarisiz` fırlatır; beklenmeyen istisna da FAIL sayılır (ayrıntı rapora).
Bir adım başarısız olunca sonraki adımlar varsayılan olarak koşmaz (ATLANDI): prova durumu artık
demo yolunda değildir; `--devam` ile yine de denenir.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PASS, FAIL, ATLANDI, UYARI = "PASS", "FAIL", "ATLANDI", "UYARI"


class Basarisiz(AssertionError):
    """Beklenen durum gerçekleşmedi (Türkçe açıklama)."""


class ZamanAsimi(Basarisiz):
    pass


def dogrula(kosul: Any, mesaj: str) -> None:
    if not kosul:
        raise Basarisiz(mesaj)


@dataclass
class Adim:
    no: str
    ad: str
    rol: str
    demo_adimi: str  # TEKNIK-TASARIM §2'deki karşılığı (ör. "2", "5–6", "12")
    butce_s: float
    fn: Callable[[Baglam], None]
    ai_adimi: bool = False  # §1/§13: ajan/AI adımı (ör. kod üretimi ≤120 sn)


@dataclass
class Kontrol:
    ad: str
    sonuc: str  # PASS | FAIL | UYARI
    ayrinti: str = ""


@dataclass
class AdimSonucu:
    no: str
    ad: str
    rol: str
    demo_adimi: str
    durum: str
    sure_s: float
    butce_s: float
    kontroller: list[Kontrol] = field(default_factory=list)
    kanit: dict[str, Any] = field(default_factory=dict)
    hata: str | None = None
    ayrinti: str | None = None

    @property
    def butce_asildi(self) -> bool:
        return self.durum != ATLANDI and self.sure_s > self.butce_s


@dataclass
class Baglam:
    """Adımlar arasında taşınan durum + istemciler. `kip`: prova | denetim."""

    kip: str
    api: Any
    jira: Any
    yigin: Any
    ortam: Any
    log: Callable[[str], None]
    bekleme_carpani: float = 1.0
    yoklama_s: float = 3.0
    veri: dict[str, Any] = field(default_factory=dict)
    # Etkin adımın kayıtları (çalıştırıcı her adımda sıfırlar)
    kontroller: list[Kontrol] = field(default_factory=list)
    kanit: dict[str, Any] = field(default_factory=dict)
    saat: Callable[[], float] = time.monotonic
    uyu: Callable[[float], None] = time.sleep

    @property
    def prova(self) -> bool:
        return self.kip == "prova"

    def kontrol(self, ad: str, kosul: Any, ayrinti: str = "", *, kritik: bool = True) -> None:
        """Adlandırılmış doğrulama. Kritikse başarısızlık adımı durdurur, değilse UYARI."""
        if kosul:
            self.kontroller.append(Kontrol(ad, PASS, ayrinti))
            return
        if kritik:
            self.kontroller.append(Kontrol(ad, FAIL, ayrinti))
            raise Basarisiz(f"{ad}: {ayrinti}" if ayrinti else ad)
        self.kontroller.append(Kontrol(ad, UYARI, ayrinti))

    def bekle(
        self,
        aciklama: str,
        kosul: Callable[[], Any],
        zaman_asimi_s: float,
        aralik_s: float | None = None,
    ) -> Any:
        """`kosul()` doğru (truthy) değer dönene kadar yoklar; değeri döner.

        Denetim kipinde bekleme kısadır: durum zaten oluşmuş olmalıdır.
        """
        sinir = zaman_asimi_s * self.bekleme_carpani
        if not self.prova:
            sinir = min(sinir, 10.0)
        aralik = self.yoklama_s if aralik_s is None else aralik_s
        t0 = self.saat()
        son: Any = None
        while True:
            son = kosul()
            if son:
                return son
            if self.saat() - t0 >= sinir:
                raise ZamanAsimi(f"zaman aşımı ({sinir:.0f} sn): {aciklama}")
            self.uyu(aralik)


@dataclass
class Calistirici:
    adimlar: list[Adim]
    baglam: Baglam
    devam: bool = False
    butce_uyari: bool = False  # True: bütçe aşımı FAIL değil UYARI
    secili: set[str] | None = None

    def calistir(self) -> list[AdimSonucu]:
        sonuclar: list[AdimSonucu] = []
        durdu = False
        for adim in self.adimlar:
            if self.secili is not None and adim.no not in self.secili:
                continue
            if durdu:
                sonuclar.append(
                    AdimSonucu(
                        adim.no,
                        adim.ad,
                        adim.rol,
                        adim.demo_adimi,
                        ATLANDI,
                        0.0,
                        adim.butce_s,
                        hata="önceki adım başarısız",
                    )
                )
                continue
            sonuc = self._tek(adim)
            sonuclar.append(sonuc)
            if sonuc.durum == FAIL and not self.devam:
                durdu = True
        return sonuclar

    def _tek(self, adim: Adim) -> AdimSonucu:
        b = self.baglam
        b.kontroller, b.kanit = [], {}
        b.log(f"▶ {adim.no} {adim.ad} [{adim.rol}] (bütçe {adim.butce_s:.0f} sn)")
        t0 = b.saat()
        durum, hata, ayrinti = PASS, None, None
        try:
            adim.fn(b)
        except Basarisiz as e:
            durum, hata = FAIL, str(e)
        except Exception as e:  # beklenmeyen hata da FAIL; iz rapora
            durum, hata = FAIL, f"{type(e).__name__}: {e}"
            ayrinti = traceback.format_exc(limit=6)
        sure = b.saat() - t0
        sonuc = AdimSonucu(
            adim.no,
            adim.ad,
            adim.rol,
            adim.demo_adimi,
            durum,
            round(sure, 1),
            adim.butce_s,
            kontroller=list(b.kontroller),
            kanit=dict(b.kanit),
            hata=hata,
            ayrinti=ayrinti,
        )
        if durum == PASS and sonuc.butce_asildi:
            mesaj = f"süre bütçesi aşıldı: {sure:.0f} sn > {adim.butce_s:.0f} sn"
            sonuc.kontroller.append(
                Kontrol("süre bütçesi", UYARI if self.butce_uyari else FAIL, mesaj)
            )
            if not self.butce_uyari:
                sonuc.durum, sonuc.hata = FAIL, mesaj
        if sonuc.durum == PASS and any(k.sonuc == UYARI for k in sonuc.kontroller):
            sonuc.durum = UYARI
        b.log(
            f"  {sonuc.durum} {adim.no} ({sure:.1f} sn){' — ' + sonuc.hata if sonuc.hata else ''}"
        )
        return sonuc
