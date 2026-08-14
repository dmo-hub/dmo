"""Fetch Thai (vplay.in.th) dungeon post bodies into cache/.

Reads data/th_patch_index.json (built by fetch_th_patch_index.py), keeps posts
whose title names a dungeon ("ดันเจี้ยน…"), and downloads each post body to
  cache/th_dungeon_<slug>.html

Offline scanning (scan_dungeons.py) parses these cached files — this fetcher is
the only step that touches the network for the TH server.
"""

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

TITLE_KW = ("ดันเจี้ยน", "ดันเจียน")


def slug_of(post):
    m = re.search(r"/([^/]+)/?$", post["url"].rstrip("/"))
    raw = m.group(1) if m else post["id"]
    return re.sub(r"[^a-z0-9%_-]", "", raw)[:60] or str(post["id"])


def dungeon_posts():
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    return [p for p in idx["posts"] if any(k in p.get("title", "") for k in TITLE_KW)]


def main():
    CACHE.mkdir(exist_ok=True)
    posts = dungeon_posts()
    print(f"TH dungeon posts in index: {len(posts)}")
    for p in posts:
        out = CACHE / f"th_dungeon_{slug_of(p)}.html"
        if out.exists():
            print(f"  cached  {out.name}")
            continue
        r = requests.get(p["url"], headers=HEADERS, timeout=30)
        r.raise_for_status()
        out.write_text(r.text, encoding="utf-8")
        print(f"  fetched {out.name}  ({len(r.text)} b)")
        time.sleep(1.5)


if __name__ == "__main__":
    main()
