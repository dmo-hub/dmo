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

Caches each list page under cache/kr_list_p<N>.html. Every run re-fetches:
- Pages (1..N) are fetched until a page's oldest date is older than STOP_DATE.
- Set STOP_DATE in main() (defaults to 2024-01-01) to cap how far back to scrape.
"""

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
OUT = PROJ / "data" / "kr_news_index.json"

BASE = "https://www.digimonmasters.com/news"
LIST_URL = f"{BASE}/newsBoard_list.aspx?Btype=Update&p={{page}}"
VIEW_URL = f"{BASE}/newsBoard_sub.aspx?o={{o}}&Btype=Update"

# Fields are matched inside one <li> at a time: a single pattern spanning the
# whole item ran on into the next one whenever an item broke it (the last row
# of each page carries class="bottom_line"class="list_title"; same-day posts
# show "today 10:47"), taking the next item's date and dropping both.
LI_RE = re.compile(r'<li class="forum_list_li">(.*?)</li>', re.DOTALL)
O_RE = re.compile(r"newsBoard_sub\.aspx\?o=(\d+)")
NUM_RE = re.compile(r'class="list_num"><p>(\d+)</p>')
TITLE_RE = re.compile(r'class="list_title"><p>([^<]+)</p>')
DATE_RE = re.compile(r'class="list_date"><p>([^<]+)</p>')
KST = timezone(timedelta(hours=9))


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


def parse_date(s: str) -> str | None:
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    if s.startswith("today"):
        # the board's "today" is Korean time
        return datetime.now(KST).strftime("%Y-%m-%d")
    return None


def parse_page(html: str) -> list[dict]:
    posts = []
    for li in LI_RE.findall(html):
        o, num, title, date = (r.search(li) for r in (O_RE, NUM_RE, TITLE_RE, DATE_RE))
        day = parse_date(date.group(1)) if date else None
        if not (o and num and title and day):
            flat = re.sub(r"\s+", " ", li)
            print(f"  ! unparsed list item: {flat[:160]}")
            continue
        posts.append(
            {
                "o": o.group(1),
                "num": int(num.group(1)),
                "date": day,
                "type": classify(title.group(1)),
                "title": title.group(1).strip(),
                "url": VIEW_URL.format(o=o.group(1)),
            }
        )
    return posts


def main(stop_date: str = "2024-01-01") -> None:
    """Scrape pages 1..N until the oldest date on a page is < stop_date.

    Every page is re-fetched: each new post pushes the rest down one slot, so a
    cached page 2 next to a fresh page 1 silently drops the posts that crossed
    the boundary.
    """
    all_posts: dict[str, dict] = {}  # keyed by o to dedupe
    page = 1
    while True:
        html = fetch_page(page, force=True)
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
