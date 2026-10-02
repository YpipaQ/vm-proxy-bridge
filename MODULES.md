# MODULES.md —— 模块边界（唯一事实来源）

> **变更（2026-10-01）**：注入层与自启动已取缔，`inject guard rehearse session desktop sysd` 六模块删除。
> 现行 **21 个模块 / 2138 行**；变更记录见 [`DESIGN-v2.md`](DESIGN-v2.md) 顶部。
> 本文件中带"已废除"标注的条目**仅存史**，不再是实现依据。

> 任何文档/代码注释**不要重复描述**模块职责，一律指向本文件。
> 目的：P1–P4 按边界填肉，**避免整体返工**。改边界必须先改本文件。

## 0. 三条硬规矩

1. **只有 core 层能写文件**；CLI/GUI 只调 core；长驻进程只写自己的日志与状态。
2. **path 解析不做 I/O**：`paths.py` 只拼路径（零副作用），因此可被任何模块与测试安全导入。
3. **变更必须成对**：`flock(single_writer)` + `Tx`（写前事务）+ `audit` 记录；三件套缺一不可。

## 1. 层与依赖方向（箭头=允许依赖，禁止反向）

```
cli ──▶ core ──▶ paths / logs / exitcodes
 │        │
 │        ├──▶ config  ──▶ paths
 │        ├──▶ state   ──▶ paths, logs        （唯一"写变更"入口）
 │        ├──▶ tunnel  ──▶ config, logs, paths （长驻；不碰 dotfile）
 │        ├──▶ backup  ──▶ paths, logs
 │        ├──▶ probe   ──▶ paths, logs
 │        ├──▶ manifest──▶ paths, backup, logs
 │        ├──▶ migrate ──▶ manifest, backup, paths
 │        ├──▶ support ──▶ config, manifest, paths
 │        ├──▶ uninstall▶ backup, logs, manifest, paths
 │        ├──▶ power   ──▶ backup, config, entry, logs, manifest, paths, state
 │        ├──▶ sysproxy▶ config, logs
 │        └──▶ entry   ──▶ （无内部依赖，只用标准库 os/pwd/sys）
 ├──▶ ctl（聚合层：config, paths, power, sysproxy, tunnel, uninstall；doctor/support 延迟 import）
 └──▶ ui（只调 ctl/core，绝不自己写文件）
```

**反向依赖一律禁止**：core 不得 import cli/ui。
`cli → ctl → doctor/support` 等构成环的边一律**函数内延迟 import**（照现状，别在模块顶层写）。

**已删除的依赖分支（2026-10-01，仅存史）**：`inject ──▶ config, state, logs, backup`、
`rehearse ▶ paths, inject`、`guard ──▶ state, logs, inject, desktop`、`sysd ──▶ paths, logs`、
`desktop ──▶ paths, logs`。原文那条"`inject` 不得 import `guard`（守卫通过 state 通信）"的约束随两者一起废止。

## 2. 模块清单（职责 / 不做什么 / 验收点）

| 模块 | 做什么 | **明确不做什么** | 验收点 |
| --- | --- | --- | --- |
| `paths.py` | XDG 路径解析 | 不建目录、不读环境以外的状态 | 单测：环境变量覆盖 |
| `exitcodes.py` | 退出码常量 0/1/2/4（`3` 已废除） | — | 单测：与 DESIGN §7 对齐 |
| `config.py` | 读 `config.toml`（只读）+ `config.d/*.json` 覆盖；校验 | **不写 TOML**（零依赖约束）、不写主配置 | 单测：覆盖优先级、坏配置 |
| `state.py` | 状态机、`flock` 单写者、`Tx` 事务、原子替换 | 不碰 dotfile、不碰 systemd | 单测：锁竞争、非法迁移、原子性 |
| `logs.py` | `app.jsonl`/`app.log`/组件日志、内部轮转 | 不联网、不抛异常 | 单测：0/1/满 边界轮转 |
| `backup.py` | 备份/还原/保留策略（每目标 10 份或 90 天） | 不判断业务、不自动删非自己产的备份 | 单测：还原后 sha256 一致 |
| `probe.py` | 上游/端口/出口 IP 探测，写 `cache/probe.json`（TTL 60s） | 不改模式、不自动切上游 | 单测：TTL 命中/过期 |
| `tunnel.py` | TCP 转发（纯标准库）、连接计数、优雅退出、上游健康探测 | 不碰 dotfile、不自动改模式 | echo server 透传 + SIGTERM |
| `sysproxy.py` | 系统代理开关（GNOME gsettings 通道，可逆）；`browser_env()` 给 Chrome 补桌面身份 | 不装 GNOME、不动系统级配置 | `tests/test_sysproxy.py`（12 条） |
| `power.py` | `on`/`off` 总开关；写 env.sh + 装稳定入口 + 起停转发器 | 不写 dotfile 以外的东西 | `tests/test_power.py`（6 条） |
| `entry.py` | **稳定入口包装**：安装/卸载/查询 `~/.local/bin/proxy` | 不碰别的路径 | `entry status` 实测 |
| `uninstall.py` | 按 `install-manifest.json` 逆序还原 | 不删没登记过的东西 | `tests/test_uninstall.py`（6 条） |
| `doctor.py` | 只读体检；"**没启用不是故障**" | 不修改任何状态 | `tests/test_doctor.py`（11 条钉死口径） |
| `ui.py` | Tk/CustomTkinter 界面 | **不写任何文件**（只发命令） | 全流程手动验收 |

**已删除的 6 个模块（2026-10-01，仅存史）**：`inject.py`（生成/校验/摘除 `~/.xsessionrc` 托管块，
D1 静态 + D2 行为）、`rehearse.py`（D3 全链路预演，`unshare` 沙箱跑真实 Xsession）、`guard.py`（D4
打卡/确认/超时/自动回滚/safe_mode）、`sysd.py`（systemd 单元安装）、`desktop.py`（`.desktop` 集成、
`notify-send`）、`session.py`（会话确认）。连同它们的验收点（事故回归、假时钟三时序、单元 dry-run）一并删除；
取而代之的是永久性"防回流"测试 `tests/test_no_injection.py`。

## 3. 关键外部契约（改这三处最容易返工）

| 契约 | 定义位置 | 消费方 |
| --- | --- | --- |
| ~~托管块格式（BEGIN/END/版本戳/校验和）~~（**已废除（2026-10-01）**：注入层取缔，契约消失） | `inject.py::build_block()` + `STAMP_RE`（**校验和口径：剔除全部注释行后的可执行正文**，两侧共用 `_body_of`） | `rehearse`、`guard`、`doctor` |
| 退出码语义（**0/1/2/4**，`3` 已废除） | `exitcodes.py` | `cli`、`doctor`、测试 |
| 状态文件 schema（`state.json`；`guard.json` 已废除） | `state.py::DEFAULT_STATE`（现为 `{schema, desired_on, actual}`） | `tunnel`、`ui`、`power` |

## 4. P0 实测得到的硬约束（实现时必须遵守）

> **第 1、2、3、4、7 条已废除（2026-10-01）**：它们都是为注入层/预演/看门狗服务的约束，随注入层取缔；
> 保留以存史。仍然有效的是第 5、6 条。**P0 事实本身仍然成立**（`unshare` 内 tmpfs-on-/ 静默失效、
> "Xsession 循环之后"不可达、`false` 型探针才有鉴别力），只是不再有注入相关实现去遵守它们。

| # | 事实 | 影响 |
| --- | --- | --- |
| 1（**已废除**：D3 预演随注入层删除） | `mount -t tmpfs tmpfs /` 在 userns 内返回 0 **但不生效** | D3 只能用"副本+只读"路线，不能依赖挂载遮罩 |
| 2（**已废除**：不再有注入块或探针） | X11 下 `70im-config_launch` 必然把 `STARTUP` 包成 `im-launch`，`99` 的 `exec` 替换 shell | **"Xsession 循环之后"的代码不可达**；探针/钩子必须放 40 号之后、不得依赖循环后阶段 |
| 3（**已废除**：D2/D3 已删除） | 旧块的 `set -e` 只在 `$HOME/.proxy_env` 存在时才真正生效 | D2/D3 的测试**必须带夹具**，否则假通过（D1 之外新增 D2/D3 的 fixture 要求） |
| 4（**已废除**：回归用例已删） | 探针用 `false` 有鉴别力、`exit 1` 没有 | 回归用例必须用 `false` 型探针 |
| 5 | 运行时零第三方；装 venv 不能构建 | 安装 = 预构建 wheel + `--no-index` 装（见 `vendor/README.md`） |
| 6 | 转发器是**无鉴权**回环 TCP → 宿主网络 | `tunnel.py` 必须：仅绑回环、记每连接审计、默认拒绝非回环绑定；文档标注"本机任何进程可直用" |
| 7（**已废除**：注入块与 `env.sh` 回退逻辑都已不存在） | 决策 3（删 `~/.proxy_env`）与注入块冲突 | **已按方案②落地**（2026-09-30，D2 轮）：块改为优先 source `~/.config/proxy-bridge/env.sh`、回退 `~/.proxy_env`，两者皆无则整段空转 → 彻底不再依赖被删的旧文件。若日后想要兼容层，再建符号链接即可（块已同时支持） |


## 5. 看门狗范围裁决（用户 2026-09-30："够用就好、两手一摊关桥"）【已废除，仅存史】

> **已废除（2026-10-01）：看门狗已取缔，本节仅存史。** 自启动三个单元已删除（备份在
> `~/backup/files/proxy-bridge-v1/legacy-backup/units-20261001/`），`guard.py` 模块也已删除。

| 项 | 决定 | 理由 |
| --- | --- | --- |
| 随程序启动 | **timer 常驻**（`enable --now`，`loginctl enable-linger` 已开） | 不依赖某个命令被调用；注销后用户管理器仍在 → 能救 |
| 回滚动作 | **摘块 + 关桥 + 通知**（`guard._stop_bridge()`） | 只摘块不够：`env.sh` 仍指 `127.0.0.1:7897`，桥停了就是断网 |
| 不做 | 不做分级告警、不做多通道冗余、不做复杂状态机 | 覆盖"人不在电脑前"这一主场景即达标 |
| 沙箱取舍 | guard 单元**不加** `ProtectSystem/ProtectHome`，只留 `NoNewPrivileges`+`PrivateTmp` | systemd 257 的 `ReadWritePaths` 要求路径已存在（`-` 前缀实测不生效），而本单元职责正是**删除** `~/.xsessionrc`（**已废除**：该单元已删除）—— 要求它存在自相矛盾。宁可少一层沙箱，也要保证"真出事真能救" |
| forward 单元 | 保留 `ProtectSystem=strict`+`ProtectHome=read-only`+`ReadWritePaths=%h/.local/state` | 转发器不需要写家目录，收紧无代价 |


## 6. 平台兼容性：本机是 SysV init + elogind（2026-09-30 实测）

| 事实 | 证据 |
| --- | --- |
| PID 1 是 `init`（SysV），**不是 systemd** | `cat /proc/1/comm` → `init`；无 `systemd --user` 进程 |
| 登录会话由 `elogind-daemon` 管理 | 进程表有 elogind；`/run/user/1000/` 无 `bus`、无 `systemd/` |
| 用户级 timer/service **不会被执行** | 重启后 `systemctl --user` → `offline`；timer 无运行痕迹 |
| **本机无 systemd 用户管理器 ⇒ 自启动方案整体不可用 ⇒ 自启动已取缔（2026-10-01）** | 同上两行；`~/.config/systemd/user/proxy-bridge-{forward,guard}.{service,timer}` 三个单元已删除，备份在 `~/backup/files/proxy-bridge-v1/legacy-backup/units-20261001/` |
| polkit 反复请求 systemd1 失败是本机既有现象 | syslog 本次启动 98 次、上次 119 次 → **与 proxy-bridge 无关** |

**结论（**已废除、仅存史**：2026-09-30 的历史记录，下列条目现已作废）**：
- 本机**没有**任何可靠常驻看门狗通道（systemd 用户管理器不存在；除非允许桌面自启项，而用户已明确不要）
- 因此 `session.on()` 的通道闸门在本机**必然拒绝**（硬约束 §5.2：无 healthy 通道不得写 `~/.xsessionrc`）
- 闸门已改为**实存性探测**（检查 `$XDG_RUNTIME_DIR/bus` 或 `systemd/`），而不是只看命令返回值
- ~~systemd 单元文件**保留**（对外发放/换到 systemd 机器即可用）~~（**已废除**：单元已删除，换机也不再随包发放）
- ~~`proxy service install --apply` 会重建该软链 → 本机不要再跑~~（**已废除**：`service` 命令已删除，实测 rc=2）

**遗留影响（已作废）**：~~`proxy session on` 在本机不可用；若日后想要注入，需要先提供一个不依赖 systemd
的常驻通道~~ —— **2026-10-01 定案：不注入**。浏览器改走「系统代理 + 桌面身份」通道（见 README 规则表），
注入层与自启动一并取缔，本节描述的阻碍不再是问题。

## 7. 构建与维护的两个坑（2026-10-01 实测，改构建脚本前必读）

1. **`build/` 残留会让已删模块"复活"**：setuptools 会把 `build/lib/` 里的旧副本重新打进 wheel，
   于是 `inject.py`/`guard.py` 这类已删模块又出现在新包里。`build.sh` 开头已 `rm -rf build` —— 别删这一行。
2. **`pip install --force-reinstall` 不会清理"新 wheel 里已不存在"的模块**：旧模块仍留在 `site-packages`
   里可被 `import`，测试会假通过。`test.sh` 已先删 `site-packages/proxybridge` 再装 —— 同样别删。

**入口包装（2026-10-01 新增）**：稳定入口现在是 `entry.py` 生成的包装 —— 项目根的 `proxy` 文件
`exec` 到 `.venv-dev/bin/python -m proxybridge`，而 `~/.local/bin/proxy` 是指向它的符号链接；
它**不再是 v1 的 bash 脚本**（v1 本体在 `~/backup/files/proxy-bridge-v1/before-optimize-20260930/proxy`）。
`paths.py` 里**没有** `xsessionrc()`（`test_no_injection.py` 有断言钉住），模块清单以本文件 §2 为准。
