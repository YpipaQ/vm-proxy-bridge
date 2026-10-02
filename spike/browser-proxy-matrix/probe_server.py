#!/usr/bin/env python3
"""探针服务器（矩阵实验的量具）。

两个角色，互不干扰：
  --proxy-port   假 HTTP 代理。浏览器若把请求交给它，就说明"读到代理了"。
                 代理收到 CONNECT 即记一笔（不需要真的建隧道）；收到绝对形式
                 GET http://host/path 则回一小段带 marker 的 HTML。
  --origin-port  普通 HTTP 源站（直连角色），提供 /proxy.pac 和 /m。
                 PAC 的抓取本身是直连的，所以必须由"源站"角色提供。

判定原理：目标主机用 .invalid 顶级域（永远无法解析）。因此
  * 直连 → DNS 失败 → 页面是错误页，永远拿不到 marker；
  * 走代理 → 代理不需要解析也能回答 → 拿到 marker。
于是"探针日志里有这一笔"就等价于"浏览器确实把请求交给了代理"，无假阳性。

事件行格式：`<iso时间> <PROXY|ORIGIN> <METHOD> <TARGET> from=<peer>`
"""
from __future__ import annotations

import argparse
import http.server
import os
import socket
import socketserver
import sys
import threading
import time
from datetime import datetime

MARKER = "PROXYBRIDGE_PROXIED_OK"

BODY = (
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    f"<title>{MARKER}</title></head>"
    f"<body><h1 id=\"marker\">{MARKER}</h1></body></html>"
).encode("utf-8")

PAC_TEMPLATE = """function FindProxyForURL(url, host) {
  return "PROXY 127.0.0.1:{port}; DIRECT";
}
"""


def now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class Log:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._fh = open(path, "a", buffering=1, encoding="utf-8")

    def write(self, kind: str, method: str, target: str, peer: str) -> None:
        with self._lock:
            self._fh.write(f"{now()} {kind} {method} {target} from={peer}\n")
            self._fh.flush()

    def raw(self, text: str) -> None:
        with self._lock:
            self._fh.write(f"{now()} {text}\n")
            self._fh.flush()


def _peer_of(handler: socketserver.BaseRequestHandler) -> str:
    try:
        return f"{handler.client_address[0]}:{handler.client_address[1]}"
    except Exception:
        return "?"


class ProxyHandler(socketserver.StreamRequestHandler):
    """假 HTTP 代理：只记录，不真的转发。"""

    timeout = 20

    def handle(self) -> None:  # noqa: C901
        log: Log = self.server.log  # type: ignore[attr-defined]
        marker = self.server.marker  # type: ignore[attr-defined]
        try:
            line = self.rfile.readline(65536)
        except (socket.timeout, OSError):
            return
        if not line:
            return
        try:
            first = line.decode("latin-1").rstrip("\r\n")
        except Exception:
            return
        parts = first.split()
        method = parts[0] if parts else "?"
        target = parts[1] if len(parts) > 1 else "?"
        # 排干请求头，避免客户端写阻塞
        try:
            while True:
                h = self.rfile.readline(65536)
                if not h or h in (b"\r\n", b"\n"):
                    break
        except (socket.timeout, OSError):
            pass
        log.write("PROXY", method, target, _peer_of(self))
        try:
            if method.upper() == "CONNECT":
                # 只需证明"客户端来了"；给 502 让它立刻收摊，不建隧道。
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n"
                                 b"Content-Length: 0\r\nConnection: close\r\n\r\n")
            else:
                if target.endswith("/proxy.pac") or "/proxy.pac" in target:
                    body = PAC_TEMPLATE.format(port=self.server.proxy_port).encode()  # type: ignore[attr-defined]
                    ctype = "application/x-ns-proxy-autoconfig"
                else:
                    body = marker
                    ctype = "text/html; charset=utf-8"
                head = (
                    f"HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\n"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                ).encode()
                self.wfile.write(head + body)
        except (socket.timeout, OSError, BrokenPipeError):
            pass


class OriginHandler(http.server.BaseHTTPRequestHandler):
    """普通源站（直连角色）：/proxy.pac 与 /m。"""

    server_version = "probe-origin/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        pass  # 只走我们自己的日志

    def _serve(self) -> None:
        log: Log = self.server.log  # type: ignore[attr-defined]
        path = self.path.split("?")[0]
        log.write("ORIGIN", self.command, self.path, f"{self.client_address[0]}:{self.client_address[1]}")
        if path == "/proxy.pac":
            body = PAC_TEMPLATE.format(port=self.server.proxy_port).encode()  # type: ignore[attr-defined]
            ctype = "application/x-ns-proxy-autoconfig"
        elif path == "/m":
            body = self.server.marker  # type: ignore[attr-defined]
            ctype = "text/html; charset=utf-8"
        else:
            body = b"probe-origin\n"
            ctype = "text/plain"
        if self.command == "HEAD":
            body = b""
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, OSError):
            pass

    do_GET = _serve
    do_POST = _serve
    do_HEAD = _serve


class ThreadedTCP(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ThreadedHTTP(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="代理矩阵实验量具：假代理 + 源站")
    ap.add_argument("--proxy-port", type=int, default=17897)
    ap.add_argument("--origin-port", type=int, default=17898)
    ap.add_argument("--log", required=True)
    ap.add_argument("--ready-file", help="两个监听器就绪后写这个文件（供 run 脚本等待）")
    args = ap.parse_args(argv)

    os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
    log = Log(args.log)
    log.raw(f"PROBE start proxy_port={args.proxy_port} origin_port={args.origin_port} pid={os.getpid()}")

    proxy = ThreadedTCP(("127.0.0.1", args.proxy_port), ProxyHandler)
    proxy.log = log          # type: ignore[attr-defined]
    proxy.marker = BODY      # type: ignore[attr-defined]
    proxy.proxy_port = args.proxy_port  # type: ignore[attr-defined]

    origin = ThreadedHTTP(("127.0.0.1", args.origin_port), OriginHandler)
    origin.log = log         # type: ignore[attr-defined]
    origin.marker = BODY     # type: ignore[attr-defined]
    origin.proxy_port = args.proxy_port  # type: ignore[attr-defined]

    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    threading.Thread(target=origin.serve_forever, daemon=True).start()

    if args.ready_file:
        with open(args.ready_file, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()}\n")
    print(f"probe ready: proxy=127.0.0.1:{args.proxy_port} origin=127.0.0.1:{args.origin_port} "
          f"marker={MARKER} log={args.log}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        log.raw("PROBE stop")
        proxy.shutdown()
        origin.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
