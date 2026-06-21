"""
mac_control/ — Jarvis's hands on the Mac.

The old Jarvis could organize files and read vitals. This package lets him
actually *operate* the machine: open and quit apps, turn the volume and
brightness, control playback, search the web, read and click UI elements
through the macOS Accessibility tree, and — gated hard — run AppleScript or
shell when nothing else fits.

The safety contract is the same one the file skills use: anything that
changes or could surprise you (quitting an app, clicking a button, locking
the screen, running a script) routes through safety.confirm_action() first.
Read-only or trivially-reversible things (open an app, set the volume,
search the web) just happen, so Jarvis still feels instant.

Each function returns a short, spoken-word-friendly string — exactly what the
skills layer expects.
"""

import subprocess


def osa(script: str, timeout: int = 15) -> tuple[bool, str]:
    """Run one AppleScript via osascript. Returns (ok, output_or_error)."""
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "the command timed out"
    except FileNotFoundError:
        return False, "osascript isn't available on this system"
    if proc.returncode != 0:
        err = (proc.stderr or "AppleScript failed").strip()
        low = err.lower()
        if "-1743" in err or "not allowed" in low or "not authorized" in low or "assistive" in low:
            err = ("I need macOS permission for that, sir — enable this app under "
                   "System Settings > Privacy & Security > Automation and "
                   "Accessibility, then ask again.")
        return False, err
    return True, proc.stdout.strip()


from mac_control.apps import open_app, quit_app, focus_app, list_apps
from mac_control.system import (
    set_volume, set_brightness, media_control, lock_screen, sleep_display,
    notification,
)
from mac_control.web import web_search, open_url
from mac_control.accessibility import ax_read_screen, ax_click, ax_set_value
from mac_control.automation import run_applescript, run_shell

__all__ = [
    "osa",
    "open_app", "quit_app", "focus_app", "list_apps",
    "set_volume", "set_brightness", "media_control", "lock_screen",
    "sleep_display", "notification",
    "web_search", "open_url",
    "ax_read_screen", "ax_click", "ax_set_value",
    "run_applescript", "run_shell",
]
