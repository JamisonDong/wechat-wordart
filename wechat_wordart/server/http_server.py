"""
轻量 HTTP 服务（基于 Python 标准库 http.server，零额外依赖）。

接口设计（供树莓派墨水屏定时拉取）：

  GET  /wordlist.json    → 返回词表 JSON
  GET  /wordart.svg      → 返回 SVG 词画
  GET  /status           → 返回服务状态 JSON
  POST /refresh          → 触发重新生成（需配合 pipeline 使用）
  GET  /                 → 简单 HTML 预览页

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
from urllib.parse import urlparse


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
    .links {{ margin-top: 1rem; display: flex; gap: 1rem; }}
    a {{ color: #3498db; text-decoration: none; font-size: 0.9rem; }}
    a:hover {{ text-decoration: underline; }}
    .ts {{ color: #999; font-size: 0.8rem; margin-top: 0.5rem; }}
  </style>
</head>
<body>
  <h1>📖 WeChat WordArt</h1>
  <img src="/wordart.svg" alt="词画" id="svg">
  <div class="links">
    <a href="/wordlist.json" target="_blank">📄 wordlist.json</a>
    <a href="/wordart.svg" target="_blank">🖼 wordart.svg</a>
    <a href="/status" target="_blank">📊 status</a>
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

        elif route == "/status":
            wl = self.output_dir / "wordlist.json"
            svg = self.output_dir / "wordart.svg"
            status = {
                "ok": True,
                "wordlist_exists": wl.exists(),
                "wordlist_size": wl.stat().st_size if wl.exists() else 0,
                "svg_exists": svg.exists(),
                "svg_size": svg.stat().st_size if svg.exists() else 0,
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
