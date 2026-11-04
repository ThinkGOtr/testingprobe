"""Asistan araçları (AI-ASISTAN-PLANI §5) ve 13 aracın tek kayıt defteri.

Yeni araçlar ham metin döndürür; sır temizleme (`scrub_secret_patterns`), maskeleme, kanıt havuzu
ve `<untrusted>` sarma ortak sarmalayıcıdadır (`tools.base`, §5.0). Rol kısıtı araç uygulamasında,
iş yükündeki kullanıcıyla (asla argümandan). Tüm roller aynı araç listesini görür.

- `product` — `product_search`, `product_read`: core-worker'a salt okunur bağlanan ürün bilgi
  paketi (`/opt/tp-bilgi`, MANIFEST birebir).
- `probe` — `probe_get`, `probe_list`, `probe_jobs`, `probe_audit`, `probe_my_queue`: portal GET
  uçlarının servis/serileştirme fonksiyonları, uç-düzeyi rol kısıtları ve alan izin listesiyle.
- `jira` — `jira_issue` (Şerit J); `ci` — `ci_log` (Şerit J).
- Mevcut dört araç: `search_code`, `get_file_contents` (`CodeTools`, test edilen uygulamanın
  forge'u) ve `db_schema`, `db_query` (`DataTools`, mesajın maskeleme oturumuyla).

Kullanım (işleyici, mesaj başına)::

    oturum = mesaj_oturumu()                       # features.assistant.maskeleme
    baglam = arac_baglami(kullanici_id, rol, oturum, bitis=bitis)
    araclar = arac_seti(baglam)
    gw.run_agent(..., tools=araclar.specs, execute=araclar.execute, masking_session=oturum)
    ...  # §7.3: araclar.havuz.al("k3", "probe_verisi")
    araclar.havuz.temizle()
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from tp_core.features.assistant.tools.base import (
    Arac,
    AracBaglami,
    AracHatasi,
    AracSarmalayici,
    AracSonucu,
    KanitHavuzu,
    KanitTuru,
    MevcutArac,
)
from tp_core.gateway.masking import MaskingSession
from tp_core.ports import ToolSpec

# Geçidin `ALLOWED_AGENT_TOOLS["assistant"]` kümesiyle birebir (test eşitliği denetler).
ARAC_ADLARI: tuple[str, ...] = (
    "product_search",
    "product_read",
    "probe_get",
    "probe_list",
    "probe_jobs",
    "probe_audit",
    "probe_my_queue",
    "jira_issue",
    "ci_log",
    "search_code",
    "get_file_contents",
    "db_schema",
    "db_query",
)
MEVCUT_TURLERI: dict[str, KanitTuru] = {
    "search_code": "uygulama_kodu",
    "get_file_contents": "uygulama_kodu",
    "db_schema": "uygulama_verisi",
    "db_query": "uygulama_verisi",
}
VERI_ROLLERI_ORTAM = "TP_ASISTAN_VERI_ROLLERI"
VERI_ARACLARI = ("db_schema", "db_query")


def veri_rolleri(environ: Mapping[str, str] | None = None) -> frozenset[str] | None:
    """`TP_ASISTAN_VERI_ROLLERI` (virgüllü rol listesi); boş/tanımsız → tüm roller (None)."""
    env = os.environ if environ is None else environ
    roller = frozenset(
        r.strip() for r in (env.get(VERI_ROLLERI_ORTAM) or "").split(",") if r.strip()
    )
    return roller or None


def arac_baglami(
    kullanici_id: uuid.UUID,
    rol: str,
    oturum: MaskingSession,
    *,
    db: Callable[[], Session] | None = None,
    bitis: float | None = None,
    sir_degerleri: tuple[str, ...] | None = None,
) -> AracBaglami:
    """Mesaj başına bağlam; sır değerleri verilmezse ortamdan (`known_secret_values`)."""
    if db is None:
        from tp_core.models import new_session

        db = new_session
    if sir_degerleri is None:
        from tp_core.gateway.factory import known_secret_values

        sir_degerleri = tuple(known_secret_values())
    return AracBaglami(
        kullanici_id=kullanici_id,
        rol=rol,
        oturum=oturum,
        db=db,
        bitis=bitis,
        sir_degerleri=sir_degerleri,
    )


# ------------------------------------------------------------------ mevcut araçların kurulumu


class _Tembel:
    """Mevcut araç nesnesini ilk çağrıda kurar (forge `head_sha` ağ çağrısı yalnız gerekirse)."""

    def __init__(self, kur: Callable[[], Any]) -> None:
        self._kur = kur
        self._nesne: Any = None

    def metot(self, ad: str) -> MevcutArac:
        def cagir(args: dict[str, Any]) -> str:
            if self._nesne is None:
                self._nesne = self._kur()
            return str(getattr(self._nesne, ad)(args))

        return cagir


def kod_araclari() -> Any:
    """§5.3: `CodeTools(requirements.services.forge(), sha=forge.head_sha(ayar.forge_ref),
    repo=ayar.forge_repo)` — test edilen uygulamanın kökü (`features/ci/services.forge()` değil)."""
    from tp_core.features.requirements import services
    from tp_core.features.requirements.codetools import CodeTools
    from tp_core.features.requirements.settings import get_requirements_settings

    ayar = get_requirements_settings()
    forge = services.forge()
    return CodeTools(forge, forge.head_sha(ayar.forge_ref), ayar.forge_repo)


def veri_araclari(oturum: MaskingSession) -> Any:
    """§5.3: `DataTools(DemoDb(...), session=oturum)` — mesajın tek maskeleme oturumu."""
    from tp_core.features.requirements import services
    from tp_core.features.requirements.datatools import DataTools

    return DataTools(services.demo_db(), session=oturum)


def _kurucu(deger: Any, metot: str, varsayilan: Callable[[], Any]) -> Callable[[], Any]:
    """Nesne (`metot`'u olan) → sabit; fonksiyon → kurucu; None → varsayılan kurulum."""
    if deger is None:
        return varsayilan
    if hasattr(deger, metot):
        return lambda: deger
    return deger


def _rol_kisitli(ad: str, izinli: frozenset[str], rol: str, asil: MevcutArac) -> MevcutArac:
    def cagir(args: dict[str, Any]) -> str:
        if rol not in izinli:
            raise AracHatasi(f"{ad} bu kurulumda rolünüze açık değil")
        return asil(args)

    return cagir


# ------------------------------------------------------------------ ürün araçları uyarlayıcısı


def _urun_araclari(urun: Any) -> dict[str, Arac]:
    def product_search(_baglam: AracBaglami, **arg: Any) -> AracSonucu:
        return AracSonucu(urun.product_search(arg), kanit_turu="urun_kodu", tur="code")

    def product_read(_baglam: AracBaglami, **arg: Any) -> AracSonucu:
        yol = arg.get("path") if isinstance(arg.get("path"), str) else None
        return AracSonucu(
            urun.product_read(arg),
            kanit_turu="urun_kodu",
            tur="code",
            kaynak=(yol or "")[:120] or None,
        )

    return {"product_search": product_search, "product_read": product_read}


# ------------------------------------------------------------------ fabrika


@dataclass
class AracSeti:
    """Geçide verilecek araç tanımları + yürütücü + mesajın kanıt havuzu."""

    specs: list[ToolSpec]
    execute: AracSarmalayici
    havuz: KanitHavuzu

    @property
    def adlar(self) -> frozenset[str]:
        return frozenset(s.name for s in self.specs)


def tool_specs() -> list[ToolSpec]:
    """13 aracın tanımı, `ARAC_ADLARI` sırasıyla."""
    from tp_core.features.assistant.tools import ci, jira, probe, product
    from tp_core.features.requirements.codetools import TOOL_SPECS as MEVCUT_SPECS

    tum = {
        s.name: s
        for s in (
            *product.TOOL_SPECS,
            *probe.TOOL_SPECS,
            *jira.TOOL_SPECS,
            *ci.TOOL_SPECS,
            *MEVCUT_SPECS,
        )
    }
    eksik = [ad for ad in ARAC_ADLARI if ad not in tum]
    if eksik:
        raise RuntimeError(f"asistan araç tanımı eksik: {eksik}")
    return [tum[ad] for ad in ARAC_ADLARI]


def arac_seti(
    baglam: AracBaglami,
    *,
    urun: Any = None,
    kod: Callable[[], Any] | Any = None,
    veri: Callable[[], Any] | Any = None,
    yeni_araclar: Mapping[str, Arac] | None = None,
    veri_rol_listesi: frozenset[str] | None = None,
) -> AracSeti:
    """Rol ve bağlamla 13 araçlık set: aynı tanımlar her role; rol kısıtı uygulamada.

    - `urun`: `UrunBilgisi` (vars. `/opt/tp-bilgi`).
    - `kod`, `veri`: `CodeTools`/`DataTools` nesnesi ya da onu kuran fonksiyon (vars. §5.3
      kurulumu; ilk çağrıda kurulur). `veri` verilmezse mesajın oturumuyla `DataTools`.
    - `yeni_araclar`: testler/eval için yeni araç uygulamalarını değiştirir (ör. sahte
      `jira_issue`).
    - `veri_rol_listesi`: `db_*` araçlarının izinli rolleri (vars. `TP_ASISTAN_VERI_ROLLERI`).
    """
    from tp_core.features.assistant.tools import ci, jira, probe
    from tp_core.features.assistant.tools.product import ProductToolError, UrunBilgisi
    from tp_core.features.requirements.codetools import CodeToolError
    from tp_core.features.requirements.datatools import DataToolError
    from tp_core.features.requirements.sqlguard import QueryRejected

    yeni: dict[str, Arac] = {
        **_urun_araclari(urun if urun is not None else UrunBilgisi()),
        **probe.ARACLAR,
        "jira_issue": jira.jira_issue,
        "ci_log": ci.ci_log,
    }
    yeni.update(yeni_araclar or {})

    kod_t = _Tembel(_kurucu(kod, "search_code", kod_araclari))
    veri_t = _Tembel(_kurucu(veri, "db_query", lambda: veri_araclari(baglam.oturum)))
    mevcut: dict[str, MevcutArac] = {
        "search_code": kod_t.metot("search_code"),
        "get_file_contents": kod_t.metot("get_file_contents"),
        "db_schema": veri_t.metot("db_schema"),
        "db_query": veri_t.metot("db_query"),
    }
    izinli = veri_rol_listesi if veri_rol_listesi is not None else veri_rolleri()
    if izinli is not None:
        for ad in VERI_ARACLARI:
            mevcut[ad] = _rol_kisitli(ad, izinli, baglam.rol, mevcut[ad])

    havuz = KanitHavuzu()
    execute = AracSarmalayici(
        baglam,
        yeni=yeni,
        mevcut=mevcut,
        mevcut_turleri=MEVCUT_TURLERI,
        guvenli_hatalar=(ProductToolError, CodeToolError, DataToolError, QueryRejected),
        havuz=havuz,
    )
    specs = tool_specs()
    if execute.adlar != frozenset(ARAC_ADLARI):
        raise RuntimeError("asistan araç seti tanımlarla uyuşmuyor")
    return AracSeti(specs=specs, execute=execute, havuz=havuz)


__all__ = [
    "ARAC_ADLARI",
    "AracBaglami",
    "AracHatasi",
    "AracSarmalayici",
    "AracSeti",
    "AracSonucu",
    "KanitHavuzu",
    "arac_baglami",
    "arac_seti",
    "kod_araclari",
    "tool_specs",
    "veri_araclari",
    "veri_rolleri",
]
