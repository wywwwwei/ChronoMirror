import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram Bot Token from @BotFather")
    ALLOWED_USER_IDS: str = Field(default="", description="Whitelisted Telegram user IDs (comma-separated)")
    TELEGRAM_PROXY: Optional[str] = Field(default=None, description="HTTP/SOCKS5 proxy, e.g. http://127.0.0.1:7890")

    # LLM Provider Configuration
    DEFAULT_LLM_PROVIDER: str = Field(default="gemini", description="'gemini' or 'openai'")

    # Gemini API Settings
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API Key")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash", description="Gemini model for text & multi-modal processing")

    # OpenAI-compatible API Settings
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI or compatible provider API Key")
    OPENAI_BASE_URL: Optional[str] = Field(default=None, description="Custom Base URL, e.g. https://api.deepseek.com/v1")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini", description="Model for review and text reasoning")
    OPENAI_VISION_MODEL: str = Field(default="gpt-4o-mini", description="Vision model for image feature extraction")
    OPENAI_WHISPER_MODEL: str = Field(default="whisper-1", description="Audio transcription model")

    # Scheduler Settings
    DAILY_REVIEW_TIME: str = Field(default="23:00", description="Daily review time, HH:MM format")
    WEEKLY_REVIEW_DAY: str = Field(default="sun", description="Day of week for weekly review (mon-sun)")
    WEEKLY_REVIEW_TIME: str = Field(default="22:00", description="Weekly review time, HH:MM format")
    TIMEZONE: str = Field(default="Asia/Shanghai", description="Local timezone")

    # Storage Paths
    VAULT_DIR: Path = Field(default=BASE_DIR / "vault")

    @property
    def allowed_user_ids_list(self) -> List[int]:
        if not self.ALLOWED_USER_IDS:
            return []
        return [int(uid.strip()) for uid in str(self.ALLOWED_USER_IDS).split(",") if uid.strip().isdigit()]

    @property
    def logs_dir(self) -> Path:
        p = self.VAULT_DIR / "logs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def attachments_dir(self) -> Path:
        p = self.VAULT_DIR / "attachments"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def daily_reviews_dir(self) -> Path:
        p = self.VAULT_DIR / "reviews" / "daily"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def weekly_reviews_dir(self) -> Path:
        p = self.VAULT_DIR / "reviews" / "weekly"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def memory_dir(self) -> Path:
        p = self.VAULT_DIR / "memory"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def user_profile_path(self) -> Path:
        return self.memory_dir / "user_profile.md"

settings = Settings()
