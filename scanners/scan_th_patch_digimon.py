"""Fetch every Thai patch-note post body from th_patch_index.json, extract:
  - Post date (parsed from Thai "DD <month_th> YYYY_BE" format)
  - `ดิจิมอนใหม่ : <thai_name>` marker (the Thai equivalent of NA's
    `[New Digimon Added - <name>]` and KR's `[신규 디지몬 추가 - <name>]`)
  - First non-thumbnail content image URL (the patch banner)

Output: th_patch_digimon.json — only posts that announce new digimon.

Caches each detail page under cache/th_view_<slug>.html.
"""

import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
INDEX = PROJ / "data" / "th_patch_index.json"
OUT = PROJ / "data" / "th_patch_digimon.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# "ดิจิมอนใหม่ : <name>" — capture up to a sentence break / next section keyword
NEW_DIGIMON_RE = re.compile(
    r"ดิจิมอนใหม่\s*[:：]\s*([^.\n]{1,120}?)(?=\s+สายวิวัฒนาการ|\s+วิวัฒนาการ|\s+\.|\s+เควส|$)",
    re.DOTALL,
)

THAI_MONTHS = {
    "มกราคม": 1,
    "กุมภาพันธ์": 2,
    "มีนาคม": 3,
    "เมษายน": 4,
    "พฤษภาคม": 5,
    "มิถุนายน": 6,
    "กรกฎาคม": 7,
    "สิงหาคม": 8,
    "กันยายน": 9,
    "ตุลาคม": 10,
    "พฤศจิกายน": 11,
    "ธันวาคม": 12,
}
THAI_DATE_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(THAI_MONTHS) + r")\s+(\d{4})")

# Banner image: wp-content/uploads/YYYY/MM/<name>.<ext>, original (not -WxH suffixed).
IMG_RE = re.compile(
    r'https?://(?:www\.)?vplay\.in\.th/wp-content/uploads/(20\d\d/\d\d)/([^"\'\s]+?\.(?:png|jpe?g|gif|webp))',
    re.IGNORECASE,
)
# Skip favicons, logos, social-share variants
CHROME_KW = ("apple-touch", "favicon", "vplay_logo", "footer", "header", "icon-")


def html_to_text(raw: str) -> str:
    t = re.sub(r"<[^>]+>", " ", raw)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def parse_thai_date(text: str) -> str | None:
    m = THAI_DATE_RE.search(text)
    if not m:
        return None
    day = int(m.group(1))
    month = THAI_MONTHS[m.group(2)]
    year = int(m.group(3)) - 543  # BE → CE
    return f"{year:04d}-{month:02d}-{day:02d}"


def is_thumbnail(url: str) -> bool:
    # Resized variants end with `-WxH.ext`
    return bool(re.search(r"-\d{2,4}x\d{2,4}\.(png|jpe?g|gif|webp)$", url, re.IGNORECASE))


def is_chrome(url: str) -> bool:
    s = url.lower()
    return any(k in s for k in CHROME_KW)


def first_banner(raw_html: str) -> str | None:
    """Return the first non-chrome, non-thumbnail uploads/ image URL."""
    for m in IMG_RE.finditer(raw_html):
        url = m.group(0)
        if is_chrome(url) or is_thumbnail(url):
            continue
        return url
    return None


def fetch_detail(slug: str, url: str, force: bool = False) -> str:
    cache_file = CACHE / f"th_view_{slug}.html"
    if cache_file.exists() and not force:
        return cache_file.read_text(encoding="utf-8")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    CACHE.mkdir(exist_ok=True)
    cache_file.write_text(r.text, encoding="utf-8")
    return r.text


def parse_post(slug: str, url: str, raw_html: str) -> dict | None:
    text = html_to_text(raw_html)
    nm = NEW_DIGIMON_RE.search(text)
    if not nm:
        return None  # not a new-digimon post
    th_name = nm.group(1).strip()
    return {
        "slug": slug,
        "url": url,
        "date": parse_thai_date(text),
        "th_name": th_name,
        "image_url": first_banner(raw_html),
    }


def process(post: dict) -> dict | None:
    try:
        raw = fetch_detail(post["slug"], post["url"])
    except Exception as e:
        print(f"  WARN {post['slug']}: {e}")
        return None
    return parse_post(post["slug"], post["url"], raw)


def cached_posts_missing_from_index(known_slugs: set[str]) -> list[dict]:
    """Posts whose detail page is cached but that the live category listing no
    longer returns. Seen for real: vplay dropped slugs -83..-87 from its
    listing (site-side renumber?), fetch_th_patch_index faithfully rebuilt the
    index without them, and the enricher then stripped source_th from entries
    whose TH match lived in those posts — while the cached HTML sat here, still
    perfectly parseable. Cache is a first-class source, not just a fetch skip."""
    extra = []
    for f in CACHE.glob("th_view_*.html"):
        slug = f.stem[len("th_view_") :]
        if slug in known_slugs or slug == "system":
            continue
        extra.append({"slug": slug, "url": f"https://www.vplay.in.th/{slug}/", "type": "patch"})
    return extra


def main() -> None:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    # Scan both `patch` (main update notices) and `coming-soon` (previews)
    candidates = [p for p in index["posts"] if p["type"] in ("patch", "coming-soon")]
    extra = cached_posts_missing_from_index({p["slug"] for p in index["posts"]})
    if extra:
        print(f"  +{len(extra)} cached post(s) missing from the live index — scanning those too")
        candidates += extra
    print(f"Scanning {len(candidates)} TH posts for `ดิจิมอนใหม่` markers...")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(process, p): p for p in candidates}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    # Dedup: the same post can be cached under two filenames (short alias like
    # "p-87" plus the full permalink slug). Same date + same th_name = same
    # post; keep the longest slug — that's the real permalink.
    best: dict[tuple, dict] = {}
    for r in results:
        k = (r["date"], r["th_name"])
        if k not in best or len(r["slug"]) > len(best[k]["slug"]):
            best[k] = r
    if len(best) != len(results):
        print(f"  deduped {len(results) - len(best)} alias-cached post(s)")
    results = list(best.values())

    results.sort(key=lambda x: x["date"] or "", reverse=True)
    out = {
        "fetched_at": time.strftime("%Y-%m-%d"),
        "scanned": len(candidates),
        "with_new_digimon": len(results),
        "posts": results,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT.name}: {len(results)}/{len(candidates)} posts had `ดิจิมอนใหม่` markers")
    for r in results[:30]:
        print(f"  {r['date']}  {r['slug'][:35]:35s}  → {r['th_name'][:60]}")
    if len(results) > 30:
        print(f"  ... ({len(results) - 30} more)")


if __name__ == "__main__":
    main()
