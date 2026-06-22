"""DMO gameking - New Deck Add scanner.

Enumerates every EventView + PatchNote post via AJAX list, then fetches
each detail page in parallel and grep-detects "New Deck Add" / existing
deck change markers. Writes scan_result.json with per-post details.

Run: python scan_decks.py
"""

import io
import json
import re
import sys
import time

# Force UTF-8 stdout on Windows so prints don't crash on Thai paths
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
CACHE.mkdir(exist_ok=True)

BASE = "https://dmo.gameking.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT = 30
MAX_WORKERS = 15

CONFIGS = {
    "event": {
        "ajax": "/News/AjaxEventList.aspx",
        "list_ref": BASE + "/news/EventList.aspx",
        "view": "/news/EventView.aspx?idx={}",
    },
    "patch": {
        "ajax": "/News/AjaxPatchNoteList.aspx",
        "list_ref": BASE + "/News/PatchNoteList.aspx",
        "view": "/News/PatchNoteView.aspx?idx={}",
    },
}

NEW_MARKER_RE = re.compile(r"\[\s*New\s+Deck\s+Add(?:ed)?\b[^\]]*\]", re.IGNORECASE)
EXISTING_MARKER_RE = re.compile(
    r"\[\s*(?:Existing\s+Deck\s+Effect\s+Changed|Modify\s+Existing\s+Deck)\b[^\]]*\]",
    re.IGNORECASE,
)
DIGIMON_LIST_RE = re.compile(r"\[\s*([^\]]{3,90}?)\s*\]\s*Digimon\s*List", re.IGNORECASE)


def make_session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def enumerate_idx(session, kind, max_pages=1000):
    """Page through AJAX list to enumerate all posts (idx, date, subject)."""
    cfg = CONFIGS[kind]
    items, seen = [], set()
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": cfg["list_ref"],
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    empty_streak = 0
    for page in range(1, max_pages + 1):
        try:
            r = session.post(
                BASE + cfg["ajax"],
                headers=headers,
                data={"page": page, "type": "", "word": ""},
                timeout=TIMEOUT,
            )
            data = r.json() if r.text.strip() else []
        except Exception as e:
            print(f"  {kind} page {page}: {e}", file=sys.stderr)
            break
        if not data:
            empty_streak += 1
            if empty_streak >= 2:
                break
            continue
        empty_streak = 0
        new_in_page = 0
        for it in data:
            idx = int(it["idx"])
            if idx in seen:
                continue
            seen.add(idx)
            items.append(it)
            new_in_page += 1
        if new_in_page == 0:
            break
        if page % 20 == 0:
            print(
                f"  {kind} page {page}: total={len(items)} min_idx={min(seen)} max_idx={max(seen)}"
            )
        time.sleep(0.15)
    return items


def html_to_text(html):
    text = html.replace("&nbsp;", " ").replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def parse_decks(text):
    """Extract new + existing deck names.

    Strategy:
      1. Find positions of [New Deck Add(ed)] and [Existing Deck ...] markers.
      2. Find every "[<X>] Digimon List" anchor — these are deck names.
      3. Each deck's classification = whichever marker preceded it most recently.
    """
    new_marker_positions = [m.end() for m in NEW_MARKER_RE.finditer(text)]
    existing_marker_positions = [m.end() for m in EXISTING_MARKER_RE.finditer(text)]

    new_decks, existing_decks = [], []
    for m in DIGIMON_LIST_RE.finditer(text):
        name = m.group(1).strip(" -_:")
        if not name or len(name) > 120:
            continue
        # Skip if the captured name itself looks like a marker phrase
        low = name.lower()
        if any(
            k in low
            for k in (
                "new deck",
                "existing deck",
                "new digimon",
                "new d-unit",
                "new seal",
                "modify",
            )
        ):
            continue
        pos = m.start()
        last_new = max([p for p in new_marker_positions if p < pos] + [-1])
        last_ex = max([p for p in existing_marker_positions if p < pos] + [-1])
        if last_ex > last_new:
            if name not in existing_decks:
                existing_decks.append(name)
        elif last_new > -1:
            if name not in new_decks:
                new_decks.append(name)
    return {
        "new_decks": new_decks,
        "existing_decks": existing_decks,
        "has_new_marker": bool(new_marker_positions),
        "has_existing_marker": bool(existing_marker_positions),
    }


def fetch_detail(session, kind, idx):
    cache_file = CACHE / f"{kind}_{idx}.html"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="ignore"), True
    cfg = CONFIGS[kind]
    url = BASE + cfg["view"].format(idx)
    last_err = None
    for attempt in range(3):
        try:
            r = session.get(url, timeout=TIMEOUT)
            return r.text, False
        except Exception as e:
            last_err = e
            time.sleep(1.5**attempt)
    raise last_err


def has_marker(html):
    low = html.lower()
    return (
        "new deck add" in low
        or "existing deck effect changed" in low
        or "modify existing deck" in low
    )


def process_one(session, kind, item):
    idx = int(item["idx"])
    try:
        html, cached = fetch_detail(session, kind, idx)
        if not has_marker(html):
            return None
        text = html_to_text(html)
        parsed = parse_decks(text)
        if not cached:
            (CACHE / f"{kind}_{idx}.html").write_text(html, encoding="utf-8")
        return {
            "kind": kind,
            "idx": idx,
            "date": item.get("reg_date", ""),
            "subject": (item.get("subject") or "").strip(),
            "url": BASE + CONFIGS[kind]["view"].format(idx),
            **parsed,
        }
    except Exception as e:
        return {"kind": kind, "idx": idx, "error": str(e)}


def main():
    session = make_session()
    print("=== Step 1: Enumerate via AJAX list ===")
    print("EventView:")
    events = enumerate_idx(session, "event")
    if events:
        idxs = [int(e["idx"]) for e in events]
        print(f"  -> {len(events)} posts, idx range {min(idxs)}..{max(idxs)}")
    print("PatchNote:")
    patches = enumerate_idx(session, "patch")
    if patches:
        idxs = [int(p["idx"]) for p in patches]
        print(f"  -> {len(patches)} posts, idx range {min(idxs)}..{max(idxs)}")

    print("\n=== Step 2: Fetch detail pages (parallel) ===")
    all_tasks = [("event", e) for e in events] + [("patch", p) for p in patches]
    total = len(all_tasks)
    results, errors = [], []

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(process_one, session, k, it): (k, int(it["idx"])) for k, it in all_tasks}
        done = 0
        for fut in as_completed(futs):
            done += 1
            r = fut.result()
            if r is None:
                pass
            elif "error" in r:
                errors.append(r)
            else:
                results.append(r)
            if done % 200 == 0:
                elapsed = time.time() - t0
                rate = done / max(elapsed, 1)
                eta = (total - done) / max(rate, 0.01)
                print(
                    f"  [{done}/{total}] {elapsed:.0f}s "
                    f"rate={rate:.1f}/s eta={eta:.0f}s "
                    f"matches={len(results)} err={len(errors)}"
                )

    results.sort(key=lambda r: (r["kind"], r["idx"]))
    new_deck_total = sum(len(r.get("new_decks", [])) for r in results)
    existing_deck_total = sum(len(r.get("existing_decks", [])) for r in results)

    out = {
        "scan_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scanned": {"event": len(events), "patch": len(patches)},
        "matched_posts": len(results),
        "new_deck_count": new_deck_total,
        "existing_deck_count": existing_deck_total,
        "matches": results,
        "errors": errors,
    }

    out_file = PROJ / "data" / "scan_result.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== Result ===")
    print(f"Scanned: {len(events)} EventView + {len(patches)} PatchNote = {total}")
    print(f"Posts with deck marker: {len(results)}")
    print(f"Total new decks: {new_deck_total}")
    print(f"Errors: {len(errors)}")
    print(f"Saved: {out_file}")


if __name__ == "__main__":
    main()
