"""Asistan rol politikası (spec 013 §4; K3, K9, K10) — `rules/assistant/rol-politikasi.yaml`.

Kurallar 8 portal rolü için yazılır (012: `auth/yetki.py` ROLLER); portal rolü doğrudan politika
rolüdür, eski `presenter` → `admin` (`yetki.normalize_rol`). Bilinmeyen rol → `viewer` (en dar;
fail-closed).

Dosya bir kez yüklenir ve önbelleğe alınır. Yükleme katıdır: bilinmeyen anahtar, bilinmeyen araç
adı (`tools.ARAC_ADLARI` dışı), eksik ya da fazla rol, ya da yetki kataloğunda izni olmayan role
kod aracı (`code.read`) veya veri aracı (`requirement.read`) `RolPolitikasiHatasi` fırlatır (bozuk
dosyayla asistan araç dağıtmaz).

    politika_rolu("presenter")   -> "admin"
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
VARSAYILAN_ROL: Final = "viewer"
TUM: Final = "tum"
EK_UST: Final = 400  # rol-politikasi.yaml "ek ≤ 400 karakter" (ANALIZ §4)
# K3 + 012: kuralların yazıldığı 8 portal rolü (dosyada hepsi zorunlu, fazlası yasak).
POLITIKA_ROLLERI: Final[tuple[str, ...]] = (
    "admin",
    "auditor",
    "analyst",
    "po",
    "tester",
    "engineer",
    "developer",
    "viewer",
)
_UST_ANAHTARLAR: Final = frozenset({"surum", "roller"})
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
    roller: Mapping[str, RolKurali]

    def rol_adi(self, rol: str | None) -> str:
        """Portal rolü (eski `presenter` → `admin`); bilinmeyen → `viewer`."""
        from tp_core.auth.yetki import normalize_rol

        r = normalize_rol((rol or "").strip())
        return r if r in self.roller else VARSAYILAN_ROL

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
    fazla_rol = sorted(set(roller) - set(POLITIKA_ROLLERI))
    if fazla_rol:
        raise _hata(f"portal rolü olmayan politika rolü: {fazla_rol}")
    _katalogla_tutarli(roller)
    return RolPolitikasi(surum=SURUM, roller=MappingProxyType(roller))


def _katalogla_tutarli(roller: Mapping[str, RolKurali]) -> None:
    """012: kod aracı yalnız `code.read`, veri aracı yalnız `requirement.read` sahibi role."""
    from tp_core.auth.yetki import izinli
    from tp_core.features.assistant.tools import KOD_ARACLARI, KOD_IZNI, VERI_ARACLARI, VERI_IZNI

    for ad, kural in roller.items():
        for araclar, izin in ((KOD_ARACLARI, KOD_IZNI), (VERI_ARACLARI, VERI_IZNI)):
            fazla = sorted(kural.araclar & set(araclar))
            if fazla and not izinli(ad, izin):
                raise _hata(f"roller.{ad}.araclar katalogda {izin} izni olmadan {fazla} içeriyor")


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
    """Portal rolü → politika rolü (eski `presenter` → `admin`); bilinmeyen → `viewer`."""
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
