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

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "data" / "clothing_items.json"
OUT = PROJ / "docs" / "gear_registry.json"

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

        ranged, other = False, []
        for st in best["stats"]:
            key = st.get("stat")
            top = top_of(st)
            if key in SOLVER_STATS and top is not None:
                rec[key] = rec.get(key, 0) + (top if key in ("CT", "EV", "BL")
                                              else round(top))
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
        out.append(rec)

    out.sort(key=lambda r: (r["slot"], r["name"]))
    payload = {
        "built_at": date.today().isoformat(),
        "source": "data/clothing_items.json",
        "note": ("stat values are the TOP of each roll range and the highest "
                 "upgrade band; axis 'unknown' means the wiki never said which "
                 "side the stat feeds"),
        "items": out,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")

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
