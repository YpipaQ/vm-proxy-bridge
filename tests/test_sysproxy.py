"""系统代理形状：`KEYS` / `browser_launch_env()` / `status()` 用假的 gsettings（不碰真实系统）。"""
import subprocess

import pytest

from proxybridge import config, sysproxy


class _R:
    """假的 CompletedProcess。"""
    def __init__(self, out: str = "", rc: int = 0):
        self.stdout, self.stderr, self.returncode = out, "", rc


def _make_fake_gs(calls: list[list[str]], schema_available: bool = True):
    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        assert cmd[0] == "gsettings", f"不该调用其它命令：{cmd}"
        if cmd[1] == "list-schemas":
            listed = sorted({s for _, s, _ in sysproxy.KEYS} | {sysproxy.SCHEMA})
            return _R("\n".join(listed) + "\n") if schema_available else _R("org.gnome.desktop.interface\n")
        if cmd[1] == "get":
            _cmd, _get, schema, key = cmd
            if schema == sysproxy.SCHEMA and key == "mode":
                return _R("'manual'\n")
            cfg = config.load()
            return _R(f"'{cfg['bind_host']}'\n" if key == "host" else f"{cfg['bind_port']}\n")
        return _R("")
    return fake_run


@pytest.fixture
def fake_gs(monkeypatch):
    """假的 gsettings：记下调用、按 schema/key 返回值；默认假装 schema 可用。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _make_fake_gs(calls))
    return calls


def test_keys_shape_covers_every_gsettings_key():
    names = [k[0] for k in sysproxy.KEYS]
    assert names == ["mode", "http_host", "http_port", "https_host", "https_port", "ignore"]
    for _, schema, key in sysproxy.KEYS:
        assert schema.startswith(sysproxy.SCHEMA)
        assert key and " " not in key


def test_schema_name_is_gnome_proxy():
    assert sysproxy.SCHEMA == "org.gnome.system.proxy"


def test_available_true_when_schema_listed(fake_gs):
    assert sysproxy.available() is True
    assert any(c[1] == "list-schemas" for c in fake_gs)


def test_available_false_when_schema_missing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _make_fake_gs([], schema_available=False))
    assert sysproxy.available() is False


def test_available_false_when_gsettings_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("gsettings")
    monkeypatch.setattr(subprocess, "run", boom)
    assert sysproxy.available() is False


def test_status_returns_every_key_plus_available(fake_gs):
    st = sysproxy.status()
    assert set(st) == {name for name, _, _ in sysproxy.KEYS} | {"available"}
    assert st["available"] is True
    assert st["mode"] == "'manual'"


def test_status_marks_gsettings_errors(monkeypatch):
    class R:
        returncode, stdout, stderr = 1, "", "Usage: gsettings get SCHEMA KEY\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    st = sysproxy.status()
    assert st["mode"].startswith("<err:") and st["available"] is False


def test_browser_launch_env_sets_every_proxy_var():
    """日常通路：给子进程 *_proxy（大小写都写）。2026-10-01 实测 52 条连接过桥。"""
    env = sysproxy.browser_launch_env("127.0.0.1:7897", "localhost,127.0.0.1")
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert env[k] == "http://127.0.0.1:7897", k
    assert env["no_proxy"] == env["NO_PROXY"] == "localhost,127.0.0.1"
    assert "XDG_CURRENT_DESKTOP" not in env, "不再靠伪装 GNOME（会改浏览器 GTK 集成）"


def test_strip_proxy_env_removes_both_cases():
    env = {"http_proxy": "x", "HTTPS_PROXY": "y", "no_proxy": "z", "NO_PROXY": "w", "PATH": "/bin"}
    assert sysproxy.strip_proxy_env(env) == {"PATH": "/bin"}


def test_on_writes_bind_address_from_config(fake_gs):
    cfg = config.load()
    o = sysproxy.on()
    assert o.ok
    sets = [tuple(c[1:]) for c in fake_gs if len(c) > 4 and c[1] == "set"]
    assert ("set", sysproxy.SCHEMA, "mode", "manual") in sets
    assert ("set", f"{sysproxy.SCHEMA}.http", "host", cfg["bind_host"]) in sets
    assert ("set", f"{sysproxy.SCHEMA}.http", "port", str(cfg["bind_port"])) in sets


def test_off_resets_to_direct(fake_gs):
    o = sysproxy.off()
    assert o.ok
    resets = {tuple(c[1:]) for c in fake_gs if len(c) > 3 and c[1] == "reset"}
    assert ("reset", f"{sysproxy.SCHEMA}.http", "host") in resets
    assert ("reset", sysproxy.SCHEMA, "ignore-hosts") in resets
    assert any(c[1:4] == ["set", sysproxy.SCHEMA, "mode"] and c[4] == "none" for c in fake_gs)


def test_on_refuses_when_schema_unavailable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _make_fake_gs([], schema_available=False))
    o = sysproxy.on()
    assert o.ok is False and "schema" in o.message
