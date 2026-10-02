#!/bin/sh
# 离线构建本项目 wheel（不联网、不用构建隔离）
# 先删 build/：setuptools 会复用其中的旧副本，删掉的模块会"复活"进新 wheel（踩过：
# inject/guard/sysd 就是这样被重新打进 wheel、又装回 .venv-dev 的）。
set -eu
cd "$(dirname "$0")"
rm -rf build
exec /usr/bin/python3 -m pip wheel --no-build-isolation --no-deps -w dist .
