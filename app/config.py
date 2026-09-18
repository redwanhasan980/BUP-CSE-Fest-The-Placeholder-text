from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_primary_api_key: str = ""
    llm_primary_base_url: str = "https://api.groq.com/openai/v1"
    llm_primary_model: str = "openai/gpt-oss-120b"

    llm_secondary_api_key: str = ""
    llm_secondary_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_secondary_model: str = "gemini-2.0-flash"

    llm_timeout_seconds: float = 8.0
    llm_max_repair_attempts: int = 1
    enable_rule_fallback: bool = True
    request_deadline_seconds: float = 25.0
    port: int = 8000
    log_level: str = "INFO"


settings = Settings()
