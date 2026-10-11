import json
import logging
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from config.settings import settings
from core.llm_errors import redact_secrets

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("gemini", "openai")


class UserConfig(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    active_provider: str = Field(
        default_factory=lambda: settings.DEFAULT_LLM_PROVIDER,
        description="'gemini' or 'openai'"
    )

    # Gemini Configuration
    gemini_api_key: Optional[str] = None
    # 模型字段为 None 表示"跟随 .env（settings）默认值"；有值表示显式覆盖。
    # 这样部署者修改 GEMINI_MODEL 后，未被显式指定的用户会跟着一起生效。
    gemini_model: Optional[str] = None

    # OpenAI Configuration
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_vision_model: Optional[str] = None
    openai_whisper_model: Optional[str] = None

    # 运行期标记：当前配置是否来自 .env 的全局兜底 Key（不落盘）
    env_key_fallback: bool = Field(default=False, exclude=True)

    created_at: str = Field(default_factory=lambda: settings.now().isoformat())
    updated_at: str = Field(default_factory=lambda: settings.now().isoformat())

    @field_validator("active_provider")
    @classmethod
    def _normalize_provider(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in VALID_PROVIDERS:
            return settings.DEFAULT_LLM_PROVIDER
        return value

    def has_valid_key(self) -> bool:
        """当前生效的提供商是否具备可用 Key（只统计用户自己的 Key）"""
        if self.active_provider == "gemini":
            return bool(self.gemini_api_key and self.gemini_api_key.strip())
        elif self.active_provider == "openai":
            return bool(self.openai_api_key and self.openai_api_key.strip())
        return False

    def key_source_label(self) -> str:
        if self.env_key_fallback:
            return "环境变量兜底"
        return "个人绑定" if self.has_valid_key() else "未配置"

    def masked_gemini_key(self) -> str:
        if not self.gemini_api_key:
            return "未配置"
        k = self.gemini_api_key.strip()
        if len(k) <= 8:
            return "****"
        return f"{k[:4]}...{k[-4:]}"

    def masked_openai_key(self) -> str:
        if not self.openai_api_key:
            return "未配置"
        k = self.openai_api_key.strip()
        if len(k) <= 8:
            return "****"
        return f"{k[:4]}...{k[-4:]}"


class UserConfigManager:
    def __init__(self):
        self.base_dir = settings.VAULT_DIR / "users"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _config_path(self, user_id: int) -> Path:
        return self.base_dir / str(user_id) / "config.json"

    def get_user_config(self, user_id: int) -> UserConfig:
        """读取用户自己的配置（不会创建目录 / 不会写入）"""
        config_path = self._config_path(user_id)
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                return UserConfig(**data)
            except Exception as e:
                logger.warning(
                    f"用户 {user_id} 的 config.json 解析失败，本次回退为默认配置"
                    f"（原文件保留未改动，请检查是否损坏）: {redact_secrets(str(e))}"
                )

        # New default user (must configure key via /setkey)
        return UserConfig(user_id=user_id)

    @staticmethod
    def _model_defaults(config: UserConfig) -> dict:
        """把用户未显式指定的模型字段回填为 .env（settings）里的默认值"""
        updates = {}
        defaults = {
            "gemini_model": settings.GEMINI_MODEL,
            "openai_model": settings.OPENAI_MODEL,
            "openai_vision_model": settings.OPENAI_VISION_MODEL,
            "openai_whisper_model": settings.OPENAI_WHISPER_MODEL,
        }
        for field_name, default in defaults.items():
            if not getattr(config, field_name):
                updates[field_name] = default
        return updates

    def resolve_config(self, user_id: int, allow_env_fallback: Optional[bool] = None) -> UserConfig:
        """返回实际用于调用 LLM 的配置副本：个人 Key 优先，否则按规则回落到 .env 全局 Key。

        返回的副本**绝不写回磁盘**，避免把部署者的全局 Key 泄漏进每个用户的
        config.json（否则无法撤销且人人可见）。

        allow_env_fallback=None 时按 settings.env_key_fallback_enabled 判定
        （仅私有白名单模式启用）；CLI 本地自用模式可显式传 True。
        """
        config = self.get_user_config(user_id)
        updates = self._model_defaults(config)

        if not config.has_valid_key():
            if allow_env_fallback is None:
                allowed = settings.env_key_fallback_enabled and settings.is_user_allowed(user_id)
            else:
                allowed = allow_env_fallback

            provider = config.active_provider
            env_key = settings.env_key_for(provider) if allowed else None
            if env_key:
                updates["gemini_api_key" if provider == "gemini" else "openai_api_key"] = env_key
                updates["env_key_fallback"] = True
                if provider == "openai" and not config.openai_base_url and settings.OPENAI_BASE_URL:
                    updates["openai_base_url"] = settings.OPENAI_BASE_URL

        if not updates:
            return config
        return config.model_copy(update=updates)

    def save_user_config(self, config: UserConfig):
        config.updated_at = settings.now().isoformat()
        config_path = self._config_path(config.user_id)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # 原子写：避免定时任务与用户 /setkey 并发时写坏 config.json
        tmp_path = config_path.with_name(config_path.name + ".tmp")
        tmp_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, config_path)

    def list_active_users(self) -> List[int]:
        """返回所有当前可正常使用 AI 功能的用户 ID。

        包含两类：已绑定个人 Key 的用户，以及白名单内可通过 .env 兜底 Key
        使用的用户（否则自建部署下定时复盘永远不会触发）。
        """
        candidates = set(settings.allowed_user_ids_list)
        if self.base_dir.exists():
            for user_folder in self.base_dir.iterdir():
                if user_folder.is_dir() and user_folder.name.isdigit():
                    candidates.add(int(user_folder.name))

        active_users = []
        for uid in sorted(candidates):
            if self.resolve_config(uid).has_valid_key():
                active_users.append(uid)
        return active_users


user_config_manager = UserConfigManager()
