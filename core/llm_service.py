import base64
import os
from pathlib import Path
from typing import Optional

from config.settings import settings
from core.prompts import (
    IMAGE_ANALYSIS_PROMPT,
    DAILY_REVIEW_SYSTEM_PROMPT,
    WEEKLY_REVIEW_SYSTEM_PROMPT,
    MEMORY_UPDATE_SYSTEM_PROMPT,
)

class LLMService:
    def __init__(self):
        self.provider = settings.DEFAULT_LLM_PROVIDER.lower()
        self._gemini_client = None
        self._openai_client = None

    def get_gemini_client(self):
        if self._gemini_client is None:
            from google import genai
            api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY 未配置，请在 .env 中设置")
            self._gemini_client = genai.Client(api_key=api_key)
        return self._gemini_client

    def get_openai_client(self):
        if self._openai_client is None:
            from openai import OpenAI
            api_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY 未配置，请在 .env 中设置")
            base_url = settings.OPENAI_BASE_URL
            self._openai_client = OpenAI(api_key=api_key, base_url=base_url)
        return self._openai_client

    async def describe_image(self, image_bytes: bytes, mime_type: str = "image/jpeg", user_caption: str = "") -> str:
        """
        Extracts structured tags and description from an image to avoid storing / resending raw images.
        """
        prompt = IMAGE_ANALYSIS_PROMPT.format(user_caption=user_caption or "（无额外说明）")

        if self.provider == "gemini":
            from google.genai import types
            client = self.get_gemini_client()
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[image_part, prompt]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client()
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            response = client.chat.completions.create(
                model=settings.OPENAI_VISION_MODEL,
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

    async def transcribe_audio(self, audio_path: Path, mime_type: str = "audio/ogg") -> str:
        """
        Transcribes speech to text.
        Gemini handles audio natively; OpenAI uses Whisper endpoint.
        """
        if self.provider == "gemini":
            from google.genai import types
            client = self.get_gemini_client()
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            stt_prompt = "请将该语音消息完整转录为文字，保留口语真实原意，不要添加任何多余的开场白或解释。"
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[audio_part, stt_prompt]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client()
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=settings.OPENAI_WHISPER_MODEL,
                    file=audio_file
                )
            return transcript.text.strip()

    async def generate_daily_review(self, date_str: str, log_content: str, profile_content: str) -> str:
        """
        Generates L1 daily review based on today's L0 logs and user L3 profile.
        """
        system_prompt = DAILY_REVIEW_SYSTEM_PROMPT.format(date=date_str)
        user_message = f"""### 当前用户长期画像 (L3 Memory)：
{profile_content}

---
### 今日时间流记录 (L0 Logs)：
{log_content}
"""
        if self.provider == "gemini":
            client = self.get_gemini_client()
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[system_prompt, user_message]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

    async def generate_weekly_review(self, week_label: str, daily_reviews_summary: str, profile_content: str) -> str:
        """
        Generates L2 weekly review using aggregated 7 days of L1 reviews.
        """
        system_prompt = WEEKLY_REVIEW_SYSTEM_PROMPT.format(week_label=week_label)
        user_message = f"""### 当前用户长期画像 (L3 Memory)：
{profile_content}

---
### 本周每日复盘汇总 (L1 Reviews)：
{daily_reviews_summary}
"""
        if self.provider == "gemini":
            client = self.get_gemini_client()
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[system_prompt, user_message]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

    async def evolve_memory(self, recent_reviews_text: str, current_profile: str) -> str:
        """
        Updates L3 user profile based on fresh reviews.
        """
        user_message = f"""### 当前画像：
{current_profile}

---
### 近期新增复盘总结：
{recent_reviews_text}
"""
        if self.provider == "gemini":
            client = self.get_gemini_client()
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[MEMORY_UPDATE_SYSTEM_PROMPT, user_message]
            )
            return response.text.strip()
        else:
            client = self.get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": MEMORY_UPDATE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.5
            )
            return response.choices[0].message.content.strip()

llm = LLMService()
