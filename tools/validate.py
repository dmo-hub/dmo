"""Static checks for the published site — run in CI and before a commit.

Three checks, no network:
  1. JSON      — every data/*.json and docs/*.json parses.
  2. HTML      — every docs/*.html has balanced tags (the build scripts inject
                 markup, so a stray/unclosed tag means a broken page).
  3. idempotent — re-running the deterministic builders leaves the tracked
                 outputs byte-for-byte unchanged (so CI's regenerate step only
                 ever produces a diff when the *input data* changed, never from
                 nondeterministic builders). Skipped with --no-build.

Exit code is non-zero if any check fails, so it doubles as a CI gate.

Run: python tools/validate.py            # all checks
     python tools/validate.py --no-build # skip the rebuild/idempotency check
"""

import io
import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
VOID = {"br", "img", "col", "meta", "link", "input", "hr", "area",
        "base", "embed", "source", "track", "wbr"}

# Deterministic, cache/data-only builders safe to re-run in CI (no network).
# Order matters: th_seal_en feeds build_seal_tables.
IDEMPOTENT_BUILDS = [
    ["builders/build_th_seal_en.py"],
    ["builders/build_seal_tables.py"],
    ["builders/build_digimon_html.py"],
]


def check_json():
    bad = []
    for p in sorted([*(PROJ / "data").glob("*.json"),
                     *(PROJ / "docs").glob("*.json")]):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:                       # noqa: BLE001
            bad.append(f"{p.relative_to(PROJ)}: {e}")
    return bad


class _Balance(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.stray = 0

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):  # <tag/>
        pass

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.stray += 1


def check_html():
    bad = []
    for p in sorted((PROJ / "docs").glob("*.html")):
        b = _Balance()
        b.feed(p.read_text(encoding="utf-8"))
        if b.stack or b.stray:
            bad.append(f"{p.relative_to(PROJ)}: "
                       f"{len(b.stack)} unclosed {b.stack[:5]}, {b.stray} stray")
    return bad


def check_idempotent():
    bad = []
    for cmd in IDEMPOTENT_BUILDS:
        r = subprocess.run([sys.executable, *cmd], cwd=PROJ,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            bad.append(f"{cmd[0]} exited {r.returncode}: {r.stderr.strip()[:300]}")
    # any tracked file changed by the rebuilds? (untracked/new files are fine)
    diff = subprocess.run(["git", "diff", "--name-only"], cwd=PROJ,
                          capture_output=True, text=True)
    changed = [f for f in diff.stdout.split() if f]
    if changed:
        bad.append("builders are non-idempotent — rebuild changed: "
                   + ", ".join(changed))
    return bad


def main():
    no_build = "--no-build" in sys.argv
    checks = [("JSON parses", check_json), ("HTML balanced", check_html)]
    if not no_build:
        checks.append(("builders idempotent", check_idempotent))

    failed = False
    for label, fn in checks:
        problems = fn()
        if problems:
            failed = True
            print(f"FAIL  {label}")
            for p in problems:
                print(f"      - {p}")
        else:
            print(f"ok    {label}")

    print("\n" + ("VALIDATION FAILED" if failed else "all checks passed"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
