#!/usr/bin/env python3.11
"""远程预览组合服务器（零 WebSocket / 生产模式）。

职责：
1. 静态托管前端构建产物 web/dist/（Vite build 产出，单页应用）。
2. 将 /api/* 以及 FastAPI 文档路由反向代理到本地后端 127.0.0.1:8000。
3. 对未知前端路由（/monitor、/stocks/:code 等）回退到 index.html，
   满足 BrowserRouter 的 SPA 路由需求。

绑定 0.0.0.0:<port>（port 由 argv[1] 指定，默认 8080），供 preview 技能
的 notify 反向代理到公网。

注意：本服务仅做 HTTP 反向代理与静态托管，不使用任何 WebSocket，
因此可安全通过 preview 代理对外暴露。
"""
from __future__ import annotations

import mimetypes
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "web", "dist")
BACKEND = "http://127.0.0.1:8000"
PROXY_TIMEOUT = 30

# 需要反向代理到后端的路径前缀 / 精确路径
PROXY_PREFIXES = ("/api",)
PROXY_EXACT = {"/docs", "/openapi.json", "/redoc"}

# 不应被 SPA 回退覆盖的代理路径都以 /api 开头，这里集中判断
def _is_proxy_path(path: str) -> bool:
    if path in PROXY_EXACT:
        return True
    return any(path.startswith(p) for p in PROXY_PREFIXES)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "quant-preview/1.0"

    # ---- 工具 ----
    def _read_body(self) -> bytes | None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return None
        return self.rfile.read(length)

    def _send(self, status: int, body: bytes, content_type: str = "application/octet-stream"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---- 反向代理 ----
    def _proxy(self, path: str):
        url = BACKEND + path  # path 含 query string
        hop_by_hop = {"host", "content-length", "connection", "transfer-encoding", "keep-alive"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in hop_by_hop}
        body = self._read_body() if self.command not in ("GET", "HEAD") else None
        try:
            resp = requests.request(
                self.command,
                url,
                headers=headers,
                data=body,
                timeout=PROXY_TIMEOUT,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            self._send(502, f"后端不可达: {exc}".encode("utf-8"), "text/plain; charset=utf-8")
            return

        self.send_response(resp.status_code)
        for k, v in resp.headers.items():
            if k.lower() in hop_by_hop:
                continue
            self.send_header(k, v)
        # 以实际内容长度覆盖，避免分块编码不匹配
        self.send_header("Content-Length", str(len(resp.content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.content)

    # ---- 静态托管（含 SPA 回退）----
    def _serve_static(self, path: str):
        rel = urllib.parse.urlparse(path).path.lstrip("/")
        if rel in ("", "/"):
            rel = "index.html"
        # 防目录穿越
        norm = os.path.normpath(os.path.join(DIST, rel))
        if not norm.startswith(DIST):
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return
        if os.path.isdir(norm):
            norm = os.path.join(norm, "index.html")
        if not os.path.isfile(norm):
            # SPA 回退：非资源请求一律交给 index.html 处理客户端路由
            if not rel.startswith("assets/"):
                norm = os.path.join(DIST, "index.html")
            else:
                self._send(404, b"Not Found", "text/plain; charset=utf-8")
                return
        try:
            with open(norm, "rb") as f:
                data = f.read()
        except OSError as exc:
            self._send(404, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(norm)[0] or "application/octet-stream"
        if ctype.startswith("text/") and "charset" not in ctype:
            ctype += "; charset=utf-8"
        self._send(200, data, ctype)

    # ---- 路由分发 ----
    def _dispatch(self):
        path = self.path.split("?", 1)[0]
        if _is_proxy_path(self.path):
            self._proxy(self.path)
        else:
            self._serve_static(path)

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def log_message(self, fmt, *args):  # 静默默认访问日志
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    if not os.path.isdir(DIST):
        sys.stderr.write(f"[preview] 未找到构建产物目录: {DIST}，请先执行 pnpm build\n")
        sys.exit(1)
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    sys.stderr.write(f"[preview] serving {DIST} + proxy /api -> {BACKEND} on 0.0.0.0:{port}\n")
    sys.stderr.flush()
    httpd.serve_forever()


if __name__ == "__main__":
    main()
