"""状态机 / 单写者锁 / 写前事务。

约定：
  - 所有"变更类"命令必须先 flock(state_root/lock) 再动盘
  - 写文件一律 tmp + os.replace(原子)，写前记 tx/<ts>-<id>.json
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
import uuid
from pathlib import Path

from . import paths
from .logs import ensure_dir

DEFAULT_STATE = {
    "schema": 1,
    "desired_on": False,
    "actual": "off",          # off | env | forward | degraded | orphan
}


@contextlib.contextmanager
def single_writer(timeout: float = 10.0):
    """flock 排他；拿不到锁则抛 TimeoutError（由 CLI 转成退出码 1）。"""
    lock = paths.lock_file()
    ensure_dir(lock.parent)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"另一个 proxy 进程正在写入：{lock}")
                time.sleep(0.05)
        yield fd
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_state() -> dict:
    f = paths.state_file()
    if not f.exists():
        return json.loads(json.dumps(DEFAULT_STATE))
    try:
        data = json.loads(f.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULT_STATE))
    merged = json.loads(json.dumps(DEFAULT_STATE))
    merged.update(data)
    return merged


def write_state(state: dict, tx_id: str = "") -> None:
    """原子替换 + 保留 3 份快照。调用方负责持锁。"""
    ensure_dir(paths.state_root())
    f = paths.state_file()
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")
    os.chmod(tmp, 0o600)
    if f.exists():
        os.replace(f, f.with_suffix(".json.prev1"))
    os.replace(tmp, f)


class Tx:
    """写前事务：intent → （调用方动作）→ commit。失败时由 proxy repair 依 tx 恢复。"""

    def __init__(self, verb: str) -> None:
        self.id = f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.verb = verb
        self.dir = paths.state_root() / "tx"
        self.path = self.dir / f"{self.id}.json"

    def begin(self, targets: list[str]) -> str:
        ensure_dir(self.dir)
        self.path.write_text(json.dumps({
            "id": self.id, "verb": self.verb, "state": "intent",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "targets": targets,
        }, ensure_ascii=False, indent=2) + "\n", "utf-8")
        os.chmod(self.path, 0o600)
        return self.id

    def commit(self) -> None:
        done = self.dir / "done"
        ensure_dir(done)
        try:
            self.path.write_text(json.dumps({
                "id": self.id, "verb": self.verb, "state": "commit",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }, ensure_ascii=False, indent=2) + "\n", "utf-8")
            os.replace(self.path, done / self.path.name)
        except OSError:
            pass
