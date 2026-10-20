"""Read the Thai-server digivices, Digi-Aura, key rings and magnetic ID cards
off vplay's GM-note posts into data/tamer_gear_th.json.

    First Digivice                 post 25337  (เฟิร์สท์ ดิจิไวซ์, + the aura)
    Xros / Fusion Loader           post 20281
    Darkness Loader                post 24075
    True crest digivices, D-Ark    post 23863  (ดิจิไวซ์ที่แท้จริงแห่ง... / D-อาร์ค ...ที่แท้จริง)
    Spiral Key Ring                post 16511
    DIGI-Key Ring                  post 19025
    Ghost Key Ring                 post 23093
    Magnetic ID Card               posts 25498 Digimon King · 25000 Heaven Wings · 25363 Time Ruler

Every line is kept at its top tier only -- the complete digivice, the Lv Max
key ring, the +15 card -- which is what a player wears. Cards and the Ghost
Key Ring keep their whole +0..+15 table so the page can follow the level.

A digivice's options are damage against one attribute or element, picked at
random from a pool. Those go to "rows" (shown on gear-names, never summed)
rather than to stats: summing a pool would credit every option at once.

Same output shape as data/goggles_th.json, so build_gear_registry reads it
with the code it already has. Posts are cached as cache_vplay/wp_<id>.json and
a cached post is never fetched again.
"""

import html
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builders"))
from stamped_json import write_stamped  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache_vplay"
OUT = PROJ / "data" / "tamer_gear_th.json"
POST_URL = "https://www.vplay.in.th/wp-json/wp/v2/posts/%d?_fields=id,date,link,content"

FIRST_POST = 25337
XROS_POST = 20281
DARKNESS_POST = 24075
TRUE_POST = 23863
SPIRAL_POST = 16511
DIGI_KEY_POST = 19025
GHOST_POST = 23093
CARD_POSTS = (25498, 25000, 25363)

# The digivice option pool. vplay spells "no attribute" two ways.
ELEMENTS = ["ดาต้า", "วัคซีน", "ไวรัส", "ไม่ระบุประเภท", "น้ำแข็ง", "น้ำ", "ไฟ",
            "ดิน", "ลม", "ไม้", "แสง", "ความมืด", "สายฟ้า", "เหล็ก"]
ELEMENT_ALIAS = {"ไม่ปรากฎประเภท": "ไม่ระบุประเภท"}

STAT_LABELS = {"AT": "AT", "HP": "HP", "HT": "HT", "CT": "CT", "DE": "DE", "EXP": "EXP",
               "พลังโจมตีสกิล": "Skill DMG", "ความเสียหายสุดท้าย": "Final DMG",
               # Ghost Key Ring's columns; dmowiki prints the first one as HT
               "อัตราโจมตี": "HT", "HP สูงสุด": "HP"}
# Printed without "%", CT is the game's raw number, 100 per 1%: the cards list
# CT +1500 where dmowiki prints 15%.
RAW_PCT = {"CT", "EV", "BL"}

CREST = [("ความกล้าหาญ", "Courage", "Digivice_of_Courage.PNG"),
         ("มิตรภาพ", "Friendship", "Digivice_of_Friendship.PNG"),
         ("ความรัก", "Love", "Digivice_of_Love.PNG"),
         ("ความบริสุทธิ์", "Purity", "Digivice_of_Purity.PNG"),
         ("ความรู้", "Knowledge", "Digivice_of_Knowledge.PNG"),
         ("ความซื่อสัตย์", "Sincerity", "Digivice_of_Reliability.PNG"),
         ("ความหวัง", "Hope", "Digivice_of_Hope.PNG"),
         ("แสง", "Light", "Digivice_of_Light.PNG"),
         ("ความเมตตา", "Kindness", "Digivice_of_Kindness.PNG"),
         ("โชคชะตา", "Fate", "Digivice_of_Fate.PNG"),
         ("ปาฏิหาริย์", "Miracles", "Digivice_of_Miracles.PNG")]
D_ARK = [("ฮาซาร์ด", "Hazard", "D-Ark-Item-Hazard.png"),
         ("เซนท์", "Saint", "D-Ark-Item-Saint.png"),
         ("ซากุยา", "Sakuya", "D-Ark-Item-Sakuya.png"),
         ("จัสติส", "Justice", "D-Ark-Item-JUSTICE.png"),
         ("เดสทินี", "Destiny", "D-Ark-Item-DESTINY.png")]
CARD_SERIES = {"Digimon King": ("Digimon King", "DigimonKing.png"),
               "Heaven Wings": ("Heaven Wing", "HeavenWing.png"),
               "Time Ruler": ("Time Ruler", "TimeRuler.png")}


def text(fragment):
    t = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def rows_of(table):
    return [[text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)]


def tables(content):
    return [rows_of(t) for t in re.findall(r"<table.*?</table>", content, re.S)]


def load_post(post_id):
    path = CACHE / ("wp_%d.json" % post_id)
    if not path.exists():
        import requests
        r = requests.get(POST_URL % post_id, timeout=40,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def stat_value(stat, cell):
    """'+1500' / '500%' / '1,940' -> {stat, value, unit}; a dash is None."""
    m = re.match(r"^\+?\s*([\d,.]+)\s*(%?)$", cell.strip())
    if not m:
        return None
    value, pct = float(m.group(1).replace(",", "")), bool(m.group(2))
    if stat in RAW_PCT and not pct:
        value, pct = value / 100.0, True
    return {"stat": stat, "value": value, "unit": "pct" if pct else "flat"}


def element(cell):
    cell = ELEMENT_ALIAS.get(cell, cell)
    return cell if cell in ELEMENTS else None


def pool_rows(rows):
    """Option pool -> [{label, min, max}] in pool order.

    Three layouts carry it: a value row of bare "8%-15%" ranges under the
    label row (True digivices), a "Lv. Max" row of ranges (the loaders), and
    the First Digivice's "สมบูรณ์" base row followed by its "สูงสุด" row.
    Only the top tier is read; an earlier level never overwrites it."""
    out, labels, base = {}, None, None
    for row in rows:
        cells = [c for c in row if c]
        if cells and all(element(c) for c in cells):
            labels = [element(c) for c in cells]
            continue
        if not labels or not cells:
            continue
        if all(re.fullmatch(r"[\d.]+%-[\d.]+%", c) for c in cells):
            pairs = [c.split("-") for c in cells]
        elif cells[0] == "Lv. Max":
            pairs = [c.split("-") for c in cells[1:]]
        elif cells[0] == "สมบูรณ์":
            base = cells[3:]
            continue
        elif cells[0] == "สูงสุด" and base:
            pairs = list(zip(base, cells[1:]))
            base = None
        else:
            continue
        for lab, (lo, hi) in zip(labels, pairs):
            out[lab] = {"label": lab, "min": lo.strip(), "max": hi.strip()}
    return [out[e] for e in ELEMENTS if e in out]


def first_digivice(content):
    ts = tables(content)
    pool = pool_rows(ts[0])
    aura_rows = ts[1]
    labels = [STAT_LABELS[c] for c in aura_rows[1]]
    lo = dict(zip(labels, aura_rows[2][1:]))
    hi = dict(zip(labels, aura_rows[3][1:]))
    aura_stats = [s for s in (stat_value(k, hi[k]) for k in labels) if s]
    return [
        {"name": "First Digivice", "nameTh": "เฟิร์สท์ ดิจิไวซ์", "slot": "digivice",
         "axis": "digimon", "picture": "EosDvice.PNG",
         "levels": [{"upgrade": 0, "stats": []}], "rows": pool,
         "info": "ค่าที่ระดับสมบูรณ์ (8 ชิปเซ็ท) พลังดิจิทารี่ 100% · สุ่มออปชันจากรายการ"},
        {"name": "DigiAura of Bracery and Friendship",
         "nameTh": "ดิจิออร่าแห่งความกล้าหาญและมิตรภาพ", "slot": "aura", "axis": "digimon",
         "picture": "DigiAura_of_Bracery_and_Friendship.png", "ranged": True,
         "levels": [{"upgrade": 0, "stats": aura_stats}],
         "rows": [{"label": k, "min": lo[k], "max": hi[k]} for k in labels]},
    ]


def loader(content, name, name_th):
    """The loaders' Lv. 0 row is a fixed AT; every level after adds the pool."""
    ts = tables(content)
    at = next((r for r in ts[0] if r and r[0] == "Lv. 0"), None)
    stats = [stat_value("AT", at[1])] if at else []
    return {"name": name, "nameTh": name_th, "slot": "digivice", "axis": "digimon",
            "picture": "SusaLoaderMax.PNG", "levels": [{"upgrade": 0, "stats": stats}],
            "rows": pool_rows(ts[0]), "info": "ค่าออปชันที่ Lv. Max · สุ่มออปชันจากรายการ"}


def true_digivices(content):
    """One stats table titled for the True Digivice serves both boxes the
    post crafts, the crest digivices and the D-Arks; the D-Arks say so."""
    pool = pool_rows(tables(content)[0])
    out = []
    for th, en, pic in CREST:
        out.append({"name": "True Digivice of %s" % en, "nameTh": "ดิจิไวซ์ที่แท้จริงแห่ง" + th,
                    "slot": "digivice", "axis": "digimon", "picture": pic,
                    "levels": [{"upgrade": 0, "stats": []}], "rows": pool,
                    "info": "สุ่มออปชันจากรายการ"})
    for th, en, pic in D_ARK:
        out.append({"name": "True D-Ark %s" % en, "nameTh": "D – อาร์ค %sที่แท้จริง" % th,
                    "slot": "digivice", "axis": "digimon", "picture": pic,
                    "levels": [{"upgrade": 0, "stats": []}], "rows": pool,
                    "rowsFrom": "ดิจิไวซ์ที่แท้จริง (โพสต์ไม่แยกตาราง D-อาร์ค)",
                    "info": "สุ่มออปชันจากรายการ"})
    return out


DETAIL = re.compile(r"(HP|AT|DE|พลังโจมตีสกิล)\s*:\s*(?:AT\s*:\s*)?([\d,.]+%?)\s*~\s*([\d,.]+%?)")


def key_detail(cell):
    """'HP: 388~1,940 AT : 55~278 พลังโจมตีสกิล: 2%~10%' -> stats at the top
    of each roll, plus the display rows."""
    stats, rows = [], []
    for lab, lo, hi in DETAIL.findall(cell):
        st = STAT_LABELS[lab]
        stats.append(stat_value(st, hi))
        rows.append({"label": st, "min": lo, "max": hi})
    return stats, rows


def families(cells, pattern):
    return sorted({m.group(1).upper() for c in cells for m in [re.search(pattern, c)] if m})


def spiral(content):
    ts = tables(content)
    base = next(r for t in ts for r in t if r and r[0].startswith("สไปรอลคีย์ริง Lv Max"))
    stats, rows = key_detail(base[-1])
    out = [{"name": "Spiral Key Ring Lv.Max", "nameTh": "สไปรอลคีย์ริง Lv Max",
            "slot": "keyring", "axis": "tamer", "picture": "Spiral_Key_Ring_Lv.6+.png",
            "ranged": True, "levels": [{"upgrade": 0, "stats": stats}], "rows": rows}]
    fam_rows = [r for t in ts for r in t
                if r and re.match(r"สไปรอลคีย์ริง ?\[\w+\] Lv Max", r[0])]
    details = {r[-1] for r in fam_rows}
    if len(details) != 1:
        print("  ! spiral family Lv Max rows disagree: %r" % details)
    fams = families([r[0] for r in fam_rows], r"\[(\w+)\]")
    stats, rows = key_detail(fam_rows[0][-1])
    out.append({"name": "Spiral Key Ring (Families) Lv.Max",
                "nameTh": "สไปรอลคีย์ริง [ตระกูล] Lv Max", "slot": "keyring",
                "axis": "unknown", "ranged": True,
                "levels": [{"upgrade": 0, "stats": stats}], "rows": rows,
                "families": fams, "info": "แยกชิ้นตามตระกูล ค่าเท่ากันทุกตระกูล"})
    return out


def digi_key(content):
    rows_ = [r for t in tables(content) for r in t if r and r[0] == "DIGI-คีย์ริง"]
    details = {r[-1] for r in rows_}
    if len(details) != 1:
        print("  ! DIGI-key ring rows disagree: %r" % details)
    stats, rows = key_detail(rows_[0][-1])
    return {"name": "DIGI-Key Ring (Families)", "nameTh": "DIGI-ที่เก็บคีย์ริง [ตระกูล]",
            "slot": "keyring", "axis": "unknown", "ranged": True,
            "levels": [{"upgrade": 0, "stats": stats}], "rows": rows,
            "families": families([r[2] for r in rows_], r"\[(\w+)\]"),
            "info": "แยกชิ้นตามตระกูล ค่าเท่ากันทุกตระกูล"}


def ghost(content):
    """Level table 0..+15; the post says the stats go to the digimon."""
    ts = tables(content)
    table = next(t for t in ts if t and t[0][:1] == ["เลเวล"] and "อัตราโจมตี" in t[1])
    labels = [STAT_LABELS[c] for c in table[1][1:]]
    levels = []
    for row in table[2:]:
        if not row or not row[0].isdigit():
            continue
        stats = [s for s in (stat_value(k, v) for k, v in zip(labels, row[1:])) if s]
        levels.append({"upgrade": int(row[0]), "stats": stats})
    fams = families([c for t in ts for r in t for c in r], r"โกสท์ คีย์ริง \[(\w+)\]")
    return {"name": "Ghost Keyring ( Families )", "nameTh": "โกสท์ คีย์ริง [ตระกูล]",
            "slot": "keyring", "axis": "digimon", "picture": "Ghost_Key_Ring.png",
            "levels": levels, "families": fams,
            "info": "แยกชิ้นตามตระกูล ค่าเท่ากันทุกตระกูล"}


def cards(content):
    """One table per post: a 1-cell title row per card, a header row, the
    "พื้นฐาน" row naming the three stats, then +1..+15 with values only."""
    out = []
    for t in tables(content):
        cur, labels = None, None
        for row in t:
            title = re.search(r"ID Card – (.+?) \[(\w+)\]", row[0]) if len(row) == 1 else None
            if title:
                series = re.sub(r"\s+", " ", title.group(1)).strip()
                en, pic = CARD_SERIES[series]
                key = title.group(2)
                cur = {"name": "Magnetic ID Card - %s [%s]" % (en, key),
                       "nameTh": "แมกเนติก ID Card – %s [%s]" % (series, key),
                       "slot": "idcard", "axis": "tamer", "picture": pic, "levels": []}
                out.append(cur)
                continue
            if cur is None or not row:
                continue
            if row[0] == "พื้นฐาน":
                labels = [STAT_LABELS[row[i]] for i in (1, 3, 5)]
                values, lvl = [row[2], row[4], row[6]], 0
            elif row[0].isdigit() and labels:
                values, lvl = row[1:4], int(row[0])
            else:
                continue
            stats = [s for s in (stat_value(k, v) for k, v in zip(labels, values)) if s]
            cur["levels"].append({"upgrade": lvl, "stats": stats})
    return [c for c in out if c["levels"]]


def main():
    posts = {pid: load_post(pid) for pid in
             (FIRST_POST, XROS_POST, DARKNESS_POST, TRUE_POST, SPIRAL_POST,
              DIGI_KEY_POST, GHOST_POST) + CARD_POSTS}
    body = {pid: p["content"]["rendered"] for pid, p in posts.items()}
    items = first_digivice(body[FIRST_POST])
    items.append(loader(body[XROS_POST], "Digimon Xros Loader", "ครอสโหลดเดอร์-ซากุระ"))
    items.append(loader(body[XROS_POST], "Digimon Fusion Loader", "ครอสโหลดเดอร์-ดิซีดวซ"))
    items.append(loader(body[DARKNESS_POST], "Digimon Darkness Loader", "ดาร์กเนส โหลดเดอร์"))
    items += true_digivices(body[TRUE_POST])
    items += spiral(body[SPIRAL_POST])
    items.append(digi_key(body[DIGI_KEY_POST]))
    items.append(ghost(body[GHOST_POST]))
    for pid in CARD_POSTS:
        items += cards(body[pid])
    write_stamped(OUT, {
        "fetched_at": date.today().isoformat(),
        "source": [posts[pid]["link"] for pid in sorted(posts)],
        "note": ("Thai-server digivices, Digi-Aura, key rings and magnetic ID cards at "
                 "each line's top tier; 'rows' is what each option can roll, a "
                 "digivice's pool is never summed; CT printed without % is raw "
                 "(100 per 1%); 'picture' is the dmowiki file the item borrows."),
        "items": items,
    }, "fetched_at")
    print("wrote %s" % OUT.relative_to(PROJ))
    by = {}
    for it in items:
        by[it["slot"]] = by.get(it["slot"], 0) + 1
    print("  " + "  ".join("%s %d" % kv for kv in sorted(by.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
