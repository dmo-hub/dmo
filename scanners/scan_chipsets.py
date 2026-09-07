"""Read the chipset stat tables off dmowiki's ChipSets page.

Output: data/chip_items.json
  {
    "fetched_at": "YYYY-MM-DD",
    "source": "dmowiki.com/ChipSets",
    "items": [
      {"id": "chip-family-r1", "name": "Family ChipSet R1", "kind": "family",
       "grade": 1, "stats": [{"stat": "HP", "unit": "flat", "value": 135.0}, ...]}
    ]
  }

Shape: the tables are PIVOTED -- stats run down the rows and the GRADE runs
across the columns (R1..R18). One column is therefore one chip, not one item
with many stats, which is the reverse of scan_clothing's pivot handling.

Two kinds sit on the page with identical headers:
  * "Family"     -- higher numbers, usable only within one digimon family
  * "All Family" -- lower numbers, usable anywhere
They are told apart by the images that precede each table (CT_Chip_All.png and
friends), because no heading text separates them.

The page is behind Cloudflare: a headless fetch returns "Just a moment...".
Refresh cache/dmowiki_chipsets.html with a HEADFUL Chrome over CDP -- no CAPTCHA
click was needed as of 2026-09-07, the challenge clears on its own:
    chrome.exe --remote-debugging-port=9343 --user-data-dir=<temp> \
               https://dmowiki.com/ChipSets
then save document.documentElement.outerHTML.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "cache" / "dmowiki_chipsets.html"
OUT = PROJ / "data" / "chip_items.json"

STAT_ALIASES = {
    "max hp": "HP", "max ds": "DS", "attack": "AT", "defense": "DE",
    "hit rate": "HT", "critical": "CT", "evade": "EV", "block": "BL",
}
PCT = {"CT", "EV", "BL"}
# The image filenames that mark the all-family tables.
ALL_FAMILY_MARK = re.compile(r"_All\.png|_Chip_All", re.I)


def clean(html):
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", txt).strip()


def cells(row):
    return [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def parse_value(text):
    """"+135" -> (135.0, False); "+0.25%" -> (0.25, True); "-" -> None.

    The wiki writes "+?" where nobody has measured the value yet (R15 of both
    kinds, R16 of the all-family one). Those cells yield nothing rather than a
    zero -- a chip that grants 0 HP and one whose HP is unknown must not look
    the same to the optimizer.
    """
    m = re.match(r"^\s*\+?\s*(\d+(?:\.\d+)?)\s*(%?)\s*$", text or "")
    if not m:
        return None
    return float(m.group(1)), bool(m.group(2))


def kind_for(html_before):
    """Family vs all-family, decided by the images just above the table."""
    imgs = re.findall(r"<img[^>]*>", html_before)[-6:]
    return "all" if any(ALL_FAMILY_MARK.search(i) for i in imgs) else "family"


def parse_chipsets(html):
    items = {}
    for m in re.finditer(r"<table.*?</table>", html, re.S):
        table = m.group(0)
        rows = re.findall(r"<tr[^>]*>.*?</tr>", table, re.S)
        if not rows:
            continue
        header = cells(rows[0])
        if not header or header[0].lower() != "stats":
            continue
        grades = []
        for h in header[1:]:
            g = re.match(r"^R(\d+)$", h.strip())
            grades.append(int(g.group(1)) if g else None)
        if not any(g is not None for g in grades):
            continue
        kind = kind_for(html[max(0, m.start() - 1500):m.start()])
        for row in rows[1:]:
            c = cells(row)
            if len(c) < 2:
                continue
            stat = STAT_ALIASES.get(c[0].lower())
            if not stat:
                continue
            for grade, raw in zip(grades, c[1:]):
                if grade is None:
                    continue
                got = parse_value(raw)
                if got is None:
                    continue
                value, pct = got
                key = (kind, grade)
                rec = items.setdefault(key, {
                    "id": "chip-%s-r%d" % (kind, grade),
                    "name": ("All Family ChipSet R%d" if kind == "all"
                             else "Family ChipSet R%d") % grade,
                    "kind": kind,
                    "grade": grade,
                    # The vplay post for the double chipsets states the stats
                    # are "สำหรับค่าคุณลักษณะดิจิมอน"
                    # -- for the DIGIMON's attributes. Same system, same axis.
                    "axis": "digimon",
                    "stats": [],
                })
                # A stat can appear in two tables of the same kind (R1-R18 and
                # the R16-R18 "double" table). Same value both times, so the
                # first write wins and the repeat is dropped.
                if any(s["stat"] == stat for s in rec["stats"]):
                    continue
                rec["stats"].append({
                    "stat": stat,
                    "unit": "pct" if (pct or stat in PCT) else "flat",
                    "value": value,
                })
    return [items[k] for k in sorted(items, key=lambda k: (k[0], k[1]))]


def main():
    if not SRC.exists():
        print("missing %s -- see the module docstring for how to refresh it" %
              SRC.relative_to(PROJ))
        return 1
    html = SRC.read_text(encoding="utf-8", errors="replace")
    items = parse_chipsets(html)
    OUT.write_text(json.dumps(
        {"fetched_at": date.today().isoformat(),
         "source": "dmowiki.com/ChipSets",
         "items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print("wrote %s" % OUT.relative_to(PROJ))
    by_kind = {}
    for it in items:
        by_kind.setdefault(it["kind"], []).append(it)
    print("  chips %d" % len(items))
    full = max((len(i["stats"]) for i in items), default=0)
    short = [i for i in items if len(i["stats"]) < full]
    if short:
        print("  WARN  %d chips carry fewer than %d stats -- the wiki writes"
              % (len(short), full))
        print("        \"+?\" for values nobody has measured yet:")
        for i in short:
            have = {s["stat"] for s in i["stats"]}
            print("          %-24s missing %s"
                  % (i["id"], ", ".join(sorted(
                      {"HP", "DS", "AT", "DE", "HT", "CT", "EV"} - have))))
    for kind, group in sorted(by_kind.items()):
        grades = [g["grade"] for g in group]
        print("    %-8s %2d chips  R%d-R%d  stats/chip %s"
              % (kind, len(group), min(grades), max(grades),
                 sorted({len(g["stats"]) for g in group})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
