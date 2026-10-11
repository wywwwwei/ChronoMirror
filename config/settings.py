import datetime
import logging
import os
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

# ALLOWED_USER_IDS 写 "*" 表示显式声明"公开模式"（对所有人开放）
PUBLIC_MODE_SENTINEL = "*"

# TIMEZONE 写错时的兜底时区，避免整个进程因一个环境变量启动失败
FALLBACK_TIMEZONE = "Asia/Shanghai"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram Bot Token from @BotFather")
    ALLOWED_USER_IDS: str = Field(
        default="",
        description="Whitelisted Telegram user IDs (comma-separated). '*' means explicit public mode."
    )
    TELEGRAM_PROXY: Optional[str] = Field(default=None, description="HTTP/SOCKS5 proxy, e.g. http://127.0.0.1:7890")

    # LLM Provider Configuration
    DEFAULT_LLM_PROVIDER: str = Field(default="gemini", description="'gemini' or 'openai'")

    # Gemini API Settings
    # 模型按用途拆两档：capture 是每条语音/照片都触发的采集，review 是每天/每周才跑一次的复盘。
    # 免费档的每日额度按 project 共享，采集用强档几个人就能打爆，所以默认分档。
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API Key")
    # 已废弃，仅用于兼容存量 .env：值会被映射到下面两个新档位上（见 model_validator）
    GEMINI_MODEL: Optional[str] = Field(default=None, description="[DEPRECATED] use GEMINI_CAPTURE_MODEL / GEMINI_REVIEW_MODEL")

    GEMINI_CAPTURE_MODEL: str = Field(
        default="gemini-3.5-flash-lite",
        description="Gemini model for high-frequency capture (audio transcription & image description)"
    )
    GEMINI_REVIEW_MODEL: str = Field(
        default="gemini-3.8-flash",
        description="Gemini model for low-frequency reviews (daily/weekly review & L3 profile evolution)"
    )

    # OpenAI-compatible API Settings
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI or compatible provider API Key")
    OPENAI_BASE_URL: Optional[str] = Field(default=None, description="Custom Base URL, e.g. https://api.siliconflow.cn/v1")
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
    # 运行日志落盘目录。刻意不放在 vault/ 下：vault/logs 是用户的日记流水账
    # （要给人看、被 Obsidian 索引），运行日志是给排障看的、会被轮转删掉。
    # 两者混在一起，Obsidian 会把日志当笔记索引，"日志"这个词也会指代两件事。
    LOG_DIR: Path = Field(default=BASE_DIR / "logs")

    @property
    def tzinfo(self) -> datetime.tzinfo:
        """TIMEZONE 的解析结果。写错时回退默认时区并告警，不让进程起不来。"""
        try:
            return ZoneInfo(self.TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            logger.warning(f"TIMEZONE={self.TIMEZONE!r} 无法识别，本次回退为 {FALLBACK_TIMEZONE}")
            return ZoneInfo(FALLBACK_TIMEZONE)

    def now(self) -> datetime.datetime:
        """当前时间（带 TIMEZONE 时区）。

        全项目统一的时间来源：日志文件名、复盘日期、附件目录都必须用它，
        否则定时任务按 TIMEZONE 触发、文件却按宿主机（常见是 UTC）时间命名，
        就会出现"复盘推的是昨天 / 写进今天的文件"这类错位。
        """
        return datetime.datetime.now(self.tzinfo)

    def today(self) -> datetime.date:
        return self.now().date()

    @model_validator(mode="after")
    def _migrate_legacy_gemini_model(self):
        """兼容旧的单档 GEMINI_MODEL：映射到两个新档位，避免存量部署无声换模型。

        必须把它保留成一个真实字段才读得到：model_config 是 extra="ignore"，
        而 pydantic-settings 会在任何 mode="before" 校验器之前就把未知键过滤掉
        （实测 before 校验器拿到的是空 dict），所以"删字段 + before 校验器"这条路走不通。

        用 model_fields_set 区分"部署者显式写了新变量"和"只是拿到了默认值"，
        显式写的那个不被旧值覆盖。
        """
        legacy = (self.GEMINI_MODEL or "").strip()
        if not legacy:
            return self

        explicit = self.model_fields_set
        if "GEMINI_CAPTURE_MODEL" not in explicit:
            self.GEMINI_CAPTURE_MODEL = legacy
        if "GEMINI_REVIEW_MODEL" not in explicit:
            self.GEMINI_REVIEW_MODEL = legacy
        logger.warning(
            f"GEMINI_MODEL 已拆分为 GEMINI_CAPTURE_MODEL 与 GEMINI_REVIEW_MODEL，"
            f"本次按旧值 {legacy!r} 应用于未显式设置的档位。请更新 .env 后删除 GEMINI_MODEL。"
        )
        return self

    @field_validator("DEFAULT_LLM_PROVIDER")
    @classmethod
    def _validate_default_provider(cls, v: str) -> str:
        value = (v or "gemini").strip().lower()
        if value not in ("gemini", "openai"):
            raise ValueError("DEFAULT_LLM_PROVIDER 只支持 'gemini' 或 'openai'")
        return value

    @property
    def allowed_user_ids_list(self) -> List[int]:
        """白名单用户 ID 列表。空列表表示公开模式（见 is_public_mode）。"""
        if not self.ALLOWED_USER_IDS:
            return []
        raw = str(self.ALLOWED_USER_IDS)
        if PUBLIC_MODE_SENTINEL in raw:
            return []
        return [int(uid.strip()) for uid in raw.split(",") if uid.strip().isdigit()]

    @property
    def has_explicit_public_mode(self) -> bool:
        """是否用 ALLOWED_USER_IDS='*' 显式声明了公开模式"""
        return PUBLIC_MODE_SENTINEL in str(self.ALLOWED_USER_IDS or "")

    @property
    def is_public_mode(self) -> bool:
        return not self.allowed_user_ids_list

    def is_user_allowed(self, user_id: int) -> bool:
        """白名单校验的唯一入口。公开模式（未配置白名单或写 '*'）放行所有人。"""
        allowed = self.allowed_user_ids_list
        if not allowed:
            return True
        return user_id in allowed

    @property
    def env_llm_keys_configured(self) -> bool:
        return bool(self.GEMINI_API_KEY or self.OPENAI_API_KEY)

    @property
    def env_key_fallback_enabled(self) -> bool:
        """环境变量里的全局 LLM Key 是否可作为用户兜底 Key。

        仅在私有（白名单）模式下启用：公开模式下若允许兜底，任何陌生人都能消耗
        部署者自己的 API 额度。
        """
        return (not self.is_public_mode) and self.env_llm_keys_configured

    def env_key_for(self, provider: str) -> Optional[str]:
        provider = (provider or "").strip().lower()
        if provider == "gemini":
            return self.GEMINI_API_KEY
        if provider == "openai":
            return self.OPENAI_API_KEY
        return None

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

if settings.TELEGRAM_PROXY:
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ[k] = settings.TELEGRAM_PROXY

