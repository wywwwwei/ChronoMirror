"""把 LLM/网络异常转成可以安全展示给用户的提示，同时把原文留在服务端日志。

为什么不能直接把 str(e) 回吐给用户：

1. **会泄漏 API Key**。OpenAI 的 401 报文是
   `Incorrect API key provided: sk-proj-****abcd`，Gemini 报错里常带查询串
   `?key=AIza...`。机器人是公开的，把这些原文回显给陌生用户，等于把部署者
   （或该用户自己）的密钥片段贴进聊天记录。
2. **对用户毫无用处**。`429 RESOURCE_EXHAUSTED`、`model not found`、
   超时堆栈，用户既看不懂也不知道下一步该做什么。
3. **会带出内部信息**：请求 ID、内部 URL、base_url（可能含内网地址）。

所以：日志里记录脱敏后的原文（便于排查），用户侧只拿到分类后的可操作提示。
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# 常见密钥形态。日志也会经过脱敏——日志经常被收集、转发、贴进 issue。
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)api[_-]?key[\"'=:\s]+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)[?&]key=[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{20,}\b"),  # Telegram bot token 形态
)

REDACTED = "[REDACTED]"


def contains_secret_like(text: str) -> bool:
    """文本里是否出现了密钥形态的字符串"""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    """抹掉文本里的密钥片段。宁可多抹一点，也不能让密钥进日志或聊天窗口。"""
    if not text:
        return ""
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def _status_code_of(err: Exception) -> Optional[int]:
    for attr in ("status_code", "http_status", "code"):
        value = getattr(err, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    return None


# 顺序敏感：先匹配更具体的，再兜底
_RULES = (
    (
        ("incorrect api key", "invalid api key", "api key not valid", "unauthenticated",
         "invalid authentication", "no auth credentials", "api_key_invalid"),
        "🔑 你的 API Key 无效或已被撤销，请用 `/setkey` 重新绑定。",
    ),
    (
        ("insufficient_quota", "exceeded your current quota", "billing", "payment required",
         "余额", "quota exceeded", "free tier"),
        "💳 你的 API 账户额度不足或计费异常，请到服务商后台确认后重试。",
    ),
    (
        ("model not exist", "model_not_found", "does not exist", "not found for api version",
         "unknown model", "is not found", "unsupported model"),
        "🧩 当前配置的模型名不被服务商接受。请联系机器人管理员检查模型配置。",
    ),
    (
        ("rate limit", "resource_exhausted", "resource exhausted", "too many requests",
         "429", "quota exceeded per minute", "overloaded"),
        "⏳ 请求太频繁或服务端繁忙，已自动重试仍未成功，请过几分钟再试。",
    ),
    (
        ("safety", "blocked", "content filter", "prohibited", "recitation"),
        "🚫 内容被模型的安全策略拦截了，换一种说法或减少敏感信息后再试。",
    ),
    (
        ("timeout", "timed out", "connection", "unavailable", "502", "503", "504",
         "bad gateway", "service unavailable", "temporarily"),
        "🌐 连接 AI 服务失败（网络或服务端临时故障），请稍后重试。",
    ),
)

# 兜底启发式：报错里同时出现"密钥类字眼"和"客户端错误特征"时，按鉴权问题处理。
# 放在上面所有明确规则之后，避免把 "Rate limit reached for default-key"
# 这类消息误判成密钥问题。
_AUTH_WORDS = ("api key", "apikey", "api_key", "credential", "unauthorized",
               "forbidden", "permission", "auth")
_CLIENT_ERROR_MARKERS = ("400", "401", "403", "bad request", "client error",
                         "invalid_argument", "permission_denied")
_AUTH_HINT = "🔑 你的 API Key 无效、已过期或无权访问该模型，请用 `/setkey` 重新绑定。"


def describe_llm_error(err: Exception, action: str = "调用 AI 服务") -> str:
    """把异常翻译成给用户看的一句话。永不包含异常原文。"""
    code = _status_code_of(err)
    text = f"{type(err).__name__}: {err}".lower()

    if code is not None:
        if code in (401, 403):
            return "🔑 你的 API Key 无效、已过期或无权访问该模型，请用 `/setkey` 重新绑定。"
        if code == 402:
            return "💳 你的 API 账户额度不足，请到服务商后台充值后重试。"
        if code == 404:
            return "🧩 当前配置的模型名不存在。请联系机器人管理员检查模型配置。"
        if code == 429:
            return "⏳ 请求太频繁或服务端繁忙，已自动重试仍未成功，请过几分钟再试。"
        if code >= 500:
            return "🌐 AI 服务端临时故障，已自动重试仍未成功，请稍后重试。"

    for markers, message in _RULES:
        if any(marker in text for marker in markers):
            return message

    # 服务商只在鉴权失败时会把 Key 回显在报错里，所以"报文里出现密钥形态的
    # 字符串"本身就是很强的鉴权信号（同时也意味着这条原文绝不能外传）
    if (any(word in text for word in _AUTH_WORDS) or contains_secret_like(str(err))) \
            and any(m in text for m in _CLIENT_ERROR_MARKERS):
        return _AUTH_HINT

    return (
        f"❌ {action}失败。请稍后重试；若持续失败，可用 `/status` 检查配置，"
        "或联系机器人管理员查看服务端日志。"
    )


def log_llm_error(err: Exception, context: str = "", user_id: Optional[int] = None) -> None:
    """把脱敏后的原文写进服务端日志。用户看到的提示由 describe_llm_error 负责。"""
    where = f"[{context}]" if context else ""
    who = f" user={user_id}" if user_id is not None else ""
    logger.error(f"{where}{who} {type(err).__name__}: {redact_secrets(str(err))}")
