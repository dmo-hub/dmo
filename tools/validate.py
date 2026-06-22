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
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
VOID = {
    "br",
    "img",
    "col",
    "meta",
    "link",
    "input",
    "hr",
    "area",
    "base",
    "embed",
    "source",
    "track",
    "wbr",
}

# Deterministic, cache/data-only builders safe to re-run in CI (no network).
# Order matters: th_seal_en feeds build_seal_tables.
IDEMPOTENT_BUILDS = [
    ["builders/build_th_seal_en.py"],
    ["builders/build_seal_tables.py"],
    ["builders/build_digimon_html.py"],
]


def check_json():
    bad = []
    for p in sorted([*(PROJ / "data").glob("*.json"), *(PROJ / "docs").glob("*.json")]):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
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
            bad.append(
                f"{p.relative_to(PROJ)}: {len(b.stack)} unclosed {b.stack[:5]}, {b.stray} stray"
            )
    return bad


def _git_state():
    """Snapshot of every dirty path -> its porcelain status (XY) code.

    Uses `git status --porcelain` (not `git diff`) so it sees BOTH tracked
    modifications and new files a builder might emit. We compare a before/after
    snapshot and flag only paths the builders actually changed — pre-existing
    edits (e.g. an uncommitted CLAUDE.md) are filtered out, so the check no
    longer false-fails just because the working tree was dirty when it ran.
    """
    r = subprocess.run(
        ["git", "status", "--porcelain", "-z"], cwd=PROJ, capture_output=True, text=True
    )
    state = {}
    for rec in r.stdout.split("\0"):
        if len(rec) > 3:
            state[rec[3:]] = rec[:2]  # path -> "XY" status code
    return state


# inline <script>…</script> with NO src= attribute (captures the JS body)
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def check_scripts():
    """node --check every inline <script> so a JS syntax slip can't ship a
    silently-broken page (the seal budget calculator + tools/curate.html carry
    real logic). Parse-only — browser globals are never evaluated. Skipped
    gracefully when node isn't installed, since Python is the only hard dep."""
    node = shutil.which("node")
    if not node:
        return ["__skip__: node not found — inline JS not syntax-checked"]
    bad = []
    targets = sorted((PROJ / "docs").glob("*.html")) + [PROJ / "tools" / "curate.html"]
    for p in targets:
        if not p.exists():
            continue
        blocks = _INLINE_SCRIPT.findall(p.read_text(encoding="utf-8"))
        if not blocks:
            continue
        js = "\n;\n".join(blocks)  # ; guards against ASI joining two blocks
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js)
            tmp = f.name
        try:
            r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                msg = (r.stderr.strip().splitlines() or ["syntax error"])[0]
                bad.append(f"{p.relative_to(PROJ)}: {msg[:200]}")
        finally:
            Path(tmp).unlink(missing_ok=True)
    return bad


def check_idempotent():
    bad = []
    before = _git_state()
    for cmd in IDEMPOTENT_BUILDS:
        r = subprocess.run(
            [sys.executable, *cmd],
            cwd=PROJ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            bad.append(f"{cmd[0]} exited {r.returncode}: {r.stderr.strip()[:300]}")
    after = _git_state()
    # a path the builders touched: newly dirty, or whose status code changed
    touched = sorted(p for p, code in after.items() if before.get(p) != code)
    if touched:
        bad.append("builders are non-idempotent — rebuild changed: " + ", ".join(touched))
    return bad


def main():
    no_build = "--no-build" in sys.argv
    checks = [
        ("JSON parses", check_json),
        ("HTML balanced", check_html),
        ("inline JS syntax", check_scripts),
    ]
    if not no_build:
        checks.append(("builders idempotent", check_idempotent))

    failed = False
    for label, fn in checks:
        problems = fn()
        # a "__skip__:" entry is informational (e.g. node absent), not a failure
        skips = [p for p in problems if p.startswith("__skip__:")]
        real = [p for p in problems if not p.startswith("__skip__:")]
        if real:
            failed = True
            print(f"FAIL  {label}")
            for p in real:
                print(f"      - {p}")
        elif skips:
            print(f"skip  {label}")
            for p in skips:
                print(f"      - {p[len('__skip__:') :].strip()}")
        else:
            print(f"ok    {label}")

    print("\n" + ("VALIDATION FAILED" if failed else "all checks passed"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
