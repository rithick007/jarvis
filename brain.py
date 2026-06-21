"""
brain.py — Jarvis's brain, now in the cloud (with a slot to come back home).

The old Jarvis thought with a local Ollama model. This one thinks with a
fast, free *hosted* model so replies feel instant and the model is actually
good — while the M1 stays cool because the heavy lifting happens elsewhere.

Two providers, one shape:

  GROQ    (primary)   — Llama 3.3 70B, astonishingly fast inference.
  GEMINI  (fallback)  — Gemini Flash, kicks in if Groq is down / rate-limited
                        / has no key.

The trick that keeps this file small: BOTH providers speak the OpenAI chat
API. Groq is OpenAI-compatible; Gemini exposes an OpenAI-compatible endpoint
too. So we use one `openai` client, just pointed at different base URLs, and
the exact same messages + tool-spec format flows to either one.

`chat()` returns an object shaped EXACTLY like Ollama's response
(`.message.content`, `.message.tool_calls[i].function.name/.arguments`), so
router.py and agents.py don't have to change how they read replies — only
where the thinking happens.

OFFLINE later: drop an OllamaProvider / MLXProvider into PROVIDERS and flip
`provider` in jarvis_config.json. Nothing else changes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

import config

load_dotenv(config.JARVIS_DIR / ".env")


# ---------------------------------------------------------------------------
# Ollama-shaped response objects — so the rest of Jarvis reads replies the
# same way it always has.
# ---------------------------------------------------------------------------

@dataclass
class _Func:
    name: str
    arguments: dict                 # parsed, for our skill runners
    arguments_json: str = "{}"      # raw, for replaying the turn to the API


@dataclass
class _ToolCall:
    function: _Func
    id: str = ""                    # needed to pair tool results in a tool-loop


@dataclass
class _Message:
    content: str | None = None
    tool_calls: list[_ToolCall] = field(default_factory=list)


@dataclass
class _Response:
    message: _Message


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

# name -> (env var for the key, OpenAI-compatible base URL, default model)
# All free tiers. The fallback chain rotates through them when one rate-limits,
# so you get far more usable time than any single provider allows.
PROVIDERS = {
    "groq": (
        "GROQ_API_KEY",
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
    ),
    "cerebras": (
        "CEREBRAS_API_KEY",
        "https://api.cerebras.ai/v1",
        "llama-3.3-70b",
    ),
    "openrouter": (
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "meta-llama/llama-3.3-70b-instruct:free",
    ),
    "gemini": (
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.0-flash",
    ),
}

# Try the configured provider first, then the others as fallbacks. When one
# returns a rate-limit (429), chat() moves to the next automatically.
FALLBACK_ORDER = ["groq", "cerebras", "openrouter", "gemini"]


class BrainError(RuntimeError):
    """Raised only when every provider failed — so callers can degrade
    gracefully instead of crashing the assistant."""


def _client(base_url: str, api_key: str):
    # Imported lazily so the CLI/TUI still start even if `openai` isn't
    # installed yet (e.g. before `pip install -r requirements.txt`).
    from openai import OpenAI
    return OpenAI(base_url=base_url, api_key=api_key)


def _model_for(provider: str, cfg: dict) -> str:
    """Per-provider model override from config, else the provider default."""
    override = cfg.get(f"{provider}_model")
    return override or PROVIDERS[provider][2]


def _call_provider(provider: str, messages, tools, cfg) -> _Response:
    env_var, base_url, _default = PROVIDERS[provider]
    api_key = os.environ.get(env_var)
    if not api_key:
        raise BrainError(f"{provider}: no {env_var} set")

    kwargs = dict(model=_model_for(provider, cfg), messages=messages)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    resp = _client(base_url, api_key).chat.completions.create(**kwargs)
    choice = resp.choices[0].message

    calls: list[_ToolCall] = []
    for tc in (choice.tool_calls or []):
        raw = tc.function.arguments or "{}"
        try:
            args = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            args = {}
        calls.append(_ToolCall(
            function=_Func(tc.function.name, args, raw),
            id=getattr(tc, "id", "") or ""))

    return _Response(_Message(content=choice.content, tool_calls=calls))


def _provider_chain(cfg: dict) -> list[str]:
    primary = cfg.get("provider", "groq")
    chain = [primary] + [p for p in FALLBACK_ORDER if p != primary]
    # de-dup while preserving order, keep only known providers
    seen, ordered = set(), []
    for p in chain:
        if p in PROVIDERS and p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def available_providers() -> list[str]:
    """Which providers actually have a key set — handy for the UI/status."""
    return [p for p, (env, _u, _m) in PROVIDERS.items() if os.environ.get(env)]


_WORKING: list[str] | None = None


def working_providers() -> list[str]:
    """Which providers actually RESPOND (key present AND has quota). Probed once
    per process and cached — a key with zero quota (429) is reported as down,
    so the UI can hide features that depend on it (e.g. realtime voice)."""
    global _WORKING
    if _WORKING is not None:
        return _WORKING
    out = []
    for p in available_providers():
        try:
            _call_provider(p, [{"role": "user", "content": "ping"}], None, config.load())
            out.append(p)
        except Exception:
            pass
    _WORKING = out
    return out


def chat(messages, tools=None, think=False) -> _Response:
    """Every model call in Jarvis funnels through here. Tries the configured
    provider, then falls back down the chain. `think` is accepted for
    drop-in compatibility with the old Ollama path and ignored (the cloud
    models don't need the reasoning toggle)."""
    cfg = config.load()
    errors = []
    for provider in _provider_chain(cfg):
        try:
            return _call_provider(provider, messages, tools, cfg)
        except Exception as e:
            msg = str(e)
            # Function-calling models occasionally emit a malformed tool call and
            # the API 400s ("Failed to call a function"). That shouldn't kill the
            # reply — retry the SAME provider without tools for a plain answer.
            if tools and "400" in msg and ("function" in msg.lower() or "tool" in msg.lower()):
                try:
                    return _call_provider(provider, messages, None, cfg)
                except Exception as e2:
                    errors.append(f"{provider} (no-tools retry): {e2}")
                    continue
            errors.append(f"{provider}: {e}")        # try the next provider

    # Everyone failed — surface a calm, spoken-word-friendly message rather
    # than throwing, so voice mode doesn't go silent.
    detail = " | ".join(errors) if errors else "no providers configured"
    return _Response(_Message(
        content=("My uplink is down, master — I couldn't reach a model. "
                 "Check the API keys in .env. "
                 f"({detail})"),
        tool_calls=[]))
