"""
config.py — Jarvis's settings, all in one place.

Settings live in jarvis_config.json next to this file, so you can edit
them by hand OR through the /scope and /model commands inside Jarvis.
If the file doesn't exist yet, sensible defaults are written on first run.

The single most important setting is `scoped_folders`: the ONLY folders
Jarvis is ever allowed to touch. Everything outside that list is
invisible to it — enforced in safety.py, not by trust in the model.
"""

import json
from pathlib import Path

# Everything Jarvis creates lives inside the project folder — easy to
# inspect, easy to delete, nothing scattered around your system.
JARVIS_DIR = Path(__file__).resolve().parent
CONFIG_FILE = JARVIS_DIR / "jarvis_config.json"
ACTION_LOG = JARVIS_DIR / "jarvis_actions.jsonl"   # every file op, for /undo
INDEX_DB = JARVIS_DIR / "jarvis_index.db"          # document-search vectors
DRAFTS_DIR = JARVIS_DIR / "drafts"                 # writer skill output

DEFAULTS = {
    # The brain now lives in the cloud (see brain.py). `provider` picks who
    # thinks first; the other is the automatic fallback. Set keys in .env.
    "provider": "groq",                 # "groq" | "gemini"  (offline modes later)
    "groq_model": "llama-3.3-70b-versatile",
    "gemini_model": "gemini-2.0-flash",
    # The old local brain — kept for the offline path / the Textual TUI.
    # OUR custom build (see Modelfile): llama3.2:3b tuned for routing.
    "chat_model": "jarvis",
    # Turns text into vectors for semantic search. Small (274 MB) and fast.
    "embed_model": "nomic-embed-text",
    # Folders Jarvis may read/organize. Add more with: /scope add <path>
    "scoped_folders": [
        str(Path.home() / "Downloads"),
        str(Path.home() / "Desktop"),
        str(Path.home() / "Documents"),
    ],
}


def load() -> dict:
    """Read settings, filling in any missing keys with defaults."""
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        return {**DEFAULTS, **cfg}
    save(DEFAULTS)
    return dict(DEFAULTS)


def save(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")
