import json
import datetime
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from config.settings import settings

class UserConfig(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    active_provider: str = Field(default="gemini", description="'gemini' or 'openai'")
    
    # Gemini Configuration
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    
    # OpenAI Configuration
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_vision_model: str = "gpt-4o-mini"
    openai_whisper_model: str = "whisper-1"
    
    created_at: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())

    def has_valid_key(self) -> bool:
        if self.active_provider == "gemini":
            return bool(self.gemini_api_key and self.gemini_api_key.strip())
        elif self.active_provider == "openai":
            return bool(self.openai_api_key and self.openai_api_key.strip())
        return False

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

    def _get_config_path(self, user_id: int) -> Path:
        user_dir = self.base_dir / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "config.json"

    def get_user_config(self, user_id: int) -> UserConfig:
        config_path = self._get_config_path(user_id)
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                return UserConfig(**data)
            except Exception:
                pass
        
        # New default user
        return UserConfig(user_id=user_id)

    def save_user_config(self, config: UserConfig):
        config.updated_at = datetime.datetime.now().isoformat()
        config_path = self._get_config_path(config.user_id)
        config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")

    def list_active_users(self) -> List[int]:
        """Returns list of user IDs that have at least one valid key configured"""
        active_users = []
        if not self.base_dir.exists():
            return active_users

        for user_folder in self.base_dir.iterdir():
            if user_folder.is_dir() and user_folder.name.isdigit():
                uid = int(user_folder.name)
                cfg = self.get_user_config(uid)
                if cfg.has_valid_key():
                    active_users.append(uid)
        return active_users

user_config_manager = UserConfigManager()
