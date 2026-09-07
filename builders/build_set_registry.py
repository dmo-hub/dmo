"""Join the Thai set rosters to the English item registry.

    data/set_rosters.json  +  data/set_effects.json  ->  docs/set_registry.json

The two sources describe the same sets from opposite ends and neither is
usable alone:

  * vplay (Thai) says WHICH ITEM is in which set, per slot.
  * dmowiki (English) carries the STATS, but writes one template row per
    group -- "Yolei,T.K,Davis Head" is a single row standing in for three
    sets' head pieces, all of which share the same numbers.

So the join key is (set, slot), not the item name: the Thai side names the
real item, the English template supplies the stats for that slot, and the set
bonus comes from data/set_effects.json.

Shin variants: a "(ชิน)" item is the upgraded version of the SAME slot -- the
roster pairs them 1:1 -- and the player may mix them freely with base pieces;
the set bonus counts either. A set is therefore complete when its six SLOTS
are filled, not when six items from a twelve-item pool are worn. Modelling it
by slot also makes the impossible case impossible: base-head and shin-head
cannot both count, because they are one slot.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
ROSTERS = PROJ / "data" / "set_rosters.json"
EFFECTS = PROJ / "data" / "set_effects.json"
REGISTRY = PROJ / "docs" / "gear_registry.json"
OUT = PROJ / "docs" / "set_registry.json"

SHIN = "(ชิน)"

# The Thai set names as vplay writes them, against dmowiki's English names in
# the bonus table. Only these three overlap: vplay also documents two sets
# dmowiki never recorded, and dmowiki's element-spirit sets have not been
# released in the Thai client, so they have no roster at all.
SET_NAMES = {
    "พลังแห่งความกล้า": "Davis-Power of Courage",
    "แสงแห่งความหวัง": "T.K-Light of Hope",
    "จิตใจแห่งรัก": "Yolei-Heart of Love",
}

# vplay's slot words, in roster order, against the solver's slot ids. The
# roster lists one item per slot in a fixed order, so position identifies the
# slot even though the item names differ per set.
SLOT_ORDER = ["head", "fashion", "top", "bottom", "gloves", "shoes"]

# The dmowiki template row that carries the stats for these sets' slots.
TEMPLATE = "Yolei,T.K,Davis"


def main():
    rosters = json.loads(ROSTERS.read_text(encoding="utf-8"))["sets"]
    effects = json.loads(EFFECTS.read_text(encoding="utf-8"))["sets"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))["items"]

    by_slot = {}
    for it in registry:
        if it["name"].startswith(TEMPLATE):
            by_slot[it["slot"]] = it

    out = []
    unmapped = []
    for r in rosters:
        english = SET_NAMES.get(r["set"])
        if not english:
            unmapped.append(r["set"])
            continue
        if len(r["items"]) != len(SLOT_ORDER):
            print("  WARN  %s: %d items, expected %d"
                  % (r["set"], len(r["items"]), len(SLOT_ORDER)))
            continue

        slots = []
        for slot, base, shin in zip(SLOT_ORDER, r["items"], r["shin_items"]):
            tmpl = by_slot.get(slot)
            stats = {}
            if tmpl:
                for k in ("AT", "HT", "CT", "DS", "DE", "EV", "BL", "HP"):
                    if tmpl.get(k):
                        stats[k] = tmpl[k]
            slots.append({
                "slot": slot,
                "item": base,
                "shin": shin,
                # either variant fills this slot and counts toward the set
                "accepts": [base, shin],
                "stats": stats,
                "stats_from": tmpl["name"] if tmpl else None,
            })

        bonuses = [e for e in effects if e["set"] == english]
        out.append({
            "set_th": r["set"],
            "set": english,
            "pieces": len(slots),
            "slots": slots,
            "bonuses": [{
                "pieces": b["pieces"],
                "permanent": b["permanent"],
                "chance": b["chance"],
                "operation": b["operation"],
                "effects": b["effects"],
            } for b in sorted(bonuses, key=lambda b: b["pieces"] or 0)],
        })

    OUT.write_text(json.dumps({
        "built_at": date.today().isoformat(),
        "source": "data/set_rosters.json + data/set_effects.json + docs/gear_registry.json",
        "note": ("a set is complete when all its SLOTS are filled; each slot "
                 "accepts either the base item or its shin variant"),
        "sets": out,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print("wrote %s" % OUT.relative_to(PROJ))
    print("  sets joined %d" % len(out))
    for s in out:
        got = sum(1 for sl in s["slots"] if sl["stats"])
        print("    %-24s %s  slots %d (stats on %d)  bonuses %d"
              % (s["set_th"], s["set"], s["pieces"], got, len(s["bonuses"])))
    if unmapped:
        print("  not joined (no English counterpart in the bonus table):")
        for n in unmapped:
            print("    %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
