"""只读体检（复刻 v1 `proxy doctor` 的结论口径）。只读：不改任何文件。

口径（用户拍板 2026-10-01）：**"没启用"不是故障**。
本机常态就是"没注入、没转发器、没设系统代理"——那是"没开"，不是"坏了"，
所以 doctor 在那里必须 ❌0/⚠️0。只有**真的不一致/真的指向错地方**才报警。
退出码：0 全过；2 有 warn / fail。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import config, paths, probe, sysproxy
from .exitcodes import DOCTOR_FAILED, OK
from .tunnel import forwarder_pids as _forwarder_pids       # 单一实现，见 tunnel.forwarder_pids

PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy")


@dataclass
class Check:
    level: str        # ok | warn | fail
    title: str
    detail: str = ""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _strip_quotes(v: str) -> str:
    return v.strip().strip("'\"")


def _points_elsewhere(value: str, cfg: dict) -> bool:
    """`*_proxy` 的值是否不指向本地转发器（空值算"没设"，不算指错）。"""
    v = value.strip()
    if not v:
        return False
    return f"{cfg['bind_host']}:{cfg['bind_port']}" not in v


def check_system_proxy(cfg: dict) -> Check:
    """系统代理（gsettings）是否指向本地转发器；`sysproxy.available()` 是否可用。

    浏览器走代理**主要靠环境变量通路**（`proxy chrome` / 图标接管）；这条 gsettings 只对
    Firefox 与"自认 GNOME"的 Chrome 有效。没设（mode=none）不算故障 —— 那是"还没开"。
    """
    if not sysproxy.available():
        return Check("warn", "系统代理", f"没有 {sysproxy.SCHEMA} schema → 浏览器走环境变量通路"
                                          f"（`proxy chrome` / `proxy desktop on`）")
    st = sysproxy.status()
    if _strip_quotes(str(st.get("mode", ""))) != "manual":
        return Check("ok", "系统代理", f"未设置（mode={st.get('mode')}）→ 需要时 `proxy sysproxy on`")
    want = f"{cfg['bind_host']}:{cfg['bind_port']}"
    got = f"{_strip_quotes(str(st.get('http_host')))}:{_strip_quotes(str(st.get('http_port')))}"
    if got != want:
        return Check("warn", "系统代理", f"指向 {got}，与本地转发器 {want} 不一致 → `proxy sysproxy on`")
    return Check("ok", "系统代理", f"mode=manual → {got}")


def check_browser_path() -> Check:
    """浏览器通路：**只报事实**，不判故障（"没开"不是故障）。

    实测口径（2026-10-01）：Chrome 在 XFCE 上不读 gsettings 系统代理，
    所以"点菜单图标"这条路必须靠 `desktop` 接管或 `proxy chrome` 才有代理。
    """
    from . import browser, launcher
    got = browser.available()
    have = [browser.LABELS[k] for k, v in got.items() if v]
    if not have:
        return Check("warn", "浏览器通路", "没发现 Chrome/Firefox（装一个再用）")
    ours = [t for t in launcher.status() if t.ours]
    tail = (f"点图标已走桥（已接管 {len(ours)} 个）" if ours
            else "点图标会**直连** → 用 `proxy chrome` 或 `proxy desktop on`")
    return Check("ok", "浏览器通路", f"{'、'.join(have)}；{tail}")


def run(env: dict | None = None) -> tuple[list[Check], int]:
    env = env if env is not None else os.environ
    checks: list[Check] = []

    try:
        cfg = config.load()
        checks.append(Check("ok", "配置",
                            f"mode={cfg['mode']} 上游={cfg['upstream']} 本地={cfg['bind_host']}:{cfg['bind_port']}"))
    except config.ConfigError as exc:
        checks.append(Check("fail", "配置", str(exc)))
        return checks, DOCTOR_FAILED

    up = str(cfg["upstream"])
    reachable = probe.upstream_reachable(up)
    checks.append(Check("ok" if reachable else "warn",
                        f"上游 {up}", "可达" if reachable else "不可达"))

    # 关键证据：本机没有转发器时，7897 必须 closed（socket 直连判定，不靠进程名）
    listening = probe.port_open(cfg["bind_host"], cfg["bind_port"])
    pids = [p for p in _forwarder_pids() if _pid_alive(p)] if listening else []
    running = bool(listening or pids)
    who = f"pid {pids[0]}" if pids else ("端口被外部进程占用" if listening else "无进程")
    checks.append(Check("ok", "转发器",
                        f"{who}；{cfg['bind_host']}:{cfg['bind_port']} "
                        f"{'listening（运行中）' if listening else 'closed'}"
                        f"{'（未运行；`proxy on` 可起）' if not running else ''}"))

    checks.append(check_system_proxy(cfg))
    checks.append(check_browser_path())

    # 下面两项只在转发器**已在跑**（= 用户确实开了）时才可能报警，避免把"没开"报成故障
    bad_vars = [k for k in PROXY_VARS if k in env and _points_elsewhere(env[k], cfg)]
    has_vars = [k for k in env if k.lower() in PROXY_VARS]
    if has_vars and bad_vars:
        checks.append(Check("warn", "当前进程 *_proxy",
                            f"{len(has_vars)} 个，但 {'、'.join(bad_vars)} 不指向 "
                            f"{cfg['bind_host']}:{cfg['bind_port']}（重开终端或 `proxy on`）"))
    else:
        checks.append(Check("ok", "当前进程 *_proxy",
                            f"{len(has_vars)} 个" if has_vars else "0 个（未启用）"))

    env_sh = paths.env_sh()
    if env_sh.exists():
        checks.append(Check("ok", "环境变量文件", str(env_sh)))
    elif running:
        checks.append(Check("warn", "环境变量文件", f"{env_sh} 不存在，但转发器在跑（重跑 `proxy on`）"))
    else:
        checks.append(Check("ok", "环境变量文件", f"{env_sh}（未创建）"))

    return checks, (OK if all(c.level == "ok" for c in checks) else DOCTOR_FAILED)


def render(checks: list[Check]) -> str:
    mark = {"ok": "[ ✓ ]", "warn": "[ ! ]", "fail": "[ ✗ ]"}
    lines = ["[proxy] ===== doctor（v2 只读骨架）====="]
    for c in checks:
        lines.append(f"[proxy] {mark[c.level]} {c.title}：{c.detail}")
    return "\n".join(lines)
