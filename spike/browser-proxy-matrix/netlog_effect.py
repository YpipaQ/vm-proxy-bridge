#!/usr/bin/env python3
"""从 Chrome 的 netlog 里读出"它最终用了什么代理"。

netlog 是浏览器自己记的账：每次代理配置生效都会留一条 PROXY_CONFIG_CHANGED，
带着 new_config（系统代理/PAC/命令行/直连都在这里现形）。比"数连接数"直接。

注意：浏览器被强杀时 netlog 会是**截断的半个 JSON**，所以用容错读取：
只把 constants 和 events 数组里"能解出来的完整事件"读进来，不追求整文件合法。

用法：
  netlog_effect.py <netlog.json> [--host HOST] [--json] [--dump-raw]
"""
from __future__ import annotations

import argparse
import json
import re
import sys


def _load_tolerant(path: str) -> dict:
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    dec = json.JSONDecoder()
    consts: dict = {}
    m = re.search(r'"constants"\s*:\s*\{', text)
    if m:
        try:
            consts, _ = dec.raw_decode(text, m.end() - 1)
        except ValueError:
            consts = {}
    events: list = []
    m = re.search(r'"events"\s*:\s*\[', text)
    if m:
        i, n = m.end(), len(text)
        while i < n:
            while i < n and text[i] in " \t\r\n,":
                i += 1
            if i >= n or text[i] == "]":
                break
            try:
                ev, j = dec.raw_decode(text, i)
            except ValueError:
                break  # 截断处，丢掉半条
            events.append(ev)
            i = j
    return {"constants": consts, "events": events, "truncated": not text.rstrip().endswith("}")}


def _type_names(consts: dict) -> dict[int, str]:
    out: dict[int, str] = {}
    for group in ("logEventTypes", "logSourceType"):
        for name, val in (consts.get(group) or {}).items():
            if isinstance(val, int):
                out.setdefault(val, name)
    return out


def _events(doc: dict):
    for ev in doc.get("events") or []:
        if isinstance(ev, dict):
            yield ev
        elif isinstance(ev, list) and len(ev) >= 6:
            yield {"type": ev[0], "time": ev[1], "phase": ev[2], "source": ev[3],
                   "id": ev[4], "params": ev[5]}


def summarize(path: str, host: str | None = None, dump_raw: bool = False) -> dict:
    doc = _load_tolerant(path)
    names = _type_names(doc.get("constants") or {})
    proxy_names: dict[str, int] = {}
    configs: list = []
    host_mentions: dict[str, int] = {}
    dns_errors: list[int] = []
    for ev in _events(doc):
        name = names.get(ev.get("type"))
        if not name:
            continue
        params = ev.get("params")
        blob = json.dumps(params, ensure_ascii=False) if params is not None else ""
        if "PROXY" in name:
            proxy_names[name] = proxy_names.get(name, 0) + 1
            if name == "PROXY_CONFIG_CHANGED" and isinstance(params, dict):
                cfg = params.get("new_config") or {k: v for k, v in params.items()}
                if cfg and cfg not in configs:
                    configs.append(cfg)
        if name.startswith("HOST_RESOLVER") and isinstance(params, dict):
            if isinstance(params.get("net_error"), int) and params["net_error"] != 0:
                dns_errors.append(params["net_error"])
        if host and host in blob:
            host_mentions[name] = host_mentions.get(name, 0) + 1
            if dump_raw:
                print(f"[{name}] {blob[:400]}")
    return {
        "netlog": path,
        "truncated": doc.get("truncated", False),
        "events": len(doc.get("events") or []),
        "proxy_events": proxy_names,
        "configs": configs,
        "host": host,
        "host_events": host_mentions,
        "host_requested": sum(host_mentions.values()),
        "dns_errors": dns_errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("netlog")
    ap.add_argument("--host", default=None, help="关心的目标主机（用于确认'确实发起了请求'）")
    ap.add_argument("--dump-raw", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    s = summarize(args.netlog, args.host, args.dump_raw)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    print(f"事件 {s['events']} 条{'（文件截断，已容错读取）' if s['truncated'] else ''}")
    print(f"代理配置生效记录 {s['configs']}")
    print(f"含 {s['host']} 的事件: {s['host_events']}")
    if s["dns_errors"]:
        print(f"DNS 失败码: {s['dns_errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
