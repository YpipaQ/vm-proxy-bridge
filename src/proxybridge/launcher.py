"""用户级 .desktop 接管：让**点菜单/面板图标**启动的浏览器也走桥。

原理：XDG 查找顺序里 `~/.local/share/applications/<同名>.desktop` 优先于
`/usr/share/applications/`，所以只要写两个**同名覆盖文件**，Exec 换成
`proxy browser <kind> %U`，系统原文件一个字节都不用动。
关闭（`proxy desktop off`）/ 卸载时按安装清单还原（原本没有 → 删掉）。

只管这两个浏览器，不碰桌面环境、不碰登录链、不碰系统目录。

输入 / 输出（模块契约）：
    输入：系统自带的 `*.desktop`（只读，抄 Name/Icon/类别）、`entry.argv()`（稳定入口路径）、
          `browser.find()`（浏览器是否装了）、XDG 环境变量（XDG_DATA_HOME / XDG_DATA_DIRS）。
    输出：`desired() → {路径: 全文}`（纯数据，**本模块不落盘**；落盘由 `power.install_desktop()`
          负责并经安装清单登记，才好还原）、`status() → list[Target]`、`summary() → str`。
    不做：不写/删文件、不动 `/usr/share`、不碰登录链与桌面环境设置。
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

from . import browser, entry

#: 我们写的文件带这个标记，用来判断"这个 .desktop 是不是我们接管的"
MARK = "X-Proxy-Bridge"

#: 桌面文件名 → (浏览器种类, 字段码, 默认图标名)
TARGETS: dict[str, tuple[str, str, str]] = {
    "google-chrome.desktop": ("chrome", "%U", "google-chrome"),
    "firefox.desktop": ("firefox", "%u", "firefox"),
}

_COPY_KEYS = ("Name", "GenericName", "Comment", "Icon", "Categories",
              "StartupWMClass", "StartupNotify")


@dataclass
class Target:
    path: Path
    name: str
    kind: str
    text: str
    ours: bool
    exists: bool


def applications_dir() -> Path:
    v = os.environ.get("XDG_DATA_HOME")
    return (Path(v) if v else Path.home() / ".local" / "share") / "applications"


def data_dirs() -> list[Path]:
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(p) for p in raw.split(":") if p]


def system_file(name: str) -> Path | None:
    """系统自带的同名 .desktop（用来抄 Name / Icon 等元信息）。"""
    for d in data_dirs():
        f = d / "applications" / name
        if f.is_file():
            return f
    return None


def _meta(src: Path | None) -> dict:
    if src is None:
        return {}
    cp = configparser.ConfigParser(strict=False, interpolation=None, delimiters=("=",))
    try:
        cp.read(src, encoding="utf-8")
    except (OSError, configparser.Error):
        return {}
    if not cp.has_section("Desktop Entry"):
        return {}
    sec = cp["Desktop Entry"]
    return {k: sec[k].strip() for k in _COPY_KEYS if sec.get(k)}


def render(name: str) -> str:
    """生成接管用 .desktop 的全文（纯函数，不落盘）。"""
    kind, field, default_icon = TARGETS[name]
    meta = _meta(system_file(name))
    exe = entry.argv("browser", kind)
    exec_line = " ".join(f'"{a}"' if " " in a else a for a in exe) + f" {field}"
    rows = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={meta.get('Name', browser.LABELS[kind])}",
        f"Comment={meta.get('Comment', 'Browser via proxy-bridge')}",
        f"Exec={exec_line}",
        f"Icon={meta.get('Icon', default_icon)}",
        "Terminal=false",
        f"Categories={meta.get('Categories', 'Network;WebBrowser;')}",
        "StartupNotify=true",
        f"{MARK}=1",
    ]
    for k in ("GenericName", "StartupWMClass"):
        if meta.get(k):
            rows.insert(4, f"{k}={meta[k]}")
    return "\n".join(rows) + "\n"


def desired() -> dict[Path, str]:
    """需要接管的 (路径 → 内容)：只对**系统里真的装了的**浏览器动手。"""
    out: dict[Path, str] = {}
    for name, (kind, _field, _icon) in TARGETS.items():
        if browser.find(kind) is None:
            continue
        out[applications_dir() / name] = render(name)
    return out


def is_ours(path: Path) -> bool:
    try:
        return f"{MARK}=1" in path.read_text("utf-8", errors="replace")
    except OSError:
        return False


def status() -> list[Target]:
    out: list[Target] = []
    for name, (kind, _f, _i) in TARGETS.items():
        p = applications_dir() / name
        out.append(Target(path=p, name=name, kind=kind,
                          text=p.read_text("utf-8", errors="replace") if p.is_file() else "",
                          ours=is_ours(p), exists=p.is_file()))
    return out


def summary() -> str:
    rows = []
    for t in status():
        label = browser.LABELS[t.kind]
        if t.ours:
            rows.append(f"{label}：已接管（{t.path.name}）")
        elif t.exists:
            rows.append(f"{label}：{t.path.name} 存在但**不是**我们写的")
        else:
            rows.append(f"{label}：未接管（点图标仍直连）")
    return "；".join(rows)
