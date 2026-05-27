"""
微信聊天记录 CSV 格式解析器。

自动识别常见列名（大小写不敏感）：

| 时间列            | 发送者列       | 内容列         |
|-------------------|---------------|----------------|
| time / createtime | sender / from | content / msg  |
| 时间              | 发送者 / 昵称  | 消息 / 内容     |

若自动识别失败，可在 config.yaml 中手动指定列名。
"""

import csv
from typing import List, Dict, Optional

from .base import BaseParser, Message

# 候选列名（小写）
_TIME_KEYS = {"time", "createtime", "create_time", "timestamp", "时间", "发送时间"}
_SENDER_KEYS = {"sender", "from", "user", "nickname", "name", "发送者", "昵称", "用户"}
_CONTENT_KEYS = {"content", "msg", "message", "text", "body", "消息", "内容", "正文"}
_TYPE_KEYS = {"type", "msgtype", "消息类型"}


def _detect_columns(header: List[str]) -> Dict[str, int]:
    """自动检测列索引。"""
    lower = [h.strip().lower() for h in header]
    result: Dict[str, int] = {}

    for i, col in enumerate(lower):
        if col in _TIME_KEYS and "time" not in result:
            result["time"] = i
        elif col in _SENDER_KEYS and "sender" not in result:
            result["sender"] = i
        elif col in _CONTENT_KEYS and "content" not in result:
            result["content"] = i
        elif col in _TYPE_KEYS and "type" not in result:
            result["type"] = i

    return result


class CsvParser(BaseParser):
    """解析微信 CSV 导出文件。"""

    def __init__(
        self,
        time_col: Optional[str] = None,
        sender_col: Optional[str] = None,
        content_col: Optional[str] = None,
        type_col: Optional[str] = None,
        text_type_value: str = "1",  # 文字消息 type 值，通常为 "1" 或 "text"
    ):
        self.time_col = time_col
        self.sender_col = sender_col
        self.content_col = content_col
        self.type_col = type_col
        self.text_type_value = text_type_value

    def parse(self, filepath: str, encoding: str = "utf-8") -> List[Message]:
        messages: List[Message] = []

        try:
            with open(filepath, encoding=encoding, errors="replace", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None:
                    print("[parser] CSV 文件为空")
                    return messages

                # 优先使用手动配置，否则自动检测
                if self.time_col or self.sender_col or self.content_col:
                    cols: Dict[str, int] = {}
                    h_lower = [h.strip().lower() for h in header]
                    if self.time_col:
                        cols["time"] = h_lower.index(self.time_col.lower())
                    if self.sender_col:
                        cols["sender"] = h_lower.index(self.sender_col.lower())
                    if self.content_col:
                        cols["content"] = h_lower.index(self.content_col.lower())
                    if self.type_col:
                        cols["type"] = h_lower.index(self.type_col.lower())
                else:
                    cols = _detect_columns(header)

                if "content" not in cols:
                    raise ValueError(
                        f"无法识别内容列，CSV 表头为：{header}。"
                        "请在 config 中手动指定 content_col。"
                    )

                for row in reader:
                    if not row:
                        continue

                    # 类型过滤（若有 type 列）
                    if "type" in cols:
                        msg_type = row[cols["type"]].strip() if cols["type"] < len(row) else ""
                        # 只保留文字消息（type=1 或 text）
                        if msg_type and msg_type not in {"1", "text", "文字", ""}:
                            continue

                    content = row[cols["content"]].strip() if cols["content"] < len(row) else ""
                    if not content or BaseParser._is_media_placeholder(content):
                        continue

                    ts = row[cols["time"]].strip() if "time" in cols and cols["time"] < len(row) else ""
                    sender = row[cols["sender"]].strip() if "sender" in cols and cols["sender"] < len(row) else "unknown"

                    messages.append(Message(
                        timestamp=ts,
                        sender=sender,
                        content=content,
                    ))

        except FileNotFoundError:
            raise FileNotFoundError(f"文件不存在：{filepath}")

        print(f"[parser] CSV 解析完成：{len(messages)} 条有效消息，来自 {filepath}")
        return messages
