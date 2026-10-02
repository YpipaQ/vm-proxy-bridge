"""总开关：`proxy on|off`（env 文件 + 转发器 + 稳定入口，一把开关）。

分工（见 MODULES.md）：本模块只做**编排**，具体动作分别落在
`state`（原子写/env）、`entry`（稳定入口）、`tunnel`（长驻）。
"""
from __future__ import annotations

import os
import time
import subprocess
from dataclasses import dataclass

from . import backup, config, entry, logs, manifest as manifest_mod, paths, state


@dataclass
class Outcome:
    ok: bool
    message: str
    detail: str = ""


ENV_TEMPLATE = """# proxy-bridge v2 生成（原内容来自 v1 ~/.proxy_env）
export http_proxy="http://{bind}"
export https_proxy="http://{bind}"
export HTTP_PROXY="http://{bind}"
export HTTPS_PROXY="http://{bind}"
# 注意：本机转发器是 HTTP CONNECT 通道，**不是** SOCKS5；v1 曾误写 socks5:// 导致协议错配
export no_proxy="{no_proxy}"
export NO_PROXY="{no_proxy}"
"""


def _backup_id(f, mf: manifest_mod.Manifest) -> str | None:
    """写之前备份，返回 backup_id。

    **只在清单首次登记该路径时备份** —— 否则重复 `proxy on` 会把"已经是我们写的"
    内容当成"安装前状态"再备份一次，覆盖掉真正的原件，卸载就还原不回去了（踩过）。
    """
    if str(f) in mf.entries:
        return mf.entries[str(f)].backup_id
    b = backup.backup(f)
    return str(b) if b else None


def register_file(f, writer: str) -> str | None:
    """备份 + 登记（首次登记时的状态才算"安装前"）；返回 backup_id。"""
    with state.single_writer():
        mf = manifest_mod.Manifest.load()
        e = mf.touch(f, writer=writer, backup_id=_backup_id(f, mf))
        mf.save()
        return e.backup_id


def _write_atomic(f, text: str, mode: int = 0o644) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(f.suffix + ".tmp")
    tmp.write_text(text, "utf-8")
    tmp.chmod(mode)
    tmp.replace(f)


def write_env(cfg: dict | None = None, mode: str | None = None) -> Outcome:
    """原子写入 `~/.config/proxy-bridge/env.sh`；`mode=off` 时清空导出并提示重开终端。"""
    cfg = cfg or config.load()
    mode = mode or str(cfg["mode"])
    f = paths.env_sh()
    if mode == "off":
        _write_atomic(f, "# proxy-bridge: 已关闭（无导出）\n")
        return Outcome(True, "已清空环境变量文件", "当前终端需重开或手动 unset（proxy env show 可看）")
    bind = f"{cfg['bind_host']}:{cfg['bind_port']}"
    text = ENV_TEMPLATE.format(bind=bind, no_proxy=cfg["no_proxy"])
    register_file(f, "power")                              # 先备份原件（写之前）
    _write_atomic(f, text)
    logs.EventLog("app").event("env_write", result="ok", bind=bind)
    return Outcome(True, f"环境变量文件已写：{f}", f"代理 {bind}；no_proxy={cfg['no_proxy']}")


def install_entry() -> Outcome:
    """写稳定入口 `~/.local/bin/proxy`，并登记进清单（重复执行 = 覆盖，幂等）。"""
    p = entry.wrapper_path()
    register_file(p, "entry")                              # 先备份原件（写之前）
    try:
        entry.install()
    except OSError as exc:
        return Outcome(False, "稳定入口写入失败", str(exc))
    return Outcome(True, f"稳定入口已就绪：{p}")


def install_desktop() -> Outcome:
    """写用户级 .desktop 覆盖，让点图标启动的浏览器也走桥（见 desktop.py）。"""
    from . import launcher
    want = launcher.desired()
    if not want:
        return Outcome(True, "没发现可接管的浏览器（跳过）", "装上 Chrome/Firefox 后再 `proxy desktop on`")
    done = []
    for p, text in want.items():
        register_file(p, "desktop")                        # 先备份原件（写之前）
        _write_atomic(p, text)
        done.append(p.name)
    return Outcome(True, f"已接管 {len(done)} 个浏览器图标", "、".join(done) +
                   "；关桥后这些图标会自动回到直连（不用改回来）")


def remove_desktop() -> Outcome:
    """撤销 .desktop 接管：按清单还原（原本没有 → 删掉）。"""
    from . import launcher, uninstall as un
    d = str(launcher.applications_dir())
    rep = un.restore_matching(d)
    return Outcome(rep.ok, f"已撤销浏览器图标接管（还原 {len(rep.restored)} / 删除 {len(rep.removed)}）",
                   "；".join(rep.mismatched or rep.missing_backup))


def _pidfile() -> Path:
    return paths.state_root() / "forward.pid"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_forward() -> Outcome:
    """把 `proxy forward run` 挂到后台；**端口已在听就跳过启动**。

    踩过：重复起第二个必然 `Address already in use` 退出，却把 pid 文件写成一个死 pid，
    于是 `proxy off` 停不掉真正在跑的那个。
    """
    from . import probe, tunnel
    cfg = config.load()
    if probe.port_open(cfg["bind_host"], int(cfg["bind_port"])):
        pids = tunnel.forwarder_pids()
        if pids:
            _pidfile().parent.mkdir(parents=True, exist_ok=True)
            _pidfile().write_text(str(pids[0]), "utf-8")
        return Outcome(True, f"转发器已在运行（pid {pids[0] if pids else '未知'}，跳过启动）",
                       "端口已在监听")
    log = paths.logs_dir() / "forward.stdout.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as fh:
            proc = subprocess.Popen(entry.argv("forward", "run"), stdout=fh, stderr=fh,
                                    start_new_session=True, close_fds=True)
    except OSError as exc:
        return Outcome(False, "转发器启动失败", str(exc))
    _pidfile().parent.mkdir(parents=True, exist_ok=True)
    _pidfile().write_text(str(proc.pid), "utf-8")
    return Outcome(True, f"转发器已后台启动（pid={proc.pid}）", f"日志：{log}")


def stop_forward(timeout: float = 6.0) -> Outcome:
    """停转发器，并**等它真的停下来**（进程没了 + 端口不再监听）。

    踩过：只发 SIGTERM 就返回，转发器还在优雅收尾的几秒里监听 7897；
    紧接着起的浏览器/转发器会以为"桥还在"，或撞上 `Address already in use`。
    """
    from . import probe, tunnel
    cfg = config.load()
    host, port = cfg["bind_host"], int(cfg["bind_port"])
    pidf = _pidfile()

    targets: list[int] = []
    try:
        if pidf.exists():
            pid = int(pidf.read_text().strip() or 0)
            if pid > 1 and _alive(pid):
                targets.append(pid)
    except (OSError, ValueError):
        pass
    for pid in tunnel.forwarder_pids():                    # 兜底：pid 文件可能是旧的/错的
        if _alive(pid) and pid not in targets:
            targets.append(pid)

    for pid in targets:
        try:
            os.kill(pid, 15)
        except OSError:
            pass

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_alive(p) for p in targets) and not probe.port_open(host, port, 0.3):
            break
        time.sleep(0.2)
    stuck = [p for p in targets if _alive(p)]
    if stuck:                                              # 赖着不走 → 升级
        for p in stuck:
            try:
                os.kill(p, 9)
            except OSError:
                pass
        time.sleep(0.3)
    pidf.unlink(missing_ok=True)
    still = probe.port_open(host, port, 0.5)
    if not targets:
        return Outcome(True, "转发器本来就没在跑", "")
    return Outcome(not still, f"转发器已停（{'、'.join(f'pid {p}' for p in targets)}）",
                   "端口已释放" if not still else f"⚠️ {host}:{port} 仍在监听（可能被别的进程占用）")


def _write_state(desired_on: bool, actual: str) -> None:
    """把开关结果落进 state.json —— 否则 `proxy status` 会一直说"没开"（踩过）。"""
    try:
        with state.single_writer():
            st = state.read_state()
            st["desired_on"] = bool(desired_on)
            st["actual"] = actual
            state.write_state(st)
    except (OSError, TimeoutError):
        pass


def on() -> Outcome:
    """**一把开关**：环境变量 + 稳定入口 + 浏览器图标接管 + 转发器 + 系统代理。"""
    steps: list[str] = []
    bad: list[str] = []
    for name, fn in (("env", write_env), ("entry", install_entry),
                     ("desktop", install_desktop), ("forward", start_forward)):
        o = fn()
        steps.append(o.message) if o.ok else bad.append(o.message)
    from . import sysproxy
    s = sysproxy.on()
    if s.ok:
        steps.append(s.message)
    else:                                   # 没有 GNOME schema 不算失败：环境变量通路仍然成立
        steps.append(f"系统代理跳过（{s.message}）")
    _write_state(True, "off" if bad else "forward")
    steps.append("用法：开浏览器用 `proxy chrome` / `proxy firefox`，或直接点图标（已接管）")
    return Outcome(not bad, "已开启", "；".join(steps) + (("\n⚠️ " + "；".join(bad)) if bad else ""))


def off() -> Outcome:
    from . import sysproxy
    steps = [write_env(mode="off").message, stop_forward().message, sysproxy.off().message]
    _write_state(False, "off")
    return Outcome(True, "已关闭", "；".join(steps) +
                   "\n浏览器图标仍归我们管，但检测到端口关着会**自动直连**，不用改回去"
                   "\n提示：当前终端的已导出变量需重开终端才消失（或手动 unset）")


def status() -> dict:
    from . import tunnel
    cfg = config.load()
    f = paths.env_sh()
    pids = []
    pidf = paths.state_root() / "forward.pid"
    try:
        if pidf.exists():
            pid = int(pidf.read_text().strip() or 0)
            os.kill(pid, 0)
            pids.append(pid)
    except (OSError, ValueError):
        pass
    return {
        "mode": cfg["mode"], "bind": f"{cfg['bind_host']}:{cfg['bind_port']}",
        "upstream": cfg["upstream"], "env_file": str(f), "env_exists": f.exists(),
        "entry": str(entry.wrapper_path()), "entry_exists": entry.wrapper_path().is_file(),
        "listening": tunnel.status()["listening"], "spawned_pid": pids or None,
    }
