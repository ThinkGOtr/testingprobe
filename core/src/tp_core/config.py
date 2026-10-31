"""Çekirdek yapılandırması (ortam değişkenleri, MIMARI-SOZLESME §6).

Yalnızca `TP_DATABASE_URL` zorunludur; diğer alanların demo için güvenli varsayılanları vardır.
Oturum sırrı (`TP_SESSION_SECRET`) yalnızca oturum açan/okuyan uçlarda istenir; yoksa bu uçlar
503 döner (core-worker ve migrate sırra ihtiyaç duymaz).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def libpq_auth_zorla(url: str, yontem: str | None) -> str:
    """Postgres URL'sine `require_auth=<yontem>` ekler (URL kendi değerini taşıyorsa dokunmaz).

    `postgres` adı çözülemediğinde (Docker yeniden başlatma yarışı, DB kapalı) Docker DNS'i adı
    LAN/kurumsal çözücüye iletebilir; libpq sunucu ne isterse (cleartext dahil) parolayı verir.
    SCRAM zorunluysa parola ağa hiç çıkmaz ve sahte sunucu kimlik doğrulamayı tamamlayamaz.
    """
    yontem = (yontem or "").strip()
    if not yontem or not url.startswith("postgresql"):
        return url
    u = make_url(url)
    if "require_auth" in u.query:
        return url
    return u.update_query_dict({"require_auth": yontem}).render_as_string(hide_password=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    database_url: str = Field(validation_alias="TP_DATABASE_URL")
    # libpq `require_auth`: varsayılan SCRAM (pg_hba scram-sha-256). Boş = zorlanmaz (ör. trust
    # kullanan yerel bir geliştirme veritabanı). URL kendi `require_auth`'unu taşıyorsa o geçerli.
    db_require_auth: str = Field(default="scram-sha-256", validation_alias="TP_DB_REQUIRE_AUTH")
    seed_user_password: SecretStr | None = Field(
        default=None, validation_alias="SEED_USER_PASSWORD"
    )

    # --- Oturum ve kimlik
    session_secret: SecretStr | None = Field(default=None, validation_alias="TP_SESSION_SECRET")
    session_max_age_s: int = Field(default=12 * 3600, validation_alias="TP_SESSION_MAX_AGE_S")
    # Yerel demo http üzerinden çalışır; TLS arkasında True yapılır.
    session_cookie_secure: bool = Field(default=False, validation_alias="TP_SESSION_COOKIE_SECURE")
    api_token_ttl_s: int = Field(default=8 * 3600, validation_alias="TP_API_TOKEN_TTL_S")
    # Gerçek istemci adresini X-Forwarded-For'dan almaya yetkili ters proxy'ler (virgülle: IP,
    # CIDR veya ad; ad DNS'te çözülür). Yalnızca bağlantı bu adreslerden geliyorsa XFF'nin EN SAĞ
    # öğesi (proxy'nin gördüğü eş) kullanılır; 127.0.0.1:8000'e doğrudan gelen XFF yok sayılır.
    trusted_proxies: str = Field(default="review-portal", validation_alias="TP_TRUSTED_PROXIES")
    # CSRF savunması (api/csrf.py): Sec-Fetch-Site göndermeyen tarayıcıların güvensiz isteklerinde
    # kabul edilen Origin'ler (virgülle). Portal başka bir adresten sunuluyorsa buraya eklenir.
    allowed_origins: str = Field(
        default="http://127.0.0.1:8080,http://localhost:8080",
        validation_alias="TP_ALLOWED_ORIGINS",
    )

    # --- Dış sistem seçimi (port + adaptör + simülatör)
    model_mode: Literal["auto", "live", "replay", "record"] = Field(
        default="auto", validation_alias="TP_MODEL_MODE"
    )
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    jira_base_url: str = Field(default="http://jira-sim:8090", validation_alias="JIRA_BASE_URL")
    jira_project: str = Field(default="TPD", validation_alias="JIRA_PROJECT")
    # Ürünün kendi Jira kimlikleri: PO onayı (etiket) bu kimliklerden gelirse reddedilir.
    jira_read_email: str | None = Field(default=None, validation_alias="JIRA_READ_EMAIL")
    jira_write_email: str | None = Field(default=None, validation_alias="JIRA_WRITE_EMAIL")
    # Virgülle ayrılmış bot accountId'leri (gerçek Jira changelog'u e-posta değil accountId verir).
    jira_bot_account_ids: str = Field(default="", validation_alias="TP_JIRA_BOT_ACCOUNT_IDS")
    # Virgülle ayrılmış PO Jira kimlikleri (e-posta/accountId); boş = liste denetimi yok.
    po_jira_users: str = Field(default="", validation_alias="TP_PO_JIRA_USERS")
    test_mgmt: Literal["jira", "xray"] = Field(default="jira", validation_alias="TP_TEST_MGMT")
    forge: Literal["local", "github"] = Field(default="local", validation_alias="TP_FORGE")
    forge_path: str = Field(default="/forge/demo-app.git", validation_alias="TP_FORGE_PATH")
    github_repo: str | None = Field(default=None, validation_alias="GITHUB_REPO")
    toolchain_url: str = Field(
        default="http://toolchain-worker:8100", validation_alias="TOOLCHAIN_URL"
    )
    playwright_mcp_url: str = Field(
        default="http://playwright-mcp:8931/mcp", validation_alias="PLAYWRIGHT_MCP_URL"
    )
    artifacts_path: str = Field(default="/artifacts", validation_alias="TP_ARTIFACTS_PATH")
    # IDE (Claude Code) kanalının kullanıcıya gösterilen MCP adresi (tarayıcı/IDE'den erişilebilir).
    mcp_public_url: str = Field(
        default="http://127.0.0.1:8000/mcp", validation_alias="TP_MCP_PUBLIC_URL"
    )

    # --- Maliyet tavanı (TEKNIK-TASARIM §8.8)
    daily_budget_usd: float = Field(default=30.0, validation_alias="TP_DAILY_BUDGET_USD")
    workflow_budget_usd: float = Field(default=2.0, validation_alias="TP_WORKFLOW_BUDGET_USD")

    # --- Worker
    worker_poll_interval_s: float = Field(default=1.0, validation_alias="TP_WORKER_POLL_S")

    @model_validator(mode="after")
    def _db_auth(self) -> "Settings":
        self.database_url = libpq_auth_zorla(self.database_url, self.db_require_auth)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
