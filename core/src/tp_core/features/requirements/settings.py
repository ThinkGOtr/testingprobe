"""Gereksinim özelliğinin ayarları (ortam değişkenleri)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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


@lru_cache
def get_requirements_settings() -> RequirementsSettings:
    return RequirementsSettings()
