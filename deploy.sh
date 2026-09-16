#!/usr/bin/env bash
# deploy.sh - deploy/update vm-proxy-bridge to a target VM
# usage: bash deploy.sh <ssh-alias>   (an SSH host defined in ~/.ssh/config)
set -euo pipefail
TARGET="${1:?usage: bash deploy.sh <ssh-alias>}"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[deploy] target = $TARGET"
scp -q "$DIR/proxy" "$DIR/proxy-forward" "$DIR/proxy-ui.py" "$TARGET:/tmp/"

ssh "$TARGET" 'bash -s' <<'EOF'
set -e

# 装到用户项目目录（首选），并保留 /usr/local/bin 兼容入口
PROJ="$HOME/project/proxy-bridge"
mkdir -p "$PROJ"
install -m 755 /tmp/proxy         "$PROJ/proxy"
install -m 755 /tmp/proxy-forward "$PROJ/proxy-forward"
install -m 755 /tmp/proxy-ui.py   "$PROJ/proxy-ui.py"

# CLI 软链（命令保持可用）
mkdir -p "$HOME/.local/bin"
ln -sf "$PROJ/proxy" "$HOME/.local/bin/proxy"

# proxy-forward 仅供 proxy 脚本内部调用，需要同目录解析
rm -f /tmp/proxy /tmp/proxy-forward /tmp/proxy-ui.py

# desktop launcher (idempotent)
D=$(xdg-user-dir DESKTOP 2>/dev/null || echo ~/Desktop)
cat > "$D/proxy-bridge.desktop" <<DESK
[Desktop Entry]
Version=1.0
Type=Application
Name=网络代理桥
Comment=VM proxy switcher (env / local-forward modes)
Exec=$PROJ/proxy-ui.py
Icon=$PROJ/icon.png
Terminal=false
Categories=Network;
DESK
chmod +x "$D/proxy-bridge.desktop"

# shell hooks (idempotent) - auto-load ~/.proxy_env in new terminals
for f in ~/.bashrc ~/.profile; do
  grep -q "proxy_env" "$f" 2>/dev/null || printf '\n# proxy switcher env (toggle with: proxy on/off)\n[ -f "$HOME/.proxy_env" ] && . "$HOME/.proxy_env"\n' >> "$f"
done

echo "[deploy] installed to $PROJ"
echo "[deploy] CLI symlink: ~/.local/bin/proxy"
EOF

echo "[deploy] done. Desktop launcher: '网络代理桥'; CLI: proxy on|off|status|test / proxy mode forward"
