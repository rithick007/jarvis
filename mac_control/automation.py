"""
mac_control/automation.py — the power tools, gated hard.

When no specific skill fits, Jarvis can fall back to raw AppleScript or a
shell command. This is how "full automation" is possible — and also the most
dangerous thing in the codebase — so BOTH always show the exact script and
demand an explicit confirm before a single character runs. There is no
allowlist bypass here, ever.
"""

import subprocess

import safety
from mac_control import osa


def run_applescript(script: str) -> str:
    """Run an arbitrary AppleScript — only after the human approves it."""
    script = script.strip()
    if not script:
        return "There was no script to run."
    if not safety.confirm_action(
            f"Run this AppleScript?\n\n{script}", title="Run AppleScript"):
        return "Held off — nothing was run."
    ok, out = osa(script, timeout=60)
    if not ok:
        return f"The script errored: {out}"
    return f"Done. {out}" if out else "Done — the script ran cleanly."


def run_shell(command: str) -> str:
    """Run an arbitrary shell command — only after the human approves it.
    This is intentionally the most heavily-gated action Jarvis has."""
    command = command.strip()
    if not command:
        return "There was no command to run."
    if not safety.confirm_action(
            f"Run this shell command?\n\n$ {command}", title="Run shell command"):
        return "Held off — nothing was run."
    try:
        proc = subprocess.run(command, shell=True, capture_output=True,
                              text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "The command timed out after 60 seconds."
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return f"Exited with code {proc.returncode}. {err or out}".strip()
    return f"Done.\n{out}" if out else "Done — no output."
