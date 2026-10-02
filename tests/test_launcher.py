"""浏览器图标接管：用户级 .desktop 覆盖（不碰 /usr，可撤销）。

全部在 tmp 的 XDG_DATA_HOME 里跑，不碰真实 HOME。
"""
import pytest

from proxybridge import browser, config, entry, launcher, manifest, power


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """XDG_DATA_HOME → tmp；两个浏览器假装都装了；系统 .desktop 用真文件（只读）。"""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setattr(browser, "find", lambda kind: f"/usr/bin/{kind}")
    monkeypatch.setattr(launcher, "system_file", lambda name: None)
    return data


def test_applications_dir_follows_xdg(fake_home):
    assert launcher.applications_dir() == fake_home / "applications"


def test_render_has_marker_and_browser_exec(fake_home):
    text = launcher.render("google-chrome.desktop")
    assert f"{launcher.MARK}=1" in text
    assert "browser chrome %U" in text
    assert entry.wrapper_path().name in text or "-m proxybridge" in text
    assert text.startswith("[Desktop Entry]")


def test_render_copies_metadata_from_system_file(fake_home, monkeypatch, tmp_path):
    src = tmp_path / "real.desktop"
    src.write_text("[Desktop Entry]\nName=My Browser\nIcon=my-icon\n"
                   "Categories=Network;WebBrowser;\nStartupWMClass=my-class\n", "utf-8")
    monkeypatch.setattr(launcher, "system_file", lambda name: src)
    text = launcher.render("firefox.desktop")
    assert "Name=My Browser" in text and "Icon=my-icon" in text
    assert "StartupWMClass=my-class" in text


def test_desired_skips_browsers_not_installed(fake_home, monkeypatch):
    monkeypatch.setattr(browser, "find", lambda kind: None if kind == "chrome" else "/usr/bin/firefox")
    got = {p.name for p in launcher.desired()}
    assert got == {"firefox.desktop"}


def test_install_writes_and_is_idempotent(fake_home):
    o1 = power.install_desktop()
    assert o1.ok
    f = launcher.applications_dir() / "google-chrome.desktop"
    assert launcher.is_ours(f) and launcher.is_ours(launcher.applications_dir() / "firefox.desktop")
    before = f.read_text("utf-8")
    assert power.install_desktop().ok                       # 再跑一次不得改坏/重复备份
    assert f.read_text("utf-8") == before
    m = manifest.Manifest.load()
    assert str(f) in m.entries and m.entries[str(f)].writer == "desktop"
    assert m.entries[str(f)].existed_before is False        # 原本没有 → 卸载时应删除


def test_remove_restores_original_or_deletes(fake_home):
    adir = launcher.applications_dir()
    adir.mkdir(parents=True)
    orig = adir / "firefox.desktop"
    orig.write_text("[Desktop Entry]\nName=系统原始\n", "utf-8")     # 用户自己先有一个
    power.install_desktop()
    assert "系统原始" not in orig.read_text("utf-8")
    o = power.remove_desktop()
    assert o.ok
    assert orig.read_text("utf-8") == "[Desktop Entry]\nName=系统原始\n"   # 逐字节还原
    assert not (adir / "google-chrome.desktop").exists()                # 原本没有 → 删掉
    assert not manifest.Manifest.load().entries                        # 登记也清掉


def test_remove_without_manifest_is_noop(fake_home):
    o = power.remove_desktop()
    assert o.ok and "0 / 删除 0" in o.message


def test_status_reports_not_ours(fake_home):
    adir = launcher.applications_dir()
    adir.mkdir(parents=True)
    (adir / "firefox.desktop").write_text("[Desktop Entry]\nName=别的\n", "utf-8")
    rows = {t.name: t for t in launcher.status()}
    assert rows["firefox.desktop"].exists and rows["firefox.desktop"].ours is False
    assert "不是" in launcher.summary()


def test_config_untouched_by_summary(fake_home):
    assert config.load()["bind_port"] == 7897                       # 顺手确认 import 无副作用
