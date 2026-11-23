"""Gereksinim özelliğinin ayarları (proje config'i + kurulum ortamı; TP-COK-PROJE-PLANI §3)."""

from __future__ import annotations

import threading
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tp_core.proje import varsa, varsayilan_pid
from tp_core.proje.ayar import PROJE_ANAHTARLARI, ayar, home_kaynakli_mi, surum
from tp_core.veri.ro_baglanti import BaglantiTanimi, cozumle

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
    # Ayrı alanlar (çoklu DB; Home `env.db.*`). Bağlantı dizesi doluysa onun önüne geçemez.
    ro_db_type: str | None = Field(default=None, validation_alias="TP_RO_DB_TYPE")
    ro_db_host: str | None = Field(default=None, validation_alias="TP_RO_DB_HOST")
    ro_db_port: str | None = Field(default=None, validation_alias="TP_RO_DB_PORT_NO")
    ro_db_name: str | None = Field(default=None, validation_alias="TP_RO_DB_NAME")
    ro_db_user: str | None = Field(default=None, validation_alias="TP_RO_DB_USER")
    # Sır: repr/log'da görünmez.
    ro_db_password: SecretStr | None = Field(default=None, validation_alias="TP_RO_DB_PASSWORD")
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

    @field_validator(
        "demoapp_ro_database_url",
        "ro_db_type",
        "ro_db_host",
        "ro_db_port",
        "ro_db_name",
        "ro_db_user",
        "ro_db_password",
        mode="before",
    )
    @classmethod
    def _bos(cls, v: object) -> object:
        return v or None

    def ro_baglanti(self) -> BaglantiTanimi | None:
        """Salt okuma test verisi bağlantısı (tek çözüm yeri: `tp_core.veri.ro_baglanti`).
        Geçersiz yapılandırma `BaglantiHatasi` verir; hiçbiri yoksa None."""
        return cozumle(
            url=self.demoapp_ro_database_url,
            tur=self.ro_db_type,
            host=self.ro_db_host,
            port=self.ro_db_port,
            ad=self.ro_db_name,
            kullanici=self.ro_db_user,
            parola=self.ro_db_password.get_secret_value() if self.ro_db_password else None,
        )

    def ro_yapilandirildi(self) -> bool:
        return bool(self.demoapp_ro_database_url or self.ro_db_type)


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
    # Home kipi: veritabanı ayrı alanları (`env.db.*`) Home'dan geliyorsa, Home'un kendisi
    # vermediği bağlantı dizesi (Deployment'ın sabit `DEMOAPP_RO_DATABASE_URL`'i) onların önüne
    # geçmez. Home bu alanları vermiyorsa bağlantı dizesi bugünkü gibi yedek kalır.
    if (
        degerler.get("DEMOAPP_RO_DATABASE_URL")
        and home_kaynakli_mi("TP_RO_DB_TYPE")
        and not home_kaynakli_mi("DEMOAPP_RO_DATABASE_URL")
    ):
        degerler["DEMOAPP_RO_DATABASE_URL"] = None
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
