"""备份 / 还原 / 保留策略。命名：<target>/<ts>.<sha8>，权限 0600。"""
from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path

from . import paths
from .logs import ensure_dir


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(target: Path, root: Path | None = None) -> Path | None:
    """备份单个文件；不存在则返回 None（不报错）。"""
    target = Path(target)
    if not target.exists():
        return None
    root = root or paths.backups_root()
    digest = sha256_file(target)[:8]
    dest_dir = ensure_dir(root / target.name, 0o700)
    dest = dest_dir / f"{time.strftime('%Y%m%dT%H%M%S')}.{digest}"
    shutil.copy2(target, dest)
    os.chmod(dest, 0o600)
    return dest


def restore(backup_path: Path, target: Path) -> None:
    """原子还原：先写同目录临时文件再 os.replace。"""
    target = Path(target)
    tmp = target.with_name(target.name + ".restore.tmp")
    shutil.copy2(backup_path, tmp)
    os.replace(tmp, target)


def prune(root: Path | None = None, keep: int = 10, days: int = 90) -> list[Path]:
    """每个目标保留最近 keep 份且不超过 days 天；返回被删列表。"""
    root = root or paths.backups_root()
    removed: list[Path] = []
    if not root.is_dir():
        return removed
    cutoff = time.time() - days * 86400
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        items = sorted((p for p in d.iterdir() if p.is_file()),
                       key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        for i, p in enumerate(items):
            if i >= keep or p.stat().st_mtime < cutoff:
                try:
                    p.unlink()
                    removed.append(p)
                except OSError:
                    pass
    return removed
