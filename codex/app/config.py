from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    confidence_threshold: float = 0.7
    max_clarification_turns: int = 5
    session_ttl_seconds: int = 1800

    database_url: str = "sqlite+aiosqlite:///./warbrain.db"

    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
