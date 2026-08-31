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


def _apply_defaults(cfg: dict) -> dict:
    """为缺省字段填充默认值（config 文件与无 config 两种路径共用）。"""
    cfg.setdefault("input", {})
    cfg["input"].setdefault("format", "txt")
    cfg["input"].setdefault("encoding", "utf-8")
    cfg.setdefault("segmenter", {})
    cfg.setdefault("sentiment", {"enabled": False})
    cfg.setdefault("wordlist", {})
    cfg.setdefault("renderer", {})
    cfg.setdefault("eink", {})
    # eink 默认值：适配主流 7.5寸 800x480，同时兼容 4.2寸 400x300 通过 config 覆盖
    cfg["eink"].setdefault("enabled", True)
    cfg["eink"].setdefault("width", 800)
    cfg["eink"].setdefault("height", 480)
    cfg["eink"].setdefault("output_path", "output/eink.bmp")
    cfg["eink"].setdefault("max_font_size", 72)
    cfg["eink"].setdefault("min_font_size", 14)
    cfg.setdefault("server", {})
    return cfg


def load_config(path: str) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        print("❌ 请先安装 PyYAML：pip install pyyaml")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    return _apply_defaults(cfg)


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


# ── Step 5b: 渲染 E-ink 位图 ────────────────────────────────────────────────

def step_eink(wordlist: List[dict], cfg: dict) -> str:
    """渲染 1-bit 墨水屏位图（供 ESP32 直刷）。"""
    eink_cfg = cfg.get("eink", {})
    if not eink_cfg.get("enabled", True):
        print("[pipeline] E-ink 渲染已禁用，跳过")
        return ""

    try:
        from wechat_wordart.renderer import EinkRenderer
    except ImportError as e:
        print(f"[pipeline] ⚠ 跳过 eink 渲染：{e}")
        print("    请安装 Pillow：pip install Pillow")
        return ""

    renderer = EinkRenderer(config=eink_cfg)
    return renderer.render(
        wordlist=wordlist,
        output_path=eink_cfg.get("output_path", "output/eink.bmp"),
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
    all_steps = ["parse", "segment", "sentiment", "wordlist", "render", "eink"]
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

        elif step == "eink":
            if not wordlist:
                wl_path = cfg.get("wordlist", {}).get("output_path", "output/wordlist.json")
                if Path(wl_path).exists():
                    with open(wl_path, encoding="utf-8") as f:
                        wordlist = json.load(f)
                    print(f"[pipeline] ℹ  从 {wl_path} 加载词表")
                else:
                    raise RuntimeError("eink 步骤需要先运行 wordlist 或有已有 wordlist.json")
            step_eink(wordlist, cfg)

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
        help="配置文件路径（默认 config.yaml；不存在且提供了 --input 时使用内置默认值）",
    )
    parser.add_argument(
        "--input", "-i",
        help="聊天记录文件路径，覆盖 config 中的 input.path（可直接生成，无需 config）",
    )
    parser.add_argument(
        "--format", "-f", choices=["txt", "csv"],
        help="输入格式，覆盖 config 中的 input.format",
    )
    parser.add_argument(
        "--output-dir", "-o",
        help="输出目录，覆盖 wordlist.json / wordart.svg 的输出路径",
    )
    parser.add_argument(
        "--no-sentiment", action="store_true",
        help="强制关闭情感筛选（等价于 --skip sentiment）",
    )
    parser.add_argument(
        "--step", "-s", nargs="+",
        choices=["parse", "segment", "sentiment", "wordlist", "render", "eink", "serve"],
        help="只运行指定步骤（可多选）",
    )
    parser.add_argument(
        "--skip", nargs="+",
        choices=["parse", "segment", "sentiment", "wordlist", "render", "eink"],
        help="跳过指定步骤",
    )

    args = parser.parse_args()

    # 加载配置：有 config 文件则读，否则在提供 --input 时用内置默认值
    if Path(args.config).exists():
        cfg = load_config(args.config)
    elif args.input:
        print(f"[pipeline] 未找到配置文件 {args.config}，使用内置默认值（仅需 --input）")
        cfg = _apply_defaults({})
    else:
        print(f"❌ 配置文件不存在：{args.config}")
        print("   请复制 config.example.yaml → config.yaml 并按需修改，")
        print("   或直接指定输入文件：python pipeline.py --input data/chat.txt")
        sys.exit(1)

    # 应用命令行覆盖
    if args.input:
        cfg["input"]["path"] = args.input
    if args.format:
        cfg["input"]["format"] = args.format
    if args.output_dir:
        out = Path(args.output_dir)
        cfg["wordlist"]["output_path"] = str(out / "wordlist.json")
        cfg["renderer"]["output_path"] = str(out / "wordart.svg")
        cfg["eink"]["output_path"] = str(out / "eink.bmp")
        cfg["server"]["output_dir"] = str(out)
    if args.no_sentiment:
        cfg["sentiment"]["enabled"] = False

    skip = list(args.skip or [])
    if args.no_sentiment and "sentiment" not in skip:
        skip.append("sentiment")

    # 友好校验：将要解析却找不到输入文件时，提前给出清晰提示（而非抛栈）
    active = args.step or ["parse", "segment", "sentiment", "wordlist", "render", "eink"]
    if "parse" in active and "parse" not in skip:
        in_path = cfg["input"].get("path")
        if not in_path:
            print("❌ 未指定输入文件，请用 --input 指定，或在 config 的 input.path 中设置")
            sys.exit(1)
        if not Path(in_path).exists():
            print(f"❌ 输入文件不存在：{in_path}")
            sys.exit(1)

    try:
        run_pipeline(cfg, steps=args.step, skip=skip or None)
    except KeyboardInterrupt:
        print("\n[pipeline] 已中断")
    except Exception as e:
        print(f"\n❌ 执行失败：{e}")
        raise


if __name__ == "__main__":
    main()
