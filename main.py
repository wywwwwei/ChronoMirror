import argparse
import asyncio
import logging
import sys
from pathlib import Path

from config.settings import settings
from core.storage import storage
from core.review_engine import review_engine
from core.scheduler import ReviewScheduler
from core.user_config import user_config_manager
from bot.telegram_bot import build_telegram_app

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ChronoMirror")

CLI_USER_ID = 99999

async def run_cli_mode():
    """Terminal interactive test mode (no Telegram bot token needed)"""
    config = user_config_manager.get_user_config(CLI_USER_ID)
    
    # Auto-populate from .env if available for CLI convenience
    if not config.gemini_api_key and settings.GEMINI_API_KEY:
        config.gemini_api_key = settings.GEMINI_API_KEY
        config.active_provider = "gemini"
        user_config_manager.save_user_config(config)
    elif not config.openai_api_key and settings.OPENAI_API_KEY:
        config.openai_api_key = settings.OPENAI_API_KEY
        config.openai_base_url = settings.OPENAI_BASE_URL
        config.active_provider = "openai"
        user_config_manager.save_user_config(config)

    print("\n" + "=" * 55)
    print("🪞 欢迎进入 ChronoMirror (溯镜) 本地终端交互模式")
    print("=" * 55)
    print(f"当前测试用户 ID: {CLI_USER_ID}")
    print(f"当前提供商: {config.active_provider} | 密钥状态: {'✅ 已配置' if config.has_valid_key() else '⚠️ 未配置 (请用 /setkey)'}")
    print("指令说明:")
    print("  1. 记录文字 (直接输入文字回车)")
    print("  2. /setkey  (绑定 Key: /setkey gemini <key> 或 /setkey openai <key> [url])")
    print("  3. /status  (查看当前 Key 状态)")
    print("  4. /today   (查看今日流水账)")
    print("  5. /review  (手动生成今日日复盘)")
    print("  6. /weekly  (手动生成本周复盘)")
    print("  7. /profile (查看长期画像)")
    print("  8. /exit    (退出)")
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
            if prov == "gemini":
                config.gemini_api_key = key
                config.active_provider = "gemini"
            elif prov == "openai":
                config.openai_api_key = key
                config.active_provider = "openai"
                if url:
                    config.openai_base_url = url
            user_config_manager.save_user_config(config)
            print(f"✅ {prov} Key 设置成功！当前生效: {config.active_provider}")
        elif user_input == "/status":
            print(f"提供商: {config.active_provider}, Gemini: {config.masked_gemini_key()}, OpenAI: {config.masked_openai_key()}")
        elif user_input == "/today":
            import datetime
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            content = await storage.get_daily_log(CLI_USER_ID, today_str)
            if not content:
                print(f"今日 ({today_str}) 暂无记录。")
            else:
                print(f"\n--- 今日记录流水账 ---\n{content}\n---------------------")
        elif user_input.startswith("/review"):
            parts = user_input.split()
            target_date = parts[1] if len(parts) > 1 else None
            print(f"正在生成复盘 (用户: {CLI_USER_ID}, LLM: {config.active_provider})...")
            success, res, path = await review_engine.run_daily_review(CLI_USER_ID, target_date)
            print(f"\n{res}\n")
            if path:
                print(f"已保存到: {path}")
        elif user_input == "/weekly":
            print(f"正在生成周复盘 (用户: {CLI_USER_ID}, LLM: {config.active_provider})...")
            success, res, path = await review_engine.run_weekly_review(CLI_USER_ID)
            print(f"\n{res}\n")
            if path:
                print(f"已保存到: {path}")
        elif user_input == "/profile":
            prof = await storage.get_user_profile(CLI_USER_ID)
            print(f"\n--- 长期画像与思维模型 (L3) ---\n{prof}\n-------------------------------")
        else:
            if not config.has_valid_key():
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
    scheduler = ReviewScheduler()
    telegram_app = build_telegram_app(scheduler=scheduler)

    # Run polling
    telegram_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
