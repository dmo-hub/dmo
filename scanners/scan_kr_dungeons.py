"""Parse cached KR update posts into data/kr_dungeons.json (offline, no network).

KR has no per-dungeon guide page: a dungeon's facts live inside the weekly
"업데이트 안내" post that adds or changes it -- a "[<name>] 던전 기본 정보"
table, a "등장 디지몬 정보" table and "... 클리어 보상" tables. Reads every
cache/kr_view_o*.html (filled by scan_kr_digimon_releases.fetch_detail) and
dates each post from data/kr_news_index.json.

The same dungeon shows up in several posts (added, then rebalanced, then a
reward change), and a change notice carries only what changed. So records are
merged per dungeon name oldest -> newest, a later post overwriting only the
fields it actually states.

    python scanners/scan_kr_dungeons.py
"""

import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
INDEX = PROJ / "data" / "kr_news_index.json"
OUT = PROJ / "data" / "kr_dungeons.json"

POST_URL = "https://www.digimonmasters.com/news/newsBoard_sub.aspx?o={o}&Btype=Update"

BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "table"}


class Flatten(HTMLParser):
    """HTML -> ordered tokens: ("text", line) outside tables, ("row", [cells])."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self.buf = []
        self.cell = None
        self.cells = None
        self.skip = 0

    def flush(self):
        line = clean("".join(self.buf))
        if line:
            self.tokens.append(("text", line))
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "tr":
            self.flush()
            self.cells = []
        elif tag in ("td", "th"):
            self.cell = []
        elif tag in BLOCK_TAGS:
            if self.cell is not None:
                self.cell.append(" ")
            else:
                self.flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th"):
            if self.cell is not None and self.cells is not None:
                self.cells.append(clean("".join(self.cell)))
            self.cell = None
        elif tag == "tr":
            if self.cells:
                cells = [c for c in self.cells if c]
                if cells:
                    self.tokens.append(("row", cells))
            self.cells = None
        elif tag in BLOCK_TAGS and self.cell is None:
            self.flush()

    def handle_data(self, data):
        if self.skip:
            return
        (self.cell if self.cell is not None else self.buf).append(data)


def clean(s):
    return re.sub(r"\s+", " ", unescape(s).replace("\xa0", " ")).strip()


def key(name):
    return re.sub(r"\s+", "", name)


HEAD_RE = re.compile(r"\[(.+?)\]\s*(?:던전\s*기본\s*정보|등장\s*(?:악역\s*)?(?:디지몬|몬스터)\s*정보)")
REWARD_RE = re.compile(r"(.+?)\s*클리어\s*보상")
NAMED_RE = re.compile(r"^(?:-\s*)?던전\s*:\s*\[?(.+?)\]?$")
LOC_RE = re.compile(r"던전\s*위치\s*:\s*(.+)")
NPC_RE = re.compile(r"던전\s*입장\s*NPC\s*:\s*(.+)")
STAGE_RE = re.compile(r"^(?:\d+\s*(?:단계|라운드)?|히든|-)$")
LEVEL_RE = re.compile(r"레벨\s*(\d{2,3})")
HEADER_CELLS = {"구분", "디지몬 이름", "몬스터 이름", "몬스터 목록", "라운드", "아이템 이름", "아이템", "보상"}
HEADER_TAILS = {"개수", "확률", "레벨", "서브 타이틀", "수량", "획득 개수"}


def quest_label(s):
    # Titles nest brackets unevenly ("◎ [파괴와 재생] 추가 클리어 보상").
    s = re.sub(r"[\[\]◎]", " ", s)
    return clean(re.sub(r"\s*추가\s*$", "", clean(s)))


def strip_num(s):
    return re.sub(r"^\d+\.\s*", "", s.strip())


def parse_post(raw):
    """-> {dungeon key: partial record} for one post.

    The "던전 이름" row is the one authoritative name: section titles above
    the tables name the area ("[베르단디 터미널] 던전 정보") or a sub-zone
    ("[로얄 베이스 중심부]"), so monster and reward tables that follow attach
    to the last dungeon named that way rather than to their own title."""
    out = {}
    flat = Flatten()
    flat.feed(raw)
    flat.flush()
    mode, cur, named, quest, seen = None, None, None, None, 0

    def rec(name):
        return out.setdefault(key(name), {"name": name})

    for kind, val in flat.tokens:
        if kind == "text":
            line = strip_num(val)
            m = NAMED_RE.match(line)
            if m:
                named = m.group(1).strip()
                continue
            m = LOC_RE.search(line)
            if m and named:
                rec(named)["location"] = m.group(1).strip()
                continue
            m = NPC_RE.search(line)
            if m and named:
                rec(named)["npc"] = m.group(1).strip()
                continue
            m = LEVEL_RE.search(line)
            if m and named and "입장 조건" in line:
                rec(named).setdefault("req", f"Lv.{m.group(1)}+")
            if HEAD_RE.search(line):
                mode, seen = ("mons" if "등장" in line else "info"), 0
                continue
            m = REWARD_RE.search(line)
            if m and cur and len(line) < 80:
                mode, seen, quest = "reward", 0, quest_label(m.group(1))
                continue
            # Any other prose ends the table run: what follows is often a
            # crafting/exchange list whose numbers are prices, not rewards.
            # A note between a title and its table is not an end.
            if seen:
                mode = None
            continue
        if val[0] == "던전 이름" and len(val) >= 2:
            cur, mode = val[1], "info"
            r = rec(cur)
            if named and key(named) != key(cur) and key(named) in out:
                for f, v in out.pop(key(named)).items():
                    if f != "name":
                        r.setdefault(f, v)
            continue
        if not cur or val[0] in HEADER_CELLS or HEADER_TAILS & set(val[1:]):
            continue
        r = rec(cur)
        seen += 1
        if mode == "info" and len(val) >= 2:
            k, v = val[0], " ".join(val[1:])
            if "입장 조건" in k:
                m = LEVEL_RE.search(v)
                if m:
                    r["req"] = f"Lv.{m.group(1)}+"
                r.setdefault("conditions", []).append(v)
            elif k.startswith("필요 아이템"):
                r["pass_item"] = v
            elif k.startswith("입장 최대 인원"):
                m = re.search(r"\d+", v)
                if m:
                    r["party"] = int(m.group())
            elif k.startswith("등장 보스"):
                r["boss"] = v
            elif "횟수" in k:
                r["limit"] = v
        elif mode == "mons" and STAGE_RE.match(val[0]):
            # Staged spawn table: stage | name | name | odds... | bounty.
            for c in val[1:]:
                if c != "-" and not re.search(r"\d", c):
                    r.setdefault("monsters", []).append({"name": c, "title": val[0]})
        elif mode == "mons" and len(val) >= 2:
            m = {"name": val[0]}
            if len(val) >= 3 and val[1] not in ("-", ""):
                m["title"] = val[1]
            lv = re.search(r"\d{2,3}", val[-1])
            if lv:
                m["level"] = int(lv.group())
            r.setdefault("monsters", []).append(m)
        elif mode == "reward" and len(val) >= 2:
            rate = next((c for c in val[1:] if "%" in c), None)
            qty = next((c for c in reversed(val[1:]) if "%" not in c), "")
            if not re.search(r"\d", qty):
                continue
            label = None
            if STAGE_RE.match(val[0]) and len(val) >= 3:
                label, val = val[0], val[1:]
            item = {"item": val[0], "qty": qty.rstrip("개").strip()}
            if label and label != "-":
                item["round"] = label
            if rate:
                item["rate"] = rate
            if quest:
                item["quest"] = quest
            r.setdefault("rewards", []).append(item)
    for r in out.values():
        if "monsters" in r:
            seen_names = set()
            r["monsters"] = [m for m in r["monsters"]
                             if not (m["name"] in seen_names or seen_names.add(m["name"]))]
    # A name with nothing under it is a passing mention, not a dungeon.
    return {k: v for k, v in out.items() if len(v) > 1}


def main():
    posts = {p["o"]: p for p in json.loads(INDEX.read_text(encoding="utf-8"))["posts"]}
    found = []
    for path in CACHE.glob("kr_view_o*.html"):
        o = path.stem.split("_o")[-1]
        raw = path.read_text(encoding="utf-8", errors="replace")
        if "던전 기본 정보" not in raw and "던전 위치" not in raw:
            continue
        date = (posts.get(o) or {}).get("date", "")
        found.append((date, o, parse_post(raw)))
    found.sort()
    # cache/ is not tracked: a fresh clone must not wipe the committed file.
    if not found:
        print("no cached KR post with dungeon info; kept", OUT.relative_to(PROJ))
        return
    merged = {}
    for date, o, recs in found:
        for k, r in recs.items():
            base = merged.setdefault(k, {"sources": []})
            for f in ("rewards", "monsters", "conditions"):
                if f in r:
                    base.pop(f, None)
            for f, v in r.items():
                base[f] = v
            base["date"] = date
            base["url"] = POST_URL.format(o=o)
            base["sources"].append(o)
    OUT.write_text(json.dumps({"dungeons": merged}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJ)}  ({len(merged)} dungeon from {len(found)} post)")


if __name__ == "__main__":
    main()
