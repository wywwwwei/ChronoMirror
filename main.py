import argparse
import asyncio
import logging
import sys
from pathlib import Path

from config.settings import settings
from core.storage import storage
from core.review_engine import review_engine
from core.scheduler import ReviewScheduler
from bot.telegram_bot import build_telegram_app

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("PersonalGrowth")

async def run_cli_mode():
    """Terminal interactive test mode (no Telegram bot token needed)"""
    print("\n" + "=" * 50)
    print("🧠 欢迎进入 PersonalGrowth 本地终端交互模式")
    print("=" * 50)
    print("指令说明:")
    print("  1. 记录文字 (直接输入文字)")
    print("  2. /today   (查看今日流水账)")
    print("  3. /review  (手动生成今日日复盘)")
    print("  4. /weekly  (手动生成本周复盘)")
    print("  5. /profile (查看长期画像)")
    print("  6. /exit    (退出)")
    print("=" * 50 + "\n")

    while True:
        try:
            user_input = input("Growth> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            break

        if not user_input:
            continue
        if user_input in ("/exit", "exit", "quit"):
            print("再见！")
            break
        elif user_input == "/today":
            import datetime
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            content = await storage.get_daily_log(today_str)
            if not content:
                print(f"今日 ({today_str}) 暂无记录。")
            else:
                print(f"\n--- 今日记录流水账 ---\n{content}\n---------------------")
        elif user_input.startswith("/review"):
            parts = user_input.split()
            target_date = parts[1] if len(parts) > 1 else None
            print(f"正在生成复盘 (当前 LLM: {settings.DEFAULT_LLM_PROVIDER})...")
            success, res, path = await review_engine.run_daily_review(target_date)
            print(f"\n{res}\n")
            if path:
                print(f"已保存到: {path}")
        elif user_input == "/weekly":
            print(f"正在生成周复盘 (当前 LLM: {settings.DEFAULT_LLM_PROVIDER})...")
            success, res, path = await review_engine.run_weekly_review()
            print(f"\n{res}\n")
            if path:
                print(f"已保存到: {path}")
        elif user_input == "/profile":
            prof = await storage.get_user_profile()
            print(f"\n--- 长期画像与思维模型 (L3) ---\n{prof}\n-------------------------------")
        else:
            await storage.append_log(content=user_input, tag="终端文字记录")
            print("✅ 已记录到今日流水账！")

def main():
    parser = argparse.ArgumentParser(description="PersonalGrowth AI Review Assistant")
    parser.add_argument("--cli", action="store_true", help="以本地终端命令行交互模式运行（无需 Telegram Token）")
    parser.add_argument("--test-review", action="store_true", help="直接测试运行今天的复盘生成")
    args = parser.parse_args()

    if args.cli:
        asyncio.run(run_cli_mode())
        return

    if args.test_review:
        async def _test():
            success, res, path = await review_engine.run_daily_review()
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

    logger.info("正在启动 PersonalGrowth Telegram 机器人与定时复盘服务...")
    telegram_app = build_telegram_app()

    # Setup Scheduler
    scheduler = ReviewScheduler(bot=telegram_app.bot)
    scheduler.start()

    try:
        # Run long polling
        telegram_app.run_polling(drop_pending_updates=True)
    finally:
        scheduler.stop()

if __name__ == "__main__":
    main()
