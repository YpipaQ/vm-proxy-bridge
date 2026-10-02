"""配置：只读 TOML 主配置 + config.d/*.json 覆盖层（零依赖约束下不写 TOML）。

优先级（低→高）：内置默认 < config.toml < config.d/*.json（文件名排序，后者胜）
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from . import paths

DEFAULTS: dict = {
    "upstream": "192.168.18.1:7897",
    "bind_host": "127.0.0.1",
    "bind_port": 7897,
    "mode": "forward",
    "test_url": "https://github.com",
    "no_proxy": "localhost,127.0.0.1,::1",
    "logs": {"max_bytes": 2097152, "backups": 5},
    "probe": {"ttl_seconds": 60, "timeout_seconds": 3},
    "retention": {"backups_per_target": 10, "backup_days": 90},
}


class ConfigError(Exception):
    """配置非法。CLI 应转成退出码 1 并指明键。"""


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"{path} 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} 顶层必须是表")
    return data


def _load_overlays(dirpath: Path) -> dict:
    out: dict = {}
    if not dirpath.is_dir():
        return out
    for f in sorted(dirpath.glob("*.json")):
        try:
            data = json.loads(f.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"{f} 解析失败：{exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{f} 顶层必须是对象")
        out = _deep_merge(out, data)
    return out


def validate(cfg: dict) -> None:
    port = cfg.get("bind_port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError(f"bind_port 非法：{port!r}")
    host = str(cfg.get("bind_host", ""))
    if not host:
        raise ConfigError("bind_host 不得为空")
    # 安全红线：转发器默认只允许回环绑定（要暴露局域网必须显式改配置并自担风险）
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigError(
            f"bind_host={host!r} 不是回环地址。转发器是**无鉴权**通道，"
            "绑到非回环等于把宿主网络暴露给局域网；如确需，请在 config.toml 里显式设 allow_non_loopback=true"
        )
    up = str(cfg.get("upstream", ""))
    if ":" not in up:
        raise ConfigError(f"upstream 需形如 host:port，当前 {up!r}")
    mode = cfg.get("mode")
    if mode not in {"env", "forward", "off"}:
        raise ConfigError(f"mode 非法：{mode!r}（env|forward|off）")


def load(config_file: Path | None = None, config_dir: Path | None = None) -> dict:
    """读并合并配置；不写任何文件。"""
    f = config_file or paths.config_file()
    d = config_dir or paths.config_d()
    cfg = _deep_merge(DEFAULTS, _load_toml(f))
    cfg = _deep_merge(cfg, _load_overlays(d))
    validate(cfg)
    return cfg
