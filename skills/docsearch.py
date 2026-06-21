"""
skills/docsearch.py — Skill 2: Local Document Search. Real RAG, fully on-device.

Two halves:

  index_documents(folder)  — read every .txt/.md/.pdf in the folder, split
      into overlapping chunks, turn each chunk into a vector with the
      nomic-embed-text model, store everything in SQLite. Re-running only
      touches files whose modification time changed.

  search_documents(query)  — embed the query the same way, cosine-compare
      against every stored chunk (numpy, instant at this scale), show the
      top matching files + snippets, then have the chat model write a
      short answer USING ONLY those snippets. Local retrieval-augmented
      generation — nothing leaves the Mac.
"""

import sqlite3
from pathlib import Path

import numpy as np
import ollama

import config
import safety

CHUNK_SIZE = 900       # characters per chunk — small enough to embed well
CHUNK_OVERLAP = 150    # neighbours share text so ideas aren't cut in half
TOP_K = 3
INDEXABLE = {".txt", ".md", ".pdf"}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(config.INDEX_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS files
                   (path TEXT PRIMARY KEY, mtime REAL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS chunks
                   (id INTEGER PRIMARY KEY, path TEXT, idx INTEGER,
                    text TEXT, vec BLOB)""")
    return con


# ---------------------------------------------------------------------------
# Reading and chunking
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)
    return path.read_text(errors="ignore")


def _chunk(text: str) -> list[str]:
    text = " ".join(text.split())          # collapse whitespace
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + CHUNK_SIZE])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def _embed(texts: list[str]) -> np.ndarray:
    """Texts → unit-length float32 vectors (unit length ⇒ dot product = cosine)."""
    cfg = config.load()
    vecs = []
    for i in range(0, len(texts), 16):     # batch to keep requests small
        resp = ollama.embed(model=cfg["embed_model"], input=texts[i:i + 16])
        vecs.extend(resp.embeddings)
    mat = np.array(vecs, dtype=np.float32)
    return mat / np.linalg.norm(mat, axis=1, keepdims=True)


# ---------------------------------------------------------------------------
# The two skill functions
# ---------------------------------------------------------------------------

def index_documents(folder: str) -> str:
    cfg = config.load()
    target = safety.resolve_folder(folder, cfg)           # scope applies to reading too

    files = sorted(p for p in target.rglob("*")
                   if p.is_file() and p.suffix.lower() in INDEXABLE
                   and not p.name.startswith("."))
    if not files:
        return f"No .txt/.md/.pdf files found in {target}."

    con = _db()
    indexed = skipped = failed = 0
    for f in files:
        mtime = f.stat().st_mtime
        row = con.execute("SELECT mtime FROM files WHERE path=?", (str(f),)).fetchone()
        if row and row[0] == mtime:
            skipped += 1
            continue
        try:
            chunks = _chunk(_read_text(f))
            if not chunks:
                continue
            vecs = _embed(chunks)
            con.execute("DELETE FROM chunks WHERE path=?", (str(f),))
            con.executemany(
                "INSERT INTO chunks (path, idx, text, vec) VALUES (?,?,?,?)",
                [(str(f), i, c, v.tobytes()) for i, (c, v) in enumerate(zip(chunks, vecs))])
            con.execute("INSERT OR REPLACE INTO files VALUES (?,?)", (str(f), mtime))
            con.commit()
            indexed += 1
        except Exception:
            failed += 1
    total = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    con.close()

    msg = f"Indexed {indexed} file(s), skipped {skipped} unchanged. {total} chunks searchable."
    if failed:
        msg += f" ({failed} file(s) could not be read.)"
    return msg


def search_documents(query: str) -> str:
    con = _db()
    rows = con.execute("SELECT path, text, vec FROM chunks").fetchall()
    con.close()
    if not rows:
        return ("The index is empty. Index a folder first — e.g. say "
                "'index my Documents folder' or use /index <folder>.")

    qvec = _embed([query])[0]
    mat = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float32)
    mat = mat.reshape(len(rows), -1)
    scores = mat @ qvec                                   # cosine similarity

    # Best chunk per file, then top files overall.
    best: dict[str, tuple[float, str]] = {}
    for (path, text, _), score in zip(rows, scores):
        if path not in best or score > best[path][0]:
            best[path] = (float(score), text)
    top = sorted(best.items(), key=lambda kv: -kv[1][0])[:TOP_K]

    home = str(Path.home())
    lines = ["Top matches:"]
    excerpts = []
    for path, (score, text) in top:
        snippet = text[:220].strip()
        lines.append(f"\n  {path.replace(home, '~')}   (match {score:.0%})")
        lines.append(f"  “…{snippet}…”")
        excerpts.append(f"[{Path(path).name}]\n{text[:800]}")

    # The RAG step: answer from the excerpts only — no making things up.
    import router
    answer = router.chat([
        {"role": "system", "content":
            "Answer the user's question in 1-3 sentences using ONLY the "
            "excerpts provided. Mention which file the answer came from. "
            "If the excerpts don't contain the answer, say so."},
        {"role": "user", "content":
            f"Question: {query}\n\nExcerpts:\n\n" + "\n\n".join(excerpts)},
    ]).message.content.strip()

    return "\n".join(lines) + f"\n\nAnswer: {answer}"
