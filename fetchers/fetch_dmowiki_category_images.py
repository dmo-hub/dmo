"""Save every picture shown on a dmowiki.com category page, full size.

    python fetchers/fetch_dmowiki_category_images.py Digimon_Rank_U
    python fetchers/fetch_dmowiki_category_images.py Digimon_Rank_U --dry-run

The category page only carries thumbnails (/images/thumb/a/ab/X.png/120px-X.png);
the original sits at /images/a/ab/X.png. Digimon portraits go to
docs/img/wiki/digimon/, the rank badges (N.png, SSS+.png ...) to
docs/img/wiki/rank/. Files already on disk are kept unless --force.

Runs inside the dmowiki tab a person already let past Cloudflare (_cdp_tab).
"""

import argparse
import base64
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cdp_tab import ORIGIN, ChallengeError, RawTab  # noqa: E402
from fetch_dmowiki_images import JS_FETCH_BYTES  # noqa: E402

PROJ = Path(__file__).resolve().parent.parent
OUT = PROJ / "docs" / "img" / "wiki"
RANK_RE = re.compile(r"^(N|A|S|SS|SSS|U)\+?$")


def originals(html: str) -> list[str]:
    out = []
    for src in re.findall(r'<img[^>]+src="(/images/[^"]+)"', html):
        m = re.match(r"/images/thumb/(\w/\w\w/[^/]+)/[^/]+$", src)
        out.append("/images/" + m.group(1) if m else src)
    return list(dict.fromkeys(out))


def target(path: str) -> Path:
    name = unquote(path.rsplit("/", 1)[-1])
    stem = name.rsplit(".", 1)[0]
    sub = "rank" if RANK_RE.match(stem) else "digimon"
    return OUT / sub / re.sub(r"[^A-Za-z0-9._+()-]+", "_", name)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("category", help="e.g. Digimon_Rank_U")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tab = RawTab()
    status, html = tab.get_html(f"{ORIGIN}/Category:{args.category}")
    if status != 200:
        sys.exit(f"ERROR: Category:{args.category} answered {status}")
    paths = originals(html)
    todo = [(p, target(p)) for p in paths if args.force or not target(p).exists()]
    print(f"{len(paths)} pictures on Category:{args.category}, {len(todo)} to fetch")
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
