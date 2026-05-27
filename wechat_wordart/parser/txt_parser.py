"""
微信聊天记录 TXT 格式解析器。

兼容多种常见导出格式：

格式 A（WeChatExporter / iOS 备份工具，最常见）:
    2024-01-15 10:30:45 张三
    你好，最近怎么样

    2024-01-15 10:31:00 李四
    还不错

格式 B（带冒号，单行）:
    2024-01-15 10:30:45 张三: 你好

格式 C（分隔线）:
    ────────────────
    2024/01/15 10:30
    张三
    你好

格式 D（方括号时间）:
    [2024-01-15 10:30:45] 张三: 你好
"""

import re
from typing import List, Optional, Tuple

from .base import BaseParser, Message

# 匹配各种时间戳 + 发送者 的行头
_HEADER_PATTERNS = [
    # [2024-01-15 10:30:45] 张三:  或  [2024-01-15 10:30:45] 张三
    re.compile(
        r"^\[(\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.+?)(?::\s*(.*))?$"
    ),
    # 2024-01-15 10:30:45 张三: 内容  或  2024-01-15 10:30:45 张三
    re.compile(
        r"^(\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s+(.+?)(?::\s*(.*))?$"
    ),
]


def _try_parse_header(line: str) -> Optional[Tuple[str, str, str]]:
    """
    尝试把一行解析为消息头。

    Returns:
        (timestamp, sender, inline_content) 或 None
    """
    for pat in _HEADER_PATTERNS:
        m = pat.match(line.strip())
        if m:
            ts = m.group(1)
            sender = m.group(2).strip()
            inline = (m.group(3) or "").strip()
            return ts, sender, inline
    return None


class TxtParser(BaseParser):
    """解析微信 TXT 导出文件。"""

    def parse(self, filepath: str, encoding: str = "utf-8") -> List[Message]:
        messages: List[Message] = []

        try:
            with open(filepath, encoding=encoding, errors="replace") as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise FileNotFoundError(f"文件不存在：{filepath}")

        current_ts: Optional[str] = None
        current_sender: Optional[str] = None
        content_lines: List[str] = []

        def flush():
            if current_ts and current_sender:
                text = "\n".join(content_lines).strip()
                if text and not BaseParser._is_media_placeholder(text):
                    messages.append(Message(
                        timestamp=current_ts,
                        sender=current_sender,
                        content=text,
                    ))

        for raw_line in lines:
            line = raw_line.rstrip("\n").rstrip("\r")

            # 跳过分隔线
            if re.match(r"^[─—\-=─*]{4,}", line):
                continue

            parsed = _try_parse_header(line)
            if parsed:
                flush()
                ts, sender, inline = parsed
                current_ts = ts
                current_sender = sender
                content_lines = [inline] if inline else []
            else:
                if current_ts is not None:
                    content_lines.append(line)

        flush()  # 最后一条

        print(f"[parser] TXT 解析完成：{len(messages)} 条有效消息，来自 {filepath}")
        return messages
