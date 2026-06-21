"""
mac_control/apps.py — open, focus, quit, and list applications.

open/focus are safe (you can always close again), so they run instantly.
quit can lose unsaved work, so it asks first via safety.confirm_action.
"""

import subprocess

import safety
from mac_control import osa


def open_app(name: str) -> str:
    """Launch (or reveal) an app by name. 'Spotify', 'Safari', 'Notes'…"""
    name = name.strip()
    try:
        proc = subprocess.run(["open", "-a", name],
                              capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"Couldn't open {name}: {e}"
    if proc.returncode != 0:
        # `open -a` prints "Unable to find application named '…'"
        return f"I couldn't find an app called {name}, master."
    return f"Opening {name}."


def focus_app(name: str) -> str:
    """Bring an already-running app to the front."""
    name = name.strip()
    ok, out = osa(f'tell application "{name}" to activate')
    return f"{name} is front and center." if ok else f"Couldn't focus {name}: {out}"


def quit_app(name: str) -> str:
    """Quit an app — gated, since it can discard unsaved work."""
    name = name.strip()
    if not safety.confirm_action(f"Quit {name}?", title="Quit application"):
        return "Left it running, master."
    ok, out = osa(f'tell application "{name}" to quit')
    return f"{name} closed." if ok else f"Couldn't quit {name}: {out}"


def list_apps() -> str:
    """Name the foreground (non-background) apps currently running."""
    ok, out = osa(
        'tell application "System Events" to get the name of every process '
        'whose background only is false')
    if not ok:
        return f"Couldn't read the app list: {out}"
    apps = ", ".join(sorted(a.strip() for a in out.split(",") if a.strip()))
    return f"Currently running: {apps}." if apps else "Nothing notable is running."
