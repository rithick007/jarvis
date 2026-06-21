#!/bin/zsh
# uninstall_service.sh — stop the always-on Jarvis and remove the LaunchAgent.
PLIST="$HOME/Library/LaunchAgents/com.jarvis.server.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "🛑 Jarvis background service stopped and removed."
echo "   (You can still run it manually with ./run.sh)"
