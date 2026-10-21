"""Save every picture shown on a dmowiki.com category page, full size.

    python fetchers/fetch_dmowiki_category_images.py Digimon_Rank_U
    python fetchers/fetch_dmowiki_category_images.py Digimon_Rank_U --dry-run
    python fetchers/fetch_dmowiki_category_images.py --page Apollomon_Whispered

--page takes digimon pages instead of a category and saves each page's
infobox portrait (its first file image). A category page leaves out the
picture of a digimon whose page has none in the gallery -- Apollomon
Whispered was listed on Category:Digimon_Rank_U without one.

The category page only carries thumbnails (/images/thumb/a/ab/X.png/120px-X.png);
the original sits at /images/a/ab/X.png. Digimon portraits go to
docs/img/wiki/digimon/ named after the wiki page each one links to
(redirects followed, so "Done Devimon" saves as DoneDevimon.png); the rank
badges (N.png, SSS+.png ...) go to docs/img/wiki/rank/. Files already on disk are kept unless --force.

Runs inside the dmowiki tab a person already let past Cloudflare (_cdp_tab).
"""

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cdp_tab import JS_FETCH_TEXT, ORIGIN, ChallengeError, RawTab  # noqa: E402
from fetch_dmowiki_digimon import safe_filename  # noqa: E402
from fetch_dmowiki_images import JS_FETCH_BYTES  # noqa: E402

PROJ = Path(__file__).resolve().parent.parent
OUT = PROJ / "docs" / "img" / "wiki"
RANK_RE = re.compile(r"^(N|A|S|SS|SSS|U)\+?$")


def originals(html: str) -> list[tuple[str, str | None]]:
    """(original image path, title of the page the picture links to or None)."""
    out = {}
    for m in re.finditer(r'(?:<a href="/[^"]+" title="([^"]+)">)?<img[^>]+src="(/images/[^"]+)"', html):
        title, src = m.group(1), m.group(2)
        t = re.match(r"/images/thumb/(\w/\w\w/[^/]+)/[^/]+$", src)
        out.setdefault("/images/" + t.group(1) if t else src, title)
    return list(out.items())


def canonical(tab: RawTab, titles: list[str]) -> dict[str, str]:
    """Gallery links may point at a redirect; name the file after the page itself."""
    if not titles:
        return {}
    res = tab.evaluate(JS_FETCH_TEXT, "/api.php?action=query&format=json&redirects=1&titles="
                       + quote("|".join(titles)))
    q = json.loads(res["body"]).get("query", {})
    norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
    red = {x["from"]: x["to"] for x in q.get("redirects", [])}
    return {t: red.get(norm.get(t, t), norm.get(t, t)) for t in titles}


def clean(part: str) -> str:
    # names come off a web page: keep a plain file name, never a path ("..", "/")
    return re.sub(r"[^A-Za-z0-9._+()~-]+", "_", part).strip(".") or "_"


def target(path: str, title: str | None) -> Path:
    name = unquote(path.rsplit("/", 1)[-1])
    stem, _, ext = name.rpartition(".")
    ext = re.sub(r"[^A-Za-z0-9]", "", ext) or "png"
    if RANK_RE.match(stem):
        out = OUT / "rank" / clean(name)
    elif not title:
        out = OUT / "digimon" / clean(name)
    else:
        out = OUT / "digimon" / f"{clean(safe_filename(title.replace(' ', '_')))}.{ext}"
    if not out.resolve().is_relative_to(OUT.resolve()):
        raise ValueError(f"refusing to write outside {OUT}: {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("category", nargs="+", help="e.g. Digimon_Rank_U (page titles with --page)")
    ap.add_argument("--page", action="store_true", help="arguments are digimon pages")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tab = RawTab()
    if args.page:
        names = canonical(tab, args.category)
        paths = []
        for title in args.category:
            status, html = tab.get_html(f"{ORIGIN}/{quote(title)}")
            if status != 200:
                sys.exit(f"ERROR: {title} answered {status}")
            found = originals(html)
            if not found:
                sys.exit(f"ERROR: {title} has no picture")
            paths.append((found[0][0], target(found[0][0], names.get(title, title))))
        where = "the given pages"
    else:
        status, html = tab.get_html(f"{ORIGIN}/Category:{args.category[0]}")
        if status != 200:
            sys.exit(f"ERROR: Category:{args.category[0]} answered {status}")
        found = originals(html)
        names = canonical(tab, [t for _, t in found if t])
        paths = [(p, target(p, names.get(t) if t else None)) for p, t in found]
        where = f"Category:{args.category[0]}"
    todo = [(p, out) for p, out in paths if args.force or not out.exists()]
    print(f"{len(paths)} pictures on {where}, {len(todo)} to fetch")
    if args.dry_run:
        for p, out in todo:
            print(f"  {p} -> {out.relative_to(PROJ)}")
        return

    ok, failed = 0, []
    try:
        for n, (p, out) in enumerate(todo):
            res = tab.evaluate(JS_FETCH_BYTES, ORIGIN + p)
            if res["status"] == 403 or res["type"].startswith("text/html"):
                raise ChallengeError(f"{p} answered {res['status']} {res['type']}")
            if res["status"] != 200 or not res["type"].startswith("image/"):
                failed.append(f"{p} ({res['status']} {res['type']})")
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(base64.b64decode(res["b64"]))
                ok += 1
                print(f"  ✓ {out.relative_to(PROJ)}")
            if n + 1 < len(todo):
                time.sleep(args.delay)
    except ChallengeError as e:
        sys.exit(f"\nSTOPPED after {ok}: {e}\nPass the challenge in Chrome and re-run; saved files are kept.")
    print(f"\n--- fetched {ok}, failed {len(failed)} ---")
    for f in failed:
        print(f"  failed: {f}")


if __name__ == "__main__":
    main()
