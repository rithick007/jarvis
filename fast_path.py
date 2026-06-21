"""
fast_path.py — instant, no-model command routing.

The single biggest reason a "Jarvis" feels sluggish is that EVERY utterance
takes a round-trip to a model before anything happens. But most of what you
actually say is simple and unambiguous: "open Spotify", "volume up", "next
track", "lock the screen". Those shouldn't wait on a network.

match() recognizes those with plain regex and returns the skill + args in
well under a millisecond. Anything it isn't sure about returns None and falls
through to the real router (router.route), which asks the cloud model. So the
fast path only ever *speeds things up* — it never guesses when it shouldn't.

Design rule: be CONSERVATIVE. If a phrase could plausibly mean something
else (e.g. "search" might mean searching your documents, "open downloads"
might mean a folder), let the model handle it.
"""

import re

# Filler/wake words stripped before matching.
_LEAD = re.compile(r"^(hey\s+|ok\s+|okay\s+)?jarvis[\s,]+|^(please|can you|could you|"
                   r"would you)\s+", re.IGNORECASE)

# Words that mean "this is about files/folders, not an app" — bail to the model.
_FILEY = ("folder", "file", "document", "downloads", "desktop", "trash",
          "directory")


def _clean(command: str) -> str:
    c = command.strip()
    prev = None
    while c != prev:                      # strip stacked prefixes ("jarvis, please …")
        prev = c
        c = _LEAD.sub("", c).strip()
    return c.rstrip(" .!?")


def match(command: str):
    """Return (skill_name, args_dict) for a confidently-recognized command,
    else None to defer to the model."""
    c = _clean(command)
    low = c.lower()
    if not low:
        return None

    # --- media playback -----------------------------------------------------
    if low in ("play", "resume", "play music"):
        return "media_control", {"action": "play"}
    if low in ("pause", "pause music", "stop music", "stop the music"):
        return "media_control", {"action": "pause"}
    if low in ("next", "next track", "next song", "skip", "skip song",
               "skip track", "skip this"):
        return "media_control", {"action": "next"}
    if low in ("previous", "previous track", "previous song", "go back a track",
               "last song"):
        return "media_control", {"action": "previous"}

    # --- volume -------------------------------------------------------------
    if low in ("mute", "mute it", "silence", "mute the volume"):
        return "set_volume", {"level": "mute"}
    if low in ("unmute", "unmute it", "sound on"):
        return "set_volume", {"level": "unmute"}
    if re.fullmatch(r"(turn (the )?)?volume up|louder|turn it up", low):
        return "set_volume", {"level": "up"}
    if re.fullmatch(r"(turn (the )?)?volume down|quieter|turn it down", low):
        return "set_volume", {"level": "down"}
    m = re.fullmatch(r"(set |turn )?(the )?volume (to |at )?(\d{1,3})%?", low)
    if m:
        return "set_volume", {"level": m.group(4)}

    # --- brightness ---------------------------------------------------------
    if re.fullmatch(r"(turn (the )?)?brightness up|brighter", low):
        return "set_brightness", {"level": "up"}
    if re.fullmatch(r"(turn (the )?)?brightness down|dimmer|darker", low):
        return "set_brightness", {"level": "down"}
    m = re.fullmatch(r"(set )?(the )?brightness (to |at )?(\d{1,3})%?", low)
    if m:
        return "set_brightness", {"level": m.group(4)}

    # --- screen / system ----------------------------------------------------
    if low in ("lock", "lock screen", "lock the screen", "lock my mac",
               "lock the mac", "lock it"):
        return "lock_screen", {}
    if low in ("sleep the display", "sleep display", "turn off the display",
               "turn off the screen"):
        return "sleep_display", {}
    if low in ("what's running", "whats running", "list apps",
               "what apps are open", "what's open", "whats open"):
        return "list_apps", {}
    if low in ("read the screen", "read screen", "what's on screen",
               "whats on the screen", "what's on the screen", "what do you see"):
        return "ax_read_screen", {}
    if re.search(r"\b(battery|disk space|storage|system status|how('s| is) "
                 r"my (battery|mac|disk|storage))\b", low) and len(low) < 40:
        return "mac_status", {}

    # --- web ----------------------------------------------------------------
    m = re.match(r"(google|search (the web|google|online) for|look up)\s+(.+)",
                 low)
    if m:
        # use the original-case tail for a nicer query
        query = c[m.start(3):].strip() if m.lastindex and m.start(3) >= 0 else m.group(3)
        return "web_search", {"query": query}

    # --- open: app vs url ---------------------------------------------------
    m = re.match(r"(open|launch|start|fire up|switch to|focus)\s+(.+)", low,
                 re.IGNORECASE)
    if m:
        verb = m.group(1).lower()
        target_raw = c[m.start(2):].strip()           # preserve original case
        target_low = target_raw.lower()
        if any(w in target_low for w in _FILEY):
            return None                               # a folder/file → let model decide
        # URL/domain → open in browser
        if (target_low.startswith(("http://", "https://"))
                or re.fullmatch(r"[\w-]+(\.[\w-]+)+(/.*)?", target_low)):
            return "open_url", {"url": target_raw}
        if verb in ("switch to", "focus"):
            return "focus_app", {"name": target_raw}
        return "open_app", {"name": target_raw}

    # --- quit ---------------------------------------------------------------
    m = re.match(r"(quit|close|exit)\s+(.+)", low, re.IGNORECASE)
    if m:
        target_raw = c[m.start(2):].strip()
        if any(w in target_raw.lower() for w in _FILEY):
            return None
        return "quit_app", {"name": target_raw}

    return None
