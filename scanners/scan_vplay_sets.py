"""Read vplay's clothing-set rosters -- which item belongs to which set.

Output: data/set_rosters.json

Why this exists: dmowiki's Clothing page lists set BONUSES but never says
which item is in which set. Its item tables carry only two set codes for nine
sets, written as templates -- "Yolei,T.K,Davis Head" is one row standing in
for three sets, "*:Spirit Helmet" for six. That is what blocks B05: without a
roster the optimizer cannot know a set is complete.

vplay publishes the roster outright, in Thai, as a two-column table:

    เซ็ท (set)          | รายการไอเทม (item list)
    พลังแห่งความกล้า     | ผ้าโพกหัวของไดสุเกะ
                        | กระเป๋าของไดสุเกะ ...

The set name sits in a cell that spans its items with rowspan, so the item
rows below it have ONE cell instead of two and inherit the set above -- the
same parallel-column trap the double-chipset reader hit, in a different shape.

A second layout appears on the Four Holy Beasts pages, where the header reads
"เช็ต | รายการเซ็ต | เอฟเฟกต์ เซ็ต 6" and a third column carries the 6-piece
bonus. Both are read here; the difference is only how many columns follow.

Not every set has a page: the element-spirit sets (dmowiki's "*:Spirit ...")
have no roster in the cache, so they stay unlinked and B05 stays partly open.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache_vplay"
OUT = PROJ / "data" / "set_rosters.json"

# Header words that mark a roster table. vplay spells "set" three ways across
# pages (เซ็ท / เซ็ต / เช็ต), so all three are accepted.
SET_WORDS = ("เซ็ท", "เซ็ต",
             "เช็ต")
ITEM_WORDS = ("รายการ",)  # รายการ

# "(ชิน)" marks the Shin/upgraded variant of an item. It is a different item
# with its own name, so it is kept and flagged rather than folded together.
SHIN = "(ชิน)"


def clean(x):
    x = re.sub(r"<br\s*/?>", "\n", x, flags=re.I)
    x = re.sub(r"<[^>]+>", " ", x)
    x = (x.replace("&nbsp;", " ").replace("&#160;", " ").replace("&amp;", "&")
          .replace("&#8211;", "-").replace("&#8217;", "'"))
    x = re.sub(r"[ \t]+", " ", x)
    return re.sub(r"\n\s*", "\n", x).strip()


def is_roster_header(cells):
    if len(cells) < 2:
        return False
    return (any(w in cells[0] for w in SET_WORDS)
            and any(w in cells[1] for w in ITEM_WORDS))


def parse_rosters(html):
    """Every roster table on one page -> {set name: [item, ...]}.

    The set name is the cell carrying rowspan; its items are the rows it
    spans. Counting cells instead does not work: the Four Holy Beasts layout
    has a third column whose bonus cells carry their own rowspan=2, so an
    item row there also has two cells and a count-based rule reads the item
    as a new set name.
    """
    out = {}
    for tb in re.findall(r"<table.*?</table>", html, re.S):
        rows = re.findall(r"<tr[^>]*>.*?</tr>", tb, re.S)
        if not rows:
            continue
        head = [clean(c) for c in
                re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], re.S)]
        if not is_roster_header(head):
            continue
        current = None
        for r in rows[1:]:
            cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", r, re.S)
            cells = [(a, clean(b)) for a, b in cells]
            cells = [(a, b) for a, b in cells if b]
            if not cells:
                continue
            attrs, text = cells[0]
            if re.search(r'rowspan\s*=\s*"?\d+', attrs, re.I):
                # Only a set name is ever both first in its row and spanning:
                # the bonus column's own rowspan cells sit last. So the first
                # cell alone decides, and no span counter is needed -- one was
                # tried and a mutant proved it never changed an outcome.
                current = text
                item_cells = cells[1:]
            else:
                item_cells = cells
            if not current:
                continue
            # the item is the first cell that is not the set name; any further
            # cell is the bonus column, which this file does not record
            if item_cells:
                for line in item_cells[0][1].split("\n"):
                    line = line.strip()
                    if line:
                        out.setdefault(current, []).append(line)
    return out


def main():
    if not CACHE.exists():
        print("missing %s" % CACHE.relative_to(PROJ))
        return 1

    merged = {}
    sources = {}
    for p in sorted(CACHE.glob("*.html")):
        html = p.read_text(encoding="utf-8", errors="replace")
        got = parse_rosters(html)
        for name, items in got.items():
            if name in merged and merged[name] != items:
                # Two pages listing the same set must agree; a mismatch means
                # one of them is a different revision and picking silently
                # would hide that.
                print("  WARN  %s: %s disagrees with %s"
                      % (name, p.name, sources.get(name)))
                continue
            merged.setdefault(name, items)
            sources.setdefault(name, p.name)

    sets = []
    for name, items in sorted(merged.items()):
        base = [i for i in items if not i.startswith(SHIN)]
        shin = [i for i in items if i.startswith(SHIN)]
        sets.append({
            "set": name,
            "items": base,
            "shin_items": shin,
            "pieces": len(base),
            "source": sources[name],
        })

    OUT.write_text(json.dumps({
        "fetched_at": date.today().isoformat(),
        "source": "cache_vplay",
        "note": ("which item belongs to which clothing set -- dmowiki does not "
                 "record this; the element-spirit sets are still missing"),
        "sets": sets,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print("wrote %s" % OUT.relative_to(PROJ))
    print("  sets %d" % len(sets))
    for s in sets:
        print("    %-24s %d items (+%d shin)  <- %s"
              % (s["set"], s["pieces"], len(s["shin_items"]), s["source"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
