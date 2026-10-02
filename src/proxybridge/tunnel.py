"""TCP 转发器（纯标准库，长驻）。安全红线：默认只允许绑定回环地址。

契约：
  - `bind_host` 非回环 → 拒绝启动（`config.validate` 同口径；这是无鉴权通道，不得暴露局域网）
  - 每条连接记一行审计：ts / #id / src / dst / bytes / duration / 状态
  - SIGTERM/SIGINT → 停止 accept，等在途连接 ≤5s，退出码 0；SIGHUP → 重载配置
"""
from __future__ import annotations

import errno
import os
import signal
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, logs, paths
from .logs import ensure_dir

GRACE_S = 5.0
BUFSIZE = 64 * 1024

_state_lock = threading.Lock()
_stop = threading.Event()
_reload = threading.Event()
_counters: dict = {"accepted": 0, "active": 0, "bytes": 0, "errors": 0}
logger = logs.RotatingWriter(paths.logs_dir() / "forward.log", 4 * 1024 * 1024, 5)


def is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


def forwarder_pids() -> list[int]:
    """正在跑的转发器进程（读 /proc/<pid>/cmdline）。

    **不靠 pgrep -f**：它是正则，会把自己这条命令行也算进去（踩过，杀过自己的 shell）。
    """
    pids: list[int] = []
    me = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        args = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        if not args:
            continue
        if any(Path(a).name == "proxy-forward" for a in args):      # v1
            pids.append(pid)
            continue
        mod = args[2] if len(args) > 2 and args[1] == "-m" else (args[1] if len(args) > 1 else "")
        if Path(args[0]).name.startswith("python") and Path(mod).name in {"proxy", "proxybridge"} \
                and "forward" in args[2:4]:
            pids.append(pid)
    return pids


class TunnelRefused(Exception):
    """启动前的安全/配置拒绝。"""


@dataclass
class Conn:
    cid: int
    src: tuple
    started: float
    bytes_up: int = 0
    bytes_down: int = 0
    status: str = "open"

    @property
    def total(self) -> int:
        return self.bytes_up + self.bytes_down


def _pump(src: socket.socket, dst: socket.socket, counter: str, conn: Conn) -> None:
    try:
        while True:
            data = src.recv(BUFSIZE)
            if not data:
                break
            dst.sendall(data)
            setattr(conn, counter, getattr(conn, counter) + len(data))
            with _state_lock:
                _counters["bytes"] += len(data)
    except OSError:
        conn.status = "error"
        with _state_lock:
            _counters["errors"] += 1
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _handle(client: socket.socket, addr: tuple, upstream: tuple, cid: int) -> None:
    conn = Conn(cid=cid, src=addr, started=time.time())
    try:
        up = socket.create_connection(upstream, timeout=10)
    except OSError as exc:
        conn.status = f"upstream_unreachable:{exc.errno}"
        with _state_lock:
            _counters["errors"] += 1
        logger.write(f"CONN #{cid} {addr[0]}:{addr[1]} -> {upstream[0]}:{upstream[1]} "
                     f"FAILED {conn.status}\n")
        # 优雅告知对端（shutdown 发 FIN，直接 close 会发 RST，客户端看到 ConnectionReset）
        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        client.close()
        return
    with _state_lock:
        _counters["active"] += 1
    t1 = threading.Thread(target=_pump, args=(client, up, "bytes_up", conn), daemon=True)
    t2 = threading.Thread(target=_pump, args=(up, client, "bytes_down", conn), daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()
    with _state_lock:
        _counters["active"] -= 1
    for s in (client, up):
        try:
            s.close()
        except OSError:
            pass
    logger.write(f"CONN #{cid} {addr[0]}:{addr[1]} -> {upstream[0]}:{upstream[1]} "
                 f"{conn.total}B {time.time() - conn.started:.2f}s {conn.status}\n")


def _reload_handlers() -> bool:
    """装信号处理器。**只有主线程能装** —— 非主线程调用时静默跳过（返回 False）。

    踩过的坑：在测试线程里跑 `run()` 会抛 `ValueError: signal only works in main thread`，
    整个转发器线程直接死掉（表现为客户端连接超时）。嵌入调用同理。
    """
    def _sigterm(signum, frame):                        # noqa: ARG001
        _stop.set()
    def _sighup(signum, frame):                          # noqa: ARG001
        _reload.set()
    try:
        signal.signal(signal.SIGTERM, _sigterm)
        signal.signal(signal.SIGINT, _sigterm)
        signal.signal(signal.SIGHUP, _sighup)
        return True
    except ValueError:
        return False


def run(bind: str | None = None, upstream: str | None = None) -> int:
    """阻塞运行直到 SIGTERM/SIGINT。返回进程退出码。"""
    cfg = config.load()
    bind = bind or f"{cfg['bind_host']}:{cfg['bind_port']}"
    upstream = upstream or str(cfg["upstream"])
    host, _, port = bind.rpartition(":")
    if not is_loopback(host):
        raise TunnelRefused(
            f"拒绝绑定非回环地址 {host}：转发器是**无鉴权**通道，绑到局域网等于把宿主网络暴露出去。"
            "如确需，请改 config.toml 的 bind_host 并自担风险")
    ensure_dir(paths.logs_dir())
    up_host, _, up_port = upstream.rpartition(":")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, int(port)))
    srv.listen(128)
    srv.settimeout(0.5)
    signals_installed = _reload_handlers()
    logger.write(f"SERVICE start bind={host}:{port} upstream={upstream} pid={os.getpid()} "
                 f"signals={'on' if signals_installed else 'off(非主线程)'}\n")

    cid = 0
    threads: list[threading.Thread] = []
    try:
        while not _stop.is_set():
            if _reload.is_set():
                _reload.clear()
                try:
                    cfg = config.load()
                    upstream = str(cfg["upstream"])
                    up_host, _, up_port = upstream.rpartition(":")
                    logger.write(f"SERVICE reload upstream={upstream}\n")
                except config.ConfigError as exc:
                    logger.write(f"SERVICE reload FAILED {exc}\n")
            try:
                client, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                if exc.errno in (errno.EBADF, errno.EINVAL):
                    break
                continue
            cid += 1
            with _state_lock:
                _counters["accepted"] += 1
            t = threading.Thread(target=_handle, args=(client, addr, (up_host, int(up_port)), cid),
                                 daemon=True)
            t.start()
            threads.append(t)
    finally:
        srv.close()
        deadline = time.time() + GRACE_S
        for t in threads:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            t.join(remaining)
        logger.write(f"SERVICE stop pid={os.getpid()} accepted={_counters['accepted']} "
                     f"bytes={_counters['bytes']} errors={_counters['errors']}\n")
    return 0


def status() -> dict:
    """只读状态：端口是否在听 + 计数器（进程内有效）。"""
    cfg = config.load()
    host, port = str(cfg["bind_host"]), int(cfg["bind_port"])
    listening = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            listening = s.connect_ex((host, port)) == 0
    except OSError:
        listening = False
    return {"bind": f"{host}:{port}", "upstream": str(cfg["upstream"]),
            "listening": listening, "counters": dict(_counters)}
