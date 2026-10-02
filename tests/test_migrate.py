"""迁移：dry-run 不动盘；apply 生效；rollback 能回到原样。"""
import hashlib
from pathlib import Path

import pytest

from proxybridge import migrate, paths


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def v1_machine(tmp_path, monkeypatch):
    """造一台"v1 用户"的机器：.proxy.conf + 旧日志 + 裸源 ~/.proxy_env 的 .profile。"""
    h = tmp_path / "home"; h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    (h / ".proxy.conf").write_text(
        '# proxy-bridge config\nPROXY_HOST="192.168.18.1:7897"\n'
        'BIND_HOST="127.0.0.1"\nBIND_PORT="7897"\nMODE="forward"\n'
        'TEST_URL="https://github.com"\n', "utf-8")
    (h / ".proxy.log").write_text("old v1 log\n", "utf-8")
    (h / ".proxy-forward.log").write_text("old forward log\n", "utf-8")
    (h / ".profile").write_text('export PATH=$PATH\n[ -f "$HOME/.proxy_env" ] && . "$HOME/.proxy_env"\n', "utf-8")
    return h


def test_dry_run_changes_nothing(v1_machine):
    before = {str(p): sha(p) for p in v1_machine.iterdir() if p.is_file()}
    pl = migrate.apply(dry_run=True)
    assert pl.actions, "应当计划出动作"
    after = {str(p): sha(p) for p in v1_machine.iterdir() if p.is_file()}
    assert before.keys() == after.keys()
    assert all(before[k] == after[k] for k in before)


def test_apply_then_rollback_restores_profile(v1_machine):
    profile = v1_machine / ".profile"
    before = sha(profile)
    migrate.apply(dry_run=False)
    # 迁移生效：config.toml 生成、旧日志搬走、profile 被改写
    assert paths.config_file().exists()
    assert "forward" in paths.config_file().read_text()
    assert not (v1_machine / ".proxy.log").exists()
    assert (paths.logs_dir() / "legacy" / ".proxy.log").exists()
    assert "[ -f \"$HOME/.proxy_env\" ] && ." not in profile.read_text()
    assert "config/proxy-bridge/env.sh" in profile.read_text()

    pl = migrate.rollback()
    assert pl.actions
    assert sha(profile) == before, "回滚后 .profile 必须逐字节还原"
    assert (v1_machine / ".proxy.log").exists(), "旧日志必须搬回原位"
    assert not paths.config_file().exists(), "config.toml 原本不存在 → 回滚应删除"


def test_config_toml_readable_by_v2(v1_machine):
    from proxybridge import config
    migrate.apply(dry_run=False)
    cfg = config.load()
    assert cfg["upstream"] == "192.168.18.1:7897"
    assert cfg["bind_port"] == 7897 and cfg["mode"] == "forward"
