"""
skills/vision.py — Jarvis's eyes: MiniCPM-V 4.6 (1.3B multimodal).

The brain (qwen3.5) decides WHEN to look; this model does the looking.
analyze_image() finds the image (newest screenshot by default, or by
name), sends it to the vision model, and returns what it sees. Strictly
read-only and scope-checked like everything else.

RAM note: the vision model loads alongside/instead of the brain for the
duration of the call (keep_alive is short so it frees memory quickly).
First call after a while has a few seconds of load time.
"""

from pathlib import Path

import ollama

import config
import safety

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".webp", ".gif", ".tiff"}


def _candidate_images(cfg: dict) -> list[Path]:
    """Every image in the scoped folders (top level + Screenshots/)."""
    images: list[Path] = []
    for root in safety.scoped_roots(cfg):
        if not root.exists():
            continue
        for folder in (root, root / "Screenshots"):
            if folder.exists():
                images += [p for p in folder.iterdir()
                           if p.is_file() and p.suffix.lower() in IMAGE_EXTS
                           and not p.name.startswith(".")]
    return images


def _find_image(target: str, cfg: dict) -> Path | None:
    images = _candidate_images(cfg)
    if not images:
        return None
    target = (target or "").strip().lower()
    if target in ("", "latest", "newest", "last", "recent",
                  "latest screenshot", "screenshot"):
        return max(images, key=lambda p: p.stat().st_mtime)
    # Otherwise: best filename match.
    matches = [p for p in images if target in p.name.lower()]
    if matches:
        return max(matches, key=lambda p: p.stat().st_mtime)
    direct = Path(target).expanduser()
    if direct.exists() and direct.suffix.lower() in IMAGE_EXTS:
        return direct
    return None


def analyze_image(image: str = "latest", question: str = "") -> str:
    cfg = config.load()
    path = _find_image(image, cfg)
    if path is None:
        return (f"Couldn't find an image matching '{image}' in the allowed "
                f"folders.")
    safety.assert_in_scope(path, cfg)

    prompt = question.strip() or ("Describe this image briefly and "
                                  "mention any readable text.")
    reply = ollama.chat(
        model=cfg.get("vision_model", "minicpm-v4.6"),
        messages=[{"role": "user", "content": prompt,
                   "images": [str(path)]}],
        keep_alive="2m",          # release RAM back to the brain quickly
    ).message.content.strip()

    home = str(Path.home())
    return f"{reply}\n\n[looked at: {str(path).replace(home, '~')}]"
