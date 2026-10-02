import json
import os
import stat
import time
from pathlib import Path

import pytest

from proxybridge import backup, config, exitcodes, logs, paths, probe, state


# ---------- paths / exitcodes ----------
def test_paths_follow_xdg(tmp_path):
    assert str(paths.state_root()).startswith(str(tmp_path))
    assert paths.logs_dir().name == "logs"
    assert "proxy-bridge" in str(paths.config_root())
    # 注入层已取缔：paths 不得再暴露 xsessionrc
    assert not hasattr(paths, "xsessionrc")


def test_exitcodes_match_design():
    assert (exitcodes.OK, exitcodes.FAIL, exitcodes.DOCTOR_FAILED,
            exitcodes.USAGE) == (0, 1, 2, 4)
    assert not hasattr(exitcodes, "NEEDS_HUMAN"), "退出码 3（safe_mode）已废除"


# ---------- config ----------
def test_config_defaults_only():
    cfg = config.load()
    assert cfg["mode"] == "forward" and cfg["bind_port"] == 7897


def test_config_overlay_priority():
    paths.config_root().mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('mode = "env"\n[logs]\nbackups = 9\n')
    d = paths.config_d(); d.mkdir(parents=True, exist_ok=True)
    (d / "10-a.json").write_text(json.dumps({"bind_port": 1080}))
    (d / "20-b.json").write_text(json.dumps({"logs": {"backups": 3}}))
    cfg = config.load()
    assert cfg["mode"] == "env"          # TOML 覆盖默认
    assert cfg["bind_port"] == 1080      # JSON 覆盖 TOML
    assert cfg["logs"]["backups"] == 3   # JSON 之间后者胜，且深度合并
    assert cfg["logs"]["max_bytes"] == config.DEFAULTS["logs"]["max_bytes"]


def test_config_rejects_non_loopback_bind():
    paths.config_root().mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('bind_host = "0.0.0.0"\n')
    with pytest.raises(config.ConfigError, match="无鉴权"):
        config.load()


def test_config_bad_toml_is_reported():
    paths.config_root().mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('mode = "forward\n')
    with pytest.raises(config.ConfigError):
        config.load()


# ---------- state ----------
def test_state_defaults_and_roundtrip():
    st = state.read_state()
    assert st["actual"] == "off" and st["desired_on"] is False
    assert "guard" not in st and "generation" not in st, "守卫字段已随死手开关取缔"
    st["actual"] = "forward"
    state.write_state(st)
    assert state.read_state()["actual"] == "forward"
    assert stat.S_IMODE(os.stat(paths.state_file()).st_mode) == 0o600


def test_state_corrupt_file_falls_back():
    paths.state_root().mkdir(parents=True, exist_ok=True)
    paths.state_file().write_text("{ not json")
    assert state.read_state()["actual"] == "off"


def test_single_writer_lock_is_exclusive():
    with state.single_writer(timeout=1):
        pid = os.fork()
        if pid == 0:
            try:
                with state.single_writer(timeout=0.3):
                    os._exit(0)
            except TimeoutError:
                os._exit(7)
            finally:
                os._exit(9)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 7   # 子进程拿不到锁


def test_tx_lifecycle():
    tx = state.Tx("on")
    txid = tx.begin(["/tmp/x"])
    assert tx.path.exists() and tx.path.name.startswith(txid)
    tx.commit()
    assert not tx.path.exists()
    assert (paths.state_root() / "tx" / "done" / f"{txid}.json").exists()


# ---------- logs ----------
def test_log_rotation_boundaries():
    p = paths.logs_dir() / "t.log"
    w = logs.RotatingWriter(p, max_bytes=100, backups=2)
    w.write("a" * 50)                     # 空文件起始，未越界
    assert p.stat().st_size == 50 and not (paths.logs_dir() / "t.log.1").exists()
    w.write("b" * 60)                     # 写前判定 50 < 100 不轮转 → 110
    assert p.stat().st_size == 110 and not (paths.logs_dir() / "t.log.1").exists()
    w.write("c" * 10)                     # 写前 110 >= 100 → 轮转，旧内容进 .1
    assert (paths.logs_dir() / "t.log.1").stat().st_size == 110
    assert p.stat().st_size == 10
    for _ in range(5):
        w.write("c" * 120)
    assert (paths.logs_dir() / "t.log.2").exists()
    assert not (paths.logs_dir() / "t.log.3").exists()   # backups=2 封顶
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_log_never_raises_on_bad_path():
    logs.RotatingWriter(Path("/proc/definitely/not/writable.log")).write("x")  # 不抛


def test_eventlog_writes_jsonl():
    logs.EventLog("app").event("doctor", result="ok")
    rec = json.loads((paths.logs_dir() / "app.jsonl").read_text().strip().splitlines()[-1])
    assert rec["verb"] == "doctor" and rec["uid"] == os.getuid()


# ---------- backup ----------
def test_backup_restore_roundtrip_sha256(tmp_path):
    target = tmp_path / "xsessionrc"
    target.write_text("user content\n")
    before = backup.sha256_file(target)
    b = backup.backup(target)
    assert b and stat.S_IMODE(os.stat(b).st_mode) == 0o600
    target.write_text("clobbered\n")
    backup.restore(b, target)
    assert backup.sha256_file(target) == before     # 逐字节还原


def test_backup_missing_target_is_noop(tmp_path):
    assert backup.backup(tmp_path / "nope") is None


def test_prune_keeps_newest(tmp_path):
    root = tmp_path / "backups"
    for i in range(5):
        f = root / "xsessionrc" / f"2026010{i}T000000.aaaaaaa{i}"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(str(i))
        os.utime(f, (time.time() + i, time.time() + i))
    removed = backup.prune(root, keep=2, days=3650)
    assert len(removed) == 3
    assert len(list((root / "xsessionrc").iterdir())) == 2


# ---------- probe ----------
def test_probe_port_and_upstream():
    assert probe.port_open("127.0.0.1", 1, timeout=0.2) is False
    assert probe.upstream_reachable("nosuchhost.invalid:1", timeout=0.2) is False
    assert probe.upstream_reachable("badformat", timeout=0.2) is False


def test_probe_cache_ttl():
    probe.write_cache({"upstream_ok": True})
    assert probe.read_cache(ttl=60)["upstream_ok"] is True
    assert probe.read_cache(ttl=-1) is None
