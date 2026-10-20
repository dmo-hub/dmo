"""Turn the scanned registry into the picker list the gear page loads.

    data/clothing_items.json  ->  docs/gear_registry.json

Decision 05 fixed the direction: data/ owns the facts, a builder writes what the
page fetches. The page never reads data/ directly.

What this has to reconcile:

  * The wiki groups items into 28 slots; the solver has 13. "Rings" -> "ring",
    the four "Spiral Key Ring (XX)" groups all -> "keyring", and several wiki
    groups (Old Avatar/Costume, DigiAura, XAI System) have no wearable slot at
    all and are dropped.
  * Most stats are RANGES ("HP 12~60"). The picker fills in the top of the
    range -- an upgraded piece is what a player actually wears, and it matches
    the "default to the maximum" rule for upgrade levels.
  * One item name can span several upgrade rows. They collapse to one entry
    holding the highest band, again per the maximum rule.
  * axis is carried through untouched. 257 rows still have none, and the page
    flags those rather than hiding them -- hiding an item a player owns is
    worse than showing it with a warning.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from stamped_json import write_stamped
from stat_units import PCT_STATS, js_round

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "data" / "clothing_items.json"
OUT = PROJ / "docs" / "gear_registry.json"
ICON_DIR = PROJ / "docs" / "img" / "gear"


def icon_filename(wiki_path):
    """/images/4/4a/Agumon_Bottom.png -> agumon_bottom.png. MediaWiki file
    names are unique per wiki, so the basename alone is a safe key."""
    base = unquote(wiki_path.rsplit("/", 1)[-1])
    return re.sub(r"[^a-z0-9._-]+", "_", base.lower())


def full_key(name):
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def icon_key(name):
    """Name with its level / duration tail dropped, so "Imperial Ring" from a
    stats table meets "Imperial Ring [15 Days]" from the list that has the
    picture."""
    name = re.sub(r"\s*\[[^\]]*\]\s*$", "", name)
    name = re.sub(r"\s*Lv\.?\s*[\d-]+$", "", name, flags=re.I)
    return full_key(name)


def stem_key(wiki_path):
    return icon_key(unquote(wiki_path.rsplit("/", 1)[-1]).rsplit(".", 1)[0])


def index_icons(items):
    """Every way a picture can be found again: the row's full name (keeps the
    level, whose picture can differ), the name without its tail, and the file
    name itself -- a pictureless "Earrings of Four Holy Beasts" table still
    has Earrings_of_Four_Holy_Beasts.png elsewhere on the page."""
    exact, loose = defaultdict(set), defaultdict(set)
    for it in items:
        p = it.get("icon")
        if not p:
            continue
        exact[full_key(it["name"])].add(p)
        loose[icon_key(it["name"])].add(p)
        loose[stem_key(p)].add(p)
    return exact, loose


# The stats tables and the list that carries the pictures spell some items
# differently: the list keeps the "Sealed" prefix the stats tables drop, and
# singular/plural flips. Spelled out per item -- a general "drop the s" rule
# would also join "Necklaces with 3 Options" to whatever "Necklace..." exists.
ICON_ALIAS = {
    "imperial earring": "imperial earrings",
    "zero unit earrings": "zero unit earring",
    "necklace of four holy beasts": "sealed necklace of four holy beasts",
    "ring of four holy beasts": "sealed ring of four holy beasts",
    "radiant necklace of four holy beasts": "sealed radiant necklace of four holy beasts",
    "radiant ring of four holy beasts": "sealed radiant ring of four holy beasts",
}


def icon_by_name(row_names, name, icons):
    """Picture for an item whose own rows had none (the pivoted stats tables).
    Several pictures under one name -- "Knight's Bracelet" also matches the
    Royal X- one -- are settled by the file name; a tie stays without one
    rather than showing the wrong item."""
    exact, loose = icons
    for n in row_names:
        found = exact.get(full_key(n)) or set()
        if len(found) == 1:
            return next(iter(found))
    key = icon_key(name)
    key = ICON_ALIAS.get(key, key)
    found = loose.get(key) or set()
    if len(found) == 1:
        return next(iter(found))
    named = [p for p in found if stem_key(p) == key]
    return named[0] if len(named) == 1 else None

# The wiki lists one row per slot for a group of in-game sets and draws every
# set's piece side by side in one picture. Each set becomes its own pick with
# its own cut-out icon; stats are per row on the wiki, so the sets share them.
#   "*:Spirit X"            "*" is the element, as in the wiki's "Fire : Spirit"
#                           set-effect rows; pictured in that same order
#                           (Agunimon, Lobomon, Kumamon, Kazemon, Beetlemon).
#   "Yolei,T.K,Davis X"     pictured Davis, T.K, Yolei -- NOT the name's order:
#                           the middle gloves are the Kaiser whip T.K's set
#                           lists, the left top is Davis's flame jacket.
# Each entry: (sets in picture order, left edge of each piece's frame, piece
# width, new name from (set, rest of the row's name)). The last Spirit piece
# is cut by the picture's edge.
SPLIT_SETS = {
    "*:Spirit ": (["Fire", "Light", "Ice", "Wind", "Thunder"],
                  [2, 40, 77, 116, 155], 34, lambda s, rest: f"{s}:Spirit {rest}"),
    "Yolei,T.K,Davis ": (["Davis", "T.K", "Yolei"],
                         [1, 43, 86], 34, lambda s, rest: f"{s} {rest}"),
}


def split_icon(src, box, tag):
    """Cut one piece out of a combined picture, saved next to it. Rewritten
    only when the bytes differ, so a rebuild leaves the files alone."""
    from io import BytesIO
    from PIL import Image
    im = Image.open(src)
    x, w = box
    tile = im.crop((x, 0, min(x + w, im.width), im.height))
    buf = BytesIO()
    tile.save(buf, "PNG", optimize=True)
    dst = src.with_name(f"{src.stem}-{tag}.png")
    if not dst.exists() or dst.read_bytes() != buf.getvalue():
        dst.write_bytes(buf.getvalue())
    return dst


def split_sets(rec):
    """One registry record, or one per set for a grouped row."""
    for prefix, (sets, xs, w, rename) in SPLIT_SETS.items():
        if not rec["name"].startswith(prefix):
            continue
        rest = rec["name"][len(prefix):]
        out = []
        for s, x in zip(sets, xs):
            tag = re.sub(r"[^a-z0-9]+", "", s.lower())
            r = dict(rec, id=f"{rec['id']}-{tag}", name=rename(s, rest))
            if rec.get("icon"):
                tile = split_icon(PROJ / "docs" / rec["icon"], (x, w), tag)
                r["icon"] = tile.relative_to(PROJ / "docs").as_posix()
            out.append(r)
        return out
    return [rec]


# Wiki slot -> solver slot id. Anything absent is not wearable gear for the
# optimizer and is left out; the counts are printed so a drop is never silent.
SLOT_MAP = {
    "Head": "head",
    "Top": "top",
    "Bottom": "bottom",
    "Gloves": "gloves",
    "Shoes": "shoes",
    "Fashion": "fashion",
    "Rings": "ring",
    "Necklaces": "necklace",
    "Bracelets": "bracelet",
    "Earrings": "earring",
    "Adventure Goggles": "glasses",
    "Digimon Kaiser´s Goggles": "glasses",
    "Tamer`s Goggles": "glasses",
    "Ghost Key Ring": "keyring",
    "Key Rings": "keyring",
    "Spiral Key Ring (DS)": "keyring",
    "Spiral Key Ring (JT)": "keyring",
    "Spiral Key Ring (ME)": "keyring",
    "Spiral Key Ring (WG)": "keyring",
}

# Stats the solver scores. Everything else (EXP, Skill DMG, Speed...) is kept
# on the record for display but never lands in a numeric field.
SOLVER_STATS = ["AT", "HT", "CT", "DS", "DE", "EV", "BL"]


def top_of(stat):
    """Highest value this stat can roll. Ranges give their max."""
    if stat.get("value") is not None:
        return float(stat["value"])
    hi = stat.get("max")
    if hi is not None:
        return float(hi)
    lo = stat.get("min")
    return float(lo) if lo is not None else None


# Some items carry the upgrade level in the NAME instead of the upgrade column
# ("Spiral Key Ring Lv.1", "Miracle Bracelet [Level 10]"). Those are one item
# with many levels, exactly like an upgrade band, and collapse the same way --
# 119 rows become 16 pickable items.
LEVEL_IN_NAME = re.compile(r"\s*(?:Lv\.?\s*(\d+)|\[Level\s*(\d+)\])\s*", re.I)


def split_level(name):
    """('Spiral Key Ring Lv.2') -> ('Spiral Key Ring', 2)."""
    m = LEVEL_IN_NAME.search(name)
    if not m:
        return name, None
    lvl = int(m.group(1) or m.group(2))
    return LEVEL_IN_NAME.sub(" ", name).strip().rstrip(",").strip(), lvl


def band_key(item):
    """Sort key that puts the highest upgrade band last."""
    if item.get("_name_level") is not None:
        return item["_name_level"]
    return (item.get("upgrade_max") if item.get("upgrade_max") is not None
            else item.get("upgrade") if item.get("upgrade") is not None else -1)


def main():
    items = json.loads(SRC.read_text(encoding="utf-8"))["items"]

    icons = index_icons(items)

    groups = defaultdict(list)
    dropped = defaultdict(int)
    for it in items:
        if not it.get("stats"):
            continue
        slot = SLOT_MAP.get(it.get("slot"))
        if not slot:
            dropped[it.get("slot")] += 1
            continue
        base, lvl = split_level(it["name"])
        if lvl is not None:
            it = dict(it, _name_level=lvl)
        groups[(slot, base)].append(it)

    out = []
    for (slot, name), rows in groups.items():
        rows.sort(key=band_key)
        best = rows[-1]                     # the maximum band, per the rule
        rec = {
            "id": best["id"],
            "name": name,
            "slot": slot,
            "wikiSlot": best.get("slot"),
            "axis": best.get("axis") or "unknown",
        }
        if best.get("upgrade") is not None:
            rec["upgrade"] = best["upgrade"]
            if best.get("upgrade_max") is not None:
                rec["upgradeMax"] = best["upgrade_max"]
        if len(rows) > 1:
            rec["bands"] = len(rows)
        if best.get("_name_level") is not None:
            rec["level"] = best["_name_level"]
        wiki_icon = (best.get("icon")
                     or next((r["icon"] for r in reversed(rows) if r.get("icon")), None)
                     or icon_by_name([r["name"] for r in reversed(rows)], name, icons))
        if wiki_icon:
            rec["iconWiki"] = wiki_icon
            # Only point the page at a picture fetch_dmowiki_images.py has
            # actually saved; a dangling path is a broken image on every row.
            local = ICON_DIR / icon_filename(wiki_icon)
            if local.exists():
                rec["icon"] = local.relative_to(PROJ / "docs").as_posix()

        ranged, other = False, []
        for st in best["stats"]:
            key = st.get("stat")
            top = top_of(st)
            if key in SOLVER_STATS and top is not None:
                rec[key] = rec.get(key, 0) + (top if key in PCT_STATS
                                              else js_round(top))
                if st.get("min") is not None and st.get("max") != st.get("min"):
                    ranged = True
            elif key and top is not None:
                other.append({"stat": key, "value": top,
                              "unit": st.get("unit", "flat")})
            elif st.get("random"):
                other.append({"stat": None, "random": True})
        if ranged:
            rec["ranged"] = True            # the page says these are top-of-roll
        if other:
            rec["extra"] = other
        out.extend(split_sets(rec))

    out.sort(key=lambda r: (r["slot"], r["name"]))
    payload = {
        "built_at": date.today().isoformat(),
        "source": "data/clothing_items.json",
        "note": ("stat values are the TOP of each roll range and the highest "
                 "upgrade band; axis 'unknown' means the wiki never said which "
                 "side the stat feeds"),
        "items": out,
    }
    write_stamped(OUT, payload, "built_at")

    by_slot = defaultdict(int)
    by_axis = defaultdict(int)
    for r in out:
        by_slot[r["slot"]] += 1
        by_axis[r["axis"]] += 1
    print("wrote %s" % OUT.relative_to(PROJ))
    print("  items %d in %d slots" % (len(out), len(by_slot)))
    print("  axis  %s" % dict(by_axis))
    print("  slots %s" % ", ".join("%s=%d" % kv for kv in sorted(by_slot.items())))
    if dropped:
        print("  dropped (no wearable slot):")
        for k, v in sorted(dropped.items(), key=lambda x: -x[1]):
            print("    %-28s %d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
