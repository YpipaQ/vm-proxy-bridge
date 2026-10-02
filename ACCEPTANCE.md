# 验收对照（HANDOFF §8 DoD）

> 最后更新：**2026-10-01**（注入层与自启动取缔后）。测试总数 **104**；测试规模 **12 文件 / 984 行**；`./test.sh` 一条命令复跑。
> 复核边界：本文数字取自 `spike/docs-plan-20261001.md` §3（Lead 已复核的落地数字）；**未在本轮重跑 `./test.sh`**（它会覆盖安装）。

## 1. 现行 DoD

| # | DoD | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | **防回流**：注入层与自启动不得复活 —— 已删模块既不许有文件、也不许还能 `import`；`src/` 里不得再出现 `xsessionrc/inject/guard/rehearse/safe_mode/systemd/autostart/linger/rescue/D1–D4/managed_block` 字样；CLI 不得再注册 `session/guard/rescue/service` 四个动词 | ✅ | `tests/test_no_injection.py`（含参数化：6 个已删模块 × 3 类断言 + src/tests 两处扫描 + 动词表 + `paths/state/manifest` 接口断言） |
| 2 | 卸载/回滚后 dotfile 全部还原到安装前 sha256 | ✅ | `tests/test_uninstall.py`（6 项）：逐字节比对 + 新建文件消失 + 无清单也能处理 |
| 3 | 日志/状态/备份逐项 `ls -l` 对齐 DESIGN §4.1（路径、0600/0700、轮转） | ✅ | `tests/test_core.py` 轮转边界 |
| 4 | `doctor` / UI 回归全绿；退出码语义符合 DESIGN §7（**0/1/2/4**，`3` 已废除） | ✅ | `tests/test_doctor.py`（11 条钉死"没启用不是故障"口径）；`tests/test_cli_smoke.py` 只读动词；`tests/test_ui_smoke.py`；v1 `test-proxy-ui.py` 31 项 ALL PASS（v1 未改动） |
| 5 | 系统代理通道回归：`sysproxy on/off` 可逆、`proxy chrome` 直通 argparse | ✅ | `tests/test_sysproxy.py`（12 条）；`proxy chrome` 在 `main()` 里被拦截（否则 `--user-data-dir=…` 会被吞） |
| 6 | `src/` 里不得再有 `xsessionrc/inject/guard/rehearse/safe_mode` 的**可执行引用** | ✅ | 已实跑 `grep -rn 'xsessionrc\|inject\|guard\|rehearse\|safe_mode' src/` → **零命中**（与 DoD 1 同源，双保险） |
| 7 | 每阶段结束落盘记忆 + 跑工作区三步 | ✅ | `memory/2026-09-30/proxy-bridge-v2-*.md` 三篇；`memory_query --rebuild/--refresh` + `memory_doctor`（❌0/⚠️0） |
| 8 | 汇报说清"验到哪一层" | ✅ | `SPIKE-P0.md` 每项标注 逻辑层/文件层/设备层/新鲜度层 |

## 2. 已废除的历史 DoD（2026-10-01，仅存史）

| # | 原 DoD（HANDOFF §8） | 处置 |
| --- | --- | --- |
| 1 | 事故回归：旧块在真实循环语义下被判失败，且该用例长期保留 | **已废除**：注入层取缔，`tests/test_inject.py` 已删；改由 DoD 1 的防回流断言接管 |
| 3 | D4 假时钟三时序全过；`safe_mode` 期间 `session on` 拒绝 | **已废除**：`tests/test_guard.py`、`tests/test_session_e2e.py` 已删 |
| 6 | 真机重登录一次（注入生效且不死）；TTY 救援演练 | **已废除**：不再有任何注入，`proxy rescue` 已删除（实测 rc=2） |

## 3. 分层证据摘要

- **逻辑层**：**104 项**单测/集成测试通过（0 skipped / 0 xfail），含真实 8 并发转发、`doctor` 口径 11 条、防回流永久断言
- **文件层**：卸载后 sha256 逐字节一致；块副本"只改一处"硬校验（v1 历史证据，保留）
- **设备层**：N/A（本项目不直接读写块设备）
- **新鲜度层**：**浏览器代理规则表**为 2026-10-01 现场实测（矩阵 33 例，PASS 8 / FAIL 0 / INFO 25，
  原始结果 `spike/browser-proxy-matrix/evidence/20261001-*`）；`proxy doctor` 每次现场探测上游可达性

## 4. 平台限制（2026-09-30 实测；2026-10-01 据此定案）

- 本机是 **SysV init + elogind**，**没有 systemd 用户管理器** → 用户级 timer/service 不会被执行
- 因此**没有可靠常驻看门狗通道**（**已废除**：看门狗随注入层取缔），`~/.config/systemd/user/proxy-bridge-{forward,guard}.{service,timer}`
  永远不会运行 → **自启动整体取缔**（三单元已删除，备份在 `~/backup/files/proxy-bridge-v1/legacy-backup/units-20261001/`）
- 桌面 autostart 是当时设想的唯一可行通道，但用户明确不要启动项 → **注入层在本机保持不可用**，
  2026-10-01 进一步**正式取缔**（浏览器改走「系统代理 + 桌面身份」，见 README 规则表）

## 5. 仍未做（留白，需用户拍板或在场）

1. **PAC 通道待查**（非阻塞）：`gsettings mode=auto` + `autoconfig-url` 下 PAC 脚本被反复下载却从不被采用，
   原因未定；因手工代理/系统代理/环境变量三条通道已验证可用，不影响交付
2. 转发器安全加固（无鉴权回环 TCP）、`no_proxy` 内网段外发脱敏
3. `~/桌面/密钥文档.txt`（疑似凭据）需用户本人确认
