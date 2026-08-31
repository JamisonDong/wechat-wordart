"""
轻量 HTTP 服务（基于 Python 标准库 http.server，零额外依赖）。

接口设计（供树莓派/ESP32墨水屏定时拉取）：

  GET  /wordlist.json    → 返回词表 JSON
  GET  /wordart.svg      → 返回 SVG 词画（彩色，浏览器预览）
  GET  /eink.bmp         → 返回 1-bit BMP（ESP32 墨水屏直刷，推荐）
  GET  /eink.png         → 返回 1-bit PNG（浏览器预览墨水屏效果）
  GET  /status           → 返回服务状态 JSON
  POST /refresh          → 触发重新生成（需配合 pipeline 使用）
  GET  /                 → 简单 HTML 预览页

ESP32 拉取示例：
  curl http://192.168.1.x:8765/eink.bmp -o /tmp/eink.bmp
  # 或指定分辨率（动态渲染，无需预生成）：
  curl "http://192.168.1.x:8765/eink.bmp?w=800&h=480" -o eink.bmp
  curl "http://192.168.1.x:8765/eink.png?w=400&h=300" -o eink.png

用法：
  python -m wechat_wordart.server --port 8765 --output-dir output/

在树莓派侧用 cron + curl 拉取：
  0 6 * * * curl -s http://192.168.1.x:8765/wordart.svg -o /tmp/wordart.svg
"""

import json
import os
import threading
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse, parse_qs


_PREVIEW_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WeChat WordArt</title>
  <style>
    body {{ margin: 0; background: #f0f0f0; display: flex;
            flex-direction: column; align-items: center; padding: 2rem; font-family: sans-serif; }}
    h1 {{ color: #333; font-size: 1.2rem; margin-bottom: 1rem; }}
    img {{ max-width: 100%; box-shadow: 0 2px 12px rgba(0,0,0,.15); background: #fff; }}
    .links {{ margin-top: 1rem; display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; }}
    a {{ color: #3498db; text-decoration: none; font-size: 0.9rem; }}
    a:hover {{ text-decoration: underline; }}
    .ts {{ color: #999; font-size: 0.8rem; margin-top: 0.5rem; }}
    .note {{ color: #666; font-size: 0.85rem; margin-top: 1rem; background: #fff; padding: 0.8rem 1rem; border-radius: 6px; max-width: 600px; }}
    code {{ background: #eee; padding: 0.15rem 0.35rem; border-radius: 3px; font-size: 0.85em; }}
  </style>
</head>
<body>
  <h1>📖 WeChat WordArt</h1>
  <img src="/wordart.svg" alt="词画 SVG" id="svg">
  <div style="margin-top:1rem; font-size:0.9rem; color:#555;">SVG 彩色预览（浏览器）</div>
  <img src="/eink.png" alt="墨水屏预览" id="eink" style="margin-top:1rem; image-rendering: pixelated;">
  <div style="margin-top:0.3rem; font-size:0.9rem; color:#555;">E-ink 1-bit 预览（墨水屏实际效果）</div>
  <div class="links">
    <a href="/wordlist.json" target="_blank">📄 wordlist.json</a>
    <a href="/wordart.svg" target="_blank">🖼 wordart.svg</a>
    <a href="/eink.bmp" target="_blank">🖨 eink.bmp (ESP32)</a>
    <a href="/eink.png" target="_blank">🔳 eink.png</a>
    <a href="/status" target="_blank">📊 status</a>
  </div>
  <div class="note">
    ESP32 拉取：<code>curl http://&lt;IP&gt;:8765/eink.bmp -o eink.bmp</code><br>
    自定义分辨率：<code>/eink.bmp?w=800&h=480</code> 或 <code>/eink.png?w=400&h=300</code>
  </div>
  <div class="ts" id="ts"></div>
  <script>
    document.getElementById('ts').textContent = '生成时间：' + new Date().toLocaleString('zh-CN');
  </script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    """请求处理器（在实例化时注入 output_dir 和 refresh_callback）。"""

    output_dir: Path = Path("output")
    refresh_callback: Optional[Callable] = None

    def log_message(self, fmt, *args):
        # 替换为简洁日志
        print(f"[server] {self.address_string()} - {fmt % args}")

    def _send(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str):
        if not path.exists():
            self._send(404, "application/json",
                       json.dumps({"error": f"{path.name} not found"}).encode())
            return
        self._send(200, content_type, path.read_bytes())

    def _serve_eink(self, fmt: str):
        """服务墨水屏位图：优先返回已生成文件，否则按 wordlist 动态渲染。"""
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        # 解析自定义分辨率参数
        def _int_param(name, default):
            try:
                return int(qs.get(name, [default])[0])
            except Exception:
                return default

        w = _int_param("w", 0)
        h = _int_param("h", 0)

        # 1) 若未指定 w/h 且存在预生成文件，直接返回文件（最快，ESP32 常用）
        if w == 0 and h == 0:
            fname = "eink.bmp" if fmt == "bmp" else "eink.png"
            fpath = self.output_dir / fname
            if fpath.exists():
                ctype = "image/bmp" if fmt == "bmp" else "image/png"
                self._send_file(fpath, ctype)
                return

        # 2) 动态渲染：需要 wordlist.json
        wl_path = self.output_dir / "wordlist.json"
        if not wl_path.exists():
            self._send(404, "application/json",
                       json.dumps({"error": "wordlist.json not found, please run pipeline first"}).encode())
            return

        try:
            with open(wl_path, encoding="utf-8") as f:
                wordlist = json.load(f)
        except Exception as e:
            self._send(500, "application/json",
                       json.dumps({"error": f"failed to load wordlist: {e}"}).encode())
            return

        # 尝试导入 EinkRenderer
        try:
            from wechat_wordart.renderer.eink_renderer import EinkRenderer
        except ImportError as e:
            self._send(500, "application/json",
                       json.dumps({"error": f"Pillow not installed: {e}"}).encode())
            return

        # 构造渲染配置：优先使用 query 参数，否则用默认
        cfg = {}
        if w > 0:
            cfg["width"] = max(100, min(w, 2000))
        if h > 0:
            cfg["height"] = max(100, min(h, 2000))
        # 支持 ?rotate=1
        if qs.get("rotate", ["0"])[0] in ("1", "true", "yes"):
            cfg["rotate"] = True

        try:
            renderer = EinkRenderer(config=cfg if cfg else None)
            data = renderer.render_to_bytes(wordlist, fmt=fmt)
            ctype = "image/bmp" if fmt == "bmp" else "image/png"
            # BMP 对 ESP32 友好，加 Content-Disposition 便于下载调试
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            if fmt == "bmp":
                self.send_header("Content-Disposition", 'inline; filename="eink.bmp"')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send(500, "application/json",
                       json.dumps({"error": f"eink render failed: {e}"}).encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/" :
            body = _PREVIEW_HTML.encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)

        elif route == "/wordlist.json":
            self._send_file(self.output_dir / "wordlist.json", "application/json; charset=utf-8")

        elif route == "/wordart.svg":
            self._send_file(self.output_dir / "wordart.svg", "image/svg+xml; charset=utf-8")

        elif route in ("/eink.bmp", "/eink"):
            self._serve_eink("bmp")

        elif route == "/eink.png":
            self._serve_eink("png")

        elif route == "/status":
            wl = self.output_dir / "wordlist.json"
            svg = self.output_dir / "wordart.svg"
            bmp = self.output_dir / "eink.bmp"
            png = self.output_dir / "eink.png"
            status = {
                "ok": True,
                "wordlist_exists": wl.exists(),
                "wordlist_size": wl.stat().st_size if wl.exists() else 0,
                "svg_exists": svg.exists(),
                "svg_size": svg.stat().st_size if svg.exists() else 0,
                "eink_bmp_exists": bmp.exists(),
                "eink_bmp_size": bmp.stat().st_size if bmp.exists() else 0,
                "eink_png_exists": png.exists(),
                "eink_png_size": png.stat().st_size if png.exists() else 0,
                "server_time": datetime.now(timezone.utc).isoformat(),
            }
            self._send(200, "application/json", json.dumps(status, ensure_ascii=False).encode())

        else:
            self._send(404, "application/json", b'{"error":"not found"}')

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/")

        if route == "/refresh":
            if self.refresh_callback:
                threading.Thread(target=self.refresh_callback, daemon=True).start()
                self._send(202, "application/json", b'{"status":"refresh_triggered"}')
            else:
                self._send(501, "application/json", b'{"error":"no refresh callback configured"}')
        else:
            self._send(404, "application/json", b'{"error":"not found"}')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()


class WordArtServer:
    """词画 HTTP 服务器。"""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        output_dir: str = "output",
        refresh_callback: Optional[Callable] = None,
    ):
        self.host = host
        self.port = port
        self.output_dir = Path(output_dir)
        self.refresh_callback = refresh_callback

        # 将配置注入 Handler 类（简单做法，无需每次实例化传参）
        _Handler.output_dir = self.output_dir
        _Handler.refresh_callback = refresh_callback

        self._server = HTTPServer((host, port), _Handler)

    def serve_forever(self):
        print(f"[server] 服务启动：http://{self.host}:{self.port}")
        print(f"[server] 树莓派拉取地址示例：")
        print(f"         curl http://<IP>:{self.port}/wordart.svg -o /tmp/wordart.svg")
        print(f"         curl http://<IP>:{self.port}/wordlist.json")
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            print("\n[server] 服务已停止")

    def start_background(self) -> threading.Thread:
        """在后台线程启动服务器，返回线程对象。"""
        t = threading.Thread(target=self.serve_forever, daemon=True)
        t.start()
        return t


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="WeChat WordArt HTTP Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    server = WordArtServer(host=args.host, port=args.port, output_dir=args.output_dir)
    server.serve_forever()


if __name__ == "__main__":
    main()
