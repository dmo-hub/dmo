"""Fetch any list of dmowiki.com pages through a Chrome that already passed
Cloudflare (CDP), into cache/.

dmowiki.com puts every path behind a Cloudflare managed challenge — api.php
included — so plain `requests` gets a 403 "Just a moment..." page. A human
solves the challenge once in a real Chrome; the `cf_clearance` cookie it earns
then covers every later request from that browser, so this script reuses it
instead of trying to look like a browser itself.

Two modes:

  --mode html  (default)  navigate the tab to each page and save the rendered
                          HTML  -> cache/dmowiki_<slug>.html  (what the existing
                          scan_clothing / scan_chipsets / scan_attributes read)
  --mode api              call MediaWiki api.php from INSIDE the tab (same
                          origin, so the clearance cookie rides along) and save
                          the raw wikitext -> cache/dmowiki_<slug>.json
                          Batches up to 50 titles per request, so a whole
                          category costs a handful of hits instead of one
                          navigation per page.

Setup before running:
  1. Close all Chrome windows.
  2. Launch Chrome with:
       chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\temp\\chrome-cdp
  3. Open https://dmowiki.com in that Chrome, solve the CAPTCHA, wait for the
     real page.
  4. Run, e.g.:
       python fetchers/fetch_dmowiki_pages.py Clothing ChipSets Equipment_attributes
       python fetchers/fetch_dmowiki_pages.py --mode api --category Digimon_Rank_U
       python fetchers/fetch_dmowiki_pages.py --mode api --list titles.txt --force
       python fetchers/fetch_dmowiki_pages.py --dry-run Clothing

Existing cache files are skipped unless --force — cache/ is the source of truth
for parser iteration, so re-hitting the wiki should be a deliberate choice.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.stdout.reconfigure(encoding="utf-8")

# fetch_dmowiki_digimon owns the slug -> filename rule; reusing it keeps every
# dmowiki cache file named the same way no matter which fetcher wrote it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_dmowiki_digimon import safe_filename  # noqa: E402
from _cdp_tab import ChallengeError, RawTab  # noqa: E402

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
ORIGIN = "https://dmowiki.com"
API = "/api.php"
# MediaWiki's per-request title limit for non-bot clients.
API_BATCH = 50

# Runs inside the page so the request carries the tab's cookies (cf_clearance).
# Returns text, not JSON: a challenge page comes back as HTML and must be
# reported, not crash JSON.parse inside the browser.
JS_FETCH = """async (url) => {
  const r = await fetch(url, {credentials: 'same-origin'});
  return {status: r.status, type: r.headers.get('content-type') || '', body: await r.text()};
}"""


class ApiUnavailable(RuntimeError):
    """api.php answered with something other than JSON (disabled, blocked, moved)."""


def slug_of(title: str) -> str:
    return title.strip().replace(" ", "_")


def cache_path(title: str, ext: str) -> Path:
    # Lowercase matches the names the scanners already read
    # (dmowiki_clothing.html for the page "Clothing").
    return CACHE / f"dmowiki_{safe_filename(slug_of(title)).lower()}.{ext}"


def read_titles(args: argparse.Namespace) -> list[str]:
    titles = list(args.titles)
    if args.list:
        for line in Path(args.list).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                titles.append(line)
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        key = slug_of(t)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def api_get(page, params: dict) -> dict:
    query = "&".join(f"{k}={quote(str(v), safe='|')}" for k, v in params.items())
    res = page.evaluate(JS_FETCH, f"{API}?{query}")
    if "Just a moment" in res["body"][:2000]:
        raise ChallengeError("Cloudflare challenge on api.php — solve it again in Chrome")
    # Parse first, judge by content-type second: some hosts send JSON as text/html,
    # and when it is not JSON the body is the only clue to why.
    try:
        data = json.loads(res["body"])
    except ValueError:
        head = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", res["body"]))[:300].strip()
        raise ApiUnavailable(f"api.php returned {res['status']} {res['type']!r}, not JSON: {head}")
    if "error" in data:
        raise RuntimeError(f"api.php error: {data['error']}")
    return data


def category_titles(page, category: str) -> list[str]:
    name = slug_of(category)
    if not name.lower().startswith("category:"):
        name = f"Category:{name}"
    titles: list[str] = []
    params = {
        "action": "query", "list": "categorymembers", "cmtitle": name,
        "cmlimit": "max", "cmtype": "page", "format": "json", "formatversion": "2",
    }
    while True:
        data = api_get(page, params)
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        cont = data.get("continue")
        if not cont:
            return titles
        params.update(cont)


def revision_text(rev: dict) -> str | None:
    # MediaWiki >= 1.32 nests content under slots.main; older versions put it
    # on the revision itself ("content" in formatversion 2, "*" in 1).
    main = rev.get("slots", {}).get("main", {})
    return main.get("content", rev.get("content", rev.get("*")))


def fetch_api(page, titles: list[str], delay: float) -> tuple[int, list[str]]:
    ok, failed = 0, []
    for i in range(0, len(titles), API_BATCH):
        batch = titles[i:i + API_BATCH]
        data = api_get(page, {
            "action": "query", "prop": "revisions", "rvprop": "ids|timestamp|content",
            "rvslots": "main", "redirects": "1", "titles": "|".join(batch),
            "format": "json", "formatversion": "2",
        })
        query = data.get("query", {})
        # Redirected / normalized titles come back under their target name;
        # map them back so the cache file is named after what was asked for.
        back: dict[str, str] = {}
        for step in query.get("normalized", []) + query.get("redirects", []):
            back[step["to"]] = back.get(step["from"], step["from"])
        for p in query.get("pages", []):
            asked = back.get(p["title"], p["title"])
            if p.get("missing") or p.get("invalid") or not p.get("revisions"):
                print(f"  ! {asked}: no such page")
                failed.append(asked)
                continue
            rev = p["revisions"][0]
            text = revision_text(rev)
            if text is None:
                print(f"  ! {asked}: revision has no content")
                failed.append(asked)
                continue
            out = cache_path(asked, "json")
            out.write_text(json.dumps({
                "title": p["title"], "pageid": p["pageid"], "revid": rev.get("revid"),
                "timestamp": rev.get("timestamp"), "wikitext": text,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  ✓ {asked} rev {rev.get('revid')} → {out.relative_to(PROJ)}")
            ok += 1
        if i + API_BATCH < len(titles):
            time.sleep(delay)
    return ok, failed


def fetch_html_one(page, title: str, out: Path) -> bool:
    url = f"{ORIGIN}/{quote(title, safe=':_()')}"
    status, html = page.get_html(url)
    # A missing page still renders (with an edit prompt); caching it would make
    # every later run skip the title as already fetched.
    if status == 404 or "noarticletext" in html:
        print(f"  ! {title}: no such page")
        return False
    if status != 200 or 'id="firstHeading"' not in html:
        print(f"  ! {title}: answered {status}, not a wiki page")
        return False
    out.write_text(html, encoding="utf-8")
    print(f"  \u2713 {title} {len(html)} bytes \u2192 {out.relative_to(PROJ)}")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("titles", nargs="*", help="page titles, e.g. Clothing ChipSets")
    ap.add_argument("--list", help="text file, one title per line (# comments ok)")
    ap.add_argument("--category", help="add every page in this category (needs api.php)")
    ap.add_argument("--mode", choices=["html", "api"], default="html")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between requests")
    ap.add_argument("--force", action="store_true", help="refetch even if cached")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    args = ap.parse_args()

    titles = read_titles(args)
    if not titles and not args.category:
        ap.error("give page titles, --list or --category")
    ext = "json" if args.mode == "api" else "html"

    if args.dry_run:
        if args.category:
            print(f"category {args.category}: members resolved at run time")
        for t in titles:
            out = cache_path(t, ext)
            state = "refetch" if out.exists() and args.force else "cached, skip" if out.exists() else "fetch"
            print(f"  {t} → {out.relative_to(PROJ)}  ({state})")
        return

    CACHE.mkdir(exist_ok=True)
    page = RawTab()
    print(f"Using tab: {page.url}")
    try:
        if args.category:
            members = category_titles(page, args.category)
            print(f"category {args.category}: {len(members)} pages")
            titles = read_titles(argparse.Namespace(titles=titles + members, list=None))
        todo = [t for t in titles if args.force or not cache_path(t, ext).exists()]
        skipped = len(titles) - len(todo)
        print(f"{len(todo)} to fetch, {skipped} cached\n")
        if args.mode == "api":
            ok, failed = fetch_api(page, todo, args.delay)
        else:
            ok, failed = 0, []
            for n, t in enumerate(todo):
                if fetch_html_one(page, t, cache_path(t, ext)):
                    ok += 1
                else:
                    failed.append(t)
                if n + 1 < len(todo):
                    time.sleep(args.delay)
    except ChallengeError as e:
        sys.exit(f"\nSTOPPED: {e}. Already-saved files stay in cache/; re-run to resume.")
    except ApiUnavailable as e:
        sys.exit(f"\nSTOPPED: {e}\nRe-run with --mode html to save the rendered pages instead.")

    print(f"\n--- fetched {ok}, skipped {skipped}, failed {len(failed)} ---")
    for t in failed:
        print(f"  failed: {t}")


if __name__ == "__main__":
    main()
