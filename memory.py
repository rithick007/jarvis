"""
memory.py — Jarvis's long-term memory.

Two halves:

  remember(fact)      — store a fact ("the landlord's name is Raj") as
                        text + embedding in SQLite. Triggered by the
                        remember_fact skill ("jarvis, remember that…").

  recall(query, k)    — embed the query, cosine-match against every
                        stored memory, return the relevant ones.

The magic is in router.py: before every routing/chat decision the user's
command is run through recall(), and matching facts are injected into
the system prompt. So "email my landlord" just *knows* who that is.
Memories live in jarvis_index.db next to the document index — same
embedding model, same math, nothing leaves the Mac.
"""

import sqlite3
import time

import numpy as np
import ollama

import config

MIN_SCORE = 0.55      # below this similarity a memory isn't relevant


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(config.INDEX_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS memories
                   (id INTEGER PRIMARY KEY, ts REAL, text TEXT, vec BLOB)""")
    return con


def _embed(text: str) -> np.ndarray:
    cfg = config.load()
    vec = np.array(ollama.embed(model=cfg["embed_model"],
                                input=[text]).embeddings[0], dtype=np.float32)
    return vec / np.linalg.norm(vec)


def remember(fact: str) -> str:
    fact = fact.strip().rstrip(".") + "."
    con = _db()
    con.execute("INSERT INTO memories (ts, text, vec) VALUES (?,?,?)",
                (time.time(), fact, _embed(fact).tobytes()))
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    con.close()
    return f"Noted, master: {fact} ({total} memories kept.)"


def recall(query: str, k: int = 3) -> list[str]:
    """The memories most relevant to this command, best first."""
    con = _db()
    rows = con.execute("SELECT text, vec FROM memories").fetchall()
    con.close()
    if not rows:
        return []
    qvec = _embed(query)
    scored = [(float(np.frombuffer(vec, dtype=np.float32) @ qvec), text)
              for text, vec in rows]
    scored.sort(reverse=True)
    return [text for score, text in scored[:k] if score >= MIN_SCORE]


def forget_all() -> str:
    con = _db()
    n = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    con.execute("DELETE FROM memories")
    con.commit()
    con.close()
    return f"Wiped {n} memories."
