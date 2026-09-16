# vm-proxy-bridge

A lightweight proxy switcher for a NAT'd Linux VM. It ships **two working modes** and lets you toggle the whole guest between *direct internet* and *proxied through the host's local proxy* (any HTTP/SOCKS5 proxy listening on the LAN — clash / mihomo / v2ray / SakuraCat, etc.).

Comes with a CLI and a small Tk GUI that share one log file.

```
                           ┌──────────────────────┐
   mode=env (default)      │                      │
  ┌──────────────┐  env    │  host proxy :7897    │
  │ app (new tty)│ ───────►│  (clash/mihomo/...)  │ ──► internet
  └──────────────┘         │                      │
                           │                      │
   mode=forward (new)      │                      │
  ┌──────────────┐ 127.0.0.1:7897 (local)         │
  │ any app      │ ───────►[proxy-forward] ──────►│
  └──────────────┘         │                      │
                           └──────────────────────┘
```

## Two modes

| Mode | How it works | Best for |
|---|---|---|
| **`env`** (default, legacy behaviour) | Writes `~/.proxy_env` with `http_proxy` etc. pointing at the host proxy's LAN address. New terminals pick it up automatically. | Shell work, `curl`, `git`, package managers — anything that honours `*_proxy`. |
| **`forward`** (new) | Runs a tiny zero-dependency TCP forwarder that listens on a **loopback** port (`127.0.0.1:7897` by default) and relays to the host proxy. Also writes `~/.proxy_env` pointing at the local port. | Apps that ignore environment variables, or when you want a stable `127.0.0.1` endpoint. |

Both modes are plain TCP relays — HTTP, HTTPS and SOCKS5 all work, since nothing is decrypted (no TLS termination).

## Components

| File | Purpose |
|---|---|
| `proxy` | CLI switcher: `on` / `off` / `status` / `test` / `mode` / `forward-*` |
| `proxy-forward` | The loopback forwarder (Python 3 stdlib only, no extra packages) |
| `proxy-ui.py` | Tk GUI: status card, mode radio, editable settings, on/off/test, colour-coded live log |
| `deploy.sh` | One-command deploy/update to a target VM over SSH (runs on the host) |

## Deploy (from the host)

```bash
bash deploy.sh <ssh-alias>    # any SSH host defined in ~/.ssh/config
```

VM-side dependencies: `python3`, `python3-tk` (GUI), `curl`.

```bash
sudo apt install -y python3-tk
```

## Usage

### CLI

```bash
proxy on               # enable the currently selected mode
proxy off              # disable (cleans up both modes' artefacts)
proxy status           # mode + state + upstream reachability + connectivity test
proxy test             # direct vs proxied check, with an explicit confirmation line

proxy mode env         # switch to env (legacy) mode
proxy mode forward     # switch to local-forward mode
proxy mode show        # show current mode

proxy forward-on       # enable forwarding without changing the saved mode
proxy forward-off      # stop the forwarder
proxy forward-status   # forwarder details
```

### GUI

Double-click the desktop launcher **网络代理桥**, or run `proxy-ui.py`:

1. Pick a **工作模式** — *环境变量模式* or *本地转发模式*.
2. Edit **上游代理** (host address, e.g. `192.168.18.1:7897`) and, for forward mode, **本地监听** (`127.0.0.1:7897`).
3. **保存配置** → **开启代理**.

## Configuration

`~/.proxy.conf` (shell format, editable from the GUI or by hand):

```sh
PROXY_HOST="192.168.18.1:7897"   # upstream host-side proxy
BIND_HOST="127.0.0.1"            # local listen address (forward mode only)
BIND_PORT="7897"                 # local listen port   (forward mode only)
TEST_URL="https://github.com"    # connectivity probe target
MODE="env"                       # env | forward
```

- `no_proxy` automatically excludes the VM/host LAN addresses, so internal services (e.g. a local LLM server on `192.168.18.1`) stay **direct** even while the proxy is on.
- Logs: `~/.proxy.log` (shared by CLI + GUI, the GUI tails it live, colour-coded) and `~/.proxy-forward.log` (forwarder runtime detail).

## Security notes

The forwarder is an **unauthenticated open relay by design** — anyone who can reach its port can use the upstream proxy.

- It therefore **binds to loopback only**. Binding to a non-loopback address is refused unless you pass `--allow-remote` explicitly:

  ```bash
  proxy-forward --bind 0.0.0.0:7897 --target 192.168.18.1:7897 --allow-remote
  ```

  The same guard exists in the CLI and the GUI, so a typo in the settings can't silently expose your proxy to the LAN.
- The forwarder makes no outbound connections of its own beyond the configured target; it stores no credentials. `~/.proxy.conf` contains addresses only.
- Connections are relayed per-flow with a 300 s idle timeout so stale sockets are reclaimed.

## Host-side checklist

- The host proxy must listen on `0.0.0.0:<port>` (in clash-like clients: enable **"Allow LAN"**).
- Allow the port through the host firewall, scoped to the VM subnet:

  ```
  netsh advfirewall firewall add rule name="Proxy VMnet8" dir=in action=allow protocol=TCP localport=7897 remoteip=192.168.18.0/24
  ```

- If the host proxy is stopped, the VM simply falls back to direct — no network breakage. The forwarder logs a `WARN` and keeps listening until the upstream returns.
