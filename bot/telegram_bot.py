import logging
from typing import Optional, Tuple
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, TelegramError, TimedOut
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config.settings import settings
from core.storage import storage
from core.llm_errors import describe_llm_error, log_llm_error, redact_secrets
from core.llm_service import llm
from core.review_engine import review_engine
from core.telegram_format import prepare_message, strip_tags
from core.user_config import (
    _MODEL_FIELDS,
    UserConfig,
    apply_role_value,
    available_roles,
    describe_role,
    get_role,
    normalize_model_name,
    user_config_manager,
)

logger = logging.getLogger(__name__)

def is_authorized(user_id: int) -> bool:
    """白名单校验统一委托给 settings 上的唯一实现，避免两处逻辑漂移。"""
    return settings.is_user_allowed(user_id)

async def send_long_message(update: Update, text: str):
    """发送模型生成的长文本：Markdown 转 Telegram HTML，并按上限安全切分。

    之前这里是直接按 4000 字符硬切后原样发出，parse_mode 为 None——模型写的
    `**粗体**` 到用户手里就是一串星号，长复盘还会被从中间劈开。
    """
    for chunk in prepare_message(text or ""):
        try:
            await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML)
        except BadRequest as e:
            # 转换器是保守子集，理论上是安全的；万一仍然解析失败，
            # 宁可让用户看到纯文本，也不能整条消息丢掉。
            logger.warning(f"HTML 渲染失败，回退为纯文本发送: {e}")
            await update.effective_message.reply_text(strip_tags(chunk))

async def ensure_user_ready(update: Update) -> Tuple[bool, Optional[UserConfig]]:
    """Checks whitelist and whether user has configured a valid API Key"""
    user = update.effective_user
    if not user:
        return False, None

    # 1. Whitelist Check (if configured)
    if not is_authorized(user.id):
        await update.effective_message.reply_text(
            f"⛔ 未授权访问。\n你的 Telegram User ID 为: `{user.id}`\n此机器人仅供授权白名单使用。",
            parse_mode="Markdown"
        )
        return False, None

    # 2. Key Check（个人 Key 优先，私有白名单模式下可回落到 .env 全局 Key）
    config = user_config_manager.resolve_config(user.id)
    if not config.has_valid_key():
        await update.effective_message.reply_text(
            "⚠️ **你尚未绑定有效的 AI API Key，暂时无法使用记录与复盘功能。**\n\n"
            "请先在私聊中发送以下指令完成绑定：\n\n"
            "🔹 **绑定 Google Gemini Key**：\n"
            "`/setkey gemini 你的GeminiKey`\n\n"
            "🔹 **绑定 OpenAI 官方 Key**：\n"
            "`/setkey openai 你的Key`\n"
            "若使用第三方兼容服务，可带上 Base URL：\n"
            "`/setkey openai 你的Key https://api.siliconflow.cn/v1`\n"
            "⚠️ 该服务必须**同时支持语音转写与图片理解**。"
            "DeepSeek 等纯文本服务用不了：它没有音频转写端点、也不接受图片输入。\n\n"
            "*(发送后，机器人会自动从聊天记录中删除你的密钥消息，保障隐私安全)*",
            parse_mode="Markdown"
        )
        return False, None

    return True, config

def _md_code(value: object) -> str:
    """放进 Markdown 代码块里展示。反引号会提前闭合代码块，
    导致整条消息被 Telegram 判为解析失败而整条丢掉，所以先摘掉。"""
    return str(value).replace("`", "")

def render_model_overview(stored: UserConfig, resolved: UserConfig, markup: bool = True) -> str:
    """当前档位清单。markup=True 给 Telegram（Markdown），False 给 CLI 纯文本。

    只列用户绑过 Key 的那一家：只有 Gemini Key 就是 2 行，只有 OpenAI Key 也是 2 行。
    """
    def code(text: object) -> str:
        return f"`{_md_code(text)}`" if markup else str(text)

    def bold(text: str) -> str:
        return f"**{text}**" if markup else text

    roles = available_roles(resolved)
    if not roles:
        return (
            f"{bold('⚠️ 你还没有绑定任何 API Key，暂时没有可配置的模型档位。')}\n"
            f"请先发送 {code('/setkey gemini 你的Key')} 或 {code('/setkey openai 你的Key')}。"
        )

    lines = [bold("🧠 当前模型档位"), ""]
    for role in roles:
        info = describe_role(stored, resolved, role)
        # chat 档写两个字段，正常同步；只有手改过 config.json 才会出现两个值，如实列出。
        shown = " / ".join(code(value) for value in info["values"])
        source = "个人设置" if info["pinned"] else "跟随 .env"
        lines.append(f"- {bold(role)}（{info['label']}）：{shown} — {source}")
    return "\n".join(lines)

def render_role_tokens(resolved: UserConfig) -> str:
    roles = available_roles(resolved)
    return "、".join(f"`{role}`" for role in roles) if roles else "（无）"

def _role_not_available_text(role: str, resolved: UserConfig) -> str:
    meta = get_role(role)
    provider = meta["provider"] if meta else "?"
    return (
        f"❌ 档位 `{role}` 属于 `{provider}`，但你还没有绑定该提供商的 Key，配置了也不会生效。\n"
        f"你当前可配置的档位：{render_role_tokens(resolved)}\n"
        f"如需使用，请先 {_md_code(f'/setkey {provider} 你的Key')}"
    )

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    config = user_config_manager.get_user_config(user.id)
    config.username = user.username
    config.first_name = user.first_name
    user_config_manager.save_user_config(config)

    effective = user_config_manager.resolve_config(user.id)
    has_key = effective.has_valid_key()
    status_text = (
        f"✅ 已就绪 (当前模型提供商: `{effective.active_provider}`, Key 来源: {effective.key_source_label()})"
        if has_key else "⚠️ **尚未绑定 API Key**（需先设置）"
    )

    welcome_text = (
        f"👋 你好，{user.first_name}！欢迎使用 **ChronoMirror (溯镜)** 个人认知复盘外脑。\n\n"
        f"🔑 **当前状态**：{status_text}\n\n"
        "💡 **核心功能**：\n"
        "- 💬 发送文字：记录闪念、想法、工作待办\n"
        "- 🎙️ 发送语音：自动识别口语转文字归档\n"
        "- 📸 发送照片：视觉模型即时提炼饮食、穿搭、场景特征（节省 90% Token）\n\n"
        "⚡ **常用指令**：\n"
        "- `/setkey`：绑定或切换 Gemini / OpenAI API Key\n"
        "- `/switch`：在 Gemini 和 OpenAI 之间快速切换\n"
        "- `/setmodel`：查看/调整各档位使用的模型（不设置则跟随默认）\n"
        "- `/status`：查看当前绑定的 Key 状态与配置\n"
        "- `/today`：查看今日时间流记录\n"
        "- `/review`：立即生成今日深度日复盘\n"
        "- `/weekly`：立即生成本周战略复盘并沉淀长期画像\n"
        "- `/profile`：查看当前积累的个人长期画像 (L3 Memory)\n"
        "- `/id`：查看当前 Telegram User ID\n"
    )

    if not has_key:
        welcome_text += (
            "\n❗ **请先绑定 Key 开启使用**：\n"
            "例如发送：`/setkey gemini 你的GeminiKey`"
        )

    await update.effective_message.reply_text(welcome_text, parse_mode="Markdown")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.effective_message.reply_text(f"你的 Telegram User ID 是: `{user.id}`", parse_mode="Markdown")

async def setkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    # Delete the message containing sensitive key if possible
    try:
        await update.effective_message.delete()
    except Exception:
        pass

    args = context.args
    if not args or len(args) < 2:
        config = user_config_manager.resolve_config(user.id)
        help_text = (
            "⚙️ **API Key 设置指令帮助**\n\n"
            "用法格式：\n"
            "`/setkey <gemini|openai> <api_key> [可选BaseURL]`\n\n"
            "📝 **示例**：\n"
            "1. 绑定 Gemini Key：\n"
            "   `/setkey gemini AIzaSyDxxxxxxxxx`\n\n"
            "2. 绑定 OpenAI 原生 Key：\n"
            "   `/setkey openai sk-proj-xxxxxxxxx`\n\n"
            "3. 绑定第三方兼容接口（须同时支持语音转写与图片理解）：\n"
            "   `/setkey openai sk-xxxx https://api.siliconflow.cn/v1`\n"
            "   ⚠️ DeepSeek 等纯文本服务用不了：没有音频转写端点，也不接受图片输入。\n\n"
            "🔍 **当前绑定状态**：\n"
            f"- 当前生效提供商: `{config.active_provider}`\n"
            f"- Gemini Key: `{config.masked_gemini_key()}`\n"
            f"- OpenAI Key: `{config.masked_openai_key()}`\n"
            f"- OpenAI Base URL: `{config.openai_base_url or '官方默认'}`\n"
            f"- Key 来源: {config.key_source_label()}\n"
        )
        await update.effective_chat.send_message(help_text, parse_mode="Markdown")
        return

    provider = args[0].lower().strip()
    api_key = args[1].strip()
    base_url = args[2].strip() if len(args) > 2 else None

    config = user_config_manager.get_user_config(user.id)
    config.username = user.username
    config.first_name = user.first_name

    if provider == "gemini":
        config.gemini_api_key = api_key
        config.active_provider = "gemini"
        user_config_manager.save_user_config(config)
        await update.effective_chat.send_message(
            f"✅ **Google Gemini API Key 绑定成功！**\n"
            f"- 当前提供商已自动切换为: `gemini`\n"
            f"- 掩码密钥: `{config.masked_gemini_key()}`\n\n"
            "🔒 *提示：包含明文密钥的消息已被自动清理，你可以随时开始记录或复盘了！*",
            parse_mode="Markdown"
        )
    elif provider == "openai":
        config.openai_api_key = api_key
        config.active_provider = "openai"
        if base_url:
            config.openai_base_url = base_url
        user_config_manager.save_user_config(config)
        await update.effective_chat.send_message(
            f"✅ **OpenAI 兼容 API Key 绑定成功！**\n"
            f"- 当前提供商已自动切换为: `openai`\n"
            f"- 掩码密钥: `{config.masked_openai_key()}`\n"
            f"- Base URL: `{config.openai_base_url or 'https://api.openai.com/v1'}`\n\n"
            "🔒 *提示：包含明文密钥的消息已被自动清理，你可以随时开始记录或复盘了！*",
            parse_mode="Markdown"
        )
    else:
        await update.effective_chat.send_message(
            "❌ 无效的提供商类型！目前支持 `gemini` 或 `openai`。\n"
            "正确示例: `/setkey gemini 你的Key` 或 `/setkey openai 你的Key`"
        )

async def setmodel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """按档位覆盖模型。不设置时一律跟随 .env 的默认值，所以绑完 Key 就能用。"""
    user = update.effective_user
    if not user:
        return

    # 必须读"存储副本"再写：resolve_config 的副本里带着 .env 的兜底 Key，
    # 直接存会把部署者的全局 Key 写进用户的 config.json。
    stored = user_config_manager.get_user_config(user.id)
    resolved = user_config_manager.resolve_config(user.id)
    args = context.args or []

    # 无参数：只列出"你绑过 Key 的那一家"的档位
    if not args:
        await update.effective_message.reply_text(
            render_model_overview(stored, resolved)
            + "\n\n🔧 调整：`/setmodel <档位> <模型名>`\n"
              "↩️ 恢复默认：`/setmodel reset <档位|all>`",
            parse_mode="Markdown",
        )
        return

    head = args[0].strip().lower()

    if head in ("reset", "clear"):
        if len(args) < 2:
            await update.effective_message.reply_text(
                f"格式：`/setmodel reset <档位|all>`\n可用档位：{render_role_tokens(resolved)}",
                parse_mode="Markdown",
            )
            return

        target = args[1].strip().lower()
        if target == "all":
            for field_name in _MODEL_FIELDS:
                setattr(stored, field_name, None)
            stored.gemini_model = None  # 旧字段，一并清掉
        elif get_role(target) is None:
            await update.effective_message.reply_text(
                f"❌ 未知档位 `{target}`。\n可用档位：{render_role_tokens(resolved)}",
                parse_mode="Markdown",
            )
            return
        elif target not in available_roles(resolved):
            await update.effective_message.reply_text(
                _role_not_available_text(target, resolved), parse_mode="Markdown"
            )
            return
        else:
            apply_role_value(stored, target, None)

        user_config_manager.save_user_config(stored)
        refreshed = user_config_manager.resolve_config(user.id)
        await update.effective_message.reply_text(
            f"✅ 已恢复为跟随 `.env` 默认值。\n\n"
            f"{render_model_overview(stored, refreshed)}\n\n"
            "*下次调用即刻生效，无需重启。*",
            parse_mode="Markdown",
        )
        return

    role = head
    if get_role(role) is None:
        await update.effective_message.reply_text(
            f"❌ 未知档位 `{_md_code(role)}`。\n可用档位：{render_role_tokens(resolved)}",
            parse_mode="Markdown",
        )
        return

    if role not in available_roles(resolved):
        await update.effective_message.reply_text(
            _role_not_available_text(role, resolved), parse_mode="Markdown"
        )
        return

    if len(args) < 2:
        await update.effective_message.reply_text(
            f"格式：`/setmodel {role} <模型名>`\n"
            f"例如：`/setmodel {role} {describe_role(stored, resolved, role)['values'][0]}`",
            parse_mode="Markdown",
        )
        return

    model_name, error = normalize_model_name(" ".join(args[1:]))
    if error:
        await update.effective_message.reply_text(
            f"❌ {error}\n例如：`/setmodel {role} gemini-3.5-flash-lite`",
            parse_mode="Markdown",
        )
        return

    apply_role_value(stored, role, model_name)
    user_config_manager.save_user_config(stored)

    refreshed = user_config_manager.resolve_config(user.id)
    await update.effective_message.reply_text(
        f"✅ 档位 {role}（{describe_role(stored, refreshed, role)['label']}）"
        f"已设置为 `{_md_code(model_name)}`。\n\n"
        f"{render_model_overview(stored, refreshed)}\n\n"
        "*下次调用即刻生效，无需重启。*",
        parse_mode="Markdown",
    )

async def switch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    config = user_config_manager.get_user_config(user.id)
    
    args = context.args
    target_provider = args[0].lower().strip() if args else None

    if not target_provider:
        # Toggle between gemini and openai
        target_provider = "openai" if config.active_provider == "gemini" else "gemini"

    if target_provider not in ("gemini", "openai"):
        await update.effective_message.reply_text("❌ 只支持切换至 `gemini` 或 `openai`。")
        return

    config.active_provider = target_provider
    user_config_manager.save_user_config(config)

    effective = user_config_manager.resolve_config(user.id)
    has_key = effective.has_valid_key()
    key_tip = (
        f"✅ 密钥已就绪 (来源: {effective.key_source_label()})" if has_key
        else "⚠️ 注意：该提供商尚未配置 Key，请用 `/setkey` 配置"
    )
    await update.effective_message.reply_text(
        f"🔄 当前生效的 AI 模型提供商已切换为: `{target_provider}`\n{key_tip}",
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # stored 用来区分"个人设置"和"跟随 .env"：resolve_config 的副本已经把默认值
    # 填满了，光看它分不出来。这一行以前标签写的是"当前生效模型"，实际打印的却是提供商。
    stored = user_config_manager.get_user_config(user.id)
    config = user_config_manager.resolve_config(user.id)

    status_text = (
        f"📊 **ChronoMirror 账户配置状态**\n\n"
        f"- **User ID**: `{user.id}`\n"
        f"- **用户**: {user.first_name} (@{user.username or '无'})\n"
        f"- **当前提供商**: `{config.active_provider}`\n"
        f"- **Gemini 状态**: `{config.masked_gemini_key()}`\n"
        f"- **OpenAI 状态**: `{config.masked_openai_key()}`\n"
        f"- **OpenAI BaseURL**: `{config.openai_base_url or '官方默认'}`\n"
        f"- **Key 来源**: {config.key_source_label()}\n"
        f"- **是否可正常使用**: {'✅ 是' if config.has_valid_key() else '❌ 否 (需设置 Key)'}\n\n"
        f"{render_model_overview(stored, config)}"
    )
    await update.effective_message.reply_text(status_text, parse_mode="Markdown")

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, _ = await ensure_user_ready(update)
    if not ok:
        return
    user_id = update.effective_user.id
    today_str = settings.today().strftime("%Y-%m-%d")
    content = await storage.get_daily_log(user_id, today_str)
    if not content:
        await update.effective_message.reply_text(f"今日 ({today_str}) 还没有任何记录，随时发点文字、语音或照片吧！")
        return
    await send_long_message(update, f"📋 【今日记录流水账】\n\n{content}")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, _ = await ensure_user_ready(update)
    if not ok:
        return
    user_id = update.effective_user.id
    profile_content = await storage.get_user_profile(user_id)
    await send_long_message(update, f"👤 【当前长期画像 (L3 Memory)】\n\n{profile_content}")

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, _ = await ensure_user_ready(update)
    if not ok:
        return
    user_id = update.effective_user.id

    target_date = None
    if context.args:
        target_date = context.args[0].strip()

    date_label = target_date or settings.today().strftime("%Y-%m-%d")
    status_msg = await update.effective_message.reply_text(f"🤖 正在为 {date_label} 进行深度日复盘与思维诊断，请稍候...")

    success, review_text, path = await review_engine.run_daily_review(user_id=user_id, target_date=target_date)
    if not success:
        await status_msg.edit_text(f"⚠️ 复盘未生成: {review_text}")
        return

    await status_msg.delete()
    await send_long_message(update, review_text)

async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, _ = await ensure_user_ready(update)
    if not ok:
        return
    user_id = update.effective_user.id

    status_msg = await update.effective_message.reply_text("📊 正在汇总过去 7 天的复盘，生成周度战略分析并更新长期画像...")
    success, weekly_text, path = await review_engine.run_weekly_review(user_id=user_id)
    if not success:
        await status_msg.edit_text(f"⚠️ 周复盘未生成: {weekly_text}")
        return

    await status_msg.delete()
    await send_long_message(update, weekly_text)

# --- Message Handlers (Capture Layer) ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, _ = await ensure_user_ready(update)
    if not ok:
        return

    user_id = update.effective_user.id
    text = update.effective_message.text
    now = settings.now()
    time_str = now.strftime("%H:%M:%S")

    await storage.append_log(user_id=user_id, content=text, tag="文字记录", dt=now)
    preview = text if len(text) < 30 else text[:27] + "..."
    await update.effective_message.reply_text(f"✅ 已记下 [{time_str}]: {preview}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, user_config = await ensure_user_ready(update)
    if not ok:
        return

    user_id = update.effective_user.id
    voice = update.effective_message.voice
    status_msg = await update.effective_message.reply_text("🎙️ 正在下载并转写语音，请稍候...")

    try:
        tg_file = await voice.get_file()
        file_bytes = await tg_file.download_as_bytearray()

        now = settings.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        filename = f"voice_{timestamp_str}.ogg"

        # Save attachment in user folder
        saved_path, rel_path = await storage.save_attachment(user_id=user_id, file_bytes=bytes(file_bytes), filename=filename)

        # Transcribe with user's config
        transcript = await llm.transcribe_audio(audio_path=saved_path, user_config=user_config, mime_type="audio/ogg")
        if not transcript:
            transcript = "（未能识别出有效语音文字）"

        # Append to log
        log_entry = f"语音转写：{transcript}"
        await storage.append_log(user_id=user_id, content=log_entry, tag="语音记录", dt=now, attachment_rel_path=rel_path)

        await status_msg.edit_text(f"🎙️ 已转写归档 [{now.strftime('%H:%M:%S')}]:\n\n{transcript}")
    except Exception as e:
        log_llm_error(e, context="voice", user_id=user_id)
        await status_msg.edit_text(f"❌ 语音处理失败。\n{describe_llm_error(e, '转写语音')}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, user_config = await ensure_user_ready(update)
    if not ok:
        return

    user_id = update.effective_user.id
    photo = update.effective_message.photo[-1]
    caption = update.effective_message.caption or ""
    status_msg = await update.effective_message.reply_text("📸 正在提取照片特征并进行文字降维...")

    try:
        tg_file = await photo.get_file()
        file_bytes = await tg_file.download_as_bytearray()

        now = settings.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp_str}.jpg"

        # Save attachment in user folder
        saved_path, rel_path = await storage.save_attachment(user_id=user_id, file_bytes=bytes(file_bytes), filename=filename)

        # Analyze image with user's config
        description = await llm.describe_image(
            image_bytes=bytes(file_bytes),
            user_config=user_config,
            mime_type="image/jpeg",
            user_caption=caption
        )

        # Append to log
        entry_parts = []
        if caption:
            entry_parts.append(f"用户说明：{caption}")
        entry_parts.append(description)
        log_entry = "\n".join(entry_parts)

        await storage.append_log(user_id=user_id, content=log_entry, tag="视觉记录", dt=now, attachment_rel_path=rel_path)

        await status_msg.edit_text(f"📸 影像特征已归档 [{now.strftime('%H:%M:%S')}]:\n\n{description}")
    except Exception as e:
        log_llm_error(e, context="photo", user_id=user_id)
        await status_msg.edit_text(f"❌ 图片解析失败。\n{describe_llm_error(e, '分析照片')}")

from telegram.request import HTTPXRequest

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """兜底错误处理器：只记日志，绝不把异常原文发回聊天窗口。"""
    error = context.error
    if isinstance(error, TelegramError) and not isinstance(error, (NetworkError, TimedOut)):
        # 消息本身的毛病（被拉黑、实体解析失败等），不是代码 bug，不必刷堆栈
        logger.warning(f"Telegram 交互异常 (自动恢复): {type(error).__name__}: {redact_secrets(str(error))}")
        return
    logger.error(f"未处理的异常: {type(error).__name__}: {redact_secrets(str(error))}", exc_info=error)

def build_telegram_app(scheduler=None):
    if not settings.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN 未配置，请在 .env 中设置")

    req_kwargs = {
        "connect_timeout": 30.0,
        "read_timeout": 35.0,
        "write_timeout": 30.0,
        "pool_timeout": 30.0,
    }
    if settings.TELEGRAM_PROXY:
        req_kwargs["proxy"] = settings.TELEGRAM_PROXY

    request = HTTPXRequest(connection_pool_size=16, media_write_timeout=60.0, **req_kwargs)
    get_updates_request = HTTPXRequest(connection_pool_size=16, **req_kwargs)

    builder = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .request(request)
        .get_updates_request(get_updates_request)
    )

    if scheduler:
        async def on_post_init(application):
            scheduler.set_bot(application.bot)
            scheduler.start()

        builder = builder.post_init(on_post_init)

    async def on_post_shutdown(application):
        """停机时释放所有长连接，避免进程退出前留下未关闭的连接池。"""
        if scheduler:
            scheduler.stop()
        await llm.aclose()

    builder = builder.post_shutdown(on_post_shutdown)

    app = builder.build()
    app.add_error_handler(global_error_handler)

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("setkey", setkey_command))
    app.add_handler(CommandHandler("setmodel", setmodel_command))
    app.add_handler(CommandHandler("switch", switch_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("weekly", weekly_command))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    return app
