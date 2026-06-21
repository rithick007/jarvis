#!/bin/zsh
# Jarvis.command — double-click to summon Jarvis (the web app).
# Boots the backend, builds the UI if needed, and opens your browser.
# (For the old terminal HUD instead, run:  source venv/bin/activate && python ui.py)
cd "$(dirname "$0")"
exec ./run.sh
