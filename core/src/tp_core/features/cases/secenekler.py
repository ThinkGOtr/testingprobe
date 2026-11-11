"""Üretim seçenekleri ve platform ekleri (specs/011 K5, F4; P1–P4.5).

Seçenekler (`requirement.uretim_secenekleri`, JSONB) analistin "Üretimi başlat" formunda seçtiği
platform(lar), test seviyesi, benimsenen standartlar, kapsam dışı, roller ve platforma özgü ek
bilgidir. Gereksinimde saklanır; sonraki üretimde (gövdesiz çağrı dahil) varsayılan olur.

Platform ekleri `rules/prompts/platform-*.md` dosyalarıdır (her biri `id`/`version` ön bilgili,
`rules/evaluations.yaml`'da kayıtlı). Mimari karar (rules/README.md "Platform ekleri"):

- Ek metni SİSTEM prompt'una değil, kullanıcı mesajına "Platform eki" bölümü olarak girer. Ek
  bizim (depodaki) metnimizdir; güvenilir talimattır, `<untrusted>` bloğu DEĞİLDİR. Paket
  (`case-generation`) ve bundle hash'i tek kalır: 5 ekin kombinasyonları ayrı bundle'a
  dönüşmez, sistem prompt'u önbellekte kalır, geçit ve golden mekanizması değişmez.
- Her ek başlık satırında `id@vN` ve dosya hash'ini taşır (`ek_basligi`); başlık girdinin
  parçası olduğundan ek metni değişince birebir replay anahtarı da değişir (bundle hash'iyle aynı
  özellik). Kullanılan ekler `ai_call.ek.platform_ekleri`'ne yazılır (geçit `call(ek=)`).
- Analistin serbest metinleri (standart kodları, roller, kapsam dışı, ek bilgi) güvenilmeyen
  veridir: `<kaynak>:secenekler` bloğunda gider. Ek metinleri bu bloktaki satırlara ad ile
  başvurur ("Tarayıcılar", "Benimsenen standartlar" …); ek dosyası şablon değildir.

Varsayılan seçenekler (platform yok, serbest metin yok) üretim girdisini bugünkü hâliyle bırakır:
yalnız `Test seviyesi: <SEVİYE>` satırı (dalga 1 davranışı, golden'lar değişmez).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from tp_core.workflow.service import WorkflowError

PLATFORMLAR = (
    "Web",
    "Mobil-iOS",
    "Mobil-Android",
    "Desktop-Win",
    "Desktop-macOS",
    "Desktop-Linux",
    "API",
    "Data",
)
TEST_SEVIYELERI = ("UNIT", "COMPONENT", "INTEGRATION", "SYSTEM", "E2E", "UAT")
VARSAYILAN_TEST_SEVIYESI = "SYSTEM"

# Sınırlar (portal `SECENEK_SINIRI` ile aynı; aşılırsa 422).
STANDART_SAYISI = 10
STANDART_UZUNLUK = 40
KAPSAM_DISI_UZUNLUK = 2000
ROLLER_UZUNLUK = 1000
METIN_UZUNLUK = 500
UZUN_METIN_UZUNLUK = 8000

_MOBIL = ("Mobil-iOS", "Mobil-Android")
_DESKTOP = ("Desktop-Win", "Desktop-macOS", "Desktop-Linux")

# Ortak ek (her platform seçiminde bir kez, platform eklerinden önce).
ORTAK_EK = "platform-common"


def platform_eki(platform: str) -> str:
    """Platform → ek paketi adı (`rules/prompts/<ad>.md`)."""
    if platform == "Web":
        return "platform-web"
    if platform in _MOBIL:
        return "platform-mobile"
    if platform in _DESKTOP:
        return "platform-desktop"
    if platform == "API":
        return "platform-api"
    if platform == "Data":
        return "platform-data"
    raise ValueError(f"bilinmeyen platform: {platform}")


@dataclass(frozen=True)
class EkBilgiAlani:
    """`ek_bilgi` alanı: etiket (seçenek bloğundaki satır adı), tür, platformlar.

    Yalnız prompt eklerinde karşılığı olan alanlar (P1–P4.5 yer tutucuları) vardır."""

    etiket: str
    tur: Literal["metin", "secim", "evet_hayir", "uzun_metin"]
    platformlar: tuple[str, ...]
    secenekler: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "etiket": self.etiket,
            "tur": self.tur,
            "platformlar": list(self.platformlar),
        }
        if self.secenekler:
            out["secenekler"] = list(self.secenekler)
        return out


EK_BILGI_ALANLARI: dict[str, EkBilgiAlani] = {
    # {{AUTOMATION_TOOL}} (tüm ekler)
    "otomasyon_araci": EkBilgiAlani("Otomasyon aracı", "metin", PLATFORMLAR),
    # P1 {{BROWSERS}}, {{VIEWPORTS}}
    "tarayicilar": EkBilgiAlani("Tarayıcılar", "metin", ("Web",)),
    "cozunurlukler": EkBilgiAlani("Çözünürlükler", "metin", ("Web",)),
    # P2/P3 {{OS_MATRIX}}, P2 {{DEVICES}}, {{APP_TYPE}}
    "os_matrisi": EkBilgiAlani("İşletim sistemi / sürüm matrisi", "metin", _MOBIL + _DESKTOP),
    "cihazlar": EkBilgiAlani("Cihaz sınıfları", "metin", _MOBIL),
    "uygulama_tipi": EkBilgiAlani(
        "Uygulama tipi",
        "secim",
        _MOBIL,
        ("native", "hybrid", "flutter", "react-native", "mobil-web"),
    ),
    # P3 {{STACK}}, {{ARCH}}, {{INSTALLER}}, {{PATH_LIMIT}}, {{SOAK_DURATION}}
    "teknoloji": EkBilgiAlani("Teknoloji", "metin", _DESKTOP),
    "mimari": EkBilgiAlani("Mimari", "secim", _DESKTOP, ("x64", "ARM64")),
    "dagitim": EkBilgiAlani("Dağıtım (MSI, DMG…)", "metin", _DESKTOP),
    "yol_limiti": EkBilgiAlani("Yol uzunluğu sınırı", "metin", _DESKTOP),
    "soak_suresi": EkBilgiAlani("Uzun süre açık kalma süresi", "metin", _DESKTOP),
    # P4 {{API_SPEC}}, {{AUTH}}
    "api_sozlesmesi_var": EkBilgiAlani("API sözleşmesi var", "evet_hayir", ("API",)),
    "api_sozlesmesi": EkBilgiAlani(
        "API sözleşmesi (OpenAPI/endpoint tanımı)", "uzun_metin", ("API",)
    ),
    "auth_tipi": EkBilgiAlani("Kimlik doğrulama tipi", "metin", ("API",)),
    # P4.5 {{SYSTEMS}}, {{SCHEMA}}, {{MAPPING}}, {{DELIVERY}}
    "sistemler": EkBilgiAlani("Sistemler", "metin", ("Data",)),
    "mesaj_semasi": EkBilgiAlani("Mesaj şeması", "uzun_metin", ("Data",)),
    "donusum_kurallari": EkBilgiAlani("Dönüşüm kuralları", "uzun_metin", ("Data",)),
    "teslim_garantisi": EkBilgiAlani(
        "Teslim garantisi",
        "secim",
        ("Data",),
        ("at-most-once", "at-least-once", "exactly-once"),
    ),
}


class UretimSecenekleri(BaseModel):
    """Doğrulanmış, tam seçenek nesnesi (saklanan biçim)."""

    model_config = ConfigDict(extra="forbid")

    platformlar: list[str] = Field(default_factory=list, max_length=len(PLATFORMLAR))
    test_seviyesi: str = VARSAYILAN_TEST_SEVIYESI
    benimsenen_standartlar: list[str] = Field(default_factory=list, max_length=STANDART_SAYISI)
    kapsam_disi: str = Field(default="", max_length=KAPSAM_DISI_UZUNLUK)
    roller: str = Field(default="", max_length=ROLLER_UZUNLUK)
    ek_bilgi: dict[str, str | bool] = Field(default_factory=dict)

    @field_validator("platformlar")
    @classmethod
    def _platformlar(cls, v: list[str]) -> list[str]:
        bilinmeyen = [p for p in v if p not in PLATFORMLAR]
        if bilinmeyen:
            raise ValueError(f"bilinmeyen platform: {', '.join(bilinmeyen)}")
        return [p for p in PLATFORMLAR if p in set(v)]  # katalog sırası, tekil

    @field_validator("test_seviyesi")
    @classmethod
    def _seviye(cls, v: str) -> str:
        if v not in TEST_SEVIYELERI:
            raise ValueError(f"bilinmeyen test seviyesi: {v[:40]}")
        return v

    @field_validator("benimsenen_standartlar")
    @classmethod
    def _standartlar(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for kod in v:
            k = " ".join(str(kod).split())
            if not 1 <= len(k) <= STANDART_UZUNLUK or any(c in k for c in "<>{}`"):
                raise ValueError(
                    f"standart kodu 1–{STANDART_UZUNLUK} karakter olmalı ve <>{{}}` içermemeli"
                )
            if k.casefold() not in {x.casefold() for x in out}:
                out.append(k)
        return out

    @field_validator("kapsam_disi", "roller")
    @classmethod
    def _kirp(cls, v: str) -> str:
        return v.strip()

    @field_validator("ek_bilgi")
    @classmethod
    def _ek_bilgi(cls, v: dict[str, str | bool]) -> dict[str, str | bool]:
        out: dict[str, str | bool] = {}
        for ad, deger in v.items():
            alan = EK_BILGI_ALANLARI.get(ad)
            if alan is None:
                raise ValueError(f"bilinmeyen ek bilgi alanı: {ad[:40]}")
            if alan.tur == "evet_hayir":
                if not isinstance(deger, bool):
                    raise ValueError(f"{ad}: evet/hayır (true/false) olmalı")
                out[ad] = deger
                continue
            if not isinstance(deger, str):
                raise ValueError(f"{ad}: metin olmalı")
            metin = deger.strip()
            sinir = UZUN_METIN_UZUNLUK if alan.tur == "uzun_metin" else METIN_UZUNLUK
            if len(metin) > sinir:
                raise ValueError(f"{ad}: en fazla {sinir} karakter")
            if alan.tur == "secim" and metin and metin not in alan.secenekler:
                raise ValueError(f"{ad}: geçersiz seçim")
            if metin:
                out[ad] = metin
        return out


class SecenekHatasi(WorkflowError):
    """Geçersiz üretim seçeneği (API 422)."""

    status_code = 422

    def __init__(self, hatalar: Sequence[str]) -> None:
        super().__init__("Geçersiz üretim seçeneği: " + "; ".join(hatalar))
        self.hatalar = list(hatalar)


def dogrula(ham: Mapping[str, Any] | None) -> dict[str, Any]:
    """Ham seçenekleri doğrular ve tam (varsayılanlarla tamamlanmış) sözlük döner."""
    try:
        return UretimSecenekleri.model_validate(dict(ham or {})).model_dump()
    except ValidationError as exc:
        raise SecenekHatasi(
            [f"{'.'.join(str(p) for p in e['loc']) or '(kök)'}: {e['msg']}" for e in exc.errors()]
        ) from None


def varsayilan() -> dict[str, Any]:
    return UretimSecenekleri().model_dump()


def kayitli(ham: Any) -> dict[str, Any] | None:
    """Gereksinimde saklı seçenekler (bozuk/eski kayıt → None: bugünkü davranış)."""
    if not isinstance(ham, Mapping) or not ham:
        return None
    try:
        return dogrula(ham)
    except SecenekHatasi:
        return None


def katalog() -> dict[str, Any]:
    """Portal formu için sabit katalog (`GET generation-options`)."""
    return {
        "platformlar": list(PLATFORMLAR),
        "test_seviyeleri": list(TEST_SEVIYELERI),
        "ek_bilgi_alanlari": {ad: a.as_dict() for ad, a in EK_BILGI_ALANLARI.items()},
    }


# ------------------------------------------------------------------ ekler


@dataclass(frozen=True)
class PlatformEki:
    ad: str  # dosya adı / paket kimliği (`platform-web`)
    version: int
    body: str
    hash: str  # sha256 (tam dosya metni)

    @property
    def etiket(self) -> str:
        return f"{self.ad}@v{self.version}"

    def baslik(self) -> str:
        return f"### Platform eki: {self.etiket} (sha256:{self.hash[:12]})"


def ek_yukle(ad: str, rules_dir: Path | None = None) -> PlatformEki:
    from tp_core.gateway.bundle import parse_prompt_file
    from tp_core.gateway.config import find_rules_dir
    from tp_core.gateway.errors import GatewayConfigError

    path = find_rules_dir(rules_dir) / "prompts" / f"{ad}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise GatewayConfigError(f"{path} bulunamadı (platform eki)") from None
    meta, body = parse_prompt_file(text, path)
    if str(meta["id"]) != ad or meta.get("kind") != "platform_ek":
        raise GatewayConfigError(f"{path}: platform eki ön bilgisi (id={ad}, kind: platform_ek)")
    return PlatformEki(ad, int(meta["version"]), body, hashlib.sha256(text.encode()).hexdigest())


def ek_adlari(secenekler: Mapping[str, Any] | None) -> list[str]:
    """Seçili platformların ek paketleri (ortak ek önce; tekil, sıralı). Platform yoksa boş."""
    platformlar = list((secenekler or {}).get("platformlar") or [])
    if not platformlar:
        return []
    return [ORTAK_EK, *sorted({platform_eki(p) for p in platformlar})]


def ekler(secenekler: Mapping[str, Any] | None, rules_dir: Path | None = None) -> list[PlatformEki]:
    return [ek_yukle(ad, rules_dir) for ad in ek_adlari(secenekler)]


def serbest_metin_var(secenekler: Mapping[str, Any] | None) -> bool:
    s = secenekler or {}
    return bool(
        s.get("platformlar")
        or s.get("benimsenen_standartlar")
        or s.get("kapsam_disi")
        or s.get("roller")
        or s.get("ek_bilgi")
    )


def secenek_metni(secenekler: Mapping[str, Any]) -> str:
    """Analistin seçenekleri, eklerin ad ile başvurduğu satırlar olarak (güvenilmeyen blok)."""
    s = secenekler
    satirlar = [
        "Platformlar: " + (", ".join(s.get("platformlar") or []) or "belirtilmedi"),
        "Benimsenen standartlar: " + ("; ".join(s.get("benimsenen_standartlar") or []) or "yok"),
        "Roller ve yetkiler: " + (s.get("roller") or "belirtilmedi"),
        "Kapsam dışı: " + (s.get("kapsam_disi") or "belirtilmedi"),
    ]
    ek = dict(s.get("ek_bilgi") or {})
    if "otomasyon_araci" not in ek:
        satirlar.append("Otomasyon aracı: bilinmiyor")
    for ad, alan in EK_BILGI_ALANLARI.items():
        if ad not in ek:
            continue
        deger = ek[ad]
        if isinstance(deger, bool):
            deger = "evet" if deger else "hayır"
        satirlar.append(f"{alan.etiket}: {deger}")
    return "\n".join(satirlar)


def mesaj_parcalari(
    secenekler: Mapping[str, Any] | None, kaynak: str, tur: str, rules_dir: Path | None = None
) -> list[str]:
    """`generation_messages`'a eklenen parçalar (test seviyesi satırından önce).

    Platform ekleri (güvenilir) + analist seçenekleri (güvenilmeyen blok). Varsayılan seçenekte boş.
    """
    from tp_core.gateway import wrap_untrusted

    if not serbest_metin_var(secenekler):
        return []
    assert secenekler is not None
    parcalar: list[str] = []
    yuklu = ekler(secenekler, rules_dir)
    if yuklu:
        parcalar.append(
            "Platform ekleri (Testing Probe kuralları; talimattır, veri bloğu değildir). "
            "Ekler bir kontrol listesidir, case kotası değildir:"
        )
        parcalar += [f"{e.baslik()}\n{e.body}" for e in yuklu]
    parcalar += [
        "Analistin üretim seçenekleri (platform eklerinin adıyla başvurduğu satırlar):",
        wrap_untrusted(secenek_metni(secenekler), source=f"{kaynak}:secenekler", kind=tur),
    ]
    return parcalar


def ai_call_eki(secenekler: Mapping[str, Any] | None, rules_dir: Path | None = None) -> dict:
    """`ai_call.ek` alanları: kullanılan ekler ve seçenek özeti (serbest metin içermez)."""
    yuklu = ekler(secenekler, rules_dir)
    if not yuklu:
        return {}
    return {
        "platform_ekleri": [
            {"id": e.ad, "version": e.version, "sha256": e.hash[:12]} for e in yuklu
        ],
        "platformlar": list((secenekler or {}).get("platformlar") or []),
    }


def replay_adi(temel: str, secenekler: Mapping[str, Any] | None) -> str:
    """Golden adı: platform eki varsa senaryo golden'ı `platform-<ekler>/<temel>`.

    Ek kısa adları (web, api …) tekil ve sıralı `-` ile birleşir (ör. `platform-api-web/TPD-4`).
    Platformsuz seçenekler golden adını değiştirmez (dalga 1 davranışı; ana golden'ın girdi beyanı
    seçenek bloğunu denetlemez — bkz. rules/replay/README.md).
    """
    adlar = [a for a in ek_adlari(secenekler) if a != ORTAK_EK]
    if not adlar:
        return temel
    return "platform-" + "-".join(a.removeprefix("platform-") for a in adlar) + "/" + temel
