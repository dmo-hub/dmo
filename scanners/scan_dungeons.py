"""Parse cached dungeon posts into data/dungeons.json (offline, no network).

Reads cache/th_dungeon_*.html (from fetch_dungeons_th.py), extracts structured
fields per dungeon, and merges by boss into a cross-server manifest:

  {
    "fetched_at": "YYYY-MM-DD",
    "dungeons": [
      { "id": "<slug>", "boss_en": "", "image": "",
        "th": { "name", "url", "date", "boss", "summary",
                "req", "pass_item", "drop": [ ... ] },
        "kr": null, "na": null },
      ...
    ]
  }

na/kr are left null until their scanners land. image is left "" for manual fill.
Re-run is idempotent: existing na/kr/boss_en/image curation is preserved by
merging onto the previous data/dungeons.json when present.
"""

import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
OUT = PROJ / "data" / "dungeons.json"

LEVEL_RE = re.compile(r"(?:Lv\.?\s*(\d+)|เลเวล\s*(\d+)|เทมเมอร์\s*(?:มี)?เลเวล\s*(\d+))")
PASS_RE = re.compile(r"บัตรผ่าน[^\n]{0,60}")


def clean_lines(html):
    m = re.search(r"entry-content[^>]*>(.*?)</article>", html, re.S) or re.search(
        r"<article[^>]*>(.*?)</article>", html, re.S
    )
    body = m.group(1) if m else html
    body = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", "", body, flags=re.S)
    body = re.sub(r"<[^>]+>", "\n", body)
    body = body.replace("&#8211;", "-").replace("&nbsp;", " ")
    body = re.sub(r"&[a-z]+;", " ", body)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in body.split("\n")]
    return [ln for ln in lines if len(ln) > 1]


def boss_from_title(title):
    # "ดันเจี้ยน<boss>:..." or "...ดันเจี้ยน<boss>[...]" or "<x>:ดันเจี้ยน<boss>[..]"
    t = re.split(r"[:：]", title)[-1] if "ดันเจี้ยน" in title.split(":")[-1] else title
    m = re.search(r"ดันเจี้ยน([^\[:：]+)", t)
    boss = m.group(1).strip() if m else title
    return re.sub(r"\[.*?\]", "", boss).strip()


def parse_date(lines):
    for i, ln in enumerate(lines):
        if "อัพเดท" in ln and i + 1 < len(lines):
            m = re.search(r"[A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}", lines[i + 1])
            if m:
                return m.group(0)
    return None


def parse_req(lines):
    for ln in lines:
        if "เลเวล" in ln or "Lv" in ln:
            m = LEVEL_RE.search(ln)
            if m:
                lv = next(g for g in m.groups() if g)
                return f"Lv.{lv}+"
    return None


def parse_pass_item(lines):
    for ln in lines:
        if "บัตรผ่าน" in ln and ("ใช้" in ln or "ต่อการ" in ln or "1 ใบ" in ln):
            return re.sub(r"\s+", " ", ln).strip()[:80]
    for ln in lines:
        if "บัตรผ่าน" in ln:
            return re.sub(r"\s+", " ", ln).strip()[:80]
    return None


def parse_drop(lines):
    """Collect item lines that follow a 'รายการไอเทม' header, de-duplicated."""
    drops, capture, seen = [], False, set()
    for ln in lines:
        if "รายการไอเทม" in ln:
            capture = True
            continue
        if capture:
            if "ได้รับ" in ln or "กล่อง" in ln and "ระดับ" in ln and ")" in ln:
                capture = "กล่อง" in ln and "ได้รับ" not in ln
            if re.search(r"\d+\s*ชิ้น|\d+\s*ใบ|\+\d+%", ln):
                key = re.sub(r"\d+", "", ln)
                if key not in seen:
                    seen.add(key)
                    drops.append(ln)
            if len(drops) >= 12:
                break
    return drops


def parse_summary(lines):
    for ln in lines:
        if len(ln) > 40 and "อัพเดท" not in ln and "GM" not in ln:
            return ln[:200]
    return None


def slug(title, fallback):
    """Stable ascii id. Thai boss names romanize to empty, so fall back to a
    short hash of the title to keep each dungeon distinct."""
    boss = boss_from_title(title)
    ascii_slug = re.sub(r"[^\w]+", "-", boss.encode("ascii", "ignore").decode()).strip("-")
    if ascii_slug:
        return ascii_slug.lower()
    import hashlib

    return "th-" + hashlib.md5(fallback.encode("utf-8")).hexdigest()[:8]


def title_from_html(html):
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    t = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    t = t.replace("&#8211;", "-").replace("&#8212;", "-")
    t = re.sub(r"&[a-z]+;", " ", t)
    return re.split(r"\s*-\s*VPLAY", t)[0].strip()


def load_prev():
    if OUT.exists():
        return {d["id"]: d for d in json.loads(OUT.read_text(encoding="utf-8")).get("dungeons", [])}
    return {}


def main():
    prev = load_prev()
    dungeons = {}
    for f in sorted(CACHE.glob("th_dungeon_*.html")):
        html = f.read_text(encoding="utf-8")
        title = title_from_html(html)
        lines = clean_lines(html)
        # trim leading nav: start at first reoccurrence of the post title
        ti = next((j for j, ln in enumerate(lines) if title[:12] and title[:12] in ln and j > 3), 0)
        body = lines[ti:]
        url_m = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        boss = boss_from_title(title)
        sid = slug(title, f.name)
        th = {
            "name": title,
            "url": url_m.group(1) if url_m else None,
            "date": parse_date(body),
            "boss": boss,
            "summary": parse_summary(body[1:]),
            "req": parse_req(body),
            "pass_item": parse_pass_item(body),
            "drop": parse_drop(body),
        }
        base = prev.get(sid, {"id": sid, "boss_en": "", "image": "", "na": None, "kr": None})
        base["th"] = th
        dungeons[sid] = base

    payload = {
        "fetched_at": dt.date.today().isoformat(),
        "dungeons": sorted(dungeons.values(), key=lambda d: d["id"]),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJ)}  ({len(dungeons)} dungeon)")
    for d in payload["dungeons"]:
        t = d["th"]
        print(f"  [{d['id']}] boss={t['boss']!r} req={t['req']} drops={len(t['drop'])}")


if __name__ == "__main__":
    main()
