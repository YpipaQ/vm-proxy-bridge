"""浏览器通路：把"点图标就直连"变成"点图标就走桥"。

**为什么需要这个模块**（2026-10-01 现场实测，转发器真实在线）：
    浏览器                     系统代理 + 真实桌面身份(XFCE)      给 *_proxy 环境变量
    Chrome（菜单点图标）        0 条连接 ❌（它只在"自认 GNOME"时才读 gsettings）
    Chrome（本模块启动）        —                                  52 条 / 3.59 MB ✅
    Firefox                    22 条 ✅（默认就是"用系统代理"）      ✅
所以日常只有一条路要走稳：**由我们带着代理变量去启动浏览器**。本模块负责这条路，
并在转发器没在跑时**主动摘掉**代理变量（否则浏览器会指着一个死端口，人被锁在门外）。

输入 / 输出（模块契约）：
    输入：`kind`（"chrome" | "firefox"）、`extra`（浏览器自己的参数，原样透传）、
          配置（`config.load()`：bind_host/bind_port/upstream/no_proxy）、环境变量、转发器是否在听。
    输出：`Outcome(ok, message, detail, pid, proxy)`；副作用 = 起一个**不等待**的浏览器进程 +
          一行 `browser_launch` 事件日志。不写任何文件，不改系统设置。
    不做：不判断浏览器内部行为、不装浏览器、不等浏览器退出、不碰用户 profile。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from . import config, logs, probe, sysproxy

#: 浏览器种类 → 候选可执行文件（按顺序取第一个存在的）
PRESETS: dict[str, tuple[str, ...]] = {
    "chrome": ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser"),
    "firefox": ("firefox", "firefox-esr"),
}
LABELS = {"chrome": "Chrome", "firefox": "Firefox"}


@dataclass
class Outcome:
    ok: bool
    message: str
    detail: str = ""
    pid: int | None = None
    proxy: bool = False


def find(kind: str) -> str | None:
    for name in PRESETS.get(kind, ()):
        p = shutil.which(name)
        if p:
            return p
    return None


def available() -> dict[str, str | None]:
    return {k: find(k) for k in PRESETS}


def build_env(kind: str, cfg: dict | None = None) -> tuple[dict, bool]:
    """子进程环境 + 这次是否真的挂了代理（转发器没在跑 → 摘掉变量，返回 False）。"""
    cfg = cfg or config.load()
    env = dict(os.environ)
    bind = f"{cfg['bind_host']}:{cfg['bind_port']}"
    if probe.port_open(cfg["bind_host"], cfg["bind_port"]):
        env.update(sysproxy.browser_launch_env(bind, str(cfg.get("no_proxy") or "") or
                                               sysproxy.DEFAULT_NO_PROXY))
        return env, True
    return sysproxy.strip_proxy_env(env), False


def launch(kind: str, extra: list[str] | None = None) -> Outcome:
    """启动浏览器。**不等待**（浏览器是长驻进程，等它等于把终端/界面占住）。"""
    if kind not in PRESETS:
        return Outcome(False, f"不认识的浏览器：{kind}",
                       "可用：" + "、".join(f"{k}（{v}）" for k, v in LABELS.items()))
    exe = find(kind)
    if not exe:
        return Outcome(False, f"系统里找不到 {LABELS[kind]}",
                       "候选：" + "、".join(PRESETS[kind]))
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        return Outcome(False, "配置非法，拒绝启动", str(exc))

    env, proxied = build_env(kind, cfg)
    argv = [exe, *(extra or [])]
    try:
        proc = subprocess.Popen(argv, env=env, start_new_session=True,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return Outcome(False, f"{LABELS[kind]} 启动失败", str(exc))

    bind = f"{cfg['bind_host']}:{cfg['bind_port']}"
    if proxied:
        msg, detail = f"已启动 {LABELS[kind]}（走桥 {bind} → {cfg['upstream']}）", \
                      "第一次开的窗口才带代理；已经开着的旧窗口不会变，重开一个即可"
    else:
        msg, detail = f"已启动 {LABELS[kind]}（**直连**：转发器没在跑）", \
                      "先 `proxy on`（或界面上的「一键开启」）再开浏览器才会走桥"
    logs.EventLog("app").event("browser_launch", result="ok" if proxied else "direct",
                               kind=kind, pid=proc.pid)
    return Outcome(True, msg, detail, pid=proc.pid, proxy=proxied)
