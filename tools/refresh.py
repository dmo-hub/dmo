"""Pipeline orchestrator — run the whole refresh in the right order.

Replaces the run-8-commands-from-CLAUDE.md ritual:

    python tools/refresh.py                     # everything: NA+KR+TH + build + validate
    python tools/refresh.py --servers na,th     # only those servers' fetch/scan legs
    python tools/refresh.py --no-fetch          # skip network scrapes, re-run enrich/build only
    python tools/refresh.py --no-validate       # skip the final validate pass

Steps that need Chrome CDP past Cloudflare (dmowiki attribute enrichment) are
NOT included — those stay manual (CLAUDE.md commands #11-12). scan_digimon.py
is merge-safe, so including it here is fine.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent

# (tag, needs_network, script, args) — tag "" runs regardless of --servers.
STEPS = [
    ("na", True, "scanners/scan_decks.py", []),
    ("na", False, "scanners/scan_digimon.py", []),
    ("na", False, "extractors/extract_digimon_images.py", []),
    ("kr", True, "fetchers/fetch_kr_news_index.py", []),
    ("kr", True, "scanners/scan_kr_digimon_releases.py", []),
    ("kr", False, "enrichers/enrich_digimon_kr.py", []),
    ("kr", False, "extractors/extract_kr_digimon_images.py", []),
    ("th", True, "fetchers/fetch_th_patch_index.py", []),
    ("th", True, "scanners/scan_th_patch_digimon.py", []),
    ("th", False, "enrichers/enrich_digimon_th.py", []),
    ("th", False, "extractors/extract_th_digimon_images.py", []),
    ("", False, "enrichers/enrich_digimon_gameking.py", []),
    ("", False, "enrichers/enrich_digimon_rebalance.py", []),
    ("", False, "builders/extract_seal_tables.py", []),
    ("", False, "builders/build_th_seal_en.py", []),
    ("", False, "builders/build_seal_tables.py", []),
    ("", False, "builders/build_seal_patch_html.py", ["--all"]),
    ("", False, "builders/build_digimon_html.py", []),
    ("", False, "builders/build_index_html.py", []),
    ("", False, "builders/build_search_index.py", []),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--servers", default="na,kr,th", help="comma list: na,kr,th")
    ap.add_argument("--no-fetch", action="store_true", help="skip network scrape steps")
    ap.add_argument("--no-validate", action="store_true", help="skip final validate.py")
    ap.add_argument("--keep-going", action="store_true", help="continue past a failed step")
    args = ap.parse_args()
    servers = {s.strip().lower() for s in args.servers.split(",") if s.strip()}

    run, skipped = [], []
    for tag, net, script, extra in STEPS:
        if tag and tag not in servers:
            skipped.append(script)
            continue
        if net and args.no_fetch:
            skipped.append(script)
            continue
        run.append((script, extra))
    if not args.no_validate:
        run.append(("tools/validate.py", []))

    print(f"refresh: {len(run)} steps (skipping {len(skipped)})\n")
    failed = []
    t0 = time.time()
    for script, extra in run:
        t = time.time()
        print(f"── {script} {' '.join(extra)}".rstrip() + " " + "─" * 20)
        r = subprocess.run(
            [sys.executable, str(PROJ / script), *extra],
            cwd=PROJ,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        tail = "\n".join((r.stdout or "").strip().splitlines()[-4:])
        print(tail or "(no output)")
        if r.returncode != 0:
            err_tail = "\n".join((r.stderr or "").strip().splitlines()[-8:])
            print(f"!! FAILED (exit {r.returncode})\n{err_tail}", file=sys.stderr)
            failed.append(script)
            if not args.keep_going:
                break
        print(f"   ok in {time.time() - t:.1f}s\n")

    print("=" * 50)
    print(f"refresh done in {time.time() - t0:.0f}s — {len(run) - len(failed)}/{len(run)} ok")
    if failed:
        print("FAILED steps: " + ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
