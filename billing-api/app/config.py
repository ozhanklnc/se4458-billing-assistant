from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://billing:billing@localhost:5432/billing"

    # HS256 secret shared with the API gateway (Kong validates the same signature).
    jwt_secret: str = "change-me-in-production-please-32b"
    jwt_issuer: str = "billing-api"
    jwt_expire_minutes: int = 60

    # When set, every request (except /health) must carry X-Gateway-Secret with this value.
    # Kong adds the header, so calls that skip the gateway are rejected with 403.
    gateway_secret: str = ""

    # Pricing constants (see Mobile_Provider_Billing_Guide.md, section 3 and 4)
    free_phone_minutes: int = 1000
    phone_block_minutes: int = 1000
    phone_block_price: int = 10
    internet_base_price: int = 50
    internet_included_mb: int = 20_000
    internet_block_mb: int = 10_000
    internet_block_price: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
