"""
router.py — the ONLY file that talks to the model for routing.

Takes the user's command, hands the model the skill specs, returns a
clean decision. Three upgrades over the v0.2 router:

  • CONVERSATION MEMORY — a rolling history so follow-ups like "now do
    the same for Desktop" make sense.
  • HALLUCINATION GUARD — small models sometimes reply with fake JSON
    text instead of a real tool call. We detect that and re-ask the
    model in plain-chat mode, so you always get a sane answer.
  • RUNTIME MODEL SWAP — reads the model name from config on every call,
    so /model qwen2.5:7b takes effect instantly.
"""

import json
import time

import brain
import config
import fast_path
import memory
from skills import SKILLS, current_tool_specs

# Every routing decision is logged here as a future fine-tuning example.
# Once a few hundred accumulate, finetune.py can train a LoRA on YOUR
# phrasing (see that file for the why and how).
TRAINING_LOG = config.JARVIS_DIR / "training_data.jsonl"


def _log_decision(command: str, skill: str | None, args: dict | None) -> None:
    try:
        with TRAINING_LOG.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "command": command,
                                "skill": skill, "args": args}) + "\n")
    except OSError:
        pass


def _memory_context(command: str) -> list[dict]:
    """Inject relevant long-term memories so 'email my landlord' knows
    who that is. Empty list when nothing relevant is stored."""
    try:
        facts = memory.recall(command)
    except Exception:
        return []
    if not facts:
        return []
    return [{"role": "system",
             "content": "Known facts about the user: " + " ".join(facts)}]

# Rolling memory of the conversation (trimmed so the 3b model stays sharp).
_HISTORY: list[dict] = []
_MAX_HISTORY = 10

SYSTEM_PROMPT = (
    "You are Jarvis, a local assistant controlling this Mac strictly through "
    "tools.\n"
    "Rules:\n"
    "- If the request matches a tool, call it. At most ONE tool per turn.\n"
    "- Organizing/renaming/sorting/cleaning files -> organize_files.\n"
    "- 'index/learn/scan a folder' -> index_documents.\n"
    "- Finding files by topic, or questions about the user's documents -> search_documents.\n"
    "- Writing/rewriting/drafting text FOR THE USER to use somewhere -> "
    "rewrite_text. Questions ABOUT you or addressed TO you are NOT tool "
    "calls — answer those in plain prose yourself.\n"
    "- Battery/disk/uptime questions -> mac_status.\n"
    "- Anything else: answer briefly in plain prose, in the JARVIS persona — "
    "precise, quietly witty, spoken-word friendly. NEVER write JSON or "
    "pretend to call a tool in a text reply."
)

def chat(messages, tools=None, think=False):
    """Every model call in Jarvis goes through here. It now delegates to
    brain.py, which picks the cloud provider (Groq → Gemini fallback) and
    returns an Ollama-shaped response, so nothing downstream had to change.
    `think` is kept for compatibility (the cloud models ignore it)."""
    return brain.chat(messages, tools=tools, think=think)


def _remember(role: str, content: str) -> None:
    _HISTORY.append({"role": role, "content": content})
    del _HISTORY[:-_MAX_HISTORY]


def record_result(skill: str, result: str) -> None:
    """Called by main.py after a skill runs, so follow-ups have context."""
    _remember("assistant", f"(ran {skill}; result: {result[:300]})")


def _looks_like_fake_json(text: str) -> bool:
    text = text.strip()
    if not text.startswith("{"):
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return True            # starts with '{' but isn't even valid — garbage
    return isinstance(data, dict) and ("name" in data or "skill" in data)


# Small talk should never reach the tool-picker — a 3b model will happily
# route "who are you?" to mac_status. Deterministic guard beats prompting.
_SMALLTALK = ("who are you", "what are you", "what can you do", "hello",
              "hi jarvis", "hey jarvis", "thank", "good morning",
              "good night", "how are you", "are you there")


def _is_smalltalk(command: str) -> bool:
    c = command.lower().strip(" ?!.")
    return any(p in c for p in _SMALLTALK) and len(c) < 40


def route(user_command: str) -> tuple[str | None, dict | None, str | None]:
    """Returns (skill, args, None) for a tool call,
    or (None, None, reply_text) for a plain answer."""
    cfg = config.load()

    # FAST PATH: common commands ("open Spotify", "volume up", "search X")
    # match deterministically here and skip the network entirely — the heart
    # of feeling instant. Returns (skill, args) or None.
    hit = fast_path.match(user_command)
    if hit is not None:
        skill, args = hit
        _remember("user", user_command)
        _remember("assistant", f"(fast-path → {skill} {json.dumps(args)})")
        _log_decision(user_command, skill, args)
        return skill, args, None

    if _is_smalltalk(user_command):
        response = chat([
            {"role": "system", "content":
             "You are JARVIS, a private AI butler running entirely on this "
             "Mac. Precise, loyal, quietly witty. You can organize files, "
             "search documents, draft text, look at images, remember facts, "
             "and watch over the system. "
             "Reply in one or two short spoken-word friendly sentences."},
            *_memory_context(user_command),
            *_HISTORY,
            {"role": "user", "content": user_command},
        ])
        text = (response.message.content or "").strip()
        _remember("user", user_command)
        _remember("assistant", text)
        return None, None, text
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                *_memory_context(user_command),
                *_HISTORY,
                {"role": "user", "content": user_command}]

    response = chat(messages, tools=current_tool_specs())
    msg = response.message

    if msg.tool_calls:
        call = msg.tool_calls[0]
        name, args = call.function.name, dict(call.function.arguments)
        if name in SKILLS:
            _remember("user", user_command)
            _remember("assistant", f"(calling {name} {json.dumps(args)})")
            _log_decision(user_command, name, args)
            return name, args, None
        # Hallucinated tool name — fall through to plain chat below.

    text = (msg.content or "").strip()
    if not text or _looks_like_fake_json(text):
        # Re-ask without tools: forces a plain-English answer.
        response = chat([
            {"role": "system",
             "content": "You are Jarvis, a concise, friendly local assistant. Answer in plain prose."},
            *_HISTORY,
            {"role": "user", "content": user_command},
        ])
        text = (response.message.content or "").strip()

    _remember("user", user_command)
    _remember("assistant", text)
    _log_decision(user_command, None, None)
    return None, None, text
