"""
skills/organizer.py — Skill 1: the File Organizer.

Four actions, all built the same way: scan the folder, build a list of
FileOp objects describing what SHOULD happen, then hand the whole plan
to safety.run_plan() — which previews it, asks for confirmation,
executes, and logs. This skill never moves a file itself.

  rename_by_date   → prefix files with their creation date (2026-06-10 ...)
  move_screenshots → gather screenshots into a Screenshots/ subfolder
  sort_by_type     → file everything into Images/, Documents/, Video/ …
  trash_installers → move old .dmg/.pkg installers to the Trash
"""

import re
import time
from datetime import datetime
from pathlib import Path

import config
import safety
from safety import FileOp

# File-extension buckets for sort_by_type. Tweak freely.
BUCKETS = {
    "Images":     {".png", ".jpg", ".jpeg", ".gif", ".heic", ".webp", ".svg", ".tiff", ".bmp"},
    "Documents":  {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".pages", ".key",
                   ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".numbers", ".epub"},
    "Audio":      {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"},
    "Video":      {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"},
    "Archives":   {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2"},
    "Installers": {".dmg", ".pkg"},
    "Code":       {".py", ".js", ".ts", ".html", ".css", ".json", ".sh", ".ipynb", ".c", ".cpp"},
}

SCREENSHOT_HINTS = ("screen shot", "screenshot", "cleanshot", "screen recording")
DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")
INSTALLER_AGE_DAYS = 30


def _visible_files(folder: Path) -> list[Path]:
    """Top-level, non-hidden files only. We never recurse — predictable."""
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and not p.name.startswith("."))


def _bucket_for(path: Path) -> str:
    for bucket, exts in BUCKETS.items():
        if path.suffix.lower() in exts:
            return bucket
    return "Other"


def _build_plan(folder: Path, action: str) -> list[FileOp]:
    plan: list[FileOp] = []

    if action == "rename_by_date":
        for f in _visible_files(folder):
            if DATE_PREFIX.match(f.name):
                continue                                  # already done
            created = datetime.fromtimestamp(f.stat().st_birthtime)
            new_name = f"{created:%Y-%m-%d} {f.name}"
            plan.append(FileOp("rename", f, f.with_name(new_name)))

    elif action == "move_screenshots":
        dest = folder / "Screenshots"
        shots = [f for f in _visible_files(folder)
                 if any(h in f.name.lower() for h in SCREENSHOT_HINTS)]
        if shots:
            plan.append(FileOp("mkdir", dest))
            plan += [FileOp("move", f, dest / f.name) for f in shots]

    elif action == "sort_by_type":
        moves: list[FileOp] = []
        needed_dirs: set[Path] = set()
        for f in _visible_files(folder):
            bucket = folder / _bucket_for(f)
            needed_dirs.add(bucket)
            moves.append(FileOp("move", f, bucket / f.name))
        plan = [FileOp("mkdir", d) for d in sorted(needed_dirs)] + moves

    elif action == "trash_installers":
        cutoff = time.time() - INSTALLER_AGE_DAYS * 86400
        for f in _visible_files(folder):
            if f.suffix.lower() in BUCKETS["Installers"] and f.stat().st_mtime < cutoff:
                plan.append(FileOp("trash", f))

    return plan


def organize_files(folder: str, action: str) -> str:
    cfg = config.load()
    target = safety.resolve_folder(folder, cfg)           # raises ScopeError if not allowed

    valid = ("rename_by_date", "move_screenshots", "sort_by_type", "trash_installers")
    if action not in valid:
        return f"Unknown action '{action}'. I know: {', '.join(valid)}."

    plan = _build_plan(target, action)
    pretty = action.replace("_", " ")
    return safety.run_plan(plan, skill="organize_files",
                           title=f"{pretty} in {target.name}/")
