"""Turn the scanned registry into the picker list the gear page loads.

    data/clothing_items.json  ->  docs/gear_registry.json

Decision 05 fixed the direction: data/ owns the facts, a builder writes what the
page fetches. The page never reads data/ directly.

What this has to reconcile:

  * The wiki groups items into 28 slots; the solver has 13. "Rings" -> "ring",
    the four "Spiral Key Ring (XX)" groups all -> "keyring", and several wiki
    groups (Old Avatar/Costume, DigiAura, XAI System) have no wearable slot at
    all and are dropped. Digivices, the aura, key rings and ID cards come from
    vplay instead (add_th_tamer_gear), which also carries the wiki's XAI rows.
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
# Accessories roll random options, so the registry's numbers are only a cap.
# What a player needs to judge one -- how many options, how high each rolls,
# where it drops -- goes to its own file for the gear-names page.
ACCESSORY_OUT = PROJ / "docs" / "accessory_registry.json"
ACCESSORY_SLOTS = ("Rings", "Necklaces", "Earrings", "Bracelets")
ACCESSORY_EXCLUDED = PROJ / "data" / "accessory_excluded.json"
ICON_DIR = PROJ / "docs" / "img" / "gear"
TH_NAMES = PROJ / "data" / "gear_th_names.json"
UPGRADE_LEVELS = PROJ / "data" / "upgrade_levels.json"
GOGGLES_TH = PROJ / "data" / "goggles_th.json"
# dmowiki files these goggles under a "Tamer's Goggles" name with NA rolls;
# the Thai server's own variants (scan_vplay_goggles) replace those rows.
GOGGLES_WIKI_SLOTS = {"Adventure Goggles", "Digimon Kaiser´s Goggles", "Tamer`s Goggles"}
# which wiki heading's picture a Thai variant borrows when no row shares its name
GOGGLES_PICTURE = {"Adventure Goggles": "Adventure Goggles",
                   "Digimon Kaiser's Goggles": "Digimon Kaiser´s Goggles"}
# vplay's Adventure Goggles post says the stats go to the digimon. The Kaiser
# post never says; its numbers (AT 4000, CT 40%) are digimon-scale, ten times
# what the tamer-side goggles give, so they are read as digimon too.
GOGGLES_AXIS = {"Adventure Goggles": "digimon", "Digimon Kaiser's Goggles": "digimon",
                "Tamer’s Goggles": "tamer", "Complete Tamer’s Goggles": "tamer"}
# Digivices, Digi-Aura, key rings and ID cards from vplay (scan_vplay_tamer_gear).
# The wiki's key ring rows (every level, four of eleven families) give way to
# them; XAI and the Final Digivice have no vplay post, so the wiki's rows stay.
TAMER_GEAR_TH = PROJ / "data" / "tamer_gear_th.json"
WIKI_ONLY_TAMER_GEAR = {"XAI System": "xai", "Eos Digivice": "digivice"}
WIKI_ONLY_NAMES = {"Eos Digivice": {"Final Digivice"}}

# vplay's per-level Spirit tables name the piece, not the element: one table
# serves all five "*:Spirit X" items.
SPIRIT_PIECES = {
    "หมวกเกราะแห่งสปิริต": "Helmet",
    "เครื่องประดับแห่งสปิริต": "Accessory",
    "เสื้อแห่งสปิริต": "Top",
    "กางเกงแห่งสปิริต": "Bottom",
    "ถุงมือแห่งสปิริต": "Gloves",
    "รองเท้าแห่งสปิริต": "Shoes",
}


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
    "earrings of four holy beasts": "sealed earrings of four holy beasts",
    "radiant earrings of four holy beasts": "sealed radiant earrings of four holy beasts",
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


def add_thai_names(out):
    """Thai names exist only for set pieces (vplay's set rosters). Joined the
    way build_set_registry.py joins them -- (set, slot) to the set's own split
    pieces -- so the two pages never disagree on which piece is which."""
    import build_set_registry as sr
    rosters = json.loads(sr.ROSTERS.read_text(encoding="utf-8"))["sets"]
    named = 0
    for r in rosters:
        english = sr.SET_NAMES.get(r["set"])
        prefix = sr.TEMPLATE_BY_SET.get(english)
        if not prefix:
            continue
        slot_order = sr.SLOT_ORDER_BY_SET.get(english, sr.CLOTHING_SLOTS)
        shins = r["shin_items"] or [None] * len(r["items"])
        for slot, base, shin in zip(slot_order, r["items"], shins):
            hits = [it for it in out if it["slot"] == slot and it["name"].startswith(prefix)]
            if len(hits) != 1:
                print(f"  ! no single {prefix!r} {slot} piece for {base}")
                continue
            hits[0]["nameTh"] = base
            if shin:
                hits[0]["nameThShin"] = shin
            named += 1

    # Gear outside the rosters: names found in vplay posts, keyed by the
    # registry's English name. A key that matches nothing is a rename upstream.
    extra = json.loads(TH_NAMES.read_text(encoding="utf-8"))["items"]
    by_name = {it["name"]: it for it in out}
    for en, th in extra.items():
        it = by_name.get(en)
        if not it:
            print(f"  ! {TH_NAMES.name}: no registry item named {en!r}")
        elif not it.get("nameTh"):
            it["nameTh"] = th
            named += 1
    return named


def level_table(levels):
    """vplay levels -> {"0": {stat: value}, ...} for every level up to the top.

    Solver stats only. A level the table leaves blank gets {} -- the stat has
    not unlocked yet -- so the page never falls back to a different level."""
    top = max(l["upgrade"] for l in levels)
    table = {str(n): {} for n in range(top + 1)}
    for l in levels:
        row = table[str(l["upgrade"])]
        for st in l["stats"]:
            key = st["stat"]
            if key in SOLVER_STATS:
                row[key] = row.get(key, 0) + (st["value"] if key in PCT_STATS
                                              else js_round(st["value"]))
    return table, top


def non_solver_at(levels, lvl):
    row = next((l for l in levels if l["upgrade"] == lvl), None)
    return [{"stat": s["stat"], "value": s["value"], "unit": s["unit"]}
            for s in (row or {}).get("stats", []) if s["stat"] not in SOLVER_STATS]


def add_level_stats(out):
    """Attach vplay's per-level stats so the page can follow the player's own
    upgrade level instead of the wiki's top band."""
    items = json.loads(UPGRADE_LEVELS.read_text(encoding="utf-8"))["items"]
    by_name = {it["name"]: it for it in items}
    done = 0

    for th, part in SPIRIT_PIECES.items():
        src = by_name.get(th)
        if not src:
            print(f"  ! {UPGRADE_LEVELS.name}: no {th!r}")
            continue
        table, top = level_table(src["levels"])
        for rec in out:
            if not re.fullmatch(r"\w+:Spirit " + part, rec["name"]):
                continue
            # The wiki's top band and vplay's top level must agree, or one of
            # the two sources is describing a different item.
            for key in SOLVER_STATS:
                if rec.get(key, 0) != table[str(top)].get(key, 0):
                    print(f"  ! {rec['name']} {key}: wiki {rec.get(key, 0)} "
                          f"vs vplay +{top} {table[str(top)].get(key, 0)}")
            rec["levelStats"] = table
            rec.pop("ranged", None)          # exact per level now, not a roll top
            done += 1

    return done


def add_th_goggles(out):
    """Swap the wiki's goggles rows for the Thai-server variants."""
    if not GOGGLES_TH.exists():
        print(f"  ! missing {GOGGLES_TH.name}")
        return 0
    old = [r for r in out if r.get("wikiSlot") in GOGGLES_WIKI_SLOTS]
    out[:] = [r for r in out if r.get("wikiSlot") not in GOGGLES_WIKI_SLOTS]
    pic_by_name = {r["name"]: r for r in old if r.get("iconWiki")}
    pic_by_slot = {}
    for r in old:
        if r.get("iconWiki"):
            pic_by_slot.setdefault(r["wikiSlot"], r)
    added = 0
    for src in json.loads(GOGGLES_TH.read_text(encoding="utf-8"))["items"]:
        table, top = level_table(src["levels"])
        family = src["name"].split(" [")[0]
        rec = {
            "id": re.sub(r"[^a-z0-9]+", "-", f"glasses-{src['name']}".lower()).strip("-"),
            "name": src["name"],
            "slot": "glasses",
            "axis": GOGGLES_AXIS.get(family, "unknown"),
            "nameTh": src["nameTh"],
        }
        if top:
            rec.update(upgrade=0, upgradeMax=top, levelStats=table)
        rec.update(table[str(top)])
        if src.get("ranged"):
            rec["ranged"] = True
        pic = pic_by_name.get(src["name"]) or pic_by_slot.get(GOGGLES_PICTURE.get(family))
        if pic:
            rec["iconWiki"] = pic["iconWiki"]
            if pic.get("icon"):
                rec["icon"] = pic["icon"]
        extra = non_solver_at(src["levels"], top)
        if extra:
            rec["extra"] = extra
        out.append(rec)
        added += 1
    return added


def wiki_picture(basename, items):
    """iconWiki path of the dmowiki file a Thai item borrows, matched by the
    file's own name so a group sharing one row name still gets the right one."""
    for it in items:
        p = it.get("icon")
        if p and unquote(p.rsplit("/", 1)[-1]) == basename:
            return p
    return None


def display_rows(stats):
    """A fixed-value piece shown like an accessory's roll table, one row per stat."""
    return [{"label": s["stat"], "fixed": "%g%s" % (s["value"], "%" if s["unit"] == "pct" else "")}
            for s in stats]


def add_th_tamer_gear(out, items):
    """Thai-server digivices, aura, key rings and ID cards, plus the wiki's XAI
    and Final Digivice rows (stat-less ones too: the page lists them by name)."""
    if not TAMER_GEAR_TH.exists():
        print(f"  ! missing {TAMER_GEAR_TH.name}")
        return 0
    out[:] = [r for r in out if r["slot"] != "keyring"]
    added = 0
    for src in json.loads(TAMER_GEAR_TH.read_text(encoding="utf-8"))["items"]:
        table, top = level_table(src["levels"])
        rec = {
            "id": re.sub(r"[^a-z0-9]+", "-", f"{src['slot']}-{src['name']}".lower()).strip("-"),
            "name": src["name"],
            "slot": src["slot"],
            "axis": src["axis"],
            "nameTh": src["nameTh"],
        }
        if top:
            rec.update(upgrade=0, upgradeMax=top, levelStats=table)
        rec.update(table[str(top)])
        if src.get("ranged"):
            rec["ranged"] = True
        wiki_icon = wiki_picture(src["picture"], items) if src.get("picture") else None
        if wiki_icon:
            rec["iconWiki"] = wiki_icon
            icon = local_icon(wiki_icon)
            if icon:
                rec["icon"] = icon
        extra = non_solver_at(src["levels"], top)
        if extra:
            rec["extra"] = extra
        top_stats = next(l["stats"] for l in src["levels"] if l["upgrade"] == top)
        rec["rows"] = src.get("rows") or display_rows(top_stats)
        for field in ("rowsFrom", "info", "families"):
            if src.get(field):
                rec[field] = src[field]
        out.append(rec)
        added += 1

    seen = set()
    for it in items:
        slot = WIKI_ONLY_TAMER_GEAR.get(it.get("slot"))
        names = WIKI_ONLY_NAMES.get(it.get("slot"))
        if not slot or (names and it["name"] not in names) or it["name"] in seen:
            continue
        seen.add(it["name"])
        rec = {"id": it["id"], "name": it["name"], "slot": slot,
               "wikiSlot": it["slot"], "axis": it.get("axis") or "unknown"}
        stats = []
        for st in it.get("stats", []):
            top = top_of(st)
            if not st.get("stat") or top is None:
                continue
            stats.append({"stat": st["stat"], "value": top, "unit": st.get("unit", "flat")})
            if st["stat"] in SOLVER_STATS:
                rec[st["stat"]] = rec.get(st["stat"], 0) + (top if st["stat"] in PCT_STATS
                                                            else js_round(top))
        other = [s for s in stats if s["stat"] not in SOLVER_STATS]
        if other:
            rec["extra"] = other
        if it.get("icon"):
            rec["iconWiki"] = it["icon"]
            icon = local_icon(it["icon"])
            if icon:
                rec["icon"] = icon
        rec["rows"] = display_rows(stats)
        rec["info"] = "ค่าจาก dmowiki (vplay ยังไม่มีโพสต์)" if stats else "dmowiki ยังไม่มีค่า"
        if it.get("obtain"):
            rec["obtain"] = it["obtain"]
        out.append(rec)
        added += 1
    return added


def add_shin_pieces(out):
    """Split each Daisuke/Takeru/Miyako piece's shin tier into its own item.

    The roster names both tiers per slot but dmowiki only has the base one, so
    the shin tier used to ride along as a second Thai name on the base item --
    and a player who owns the shin piece got the base numbers. vplay tables
    both tiers per level; one table serves all three sets. Needs nameThShin,
    so it runs after add_thai_names."""
    items = json.loads(UPGRADE_LEVELS.read_text(encoding="utf-8"))["items"]
    tiers = {(it["char_slot"], it["shin"]): it for it in items if it.get("char_slot")}
    added = []
    for rec in out:
        shin_th = rec.get("nameThShin")
        if not shin_th or not re.fullmatch(r"(Davis|T\.K|Yolei) \w+", rec["name"]):
            continue
        base, shin = tiers.get((rec["slot"], False)), tiers.get((rec["slot"], True))
        if not (base and shin):
            print(f"  ! {UPGRADE_LEVELS.name}: no per-level tiers for {rec['name']}")
            continue
        table, top = level_table(base["levels"])
        for key in SOLVER_STATS:
            if rec.get(key, 0) != table[str(top)].get(key, 0):
                print(f"  ! {rec['name']} {key}: wiki {rec.get(key, 0)} "
                      f"vs vplay +{top} {table[str(top)].get(key, 0)}")
        rec["levelStats"] = table
        rec.pop("ranged", None)
        rec.pop("nameThShin")

        table, top = level_table(shin["levels"])
        # the shin piece looks the same in game, so it borrows the base icon
        twin = {k: rec[k] for k in ("slot", "axis", "icon") if k in rec}
        twin.update({
            "id": rec["id"] + "-shin",
            "name": rec["name"] + " (Shin)",
            "upgrade": 0,
            "upgradeMax": top,
            "nameTh": shin_th,
            "levelStats": table,
        })
        twin.update(table[str(top)])
        extra = non_solver_at(shin["levels"], top)
        if extra:
            twin["extra"] = extra
        added.append(twin)
    out.extend(added)
    return len(added)


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


def local_icon(wiki_icon):
    """Page-relative path of a picture fetch_dmowiki_images.py saved, else None."""
    if not wiki_icon:
        return None
    local = ICON_DIR / icon_filename(wiki_icon)
    return local.relative_to(PROJ / "docs").as_posix() if local.exists() else None


def excluded_key(name):
    """Name with only a level or duration tail dropped. icon_key drops any
    bracket, which would take "Miracle Bracelet [Special]" out along with the
    "Miracle Bracelet [Level 1]" the list names -- a different item."""
    name = re.sub(r"\s*\[\s*(?:(?:Level|Lv)\.?\s*[\d-][^\]]*)?\]\s*$", "", name, flags=re.I)
    name = re.sub(r"\s*\[\s*\d+\s*Days?\s*\]\s*$", "", name, flags=re.I)
    name = re.sub(r"\s*Lv\.?\s*[\d-]+$", "", name, flags=re.I)
    key = full_key(name)
    return ICON_ALIAS.get(key, key)


def excluded_accessories():
    """Keys of the accessories the site leaves out, aliased so one list entry
    removes the list row and its stats row alike."""
    if not ACCESSORY_EXCLUDED.exists():
        return set()
    names = json.loads(ACCESSORY_EXCLUDED.read_text(encoding="utf-8"))["items"]
    return {excluded_key(n) for n in names}


def is_excluded(it, keys):
    if it.get("slot") not in ACCESSORY_SLOTS:
        return False
    return excluded_key(it["name"]) in keys


def build_accessory_ref(items, icons):
    """One record per accessory: the list row (options, drop) joined to the
    roll table that belongs to it. A piece with no table of its own takes the
    cap for its kind ("Ring with 3 Options"), named in rowsFrom."""
    rows_by = defaultdict(list)
    caps = defaultdict(dict)
    lists = {}
    skip = excluded_accessories()
    for it in items:
        if it.get("slot") not in ACCESSORY_SLOTS or is_excluded(it, skip):
            continue
        key = icon_key(it["name"])
        key = (it["slot"], ICON_ALIAS.get(key, key))
        if it.get("category"):
            caps[it["slot"]][it["name"]] = it.get("option_rows") or []
        elif it.get("option_rows"):
            rows_by[key].append(it)
        elif not it.get("stats"):
            lists.setdefault(key, it)

    def cap_for(slot, options):
        n = [int(x) for x in re.findall(r"\d+", options or "")]
        for name, rows in caps[slot].items():
            low = name.lower()
            if low.startswith("regular") or (n and "with %d" % n[0] in low) \
                    or (n and n[0] in (4, 5) and "4 or 5" in low):
                return name, rows
        return None, []

    out = []
    for key in sorted(set(lists) | set(rows_by)):
        slot = key[0]
        head = lists.get(key)
        tables = sorted(rows_by.get(key, []), key=lambda r: split_level(r["name"])[1] or 0)
        top = tables[-1] if tables else None
        rec = {"name": (head or top)["name"], "slot": SLOT_MAP[slot]}
        wiki_icon = ((head or {}).get("icon") or (top or {}).get("icon")
                     or icon_by_name([rec["name"]], rec["name"], icons))
        if wiki_icon:
            rec["iconWiki"] = wiki_icon
            icon = local_icon(wiki_icon)
            if icon:
                rec["icon"] = icon
        for field, to in (("options", "options"), ("number_change", "numberChange"),
                          ("obtain", "obtain"), ("recommended", "recommended")):
            if head and head.get(field) is not None:
                rec[to] = head[field]
        if top:
            rec["rows"] = top["option_rows"]
            if len(tables) > 1:
                rec["rowsFrom"] = top["name"]   # the highest level printed
        else:
            name, rows = cap_for(slot, rec.get("options"))
            if rows:
                rec["rows"] = rows
                rec["rowsFrom"] = name
        out.append(rec)

    write_stamped(ACCESSORY_OUT, {
        "built_at": date.today().isoformat(),
        "source": "data/clothing_items.json",
        "note": ("accessories roll random options; rows are what each option "
                 "can roll (min/max, or the cap), not what a piece has"),
        "items": out,
    }, "built_at")
    return out


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
    skip = excluded_accessories()
    for it in items:
        # a category column is the cap for a kind of accessory, not a piece
        if not it.get("stats") or it.get("category") or is_excluded(it, skip):
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

    leveled = add_level_stats(out)
    goggles = add_th_goggles(out)
    tamer_gear = add_th_tamer_gear(out, items)
    named_th = add_thai_names(out)
    shin = add_shin_pieces(out)
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
    accessories = build_accessory_ref(items, icons)

    by_slot = defaultdict(int)
    by_axis = defaultdict(int)
    for r in out:
        by_slot[r["slot"]] += 1
        by_axis[r["axis"]] += 1
    print("wrote %s" % OUT.relative_to(PROJ))
    print("  items %d in %d slots, %d with a Thai name" % (len(out), len(by_slot), named_th))
    print("  per-level stats on %d items" % leveled)
    print("  shin pieces split out %d" % shin)
    print("  Thai-server goggles %d" % goggles)
    print("  digivice/aura/key ring/ID card/XAI %d" % tamer_gear)
    print("  axis  %s" % dict(by_axis))
    print("  slots %s" % ", ".join("%s=%d" % kv for kv in sorted(by_slot.items())))
    if dropped:
        print("  dropped (no wearable slot):")
        for k, v in sorted(dropped.items(), key=lambda x: -x[1]):
            print("    %-28s %d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
