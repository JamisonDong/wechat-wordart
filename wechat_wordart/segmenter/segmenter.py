"""
基于 jieba 的中文分词 + 词频统计模块。

功能：
  - 加载内置停用词表 + 用户自定义停用词
  - 过滤纯数字、URL、单字（可配置）
  - 返回 {word: count} 字典，按频率降序
"""

import re
import os
from collections import Counter
from pathlib import Path
from typing import List, Dict, Optional

import jieba
import jieba.analyse  # TF-IDF（备用）

# 内置停用词表路径
_STOPWORDS_PATH = Path(__file__).parent / "stopwords.txt"

# 过滤模式：纯数字、纯标点、URL
_RE_NOISE = re.compile(
    r"^[\d\s.,!?，。！？、；：“”‘’【】《》（）\[\]{}@#$%^&*+=|\\/<>~`\-]+$"
    r"|^https?://"
    r"|^www\."
)


class Segmenter:
    """jieba 分词 + 词频统计器。"""

    def __init__(
        self,
        min_word_length: int = 2,
        top_n: int = 200,
        extra_stopwords: Optional[List[str]] = None,
        user_dict: Optional[str] = None,
    ):
        self.min_word_length = min_word_length
        self.top_n = top_n

        # 加载停用词
        self._stopwords: set = self._load_stopwords()
        if extra_stopwords:
            self._stopwords.update(extra_stopwords)

        # 加载用户自定义词典
        if user_dict and os.path.exists(user_dict):
            jieba.load_userdict(user_dict)
            print(f"[segmenter] 已加载自定义词典：{user_dict}")

        jieba.setLogLevel("WARNING")  # 静默 jieba 初始化日志

    @staticmethod
    def _load_stopwords() -> set:
        stopwords = set()
        if _STOPWORDS_PATH.exists():
            with open(_STOPWORDS_PATH, encoding="utf-8") as f:
                for line in f:
                    w = line.strip()
                    if w:
                        stopwords.add(w)
        return stopwords

    def _is_valid(self, word: str) -> bool:
        """过滤无意义词。"""
        if len(word) < self.min_word_length:
            return False
        if _RE_NOISE.match(word):
            return False
        if word in self._stopwords:
            return False
        return True

    def segment(self, texts: List[str]) -> Dict[str, int]:
        """
        对消息列表分词并统计词频。

        Args:
            texts: 消息正文列表

        Returns:
            {word: count} 字典，按频率降序，最多 top_n 个
        """
        counter: Counter = Counter()

        for text in texts:
            # 简单预处理：去掉表情符号（Unicode emoji 区间）
            text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
            text = re.sub(r"[\U0001F300-\U0001F9FF]", "", text)

            words = jieba.lcut(text, cut_all=False)
            for w in words:
                w = w.strip()
                if self._is_valid(w):
                    counter[w] += 1

        result = dict(counter.most_common(self.top_n))
        print(f"[segmenter] 分词完成：{len(counter)} 个独立词，返回前 {len(result)} 个")
        return result
