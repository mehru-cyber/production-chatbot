from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    
   # required
    openai_api_key: str
    database_url: str
    jwt_secret_key: str

    llm_base_url: str | None = None
    chat_model: str = "gpt-4o-mini"

    # recommended / optional integrations
    finnhub_api_key: str | None = None
    alpaca_api_key_id: str | None = None
    alpaca_api_secret_key: str | None = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # app tuning
    access_token_expire_minutes: int = 30
    rate_limit_per_minute: int = 20
    daily_token_cap: int = 200_000
    stm_trim_message_threshold: int = 6
    stm_keep_last_n: int = 2
    cors_allowed_origins: str = "http://localhost:8000"

    jwt_algorithm: str = "HS256"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def alpaca_configured(self) -> bool:
        return bool(self.alpaca_api_key_id and self.alpaca_api_secret_key)

    @property
    def finnhub_configured(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


settings = Settings()
