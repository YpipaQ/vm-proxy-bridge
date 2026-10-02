"""support-bundle：把日志/状态/配置打成一个**脱敏** tar.gz，便于外发排查。"""
from __future__ import annotations

import re
import shutil
import tarfile
import time
from pathlib import Path

from . import config, manifest as manifest_mod, paths

KEEP = 5
#: 脱敏规则：上游地址、内网段、可能的凭据串
SCRUB_RULES = [
    (re.compile(r"(?i)(proxy[_a-z]*\s*[:=]\s*)(\S+)"), r"\1<redacted>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip:port>"),
    (re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+"), r"\1=<redacted>"),
]


def scrubbed(text: str) -> str:
    for pat, repl in SCRUB_RULES:
        text = pat.sub(repl, text)
    return text


def _add(tar: tarfile.TarFile, path: Path, arcname: str) -> None:
    if not path.exists():
        return
    info = tar.gettarinfo(str(path), arcname=arcname)
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    if path.is_file():
        with path.open("rb") as fh:
            tar.addfile(info, fh)
    else:
        tar.addfile(info)


def build(dest_dir: Path | None = None) -> Path:
    """生成 bundle；同时把配置/状态以**脱敏后的文本**放进 `scrubbed/`。"""
    root = dest_dir or (paths.state_root() / "support")
    root.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    out = root / f"{ts}-bundle.tar.gz"

    with tarfile.open(out, "w:gz") as tar:
        _add(tar, paths.logs_dir(), "logs")
        for f in sorted(paths.logs_dir().glob("*")):
            _add(tar, f, f"logs/{f.name}")
        _add(tar, paths.state_file(), "state.json")

        # 脱敏摘要（不打包原配置）
        lines = [f"# proxy-bridge support bundle {ts}", ""]
        try:
            for k, v in sorted(config.load().items()):
                lines.append(f"{k} = {json_safe(v)}")
        except Exception as exc:                                    # noqa: BLE001
            lines.append(f"# 配置读取失败：{exc}")
        m = manifest_mod.Manifest.load()
        lines += ["", f"# 清单条目 {len(m.entries)} 项", *[f"  {k}" for k in m.entries]]
        info = tarfile.TarInfo("summary.txt")
        data = scrubbed("\n".join(lines) + "\n").encode()
        info.size = len(data)
        import io
        tar.addfile(info, io.BytesIO(data))

    # 保留最近 KEEP 份
    bundles = sorted(root.glob("*-bundle.tar.gz"), reverse=True)
    for old in bundles[KEEP:]:
        old.unlink(missing_ok=True)
    return out


def json_safe(v):
    import json
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
