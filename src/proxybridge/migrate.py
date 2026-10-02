"""v1 → v2 迁移：路径搬迁 + 配置转换 + 旧日志归档，全程可回滚。

设计：**只做用户显式允许的三件事**
  1. `~/.proxy.conf` 的 MODE/上游/端口/测试 URL → `config.toml`（旧文件保留不动）
  2. 旧日志 `~/.proxy.log`、`~/.proxy-forward.log` → `logs/legacy/`（`mv`，不 `rm`）
  3. `.profile`/`.bashrc` 里对 `~/.proxy_env` 的裸行 → v2 兼容 shim（执行时解析，无空窗）
"""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import manifest as manifest_mod, paths
from .backup import sha256_file

V1_CONF = ".proxy.conf"
V1_LOGS = [".proxy.log", ".proxy-forward.log", ".proxy-forward.pid"]
MARK = "# >>> proxy-bridge migrate >>>"


@dataclass
class Plan:
    actions: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def summary(self) -> str:
        return "\n".join(f"  - {a}" for a in self.actions) or "  （无动作）"


def _parse_v1_conf(p: Path) -> dict:
    out: dict = {}
    try:
        for line in p.read_text("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def plan() -> Plan:
    pl = Plan()
    home = Path.home()
    conf = home / V1_CONF
    if conf.is_file():
        pl.data["v1_conf"] = _parse_v1_conf(conf)
        pl.actions.append(f"读 {conf} → 生成 config.toml（MODE/上游/端口/测试URL）；旧文件保留")
    for name in V1_LOGS:
        p = home / name
        if p.exists():
            pl.actions.append(f"迁移 {p} → {paths.logs_dir()}/legacy/{name}")
    for name in (".profile", ".bashrc"):
        p = home / name
        if p.is_file() and re.search(r'^\s*\[ -f "\$HOME/\.proxy_env" \] && \. "\$HOME/\.proxy_env"\s*$',
                                     p.read_text("utf-8", errors="replace"), re.M):
            pl.actions.append(f"改写 {p}：裸源 ~/.proxy_env → v2 兼容 shim")
    return pl


def _toml_from(v1: dict) -> str:
    upstream = v1.get("PROXY_HOST", "192.168.18.1:7897")
    bind_host = v1.get("BIND_HOST", "127.0.0.1")
    bind_port = v1.get("BIND_PORT", "7897")
    mode = v1.get("MODE", "forward")
    test_url = v1.get("TEST_URL", "https://github.com")
    return (f"# proxy-bridge v2 配置（由 `proxy migrate` 从 ~/{V1_CONF} 转换）\n"
            f'upstream = "{upstream}"\n'
            f'bind_host = "{bind_host}"\n'
            f"bind_port = {int(bind_port)}\n"
            f'mode = "{mode}"\n'
            f'test_url = "{test_url}"\n')


def apply(dry_run: bool = False) -> Plan:
    pl = plan()
    mf = manifest_mod.Manifest.load()
    ts = time.strftime("%Y%m%dT%H%M%S")

    if "v1_conf" in pl.data:
        cfg = paths.config_file()
        if not dry_run:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            mf.touch(cfg, writer="migrate")
            tmp = cfg.with_suffix(".toml.tmp")
            tmp.write_text(_toml_from(pl.data["v1_conf"]), "utf-8")
            tmp.chmod(0o600)
            tmp.replace(cfg)

    legacy = paths.logs_dir() / "legacy"
    if not dry_run:
        legacy.mkdir(parents=True, exist_ok=True)
    for name in V1_LOGS:
        src = Path.home() / name
        if src.exists() and not dry_run:
            shutil.move(str(src), str(legacy / name))

    for name in (".profile", ".bashrc"):
        p = Path.home() / name
        if not p.is_file():
            continue
        text = p.read_text("utf-8", errors="replace")
        pat = re.compile(r'^\s*\[ -f "\$HOME/\.proxy_env" \] && \. "\$HOME/\.proxy_env"\s*$', re.M)
        if not pat.search(text):
            continue
        if dry_run:
            continue
        backup = p.with_name(p.name + f".migrate-bak-{ts}")
        shutil.copy2(p, backup)
        mf.touch(p, writer="migrate", backup_id=str(backup))
        new = pat.sub(
            "if [ -r \"$HOME/.config/proxy-bridge/env.sh\" ]; then\n"
            "    . \"$HOME/.config/proxy-bridge/env.sh\"\n"
            "elif [ -f \"$HOME/.proxy_env\" ]; then\n"
            "    . \"$HOME/.proxy_env\"\n"
            "fi", text)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(new, "utf-8")
        tmp.replace(p)

    if not dry_run:
        rollback = {"ts": ts, "manifest": str(mf.path)}
        mf.save()
        (paths.state_root()).mkdir(parents=True, exist_ok=True)
        (paths.state_root() / "migrate-last.json").write_text(
            json.dumps(rollback, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return pl


def rollback() -> Plan:
    """用备份还原 `.profile`/`.bashrc`，并把 legacy 日志搬回原处。"""
    pl = Plan()
    mf = manifest_mod.Manifest.load()
    ts = ""
    try:
        ts = json.loads((paths.state_root() / "migrate-last.json").read_text())["ts"]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    for name in (".profile", ".bashrc"):
        p = Path.home() / name
        cand = sorted(p.parent.glob(f"{name}.migrate-bak-*"))
        if cand:
            backups_pre = [c for c in cand if c.name.endswith(ts)] or cand
            shutil.copy2(backups_pre[-1], p)
            pl.actions.append(f"还原 {p} ← {backups_pre[-1].name}")
    legacy = paths.logs_dir() / "legacy"
    for name in V1_LOGS:
        src = legacy / name
        if src.exists():
            shutil.move(str(src), str(Path.home() / name))
            pl.actions.append(f"搬回 {src.name} → ~/{name}")
    # config.toml 若由 migrate 生成则按清单还原
    for key, e in list(mf.entries.items()):
        if e.writer == "migrate" and Path(key).name == "config.toml":
            if e.existed_before and e.backup_id and Path(e.backup_id).is_file():
                shutil.copy2(e.backup_id, key)
                pl.actions.append(f"还原 {key}")
            elif not e.existed_before:
                Path(key).unlink(missing_ok=True)
                pl.actions.append(f"删除 {key}（原本不存在）")
    return pl
