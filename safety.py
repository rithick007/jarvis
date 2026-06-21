"""
safety.py — the layer between "the model decided" and "files actually move".

Non-negotiable rules, enforced HERE in deterministic Python (never by the
model):

  1. SCOPE     — Jarvis may only touch folders in the scoped_folders list.
                 Anything else raises ScopeError before a single byte moves.
  2. PREVIEW   — every plan of file operations is shown as a table first.
  3. CONFIRM   — nothing runs until you type 'y'.
  4. TRASH     — "delete" always means send2trash. Finder's Trash → Put Back
                 is your ultimate undo.
  5. LOG       — every executed operation is appended to jarvis_actions.jsonl
                 with a batch id, so /undo can reverse the whole batch.

Skills never move files themselves. They build a list of FileOp objects
and hand it to run_plan(), which does preview → confirm → execute → log.
"""

import ast
import json
import time
import shutil
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from send2trash import send2trash

import config

console = Console()


class ScopeError(Exception):
    """Raised when a path is outside the folders the user allowed."""


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

def scoped_roots(cfg: dict) -> list[Path]:
    return [Path(p).expanduser().resolve() for p in cfg["scoped_folders"]]


def assert_in_scope(path: Path, cfg: dict) -> None:
    """Raise ScopeError unless `path` is inside an allowed folder."""
    resolved = path.expanduser().resolve()
    for root in scoped_roots(cfg):
        if resolved == root or root in resolved.parents:
            return
    raise ScopeError(
        f"'{path}' is outside Jarvis's allowed folders.\n"
        f"Allowed: {', '.join(str(r) for r in scoped_roots(cfg))}\n"
        f"Add it with:  /scope add {path}"
    )


def resolve_folder(name: str, cfg: dict) -> Path:
    """Turn what the user/model said ('Downloads', '~/Desktop', 'sandbox')
    into a real, existing, in-scope folder path."""
    raw = name.strip().rstrip("/")
    candidates: list[Path] = []

    p = Path(raw).expanduser()
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(Path.home() / raw)            # "Downloads" → ~/Downloads
        for root in scoped_roots(cfg):
            if root.name.lower() == raw.lower():        # matches a scoped root by name
                candidates.append(root)
            candidates.append(root / raw)               # subfolder of a scoped root

    for cand in candidates:
        if cand.exists() and cand.is_dir():
            assert_in_scope(cand, cfg)
            return cand.resolve()

    raise ScopeError(f"Couldn't find a folder called '{name}' in the allowed folders.")


# ---------------------------------------------------------------------------
# File operations — the only four things Jarvis can do to a file
# ---------------------------------------------------------------------------

@dataclass
class FileOp:
    kind: str                # "move" | "rename" | "trash" | "mkdir"
    src: Path
    dst: Path | None = None  # unused for trash/mkdir(src is the new dir)

    def describe(self) -> tuple[str, str, str]:
        """(verb, from, to) strings for the preview table."""
        if self.kind == "mkdir":
            return ("create folder", str(self.src), "")
        if self.kind == "trash":
            return ("move to Trash", str(self.src), "Trash")
        return (self.kind, str(self.src), str(self.dst))


def unique_path(dst: Path) -> Path:
    """Never overwrite: if dst exists, find 'name 2.ext', 'name 3.ext', …"""
    if not dst.exists():
        return dst
    n = 2
    while True:
        cand = dst.with_name(f"{dst.stem} {n}{dst.suffix}")
        if not cand.exists():
            return cand
        n += 1


# ---------------------------------------------------------------------------
# Preview → confirm → execute → log
# ---------------------------------------------------------------------------

# The HUD (ui.py) plugs in here to render previews inside its own chat
# panel instead of printing to a terminal that isn't visible.
PREVIEW_HANDLER = None


def build_preview_table(plan: list[FileOp], title: str) -> Table:
    table = Table(title=f"Plan: {title}  ({len(plan)} operation(s))",
                  title_style="bold cyan", header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("action", style="yellow")
    table.add_column("from")
    table.add_column("to", style="green")
    home = str(Path.home())
    for i, op in enumerate(plan, 1):
        verb, src, dst = op.describe()
        table.add_row(str(i), verb, src.replace(home, "~"), dst.replace(home, "~"))
    return table


def preview(plan: list[FileOp], title: str) -> None:
    if PREVIEW_HANDLER is not None:
        PREVIEW_HANDLER(plan, title)
    else:
        console.print(build_preview_table(plan, title))


# Voice mode plugs its own spoken yes/no handler in here. When None,
# confirmation is the keyboard prompt. Either way a human always decides.
CONFIRM_HANDLER = None


def confirm() -> bool:
    if CONFIRM_HANDLER is not None:
        return CONFIRM_HANDLER()
    answer = console.input("[bold]Proceed? [y/N] [/bold]").strip().lower()
    return answer in ("y", "yes")


def run_plan(plan: list[FileOp], skill: str, title: str) -> str:
    """The one gate every destructive action passes through."""
    if not plan:
        return "Nothing to do — everything is already in order."

    cfg = config.load()
    # Defense in depth: re-check EVERY path even though skills already did.
    for op in plan:
        assert_in_scope(op.src, cfg)
        if op.dst is not None:
            assert_in_scope(op.dst, cfg)

    preview(plan, title)
    if not confirm():
        return "Cancelled — no files were touched."

    batch_id = f"{skill}-{int(time.time())}"
    done = 0
    with config.ACTION_LOG.open("a") as log:
        for op in plan:
            try:
                if op.kind == "mkdir":
                    op.src.mkdir(parents=True, exist_ok=True)
                elif op.kind == "trash":
                    send2trash(str(op.src))            # NEVER os.remove
                else:                                   # move / rename
                    final_dst = unique_path(op.dst)
                    final_dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(op.src), str(final_dst))
                    op.dst = final_dst                  # log where it really went
                log.write(json.dumps({
                    "batch": batch_id, "ts": time.time(), "skill": skill,
                    "kind": op.kind, "src": str(op.src),
                    "dst": str(op.dst) if op.dst else None,
                }) + "\n")
                done += 1
            except Exception as e:                      # keep going, report at end
                console.print(f"[red]  failed on {op.src.name}: {e}[/red]")

    return f"Done — {done}/{len(plan)} operation(s) completed. Undo with /undo."


# ---------------------------------------------------------------------------
# The action log and /undo
# ---------------------------------------------------------------------------

def _read_log() -> list[dict]:
    if not config.ACTION_LOG.exists():
        return []
    return [json.loads(line) for line in config.ACTION_LOG.read_text().splitlines() if line]


def show_log(last: int = 10) -> None:
    entries = [e for e in _read_log() if "kind" in e]   # skip undo markers
    if not entries:
        console.print("[dim]No actions logged yet.[/dim]")
        return
    table = Table(title=f"Last {min(last, len(entries))} action(s)", header_style="bold")
    table.add_column("when", style="dim")
    table.add_column("batch")
    table.add_column("action", style="yellow")
    table.add_column("file")
    for e in entries[-last:]:
        when = time.strftime("%b %d %H:%M", time.localtime(e["ts"]))
        table.add_row(when, e["batch"], e["kind"], Path(e["src"]).name)
    console.print(table)


def undo_last() -> str:
    """Reverse the most recent batch of operations (moves/renames only —
    trashed files are restored by hand: Finder → Trash → Put Back)."""
    entries = _read_log()
    undone = {e["undo_of"] for e in entries if e.get("undo_of")}
    batches = [e["batch"] for e in entries if "kind" in e and e["batch"] not in undone]
    if not batches:
        return "Nothing to undo."

    target = batches[-1]
    ops = [e for e in entries if e.get("batch") == target and "kind" in e]
    reversed_count, trash_count = 0, 0

    for e in reversed(ops):                              # reverse in reverse order
        if e["kind"] in ("move", "rename"):
            src, dst = Path(e["src"]), Path(e["dst"])
            if dst.exists():
                shutil.move(str(dst), str(unique_path(src)))
                reversed_count += 1
        elif e["kind"] == "trash":
            trash_count += 1
        elif e["kind"] == "mkdir":
            d = Path(e["src"])
            if d.exists() and not any(d.iterdir()):      # only remove if empty
                d.rmdir()

    with config.ACTION_LOG.open("a") as log:
        log.write(json.dumps({"undo_of": target, "ts": time.time()}) + "\n")

    msg = f"Undid batch '{target}': {reversed_count} file(s) moved back."
    if trash_count:
        msg += (f" {trash_count} trashed file(s) must be restored by hand:"
                " Finder → Trash → right-click → Put Back.")
    return msg


# ---------------------------------------------------------------------------
# Tiered confirmation for ANY action (not just file batches)
# ---------------------------------------------------------------------------
#
# File ops get the rich preview table above. But Jarvis now also opens apps,
# quits apps, clicks UI elements, runs scripts… so we need a way to gate ANY
# action through the same human-in-the-loop confirm. The web UI / TUI plug a
# renderer in here; with none set we fall back to the terminal.

ACTION_PREVIEW_HANDLER = None    # fn(summary: str, title: str) -> None


def confirm_action(summary: str, title: str = "Confirm action") -> bool:
    """Show `summary`, then ask the human yes/no. Returns True to proceed.
    Reuses the same CONFIRM_HANDLER the file-op path uses, so a single
    confirm modal in the UI serves every kind of action."""
    if ACTION_PREVIEW_HANDLER is not None:
        ACTION_PREVIEW_HANDLER(summary, title)
    else:
        console.print(Panel(summary, title=title, border_style="yellow"))
    return confirm()


# Skills safe enough to run with NO confirmation — they don't change or
# destroy anything the user can't trivially reverse. Everything NOT in here
# (quitting apps, mutating UI, deleting, running scripts) must gate itself
# with confirm_action() or run_plan(). The agent loop also consults this to
# decide whether a step needs the human in the loop.
SAFE_SKILLS = {
    "mac_status", "search_documents", "index_documents", "analyze_image",
    "remember_fact", "rewrite_text",
    "open_app", "focus_app", "web_search", "open_url",
    "set_volume", "set_brightness", "media_control",
    "ax_read_screen", "list_apps",
}


def is_safe(skill_name: str) -> bool:
    return skill_name in SAFE_SKILLS


# ---------------------------------------------------------------------------
# Static safety scan for forged (model-written) skills
# ---------------------------------------------------------------------------
#
# The Skill Forge lets the model WRITE NEW CODE that Jarvis will then run.
# That is powerful and dangerous, so no forged skill is allowed to exist
# until this scan passes. It is deterministic Python — never the model — that
# decides what code is acceptable. Rules: no arbitrary deletion, no shell, no
# network, no dynamic exec. File changes must go through THIS module's
# run_plan(), which re-enforces scope + Trash-only deletes at run time.

# Modules a forged skill may not import at all.
_FORBIDDEN_IMPORTS = {
    "subprocess", "socket", "requests", "urllib", "http", "httpx",
    "ftplib", "telnetlib", "smtplib", "ctypes", "pickle", "marshal",
}

# Dotted call names a forged skill may not invoke.
_FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "__import__", "open",        # use safety/pathlib
    "os.system", "os.popen", "os.remove", "os.unlink", "os.rmdir",
    "os.removedirs", "os.rename", "os.replace", "os.execv", "os.execve",
    "shutil.rmtree", "shutil.move", "shutil.copy", "shutil.copytree",
    "pathlib.Path.unlink", "Path.unlink", "Path.rmdir", "Path.write_text",
    "Path.write_bytes", "send2trash.send2trash",
}


def _dotted(node: ast.AST) -> str:
    """Best-effort dotted name for an ast.Attribute/Name (e.g. 'os.remove')."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def scan_skill_source(source: str) -> list[str]:
    """Return a list of human-readable violations. Empty list == the code is
    allowed to be forged. Any non-empty list means: reject, do not save."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"syntax error: {e}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_IMPORTS:
                    violations.append(f"forbidden import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _FORBIDDEN_IMPORTS:
                violations.append(f"forbidden import from: {node.module}")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name in _FORBIDDEN_CALLS:
                violations.append(f"forbidden call: {name}()")
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted in _FORBIDDEN_CALLS:
                violations.append(f"forbidden reference: {dotted}")

    # De-dup, keep order.
    seen, out = set(), []
    for v in violations:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
