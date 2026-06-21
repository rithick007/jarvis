"""
agent_loop.py — the agentic brain: reason → act → observe → repeat.

The old planner (agents.py) asked a small local model to emit a fixed JSON
list of steps up front. That's brittle: it can't react to what a step
actually returns. This loop is the modern alternative — a ReAct-style tool
loop on the cloud model:

    model proposes a tool call
        → we run it through the safety layer
        → feed the real result back to the model
        → it decides the next step (or that it's done)

So "open Notes, read what's on screen, and summarize it" works: the model
opens Notes, calls ax_read_screen, SEES the result, then writes the summary.
If no tool fits, the model can call forge_skill to build one on the spot.

Skills self-gate (risky ones call safety.confirm_action), so the loop never
has to know which actions are dangerous — it just runs them and reports back.
agents.py stays as the lightweight/offline fallback.
"""

from __future__ import annotations

import json

import brain
import memory
from skills import SKILLS, current_tool_specs

MAX_STEPS = 8

AGENT_SYSTEM = (
    "You are JARVIS — Tony Stark's AI butler — running on and fully in command "
    "of this Mac. Persona: composed, precise, quietly witty, unfailingly loyal. "
    "Address the user as 'sir'. You speak; you don't write — every reply is read "
    "aloud, so keep it to ONE or two short, natural spoken sentences. Never use "
    "markdown, lists, code blocks, or emoji.\n"
    "You genuinely control this machine through your tools — open/close/focus "
    "apps, click and type into any app via the accessibility tree, set volume "
    "and brightness, control media, search the web and documents, manage files, "
    "lock the screen, remember facts, run AppleScript/shell, and read the "
    "screen. Act with confidence.\n"
    "Rules:\n"
    "- DO the thing with a tool; never say you can't or that you're just an AI. "
    "If a tool exists, call it.\n"
    "- Prefer the specific tool; use run_shell/run_applescript only as a last "
    "resort for things no other tool covers.\n"
    "- To act on what's on screen, call ax_read_screen first, then act.\n"
    "- For a repeatable ability you lack, call forge_skill instead of refusing.\n"
    "- If a tool reports a macOS permission is missing, tell the user exactly "
    "what to enable, in one sentence.\n"
    "- After acting, confirm crisply in character — e.g. 'Done, sir.' or a "
    "one-line result. Don't narrate what you're about to do.\n"
    "- If a tool's result is an error or starts with 'blocked'/'failed'/'I need', "
    "relay that problem to the user in one sentence — never just say 'Done'. "
    "Do not silently retry the same failing tool more than once."
)


def _noop(kind: str, data) -> None:
    pass


def _memory_context(command: str) -> list[dict]:
    try:
        facts = memory.recall(command)
    except Exception:
        return []
    if not facts:
        return []
    return [{"role": "system",
             "content": "Known facts about the user: " + " ".join(facts)}]


def run(command: str, run_skill, emit=_noop, history: list[dict] | None = None,
        max_steps: int = MAX_STEPS) -> str:
    """Drive the task to completion.

    run_skill(name, args) -> result string  (caller wires this to the safety
        layer; it should never raise — return an error string instead).
    emit(kind, data)  optional callback for streaming UI updates; kinds:
        'thinking', 'tool', 'tool_result', 'final'.
    """
    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM}]
    messages += _memory_context(command)
    if history:
        messages += history
    messages.append({"role": "user", "content": command})

    final = ""
    for _step in range(max_steps):
        emit("thinking", None)
        msg = brain.chat(messages, tools=current_tool_specs()).message

        if not msg.tool_calls:
            final = (msg.content or "").strip()
            break

        # Record the assistant's tool-call turn so the model has the thread.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{
                "id": tc.id or f"call_{i}",
                "type": "function",
                "function": {"name": tc.function.name,
                             "arguments": tc.function.arguments_json},
            } for i, tc in enumerate(msg.tool_calls)],
        })

        # Run each requested tool and feed results back.
        for i, tc in enumerate(msg.tool_calls):
            name, args = tc.function.name, tc.function.arguments
            emit("tool", {"name": name, "args": args})
            if name not in SKILLS:
                result = f"(no such tool: {name})"
            else:
                result = run_skill(name, args)
            emit("tool_result", {"name": name, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id or f"call_{i}",
                "content": str(result),
            })
    else:
        # Ran out of steps — ask for a closing summary without tools.
        messages.append({"role": "user", "content":
                         "Wrap up: tell me briefly what you accomplished."})
        final = (brain.chat(messages).message.content or "").strip()

    final = final or "Done, master."
    emit("final", final)
    return final
