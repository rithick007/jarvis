#!/bin/zsh
# install_service.sh — make Jarvis always-on.
# Installs a LaunchAgent that runs the web server at login (and restarts it if
# it crashes), so Jarvis lives at http://127.0.0.1:8000 with no commands.
set -e
cd "$(dirname "$0")"
JARVIS_DIR="$(pwd)"
PLIST="$HOME/Library/LaunchAgents/com.jarvis.server.plist"
LABEL="com.jarvis.server"

# Prerequisites: deps installed + UI built (so the server has something to serve).
if [ ! -d venv ]; then python3.11 -m venv venv; fi
./venv/bin/pip install -q -r requirements.txt
if [ ! -d web/dist ]; then (cd web && npm install --silent && npm run build); fi
mkdir -p logs

# Render the template with this machine's real path and install it.
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__JARVIS_DIR__|$JARVIS_DIR|g" com.jarvis.server.plist > "$PLIST"

# (Re)load it.
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"

sleep 2
if launchctl list | grep -q "$LABEL"; then
  echo "✅ Jarvis is now always-on at http://127.0.0.1:8000"
  echo "   It starts automatically at login. Logs: logs/server.log"
  echo "   Stop/remove it anytime with: ./uninstall_service.sh"
else
  echo "⚠  Service didn't register — check logs/server.log"
fi
