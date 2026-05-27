"""
词表 JSON 生成模块。

输出格式：
[
  {"word": "朋友", "weight": 1.0,  "count": 342, "updated_at": "2024-01-15T10:30:45"},
  {"word": "生活", "weight": 0.87, "count": 298, "updated_at": "2024-01-15T10:30:45"},
  ...
]

weight 为归一化权重（0~1），count 为原始词频。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


class WordlistGenerator:
    """将词频字典转换为标准化 JSON 词表。"""

    def __init__(self, top_n: int = 100, output_path: str = "output/wordlist.json"):
        self.top_n = top_n
        self.output_path = output_path

    def generate(
        self,
        word_counts: Dict[str, int],
        timestamp: Optional[str] = None,
    ) -> List[dict]:
        """
        生成并写入词表 JSON。

        Args:
            word_counts: {word: count} 字典
            timestamp:   updated_at 时间戳（ISO 8601），默认取当前时间

        Returns:
            词表列表（同时写入文件）
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 排序 + 截断
        sorted_items = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[: self.top_n]

        if not sorted_items:
            print("[wordlist] 词表为空，跳过写入")
            return []

        max_count = sorted_items[0][1]
        min_count = sorted_items[-1][1]
        count_range = max(max_count - min_count, 1)

        wordlist = [
            {
                "word": word,
                "weight": round((count - min_count) / count_range, 4),
                "count": count,
                "updated_at": timestamp,
            }
            for word, count in sorted_items
        ]

        # 最高频词权重强制为 1.0
        if wordlist:
            wordlist[0]["weight"] = 1.0

        # 写入文件
        out = Path(self.output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(wordlist, f, ensure_ascii=False, indent=2)

        print(
            f"[wordlist] 词表已写入 {self.output_path}，共 {len(wordlist)} 个词，"
            f"最高频词：'{wordlist[0]['word']}' ({wordlist[0]['count']} 次)"
        )
        return wordlist
