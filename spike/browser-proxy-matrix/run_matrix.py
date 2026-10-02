#!/usr/bin/env python3
"""浏览器代理矩阵实验台（数据驱动，规格在 cases.json）。

问题：浏览器到底"什么时候"读得到代理？
做法：每条交付通道指向**不同的探针端口**，于是"哪条通道赢了"可以从端口上看出来：
  A=17897 / B=17896 两个假代理各自记日志。目标主机是 .invalid（永远解析不了），
  所以"探针收到请求"是不可伪造的证据，"探针没收到"就是没走代理。

用法：
  run_matrix.py --cases cases.json [--only 前缀] [--out results.json] [--md results.md]
安全：
  * 运行前 dump /system/proxy/，无论成败都在 finally 里原样 load 回去；
  * 每个用例用一次性 --user-data-dir / -profile，绝不碰用户真实配置；
  * 浏览器用独立进程组启动，超时整组 kill。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME = "/usr/bin/google-chrome"
FIREFOX = "/usr/bin/firefox"

PORT_A = 17897          # 通道 A 假代理
PORT_B = 17896          # 通道 B 假代理
ORIGIN_A = 17898        # 源站/PAC（直连角色）
ORIGIN_B = 17900

PORTMAP = {"PROBE_A": str(PORT_A), "PROBE_B": str(PORT_B),
           "ORIGIN_A": str(ORIGIN_A), "ORIGIN_B": str(ORIGIN_B)}
LABEL = {PORT_A: "A", PORT_B: "B"}


def subst(text: str) -> str:
    for k, v in PORTMAP.items():
        text = text.replace(k, v)
    return text


def run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- 探针进程
class Probes:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.logs: dict[str, Path] = {"A": run_dir / "probe-A.log", "B": run_dir / "probe-B.log"}
        self.procs: list[subprocess.Popen] = []

    def start(self) -> None:
        for label, pport, oport in (("A", PORT_A, ORIGIN_A), ("B", PORT_B, ORIGIN_B)):
            ready = self.run_dir / f"ready-{label}"
            proc = subprocess.Popen(
                [sys.executable, str(HERE / "probe_server.py"),
                 "--proxy-port", str(pport), "--origin-port", str(oport),
                 "--log", str(self.logs[label]), "--ready-file", str(ready)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.procs.append(proc)
            deadline = time.time() + 8
            while time.time() < deadline and not ready.exists():
                if proc.poll() is not None:
                    raise RuntimeError(f"探针 {label} 启动失败 rc={proc.returncode}")
                time.sleep(0.05)
            if not ready.exists():
                raise RuntimeError(f"探针 {label} 未就绪")

    def stop(self) -> None:
        for proc in self.procs:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass

    def _lines(self, label: str) -> list[str]:
        path = self.logs[label]
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()

    def mark(self) -> dict[str, int]:
        """各日志当前行数（每个用例只看自己新增的行；必须逐日志记，不能求总和）。"""
        return {label: len(self._lines(label)) for label in self.logs}

    def hits(self, marks: dict[str, int], token: str) -> tuple[list[str], list[str]]:
        """返回 (代理命中[形如 'A GET http://x/m'], PAC/源站抓取)。"""
        proxied: list[str] = []
        origin: list[str] = []
        for label in self.logs:
            for ln in self._lines(label)[marks.get(label, 0):]:
                parts = ln.split()
                if len(parts) < 4:
                    continue
                # 行格式：<时间> <PROXY|ORIGIN> <METHOD> <TARGET> [from=...]
                kind, method, target = parts[1], parts[2], parts[3]
                if token not in ln:
                    continue
                if kind == "PROXY":
                    proxied.append(f"{label} {method} {target}")
                elif kind == "ORIGIN":
                    origin.append(f"{label} {method} {target}")
        return proxied, origin


# ---------------------------------------------------------------- gsettings
def gs_reset() -> None:
    run(["dconf", "reset", "-f", "/system/proxy/"])


def gs_apply(spec: dict) -> None:
    gs_reset()
    for key, val in (spec or {}).items():
        if val is None:
            continue
        if key == "mode":
            run(["gsettings", "set", "org.gnome.system.proxy", "mode", subst(str(val))])
        elif key == "autoconfig_url":
            run(["gsettings", "set", "org.gnome.system.proxy", "autoconfig-url", subst(str(val))])
        elif key == "use_same_proxy":
            run(["gsettings", "set", "org.gnome.system.proxy", "use-same-proxy", str(bool(val)).lower()])
        elif key == "ignore_hosts":
            run(["gsettings", "set", "org.gnome.system.proxy", "ignore-hosts",
                 "[" + ",".join(f"'{x}'" for x in val) + "]"])
        elif "_" in key:
            proto, attr = key.split("_", 1)
            run(["gsettings", "set", f"org.gnome.system.proxy.{proto}", attr, subst(str(val))])
        else:
            raise SystemExit(f"未知 gsettings 键: {key}")


def gs_dump() -> str:
    return run(["dconf", "dump", "/system/proxy/"]).stdout


# ---------------------------------------------------------------- 浏览器
MINIMAL_ENV_KEYS = ("PATH", "HOME", "USER", "LOGNAME", "DISPLAY", "XAUTHORITY", "LANG", "TERM")

# 量具专用开关（不碰代理判定逻辑，只为了跑得快、日志干净）：
#   --disable-background-networking  关掉变化量/更新检查等后台请求，免得日志被 google.com 淹没
#   --host-resolver-rules=...~NOTFOUND  让 .invalid 立刻返回"解析不了"，
#       直连用例从 ~60 秒缩到 ~1.2 秒；走代理的请求本来就不解析目标主机，不受影响。
# cases.json 里设 "stock_flags": true 可关掉这两条，跑"原厂参数"对照。
HARNESS_FLAGS = ["--disable-background-networking",
                 "--host-resolver-rules=MAP proxy-test.invalid ~NOTFOUND"]


def build_env(case: dict) -> dict[str, str]:
    if case.get("env_base") == "minimal":
        env = {k: os.environ[k] for k in MINIMAL_ENV_KEYS if k in os.environ}
        env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    else:
        env = dict(os.environ)
    overrides = {**(case.get("desktop") or {}), **(case.get("env") or {})}
    for k, v in overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = subst(str(v))
    return env


def chrome_argv(case: dict, profile: Path, netlog: Path, url: str) -> list[str]:
    flags = [subst(f) for f in (case.get("flags") or [])]
    harness = [] if case.get("stock_flags") else list(HARNESS_FLAGS)
    return [CHROME, "--headless", "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={profile}", "--disable-gpu",
            f"--log-net-log={netlog}", "--net-log-capture-mode=Default",
            *harness, *flags, url]


NOISE_PREFS = {
    "browser.shell.checkDefaultBrowser": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "datareporting.policy.dataSubmissionEnabled": False,
    "toolkit.telemetry.enabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "browser.aboutwelcome.enabled": False,
    "network.dns.blockDotOnion": False,
    # 对应 Chrome 的 ~NOTFOUND：直连要解析目标主机，禁掉 DNS 就立刻失败（~1 秒），
    # 而走 HTTP 代理的请求本来不解析目标主机，所以不影响"是否用了代理"的判定。
    "network.dns.disabled": True,
    "network.dns.disablePrefetch": True,
}


def firefox_argv(case: dict, profile: Path, png: Path, url: str) -> list[str]:
    prefs = {**NOISE_PREFS, **(case.get("prefs") or {})}
    lines = ["// 矩阵实验临时 profile，勿复用"]
    for k, v in prefs.items():
        if isinstance(v, bool):
            js = "true" if v else "false"
        elif isinstance(v, str):
            js = json.dumps(subst(v))
        else:
            js = str(v)
        lines.append(f"user_pref({json.dumps(k)}, {js});")
    (profile / "user.js").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [FIREFOX, "--headless", "-no-remote", "-profile", str(profile),
            "--window-size=900,600", "--screenshot", str(png), url]


def launch_and_wait(argv: list[str], env: dict, timeout: float,
                    seen=None, hit_grace: float = 2.0,
                    out_path: Path | None = None, err_path: Path | None = None
                    ) -> tuple[str, str, str, float | None]:
    """跑浏览器直到自然退出；已命中探针还赖着不走的，等 hit_grace 秒后整组 kill。

    输出一律重定向到**文件**，不用管道：Chrome 的错误页 DOM 有一两百 KB，
    管道没人读就会写阻塞 —— 表现是"浏览器永远不退出"，第一次跑矩阵就栽在这上面。
    """
    fout = open(out_path, "w", encoding="utf-8", errors="replace") if out_path else subprocess.DEVNULL
    ferr = open(err_path, "w", encoding="utf-8", errors="replace") if err_path else subprocess.DEVNULL
    status = "exit"
    hit_at: float | None = None
    try:
        proc = subprocess.Popen(argv, env=env, stdout=fout, stderr=ferr,
                                start_new_session=True)
        t0 = time.time()
        while True:
            if proc.poll() is not None:
                status = "exit"
                break
            now = time.time()
            if hit_at is None and seen is not None and seen():
                hit_at = now
            if hit_at is not None and now - hit_at > hit_grace:
                status = "killed_after_hit"
                break
            if now - t0 > timeout:
                status = "timeout"
                break
            time.sleep(0.2)
        if status != "exit":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass
        proc.wait()
    finally:
        for fh in (fout, ferr):
            if hasattr(fh, "close"):
                fh.close()  # type: ignore[union-attr]
    out = out_path.read_text(encoding="utf-8", errors="replace") if out_path and out_path.exists() else ""
    err = err_path.read_text(encoding="utf-8", errors="replace") if err_path and err_path.exists() else ""
    return status, out, err, (round(hit_at - t0, 2) if hit_at else None)


def netlog_summary(path: Path, host: str) -> dict:
    if not path.exists():
        return {}
    proc = run([sys.executable, str(HERE / "netlog_effect.py"), str(path), "--host", host, "--json"])
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {}


# ---------------------------------------------------------------- 主流程
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(HERE / "cases.json"))
    ap.add_argument("--only", default=None, help="只跑 id 以该前缀开头的用例")
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", default=None)
    ap.add_argument("--timeout", type=float, default=12.0,
                    help="每个用例的硬上限；探针命中约 1.5 秒，直连立刻 DNS 失败，12 秒足够")
    ap.add_argument("--run-dir", default="/tmp/bpm/run")
    ap.add_argument("--keep", action="store_true", help="保留 profile（调试用）")
    args = ap.parse_args(argv)

    cases: list[dict] = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if c["id"].startswith(args.only)]
    if not cases:
        print("没有匹配的用例", file=sys.stderr)
        return 2

    run_dir = Path(args.run_dir)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    (run_dir / "profiles").mkdir(parents=True)
    (run_dir / "netlog").mkdir(parents=True)
    (run_dir / "out").mkdir(parents=True)

    snapshot = gs_dump()
    (run_dir / "gsettings.before.dump").write_text(snapshot, encoding="utf-8")
    probes = Probes(run_dir)
    probes.start()
    results: list[dict] = []
    try:
        for case in cases:
            cid = case["id"]
            browser = case.get("browser", "chrome")
            url = subst(case.get("url", "http://proxy-test.invalid/m"))
            token = case.get("watch", "proxy-test.invalid")
            gs_apply(case.get("gsettings") or {})
            env = build_env(case)
            mark = probes.mark()
            t0 = time.time()
            timeout = float(case.get("timeout", args.timeout))

            def seen(mark=mark, token=token) -> bool:
                return bool(probes.hits(mark, token)[0])

            if browser == "chrome":
                profile = run_dir / "profiles" / cid
                netlog = run_dir / "netlog" / f"{cid}.json"
                status, out, err, hit_s = launch_and_wait(
                    chrome_argv(case, profile, netlog, url), env, timeout, seen=seen,
                    out_path=run_dir / "out" / f"{cid}.stdout",
                    err_path=run_dir / "out" / f"{cid}.stderr")
                marker = "PROXYBRIDGE_PROXIED_OK" in out
                dom_host = token in out
                errs = sorted(set(re.findall(r"ERR_[A-Z_]+", out)))
                nl = netlog_summary(netlog, token)
            else:
                profile = run_dir / "profiles" / cid
                profile.mkdir(parents=True, exist_ok=True)
                png = run_dir / f"{cid}.png"
                status, out, err, hit_s = launch_and_wait(
                    firefox_argv(case, profile, png, url), env, timeout,
                    out_path=run_dir / "out" / f"{cid}.stdout",
                    err_path=run_dir / "out" / f"{cid}.stderr")
                marker, dom_host, errs, nl = None, None, [], {}
            dt = round(time.time() - t0, 1)
            proxied, origin = probes.hits(mark, token)
            channels = sorted({h.split()[0] for h in proxied})
            if status == "timeout" and not proxied:
                measured = "timeout"
            elif proxied:
                measured = "+".join(channels)
            else:
                measured = "direct"
            expect = case.get("expect", "any")
            if expect == "any":
                verdict = "INFO"
            elif expect == "proxied":
                verdict = "PASS" if proxied else "FAIL"
            else:
                verdict = "PASS" if not proxied else "FAIL"
            results.append({
                "id": cid, "browser": browser, "expect": expect, "measured": measured,
                "verdict": verdict, "channels": channels, "hits": proxied[:6],
                "pac_fetch": bool(origin), "marker_in_output": marker,
                "dom_mentions_host": dom_host, "dom_error_codes": errs,
                "status": status, "seconds": dt,
                "hit_latency_s": hit_s,
                "netlog_configs": (nl or {}).get("configs"),
                "netlog_host_requested": (nl or {}).get("host_requested"),
                "netlog_dns_errors": (nl or {}).get("dns_errors"),
                "netlog_truncated": (nl or {}).get("truncated"),
                "note": case.get("note", ""),
            })
            flag = {"PASS": "ok  ", "FAIL": "FAIL", "INFO": "--  "}[verdict]
            print(f"[{flag}] {cid:34s} expect={expect:8s} measured={measured:8s} "
                  f"{'marker ' if marker else ''}{dt:5.1f}s", flush=True)
            if not args.keep:
                shutil.rmtree(profile, ignore_errors=True)
    finally:
        probes.stop()
        gs_reset()
        if snapshot.strip():
            run(["dconf", "load", "/system/proxy/"], input=snapshot)
        after = gs_dump()
        (run_dir / "gsettings.after.dump").write_text(after, encoding="utf-8")
        restored = after == snapshot

    payload = {"cases_file": str(args.cases), "restored_gsettings": restored,
               "probe_ports": {"A": PORT_A, "B": PORT_B, "origin_A": ORIGIN_A},
               "results": results}
    out_path = Path(args.out) if args.out else run_dir / "results.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    npass = sum(1 for r in results if r["verdict"] == "PASS")
    nfail = sum(1 for r in results if r["verdict"] == "FAIL")
    print(f"\n合计 {len(results)} 例：PASS {npass} / FAIL {nfail} / INFO "
          f"{len(results) - npass - nfail}；gsettings 已还原={restored}")
    print(f"结果: {out_path}")

    if args.md:
        lines = ["| 用例 | 浏览器 | 预期 | 实测 | 判定 | 说明 |", "| --- | --- | --- | --- | --- | --- |"]
        for r in results:
            lines.append(f"| `{r['id']}` | {r['browser']} | {r['expect']} | **{r['measured']}** | "
                         f"{r['verdict']} | {r['note']} |")
        Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"表格: {args.md}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
