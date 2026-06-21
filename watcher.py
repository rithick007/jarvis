"""
watcher.py — the Sentinel: Jarvis's background watch ("taking care of
things at night").

A daemon thread that wakes every CHECK_INTERVAL seconds and looks at:

  • battery   — warns at 15%, urgently at 7% (once per discharge, not
                every minute — it remembers what it already told you)
  • disk      — warns when the home volume crosses 90%, again at 95%
  • downloads — counts new files landing in ~/Downloads and mentions
                them every few, so you know clutter is building

STRICTLY READ-ONLY by design. The Sentinel observes and announces; it
never moves, deletes, or organizes anything on its own. Acting always
goes through you + the safety layer. (An assistant that silently
rearranges your files at 3 a.m. is a horror movie, not a feature.)

Alerts go through a callback so main.py decides how to deliver them:
printed in the terminal, and spoken aloud if voice mode is on.
"""

import shutil
import subprocess
import threading
import time
from pathlib import Path

CHECK_INTERVAL = 60          # seconds between patrols
DOWNLOADS = Path.home() / "Downloads"


def _battery_percent() -> int | None:
    out = subprocess.run(["pmset", "-g", "batt"],
                         capture_output=True, text=True).stdout
    for token in out.replace(";", " ").split():
        if token.endswith("%"):
            try:
                return int(token.rstrip("%"))
            except ValueError:
                return None
    return None


def _charging() -> bool:
    out = subprocess.run(["pmset", "-g", "batt"],
                         capture_output=True, text=True).stdout
    return "AC Power" in out or "charging" in out.lower()


class Sentinel(threading.Thread):
    """Background patrol. Start with .start(), stop with .stop()."""

    def __init__(self, on_alert):
        super().__init__(daemon=True)        # dies with the main program
        self.on_alert = on_alert             # callback: fn(message: str)
        self._stop_flag = threading.Event()
        # Memory of what we've already said, so we don't nag.
        self._warned_battery = set()         # {15, 7}
        self._warned_disk = set()            # {90, 95}
        self._baseline_downloads = self._count_downloads()
        self._announced_downloads = 0

    # -- individual checks ----------------------------------------------------

    def _count_downloads(self) -> int:
        if not DOWNLOADS.exists():
            return 0
        return sum(1 for p in DOWNLOADS.iterdir()
                   if p.is_file() and not p.name.startswith("."))

    def _check_battery(self) -> None:
        pct = _battery_percent()
        if pct is None:
            return
        if _charging():
            self._warned_battery.clear()     # reset warnings once plugged in
            return
        for threshold, tone in ((7, "Urgent, sir — battery at"),
                                (15, "Heads up — battery is at")):
            if pct <= threshold and threshold not in self._warned_battery:
                self._warned_battery.add(threshold)
                self.on_alert(f"{tone} {pct} percent. Recommend plugging in.")
                break

    def _check_disk(self) -> None:
        du = shutil.disk_usage(Path.home())
        pct = du.used / du.total * 100
        for threshold in (95, 90):
            if pct >= threshold and threshold not in self._warned_disk:
                self._warned_disk.add(threshold)
                free_gb = du.free / 1e9
                self.on_alert(f"Storage notice: disk is {pct:.0f} percent full "
                              f"— {free_gb:.0f} gigabytes free. I can sort or "
                              f"clean Downloads whenever you ask.")
                break

    def _check_downloads(self) -> None:
        now = self._count_downloads()
        new = now - self._baseline_downloads
        if new >= self._announced_downloads + 5:     # speak every 5 new files
            self._announced_downloads = new
            self.on_alert(f"{new} new file(s) have landed in Downloads since "
                          f"I started watching. Say the word and I'll sort them.")

    # -- the patrol loop --------------------------------------------------------

    def run(self) -> None:
        while not self._stop_flag.is_set():
            try:
                self._check_battery()
                self._check_disk()
                self._check_downloads()
            except Exception:
                pass                          # a failed patrol never kills the thread
            self._stop_flag.wait(CHECK_INTERVAL)

    def stop(self) -> None:
        self._stop_flag.set()
