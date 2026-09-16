#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""proxy-ui - VM 网络代理桥界面

双模式：
  * 环境变量模式（旧）  —— 新终端直接用宿主代理
  * 本地转发模式（新）  —— 本地回环端口映射到宿主代理，兼容不读环境变量的程序

界面功能：模式切换 / 开关 / 连通测试（带明确确认）/ 实时日志 / 转发器状态
"""
import os
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

PROXY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy")
LOG_FILE = os.path.expanduser("~/.proxy.log")
ENV_FILE = os.path.expanduser("~/.proxy_env")
CONF_FILE = os.path.expanduser("~/.proxy.conf")
PID_FILE = os.path.expanduser("~/.proxy-forward.pid")

DEFAULTS = {
    "PROXY_HOST": "192.168.18.1:7897",
    "BIND_HOST": "127.0.0.1",
    "BIND_PORT": "7897",
    "TEST_URL": "https://github.com",
    "MODE": "env",
}

# ---- 配色（浅色主题） ----
BG = "#f7f7f9"
CARD = "#ffffff"
FG = "#1f2328"
MUTED = "#6b7280"
OK = "#137333"
WARN = "#b45309"
ERR = "#b3261e"
ACCENT = "#2563eb"
LOG_BG = "#1e1e24"
LOG_FG = "#dcdcdc"
LOG_OK = "#4ade80"
LOG_WARN = "#fbbf24"
LOG_ERR = "#f87171"


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def load_conf():
    conf = dict(DEFAULTS)
    if os.path.exists(CONF_FILE):
        try:
            txt = open(CONF_FILE, encoding="utf-8", errors="ignore").read()
        except OSError:
            return conf
        for key in conf:
            m = re.search(rf'^\s*{key}\s*=\s*"([^"]*)"', txt, re.M)
            if m:
                conf[key] = m.group(1)
                continue
            m = re.search(rf"^\s*{key}\s*=\s*('([^']*)'|[^\s#]+)", txt, re.M)
            if m:
                conf[key] = m.group(2) if m.group(2) else m.group(1).strip("'\"")
    return conf


def save_conf(conf):
    tmp = CONF_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# proxy-bridge config (used by the `proxy` CLI)\n")
        for k, v in conf.items():
            f.write(f'{k}="{v}"\n')
    os.replace(tmp, CONF_FILE)


def pid_alive(path):
    try:
        pid = int(open(path, encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return None


class App:
    def __init__(self, root):
        self.root = root
        root.title("网络代理桥 - VM")
        root.geometry("880x660")
        root.minsize(760, 560)
        root.configure(bg=BG)

        self._busy = False
        self._build_style()

        # ===== 顶部状态卡 =====
        head = tk.Frame(root, bg=CARD, highlightthickness=1,
                        highlightbackground="#e5e7eb")
        head.pack(fill="x", padx=10, pady=(10, 6))
        self.status_dot = tk.Label(head, text="●", font=("Sans", 16), bg=CARD, fg=MUTED)
        self.status_dot.pack(side="left", padx=(12, 6), pady=10)
        box = tk.Frame(head, bg=CARD)
        box.pack(side="left", fill="x", expand=True, pady=8)
        self.status = tk.Label(box, text="正在检测…", font=("Sans", 12, "bold"),
                               bg=CARD, fg=FG, anchor="w")
        self.status.pack(fill="x")
        self.sub = tk.Label(box, text="", font=("Sans", 9), bg=CARD, fg=MUTED, anchor="w")
        self.sub.pack(fill="x")
        self.fwd_badge = tk.Label(head, text="转发器：未运行", font=("Sans", 9),
                                  bg=CARD, fg=MUTED)
        self.fwd_badge.pack(side="right", padx=12)

        # ===== 配置卡 =====
        cfg = tk.LabelFrame(root, text=" 配置 ", bg=CARD, fg=FG, padx=10, pady=8,
                            font=("Sans", 10, "bold"), highlightthickness=1,
                            highlightbackground="#e5e7eb")
        cfg.pack(fill="x", padx=10, pady=6)
        conf = load_conf()

        tk.Label(cfg, text="上游代理", bg=CARD, fg=FG).grid(row=0, column=0, sticky="e", pady=3)
        self.host_var = tk.StringVar(value=conf["PROXY_HOST"])
        ttk.Entry(cfg, textvariable=self.host_var, width=22).grid(row=0, column=1, padx=6, sticky="w")

        tk.Label(cfg, text="本地监听", bg=CARD, fg=FG).grid(row=0, column=2, sticky="e", pady=3)
        self.bind_var = tk.StringVar(value=f'{conf["BIND_HOST"]}:{conf["BIND_PORT"]}')
        ttk.Entry(cfg, textvariable=self.bind_var, width=18).grid(row=0, column=3, padx=6, sticky="w")

        tk.Label(cfg, text="测试地址", bg=CARD, fg=FG).grid(row=0, column=4, sticky="e", pady=3)
        self.test_var = tk.StringVar(value=conf["TEST_URL"])
        ttk.Entry(cfg, textvariable=self.test_var, width=24).grid(row=0, column=5, padx=6, sticky="w")

        ttk.Button(cfg, text="保存配置", width=10, command=self.save_conf)\
            .grid(row=0, column=6, padx=6)

        tk.Label(cfg, text="本地监听仅用于「本地转发」模式；上游代理填宿主机地址（如 192.168.18.1:7897）",
                 bg=CARD, fg=MUTED, font=("Sans", 9), anchor="w")\
            .grid(row=1, column=0, columnspan=7, sticky="w", pady=(4, 0))

        # ===== 模式卡 =====
        modef = tk.LabelFrame(root, text=" 工作模式 ", bg=CARD, fg=FG, padx=10, pady=8,
                              font=("Sans", 10, "bold"), highlightthickness=1,
                              highlightbackground="#e5e7eb")
        modef.pack(fill="x", padx=10, pady=6)
        self.mode_var = tk.StringVar(value=conf.get("MODE", "env"))

        ttk.Radiobutton(modef, text="环境变量模式（旧）— 新终端直接使用宿主代理",
                        variable=self.mode_var, value="env",
                        command=self._mode_changed).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Radiobutton(modef, text="本地转发模式（新）— 本机端口转发到宿主代理，兼容不读环境变量的程序",
                        variable=self.mode_var, value="forward",
                        command=self._mode_changed).grid(row=1, column=0, sticky="w", pady=2)

        # ===== 操作卡 =====
        act = tk.Frame(root, bg=BG)
        act.pack(fill="x", padx=10, pady=(4, 6))
        self.btn_on = ttk.Button(act, text="开启代理", width=14, command=lambda: self._run("on"))
        self.btn_on.pack(side="left", padx=(0, 6))
        self.btn_off = ttk.Button(act, text="关闭代理", width=14, command=lambda: self._run("off"))
        self.btn_off.pack(side="left", padx=6)
        self.btn_test = ttk.Button(act, text="测试连通", width=14, command=lambda: self._run("test"))
        self.btn_test.pack(side="left", padx=6)
        ttk.Button(act, text="刷新状态", width=12, command=self.refresh).pack(side="left", padx=6)
        ttk.Button(act, text="清空日志", width=12, command=self.clear_log).pack(side="right")

        # ===== 日志卡 =====
        logf = tk.LabelFrame(root, text=" 运行日志（~/.proxy.log） ", bg=CARD, fg=FG,
                             padx=8, pady=6, font=("Sans", 10, "bold"),
                             highlightthickness=1, highlightbackground="#e5e7eb")
        logf.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.logbox = ScrolledText(logf, height=14, state="disabled", wrap="word",
                                   font=("TkFixedFont", 9), bg=LOG_BG, fg=LOG_FG,
                                   insertbackground=LOG_FG, relief="flat",
                                   highlightthickness=0)
        self.logbox.pack(fill="both", expand=True)
        # 日志着色：确认绿 / 警告黄 / 失败红
        self.logbox.tag_config("ok", foreground=LOG_OK)
        self.logbox.tag_config("warn", foreground=LOG_WARN)
        self.logbox.tag_config("err", foreground=LOG_ERR)
        self.logbox.tag_config("head", foreground=ACCENT)

        self._log_pos = 0
        self._sync_log_pos()
        self.refresh()
        self._tail()
        self._append(f"=== UI 启动 {now()} ===\n", "head")

    # ---------- style ----------
    def _build_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("TButton", padding=(8, 5), font=("Sans", 9))
        st.configure("TRadiobutton", background=CARD, font=("Sans", 9))
        st.configure("TEntry", padding=3)

    # ---------- log helpers ----------
    def _tag_for(self, line):
        if "CONFIRMED" in line or "✓" in line:
            return "ok"
        if "FAIL" in line or "✗" in line or "ERROR" in line or "FATAL" in line:
            return "err"
        if "WARN" in line:
            return "warn"
        return None

    def _append(self, text, tag=None):
        def _do():
            self.logbox.configure(state="normal")
            for line in text.splitlines(True):
                self.logbox.insert("end", line, tag or self._tag_for(line) or "")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.root.after(0, _do)

    def _sync_log_pos(self):
        try:
            self._log_pos = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0
        except OSError:
            self._log_pos = 0

    def _tail(self):
        try:
            if os.path.exists(LOG_FILE):
                size = os.path.getsize(LOG_FILE)
                if size < self._log_pos:
                    self._log_pos = 0
                if size > self._log_pos:
                    with open(LOG_FILE, encoding="utf-8", errors="ignore") as f:
                        f.seek(self._log_pos)
                        self._append(f.read())
                    self._log_pos = size
        except OSError:
            pass
        self.root.after(2000, self._tail)

    def clear_log(self):
        try:
            open(LOG_FILE, "w").close()
        except OSError:
            pass
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")
        self._sync_log_pos()
        self._append(f"[{now()}] 日志已清空（界面）\n", "head")

    # ---------- state ----------
    def _conf_now(self):
        conf = load_conf()
        conf["MODE"] = self.mode_var.get()
        return conf

    def refresh(self):
        conf = load_conf()
        mode = self.mode_var.get() or conf.get("MODE", "env")
        on = os.path.exists(ENV_FILE)
        pid = pid_alive(PID_FILE)

        if mode == "forward":
            if on and pid:
                self.status_dot.config(fg=OK)
                self.status.config(text=f"本地转发 ON → {conf['BIND_HOST']}:{conf['BIND_PORT']}  上游 {conf['PROXY_HOST']}",
                                   fg=OK)
                self.sub.config(text="已开启：本机程序通过 127.0.0.1 端口走宿主代理")
            elif on:
                self.status_dot.config(fg=WARN)
                self.status.config(text="环境变量已写入，但转发器未运行", fg=WARN)
                self.sub.config(text="点击「开启代理」重新拉起转发器")
            else:
                self.status_dot.config(fg=MUTED)
                self.status.config(text=f"本地转发 OFF（监听 {conf['BIND_HOST']}:{conf['BIND_PORT']}）", fg=MUTED)
                self.sub.config(text="关闭状态：直连网络")
        else:
            if on:
                self.status_dot.config(fg=OK)
                self.status.config(text=f"环境变量模式 ON → {conf['PROXY_HOST']}", fg=OK)
                self.sub.config(text="已开启：新开终端自动使用宿主代理")
            else:
                self.status_dot.config(fg=MUTED)
                self.status.config(text="环境变量模式 OFF（直连）", fg=MUTED)
                self.sub.config(text="关闭状态：直连网络")

        if pid:
            self.fwd_badge.config(text=f"转发器：运行中 (PID {pid})", fg=OK)
        else:
            self.fwd_badge.config(text="转发器：未运行", fg=MUTED)

    def _mode_changed(self):
        """切换模式：写入配置；若原模式处于开启状态则平滑切换"""
        mode = self.mode_var.get()
        conf = load_conf()
        conf["MODE"] = mode
        try:
            save_conf(conf)
        except OSError as exc:
            self._append(f"[{now()}] !! 模式保存失败：{exc}\n", "err")
            return
        self._append(f"[{now()}] 模式切换为：{mode}\n", "head")
        # 切换时清掉旧模式残留，避免两套同时生效
        self._run("off", quiet=True, then=lambda: self.refresh())

    # ---------- actions ----------
    def save_conf(self):
        host = self.host_var.get().strip()
        bind = self.bind_var.get().strip()
        url = self.test_var.get().strip()
        if not host or ":" not in host:
            self._append(f"[{now()}] !! 上游代理地址格式应为 IP:端口，未保存\n", "err")
            return
        if not bind or ":" not in bind:
            self._append(f"[{now()}] !! 本地监听地址格式应为 IP:端口，未保存\n", "err")
            return
        bh, _, bp = bind.rpartition(":")
        bh = bh or "127.0.0.1"
        # 安全闸门：只允许回环绑定（防开放代理暴露到局域网）
        if bh not in ("127.0.0.1", "localhost", "::1"):
            self._append(f"[{now()}] !! 本地监听只允许回环地址（127.0.0.1 / localhost / ::1）；"
                         f"绑定 {bh} 会把无鉴权端口暴露到局域网，已拒绝\n", "err")
            return
        conf = load_conf()
        conf.update({
            "PROXY_HOST": host,
            "BIND_HOST": bh,
            "BIND_PORT": bp,
            "TEST_URL": url or DEFAULTS["TEST_URL"],
            "MODE": self.mode_var.get(),
        })
        try:
            save_conf(conf)
        except OSError as exc:
            self._append(f"[{now()}] !! 保存失败：{exc}\n", "err")
            return
        self._append(f"[{now()}] 配置已保存：上游 {host}｜本地 {bind}｜模式 {conf['MODE']}\n", "head")
        if os.path.exists(ENV_FILE):
            self._run("on", quiet=True)
        else:
            self.refresh()

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_on, self.btn_off, self.btn_test):
            b.config(state=state)

    def _run(self, arg, quiet=False, then=None):
        if self._busy:
            return
        self._set_busy(True)

        def work():
            if not quiet:
                self._append(f"--- proxy {arg} ({now()}) ---\n", "head")
            try:
                r = subprocess.run([PROXY, arg], capture_output=True, text=True, timeout=120)
                out = (r.stdout + r.stderr).strip()
            except subprocess.TimeoutExpired:
                out = "ERROR: 执行超时（120s）"
            except Exception as exc:  # noqa: BLE001
                out = f"ERROR: {exc}"
            if out:
                self._append(out + "\n\n")
            self.root.after(0, self.refresh)
            self.root.after(0, lambda: self._set_busy(False))
            if then:
                self.root.after(0, then)

        threading.Thread(target=work, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
