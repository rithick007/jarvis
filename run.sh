#!/bin/zsh
# run.sh — boot the Jarvis web app: build the UI if needed, start the backend,
# and open the browser. One command, one local URL (http://127.0.0.1:8000).
set -e
cd "$(dirname "$0")"

PORT=${PORT:-8000}

# 1. Python deps (first run only — quiet if already satisfied).
if [ ! -d venv ]; then
  echo "· creating virtualenv…"
  python3.11 -m venv venv
fi
./venv/bin/pip install -q -r requirements.txt

# 2. Generate the served page: the custom-designed UI wired to the live backend.
#    (Self-contained HTML — no npm build needed for the main page.)
echo "· wiring the design UI to the backend…"
./venv/bin/python build_design.py

# 3. .env reminder.
if [ ! -f .env ]; then
  echo "⚠  No .env found — copy .env.example to .env and add your free API keys"
  echo "   (Groq: https://console.groq.com/keys · Gemini: https://aistudio.google.com/apikey)"
fi

# 4. Launch — open the browser shortly after the server comes up.
( sleep 1.5; open "http://127.0.0.1:${PORT}" ) &
echo "· JARVIS online at http://127.0.0.1:${PORT}  (Ctrl+C to stop)"
exec ./venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port "${PORT}"
