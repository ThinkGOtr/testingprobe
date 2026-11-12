"""Asistan rol politikası (spec 013 §4; K3, K9, K10) — `rules/assistant/rol-politikasi.yaml`.

Kurallar 9 politika rolü için yazılır; bugünkü 5 portal rolü dosyadaki `esleme` ile bağlanır.
Her fonksiyon portal rolünü **ya da** doğrudan politika rolünü kabul eder (012 geçişinde eşleme
kalkınca çağıranlar değişmez). Bilinmeyen rol → `goruntuleyici` (en dar; fail-closed).

Dosya bir kez yüklenir ve önbelleğe alınır. Yükleme katıdır: bilinmeyen anahtar, bilinmeyen araç
adı (`tools.ARAC_ADLARI` dışı), eksik politika rolü ya da eşlemede tanımsız rol
`RolPolitikasiHatasi` fırlatır (bozuk dosyayla asistan araç dağıtmaz).

    politika_rolu("tester")      -> "testci"
    izinli_araclar("po")         -> frozenset({"product_search", …, "jira_issue"})
    etiket("analyst")            -> "Analist"
    rol_eki("analyst")           -> "Gereksinimi kaynaklarına dayanarak …"
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml

POLITIKA_DOSYASI: Final = "rol-politikasi.yaml"
SURUM: Final = 1
VARSAYILAN_ROL: Final = "goruntuleyici"
TUM: Final = "tum"
EK_UST: Final = 400  # rol-politikasi.yaml "ek ≤ 400 karakter" (ANALIZ §4)
# K3: kuralların yazıldığı 9 rol (dosyada hepsi zorunlu). `sunucu` geçiş rolüdür (K10).
POLITIKA_ROLLERI: Final[tuple[str, ...]] = (
    "sistem_yoneticisi",
    "erisim_yoneticisi",
    "denetci",
    "analist",
    "po",
    "testci",
    "automation_engineer",
    "developer",
    "goruntuleyici",
)
_UST_ANAHTARLAR: Final = frozenset({"surum", "esleme", "roller"})
_ROL_ANAHTARLARI: Final = frozenset({"araclar", "etiket", "ek"})


class RolPolitikasiHatasi(ValueError):
    """Rol politikası dosyası eksik ya da geçersiz."""


@dataclass(frozen=True)
class RolKurali:
    ad: str
    etiket: str
    ek: str
    araclar: frozenset[str]


@dataclass(frozen=True)
class RolPolitikasi:
    surum: int
    esleme: Mapping[str, str]
    roller: Mapping[str, RolKurali]

    def rol_adi(self, rol: str | None) -> str:
        """Portal rolü → politika rolü; politika rolü kendisi; bilinmeyen → `goruntuleyici`."""
        r = (rol or "").strip()
        if r in self.esleme:
            return self.esleme[r]
        if r in self.roller:
            return r
        return VARSAYILAN_ROL

    def kural(self, rol: str | None) -> RolKurali:
        return self.roller[self.rol_adi(rol)]


# ------------------------------------------------------------------ yükleme


def _hata(mesaj: str) -> RolPolitikasiHatasi:
    return RolPolitikasiHatasi(f"{POLITIKA_DOSYASI}: {mesaj}")


def _metin(deger: Any, yer: str, *, bos_olabilir: bool = False) -> str:
    if not isinstance(deger, str) or (not bos_olabilir and not deger.strip()):
        raise _hata(f"{yer} boş olmayan metin olmalı")
    return " ".join(deger.split())


def _araclar(deger: Any, yer: str, gecerli: tuple[str, ...]) -> frozenset[str]:
    if deger == TUM:
        return frozenset(gecerli)
    if not isinstance(deger, list) or not deger:
        raise _hata(f"{yer}.araclar '{TUM}' ya da boş olmayan liste olmalı")
    if not all(isinstance(a, str) for a in deger):
        raise _hata(f"{yer}.araclar yalnız araç adı içermeli")
    bilinmeyen = sorted(set(deger) - set(gecerli))
    if bilinmeyen:
        raise _hata(f"{yer}.araclar bilinmeyen araç: {bilinmeyen}")
    if len(set(deger)) != len(deger):
        raise _hata(f"{yer}.araclar yinelenen araç içeriyor")
    return frozenset(deger)


def politika_coz(veri: Any) -> RolPolitikasi:
    """Ayrıştırılmış YAML → doğrulanmış politika (testler bozuk girdiyi buradan dener)."""
    from tp_core.features.assistant.tools import ARAC_ADLARI

    if not isinstance(veri, Mapping):
        raise _hata("kök eşleme olmalı")
    fazla = sorted(set(veri) - _UST_ANAHTARLAR)
    eksik = sorted(_UST_ANAHTARLAR - set(veri))
    if fazla or eksik:
        raise _hata(f"üst anahtarlar hatalı (fazla={fazla}, eksik={eksik})")
    if veri["surum"] != SURUM or isinstance(veri["surum"], bool):
        raise _hata(f"surum {SURUM} olmalı")

    ham_roller = veri["roller"]
    if not isinstance(ham_roller, Mapping) or not ham_roller:
        raise _hata("roller boş olmayan eşleme olmalı")
    roller: dict[str, RolKurali] = {}
    for ad, kural in ham_roller.items():
        yer = f"roller.{ad}"
        if not isinstance(ad, str) or not isinstance(kural, Mapping):
            raise _hata(f"{yer} eşleme olmalı")
        fazla = sorted(set(kural) - _ROL_ANAHTARLARI)
        eksik = sorted(_ROL_ANAHTARLARI - set(kural))
        if fazla or eksik:
            raise _hata(f"{yer} anahtarları hatalı (fazla={fazla}, eksik={eksik})")
        ek = _metin(kural["ek"], f"{yer}.ek")
        if len(ek) > EK_UST:
            raise _hata(f"{yer}.ek {EK_UST} karakteri aşıyor")
        roller[ad] = RolKurali(
            ad=ad,
            etiket=_metin(kural["etiket"], f"{yer}.etiket"),
            ek=ek,
            araclar=_araclar(kural["araclar"], yer, ARAC_ADLARI),
        )
    eksik_rol = sorted(set(POLITIKA_ROLLERI) - set(roller))
    if eksik_rol:
        raise _hata(f"politika rolleri eksik: {eksik_rol}")

    ham_esleme = veri["esleme"]
    if not isinstance(ham_esleme, Mapping):
        raise _hata("esleme eşleme olmalı")
    esleme: dict[str, str] = {}
    for portal, hedef in ham_esleme.items():
        if not isinstance(portal, str) or not isinstance(hedef, str):
            raise _hata("esleme yalnız metin → metin içermeli")
        if hedef not in roller:
            raise _hata(f"esleme.{portal} tanımsız role gidiyor: {hedef}")
        esleme[portal] = hedef
    return RolPolitikasi(
        surum=SURUM,
        esleme=MappingProxyType(esleme),
        roller=MappingProxyType(roller),
    )


@lru_cache(maxsize=4)
def _yukle(yol: str) -> RolPolitikasi:
    try:
        veri = yaml.safe_load(Path(yol).read_text(encoding="utf-8"))
    except OSError as exc:
        raise _hata(f"okunamadı ({type(exc).__name__})") from None
    except yaml.YAMLError:
        raise _hata("YAML ayrıştırılamadı") from None
    return politika_coz(veri)


def politika_yukle(rules_dir: Path | None = None) -> RolPolitikasi:
    """Politika (önbellekli; `rules_dir` None → `find_rules_dir()`)."""
    from tp_core.gateway.config import find_rules_dir

    return _yukle(str(find_rules_dir(rules_dir) / "assistant" / POLITIKA_DOSYASI))


# ------------------------------------------------------------------ API


def politika_rolu(rol: str | None, *, rules_dir: Path | None = None) -> str:
    """Portal (ya da politika) rolü → politika rolü; bilinmeyen → `goruntuleyici`."""
    return politika_yukle(rules_dir).rol_adi(rol)


def izinli_araclar(rol: str | None, *, rules_dir: Path | None = None) -> frozenset[str]:
    """Rolün görebileceği/çağırabileceği araçlar (`TP_ASISTAN_VERI_ROLLERI` daraltması hariç)."""
    return politika_yukle(rules_dir).kural(rol).araclar


def etiket(rol: str | None, *, rules_dir: Path | None = None) -> str:
    """Prompt'taki rol satırının Türkçe adı."""
    return politika_yukle(rules_dir).kural(rol).etiket


def rol_eki(rol: str | None, *, rules_dir: Path | None = None) -> str:
    """Rol uzantısı (ilk kullanıcı mesajında rol satırının altına sunucu metni)."""
    return politika_yukle(rules_dir).kural(rol).ek


__all__ = [
    "POLITIKA_ROLLERI",
    "VARSAYILAN_ROL",
    "RolKurali",
    "RolPolitikasi",
    "RolPolitikasiHatasi",
    "etiket",
    "izinli_araclar",
    "politika_coz",
    "politika_rolu",
    "politika_yukle",
    "rol_eki",
]
