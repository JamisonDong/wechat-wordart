"""
SVG 词画渲染器。

纯 Python 实现，无需 Pillow / wordcloud 等图像依赖。

布局算法：
  1. 按权重降序排列
  2. 以画布中心为起点，螺旋向外放置
  3. 使用近似包围盒做碰撞检测
  4. 中文字符宽度 ≈ font_size，ASCII ≈ 0.6 * font_size
  5. 高频词随机旋转角度（-30°~30°），增加视觉层次

输出为标准 SVG 1.1 文件，可直接嵌入 HTML 或部署为静态资源。
"""

import math
import random
import html
from pathlib import Path
from typing import List, Dict, Tuple, Optional


class _Box:
    """轴对齐包围盒（AABB），用于碰撞检测。"""

    __slots__ = ("cx", "cy", "w", "h")

    def __init__(self, cx: float, cy: float, w: float, h: float):
        self.cx, self.cy, self.w, self.h = cx, cy, w, h

    @property
    def left(self): return self.cx - self.w / 2
    @property
    def right(self): return self.cx + self.w / 2
    @property
    def top(self): return self.cy - self.h / 2
    @property
    def bottom(self): return self.cy + self.h / 2

    def overlaps(self, other: "_Box", padding: float = 4.0) -> bool:
        return not (
            self.right + padding < other.left
            or self.left > other.right + padding
            or self.bottom + padding < other.top
            or self.top > other.bottom + padding
        )

    def in_bounds(self, width: float, height: float, margin: float = 8.0) -> bool:
        return (
            self.left >= margin
            and self.right <= width - margin
            and self.top >= margin
            and self.bottom <= height - margin
        )


def _char_width_ratio(c: str) -> float:
    """估算字符相对宽度（相对于 font_size）。"""
    cp = ord(c)
    # CJK 统一汉字 + 扩展区
    if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF:
        return 1.0
    # 全角字符
    if 0xFF01 <= cp <= 0xFF5E:
        return 1.0
    # 平假名 / 片假名
    if 0x3040 <= cp <= 0x30FF:
        return 1.0
    # ASCII
    return 0.6


def _estimate_text_size(word: str, font_size: float) -> Tuple[float, float]:
    """估算文字包围盒 (width, height)。"""
    width = sum(_char_width_ratio(c) for c in word) * font_size
    height = font_size * 1.25
    return width, height


class SVGRenderer:
    """将词表渲染为 SVG 词画。"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.width: int = cfg.get("width", 800)
        self.height: int = cfg.get("height", 600)
        self.max_font_size: float = cfg.get("max_font_size", 80)
        self.min_font_size: float = cfg.get("min_font_size", 12)
        self.font_family: str = cfg.get(
            "font_family",
            "PingFang SC, Noto Sans CJK SC, Microsoft YaHei, sans-serif",
        )
        self.colors: List[str] = cfg.get(
            "colors",
            ["#2C3E50", "#E74C3C", "#3498DB", "#27AE60", "#F39C12", "#9B59B6"],
        )
        self.background: str = cfg.get("background", "#FAFAFA")
        self._seed: int = cfg.get("seed", 42)

    # ── 内部工具 ─────────────────────────────────────────────────────────────

    def _font_size(self, weight: float) -> float:
        """将 0~1 权重映射到字体大小。"""
        # 使用平方根缩放，视觉上更均匀
        return self.min_font_size + (self.max_font_size - self.min_font_size) * math.sqrt(weight)

    def _spiral_offsets(self, step_px: float = 5.0, loop_spacing: float = 6.0):
        """
        阿基米德螺旋线 r = b*θ，按弧长自适应采样、扫满整个画布。

        - loop_spacing: 相邻两圈的径向间距（px），越小词排得越密
        - step_px:      同一圈上相邻候选点的弧长间距（px），越小采样越细

        先 yield 画布正中心 (0,0)，再沿螺旋向外，直到半径超过画布对角线半长。
        逐点 yield 相对中心的偏移 (dx, dy)，迭代次数有上界，不会无限循环。
        """
        max_r = math.hypot(self.width, self.height) / 2.0 + 10.0
        b = loop_spacing / (2.0 * math.pi)  # r = b*θ → 每圈径向增长 loop_spacing
        yield 0.0, 0.0                       # 最大的词优先落在正中心
        theta = step_px / max(b, 1e-6)       # 从一个非零半径起步，避免中心拥挤
        while True:
            r = b * theta
            if r > max_r:
                return
            yield r * math.cos(theta), r * math.sin(theta)
            theta += step_px / max(r, step_px)

    # ── 主渲染方法 ────────────────────────────────────────────────────────────

    def render(self, wordlist: List[dict], output_path: str) -> str:
        """
        渲染词表为 SVG 文件。

        Args:
            wordlist:    词表列表，每项含 word / weight 字段
            output_path: SVG 输出路径

        Returns:
            SVG 字符串内容
        """
        rng = random.Random(self._seed)
        words = sorted(wordlist, key=lambda x: x["weight"], reverse=True)

        cx, cy = self.width / 2.0, self.height / 2.0
        placed: List[_Box] = []
        elements: List[str] = []
        skipped = 0

        for idx, item in enumerate(words):
            word = html.escape(item["word"])
            weight = float(item.get("weight", 0.5))
            fs = self._font_size(weight)
            tw, th = _estimate_text_size(item["word"], fs)
            color = self.colors[idx % len(self.colors)]

            # 高权重词轻微随机旋转
            angle = 0.0
            if weight > 0.5:
                angle = rng.choice([0, 0, -30, 30, -15, 15])
            elif weight > 0.3:
                angle = rng.choice([0, 0, 0, -15, 15])

            # 若有旋转，需要扩展包围盒（近似）
            if angle != 0:
                rad = math.radians(abs(angle))
                rotated_w = tw * math.cos(rad) + th * math.sin(rad)
                rotated_h = tw * math.sin(rad) + th * math.cos(rad)
            else:
                rotated_w, rotated_h = tw, th

            # 沿螺旋尝试放置
            placed_ok = False
            for dx, dy in self._spiral_offsets():
                x, y = cx + dx, cy + dy
                box = _Box(x, y, rotated_w, rotated_h)

                if not box.in_bounds(self.width, self.height):
                    continue
                if any(box.overlaps(p) for p in placed):
                    continue

                placed.append(box)
                transform = ""
                if angle != 0:
                    transform = f' transform="rotate({angle},{x:.2f},{y:.2f})"'

                elements.append(
                    f'  <text'
                    f' x="{x:.2f}" y="{y:.2f}"'
                    f' font-size="{fs:.1f}"'
                    f' font-family="{self.font_family}"'
                    f' fill="{color}"'
                    f' text-anchor="middle"'
                    f' dominant-baseline="central"'
                    f'{transform}'
                    f'>{word}</text>'
                )
                placed_ok = True
                break

            if not placed_ok:
                # 当前词在画布内找不到不重叠的位置，跳过它继续尝试更小的词
                skipped += 1

        svg_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg"'
            f' width="{self.width}" height="{self.height}"'
            f' viewBox="0 0 {self.width} {self.height}">',
            f'  <rect width="{self.width}" height="{self.height}" fill="{self.background}"/>',
        ]
        svg_lines.extend(elements)
        svg_lines.append("</svg>")

        svg_content = "\n".join(svg_lines)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(svg_content)

        msg = (
            f"[renderer] SVG 已写入 {output_path}，"
            f"成功放置 {len(elements)}/{len(words)} 个词"
        )
        if skipped:
            msg += f"（{skipped} 个词因空间不足未放置，可增大画布或调小字号）"
        print(msg)
        return svg_content
