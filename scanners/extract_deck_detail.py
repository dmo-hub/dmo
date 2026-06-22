"""Extract Digimon List + Effect tables for given idx from cached HTML.

Usage: python extract_deck_detail.py event 635 770 patch 4148 ...
"""

import io
import re
import sys
from html import unescape
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"


def find_deck_sections(html):
    """Find each deck section: name + Digimon List table + Effect table."""
    # Normalize entities except for table structure
    norm = html.replace("&nbsp;", " ").replace("–", "-").replace("—", "-")

    # Find each [<DeckName>] Digimon List heading (in raw HTML, may have inline tags)
    decks = []
    for m in re.finditer(
        r"\[\s*([^\]<>]{3,90}?)\s*\]\s*(?:</[^>]+>\s*)*Digimon\s*List",
        re.sub(r"<[^>]+>", "", norm),
        re.IGNORECASE,
    ):
        decks.append(m.group(1).strip(" -:_"))

    # Dedupe while preserving order
    seen, dedupe = set(), []
    for d in decks:
        if d not in seen:
            seen.add(d)
            dedupe.append(d)
    return dedupe


def extract_text_table(html, deck_name, kind):
    """Find the table that follows '[deck_name] kind' heading. kind: 'Digimon List' or 'Effect'.

    Returns list of rows (each row = list of cell strings) or None.
    """
    # Find heading text (escape regex special chars in deck_name)
    esc = re.escape(deck_name)
    # The heading appears as plain text like '[Name] Digimon List' but may be
    # split across HTML tags. We strip tags from a window then locate it.
    stripped = re.sub(r"<[^>]+>", " ", html.replace("&nbsp;", " "))
    stripped = re.sub(r"\s+", " ", stripped)
    pat = re.compile(rf"\[\s*{esc}\s*\]\s*{kind}", re.IGNORECASE)
    sm = pat.search(stripped)
    if not sm:
        return None
    # Now find the offset back in the original HTML. Use the deck_name + kind
    # appearing in order in raw HTML (allow tags between).
    # Search a more forgiving pattern in raw html:
    raw_pat = re.compile(
        rf"\[\s*{esc}\s*\][\s\S]{{0,400}}?{re.escape(kind)}",
        re.IGNORECASE,
    )
    rm = raw_pat.search(html.replace("&nbsp;", " "))
    if not rm:
        return None
    # The next <table>...</table> after this is the table
    rest = html[rm.end() :]
    tm = re.search(r"<table[^>]*>([\s\S]*?)</table>", rest, re.IGNORECASE)
    if not tm:
        return None
    table_html = tm.group(1)
    rows = []
    for trm in re.finditer(r"<tr[^>]*>([\s\S]*?)</tr>", table_html, re.IGNORECASE):
        row_html = trm.group(1)
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row_html, re.IGNORECASE)
        cleaned = []
        for c in cells:
            t = re.sub(r"<[^>]+>", "", c)
            t = unescape(t).replace("\xa0", " ").strip()
            t = re.sub(r"\s+", " ", t)
            cleaned.append(t)
        if cleaned:
            rows.append(cleaned)
    return rows


def get_post_date(html):
    m = re.search(r">\s*(\d{2}-\d{2}-\d{4})\s*<", html)
    return m.group(1) if m else ""


def main(targets):
    # targets is list of (kind, idx) tuples
    for kind, idx in targets:
        f = CACHE / f"{kind}_{idx}.html"
        if not f.exists():
            print(f"\n=== {kind} {idx} === MISSING CACHE")
            continue
        html = f.read_text(encoding="utf-8", errors="ignore")
        date = get_post_date(html)
        print(f"\n=== {kind} idx {idx} (date {date}) ===")
        decks = find_deck_sections(html)
        print(f"  Decks: {decks}")
        for d in decks:
            digi = extract_text_table(html, d, "Digimon List")
            eff = extract_text_table(html, d, "Effect")
            print(f"\n  [{d}]")
            print("  Digimon List:")
            if digi:
                for row in digi:
                    print(f"    {row}")
            else:
                print("    (not found)")
            print("  Effect:")
            if eff:
                for row in eff:
                    print(f"    {row}")
            else:
                print("    (not found)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python extract_deck_detail.py <kind> <idx> [<kind> <idx>...]")
        sys.exit(1)
    targets = []
    cur_kind = None
    for a in args:
        if a in ("event", "patch"):
            cur_kind = a
        else:
            try:
                targets.append((cur_kind or "event", int(a)))
            except ValueError:
                print(f"skip: {a}")
    main(targets)
