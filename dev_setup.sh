#!/bin/sh
# 开发环境一键就绪（离线，用 vendor/wheels）。产物：.venv-dev/
set -eu
cd "$(dirname "$0")"
[ -d .venv-dev ] || /usr/bin/python3 -m venv .venv-dev
if [ -f dist/proxybridge-*.whl ]; then
  .venv-dev/bin/python -m pip install --no-index --find-links dist --find-links vendor/wheels --force-reinstall proxybridge >/dev/null
else
  echo "提示：先跑 ./build.sh 出 dist/*.whl" >&2; exit 1
fi
.venv-dev/bin/python -m pip install --no-index --find-links vendor/wheels pytest >/dev/null
# UI 依赖（CustomTkinter）也走离线 wheel；装了才会走 CTk 而非 tkinter 降级路径
.venv-dev/bin/python -m pip install --no-index --find-links vendor/wheels customtkinter >/dev/null
echo "dev 环境就绪：.venv-dev/bin/python；test=./test.sh；GUI=./bin 无，用 .venv-dev/bin/proxy ui"
