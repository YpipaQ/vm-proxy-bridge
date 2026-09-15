#!/usr/bin/env bash
# deploy.sh - deploy/update vm-proxy-bridge to a target VM
# usage: bash deploy.sh <ssh-alias>   (an SSH host defined in ~/.ssh/config)
set -euo pipefail
TARGET="${1:?usage: bash deploy.sh <ssh-alias>}"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[deploy] target = $TARGET"
scp -q "$DIR/proxy" "$DIR/proxy-ui.py" "$TARGET:/tmp/"

ssh "$TARGET" 'bash -s' <<'EOF'
set -e
sudo -n install -m 755 /tmp/proxy /usr/local/bin/proxy
sudo -n install -m 755 /tmp/proxy-ui.py /usr/local/bin/proxy-ui
rm -f /tmp/proxy /tmp/proxy-ui.py

# desktop launcher (idempotent)
D=$(xdg-user-dir DESKTOP 2>/dev/null || echo ~/Desktop)
cat > "$D/proxy-bridge.desktop" <<'DESK'
[Desktop Entry]
Version=1.0
Type=Application
Name=Proxy Bridge
Comment=VM proxy on/off with log
Exec=/usr/local/bin/proxy-ui
Icon=preferences-system-network
Terminal=false
Categories=Network;
DESK
chmod +x "$D/proxy-bridge.desktop"

# shell hooks (idempotent) - auto-load ~/.proxy_env in new terminals
for f in ~/.bashrc ~/.profile; do
  grep -q "proxy_env" "$f" 2>/dev/null || printf '\n# proxy switcher env (toggle with: proxy on/off)\n[ -f "$HOME/.proxy_env" ] && . "$HOME/.proxy_env"\n' >> "$f"
done

echo "[deploy] installed: proxy / proxy-ui / desktop launcher"
EOF

echo "[deploy] done. Desktop launcher: 'Proxy Bridge'; CLI: proxy on|off|status|test"
