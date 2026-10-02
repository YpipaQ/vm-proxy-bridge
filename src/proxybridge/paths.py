"""XDG 路径解析。设计约束：本模块不做任何 I/O 副作用（只拼路径）。"""
from __future__ import annotations

import os
from pathlib import Path

APP = "proxy-bridge"


def _xdg(env: str, default: str) -> Path:
    v = os.environ.get(env)
    return Path(v) if v else Path.home() / default


def config_root() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def data_root() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def state_root() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / APP


def cache_root() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def config_file() -> Path:
    return config_root() / "config.toml"


def config_d() -> Path:
    return config_root() / "config.d"


def env_sh() -> Path:
    return config_root() / "env.sh"


def logs_dir() -> Path:
    return state_root() / "logs"


def state_file() -> Path:
    return state_root() / "state.json"


def lock_file() -> Path:
    return state_root() / "lock"


def backups_root() -> Path:
    return data_root() / "backups"


def app_root() -> Path:
    return data_root() / "app"


def manifest_file() -> Path:
    return data_root() / "install-manifest.json"
