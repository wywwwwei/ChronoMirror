import base64
import os
from pathlib import Path
from typing import Optional

from core.user_config import UserConfig
from core.prompts import (
    IMAGE_ANALYSIS_PROMPT,
    DAILY_REVIEW_SYSTEM_PROMPT,
    WEEKLY_REVIEW_SYSTEM_PROMPT,
    MEMORY_UPDATE_SYSTEM_PROMPT,
)

class LLMService:
    def get_gemini_client(self, user_config: UserConfig):
        from google import genai
        api_key = user_config.gemini_api_key
        if not api_key:
            raise ValueError("未检测到 Gemini API Key。请使用 `/setkey gemini 你的Key` 进行设置。")
        return genai.Client(api_key=api_key)

    def get_openai_client(self, user_config: UserConfig):
        from openai import OpenAI
        api_key = user_config.openai_api_key
        if not api_key:
            raise ValueError("未检测到 OpenAI API Key。请使用 `/setkey openai 你的Key` 进行设置。")
        base_url = user_config.openai_base_url
        return OpenAI(api_key=api_key, base_url=base_url)

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
            client = self.get_gemini_client(user_config)
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            response = client.models.generate_content(
                model=user_config.gemini_model,
                contents=[image_part, prompt]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client(user_config)
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            response = client.chat.completions.create(
                model=user_config.openai_vision_model,
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
            return response.choices[0].message.content.strip()

    async def transcribe_audio(
        self,
        audio_path: Path,
        user_config: UserConfig,
        mime_type: str = "audio/ogg"
    ) -> str:
        provider = user_config.active_provider.lower()

        if provider == "gemini":
            from google.genai import types
            client = self.get_gemini_client(user_config)
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            stt_prompt = "请将该语音消息完整转录为文字，保留口语真实原意，不要添加任何多余的开场白或解释。"
            response = client.models.generate_content(
                model=user_config.gemini_model,
                contents=[audio_part, stt_prompt]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client(user_config)
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=user_config.openai_whisper_model,
                    file=audio_file
                )
            return transcript.text.strip()

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
            client = self.get_gemini_client(user_config)
            response = client.models.generate_content(
                model=user_config.gemini_model,
                contents=[system_prompt, user_message]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client(user_config)
            response = client.chat.completions.create(
                model=user_config.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

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
            client = self.get_gemini_client(user_config)
            response = client.models.generate_content(
                model=user_config.gemini_model,
                contents=[system_prompt, user_message]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client(user_config)
            response = client.chat.completions.create(
                model=user_config.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

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
            client = self.get_gemini_client(user_config)
            response = client.models.generate_content(
                model=user_config.gemini_model,
                contents=[MEMORY_UPDATE_SYSTEM_PROMPT, user_message]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client(user_config)
            response = client.chat.completions.create(
                model=user_config.openai_model,
                messages=[
                    {"role": "system", "content": MEMORY_UPDATE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.5
            )
            return response.choices[0].message.content.strip()

llm = LLMService()
