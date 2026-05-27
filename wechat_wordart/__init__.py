"""
wechat-wordart
微信聊天记录 → 分词 → 情感筛选 → SVG 词画

模块结构：
  parser/      解析 txt/csv 导出文件
  segmenter/   jieba 分词 + 词频统计
  sentiment/   Ollama 情感筛选（可选）
  wordlist/    生成 JSON 词表
  renderer/    渲染 SVG 词画
  server/      轻量 HTTP 接口
"""

__version__ = "0.1.0"
