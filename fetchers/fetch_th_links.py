"""Fetch the vplay.in.th pages that cached Thai posts link to.

A patch-note post often names a dungeon or event and links to its own page
for the drop table, so a Thai item name missing from cache/th_view_*.html is
often one link away. This walks every vplay link in those posts and saves each
target once.

Output: cache/th_link_<sha1[:12]>.html per page, plus cache/th_link_index.json
mapping each key to {"url", "label"} (label = the anchor text).

Links seen 100+ times are site navigation, not content, and category / wp-*
URLs are archive pages, so both are skipped. Already-cached pages are skipped;
delete a file to refetch it.
"""

import collections
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

HEADERS = {"User-Agent": "Mozilla/5.0"}
LINK_RE = re.compile(
    r'<a[^>]+href="(https?://(?:www\.)?vplay\.in\.th/[^"#?]+)"[^>]*>(.*?)</a>', re.S
)


def main():
    links = collections.Counter()
    label = {}
    for f in CACHE.glob("th_view_*.html"):
        h = f.read_text(encoding="utf-8", errors="ignore")
        for m in LINK_RE.finditer(h):
            u = m.group(1).rstrip("/")
            links[u] += 1
            label.setdefault(u, re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()[:80])
    todo = [u for u, c in links.items() if c < 100 and "/category/" not in u and "/wp-" not in u]
    print("to fetch", len(todo), flush=True)

    index = {}
    ok = fail = skip = 0
    for u in todo:
        key = hashlib.sha1(u.encode()).hexdigest()[:12]
        path = CACHE / f"th_link_{key}.html"
        index[key] = {"url": u, "label": label[u]}
        if path.exists():
            skip += 1
            continue
        try:
            r = requests.get(u, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                path.write_text(r.text, encoding="utf-8")
                ok += 1
            else:
                fail += 1
                print("HTTP", r.status_code, u, flush=True)
        except Exception as e:
            fail += 1
            print("ERR", str(e)[:80], u, flush=True)
        time.sleep(0.3)

    (CACHE / "th_link_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"done ok={ok} skip={skip} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
