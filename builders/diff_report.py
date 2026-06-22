"""Diff scan_result.json against the current docs/decks.html.

Outputs:
  - Posts in scan but NOT in report (missed previously)
  - Posts in report but NOT in scan (over-claimed, or post deleted)
  - Per-post deck counts
"""

import json
import re
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCAN = PROJ / "data" / "scan_result.json"
REPORT = PROJ / "docs/decks.html"


def parse_report_idx():
    """Extract {kind: {idx: post_summary}} from existing HTML report.

    Supports both old (<h2>idx 743 (date) — Name</h2>) and new layouts
    (<section id="e743">...idx-badge>idx 743</span>...<h2>Name</h2>).
    """
    html = REPORT.read_text(encoding="utf-8")
    posts = {"event": {}, "patch": {}}

    # New layout: <section ... id="(e|p)<idx>"> ... aspx?idx=<idx>
    for m in re.finditer(
        r'<section[^>]*\sid="([ep])(\d+)"[\s\S]*?(EventView|PatchNoteView)\.aspx\?idx=(\d+)',
        html,
    ):
        prefix = m.group(1)
        idx_in_section = int(m.group(2))
        view = m.group(3)
        kind = "event" if (view == "EventView" or prefix == "e") else "patch"
        posts[kind][idx_in_section] = {"idx": idx_in_section}

    # Old layout fallback
    for m in re.finditer(
        r"<h2>idx\s+(\d+)\s*(?:\(([^)]+)\))?\s*[—\-]\s*([^<]+?)</h2>"
        r"[\s\S]*?(EventView|PatchNoteView)\.aspx\?idx=(\d+)",
        html,
    ):
        idx = int(m.group(1))
        view = m.group(4)
        kind = "event" if view == "EventView" else "patch"
        posts[kind].setdefault(idx, {"idx": idx})

    return posts


def main():
    if not SCAN.exists():
        print(f"ERROR: {SCAN} not found — run scan_decks.py first")
        return

    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    report = parse_report_idx()

    print(f"Scan date:   {scan.get('scan_date')}")
    print(f"Scanned:     {scan.get('scanned')}")
    print(f"Matched posts in scan:   {scan.get('matched_posts')}")
    print(f"New decks total in scan: {scan.get('new_deck_count')}")
    print(f"Posts in current report: event={len(report['event'])} patch={len(report['patch'])}")
    print()

    # Build idx sets per kind
    scan_by_kind = {"event": {}, "patch": {}}
    for r in scan["matches"]:
        if r.get("new_decks"):
            scan_by_kind[r["kind"]][r["idx"]] = r

    for kind in ("event", "patch"):
        scan_idx = set(scan_by_kind[kind].keys())
        report_idx = set(report[kind].keys())
        missed = sorted(scan_idx - report_idx)  # found by scanner, not in report
        extra = sorted(report_idx - scan_idx)  # in report, not in scan
        common = sorted(scan_idx & report_idx)

        kind_label = "EventView" if kind == "event" else "PatchNote"
        print(f"=== {kind_label} ===")
        print(f"  In scan:   {len(scan_idx)}")
        print(f"  In report: {len(report_idx)}")
        print(f"  Common:    {len(common)}")
        print(f"  Missed by previous report ({len(missed)}):")
        for i in missed:
            r = scan_by_kind[kind][i]
            decks = " / ".join(r["new_decks"])
            print(f"    idx {i:>5} ({r['date']}) [{r['subject'][:60]}] -> {decks}")
        if extra:
            print(f"  In report but missing in scan ({len(extra)}):")
            for i in extra:
                rep = report[kind][i]
                print(f"    idx {i:>5} - {rep.get('name', '')}")
        print()

    # Save concise comparison json
    diff_out = {}
    for kind in ("event", "patch"):
        scan_idx = set(scan_by_kind[kind].keys())
        report_idx = set(report[kind].keys())
        diff_out[kind] = {
            "missed_in_report": sorted(scan_idx - report_idx),
            "extra_in_report": sorted(report_idx - scan_idx),
            "common": sorted(scan_idx & report_idx),
        }
    (PROJ / "data" / "diff.json").write_text(
        json.dumps(diff_out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Saved: {PROJ / 'diff.json'}")


if __name__ == "__main__":
    main()
