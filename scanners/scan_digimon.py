"""Scan cached gameking posts for `[New Digimon ...]` announcements.

Reads only from cache/ (no network). Run scan_decks.py first to populate cache.
Output: scan_result_digimon.json with {kind: {idx: {date, source, digimon: [name, ...]}}}.
"""

import html
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
OUT = PROJ / "data" / "scan_result_digimon.json"

# Reuse same date regex as scan_decks.py (MM-DD-YYYY format in raw HTML)
DATE_RE = re.compile(r">\s*(\d{2}-\d{2}-\d{4})\s*<")

# Match `[New Digimon ...]` with optional "Added"/"release" before the dash separator
MARKER_PREFIX = re.compile(
    r"^\s*New Digimon(?:\s+Added|\s+release)?\s*[–—-]\s*",
    re.IGNORECASE,
)
MARKER_FIND = re.compile(
    r"\[\s*New Digimon(?:\s+Added|\s+release)?\s*[–—-]\s*",
    re.IGNORECASE,
)

BASE = "https://dmo.gameking.com/news"
URL_TEMPLATE = {
    "event": f"{BASE}/EventView.aspx?idx={{idx}}",
    "patch": f"{BASE}/PatchNoteView.aspx?idx={{idx}}",
}


def html_to_text(raw: str) -> str:
    t = re.sub(r"<[^>]+>", " ", raw)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def find_balanced_close(text: str, start: int) -> int:
    """Return index just past the matching `]` for the `[` at `text[start]`."""
    assert text[start] == "["
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def parse_digimon(raw_html: str) -> list[str]:
    text = html_to_text(raw_html)
    names: list[str] = []
    for m in MARKER_FIND.finditer(text):
        bracket_start = text.rfind("[", 0, m.end())
        end = find_balanced_close(text, bracket_start)
        # content is everything between the outer brackets
        content = text[bracket_start + 1 : end - 1]
        name = MARKER_PREFIX.sub("", content).strip()
        # Multi-digimon in one marker (comma-separated, no nested brackets)
        if "[" not in name and "," in name:
            names.extend(n.strip() for n in name.split(",") if n.strip())
        elif name:
            names.append(name)
    return names


def parse_date(raw_html: str) -> str | None:
    m = DATE_RE.search(raw_html)
    return m.group(1) if m else None


def main() -> None:
    result: dict[str, dict[str, dict]] = {"event": {}, "patch": {}}
    for f in sorted(CACHE.glob("*.html")):
        kind, _, idx = f.stem.partition("_")
        if kind not in result:
            continue
        raw = f.read_text(encoding="utf-8")
        digimon = parse_digimon(raw)
        if not digimon:
            continue
        result[kind][idx] = {
            "date": parse_date(raw),
            "source": URL_TEMPLATE[kind].format(idx=idx),
            "digimon": digimon,
        }

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(p["digimon"]) for k in result for p in result[k].values())
    posts = sum(len(result[k]) for k in result)
    print(f"Wrote {OUT.name}: {total} digimon across {posts} posts")
    for k in result:
        for idx, p in result[k].items():
            print(f"  {k} {idx} ({p['date']}): {', '.join(p['digimon'])}")


if __name__ == "__main__":
    main()
