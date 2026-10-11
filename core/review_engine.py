import datetime
import re
from pathlib import Path
from typing import Optional, Tuple

from config.settings import settings
from core.storage import storage
from core.llm_service import llm
from core.user_config import user_config_manager

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

class ReviewEngine:
    @staticmethod
    def normalize_target_date(target_date: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """校验 /review 指令传入的日期，返回 (合法日期, 错误提示)。

        这个值会直接被拼进文件路径，如果不校验，`/review ../../../README`
        就能读到 vault 之外的文件。这里只放行严格的 YYYY-MM-DD。
        """
        if target_date is None:
            return None, None
        cleaned = target_date.strip()
        if not cleaned:
            return None, None
        if not DATE_PATTERN.fullmatch(cleaned):
            return None, "日期格式不正确，请使用 YYYY-MM-DD 格式（例如 `/review 2026-10-10`）。"
        try:
            datetime.date.fromisoformat(cleaned)
        except ValueError:
            return None, f"`{cleaned}` 不是一个真实存在的日期，请检查后重试。"
        return cleaned, None

    async def run_daily_review(
        self,
        user_id: int,
        target_date: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Path]]:
        # 0. Validate the externally supplied date BEFORE it reaches the filesystem
        target_date, date_error = self.normalize_target_date(target_date)
        if date_error:
            return False, date_error, None

        # 1. Check User Config & Key
        user_config = user_config_manager.resolve_config(user_id)
        if not user_config.has_valid_key():
            provider = user_config.active_provider
            return False, f"⚠️ 你尚未配置当前提供商 ({provider}) 的 API Key，无法生成复盘。\n请使用 `/setkey {provider} 你的Key` 进行设置。", None

        date_str = target_date or settings.today().strftime("%Y-%m-%d")

        # 2. Fetch L0 logs
        log_content = await storage.get_daily_log(user_id, date_str)
        if not log_content or not log_content.strip():
            return False, f"未找到 {date_str} 的日常记录流水账，无法生成复盘。快去发送几条语音或照片吧！", None

        # 3. Fetch L3 Profile
        profile_content = await storage.get_user_profile(user_id)

        # 4. Call LLM with user_config
        try:
            review_text = await llm.generate_daily_review(
                date_str=date_str,
                log_content=log_content,
                profile_content=profile_content,
                user_config=user_config
            )
        except Exception as e:
            return False, f"生成日复盘失败，LLM 报错: {str(e)}", None

        # 5. Save L1 review with Obsidian YAML frontmatter
        obsidian_content = (
            f"---\n"
            f"user_id: {user_id}\n"
            f"date: {date_str}\n"
            f"type: daily-review\n"
            f"tags: [review, daily, growth]\n"
            f"---\n\n"
            f"{review_text}\n"
        )
        try:
            saved_path = await storage.save_daily_review(user_id, date_str, obsidian_content)
        except ValueError as e:
            return False, f"复盘内容无法保存：{e}", None
        return True, review_text, saved_path

    async def run_weekly_review(self, user_id: int) -> Tuple[bool, str, Optional[Path]]:
        # 1. Check User Config & Key
        user_config = user_config_manager.resolve_config(user_id)
        if not user_config.has_valid_key():
            provider = user_config.active_provider
            return False, f"⚠️ 你尚未配置当前提供商 ({provider}) 的 API Key，无法生成周复盘。\n请使用 `/setkey {provider} 你的Key` 进行设置。", None

        today = settings.today()
        week_label = today.strftime("%Y-W%W")

        # 2. Fetch past 7 days of L1 reviews for user
        recent_reviews = await storage.get_recent_daily_reviews(user_id, days=7)
        if not recent_reviews:
            return False, "过去 7 天内没有任何【每日复盘】记录，无法生成周度战略复盘。请先积累日常记录并进行日复盘。", None

        aggregated_text = []
        for d_str, content in recent_reviews:
            aggregated_text.append(f"### 日期: {d_str}\n{content}\n")
        combined_reviews = "\n---\n".join(aggregated_text)

        # 3. Fetch L3 Profile
        profile_content = await storage.get_user_profile(user_id)

        # 4. Generate L2 Weekly Review
        try:
            weekly_text = await llm.generate_weekly_review(
                week_label=week_label,
                daily_reviews_summary=combined_reviews,
                profile_content=profile_content,
                user_config=user_config
            )
        except Exception as e:
            return False, f"生成周复盘失败，LLM 报错: {str(e)}", None

        # 5. Save Weekly Review with Obsidian YAML frontmatter
        obsidian_weekly = (
            f"---\n"
            f"user_id: {user_id}\n"
            f"week: {week_label}\n"
            f"type: weekly-review\n"
            f"tags: [review, weekly, strategy]\n"
            f"---\n\n"
            f"{weekly_text}\n"
        )
        saved_path = await storage.save_weekly_review(user_id, week_label, obsidian_weekly)

        # 6. Automatically evolve L3 Memory Profile
        try:
            new_profile = await llm.evolve_memory(
                recent_reviews_text=weekly_text,
                current_profile=profile_content,
                user_config=user_config
            )
            await storage.save_user_profile(user_id, new_profile)
        except Exception as e:
            print(f"[Warning] 更新用户 {user_id} 长期画像失败: {e}")

        return True, weekly_text, saved_path

review_engine = ReviewEngine()
