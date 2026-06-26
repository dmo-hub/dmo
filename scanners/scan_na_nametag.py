"""Extract NA Name-Tag-set exchange detail from gameking PatchNote + EventView.

Name Tag set only (generic "Enhancement Backup Chip" excluded):
  - Equipment Data: Name Tag
  - Name Tag Enhancement Hacking Tool
  - Name Tag Enhancement Backup Chip
  - (bare) Name Tag

For every post containing one, pulls the <table> row(s) that name the item:
the item label + amount, plus the box/exchange the row sits under. Output is a
matrix-friendly JSON: per-item -> per-patch counts/amounts.

    python scanners/scan_na_nametag.py                 # patch + event (default)
    python scanners/scan_na_nametag.py --patch-only

Writes data/na_nametag_items.json and caches each fetched post under cache/.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_decks import (  # noqa: E402
    BASE,
    CACHE,
    CONFIGS,
    enumerate_idx,
    fetch_detail,
    make_session,
)

PROJ = Path(__file__).resolve().parent.parent
OUT = PROJ / "data" / "na_nametag_items.json"

# canonical item -> match regex (longest/most-specific first). "Reinforced" is
# an older spelling of "Reinforcement" — folded onto the same canonical name.
ITEMS = [
    ("Name Tag Enhancement Backup Chip", r"Name\s*Tag\s*Enhancement\s*Backup\s*Chip"),
    ("Name Tag Enhancement Hacking Tool", r"Name\s*Tag\s*Enhancement\s*Hacking\s*Tool"),
    ("Name Tag Reinforcement Backup Chip", r"Name\s*Tag\s*Reinforce(?:ment|d)\s*Backup\s*Chip"),
    ("Name Tag Reinforcement Hacking Tool", r"Name\s*Tag\s*Reinforce(?:ment|d)\s*Hacking\s*Tool"),
    ("Equipment Data: Name Tag", r"Equipment\s*Data\s*:?\s*Name\s*Tag"),
]
ITEM_PATS = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in ITEMS]


def cell_text(cell_html):
    t = re.sub(r"<[^>]+>", " ", cell_html)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", t).strip()


def classify_item(label):
    """Return canonical item for a cell label, or None. Longest-match first."""
    for name, pat in ITEM_PATS:
        if pat.search(label):
            return name
    return None


# how a Name-Tag item was obtained, inferred from the table header + the text
# just above the table. Order matters — first match wins, so the paid/exchange
# sources are checked before "box" (a "Box Name | Item | Amount" table header
# appears inside package contents too, so it must NOT win over a Package/Summon
# context).
SOURCE_RULES = [
    # paid bundles — "Magnetic <anything> Package", Premium/Celebration packages,
    # "N Times per account", limited sale
    ("package", r"Magnetic\b[\w\s]*Package|Premium\s*Package|Celebration\s*Package"
                r"|Times?\s*per\s*account|limited\s*sale|on\s*sale"),
    # gacha / data summon
    ("summon", r"Data\s*Summon|New\s*Data\s*Summon|\bSummon\b"),
    ("exchange", r"Exchange(?:ment)?\s*[Ll]ist|Pendant\s*Exchange|Mileage"
                 r"|exchange\s*crafting|Exchangement"),
    ("craft", r"\bCraft\b"),
    # genuine drop / free box: monster drop, random box, event reward
    ("box", r"Random\s*Box|randomly\s*obtain|Reward\s*Item|Box\s*Name|\bdrop\b"),
]
SOURCE_PATS = [(k, re.compile(p, re.IGNORECASE)) for k, p in SOURCE_RULES]


def classify_source(header, context):
    """Tag a table as package / summon / exchange / craft / box. Default box."""
    blob = f"{context} {header}"
    for kind, pat in SOURCE_PATS:
        if pat.search(blob):
            return kind
    return "box"


def extract_rows(html):
    """Find every table row whose first/any cell names a Name-Tag item.

    Returns list of {item, amount, source, header, row: [cells...]}. `source`
    is the obtain-type inferred from the table header + preceding text, so the
    builder can split drop vs sale/exchange instead of summing them together.
    """
    out = []
    for m in re.finditer(r"<table.*?</table>", html, re.S | re.I):
        table = m.group()
        context = cell_text(html[max(0, m.start() - 280) : m.start()])[-160:]
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S | re.I)
        header = cell_text(rows[0]) if rows else ""
        source = classify_source(header, context)
        for row in rows:
            cells = [
                cell_text(c)
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
            ]
            cells = [c for c in cells if c]
            if not cells:
                continue
            label_cell = next((c for c in cells if classify_item(c)), None)
            if not label_cell:
                continue
            item = classify_item(label_cell)
            li = cells.index(label_cell)
            amount = cells[li + 1] if li + 1 < len(cells) else ""
            # skip section-title rows (a lone item label, no numeric amount) —
            # they are headings, not an actual grant
            if not re.search(r"\d", amount):
                continue
            out.append(
                {
                    "item": item,
                    "amount": amount,
                    "source": source,
                    "header": header[:80],
                    "row": cells,
                }
            )
    return out


SUBJECT_RE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4})\s*Update", re.IGNORECASE)


def cache_listing(kind):
    """Build a listing from cached HTML files (offline). idx + subject only."""
    items = []
    for f in sorted(CACHE.glob(f"{kind}_*.html")):
        idx = f.stem.split("_", 1)[1]
        if not idx.isdigit():
            continue
        body = f.read_text(encoding="utf-8", errors="ignore")
        m = SUBJECT_RE.search(body)
        items.append({"idx": idx, "subject": (m.group(0) if m else ""), "reg_date": ""})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch-only", action="store_true")
    ap.add_argument("--from-cache", action="store_true",
                    help="skip network; reparse cached HTML only")
    args = ap.parse_args()
    kinds = ["patch"] if args.patch_only else ["patch", "event"]

    session = make_session()
    posts_out = []  # {kind, idx, date, subject, url, items: {item: [amounts]}}

    for kind in kinds:
        if args.from_cache:
            print(f"=== Reparsing {kind} from cache ===", file=sys.stderr)
            listing = cache_listing(kind)
        else:
            print(f"=== Enumerating {kind} ===", file=sys.stderr)
            listing = enumerate_idx(session, kind)
        print(f"  {len(listing)} posts", file=sys.stderr)
        for i, it in enumerate(listing, 1):
            idx = int(it["idx"])
            try:
                html, cached = fetch_detail(session, kind, idx)
                if not cached:
                    (CACHE / f"{kind}_{idx}.html").write_text(html, encoding="utf-8")
            except Exception as e:
                print(f"  ! {kind} {idx}: {e}", file=sys.stderr)
                continue
            rows = extract_rows(html)
            if not rows:
                continue
            items = {}
            for r in rows:
                items.setdefault(r["item"], []).append(
                    {
                        "amount": r["amount"],
                        "source": r["source"],
                        "header": r["header"],
                        "row": r["row"],
                    }
                )
            posts_out.append(
                {
                    "kind": kind,
                    "idx": idx,
                    "date": (it.get("reg_date") or it.get("regdate") or "").strip(),
                    "subject": (it.get("subject") or "").strip(),
                    "url": BASE + CONFIGS[kind]["view"].format(idx),
                    "items": items,
                }
            )
            if i % 50 == 0:
                print(f"  scanned {i}/{len(listing)} {kind}", file=sys.stderr)

    posts_out.sort(key=lambda p: p["idx"], reverse=True)
    item_names = [n for n, _ in ITEMS]
    payload = {
        "source": "dmo.gameking.com NA PatchNote + EventView",
        "items_tracked": item_names,
        "total_posts": len(posts_out),
        "posts": posts_out,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"Matched posts: {len(posts_out)}  ->  {OUT.relative_to(PROJ)}")
    print("=" * 70)
    for p in posts_out:
        tag = ", ".join(f"{k}×{len(v)}" for k, v in p["items"].items())
        print(f"[{p['kind']}] {p['idx']}  {p['date']:<12} {tag}")
        print(f"   {p['subject'][:70]}")


if __name__ == "__main__":
    main()
