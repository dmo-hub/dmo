"""Scrape KR news board (digimonmasters.com Btype=Update) and build a date-indexed
list of Update posts, so other scripts can cross-reference English gameking posts
to their original Korean source.

Output: kr_news_index.json
  {
    "fetched_at": "YYYY-MM-DD",
    "posts": [
      {"o": "816756", "date": "2026-05-19", "type": "update", "title": "...", "url": "..."},
      ...
    ]
  }

Caches each list page under cache/kr_list_p<N>.html. Re-running is incremental:
- New pages (1..N) are fetched until a page's oldest date is older than STOP_DATE.
- Set STOP_DATE in main() (defaults to 2024-01-01) to cap how far back to scrape.
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
OUT = PROJ / "data" / "kr_news_index.json"

BASE = "https://www.digimonmasters.com/news"
LIST_URL = f"{BASE}/newsBoard_list.aspx?Btype=Update&p={{page}}"
VIEW_URL = f"{BASE}/newsBoard_sub.aspx?o={{o}}&Btype=Update"

# Each <li class="forum_list_li"> contains: num, title, hit, date, anchored by o=
POST_RE = re.compile(
    r"newsBoard_sub\.aspx\?o=(?P<o>\d+)[^'\"]*['\"][^>]*>"
    r".*?<div class=\"list_num\"><p>(?P<num>\d+)</p></div>"
    r".*?<div class=\"list_title\"><p>(?P<title>[^<]+)</p></div>"
    r".*?<div class=\"list_date\"><p>(?P<date>\d{4}-\d{2}-\d{2})</p></div>",
    re.DOTALL,
)


def classify(title: str) -> str:
    """KR titles end with '업데이트 안내' (Update) or '프로모션 안내' (Promotion)."""
    if "업데이트" in title:
        return "update"
    if "프로모션" in title:
        return "promotion"
    return "other"


def fetch_page(page: int, force: bool = False) -> str:
    cache_file = CACHE / f"kr_list_p{page}.html"
    if cache_file.exists() and not force:
        return cache_file.read_text(encoding="utf-8")
    r = requests.get(LIST_URL.format(page=page), timeout=30)
    r.raise_for_status()
    CACHE.mkdir(exist_ok=True)
    cache_file.write_text(r.text, encoding="utf-8")
    return r.text


def parse_page(html: str) -> list[dict]:
    posts = []
    for m in POST_RE.finditer(html):
        posts.append(
            {
                "o": m.group("o"),
                "num": int(m.group("num")),
                "date": m.group("date"),
                "type": classify(m.group("title")),
                "title": m.group("title").strip(),
                "url": VIEW_URL.format(o=m.group("o")),
            }
        )
    return posts


def main(stop_date: str = "2024-01-01", force_first: bool = True) -> None:
    """Scrape pages 1..N until the oldest date on a page is < stop_date.

    force_first: re-fetch page 1 to pick up the latest posts (other pages are stable).
    """
    all_posts: dict[str, dict] = {}  # keyed by o to dedupe
    page = 1
    while True:
        force = force_first and page == 1
        html = fetch_page(page, force=force)
        posts = parse_page(html)
        if not posts:
            print(f"page {page}: 0 posts, stopping")
            break
        for p in posts:
            all_posts[p["o"]] = p
        oldest = min(p["date"] for p in posts)
        newest = max(p["date"] for p in posts)
        print(f"page {page}: {len(posts)} posts, {oldest} … {newest}")
        if oldest < stop_date:
            print(f"  oldest {oldest} < stop {stop_date} — done")
            break
        page += 1
        if page > 200:
            print("  page cap 200 reached")
            break
        time.sleep(0.3)

    sorted_posts = sorted(all_posts.values(), key=lambda x: -x["num"])
    out = {
        "fetched_at": time.strftime("%Y-%m-%d"),
        "stop_date": stop_date,
        "total": len(sorted_posts),
        "update_count": sum(1 for p in sorted_posts if p["type"] == "update"),
        "posts": sorted_posts,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\nWrote {OUT.name}: {out['total']} posts ({out['update_count']} update, "
        f"{out['total'] - out['update_count']} other)"
    )


if __name__ == "__main__":
    # Earliest digimon post in scan_result_digimon.json is 2024-03-05;
    # default cap a bit earlier for safety.
    main(stop_date="2024-01-01")
