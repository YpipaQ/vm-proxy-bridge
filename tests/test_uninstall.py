"""P4 头号验收：卸载后所有集成点与安装前【逐字节一致】；幂等；dry-run 不动盘。"""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from proxybridge import entry, manifest as manifest_mod, paths, power, uninstall


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def installed_home(tmp_path, monkeypatch):
    """模拟"用户已有一堆 dotfile"的真实机器，然后走一遍安装。"""
    h = tmp_path / "home"; h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(entry, "real_home", lambda home=None: str(h))

    pre = {
        paths.env_sh(): "# 我自己的 env\n",
        h / ".local" / "bin" / "proxy": "#!/bin/sh\necho 我自己的入口\n",
    }
    for p, text in pre.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
    before = {str(p): sha(p) for p in pre}

    power.write_env()          # env.sh
    power.install_entry()      # ~/.local/bin/proxy
    return before


def test_uninstall_restores_every_integration_point(installed_home):
    before = installed_home
    assert "http_proxy" in paths.env_sh().read_text()

    rep = uninstall.run()
    assert rep.ok, uninstall.render(rep)

    # ① 原本存在的文件 → 逐字节还原
    for path_str, original_sha in before.items():
        p = Path(path_str)
        assert p.exists(), f"{path_str} 应被还原但不存在"
        assert sha(p) == original_sha, f"{path_str} 还原后 sha256 不符"

    # ② 清单自身 → 卸载后必须消失
    assert not paths.manifest_file().exists()


def test_uninstall_removes_files_it_created(tmp_path, monkeypatch):
    """安装时新建的东西 → 必须消失（env.sh；入口在本用例里原本不存在）。"""
    h = tmp_path / "home"; h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(entry, "real_home", lambda home=None: str(h))
    power.write_env()
    power.install_entry()      # 走安装路径（会登记清单），不是裸 entry.install()
    assert paths.env_sh().exists() and entry.wrapper_path().exists()

    rep = uninstall.run()
    assert rep.ok, uninstall.render(rep)
    assert not paths.env_sh().exists(), "安装时新建的 env.sh 应被删除"
    assert not entry.wrapper_path().exists(), "安装时新建的入口应被删除"


def test_uninstall_without_manifest_touches_nothing(tmp_path, monkeypatch):
    """没有清单 → 拒绝猜：什么都不删（清单是唯一依据）。"""
    h = tmp_path / "home"; h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    user_file = h / ".local" / "bin" / "proxy"
    user_file.parent.mkdir(parents=True)
    user_file.write_text("#!/bin/sh\necho mine\n")
    rep = uninstall.run()
    assert rep.restored == [] and rep.removed == []
    assert user_file.exists(), "没有清单时不得删除任何文件"
    assert "没有安装清单" in uninstall.render(rep)


def test_manifest_records_before_state(installed_home):
    m = manifest_mod.Manifest.load()
    e = m.entries[str(paths.env_sh())]
    assert e.existed_before is True and e.writer == "power"
    assert m.entries[str(entry.wrapper_path())].writer == "entry"


def test_uninstall_is_idempotent(installed_home):
    rep1 = uninstall.run()
    assert rep1.ok, uninstall.render(rep1)
    rep2 = uninstall.run()                     # 第二次：清单已删 → 空报告，不报错
    assert rep2.ok and rep2.restored == [] and rep2.removed == []


def test_uninstall_dry_run_touches_nothing(installed_home):
    env_sh, wrapper = paths.env_sh(), entry.wrapper_path()
    before = {str(env_sh): sha(env_sh), str(wrapper): sha(wrapper)}
    r = subprocess.run([sys.executable, "-m", "proxybridge", "uninstall", "--dry-run"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    for path_str, original_sha in before.items():
        assert sha(Path(path_str)) == original_sha, f"dry-run 改动了 {path_str}"
