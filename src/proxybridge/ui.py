"""主界面（CustomTkinter → 标准库 tkinter 降级）。**只调 `ctl`，绝不自己写文件**。

设计口径（2026-10-01 重做）：界面只回答三个问题 ——
    ① 桥现在是开是关？② 怎么把浏览器送进桥？③ 出问题看哪里？
所以顶部是**一行状态**（转发器 / 系统代理 / 浏览器 / 图标接管），中间是**按钮**，
底部才是日志。上一版把按钮排成"总开关：开 / 总开关：关"两个并列按钮、日志刷屏，
既看不出状态也没法用 —— 那版已作废。
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext

from . import ctl, paths

try:                                                     # 可选依赖（vendor/wheels 里）
    import customtkinter as ctk
    _HAS_CTK = True
except Exception:                                        # noqa: BLE001
    ctk = None
    _HAS_CTK = False

POLL_MS = 4000


class App:
    """状态模型 + 命令队列：所有动作串行执行，连点不会叠命令。"""

    def __init__(self, root) -> None:
        self.root = root
        self.busy = False
        self.queue: list[str] = []
        self.snapshot: dict = {}
        self.log_view = None
        self.status_labels: dict[str, object] = {}
        self.events: list[str] = []          # 界面内的操作回执（刷新时不会被日志覆盖）
        self._build()
        self._tick()

    # ---------------- 小工具 ----------------
    def _mk_button(self, parent, text, action, danger=False, width=132):
        cmd = (lambda: self.enqueue(action))             # noqa: E731
        if _HAS_CTK:
            kw = {"fg_color": "#b3261e", "hover_color": "#8c1d18"} if danger else {}
            return ctk.CTkButton(parent, text=text, command=cmd, width=width, **kw)
        return tk.Button(parent, text=text, command=cmd, width=16)

    def _mk_label(self, parent, text, **kw):
        if _HAS_CTK:
            return ctk.CTkLabel(parent, text=text, anchor="w", justify="left", **kw)
        return tk.Label(parent, text=text, anchor="w", justify="left", **kw)

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        root = self.root
        root.title("proxy-bridge")
        root.geometry("740x640")
        root.minsize(640, 520)

        head = ctk.CTkFrame(root) if _HAS_CTK else tk.Frame(root)
        head.pack(fill="x", padx=12, pady=(12, 6))
        self.header = self._mk_label(head, "读取中…", font=(None, 13) if _HAS_CTK else None)
        self.header.pack(fill="x", padx=10, pady=10)

        # ① 开关
        box1 = ctk.CTkFrame(root) if _HAS_CTK else tk.LabelFrame(root, text=" 桥开关 ")
        box1.pack(fill="x", padx=12, pady=6)
        self._mk_button(box1, "一键开启（转发器＋系统代理）", "on").pack(
            side="left", padx=8, pady=8, fill="x", expand=True)
        self._mk_button(box1, "关闭", "off", danger=True, width=90).pack(
            side="left", padx=8, pady=8)

        # ② 浏览器（日常就点这里）
        box2 = ctk.CTkFrame(root) if _HAS_CTK else tk.LabelFrame(root, text=" 浏览器（走桥） ")
        box2.pack(fill="x", padx=12, pady=6)
        self._mk_button(box2, "打开 Chrome", "open_chrome").pack(
            side="left", padx=8, pady=8, fill="x", expand=True)
        self._mk_button(box2, "打开 Firefox", "open_firefox").pack(
            side="left", padx=8, pady=8, fill="x", expand=True)
        self._mk_button(box2, "接管菜单图标", "desktop_on", width=130).pack(
            side="left", padx=8, pady=8)

        # ③ 其它
        box3 = ctk.CTkFrame(root) if _HAS_CTK else tk.LabelFrame(root, text=" 其它 ")
        box3.pack(fill="x", padx=12, pady=6)
        for text, action in (("系统代理 开", "sysproxy_on"), ("系统代理 关", "sysproxy_off"),
                             ("撤销图标接管", "desktop_off"), ("自检 doctor", "doctor"),
                             ("排查包", "support_bundle"), ("卸载", "uninstall")):
            self._mk_button(box3, text, action,
                            danger=action == "uninstall", width=104).pack(
                side="left", padx=6, pady=8)

        # ④ 日志（先占底部按钮条，再让日志吃剩余空间 —— 否则日志会盖住按钮）
        bar = ctk.CTkFrame(root) if _HAS_CTK else tk.Frame(root)
        bar.pack(side="bottom", fill="x", padx=12, pady=(4, 12))
        self._mk_button(bar, "刷新状态", "refresh", width=110).pack(side="right", padx=6)
        self._mk_label(bar, "日志：上半＝桥上真实连接，下半＝你的操作结果").pack(side="left", padx=6)

        mid = ctk.CTkFrame(root) if _HAS_CTK else tk.Frame(root)
        mid.pack(side="top", fill="both", expand=True, padx=12, pady=(6, 0))
        if _HAS_CTK:
            self.log_view = ctk.CTkTextbox(mid, wrap="none", font=("monospace", 11))
        else:
            self.log_view = scrolledtext.ScrolledText(mid, height=10, wrap="none")
        self.log_view.pack(fill="both", expand=True)
        try:
            self.log_view.configure(state="disabled")
        except Exception:                                # noqa: BLE001
            pass

    # ---------------- 状态 ----------------
    def refresh(self) -> None:
        try:
            self.snapshot = ctl.snapshot()
        except Exception as exc:                          # noqa: BLE001 —— GUI 不得因探测失败崩掉
            self.header.configure(text=f"状态读取失败：{exc}")
            return
        self.header.configure(text=self._headline(self.snapshot))
        self._load_log()

    @staticmethod
    def _headline(s: dict) -> str:
        pw, sp = s["power"], s["sysproxy"]
        on = pw["listening"]
        mode = str(sp.get("mode", "?")).strip("'\"")
        if mode == "manual":
            host = str(sp.get("http_host", "?")).strip("'")
            port = str(sp.get("http_port", "?")).strip("'")
            sysline = f"系统代理  已指向 {host}:{port}"
        else:
            sysline = f"系统代理  未设置（mode={mode}）"
        browsers = s.get("browsers") or {}
        bline = " · ".join(f"{'Chrome' if k == 'chrome' else 'Firefox'} "
                           f"{'✓' if v else '✗ 未安装'}" for k, v in browsers.items())
        taken = [d for d in (s.get("desktop") or []) if d.get("ours")]
        tline = f"已接管 {len(taken)} 个" if taken else "未接管（点图标会直连）"
        conf = "正常" if s.get("config_ok", True) else f"错误：{s.get('config_error', '')}"
        head = (f"{'● 桥已开启' if on else '○ 桥未开启'}\n"
                f"转发器    {'运行中' if on else '未运行'}  {pw['bind']} → {pw['upstream']}\n"
                f"{sysline}\n"
                f"浏览器    {bline}\n"
                f"图标      {tline}\n"
                f"配置      {conf}")
        if s.get("errors"):
            head += "\n⚠️ " + "；".join(s["errors"][:2])
        return head

    def _load_log(self) -> None:
        if self.log_view is None:
            return
        rows = ["—— 桥上最近的连接（forward.log，有这些就说明浏览器真的在走桥）——"]
        conns = self._forward_tail()
        rows += conns or ["（还没有连接经过：浏览器还没走桥）"]
        rows += ["", "—— 最近操作 ——"]
        rows += self.events[-12:] or ["（还没有操作）"]
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        self.log_view.insert("end", "\n".join(rows) + "\n")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    @staticmethod
    def _forward_tail(n: int = 22) -> list[str]:
        """forward.log 里最后 n 条真实连接（只挑 CONN 行；文件没有 ts，只报事实）。"""
        f = paths.logs_dir() / "forward.log"
        try:
            lines = [ln for ln in f.read_text("utf-8", errors="replace").splitlines()
                     if ln.startswith("CONN")]
        except OSError:
            return []
        return lines[-n:]

    def _tick(self) -> None:
        """定时只读刷新（不写盘）；窗口销毁后 after 会随之失效。"""
        try:
            self.refresh()
        except Exception:                                 # noqa: BLE001
            pass
        self.root.after(POLL_MS, self._tick)

    # ---------------- 命令队列（串行） ----------------
    def enqueue(self, action: str) -> None:
        if action == "refresh":
            self.refresh()
            return
        if self.busy:
            return                                        # 忙时忽略点击，不排队堆积
        self.queue.append(action)
        if len(self.queue) == 1:
            self._run_next()

    def _run_next(self) -> None:
        if not self.queue:
            self.busy = False
            return
        self.busy = True
        action = self.queue.pop(0)
        if action in ctl.DANGEROUS:
            if not messagebox.askyesno("确认", f"{action}：{ctl.DANGEROUS[action]}\n继续？"):
                self._after_action({"ok": False, "message": "已取消"})
                return
        threading.Thread(target=self._worker, args=(action,), daemon=True).start()

    def _worker(self, action: str) -> None:
        try:
            res = ctl.call(action)
        except Exception as exc:                          # noqa: BLE001
            res = {"ok": False, "message": f"异常：{exc}"}
        self.root.after(0, lambda: self._after_action(res))

    def _append_log(self, line: str) -> None:
        self.events.append(f"[{time.strftime('%H:%M:%S')}] {line}")
        self._load_log()

    def _after_action(self, res: dict) -> None:
        msg = res.get("message", "")
        if res.get("detail"):
            msg += "\n" + str(res["detail"])
        self._append_log(f"[{'OK' if res.get('ok') else 'FAIL'}] {msg}")
        if not res.get("ok"):
            messagebox.showwarning("proxy-bridge", msg[:800])
        self.refresh()
        self._run_next()


def build_window():
    """创建（不 mainloop）主窗口，供冒烟测试与 main() 复用。"""
    root = ctk.CTk() if _HAS_CTK else tk.Tk()
    app = App(root)
    return root, app


def main() -> int:
    try:
        root, _app = build_window()
    except tk.TclError as exc:
        print(f"无法创建窗口（无显示？）：{exc}")
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
