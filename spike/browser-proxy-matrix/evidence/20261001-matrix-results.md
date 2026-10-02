| 用例 | 浏览器 | 预期 | 实测 | 判定 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `C00-chrome-flag-only` | chrome | proxied | **A** | PASS | 仪器自检：命令行通道，不看系统代理也应命中 A |
| `C01-chrome-nothing` | chrome | direct | **timeout** | PASS | 仪器自检：什么都不给，必须直连（证明没有假阳性） |
| `C02-gs-manual-no-ident` | chrome | direct | **timeout** | PASS | 只有系统代理、无桌面标识 |
| `C03-gs-manual-GNOME` | chrome | proxied | **A** | PASS | 已知通路：系统代理 + GNOME 标识 |
| `C04-gs-manual-XFCE` | chrome | direct | **timeout** | PASS | 本机真实桌面值 |
| `C05-gs-manual-gnome-lower` | chrome | any | **timeout** | INFO | 问：标识大小写敏感吗 |
| `C06-gs-manual-ubuntu-GNOME` | chrome | any | **A** | INFO | 问：发行版前缀形式（Ubuntu 实际取值）认不认 |
| `C07-gs-manual-GNOME-Classic` | chrome | any | **timeout** | INFO | 问：GNOME 变体（前缀匹配？） |
| `C08-gs-manual-KDE` | chrome | any | **timeout** | INFO | 问：KDE 通道是否也读系统代理（本机无 kioslaverc） |
| `C09-desktop-session-only` | chrome | any | **A** | INFO | 问：只有 DESKTOP_SESSION=gnome 够不够 |
| `C10-gdm-session-only` | chrome | any | **timeout** | INFO | 问：只有 GDMSESSION=gnome 够不够 |
| `C11-empty-ident` | chrome | any | **timeout** | INFO | 问：空字符串标识（桌面环境常留空） |
| `C12-env-http-proxy` | chrome | proxied | **A** | PASS | 环境变量通道（小写） |
| `C13-env-HTTP-PROXY-upper` | chrome | any | **A** | INFO | 问：大写 HTTP_PROXY 认不认 |
| `C14-env-all-proxy` | chrome | any | **A** | INFO | 问：只有 all_proxy 够不够 |
| `C15-env-B-vs-gs-A-GNOME` | chrome | any | **A** | INFO | 问：系统代理(A) 与环境变量(B) 谁优先 |
| `C16-env-B-vs-gs-A-no-ident` | chrome | any | **B** | INFO | 问：无桌面标识时环境变量是否照常生效 |
| `C17-flag-B-vs-gs-A-GNOME` | chrome | any | **B** | INFO | 问：命令行(B) 与系统代理(A) 谁优先 |
| `C18-noproxy-flag-vs-gs-A` | chrome | any | **timeout** | INFO | 问：--no-proxy-server 能否压掉系统代理 |
| `C19-pac-GNOME` | chrome | any | **timeout** | INFO | 问：PAC 通道（mode=auto）是否也走这条路 |
| `C20-pac-no-ident` | chrome | any | **timeout** | INFO | 问：PAC 是否同样被标识卡住 |
| `C21-GNOME-no-session-bus` | chrome | any | **A** | INFO | 问：没有会话总线还能读 gsettings 吗（影响裸启动器/定时任务） |
| `C22-GNOME-bogus-session-bus` | chrome | any | **A** | INFO | 问：总线地址坏掉时的行为（超时？回退？） |
| `C23-GNOME-gsettings-memory` | chrome | any | **timeout** | INFO | 问：读不到后端时是否安全回退直连（不能崩） |
| `C24-GNOME-alien-HOME` | chrome | any | **A** | INFO | 问：读的是不是'该用户 dconf 库'（换 HOME 应读不到） |
| `C25-GNOME-minimal-env` | chrome | any | **A** | INFO | 问：裸启动器环境（无总线/无 runtime dir）下还能不能读 |
| `F00-firefox-manual` | firefox | proxied | **A** | PASS | 仪器自检：Firefox 手工代理通道 |
| `F01-ff-default-no-ident` | firefox | any | **A** | INFO | 问：FF 默认(用系统代理)+系统代理，无桌面标识——不用伪装就通？ |
| `F02-ff-default-GNOME` | firefox | any | **A** | INFO | 问：FF 在 GNOME 标识下是否同样生效 |
| `F03-ff-system-env-only` | firefox | any | **A** | INFO | 问：FF 读不读 http_proxy 环境变量 |
| `F04-ff-system-nothing` | firefox | direct | **timeout** | PASS | 仪器自检：FF 系统代理模式 + 无任何配置 = 直连 |
| `F05-ff-system-no-session-bus` | firefox | any | **A** | INFO | 问：FF 读系统代理是否也依赖会话总线 |
| `F06-ff-system-pac` | firefox | any | **timeout** | INFO | 问：FF 系统代理模式下 PAC 是否可用 |
