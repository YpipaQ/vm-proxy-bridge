# 新机验收清单（换机 / 迁移后照做）

> 适用：**任何** Debian 系新机（Debian+GNOME、UOS、麒麟、openKylin、deepin…）。
> 设计原则：每一条都是**可观测的铁证**，不是"看起来对了"。全部只读或可逆。
> 生成：2026-09-30；**改版：2026-10-01**（注入层与自启动取缔 → 删除 `session on` / `~/.xsessionrc` /
> 看门狗实机验证（**已废除**）；§4 换成已验证的规则表 + 三步复核）。

## 0. 搬迁前：旧机必须先做的事

```bash
# ① 清掉历史里的明文 Key（实测存在于 ~/.bash_history 第 37/42/47 行，sk- 开头）
cp -p ~/.bash_history ~/.bash_history.bak-$(date +%F)
grep -v 'sk-' ~/.bash_history > /tmp/h && mv /tmp/h ~/.bash_history
grep -c 'sk-' ~/.bash_history          # 期望 0

# ② 打包前再扫一遍待搬目录（只报命中，不打印内容）
grep -rIl --exclude-dir=.git -e 'sk-' -e 'AKIA' -e 'BEGIN.*PRIVATE KEY' \
     ~/Work ~/project ~/.dsh 2>/dev/null | head -20
```

## 1. 新机装完先验的三条（决定这套东西能不能用）

```bash
# ① 网络：能到宿主代理
nc -z -w3 192.168.18.1 7897 && echo "上游可达 ✓" || echo "上游不可达 ✗——先解决网络"

# ② gsettings 可用（"系统代理"通道的硬前提；不再要求 systemd 用户管理器）
command -v gsettings >/dev/null && gsettings list-schemas | grep -qx org.gnome.system.proxy \
  && echo "gsettings + org.gnome.system.proxy ✓" || echo "缺 gsettings/schema ✗——系统代理通道不可用"

# ③ 桌面环境（决定要不要给浏览器补身份）
echo "XDG_CURRENT_DESKTOP=$XDG_CURRENT_DESKTOP  SESSION=$XDG_SESSION_TYPE"
```

**判据**：①、②必须是 ✓。
②不成立时才需要换发行版或装 `libglib2.0-bin`；**注意：不再要求 systemd 用户会话** ——
2026-10-01 实测已证明浏览器走「系统代理 + 桌面身份」即可，注入层与自启动都已取缔。

> **平台事实（换机时别再踩）**：本机是 SysV init + elogind，**没有 systemd 用户管理器**，
> 用户级 timer/service 永远不会执行；桌面环境是 XFCE，`XDG_CURRENT_DESKTOP=XFCE` 时 **Chrome 不读系统代理**。

## 2. 装项目 + 跑测试

```bash
# 拷过来：~/Work ~/project ~/.dsh ~/.config/proxy-bridge/env.sh ~/.ssh
cd ~/project/proxy-bridge
sudo apt install -y python3-venv            # Debian 系
./build.sh && ./dev_setup.sh                 # 离线建 venv（用 vendor/wheels，不联网）
./test.sh                                    # 期望 104 passed
```

## 3. 现行功能自检（取代原"闸门是否放行"）

```bash
.venv-dev/bin/proxy doctor ; echo "rc=$?"          # 期望：rc=0，逐项 ✓
.venv-dev/bin/proxy status                          # 期望：desired_on / actual 一行
.venv-dev/bin/proxy entry status                    # 期望：稳定入口 ~/.local/bin/proxy 存在
.venv-dev/bin/proxy sysproxy status                 # 期望：mode 与 host/port
```

**判据**：`doctor` 的纪律是"**没启用不是故障**" —— 未起转发器 / 未设系统代理 / 无 `*_proxy` /
env.sh 未创建 → 一律 ✓；只有**真不一致**（系统代理指向别处、转发器在跑但 env.sh 没了、`*_proxy`
指向别处、上游不可达）才 ⚠️/❌。这条口径已用 `tests/test_doctor.py` 11 条钉死。

**回滚**：`proxy sysproxy off`（系统代理还原直连）、`proxy off`（清 env + 停转发器）、`proxy uninstall`。

## 4. 浏览器是否**真的**认系统代理（唯一不能靠猜的一条）

**方法：看转发器日志的 `^CONN` 增长** —— 这是唯一无法伪造的证据。
（本次在 MX/XFCE 上就是靠它推翻了"系统代理能用"的假设。）

### 4.1 已验证的规则表（2026-10-01 实测，矩阵 33 例：PASS 8 / FAIL 0 / INFO 25）

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

**PAC 待查（非阻塞）**：`mode=auto` + `autoconfig-url` 下 PAC 脚本被反复下载却从不被采用，
原因未定；三条可用通道已足够，不依赖它。

量具与原始证据：`spike/browser-proxy-matrix/`（`README.md` 讲量具，`evidence/20261001-*` 是原始结果）。

### 4.2 三步复核（换机后照做）

```bash
cd ~/project/proxy-bridge
count() { grep -c '^CONN' ~/.local/state/proxy-bridge/logs/forward.log; }

# ① 起转发器
.venv-dev/bin/proxy forward run &
sleep 1; .venv-dev/bin/proxy forward status | head -1     # 期望 listening

# ② 系统代理指向本地端口（可逆）
.venv-dev/bin/proxy sysproxy on

# ③ 带桌面身份起浏览器，看 CONN 是否增长
B=$(count)
.venv-dev/bin/proxy chrome --user-data-dir=$(mktemp -d) --headless=new --dump-dom https://example.com >/dev/null 2>&1
sleep 1; A=$(count); echo "CONN 增长 $((A-B)) 条"
```

**判据**：增长 **>0** 才算认；**=0 就是不认**。
**对照组（必做）**：把第 ③ 步换成同一浏览器、同一 URL，但环境里 `XDG_CURRENT_DESKTOP=XFCE`
（即用 `env XDG_CURRENT_DESKTOP=XFCE google-chrome …` 直接起），**应 +0** —— 这是证明"增长确实来自身份"
而不是噪声的关键对照。

### 4.3 兜底（都不需要注入）

- 启动器 `Exec=... --proxy-server="http://127.0.0.1:7897"`（命令行通道优先级最高）
- 或 `http_proxy=http://127.0.0.1:7897` 环境变量（两条都实测有效）

## 5. 已废除的历史章节（2026-10-01，仅存史）

- ~~§3 闸门是否放行：`proxy session on` + `~/.xsessionrc` 托管块 + `session status` + D3 预演~~ ——
  `session` 命令已删除（实测 rc=2），注入层取缔。
- ~~§5 看门狗是否真在跑：装 `proxy-bridge-guard.timer`、`systemctl --user enable --now`、造过期打卡让心跳摘块~~ ——
  自启动三个单元已删除，本机也没有 systemd 用户管理器。
- ~~§6 真机重登录（注入生效且不死）+ `proxy rescue` TTY 救援~~ —— 不再有任何注入，不会再有登录循环。

## 6. 全绿之后才算"夺舍"完成

- [ ] `./test.sh` **104 passed**
- [ ] `proxy doctor` rc=0、逐项 ✓（"没启用不是故障"口径）
- [ ] `gsettings` 存在且 `org.gnome.system.proxy` schema 可用
- [ ] 三步复核：`proxy chrome <url>` 后转发器 `^CONN` 增长 **>0**
- [ ] 对照组：`XDG_CURRENT_DESKTOP=XFCE` 起同一浏览器为 **+0**
- [ ] `~/.xsessionrc` 不存在（不再有任何注入；本项目也不再创建它）
- [ ] 旧机**保留**到以上全绿，再决定是否停用（真正不可逆的只有删旧 VM）
