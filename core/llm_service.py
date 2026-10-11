import asyncio
import base64
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple

from config.settings import settings
from core.user_config import UserConfig
from core.prompts import (
    IMAGE_ANALYSIS_PROMPT,
    DAILY_REVIEW_SYSTEM_PROMPT,
    WEEKLY_REVIEW_SYSTEM_PROMPT,
    MEMORY_UPDATE_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# 客户端缓存上限。每个条目都持有一个连接池；用户改了 Key 会留下旧条目，
# 所以需要上限 + 淘汰，避免长时间运行的进程把连接越攒越多。
MAX_CACHED_CLIENTS = 32

# --- 重试策略（Gemini 与 OpenAI 共用，避免两条路行为不一致）---
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0
# 服务端过载/限流/网关抖动的状态码
RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
# 拿不到结构化状态码时，退化为文本匹配（两个 SDK 的报错格式不同）
RETRYABLE_MARKERS = (
    "429", "500", "502", "503", "504",
    "unavailable", "resource_exhausted", "resource exhausted",
    "overloaded", "rate limit", "rate_limit",
    "timed out", "timeout", "connection error", "connection reset",
    "temporarily", "try again",
)


def _status_code_of(err: Exception):
    """尽力从两个 SDK 的异常对象里挖出 HTTP 状态码"""
    for attr in ("status_code", "http_status", "code"):
        value = getattr(err, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    return None


def is_retryable_error(err: Exception) -> bool:
    """判断是否值得重试。只对"服务端/网络临时故障"重试，
    参数错误、鉴权失败、额度耗尽等重试多少次都一样，必须立刻上抛。"""
    status = _status_code_of(err)
    if status is not None:
        return status in RETRYABLE_STATUS_CODES

    text = str(err).lower()
    return any(marker in text for marker in RETRYABLE_MARKERS)

# 模型字段为空表示"跟随 .env 默认值"（见 UserConfigManager.resolve_config）。
# 这里再兜一层，避免调用方传入未解析的配置时把 None 当成模型名发给 API。
def _gemini_model(cfg: UserConfig) -> str:
    return cfg.gemini_model or settings.GEMINI_MODEL

def _openai_model(cfg: UserConfig) -> str:
    return cfg.openai_model or settings.OPENAI_MODEL

def _openai_vision_model(cfg: UserConfig) -> str:
    return cfg.openai_vision_model or settings.OPENAI_VISION_MODEL

def _openai_whisper_model(cfg: UserConfig) -> str:
    return cfg.openai_whisper_model or settings.OPENAI_WHISPER_MODEL

class LLMService:
    """按 Key 复用 LLM 客户端。

    之前每次调用都 new 一个客户端且从不关闭：每个客户端都带一个 httpx 连接池，
    在长时间运行的机器人进程里等于每次消息都漏一个连接池（连接、socket、
    TLS 会话都不释放）。现在按 (api_key[, base_url]) 缓存复用，超出上限时
    淘汰并关闭最久未用的，进程退出时统一 aclose()。

    缓存键里含明文 Key，仅存在于内存，绝不写日志。
    """

    def __init__(self):
        self._gemini_clients: "OrderedDict[str, object]" = OrderedDict()
        self._openai_clients: "OrderedDict[Tuple[str, Optional[str]], object]" = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def _require_key(api_key: Optional[str], provider: str) -> str:
        key = (api_key or "").strip()
        if not key:
            raise ValueError(f"未检测到 {provider} API Key。请使用 `/setkey {provider.lower()} 你的Key` 进行设置。")
        return key

    async def _get_gemini_client(self, user_config: UserConfig):
        from google import genai
        api_key = self._require_key(user_config.gemini_api_key, "Gemini")
        async with self._lock:
            client = self._gemini_clients.get(api_key)
            if client is None:
                client = genai.Client(api_key=api_key)
                self._gemini_clients[api_key] = client
            self._gemini_clients.move_to_end(api_key)
            stale = self._evict_over_limit(self._gemini_clients)
        for old in stale:
            await self._close_gemini(old)
        return client

    async def _get_openai_client(self, user_config: UserConfig):
        from openai import AsyncOpenAI
        api_key = self._require_key(user_config.openai_api_key, "OpenAI")
        base_url = user_config.openai_base_url or None
        cache_key = (api_key, base_url)
        async with self._lock:
            client = self._openai_clients.get(cache_key)
            if client is None:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                self._openai_clients[cache_key] = client
            self._openai_clients.move_to_end(cache_key)
            stale = self._evict_over_limit(self._openai_clients)
        for old in stale:
            await self._close_openai(old)
        return client

    @staticmethod
    def _evict_over_limit(cache: OrderedDict) -> List[object]:
        stale = []
        while len(cache) > MAX_CACHED_CLIENTS:
            _, old = cache.popitem(last=False)
            stale.append(old)
        return stale

    @staticmethod
    async def _close_gemini(client) -> None:
        # genai.Client 的同步与异步 api_client 是两套连接池，都要收
        try:
            client.close()
        except Exception as e:
            logger.warning(f"关闭 Gemini 同步客户端失败: {e}")
        aio = getattr(client, "aio", None)
        if aio is not None:
            try:
                await aio.aclose()
            except Exception as e:
                logger.warning(f"关闭 Gemini 异步客户端失败: {e}")

    @staticmethod
    async def _close_openai(client) -> None:
        try:
            await client.close()
        except Exception as e:
            logger.warning(f"关闭 OpenAI 客户端失败: {e}")

    async def aclose(self) -> None:
        """关闭所有缓存客户端。在机器人停机 / 进程退出时调用。"""
        async with self._lock:
            gemini_clients = list(self._gemini_clients.values())
            openai_clients = list(self._openai_clients.values())
            self._gemini_clients.clear()
            self._openai_clients.clear()
        for client in gemini_clients:
            await self._close_gemini(client)
        for client in openai_clients:
            await self._close_openai(client)

    async def _with_retry(self, operation: str, call, retries: int = MAX_RETRIES):
        """统一的重试入口：指数退避重试可恢复错误，其余立刻上抛。

        operation 只用于日志，绝不能把 API Key 拼进去。
        """
        for attempt in range(retries):
            try:
                return await call()
            except Exception as e:
                if attempt >= retries - 1 or not is_retryable_error(e):
                    # 裸 raise 保留原始 traceback；`raise e` 会把 traceback 重置到
                    # 这一行，真正的出错位置（SDK 内部）在日志里就再也看不到了。
                    raise
                delay = BASE_BACKOFF_SECONDS * (2 ** attempt)
                logger.warning(
                    f"{operation} 第 {attempt + 1}/{retries} 次调用失败"
                    f"（{type(e).__name__}），{delay:.0f}s 后重试: {e}"
                )
                await asyncio.sleep(delay)

    async def _call_gemini_with_retry(
        self,
        client,
        model: str,
        contents,
        system_instruction: Optional[str] = None,
        retries: int = MAX_RETRIES,
    ) -> str:
        """Gemini 文本/多模态调用。两种提供商共用 _with_retry。"""
        return await self._with_retry(
            f"Gemini/{model}",
            lambda: self._gemini_generate(client, model, contents, system_instruction),
            retries=retries,
        )

    @staticmethod
    async def _gemini_generate(client, model: str, contents, system_instruction: Optional[str] = None) -> str:
        """system_instruction 必须走 GenerateContentConfig。

        之前是把系统提示词塞进 contents 的第一项，那样它只是一条普通的
        user turn：模型不会按 system 角色对待它（拿到的是两条连续 user 消息），
        角色约束与指令优先级都被削弱，还白白多消耗一轮上下文。
        """
        config = None
        if system_instruction:
            from google.genai import types
            config = types.GenerateContentConfig(system_instruction=system_instruction)

        response = await client.aio.models.generate_content(
            model=model, contents=contents, config=config
        )
        return response.text.strip()

    @staticmethod
    async def _openai_complete(client, *, model: str, messages, **kwargs) -> str:
        response = await client.chat.completions.create(
            model=model, messages=messages, **kwargs
        )
        return response.choices[0].message.content.strip()

    async def describe_image(
        self,
        image_bytes: bytes,
        user_config: UserConfig,
        mime_type: str = "image/jpeg",
        user_caption: str = ""
    ) -> str:
        prompt = IMAGE_ANALYSIS_PROMPT.format(user_caption=user_caption or "（无额外说明）")
        provider = user_config.active_provider.lower()

        if provider == "gemini":
            from google.genai import types
            client = await self._get_gemini_client(user_config)
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            return await self._call_gemini_with_retry(
                client=client,
                model=_gemini_model(user_config),
                contents=[image_part, prompt]
            )
        else:
            client = await self._get_openai_client(user_config)
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            return await self._with_retry(
                f"OpenAI/{_openai_vision_model(user_config)}",
                lambda: self._openai_complete(
                    client,
                    model=_openai_vision_model(user_config),
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime_type};base64,{b64_image}"}
                                }
                            ]
                        }
                    ],
                    max_tokens=300
                )
            )

    async def transcribe_audio(
        self,
        audio_path: Path,
        user_config: UserConfig,
        mime_type: str = "audio/ogg"
    ) -> str:
        provider = user_config.active_provider.lower()

        if provider == "gemini":
            from google.genai import types
            client = await self._get_gemini_client(user_config)
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            stt_prompt = "请将该语音消息完整转录为文字，保留口语真实原意，不要添加任何多余的开场白或解释。"
            return await self._call_gemini_with_retry(
                client=client,
                model=_gemini_model(user_config),
                contents=[audio_part, stt_prompt]
            )
        else:
            client = await self._get_openai_client(user_config)

            async def _transcribe():
                # 每次重试都要把文件指针拨回开头，否则第二次上传的是空文件
                with open(audio_path, "rb") as audio_file:
                    transcript = await client.audio.transcriptions.create(
                        model=_openai_whisper_model(user_config),
                        file=audio_file
                    )
                return transcript.text.strip()

            return await self._with_retry(
                f"OpenAI/{_openai_whisper_model(user_config)}",
                _transcribe
            )

    async def generate_daily_review(
        self,
        date_str: str,
        log_content: str,
        profile_content: str,
        user_config: UserConfig
    ) -> str:
        system_prompt = DAILY_REVIEW_SYSTEM_PROMPT.format(date=date_str)
        user_message = f"""### 当前用户长期画像 (L3 Memory)：
{profile_content}

---
### 今日时间流记录 (L0 Logs)：
{log_content}
"""
        provider = user_config.active_provider.lower()
        if provider == "gemini":
            client = await self._get_gemini_client(user_config)
            return await self._call_gemini_with_retry(
                client=client,
                model=_gemini_model(user_config),
                contents=user_message,
                system_instruction=system_prompt,
            )
        else:
            client = await self._get_openai_client(user_config)
            return await self._with_retry(
                f"OpenAI/{_openai_model(user_config)}",
                lambda: self._openai_complete(
                    client,
                    model=_openai_model(user_config),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7
                )
            )

    async def generate_weekly_review(
        self,
        week_label: str,
        daily_reviews_summary: str,
        profile_content: str,
        user_config: UserConfig
    ) -> str:
        system_prompt = WEEKLY_REVIEW_SYSTEM_PROMPT.format(week_label=week_label)
        user_message = f"""### 当前用户长期画像 (L3 Memory)：
{profile_content}

---
### 本周每日复盘汇总 (L1 Reviews)：
{daily_reviews_summary}
"""
        provider = user_config.active_provider.lower()
        if provider == "gemini":
            client = await self._get_gemini_client(user_config)
            return await self._call_gemini_with_retry(
                client=client,
                model=_gemini_model(user_config),
                contents=user_message,
                system_instruction=system_prompt,
            )
        else:
            client = await self._get_openai_client(user_config)
            return await self._with_retry(
                f"OpenAI/{_openai_model(user_config)}",
                lambda: self._openai_complete(
                    client,
                    model=_openai_model(user_config),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7
                )
            )

    async def evolve_memory(
        self,
        recent_reviews_text: str,
        current_profile: str,
        user_config: UserConfig
    ) -> str:
        user_message = f"""### 当前画像：
{current_profile}

---
### 近期新增复盘总结：
{recent_reviews_text}
"""
        provider = user_config.active_provider.lower()
        if provider == "gemini":
            client = await self._get_gemini_client(user_config)
            return await self._call_gemini_with_retry(
                client=client,
                model=_gemini_model(user_config),
                contents=user_message,
                system_instruction=MEMORY_UPDATE_SYSTEM_PROMPT,
            )
        else:
            client = await self._get_openai_client(user_config)
            return await self._with_retry(
                f"OpenAI/{_openai_model(user_config)}",
                lambda: self._openai_complete(
                    client,
                    model=_openai_model(user_config),
                    messages=[
                        {"role": "system", "content": MEMORY_UPDATE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.5
                )
            )

llm = LLMService()
