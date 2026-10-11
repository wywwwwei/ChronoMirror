"""运行日志的装配：stdout + 轮转日志文件，统一走 RedactingFormatter。

单独成一个模块、而不是写在 main.py 里，是为了能在测试里直接装配它：
import main 会连带执行整个入口模块（包括模块级的装配调用），测试要么在仓库里
建出 logs/ 目录污染工作区，要么得绕一圈先打补丁再导入。
"""
import logging
import logging.handlers
from typing import List, Optional

from config.settings import settings
from core.llm_errors import RedactingFormatter

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_FILE_NAME = "chronomirror.log"
# 2MB × 5 份，上限约 10MB。私人日记应用的日志量很小，这个量级够翻很久了。
LOG_FILE_MAX_BYTES = 2 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 5


def file_handler() -> Optional[logging.Handler]:
    """轮转日志文件 handler；建不出来就返回 None，由调用方降级为只打 stdout。

    只有 stdout 的话，容器里能不能翻到旧日志完全取决于 docker 的日志驱动策略
    （json-file 默认也不轮转，跑久了照样把磁盘写满），真出事时往往已经滚没了。
    所以自己再落一份并按大小轮转。

    日志目录不可写（只读文件系统、权限不足）时不能让机器人起不来——这是可观测性，
    不该成为启动前提，所以这里吞掉 OSError 交给调用方降级。
    """
    try:
        settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
        return logging.handlers.RotatingFileHandler(
            settings.LOG_DIR / LOG_FILE_NAME,
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None


def configure_logging() -> None:
    """装配 root logger。由入口模块在启动时调用一次。

    两个 handler 共用同一个 RedactingFormatter：脱敏必须对落盘同样生效。日志文件
    比 stdout 活得更久，明文令牌留在文件里比一闪而过更糟。
    """
    formatter = RedactingFormatter(LOG_FORMAT)
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    rolling_file = file_handler()
    if rolling_file is not None:
        handlers.append(rolling_file)
    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=logging.INFO, handlers=handlers)
    # httpx 每次长轮询都打一行 INFO，噪音大且是令牌泄露的主要来源
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger = logging.getLogger("ChronoMirror")
    if rolling_file is not None:
        logger.info(
            f"运行日志同时写入 {settings.LOG_DIR / LOG_FILE_NAME}"
            f"（按大小轮转，保留 {LOG_FILE_BACKUP_COUNT} 份）"
        )
    else:
        logger.warning(f"无法在 {settings.LOG_DIR} 创建日志文件，本次只在标准输出打印运行日志。")
