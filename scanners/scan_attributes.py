"""Read the Equipment attributes tables off dmowiki.

Output: data/attribute_items.json

These are NOT part of the optimizer, and the wiki says why:

    "Analyzed attributes can be merged with equipment ... only a certain
     percentage of merged attribute stats is applied to TAMER stats - the
     percentage is determined by clothes stats"

Two independent reasons they stay out of the solve:
  1. they feed TAMER stats, and decision 02 scoped the optimizer to digimon
     stats only;
  2. the number in the table is not the number you get -- an unknown
     clothes-dependent fraction of it is.

The registry is still worth keeping: it records which slot each kind merges
into, the roll range, and the tamer level needed.

Two table shapes live on the page:
  * five per-kind tables (HP/DS/AP/DF/MS) -- one row per obtainable attribute,
    with a "Range" column holding the roll spread ("15~20", "1~2%")
  * one "Attribute Rank New" table -- pivoted, stats down the rows and
    Rank/Level across the columns, for the upgradable kind

Refresh cache/dmowiki_equipment_attributes.html the same way as the chipset
page -- see the docstring of scan_chipsets.py (headful Chrome over CDP).
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "cache" / "dmowiki_equipment_attributes.html"
OUT = PROJ / "data" / "attribute_items.json"

# Which equipment slot each kind merges into, per the prose above each table.
MERGES_INTO = {
    "HP": "Jacket", "DS": "Head accessories", "AP": "Gloves",
    "DF": "Pants", "MS": "Shoes",
}
STAT_ALIASES = {
    "max hp": "HP", "max ds": "DS", "attack": "AT", "defense": "DE",
    "hit rate": "HT", "critical": "CT", "evade": "EV", "block": "BL",
    "move speed": "MS",
}
PCT = {"CT", "EV", "BL", "MS"}


def clean(html):
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", txt).strip()


def cells(row):
    return [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def headings(html):
    return [(m.start(), clean(m.group(1)))
            for m in re.finditer(r'<span class="mw-headline"[^>]*>(.*?)</span>',
                                 html, re.S)]


def parse_range(text):
    """"15~20" -> (15.0, 20.0, False); "1~2%" -> (1.0, 2.0, True).

    Most rows separate the bounds with "~", but at least one ("Pyramid AT
    attribute", 168-280) uses a hyphen. An empty cell means the wiki has no
    value and yields nothing -- not a zero-width range.
    """
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[~-]\s*(\d+(?:\.\d+)?)\s*(%?)\s*$", text or "")
    if m:
        return float(m.group(1)), float(m.group(2)), bool(m.group(3))
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(%?)\s*$", text or "")
    if m:
        v = float(m.group(1))
        return v, v, bool(m.group(2))
    return None


def parse_attributes(html):
    """The five per-kind tables: one row per obtainable attribute."""
    heads = headings(html)
    out = []
    for m in re.finditer(r"<table.*?</table>", html, re.S):
        rows = re.findall(r"<tr[^>]*>.*?</tr>", m.group(0), re.S)
        if not rows:
            continue
        header = [h.lower() for h in cells(rows[0])]
        if "range" not in header or "name" not in header:
            continue
        prev = [h for p, h in heads if p < m.start()]
        section = prev[-1] if prev else ""
        kind = section.split()[0].upper() if section else ""
        if kind not in MERGES_INTO:
            continue
        idx = {k: header.index(k) for k in
               ("name", "class", "tamer level", "range") if k in header}
        for row in rows[1:]:
            c = cells(row)
            if len(c) < len(header):
                continue
            name = c[idx["name"]]
            if not name:
                continue
            rng = parse_range(c[idx["range"]]) if "range" in idx else None
            rec = {
                "name": name,
                "kind": kind,
                "merges_into": MERGES_INTO[kind],
                "class": c[idx["class"]] if "class" in idx else "",
            }
            lvl = c[idx["tamer level"]] if "tamer level" in idx else ""
            if re.fullmatch(r"\d+", lvl or ""):
                rec["tamer_level"] = int(lvl)
            if rng:
                lo, hi, pct = rng
                rec["roll"] = {"min": lo, "max": hi,
                               "unit": "pct" if pct else "flat"}
            out.append(rec)
    return out


def parse_rank_table(html):
    """The pivoted "Attribute Rank New" table: Rank/Level across the columns."""
    out = []
    for m in re.finditer(r"<table.*?</table>", html, re.S):
        rows = re.findall(r"<tr[^>]*>.*?</tr>", m.group(0), re.S)
        if not rows:
            continue
        header = cells(rows[0])
        if not header or header[0].lower() != "stats":
            continue
        cols = []
        for h in header[1:]:
            g = re.match(r"^Rank\s+(\w+)\s+Lv(\w+)$", h.strip())
            cols.append((g.group(1), g.group(2)) if g else None)
        if not any(cols):
            continue
        levels = {}
        for row in rows[1:]:
            c = cells(row)
            if len(c) < 2:
                continue
            stat = STAT_ALIASES.get(c[0].lower())
            if not stat:
                continue
            for col, raw in zip(cols, c[1:]):
                if col is None:
                    continue
                v = re.match(r"^\s*\+?\s*(\d+(?:\.\d+)?)\s*(%?)\s*$", raw or "")
                if not v:
                    continue
                rank, lvl = col
                key = "rank-%s-lv%s" % (rank.lower(), lvl.lower())
                rec = levels.setdefault(key, {
                    "id": key, "rank": rank, "level": lvl, "stats": []})
                rec["stats"].append({
                    "stat": stat,
                    "unit": "pct" if (v.group(2) or stat in PCT) else "flat",
                    "value": float(v.group(1)),
                })
        out.extend(levels[k] for k in levels)
    return out


def main():
    if not SRC.exists():
        print("missing %s -- see the module docstring" % SRC.relative_to(PROJ))
        return 1
    html = SRC.read_text(encoding="utf-8", errors="replace")
    attrs = parse_attributes(html)
    ranks = parse_rank_table(html)
    OUT.write_text(json.dumps({
        "fetched_at": date.today().isoformat(),
        "source": "dmowiki.com/Equipment_attributes",
        "note": ("feeds TAMER stats through a clothes-dependent fraction; "
                 "outside the optimizer's scope (decision 02)"),
        "attributes": attrs,
        "rank_levels": sorted(ranks, key=lambda r: r["id"]),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("wrote %s" % OUT.relative_to(PROJ))
    print("  attributes %d  rank levels %d" % (len(attrs), len(ranks)))
    noroll = [a for a in attrs if "roll" not in a]
    if noroll:
        print("  WARN  %d attribute(s) have no roll range -- the wiki leaves"
              % len(noroll))
        print("        the cell blank, so the spread is unknown, not zero:")
        for a in noroll:
            print("          %s (%s)" % (a["name"], a["kind"]))
    by = {}
    for a in attrs:
        by.setdefault(a["kind"], []).append(a)
    for k in sorted(by):
        rolled = [a for a in by[k] if "roll" in a]
        print("    %-3s %2d rows -> %-18s roll parsed %d/%d"
              % (k, len(by[k]), MERGES_INTO[k], len(rolled), len(by[k])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
