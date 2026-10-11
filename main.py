import argparse
import asyncio
import logging
import sys
from pathlib import Path

from config.settings import settings
from core.storage import storage
from core.review_engine import review_engine
from core.scheduler import ReviewScheduler
from core.user_config import (
    _MODEL_FIELDS,
    apply_role_value,
    available_roles,
    get_role,
    normalize_model_name,
    user_config_manager,
)
from bot.telegram_bot import build_telegram_app, render_model_overview, render_role_tokens

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ChronoMirror")

CLI_USER_ID = 99999

def log_startup_security_notice():
    """启动时把访问模式与 Key 兜底策略讲清楚，避免部署者以为自己配了白名单"""
    logger.info(f"当前时区: {settings.TIMEZONE}（日志文件名、复盘日期、定时触发均以此为准）")

    if settings.is_public_mode:
        if settings.has_explicit_public_mode:
            logger.warning("⚠️ 当前为【公开模式】(ALLOWED_USER_IDS='*')：任何 Telegram 用户都可以使用本机器人。")
        else:
            logger.warning(
                "⚠️ 未配置 ALLOWED_USER_IDS，当前为【公开模式】：任何 Telegram 用户都可以使用本机器人。"
                "自建自用请填写你的 User ID，或显式写 '*' 表明这是有意为之。"
            )
        if settings.env_llm_keys_configured:
            logger.warning(
                "⚠️ 检测到 .env 中配置了全局 LLM Key，但公开模式下【不会】作为用户兜底 Key 使用"
                "（否则陌生用户会消耗你的额度）。每位用户都必须自行发送 /setkey 绑定。"
            )
    else:
        logger.info(f"🔒 当前为【私有模式】：仅白名单用户 {settings.allowed_user_ids_list} 可用。")
        if settings.env_key_fallback_enabled:
            logger.info("ℹ️ 白名单用户未绑定个人 Key 时，将回落到 .env 中的全局 LLM Key。")

async def run_cli_mode():
    """Terminal interactive mode (no Telegram bot token needed).

    CLI 是部署者本机自用，因此允许直接使用 .env 的全局 Key 兜底，无需白名单。
    """
    def current_config():
        # 本地终端模式即"你自己在用"，允许直接使用 .env 的全局 Key；
        # 该副本只存在于内存，不会被写回 config.json。
        return user_config_manager.resolve_config(CLI_USER_ID, allow_env_fallback=True)

    config = current_config()

    print("\n" + "=" * 55)
    print("🪞 欢迎进入 ChronoMirror (溯镜) 本地终端交互模式")
    print("=" * 55)
    print(f"当前测试用户 ID: {CLI_USER_ID}")
    print(f"当前提供商: {config.active_provider} | 密钥状态: {'✅ 已配置' if config.has_valid_key() else '⚠️ 未配置 (请用 /setkey)'}")
    print(f"密钥来源: {config.key_source_label()}")
    print("指令说明:")
    print("  1. 记录文字 (直接输入文字回车)")
    print("  2. /setkey  (绑定 Key: /setkey gemini <key> 或 /setkey openai <key> [url])")
    print("  3. /setmodel (查看/调整模型档位: /setmodel <档位> <模型名> | /setmodel reset all)")
    print("  4. /status  (查看当前 Key 状态)")
    print("  5. /today   (查看今日流水账)")
    print("  6. /review  (手动生成今日日复盘)")
    print("  7. /weekly  (手动生成本周复盘)")
    print("  8. /profile (查看长期画像)")
    print("  9. /exit    (退出)")
    print("=" * 55 + "\n")

    while True:
        try:
            user_input = input("ChronoMirror> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            break

        if not user_input:
            continue
        if user_input in ("/exit", "exit", "quit"):
            print("再见！")
            break
        elif user_input.startswith("/setkey"):
            parts = user_input.split()
            if len(parts) < 3:
                print("格式: /setkey <gemini|openai> <api_key> [可选BaseURL]")
                continue
            prov = parts[1].lower()
            key = parts[2]
            url = parts[3] if len(parts) > 3 else None
            # 注意：必须改写"用户自己的配置"，不能用 resolve_config 的兜底副本，
            # 否则 .env 的全局 Key 会被一起写进 config.json。
            stored = user_config_manager.get_user_config(CLI_USER_ID)
            if prov == "gemini":
                stored.gemini_api_key = key
                stored.active_provider = "gemini"
            elif prov == "openai":
                stored.openai_api_key = key
                stored.active_provider = "openai"
                if url:
                    stored.openai_base_url = url
            else:
                print("❌ 只支持 gemini 或 openai。")
                continue
            user_config_manager.save_user_config(stored)
            print(f"✅ {prov} Key 设置成功！当前生效: {stored.active_provider}")
        elif user_input.startswith("/setmodel"):
            parts = user_input.split()
            # 与 /setkey 同理：改的必须是"用户自己的配置"，不能用 resolve_config 的
            # 兜底副本，否则 .env 的全局 Key 会被一起写进 config.json。
            stored = user_config_manager.get_user_config(CLI_USER_ID)
            resolved = current_config()

            if len(parts) == 1:
                print(render_model_overview(stored, resolved, markup=False))
            elif parts[1].lower() in ("reset", "clear"):
                if len(parts) < 3:
                    print(f"格式: /setmodel reset <档位|all>    可用档位: {render_role_tokens(resolved)}")
                    continue
                target = parts[2].lower()
                if target == "all":
                    for field_name in _MODEL_FIELDS:
                        setattr(stored, field_name, None)
                    stored.gemini_model = None
                elif get_role(target) is None or target not in available_roles(resolved):
                    print(f"❌ 档位 {target} 不可用。可用档位: {render_role_tokens(resolved)}")
                    continue
                else:
                    apply_role_value(stored, target, None)
                user_config_manager.save_user_config(stored)
                print("✅ 已恢复为跟随 .env 默认值。")
                print(render_model_overview(stored, current_config(), markup=False))
            elif len(parts) < 3:
                print(f"格式: /setmodel <档位> <模型名>    可用档位: {render_role_tokens(resolved)}")
            elif get_role(parts[1].lower()) is None or parts[1].lower() not in available_roles(resolved):
                print(f"❌ 档位 {parts[1].lower()} 不可用。可用档位: {render_role_tokens(resolved)}")
            else:
                model_name, error = normalize_model_name(" ".join(parts[2:]))
                if error:
                    print(f"❌ {error}")
                    continue
                role = parts[1].lower()
                apply_role_value(stored, role, model_name)
                user_config_manager.save_user_config(stored)
                print(f"✅ 档位 {role} 已设置为 {model_name}")
        elif user_input == "/status":
            config = current_config()
            print(
                f"提供商: {config.active_provider} | Key 来源: {config.key_source_label()} | "
                f"Gemini: {config.masked_gemini_key()}, OpenAI: {config.masked_openai_key()}"
            )
            print(render_model_overview(
                user_config_manager.get_user_config(CLI_USER_ID), config, markup=False
            ))
        elif user_input == "/today":
            today_str = settings.today().strftime("%Y-%m-%d")
            content = await storage.get_daily_log(CLI_USER_ID, today_str)
            if not content:
                print(f"今日 ({today_str}) 暂无记录。")
            else:
                print(f"\n--- 今日记录流水账 ---\n{content}\n---------------------")
        elif user_input.startswith("/review"):
            parts = user_input.split()
            target_date = parts[1] if len(parts) > 1 else None
            print(f"正在生成复盘 (用户: {CLI_USER_ID}, LLM: {current_config().active_provider})...")
            success, res, path = await review_engine.run_daily_review(CLI_USER_ID, target_date)
            print(f"\n{res}\n")
            if path:
                print(f"已保存到: {path}")
        elif user_input == "/weekly":
            print(f"正在生成周复盘 (用户: {CLI_USER_ID}, LLM: {current_config().active_provider})...")
            success, res, path = await review_engine.run_weekly_review(CLI_USER_ID)
            print(f"\n{res}\n")
            if path:
                print(f"已保存到: {path}")
        elif user_input == "/profile":
            prof = await storage.get_user_profile(CLI_USER_ID)
            print(f"\n--- 长期画像与思维模型 (L3) ---\n{prof}\n-------------------------------")
        else:
            if not current_config().has_valid_key():
                print("⚠️ 尚未绑定有效 API Key，请先执行 `/setkey gemini 你的Key` 或 `/setkey openai 你的Key`")
                continue
            await storage.append_log(user_id=CLI_USER_ID, content=user_input, tag="终端文字记录")
            print("✅ 已记录到今日流水账！")

def main():
    parser = argparse.ArgumentParser(description="ChronoMirror AI Review Assistant")
    parser.add_argument("--cli", action="store_true", help="以本地终端命令行交互模式运行（无需 Telegram Token）")
    parser.add_argument("--test-review", type=int, default=None, help="指定 user_id 测试运行今天的复盘生成")
    args = parser.parse_args()

    if args.cli:
        asyncio.run(run_cli_mode())
        return

    if args.test_review is not None:
        async def _test():
            success, res, path = await review_engine.run_daily_review(args.test_review)
            print(f"Status: {success}")
            print(res)
            if path:
                print(f"File: {path}")
        asyncio.run(_test())
        return

    # Check Telegram Token
    if not settings.TELEGRAM_BOT_TOKEN:
        print("\n❌ 错误: 未检测到 TELEGRAM_BOT_TOKEN！")
        print("请在 .env 文件中填入你的 Telegram Bot Token。")
        print("或者使用以下命令在本地终端先行体验:")
        print("   python main.py --cli\n")
        sys.exit(1)

    logger.info("正在启动 ChronoMirror Telegram 机器人与多用户定时复盘服务...")
    log_startup_security_notice()
    scheduler = ReviewScheduler()
    telegram_app = build_telegram_app(scheduler=scheduler)

    # Run polling with auto-retry and pending update processing
    telegram_app.run_polling(
        drop_pending_updates=False,
        timeout=20,
        poll_interval=0.5,
        bootstrap_retries=-1
    )

if __name__ == "__main__":
    main()
