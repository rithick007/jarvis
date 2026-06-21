"""
news_service.py — Section 2's brain: what's happening in the world, right now.

Pulls from free RSS feeds (BBC, Al Jazeera, Guardian + Times of India, Economic
Times, The Hindu for India), live market quotes from Yahoo Finance, and —
optionally — NewsAPI if a key is present. Groups everything into world / war /
economy / India, and asks the cloud brain for a short spoken-style daily
briefing. Results are cached in memory so the dashboard loads instantly and we
don't hammer the sources.

Everything is defensive: any single source failing just drops out; the rest
still render. No key required for the core experience.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import feedparser
import httpx
from dotenv import load_dotenv

import config

load_dotenv(config.JARVIS_DIR / ".env")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Apple Silicon) JarvisNews/1.0"}
CACHE_TTL = 900            # 15 minutes
_CACHE: dict = {"data": None, "ts": 0}

FEEDS = {
    "world": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.theguardian.com/world/rss",
    ],
    "economy": [
        "http://feeds.bbci.co.uk/news/business/rss.xml",
        "https://www.theguardian.com/business/rss",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    ],
    "india": [
        "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
        "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
        "https://www.thehindu.com/news/national/feeder/default.rss",
    ],
}

WAR_KEYWORDS = ("war", "strike", "missile", "troops", "military", "ceasefire",
                "conflict", "attack", "border", "drone", "invasion", "clash",
                "gaza", "ukraine", "sudan", "nuclear", "rebel", "offensive")

MARKETS = [
    ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Brent", "BZ=F"),
    ("Gold", "GC=F"), ("Bitcoin", "BTC-USD"),
    ("NIFTY 50", "^NSEI"), ("SENSEX", "^BSESN"), ("USD/INR", "INR=X"),
]


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host.replace("www.", "")
    except Exception:
        return ""


def _fetch_feed(url: str) -> list[dict]:
    try:
        r = httpx.get(url, headers=UA, timeout=8.0, follow_redirects=True)
        parsed = feedparser.parse(r.content)
        out = []
        for e in parsed.entries[:12]:
            out.append({
                "title": (e.get("title") or "").strip(),
                "link": e.get("link") or "",
                "source": _host(url),
                "published": e.get("published", "") or e.get("updated", ""),
                "ts": time.mktime(e.published_parsed) if e.get("published_parsed") else 0,
            })
        return out
    except Exception:
        return []


def _gather(urls: list[str]) -> list[dict]:
    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(_fetch_feed, urls):
            items += res
    # dedupe by title, newest first
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: x["ts"], reverse=True):
        key = it["title"].lower()[:60]
        if it["title"] and key not in seen:
            seen.add(key)
            uniq.append(it)
    return uniq


def _quote(symbol: str) -> dict | None:
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
        r = httpx.get(url, headers=UA, timeout=6.0)
        meta = r.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None or not prev:
            return None
        change = (price - prev) / prev * 100
        return {"price": round(price, 2), "change_pct": round(change, 2)}
    except Exception:
        return None


def _markets() -> list[dict]:
    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda s: (s[0], _quote(s[1])), MARKETS))
    for name, q in results:
        if q:
            out.append({"name": name, **q})
    return out


def _newsapi(endpoint: str, params: dict) -> list[dict]:
    key = os.environ.get("NEWSAPI_KEY")
    if not key:
        return []
    try:
        params = {**params, "apiKey": key, "pageSize": 10}
        r = httpx.get(f"https://newsapi.org/v2/{endpoint}", params=params, timeout=8.0)
        arts = r.json().get("articles", [])
        return [{"title": a.get("title", ""), "link": a.get("url", ""),
                 "source": (a.get("source") or {}).get("name", ""),
                 "published": a.get("publishedAt", ""), "ts": 0}
                for a in arts if a.get("title")]
    except Exception:
        return []


def _briefing(world, economy, india) -> str:
    try:
        import brain
        if not brain.available_providers():
            return ""
        heads = [h["title"] for h in (world[:6] + economy[:3] + india[:3])]
        msg = [
            {"role": "system", "content":
             "You are JARVIS giving a crisp morning briefing. In 3-4 short "
             "spoken-style sentences, summarize the day's most important world "
             "news, any conflict/war developments, and key economy/market "
             "moves (global + India). No lists, no markdown, just the briefing."},
            {"role": "user", "content": "Headlines:\n" + "\n".join(heads)},
        ]
        return (brain.chat(msg).message.content or "").strip()
    except Exception:
        return ""


def get_news(force: bool = False) -> dict:
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["ts"] < CACHE_TTL:
        return _CACHE["data"]

    world = _gather(FEEDS["world"]) + _newsapi("top-headlines", {"language": "en"})
    economy = _gather(FEEDS["economy"]) + _newsapi(
        "top-headlines", {"category": "business", "language": "en"})
    india = _gather(FEEDS["india"]) + _newsapi("top-headlines", {"country": "in"})

    # War/geopolitics = world items mentioning conflict keywords.
    war = [w for w in world
           if any(k in w["title"].lower() for k in WAR_KEYWORDS)][:8]

    data = {
        "updated": now,
        "briefing": _briefing(world, economy, india),
        "world": world[:14],
        "war": war,
        "economy": economy[:10],
        "india": india[:10],
        "markets": _markets(),
    }
    _CACHE["data"], _CACHE["ts"] = data, now
    return data
