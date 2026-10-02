"""doctor 口径：**"没启用"不是故障**（用户拍板 2026-10-01）。

本机常态 = 没注入、没转发器、没设系统代理 → 必须 ❌0/⚠️0（退出码 0）。
只有"真的不一致 / 真的指错地方 / 上游不通"才报警。
"""
import pytest

from proxybridge import config, doctor, exitcodes, sysproxy


@pytest.fixture
def quiet_probes(monkeypatch):
    """把外部探测钉死，只测 doctor 的判定逻辑（不碰网络/系统/真实 HOME）。"""
    from proxybridge import browser, launcher
    monkeypatch.setattr(doctor.probe, "upstream_reachable", lambda *a, **k: True)
    monkeypatch.setattr(doctor.probe, "port_open", lambda *a, **k: False)
    monkeypatch.setattr(doctor, "_forwarder_pids", lambda: [])
    monkeypatch.setattr(sysproxy, "available", lambda: True)
    monkeypatch.setattr(sysproxy, "status", lambda: {
        "mode": "'none'", "http_host": "''", "http_port": "8080",
        "https_host": "''", "https_port": "0", "ignore": "[]", "available": True})
    monkeypatch.setattr(browser, "available",
                        lambda: {"chrome": "/usr/bin/google-chrome-stable",
                                 "firefox": "/usr/bin/firefox"})
    monkeypatch.setattr(launcher, "status", lambda: [])
    return monkeypatch


def levels(checks):
    return {c.title: c.level for c in checks}


def test_fresh_machine_is_all_ok(quiet_probes, monkeypatch):
    """全新机器：什么都不开 → 全 ok，退出码 0。"""
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    checks, code = doctor.run(env={})
    assert code == exitcodes.OK, doctor.render(checks)
    assert [c.level for c in checks] == ["ok"] * len(checks)


def test_not_listening_is_not_a_warning(quiet_probes):
    checks, code = doctor.run(env={})
    assert levels(checks)["转发器"] == "ok"
    assert "未运行" in next(c.detail for c in checks if c.title == "转发器")


def test_system_proxy_none_is_ok(quiet_probes):
    checks, _ = doctor.run(env={})
    assert levels(checks)["系统代理"] == "ok"
    assert "未设置" in next(c.detail for c in checks if c.title == "系统代理")


def test_system_proxy_pointing_elsewhere_warns(quiet_probes):
    quiet_probes.setattr(sysproxy, "status", lambda: {
        "mode": "'manual'", "http_host": "'10.0.0.9'", "http_port": "1080",
        "https_host": "'10.0.0.9'", "https_port": "1080", "ignore": "[]", "available": True})
    checks, code = doctor.run(env={})
    assert levels(checks)["系统代理"] == "warn" and code == exitcodes.DOCTOR_FAILED


def test_system_proxy_schema_missing_warns(quiet_probes):
    quiet_probes.setattr(sysproxy, "available", lambda: False)
    checks, code = doctor.run(env={})
    assert levels(checks)["系统代理"] == "warn" and code == exitcodes.DOCTOR_FAILED


def test_system_proxy_matching_bind_is_ok(quiet_probes):
    cfg = config.load()
    quiet_probes.setattr(sysproxy, "status", lambda: {
        "mode": "'manual'", "http_host": f"'{cfg['bind_host']}'",
        "http_port": str(cfg["bind_port"]), "https_host": f"'{cfg['bind_host']}'",
        "https_port": str(cfg["bind_port"]), "ignore": "[]", "available": True})
    checks, code = doctor.run(env={})
    assert levels(checks)["系统代理"] == "ok" and code == exitcodes.OK


def test_proxy_vars_pointing_elsewhere_warn(quiet_probes):
    checks, code = doctor.run(env={"http_proxy": "http://10.0.0.9:1080"})
    assert levels(checks)["当前进程 *_proxy"] == "warn" and code == exitcodes.DOCTOR_FAILED


def test_proxy_vars_matching_bind_are_ok(quiet_probes):
    cfg = config.load()
    url = f"http://{cfg['bind_host']}:{cfg['bind_port']}"
    checks, code = doctor.run(env={"http_proxy": url, "https_proxy": url})
    assert levels(checks)["当前进程 *_proxy"] == "ok" and code == exitcodes.OK


def test_unreachable_upstream_warns(quiet_probes):
    quiet_probes.setattr(doctor.probe, "upstream_reachable", lambda *a, **k: False)
    checks, code = doctor.run(env={})
    assert levels(checks)["上游 " + str(config.load()["upstream"])] == "warn"
    assert code == exitcodes.DOCTOR_FAILED


def test_env_sh_missing_while_running_warns(quiet_probes):
    """不一致才报：转发器在跑、env 文件却没了。"""
    quiet_probes.setattr(doctor.probe, "port_open", lambda *a, **k: True)
    checks, code = doctor.run(env={})
    assert levels(checks)["环境变量文件"] == "warn" and code == exitcodes.DOCTOR_FAILED


def test_bad_config_is_fail_and_stops_early(quiet_probes):
    from proxybridge import paths
    paths.config_root().mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('bind_host = "0.0.0.0"\n')
    checks, code = doctor.run(env={})
    assert code == exitcodes.DOCTOR_FAILED
    assert levels(checks)["配置"] == "fail"


def test_browser_path_reports_direct_when_not_taken_over(quiet_probes):
    """点图标直连是**事实**，要看得见（这正是 2026-10-01 "桥不起作用" 的根因）。"""
    checks, _ = doctor.run(env={})
    c = next(c for c in checks if c.title == "浏览器通路")
    assert c.level == "ok" and "直连" in c.detail


def test_browser_path_reports_taken_over(quiet_probes):
    from proxybridge import launcher
    quiet_probes.setattr(launcher, "status",
                         lambda: [launcher.Target(path=None, name="firefox.desktop",
                                                 kind="firefox", text="", ours=True, exists=True)])
    checks, _ = doctor.run(env={})
    c = next(c for c in checks if c.title == "浏览器通路")
    assert "已走桥" in c.detail


def test_browser_path_warns_when_no_browser(quiet_probes):
    from proxybridge import browser
    quiet_probes.setattr(browser, "available", lambda: {"chrome": None, "firefox": None})
    checks, code = doctor.run(env={})
    assert levels(checks)["浏览器通路"] == "warn" and code == exitcodes.DOCTOR_FAILED
