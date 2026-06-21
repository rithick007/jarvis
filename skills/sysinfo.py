"""
skills/sysinfo.py — Skill 4 (bonus): Mac status report.

Strictly READ-ONLY. It runs exactly two fixed commands (pmset for battery,
uptime) plus Python's own disk-usage call. The model cannot inject
arbitrary shell commands here — there is no parameter that reaches a shell.
"""

import shutil
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def mac_status() -> str:
    lines = []

    # Battery — parse pmset's "85%; discharging; 4:32 remaining" line.
    batt = _run(["pmset", "-g", "batt"])
    for line in batt.splitlines():
        if "%" in line:
            lines.append("Battery:  " + line.split("\t")[-1].strip())
            break

    # Disk space on the volume holding your home folder.
    du = shutil.disk_usage(Path.home())
    free_gb, total_gb = du.free / 1e9, du.total / 1e9
    pct = du.used / du.total * 100
    lines.append(f"Disk:     {free_gb:.0f} GB free of {total_gb:.0f} GB ({pct:.0f}% used)")

    # Uptime — how long since the last reboot.
    up = _run(["uptime"])
    if "up" in up:
        lines.append("Uptime:   " + up.split("up", 1)[1].split(",")[0].strip())

    return "\n".join(lines) if lines else "Couldn't read system status."
