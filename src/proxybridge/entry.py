"""稳定入口 `~/.local/bin/proxy` 的渲染与安装/卸载。

`proxy on` 会写这个入口，卸载按清单还原；它只是 `python -m proxybridge` 的薄壳。
坑：wrapper 里**不能**用 `$HOME` —— 如果生成环境或调用环境带着被污染的 HOME
（例如测试里 monkeypatch 过），就会解析到错误的目录。真 HOME 用
`pwd.getpwuid(os.getuid()).pw_dir` 取，不受环境变量影响；`home` 参数只为测试保留。
"""
from __future__ import annotations

import os
import pwd
import sys
from pathlib import Path


def real_home(home: str | None = None) -> str:
    return home or pwd.getpwuid(os.getuid()).pw_dir


def wrapper_path(home: str | None = None) -> Path:
    return Path(real_home(home)) / ".local" / "bin" / "proxy"


def render(home: str | None = None) -> str:
    h = real_home(home)
    return f"""#!/bin/sh
# proxy-bridge v2 入口（由 proxybridge.entry 生成）
exec "{sys.executable}" -m proxybridge "$@"
"""


def install(home: str | None = None) -> Path:
    p = wrapper_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(home), "utf-8")
    p.chmod(0o755)
    return p


def remove(home: str | None = None) -> Path:
    p = wrapper_path(home)
    p.unlink(missing_ok=True)
    return p


def argv(*args: str) -> list[str]:
    """子进程调用 `proxy <args>` 的命令行：优先稳定入口，否则当前解释器 -m proxybridge。"""
    return [str(wrapper_path()), *args] if wrapper_path().is_file() \
        else [sys.executable, "-m", "proxybridge", *args]
