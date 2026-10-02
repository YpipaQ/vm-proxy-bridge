# proxy-bridge

VM 网络代理桥：把宿主机代理接到客户机，并让**图形程序（浏览器）也真的走代理**。

零依赖，只用 Python 标准库 + bash + tkinter。

## 文档导航

| 文档 | 是什么 |
| --- | --- |
| `README.md`（本文） | 现状与用法：三层接入、浏览器系统代理规则表、命令速查、安全性说明、风险与回滚 |
| [`DESIGN-v2.md`](DESIGN-v2.md) | v2 方案全文：XDG 日志布局、命令面、排期、风险；**顶部有 2026-10-01 变更记录（注入层四道防线等章节现已存史）** |
| [`HANDOFF-v2.md`](HANDOFF-v2.md) | **v2 施工交接书（冷启动专用）**：环境事实、红线、分阶段施工单、验收清单、急救卡、已知坑（含 2026-10-01 废除标注） |
| [`MODULES.md`](MODULES.md) | 模块边界（唯一事实来源）：现行 21 个模块、依赖方向、构建坑 |
| [`ACCEPTANCE.md`](ACCEPTANCE.md) | 现行 DoD 与实测数字（104 passed） |
| [`NEWHOST-ACCEPTANCE.md`](NEWHOST-ACCEPTANCE.md) | 换机验收清单：规则表 + 三步复核 |
| [`SPIKE-P0.md`](SPIKE-P0.md) | P0 spike 历史记录（注入相关结论已存史） |

> 当前运行状态：**无注入层（已取缔，2026-10-01）**——不再有任何东西写 `~/.xsessionrc`，也不会再有登录循环；
> 转发器与系统代理开关照常可用。变更理由与证据见 [`DESIGN-v2.md`](DESIGN-v2.md) 顶部「变更记录（2026-10-01）」。

## 变更记录（2026-10-01）：注入层与自启动已取缔

| 取缔项 | 三条理由 | 证据 |
| --- | --- | --- |
| **注入层**（`inject/guard/rehearse/session/desktop/sysd` 六模块、D1–D4 防线、死手开关、预演、救援、会话确认） | ① 本机无 systemd 用户管理器 → 看门狗通道永不 healthy → `session on` 本就硬拒绝；② 2026-09-30 登录循环事故由它引起；③ 浏览器根本不需要它 | 理由①②见本文「安全性说明」与 [`MODULES.md`](MODULES.md) §6；理由③与替代通道见本文「系统代理」与 `DESIGN-v2.md` §1.1/§1.3 |
| **自启动**（`~/.config/systemd/user/proxy-bridge-{forward,guard}.{service,timer}`） | 本机没有 systemd 用户管理器，这些单元永远不会运行 | `MODULES.md` §6；原单元备份在 `~/backup/files/proxy-bridge-v1/legacy-backup/units-20261001/` |

保留并继续维护：转发器（`proxy forward run`）、系统代理开关（`proxy sysproxy on/off/status`）、
`proxy chrome`、终端环境变量 `~/.config/proxy-bridge/env.sh`、`proxy on/off` 总开关，以及卸载/迁移/体检/支持包/Tk 界面。

## 三层接入，别混淆

| 层 | 谁在用 | 靠什么生效 |
|---|---|---|
| 终端环境变量 | 新开的终端、curl/wget/git 等 CLI | `~/.config/proxy-bridge/env.sh`（由 `~/.bashrc` / `~/.profile` source） |
| 本地转发 | 需要固定本地端口的程序 | `proxy forward run` 监听 `127.0.0.1:7897` 透传到宿主代理 |
| **系统代理接入** | **从桌面菜单启动的浏览器 / 图形程序** | **`gsettings`（`org.gnome.system.proxy`）＋ `proxy chrome` 补的桌面身份**；Firefox **不需要身份** |

**覆盖范围（2026-10-01 实测）**：可用的两条浏览器通道是 **系统代理（+ 桌面身份）** 与 **环境变量**；
两者都不需要注入，规则表见「系统代理」一节。

## 历史背景：浏览器曾经为什么读不到代理（结论已作废）

> 本节只保留机理与当时的事实（**存史**）；**当时的结论"`~/.xsessionrc` 是唯一的注入点"已被 2026-10-01 实测推翻**
> ——见「系统代理」一节。图形程序确实不继承 `~/.bashrc`，但读系统代理另有通道。

浏览器继承的是**图形会话的环境**，不是 `~/.bashrc`。
`~/.bashrc` / `~/.profile` 只影响新开的终端；而 lightdm 的会话链是
`/etc/lightdm/lightdm.conf (session-wrapper=/etc/X11/Xsession)` → `/etc/X11/Xsession`
→ `40x11-common_xsessionrc` 去 source `~/.xsessionrc` → `99x11-common_start` 才 `exec` 会话。

实测：`xfce4-session` 的环境里代理变量数量 = **0**。当时据此判断"转发器在跑、端口在听，
但浏览器不知道有这个端口"，并把 `~/.xsessionrc` 当成唯一注入点；后来发现真正卡住浏览器的是**桌面身份**。

## 命令速查

`proxy --help` 实测列出的子命令，共 13 个：
`{version,paths,status,doctor,on,off,uninstall,support-bundle,migrate,manifest,ui,sysproxy,entry,forward}`

```bash
proxy on | off                        # 总开关：写 env + 装稳定入口 + 起/停转发器
proxy forward run | status | tail     # 转发器（run 前台跑；status 只读；tail 跟随日志）
proxy sysproxy on | off | status      # 系统代理（GNOME gsettings 通道，可逆）
proxy chrome [chrome 参数…]           # 不带桌面身份的桌面 → 补身份再起 Chrome（见下）
proxy entry install|uninstall|status  # 稳定入口 ~/.local/bin/proxy
proxy status | doctor | paths | manifest | version
proxy ui                              # Tk 图形界面
proxy support-bundle | migrate | uninstall [--purge]
```

**已删除**：`session`、`guard`、`rescue`、`service`（实测 rc=2，且不在 `proxy --help` 里）。
**`chrome` 不在 `proxy --help` 里**：它在 `argparse` 之前被拦截 —— 必须如此，否则 `--user-data-dir=…`
这类浏览器参数会被当成 `proxy` 自己的选项吞掉。所以"help 里看不到"不等于"没有这个命令"。

**退出码**：`0` OK / `1` FAIL / `2` DOCTOR_FAILED / `4` USAGE。
原 `3`（safe_mode，需人工介入）**已随注入层废除**。

## 生效时机（最容易误解的一点）

- **已运行的浏览器不会改变**：代理是进程启动时读入的，重启浏览器也没用。
- 想让当前会话立刻生效：`source ~/.config/proxy-bridge/env.sh` 后**从该终端启动**浏览器。
- 系统代理（`proxy sysproxy on`）对**新启动**的浏览器生效：从桌面菜单起的要桌面身份，
  用 `proxy chrome` 起就不用管。
- 环境变量通道对**新开的终端**生效。

## 风险与回滚

转发模式下 `~/.config/proxy-bridge/env.sh` 指向 `127.0.0.1:7897`：**转发器一停，用到它的程序不是"不走代理"而是直接断网**。
因此 `proxy doctor` / 界面状态栏会明确报出这个配对关系。
（自启动已取缔，转发器不会被自动拉起：用之前先 `proxy forward run`。）

回滚：

```bash
proxy sysproxy off    # 系统代理还原为直连（mode=none）
proxy off             # 清 env + 停转发器
```

## 安全性说明（含 2026-09-30 登录循环事故）

> **已废除（2026-10-01）：注入层取缔，本节仅存史。** 下面记录的是一起真实事故的机理与教训，
> 必须保留；但引发它的注入块已经不存在了，现在**没有任何东西会写 `~/.xsessionrc`**。

**真实机制**：`/etc/X11/Xsession` 第 9 行是 `set -e`，但它刻意把 session.d 循环包成

```sh
set +e
for SESSIONFILE in $SESSIONFILES; do . $SESSIONFILE; done   # ~/.xsessionrc 在这里被 source
set -e
exit 0
```

也就是说：**循环期间的 `-e` 必须保持关闭**，这是 Xsession 自己为了容忍单个脚本失败而设计的。
注入块如果在这个循环中途重新 `set -e`，就把「循环内零容忍」打开了 —— 之后任一脚本返回非零
都会让 Xsession 以退出码 1 结束 → lightdm 判定会话结束 → 黑屏退回 greeter → 无限循环。

**事故**：2026-09-30 21:19 的旧注入块结尾是 `...; set -e; fi; true`，`proxy on`（生成
`~/.proxy_env`）后重启，登录即黑屏循环。lightdm 日志里 5 次
`Session pid=...: Running command /etc/X11/Xsession default` → `Exited with return value 1`；
`~/.xsession-errors` 只写到第 40 号脚本就断了。摘除注入块后 21:58 登录立即正常。

**修复历史**：当时的注入块结尾不再恢复 `-e`，只用 `; true` 兜底。

**回归防线（已随注入层废除）**：曾经用 `session_selftest()` 以 dash 复刻 run-parts 语义
（`set -e` → `set +e` → 注入块 → `false` 探针 → 应继续）来守住这条链路；注入层取缔后该防线一并删除，
取而代之的是永久性"防回流"测试（见 [`ACCEPTANCE.md`](ACCEPTANCE.md) 的 DoD 新条目）。

**教训（仍然有效）**：先前用 `dash -c 'set -e; . ~/.xsessionrc'` 做 8 种损坏场景测试全部通过，
但它**没有复刻循环里 `set +e` 这个关键状态**，所以漏掉了这个致命维度。
验证登录链路的改动，必须按真实调用链造环境，不能只做 `-n` 语法检查和单层 `set -e` 模拟。

**另一处同类隐患已修**：`~/.profile` 里的 `[ -f "$HOME/.proxy_env" ] && . "$HOME/.proxy_env"`
在文件不存在时整条列表返回非零，在 `set -e` 的调用方里会直接终止；已改成 `if ...; then ...; fi`。

**这个坑现在怎么定位（不再专指本项目）**：登录"黑一下退回登录界面"的循环，先按下面两条定性，
再逐个停掉可疑的 autostart / xsession 项复测（用 `--disable` 或临时改名，别直接删）：

```bash
sudo grep -n 'Exited with return value' /var/log/lightdm/lightdm.log | tail
tail -30 ~/.xsession-errors          # 只写到某个编号脚本前后就断 → 问题出在那个脚本附近
ls ~/.config/autostart /etc/xdg/autostart   # 逐个排除登录时自动启动的项
```

**不要动 `/etc/lightdm`。**

## 文件

| 文件 | 说明 |
|---|---|
| `proxy` | **v2 生成的入口包装**（`~/.local/bin/proxy` 是指向它的符号链接），由 `proxy entry install` 维护 |
| `src/proxybridge/` | v2 软件包（21 个模块，2138 行） |
| ~~`proxy-forward`、`proxy-ui.py`、`test-proxy-ui.py`~~ | **v1 历史，2026-10-01 已迁出项目** → `~/backup/files/proxy-bridge-v1/v1-live-20260930/`（本机备份台账有记） |
| ~~`~/backup/files/proxy-bridge-v1/before-optimize-20260930/`~~ | **v1 历史，2026-10-01 已迁出项目** → `~/backup/files/proxy-bridge-v1/before-optimize-20260930/`（含 v1 的 `proxy` 脚本本体） |

配置：`~/.config/proxy-bridge/config.toml`　环境变量：`~/.config/proxy-bridge/env.sh`　
日志与状态：`~/.local/state/proxy-bridge/`

---

## 急救卡（真出事时先看这里）

**登录"黑一下退回登录界面"的循环，本项目现在不可能引起**：注入层已取缔，不再有任何注入、不会再有登录循环。
按「安全性说明」末尾的通用排查（看 lightdm 日志 + 逐个排除 autostart 项），**不要动 `/etc/lightdm`**。

### 系统代理（推荐路径：不注入、不装 GNOME、不动系统）

**以下为 2026-10-01 实测的规则表**（矩阵 33 例，PASS 8 / FAIL 0 / INFO 25；
量具与原始证据：`spike/browser-proxy-matrix/`，逐例结果见 `evidence/20261001-*`）。

**Chrome 153**

| 通道 | 生效条件 | 用例 |
| --- | --- | --- |
| 系统代理（`gsettings org.gnome.system.proxy` = manual） | 进程环境里要有"GNOME 桌面身份"：`XDG_CURRENT_DESKTOP` **冒号分隔的某一段恰好等于 `GNOME`**（例 `ubuntu:GNOME` 可以）；**或**未设 `XDG_CURRENT_DESKTOP` 时 `DESKTOP_SESSION=gnome` | C03、C06、C09 |
| 上述身份不成立就不读系统代理 | `gnome` 小写不行、`GNOME-Classic` 不行、空串不行、`XFCE` 不行、`GDMSESSION=gnome` 不行 | C05、C07、C11、C04、C10 |
| 环境变量 | `http_proxy`、`HTTP_PROXY`（大写同样被接受）、`all_proxy` 都有效，**不需要任何桌面身份** | C12、C13、C14 |
| 优先级 | 命令行 `--proxy-server` > 系统代理 > 环境变量；`--no-proxy-server` 一票否决 | C17、C15、C16、C18 |
| 环境健壮性 | 无会话总线、总线地址无效、`HOME` 指向别处、极简环境，**只要身份在就能读到系统代理**；`GSETTINGS_BACKEND=memory` 时读不到（反证走的是 GSettings） | C21、C22、C24、C25、C23 |

**Firefox 156**：默认设置就是"使用系统代理"，读 `gsettings` **不需要任何桌面身份**（F01），
也认 `http_proxy`（F03），无会话总线同样可用（F05）。

**PAC 待查（非阻塞）**：`gsettings mode=auto` + `autoconfig-url` 下，URL 确实被读到、PAC 脚本被反复下载
（矩阵里 16 次；单独复测 15 秒内 6 次），**但从不被采用** —— 即使先等 5 秒让 PAC 装载再导航，
目标请求一次都没交给代理（Chrome C19/C20、Firefox F06 + 单独复测）。反复重取是"装载被判失败"的特征；
Chrome 自己的日志里没有相关报错，具体原因**未定**（未验证的猜测：PAC 脚本地址是回环地址、或 PAC 返回值被拒）。
因为手工代理 / 系统代理 / 环境变量三条通道都已验证可用，**PAC 不是必需项，判定为待查、非阻塞**。

**真机端到端（GitHub）**：转发器 `127.0.0.1:7897` → 上游 `192.168.18.1:7897`；`proxy sysproxy on` 后
`CONN before=384 → mid=454 → after=454`，`XDG_CURRENT_DESKTOP=GNOME` 组 **+70**（其中 1 条为启动探测，
实际带字节 69 条），页面 `gh1.html` = 580094 字节，标题是真实 GitHub 首页；对照组 `XDG_CURRENT_DESKTOP=XFCE`
**+0**、页面 0 字节。**这条链路不需要注入。**

```bash
proxy forward run &     # 起转发器（前台）
proxy sysproxy on       # 系统代理 → 127.0.0.1:7897（只改当前用户 gsettings，可逆）
proxy chrome            # 以 XDG_CURRENT_DESKTOP=GNOME 启动 Chrome → 它就会读系统代理
proxy sysproxy off      # 还原为直连（mode=none）
```

**边界（别误解）**：系统代理通道只覆盖**读 gsettings 的程序**（Chrome/Chromium 系）；
Firefox 默认就读系统代理；终端类由 `~/.config/proxy-bridge/env.sh` 覆盖；
两条都不看的程序仍不会被覆盖。

**两个实现坑（本仓库踩过）**：`gsettings get/set` 必须写 `get <schema> <key>`（只给 schema 会 Usage 报错）；
`proxy chrome` 的参数**不能经过 argparse**（`--user-data-dir=…` 会被当成自己的选项吞掉），
故 `main()` 里对 `chrome` 走直通分支。

### 图形界面

```bash
proxy ui        # Tk/CustomTkinter 界面（只调 core，绝不自己写文件）
```

界面只做三件事：显示状态快照（转发器/系统代理/环境变量文件）、串行执行动作、展示日志尾部。
危险动作（`uninstall`）**强制二次确认**；忙时点击被忽略（不堆队列）。

## 界面行为（选择保护）

代理处于**已启用**状态（`ON` / `DEGRADED` / `ORPHAN`）时：

- 模式单选按钮**锁定**，并显示 🔒 提示 —— 防止误触把运行中的代理切掉；
- 「开启代理」禁用，「关闭代理」可用；「关闭代理」需二次确认；
- 所有操作走单条队列串行执行，连点不会叠命令；
- 顶部另有独立状态行显示「系统代理」是否已挂载。
