# Pydantic-settings

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # App
    app_name: str = "URL Shortener"
    debug: bool = False
    base_url: str = "http://localhost:8000"
    
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/urlshortener"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Rate limiting
    shorten_rate_limit_calls: int = 10
    shorten_rate_limit_period: int = 60  # seconds
    redirect_rate_limit_calls: int = 60
    redirect_rate_limit_period: int = 60  # seconds
    
# Single import across the entire app
settings = Settings()