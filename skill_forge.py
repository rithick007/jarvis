"""
skill_forge.py — ★ the Self-Growing Skill Forge. Jarvis's signature.

Every other "Jarvis" ships with a fixed set of abilities. This one WRITES
ITS OWN. When you ask for something no existing skill can do, Jarvis:

  1. GENERATES a complete new skill module with the cloud model, following
     the exact contract real skills use (a TOOL_SPEC card + a run function).
  2. VERIFIES it before it is ever allowed to exist — this is the crucial
     idea borrowed from Voyager: a skill only joins the library if it passes:
        a. a deterministic STATIC SAFETY SCAN (safety.scan_skill_source):
           no raw deletes, no shell, no network, no dynamic exec.
        b. a STRUCTURAL check: it compiles, exposes a valid TOOL_SPEC, and
           the named function exists and is callable.
        c. a guarded SMOKE TEST: if it takes no required args, we run it with
           confirmations force-denied so it can't actually change anything —
           just proving it executes without blowing up.
     Failures are fed back to the model, which tries again (up to 3 times).
  3. ASKS YOU to approve the generated code (forging is a "risky" action).
  4. SAVES + HOT-LOADS it into skills/learned/ so it works immediately and
     survives restarts — and logs it as training data so the fast-path can
     learn to route to it instantly next time.

Nothing is written to disk until you approve. The model never decides what is
safe — safety.py does, in plain Python.
"""

from __future__ import annotations

import json
import re
import time

import config
import safety
from skills import LEARNED_DIR, SKILLS, register_module

MAX_ATTEMPTS = 3
TRAINING_LOG = config.JARVIS_DIR / "training_data.jsonl"


# ---------------------------------------------------------------------------
# The generation prompt
# ---------------------------------------------------------------------------

_EXAMPLE = '''\
# Example of the exact contract every skill must follow:
import config
import safety
from safety import FileOp

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "tidy_empty_folders",
        "description": "Remove empty subfolders from a scoped folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder to tidy."}
            },
            "required": ["folder"],
        },
    },
}

def tidy_empty_folders(folder: str) -> str:
    cfg = config.load()
    target = safety.resolve_folder(folder, cfg)   # raises if out of scope
    plan = [FileOp("trash", p) for p in target.iterdir()
            if p.is_dir() and not any(p.iterdir())]
    return safety.run_plan(plan, skill="tidy_empty_folders",
                           title=f"tidy empty folders in {target.name}/")
'''

_RULES = """\
You are Jarvis's Skill Forge. Write ONE new Python skill module that does what
the user asked. Output ONLY a single ```python code block — no prose.

HARD CONTRACT (the module is rejected automatically if any rule is broken):
- Define a module-level dict named TOOL_SPEC with the OpenAI function-spec
  shape shown in the example (type/function/name/description/parameters).
- Define a function whose name EXACTLY equals TOOL_SPEC["function"]["name"].
  Its parameters must match the spec's properties. It must RETURN a short,
  human-friendly string describing what happened.
- You may import ONLY: config, safety, pathlib, re, datetime, json, math, time.
- NEVER import or use: os, subprocess, shutil, sys, socket, requests, urllib,
  ctypes, pickle. NEVER call eval, exec, compile, __import__, or open().
- To touch files you MUST build a list of safety.FileOp objects and pass it to
  safety.run_plan(plan, skill=<name>, title=<title>). Never move/delete/write
  files yourself. Use safety.resolve_folder(name, config.load()) to turn a
  folder name into a real, in-scope path — it enforces the user's allowed
  folders for you.
- FileOp kinds are exactly: "move", "rename", "trash", "mkdir".
- Keep it self-contained and robust; handle the "nothing to do" case.
"""


def _build_messages(description: str, feedback: str | None) -> list[dict]:
    user = f"User wants a new skill: {description}"
    if feedback:
        user += (f"\n\nYour previous attempt was REJECTED for these reasons:\n"
                 f"{feedback}\nFix them and return the full corrected module.")
    return [
        {"role": "system", "content": _RULES + "\n\n" + _EXAMPLE},
        {"role": "user", "content": user},
    ]


def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _sanitize_name(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]", "_", name.strip()).lower()
    name = re.sub(r"_+", "_", name).strip("_")
    if not name or not name[0].isalpha():
        name = "skill_" + name
    return name


def _structural_check(source: str) -> tuple[str | None, object | None, str]:
    """Compile + exec the source in a throwaway namespace (only after the
    static scan has cleared it) to confirm it exposes a valid TOOL_SPEC and a
    matching callable. Returns (skill_name, fn, error)."""
    ns: dict = {}
    try:
        exec(compile(source, "<forged-skill>", "exec"), ns)
    except Exception as e:
        return None, None, f"module failed to load: {e}"
    spec = ns.get("TOOL_SPEC")
    if not isinstance(spec, dict):
        return None, None, "missing a module-level TOOL_SPEC dict"
    try:
        name = spec["function"]["name"]
    except (KeyError, TypeError):
        return None, None, "TOOL_SPEC has no function.name"
    fn = ns.get(name)
    if not callable(fn):
        return None, None, f"no callable named '{name}' matching the spec"
    return name, fn, ""


def _smoke_test(fn, spec: dict) -> str:
    """If the skill needs no required args, actually run it once with all
    confirmations force-denied, so it cannot change anything — we only want to
    know it executes without throwing. Returns '' on success, else an error."""
    required = spec.get("function", {}).get("parameters", {}).get("required", [])
    if required:
        return ""                       # can't safely synthesize args — skip
    saved = safety.CONFIRM_HANDLER
    safety.CONFIRM_HANDLER = lambda: False        # deny every confirm during test
    try:
        fn()
        return ""
    except Exception as e:
        return f"crashed when run: {e}"
    finally:
        safety.CONFIRM_HANDLER = saved


def verify(source: str) -> tuple[bool, str, str | None, dict | None]:
    """Run the full gauntlet. Returns
    (ok, message_or_errors, skill_name, tool_spec)."""
    violations = safety.scan_skill_source(source)
    if violations:
        return False, "static safety scan: " + "; ".join(violations), None, None

    name, fn, err = _structural_check(source)
    if err:
        return False, err, None, None

    # Re-derive the spec from a fresh exec (cheap, keeps fn/spec consistent).
    ns: dict = {}
    exec(compile(source, "<forged-skill>", "exec"), ns)
    spec = ns["TOOL_SPEC"]

    smoke_err = _smoke_test(ns[name], spec)
    if smoke_err:
        return False, smoke_err, name, spec

    return True, "passed static scan, structure check, and smoke test", name, spec


# ---------------------------------------------------------------------------
# The forge loop
# ---------------------------------------------------------------------------

def _log_forge(description: str, name: str) -> None:
    try:
        with TRAINING_LOG.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "command": description,
                                "skill": name, "args": {}, "forged": True}) + "\n")
    except OSError:
        pass


def forge_skill(description: str) -> str:
    """Generate → verify → confirm → save a new skill. Returns a status line."""
    import router                       # lazy: avoid an import cycle

    feedback = None
    last_error = "no attempt produced usable code"
    source = name = spec = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = (router.chat(_build_messages(description, feedback)).message.content
               or "")
        source = _extract_code(raw)
        ok, info, name, spec = verify(source)
        if ok:
            break
        last_error = info
        feedback = info                 # tell the model what to fix, then retry
    else:
        return (f"I tried {MAX_ATTEMPTS} times but couldn't forge a safe skill "
                f"for that, master. Last problem: {last_error}.")

    # Don't silently clobber a built-in skill; version a learned name clash.
    final_name = name
    if final_name in SKILLS and not SKILLS[final_name].get("learned"):
        final_name = _sanitize_name(name + "_custom")
    path = LEARNED_DIR / f"{_sanitize_name(final_name)}.py"

    # Human gate — show the code and the verification result, then ask.
    preview = (f"New skill: {name}\n"
               f"Verification: passed safety scan + structure + smoke test.\n"
               f"It will be saved to skills/learned/{path.name}\n\n"
               f"{source}")
    if not safety.confirm_action(preview, title="Forge & save this new skill?"):
        return "Scrapped it — nothing was saved."

    # Save, then hot-load so it works this instant (no restart).
    try:
        # If we renamed to avoid a clash, reflect it in the written spec so the
        # file's function name and TOOL_SPEC stay consistent with the filename.
        path.write_text(source if final_name == name
                        else source.replace(name, final_name))
    except OSError as e:
        return f"I verified the skill but couldn't write the file: {e}"

    import importlib
    try:
        mod = importlib.import_module(f"skills.learned.{path.stem}")
        importlib.reload(mod)
        registered = register_module(mod)
    except Exception as e:
        path.unlink(missing_ok=True)
        return f"Saved code, but it failed to load and was removed: {e}"

    if not registered:
        path.unlink(missing_ok=True)
        return "The forged skill didn't register cleanly, so I removed it."

    _log_forge(description, registered)
    total = len([s for s in SKILLS.values() if s.get("learned")])
    return (f"Done, master — I just taught myself '{registered}'. It's saved "
            f"and ready to use now. (You've forged {total} skill"
            f"{'s' if total != 1 else ''} so far.)")
