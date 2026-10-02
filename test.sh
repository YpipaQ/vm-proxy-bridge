#!/bin/sh
# 构建 → 离线装 → 跑测试（一条命令；避免"改了源码但测的是旧 wheel"这个坑）
set -eu
cd "$(dirname "$0")"
./build.sh >/dev/null
# 先删掉 venv 里已安装的旧包：pip 的 --force-reinstall 不会清理"新 wheel 里已不存在的模块"，
# 删过模块后残留的 inject.py/guard.py… 仍可被 import（踩过：防回流测试因此假通过）。
SITE=$(.venv-dev/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
rm -rf "$SITE/proxybridge"
.venv-dev/bin/python -m pip install --no-index --find-links dist --find-links vendor/wheels \
    --force-reinstall --no-deps proxybridge >/dev/null
exec .venv-dev/bin/python -m pytest "$@"
