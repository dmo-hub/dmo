"""Fetch dmowiki.com digimon pages for entries that DMW Wiki doesn't have data for,
using a running Chrome (CDP). dmowiki.com is behind Cloudflare so plain `requests`
can't reach it — we ride along with a Chrome session that has already solved the
CAPTCHA, just like fetch_via_cdp.py.

Setup before running:
  1. Close all Chrome windows.
  2. Launch Chrome with:
       chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\temp\\chrome-cdp
  3. In that Chrome, open  https://dmowiki.com/Category:Digimon_Rank_U
     (any dmowiki URL works). Click the CAPTCHA, wait for the real page.
  4. Run this script:  python fetch_dmowiki_digimon.py

For each digimon in scan_result_digimon.json that lacks an `attributes` field,
the script:
  * resolves a dmowiki URL  (via rank_u.html mapping + manual OVERRIDES)
  * navigates the existing CDP tab to that URL
  * waits for #firstHeading to render (means past Cloudflare)
  * saves the page HTML to cache/dmowiki_<slug>.html

After fetching, run  python enrich_digimon_attributes.py  to parse the new
cache files into scan_result_digimon.json.
"""

import json
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SCAN = PROJ / "data" / "scan_result_digimon.json"
RANK_U = PROJ / "rank_u.html"
CACHE = PROJ / "cache"

# Manual gameking-name → dmowiki-slug overrides for cases where the dmowiki
# page name can't be derived directly from the gameking name (Eosmon LV6,
# different parenthesization, etc.). Slugs are the portion of the URL after
# https://dmowiki.com/.
OVERRIDES: dict[str, str] = {
    "Kuzuhamon MikoMode": "Kuzuhamon_-_Miko_Mode",
    "Eosmon": "Eosmon_LV6",
    "QUANTUMON": "Quantumon",
    # one wiki page covers the species whichever line it evolves into
    "Tsukaimon (Barbamon Line)": "Tsukaimon",
    "Chaosmon": "Chaosmon",
    "Rafflesimon": "Rafflesimon",
    "Fanglongmon (Shin)": "Fanglongmon_(Shin)",
}


def safe_filename(slug: str) -> str:
    """Slug → filesystem-safe filename component.

    Windows / NTFS rejects `:` in filenames (it silently turns the rest into
    an Alternate Data Stream). Replace it (and other reserved chars) with `~`
    so cache files round-trip cleanly. The transformation is reversible per
    the slug only via the same call (we never reconstruct slugs from filenames
    — name→slug always goes via rank_u.html + OVERRIDES).
    """
    return re.sub(r'[:<>"/\\|?*]', "~", slug)


def build_rank_u_map() -> dict[str, str]:
    """Parse rank_u.html for (title, href) pairs → {title: slug}."""
    html = RANK_U.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for href, title in re.findall(r'<li><a href="([^"]+)" title="([^"]+)">', html):
        slug = href.rsplit("/", 1)[-1]
        out[title] = slug
    return out


def resolve_slug(name: str, rank_map: dict[str, str]) -> str | None:
    """Return the dmowiki slug for a digimon name, or None if unknown."""
    if name in OVERRIDES:
        return OVERRIDES[name]
    # Exact match against rank_u titles
    if name in rank_map:
        return rank_map[name]

    # Normalize: collapse spaces/punctuation, try fuzzy contains both ways
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    n = norm(name)
    for title, slug in rank_map.items():
        t = norm(title)
        if n == t or n in t or t in n:
            return slug
    return None


def find_missing(data: dict, rank_map: dict[str, str]) -> list[tuple[str, str]]:
    """Return [(name, slug)] pairs for digimon lacking `attributes`."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind in ("event", "patch"):
        for post in data.get(kind, {}).values():
            attrs = post.get("attributes", {})
            for name in post["digimon"]:
                if name in attrs or name in seen:
                    continue
                seen.add(name)
                slug = resolve_slug(name, rank_map)
                if slug:
                    pairs.append((name, slug))
                else:
                    print(f"  ! no slug mapping for: {name}")
    return pairs


def fetch_one(page, slug: str, out: Path) -> bool:
    url = f"https://dmowiki.com/{slug}"
    print(f"  \u2192 {url}")
    status, html = page.get_html(url)
    if status != 200 or 'id="firstHeading"' not in html:
        print(f"    ! answered {status}, not a wiki page")
        return False
    out.write_text(html, encoding="utf-8")
    print(f"    \u2713 saved {len(html)} bytes \u2192 {out.relative_to(PROJ)}")
    return True


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    rank_map = build_rank_u_map()
    print(f"Loaded {len(rank_map)} entries from rank_u.html\n")

    data = json.loads(SCAN.read_text(encoding="utf-8"))
    missing = find_missing(data, rank_map)
    if not missing:
        print("Nothing missing — all digimon already have `attributes`.")
        return
    print(f"\n{len(missing)} digimon need dmowiki fetch:")
    for name, slug in missing:
        print(f"  - {name}  →  {slug}")

    from _cdp_tab import RawTab

    page = RawTab()
    print(f"\nUsing tab: {page.url}")

    ok, skipped = 0, 0
    for name, slug in missing:
        out = CACHE / f"dmowiki_{safe_filename(slug)}.html"
        if out.exists():
            print(f"\n{name}  (cached, skip)")
            skipped += 1
            continue
        print(f"\n{name}")
        if fetch_one(page, slug, out):
            ok += 1
        time.sleep(1.2)  # polite delay

    print(f"\n--- fetched {ok}, skipped {skipped} ---")


if __name__ == "__main__":
    main()
