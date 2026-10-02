# browser-proxy-matrix —— 浏览器"到底什么时候读得到代理"的测试台

一次性问清一件事：**什么条件下浏览器才会把请求交给代理**。工具是通用的（规格全在
`cases.json`，加一条 JSON 就多一个用例），不是硬编码的一次性脚本。

## 三个量具（互相独立，能对不上账就是发现了新东西）

| 量具 | 原理 | 能证明什么 |
| --- | --- | --- |
| `probe_server.py` | 目标主机用 `.invalid` 顶级域（**永远解析不了**），探针假代理收到请求才回 marker 页 | 探针日志里有这一笔 ⇔ **请求真的交给了代理**（无假阳性：直连只会 DNS 失败） |
| 双探针端口 | A=17897 / B=17896 两个假代理各记一份日志 | 系统代理与环境变量/命令行**同时给**时，看端口就知道**哪条通道赢了** |
| netlog（`netlog_effect.py`） | 浏览器自己记的账：`PROXY_CONFIG_CHANGED` 带 `new_config` | 最终生效的是 `{"single_proxy":[...]}` 还是 `{}`（直连）；直连用例另有 DNS 失败码 `-105` 证明"确实发起了请求" |

`--dump-dom` 的输出再补一刀：命中时 DOM 里有 `PROXYBRIDGE_PROXIED_OK`。

## 用法

```bash
# 全量矩阵（约 5 分钟；每例用完即还原 gsettings）
python3 run_matrix.py --cases cases.json --out /tmp/bpm/results.json --md /tmp/bpm/results.md

# 只跑某些用例（按 id 前缀）
python3 run_matrix.py --only C03

# 动态实验：已开着的浏览器，改系统代理要不要重启
python3 dynamic_reload.py

# 单看一份 netlog（文件被强杀截断也能读）
python3 netlog_effect.py /path/to/netlog.json --host proxy-test.invalid
```

`cases.json` 里每条用例只动一个自变量：

```json
{"id":"C03-gs-manual-GNOME","browser":"chrome",
 "gsettings":{"mode":"manual","http_host":"127.0.0.1","http_port":"PROBE_A","use_same_proxy":true},
 "desktop":{"XDG_CURRENT_DESKTOP":"GNOME"},
 "env":{"http_proxy":null},          // null = 显式取消该变量
 "flags":["--proxy-server=http://127.0.0.1:PROBE_B"],
 "prefs":{"network.proxy.type":5},   // 仅 firefox：写进临时 profile 的 user.js
 "stock_flags":true, "timeout":150,  // 原厂参数对照 / 覆盖超时
 "expect":"proxied|direct|any",      // any=只观测不判定
 "note":"这条在问什么"}
```

占位符：`PROBE_A`(17897) `PROBE_B`(17896) `ORIGIN_A`(17898) `ORIGIN_B`(17900)。

## 安全边界（工具自己保证）

* 运行前 `dconf dump /system/proxy/`，无论成败都在 `finally` 里 `reset -f` + `load` 还原，并核对还原结果；
* 浏览器一律用**一次性 profile**（`--user-data-dir` / `-profile`），绝不碰用户真实配置；
* 每次 `launch_and_wait` 用独立进程组启动，超时/拒退整组 kill。

## 踩过的坑（改这个工具前先读）

1. **别用管道收浏览器输出**：Chrome 错误页 DOM 有一两百 KB，管道没人读就写阻塞，表现是
   "浏览器永远不退出"（第一版矩阵 36 例全超时就是栽在这）。改成重定向到文件。
2. **直连用例的 DNS 很慢**（本机解析器对 `.invalid` 要等 ~60 秒）：给 Chrome 加
   `--host-resolver-rules=MAP proxy-test.invalid ~NOTFOUND`、给 Firefox 加
   `network.dns.disabled=true`，缩到 ~1.2 秒。这两条**不碰代理判定逻辑**，且已用
   `C01s/C03s`（`stock_flags`，完全原厂参数）对照确认结论一致；走 HTTP 代理的请求本来
   就不解析目标主机，所以不受影响。
3. **探针日志里有大量浏览器后台噪声**（`accounts.google.com`、`clients2.google.com`…），
   统计必须按目标主机过滤，否则"连接数变多"会被误当成"走了代理"。
4. **netlog 可能被截断**（强杀浏览器时）：`netlog_effect.py` 用容错读取，只收完整事件。
5. **`pgrep -f` 会匹配到自己的命令行**：它是**正则**匹配。方括号写法（`probe[_]server`）只在
   "模式本身没出现在同一条命令行里"时安全 —— 如果脚本正文里含有 `--user-data-dir=<路径>`，
   那么 `pgrep -f 'user[-]data-dir=<路径>'` 依然会命中**自己这个 bash**，把自己 SIGKILL 掉，
   后面的清理代码就再也不执行了（踩过三次）。**结论：清理一律用显式 PID**，别用模式匹配。
6. 判定通道靠**端口**而不是靠猜：两条通道各指一个探针，谁赢看日志落在哪个端口。
7. Firefox 没有 `--dump-dom`，用 `--screenshot`（也能`read_image` 直接看渲染结果），
   主判据仍是探针日志。
