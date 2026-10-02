# vendor/ —— 离线依赖（关桥/断网也能装）

> **结论**：本项目的**运行时核心零第三方依赖**；只有 GUI（CustomTkinter）与人读输出（rich）
> 用了第三方，且全部是**纯 Python wheel**（无编译、无平台绑定），共 **2.4 MB**。
> 离线安装 = `pip install --no-index --find-links vendor/wheels <包名>`，已实测通过（见下"实跑证据"）。

## 1. 选型与配额（用户口径：UI 库 ≤1、功能库 ≤3）

| 槽位 | 包 | 版本 | 归类 | 上线时机 | 为什么是它 |
| --- | --- | --- | --- | --- | --- |
| UI ×1 | `customtkinter` | 5.2.2 | 运行时 | P3（GUI 重构） | PyPI 月下载约 2–3M、持续活跃；纯 Python 包在 Tk 8.6 上；比裸 Tk 现代、比 PyQt6 轻且无 GPL 传染（PyQt6 = GPL / 商业双许可） |
| 功能 1 | `rich` | 13.9.4 | 运行时（可选） | P1（doctor/status 起） | 月下载 100M+、维护活跃；纯 Python；只用于**人读**输出，不参与状态落盘。若导入失败应**自动降级为纯文本**（代码里必须写降级分支） |
| 功能 2 | `pytest` | 8.3.5 | **dev-only** | P1（单测） | Python 测试事实标准；只进 vendor，**绝不进运行时依赖** |
| 槽位 3 | *（留空）* | — | — | — | 不凑配额。运行时核心（config/state/inject/guard/tunnel/probe/backup）**零第三方** |

传递依赖（随 `--find-links` 自动解析，均已下载）：

```
customtkinter 5.2.2 → darkdetect 0.8.0, packaging 26.3
rich 13.9.4         → markdown-it-py 4.2.0 → mdurl 0.1.2, pygments 2.21.0
pytest 8.3.5 (dev)  → iniconfig 2.3.0, packaging 26.3, pluggy 1.6.0, pygments 2.21.0
```

**环境标记已核对**：所有 `Requires-Dist` 上的条件（`sys_platform == "win32"`、`python_version < "3.11"`、
`extra == ...`）在本机（Linux / CPython 3.13.5）**均不触发** → 上面的清单就是完整闭包。

## 2. 离线安装（目标机无需编译、无需 setuptools/wheel、无需网络）

```bash
# ① 建 venv（venv 里只有 pip，这是正常的）
/usr/bin/python3 -m venv ~/.local/share/proxy-bridge/app/venv

# ② 从 vendor 离线装（本文件所在目录）
~/.local/share/proxy-bridge/app/venv/bin/python -m pip install \
  --no-index --find-links vendor/wheels \
  customtkinter rich

# ③ dev 环境（跑测试才需要）
~/.local/share/proxy-bridge/app/venv/bin/python -m pip install \
  --no-index --find-links vendor/wheels pytest
```

**不要用** `pip install --no-index .`（交接书 §7 P0 原写法）：全新 venv 里没有 setuptools/wheel，
`--no-build-isolation` 会 `BackendUnavailable: Cannot import 'setuptools.build_meta'`；带隔离则因
`--no-index` 拿不到构建后端而失败。**已实测失败**，故改为上面的 wheel 直装法。

本项目自身的安装（P4）同样不构建：在**有网/有工具的机器**上 `python -m build --wheel` 出
`proxybridge-<ver>-py3-none-any.whl` 放进 `vendor/wheels/`，目标机只做"直装 wheel + 写入口"。

## 3. 实跑证据（2026-09-30，本机）

| 验证 | 命令要点 | 结果 |
| --- | --- | --- |
| 纯离线安装 | `env -u http_proxy -u https_proxy -u all_proxy python -m pip install --no-index --find-links . customtkinter rich pytest` | `Successfully installed customtkinter-5.2.2 darkdetect-0.8.0 iniconfig-2.3.0 markdown-it-py-4.2.0 mdurl-0.1.2 packaging-26.3 pluggy-1.6.0 pygments-2.21.0 pytest-8.3.5 rich-13.9.4` |
| 导入 | `import customtkinter, rich, darkdetect, pytest` | 全部成功（`rich` 无 `__version__` 属性，属正常） |
| GUI 冒烟 | `tkinter.Tk()` + `ctk.CTkButton` + `update_idletasks()`（不 mainloop） | `tkinter 8.6` / `CTk widget 创建 + update 成功` |
| 完整性 | `sha256sum *.whl > ../SHA256SUMS.txt` | 10 个 wheel，见 `vendor/SHA256SUMS.txt` |

> 局限（诚实标注）：GUI 冒烟只到"能创建控件 + update"，**没有**进 mainloop、没有真交互；
> 真 GUI 验收要到 P3。离线安装验证是在 `/tmp` 的临时 venv 里做的，未碰 `~/.local/share`。

## 4. 复现/增补下载（有网时）

```bash
cd ~/project/proxy-bridge/vendor
http_proxy=http://127.0.0.1:7897 https_proxy=http://127.0.0.1:7897 \
/usr/bin/python3 -m pip download --only-binary=:all: --dest wheels --no-cache-dir \
  "customtkinter==5.2.2" "rich==13.9.4" "pytest==8.3.5"
sha256sum wheels/*.whl > SHA256SUMS.txt
```

**Why 全部 `--only-binary=:all:`**：禁止 sdist，避免目标机需要编译器；一旦某包只有 sdist，
这条命令会**直接失败**，等于把"不可离线安装"的问题挡在下单之前。

## 5. 外发（GitHub）注意

- `vendor/wheels/` 是**可公开**的（纯 PyPI 制品），但请连同 `SHA256SUMS.txt` 一起提交，便于第三方校验。
- **不进仓库**：`vendor/*.log`、任何 `env.sh`、`state/`、`logs/`、备份、`install-manifest.json`。
  见 P4 的 `.gitignore`（会逐条列出）。
- 运行时日志/状态里若出现上游地址（`192.168.18.1:7897`），属**内网地址**，外发前用 `support-bundle`
  的脱敏路径处理，不要直接把 `~/.local/state/proxy-bridge/` 打进仓库。
