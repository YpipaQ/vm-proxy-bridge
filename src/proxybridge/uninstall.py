"""卸载：按清单**逆序**还原每一个集成点，然后逐字节校验。

硬验收（HANDOFF §8）：卸载后 `~/.config/proxy-bridge/env.sh`、`~/.local/bin/proxy`
等所有集成点全部还原到安装前 sha256；`--dry-run` 与实际一致、可重复执行。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import backup, logs, manifest as manifest_mod, paths
from .backup import sha256_file


@dataclass
class Report:
    restored: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)         # 原本不存在 → 删除
    missing_backup: list[str] = field(default_factory=list)  # 清单有、备份没了 → 必须报告
    mismatched: list[str] = field(default_factory=list)      # 还原后 sha256 不符
    kept: list[str] = field(default_factory=list)            # --purge 时才删的数据

    @property
    def ok(self) -> bool:
        return not self.mismatched and not self.missing_backup


def restore_entry(entry: manifest_mod.Entry, report: Report) -> None:
    p = Path(entry.path)
    if not entry.existed_before:
        if p.exists() or p.is_symlink():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            report.removed.append(entry.path)
        return
    bpath = Path(entry.backup_id) if entry.backup_id else None
    if not bpath or not bpath.is_file():
        report.missing_backup.append(f"{entry.path}（清单说原本存在，但备份缺失）")
        return
    backup.restore(bpath, p)
    got = sha256_file(p) if p.is_file() else None
    if got != entry.sha256_before:
        report.mismatched.append(f"{entry.path}：还原后 {got} ≠ 登记 {entry.sha256_before}")
    else:
        report.restored.append(entry.path)


def restore_matching(prefix: str) -> Report:
    """只还原清单里**路径以 prefix 开头**的项，其余登记保留（给 `proxy desktop off` 用）。"""
    rep = Report()
    m = manifest_mod.Manifest.load()
    keys = [k for k in m.entries if k.startswith(prefix)]
    if not keys:
        return rep
    for k in reversed(keys):
        restore_entry(m.entries[k], rep)
        m.entries.pop(k, None)
    m.save()
    logs.EventLog("app").event("restore_matching", result="ok" if rep.ok else "mismatch",
                               prefix=prefix, n=len(keys))
    return rep


def run(purge: bool = False) -> Report:
    rep = Report()
    m = manifest_mod.Manifest.load()
    if not m.entries:
        # 没有清单：**什么都不删**（清单是唯一依据，宁可拒绝也不猜）
        return rep

    # 逆序还原：后写的先撤
    for key in reversed(list(m.entries)):
        restore_entry(m.entries[key], rep)

    if purge:
        for d in (paths.state_root(), paths.cache_root(), paths.backups_root(), paths.data_root()):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                rep.removed.append(str(d))
    else:
        rep.kept = [str(paths.state_root()), str(paths.backups_root()), str(paths.data_root())]

    m.path.unlink(missing_ok=True)
    logs.EventLog("app").event("uninstall", result="ok" if rep.ok else "mismatch",
                               restored=len(rep.restored), removed=len(rep.removed))
    return rep


def render(rep: Report) -> str:
    lines = []
    if not rep.restored and not rep.removed and not rep.kept:
        return "没有安装清单：无可卸载项（未改动任何文件）"
    lines.append(f"还原 {len(rep.restored)} 项 / 删除 {len(rep.removed)} 项")
    if rep.missing_backup:
        lines.append("❌ 缺备份（无法还原）：")
        lines += [f"   - {x}" for x in rep.missing_backup]
    if rep.mismatched:
        lines.append("❌ 还原后 sha256 不符：")
        lines += [f"   - {x}" for x in rep.mismatched]
    if rep.kept:
        lines.append("保留（加 --purge 可删）：" + "、".join(rep.kept))
    if rep.ok:
        lines.append("✅ 卸载校验通过：所有集成点与安装前逐字节一致")
    return "\n".join(lines)
