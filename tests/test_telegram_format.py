"""回归测试：复盘推送必须保留粗体等富文本，且长消息切分后仍能解析。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import re
import unittest

from core.telegram_format import (
    TELEGRAM_MESSAGE_LIMIT,
    markdown_to_telegram_html,
    prepare_message,
    split_html_message,
    strip_tags,
    utf16_len,
)


class MarkdownConversionTests(unittest.TestCase):
    def test_double_asterisk_becomes_bold(self):
        """这是本次修复的核心：模型写 **粗体**，之前原样发出去就是星号"""
        html = markdown_to_telegram_html("今天的**专注力峰值**在上午")
        self.assertIn("<b>专注力峰值</b>", html)
        self.assertNotIn("**", html)

    def test_heading_becomes_bold(self):
        self.assertIn("<b>今日能量曲线</b>", markdown_to_telegram_html("## 今日能量曲线"))

    def test_inline_code_and_fence(self):
        html = markdown_to_telegram_html("用 `45min` 完成\n\n```py\nx = 1 < 2\n```")
        self.assertIn("<code>45min</code>", html)
        self.assertIn("<pre>x = 1 &lt; 2</pre>", html)

    def test_bullet_list(self):
        html = markdown_to_telegram_html("- 任务 A\n- 任务 B")
        self.assertIn("• 任务 A", html)
        self.assertIn("• 任务 B", html)

    def test_strikethrough_and_italic(self):
        html = markdown_to_telegram_html("~~放弃了~~ 但 *坚持了* 一点")
        self.assertIn("<s>放弃了</s>", html)
        self.assertIn("<i>坚持了</i>", html)

    def test_link(self):
        html = markdown_to_telegram_html("详见 [日程](https://example.com/log)")
        self.assertIn('<a href="https://example.com/log">日程</a>', html)

    def test_blockquote(self):
        html = markdown_to_telegram_html("> 不做任何事\n> 也是如此")
        self.assertIn("<blockquote>", html)
        self.assertIn("不做任何事", html)

    def test_html_is_escaped(self):
        """用户日记里出现尖括号时，绝不能破坏实体解析"""
        html = markdown_to_telegram_html("我写了 <b>不是标签</b> 和 a & b")
        self.assertIn("&lt;b&gt;", html)
        self.assertIn("&amp;", html)
        self.assertNotIn("<b>不是标签</b>", html)

    def test_unbalanced_asterisk_does_not_break(self):
        """snake_case / 2*3 这类文本不能把整条消息搞成解析失败"""
        html = markdown_to_telegram_html("变量 user_id 和 2*3=6 都在")
        self.assertIn("user_id", html)
        self.assertIn("2*3=6", html)

    def test_code_span_protects_asterisks(self):
        html = markdown_to_telegram_html("`a**b**c` 保持原样")
        self.assertIn("<code>a**b**c</code>", html)

    def test_empty_input(self):
        self.assertEqual(markdown_to_telegram_html(""), "")
        self.assertEqual(prepare_message(""), [])


class SplittingTests(unittest.TestCase):
    def test_short_message_is_one_chunk(self):
        self.assertEqual(split_html_message("hello"), ["hello"])

    def test_long_message_respects_limit(self):
        text = "\n".join(f"第 {i} 行" * 20 for i in range(400))
        chunks = split_html_message(text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(utf16_len(chunk), TELEGRAM_MESSAGE_LIMIT)

    def test_tags_are_balanced_across_chunks(self):
        body = "这是一段很长的粗体内容。" * 500
        chunks = split_html_message(markdown_to_telegram_html(f"**{body}**"))
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(
                len(re.findall(r"<b>", chunk)), len(re.findall(r"</b>", chunk)),
                f"标签未闭合，这段消息会被 Telegram 拒绝:\n{chunk[:80]}...",
            )
        # 内容不能因为切分而丢失
        joined = "".join(re.sub(r"</?b>", "", c) for c in chunks)
        self.assertEqual(joined.count("这是一段很长的粗体内容。"), body.count("这是一段很长的粗体内容。"))

    def test_splits_on_line_boundaries_when_possible(self):
        text = "\n".join(["x" * 60] * 200)
        for chunk in split_html_message(text):
            self.assertFalse(chunk.startswith("x" * 200), "切分点落在了行中间")

    def test_prepare_message_end_to_end(self):
        review = "## 复盘\n\n**峰值**在上午\n" + "\n".join(
            f"- 条目 {i}：今天在深度工作上投入了较长时间，值得记录" for i in range(200)
        )
        chunks = prepare_message(review)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(any("<b>" in c for c in chunks))
        for chunk in chunks:
            self.assertLessEqual(utf16_len(chunk), TELEGRAM_MESSAGE_LIMIT)


class StripTagsTests(unittest.TestCase):
    def test_strip_and_unescape(self):
        self.assertEqual(strip_tags("<b>a</b> &lt;c&gt; &amp; d"), "a <c> & d")


if __name__ == "__main__":
    unittest.main()
