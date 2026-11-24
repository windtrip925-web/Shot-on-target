from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    OWNER_PASSWORD: str
    CORS_ORIGIN: str = "http://localhost:3000"
    MODE_UJI: bool = False
    JAM_MULAI: int = 8
    JAM_SELESAI: int = 15
    HARI_LIBUR: int = 6
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-5-5"
    RSS_FEEDS: str = ""
    NEWS_API_KEY: str = ""
    PEXELS_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()