#!/usr/bin/env python3
"""动态实验：已经开着的浏览器，改系统代理后**要不要重启**才生效？

做法：起一个常驻 headless Chrome（带远程调试口），用 CDP 的 /json/new 反复开新标签页：
  1) 代理=none 时开一次  → 应当拿不到 marker（基线）
  2) 把系统代理改成探针 A  → 再开一次 → 命中说明"运行中就重读了配置"
  3) 改回 none            → 再开一次 → 不命中说明"关掉也立刻生效"，仍命中说明是缓存/未刷新
每次 URL 带不同 ?t= 参数，绕开浏览器缓存，保证"没命中"不是因为缓存命中。

用法：dynamic_reload.py [--probe-port 17897] [--cdp-port 9222] [--run-dir /tmp/bpm/dyn]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME = "/usr/bin/google-chrome"
TARGET = "http://proxy-test.invalid/m"


def sh(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def gs(mode: str, port: int | None = None) -> None:
    sh(["dconf", "reset", "-f", "/system/proxy/"])
    sh(["gsettings", "set", "org.gnome.system.proxy", "mode", mode])
    if mode == "manual" and port:
        sh(["gsettings", "set", "org.gnome.system.proxy.http", "host", "127.0.0.1"])
        sh(["gsettings", "set", "org.gnome.system.proxy.http", "port", str(port)])
        sh(["gsettings", "set", "org.gnome.system.proxy", "use-same-proxy", "true"])


def hit_count(log: Path) -> int:
    if not log.exists():
        return 0
    return sum(1 for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
               if " PROXY " in ln and TARGET.split("/m")[0] in ln)


def navigate(cdp_port: int, url: str) -> str:
    req = urllib.request.Request(f"http://127.0.0.1:{cdp_port}/json/new?{url}", method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return f"ok({resp.status})"
    except Exception as exc:  # noqa: BLE001
        return f"err({exc.__class__.__name__})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-port", type=int, default=17897)
    ap.add_argument("--origin-port", type=int, default=17898)
    ap.add_argument("--cdp-port", type=int, default=9222)
    ap.add_argument("--run-dir", default="/tmp/bpm/dyn")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    probe_log = run_dir / "probe.log"
    netlog = run_dir / "netlog.json"
    profile = run_dir / "profile"

    snapshot = sh(["dconf", "dump", "/system/proxy/"]).stdout
    probe = subprocess.Popen([sys.executable, str(HERE / "probe_server.py"),
                              "--proxy-port", str(args.probe_port),
                              "--origin-port", str(args.origin_port),
                              "--log", str(probe_log),
                              "--ready-file", str(run_dir / "ready")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    chrome = None
    steps: list[dict] = []
    try:
        for _ in range(80):
            if (run_dir / "ready").exists():
                break
            time.sleep(0.1)
        gs("none")
        env = dict(os.environ)
        env["XDG_CURRENT_DESKTOP"] = "GNOME"          # 与 proxy chrome 同款启动环境
        chrome = subprocess.Popen(
            [CHROME, "--headless", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={profile}", "--disable-gpu",
             f"--remote-debugging-port={args.cdp_port}",
             f"--log-net-log={netlog}", "--net-log-capture-mode=Default",
             "about:blank"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        # 等调试口就绪
        for _ in range(100):
            if chrome.poll() is not None:
                print("Chrome 提前退出 rc=", chrome.returncode)
                return 3
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.cdp_port}/json/version", timeout=2):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)

        def step(tag: str, url: str, expect_hit: bool, wait: float = 6.0) -> dict:
            before = hit_count(probe_log)
            note = navigate(args.cdp_port, url)
            t0 = time.time()
            while time.time() - t0 < wait:
                if hit_count(probe_log) > before:
                    break
                time.sleep(0.2)
            got = hit_count(probe_log) > before
            rec = {"step": tag, "expect_hit": expect_hit, "hit": got,
                   "seconds": round(time.time() - t0, 2), "nav": note}
            print(f"[{'命中' if got else '未命中'}] {tag:34s} 期望={'命中' if expect_hit else '不命中'} "
                  f"{rec['seconds']:5.2f}s {note}", flush=True)
            steps.append(rec)
            return rec

        step("1-代理未开-直连基线", f"{TARGET}?t=1", expect_hit=False)
        gs("manual", args.probe_port)
        time.sleep(2.0)
        step("2-运行中改 manual", f"{TARGET}?t=2", expect_hit=True)
        gs("none")
        time.sleep(2.0)
        step("3-运行中改回 none", f"{TARGET}?t=3", expect_hit=False)
    finally:
        for proc in (chrome, probe):
            if proc is not None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
        time.sleep(0.3)
        sh(["dconf", "reset", "-f", "/system/proxy/"])
        if snapshot.strip():
            subprocess.run(["dconf", "load", "/system/proxy/"], input=snapshot, text=True)
        restored = sh(["dconf", "dump", "/system/proxy/"]).stdout == snapshot

    nl = sh([sys.executable, str(HERE / "netlog_effect.py"), str(netlog), "--json"])
    try:
        nl_data = json.loads(nl.stdout)
    except Exception:  # noqa: BLE001
        nl_data = {}
    payload = {"steps": steps, "restored_gsettings": restored,
               "netlog_configs": nl_data.get("configs")}
    (run_dir / "dynamic.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"\nChrome 记下的代理配置变更序列: {json.dumps(nl_data.get('configs'), ensure_ascii=False)}")
    print(f"gsettings 已还原={restored}；结果 {run_dir / 'dynamic.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
