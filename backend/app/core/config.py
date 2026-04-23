from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Binance Futures Auto Trading Platform"
    app_env: str = "local"

    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/binance_auto_trader"
    test_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    binance_futures_base_url: str = "https://fapi.binance.com"
    binance_futures_testnet_base_url: str = "https://testnet.binancefuture.com"

    encryption_key: str = "change_me"

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    enable_metrics: bool = True

    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
