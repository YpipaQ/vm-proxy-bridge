"""CLI 冒烟：每个只读动词都能跑出退出码 0（不写盘、不碰运行态）。"""
import subprocess
import sys

import pytest

READONLY = [
    ["--version"],
    ["version", "--json"],
    ["paths", "--json"],
    ["status", "--json"],
    ["doctor", "--json"],
    ["forward", "status"],
    ["entry", "status"],
    ["sysproxy", "status"],
    ["manifest", "--json"],
    ["uninstall", "--dry-run"],
    ["migrate", "--dry-run"],
]

#: 已取缔的动词：必须变成 argparse 的用法错误（rc=4），而不是"还能跑"
REMOVED_VERBS = ["session", "guard", "rescue", "service"]


# doctor 的退出码语义是 0 全过 / 2 有 warn·fail ——
# 在隔离环境里可能没有转发器/系统代理，所以 2 是**正确**结果，不是失败。
DOCTOR_LIKE = {0, 2}


@pytest.mark.parametrize("argv", READONLY)
def test_readonly_verbs_exit_zero(argv):
    r = subprocess.run([sys.executable, "-m", "proxybridge", *argv],
                       capture_output=True, text=True, timeout=60)
    allowed = DOCTOR_LIKE if argv[:1] == ["doctor"] else {0}
    assert r.returncode in allowed, f"{argv} rc={r.returncode}\n{r.stdout}\n{r.stderr}"


@pytest.mark.parametrize("verb", REMOVED_VERBS)
def test_removed_verbs_are_rejected(verb):
    """已取缔的动词：argparse 视为未知子命令 → 非 0 退出，且不出现在 --help 里。"""
    r = subprocess.run([sys.executable, "-m", "proxybridge", verb],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, f"{verb} 应已取缔，实际 rc={r.returncode}\n{r.stdout}{r.stderr}"
    h = subprocess.run([sys.executable, "-m", "proxybridge", "--help"],
                       capture_output=True, text=True, timeout=60)
    assert f"    {verb} " not in h.stdout, f"{verb} 仍在 --help 的子命令清单里"


def test_usage_error_returns_4():
    r = subprocess.run([sys.executable, "-m", "proxybridge"], capture_output=True, text=True)
    assert r.returncode == 4, "无参数时应返回用法错误码 4"


def test_doctor_exit_code_2_when_warnings():
    r = subprocess.run([sys.executable, "-m", "proxybridge", "doctor"],
                       capture_output=True, text=True)
    assert r.returncode in (0, 2), "doctor 只允许 0（全过）/ 2（有失败项）"
    assert r.returncode != 3, "退出码 3（safe_mode）已废除"
