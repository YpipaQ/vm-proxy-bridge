# proxy-bridge v2 施工交接书（冷启动专用）

> **给一个完全没有上下文的新会话。** 读完这一页就能开工；方案细节在同目录 `DESIGN-v2.md`。
> 本文件是"施工总纲"，`DESIGN-v2.md` 是"设计全文"，两份都为 v2 施工服务，冲突时以本文件的操作性条款为准并回来改本文。
> 最后更新：2026-09-30 22:20（基线见 §4）；**2026-10-01 改版**：注入层与自启动取缔 →
> §0 任务目标、§2 决策 1、§5 第 1/2/5/10 条、§7 的 P0/P2、§8 部分 DoD、§10 全部已标"已废除"（仅存史）。

---

## 0. 一句话任务

把 `~/project/proxy-bridge`（**此句描述 v2 开工前的起点**：当时是 700+ 行 bash + 250 行 Python 的散装脚本，1662 行；
**现状（2026-10-01）：21 个 Python 模块 / 2138 行，104 项测试全绿**）升级成一个正经软件：
运行时用 Python 3.13 纯标准库，配置/状态/日志按 XDG 分家，转发器交给前台命令 `proxy forward run`；
分 P0→P4 施工，每阶段汇报验收。

> **变更（2026-10-01）：注入层与自启动已取缔。** 原文要求"保留 `~/.xsessionrc` 注入，并在四道防线
> （D1 静态 / D2 行为自检 / D3 全链路预演 / D4 死手开关）护航下才允许写入" —— **该要求已作废**：
> 六模块（`inject/guard/rehearse/session/desktop/sysd`）已删除，自启动三个 systemd 单元也已删除。
> 理由与证据见 [`DESIGN-v2.md`](DESIGN-v2.md) 顶部「变更记录（2026-10-01）」。
> 本文件里所有与注入/重登录/TTY 救援有关的施工项与验收项**已废除**，仅存史。

## 0.1 开场提示词（直接粘给新会话）

```
读 /home/ypipaq/project/proxy-bridge/HANDOFF-v2.md（施工交接书）和同目录 DESIGN-v2.md（方案全文），
按交接书 §2 先问我 5 个决策，拿到答案后从 P0（只读 spike）开始施工。
每个阶段结束按 §7 的验收项汇报"验到哪一层"，不要一次做完 P0–P4。
当前系统是好的（转发器在跑、无注入层），未经我同意不要改运行态。
```

## 1. 冷启动阅读顺序（先只读，别急着动手）

| 顺序 | 文件 | 为什么读 |
| --- | --- | --- |
| 1 | 本文 `~/project/proxy-bridge/HANDOFF-v2.md` | 施工总纲、红线、验收 |
| 2 | `~/project/proxy-bridge/DESIGN-v2.md` | 架构、XDG 布局、防线、命令面、排期 |
| 3 | `~/project/proxy-bridge/README.md` | v1 现状、三层接入、风险与回滚 |
| 4 | `~/project/proxy-bridge/proxy`（758 行）、`proxy-forward`（250）、`proxy-ui.py`（537）、`test-proxy-ui.py`（117） | 要重构/平移的现有实现 |
| 5 | `/home/ypipaq/DeepSeek-Harness/memory/2026-09-30/proxy会话注入事故.md` | 2026-09-30 登录循环事故与教训（**历史存档**：注入层已于 2026-10-01 取缔，不必再"做注入层前必读"） |
| 6 | `/home/ypipaq/DeepSeek-Harness/AGENTS.md` | 工作区工作方式与落盘规则（交付前实跑、单写者、批量落盘…） |

## 2. 先问 5 个决策（没有答案不要写代码）

> **决策 1 已取缔（2026-10-01）**：看门狗通道随注入层与自启动一并取缔，不再需要拍板。
> 其余决策见各行末尾标注。

| # | 决策 | 选项 | 建议默认 | 影响 |
| --- | --- | --- | --- | --- |
| 1 | 看门狗通道（**已取缔，2026-10-01**：注入层与自启动取缔，此项不再需要拍板） | ① root systemd 单元（需一次性 `sudo -n`）② `systemd --user` + `loginctl enable-linger`（当前 `Linger=no`）③ cron `@reboot`（`cron.service` 已 enabled） | ① 最稳；退而求其次 ② | 决定 D4 死手开关的可靠性；**无 healthy 通道则 `session on` 必须拒绝执行** |
| 2 | 依赖红线 | 运行时纯标准库 / 允许第三方 | 纯标准库 | 决定配置序列化、日志、测试框架的写法 |
| 3 | `~/.proxy_env` | 留符号链接指向 `~/.config/proxy-bridge/env.sh` / 彻底搬走 | 留符号链接 | 你现有脚本/终端若引用它，搬走会断（**现状**：已彻底搬走，`~/.proxy_env` 由 v1 备份保管） |
| 4 | 面板常驻指示器 | 不做 / 装 `xfce4-genmon-plugin` | 不做（本机没有该插件） | 只影响观感，用 `notify-send` + Tk 界面替代 |
| 5 | 代码位置 | 继续 `~/project/proxy-bridge`（安装到 `~/.local/share/proxy-bridge/app/`）/ 挪进 workspace `projects/` | 继续原地 | 决定文档与相对链接的写法（**现状**：代码仍在 `~/project/proxy-bridge`，装到 `.venv-dev/`） |

## 3. 环境事实（2026-09-30 实测，别再重新猜）

| 项 | 事实 |
| --- | --- |
| 系统 | Debian GNU/Linux 13 (trixie)，XFCE，X11（`XDG_SESSION_TYPE=x11`） |
| Python | `/usr/bin/python3` = **3.13.5**，`venv`/`sqlite3`/`tomllib` 可用；**没有 pipx** |
| systemd | 2026-09-30 记录：`systemctl --user` = running；`Linger=no`；`loginctl` 可用。**2026-10-01 更正**：本机实际**没有 systemd 用户管理器**（SysV init + elogind）→ 用户级 timer/service 永远不会执行 → **自启动方案整体不可用，自启动已取缔**；权威表述见 [`MODULES.md`](MODULES.md) §6 |
| 权限 | **`sudo -n` 免密可用**；DSH 文件策略 danger-full-access、审批提示被禁用（**不要请求 `sandbox_permissions`**） |
| 命名空间 | `unshare -rm` **可用**（D3 全链路预演在本机走得通） |
| 工具 | 有 `flock` `notify-send` `systemd-analyze` `update-desktop-database` `desktop-file-validate`；**没有** `logrotate`、`pipx`、`genmon`、PATH 里的 `cron`（但 `cron.service` 已 enabled，二进制在 `/usr/sbin`） |
| 磁盘 | `/` 99G，已用 21G（余 73G，23%） |
| 网络 | 客户机 `192.168.18.129/24`，网关 `192.168.18.2`，宿主代理 **`192.168.18.1:7897`（实测可达）**，本地转发端口 `127.0.0.1:7897` |
| XDG | 默认 `~/.config`、`~/.local/share`、`~/.local/state`、`~/.cache`（未被自定义） |
| 登录链 | lightdm → `/etc/lightdm/lightdm.conf`(`session-wrapper=/etc/X11/Xsession`) → **`/etc/X11/Xsession`（第 9 行 `set -e`；122–126 行 `set +e; for f in Xsession.d/*; do . $f; done; set -e`）** → `40x11-common_xsessionrc` source `$USERXSESSIONRC`(=`~/.xsessionrc`) → `99x11-common_start` `exec $STARTUP`；会话类型 `Xsession default` |

## 4. 开工前基线（先核对，别假设）

> **本节是 2026-09-30 的历史基线，仅存史。** 当时用的是 v1 脚本命令（`session-status`、`bash -n proxy` 等），
> 这些命令与 `~/.xsessionrc` 检查**已随注入层取缔而作废**；现行复核命令见下方「4.0 现行复核」。

### 4.0 现行复核（2026-10-01 口径，用 v2 命令）

```bash
cd ~/project/proxy-bridge
.venv-dev/bin/proxy doctor        # 期望：rc=0，逐项 ✓（"没启用不是故障"）
.venv-dev/bin/proxy status        # 期望：desired_on / actual 一行
.venv-dev/bin/proxy forward run & # 起转发器（前台跑）
.venv-dev/bin/proxy forward status | head -1   # 期望：listening
.venv-dev/bin/proxy sysproxy on   # 系统代理 → 127.0.0.1:7897（可逆）
.venv-dev/bin/proxy sysproxy off  # 还原 mode=none
```

**doctor 口径**（已用 `tests/test_doctor.py` 11 条钉死）："**没启用不是故障**"—— 未起转发器 / 未设系统代理 /
无 `*_proxy` / env.sh 未创建 → 一律 ✓；只有**真不一致**（系统代理指向别处、转发器在跑但 env.sh 没了、
`*_proxy` 指向别处、上游不可达）才 ⚠️/❌。

### 4.0.1 历史基线（2026-09-30 22:20，仅存史）

```bash
cd ~/project/proxy-bridge
proxy doctor          # 期望：退出码 0，含「接入块行为自检：不会污染 Xsession 的 set -e」
proxy verify          # 期望：HTTP 200 + 出口 IP 已切换 + 转发器新增 CONN
proxy session-status  # 期望：系统代理接入 OFF（~/.xsessionrc 无托管块）
bash -n proxy         # 期望：语法 OK
ls -l ~/.xsessionrc   # 期望：No such file（注入未挂载）
```

| 项 | 基线值（2026-09-30 22:20） |
| --- | --- |
| 转发器 | 运行中（当时 PID 4271，`127.0.0.1:7897 → 192.168.18.1:7897`）；**PID 会变，看 `forward status`** |
| `~/.xsessionrc` | **不存在**（当时叫"注入 OFF"；现在是永久状态——不会再写入） |
| `~/.proxy_env` | 存在，指向 `127.0.0.1:7897`；`~/.proxy.conf` 里 `MODE="forward"` |
| v1 脚本补丁 | `SESSION_BLOCK` 结尾不再 `set -e`（54 行）；`session_selftest()`（129 行）；`session-on` 行为自检拦截（187 行）；`doctor` 含行为自检项（533 行附近） |
| 已修隐患 | `~/.profile` 的 `[ -f ] && .` 已改 `if …; then …; fi` |
| 测试 | `python3 test-proxy-ui.py` → ALL PASS（31 项） |
| 工作区体检 | `memory_doctor.py` → ❌0 / ⚠️0 |

### 4.1 施工中状态更新（2026-09-30 22:37，P0 期间由本会话改动，上表为历史基线）

> **仅存史（2026-10-01）**：本节记录 P0 期间的临时状态与回滚手段，其中"回滚到 v1 脚本"的路径
> 依赖已被替换的 `~/project/proxy-bridge/proxy`（现在是 v2 生成的入口包装，v1 本体在
> `~/backup/files/proxy-bridge-v1/before-optimize-20260930/proxy`）。

| 项 | 现在的事实 | 回滚方式 |
| --- | --- | --- |
| 转发器 | **已停**（用户授权"先规划下载→关桥→删文件"：`proxy off`，PID 4271 已退） | `~/backup/files/proxy-bridge-v1/before-optimize-20260930/proxy` 需先补 `~/.proxy.conf` 才回到 forward 模式（v1 历史路径） |
| `~/.proxy_env` | **已删除**（用户决策 3=彻底搬走） | `cp ~/proxy-v1-backup-*/\.proxy_env ~/` |
| `~/.config/proxy-bridge/env.sh` | **已建**（0644，正文 = 原 `.proxy_env` + 一行来源注释） | 删除即可 |
| `~/.bashrc` / `~/.profile` | 引用改为**执行时解析 shim**：`env.sh` 在就用它，否则回退 `~/.proxy_env`（不会因文件缺失返回非零） | `cp ~/proxy-v1-backup-*/.bashrc ~/`（同上 `.profile`） |
| 自启项 | `~/.config/autostart/proxy-forward-autostart.desktop` → `.disabled`，并已移入 trash | 从 `~/trash/proxy-bridge-v1-20260930/` 拿回并去掉 `.disabled` |
| 旧文件 | `~/.proxy.conf`/`.proxy.log`/`.proxy-forward.log`/`.xsessionrc.bak.*`/`.xsession-errors.old` → `~/trash/proxy-bridge-v1-20260930/`（`mv` 不 `rm`） | 从 trash 拿回 |
| 备份 | `~/proxy-v1-backup-20260930-223649/`（含 `SHA256SUMS.before`，8 个文件） | — |
| 网络 | 直连可用（实测 `pypi.org` 直连 HTTP 200 / 1.6s）；GUI `127.0.0.1:3080` 本地监听正常 | — |
| **新隐患** | v1 脚本 `MODE` 默认是 `env`（proxy:28），`.proxy.conf` 搬走后 `proxy on` 会**退回 env 模式**而非 forward | P4 的 `migrate` 必须把 MODE/上游写进新 `config.toml` |

## 5. 硬约束（红线，违反即返工）

> **第 1、2、5、10 条已废除（2026-10-01）**：它们都是为注入层设计的红线，注入层取缔后不再适用；保留以存史。
> 仍然有效的是第 3、4、6、7、8、9 条。

1. **（已废除）注入块永不含 `set -e`、永不返回非零、结尾必须 `; true`**；D1 要把它做成正则级硬规则，而不是靠人记。
2. **（已废除）只有 D1 + D2（+ D3，若可用）全过、且看门狗通道 healthy，才允许写 `~/.xsessionrc`**；任一不满足必须拒绝并说明原因。
3. 所有变更走 **`flock` 单写者** + 写前事务（`tx/`）+ `audit.jsonl`；写一半被杀要能 `proxy repair`。
4. **运行时零第三方依赖**（若决策 2 同意）；测试可用 pytest（dev 依赖）。
5. **不碰 `/etc/lightdm`、不碰 `/etc/fstab`、不装 root 常驻服务**——~~除非决策 1 明确授权 root 看门狗单元~~（**已废除**：决策 1 与看门狗已取缔，本机不装任何常驻服务）。
6. **不删用户文件**：一律先备份再 `mv`/原子替换；备份落在 `~/.local/share/proxy-bridge/backups/`。
7. 日志/状态**只写 XDG 目录**，不再往 `~` 下新增散装文件（~~`~/.proxy_env` 符号链接是唯一例外，见决策 3~~ —— 现状：已彻底搬走，无例外）。
8. 密钥/敏感串不进日志、不进命令行参数（本机目前没有密钥；`no_proxy` 列表不算敏感）。
9. **一次会话只推一个阶段并汇报**（P0→P4），不要闷头全做完；每阶段结束按工作区规则落盘（见 §8）。
10. （**已废除**：当时的状态描述已过时）未经用户同意**不改运行态**：当前系统可用（转发器在跑、~~注入 OFF~~），P0 是只读 spike。
    **现行等价红线**：未经用户同意不改运行态；转发器默认不常驻，用 `proxy forward run` 显式拉起。

## 6. 事故教训（历史存档，2026-10-01 起注入层已不存在）

> **仅存史**：以下是 2026-09-30 登录循环事故的完整记录，**必须保留**；但注入层已取缔，
> 这些教训现在的适用对象是"任何往登录链路注入东西的尝试"，不是本项目的待办。

- **事实**：2026-09-30 21:19 的 v1 注入块结尾是 `...; set -e; fi; true`。`~/.xsessionrc` 是在 Xsession 的 **run-parts 循环里**被 source 的，而该循环刻意用 `set +e` 包住；块尾的 `set -e` 把"零容忍"在中途打开，之后任一 Xsession.d 脚本返回非零 → Xsession 以 **退出码 1** 结束 → lightdm 判定会话结束 → 黑屏退回 greeter → 无限循环。
- **证据**：`/var/log/lightdm/lightdm.log.old` 里 5 次 `Running command /etc/X11/Xsession default` → `Exited with return value 1`；`~/.xsession-errors.old` 只写到第 40 号脚本就断（`xfce4-session` 从未启动）；摘块后 21:58 登录立即正常。
- **为什么漏测**：当时用 `dash -c 'set -e; . ~/.xsessionrc'` 造了 8 种损坏场景全过，**没有复刻循环里 `set +e` 这个状态**。
- **铁律（仍然有效）**：涉及登录链路的改动，必须按真实调用链造环境（D2 复刻循环语义 / D3 跑真实 Xsession），`dash -n` 通过**不算**验证。
- **v2 当时的答案（已废除）**：D1+D2+D3 事前拦，D4 事后救（打卡有、确认无 → 自动摘块 + 通知 + `safe_mode`）；再加不依赖桌面的 TTY 救援（§10）。
  **2026-10-01 的最终答案**：不再注入 —— 注入层取缔，问题从根上消失（见 [`DESIGN-v2.md`](DESIGN-v2.md) 顶部变更记录）。

## 7. 分阶段施工单

> 每阶段：**先只读**→ 改 → **按验收实跑** → 汇报 → 落盘。回滚手段每阶段都要能一条命令执行。
>
> **P0（D3 预演 + 看门狗通道矩阵）与 P2（注入层 + 看门狗）已废除（2026-10-01）**：见 [`DESIGN-v2.md`](DESIGN-v2.md) §12。
> P3 的 systemd 服务部分同样已废除（自启动取缔），转发器与 GUI 保留。

### P0 只读 spike（0.5 天，产出 `SPIKE-P0.md` 写在项目目录）（**注入相关项已废除**，仅存史）
| 项 | 做什么 | 验收 |
| --- | --- | --- |
| D3 预演原型（**已废除**：注入层取缔） | 用 `unshare -rm` 造沙箱：tmpfs 当临时 HOME、待测 `.xsessionrc` 挂进去、`/etc` 只读绑定、`USERXSESSIONRC` 指沙箱文件、`STARTUP=/bin/true`，跑**真实** `/etc/X11/Xsession`；先跑"不带块"基线 | 基线 rc=0；带旧块 rc≠0；带新块 rc=0 —— 三者可重复 |
| 看门狗通道矩阵（**已废除**：自启动取缔） | 三条通道各空转一次判定（root 单元 / user+linger / cron） | 每条能写出"healthy/不可用"的结论与依据命令 |
| 打包骨架 | `python3 -m venv` + 从 `vendor/wheels/` 离线装（**不是** `pip install --no-index .`，见下） | venv 里 `proxy --version` 能跑；且**断网**可复现 |
| | ⚠️ 原写法 `pip install --no-index .` **实测必失败**：全新 venv 只有 pip，没有 setuptools/wheel → `BackendUnavailable`。改为：目标机不构建，直接装 wheel（本项目自身 wheel 也在有网机器上预构建后放进 `vendor/wheels/`）。详见 `vendor/README.md` | |
| 日志落位 | 造出 `~/.local/state/proxy-bridge/logs/` 与一次轮转 | `ls` 能对上 DESIGN-v2 §4.1 表格 |

### P1 骨架（1–2 天）
包结构 `proxybridge/{cli,config,state,logs,backup,probe}.py`；`config.toml` 只读 + `config.d/*.json` 覆盖层；`state.json` + `flock` + `tx`；`app.jsonl`/`app.log` 与内部轮转；`status`/`doctor` 三个只读命令先跑通。
（原文还列了 `sysd.py`，**已随自启动取缔删除**。）
**验收**：单测过；`proxy doctor` 与 v1 结论一致；日志只落在新 XDG 路径。

### P2 注入层 + 看门狗（1–2 天，**本阶段最危险，逐项对照 §5/§6**）

> **已废除（2026-10-01）：整个阶段取消。** 下面是要建的东西与当时的验收，保留以存史。

`inject.py`（生成/校验/摘除托管块，版本戳 + sha256）；D1/D2/D3 串成 `session rehearse`；`guard.py` + `confirm` + systemd 单元；`safe_mode`；`proxy rescue`。
**验收**：事故回归用例（旧块必须被判失败）；假时钟时序用例（打卡无确认→自动回滚；确认早到→不误杀；`safe_mode` 后 `session on` 拒绝）；**真机重登录一次**确认注入生效且不死；TTY 里演练一次 `proxy rescue`。

### P3 转发器 + GUI（1 天）
`tunnel.py` + ~~`proxy-bridge-forward.service`（`Restart=always`、优雅退出、连接计数、上游健康探测、日志双写 journal + 文件）~~（**systemd 服务已废除**：自启动取缔）；
Tk 界面接新 core（只发命令，不自己写文件）。
**验收**：~~`forward status` 与 `journalctl --user -u proxy-bridge-forward` 一致~~（**已废除**）；GUI 全流程可用；断开上游时行为与日志符合预期。

### P4 打包 / 迁移 / 卸载（0.5–1 天）
`pyproject.toml`、`install-manifest.json`、`migrate`（v1→v2 路径搬迁，旧日志进 `logs/legacy/`）、`uninstall`（按清单逆向还原集成点；**不再是 6 处**，注入相关集成点已废除）、`support-bundle`、README 的"急救卡"。
**验收**：隔离 HOME 端到端；**卸载后所有 dotfile 与安装前 sha256 逐字节一致**；`migrate --rollback` 可用。

## 8. 验收总清单（DoD）

> **第 1、3、6 条与第 2 条的一部分已废除（2026-10-01）**：注入层取缔后，这些验收项失去对象；
> 现行 DoD 与实测数字见 [`ACCEPTANCE.md`](ACCEPTANCE.md)。本清单保留以存史。

- [ ] ~~事故回归：旧注入块在真实循环语义下被判失败，新块通过，且测试里**长期保留**这个用例。~~（**已废除**：注入层已取缔，改为永久性"防回流"断言）
- [ ] 卸载/回滚后：~~`~/.xsessionrc`~~、`~/.profile`、`~/.bashrc`、`.desktop`、~~systemd 单元~~、`~` 下临时文件全部还原到安装前 sha256。（**部分已废除**：斜线项已不存在）
- [ ] ~~D4 死手开关在假时钟下三条时序用例全过；`safe_mode` 生效期间 `session on` 拒绝执行。~~（**已废除**）
- [ ] 日志/状态/备份/缓存逐项 `ls -l` 对齐 DESIGN-v2 §4.1 表格（路径、权限 0600/0700、轮转生效）。
- [ ] `proxy doctor` / UI 回归测试全绿；退出码语义符合 DESIGN-v2 §7（**0/1/2/4**，`3` 已废除）。
- [ ] ~~真机重登录一次：注入生效（会话进程有 `*_proxy`）且不死；TTY 救援演练完成。~~（**已废除**）
- [ ] 每阶段结束：写 `memory/2026-09-../proxy-bridge-v2-阶段N.md`，然后按工作区规则跑
      `memory_query.py --rebuild` → `--refresh` → `memory_doctor.py`（动过盘再跑 `state_snapshot.py`）。
- [ ] 汇报时说清"验到哪一层"（逻辑层/文件层/设备层/新鲜度层），实跑输出贴关键行。

## 9. 交付物清单

> **已按 2026-10-01 现状更新**：删除已取缔模块与单元，标出 v1 遗留。

```
~/project/proxy-bridge/
  pyproject.toml
  README.md              # v1 历史机制 + v2 用法 + 浏览器系统代理规则表
  DESIGN-v2.md           # 设计全文（含 2026-10-01 变更记录）
  HANDOFF-v2.md          # 本文（施工总纲）
  SPIKE-P0.md            # P0 产出（历史记录）
  src/proxybridge/*.py   # 21 个模块 / 2138 行：cli ctl config state logs backup probe tunnel ui
                         #   power entry exitcodes manifest migrate support sysproxy doctor uninstall paths
  tests/*.py             # 12 文件 / 984 行（./test.sh = 104 passed）；含防回流 test_no_injection.py
  proxy                  # v2 生成的入口包装（v1 主脚本已归档到
                         #   ~/backup/files/proxy-bridge-v1/before-optimize-20260930/proxy）
  # v1 遗留的 proxy-forward / proxy-ui.py / test-proxy-ui.py 与 ~/backup/files/proxy-bridge-v1/before-optimize-20260930/
  #   已于 2026-10-01 **全部迁出项目** → ~/backup/files/proxy-bridge-v1/
  #   （已废除的 systemd 单元备份在 ~/backup/files/proxy-bridge-v1/legacy-backup/units-20261001/）
  dist/                  # ./build.sh 产出的 wheel（dev_setup.sh 从它离线装）
.venv-dev/               # 开发/测试用 venv（test.sh 在这里装）
~/.local/bin/proxy                                 # 稳定入口（符号链接到上面那个 proxy）
```

## 10. 急救卡（真出事时的第一反应）

> **已废除（2026-10-01）：本节仅存史。** 注入层取缔后不再有任何东西写 `~/.xsessionrc`，
> **本项目不可能再引起登录循环**；`proxy rescue` / `proxy session-off` 两个命令也已删除。
> 若真遇到登录循环，按 README「安全性说明」末尾的通用排查逐步排除其它 autostart 项。

**判读**：登录"黑一下退回登录界面"循环 → ~~大概率是注入块~~（已废除，本项目不再引起）。看两条命令：
```bash
sudo grep -n 'Exited with return value' /var/log/lightdm/lightdm.log | tail
tail -30 ~/.xsession-errors          # 若只写到第 40 号脚本前后就断，几乎确诊
```
**救援（不需要桌面）**：切 TTY（`Ctrl+Alt+F3`）或 ssh 登录后：
```bash
proxy rescue              # 已废除：命令已删除，实测 rc=2
proxy session-off         # 已废除：v1 命令，v2 早已没有
```
**完全不依赖本项目的手工摘块**（~~软件坏了也能救，记住这条~~ —— 已废除：本项目不再产生托管块；
但若别的工具在 `~/.xsessionrc` 里留了块，这段 awk 仍可作为通用手法）：
```bash
awk '/^# >>> proxy-bridge managed block >>>$/{s=1;next} /^# <<< proxy-bridge managed block <<<$/{s=0;next} !s' \
    ~/.xsessionrc > /tmp/x && mv /tmp/x ~/.xsessionrc
# 若文件只剩空白：rm -f ~/.xsessionrc
```
改完回图形界面重新登录即可；不要动 `/etc/lightdm`。

## 11. 已知坑（v1 踩过，别重复）

> 前 6 条与注入层/`.proxy_env` 有关，**已成为历史（2026-10-01 起不再适用）**；
> 后 2 条仍然有效。

| 坑 | 说明 |
| --- | --- |
| `dash -n` 通过 ≠ 安全（**历史**） | 语法正确但语义致命，这正是事故根因 |
| 触发条件要认准（**历史**） | 只有"注入了块 **且** `~/.proxy_env` 存在"才会踩登录循环；`session-off` 后即使 `.proxy_env` 还在也不会崩 |
| `session-off` ≠ 全关（**历史**） | 它只摘块；`.proxy_env` 仍在 → 新终端照走代理。要全关用 `proxy off` |
| 转发器死了 = 断网（**仍然有效**） | `env.sh` 指向 `127.0.0.1:7897`，转发器一停是"断网"而不是"直连" |
| `~/.profile` 的 `[ -f ] && .`（**历史**） | 文件不存在时整条返回非零，在 `set -e` 调用方会终止（已改 `if…;then…;fi`） |
| 写 `~/.xsessionrc` 前必须备份（**历史**） | 用户可能已有自己的 `.xsessionrc` 内容，只能摘自己的托管块，其余逐字节保留 |
| 面板固定项（**仍然有效**） | XFCE 面板/dock 存的是 desktop id（如 `firefox.desktop`），改 `~/.local/share/applications/` 覆盖即可生效 |
| DSH 侧注意 | 审批提示已禁用，**不要**请求 `sandbox_permissions`；需要 root 用 `sudo -n`；不要启动替代 GUI 服务 |
