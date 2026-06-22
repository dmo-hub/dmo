"""Re-parse cached HTML files (no network) using current scan_decks.py logic.
Used to refresh scan_result.json after parser tweaks without re-hitting the server.
"""

import io
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from scan_decks import (
    CACHE,
    CONFIGS,
    html_to_text,
    parse_decks,
)

PROJ = Path(__file__).resolve().parent.parent

# Preserve prior subject/date from existing scan_result.json if present
prior = {}
sr = PROJ / "data" / "scan_result.json"
prior_data = {}
if sr.exists():
    try:
        prior_data = json.loads(sr.read_text(encoding="utf-8"))
        for m in prior_data.get("matches", []):
            prior[(m["kind"], m["idx"])] = m
    except Exception:
        pass

DATE_RE = re.compile(r">\s*(\d{2}-\d{2}-\d{4})\s*<")
SUBJ_RE = re.compile(r"FINISHED([^<]+?)</")
SUBJ_RE2 = re.compile(r"<title[^>]*>[^<]*</title>", re.IGNORECASE)  # fallback


def extract_meta(html):
    """Pull date (mm-dd-yyyy) and subject from the post detail HTML."""
    date = ""
    m = DATE_RE.search(html)
    if m:
        date = m.group(1)
    subject = ""
    m = SUBJ_RE.search(html)
    if m:
        subject = m.group(1).strip()
    else:
        # Try anchor: look for the title near .news_title or similar
        m = re.search(
            r'class="(?:title|news_title|view_subject)"[^>]*>([^<]+)<',
            html,
            re.IGNORECASE,
        )
        if m:
            subject = m.group(1).strip()
    return date, subject


results = []
for f in sorted(CACHE.glob("*.html")):
    name = f.stem
    kind, _, idx_s = name.partition("_")
    if kind not in CONFIGS:
        continue
    idx = int(idx_s)
    html = f.read_text(encoding="utf-8", errors="ignore")
    text = html_to_text(html)
    parsed = parse_decks(text)
    date, subject = extract_meta(html)
    prev = prior.get((kind, idx), {})
    if not date:
        date = prev.get("date", "")
    if not subject:
        subject = prev.get("subject", "")
    results.append(
        {
            "kind": kind,
            "idx": idx,
            "date": date,
            "subject": subject,
            "url": "https://dmo.gameking.com" + CONFIGS[kind]["view"].format(idx),
            **parsed,
        }
    )

results.sort(key=lambda r: (r["kind"], r["idx"]))
new_total = sum(len(r["new_decks"]) for r in results)
ex_total = sum(len(r["existing_decks"]) for r in results)

out = {
    "scan_date": time.strftime("%Y-%m-%d %H:%M:%S") + " (re-parsed from cache)",
    "scanned": prior_data.get("scanned"),
    "matched_posts": len(results),
    "new_deck_count": new_total,
    "existing_deck_count": ex_total,
    "matches": results,
    "errors": [],
}

sr.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Re-parsed {len(results)} cached posts")
print(f"  new_deck_count:      {new_total}")
print(f"  existing_deck_count: {ex_total}")
print(f"Saved: {sr}")
