"""Application settings (spec M0.1, M0.2).

All env vars from .env.example are declared here. Modules import `settings`
rather than reading os.environ directly.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/wanderguard"

    LINE_CHANNEL_SECRET: str = ""
    LINE_CHANNEL_ACCESS_TOKEN: str = ""
    WEB_APP_URL: str = "http://localhost:3000"

    GOOGLE_MAPS_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    CWB_API_KEY: str = ""

    REDIS_URL: str = "redis://localhost:6379"

    # M2: optional cookies file path (Netscape format) for yt-dlp to bypass
    # Instagram's anonymous-fetch rate limit. Empty → anonymous download.
    IG_COOKIES_PATH: str = ""


settings = Settings()
