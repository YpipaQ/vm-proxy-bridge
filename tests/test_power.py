"""总开关：env 文件内容与协议正确性、off 清空、稳定入口、状态可读。"""
from pathlib import Path

import pytest

from proxybridge import entry, manifest as manifest_mod, paths, power


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """隔离 HOME，并把 `entry.real_home` 也指到临时家目录。

    entry 默认用 pwd 取真 HOME（防 $HOME 被污染），测试里必须显式改掉它，
    否则会写真实的 `~/.local/bin`。
    """
    h = tmp_path / "home"; h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(entry, "real_home", lambda home=None: str(h))
    return h


def test_write_env_uses_http_not_socks5(iso):
    o = power.write_env()
    assert o.ok
    text = paths.env_sh().read_text()
    assert 'http_proxy="http://127.0.0.1:7897"' in text
    # 只断言"没有任何 export 语句写 socks5"（注释里提到历史错配是允许的）
    assert "export all_proxy" not in text and "export ALL_PROXY" not in text, \
        "转发器是 HTTP CONNECT 通道，不得导出 SOCKS5 代理（v1 的协议错配）"
    assert "socks5://127.0.0.1" not in text
    assert text.count("no_proxy=") == 1 and text.count("NO_PROXY=") == 1
    assert paths.env_sh().stat().st_mode & 0o777 == 0o644


def test_write_env_off_clears_exports(iso):
    power.write_env()
    assert "http_proxy" in paths.env_sh().read_text()
    o = power.write_env(mode="off")
    assert o.ok and "http_proxy" not in paths.env_sh().read_text()


def test_status_reports_config_and_entry(iso):
    st = power.status()
    assert st["bind"] == "127.0.0.1:7897" and st["upstream"] == "192.168.18.1:7897"
    assert st["env_file"] == str(paths.env_sh())
    assert "watchdog" not in st and "guard" not in st, "看门狗/守卫字段已随自启动取缔"
    assert st["entry_exists"] is False


def test_install_entry_is_idempotent_and_registered(iso):
    """`proxy on` 的稳定入口：写在隔离 HOME 下、内容不依赖 $HOME、可重复执行、登记进清单。"""
    assert power.install_entry().ok
    p = entry.wrapper_path()
    assert p.is_file() and p.stat().st_mode & 0o111, "入口必须可执行"
    assert p.parent == iso / ".local" / "bin"
    text = p.read_text()
    assert "$HOME" not in text, "wrapper 不能用 $HOME（会被污染环境解析到错目录）"
    assert "-m proxybridge" in text
    assert power.install_entry().ok                        # 幂等：再来一次不报错
    assert str(p) in manifest_mod.Manifest.load().entries
    assert manifest_mod.Manifest.load().entries[str(p)].writer == "entry"


def test_reinstall_does_not_overwrite_original_backup(iso):
    """重复 `proxy on` 不得把"我们已经写的内容"当成原件备份（否则卸载还原不回去）。"""
    user = iso / ".local" / "bin" / "proxy"
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text("#!/bin/sh\necho 用户自己的入口\n", "utf-8")
    original = user.read_text()

    power.install_entry()
    first = manifest_mod.Manifest.load().entries[str(user)].backup_id
    power.install_entry()                                  # 第二次
    m = manifest_mod.Manifest.load()
    assert m.entries[str(user)].backup_id == first, "第二次安装不得改 backup_id"
    assert Path(first).read_text() == original, "备份必须是安装前的原件"


def test_entry_argv_prefers_wrapper_then_falls_back(iso):
    assert entry.argv("forward", "run")[1:] == ["-m", "proxybridge", "forward", "run"]
    entry.install()
    assert entry.argv("forward", "run")[0] == str(entry.wrapper_path())
    assert entry.argv("forward", "run")[-2:] == ["forward", "run"]


def test_state_file_reflects_switch(iso):
    """`proxy status` 必须跟上开关：开过就说开，关了就变回来（曾经一直说 off）。"""
    from proxybridge import state
    power._write_state(True, "forward")
    st = state.read_state()
    assert st["desired_on"] is True and st["actual"] == "forward"
    power._write_state(False, "off")
    st = state.read_state()
    assert st["desired_on"] is False and st["actual"] == "off"
