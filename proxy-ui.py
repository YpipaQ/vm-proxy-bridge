#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""proxy-ui - VM 网络代理桥界面（桥接地址可配置 + 开关 + 测试 + 日志）"""
import os
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

PROXY = "/usr/local/bin/proxy"
LOG_FILE = os.path.expanduser("~/.proxy.log")
ENV_FILE = os.path.expanduser("~/.proxy_env")
CONF_FILE = os.path.expanduser("~/.proxy.conf")

DEFAULTS = {
    "PROXY_HOST": "192.168.18.1:7897",
    "TEST_URL": "https://github.com",
}


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
            if not m:
                m = re.search(rf"^\s*{key}\s*=\s*('([^']*)'|[^\s#]+)", txt, re.M)
                if m:
                    conf[key] = m.group(2) if m.group(2) else m.group(1).strip("'\"")
                    continue
            if m:
                conf[key] = m.group(1)
    return conf


def save_conf(conf):
    lines = [f'{k}="{v}"' for k, v in conf.items()]
    tmp = CONF_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# proxy-bridge config (used by /usr/local/bin/proxy)\n")
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, CONF_FILE)


class App:
    def __init__(self, root):
        self.root = root
        root.title("网络代理桥 - VM")
        root.geometry("600x500")
        root.minsize(520, 420)

        self.status = tk.Label(root, text="...", font=("Sans", 13, "bold"), pady=6)
        self.status.pack(fill="x")

        # ---- settings row ----
        conf = load_conf()
        cfg = tk.LabelFrame(root, text="桥接配置", padx=6, pady=4)
        cfg.pack(fill="x", padx=8)
        tk.Label(cfg, text="代理地址").grid(row=0, column=0, sticky="e")
        self.host_var = tk.StringVar(value=conf["PROXY_HOST"])
        tk.Entry(cfg, textvariable=self.host_var, width=24).grid(row=0, column=1, padx=4)
        tk.Label(cfg, text="测试地址").grid(row=0, column=2, sticky="e")
        self.test_var = tk.StringVar(value=conf["TEST_URL"])
        tk.Entry(cfg, textvariable=self.test_var, width=24).grid(row=0, column=3, padx=4)
        tk.Button(cfg, text="保存配置", width=10, command=self.save_conf).grid(row=0, column=4, padx=4)
        tk.Label(cfg, text="保存后：新开终端生效；若当前为 ON 会自动按新地址重生成", fg="#777",
                 anchor="w").grid(row=1, column=0, columnspan=5, sticky="w")

        # ---- action buttons ----
        btns = tk.Frame(root)
        btns.pack(pady=4)
        for text, cmd in (("开启代理", self.on), ("关闭代理", self.off), ("测试连通", self.test)):
            tk.Button(btns, text=text, width=12, command=cmd).pack(side="left", padx=6)

        tk.Label(root, text="日志（~/.proxy.log）", anchor="w", fg="#666").pack(fill="x", padx=8)
        self.logbox = ScrolledText(root, height=14, state="disabled",
                                   font=("TkFixedFont", 9), bg="#111", fg="#ddd")
        self.logbox.pack(fill="both", expand=True, padx=8, pady=(2, 8))

        self._log_pos = 0
        self.refresh()
        self._tail()
        self._append(f"=== UI 启动 {now()} ===\n")

    # ---------- helpers ----------
    def _append(self, text):
        def _do():
            self.logbox.configure(state="normal")
            self.logbox.insert("end", text)
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.root.after(0, _do)

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
        self.root.after(3000, self._tail)

    def refresh(self):
        conf = load_conf()
        on = os.path.exists(ENV_FILE)
        if on:
            self.status.config(text=f"当前状态：代理 ON → {conf['PROXY_HOST']}（新开终端生效）",
                               fg="#1a7f37")
        else:
            self.status.config(text="当前状态：直连 OFF", fg="#8a8a8a")

    def _run(self, arg):
        def work():
            self._append(f"--- proxy {arg} ({now()}) ---\n")
            try:
                r = subprocess.run([PROXY, arg], capture_output=True, text=True, timeout=90)
                out = (r.stdout + r.stderr).strip()
            except Exception as exc:  # noqa: BLE001
                out = f"ERROR: {exc}"
            self._append((out or "(no output)") + "\n\n")
            self.root.after(0, self.refresh)
        threading.Thread(target=work, daemon=True).start()

    # ---------- buttons ----------
    def save_conf(self):
        host = self.host_var.get().strip()
        url = self.test_var.get().strip()
        if not host or ":" not in host:
            self._append(f"[{now()}] !! 代理地址格式应为 IP:端口，未保存\n")
            return
        conf = {"PROXY_HOST": host, "TEST_URL": url or DEFAULTS["TEST_URL"]}
        try:
            save_conf(conf)
        except OSError as exc:
            self._append(f"[{now()}] !! 保存失败：{exc}\n")
            return
        self._append(f"[{now()}] 配置已保存：{conf}\n")
        if os.path.exists(ENV_FILE):  # 当前 ON → 按新地址重新生成 env
            self._run("on")
        else:
            self.refresh()

    def on(self):
        self._run("on")

    def off(self):
        self._run("off")

    def test(self):
        self._run("test")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
