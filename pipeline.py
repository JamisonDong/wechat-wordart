#!/usr/bin/env python3
"""
WeChat WordArt — 主管道

用法：
  # 完整流程
  python pipeline.py --config config.yaml

  # 单步运行
  python pipeline.py --config config.yaml --step parse
  python pipeline.py --config config.yaml --step segment
  python pipeline.py --config config.yaml --step sentiment
  python pipeline.py --config config.yaml --step wordlist
  python pipeline.py --config config.yaml --step render
  python pipeline.py --config config.yaml --step serve

  # 跳过某步骤（例如不做情感筛选）
  python pipeline.py --config config.yaml --skip sentiment

各模块也可单独导入使用：
  from wechat_wordart.parser import get_parser
  from wechat_wordart.segmenter import Segmenter
  ...
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


def load_config(path: str) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        print("❌ 请先安装 PyYAML：pip install pyyaml")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 设置默认值
    cfg.setdefault("input", {})
    cfg["input"].setdefault("format", "txt")
    cfg["input"].setdefault("encoding", "utf-8")
    cfg.setdefault("segmenter", {})
    cfg.setdefault("sentiment", {"enabled": False})
    cfg.setdefault("wordlist", {})
    cfg.setdefault("renderer", {})
    cfg.setdefault("server", {})
    return cfg


# ── Step 1: 解析 ─────────────────────────────────────────────────────────────

def step_parse(cfg: dict) -> List[str]:
    """解析聊天记录，返回消息正文列表。"""
    from wechat_wordart.parser import get_parser

    inp = cfg["input"]
    parser = get_parser(inp.get("format", "txt"))
    messages = parser.parse(
        filepath=inp["path"],
        encoding=inp.get("encoding", "utf-8"),
    )
    return [m.content for m in messages]


# ── Step 2: 分词 ─────────────────────────────────────────────────────────────

def step_segment(texts: List[str], cfg: dict) -> dict:
    """jieba 分词 + 词频统计。"""
    from wechat_wordart.segmenter import Segmenter

    seg_cfg = cfg.get("segmenter", {})
    segmenter = Segmenter(
        min_word_length=seg_cfg.get("min_word_length", 2),
        top_n=seg_cfg.get("top_n", 200),
        extra_stopwords=seg_cfg.get("extra_stopwords", []),
        user_dict=seg_cfg.get("user_dict"),
    )
    return segmenter.segment(texts)


# ── Step 3: 情感筛选（可选）───────────────────────────────────────────────────

def step_sentiment(word_counts: dict, cfg: dict) -> dict:
    """Ollama 情感筛选（disabled 时直接透传）。"""
    sent_cfg = cfg.get("sentiment", {})
    if not sent_cfg.get("enabled", False):
        print("[pipeline] 情感筛选已禁用，跳过")
        return word_counts

    from wechat_wordart.sentiment import OllamaFilter

    filt = OllamaFilter(
        model=sent_cfg.get("model", "qwen2:7b"),
        base_url=sent_cfg.get("base_url", "http://localhost:11434"),
        filter_negative=sent_cfg.get("filter_negative", True),
        batch_size=sent_cfg.get("batch_size", 50),
    )
    return filt.filter(word_counts)


# ── Step 4: 生成词表 ─────────────────────────────────────────────────────────

def step_wordlist(word_counts: dict, cfg: dict) -> List[dict]:
    """生成并写入 wordlist.json。"""
    from wechat_wordart.wordlist import WordlistGenerator

    wl_cfg = cfg.get("wordlist", {})
    gen = WordlistGenerator(
        top_n=wl_cfg.get("top_n", 100),
        output_path=wl_cfg.get("output_path", "output/wordlist.json"),
    )
    return gen.generate(word_counts)


# ── Step 5: 渲染 SVG ─────────────────────────────────────────────────────────

def step_render(wordlist: List[dict], cfg: dict) -> str:
    """渲染 SVG 词画。"""
    from wechat_wordart.renderer import SVGRenderer

    r_cfg = cfg.get("renderer", {})
    renderer = SVGRenderer(config=r_cfg)
    return renderer.render(
        wordlist=wordlist,
        output_path=r_cfg.get("output_path", "output/wordart.svg"),
    )


# ── Step 6: 启动服务 ─────────────────────────────────────────────────────────

def step_serve(cfg: dict):
    """启动 HTTP 服务（阻塞）。"""
    from wechat_wordart.server import WordArtServer

    srv_cfg = cfg.get("server", {})
    server = WordArtServer(
        host=srv_cfg.get("host", "0.0.0.0"),
        port=srv_cfg.get("port", 8765),
        output_dir=srv_cfg.get("output_dir", "output"),
    )
    server.serve_forever()


# ── 主程序 ───────────────────────────────────────────────────────────────────

def run_pipeline(cfg: dict, steps: Optional[List[str]] = None, skip: Optional[List[str]] = None):
    all_steps = ["parse", "segment", "sentiment", "wordlist", "render"]
    active = steps if steps else all_steps
    skipped = set(skip or [])

    texts = []
    word_counts = {}
    wordlist = []

    for step in active:
        if step in skipped:
            print(f"[pipeline] ⏭  跳过步骤：{step}")
            continue

        print(f"\n[pipeline] ▶  步骤：{step}")

        if step == "parse":
            texts = step_parse(cfg)
            print(f"[pipeline] ✓  解析完成，共 {len(texts)} 条消息")

        elif step == "segment":
            if not texts:
                raise RuntimeError("segment 步骤需要先运行 parse")
            word_counts = step_segment(texts, cfg)

        elif step == "sentiment":
            if not word_counts:
                # 尝试从已有词表加载
                wl_path = cfg.get("wordlist", {}).get("output_path", "output/wordlist.json")
                if Path(wl_path).exists():
                    with open(wl_path, encoding="utf-8") as f:
                        wl = json.load(f)
                    word_counts = {item["word"]: item["count"] for item in wl}
                    print(f"[pipeline] ℹ  从 {wl_path} 加载词频数据")
                else:
                    raise RuntimeError("sentiment 步骤需要先运行 segment 或有已有词表")
            word_counts = step_sentiment(word_counts, cfg)

        elif step == "wordlist":
            if not word_counts:
                raise RuntimeError("wordlist 步骤需要先运行 segment")
            wordlist = step_wordlist(word_counts, cfg)

        elif step == "render":
            if not wordlist:
                # 尝试从已有词表文件加载
                wl_path = cfg.get("wordlist", {}).get("output_path", "output/wordlist.json")
                if Path(wl_path).exists():
                    with open(wl_path, encoding="utf-8") as f:
                        wordlist = json.load(f)
                    print(f"[pipeline] ℹ  从 {wl_path} 加载词表")
                else:
                    raise RuntimeError("render 步骤需要先运行 wordlist 或有已有 wordlist.json")
            step_render(wordlist, cfg)

        elif step == "serve":
            step_serve(cfg)

        print(f"[pipeline] ✓  {step} 完成")

    print("\n[pipeline] 🎉  全部步骤执行完毕")


def main():
    parser = argparse.ArgumentParser(
        description="WeChat WordArt Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", "-c", default="config.yaml",
        help="配置文件路径（默认 config.yaml）",
    )
    parser.add_argument(
        "--step", "-s", nargs="+",
        choices=["parse", "segment", "sentiment", "wordlist", "render", "serve"],
        help="只运行指定步骤（可多选）",
    )
    parser.add_argument(
        "--skip", nargs="+",
        choices=["parse", "segment", "sentiment", "wordlist", "render"],
        help="跳过指定步骤",
    )

    args = parser.parse_args()

    if not Path(args.config).exists():
        print(f"❌ 配置文件不存在：{args.config}")
        print("   请复制 config.example.yaml → config.yaml 并按需修改")
        sys.exit(1)

    cfg = load_config(args.config)

    try:
        run_pipeline(cfg, steps=args.step, skip=args.skip)
    except KeyboardInterrupt:
        print("\n[pipeline] 已中断")
    except Exception as e:
        print(f"\n❌ 执行失败：{e}")
        raise


if __name__ == "__main__":
    main()
