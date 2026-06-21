"""
tech_service.py — Section 3's brain: catch up on AI/ML/tech for the day.

Aggregates what actually moves in this field, from the places it breaks first:
  · Reddit  — r/MachineLearning, r/LocalLLaMA, r/artificial, r/singularity (top/day)
  · Hacker News — front page + an AI-focused recent search (Algolia API)
  · arXiv   — newest cs.AI / cs.LG / cs.CL papers
  · YouTube — newest AI/agents videos (Data API if a key is set; otherwise RSS
              from a few staple AI channels)

Optionally asks the cloud brain for a one-paragraph "what happened in AI today"
digest. Cached in memory. Every source is independent and failure-tolerant.
Instagram is intentionally absent: no free/legal API, login-walled.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import httpx
from dotenv import load_dotenv

import config

load_dotenv(config.JARVIS_DIR / ".env")

UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
CACHE_TTL = 1800           # 30 minutes
_CACHE: dict = {"data": None, "ts": 0}

SUBREDDITS = ["MachineLearning", "LocalLLaMA", "artificial", "singularity"]
# Stable, real channel IDs — the no-key YouTube fallback.
YT_CHANNELS = {
    "Two Minute Papers": "UCbfYPyITQ-7l4upoX8nvctg",
    "Yannic Kilcher": "UCZHmQk67mSJgfCCTn7xBfew",
    "Lex Fridman": "UCSHZKyawb77ixDdsGog4iWA",
}


def _reddit(sub: str) -> list[dict]:
    # Reddit blocks the JSON API for datacenter IPs, but the RSS feed is open.
    try:
        url = f"https://www.reddit.com/r/{sub}/top.rss?t=day&limit=8"
        r = httpx.get(url, headers=UA, timeout=8.0, follow_redirects=True)
        parsed = feedparser.parse(r.content)
        out = []
        for e in parsed.entries[:8]:
            out.append({
                "title": (e.get("title") or "").strip(),
                "link": e.get("link") or "",
                "source": f"r/{sub}",
                "score": 0,    # not exposed in RSS; we sort by recency instead
                "ts": time.mktime(e.published_parsed) if e.get("published_parsed") else 0,
            })
        return out
    except Exception:
        return []


def _hackernews() -> list[dict]:
    out = []
    try:
        r = httpx.get("https://hn.algolia.com/api/v1/search",
                      params={"tags": "front_page", "hitsPerPage": 12},
                      headers=UA, timeout=8.0)
        for h in r.json().get("hits", []):
            out.append({
                "title": h.get("title", ""),
                "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "source": "Hacker News",
                "score": h.get("points", 0),
                "ts": h.get("created_at_i", 0),
            })
    except Exception:
        pass
    try:  # AI-specific recent stories
        r = httpx.get("https://hn.algolia.com/api/v1/search_by_date",
                      params={"tags": "story", "query": "AI OR LLM OR agent",
                              "hitsPerPage": 8, "numericFilters": "points>30"},
                      headers=UA, timeout=8.0)
        for h in r.json().get("hits", []):
            out.append({
                "title": h.get("title", ""),
                "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "source": "Hacker News", "score": h.get("points", 0),
                "ts": h.get("created_at_i", 0)})
    except Exception:
        pass
    seen, uniq = set(), []
    for it in sorted(out, key=lambda x: x["score"], reverse=True):
        k = it["title"].lower()[:60]
        if it["title"] and k not in seen:
            seen.add(k); uniq.append(it)
    return uniq[:12]


def _arxiv() -> list[dict]:
    try:
        url = ("https://export.arxiv.org/api/query?search_query="
               "cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL"
               "&sortBy=submittedDate&sortOrder=descending&max_results=10")
        r = httpx.get(url, headers=UA, timeout=10.0, follow_redirects=True)
        parsed = feedparser.parse(r.content)
        out = []
        for e in parsed.entries:
            out.append({
                "title": e.get("title", "").replace("\n", " ").strip(),
                "link": e.get("link", ""),
                "source": "arXiv",
                "authors": ", ".join(a.name for a in e.get("authors", [])[:3]),
                "summary": (e.get("summary", "")[:200].replace("\n", " ") + "…"),
                "ts": time.mktime(e.published_parsed) if e.get("published_parsed") else 0,
            })
        return out
    except Exception:
        return []


def _youtube() -> list[dict]:
    key = os.environ.get("YOUTUBE_API_KEY")
    if key:
        try:
            from datetime import timedelta
            after = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
            r = httpx.get("https://www.googleapis.com/youtube/v3/search",
                          params={"part": "snippet",
                                  "q": ('"LLM" OR "AI agents" OR "machine learning" OR '
                                        'OpenAI OR Anthropic OR "DeepMind" OR "neural network"'),
                                  "type": "video", "order": "relevance",
                                  "videoCategoryId": "28",     # Science & Technology
                                  "publishedAfter": after,
                                  "maxResults": 10, "relevanceLanguage": "en", "key": key},
                          timeout=8.0)
            out = []
            for it in r.json().get("items", []):
                vid = it.get("id", {}).get("videoId")
                sn = it.get("snippet", {})
                if vid:
                    out.append({"title": sn.get("title", ""),
                                "link": f"https://www.youtube.com/watch?v={vid}",
                                "source": sn.get("channelTitle", "YouTube"),
                                "ts": 0})
            if out:
                return out[:10]
        except Exception:
            pass
    # No-key fallback: RSS from staple AI channels.
    out = []
    for name, cid in YT_CHANNELS.items():
        try:
            r = httpx.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                          headers=UA, timeout=8.0)
            parsed = feedparser.parse(r.content)
            for e in parsed.entries[:3]:
                out.append({"title": e.get("title", ""), "link": e.get("link", ""),
                            "source": name,
                            "ts": time.mktime(e.published_parsed) if e.get("published_parsed") else 0})
        except Exception:
            continue
    return sorted(out, key=lambda x: x["ts"], reverse=True)[:10]


def _digest(reddit, hn, arxiv) -> str:
    try:
        import brain
        if not brain.available_providers():
            return ""
        heads = [x["title"] for x in (hn[:6] + reddit[:5] + arxiv[:4])]
        msg = [
            {"role": "system", "content":
             "You are JARVIS giving a quick 'what happened in AI today' digest. "
             "In 3-4 short spoken-style sentences, call out the most notable "
             "AI/ML/agents news, releases, or papers from these items. No lists."},
            {"role": "user", "content": "Items:\n" + "\n".join(heads)},
        ]
        return (brain.chat(msg).message.content or "").strip()
    except Exception:
        return ""


def get_techfeed(force: bool = False) -> dict:
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["ts"] < CACHE_TTL:
        return _CACHE["data"]

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_reddit = ex.submit(lambda: [x for s in SUBREDDITS for x in _reddit(s)])
        f_hn = ex.submit(_hackernews)
        f_arxiv = ex.submit(_arxiv)
        f_yt = ex.submit(_youtube)
        reddit = sorted(f_reddit.result(), key=lambda x: x["ts"], reverse=True)[:14]
        hn = f_hn.result()
        arxiv = f_arxiv.result()
        youtube = f_yt.result()

    data = {
        "updated": now,
        "digest": _digest(reddit, hn, arxiv),
        "reddit": reddit,
        "hackernews": hn,
        "arxiv": arxiv,
        "youtube": youtube,
    }
    _CACHE["data"], _CACHE["ts"] = data, now
    return data
