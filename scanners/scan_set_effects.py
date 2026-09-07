"""Read the set-effect table off the dmowiki Clothing page.

Output: data/set_effects.json

scan_clothing skips this table on purpose: every other table on the page is
one row per item, while this one is one row per SET, so feeding it through the
per-item path produced rows with no item and no slot. It gets its own reader
instead of a special case inside that one.

What the table looks like:

    Name                | Set-Number   | Chance | Operation     | Time | Effect Increase
    Yolei-Heart of Love | 4 Set-Effect | 100%   | None          | Perma| +40% SKill DMG, 4500 HP, ...
    Yolei-Heart of Love | 6 Set-Effect | 50%    | Digimon Skill | 10 Sec| 50% Skilldmg, 1000 HT, ...

Decision 06 settled that a proc effect counts at full value, so chance and
operation are carried for display only -- nothing here multiplies by them.
The permanent/proc split is read off `Chance`+`Operation`, NOT off the set
size: Davis-Power of Courage is a proc at both 4 and 6 pieces while every
other set's 4-piece row is permanent.

This file records the BONUSES only. It deliberately does not say which item
belongs to which set, because the wiki does not: the item tables carry two
set codes (DF, MDG) for nine sets, written as templates -- "*:Spirit Helmet"
stands for five element sets at once and "Yolei,T.K,Davis Head" for three
tamer sets. Until an item can be tied to one set, the optimizer cannot know a
set is complete, so it must not award these bonuses.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from scan_clothing import canon_stat, strip_tags  # noqa: E402

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "cache" / "dmowiki_clothing.html"
OUT = PROJ / "data" / "set_effects.json"

# Sets dmowiki never recorded live in their own hand-kept files and get merged
# into the output here. The merge belongs in the scanner rather than in the
# artifact: a rescan rebuilds every row, so a bonus pasted into the output by
# hand would be dropped on the next run -- and the validate gate re-runs this
# scanner precisely to prove the output is reproducible.
EXTRA_SOURCES = [PROJ / "data" / "last_evolution.json",
                 PROJ / "data" / "four_holy_beasts.json"]

# Terms this table uses that the per-item tables never do. Kept here rather
# than in scan_clothing's table so the item scanner's vocabulary stays the
# vocabulary of the item tables.
SET_ALIASES = {
    "ctdmg": "CT DMG",
    "ct-dmg": "CT DMG",
    "critdmg": "CT DMG",
    "atkspeed": "AS",
    "atk speed": "AS",
    "attackspeed": "AS",
    "final damage": "Final DMG",
    "received skill damage reduction": "Skill DMG Taken",
    "reduce skill dmg taken": "Skill DMG Taken",
    "skill dmg received": "Skill DMG Taken",
    "received damage reduction": "DMG Taken",
    "reduce dmg taken": "DMG Taken",
    "dmg taken": "DMG Taken",
}

# Stats the solver can score. The rest are recorded but flagged, so a reader
# can tell "we could not read this" from "we read it and it is not scoreable".
SOLVER_STATS = {"AT", "HT", "CT", "DS", "DE", "EV", "BL", "HP"}

# Stats where a positive number in the wiki means "take less" -- see the sign
# note in parse_effect.
REDUCTION_STATS = {"Skill DMG Taken", "DMG Taken"}

# "4500 HP" and "1000HT" both appear -- the space is not reliable, so it is
# optional. The stat side must start with a letter, which keeps a bare range
# like "1000-1250" from being read as a value plus a stat named "-1250".
VALUE_FIRST = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*(%?)\s*([A-Za-z].*?)\s*$"
)
VALUE_LAST = re.compile(
    r"^\s*(.*?)\s+([+-]?\d+(?:\.\d+)?)\s*(%?)\s*$"
)


def clean(html):
    # <br> is what actually separates effects in the multi-line cells;
    # the newline that happens to follow it in the source is not
    # load-bearing. Turn the tag itself into the separator so a source
    # reflow cannot merge two effects into one unreadable blob.
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    txt = strip_tags(html)
    txt = txt.replace("&nbsp;", " ").replace("&#160;", " ")
    txt = txt.replace("&amp;", "&")
    txt = re.sub(r"[ \t]+", " ", txt)
    return re.sub(r"\n\s*", "\n", txt).strip()


def canon(label):
    """Resolve a stat name, trying this table's extra terms first."""
    key = re.sub(r"[^a-z -]", "", label.lower()).strip()
    key = re.sub(r"\s+", " ", key)
    if key in SET_ALIASES:
        return SET_ALIASES[key]
    hit = canon_stat(label)
    if hit:
        return hit
    # "40% SKill DMG" style: the stat may trail extra words like "Received"
    squashed = key.replace(" ", "")
    return SET_ALIASES.get(squashed)


def parse_effect(part):
    """One sub-effect -> {stat, value, unit} or None.

    The cell mixes both orders in the same row -- "4500 HP" puts the value
    first, "Reduce DMG taken 30%" puts it last -- so both are tried. A minus
    on a damage-taken stat is kept: it is a reduction, and dropping the sign
    would turn a defensive bonus into an offensive one.
    """
    part = part.strip().strip(",").strip()
    if not part:
        return None
    for rx, order in ((VALUE_FIRST, "first"), (VALUE_LAST, "last")):
        m = rx.match(part)
        if not m:
            continue
        if order == "first":
            raw, pct, label = m.group(1), m.group(2), m.group(3)
        else:
            label, raw, pct = m.group(1), m.group(2), m.group(3)
        stat = canon(label)
        if not stat:
            continue
        value = float(raw)
        # The page writes the same reduction three ways: "-20% SKill DMG
        # Received", "Reduce DMG taken 30%", "Received Damage Reduction + 30%".
        # Only the first carries a sign, so without this the other two read as
        # an INCREASE in damage taken -- a defensive bonus flipped into its
        # opposite. Store every reduction as negative and let the sign mean
        # one thing.
        if stat in REDUCTION_STATS and value > 0:
            value = -value
        return {
            "stat": stat,
            "value": value,
            "unit": "pct" if pct else "flat",
            "scoreable": stat in SOLVER_STATS,
            "text": part,
        }
    return None


def split_effects(cell):
    """Sub-effects are comma separated, but a cell may also use newlines.

    Digimon Frontier packs five of them into one cell using line breaks, so
    splitting on commas alone reads that row as a single unparseable blob.
    """
    parts = re.split(r"[,\n]+", cell)
    return [p for p in (x.strip() for x in parts) if p]


def parse_sets(html):
    tables = re.findall(r"<table.*?</table>", html, re.S)
    for tb in tables:
        rows = re.findall(r"<tr[^>]*>.*?</tr>", tb, re.S)
        if not rows:
            continue
        header = [clean(h) for h in
                  re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], re.S)]
        if "Set-Number" not in header:
            continue
        idx = {h: i for i, h in enumerate(header)}
        out = []
        for r in rows[1:]:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
            if len(cells) < len(header):
                continue
            get = lambda k: clean(cells[idx[k]]) if k in idx else ""
            raw = get("Effect Increase")
            effects, unread = [], []
            for part in split_effects(raw):
                got = parse_effect(part)
                (effects if got else unread).append(got or part)
            chance = get("Chance Effect")
            operation = get("Operation")
            # Permanent means it is always on: a full-chance effect with no
            # trigger. Anything else fires on an event and lasts a while.
            permanent = chance.startswith("100") and operation.lower() in ("none", "")
            size = re.search(r"(\d+)", get("Set-Number"))
            out.append({
                "set": get("Name"),
                "pieces": int(size.group(1)) if size else None,
                "permanent": permanent,
                "chance": chance,
                "operation": operation,
                "effect_time": get("Effect-Time"),
                "effects": effects,
                "unreadable": unread,
                "raw": raw,
            })
        return out
    return []


def main():
    if not SRC.exists():
        print("missing %s" % SRC.relative_to(PROJ))
        return 1
    html = SRC.read_text(encoding="utf-8", errors="replace")
    sets = parse_sets(html)
    if not sets:
        print("no set-effect table found")
        return 1

    # Merge the hand-kept sets, in the same row shape the wiki path produces so
    # nothing downstream has to know which source a row came from -- except via
    # the "source" field, which is what keeps the provenance readable.
    extra_rows = 0
    for path in EXTRA_SOURCES:
        if not path.exists():
            print("  MISSING %s" % path.relative_to(PROJ))
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        for b in doc.get("bonuses") or []:
            effects = b.get("effects") or []
            sets.append({
                "set": b["set"],
                "pieces": b["pieces"],
                "permanent": b["permanent"],
                "chance": b.get("chance", ""),
                "operation": b.get("operation", ""),
                "effect_time": b.get("effect_time", "Perma" if b["permanent"] else ""),
                "effects": effects,
                "unreadable": [],
                "raw": ", ".join(e.get("text", "") for e in effects),
                "source": path.name,
            })
            extra_rows += 1

    total = sum(len(s["effects"]) + len(s["unreadable"]) for s in sets)
    read = sum(len(s["effects"]) for s in sets)
    scoreable = sum(1 for s in sets for e in s["effects"] if e["scoreable"])

    OUT.write_text(json.dumps({
        "fetched_at": date.today().isoformat(),
        "source": ", ".join(["cache/dmowiki_clothing.html"]
                            + [str(p.relative_to(PROJ)).replace("\\", "/")
                               for p in EXTRA_SOURCES if p.exists()]),
        "note": ("set bonuses only. Most rows are read off the dmowiki table; "
                 "rows carrying a \"source\" field come from a hand-kept file "
                 "for a set dmowiki never recorded. Which item belongs to "
                 "which set is not here -- that join lives in "
                 "data/set_rosters.json"),
        "sub_effects": {"total": total, "read": read, "scoreable": scoreable},
        "sets": sets,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print("wrote %s" % OUT.relative_to(PROJ))
    print("  set rows %d  (permanent %d / proc %d)  merged from files %d"
          % (len(sets), sum(1 for s in sets if s["permanent"]),
             sum(1 for s in sets if not s["permanent"]), extra_rows))
    print("  sub-effects %d  read %d  unreadable %d  scoreable %d"
          % (total, read, total - read, scoreable))
    for s in sets:
        mark = "perma" if s["permanent"] else "proc "
        print("    %-24s %s-set %s  read %d/%d"
              % (s["set"], s["pieces"], mark,
                 len(s["effects"]), len(s["effects"]) + len(s["unreadable"])))
        for u in s["unreadable"]:
            print("        UNREAD %r" % u)
    return 0


if __name__ == "__main__":
    sys.exit(main())
