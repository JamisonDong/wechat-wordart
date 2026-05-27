"""
基于本地 Ollama 的词汇情感筛选模块。

工作流：
  1. 将词表分批（batch_size 个）发给 Ollama
  2. 让模型判断每个词的情感（正面/中性/负面）
  3. 按配置过滤掉负面词
  4. 返回过滤后的 {word: count} 字典

注：此模块为可选步骤。若 Ollama 不可用，pipeline 会跳过此步骤。
"""

import json
import logging
from typing import Dict, List, Optional

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个中文词汇情感分类助手。
用户会给你一个词语列表（JSON 数组），请对每个词语判断情感倾向：
- positive（正面）
- neutral（中性）
- negative（负面）

请直接返回 JSON 对象，格式为：{"词语": "positive/neutral/negative", ...}
不要输出任何其他内容。"""

_USER_PROMPT_TEMPLATE = "请对以下词语进行情感分类：\n{words_json}"


class OllamaFilter:
    """调用本地 Ollama 接口对词表做情感筛选。"""

    def __init__(
        self,
        model: str = "qwen2:7b",
        base_url: str = "http://localhost:11434",
        filter_negative: bool = True,
        batch_size: int = 50,
        timeout: int = 30,
    ):
        if not _HAS_REQUESTS:
            raise ImportError("情感筛选需要 requests 库，请运行：pip install requests")

        self.model = model
        self.base_url = base_url.rstrip("/")
        self.filter_negative = filter_negative
        self.batch_size = batch_size
        self.timeout = timeout

    def is_available(self) -> bool:
        """检查 Ollama 服务是否可达。"""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def _classify_batch(self, words: List[str]) -> Dict[str, str]:
        """对一批词语调用 Ollama，返回 {word: sentiment}。"""
        words_json = json.dumps(words, ensure_ascii=False)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(words_json=words_json)},
            ],
            "stream": False,
            "options": {"temperature": 0.0},
        }

        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["message"]["content"].strip()

            # 兼容模型可能在 JSON 外包裹 markdown 代码块
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            result = json.loads(content)
            return {k: str(v).lower() for k, v in result.items()}

        except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[sentiment] 批次处理失败：{e}，跳过本批次")
            return {}

    def filter(self, word_counts: Dict[str, int]) -> Dict[str, int]:
        """
        对词表进行情感筛选。

        Args:
            word_counts: {word: count} 字典

        Returns:
            过滤后的 {word: count} 字典
        """
        if not self.is_available():
            logger.warning(
                f"[sentiment] Ollama 不可达（{self.base_url}），跳过情感筛选"
            )
            return word_counts

        words = list(word_counts.keys())
        sentiment_map: Dict[str, str] = {}

        # 分批处理
        for i in range(0, len(words), self.batch_size):
            batch = words[i : i + self.batch_size]
            result = self._classify_batch(batch)
            sentiment_map.update(result)
            print(
                f"[sentiment] 已处理 {min(i + self.batch_size, len(words))}/{len(words)} 个词"
            )

        if not sentiment_map:
            logger.warning("[sentiment] 未获得任何情感标注，返回原始词表")
            return word_counts

        # 过滤
        filtered = {}
        removed = []
        for word, count in word_counts.items():
            sentiment = sentiment_map.get(word, "neutral")
            if self.filter_negative and sentiment == "negative":
                removed.append(word)
            else:
                filtered[word] = count

        print(
            f"[sentiment] 筛选完成：保留 {len(filtered)} 个词，"
            f"移除 {len(removed)} 个负面词：{removed[:10]}{'...' if len(removed) > 10 else ''}"
        )
        return filtered
