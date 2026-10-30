from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = Field(validation_alias="TP_DATABASE_URL")
    seed_user_password: SecretStr | None = Field(
        default=None, validation_alias="SEED_USER_PASSWORD"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
