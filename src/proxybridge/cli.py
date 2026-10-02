"""命令行入口：只做参数解析与输出，不做副作用（副作用都在 core 模块）。"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, paths
from .exitcodes import FAIL, OK, USAGE


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="proxy", description="proxy-bridge v2")
    p.add_argument("--version", action="version", version=f"proxybridge {__version__}")
    sub = p.add_subparsers(dest="verb")

    s = sub.add_parser("version", help="打印版本与路径（--json 输出结构化）")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("paths", help="打印 XDG 路径（P0 骨架自检用）")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("status", help="只读状态")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("doctor", help="只读体检；退出码 0 通过 / 2 有失败项")
    s.add_argument("--json", action="store_true")

    sub.add_parser("on", help="一键开启：env + 入口 + 接管浏览器图标 + 转发器 + 系统代理")
    sub.add_parser("off", help="一键关闭：停转发器 + 清 env + 还原系统代理")

    un = sub.add_parser("uninstall", help="按清单逆序还原所有集成点（--purge 连数据一起删）")
    un.add_argument("--purge", action="store_true")
    un.add_argument("--dry-run", action="store_true")
    sub.add_parser("support-bundle", help="打包脱敏排查包")
    mg = sub.add_parser("migrate", help="v1 → v2 迁移")
    mg.add_argument("--dry-run", action="store_true")
    mg.add_argument("--rollback", action="store_true")

    mn = sub.add_parser("manifest", help="安装清单")
    mn.add_argument("--json", action="store_true")

    sub.add_parser("ui", help="Tk 主界面（只调 core，不自己写文件）")

    # 下面三个在 main() 里被**提前拦截**（浏览器自己的参数不能被 argparse 吃掉）；
    # 这里登记只为 `proxy --help` 能列出来。
    sub.add_parser("chrome", help="启动 Chrome 走桥（直通参数，不等待退出）")
    sub.add_parser("firefox", help="启动 Firefox 走桥（直通参数，不等待退出）")
    sub.add_parser("browser", help="浏览器通路：`proxy browser status`")

    dk = sub.add_parser("desktop", help="浏览器图标接管（用户级 .desktop 覆盖，可撤销）")
    dks = dk.add_subparsers(dest="action")
    dks.add_parser("on"); dks.add_parser("off"); dks.add_parser("status")

    sp = sub.add_parser("sysproxy", help="系统代理（GNOME gsettings 通道；可逆）")
    sps = sp.add_subparsers(dest="action")
    sps.add_parser("on"); sps.add_parser("off"); sps.add_parser("status")

    en = sub.add_parser("entry", help="稳定入口 ~/.local/bin/proxy")
    ens = en.add_subparsers(dest="action")
    ens.add_parser("install"); ens.add_parser("uninstall"); ens.add_parser("status")

    ff = sub.add_parser("forward", help="TCP 转发器")
    fs = ff.add_subparsers(dest="action")
    fs.add_parser("run", help="前台运行")
    fs.add_parser("status", help="转发器状态（只读）")
    fs.add_parser("tail", help="跟随 forward.log")
    return p


def _browser_usage() -> str:
    return ("用法：proxy chrome [chrome 参数...] ／ proxy firefox [firefox 参数...]／ proxy browser status\n"
            "说明：带代理变量启动浏览器（**不等待退出**）。转发器没在跑时自动直连。")


def _browser_main(verb: str, rest: list[str]) -> int:
    """`proxy chrome|firefox|browser ...`：**不经过 argparse**（否则浏览器自己的 --xxx 会被吞）。"""
    from . import browser

    if any(a in ("-h", "--help") for a in rest):
        print(_browser_usage())
        return OK
    if verb == "browser":
        if not rest or rest[0] == "status":
            got = browser.available()
            for kind, label in browser.LABELS.items():
                print(f"[proxy] {label}：{got.get(kind) or '未安装'}")
            return OK
        kind, rest = rest[0], rest[1:]
    else:
        kind = verb
    o = browser.launch(kind, rest)
    print(f"[proxy] {o.message}")
    for line in o.detail.splitlines():
        print(f"[proxy] {line}")
    return OK if o.ok else FAIL


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] in {"chrome", "firefox", "browser"}:   # 直通，不走 argparse
        return _browser_main(raw[0], raw[1:])
    args = build_parser().parse_args(raw)
    _log_event(args.verb, argv)
    if args.verb == "version":
        info = {"version": __version__, "install_path": str(paths.app_root())}
        if args.json:
            print(json.dumps(info, ensure_ascii=False))
        else:
            print(f"proxybridge {__version__}")
        return OK
    if args.verb == "paths":
        info = {
            "config": str(paths.config_root()), "data": str(paths.data_root()),
            "state": str(paths.state_root()), "cache": str(paths.cache_root()),
            "logs": str(paths.logs_dir()),
        }
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            for k, v in info.items():
                print(f"{k:<11} {v}")
        return OK
    if args.verb == "status":
        from . import state
        st = state.read_state()
        if args.json:
            print(json.dumps(st, ensure_ascii=False, indent=2))
        else:
            print(f"desired_on={st['desired_on']} actual={st['actual']}")
        return OK
    if args.verb == "doctor":
        from . import doctor
        checks, code = doctor.run()
        if args.json:
            print(json.dumps([{"level": c.level, "title": c.title, "detail": c.detail}
                              for c in checks], ensure_ascii=False, indent=2))
        else:
            print(doctor.render(checks))
        return code
    if args.verb in {"on", "off"}:
        from . import power
        o = power.on() if args.verb == "on" else power.off()
        print(f"[proxy] {o.message}")
        for line in o.detail.splitlines():
            print(f"[proxy] {line}")
        return OK if o.ok else FAIL

    if args.verb == "forward":
        from . import tunnel
        act = getattr(args, "action", None)
        if act == "run":
            try:
                return tunnel.run()
            except tunnel.TunnelRefused as exc:
                print(f"[proxy] 拒绝启动：{exc}", file=sys.stderr)
                return FAIL
        if act == "status":
            st = tunnel.status()
            print(f"[proxy] 绑定 {st['bind']} -> 上游 {st['upstream']}："
                  f"{'listening' if st['listening'] else 'closed'}")
            print(f"[proxy] 计数器（本进程）：{st['counters']}")
            return OK
        if act == "tail":
            import subprocess as sp
            return sp.call(["tail", "-f", str(paths.logs_dir() / "forward.log")])
        print("用法：proxy forward {run|status|tail}"); return USAGE

    if args.verb == "uninstall":
        from . import uninstall as un
        if args.dry_run:
            m = __import__("proxybridge.manifest", fromlist=["Manifest"]).Manifest.load()
            print(f"[proxy] dry-run：清单里 {len(m.entries)} 项将被处理")
            for k, e in reversed(list(m.entries.items())):
                print(f"  {'还原' if e.existed_before else '删除'} {k}")
            return OK
        rep = un.run(purge=args.purge)
        for line in un.render(rep).splitlines():
            print(f"[proxy] {line}")
        return OK if rep.ok else FAIL

    if args.verb == "support-bundle":
        from . import support
        out = support.build()
        print(f"[proxy] 已生成脱敏排查包：{out}")
        print(f"[proxy] 大小 {out.stat().st_size} 字节；同目录保留最近 5 份")
        return OK

    if args.verb == "migrate":
        from . import migrate
        if args.rollback:
            pl = migrate.rollback()
            print("[proxy] 回滚完成：")
        else:
            pl = migrate.apply(dry_run=args.dry_run)
            print(f"[proxy] {'dry-run' if args.dry_run else '迁移完成'}：")
        print(pl.summary())
        return OK

    if args.verb == "manifest":
        from . import manifest as mf
        m = mf.Manifest.load()
        if args.json:
            print(json.dumps({k: vars(v) for k, v in m.entries.items()},
                             ensure_ascii=False, indent=2))
        else:
            print(f"[proxy] 清单：{len(m.entries)} 项（schema {m.schema}）")
            for k, e in m.entries.items():
                print(f"  [{'原存在' if e.existed_before else '原不存在'}] {k}")
        return OK

    if args.verb == "sysproxy":
        from . import sysproxy
        act = getattr(args, "action", None)
        if act == "on":
            o = sysproxy.on()
        elif act == "off":
            o = sysproxy.off()
        else:
            st = sysproxy.status()
            print(f"[proxy] 系统代理（{sysproxy.SCHEMA}）：mode={st['mode']} "
                  f"http={st['http_host']}:{st['http_port']} https={st['https_host']}:{st['https_port']}")
            print(f"[proxy] schema 可用={st['available']}  ignore-hosts={st['ignore']}")
            return OK
        print(f"[proxy] {o.message}")
        for line in o.detail.splitlines():
            print(f"[proxy] {line}")
        return OK if o.ok else FAIL

    if args.verb == "entry":
        from . import entry
        act = getattr(args, "action", None)
        if act == "install":
            print(f"[proxy] 稳定入口已写入：{entry.install()}")
            return OK
        if act == "uninstall":
            print(f"[proxy] 稳定入口已移除：{entry.remove()}")
            return OK
        p = entry.wrapper_path()
        print(f"[proxy] 稳定入口 {p}：{'存在' if p.is_file() else '不存在'}")
        return OK

    if args.verb == "ui":
        from . import ui
        return ui.main()

    if args.verb == "desktop":
        from . import launcher, power
        act = getattr(args, "action", None)
        if act == "on":
            o = power.install_desktop()
        elif act == "off":
            o = power.remove_desktop()
        else:
            print(f"[proxy] {launcher.summary()}")
            return OK
        print(f"[proxy] {o.message}")
        for line in o.detail.splitlines():
            print(f"[proxy] {line}")
        return OK if o.ok else FAIL

    build_parser().print_help()
    return USAGE


def _log_event(verb: str | None, argv) -> None:
    if not verb:
        return
    try:
        from .logs import EventLog
        EventLog("app").event(verb)
    except Exception:  # 日志永不致命
        pass


if __name__ == "__main__":
    sys.exit(main())
