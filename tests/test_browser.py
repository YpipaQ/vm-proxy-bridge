"""浏览器通路：**转发器在不在跑，决定浏览器是走桥还是直连**（2026-10-01 的核心修复）。

不真的开浏览器：把 Popen 换成假的，只看喂进去的 argv/env。
"""
import pytest

from proxybridge import browser, config


class _FakeProc:
    pid = 4242


@pytest.fixture
def fake_popen(monkeypatch):
    seen: dict = {}

    def fake(argv, env=None, **kw):
        seen["argv"], seen["env"], seen["kw"] = argv, env, kw
        return _FakeProc()

    monkeypatch.setattr(browser.subprocess, "Popen", fake)
    monkeypatch.setattr(browser, "find", lambda kind: f"/usr/bin/{kind}-bin")
    return seen


def test_up_when_forwarder_listens(fake_popen, monkeypatch):
    monkeypatch.setattr(browser.probe, "port_open", lambda *a, **k: True)
    o = browser.launch("chrome")
    assert o.ok and o.proxy is True and o.pid == 4242
    assert fake_popen["argv"] == ["/usr/bin/chrome-bin"]
    cfg = config.load()
    bind = f"{cfg['bind_host']}:{cfg['bind_port']}"
    assert fake_popen["env"]["http_proxy"] == f"http://{bind}"
    assert fake_popen["env"]["no_proxy"]


def test_direct_when_forwarder_down_and_env_stripped(fake_popen, monkeypatch):
    """转发器没在跑时必须**摘掉**代理变量，否则浏览器指着一个死端口 = 打不开网页。"""
    monkeypatch.setattr(browser.probe, "port_open", lambda *a, **k: False)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7897")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    o = browser.launch("firefox")
    assert o.ok and o.proxy is False
    assert "直连" in o.message
    assert "http_proxy" not in fake_popen["env"]
    assert "HTTPS_PROXY" not in fake_popen["env"]


def test_extra_args_pass_through_verbatim(fake_popen, monkeypatch):
    """浏览器自己的 --xxx 必须原样传下去（曾经被 argparse 吃掉两次）。"""
    monkeypatch.setattr(browser.probe, "port_open", lambda *a, **k: True)
    browser.launch("chrome", ["--incognito", "--proxy-server=http://1.2.3.4:1", "https://a.b"])
    assert fake_popen["argv"] == ["/usr/bin/chrome-bin", "--incognito",
                                  "--proxy-server=http://1.2.3.4:1", "https://a.b"]


def test_unknown_or_missing_browser_is_reported(fake_popen):
    assert browser.launch("netscape").ok is False
    assert browser.launch("netscape").message.startswith("不认识的浏览器")


def test_missing_binary_is_reported(monkeypatch):
    monkeypatch.setattr(browser, "find", lambda kind: None)
    o = browser.launch("chrome")
    assert o.ok is False and "找不到" in o.message


def test_presets_cover_chrome_and_firefox():
    assert set(browser.PRESETS) == {"chrome", "firefox"}
    assert "google-chrome-stable" in browser.PRESETS["chrome"]
