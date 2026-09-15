# vm-proxy-bridge

A lightweight proxy switcher for a NAT'd Linux VM: toggle the whole guest between **direct internet** and **bridged through the host's local proxy** (any HTTP/SOCKS5 proxy listening on the LAN, e.g. clash / mihomo / v2ray). Ships with both a CLI and a small Tk GUI, with shared logging.

```
┌──────────────┐   HTTP/SOCKS5     ┌──────────────────────┐
│  VM (Linux)  │ ────────────────► │ host proxy :7897     │ ───► internet
│ proxy on/off │   host LAN IP     │ (clash/mihomo/v2ray) │
└──────────────┘                   └──────────────────────┘
```

## Components

| File | Purpose | Installed to |
|---|---|---|
| `proxy` | CLI switcher (`on` / `off` / `status` / `test`), reads `~/.proxy.conf` | VM: `/usr/local/bin/proxy` |
| `proxy-ui.py` | Tk GUI: status indicator, editable bridge address, on/off/test, live log view | VM: `/usr/local/bin/proxy-ui` |
| `deploy.sh` | One-command deploy/update to a target VM over SSH | runs on the host |

## Deploy (from the host)

```bash
bash deploy.sh <ssh-alias>   # any SSH host defined in ~/.ssh/config
```

VM-side dependencies: `python3-tk` (GUI), `curl`.

```bash
sudo apt install -y python3-tk
```

## Usage

- **GUI**: double-click the desktop launcher → edit the bridge address (e.g. `192.168.18.1:7897`) → Save → toggle.
- **CLI**:
  ```bash
  proxy on      # route new terminals through the bridge
  proxy off     # back to direct
  proxy status  # state + reachability
  proxy test    # direct vs proxied connectivity check
  ```

## Configuration

`~/.proxy.conf` (shell format, editable from the GUI):

```sh
PROXY_HOST="192.168.18.1:7897"
TEST_URL="https://github.com"
```

- `no_proxy` automatically excludes the VM/host LAN addresses, so internal services (e.g. a local LLM server) stay **direct** even when the proxy is on.
- Log: `~/.proxy.log` — shared by CLI and GUI (the GUI tails it incrementally).

## Notes

- The host proxy must listen on `0.0.0.0:<port>` (in clash-like clients: "Allow LAN").
- Allow the port through the host firewall, scoped to the VM subnet:
  `netsh advfirewall firewall add rule name="Proxy VMnet8" dir=in action=allow protocol=TCP localport=7897 remoteip=192.168.18.0/24`
- If the host proxy is stopped, the VM simply falls back to direct — no network breakage.
