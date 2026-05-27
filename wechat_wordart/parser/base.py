"""解析器基类及消息数据类。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class Message:
    """单条聊天消息。"""
    timestamp: str      # 原始时间字符串，如 "2024-01-15 10:30:45"
    sender: str         # 发送者昵称
    content: str        # 消息正文（纯文本）
    raw: str = field(default="", repr=False)  # 原始行（调试用）


class BaseParser(ABC):
    """聊天记录解析器抽象基类。"""

    @abstractmethod
    def parse(self, filepath: str, encoding: str = "utf-8") -> List[Message]:
        """
        解析导出文件，返回消息列表。

        Args:
            filepath: 文件路径
            encoding: 文件编码

        Returns:
            Message 对象列表
        """

    @staticmethod
    def _is_media_placeholder(text: str) -> bool:
        """判断是否为系统提示/媒体占位符，不计入词频。"""
        placeholders = [
            "[图片]", "[视频]", "[语音]", "[文件]", "[表情]",
            "[链接]", "[撤回了一条消息]", "[位置]", "[红包]",
            "[音乐]", "[名片]", "[转账]", "[语音通话]", "[视频通话]",
            "<img", "<audio", "[Photo]", "[Video]",
        ]
        t = text.strip()
        return any(t.startswith(p) or t == p for p in placeholders)
