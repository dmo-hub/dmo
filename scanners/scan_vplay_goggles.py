"""Read the Thai-server goggles off two vplay posts into data/goggles_th.json.

    Adventure Goggles      post 19820  (แว่นนิรภัยแอดเวนเจอร์)
    Digimon Kaiser Goggles post 25445  (แว่นตาของดิจิมอนไกเซอร์)
    Tamer's Goggles        post 17826  (แว่นตาของเทมเมอร์)

Why vplay: dmowiki writes both goggles under a "Tamer's Goggles" name with NA
roll ranges, while the Thai server sells different variants -- Adventure
Goggles come as 25 fixed pairs (main stat x third option), Kaiser goggles as
5 variants with a per-level table. vplay's tables are the ones that match the
game the site tracks.

Output items use the same "levels" shape as data/upgrade_levels.json, so
build_gear_registry reads them with the code it already has:

    {"name", "nameTh", "levels": [{"upgrade": n, "stats": [{stat, value, unit}]}]}

Posts are cached as cache_vplay/wp_<id>.json; a cached post is never fetched
again, which keeps the validate gate's re-run offline and reproducible.
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
OUT = PROJ / "data" / "goggles_th.json"
POST_URL = "https://www.vplay.in.th/wp-json/wp/v2/posts/%d?_fields=id,date,link,content"

ADVENTURE_POST = 19820
KAISER_POST = 25445
TAMER_POST = 17826

# Column labels in these tables. "SCD" and "พลังโจมตีสกิล" have no solver stat;
# they are kept as extras, the way vplay prints them.
STAT_LABELS = {"HT": "HT", "EV": "EV", "CT": "CT", "HP": "HP", "AT": "AT",
               "SCD": "SCD", "พลังโจมตีสกิล": "Skill DMG"}
# Printed without "%", these three are the game's raw number, 100 per 1%:
# Adventure Goggles list CT 1500 for the 15% the item shows.
RAW_PCT = {"CT", "EV", "BL"}


def text(fragment):
    t = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def rows_of(table):
    return [[text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)]


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
    m = re.match(r"^([\d.]+)\s*(%?)$", cell.replace(",", ""))
    if not m:
        return None
    value, pct = float(m.group(1)), bool(m.group(2))
    if stat in RAW_PCT and not pct:
        value, pct = value / 100.0, True
    return {"stat": stat, "value": value, "unit": "pct" if pct else "flat"}


def adventure(content):
    """One table per variant: header "ค่าสเตตัสหลัก <main>", a label row
    (Lv, SCD, <main>, <third>), then Lv 0 and "สมบูรณ์" rows. Only the
    complete row is kept -- it is what a finished pair gives."""
    out = []
    for table in re.findall(r"<table.*?</table>", content, re.S):
        rows = rows_of(table)
        if not rows or not rows[0] or not rows[0][0].startswith("ค่าสเตตัสหลัก"):
            continue
        labels = [STAT_LABELS.get(x) for x in rows[1][1:]]
        done = next((r for r in rows if r and r[0] == "สมบูรณ์"), None)
        if not done or None in labels:
            print("  ! adventure table not read: %r" % rows[:2])
            continue
        main, third = labels[1], labels[2]
        stats = [s for s in (stat_value(k, v) for k, v in zip(labels, done[1:])) if s]
        out.append({
            "name": "Adventure Goggles [%s/%s]" % (main, third),
            "nameTh": "แว่นนิรภัยแอดเวนเจอร์ [%s/%s]" % (main, third),
            "levels": [{"upgrade": 0, "stats": stats}],
        })
    return out


def kaiser(content):
    """One table holds all five variants, each opened by a 1-cell title row
    "... แว่นตาของดิจิมอนไกเซอร์ [<stat>]", a label row, then Lv 1..10."""
    out = []
    for table in re.findall(r"<table.*?</table>", content, re.S):
        if "แว่นตาของดิจิมอนไกเซอร์ [" not in text(table):
            continue
        cur, labels = None, None
        for row in rows_of(table):
            title = re.search(r"แว่นตาของดิจิมอนไกเซอร์ \[(\w+)\]", row[0]) if len(row) == 1 else None
            if title:
                key = title.group(1)
                cur = {"name": "Digimon Kaiser's Goggles [%s]" % key,
                       "nameTh": "แว่นตาของดิจิมอนไกเซอร์ [%s]" % key, "levels": []}
                out.append(cur)
                labels = None
                continue
            if cur is None:
                continue
            if all(x in STAT_LABELS for x in row) and row:
                labels = [STAT_LABELS[x] for x in row]
                continue
            lv = re.match(r"^Lv\s*(\d+)$", row[0]) if row else None
            if lv and labels:
                stats = [s for s in (stat_value(k, v) for k, v in zip(labels, row[1:])) if s]
                cur["levels"].append({"upgrade": int(lv.group(1)), "stats": stats})
    return [k for k in out if k["levels"]]


def tamer(content):
    """One table: "แว่นตาของเทมเมอร์ Lv <n>" rows and a complete row, each
    cell "AT +50 / EXP +5% / HP+100". vplay says the numbers are the TOP of a
    random roll, so the items are marked ranged."""
    lv_rows, complete = [], None
    for table in re.findall(r"<table.*?</table>", content, re.S):
        for row in rows_of(table):
            if len(row) != 2:
                continue
            lv = re.match(r"^แว่นตาของเทมเมอร์ Lv\s*(\d+)$", row[0])
            stats = []
            for part in row[1].split("/"):
                m = re.match(r"^\s*([A-Z]+)\s*\+\s*([\d.]+)\s*(%?)\s*$", part)
                if m:
                    stats.append({"stat": m.group(1), "value": float(m.group(2)),
                                  "unit": "pct" if m.group(3) else "flat"})
            if lv:
                lv_rows.append({"upgrade": int(lv.group(1)), "stats": stats})
            elif row[0] == "แว่นตาของเทมเมอร์ที่สมบูรณ์":
                complete = stats
    out = []
    if lv_rows:
        out.append({"name": "Tamer’s Goggles", "nameTh": "แว่นตาของเทมเมอร์",
                    "ranged": True, "levels": lv_rows})
    if complete:
        out.append({"name": "Complete Tamer’s Goggles",
                    "nameTh": "แว่นตาของเทมเมอร์ที่สมบูรณ์", "ranged": True,
                    "levels": [{"upgrade": 0, "stats": complete}]})
    return out


def main():
    adv = load_post(ADVENTURE_POST)
    kai = load_post(KAISER_POST)
    tam = load_post(TAMER_POST)
    items = (adventure(adv["content"]["rendered"]) + kaiser(kai["content"]["rendered"])
             + tamer(tam["content"]["rendered"]))
    write_stamped(OUT, {
        "fetched_at": date.today().isoformat(),
        "source": [adv["link"], kai["link"], tam["link"]],
        "note": ("Thai-server goggles; CT/EV printed without % are raw (100 per 1%). "
                 "Adventure Goggles keep only the complete row."),
        "items": items,
    }, "fetched_at")
    print("wrote %s" % OUT.relative_to(PROJ))
    print("  adventure %d  kaiser %d  tamer %d"
          % (sum(1 for i in items if i["name"].startswith("Adventure")),
             sum(1 for i in items if i["name"].startswith("Digimon Kaiser")),
             sum(1 for i in items if "Tamer" in i["name"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
