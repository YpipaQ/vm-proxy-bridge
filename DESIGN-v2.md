# proxy-bridge v2 设计书 —— 从脚本升级为软件（含注入层四道防线）

## 变更记录（2026-10-01）：注入层与自启动取缔

**结论：注入层与自启动已全部取缔；本文中一切与注入相关的章节仅存史，不再是待建项。**

| 取缔项 | 三条理由 | 证据指针 |
| --- | --- | --- |
| **注入层**：删 `inject/guard/rehearse/session/desktop/sysd` 六模块；移除 D1–D4 防线、死手开关、预演、救援、会话确认 | ① 本机无 systemd 用户管理器 → 看门狗通道永不 healthy → `session on` 本就硬拒绝；② 2026-09-30 登录循环事故由它引起；③ 浏览器根本不需要它 | ①②见本文 §6（转发器与守护进程）与 §13（风险登记），以及 [`MODULES.md`](MODULES.md) §6 平台事实；③见 `spike/browser-proxy-matrix/` 的规则表与真机端到端（原始证据 `spike/browser-proxy-matrix/evidence/20261001-*`） |
| **自启动**：删 `~/.config/systemd/user/proxy-bridge-{forward,guard}.{service,timer}` | 本机没有 systemd 用户管理器，这些单元永远不会运行 | 同上 §6 平台事实；原单元备份于 `~/backup/files/proxy-bridge-v1/legacy-backup/units-20261001/` |

**保留**：转发器、系统代理开关、`proxy chrome`、终端环境变量 `env.sh`、`proxy on/off` 总开关、卸载/迁移/体检/支持包/Tk 界面。
**规模变化**：模块 26 → **21**，总行数 3335 → **2138**；测试 18 文件/1205 行 → **12 文件/984 行**（`./test.sh` = 104 passed）。
**退出码**：`3`（safe_mode）已废除，现为 `0 OK / 1 FAIL / 2 DOCTOR_FAILED / 4 USAGE`。

> 执行细则与逐文档改法见 `spike/docs-plan-20261001.md`；本文下方带 `> 已废除（2026-10-01）` 标注的章节**仅存史**，
> 保留目的是记录事故教训与决策过程，不是施工依据。

---

> **结论（12 行内）**
>
> **⚠️ 以下第 1、2、4、5 条已废除（2026-10-01）**：注入层（含四道防线与死手开关）与 systemd 自启动
> 已取缔，见顶部「变更记录」；第 3 条（XDG 分家）仍然有效。原文保留，仅存史。
>
> 1. 保留 `~/.xsessionrc` 注入，但它不再是"手写一行就上"的操作：由软件生成、带版本戳与校验和，且**必须**在死手开关（watchdog）就绪后才允许写入。
> 2. **（已废除）**运行时形态：Python 3.13 **纯标准库**软件包（`proxybridge/`）+ `proxy` 同名 CLI + ~~`systemd --user` 托管的转发器与看门狗~~（自启动已取缔）；bash 只保留一个兼容壳。
> 3. 状态/配置/日志**全部按 XDG 分开**：配置 `~/.config/proxy-bridge/`、数据与备份 `~/.local/share/proxy-bridge/`、**日志与运行状态 `~/.local/state/proxy-bridge/`**、缓存 `~/.cache/proxy-bridge/`。旧的 `~/.proxy.log`、`~/.proxy-forward.log`、`~/.proxy-forward.pid` 迁走后清理。
> 4. **（已废除）**防线四层：**D1 静态检查** → **D2 行为自检**（复刻 Xsession run-parts 语义）→ **D3 全链路预演**（`unshare -rm` 沙箱里跑真实 `/etc/X11/Xsession`）→ **D4 死手开关**（注入点打卡 + 会话确认，超时自动摘块 + 通知 + 审计）。
> 5. **（已废除）**任何一层不过，`session on` 拒绝执行；`unshare` 不可用的机器降级但需显式 `--accept-degraded`。

---

## 1. 为什么必须升格（现状问题清单）

| # | 现状 | 后果 |
| --- | --- | --- |
| 1 | 状态散在 8 个 dotfile（`.proxy_env`/`.proxy.conf`/`.proxy.log`/`.proxy-forward.log`/`.proxy-forward.pid`/`.xsessionrc`/autostart/`.profile`） | 没有单一事实来源，卸载靠人记 |
| 2 | 注入无"死手开关" | 2026-09-30 登录循环：人不在电脑前就救不回来 |
| 3 | 测试用 `dash -c 'set -e; . 文件'` 模拟登录链 | 语义失真，漏掉致命维度（真实事故根因） |
| 4 | 转发器 = `nohup` + pidfile | 无自动重启、无优雅退出、日志无轮转 |
| 5 | 无事务/无备份清单 | 写到一半被杀会留半残状态 |
| 6 | bash 700+ 行 + Python 混写 | 难以测试、难以演进 |

## 2. 目标 / 非目标

**目标**：单入口、可安装/可卸载、状态可查、日志可轮转可打包、~~注入改动可预演可自动回滚~~（**已废除**：注入层取缔）、单写者并发安全、零运行时依赖。

**非目标**：不做全局透明代理（不碰 iptables/root 网络栈）；不自动联网更新；不接管浏览器以外的 GUI 程序（~~注入层已天然全局~~ **已废除**：注入层不存在了，覆盖面改由"系统代理 + 桌面身份"或"环境变量"决定，见 §1.1 与 README「系统代理」）；不替换 lightdm。

## 3. 架构

> **已废除（2026-10-01）**：下面这张是设计期架构图，其中 `inject.py / guard.py / desktop.py / sysd.py` 与
> `systemd --user` 均已删除，**仅存史**；现行架构见紧随其后的第二张图与 [`MODULES.md`](MODULES.md) §1。

```
             ┌──────────────── proxy (console_script) ────────────────┐
             │  cli.py  verbs → 只做参数解析/输出，不做副作用            │
             └───────┬───────────────────────────────────────┬────────┘
                     │                                       │
             core 层（纯函数/可单测）                  进程层（长驻）
   ┌─────────────────┴───────────────┐        ┌──────────────┴──────────────┐
   │ config.py  配置合并/校验         │        │ tunnel.py   TCP 转发器       │
   │ state.py   状态机/事务/锁        │        │  ← systemd --user service   │
   │ inject.py  Xsession 注入/还原    │        │ guard.py    死手开关         │
   │ guard.py   打卡/确认/超时判定    │        │  ← systemd --user timer     │
   │ desktop.py 启动器接管（v2.1）    │        └─────────────────────────────┘
   │ backup.py  备份/还原/保留策略    │
   │ logs.py    结构化日志+内部轮转   │
   │ probe.py   上游/端口/出口 IP     │
   │ sysd.py    unit 安装/查询        │
   └─────────────────────────────────┘
                     │
             ui.py（Tk 主界面，只发命令不自己改文件）
```

**现行架构（2026-10-01 实测状态：21 模块 / 2138 行）**：

```
             ┌──────── proxy（~/.local/bin/proxy → entry.py 生成的包装）────────┐
             │  cli.py  verbs → 只做参数解析/输出（chrome 走 argparse 前直通）   │
             └───────┬──────────────────────────────────────────┬───────────┘
                     │                                          │
             core 层（纯函数/可单测）                     进程层（长驻）
   ┌─────────────────┴───────────────┐        ┌──────────────┴──────────────┐
   │ config.py   配置合并/校验        │        │ tunnel.py   TCP 转发器       │
   │ state.py    状态机/事务/锁       │        │  （前台 `proxy forward run`，│
   │ backup.py   备份/还原/保留策略   │        │    自启动已取缔）            │
   │ logs.py     结构化日志+内部轮转  │        └─────────────────────────────┘
   │ probe.py    上游/端口/出口 IP    │
   │ sysproxy.py 系统代理(gsettings)  │
   │ power.py    总开关：env+入口+转发 │
   │ entry.py    ~/.local/bin/proxy   │
   │ doctor.py   只读体检（现行口径见 §7）│
   │ ctl.py      串行动作队列         │
   └─────────────────────────────────┘
                     │
             ui.py（Tk 主界面，只发命令不自己改文件）
```

分层硬规矩：**只有 core 层能写文件**；CLI/GUI 只调 core；长驻进程只写自己的日志与状态。写操作一律走 `state.tx()` 事务 + `flock`。

## 4. 目录与文件布局（日志到底放哪 —— 本节是重点）

### 4.1 运行期路径

| 路径 | 来源 | 内容 | 权限 | 轮转/保留 |
| --- | --- | --- | --- | --- |
| `~/.config/proxy-bridge/config.toml` | `XDG_CONFIG_HOME` | 主配置（上游、端口、超时、保留策略）。**只读**，应用不改写 | 0600 | 用户自己管 |
| `~/.config/proxy-bridge/config.d/*.json` | 同上 | CLI `config set` 写的覆盖层（JSON，应用可写） | 0600 | 保留 5 份快照 |
| `~/.config/proxy-bridge/env.sh` | 同上 | 生成的环境变量文件（原 `~/.proxy_env` 的正文） | 0644 | 每次原子替换 |
| `~/.local/share/proxy-bridge/app/` | `XDG_DATA_HOME` | 安装副本（venv + 包），`proxy upgrade` 的目标 | 0755 | 保留上一版 1 份 |
| `~/.local/share/proxy-bridge/backups/<target>/<ts>.<sha8>`（**已废除**：不再备份 `~/.xsessionrc` 与 `.desktop`） | 同上 | `~/.xsessionrc`、`~/.profile`、`~/.bashrc`、被覆盖的 `.desktop` 的备份 | 0600 | 每目标 10 份 或 90 天 |
| `~/.local/share/proxy-bridge/desktop/` | 同上 | 接管后的启动器（唯一写入点，v2.1） | 0644 | 随开关增删 |
| `~/.local/share/proxy-bridge/install-manifest.json` | 同上 | 安装清单：版本、写过的每个 dotfile、备份 id、hash → 卸载依据 | 0600 | 覆盖式 |
| `~/.local/state/proxy-bridge/state.json` | `XDG_STATE_HOME` | 主状态机：`desired_on`/`actual`/`generation`/`guard`/`counters` | 0600 | 原子替换 + 保留 3 份 |
- **日志/状态**：注入块每次被 Xsession 执行时追加一行时间戳（只追加、永不失败；注入层已废除，该文件不再产生）
| `~/.local/state/proxy-bridge/guard.json`（**已废除，2026-10-01 注入层取缔后不再产生**） | 同上 | 死手开关：`armed_at`/`reached_at`/`confirmed_at`/`safe_mode` | 0600 | 覆盖式 |
| `~/.local/state/proxy-bridge/tx/<ts>-<id>.json` | 同上 | 写前事务日志（intent → apply → commit），`proxy repair` 用 | 0600 | 成功后移入 `tx/done/`，保留 50 条 |
| `~/.local/state/proxy-bridge/xsession-reached.log`（**已废除，2026-10-01 注入层取缔后不再产生**） | 同上 | **注入块**每次被 Xsession 执行时追加一行时间戳（只追加、永不失败） | 0600 | 2 MiB × 3 |
| `~/.local/state/proxy-bridge/lock` | 同上 | `flock` 单写者锁（所有变更命令持有） | 0600 | 常驻 |
| `~/.local/state/proxy-bridge/logs/app.jsonl` | 同上 | **结构化事件流**（每命令一条 JSON：ts/level/verb/pid/uid/argv/result/duration/tx_id） | 0600 | 2 MiB × 5 |
| `~/.local/state/proxy-bridge/logs/app.log` | 同上 | 人读日志（app.jsonl 的文本渲染，`proxy log` 读它） | 0600 | 2 MiB × 5 |
| `~/.local/state/proxy-bridge/logs/inject.log` | 同上 | 注入层专用：生成/预演/写入/摘除/校验和、每次改动前后的 hash | 0600 | 1 MiB × 5 |
| `~/.local/state/proxy-bridge/logs/guard.log`（**已废除**：`guard.py` 已删除，注入层取缔后不再产生） | 同上 | 看门狗：打卡、确认、超时判定、自动回滚、safe_mode 进出 | 0600 | 1 MiB × 5 |
| `~/.local/state/proxy-bridge/logs/forward.log` | 同上 | 转发器连接流水（原 `~/.proxy-forward.log`）：`CONN id/#/ts/src→dst/bytes/duration` | 0600 | 4 MiB × 5 |
| `~/.local/state/proxy-bridge/logs/audit.jsonl` | 同上 | 审计：对**本机 dotfile/单元**的每次变更（路径、旧 hash、新 hash、备份 id、触发器） | 0600 | 10 MiB × 5，保留 180 天 |
| `~/.local/state/proxy-bridge/logs/service.log`（**部分已废除**：看门狗已取缔、转发器也不再由 systemd 托管） | 同上 | 转发器/看门狗的进程生命周期（启动、退出码、重启原因） | 0600 | 1 MiB × 5 |
| `~/.local/state/proxy-bridge/support/<ts>-bundle.tar.gz` | 同上 | `proxy support-bundle` 产物（日志+配置+状态，脱敏后） | 0600 | 保留 5 份 |
| `~/.cache/proxy-bridge/probe.json` | `XDG_CACHE_HOME` | 最近一次上游/端口/出口 IP 探测结果（GUI 状态栏读它，避免频繁探测） | 0600 | TTL 60s |

**轮转实现**：不依赖 logrotate（本机没有）。`logs.py` 在每次写前检查 `size >= max_bytes` → `os.replace` 成 `.1`，最多 `backups` 份；JSONL 与文本日志同一策略。
**journald（已废除，2026-10-01）**：~~转发器/看门狗是 systemd 单元~~ 曾设计为同一份输出也进 journal，
`journalctl --user -u proxy-bridge-forward` 可查（双写：文件便于打包外发，journal 便于 `-f` 跟随）；
自启动取缔后转发器不再由 systemd 托管，日志只落文件。

### 4.2 系统集成点（软件会碰的每一个文件，共 6 处）

> **部分已废除（2026-10-01）**：下表是 v2 当初设计的 6 个集成点，其中**只与注入层/自启动相关**的行
> （`~/.xsessionrc`、会话确认 `.desktop`、兜底自启 `.desktop`、systemd 单元）**已随注入层一并取缔**；
> 现行集成点以 `proxy manifest` 的实际清单为准。

| 路径 | 谁写 | 可逆性 |
| --- | --- | --- |
| `~/.xsessionrc`（**已废除**：不再写入） | inject.py，托管块 + 版本戳 + 校验和 | `session off` 逐字节还原；写前备份 |
| `~/.config/proxy-bridge/env.sh` + `~/.proxy_env`（**符号链接**指向它） | core | 删链接即还原；旧引用 `~/.proxy_env` 的脚本不受影响 |
| `~/.profile`、`~/.bashrc` | 托管块（BEGIN/END 标记，不再裸插一行） | 摘块还原；写前备份 |
| `~/.config/autostart/proxy-bridge-confirm.desktop`（**已废除**：不再创建） | 会话确认（必须存在，D4 依赖） | 删文件即还原 |
| `~/.config/autostart/proxy-bridge-forward.desktop`（**已废除**：不再创建） | 兜底自启（systemd 不可用时） | 删文件即还原 |
| `~/.config/systemd/user/proxy-bridge-{forward,guard}.{service,timer}`（**已废除**：三个单元已删除，备份在 `~/backup/files/proxy-bridge-v1/legacy-backup/units-20261001/`） | sysd.py | `service uninstall` |

`chain of custody`：~~以上 6 处全部登记进 `install-manifest.json`（含写入前后 sha256），`proxy uninstall` 按清单逆向还原，`proxy doctor` 校验 hash 是否被外部改过（改了 → 告警并拒绝 `session on`）。~~
（**已废除（2026-10-01）**：现行清单只登记仍存在的集成点，且不再有 `kind="unit"` 这类单元条目。）

## 5. 注入层（保留）的四道防线【已废除，仅存史】

> **已废除（2026-10-01）：注入层取缔，见顶部变更记录；本节仅存史。**
> 下面的 D1–D4 是为"往 `~/.xsessionrc` 写托管块"设计的防线；注入层与它一起被移除，
> 六个模块（`inject`/`guard`/`rehearse`/`session`/`desktop`/`sysd`）已删除。

### D1 静态检查（已废除）
`dash -n` + 禁止词表（`exit|return|exec`）+ 块内**不允许出现 `set -e`**（正则级硬规则，不是靠人记）+ 版本戳/校验和匹配。

### D2 行为自检（已实现，升级为库函数）（已废除）
用 dash 复刻 `/etc/X11/Xsession` 的真实语义：
```
set -e → set +e → source 注入块 → false 探针 → 必须继续执行
```
旧块在此 rc=1（会杀掉整个会话），新块 rc=0。

### D3 全链路预演 `proxy session rehearse`（新增，本机已确认可行）（已废除）
`unshare -rm`（用户+挂载命名空间，本机 `USERNS_OK` 已实测）里造沙箱：
1. （已废除）tmpfs 当临时 HOME，把**待写入的** `~/.xsessionrc` 挂进去；
2. `/etc` 以只读方式绑定，防止预演污染系统；
3. 跑**真实的** `/etc/X11/Xsession`，`USERXSESSIONRC` 指向沙箱文件，`STARTUP=/bin/true`；
4. 同时跑一次"不带注入块"的基线，断言**两次退出码都是 0**；带块的退出码 ≠ 0 或与基线不一致 → 拒绝写入。
这条能抓住 D2 抓不到的间接影响（比如块写坏、权限问题、与 40 号脚本的交互）。（已废除）
`unshare` 不可用时：跳过并明确打印"已降级"，`session on` 需显式 `--accept-degraded`。（已废除）

### D4 死手开关（核心，防的正是"人不在电脑前"）（已废除）
- 通道优先级：① root systemd 单元 + timer（需一次性 sudo，最稳，开机即跑）；② `systemd --user` + `loginctl enable-linger`（本机 `Linger=no`，安装时自动开启）；③ cron `@reboot` + 每分钟（兜底）。
  **（已废除）规则：至少一条通道 healthy，否则 `session on` 拒绝执行。**
- 时序：
  1. （已废除）`session on` 写 `guard.json{armed_at}`，并把**打卡语句**写进注入块（追加 `xsession-reached.log`，`{ ...; } 2>/dev/null || true`，永不返回非零）；
  2. 用户重新登录 → 注入块执行 → 打卡；
  3. 桌面起来后 autostart 跑 `proxy session confirm` → 写 `confirmed_at`；
  4. （已废除）看门狗每 30s 判定：**存在 `reached_at > armed_at` 且 120s 内无对应 `confirmed_at`** → 判定"会话起来了但死了" → 自动摘块（只摘托管块，其余内容逐字节保留）+ 备份 + `notify-send` 告警 + 置 `safe_mode=true`（此后 `session on` 拒绝，直到 `proxy session on --reset-guard`）+ 写 `guard.log`/`audit.jsonl`。
- （已废除）救援路径（不依赖桌面）：切到 TTY（Ctrl+Alt+F3）或 ssh 一条命令 `proxy rescue`（= `session off --force`，先摘块再摘自启）。README 顶部放"急救卡"。

## 6. 转发器与守护进程

> **部分已废除（2026-10-01）**：本节中"转发器"仍然有效；**systemd 单元与"守护进程"部分已废除**
> ——本机没有 systemd 用户管理器（见 §13 与 [`MODULES.md`](MODULES.md) §6），自启动三个单元已删除。
> 现在转发器就是前台命令 `proxy forward run`。

- `proxybridge/tunnel.py`：现有纯 TCP 透传逻辑平移，新增：连接计数、每连接日志、上游健康探测（30s，失败只在日志与状态里体现，不自动切模式）、`SIGHUP` 重载配置、退出码语义、`SIGTERM` 优雅关闭（等在途连接 ≤5s）。
- `proxy-bridge-forward.service`（**已废除**：自启动取缔，单元已删除；原设计为 `ExecStart=... forward run`、`Restart=always`、`RestartSec=1`、`StartLimitBurst=5`、`StandardOutput=append:<state>/logs/service.log`、`BindReadOnlyPaths` 收紧、`NoNewPrivileges=yes`）。
- 单实例：systemd 唯一 + 状态里的 pid 双重校验（旧 pidfile 标记为 legacy）。（**已废除**：自启动取缔后不再有 systemd 唯一性保证。）
- 兜底：若 `systemctl --user` 不可用，退回 `~/.config/autostart/proxy-bridge-forward.desktop` + `nohup`（v1 行为，日志仍走新目录）。（**已废除（2026-10-01）**：自启动整体取缔，不再有 autostart 兜底。）

## 7. CLI 命令面（保持与 v1 同名，肌肉记忆不废）

> **部分已废除（2026-10-01）**：下表中 **注入 / 守卫 / 自启 / 服务** 四类已随注入层一并删除；
> 其余类别以本节末尾的**现行命令面**为准。

| 分类 | 命令 | 说明 |
| --- | --- | --- |
| 开关 | `proxy on \| off \| toggle` | 唯一总开关（env.sh + 转发器 + 自启） |
| 观测（**部分已废除**） | `status [--json]`、`doctor [--json] [--fix]`、`verify [--browser]`、`log [-f] [--since]`、`support-bundle` | doctor 退出码：0 通过 / 2 有失败项 / ~~3 safe_mode~~（已废除） |
| 注入（**已废除**） | `session on \| off \| status`、`session rehearse`、`session confirm` | `on` 需四道防线全过 + 守卫通道 healthy |
| 守卫（**已废除**） | `guard status \| test \| arm \| disarm` | `test` 立即跑一遍超时判定逻辑 |
| 转发 | `forward on \| off \| restart \| status \| tail` | systemd 优先 |
| 环境 | `env on \| off \| show \| path`、`exec -- cmd...` | `exec` 供启动器/自救 |
| 自启（**已废除**） | `autostart on \| off \| status` | unit 与兜底桌面项统一管理 |
| 服务（**已废除**） | `service install \| uninstall \| status \| logs` | systemd 单元生命周期 |
| 维护 | `backup list \| restore <id>`、`repair`、`migrate`、`uninstall [--purge]`、`version` | `migrate` 处理 v1 → v2 路径搬迁 |
| 界面 | `ui` | Tk 主界面，只调 CLI/core |

退出码统一：`0` 成功、`1` 一般失败、`2` 体检失败、`4` 用法错误
（`3` = 需人工介入 / safe_mode **已随注入层废除**，实测不再返回）。所有变更类命令幂等，且都写 `tx` + `audit`。

**现行命令面（`proxy --help` 实测，13 个）**：
`{version,paths,status,doctor,on,off,uninstall,support-bundle,migrate,manifest,ui,sysproxy,entry,forward}`

- `sysproxy on|off|status`：系统代理开关（GNOME gsettings 通道，可逆）——**替代原来的注入通道**；
- `entry install|uninstall|status`：稳定入口 `~/.local/bin/proxy`（新增）；
- `forward run|status|tail`：转发器前台运行 / 只读状态 / 跟随日志；
- **`chrome` 不在 help 里**：它在 argparse 之前被拦截（必须如此，否则浏览器参数会被吞），不是"没有这个命令"。

## 8. GUI / 通知 / 面板

- `ui.py`：现 Tk 界面重构为"状态模型 + 命令队列"（已有雏形），新增：守卫状态、注入块校验和、日志窗口（读 `logs/app.log`）、`support-bundle` 按钮、危险操作二次确认。
- 通知：`notify-send`（本机有）用于 ~~"注入已生效/已回滚/safe_mode~~ / 转发器掉线"。（**已废除**：注入相关通知随注入层删除）
- 面板：本机**没有** genmon 插件；先不做常驻面板图标，改为可选 `proxy toggle` 绑定快捷键或 XFCE 启动器（零依赖）。要面板常驻再单独评估装插件。

## 9. 打包、安装、升级、卸载

- `pyproject.toml`（`requires-python >= 3.11`，运行时 `dependencies = []`；`[project.optional-dependencies] dev = ["pytest","ruff"]`）。
- 安装：`python3 -m venv ~/.local/share/proxy-bridge/app/venv && pip install --no-index .`（离线可装），`~/.local/bin/proxy` 指向 venv 入口；`pipx` 本机没有，不依赖它。
- 版本：`0.1.0` 起，`proxy version --json` 输出 `{version, git_sha, install_path, manifest_hash}`。
- 升级：装到 `app/new/` → 通过 `proxy repair` 走一次预演 → 原子切换 `app/current` 符号链接 → 失败自动回退上一版。
- 卸载：按 `install-manifest.json` 逆序还原 6 个集成点（先摘注入块、再摘单元），`--purge` 连 state/logs 一起删；卸载前自动打一份 `support-bundle`。

## 10. 迁移（v1 → v2，一次性）

1. `proxy migrate --dry-run`（**已废除**：不再改写托管块）：列出将要移动/改写的东西（旧日志、pidfile、`.proxy.conf`→`config.toml`、`.proxy_env`→`env.sh`+符号链接、`.profile`/`.bashrc` 裸行→托管块）。
2. 备份 → 执行 → 校验：`doctor` 全绿 + `verify` 通过 + `~/.xsessionrc` 若已挂载则校验和必须与 v2 生成的一致（不一致则摘除并提示重新 `session on`）。（**已废除（2026-10-01）**：不再有 `session on`，迁移也不再碰 `~/.xsessionrc`。）
3. 回滚：`proxy migrate --rollback`（用 `tx` + 备份还原）。
4. 旧日志搬进 `logs/legacy/` 而非删除；`~/.proxy.log`、`~/.proxy-forward.log`、`~/.proxy-forward.pid` 清理。

## 11. 测试策略

| 层 | 用例（必须包含的回归） |
| --- | --- |
| 单元 | 配置合并优先级；状态机非法迁移；锁竞争；轮转边界（0/1/满）；TOML 读取坏配置 |
| 注入（**已废除**：用例已随模块删除） | **事故回归**：旧块在真实循环语义下必须被判失败；新块通过；`strip_block` 还原后与原文件 sha256 相同；块内出现 `set -e` 被 D1 拦截 |
| 预演（**已废除**：用例已随模块删除） | `unshare` 沙箱里带块/不带块基线一致；`unshare` 不可用时的降级路径 |
| 守卫（**已废除**：用例已随模块删除） | 用假时钟（依赖注入，不 mock 系统）跑时序：打卡无确认→回滚；确认早到→不误杀；`safe_mode` 后 `session on` 必须拒绝 |
| 转发器 | 本机 echo server 透传、并发连接、SIGTERM 优雅关闭、上游不可达时的行为与日志 |
| 集成 | 隔离 HOME 全流程：`on → status → verify → off → uninstall` 后 dotfile 与安装前逐字节一致 |
| 防回流（**现行**） | `tests/test_no_injection.py`：已删模块既不许有文件也不许能 import；`src/` 与 `tests/` 里不得再出现 `xsessionrc/inject/guard/rehearse/safe_mode/systemd/autostart/linger/rescue/D1–D4/managed_block` 字样；CLI 不得再注册 `session/guard/rescue/service` |
| 手工验收（**已废除**：真机重登录演练项已删） | 真机重登录一次确认注入生效；TTY 里跑一次 `proxy rescue` 演练 |

> 现状：测试 **12 文件 / 984 行**，`./test.sh` = **104 passed**（0 skipped / 0 xfail）；删掉的 9 个测试文件见 `spike/docs-plan-20261001.md` §3。

## 12. 实施阶段

> **P0、P2 整阶段与 P3 的部分交付已废除（2026-10-01）**：注入层与自启动取缔后，P0 的"看门狗通道矩阵"、
> P2 全部、P3 的 systemd 服务不再有交付物。此表仅存史。

| 阶段 | 交付 | 验收 | 回滚 |
| --- | --- | --- | --- |
| P0 spike（0.5d）（**已废除**：看门狗通道矩阵随自启动取缔而作废） | `unshare` 预演可行性报告、systemd/linger/cron 通道可用性矩阵 | 三条通道各自能跑一次空转判定 | 无（不改盘） |
| P1 骨架（1–2d） | 包结构、config/state/logs/lock/tx、`status`/`doctor`/`log` | 单测过；日志落在正确 XDG 路径 | 删目录 |
| P2 注入层（1–2d）（**已废除**：整阶段取消） | inject/guard/D1–D4、watchdog 单元、`rescue` | 事故回归用例过；假时钟时序用例过；**真机重登录一次** | `session off` |
| P3 转发器+GUI（1d）（**systemd 服务部分已废除**） | systemd 服务、日志计数、Tk 重构 | `forward status` 与 journal 一致；GUI 全流程 | 退回 nohup 兜底 |
| P4 打包/迁移（0.5–1d） | pyproject、manifest、`migrate`/`uninstall`、急救卡文档 | 隔离 HOME 端到端 + 卸载后 dotfile 逐字节还原 | `migrate --rollback` |

## 13. 风险登记

> **部分已废除（2026-10-01）**：前三条与注入层/自启动相关，随取缔一并失效（保留以记录当时判断）；
> 后四条仍然有效。

| 风险 | 缓解 |
| --- | --- |
| 再次搞崩登录（**已废除**：注入层取缔后不再有该风险面） | D2+D3 预演 + D4 超时自动摘块 + `safe_mode` 阻断重试 + TTY 救援卡 |
| 看门狗本身没起来（linger 未生效/无 cron）（**已废除**：自启动取缔） | 安装时强制校验通道 healthy，否则拒绝 `session on`；doctor 持续监测 |
| 其他工具改写 `~/.xsessionrc`/`.profile`（**已废除**：不再写这两个文件） | 每次启动校验 hash，不符则告警并拒绝注入；托管块标记保证只摘自己的 |
| 转发器挂了但 env 指向它 → 断网 | doctor 风险项 + `probe.json` 探针；`proxy off` 一键清（**自启动已取缔，需手动 `proxy forward run`**） |
| 本地端口被无鉴权访问 | 强制回环绑定（已有）；文档标注"本机进程可直用"；不做局域网暴露 |
| 日志无限增长 | 内部按 size×count 轮转 + 保留天数；`support-bundle` 只打包必要文件 |
| 零依赖约束下的 TOML 写入 | 配置只读、覆盖层用 JSON，避免自己写 TOML 序列化 |

## 14. 需要你拍板的 5 件事

> **第 1 条已废除（2026-10-01）**：看门狗通道随注入层取缔，不再需要拍板；其余按现状记录。

1. **看门狗通道（已废除）**：给不给一次性 `sudo -n` 装 root systemd 单元（最稳、开机即跑）？还是只用 `systemd --user` + 开 linger（无需 root，但用户管理器生命周期略弱）？
2. **依赖红线**：运行时**零第三方依赖**（纯标准库）、测试才用 pytest——可以吗？
3. **`~/.proxy_env`**：保留为指向 `~/.config/proxy-bridge/env.sh` 的符号链接（兼容你现有引用），还是彻底搬走？
4. **面板指示器**：本机没有 genmon 插件，先不做常驻图标（只用通知 + Tk 界面），可以吗？
5. **代码位置**：继续在 `~/project/proxy-bridge` 开发、安装到 `~/.local/share/proxy-bridge/app/`（venv），还是挪进 workspace 的 `projects/`？

拍板后我按 P0 → P4 出代码；P0 只读不改盘。
