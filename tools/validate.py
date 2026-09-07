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
# Order matters: th_seal_en feeds build_seal_tables, which feeds build_seal_budget
# (the budget page copies its nav/footer from the rebuilt seals.html).
IDEMPOTENT_BUILDS = [
    ["builders/build_th_seal_en.py"],
    ["builders/build_seal_tables.py"],
    ["builders/build_seal_budget.py"],
    ["builders/build_seal_patch_html.py", "--all"],
    ["builders/build_digimon_html.py"],
    ["builders/build_nametag_html.py"],
    ["builders/build_search_index.py"],
    ["builders/build_index_html.py"],
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


def check_parsers():
    """Frozen-fixture regression tests for the scrape parsers.

    tools/fixtures/ holds small slices of REAL cached posts (one per parser).
    They are frozen on purpose: a failure here means a parser edit changed
    behaviour on markup that used to work — not that the live site changed.
    """
    fx = PROJ / "tools" / "fixtures"
    if not fx.exists():
        return ["__skip__: tools/fixtures missing — parser regression not checked"]
    sys.path.insert(0, str(PROJ / "scanners"))
    bad = []
    try:
        from scan_vplay_upgrade import parse_blocks as parse_vplay_blocks
        from scan_chipsets import parse_chipsets
        from scan_attributes import parse_attributes, parse_rank_table
        from scan_clothing import (build_heading_map, canon_stat, header_labels,
                                   parse_rowwise, parse_stat_cell, slot_from,
                                   split_rows)

        def _clothing_rows(text, slot, marker="Column Named Ring"):
            """Drive parse_rowwise the way main() does, for one fixture table."""
            import re as _re
            for m in _re.finditer(r"<table.*?</table>", text, _re.S):
                rows = split_rows(m.group(0))
                if not rows:
                    continue
                header = header_labels(rows[0])
                lower = [h.lower() for h in header]
                if "name" not in lower or "upgrade" not in lower:
                    continue
                if marker not in m.group(0):
                    continue
                cols = [i for i, h in enumerate(lower)
                        if "stat" in h or "effect" in h or canon_stat(header[i])]
                got, _ = parse_rowwise(rows, {2: slot}, set(), cols,
                                       lower.index("name"), lower.index("upgrade"),
                                       header)
                return got
            return []
        from scan_decks import parse_decks
        from scan_digimon import parse_digimon
        from scan_kr_digimon_releases import extract_releases
        from scan_th_patch_digimon import NEW_DIGIMON_RE, html_to_text

        cases = [
            (
                "na_deck_event_673.html",
                lambda t: parse_decks(t)["new_decks"],
                ["God’s Will", "Leader of the Awakened Four Holy Beasts"],
            ),
            ("na_digimon_patch_4171.html", parse_digimon, ["Apollomon"]),
            (
                "clothing_shapes.html",
                lambda t: [
                    "%s:%s" % (x["stat"], x.get("value", "%s-%s" % (x.get("min"), x.get("max"))))
                    for x in parse_stat_cell("Attack +133~152")
                ]
                + [x["unit"] for x in parse_stat_cell("HP +5%")]
                + ["random" if parse_stat_cell("Random bonus stat")[0]["random"] else "no"]
                + ["unsigned:%d" % len(parse_stat_cell("Attack 92"))]
                + ["%s/%s" % (x["stat"], x.get("axis"))
                   for x in parse_stat_cell("Digimon HP +12, Tamer Attack +4")],
                ["AT:133.0-152.0", "pct", "random", "unsigned:0",
                 "HP/digimon", "AT/tamer"],
            ),
            (
                # A nested table makes "<table" openings and "<table>...</table>"
                # pairs disagree; keying slots off the wrong one shifts every
                # heading by a table and silently mislabels every item after it.
                "clothing_shapes.html",
                lambda t: [
                    slot_from(build_heading_map(t)(m.start()))
                    for m in __import__("re").finditer(
                        r"<table.*?</table>", t, __import__("re").S
                    )
                ],
                ["Top", "Rings", "Gloves", "Shoes", "Ghost Key Ring", "Bottom"],
            ),
            (
                # Upgrade tables name the stat in the COLUMN and leave a bare
                # number in the cell. parse_stat_cell needs "HT +100", so a
                # table like this silently yielded stats:[] -- which is
                # indistinguishable from a cosmetic that grants nothing.
                "clothing_shapes.html",
                lambda t: sorted(
                    "%s:%s@%s" % (st["stat"], st.get("value"), it["upgrade"])
                    for it in _clothing_rows(t, "Ghost Key Ring")
                    for st in it["stats"]
                    if st.get("value")
                ),
                ["HP:500.0@1", "HT:100.0@0", "HT:150.0@1", "Skill DMG:3.0@1"],
            ),
            (
                # "Stats Increase" cells put the value first and the stat last
                # ("1000-1250 DS"), the reverse of every other cell. One cell
                # can also name several stats ("10% SkillDmg/AT/HP"), and a row
                # can cover a BAND of levels rather than one.
                "clothing_shapes.html",
                lambda t: sorted(
                    "%s:%s@%s" % (st["stat"],
                                  st.get("value", "%s-%s" % (st.get("min"), st.get("max"))),
                                  it.get("upgrade_max", it["upgrade"]))
                    for it in _clothing_rows(t, "Bottom", "Trailing Stat Pants")
                    for st in it["stats"]
                ),
                ["AT:10.0@15", "DS:1000.0-1250.0@4", "HP:10.0@15",
                 "HT:1500.0-3000.0@15", "HT:25.0@15", "Skill DMG:10.0@15"],
            ),
            (
                # vplay writes the stat names only on the base row; levels 1..15
                # carry bare values that inherit them. It also spells the same
                # item with an en dash in one post and "&#8211;" in another, so
                # the two must normalise to one name or de-dupe never fires.
                "vplay_upgrade_slice.html",
                lambda t: [
                    "%s|%s" % (b["name"], ",".join(
                        "%d:%s=%s%s" % (l["upgrade"], st["stat"], st["value"],
                                        "%" if st["unit"] == "pct" else "")
                        for l in b["levels"] for st in l["stats"]))
                    for b in parse_vplay_blocks(t)
                ],
                ["แมกเนติก ID Card - Fixture [AT]|"
                 "0:AT=50.0,1:AT=100.0,15:AT=1500.0,15:Skill DMG=12.0%,15:Final DMG=3.0%",
                 "แมกเนติก ID Card - Fixture [CT]|"
                 "0:CT=5.0%,1:CT=7.0%"],
            ),
            (
                # Chipset tables are pivoted: stats down the rows, GRADE across
                # the columns, so one column is one chip. Two kinds share the
                # same header and are told apart only by the image above the
                # table. "+?" means the wiki has no value -- it must not become
                # a zero, or an unmeasured stat reads as "this chip gives none".
                "chipsets_slice.html",
                lambda t: [
                    "%s|%s" % (c["id"], ",".join(
                        "%s=%s%s" % (s["stat"], s["value"],
                                     "%" if s["unit"] == "pct" else "")
                        for s in c["stats"]))
                    for c in parse_chipsets(t)
                ],
                ["chip-all-r1|HP=108.0,AT=16.0,CT=0.2%",
                 "chip-all-r2|HP=215.0,AT=31.0,CT=0.4%",
                 "chip-family-r1|HP=135.0,AT=20.0,CT=0.25%",
                 "chip-family-r2|HP=269.0,AT=39.0,CT=0.5%",
                 "chip-family-r15|AT=288.0,CT=3.75%"],
            ),
            (
                # Attribute rows carry a roll RANGE, written with "~" on most
                # rows and a hyphen on at least one. A blank cell means the
                # wiki has no value -- it must not become a zero-width range.
                # The slot each kind merges into comes from the prose above
                # the table, not from any column.
                "attributes_slice.html",
                lambda t: [
                    "%s|%s|%s" % (a["name"], a["merges_into"],
                                  ("%s-%s%s" % (a["roll"]["min"], a["roll"]["max"],
                                                "%" if a["roll"]["unit"] == "pct" else "")
                                   if "roll" in a else "no-roll"))
                    for a in parse_attributes(t)
                ],
                ["HP attribute rank A|Jacket|15.0-20.0",
                 "HP attribute rank X|Jacket|168.0-280.0",
                 "HP attribute rank Z|Jacket|no-roll",
                 "MS attribute rank A|Shoes|1.0-2.0%"],
            ),
            (
                "attributes_slice.html",
                lambda t: sorted(
                    "%s|%s" % (r["id"], ",".join(
                        "%s=%s" % (s["stat"], s["value"]) for s in r["stats"]))
                    for r in parse_rank_table(t)
                ),
                ["rank-a-lv1|HP=50.0,AT=28.0", "rank-a-lvmax|HP=250.0,AT=140.0"],
            ),
            ("kr_release_o797630_slice.html", extract_releases, ["블룸로드몬"]),
            (
                "th_digimon_slice.html",
                lambda t: [
                    m.group(1).strip() for m in [NEW_DIGIMON_RE.search(html_to_text(t))] if m
                ],
                ["ดูนัสมอน X"],
            ),
        ]
        for name, fn, expect in cases:
            p = fx / name
            if not p.exists():
                bad.append(f"fixture missing: {name}")
                continue
            got = fn(p.read_text(encoding="utf-8"))
            if got != expect:
                bad.append(f"{name}: expected {expect}, got {got}")
    except Exception as e:  # noqa: BLE001
        bad.append(f"parser import/run failed: {e}")
    finally:
        sys.path.pop(0)
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
        ("parser fixtures", check_parsers),
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
