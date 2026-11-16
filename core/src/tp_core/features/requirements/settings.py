"""Gereksinim özelliğinin ayarları (proje config'i + kurulum ortamı; TP-COK-PROJE-PLANI §3)."""

from __future__ import annotations

import threading
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tp_core.proje import varsa, varsayilan_pid
from tp_core.proje.ayar import PROJE_ANAHTARLARI, ayar, surum

PO_PENDING_LABEL = "tp-po-pending"
PO_APPROVED_LABEL = "tp-po-approved"
AI_LABEL = "AI-generated"


class RequirementsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    jira_project: str = Field(default="TPD", validation_alias="JIRA_PROJECT")
    # Test edilen uygulamanın salt okuma veritabanı (demoapp_ro rolü). Boşsa veri araçları
    # "yapılandırılmamış" hatası döner; kod araçları ve iç tutarlılık yine çalışır.
    demoapp_ro_database_url: str | None = Field(
        default=None, validation_alias="DEMOAPP_RO_DATABASE_URL"
    )
    # PO etiketinin sorgulanma aralığı (TEKNIK-TASARIM §2.1: 15 sn).
    po_poll_s: float = Field(default=15.0, validation_alias="TP_PO_POLL_S")
    # Tutarlılık denetimi döngüsünün en fazla tur sayısı (§8.2b adım 7).
    max_rounds: int = Field(default=3, validation_alias="TP_CONSISTENCY_MAX_ROUNDS")
    # Kod kanıtındaki depo adı (`evidence.repo`); forge tek depo sunar.
    forge_repo: str = Field(default="demo-app", validation_alias="TP_FORGE_REPO_NAME")
    forge_ref: str = Field(default="main", validation_alias="TP_FORGE_CHECK_REF")

    @field_validator("jira_project", mode="before")
    @classmethod
    def _proje(cls, v: object) -> object:
        return v or "TPD"

    @field_validator("demoapp_ro_database_url", mode="before")
    @classmethod
    def _bos(cls, v: object) -> object:
        return v or None


def _kur() -> RequirementsSettings:
    """Proje/ürün ayarları (`PROJE_ANAHTARLARI`) bağlamdaki projenin config'inden, kurulum
    ayarları (`TP_PO_POLL_S`) ortamdan. Proje ayarı yoksa alan varsayılanı açıkça verilir: başka
    projenin değeri süreç ortamından sızmaz (TP-COK-PROJE-PLANI §3.2)."""
    degerler: dict[str, Any] = {}
    for alan in RequirementsSettings.model_fields.values():
        ad = alan.validation_alias
        if isinstance(ad, str) and ad in PROJE_ANAHTARLARI:
            deger = ayar(ad)
            degerler[ad] = alan.default if deger is None else deger
    return RequirementsSettings(**degerler)


class _ProjeOnbellegi:
    """`(pid, config sürümü)` anahtarlı önbellek (`lru_cache` yerine; §3.2). `cache_clear`
    eski arayüzle uyumludur (testler)."""

    def __init__(self) -> None:
        self._kilit = threading.Lock()
        self._kayit: dict[tuple[str, str], RequirementsSettings] = {}

    def __call__(self) -> RequirementsSettings:
        sur = surum()
        b = varsa()
        anahtar = (b.pid if b is not None else varsayilan_pid(), sur)
        with self._kilit:
            deger = self._kayit.get(anahtar)
        if deger is None:
            deger = _kur()
            with self._kilit:
                for k in [k for k in self._kayit if k[0] == anahtar[0]]:
                    del self._kayit[k]
                self._kayit[anahtar] = deger
        return deger

    def cache_clear(self) -> None:
        with self._kilit:
            self._kayit.clear()


get_requirements_settings = _ProjeOnbellegi()
