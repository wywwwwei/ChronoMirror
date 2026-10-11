import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

from config.settings import settings
from core.llm_errors import redact_secrets

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("gemini", "openai")

# 可配置的模型档位。每个档位归属一个 provider —— 用户只会看到自己绑过 Key 的那一家：
# 只有 Gemini Key 就 2 个档位，只有 OpenAI Key 也是 2 个，不存在"要同时配好几家"的情况。
#
# 档位名刻意避开 provider 名（不要用 "openai" 当档位名，否则 /setmodel openai X
# 既可读成"设置 openai 这家"也可读成"设置 openai 档位"）。
MODEL_ROLES: Dict[str, dict] = {
    "capture": {
        "provider": "gemini",
        "fields": ("gemini_capture_model",),
        "label": "语音转写 + 照片描述",
    },
    "review": {
        "provider": "gemini",
        "fields": ("gemini_review_model",),
        # 旧字段也是 review 档的"钉住"来源（见 _model_defaults）。不把它算进来，
        # 存量用户的 review 明明被 gemini_model 钉着，却会显示成"跟随 .env"。
        "legacy_fields": ("gemini_model",),
        "label": "日/周复盘 + 画像进化",
    },
    "chat": {
        "provider": "openai",
        # 文本复盘与照片描述共用一个档位：两者本来就是同一个模型的两种用法，
        # 默认值也一致，拆成两个只会多一个要理解的概念。
        "fields": ("openai_model", "openai_vision_model"),
        "label": "文本复盘 + 照片描述",
    },
    "whisper": {
        "provider": "openai",
        "fields": ("openai_whisper_model",),
        "label": "语音转写",
    },
}

# 与 settings 字段一一对应：gemini_capture_model -> GEMINI_CAPTURE_MODEL
_MODEL_FIELDS: Tuple[str, ...] = tuple(
    field_name for meta in MODEL_ROLES.values() for field_name in meta["fields"]
)

# 只做保守的格式校验，不维护模型白名单：模型目录变化太快，硬编码会让用户
# 用不上刚发布的模型。名字写错时 API 会返回 404，core/llm_errors.py 已经
# 把那条错误翻译成人话了。
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._:/@-]{1,64}$")


def _env_default(field_name: str) -> str:
    """.env（settings）里该字段的全局默认值"""
    return getattr(settings, field_name.upper())


def normalize_model_name(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """校验并清洗用户输入的模型名，返回 (模型名, 错误提示)。

    与 ReviewEngine.normalize_target_date 保持同一约定：失败时第一个元素为 None。
    """
    if value is None or not value.strip():
        return None, "模型名不能为空"

    name = value.strip()
    if len(name) > 64:
        return None, f"模型名过长（{len(name)} 个字符，上限 64）"
    if not MODEL_NAME_PATTERN.match(name):
        return None, "模型名只能包含字母、数字以及 `. _ - : / @` 这些符号"

    return name, None


def get_role(role: str) -> Optional[dict]:
    """按档位名取元信息，未知档位返回 None"""
    return MODEL_ROLES.get((role or "").strip().lower())


def available_roles(resolved: "UserConfig") -> List[str]:
    """该用户实际能配置的档位：只包含他绑过 Key（含 .env 兜底）的那一家。

    这样单 Key 用户永远不会看到一个自己用不上的档位。
    """
    roles: List[str] = []
    for provider, key_field in (("gemini", "gemini_api_key"), ("openai", "openai_api_key")):
        if getattr(resolved, key_field):
            roles.extend(name for name, meta in MODEL_ROLES.items() if meta["provider"] == provider)
    return roles


def apply_role_value(config: "UserConfig", role: str, value: Optional[str]) -> None:
    """把档位值写入（value=None 表示清除，恢复跟随 .env）。

    只改内存里的配置对象，落盘由调用方显式 save_user_config。
    """
    for field_name in MODEL_ROLES[role]["fields"]:
        setattr(config, field_name, value)

    # 旧字段 gemini_model 是 review 档的前身（见 _model_defaults）。
    # 重置 review 时必须连它一起清掉，否则它会立刻把 review 顶回旧值。
    if role == "review" and value is None:
        config.gemini_model = None


def describe_role(stored: "UserConfig", resolved: "UserConfig", role: str) -> dict:
    """组装单个档位的展示信息。

    stored 用于判断"用户钉过没有"：resolved 的默认值已经被填满，光看它分不出
    "个人设置"和"跟随 .env"。两者都必须传。
    """
    meta = MODEL_ROLES[role]
    fields = meta["fields"]
    values = [getattr(resolved, field_name) for field_name in fields]
    pinned_fields = fields + tuple(meta.get("legacy_fields", ()))

    # chat 档写两个字段，正常情况下两者同步；只有手改过 config.json 才会不一致，
    # 那种情况下如实把两个值都列出来，不藏。
    distinct = list(dict.fromkeys(values))
    return {
        "role": role,
        "provider": meta["provider"],
        "label": meta["label"],
        "values": distinct,
        "pinned": any(getattr(stored, field_name) for field_name in pinned_fields),
    }


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
    # 这样部署者改 .env 后，未被显式指定的用户会跟着一起生效。
    gemini_capture_model: Optional[str] = None
    gemini_review_model: Optional[str] = None
    # 旧字段，单档时代的遗留。不再被写入，只在读取时作为 review 档的兜底
    # （见 UserConfigManager._model_defaults），保证存量 config.json 不改变行为。
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
        """把用户未显式指定的模型字段回填为 .env（settings）里的默认值。

        刻意**不回填**旧的 gemini_model：它填了之后解析副本里就永远有值，
        /status 再也分不出"用户钉的"和"默认填的"，来源标签会全体显示成"个人设置"。
        """
        updates = {}
        for field_name in _MODEL_FIELDS:
            if not getattr(config, field_name):
                updates[field_name] = _env_default(field_name)

        # 旧字段只喂 review 档，不给 capture：capture 落到便宜默认正是本次的目标，
        # 让它被旧值顶回去的话拆档在存量用户身上等于没做（review 的语义也最接近
        # 旧的单档 GEMINI_MODEL —— 当年那个档位就是拿来跑复盘的）。
        if not config.gemini_review_model and config.gemini_model:
            updates["gemini_review_model"] = config.gemini_model

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
