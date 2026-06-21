"""
server.py — Jarvis as a local web app.

This is the bridge between the browser HUD (web/) and everything the old
terminal Jarvis could do. It wraps the SAME brain, skills, safety layer,
monitor and Sentinel — nothing was rewritten, only re-fronted.

  WS  /ws        the conversation: send {type:"command", text}, get back a
                 stream of status / tool / tool_result / reply messages, plus
                 confirm_request round-trips for any risky action.
  GET /api/vitals      live machine vitals for the HUD
  GET /api/status      providers, model, scope, forged-skill count
  GET /api/skills      the skill library (built-in + forged-by-you)
  GET/POST /api/config, /api/scope    settings the UI can edit
  POST /api/undo, GET /api/log        the file-op safety log
  POST /api/sentinel  toggle the background watcher (alerts pushed over /ws)

The one subtlety is the CONFIRM BRIDGE: skills run on a worker thread and may
need a human yes/no. safety.py's handlers are pointed at functions that push a
confirm_request to the browser and block the worker thread until the browser
answers — the same pattern the Textual TUI already used, just over a socket.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import agent_loop
import brain
import config
import fast_path
import safety
from monitor import SystemMonitor
from skills import SKILLS, learned_names

app = FastAPI(title="JARVIS")
MONITOR = SystemMonitor()
CLIENTS: set["Conn"] = set()

# Only one command runs at a time (single local user) — keeps the global
# safety confirm handlers unambiguous.
_RUN_LOCK = threading.Lock()

WEB_DIST = config.JARVIS_DIR / "web" / "dist"


# ---------------------------------------------------------------------------
# Per-connection context + the confirm bridge
# ---------------------------------------------------------------------------

class Conn:
    def __init__(self, ws: WebSocket, loop: asyncio.AbstractEventLoop):
        self.ws = ws
        self.loop = loop
        self.history: list[dict] = []
        self.pending: dict[str, tuple[threading.Event, dict]] = {}
        self._preview: dict | None = None

    # -- sending (safe to call from any thread) ----------------------------
    def send(self, payload: dict) -> None:
        asyncio.run_coroutine_threadsafe(self.ws.send_json(payload), self.loop)

    def emit(self, kind: str, data) -> None:
        if kind == "thinking":
            self.send({"type": "status", "state": "thinking"})
        elif kind == "tool":
            self.send({"type": "tool", "name": data["name"], "args": data["args"]})
        elif kind == "tool_result":
            self.send({"type": "tool_result", "name": data["name"],
                       "result": data["result"]})

    # -- the confirm bridge (called from the worker thread) ----------------
    def stash_preview(self, summary: str, title: str) -> None:
        self._preview = {"summary": summary, "title": title}

    def confirm(self) -> bool:
        cid = uuid.uuid4().hex
        ev = threading.Event()
        box: dict = {}
        self.pending[cid] = (ev, box)
        prev = self._preview or {"summary": "Proceed?", "title": "Confirm"}
        self._preview = None
        self.send({"type": "confirm_request", "id": cid,
                   "summary": prev["summary"], "title": prev["title"]})
        ev.wait()                       # block the worker until the browser answers
        return bool(box.get("approved", False))

    def resolve_confirm(self, cid: str, approved: bool) -> None:
        item = self.pending.pop(cid, None)
        if item:
            ev, box = item
            box["approved"] = approved
            ev.set()


def _run_skill(name: str, args: dict) -> str:
    """Run one skill behind the safety layer; never raise."""
    try:
        return SKILLS[name]["run"](**args)
    except safety.ScopeError as e:
        return f"blocked — {e}"
    except TypeError:
        return "I had the right idea but the wrong details — try rephrasing, master."
    except Exception as e:
        return f"failed — {e}"


# Words that signal the user wants an ACTION on the Mac (→ use the tool loop).
# Anything without these is treated as conversation and answered with a cheap
# no-tools call, which keeps token usage (and Groq's rate limit) way down.
_ACTION_HINTS = (
    "open", "launch", "start", "run", "close", "quit", "exit", "switch",
    "play", "pause", "next", "previous", "skip", "volume", "mute", "louder",
    "quieter", "brightness", "dimmer", "search", "google", "look up", "browse",
    "website", "url", "file", "files", "folder", "downloads", "desktop",
    "document", "screenshot", "screen", "image", "photo", "organize", "sort",
    "clean", "tidy", "trash", "delete", "rename", "move", "remember", "note",
    "lock", "sleep", "battery", "disk", "storage", "status", "click", "type",
    "app", "spotify", "safari", "chrome", "finder", "notes", "calendar", "mail",
    "music", "learn to", "teach yourself", "forge", "skill", "what's running",
    "running", "cpu", "memory", "network", "uptime", "system",
)
JARVIS_CHAT = (
    "You are JARVIS — Tony Stark's witty, loyal British AI butler. Address the "
    "user as 'sir'. Reply in one or two short, natural spoken sentences. No "
    "markdown, no lists, no emoji."
)


def _needs_tools(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in _ACTION_HINTS)


def _chat_reply(text: str, history: list[dict]) -> str:
    """A cheap, no-tools conversational reply — small token footprint so long
    chats don't exhaust the rate limit."""
    msgs = [{"role": "system", "content": JARVIS_CHAT}, *history,
            {"role": "user", "content": text}]
    return (brain.chat(msgs).message.content or "").strip() or "At your service, sir."


def _process(conn: Conn, text: str) -> str:
    """Full pipeline for one command. Runs on a worker thread so the confirm
    bridge can block. Wires the safety handlers to THIS connection."""
    with _RUN_LOCK:
        safety.PREVIEW_HANDLER = lambda plan, title: conn.stash_preview(
            _plan_to_text(plan, title), title)
        safety.ACTION_PREVIEW_HANDLER = lambda summary, title: conn.stash_preview(
            summary, title)
        safety.CONFIRM_HANDLER = conn.confirm
        try:
            # Fast path: instant, no model.
            hit = fast_path.match(text)
            if hit is not None:
                name, args = hit
                conn.emit("tool", {"name": name, "args": args})
                result = _run_skill(name, args)
                conn.emit("tool_result", {"name": name, "result": result})
                return result
            # Only spend the big tool-laden agent loop on actual actions; plain
            # conversation gets a cheap no-tools reply. This keeps Groq's
            # tokens-per-minute budget from blowing up during a chat.
            if _needs_tools(text):
                return agent_loop.run(text, _run_skill, emit=conn.emit,
                                      history=conn.history[-6:])
            return _chat_reply(text, conn.history[-6:])
        finally:
            safety.PREVIEW_HANDLER = None
            safety.ACTION_PREVIEW_HANDLER = None
            safety.CONFIRM_HANDLER = None


def _plan_to_text(plan, title) -> str:
    lines = [f"Plan: {title} ({len(plan)} operation(s))"]
    for i, op in enumerate(plan, 1):
        verb, src, dst = op.describe()
        lines.append(f"  {i}. {verb}: {src}" + (f" → {dst}" if dst else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WebSocket: the conversation
# ---------------------------------------------------------------------------

async def _handle_command(conn: "Conn", text: str) -> None:
    ws = conn.ws
    await ws.send_json({"type": "user", "text": text})
    await ws.send_json({"type": "status", "state": "thinking"})
    reply = await asyncio.get_running_loop().run_in_executor(
        None, _process, conn, text)
    conn.history.append({"role": "user", "content": text})
    conn.history.append({"role": "assistant", "content": reply})
    del conn.history[:-12]                     # keep memory + tokens bounded
    await ws.send_json({"type": "reply", "text": reply})
    await ws.send_json({"type": "status", "state": "idle"})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    conn = Conn(ws, asyncio.get_running_loop())
    CLIENTS.add(conn)
    try:
        while True:
            data = await ws.receive_json()
            kind = data.get("type")

            if kind == "confirm_response":
                conn.resolve_confirm(data.get("id", ""), bool(data.get("approved")))
                continue

            if kind == "command":
                text = (data.get("text") or "").strip()
                if not text:
                    continue
                # Run the command as a background task so THIS loop stays free
                # to receive confirm_response messages while a skill is blocked
                # waiting on a confirm — otherwise the confirm bridge deadlocks.
                asyncio.create_task(_handle_command(conn, text))
    except WebSocketDisconnect:
        pass
    finally:
        CLIENTS.discard(conn)


# ---------------------------------------------------------------------------
# WebSocket: realtime voice (Gemini Live relay) — optional, opt-in
# ---------------------------------------------------------------------------

@app.websocket("/live")
async def live_endpoint(ws: WebSocket):
    await ws.accept()
    import live
    loop = asyncio.get_running_loop()
    in_q: asyncio.Queue = asyncio.Queue()
    pending: dict[str, tuple[threading.Event, dict]] = {}
    preview: dict = {}

    async def send_event(d):
        await ws.send_json(d)

    async def send_audio(b):
        await ws.send_bytes(b)

    async def recv_audio():
        return await in_q.get()

    def confirm() -> bool:
        cid = uuid.uuid4().hex
        ev = threading.Event(); box: dict = {}
        pending[cid] = (ev, box)
        p = preview.pop("v", {"summary": "Proceed?", "title": "Confirm"})
        asyncio.run_coroutine_threadsafe(ws.send_json({
            "type": "confirm_request", "id": cid,
            "summary": p["summary"], "title": p["title"]}), loop)
        ev.wait()
        return bool(box.get("approved", False))

    async def run_skill(name, args):
        # offload to a thread so a blocking confirm doesn't stall the loop
        return await loop.run_in_executor(None, _run_skill, name, args)

    # wire the safety layer to this live session for its lifetime
    safety.PREVIEW_HANDLER = lambda plan, title: preview.__setitem__(
        "v", {"summary": _plan_to_text(plan, title), "title": title})
    safety.ACTION_PREVIEW_HANDLER = lambda s, t: preview.__setitem__(
        "v", {"summary": s, "title": t})
    safety.CONFIRM_HANDLER = confirm

    async def receiver():
        try:
            while True:
                msg = await ws.receive()
                if msg.get("bytes") is not None:
                    await in_q.put(msg["bytes"])
                elif msg.get("text") is not None:
                    data = __import__("json").loads(msg["text"])
                    if data.get("type") == "confirm_response":
                        item = pending.pop(data.get("id", ""), None)
                        if item:
                            item[1]["approved"] = bool(data.get("approved"))
                            item[0].set()
                    elif data.get("type") == "end":
                        await in_q.put(None)
                        break
        except WebSocketDisconnect:
            await in_q.put(None)

    try:
        await asyncio.gather(
            receiver(),
            live.relay(recv_audio, send_audio, send_event, run_skill))
    except Exception as e:
        try:
            await ws.send_json({"type": "live_error", "message": str(e)})
        except Exception:
            pass
    finally:
        safety.PREVIEW_HANDLER = None
        safety.ACTION_PREVIEW_HANDLER = None
        safety.CONFIRM_HANDLER = None


# ---------------------------------------------------------------------------
# REST: vitals, status, settings, safety log, sentinel
# ---------------------------------------------------------------------------

@app.get("/api/vitals")
def api_vitals():
    return JSONResponse(MONITOR.sample())


@app.get("/api/status")
def api_status():
    cfg = config.load()
    working = brain.working_providers()
    return {
        "provider": cfg.get("provider"),
        "providers_available": brain.available_providers(),
        "working_providers": working,
        "realtime": "gemini" in working,        # Gemini Live needs a live Gemini key
        "model": brain.PROVIDERS.get(cfg.get("provider", "groq"), (None, None, "?"))[2],
        "scope": cfg.get("scoped_folders", []),
        "learned_skills": learned_names(),
        "skill_count": len(SKILLS),
    }


@app.get("/api/skills")
def api_skills():
    return [{"name": n, "description": s["spec"]["function"]["description"],
             "learned": bool(s.get("learned"))}
            for n, s in sorted(SKILLS.items())]


@app.get("/api/config")
def api_get_config():
    return config.load()


@app.post("/api/config")
async def api_set_config(req: dict):
    cfg = config.load()
    for key in ("provider", "groq_model", "gemini_model"):
        if key in req:
            cfg[key] = req[key]
    config.save(cfg)
    return cfg


@app.post("/api/scope")
async def api_scope(req: dict):
    cfg = config.load()
    action, path = req.get("action"), req.get("path", "")
    p = str(Path(path).expanduser().resolve())
    if action == "add" and Path(p).is_dir() and p not in cfg["scoped_folders"]:
        cfg["scoped_folders"].append(p)
    elif action == "remove" and p in cfg["scoped_folders"]:
        cfg["scoped_folders"].remove(p)
    config.save(cfg)
    return {"scope": cfg["scoped_folders"]}


@app.get("/api/news")
def api_news(force: bool = False):
    import news_service
    return JSONResponse(news_service.get_news(force=force))


@app.get("/api/techfeed")
def api_techfeed(force: bool = False):
    import tech_service
    return JSONResponse(tech_service.get_techfeed(force=force))


@app.post("/api/undo")
def api_undo():
    return {"message": safety.undo_last()}


@app.get("/api/log")
def api_log():
    return [e for e in safety._read_log() if "kind" in e][-20:]


_SENTINEL = {"obj": None}


@app.post("/api/sentinel")
async def api_sentinel(req: dict):
    from watcher import Sentinel
    on = bool(req.get("on"))
    if on and _SENTINEL["obj"] is None:
        def alert(message: str):
            for c in list(CLIENTS):
                c.send({"type": "sentinel", "message": message})
        _SENTINEL["obj"] = Sentinel(on_alert=alert)
        _SENTINEL["obj"].start()
    elif not on and _SENTINEL["obj"] is not None:
        _SENTINEL["obj"].stop()
        _SENTINEL["obj"] = None
    return {"sentinel": _SENTINEL["obj"] is not None}


# ---------------------------------------------------------------------------
# Static frontend (built React app) — keep this LAST so /api and /ws win.
# ---------------------------------------------------------------------------

if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
else:
    @app.get("/", response_class=HTMLResponse)
    def _placeholder():
        return ("<h1>JARVIS backend is running.</h1>"
                "<p>The web UI isn't built yet. Run "
                "<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>, "
                "or use the Vite dev server during development.</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
