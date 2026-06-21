"""
mac_control/system.py — volume, brightness, playback, lock, sleep, notify.

Volume / brightness / playback are trivially reversible → instant.
Locking the screen and sleeping the display interrupt you → they ask first.
"""

import safety
from mac_control import osa


def set_volume(level) -> str:
    """Set output volume. Accepts 0-100, or 'up'/'down'/'mute'/'unmute'."""
    s = str(level).strip().lower()
    if s in ("mute", "off", "silence"):
        osa("set volume with output muted")
        return "Muted."
    if s in ("unmute", "on"):
        osa("set volume without output muted")
        return "Unmuted."
    if s in ("up", "louder", "increase"):
        osa("set volume output volume (output volume of (get volume settings) + 12)")
        return "Volume up."
    if s in ("down", "quieter", "lower", "decrease"):
        osa("set volume output volume (output volume of (get volume settings) - 12)")
        return "Volume down."
    try:
        pct = max(0, min(100, int(float(s))))
    except ValueError:
        return f"I didn't understand the volume '{level}'."
    osa(f"set volume output volume {pct}")
    return f"Volume set to {pct} percent."


def set_brightness(level) -> str:
    """Step display brightness. Accepts 'up'/'down' (reliable everywhere) or
    a 0-100 number (best-effort, needs the `brightness` CLI if installed)."""
    s = str(level).strip().lower()
    if s in ("up", "brighter", "increase"):
        ok, out = osa('tell application "System Events" to key code 144')
        return "Brightness up." if ok else f"Couldn't change brightness: {out}"
    if s in ("down", "dimmer", "decrease", "lower"):
        ok, out = osa('tell application "System Events" to key code 145')
        return "Brightness down." if ok else f"Couldn't change brightness: {out}"
    # Numeric set — try the optional `brightness` tool (brew install brightness).
    try:
        pct = max(0, min(100, int(float(s))))
    except ValueError:
        return f"I didn't understand the brightness '{level}'."
    import shutil
    import subprocess
    if shutil.which("brightness"):
        subprocess.run(["brightness", f"{pct / 100:.2f}"], capture_output=True)
        return f"Brightness set to {pct} percent."
    return ("I can nudge brightness up or down, but setting an exact level "
            "needs the 'brightness' tool (brew install brightness).")


def media_control(action: str, app: str = "") -> str:
    """play/pause/next/previous for Spotify or Music. Tries the named app,
    else whichever music app is running."""
    action = action.strip().lower()
    verb = {
        "play": "play", "pause": "pause", "playpause": "playpause",
        "toggle": "playpause", "next": "next track", "skip": "next track",
        "previous": "previous track", "back": "previous track",
        "prev": "previous track",
    }.get(action)
    if not verb:
        return f"I can play, pause, skip or go back — not '{action}'."

    candidates = [app] if app else ["Spotify", "Music"]
    for name in candidates:
        if not name:
            continue
        running, _ = osa(f'application "{name}" is running')
        if running == "true" or app:
            ok, out = osa(f'tell application "{name}" to {verb}')
            if ok:
                return f"{action.capitalize()} on {name}."
    return "No music app seems to be running, master."


def lock_screen() -> str:
    """Lock the Mac — gated so a misheard command doesn't boot you out."""
    if not safety.confirm_action("Lock the screen now?", title="Lock screen"):
        return "Kept it unlocked."
    ok, out = osa('tell application "System Events" to keystroke "q" '
                  'using {control down, command down}')
    return "Locked." if ok else f"Couldn't lock: {out}"


def sleep_display() -> str:
    """Put the display to sleep — gated."""
    if not safety.confirm_action("Put the display to sleep?", title="Sleep display"):
        return "Display stays awake."
    import subprocess
    try:
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True, timeout=10)
        return "Display sleeping."
    except Exception as e:
        return f"Couldn't sleep the display: {e}"


def notification(text: str, title: str = "JARVIS") -> str:
    """Post a macOS notification banner. Harmless → instant."""
    safe_text = text.replace('"', "'")
    safe_title = title.replace('"', "'")
    ok, out = osa(f'display notification "{safe_text}" with title "{safe_title}"')
    return "Notified." if ok else f"Couldn't post the notification: {out}"
