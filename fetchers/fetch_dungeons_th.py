"""Fetch Thai (vplay.in.th) dungeon post bodies into cache/.

Reads data/th_patch_index.json (built by fetch_th_patch_index.py), keeps posts
whose title names a dungeon ("ดันเจี้ยน…"), and downloads each post body to
  cache/th_dungeon_<slug>.html

Offline scanning (scan_dungeons.py) parses these cached files — this fetcher is
the only step that touches the network for the TH server.
"""

import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
INDEX = PROJ / "data" / "th_patch_index.json"
PATCH_DUNGEONS = PROJ / "data" / "th_patch_dungeons.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

TITLE_KW = ("ดันเจี้ยน", "ดันเจียน")


def slug_of(post):
    m = re.search(r"/([^/]+)/?$", post["url"].rstrip("/"))
    raw = m.group(1) if m else post["id"]
    safe = re.sub(r"[^a-z0-9%_-]", "", raw)
    if len(safe) > 60:
        # Thai slugs percent-encode to ~9 bytes a letter, so 60 bytes is just
        # "ดันเจี้ยน" and every dungeon page landed on the same file.
        safe = safe[:44] + "-" + hashlib.md5(safe.encode()).hexdigest()[:12]
    return safe or str(post["id"])


def dungeon_posts():
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    return [p for p in idx["posts"] if any(k in p.get("title", "") for k in TITLE_KW)]


def detail_pages():
    """The "more details" pages a patch post links its new dungeons to (see
    scan_th_patch_dungeons.py); they are not in the patch category index."""
    if not PATCH_DUNGEONS.exists():
        return []
    rows = json.loads(PATCH_DUNGEONS.read_text(encoding="utf-8"))["dungeons"]
    return [{"id": d["name"], "url": d["detail_url"]} for d in rows if d.get("detail_url")]


def main():
    CACHE.mkdir(exist_ok=True)
    posts = dungeon_posts()
    details = detail_pages()
    print(f"TH dungeon posts in index: {len(posts)}, detail pages linked from patches: {len(details)}")
    for p in posts + details:
        out = CACHE / f"th_dungeon_{slug_of(p)}.html"
        if out.exists():
            print(f"  cached  {out.name}")
            continue
        r = requests.get(p["url"], headers=HEADERS, timeout=30)
        if r.status_code == 404 and p in details:
            # vplay has binned some of these (".../__trashed/"); the patch
            # post's own section is then all there is.
            print(f"  gone    {p['url']}")
            continue
        r.raise_for_status()
        out.write_text(r.text, encoding="utf-8")
        print(f"  fetched {out.name}  ({len(r.text)} b)")
        time.sleep(1.5)


if __name__ == "__main__":
    main()
