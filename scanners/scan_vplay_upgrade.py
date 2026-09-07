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

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

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
QUERIES = ["ระดับการเสริมแกร่ง", "เสริมแกร่ง", "ค่าสเตตัส"]

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
}
PCT_STATS = {"CT", "EV", "BL", "Skill DMG", "Final DMG", "EXP"}


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


def parse_blocks(html):
    """Pull every (item name, [levels]) pair out of one post."""
    items = []
    for table in re.findall(r"<table.*?</table>", html, re.S):
        if LEVEL_HEADER not in table:
            continue
        rows = re.findall(r"<tr[^>]*>.*?</tr>", table, re.S)
        name = None
        stat_names = []
        levels = []
        for row in rows:
            c = cells(row)
            if len(c) == 1:
                # a heading row closes the previous block and opens the next
                if name and levels:
                    items.append({"name": name, "levels": levels})
                title = c[0]
                name = (title[len(TITLE_PREFIX):].strip()
                        if title.startswith(TITLE_PREFIX) else None)
                stat_names, levels = [], []
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
                val, pct = got
                stats.append({
                    "stat": stat,
                    "unit": "pct" if (pct or stat in PCT_STATS) else "flat",
                    "value": val,
                })
            if stats:
                levels.append({"upgrade": lvl, "stats": stats})
        if name and levels:
            items.append({"name": name, "levels": levels})
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
        if LEVEL_HEADER not in html:
            continue
        for block in parse_blocks(html):
            key = block["name"]
            if key in seen:      # the same table is reposted in the patch note
                continue
            seen.add(key)
            block["post"] = url
            out.append(block)
    OUT.write_text(json.dumps(
        {"fetched_at": date.today().isoformat(), "source": "vplay.in.th",
         "items": sorted(out, key=lambda x: x["name"])},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    lv = sum(len(i["levels"]) for i in out)
    print("wrote %s" % OUT.relative_to(PROJ))
    print("  items %d  levels %d" % (len(out), lv))
    for i in out:
        print("    %-46s %2d levels" % (i["name"][:46], len(i["levels"])))


if __name__ == "__main__":
    main()
