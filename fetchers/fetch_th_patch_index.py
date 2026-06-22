"""Scrape vplay.in.th (Thai DMO server fansite) /category/news/patch-note/
pagination to build a date-indexed list of Thai patch posts.

Output: th_patch_index.json
  {
    "fetched_at": "YYYY-MM-DD",
    "posts": [
      {"slug": "...-87", "url": "...", "date": "YYYY-MM-DD",
       "title": "รายละเอียดการอัพเดท…", "type": "patch" | "coming-soon" | "other"},
      ...
    ]
  }

Caches each category page under cache/th_list_p<N>.html. The Thai server lags
NA/KR by months (sometimes ~1 year), so we scan the full archive (19 pages
as of 2026-05).
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
OUT = PROJ / "data" / "th_patch_index.json"

LIST_URL_FIRST = "https://www.vplay.in.th/category/news/patch-note/"
LIST_URL_PAGE = "https://www.vplay.in.th/category/news/patch-note/page/{page}/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# vplay.in.th uses a custom WP theme; posts are wrapped in
#   <div id="post-N" class="seil-blog-post ... category-XXX ...">…</div>
# (not <article>). We split the page by post-N opening tags, then parse each.
POST_OPEN_RE = re.compile(
    r'<div\s+id="post-(?P<id>\d+)"\s+class="(?P<classes>[^"]*seil-blog-post[^"]*)"[^>]*>',
    re.IGNORECASE,
)
TITLE_RE = re.compile(
    r'<h3\s+class="post-title"><a\s+href="(?P<href>[^"]+)"[^>]*>(?P<title>[^<]+)</a>',
    re.IGNORECASE,
)
DATE_TIME_RE = re.compile(r'datetime="(\d{4}-\d{2}-\d{2})')
# Fallback: Thai date string like "21 พ.ค. 2569" (Buddhist year)
THAI_DATE_RE = re.compile(
    r"(\d{1,2})\s*(ม\.?ค\.?|ก\.?พ\.?|มี\.?ค\.?|เม\.?ย\.?|พ\.?ค\.?|มิ\.?ย\.?|ก\.?ค\.?|ส\.?ค\.?|ก\.?ย\.?|ต\.?ค\.?|พ\.?ย\.?|ธ\.?ค\.?)\s*(\d{4})"
)
THAI_MONTH = {
    "ม.ค.": 1,
    "มค": 1,
    "ก.พ.": 2,
    "กพ": 2,
    "มี.ค.": 3,
    "มีค": 3,
    "เม.ย.": 4,
    "เมย": 4,
    "พ.ค.": 5,
    "พค": 5,
    "มิ.ย.": 6,
    "มิย": 6,
    "ก.ค.": 7,
    "กค": 7,
    "ส.ค.": 8,
    "สค": 8,
    "ก.ย.": 9,
    "กย": 9,
    "ต.ค.": 10,
    "ตค": 10,
    "พ.ย.": 11,
    "พย": 11,
    "ธ.ค.": 12,
    "ธค": 12,
}


def parse_thai_date(s: str) -> str | None:
    m = THAI_DATE_RE.search(s)
    if not m:
        return None
    day = int(m.group(1))
    month_key = m.group(2).replace(" ", "")
    month = THAI_MONTH.get(month_key)
    if not month:
        return None
    year_be = int(m.group(3))
    year = year_be - 543  # Buddhist Era → CE
    return f"{year:04d}-{month:02d}-{day:02d}"


def classify_slug(slug: str) -> str:
    sl = slug.lower()
    # main update posts: Thai-slug (url-encoded) ending with -N (patch number)
    if "%e0%b8%a3%e0%b8%b2%e0%b8%a2%e0%b8%a5%e0%b8%b0" in sl and re.search(r"-\d+/?$", sl):
        return "patch"
    # alternative slugs
    if "coming-soon-patch" in sl:
        return "coming-soon"
    if "flash-sale" in sl:
        return "flash-sale"
    if "promo" in sl or "event" in sl:
        return "promo"
    return "other"


def fetch_page(page: int, force: bool = False) -> str:
    cache_file = CACHE / f"th_list_p{page}.html"
    if cache_file.exists() and not force:
        return cache_file.read_text(encoding="utf-8")
    url = LIST_URL_FIRST if page == 1 else LIST_URL_PAGE.format(page=page)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    CACHE.mkdir(exist_ok=True)
    cache_file.write_text(r.text, encoding="utf-8")
    return r.text


def parse_page(html: str) -> list[dict]:
    """Split page by `<div id="post-N">` openings and parse each block."""
    out = []
    matches = list(POST_OPEN_RE.finditer(html))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        block = html[start:end]
        title_m = TITLE_RE.search(block)
        if not title_m:
            continue
        url = title_m.group("href")
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        title = title_m.group("title").strip()
        date_m = DATE_TIME_RE.search(block)
        date = date_m.group(1) if date_m else parse_thai_date(block)
        out.append(
            {
                "id": m.group("id"),
                "slug": slug,
                "url": url,
                "title": title,
                "date": date,
                "type": classify_slug(url),
                "classes": m.group("classes")[:200],
            }
        )
    return out


def main(max_pages: int = 30, force_first: bool = True) -> None:
    seen: dict[str, dict] = {}
    page = 1
    while page <= max_pages:
        force = force_first and page == 1
        try:
            html = fetch_page(page, force=force)
        except requests.HTTPError as e:
            print(f"page {page}: HTTP {e.response.status_code} — stopping")
            break
        posts = parse_page(html)
        if not posts:
            print(f"page {page}: 0 posts, stopping")
            break
        for p in posts:
            seen[p["id"]] = p
        dates = [p["date"] for p in posts if p["date"]]
        print(
            f"page {page}: {len(posts)} posts ({dates[-1] if dates else '?'} … {dates[0] if dates else '?'})"
        )
        page += 1
        time.sleep(0.3)

    sorted_posts = sorted(seen.values(), key=lambda x: x["date"] or "", reverse=True)
    by_type: dict[str, int] = {}
    for p in sorted_posts:
        by_type[p["type"]] = by_type.get(p["type"], 0) + 1

    out = {
        "fetched_at": time.strftime("%Y-%m-%d"),
        "total": len(sorted_posts),
        "by_type": by_type,
        "posts": sorted_posts,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT.name}: {len(sorted_posts)} posts, by type: {by_type}")


if __name__ == "__main__":
    main()
