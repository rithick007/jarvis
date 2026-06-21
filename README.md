# J.A.R.V.I.S — the AI agent that writes its own skills

> A private, local, voice-driven AI assistant for macOS — with a film-grade HUD,
> real laptop control, a live world/tech intelligence feed, and a **Self-Growing
> Skill Forge** that writes, verifies, and permanently keeps its own new abilities.
>
> Most "Jarvis" projects are a voice wrapper around an LLM. This one *grows*.

---

## Why this is different

Every other Jarvis clone ships a fixed set of abilities. **This one writes new
ones on demand.** Ask it to "learn to archive last month's invoices" and it:

1. **generates** a complete new skill (code + tool spec) with the model,
2. **verifies** it — a deterministic AST safety scan (no shell, network, raw
   deletes, or dynamic exec) + a sandbox smoke test,
3. **asks you** to approve the generated code, then
4. **hot-loads + saves** it forever in `skills/learned/`.

That's [Voyager](https://voyager.minedojo.org/)'s lifelong-learning idea applied,
for the first time, to a personal macOS assistant. Every install becomes unique.

## Features

- **Voice-first HUD** — a purple "command center" with a reactive core, live
  system log, world dashboard, and AI/tech feed. Hands-free conversation.
- **Real laptop control** — open/quit/focus apps, volume, brightness, media,
  web search, lock/sleep, and the macOS **Accessibility tree** to read and
  click/type into any app. Everything behind a tiered safety layer.
- **Self-Growing Skill Forge** ★ — writes, verifies, and keeps its own skills.
- **World + Tech intelligence** — live global news, war/economy, Indian markets
  (RSS + Yahoo Finance), and a daily AI feed (Reddit, Hacker News, arXiv,
  YouTube), each summarized by the model.
- **Resilient free brain** — rotates across Groq → Cerebras → OpenRouter →
  Gemini (all free tiers), plus a browser Gemini fallback (Puter), so it keeps
  going when any one provider rate-limits.
- **Safety by construction** — scoped folders, preview + one-tap confirm,
  Trash-only deletes, undo, and a static scanner gating all forged code.

## Quick start

```bash
git clone <this-repo> jarvis && cd jarvis
cp .env.example .env          # add at least one free key (Groq is enough)
./run.sh                      # installs deps, builds the UI, opens localhost:8000
```

Get free keys (any one works; more = more uptime): **Groq** (console.groq.com/keys),
**Cerebras** (cloud.cerebras.ai), **OpenRouter** (openrouter.ai/keys).

Always-on: `./install_service.sh` runs it at login (macOS LaunchAgent).
For full app control, grant **Accessibility + Automation** in System Settings,
or run `./run.sh` from Terminal once so the permission prompts appear.

## Architecture

| Piece | File(s) |
|-------|---------|
| Resilient cloud brain (4 free providers, auto-rotate) | `brain.py` |
| Instant no-model command routing | `fast_path.py` |
| Agentic reason → act → observe loop | `agent_loop.py` |
| ★ Self-growing skill forge | `skill_forge.py`, `skills/learned/` |
| Real macOS control (apps, system, AX tree, scripts) | `mac_control/` |
| Safety (scope, preview/confirm, undo, AST scan) | `safety.py` |
| World + tech intelligence | `news_service.py`, `tech_service.py` |
| Web backend (WebSocket + REST) | `server.py` |
| Front-end design → wired to backend → served page | `web/design-src.html`, `build_design.py` |

## Notes

This is a **local** assistant: it controls *your* Mac and talks to *your*
localhost, so it runs on your machine, not as a public website. Voice uses the
browser's Web Speech API (best in Chrome) with a macOS Enhanced voice for a
natural sound. The model providers are free tiers with their own limits — the
fallback chain is what keeps it talking.
