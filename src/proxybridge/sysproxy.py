"""代理接入的两条通路：① 环境变量（**日常主用**）② GNOME gsettings 系统代理（副）。

**2026-10-01 现场复测（转发器真实在线、真实 GUI 会话身份）——修正了此前的判断**
    只给 `*_proxy` 环境变量  → 52 条连接 / 3.59 MB 过桥 ✅
    只给 `--proxy-server`    → 46 条连接 / 5.88 MB 过桥 ✅
    什么都不给（= 从菜单点浏览器图标）→ 0 条 ❌
结论：**桥本身没问题，问题在"浏览器怎么启动"**。`browser_launch_env()` 就是补这个条件。
从菜单/面板点图标启动的浏览器拿不到这些变量，于是走 `desktop.py`（用户级 .desktop 接管）。

**关键实测（2026-10-01，矩阵 33 例；探针假代理 + netlog 双证据）**
    系统代理 manual + `XDG_CURRENT_DESKTOP` 里**冒号分隔的某一段恰好是 `GNOME`**（如 `ubuntu:GNOME`）→ 走代理 ✅
    未设 `XDG_CURRENT_DESKTOP` 时 `DESKTOP_SESSION=gnome` 也认                                  → 走代理 ✅
    `gnome` 小写 / `GNOME-Classic` / 空串 / `XFCE` / 只给 `GDMSESSION`                          → 不走 ❌
    环境变量 `http_proxy` / `HTTP_PROXY`（大写也认）/ `all_proxy`                                → 走代理 ✅（**不需要桌面身份**）
    优先级：命令行 `--proxy-server` > 系统代理 > 环境变量；`--no-proxy-server` 一票否决
    Firefox：默认设置就是"用系统代理"，读本通道**不需要任何身份**（同批实测）

结论：`org.gnome.system.proxy` 的 schema 与读取链路在**任何桌面**上都可用；Chrome 只是用
`XDG_CURRENT_DESKTOP`（缺失时回退 `DESKTOP_SESSION`）判断"当前是不是 GNOME 桌面"。因此在 XFCE/MX 上
让 Chrome 走系统代理只需要两件事：
  ① `gsettings` 把代理指向本地转发端口（本模块 on()）
  ② 启动浏览器时带 `XDG_CURRENT_DESKTOP=GNOME`（本模块 browser_env()）

不需要安装 GNOME/gnome-settings-daemon/gnome-control-center，不需要换系统，也不需要改动登录链文件。
环境健壮性：无会话总线 / 总线地址无效 / `HOME` 指向别处 / 极简环境，**只要身份在就读得到**；
`GSETTINGS_BACKEND=memory` 时读不到（反证机制就是 GSettings）。
原始证据：`spike/browser-proxy-matrix/evidence/20261001-*`（量具说明书见同目录 README.md）。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from . import config, logs

SCHEMA = "org.gnome.system.proxy"
DEFAULT_IGNORE = ["localhost", "127.0.0.1", "::1", "192.168.18.1", "192.168.18.2"]


@dataclass
class Outcome:
    ok: bool
    message: str
    detail: str = ""


def _gs(*args: str, timeout: int = 10) -> tuple[bool, str]:
    try:
        r = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def available() -> bool:
    ok, _ = _gs("list-schemas")
    if not ok:
        return False
    ok2, out = _gs("list-schemas")
    return SCHEMA in out.split()


#: (逻辑名, gsettings schema, key)
KEYS = [
    ("mode", SCHEMA, "mode"),
    ("http_host", f"{SCHEMA}.http", "host"),
    ("http_port", f"{SCHEMA}.http", "port"),
    ("https_host", f"{SCHEMA}.https", "host"),
    ("https_port", f"{SCHEMA}.https", "port"),
    ("ignore", SCHEMA, "ignore-hosts"),
]


def status() -> dict:
    out: dict = {}
    for name, schema, key in KEYS:
        ok, val = _gs("get", schema, key)          # 坑：必须 get <schema> <key>，只传 schema 会 Usage 报错
        out[name] = val if ok else f"<err: {val.splitlines()[0][:50]}>"
    out["available"] = available()
    return out


def on(host: str | None = None, port: int | None = None) -> Outcome:
    """把系统代理指向本地转发器（只改当前用户的 gsettings，可逆）。"""
    cfg = config.load()
    host = host or str(cfg["bind_host"])
    port = int(port or cfg["bind_port"])
    if not available():
        return Outcome(False, "系统里没有 GNOME 代理 schema，本方案不适用",
                       "可以用浏览器参数兜底：--proxy-server=http://127.0.0.1:7897")
    steps = []
    plan = [(SCHEMA, "mode", "manual"),
            (f"{SCHEMA}.http", "host", host), (f"{SCHEMA}.http", "port", str(port)),
            (f"{SCHEMA}.https", "host", host), (f"{SCHEMA}.https", "port", str(port)),
            (SCHEMA, "ignore-hosts", str(DEFAULT_IGNORE))]
    for schema, key, value in plan:
        ok, msg = _gs("set", schema, key, value)
        steps.append(f"{schema}:{key}={'ok' if ok else 'FAIL:' + msg.splitlines()[0][:40]}")
    logs.EventLog("app").event("sysproxy_on", result="ok", host=host, port=port)
    return Outcome(True, f"系统代理已指向 {host}:{port}",
                   "；".join(steps) + "\n注意：Chrome 在 XFCE 上**不读**这条（实测）——"
                   "走桥请用 `proxy chrome`，或先 `proxy desktop on` 接管图标")


def off() -> Outcome:
    """还原为直连（mode=none），并清掉我们设过的键。"""
    if not available():
        return Outcome(True, "无 GNOME 代理 schema，无需还原")
    _gs("set", SCHEMA, "mode", "none")
    for sub in ("http", "https"):
        _gs("reset", f"{SCHEMA}.{sub}", "host")
        _gs("reset", f"{SCHEMA}.{sub}", "port")
    _gs("reset", SCHEMA, "ignore-hosts")
    # 复核：mode 必须真的回到 none
    ok, val = _gs("get", SCHEMA, "mode")
    logs.EventLog("app").event("sysproxy_off", result="ok")
    return Outcome(True, "系统代理已还原为直连（mode=none）", f"当前 mode={status()['mode']}")


#: 我们写进子进程环境的代理变量（大写一并给：Chrome 两种都认，curl/pip 认小写）
PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy")

#: 本地地址永远直连（含 VPN 网关，避免自环）
DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1,192.168.18.1,192.168.18.2"


def browser_launch_env(bind: str, no_proxy: str = DEFAULT_NO_PROXY) -> dict:
    """**由我们启动的浏览器**要带的代理环境变量 —— 唯一不依赖桌面身份的通路。

    为什么不是 `XDG_CURRENT_DESKTOP=GNOME`：那会让浏览器按 GNOME 去做 GTK 集成，
    而且只在读 gsettings 时才需要；环境变量在**任何桌面**都生效，也更接近 v1 的老通路。
    """
    url = f"http://{bind}"
    env = {v: url for v in PROXY_VARS}
    env.update({v.upper(): url for v in PROXY_VARS})
    env["no_proxy"] = no_proxy
    env["NO_PROXY"] = no_proxy
    return env


def strip_proxy_env(env: dict) -> dict:
    """把 `*_proxy` 从环境里摘掉（转发器没在跑时必须摘，否则浏览器被锁在门外）。"""
    for k in list(env):
        if k.lower() in PROXY_VARS or k.lower() in ("no_proxy",):
            env.pop(k, None)
    return env
