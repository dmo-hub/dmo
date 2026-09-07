"""Read the Double ChipSet tables off vplay.in.th.

Output: data/chip_double.json

Why this exists on top of scan_chipsets.py: dmowiki records one value per
grade, but the Thai post shows a Double ChipSet carries TWO sets --

    "ดับเบิ้ลชิปเซ็ท ประกอบด้วย ค่าความสามารถหลักและค่าความสามารถรอง
     สำหรับค่าคุณลักษณะดิจิมอน"

    (a Double ChipSet carries a PRIMARY and a SECONDARY stat set, for the
     DIGIMON's attributes)

The primary numbers match dmowiki's family chipset exactly (R16 HP 2151, AT
306 ...), so this file adds the secondary set -- roughly 60% of the primary --
which dmowiki does not record at all.

That last clause also settles a question left open by B08: chipset stats feed
the DIGIMON, so the solver may score them.

Table shape: each grade gets a heading ("ดับเบิ้ลชิปเซ็ท R17") followed by
two 2-column tables, primary then secondary, each row "STAT | value".
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache_vplay"
OUT = PROJ / "data" / "chip_double.json"

POST = ("https://www.vplay.in.th/%E0%B8%94%E0%B8%B1%E0%B8%9A%E0%B9%80%E0%B8%9A"
        "%E0%B8%B4%E0%B9%89%E0%B8%A5%E0%B8%8A%E0%B8%B4%E0%B8%9B%E0%B9%80%E0%B8"
        "%8B%E0%B9%87%E0%B8%97-r16-r18/")

PRIMARY = "สเตตัสหลัก"     # primary
SECONDARY = "สเตตัสรอง"          # secondary
GRADE_RE = re.compile(r"R(\d+)")
NAME_TH = "ดับเบิ้ลชิปเซ็ท"

STATS = {"HP", "DS", "AT", "DE", "HT", "EV", "CT", "BL"}
PCT = {"CT", "EV", "BL"}


def clean(html):
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", txt).strip()


def cache_path(url):
    import hashlib
    return CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")


def parse_double(html):
    """Pull (grade, primary, secondary) out of the post.

    The page lays each grade out as TWO parallel columns: one row carries both
    labels ("สเตตัสหลัก" | "สเตตัสรอง"), and the row
    below carries the two tables in the same order. The labels therefore do NOT
    each sit above their own table -- walking the document and taking the
    nearest preceding label lands on the second one every time, which is how
    the primary numbers first came out tagged as secondary.

    Pairing is positional instead: within one grade, the first stat table is
    the primary and the second is the secondary.
    """
    out = []
    # Split the document at each grade heading, so tables cannot leak across.
    # R16 splits the name and the grade across two <strong> tags; R17 and
    # R18 keep both inside one. Matching only the first shape found a
    # single grade and silently dropped the other two.
    heads = list(re.finditer(
        r"<strong>\s*" + re.escape(NAME_TH) +
        r"\s*(?:</strong>\s*<strong>)?\s*R(\d+)\s*</strong>", html))
    for i, h in enumerate(heads):
        grade = int(h.group(1))
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(html)
        chunk = html[h.end():stop]
        sets = []
        for tb in re.findall(r"<table.*?</table>", chunk, re.S):
            stats = {}
            for row in re.findall(r"<tr[^>]*>.*?</tr>", tb, re.S):
                c = [clean(x) for x in
                     re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
                if len(c) != 2:
                    continue
                name = c[0].strip().upper()
                if name not in STATS:
                    continue
                v = re.match(r"^\s*\+?\s*(\d+(?:\.\d+)?)\s*(%?)\s*$", c[1])
                if not v:
                    continue
                value = float(v.group(1))
                unit = "pct" if (v.group(2) or name in PCT) else "flat"
                if unit == "pct" and not v.group(2):
                    # vplay writes percentages here as hundredths of a percent
                    # and drops the % sign: "CT 400" is dmowiki's "CT +4%".
                    # Verified against every grade -- flat stats match 1:1
                    # while CT and EV are exactly 100x on R16, R17 and R18.
                    value = value / 100.0
                stats[name] = {"value": value, "unit": unit}
            if stats:
                sets.append(stats)
        if not sets:
            continue
        rec = {"grade": grade, "id": "chip-double-r%d" % grade,
               "name": "Double ChipSet R%d" % grade, "axis": "digimon",
               "primary": sets[0]}
        if len(sets) > 1:
            rec["secondary"] = sets[1]
        out.append(rec)
    return sorted(out, key=lambda r: r["grade"])


def main():
    path = cache_path(POST)
    if not path.exists():
        print("missing %s -- fetch the post first" % path.relative_to(PROJ))
        return 1
    html = path.read_text(encoding="utf-8", errors="replace")
    items = parse_double(html)
    OUT.write_text(json.dumps({
        "fetched_at": date.today().isoformat(),
        "source": POST,
        "note": ("a Double ChipSet grants a primary AND a secondary stat set; "
                 "the post states both feed the DIGIMON's attributes"),
        "items": items,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("wrote %s" % OUT.relative_to(PROJ))
    print("  grades %d" % len(items))
    for it in items:
        p = it.get("primary", {})
        s = it.get("secondary", {})
        print("    R%-3d primary %d stats (HP %s)  secondary %d stats (HP %s)"
              % (it["grade"], len(p), p.get("HP", {}).get("value"),
                 len(s), s.get("HP", {}).get("value")))
    missing = [it["grade"] for it in items
               if "primary" not in it or "secondary" not in it]
    if missing:
        print("  WARN  grades missing one of the two sets: %s" % missing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
