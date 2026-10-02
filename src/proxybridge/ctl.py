"""控制层：给 GUI / 脚本用的**唯一命令入口**（JSON in / JSON out，绝不写文件）。

GUI 只调本模块；本模块只调 core。这样 GUI 永远不可能绕过 core 直接写盘。
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Callable

from . import browser, config, launcher, paths, power, sysproxy, tunnel, uninstall


def _timed(fn: Callable[[], Any]) -> tuple[Any, int]:
    t0 = time.monotonic()
    out = fn()
    return out, int((time.monotonic() - t0) * 1000)


# ---------------- 只读 ----------------
def snapshot() -> dict:
    """GUI 状态栏用的单次快照（只读）。**任何子项失败都不得让整块崩掉**（GUI 兜底契约）。"""
    out: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config_ok": True, "config_error": "", "config": {},
        "power": {"env_exists": False, "listening": False, "bind": "?", "upstream": "?"},
        "sysproxy": {}, "logs_dir": str(paths.logs_dir()),
        "browsers": {}, "desktop": [],
        "errors": [],
    }

    def _try(label, fn, default=None):
        try:
            return fn()
        except Exception as exc:                              # noqa: BLE001
            out["errors"].append(f"{label}: {exc}")
            return default

    cfg = _try("config", config.load, None)
    if cfg is None:
        out["config_ok"] = False
        out["config_error"] = out["errors"][-1] if out["errors"] else "配置读取失败"
    else:
        out["config"] = cfg
    tun = _try("tunnel", tunnel.status, {}) or {}
    out["power"] = {
        "env_exists": paths.env_sh().exists(),
        "listening": bool(tun.get("listening")),
        "bind": tun.get("bind", "?"), "upstream": tun.get("upstream", "?"),
    }
    out["sysproxy"] = _try("sysproxy", sysproxy.status, {}) or {}
    out["browsers"] = _try("browsers", browser.available, {}) or {}
    out["desktop"] = [{"kind": t.kind, "name": t.name, "ours": t.ours, "exists": t.exists}
                      for t in (_try("desktop", launcher.status, []) or [])]
    return out


def doctor_json() -> dict:
    from . import doctor
    checks, code = doctor.run()
    return {"exit_code": code,
            "checks": [asdict(c) for c in checks]}


def doctor_text() -> dict:
    """体检（只读）。GUI 用：不弹窗报错，只把结论写进日志/状态。"""
    from . import doctor
    checks, code = doctor.run()
    bad = [c for c in checks if c.level != "ok"]
    msg = f"体检：{'全部通过' if code == 0 else f'{len(bad)} 项需要注意'}"
    detail = "\n".join(f"{c.level.upper():4} {c.title}：{c.detail}" for c in checks)
    return {"ok": True, "message": msg, "detail": detail, "exit_code": code}


# ---------------- 变更 ----------------
def on() -> dict:
    o, ms = _timed(power.on)
    return {"ok": o.ok, "message": o.message, "detail": o.detail, "ms": ms}


def off() -> dict:
    o, ms = _timed(power.off)
    return {"ok": o.ok, "message": o.message, "detail": o.detail, "ms": ms}


def sysproxy_on() -> dict:
    o, ms = _timed(sysproxy.on)
    return {"ok": o.ok, "message": o.message, "detail": o.detail, "ms": ms}


def sysproxy_off() -> dict:
    o, ms = _timed(sysproxy.off)
    return {"ok": o.ok, "message": o.message, "detail": o.detail, "ms": ms}


def support_bundle() -> dict:
    from . import support
    path, ms = _timed(support.build)
    return {"ok": True, "message": f"已生成 {path}", "path": str(path), "ms": ms}


def open_browser(kind: str) -> dict:
    """开一个走桥的浏览器窗口（不等待退出）。"""
    o, ms = _timed(lambda: browser.launch(kind))
    return {"ok": o.ok, "message": o.message, "detail": o.detail,
            "pid": o.pid, "proxy": o.proxy, "ms": ms}


def open_chrome() -> dict:
    return open_browser("chrome")


def open_firefox() -> dict:
    return open_browser("firefox")


def desktop_on() -> dict:
    o, ms = _timed(power.install_desktop)
    return {"ok": o.ok, "message": o.message, "detail": o.detail, "ms": ms}


def desktop_off() -> dict:
    o, ms = _timed(power.remove_desktop)
    return {"ok": o.ok, "message": o.message, "detail": o.detail, "ms": ms}


def uninstall(purge: bool = False) -> dict:
    def _do():
        return uninstall.run(purge=purge)
    rep, ms = _timed(_do)
    return {"ok": rep.ok, "message": uninstall.render(rep), "ms": ms}


# ---------------- 给 GUI 的动作表 ----------------
ACTIONS: dict[str, Callable[..., dict]] = {
    "on": on, "off": off,
    "sysproxy_on": sysproxy_on, "sysproxy_off": sysproxy_off,
    "open_chrome": open_chrome, "open_firefox": open_firefox,
    "desktop_on": desktop_on, "desktop_off": desktop_off,
    "support_bundle": support_bundle,
    "doctor": doctor_text,
    "uninstall": uninstall,
}

#: GUI 危险操作 → 需要二次确认的文案
DANGEROUS = {
    "uninstall": "将按清单还原所有集成点并删除安装文件",
    "sysproxy_on": "会改写当前用户的系统代理设置（可 `proxy sysproxy off` 还原）",
    "off": "会断开正在走桥的程序（浏览器会自动回到直连，需要重开浏览器）",
}


def call(action: str, **kw) -> dict:
    fn = ACTIONS.get(action)
    if fn is None:
        return {"ok": False, "message": f"未知动作：{action}"}
    try:
        return fn(**kw)
    except TypeError:
        return fn()
