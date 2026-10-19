"""Pull every "new dungeon" section out of the cached TH patch posts (offline).

Most TH dungeons never got a post of their own: they ship as one numbered item
inside a patch note ("6. เพิ่มดันเจี้ยนใหม่ : ด้านหลังของอาณาจักร"). This reads
cache/th_view_*.html (fetched by scan_th_patch_digimon.py) and writes

  data/th_patch_dungeons.json
    { "scanned": N, "dungeons": [
        { "name", "url", "date", "location", "npc", "req", "pass_item",
          "party", "monsters": [{"name", "title", "level"}],
          "rewards": [{"item", "rate", "qty"}], "clear_reward" } ] }

scan_dungeons.py merges these into data/dungeons.json.

Where a section ends: vplay colours each top-level heading of a post the same
way (orange, purple, cyan ...) and the body text black, so a section runs from
its heading to the next paragraph in the heading's colour.
"""

import html as html_lib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builders"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fetchers"))
from fetch_dungeons_th import slug_of  # noqa: E402
from scan_th_patch_digimon import parse_thai_date  # noqa: E402
from stamped_json import write_stamped  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
OUT = PROJ / "data" / "th_patch_dungeons.json"

BLOCK_RE = re.compile(r"<(p|figure|table|ul|ol|h[1-6])\b([^>]*)>(.*?)</\1>", re.S)
BUTTON_RE = re.compile(r'<a\b[^>]*wp-block-button__link[^>]*href="([^"]+)"')
HEADING_RE = re.compile(
    r"^(?:\d+\s*\.\s*)?(?:อัพเดทและ)?(?:เพิ่ม)?ดันเจี้ยนใหม่\s*(?:[:：–-]\s*|\s+)(.+)$")
TIER_HEADING_RE = re.compile(r"^(?:\d+\s*\.\s*)?(?:เพิ่ม)?ดันเจี้ยน(?!ใหม่)(.*ระดับ.*)$")
COLOR_RE =re.compile(r"\bhas-([a-z-]+)-color\b")
NOT_COLORS = {"text", "link", "background"}
LEVEL_RE = re.compile(r"เลเวล\s*(?:มากกว่า\s*)?(\d{2,3})|Lv\.?\s*(\d{2,3})")
PARTY_RE = re.compile(r"(\d+)\s*คน")
# A black heading (one post colours its headings black) cannot be told from
# body text by colour; these sub-headings appear inside a dungeon section.
INNER_LABELS = ("รายละเอียด", "มอนสเตอร์", "ของรางวัล", "ไอเทม", "เงื่อนไข", "ข้อมูล")


def text_of(fragment):
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = html_lib.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"[ \t ]+", " ", t).strip()


def color_of(attrs):
    return next((c for c in COLOR_RE.findall(attrs) if c not in NOT_COLORS), None)


def table_rows(fragment):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", fragment, re.S):
        cells = [re.sub(r"\s+", " ", text_of(c)).strip()
                 for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
        if any(cells):
            rows.append(cells)
    return rows


def blocks(raw):
    m = re.search(r"entry-content[^>]*>(.*)", raw, re.S)
    body = m.group(1) if m else raw
    out = []
    # "More details" usually sits in a button block outside any <p>, so the
    # buttons are picked up separately and slotted in by position.
    found = [(b.start(), b) for b in BLOCK_RE.finditer(body)]
    found += [(a.start(), a) for a in BUTTON_RE.finditer(body)]
    for _, b in sorted(found, key=lambda x: x[0]):
        if b.re is BUTTON_RE:
            out.append({"kind": "link", "links": [b.group(1)]})
            continue
        tag, attrs, inner = b.groups()
        if tag in ("figure", "table"):
            rows = table_rows(inner)
            if rows:
                out.append({"kind": "table", "rows": rows})
            continue
        t = text_of(inner)
        if t:
            out.append({"kind": "text", "text": t, "color": color_of(attrs),
                        "strong": bool(re.fullmatch(r"\s*<(strong|b)>.*</\1>\s*", inner, re.S)),
                        "links": re.findall(r'<a\b[^>]*href="([^"]+)"', inner)})
    return out


def detail_link(sec):
    for b in sec:
        for href in b.get("links") or []:
            if re.match(r"https?://(?:www\.)?vplay\.in\.th/[^/?#]+/?$", href) and "wp-content" not in href:
                return href
    return None


def is_heading(b):
    if b["kind"] != "text" or len(b["text"]) > 100 or b["text"].startswith("เตรียมตัว"):
        return None
    text = re.sub(r"\s+", " ", b["text"])
    m = HEADING_RE.match(text)
    if m:
        return m.group(1).strip()
    # Older posts (2019-2022) name the dungeon straight away, with its tier:
    # "3. ดันเจี้ยนเปลวเพลิงที่ลุกโชน [ระดับยาก]". The same words also turn up
    # in body text, so only a bold, coloured heading line counts.
    if b.get("strong") and b.get("color") not in (None, "black", "vivid-red"):
        m = TIER_HEADING_RE.match(text)
        if m:
            return re.sub(r"^ระดับง่าย\s*-\s*(.+)$", r"\1 (ระดับง่าย)", m.group(1).strip())
    return None


def section_end(bl, start):
    head = bl[start]
    for j in range(start + 1, len(bl)):
        b = bl[j]
        if b["kind"] != "text":
            continue
        nxt = is_heading(b)
        # Some posts repeat the heading as a banner line right under it.
        if nxt and re.sub(r"\W+", "", nxt) != re.sub(r"\W+", "", is_heading(head) or ""):
            return j
        if nxt:
            continue
        if (head["color"] not in (None, "black") and b["color"] == head["color"]
                and len(b["text"]) < 100):
            return j
        # A post can colour one heading differently from the rest (the
        # Neverland one is cyan, the "new gear" one after it orange). Notes
        # inside a section are red, so red alone does not end it.
        if (b["strong"] and len(b["text"]) < 100
                and not any(k in b["text"] for k in INNER_LABELS)
                and b["color"] not in (None, "black", "vivid-red")):
            return j
    return len(bl)


def kv_value(rows, *keys):
    for r in rows:
        if len(r) >= 2 and any(k in r[0] for k in keys):
            v = " ".join(c for c in r[1:] if c).strip()
            return v if v.strip("–- ") else None     # "–" is the table's "none"
    return None


def first_match(lines, pattern):
    for ln in lines:
        m = re.search(pattern, ln)
        if m:
            return m.group(1).strip(" :")
    return None


def parse_section(name, sec):
    lines = []
    for b in sec:
        if b["kind"] == "text":
            lines += [ln.strip() for ln in b["text"].split("\n") if ln.strip()]
    tables = [b["rows"] for b in sec if b["kind"] == "table"]
    kv = [r for t in tables for r in t]

    d = {"name": re.sub(r"\s+", " ", name)}
    loc = first_match(lines, r"^(?:ที่ตั้ง|ตำแหน่ง)\S*\s*:\s*(.+)") or \
        first_match(lines, r"ในแผนที่\s*(.+?)(?:\s*$|\s+และ)")
    d["location"] = re.sub(r"^แผนที่\s*", "", loc) if loc else None
    # "เงื่อนไขการปรากฏตัวของ NPC : ..." is a quest, not the NPC; anchoring on
    # a line that starts with NPC keeps it out.
    d["npc"] = first_match(lines, r"^NPC[^:]{0,25}:\s*(.+)") or \
        first_match([ln for ln in lines if "เข้า" in ln], r"(?:ที่|จาก)\s*(NPC\s*<[^>]+>\s*\S+)")
    cond = " ".join(" ".join(r[1:]) for r in kv if len(r) >= 2 and "เงื่อนไข" in r[0]) + " " + \
        " ".join(ln for ln in lines if "เงื่อนไข" in ln or "เลเวล" in ln or "Lv" in ln)
    lv = LEVEL_RE.search(cond) or re.search(r"ดิจิมอน\s*(\d{2,3})\s*ขึ้นไป", cond)
    d["req"] = "Lv.%s+" % next(g for g in lv.groups() if g) if lv else None
    d["pass_item"] = kv_value(kv, "ใช้ไอเทม") or \
        first_match(lines, r"(บัตรผ่าน(?!จะ|ได้|ที่|สามารถ|มี)\S[^\n]{0,60})")
    party = kv_value(kv, "จำนวนคน") or first_match(lines, r"(\d+\s*คน)")
    pm = PARTY_RE.search(party or "")
    d["party"] = int(pm.group(1)) if pm else None
    d["clear_reward"] = kv_value(kv, "ของรางวัลเคลียร์", "ของรางวัลเมื่อผ่าน")

    monsters, rewards = [], []
    for t in tables:
        head = " ".join(t[0])
        if ("มอนสเตอร์" in head or "ชื่อดิจิมอน" in head) and len(t[0]) >= 2:
            for r in t[1:]:
                lvl = next((int(x) for x in reversed(r) if re.fullmatch(r"\d{2,3}", x)), None)
                name, title = r[0], (r[1] if len(r) >= 2 else "")
                # Stage tables put the floor first ("ระดับ 3" | บิชอปเชสมอน).
                if re.fullmatch(r"(ระดับ\s*\d+|[–-])", name) and title:
                    name, title = title, (name if name.strip("–- ") else "")
                elif len(r) <= 2:
                    title = ""
                title = title.strip("<>() ")
                if "กล่อง" in name:
                    continue
                monsters.append({"name": name, "title": title if title not in ("", "–", "-") else None,
                                 "level": lvl})
        elif "รายการไอเทม" in head:
            hdr = t[0]
            item_col = next(i for i, c in enumerate(hdr) if "รายการไอเทม" in c)
            rate_col = next((i for i, c in enumerate(hdr) if "%" in c or "ความเป็นไปได้" in c), None)
            box = None
            for r in t[1:]:
                if not r or r[0] == "รายการไอเทม":
                    continue
                # A leading "box" column spans its rows, so later rows are
                # shorter than the header; line them up from the right.
                off = len(hdr) - len(r)
                cell = lambda c: r[c - off] if c is not None and 0 <= c - off < len(r) else None
                if off == 0 and item_col > 0:
                    box = r[0]
                if not cell(item_col):
                    continue
                rewards.append({"item": cell(item_col), "rate": cell(rate_col),
                                "qty": r[-1] if len(r) > 1 else None, "box": box})
    # Others put them in the details table, one "<name> <title> เลเวล N" after another.
    if not monsters:
        listed = kv_value(kv, "มอนสเตอร์") or ""
        for m in re.finditer(r"(\S[^<]*?)\s*(<[^>]+>)?\s*เลเวล\s*(\d{2,3})", listed):
            monsters.append({"name": m.group(1).strip(), "title": (m.group(2) or "").strip("<>() ") or None,
                             "level": int(m.group(3))})
        if not monsters and listed and len(listed) < 60:
            monsters.append({"name": listed, "title": None, "level": None})
    # Older posts list monsters as text rows "<name> <title> เลเวล 126".
    if not monsters:
        for ln in lines:
            m = re.match(r"^(.+?)\s*(<[^>]+>)?\s*เลเวล\s*(\d{2,3})$", ln)
            # Numbered lines are entry conditions ("1. ดิจิมอนคู่หูต้องมีเลเวล 99").
            if m and not re.match(r"^\d+\.", ln) and "ต้อง" not in ln and "ดิจิมอน" not in m.group(1)[:8]:
                monsters.append({"name": m.group(1).strip(), "title": (m.group(2) or "").strip("<>() ") or None,
                                 "level": int(m.group(3))})
    # The four-holy-beast hard modes name one boss per reward box:
    # "5.1 ให้จัดการ เบิร์ดดรามอน เพื่อรับรางวัล กล่องแห่งเปลวเพลิง(...)".
    if not monsters:
        for ln in lines:
            m = re.match(r"^\d+\.\d+\s*(?:ให้)?(?:จัดการ)?\s*(\S+)\s+เพื่อรับรางวัล", ln)
            if m:
                monsters.append({"name": m.group(1), "title": None, "level": None})
    # Pages with an easy and a hard table list the same room twice.
    uniq = []
    for m in monsters:
        if m not in uniq:
            uniq.append(m)
    d["monsters"] = uniq
    d["rewards"] = rewards
    return d


def fill_from_detail(d):
    """Fill what the patch section left empty from the page it links to
    (fetched by fetch_dungeons_th.py). The patch section wins where both say
    something: it is what shipped on that date."""
    if not d.get("detail_url"):
        return False
    page = CACHE / ("th_dungeon_%s.html" % slug_of({"url": d["detail_url"], "id": d["name"]}))
    if not page.exists():
        return False
    raw = page.read_text(encoding="utf-8")
    raw = raw.split("</article>", 1)[0]     # drop the sidebar and footer
    more = parse_section(d["name"], blocks(raw))
    changed = False
    for k, v in more.items():
        if k != "name" and v and not d.get(k):
            d[k] = v
            changed = True
    return changed


def main():
    files = sorted(CACHE.glob("th_view_*.html"))
    if not files:
        sys.exit("no cache/th_view_*.html -- run scanners/scan_th_patch_digimon.py first; "
                 "%s left untouched" % OUT.relative_to(PROJ))
    found = {}
    for f in files:
        raw = f.read_text(encoding="utf-8")
        canon = re.search(r'<link rel="canonical" href="([^"]+)"', raw)
        url = canon.group(1) if canon else "https://www.vplay.in.th/%s/" % f.stem[len("th_view_"):]
        bl = blocks(raw)
        date = parse_thai_date(" ".join(b["text"] for b in bl[:40] if b["kind"] == "text")) \
            or parse_thai_date(text_of(raw))
        for i, b in enumerate(bl):
            name = is_heading(b)
            if not name:
                continue
            sec = bl[i + 1:section_end(bl, i)]
            d = parse_section(name, sec)
            d["detail_url"] = detail_link(sec)
            # A teaser names the dungeon and nothing else; the release post
            # carries the details, so an empty one is not worth a card.
            # A tier heading ("[ระดับยาก]") is the dungeon's own section, never
            # a teaser, even when it only describes a daily-rotating roster.
            tiered = not HEADING_RE.match(re.sub(r"\s+", " ", b["text"]))
            if not (tiered or d["req"] or d["monsters"] or d["rewards"] or d["npc"] or d["detail_url"]):
                continue
            d["url"], d["date"] = url, date
            key = re.sub(r"\W+", "", d["name"])
            # The same post can be cached under an alias slug too.
            if key not in found or len(url) > len(found[key]["url"]):
                found[key] = d

    filled = 0
    for d in found.values():
        if fill_from_detail(d):
            filled += 1

    out = sorted(found.values(), key=lambda d: d["date"] or "")
    payload = {"fetched_at": __import__("datetime").date.today().isoformat(),
               "scanned": len(files), "dungeons": out}
    write_stamped(OUT, payload, "fetched_at")
    print("wrote %s: %d dungeons from %d posts" % (OUT.relative_to(PROJ), len(out), len(files)))
    for d in out:
        print("  %s  %-36s req=%-7s party=%-4s npc=%s mon=%d rew=%d" % (
            d["date"], d["name"][:36], d["req"], d["party"], (d["npc"] or "")[:28],
            len(d["monsters"]), len(d["rewards"])))


if __name__ == "__main__":
    main()
