"""Pull every "new deck" out of the cached TH patch posts (offline).

    cache/th_view_*.html  ->  data/th_patch_decks.json
      { "decks": [ { "name", "url", "date", "digimon": [...],
                     "effects": [[stat, chance, effect], ...] } ] }

A deck section is a "เพิ่มเด็คใหม่" heading followed by pairs of tables: a
one-column digimon list, then a three-column buff table. One heading can carry
several pairs (post 61 adds three decks under one "เพิ่มเด็คใหม่").
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builders"))
from scan_th_patch_dungeons import blocks  # noqa: E402
from scan_th_patch_digimon import parse_thai_date, html_to_text  # noqa: E402
from stamped_json import write_stamped  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
OUT = PROJ / "data" / "th_patch_decks.json"

DECK_HEADING_RE = re.compile(r"^(?:\d+\s*\.\s*)?เพิ่มเด็คใหม่\s*(?:[:：–-]\s*(.*))?$")
LIST_TITLE_RE = re.compile(r"^(?:รายชื่อดิจิมอน|รายการดิจิมอน(?:เด็คใหม่)?)\s*(?:[–-]\s*(.*))?$")


def deck_heading(b):
    if b["kind"] != "text" or not b.get("strong") or len(b["text"]) > 120:
        return None
    m = DECK_HEADING_RE.match(re.sub(r"\s+", " ", b["text"]).strip())
    return (m.group(1) or "").strip() if m else None


def deck_section_end(bl, start):
    """Next heading in the deck heading's own colour. Sub-headings naming each
    deck under one "เพิ่มเด็คใหม่" are coloured differently, so they stay in."""
    color = bl[start].get("color")
    listed = {n.strip() for n in (deck_heading(bl[start]) or "").split(",") if n.strip()}
    for j in range(start + 1, len(bl)):
        b = bl[j]
        # Post 94 colours its last sub-heading like the heading itself; a bold
        # line that is exactly one of the deck names the heading lists is
        # still one of its decks, not the next section.
        if b["kind"] == "text" and b.get("strong") and b["text"].strip() in listed:
            continue
        if b["kind"] == "text" and b.get("strong") and len(b["text"]) < 120:
            if (color not in (None, "black") and b.get("color") == color) or deck_heading(b) is not None:
                return j
    return len(bl)


def decks_in(section, heading_name):
    out, pending, sub = [], None, None
    for b in section:
        if b["kind"] == "text":
            if b.get("strong") and b.get("color") not in (None, "black", "vivid-red") and len(b["text"]) < 120:
                sub = re.sub(r"^เด็คใหม่\s*[–-]\s*", "", b["text"].strip())
            continue
        rows = b["rows"]
        if all(len(r) == 1 for r in rows):
            title = rows[0][0]
            m = LIST_TITLE_RE.match(title)
            from_table = (m.group(1) or "").strip() if m else title
            # A sub-heading or the heading names the deck; the table title is
            # the fallback because it gets copy-pasted (post 90's third deck
            # repeats the second deck's title).
            pending = {"name": sub or heading_name or from_table,
                       "digimon": [r[0] for r in rows[1:] if r[0]]}
            sub = None
        elif pending and len(rows[0]) >= 2:
            # Some buff tables drop the chance column (stat | effect).
            pending["effects"] = [(r[:3] if len(r) >= 3 else [r[0], None, r[-1]])
                                  for r in rows[1:] if len(r) >= 2]
            out.append(pending)
            pending = None
    return out


def main():
    files = sorted(CACHE.glob("th_view_*.html"))
    if not files:
        sys.exit("no cache/th_view_*.html -- run scanners/scan_th_patch_digimon.py first; "
                 "%s left untouched" % OUT.relative_to(PROJ))
    found = {}
    for f in files:
        raw = f.read_text(encoding="utf-8")
        canon = re.search(r'<link rel="canonical" href="([^"]+)"', raw)
        url = canon.group(1) if canon else "https://www.vplay.in.th/%s/" % f.stem[len("th_view_"):]
        bl = blocks(raw)
        when = parse_thai_date(html_to_text(raw))
        for i, b in enumerate(bl):
            name = deck_heading(b)
            if name is None:
                continue
            for d in decks_in(bl[i + 1:deck_section_end(bl, i)], name):
                d.update(url=url, date=when)
                key = re.sub(r"\W+", "", d["name"]) + "|" + "|".join(d["digimon"])
                # the same post can be cached under an alias slug too
                if key not in found or len(url) > len(found[key]["url"]):
                    found[key] = d
    out = sorted(found.values(), key=lambda d: d["date"] or "")
    write_stamped(OUT, {"fetched_at": date.today().isoformat(), "scanned": len(files),
                        "decks": out}, "fetched_at")
    print("wrote %s: %d decks" % (OUT.relative_to(PROJ), len(out)))
    for d in out:
        print("  %s  %-40s mons=%d eff=%d" % (d["date"], d["name"][:40], len(d["digimon"]), len(d.get("effects", []))))


if __name__ == "__main__":
    main()
