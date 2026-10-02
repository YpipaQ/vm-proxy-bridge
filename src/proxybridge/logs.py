"""结构化日志 + 内部轮转（不依赖 logrotate）。

契约：
  - 写入永不抛异常（日志失败不得让业务命令失败）
  - 打开/替换后权限恒为 0600
  - 轮转：size >= max_bytes 时 os.replace(当前, .1)，最多 backups 份
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import paths

DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUPS = 5


def ensure_dir(p: Path, mode: int = 0o700) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, mode)
    except OSError:
        pass
    return p


class RotatingWriter:
    """按尺寸轮转的追加写入器。"""

    def __init__(self, path: Path, max_bytes: int = DEFAULT_MAX_BYTES,
                 backups: int = DEFAULT_BACKUPS, mode: int = 0o600) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self.mode = mode

    def rotate(self) -> None:
        if self.backups <= 0 or not self.path.exists():
            return
        oldest = self.path.with_suffix(self.path.suffix + f".{self.backups}")
        if oldest.exists():
            oldest.unlink()
        for i in range(self.backups - 1, 0, -1):
            src = self.path.with_suffix(self.path.suffix + f".{i}")
            if src.exists():
                os.replace(src, self.path.with_suffix(self.path.suffix + f".{i + 1}"))
        os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))

    def write(self, text: str) -> None:
        try:
            ensure_dir(self.path.parent)
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                self.rotate()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, self.mode)
            try:
                os.write(fd, text.encode("utf-8", "replace"))
            finally:
                os.close(fd)
            os.chmod(self.path, self.mode)
        except OSError:
            pass  # 日志永不致命


class EventLog:
    """app.jsonl（结构化）+ app.log（人读）双写。"""

    def __init__(self, name: str = "app", max_bytes: int = DEFAULT_MAX_BYTES,
                 backups: int = DEFAULT_BACKUPS) -> None:
        self.jsonl = RotatingWriter(paths.logs_dir() / f"{name}.jsonl", max_bytes, backups)
        self.text = RotatingWriter(paths.logs_dir() / f"{name}.log", max_bytes, backups)

    def event(self, verb: str, level: str = "info", result: str = "ok",
              duration_ms: int = 0, tx_id: str = "", **extra) -> None:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "level": level, "verb": verb, "pid": os.getpid(), "uid": os.getuid(),
            "argv": [], "result": result, "duration_ms": duration_ms, "tx_id": tx_id,
        }
        rec.update(extra)
        self.jsonl.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.text.write(f"[{rec['ts']}] {level:<5} {verb} -> {result} ({duration_ms}ms)\n")
