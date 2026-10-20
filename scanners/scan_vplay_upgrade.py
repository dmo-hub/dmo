"""Read the per-level upgrade stat tables off vplay.in.th (Thai DMO server).

Output: data/upgrade_levels.json
  {
    "fetched_at": "YYYY-MM-DD",
    "source": "vplay.in.th",
    "items": [
      {"name": "Magnetic ID Card - Heaven Wings [AT]",
       "post": "https://...",
       "levels": [{"upgrade": 0, "stats": [{"stat": "AT", "unit": "flat", "value": 50.0}]}, ...]}
    ]
  }

Why vplay and not dmowiki: dmowiki records these as BANDS ("0-4", "5-9"),
while vplay lists every level 0..15 individually. The user locks a specific
level per item, so the per-level values are what the optimizer needs.

Shape of the source table (nothing like dmowiki's):
  * several item blocks live inside ONE <table>, separated by a 1-cell
    heading row ("รายละเอียดค่าสเตตัสของ<ชื่อไอเทม>")
  * the "พื้นฐาน" (base) row has 7 cells and NAMES each stat
  * levels 1..15 have only 4 cells -- bare values that inherit the stat
    names from the base row above them
  * "–" means "no value", not zero
"""

import re
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builders"))
from stamped_json import write_stamped  # noqa: E402

import requests

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache_vplay"
OUT = PROJ / "data" / "upgrade_levels.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
SEARCH = ("https://www.vplay.in.th/wp-json/wp/v2/search"
          "?search={q}&per_page=50&page={page}")
# Only these two turned up real upgrade tables across 279 searched posts;
# the wider terms match craft tables and event calendars instead.
QUERIES = ["ระดับการเสริมแกร่ง", "เสริมแกร่ง", "ค่าสเตตัส", "ประเภทสเตตัส"]

LEVEL_HEADER = "ระดับการเสริมแกร่ง"
BASE_ROW = "พื้นฐาน"
TITLE_PREFIX = "รายละเอียดค่าสเตตัสของ"
NO_VALUE = {"–", "-", "", "0"}

# Thai stat names, plus the Latin ones the tables mix in.
STAT_ALIASES = {
    "at": "AT", "hp": "HP", "ht": "HT", "ct": "CT", "ds": "DS",
    "de": "DE", "ev": "EV", "bl": "BL", "exp": "EXP",
    "พลังโจมตีสกิล": "Skill DMG",
    "ความเสียหายสุดท้าย": "Final DMG",
    "พลังโจมตี": "AT",
    "พลังชีวิต": "HP",
    "ความแม่นยำ": "HT",
    "คริติคอล": "CT",
    "ความเร็วโจมตี": "AS",
    # Frontier (Spirit) gear labels. "อัตราโจมตี" is hit rate, not attack:
    # summed over its two options at +15 it gives dmowiki's HT 5500.
    "อัตราโจมตี": "HT",
    "โจมตี": "AT",
    "ป้องกัน": "DE",
    "พลังโจมตีคริติคอล": "CT DMG",
    "ความเร็วในการโจมตี": "AS",
    "ความเร็วในการเคลื่อนที่": "Speed",
    "เป็นมิตร": "Affinity",
    # vplay's "SCD" is skill damage: dmowiki prints "Skill Damage %" in the
    # same option slot of the same items
    "scd": "Skill DMG",
    "ms": "Speed",
    # Daisuke/Takeru/Miyako gear labels.
    "โจมตีแบบคริติคอล": "CT",
    "พลังโจมตีแบบคริติคอล": "CT DMG",
    "การโจมตี": "AT",
    "ค่าป้องกัน": "DE",
    "max hp": "HP",
    "max ds": "DS",
    "ความเร็ว": "Speed",
}
PCT_STATS = {"CT", "EV", "BL", "Skill DMG", "Final DMG", "EXP", "CT DMG"}

# Frontier gear: one table holds a block per slot, each opened by
# [LEVEL_HEADER, <slot>] instead of a 1-cell title. The table never names the
# piece, so the slot maps to the piece name its own post lists; every element
# (Fire/Light/Ice/Wind/Thunder) shares the block.
SLOT_PIECES = {
    "อุปกรณ์ส่วนหัว": "หมวกเกราะแห่งสปิริต",
    "อุปกรณ์เครื่องประดับ": "เครื่องประดับแห่งสปิริต",
    "อุปกรณ์ส่วนเสื้อ": "เสื้อแห่งสปิริต",
    "อุปกรณ์กางเกง": "กางเกงแห่งสปิริต",
    "อุปกรณ์ส่วนมือ": "ถุงมือแห่งสปิริต",
    "อุปกรณ์ส่วนรองเท้า": "รองเท้าแห่งสปิริต",
}

# Daisuke/Takeru/Miyako gear: the same one-table-many-blocks shape, opened by
# [CHAR_LEVEL_HEADER, <slot>]. One block serves all three sets (their pieces
# share stats), and the shin tier gets its own block with SHIN in front of
# the slot. The slot words overlap SLOT_PIECES, so the header word is what
# tells the two posts apart.
CHAR_LEVEL_HEADER = "เลเวล"
SHIN = "(ชิน)"
CHAR_SLOTS = {
    "อุปกรณ์ส่วนหัว": "head",
    "อุปกรณ์เครื่องประดับ": "fashion",
    "อุปกรณ์เสื้อ": "top",
    "อุปกรณ์กางเกง": "bottom",
    "อุปกรณ์ส่วนมือ": "gloves",
    "อุปกรณ์รองเท้า": "shoes",
}
CHAR_PIECE = "ชุดไดสุเกะ/ทาเครุ/มิยาโกะ : "


def char_block(c):
    """[CHAR_LEVEL_HEADER, "(ชิน) อุปกรณ์ส่วนหัว"] -> (name, slot, shin)."""
    if len(c) != 2 or c[0] != CHAR_LEVEL_HEADER:
        return None
    label = c[1]
    shin = label.startswith(SHIN)
    if shin:
        label = label[len(SHIN):].strip()
    slot = CHAR_SLOTS.get(label)
    if not slot:
        return None
    return (SHIN + " " if shin else "") + CHAR_PIECE + label, slot, shin
OPTION_ROW = "ออฟชั่น"

# Four Holy Beasts gear: one table per piece, a column per grade, and a
# second stat restarting at Lv.0 under a repeated header row. NA sells these
# under the English names below (its Four Holy Beasts fragment exchange);
# dmowiki has no page for them yet, so this is the only stat source.
GRADE_HEADER = ["ประเภทไอเทม", "ประเภทสเตตัส"]
GRADE_PIECE_EN = {
    "มงกุฎศักดิ์สิทธิ์ของฟานลอนมอน": "Noble Head Ornament of Huanglongmon",
    "เสื้อคลุมขนนกฟีนิกซ์ของซูเซมอน": "Phoenix Feather Robe of Zhuqiaomon",
    "เกราะแห่งห้วงมหาสมุทรของเชนวูมอน": "Abyssal Armor of Xuanwumon",
    "กางเกงแห่งสายฟ้าของจินลอนมอน": "Thunderbolt Bottom of Qinglongmon",
    "สนับมือศักดิ์สิทธิ์ของไบฟูมอน": "Immaculate Gauntlet of Baihumon",
    "รองเท้าแห่งสี่สัตว์เทพ": "Shoes of the Four Holy Beasts",
}


def clean(html):
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&")
    # The same item is written with an en dash in one post and the &#8211;
    # entity in another. Left alone, the two spellings look like two items
    # and the de-dupe by name never fires.
    txt = txt.replace("&#8211;", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", txt).strip()


def canon_stat(label):
    key = label.strip().lower()
    if key in STAT_ALIASES:
        return STAT_ALIASES[key]
    key2 = re.sub(r"[^a-z]", "", key)
    return STAT_ALIASES.get(key2)


def cells(row_html):
    return [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)]


def parse_value(text):
    """"+1500" -> 1500.0 flat; "12%" -> 12.0 pct; "–" -> None."""
    if text in NO_VALUE:
        return None
    m = re.match(r"^\s*\+?\s*(\d+(?:\.\d+)?)\s*(%?)\s*$", text)
    if not m:
        return None
    return float(m.group(1)), bool(m.group(2))


def raw_to_pct(stat, val, pct):
    """A CT value printed without "%" is the game's raw number, 100 per 1%
    (ID Card "CT +1500" is 15%; the Spirit Helmet table prints "10%")."""
    return (val / 100.0, True) if stat == "CT" and not pct else (val, pct)


def parse_blocks(html):
    """Pull every (item name, [levels]) pair out of one post."""
    items = []
    for table in re.findall(r"<table.*?</table>", html, re.S):
        if LEVEL_HEADER not in table and CHAR_LEVEL_HEADER not in table:
            continue
        rows = re.findall(r"<tr[^>]*>.*?</tr>", table, re.S)
        name = None
        tags = {}
        stat_names = []
        levels = []
        awaiting_labels = False
        for row in rows:
            c = cells(row)
            if len(c) == 2 and c[0] == LEVEL_HEADER and c[1] in SLOT_PIECES:
                if name and levels:
                    items.append({"name": name, "levels": levels, **tags})
                name, tags, stat_names, levels = SLOT_PIECES[c[1]], {}, [], []
                awaiting_labels = True
                continue
            block = char_block(c)
            if block:
                if name and levels:
                    items.append({"name": name, "levels": levels, **tags})
                name, stat_names, levels = block[0], [], []
                tags = {"char_slot": block[1], "shin": block[2]}
                awaiting_labels = True
                continue
            if awaiting_labels:
                # "ออฟชั่น 1/2/3" first, then the row that names each option
                if c and not c[0].startswith(OPTION_ROW):
                    # the character-gear post opens this row with a label
                    # cell; left in, every stat would pair with the value
                    # one column to its right
                    stat_names = c[1:] if c[0] == GRADE_HEADER[1] else c
                    awaiting_labels = False
                continue
            if len(c) == 1:
                # a heading row closes the previous block and opens the next
                if name and levels:
                    items.append({"name": name, "levels": levels, **tags})
                title = c[0]
                name = (title[len(TITLE_PREFIX):].strip()
                        if title.startswith(TITLE_PREFIX) else None)
                tags, stat_names, levels = {}, [], []
                continue
            if not c:
                continue
            if c[0] == LEVEL_HEADER:
                # header pairs up as (type1, value1, type2, value2, ...)
                stat_names = [c[i] for i in range(1, len(c), 2)]
                continue
            if not stat_names:
                continue
            if c[0] == BASE_ROW:
                # the base row carries the stat names AND the level-0 values
                stat_names = [c[i] for i in range(1, len(c), 2)]
                values = [c[i] for i in range(2, len(c), 2)]
                lvl = 0
            elif re.fullmatch(r"\d{1,2}", c[0]):
                lvl = int(c[0])
                values = c[1:]
            else:
                continue
            stats = []
            for label, raw in zip(stat_names, values):
                stat = canon_stat(label)
                if not stat:
                    continue
                got = parse_value(raw)
                if got is None:
                    continue
                val, pct = raw_to_pct(stat, *got)
                unit = "pct" if (pct or stat in PCT_STATS) else "flat"
                # Frontier options repeat a stat (CT twice on the helmet);
                # the game adds them, as the registry does.
                same = next((s for s in stats
                             if s["stat"] == stat and s["unit"] == unit), None)
                if same:
                    same["value"] += val
                    continue
                stats.append({"stat": stat, "unit": unit, "value": val})
            if stats:
                levels.append({"upgrade": lvl, "stats": stats})
        if name and levels:
            items.append({"name": name, "levels": levels, **tags})
    return items


def parse_grade_tables(html):
    """Pull (piece [grade], [levels]) pairs out of the per-grade tables."""
    items = []
    for table in re.findall(r"<table.*?</table>", html, re.S):
        rows = [cells(r) for r in re.findall(r"<tr[^>]*>.*?</tr>", table, re.S)]
        if not rows or rows[0][:2] != GRADE_HEADER:
            continue
        grades = rows[0][3:]
        piece, stat = None, None
        by_grade = {g: {} for g in grades}     # grade -> level -> stats
        for c in rows[1:]:
            if len(c) == len(grades) + 3:
                piece, stat, lvl_cell, values = c[0], c[1], c[2], c[3:]
            elif len(c) == len(grades) + 2:
                stat, lvl_cell, values = c[0], c[1], c[2:]
            elif len(c) == len(grades) + 1:
                lvl_cell, values = c[0], c[1:]
            else:
                continue
            m = re.fullmatch(r"Lv\.?\s*(\d{1,2})", lvl_cell)
            key = canon_stat(stat or "")
            if not (m and key and piece):
                continue
            lvl = int(m.group(1))
            for grade, raw in zip(grades, values):
                got = parse_value(raw)
                stats = by_grade[grade].setdefault(lvl, [])
                if got is None:
                    continue
                val, pct = raw_to_pct(key, *got)
                stats.append({"stat": key,
                              "unit": "pct" if (pct or key in PCT_STATS) else "flat",
                              "value": val})
        if not piece:
            continue
        for grade in grades:
            levels = [{"upgrade": lvl, "stats": st}
                      for lvl, st in sorted(by_grade[grade].items()) if st]
            if levels:
                item = {"name": "%s [%s]" % (piece, grade), "levels": levels}
                if piece in GRADE_PIECE_EN:
                    item["piece_en"] = GRADE_PIECE_EN[piece]
                items.append(item)
    return items


def cache_path(url):
    import hashlib
    return CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")


def fetch(url):
    p = cache_path(url)
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace")
    text = requests.get(url, headers=HEADERS, timeout=25).text
    CACHE.mkdir(exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    time.sleep(0.25)
    return text


def find_posts():
    urls = {}
    for q in QUERIES:
        for page in (1, 2, 3):
            try:
                r = requests.get(SEARCH.format(q=requests.utils.quote(q), page=page),
                                 headers=HEADERS, timeout=25)
                if r.status_code != 200:
                    break
                data = r.json()
            except Exception:
                break
            if not isinstance(data, list) or not data:
                break
            for it in data:
                urls.setdefault(it["url"], it.get("title", ""))
            if len(data) < 50:
                break
            time.sleep(0.3)
    return urls


def main():
    posts = find_posts()
    print("posts searched: %d" % len(posts))
    out, seen = [], set()
    for url in sorted(posts):
        try:
            html = fetch(url)
        except Exception as exc:
            print("  ERR %s %s" % (url[:60], exc))
            continue
        if LEVEL_HEADER not in html and GRADE_HEADER[1] not in html:
            continue
        for block in parse_blocks(html) + parse_grade_tables(html):
            key = block["name"]
            if key in seen:      # the same table is reposted in the patch note
                continue
            seen.add(key)
            block["post"] = url
            out.append(block)
    write_stamped(OUT, {"fetched_at": date.today().isoformat(), "source": "vplay.in.th",
                        "items": sorted(out, key=lambda x: x["name"])}, "fetched_at")
    lv = sum(len(i["levels"]) for i in out)
    print("wrote %s" % OUT.relative_to(PROJ))
    print("  items %d  levels %d" % (len(out), lv))
    for i in out:
        print("    %-46s %2d levels" % (i["name"][:46], len(i["levels"])))


if __name__ == "__main__":
    main()
