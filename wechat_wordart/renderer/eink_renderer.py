"""
E-ink 位图渲染器 —— 专为 ESP32 + 墨水屏设计。

与 SVGRenderer 的区别：
  - 输出 1-bit BMP/PNG (白底黑字)，无灰度、无彩色，直接适合 GxEPD2 / Waveshare 驱动
  - 使用 Pillow 精确 textbbox 做碰撞检测，像素级对齐墨水屏分辨率
  - 禁用抗锯齿渐变（1-bit 模式），保证墨水屏锐利
  - 内置中文字体自动探测（STHeiti / Hiragino / Noto），找不到则回退

输出：
  - eink.bmp  1-bit BMP，ESP32 直接下载刷屏（推荐）
  - eink.png  1-bit PNG，浏览器预览 / 调试
  - eink.raw  可选纯字节流（每8像素1字节，Waveshare 原始格式，可按需扩展）

依赖：Pillow (pip install Pillow)

用法：
  from wechat_wordart.renderer.eink_renderer import EinkRenderer
  r = EinkRenderer({"width": 800, "height": 480, "max_font_size": 72})
  r.render(wordlist, "output/eink.bmp")
"""

import math
import random
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# 常见中文字体候选（按优先级），macOS / Linux / 树莓派 / NAS 常见路径
_FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]


def _load_font(size: int):
    """按候选列表探测中文字体，失败回退到 PIL 默认字体（无中文）。"""
    size = max(8, int(size))
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                try:
                    return ImageFont.truetype(path, size, index=0)
                except Exception:
                    continue
    # 最后兜底：Pillow 内置位图字体（英文正常，中文会显示方块，但至少不崩）
    try:
        return ImageFont.load_default()
    except Exception:
        return None


class _Box:
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

    def in_bounds(self, width: float, height: float, margin: float = 6.0) -> bool:
        return (
            self.left >= margin
            and self.right <= width - margin
            and self.top >= margin
            and self.bottom <= height - margin
        )


class EinkRenderer:
    """将词表渲染为 1-bit 墨水屏位图。"""

    def __init__(self, config: Optional[dict] = None):
        if not _PIL_AVAILABLE:
            raise ImportError("EinkRenderer 需要 Pillow，请执行：pip install Pillow")

        cfg = config or {}
        self.width: int = int(cfg.get("width", 800))
        self.height: int = int(cfg.get("height", 480))
        self.max_font_size: float = float(cfg.get("max_font_size", 72))
        self.min_font_size: float = float(cfg.get("min_font_size", 14))
        # 墨水屏只有黑白，colors 忽略，固定黑字白底；保留字段兼容旧配置
        self.background: int = 1  # 1=white in '1' mode
        self.foreground: int = 0  # 0=black
        self.margin: float = float(cfg.get("margin", 8))
        self.padding: float = float(cfg.get("padding", 4))  # 词间距
        self.rotate: bool = bool(cfg.get("rotate", False))  # 墨水屏默认不旋转，更易读
        self.max_words: Optional[int] = cfg.get("max_words")  # 可限制词数，省内存
        self._seed: int = int(cfg.get("seed", 42))

        # 字体缓存：size -> font object
        self._font_cache: dict = {}

    def _get_font(self, size: float):
        key = int(size)
        if key not in self._font_cache:
            self._font_cache[key] = _load_font(key)
        return self._font_cache[key]

    def _font_size(self, weight: float) -> float:
        # 平方根缩放，视觉更均匀，与 SVG 保持一致
        return self.min_font_size + (self.max_font_size - self.min_font_size) * math.sqrt(weight)

    def _spiral_offsets(self, step_px: float = 6.0, loop_spacing: float = 8.0):
        max_r = math.hypot(self.width, self.height) / 2.0 + 10.0
        b = loop_spacing / (2.0 * math.pi)
        yield 0.0, 0.0
        theta = step_px / max(b, 1e-6)
        while True:
            r = b * theta
            if r > max_r:
                return
            yield r * math.cos(theta), r * math.sin(theta)
            theta += step_px / max(r, step_px)

    def _measure(self, word: str, font) -> Tuple[float, float]:
        """用 Pillow 精确测量文字包围盒，失败则回退到估算。"""
        if font is None:
            # 粗略估算：中文按 font size，ascii 0.6
            w = sum(1.0 if 0x4E00 <= ord(c) <= 0x9FFF else 0.6 for c in word) * 12
            return w, 16
        try:
            # 需要临时 Draw 来测 bbox
            dummy = Image.new("1", (10, 10), 1)
            draw = ImageDraw.Draw(dummy)
            bbox = draw.textbbox((0, 0), word, font=font)
            # bbox: (left, top, right, bottom)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            # 加一点行高余量，防止截断
            h = max(h, int(font.size * 1.15)) if hasattr(font, "size") else h
            return float(max(w, 1)), float(max(h, 1))
        except Exception:
            # 回退估算
            sz = getattr(font, "size", 16)
            w = sum(1.0 if 0x4E00 <= ord(c) <= 0x9FFF else 0.6 for c in word) * sz
            return w, sz * 1.2

    def render(self, wordlist: List[dict], output_path: str) -> str:
        """
        渲染词表为 1-bit 位图。

        Args:
            wordlist:    词表，每项含 word / weight
            output_path: 输出路径，后缀决定格式：.bmp / .png

        Returns:
            输出路径
        """
        if not wordlist:
            raise ValueError("wordlist 为空，无法渲染")

        rng = random.Random(self._seed)
        words = sorted(wordlist, key=lambda x: x.get("weight", 0), reverse=True)
        if self.max_words:
            words = words[: self.max_words]

        # 创建 1-bit 画布（1=white, 0=black）
        image = Image.new("1", (self.width, self.height), 1)
        draw = ImageDraw.Draw(image)

        # 可选：画细边框，墨水屏相框感
        border = 1
        if border:
            draw.rectangle([0, 0, self.width - 1, self.height - 1], outline=0, width=1)

        cx, cy = self.width / 2.0, self.height / 2.0
        placed: List[_Box] = []
        placed_info: List[Tuple[str, float, float, float, object]] = []  # word, x, y, fs, font
        skipped = 0

        for idx, item in enumerate(words):
            word = str(item.get("word", "")).strip()
            if not word:
                continue
            weight = float(item.get("weight", 0.5))
            fs = self._font_size(weight)
            font = self._get_font(fs)

            # 旋转角度：墨水屏默认关闭，开启时仅轻微旋转
            angle = 0.0
            if self.rotate:
                if weight > 0.5:
                    angle = rng.choice([0, 0, -15, 15])
                elif weight > 0.3:
                    angle = rng.choice([0, 0, -10, 10])

            tw, th = self._measure(word, font)

            # 旋转后包围盒扩展
            if angle != 0:
                rad = math.radians(abs(angle))
                rw = tw * math.cos(rad) + th * math.sin(rad)
                rh = tw * math.sin(rad) + th * math.cos(rad)
            else:
                rw, rh = tw, th

            placed_ok = False
            for dx, dy in self._spiral_offsets():
                x, y = cx + dx, cy + dy
                box = _Box(x, y, rw, rh)
                if not box.in_bounds(self.width, self.height, margin=self.margin):
                    continue
                if any(box.overlaps(p, padding=self.padding) for p in placed):
                    continue

                placed.append(box)
                placed_info.append((word, x, y, fs, font, angle))
                placed_ok = True
                break

            if not placed_ok:
                skipped += 1

        # 真正绘制文字（在确定位置后）
        for word, x, y, fs, font, angle in placed_info:
            if font is None:
                continue
            # textbbox 用于居中：计算偏移
            try:
                bbox = draw.textbbox((0, 0), word, font=font)
                bw = bbox[2] - bbox[0]
                bh = bbox[3] - bbox[1]
                # 调整基线：Pillow text 锚点默认左上，需要居中处理
                # 使用 anchor='mm'（middle-middle）最简洁（Pillow 8+ 支持）
                try:
                    # 如果有 angle，需要创建临时图再旋转（1-bit 旋转会锯齿但可接受）
                    if angle != 0:
                        # 创建单字临时图
                        tmp_w = int(bw + 8)
                        tmp_h = int(bh + 8)
                        tmp = Image.new("1", (tmp_w, tmp_h), 1)
                        tmp_draw = ImageDraw.Draw(tmp)
                        tmp_draw.text((tmp_w / 2, tmp_h / 2), word, font=font, fill=0, anchor="mm")
                        tmp = tmp.rotate(-angle, expand=True, fillcolor=1)
                        # 粘贴到主图居中
                        px = int(x - tmp.width / 2)
                        py = int(y - tmp.height / 2)
                        image.paste(tmp, (px, py))
                    else:
                        draw.text((x, y), word, font=font, fill=0, anchor="mm")
                except TypeError:
                    # 旧 Pillow 无 anchor 参数，回退到手动偏移
                    draw.text((x - bw / 2 - bbox[0], y - bh / 2 - bbox[1]), word, font=font, fill=0)
            except Exception as e:
                # 单个词绘制失败不影响整体
                print(f"[eink] 绘制 '{word}' 失败：{e}")
                continue

        # 保存
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        suffix = out.suffix.lower()

        # 根据后缀保存，BMP 最适合 ESP32（无需解码），PNG 适合预览
        if suffix == ".bmp":
            # BMP 1-bit 保存（Pillow 会自动处理调色板）
            image.save(str(out), format="BMP")
        elif suffix in (".png", ""):
            if suffix == "":
                out = out.with_suffix(".png")
            image.save(str(out), format="PNG", optimize=True)
        else:
            # 其他格式一律按 PNG 保存
            image.save(str(out), format="PNG")

        # 同时生成另一格式便于调试（如果主输出是 bmp，再存一份 png 预览）
        preview_path = None
        if suffix == ".bmp":
            preview_path = str(out.with_suffix(".png"))
            try:
                image.save(preview_path, format="PNG", optimize=True)
            except Exception:
                pass

        msg = f"[eink] 位图已写入 {out} ({self.width}x{self.height} 1-bit)，成功放置 {len(placed_info)}/{len(words)} 个词"
        if skipped:
            msg += f"（{skipped} 个词因空间不足未放置，可增大画布或调小字号）"
        if preview_path:
            msg += f"，预览图：{preview_path}"
        print(msg)

        # 检查字体是否有效（中文是否会变方块）
        sample_font = self._get_font(self.max_font_size)
        if sample_font is None or "load_default" in str(type(sample_font)):
            print("[eink] ⚠ 警告：未找到中文字体，中文可能显示为方块/乱码。")
            print("    Mac: /System/Library/Fonts/STHeiti Light.ttc 应存在")
            print("    Linux/NAS: 请安装 wqy-microhei 或 noto-cjk：apt install fonts-wqy-microhei fonts-noto-cjk")

        return str(out)

    def render_to_bytes(self, wordlist: List[dict], fmt: str = "BMP") -> bytes:
        """渲染到内存字节（供 HTTP 接口直接返回，无需落盘）。"""
        import io

        if not wordlist:
            raise ValueError("wordlist 为空")

        # 复用 render 逻辑但不落盘：直接生成 image 并存到 BytesIO
        # 为避免重复代码，这里临时调用 render 到临时路径再读回，需重构时再抽公共方法
        # 简化：直接内联生成
        rng = random.Random(self._seed)
        words = sorted(wordlist, key=lambda x: x.get("weight", 0), reverse=True)
        if self.max_words:
            words = words[: self.max_words]

        image = Image.new("1", (self.width, self.height), 1)
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, self.width - 1, self.height - 1], outline=0, width=1)

        cx, cy = self.width / 2.0, self.height / 2.0
        placed: List[_Box] = []
        placed_info: List[Tuple] = []

        for item in words:
            word = str(item.get("word", "")).strip()
            if not word:
                continue
            weight = float(item.get("weight", 0.5))
            fs = self._font_size(weight)
            font = self._get_font(fs)
            angle = 0.0
            if self.rotate and weight > 0.5:
                angle = rng.choice([0, 0, -15, 15])
            tw, th = self._measure(word, font)
            if angle != 0:
                rad = math.radians(abs(angle))
                rw = tw * math.cos(rad) + th * math.sin(rad)
                rh = tw * math.sin(rad) + th * math.cos(rad)
            else:
                rw, rh = tw, th
            for dx, dy in self._spiral_offsets():
                x, y = cx + dx, cy + dy
                box = _Box(x, y, rw, rh)
                if not box.in_bounds(self.width, self.height, margin=self.margin):
                    continue
                if any(box.overlaps(p, padding=self.padding) for p in placed):
                    continue
                placed.append(box)
                placed_info.append((word, x, y, font, angle))
                break

        for word, x, y, font, angle in placed_info:
            if font is None:
                continue
            try:
                bbox = draw.textbbox((0, 0), word, font=font)
                bw = bbox[2] - bbox[0]
                bh = bbox[3] - bbox[1]
                try:
                    if angle != 0:
                        tmp_w = int(bw + 8)
                        tmp_h = int(bh + 8)
                        tmp = Image.new("1", (tmp_w, tmp_h), 1)
                        tmp_draw = ImageDraw.Draw(tmp)
                        tmp_draw.text((tmp_w / 2, tmp_h / 2), word, font=font, fill=0, anchor="mm")
                        tmp = tmp.rotate(-angle, expand=True, fillcolor=1)
                        px = int(x - tmp.width / 2)
                        py = int(y - tmp.height / 2)
                        image.paste(tmp, (px, py))
                    else:
                        draw.text((x, y), word, font=font, fill=0, anchor="mm")
                except TypeError:
                    draw.text((x - bw / 2 - bbox[0], y - bh / 2 - bbox[1]), word, font=font, fill=0)
            except Exception:
                continue

        buf = io.BytesIO()
        fmt_upper = fmt.upper()
        if fmt_upper == "BMP":
            image.save(buf, format="BMP")
        elif fmt_upper == "PNG":
            image.save(buf, format="PNG", optimize=True)
        else:
            image.save(buf, format="PNG")
        return buf.getvalue()
