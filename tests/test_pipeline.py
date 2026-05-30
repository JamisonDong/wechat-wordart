#!/usr/bin/env python3
"""
端到端冒烟 / 回归测试（纯标准库，无需 pytest）。

直接运行：
    python tests/test_pipeline.py
或用 pytest：
    pytest tests/

覆盖点（含两个已修 bug 的回归）：
  - parser   ：解析示例聊天、过滤媒体占位符
  - segmenter：分词出主题词、滤掉停用词；噪声正则正确（修复 raw string 截断）
  - wordlist ：JSON 结构、权重归一化、最高权重为 1.0
  - renderer ：所有词都被放置（修复螺旋布局只放 9/100 的 bug）、SVG 合法且在界内
"""

import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

# 让测试可在仓库任意位置运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SAMPLE = ROOT / "data" / "sample_chat.txt"

from wechat_wordart.parser import get_parser
from wechat_wordart.segmenter import Segmenter
from wechat_wordart.segmenter.segmenter import _RE_NOISE
from wechat_wordart.wordlist import WordlistGenerator
from wechat_wordart.renderer import SVGRenderer


def _messages():
    assert SAMPLE.exists(), f"缺少示例数据：{SAMPLE}"
    return get_parser("txt").parse(str(SAMPLE))


def test_parser_filters_media_placeholders():
    msgs = _messages()
    assert len(msgs) > 0, "应解析出消息"
    joined = "\n".join(m.content for m in msgs)
    for ph in ("[图片]", "[语音]", "[链接]", "[表情]"):
        assert ph not in joined, f"媒体占位符未被过滤：{ph}"


def test_noise_regex_is_well_formed():
    # 回归：raw string 曾被中间的 ASCII 引号截断，导致非法转义警告 + 正则错误。
    # 纯标点/数字应判为噪声，正常中文词不应。
    assert _RE_NOISE.match("，。！？")
    assert _RE_NOISE.match("12345")
    assert _RE_NOISE.match("https://example.com")
    assert _RE_NOISE.match("“”‘’")  # 中文弯引号应在噪声字符集中
    assert not _RE_NOISE.match("工作")
    assert not _RE_NOISE.match("旅行")


def test_segmenter_keeps_themes_drops_stopwords():
    counts = Segmenter(min_word_length=2, top_n=200).segment(
        [m.content for m in _messages()]
    )
    assert counts, "应得到词频"
    for theme in ("工作", "旅行", "生活"):
        assert theme in counts, f"主题词缺失：{theme}"
    for stop in ("的", "了", "我", "你"):
        assert stop not in counts, f"停用词未过滤：{stop}"


def test_wordlist_structure_and_weights():
    counts = Segmenter().segment([m.content for m in _messages()])
    with tempfile.TemporaryDirectory() as d:
        wl = WordlistGenerator(top_n=100, output_path=str(Path(d) / "wl.json")).generate(counts)
    assert wl, "词表不应为空"
    assert set(wl[0]) == {"word", "weight", "count", "updated_at"}
    assert wl[0]["weight"] == 1.0, "最高频词权重应为 1.0"
    assert all(0.0 <= w["weight"] <= 1.0 for w in wl), "权重应归一化到 [0,1]"
    # 按 count 降序
    assert all(wl[i]["count"] >= wl[i + 1]["count"] for i in range(len(wl) - 1))


def test_renderer_places_all_words_in_bounds():
    counts = Segmenter().segment([m.content for m in _messages()])
    with tempfile.TemporaryDirectory() as d:
        wl = WordlistGenerator(top_n=100, output_path=str(Path(d) / "wl.json")).generate(counts)
        svg_path = str(Path(d) / "art.svg")
        cfg = {"width": 800, "height": 600}
        svg = SVGRenderer(config=cfg).render(wordlist=wl, output_path=svg_path)

    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    texts = root.findall(".//svg:text", ns)
    # 回归：螺旋太小 + 一失败即 break 曾导致只放 9/100。现在应全部放置。
    assert len(texts) == len(wl), f"应放置全部 {len(wl)} 个词，实际 {len(texts)}"
    W, H = int(root.get("width")), int(root.get("height"))
    for t in texts:
        x, y = float(t.get("x")), float(t.get("y"))
        assert 0 <= x <= W and 0 <= y <= H, f"文本锚点越界：({x},{y})"


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # 任何 SyntaxWarning/DeprecationWarning 直接判失败
        for t in tests:
            try:
                t()
                print(f"  ✓ {t.__name__}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{'❌' if failed else '✅'} {len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
