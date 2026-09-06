"""Parse the cached dmowiki Clothing page into data/clothing_items.json (offline).

Reads cache/dmowiki_clothing.html and emits one record per wearable item:

  {
    "source": {"site", "page", "oldid", "tables", "rows"},
    "items": [
      {"id", "name", "slot", "axis", "upgrade", "stats": [
          {"stat", "unit", "value"|"min"/"max", "random"}]},
      ...
    ],
    "skipped": [ {"table", "heading", "rows", "reason"} ]
  }

Three parsers, because the page has three table shapes and one schema will not
fit them (see the notes on each below): row-wise, pivoted, and gallery.

Every one of the page's <tr> lands in exactly one bucket and the totals are
asserted, so a row can never disappear quietly -- rows the parsers cannot read
are reported in "skipped" with a reason rather than dropped.
"""

import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache" / "dmowiki_clothing.html"
OUT = PROJ / "data" / "clothing_items.json"

# Stat vocabulary, resolved in ticket 01. HT is hit rate, NOT hit points -- the
# game shows HP and HT as separate stats, so they must never be merged.
FLAT = ["HP", "DS", "AT", "HT", "DE", "Skill DMG"]
PCT = ["CT", "BL", "EV", "EXP"]
DECIMAL = ["AS"]

# Wiki spellings -> canonical key.
STAT_ALIASES = {
    "max hp": "HP", "hp": "HP",
    "max ds": "DS", "ds": "DS", "digi-soul": "DS",
    "attack": "AT", "at": "AT", "atk": "AT",
    "hit rate": "HT", "ht": "HT", "hit": "HT",
    "critical": "CT", "ct": "CT", "crit": "CT",
    "defense": "DE", "de": "DE", "def": "DE",
    "evade": "EV", "ev": "EV", "evasion": "EV",
    "block": "BL", "bl": "BL",
    "attack speed": "AS", "as": "AS",
    "exp": "EXP",
    "skill dmg": "Skill DMG", "skilldmg": "Skill DMG", "skill damage": "Skill DMG",
}

# Headings whose tables describe something other than a wearable item.
NON_ITEM_HEADINGS = {"Set-Effect´s", "Set-Effects", "Set Effect"}


def unit_for(stat):
    if stat in PCT:
        return "pct"
    if stat in DECIMAL:
        return "decimal"
    return "flat"


def strip_tags(html):
    return re.sub(r"<[^>]+>", " ", html)


def clean(html):
    txt = strip_tags(html)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", txt).strip()


def canon_stat(label):
    """Resolve a wiki stat label, ignoring any Tamer/Digimon prefix.

    The page writes "Digimon HP +12~60" wherever both axes appear in one table,
    so the prefix has to be stripped before the lookup -- otherwise every
    prefixed stat resolves to nothing and the row silently loses its numbers.
    """
    key = re.sub(r"[^a-z ]", "", label.lower()).strip()
    key = re.sub(r"^(?:tamer|digimon)\s+", "", key)
    return STAT_ALIASES.get(key)


def parse_stat_cell(text):
    """Pull every stat out of one cell.

    Five shapes appear on the page and each needs different handling:
      Attack +92                      single value
      Attack +133~152                 a range -- min/max, not one number
      Attack +200 / HP +1000          several stats in one cell
      Critical +4%                    percentage, must not be stored as flat 4
      Random bonus stat equivalent... no determinate value at all
    """
    out = []
    if not text:
        return out

    if re.search(r"\brandom\b", text, re.I):
        return [{"stat": None, "unit": None, "random": True, "text": text[:120]}]

    # "<label> +<n>[~<m>][%]" -- the sign is required, which keeps level ranges
    # like "Loader 1-4" from being read as a stat range.
    pattern = re.compile(
        r"([A-Za-z][A-Za-z .\-]*?)\s*\+\s*(\d+(?:\.\d+)?)(?:\s*~\s*\+?(\d+(?:\.\d+)?))?\s*(%?)"
    )
    for m in pattern.finditer(text):
        label = m.group(1)
        stat = canon_stat(label)
        if not stat:
            continue
        lo, hi, pct = m.group(2), m.group(3), m.group(4)
        unit = "pct" if pct else unit_for(stat)
        rec = {"stat": stat, "unit": unit, "random": False}
        # The prefix belongs to this stat, not to the row: one Key Ring line can
        # grant Digimon HP and Tamer Attack together.
        pre = re.match(r"\s*(tamer|digimon)", label.lower())
        if pre:
            rec["axis"] = pre.group(1)
        if hi is not None:
            rec["min"] = float(lo)
            rec["max"] = float(hi)
        else:
            rec["value"] = float(lo)
        out.append(rec)
    return out


def axis_for(text, heading):
    """digimon | tamer -- from the text prefix, never guessed from the slot.

    Ticket 01 established that slot is not a safe proxy: the Spiral Key Ring
    grants digimon stats while other key rings grant tamer stats. Only the
    explicit prefix decides, and a row with neither is reported, not defaulted.
    """
    if re.search(r"\btamer\b", text, re.I):
        return "tamer"
    if re.search(r"\bdigimon\b", text, re.I):
        return "digimon"
    return None


def split_rows(table_html):
    return re.findall(r"<tr.*?</tr>", table_html, flags=re.S)


def split_cells(row_html):
    return re.findall(r"<t[hd][^>]*>.*?</t[hd]>", row_html, flags=re.S)


def header_labels(row_html):
    return [clean(c) for c in re.findall(r"<th[^>]*>.*?</th>", row_html, flags=re.S)]


def build_heading_map(html):
    """Map each table's document position to the h1/h2/h3 path above it.

    Most tables carry no slot column, so the heading is where the slot comes
    from. Returns a lookup keyed by document offset rather than a list: indexing
    a parallel list by table number silently desyncs, because "<table" openings
    and "<table>...</table>" pairs disagree wherever a table is nested.
    """
    heads = []
    for m in re.finditer(r"<h([1-3])[^>]*>(.*?)</h\1>", html, flags=re.S):
        level = int(m.group(1))
        text = clean(m.group(2))
        if text and text != "Contents":
            heads.append((m.start(), level, text))

    def path_at(pos):
        path = {}
        for hpos, level, text in heads:
            if hpos < pos:
                path[level] = text
                for deeper in (2, 3):
                    if deeper > level:
                        path.pop(deeper, None)
            else:
                break
        return path

    return path_at


def slot_from(path):
    """Deepest heading wins -- 'Armor parts > Head' means the Head slot."""
    for level in (3, 2, 1):
        if level in path:
            return path[level]
    return None


def mk_id(name, slot, seen):
    base = re.sub(r"[^a-z0-9]+", "-", ("%s-%s" % (slot or "x", name)).lower()).strip("-")
    cand, n = base, 1
    while cand in seen:
        n += 1
        cand = "%s-%d" % (base, n)
    seen.add(cand)
    return cand


def parse_rowwise(rows, path, seen, stats_cols, name_col, upgrade_col):
    """Tables with a Name column: one item per row."""
    items, unread = [], 0
    for row in rows[1:]:
        cells = split_cells(row)
        if not cells:
            unread += 1
            continue
        texts = [clean(c) for c in cells]
        name = texts[name_col] if name_col < len(texts) else ""
        if not name:
            unread += 1
            continue

        blob = " ".join(texts[c] for c in stats_cols if c < len(texts))
        stats = parse_stat_cell(blob)
        # A named row with no numbers is a real item that simply grants no stat
        # (cosmetics, and the option-slot tables). It belongs in the registry;
        # only rows we could not READ are failures, so the two are kept apart.
        slot = slot_from(path)
        axes_seen = {st.get("axis") for st in stats if st.get("axis")}
        if len(axes_seen) == 1:
            row_axis = axes_seen.pop()
        elif len(axes_seen) > 1:
            row_axis = "mixed"      # per-stat axis is authoritative in this case
        else:
            row_axis = axis_for(blob, slot) or "unknown"
        rec = {
            "id": mk_id(name, slot, seen),
            "name": name,
            "slot": slot,
            "axis": row_axis,
            "stats": stats,
        }
        if upgrade_col is not None and upgrade_col < len(texts):
            up = re.search(r"\d+", texts[upgrade_col])
            if up:
                rec["upgrade"] = int(up.group(0))
        items.append(rec)
    return items, unread


def parse_pivot(rows, path, seen):
    """Transposed tables: item names are column headers, stats are row labels."""
    header = header_labels(rows[0])
    if len(header) < 2:
        return [], len(rows)
    names = header[1:]
    columns = {n: [] for n in names}

    unread = 0
    for row in rows[1:]:
        cells = [clean(c) for c in split_cells(row)]
        if len(cells) < 2:
            unread += 1
            continue
        stat = canon_stat(cells[0])
        if not stat:
            unread += 1
            continue
        for i, name in enumerate(names):
            if i + 1 >= len(cells):
                continue
            parsed = parse_stat_cell("%s %s" % (cells[0], cells[i + 1]))
            columns[name].extend(parsed)

    slot = slot_from(path)
    items = []
    for name in names:
        if not columns[name]:
            continue
        items.append({
            "id": mk_id(name, slot, seen),
            "name": name,
            "slot": slot,
            # Pivot tables never carry a Tamer/Digimon prefix, so the axis is
            # genuinely unknown here rather than assumed.
            "axis": "unknown",
            "stats": columns[name],
        })
    return items, unread


def main():
    html = io.open(CACHE, encoding="utf-8", errors="replace").read()

    oldid = re.search(r"oldid=(\d+)", html)
    tables = [(m.start(), m.group(0))
              for m in re.finditer(r"<table.*?</table>", html, flags=re.S)]
    path_at = build_heading_map(html)
    total_rows = len(re.findall(r"<tr", html))

    items, skipped = [], []
    seen_ids = set()
    counted = 0

    for idx, (pos, table) in enumerate(tables):
        path = path_at(pos)
        heading = slot_from(path)
        rows = split_rows(table)
        # Count <tr> openings, not matched pairs: table 6 wraps the Spiral Key
        # Ring tables, and the inner table's </tr> closes the outer row first,
        # so pairing loses exactly one row against the page total.
        counted += len(re.findall(r"<tr", table))

        if not rows:
            skipped.append({"table": idx, "heading": heading, "rows": 0,
                            "reason": "no rows"})
            continue

        header = header_labels(rows[0])

        if heading in NON_ITEM_HEADINGS:
            skipped.append({"table": idx, "heading": heading, "rows": len(rows),
                            "reason": "set-effect procs, not per-item stats"})
            continue

        if not header:
            skipped.append({"table": idx, "heading": heading, "rows": len(rows),
                            "reason": "image gallery, no header row"})
            continue

        lower = [h.lower() for h in header]
        if "name" in lower:
            name_col = lower.index("name")
            stats_cols = [i for i, h in enumerate(lower)
                          if "stat" in h or "effect" in h or canon_stat(header[i])]
            # No stat column at all still lists items (the "Number of Options"
            # tables); record them with an empty stat list rather than dropping
            # the names on the floor.
            upgrade_col = lower.index("upgrade") if "upgrade" in lower else None
            got, unread = parse_rowwise(rows, path, seen_ids, stats_cols,
                                        name_col, upgrade_col)
        elif header[0] == "" or canon_stat(header[0]) or header[0].lower() == "stats":
            got, unread = parse_pivot(rows, path, seen_ids)
        else:
            skipped.append({"table": idx, "heading": heading, "rows": len(rows),
                            "reason": "unrecognised header: %s" % " | ".join(header[:5])})
            continue

        items.extend(got)
        if unread:
            skipped.append({"table": idx, "heading": heading, "rows": unread,
                            "reason": "rows without a readable name or stat"})

    assert counted == total_rows, "row accounting: walked %d of %d" % (counted, total_rows)
    # "unknown" is deliberate. Ticket 01 showed slot cannot imply axis (the
    # Spiral Key Ring grants digimon stats while other key rings grant tamer),
    # and this page proves it again: Bottom holds tamer items AND items whose
    # axis is never stated. Defaulting those to digimon would put tamer-scale
    # numbers (~10x smaller) into the optimizer with nothing to flag it, so the
    # gap is recorded instead of filled in.
    assert all(i["axis"] in ("digimon", "tamer", "mixed", "unknown")
               for i in items), "bad axis"

    payload = {
        "source": {
            "site": "dmowiki.com",
            "page": "Clothing",
            "oldid": int(oldid.group(1)) if oldid else None,
            "tables": len(tables),
            "rows": total_rows,
        },
        "items": sorted(items, key=lambda i: i["id"]),
        "skipped": skipped,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with_stats = sum(1 for i in items if i["stats"])
    by_slot = Counter(i["slot"] for i in items)
    by_axis = Counter(i["axis"] for i in items)
    unknown_with_stats = sum(1 for i in items if i["stats"] and i["axis"] == "unknown")
    print("wrote %s" % OUT.relative_to(PROJ))
    print("  tables %d  rows %d" % (len(tables), total_rows))
    print("  items  %d  (%d carry stats, %d are stat-less)"
          % (len(items), with_stats, len(items) - with_stats))
    print("  axis   %s" % dict(by_axis))
    if unknown_with_stats:
        print("  WARN   %d items carry stats but no stated axis -- the optimizer"
              % unknown_with_stats)
        print("         must not score these until the axis is resolved")
    print("  skipped tables/rows: %d entries" % len(skipped))
    print("  slots: %s" % ", ".join("%s=%d" % (k, v) for k, v in by_slot.most_common(8)))


if __name__ == "__main__":
    main()
