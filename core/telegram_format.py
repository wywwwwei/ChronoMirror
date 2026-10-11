"""把 LLM 输出的 Markdown 转成 Telegram 能渲染的 HTML，并安全切分长消息。

为什么不用 parse_mode="Markdown"：
1. Telegram 的 legacy Markdown 只认 `*bold*`、`_italic_`、`` `code` ``，
   而模型的习惯输出是 `**bold**`、`## 标题`、`- 列表`，直接发出去就是一堆
   裸露的星号和井号——复盘推送里的粗体就是这么丢的；
2. legacy Markdown 只要出现不成对的 `*` / `_` / `` ` ``（比如用户日记里的
   `snake_case`、`2*3`）就会整条消息报 "Can't parse entities" 发不出去；
3. 切分长消息时按字符数硬切，会把 `**` 或 `` ` `` 劈成两半，两边都解析失败。

HTML 模式配合显式转义没有 2、3 两个问题，所以统一走 HTML。
"""
import re
from typing import List, Tuple

# Telegram 单条消息上限是 4096 个 UTF-16 码元（emoji 算 2）。留出余量，
# 因为下面还会插入闭合标签。
TELEGRAM_MESSAGE_LIMIT = 3500

_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)")
_HORIZONTAL_RULE_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")


def escape_html(text: str) -> str:
    """Telegram HTML 模式只要求转义这三个字符"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _convert_inline(text: str) -> str:
    """处理行内语法。入参必须是已经转义过的文本。"""
    # 行内代码先摘出来，避免里面的 * 被当成粗体
    placeholders: List[str] = []

    def _stash(match: "re.Match[str]") -> str:
        placeholders.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(placeholders) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", _stash, text)

    text = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _BOLD_RE.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BOLD_UNDERSCORE_RE.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _STRIKE_RE.sub(lambda m: f"<s>{m.group(1)}</s>", text)
    text = _ITALIC_STAR_RE.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _ITALIC_UNDERSCORE_RE.sub(lambda m: f"<i>{m.group(1)}</i>", text)

    for index, snippet in enumerate(placeholders):
        text = text.replace(f"\x00{index}\x00", snippet)
    return text


def markdown_to_telegram_html(text: str) -> str:
    """把模型输出的 Markdown 子集转成 Telegram HTML。

    只做保守转换：能识别的语法转成实体，识别不了的保持原样（已转义），
    宁可少一点样式，也不要因为解析失败整条消息发不出去。
    """
    if not text:
        return ""

    lines = text.split("\n")
    out: List[str] = []
    in_fence = False
    fence_buffer: List[str] = []
    paragraph_buffer: List[str] = []
    quote_buffer: List[str] = []

    def flush_paragraph() -> None:
        if paragraph_buffer:
            out.append(_convert_inline(escape_html("\n".join(paragraph_buffer))))
            paragraph_buffer.clear()

    def flush_quote() -> None:
        if quote_buffer:
            body = _convert_inline(escape_html("\n".join(quote_buffer)))
            out.append(f"<blockquote>{body}</blockquote>")
            quote_buffer.clear()

    def flush_all() -> None:
        flush_paragraph()
        flush_quote()

    for line in lines:
        fence_match = _FENCE_RE.match(line.strip())

        if in_fence:
            if fence_match:
                out.append("<pre>" + escape_html("\n".join(fence_buffer)) + "</pre>")
                fence_buffer.clear()
                in_fence = False
            else:
                fence_buffer.append(line)
            continue

        if fence_match:
            flush_all()
            in_fence = True
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            flush_paragraph()
            quote_buffer.append(quote.group(1))
            continue
        flush_quote()

        if not line.strip():
            flush_paragraph()
            out.append("")
            continue

        if _HORIZONTAL_RULE_RE.match(line):
            flush_paragraph()
            out.append("──────────")
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            out.append(f"<b>{_convert_inline(escape_html(heading.group(2).strip()))}</b>")
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_paragraph()
            indent = "  " * (len(bullet.group(1)) // 2)
            out.append(f"{indent}• {_convert_inline(escape_html(bullet.group(2)))}")
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            flush_paragraph()
            indent = "  " * (len(ordered.group(1)) // 2)
            out.append(f"{indent}{ordered.group(2)}. {_convert_inline(escape_html(ordered.group(3)))}")
            continue

        paragraph_buffer.append(line)

    # 收尾：未闭合的代码块按普通文本处理，避免整段丢失
    if in_fence:
        out.append("<pre>" + escape_html("\n".join(fence_buffer)) + "</pre>")
    flush_all()

    return "\n".join(out)


def utf16_len(text: str) -> int:
    """Telegram 按 UTF-16 码元计数，emoji 等补充平面字符算 2"""
    return len(text.encode("utf-16-le")) // 2


_OPEN_TAG_RE = re.compile(r"<(b|i|u|s|code|pre|blockquote|a)(\s[^>]*)?>")
_CLOSE_TAG_RE = re.compile(r"</(b|i|u|s|code|pre|blockquote|a)>")


def _open_tags(chunk: str) -> List[Tuple[str, str]]:
    """返回 chunk 结束时仍未闭合的标签，形如 [("<b>", "</b>")]"""
    stack: List[str] = []
    for token in re.finditer(r"<(/?)(b|i|u|s|code|pre|blockquote|a)(\s[^>]*)?>", chunk):
        closing, name, attrs = token.group(1), token.group(2), token.group(3)
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
        else:
            stack.append(name)
    return [(f"<{name}>", f"</{name}>") for name in stack]


def split_html_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> List[str]:
    """按 Telegram 长度上限切分，并保证每段标签闭合。

    切分点优先取空行，其次取换行，最后才硬切；跨越切分点的标签会自动在
    上一段结尾补齐、下一段开头重新打开，这样模型输出的长粗体段落不会因为
    被切开而整段解析失败。
    """
    if not text:
        return []
    if utf16_len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text
    carry: List[Tuple[str, str]] = []

    while remaining:
        prefix = "".join(open_tag for open_tag, _ in carry)
        budget = limit - utf16_len(prefix)

        if utf16_len(remaining) <= budget:
            body, remaining = remaining, ""
        else:
            cut = _find_cut(remaining, budget)
            body, remaining = remaining[:cut], remaining[cut:]

        chunk = prefix + body
        carry = _open_tags(chunk)
        suffix = "".join(close_tag for _, close_tag in reversed(carry))
        chunks.append(chunk + suffix)

        if remaining:
            # 下一段从干净状态开始，前面已补过闭合标签
            remaining = remaining.lstrip("\n")

    return [c for c in chunks if c.strip()]


def _find_cut(text: str, budget: int) -> int:
    """在 budget 之内找一个自然的切分点（返回字符下标）"""
    window = text[:budget]
    for separator in ("\n\n", "\n"):
        index = window.rfind(separator)
        if index > budget // 4:
            return index + len(separator)

    # 退无可退时按空格切，避免把单词劈开；再不行才硬切
    index = window.rfind(" ")
    if index > budget // 2:
        return index + 1
    return max(budget, 1)


def prepare_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> List[str]:
    """Markdown -> 已转义、已切分、标签闭合的 HTML 片段列表"""
    return split_html_message(markdown_to_telegram_html(text), limit=limit)


def strip_tags(text: str) -> str:
    """兜底：去掉标签并还原实体，用于 HTML 发送失败时的纯文本重试"""
    no_tags = re.sub(r"</?(?:b|i|u|s|code|pre|blockquote|a)(?:\s[^>]*)?>", "", text)
    return no_tags.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
