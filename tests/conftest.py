"""所有测试都在临时 XDG 里跑，绝不碰真实家目录。

（原 `fake_watchdog_channel` fixture 是给注入层/看门狗通道造的，注入层已取缔 → 一并删除，
不跳过任何测试。）
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path, monkeypatch):
    for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                     ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return tmp_path
