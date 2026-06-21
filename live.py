"""
live.py — realtime, movie-grade voice via Gemini Live (audio-to-audio).

Web Speech (in the browser) already gives Jarvis working voice with zero
setup. THIS is the upgrade: Gemini's Live API processes your speech directly
as audio and answers directly as audio over one WebSocket — no
speech-to-text-to-LLM-to-text-to-speech chain. That removes ~100-200 ms per
turn and keeps vocal nuance, so it sounds like the films instead of a robot.
It's also multimodal (it can take live screen frames) and supports tool
calls, so spoken commands still drive the same skills + safety layer.

This module is the SERVER-SIDE relay: the browser streams mic PCM up to our
backend, we forward it to Gemini Live, and stream Gemini's audio back down —
running any tool calls Gemini makes through run_skill() on the way.

Audio contract (kept simple and standard):
  · input : 16 kHz, 16-bit, mono PCM   (what the browser worklet sends)
  · output: 24 kHz, 16-bit, mono PCM   (what Gemini returns; browser plays it)

Requires GEMINI_API_KEY and the `google-genai` package. If either is missing,
relay() reports that cleanly and the client simply stays on Web Speech.
"""

from __future__ import annotations

import os

import config
from skills import current_tool_specs

LIVE_MODEL = "gemini-2.0-flash-live-001"

SYSTEM_INSTRUCTION = (
    "You are JARVIS, a private AI assistant operating this Mac by voice. "
    "Speak concisely, precisely, loyally, with quiet wit. Use the provided "
    "tools to actually act on the Mac; if no tool fits a repeatable request, "
    "use forge_skill. Keep spoken replies to a sentence or two."
)


def available() -> bool:
    if not os.environ.get("GEMINI_API_KEY"):
        return False
    try:
        import google.genai  # noqa: F401
        return True
    except ImportError:
        return False


def _gemini_tools():
    """Translate our OpenAI-style tool specs into Gemini function declarations."""
    from google.genai import types
    decls = []
    for spec in current_tool_specs():
        fn = spec["function"]
        decls.append(types.FunctionDeclaration(
            name=fn["name"],
            description=fn.get("description", ""),
            parameters=fn.get("parameters", {"type": "object", "properties": {}}),
        ))
    return [types.Tool(function_declarations=decls)]


async def relay(recv_audio, send_audio, send_event, run_skill):
    """Bridge one browser voice session to Gemini Live.

    recv_audio()  -> awaitable yielding the next chunk of mic PCM (bytes), or
                     None when the client hangs up.
    send_audio(b) -> coroutine: push a chunk of Gemini's reply PCM to the client.
    send_event(d) -> coroutine: push a JSON status/tool/transcript event.
    run_skill(name, args) -> awaitable[str]: execute a tool through the safety
        layer (awaitable so it can offload to a thread for blocking confirms).
    """
    if not available():
        await send_event({"type": "live_error",
                           "message": "Gemini Live needs GEMINI_API_KEY and "
                                      "google-genai. Staying on browser voice."})
        return

    import asyncio
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=SYSTEM_INSTRUCTION,
        tools=_gemini_tools(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    async with client.aio.live.connect(model=LIVE_MODEL, config=cfg) as session:
        await send_event({"type": "live_ready", "model": LIVE_MODEL})

        async def pump_mic():
            while True:
                chunk = await recv_audio()
                if chunk is None:
                    break
                await session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))

        async def pump_gemini():
            async for response in session.receive():
                # streamed audio out
                if getattr(response, "data", None):
                    await send_audio(response.data)
                sc = getattr(response, "server_content", None)
                if sc:
                    it = getattr(sc, "input_transcription", None)
                    if it and getattr(it, "text", None):
                        await send_event({"type": "live_transcript",
                                          "role": "you", "text": it.text})
                    ot = getattr(sc, "output_transcription", None)
                    if ot and getattr(ot, "text", None):
                        await send_event({"type": "live_transcript",
                                          "role": "jarvis", "text": ot.text})
                # tool calls → run through our skills, return results
                tc = getattr(response, "tool_call", None)
                if tc and getattr(tc, "function_calls", None):
                    responses = []
                    for fc in tc.function_calls:
                        await send_event({"type": "tool", "name": fc.name,
                                          "args": dict(fc.args or {})})
                        result = await run_skill(fc.name, dict(fc.args or {}))
                        await send_event({"type": "tool_result",
                                          "name": fc.name, "result": result})
                        responses.append(types.FunctionResponse(
                            id=getattr(fc, "id", None), name=fc.name,
                            response={"result": result}))
                    await session.send_tool_response(function_responses=responses)

        await asyncio.gather(pump_mic(), pump_gemini())
