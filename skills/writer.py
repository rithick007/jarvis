"""
skills/writer.py — Skill 3: Rewrite / Draft.

Takes an instruction ("make this professional", "draft a polite decline")
and optional source text, asks the local model to write, then:

  • copies the result to your clipboard (macOS pbcopy — built in)
  • saves it to drafts/draft_<timestamp>.txt as a permanent copy

It NEVER sends anything anywhere. You paste it where you want it.
"""

import subprocess
from datetime import datetime

import config

SYSTEM = (
    "You are a precise writing assistant. Produce ONLY the requested text — "
    "no preamble, no explanations, no quotation marks around the output. "
    "Match the tone the user asked for. Be natural, not stiff."
)


def rewrite_text(instruction: str, text: str = "") -> str:
    cfg = config.load()

    user_msg = f"Task: {instruction}"
    if text.strip():
        user_msg += f"\n\nOriginal text:\n{text}"

    import router            # lazy: skills/ and router import each other
    result = router.chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_msg},
    ]).message.content.strip()

    # Clipboard — pbcopy ships with macOS, no extra packages needed.
    subprocess.run(["pbcopy"], input=result.encode())

    # Draft file — a paper trail of everything Jarvis ever wrote for you.
    config.DRAFTS_DIR.mkdir(exist_ok=True)
    draft = config.DRAFTS_DIR / f"draft_{datetime.now():%Y%m%d_%H%M%S}.txt"
    draft.write_text(result + "\n")

    return (f"{result}\n\n"
            f"— copied to clipboard ✓  saved to {draft.relative_to(config.JARVIS_DIR)} ✓")
