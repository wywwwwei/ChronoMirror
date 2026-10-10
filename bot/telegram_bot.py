import datetime
import io
import logging
from typing import Optional
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config.settings import settings
from core.storage import storage
from core.llm_service import llm
from core.review_engine import review_engine

logger = logging.getLogger(__name__)

def is_authorized(user_id: int) -> bool:
    allowed = settings.allowed_user_ids_list
    if not allowed:
        return True
    return user_id in allowed

async def send_long_message(update: Update, text: str):
    """Splits text into chunks of <= 4000 characters to comply with Telegram limits"""
    chunk_size = 4000
    if len(text) <= chunk_size:
        await update.effective_message.reply_text(text)
        return

    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        await update.effective_message.reply_text(chunk)

async def check_auth_or_reject(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    if not is_authorized(user.id):
        await update.effective_message.reply_text(
            f"⛔ 未授权访问。\n你的 Telegram User ID 为: `{user.id}`\n请将其加入 .env 的 ALLOWED_USER_IDS 中。",
            parse_mode="Markdown"
        )
        return False
    return True

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_auth_or_reject(update):
        return

    welcome_text = (
        f"👋 你好，{user.first_name}！我是你的 AI 个人成长复盘外脑。\n\n"
        "💡 **随时记录模式**：\n"
        "- 💬 直接发送文字：记录闪念、想法、工作待办\n"
        "- 🎙️ 发送语音消息：自动转写文字并归档（无痛记录）\n"
        "- 📸 发送照片（可带文字说明）：自动提取饮食、穿搭、场景特征\n\n"
        "⚡ **复盘与管理指令**：\n"
        "- `/review`：立即生成今天的深度日复盘\n"
        "- `/review YYYY-MM-DD`：复盘指定某一天的日记\n"
        "- `/weekly`：立即生成本周战略复盘并沉淀长期画像\n"
        "- `/today`：查看今天已记录的时间流日志\n"
        "- `/profile`：查看当前积累的长期画像与思维模型 (L3)\n"
        "- `/id`：查看当前 Telegram User ID\n"
    )
    await update.effective_message.reply_text(welcome_text, parse_mode="Markdown")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.effective_message.reply_text(
        f"你的 Telegram User ID 是: `{user.id}`",
        parse_mode="Markdown"
    )

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_reject(update):
        return
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    content = await storage.get_daily_log(today_str)
    if not content:
        await update.effective_message.reply_text(f"今日 ({today_str}) 还没有任何记录，随时发点文字、语音或照片吧！")
        return
    await send_long_message(update, f"📋 【今日记录流水账】\n\n{content}")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_reject(update):
        return
    profile_content = await storage.get_user_profile()
    await send_long_message(update, f"👤 【当前长期画像 (L3 Memory)】\n\n{profile_content}")

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_reject(update):
        return

    target_date = None
    if context.args:
        target_date = context.args[0].strip()
    
    date_label = target_date or datetime.date.today().strftime("%Y-%m-%d")
    status_msg = await update.effective_message.reply_text(f"🤖 正在为 {date_label} 进行深度日复盘与思维诊断，请稍候...")

    success, review_text, path = await review_engine.run_daily_review(target_date)
    if not success:
        await status_msg.edit_text(f"⚠️ 复盘未生成: {review_text}")
        return

    await status_msg.delete()
    header = f"✅ 【日复盘已生成并已归档至 Obsidian】\n\n"
    await send_long_message(update, header + review_text)

async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_reject(update):
        return

    status_msg = await update.effective_message.reply_text("📊 正在汇总过去 7 天的复盘，生成周度战略分析并更新长期画像...")
    success, weekly_text, path = await review_engine.run_weekly_review()
    if not success:
        await status_msg.edit_text(f"⚠️ 周复盘未生成: {weekly_text}")
        return

    await status_msg.delete()
    header = "🏆 【周度战略复盘完成 & 长期画像已迭代】\n\n"
    await send_long_message(update, header + weekly_text)

# --- Message Handlers (Capture Layer) ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_reject(update):
        return

    text = update.effective_message.text
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M:%S")

    await storage.append_log(content=text, tag="文字记录", dt=now)
    preview = text if len(text) < 30 else text[:27] + "..."
    await update.effective_message.reply_text(f"✅ 已记下 [{time_str}]: {preview}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_reject(update):
        return

    voice = update.effective_message.voice
    status_msg = await update.effective_message.reply_text("🎙️ 正在下载并转写语音，请稍候...")

    try:
        tg_file = await voice.get_file()
        file_bytes = await tg_file.download_as_bytearray()
        
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        filename = f"voice_{timestamp_str}.ogg"
        
        # Save attachment
        saved_path, rel_path = await storage.save_attachment(bytes(file_bytes), filename)

        # Transcribe
        transcript = await llm.transcribe_audio(saved_path, mime_type="audio/ogg")
        if not transcript:
            transcript = "（未能识别出有效语音文字）"

        # Append to log
        log_entry = f"语音转写：{transcript}"
        await storage.append_log(content=log_entry, tag="语音记录", dt=now, attachment_rel_path=rel_path)

        await status_msg.edit_text(f"🎙️ 已转写归档 [{now.strftime('%H:%M:%S')}]:\n\n{transcript}")
    except Exception as e:
        logger.exception("语音处理失败")
        await status_msg.edit_text(f"❌ 语音处理失败: {str(e)}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_reject(update):
        return

    # Telegram sends multiple photo sizes; the last one is the largest
    photo = update.effective_message.photo[-1]
    caption = update.effective_message.caption or ""
    status_msg = await update.effective_message.reply_text("📸 正在提取照片特征并进行文字降维...")

    try:
        tg_file = await photo.get_file()
        file_bytes = await tg_file.download_as_bytearray()

        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp_str}.jpg"

        # Save attachment
        saved_path, rel_path = await storage.save_attachment(bytes(file_bytes), filename)

        # Analyze image
        description = await llm.describe_image(
            image_bytes=bytes(file_bytes),
            mime_type="image/jpeg",
            user_caption=caption
        )

        # Append to log
        entry_parts = []
        if caption:
            entry_parts.append(f"用户说明：{caption}")
        entry_parts.append(description)
        log_entry = "\n".join(entry_parts)

        await storage.append_log(content=log_entry, tag="视觉记录", dt=now, attachment_rel_path=rel_path)

        await status_msg.edit_text(f"📸 影像特征已归档 [{now.strftime('%H:%M:%S')}]:\n\n{description}")
    except Exception as e:
        logger.exception("图片解析失败")
        await status_msg.edit_text(f"❌ 图片解析失败: {str(e)}")

def build_telegram_app():
    if not settings.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN 未配置，请在 .env 中设置")

    builder = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN)
    if settings.TELEGRAM_PROXY:
        builder = builder.proxy(settings.TELEGRAM_PROXY)

    app = builder.build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("weekly", weekly_command))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    return app
