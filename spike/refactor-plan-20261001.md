# 精简改造单：取缔注入层（2026-10-01）

> 施工范围：**只改 `src/proxybridge/` 与 `tests/`**。文档（README/DESIGN/HANDOFF/MODULES/ACCEPTANCE/NEWHOST/SPIKE）由 Lead 改，别动。

## 0. 为什么

实测定论（矩阵 33 例 + 真机 GitHub 抓取）：
1. 浏览器**根本不需要注入**就能走代理：Chrome 认系统代理（要桌面标识）、也认 `http_proxy`/`HTTP_PROXY`/`all_proxy`、也认 `--proxy-server`；Firefox 默认"用系统代理"，**连桌面标识都不需要**。
2. 注入层（`~/.xsessionrc`）在本机本来就不可用（无 systemd 用户管理器 → 看门狗通道不 healthy → `session on` 硬拒绝），且 2026-09-30 的登录循环事故就是它引起的。
3. 结论：注入层 = 危险 + 不可用 + 无收益 → **取缔**。配套的死手开关、D1–D4 防线、预演、救援、会话确认全部随之删除。

## 1. 删除这些模块（整文件删）

| 文件 | 行数 | 原来干什么 |
| --- | --- | --- |
| `inject.py` | 178 | 生成/校验/摘除 `~/.xsessionrc` 托管块 |
| `guard.py` | 263 | D4 死手开关（打卡/确认/超时回滚/safe_mode） |
| `rehearse.py` | 84 | D3 沙箱全链路预演 |
| `session.py` | 290 | 注入层编排（`session on/off/status/confirm`） |
| `desktop.py` | 91 | `.desktop`/autostart 集成（自启动一并取缔） |
| `sysd.py` | 202 | systemd 单元（guard/forward 自启动） |

**例外**：`sysd.py` 里 `install_entry_wrapper()`（生成 `~/.local/bin/proxy` 稳定入口）是有用的，
先 `grep -rn 'install_entry_wrapper' src tests` 找到调用方，把这个函数**搬到** `paths.py` 或新建的
小模块 `entry.py`（≤40 行），保留"安装/卸载入口包装"能力。找不到调用方就一并删，但要在回报里写明。

## 2. 修剪这些模块（保留其核心职责，只摘掉注入/守卫/自启动部分）

| 模块 | 要做的 |
| --- | --- |
| `cli.py` | 删 `session`、`guard`、`rescue`、`service` 四组子命令；删 `doctor --no-rehearse`；`paths --json` 去掉 `xsessionrc`。保留：`version/paths/status/doctor/on/off/forward/uninstall/support-bundle/migrate/manifest/ui/sysproxy/chrome` |
| `power.py` | 删 `guard` 相关（第 146 行 `from . import guard`）与"起看门狗"；`on` = 写 env + 起转发器，`off` 反之 |
| `state.py` | 删 `guard` 字段（safe_mode/armed_at/generation）；保留 `desired_on`/`actual`。注意 `cli status` 现在读 `st['guard']['safe_mode']`，要一起改 |
| `doctor.py` | 删 D3 预演与注入检查；保留其余检查项。**新增**一项：系统代理（gsettings）是否已指向本地转发器，以及 `sysproxy.available()` |
| `ctl.py` | 删守卫/注入动作，保留"串行动作队列"这个骨架 |
| `ui.py` | 删注入/守卫/safe_mode 的显示与按钮，保留状态快照+动作+日志尾部 |
| `support.py` | 打包清单里删 `xsession-reached.log`、`guard.jsonl`、`~/.xsessionrc` 相关内容 |
| `manifest.py` | 集成点去掉 `~/.xsessionrc`、autostart、systemd 单元；保留剩余点位（env.sh、入口包装、备份目录） |
| `uninstall.py` | 同上对齐，保证 `--dry-run` 与实际一致、幂等 |
| `migrate.py` | 若引用了 `~/.xsessionrc`/注入块，删掉那部分（v1 的 `.proxy_env` 迁移保留） |
| `paths.py` | `xsessionrc()` 若已无人用则删 |

## 3. 测试

- **删**：`test_inject.py`、`test_guard.py`、`test_guard_watch.py`、`test_d4_render.py`、
  `test_session_e2e.py`、`test_rescue.py`、`test_channel_guard.py`、`test_rehearse.py`、
  `test_desktop_ctl.py`（desktop 已删）。
- **改**：`test_cli_smoke.py`（去掉 session/guard/确认断言）、`test_uninstall.py`（去掉 session/sysd 点位）、
  `test_core.py`、`conftest.py`（若 fixture 是为看门狗通道造的，删掉；保证不跳过任何测试）。
- **加**（要能长期留着，不是一次性）：
  1. `test_no_injection.py`：断言 `inject/guard/rehearse/session/desktop/sysd` 模块**不存在**，
     且 `src/` 里搜不到 `xsessionrc`、`D4`、`safe_mode` 字样（防回流）；
  2. `test_sysproxy.py`：`sysproxy.KEYS`/`browser_env()`/`status()` 形状，`gsettings` 用假的（不碰真实系统）。
- `./test.sh` 必须绿。

## 4. 验收（缺一不可）

1. `./test.sh` → 全绿，报出测试条数。
2. `python3 - <<'PY'` 式自检：`proxy doctor` 在**当前系统状态**（注入本就没有、转发器未跑）下 **❌0 / ⚠️0**；`proxy status`、`proxy sysproxy status`、`proxy --help` 正常。
3. `grep -rn 'xsessionrc\|inject\|guard\|rehearse\|safe_mode\|D1\|D2\|D3\|D4' src/` 只剩**历史注释**（若保留注释，必须是"/曾用于…，已取缔"这种说明），不得有可执行引用。
4. 模块数与行数**下降**，并在回报里给出：`wc -l src/proxybridge/*.py | tail -1` 前后对比、模块个数前后对比。
5. 模块化不倒退：不许把被删模块的功能塞进 `cli.py`；`cli.py` 应因删命令而**变短**。
6. 不许 `try: import 已删模块 except ImportError: pass` 这类兜底；要真删干净。

## 5. 纪律

- 别跑 `./test.sh` 之前先确认没有别的测试在跑：`pgrep -f 'google[-]chrome.*gh'` 为空再跑（另一个子任务正在做真机 GitHub 端到端）。
- 只动 `src/` 与 `tests/`；不碰 `~/` 下任何用户配置、不碰桌面文件、不装东西。
- 用 `probe[_]server` 这种方括号写法做进程匹配，别用 `pkill -f`（会杀掉自己的 shell）。
- 回报格式：删了什么（文件+行数）、改了哪些文件的哪些函数、`./test.sh` 原始结论行、验收 1–6 的原始证据、遗留问题。
