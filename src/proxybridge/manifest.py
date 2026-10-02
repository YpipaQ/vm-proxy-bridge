"""安装清单：记录软件碰过的每一个文件（写入前 sha256 / 是否原本不存在）。

这是 `proxy uninstall` 的唯一依据 —— 没有清单就不许卸载（宁可拒绝，也不猜）。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import paths
from .backup import sha256_file
from .logs import ensure_dir

SCHEMA = 1


@dataclass
class Entry:
    path: str
    existed_before: bool
    sha256_before: str | None      # 原本不存在 → None
    backup_id: str | None
    writer: str                    # power | entry | migrate
    ts: str
    kind: str = "file"             # file | symlink


class Manifest:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.manifest_file()
        self.schema = SCHEMA
        self.version = "0.1.0"
        self.entries: dict[str, Entry] = {}

    # ---------- 读 ----------
    @classmethod
    def load(cls, path: Path | None = None) -> "Manifest":
        m = cls(path)
        try:
            data = json.loads(m.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return m
        m.schema = data.get("schema", SCHEMA)
        m.version = data.get("version", m.version)
        for p, e in (data.get("entries") or {}).items():
            known = set(Entry.__dataclass_fields__)
            m.entries[p] = Entry(**{k: v for k, v in e.items() if k in known})
        return m

    # ---------- 写 ----------
    def save(self) -> None:
        ensure_dir(self.path.parent)
        payload = {
            "schema": self.schema, "version": self.version,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "entries": {p: asdict(e) for p, e in self.entries.items()},
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def _record(self, path: Path, writer: str, kind: str, backup_id: str | None,
                existed: bool, sha: str | None, *, force: bool = False) -> Entry:
        """登记一个将被写入的路径。**首次登记时的状态才是"安装前"状态**（后续调用不覆盖）。"""
        key = str(path)
        if force or key not in self.entries:
            self.entries[key] = Entry(
                path=key, existed_before=existed, sha256_before=sha,
                backup_id=backup_id, writer=writer, kind=kind,
                ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            )
        return self.entries[key]

    def touch(self, path: Path, writer: str, kind: str = "file",
              backup_id: str | None = None) -> Entry:
        """**写之前**调用：记录原始状态。"""
        p = Path(path)
        existed = p.exists()
        return self._record(p, writer, kind, backup_id, existed,
                            sha256_file(p) if existed and p.is_file() else None)

    def scan_integration_points(self, extra: list[Path] | None = None) -> list[Path]:
        """软件会碰的全部集成点（env.sh、稳定入口、备份目录 + 传入的额外路径）。"""
        pts = [
            paths.env_sh(),
            Path.home() / ".local" / "bin" / "proxy",
            paths.backups_root(),
        ]
        pts.extend(Path(p) for p in (extra or []))
        return pts

    def verify_unchanged_by_others(self) -> list[str]:
        """doctor 用：清单登记后又被外部改过的文件（改了 → 应告警）。"""
        bad: list[str] = []
        for key, e in self.entries.items():
            if not e.existed_before or e.sha256_before is None:
                continue
            p = Path(key)
            if not p.is_file():
                bad.append(f"{key}：清单登记时存在，现在不见了")
                continue
            if sha256_file(p) != e.sha256_before:
                bad.append(f"{key}：sha256 与登记不符（外部改动？）")
        return bad
