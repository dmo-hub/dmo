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
# The hand-kept files for sets dmowiki never recorded. Their BONUSES reach us
# through data/set_effects.json (scan_set_effects merges them there); what is
# read from here are the ITEMS, which are in no item registry either.
EXTRA = [PROJ / "data" / "last_evolution.json"]
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
    # dmowiki never recorded this one, so the English name is ours: it is only
    # a join key, and the page shows set_th to the player either way.
    "ลาสต์ อีโวลูชัน": "Last Evolution",
}

# vplay's slot words, in roster order, against the solver's slot ids. The
# roster lists one item per slot in a fixed order, so position identifies the
# slot even though the item names differ per set.
#
# Not every set claims the six clothing slots: the Last Evolution pair is two
# accessories in slots of their own. The order is therefore per set, keyed by
# the English name, with the clothing six as the default.
CLOTHING_SLOTS = ["head", "fashion", "top", "bottom", "gloves", "shoes"]
SLOT_ORDER_BY_SET = {
    "Last Evolution": ["digivice", "aura"],
}

# The dmowiki template row that carries the stats for these sets' slots.
TEMPLATE = "Yolei,T.K,Davis"


def main():
    rosters = json.loads(ROSTERS.read_text(encoding="utf-8"))["sets"]
    effects = json.loads(EFFECTS.read_text(encoding="utf-8"))["sets"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))["items"]
    extra_items = []
    for path in EXTRA:
        extra_items += json.loads(path.read_text(encoding="utf-8"))["items"]

    # Only the ITEMS are read from here: the bonuses are merged into
    # data/set_effects.json by scan_set_effects, so taking them from both
    # places would award them twice.

    by_slot = {}
    for it in registry:
        if it["name"].startswith(TEMPLATE):
            by_slot[it["slot"]] = it

    # Those items are in no dmowiki registry either, so their stats come
    # straight from the hand-kept file rather than the template rows above.
    stats_by_item = {}
    for it in extra_items:
        stats = {}
        for k in ("AT", "HT", "CT", "DS", "DE", "EV", "BL", "HP"):
            if it.get(k):
                stats[k] = it[k]
        stats_by_item[it["name"]] = (stats, it["id"])

    out = []
    unmapped = []
    for r in rosters:
        english = SET_NAMES.get(r["set"])
        if not english:
            unmapped.append(r["set"])
            continue
        slot_order = SLOT_ORDER_BY_SET.get(english, CLOTHING_SLOTS)
        if len(r["items"]) != len(slot_order):
            print("  WARN  %s: %d items, expected %d"
                  % (r["set"], len(r["items"]), len(slot_order)))
            continue

        # A set without shin variants has shin_items == [], and zip() would
        # silently yield nothing -- producing a set with zero slots and no
        # error at all. Pad instead, so "no shin variant" means the slot
        # accepts only the base item rather than the slot vanishing.
        shins = r["shin_items"] or [None] * len(r["items"])

        slots = []
        for slot, base, shin in zip(slot_order, r["items"], shins):
            tmpl = by_slot.get(slot)
            stats = {}
            stats_from = None
            if base in stats_by_item:
                stats, stats_from = stats_by_item[base]
            elif tmpl:
                for k in ("AT", "HT", "CT", "DS", "DE", "EV", "BL", "HP"):
                    if tmpl.get(k):
                        stats[k] = tmpl[k]
                stats_from = tmpl["name"]
            slots.append({
                "slot": slot,
                "item": base,
                "shin": shin,
                # either variant fills this slot and counts toward the set;
                # a set with no shin variants accepts the base item only
                "accepts": [n for n in (base, shin) if n],
                "stats": stats,
                "stats_from": stats_from,
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
