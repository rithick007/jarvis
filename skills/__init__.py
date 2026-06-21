"""
skills/ — the skill registry.

A skill is two things:

  1. A TOOL SPEC — a JSON-schema card the model reads to decide WHEN to
     call the skill and WHAT arguments to pass. These descriptions are
     the router's "tuning knob": crisp, example-rich descriptions are
     what make a small local model route reliably.

  2. A RUN FUNCTION — plain Python that does the real work. The model
     only ever chooses; this code acts (behind the safety layer).

Adding a new skill = write its module, add one entry to SKILLS below.
"""

from skills.organizer import organize_files
from skills.docsearch import index_documents, search_documents
from skills.writer import rewrite_text
from skills.sysinfo import mac_status
from skills.vision import analyze_image
from memory import remember as remember_fact

import mac_control

ORGANIZE_SPEC = {
    "type": "function",
    "function": {
        "name": "organize_files",
        "description": (
            "Tidy files in a folder on this Mac: rename, sort, move, or clean "
            "up. Examples: 'sort my Downloads', 'move screenshots into a "
            "folder', 'rename desktop files by date', 'trash old installers'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Folder to organize, exactly as the user said it: 'Downloads', 'Desktop', 'sandbox'…",
                },
                "action": {
                    "type": "string",
                    "enum": ["rename_by_date", "move_screenshots", "sort_by_type", "trash_installers"],
                    "description": (
                        "rename_by_date: prefix files with creation date. "
                        "move_screenshots: gather screenshots into Screenshots/. "
                        "sort_by_type: file everything into Images/Documents/Video… "
                        "trash_installers: send old .dmg/.pkg files to the Trash."
                    ),
                },
            },
            "required": ["folder", "action"],
        },
    },
}

INDEX_SPEC = {
    "type": "function",
    "function": {
        "name": "index_documents",
        "description": (
            "Read and memorize the documents in a folder so they become "
            "searchable. Use when the user says 'index', 'learn', 'scan', or "
            "'read my <folder>'. Must happen before search works."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Folder whose documents to index, e.g. 'Documents'.",
                },
            },
            "required": ["folder"],
        },
    },
}

SEARCH_SPEC = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": (
            "Find documents on this Mac by what they're ABOUT and answer "
            "questions from their contents. Examples: 'find my notes about "
            "taxes', 'where is the essay on whales', 'what does my lease say "
            "about pets'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What the user wants to find or know, in their own words.",
                },
            },
            "required": ["query"],
        },
    },
}

REWRITE_SPEC = {
    "type": "function",
    "function": {
        "name": "rewrite_text",
        "description": (
            "Rewrite text or draft something new (email, reply, message, "
            "paragraph). Examples: 'make this sound professional', 'draft a "
            "polite reply declining the invite'. Output goes to the clipboard "
            "and a draft file — never sent anywhere."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "What to write or how to rewrite it, e.g. 'polite decline, two sentences'.",
                },
                "text": {
                    "type": "string",
                    "description": "The original text to rewrite, if the user provided any.",
                },
            },
            "required": ["instruction"],
        },
    },
}

STATUS_SPEC = {
    "type": "function",
    "function": {
        "name": "mac_status",
        "description": (
            "Report this Mac's vital signs: battery level, free disk space, "
            "uptime. Use for 'how's my battery', 'am I low on storage', "
            "'system status'."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

VISION_SPEC = {
    "type": "function",
    "function": {
        "name": "analyze_image",
        "description": (
            "Look at an image or screenshot on this Mac and describe it or "
            "answer a question about it. Examples: 'what's in my latest "
            "screenshot', 'read the text in that screenshot', 'describe "
            "vacation photo'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": "'latest' for the newest screenshot/image, or part of a filename.",
                },
                "question": {
                    "type": "string",
                    "description": "What the user wants to know about the image, if anything specific.",
                },
            },
            "required": ["image"],
        },
    },
}

REMEMBER_SPEC = {
    "type": "function",
    "function": {
        "name": "remember_fact",
        "description": (
            "Store a personal fact the user wants remembered for the future. "
            "Use when the user says 'remember that…', 'note that…', 'don't "
            "forget…'. Example: 'remember that my landlord is named Raj'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The fact to remember, as a standalone sentence.",
                },
            },
            "required": ["fact"],
        },
    },
}

# ---------------------------------------------------------------------------
# Laptop control specs (mac_control/) — Jarvis's hands on the Mac.
# ---------------------------------------------------------------------------

def _spec(name, description, properties=None, required=None):
    """Compact helper for the many small mac_control tool cards."""
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object",
                       "properties": properties or {},
                       "required": required or []}}}

_STR = {"type": "string"}

OPEN_APP_SPEC = _spec(
    "open_app", "Launch or reveal a Mac application by name. "
    "Examples: 'open Spotify', 'launch Safari', 'start Notes'.",
    {"name": {**_STR, "description": "The app name, e.g. 'Spotify'."}}, ["name"])

QUIT_APP_SPEC = _spec(
    "quit_app", "Quit/close a running Mac application. Asks before quitting.",
    {"name": {**_STR, "description": "The app to quit."}}, ["name"])

FOCUS_APP_SPEC = _spec(
    "focus_app", "Bring an already-open app to the front (switch to it).",
    {"name": {**_STR, "description": "The app to focus."}}, ["name"])

LIST_APPS_SPEC = _spec(
    "list_apps", "List the apps currently open in the foreground.")

VOLUME_SPEC = _spec(
    "set_volume", "Set or change the Mac's output volume. Accepts 0-100, or "
    "'up'/'down'/'mute'/'unmute'.",
    {"level": {**_STR, "description": "0-100, or up/down/mute/unmute."}}, ["level"])

BRIGHTNESS_SPEC = _spec(
    "set_brightness", "Change the display brightness. Use 'up'/'down', or a "
    "0-100 number (exact level needs the 'brightness' CLI).",
    {"level": {**_STR, "description": "up/down, or 0-100."}}, ["level"])

MEDIA_SPEC = _spec(
    "media_control", "Control music playback (Spotify/Music): play, pause, "
    "next, previous.",
    {"action": {**_STR, "description": "play, pause, next, or previous."},
     "app": {**_STR, "description": "Optional app: 'Spotify' or 'Music'."}},
    ["action"])

LOCK_SPEC = _spec("lock_screen", "Lock the Mac's screen. Asks first.")
SLEEP_SPEC = _spec("sleep_display", "Put the display to sleep. Asks first.")

NOTIFY_SPEC = _spec(
    "notification", "Show a macOS notification banner.",
    {"text": {**_STR, "description": "The notification body."},
     "title": {**_STR, "description": "Optional title (defaults to JARVIS)."}},
    ["text"])

WEB_SEARCH_SPEC = _spec(
    "web_search", "Search the web in the default browser. Use for 'google X', "
    "'search the web for X', 'look up X online'.",
    {"query": {**_STR, "description": "What to search for."}}, ["query"])

OPEN_URL_SPEC = _spec(
    "open_url", "Open a specific website/URL in the default browser.",
    {"url": {**_STR, "description": "The URL, e.g. 'github.com'."}}, ["url"])

AX_READ_SPEC = _spec(
    "ax_read_screen", "Read the buttons, fields, links and text of the "
    "frontmost app via the accessibility tree, so you know what's on screen "
    "and what can be clicked. Use before clicking by name.",
    {"question": {**_STR, "description": "Optional: what you're looking for."}})

AX_CLICK_SPEC = _spec(
    "ax_click", "Click a button/link/menu item in the frontmost app by its "
    "visible name (uses the accessibility tree). Asks first.",
    {"element": {**_STR, "description": "The visible label of the element."}},
    ["element"])

AX_SET_SPEC = _spec(
    "ax_set_value", "Type text into a field in the frontmost app by its "
    "name/label (uses the accessibility tree). Asks first.",
    {"element": {**_STR, "description": "The field's label."},
     "value": {**_STR, "description": "The text to type in."}},
    ["element", "value"])

APPLESCRIPT_SPEC = _spec(
    "run_applescript", "Run an arbitrary AppleScript for automation that no "
    "other tool covers. Always shows the script and asks before running.",
    {"script": {**_STR, "description": "The AppleScript source to run."}},
    ["script"])

SHELL_SPEC = _spec(
    "run_shell", "Run an arbitrary shell command as a last resort. Always "
    "shows the command and asks before running. Avoid if a specific tool fits.",
    {"command": {**_STR, "description": "The shell command to run."}},
    ["command"])

SKILLS = {
    "organize_files":   {"spec": ORGANIZE_SPEC, "run": organize_files},
    "index_documents":  {"spec": INDEX_SPEC,    "run": index_documents},
    "search_documents": {"spec": SEARCH_SPEC,   "run": search_documents},
    "rewrite_text":     {"spec": REWRITE_SPEC,  "run": rewrite_text},
    "mac_status":       {"spec": STATUS_SPEC,   "run": mac_status},
    "analyze_image":    {"spec": VISION_SPEC,   "run": analyze_image},
    "remember_fact":    {"spec": REMEMBER_SPEC, "run": remember_fact},
    # Laptop control
    "open_app":      {"spec": OPEN_APP_SPEC,    "run": mac_control.open_app},
    "quit_app":      {"spec": QUIT_APP_SPEC,    "run": mac_control.quit_app},
    "focus_app":     {"spec": FOCUS_APP_SPEC,   "run": mac_control.focus_app},
    "list_apps":     {"spec": LIST_APPS_SPEC,   "run": mac_control.list_apps},
    "set_volume":    {"spec": VOLUME_SPEC,      "run": mac_control.set_volume},
    "set_brightness":{"spec": BRIGHTNESS_SPEC,  "run": mac_control.set_brightness},
    "media_control": {"spec": MEDIA_SPEC,       "run": mac_control.media_control},
    "lock_screen":   {"spec": LOCK_SPEC,        "run": mac_control.lock_screen},
    "sleep_display": {"spec": SLEEP_SPEC,       "run": mac_control.sleep_display},
    "notification":  {"spec": NOTIFY_SPEC,      "run": mac_control.notification},
    "web_search":    {"spec": WEB_SEARCH_SPEC,  "run": mac_control.web_search},
    "open_url":      {"spec": OPEN_URL_SPEC,    "run": mac_control.open_url},
    "ax_read_screen":{"spec": AX_READ_SPEC,     "run": mac_control.ax_read_screen},
    "ax_click":      {"spec": AX_CLICK_SPEC,    "run": mac_control.ax_click},
    "ax_set_value":  {"spec": AX_SET_SPEC,      "run": mac_control.ax_set_value},
    "run_applescript":{"spec": APPLESCRIPT_SPEC,"run": mac_control.run_applescript},
    "run_shell":     {"spec": SHELL_SPEC,       "run": mac_control.run_shell},
}


# ---------------------------------------------------------------------------
# The forged library — skills Jarvis wrote for you (skills/learned/).
#
# The Skill Forge writes verified new skill modules into skills/learned/.
# Each such module exposes a top-level TOOL_SPEC dict and a function whose
# name matches TOOL_SPEC["function"]["name"]. We auto-load them here on every
# startup so a forged skill survives restarts, and register_module() lets the
# forge hot-load a brand-new skill without restarting.
# ---------------------------------------------------------------------------

LEARNED_DIR = __import__("pathlib").Path(__file__).resolve().parent / "learned"


def register_module(module) -> str | None:
    """Register one already-imported learned-skill module into SKILLS.
    Returns the skill name on success, or None if the module is malformed."""
    spec = getattr(module, "TOOL_SPEC", None)
    if not isinstance(spec, dict):
        return None
    try:
        name = spec["function"]["name"]
        fn = getattr(module, name)
    except (KeyError, TypeError, AttributeError):
        return None
    if not callable(fn):
        return None
    SKILLS[name] = {"spec": spec, "run": fn, "learned": True}
    return name


def load_learned() -> list[str]:
    """Import every module in skills/learned/ and register the valid ones."""
    import importlib
    loaded = []
    if not LEARNED_DIR.is_dir():
        return loaded
    for path in sorted(LEARNED_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"skills.learned.{path.stem}")
            mod = importlib.reload(mod)
            name = register_module(mod)
            if name:
                loaded.append(name)
        except Exception:
            # A broken forged file must never take the whole app down.
            continue
    return loaded


# ---------------------------------------------------------------------------
# The Skill Forge meta-skill — how the library grows.
# ---------------------------------------------------------------------------

FORGE_SPEC = _spec(
    "forge_skill",
    "Create a brand-new permanent skill for Jarvis when NO existing tool can "
    "do what the user asked. The user typically says 'learn to…', 'teach "
    "yourself to…', or asks for a repeatable capability you don't have. "
    "Jarvis writes the code, safety-checks it, asks the user to approve it, "
    "then keeps it forever. Use only when nothing else fits.",
    {"description": {**_STR, "description":
        "A clear description of the new ability to build, in the user's "
        "words, e.g. 'move every PDF in Downloads into a Reading folder'."}},
    ["description"])


def _forge(description: str) -> str:
    # Imported lazily so skills/ has finished loading first (no import cycle).
    import skill_forge
    return skill_forge.forge_skill(description)


SKILLS["forge_skill"] = {"spec": FORGE_SPEC, "run": _forge}


def learned_names() -> list[str]:
    return [n for n, s in SKILLS.items() if s.get("learned")]


def current_tool_specs() -> list[dict]:
    """The live tool list — includes any skills forged since startup. Callers
    that want the model to see newly-forged skills use this instead of the
    module-level TOOL_SPECS snapshot."""
    return [s["spec"] for s in SKILLS.values()]


load_learned()

# Snapshot at import for code that wants a stable list; use current_tool_specs()
# when freshly-forged skills must be visible without a restart.
TOOL_SPECS = current_tool_specs()
