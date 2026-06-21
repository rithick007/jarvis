"""
mac_control/web.py — open URLs and run web searches in the default browser.

Both are safe: opening a tab can't hurt anything, so they happen instantly.
"""

import subprocess
from urllib.parse import quote_plus


def _open(target: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(["open", target],
                              capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return proc.returncode == 0, (proc.stderr or "").strip()


def web_search(query: str) -> str:
    """Open the default browser to a Google search for `query`."""
    query = query.strip()
    if not query:
        return "What should I search for, master?"
    ok, err = _open(f"https://www.google.com/search?q={quote_plus(query)}")
    return f"Searching the web for '{query}'." if ok else f"Couldn't open the browser: {err}"


def open_url(url: str) -> str:
    """Open a URL in the default browser. Adds https:// if missing."""
    url = url.strip()
    if not url:
        return "Which page should I open?"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    ok, err = _open(url)
    return f"Opening {url}." if ok else f"Couldn't open {url}: {err}"
