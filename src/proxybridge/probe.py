"""探测：TCP 端口、上游可达性、缓存（TTL）。不做任何模式切换。"""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from . import paths
from .logs import ensure_dir


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """探测函数契约：**永不抛异常**，任何失败都返回 False。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, int(port))) == 0
    except (OSError, ValueError, TypeError):
        return False


def upstream_reachable(upstream: str, timeout: float = 2.0) -> bool:
    host, _, port = upstream.rpartition(":")
    if not host or not port.isdigit():
        return False
    return port_open(host, int(port), timeout)


def read_cache(ttl: int = 60, path: Path | None = None) -> dict | None:
    p = path or (paths.cache_root() / "probe.json")
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - float(data.get("ts", 0)) > ttl:
        return None
    return data


def write_cache(payload: dict, path: Path | None = None) -> None:
    p = path or (paths.cache_root() / "probe.json")
    ensure_dir(p.parent)
    data = dict(payload, ts=time.time())
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    p.parent.chmod(0o700)
    p.write_text(tmp.read_text("utf-8"), "utf-8")
    tmp.unlink(missing_ok=True)
