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
    ["builders/build_gear_registry.py"],
    ["builders/build_chip_registry.py"],
    # reads a cached page, so it is safe to re-run in the gate
    ["scanners/scan_set_effects.py"],
    ["scanners/scan_vplay_sets.py"],
    ["builders/build_set_registry.py"],
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
            # Read bytes, not text: node echoes the offending source line, so a
            # syntax error inside a Thai string makes the default locale decode
            # (cp874 on this machine) fail. text=True then hands back None and
            # the .strip() below used to crash the whole gate -- turning "this
            # file has a syntax error" into "the checker exploded".
            r = subprocess.run([node, "--check", tmp], capture_output=True)
            if r.returncode != 0:
                err = (r.stderr or b"").decode("utf-8", errors="replace")
                lines = [ln for ln in err.strip().splitlines() if ln.strip()]
                msg = lines[0] if lines else "syntax error"
                # node prints the source line first and the reason further down;
                # the reason is what a reader needs.
                for ln in lines:
                    if "Error" in ln:
                        msg = ln.strip()
                        break
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
        from scan_vplay_chipsets import parse_double
        from scan_set_effects import parse_sets
        from scan_vplay_sets import parse_rosters
        from scan_attributes import parse_attributes, parse_rank_table
        from scan_clothing import (build_heading_map, canon_stat, header_labels,
                                   parse_rowwise, parse_stat_cell, slot_from,
                                   split_rows)

        def _axis_override_probe():
            """Run the override layer over three synthetic rows."""
            import json as _json
            from pathlib import Path as _Path
            ov = _json.loads(
                (_Path(__file__).resolve().parent.parent / "data" /
                 "axis_overrides.json").read_text(encoding="utf-8"))
            by_axis = {}
            for rec in ov["overrides"].values():
                by_axis.setdefault(rec["axis"], set()).add(
                    "Yolei,T.K,Davis" if "Yolei" in rec["name"] else rec["slot"])
            out = []
            for want, key in (("digimon", "Yolei,T.K,Davis"),
                              ("tamer", "Perma ID Cards")):
                out.append("%s|%s" % (key, want if key in by_axis.get(want, ())
                                      else "MISSING"))
            # an id the file does not mention must stay untouched
            out.append("other|%s" % ("unknown" if "no-such-id" not in ov["overrides"]
                                     else "LEAKED"))
            return out

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
            (
                # The axis override layer: answers the wiki never states, taken
                # from the game and vplay. They cannot live in the registry
                # because scan_clothing rewrites it from scratch every run.
                "clothing_shapes.html",
                lambda t: _axis_override_probe(),
                ["Yolei,T.K,Davis|digimon", "Perma ID Cards|tamer", "other|unknown"],
            ),
            (
                # A Double ChipSet lists its primary and secondary sets as two
                # PARALLEL columns: one row holds both labels, the next holds
                # both tables. Reading the nearest preceding label tags the
                # primary numbers as secondary, so pairing is positional.
                # The grade heading also comes in two shapes -- R16 splits the
                # name and grade across two <strong> tags, R17 does not.
                "vplay_double_chipset.html",
                lambda t: [
                    "R%d|%s|%s" % (b["grade"],
                                   b["primary"].get("HP", {}).get("value"),
                                   b.get("secondary", {}).get("HP", {}).get("value"))
                    for b in parse_double(t)
                ],
                ["R16|2151.0|1291.0", "R17|2285.0|1371.0"],
            ),
            (
                # vplay writes percentages as hundredths of a percent with no
                # % sign -- "CT 400" is 4%, not 400%. Left as read it would be
                # 100x too generous and the solver would pick these every time.
                "vplay_double_chipset.html",
                lambda t: [
                    "%s:%s%s" % (k, v["value"], "%" if v["unit"] == "pct" else "")
                    for b in parse_double(t) if b["grade"] == 16
                    for k, v in sorted(b["primary"].items())
                ],
                ["AT:306.0", "CT:4.0%", "HP:2151.0"],
            ),
            (
                "vplay_double_chipset.html",
                lambda t: sorted({b["axis"] for b in parse_double(t)}),
                ["digimon"],
            ),
            (
                # The name is the post's own wording, which is what the game
                # shows the player. Nothing else asserts it, so a rescrape
                # could quietly put an invented English name back.
                "vplay_double_chipset.html",
                lambda t: [b["name"] for b in parse_double(t) if b["grade"] == 16],
                ["ดับเบิ้ล"
                 "ชิปเซ็ท R16"],
            ),
            (
                # 33 sub-effects across 12 rows. The count is the point: the
                # cell mixes value-first ("4500 HP"), value-last ("Reduce DMG
                # taken 30%"), no space at all ("1000HT"), and newlines instead
                # of commas -- any one of those regressing drops the tally.
                "set_effects_slice.html",
                lambda t: [sum(len(b["effects"]) for b in parse_sets(t)),
                           sum(len(b["unreadable"]) for b in parse_sets(t))],
                [33, 0],
            ),
            (
                # Davis procs at BOTH sizes while every other 4-set row is
                # permanent, so the split cannot be read off the piece count.
                "set_effects_slice.html",
                lambda t: sorted("%s/%s" % (b["pieces"], "perma" if b["permanent"]
                                            else "proc")
                                 for b in parse_sets(t)
                                 if b["set"].startswith("Davis")),
                ["4/proc", "6/proc"],
            ),
            (
                # A reduction is negative however the wiki phrased it.
                "set_effects_slice.html",
                lambda t: sorted({e["value"] for b in parse_sets(t)
                                  for e in b["effects"] if "Taken" in e["stat"]}),
                [-30.0, -20.0],
            ),
            (
                # The set name is held by a rowspan cell. The 3-column layout
                # (set | items | 6-set bonus) has bonus cells with their own
                # rowspan=2, so a row there can have two cells without being
                # a new set -- reading cell COUNT instead of rowspan promoted
                # items to set names and invented five sets that do not exist.
                "vplay_set_rosters.html",
                lambda t: sorted((k, len(v)) for k, v in parse_rosters(t).items()),
                [('จิตใจแห่งรัก', 12), ('พลังของสี่สัตว์เทพเซ็ต', 6), ('พลังแห่งความกล้า', 12), ('แสงแห่งความหวัง', 12)],
            ),
            (
                # Counting sets is not enough: ignoring the rowspan
                # WIDTH still yields the right totals here. The Four
                # Holy Beasts rows that carry the bonus column's own
                # rowspan=2 would become sets of their own, which only
                # shows up in the item list.
                "vplay_set_rosters.html",
                lambda t: [k for k in parse_rosters(t)
                           if k.startswith('เกราะแห่งห้วงมหาสมุทรของเชนวูมอน [อัลติเมท]'[:12])],
                [],
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


def check_chip_registry():
    """The chip list the gear page loads.

    Two things can go wrong silently here and neither shows up as a crash:
    the low grades creeping back in (they were dropped on purpose), and the
    secondary set going missing so a chip is scored at roughly 60% of what it
    really gives.
    """
    bad = []
    p = PROJ / "docs" / "chip_registry.json"
    if not p.exists():
        return ["docs/chip_registry.json missing -- run builders/build_chip_registry.py"]
    items = json.loads(p.read_text(encoding="utf-8"))["items"]

    grades = sorted(it["grade"] for it in items)
    if grades != [16, 17, 18]:
        bad.append(f"expected only R16-R18, got {grades}")

    # B09: a "family" chipset is stronger but only fits a matching digimon, and
    # the solver has no idea which family the player runs -- it would pick the
    # stronger one every time and recommend a chip that cannot be equipped.
    # Today the list is Double ChipSets only, which carry no such restriction,
    # so the decision is to score all-family chips only. This guard is what
    # keeps that true: adding a restricted chip must fail here rather than
    # quietly produce an unusable answer.
    for it in items:
        if (it.get("kind") or "all") != "all":
            bad.append("%s: kind=%r -- the solver scores all-family chips only "
                       "(a family chip needs the player's family, see B09)"
                       % (it["id"], it.get("kind")))

    for it in items:
        parts = it.get("parts") or {}
        prim, sec = parts.get("primary") or {}, parts.get("secondary") or {}
        if not sec:
            bad.append(f"{it['id']}: no secondary set -- a Double ChipSet grants both")
            continue
        for key in set(prim) | set(sec):
            want = round(prim.get(key, 0) + sec.get(key, 0), 2)
            got = it.get(key)
            if got is None:
                bad.append(f"{it['id']}: {key} dropped from the totals")
            elif abs(got - want) > 0.011:
                bad.append(f"{it['id']}: {key} is {got}, primary+secondary is {want}")

    # The secondary set is 60% of the primary, rounded to whole numbers, on
    # every stat of every grade. Only vplay records it, so there is no second
    # source to diff against; what stands in for one is that the primary set
    # from the same tables matches dmowiki's family chipset exactly, and the
    # 60% rule holds across all three grades without a hand-typed outlier.
    # This guard catches a rescrape that breaks the rule.
    for it in items:
        parts = it.get("parts") or {}
        prim, sec = parts.get("primary") or {}, parts.get("secondary") or {}
        for key in sorted(set(prim) & set(sec)):
            want = prim[key] * 0.6
            # whole-stat values are rounded; CT/EV/BL keep their decimals
            slack = 0.5 if key not in ("CT", "EV", "BL") else 0.011
            if abs(sec[key] - want) > slack:
                bad.append(
                    f"{it['id']}: secondary {key} is {sec[key]}, "
                    f"60% of the primary is {round(want, 2)}"
                )

    r16 = next((it for it in items if it["grade"] == 16), None)
    if r16:
        # dmowiki's family chipset R16 is AT +306 / CT +4%; the secondary set
        # is what vplay adds on top, so the totals must exceed those.
        if r16.get("AT") != 490 or abs(r16.get("CT", 0) - 6.4) > 0.011:
            bad.append(f"R16 totals moved: AT={r16.get('AT')} CT={r16.get('CT')}")
    else:
        bad.append("R16 missing")
    return bad


def check_set_rosters():
    """The roster artifact: which item belongs to which clothing set.

    The parser fixtures stop at parse_rosters; the split between base items
    and their "(ชิน)" upgraded variants happens when the file is written, so
    it needs checking here or it is not checked at all.
    """
    bad = []
    p = PROJ / "data" / "set_rosters.json"
    if not p.exists():
        return ["data/set_rosters.json missing -- run scanners/scan_vplay_sets.py"]
    sets = json.loads(p.read_text(encoding="utf-8"))["sets"]
    if not sets:
        return ["set_rosters.json has no sets"]

    SHIN = "(\u0e0a\u0e34\u0e19)"
    for s in sets:
        if any(i.startswith(SHIN) for i in s["items"]):
            bad.append("%s: a shin variant leaked into the base item list" % s["set"])
        if any(not i.startswith(SHIN) for i in s["shin_items"]):
            bad.append("%s: a base item leaked into the shin list" % s["set"])
        if s["pieces"] != len(s["items"]):
            bad.append("%s: pieces=%d but %d items listed"
                       % (s["set"], s["pieces"], len(s["items"])))
        if not s["items"]:
            bad.append("%s: no items" % s["set"])

    # The three tamer sets are the ones that unblock B05; each is six worn
    # pieces plus six shin variants.
    tamer = [s for s in sets if s["shin_items"]]
    if len(tamer) != 3:
        bad.append("expected 3 sets carrying shin variants, got %d" % len(tamer))
    for s in tamer:
        if s["pieces"] != 6 or len(s["shin_items"]) != 6:
            bad.append("%s: expected 6 base + 6 shin, got %d + %d"
                       % (s["set"], s["pieces"], len(s["shin_items"])))
    return bad


def check_set_registry():
    """The joined set registry the optimizer will read.

    Two sources meet here: vplay names the items per slot (Thai) and dmowiki
    supplies the stats via one template row per slot (English). The join key
    is (set, slot), so the thing that can silently rot is a slot losing its
    template -- the set would still look complete while scoring zero.
    """
    bad = []
    p = PROJ / "docs" / "set_registry.json"
    if not p.exists():
        return ["docs/set_registry.json missing -- run builders/build_set_registry.py"]
    sets = json.loads(p.read_text(encoding="utf-8"))["sets"]

    # The three tamer sets claim the six clothing slots and have shin variants.
    # Last Evolution is a two-piece accessory set with no shin variants at all,
    # so the shape checks below are split: what holds for every set, and what
    # holds only for the clothing three.
    # Sets that fill the six clothing slots.
    CLOTHING = {"Yolei-Heart of Love", "T.K-Light of Hope",
                "Davis-Power of Courage", "Four Holy Beasts"}
    # Of those, the three tamer sets are the ones with shin variants and a
    # 4-piece plus 6-piece bonus. Four Holy Beasts has neither: no shin item
    # exists, and vplay lists a single 6-piece bonus.
    TAMER = CLOTHING - {"Four Holy Beasts"}
    if len(sets) != 5:
        bad.append("expected 4 clothing sets + Last Evolution, got %d" % len(sets))

    SHIN = "(\u0e0a\u0e34\u0e19)"
    for s in sets:
        clothing = s["set"] in CLOTHING
        tamer = s["set"] in TAMER
        if not s.get("set") or not s.get("set_th"):
            bad.append("%s: missing one of the two names" % s.get("set_th"))
        if clothing and len(s["slots"]) != 6:
            bad.append("%s: %d slots, expected 6" % (s["set"], len(s["slots"])))
        if not s["slots"]:
            bad.append("%s: no slots at all" % s["set"])
        if len(s["slots"]) != s["pieces"]:
            bad.append("%s: pieces %s but %d slots"
                       % (s["set"], s["pieces"], len(s["slots"])))
        seen = set()
        for sl in s["slots"]:
            if sl["slot"] in seen:
                bad.append("%s: slot %s appears twice" % (s["set"], sl["slot"]))
            seen.add(sl["slot"])
            # a slot takes the base item or its shin variant, never both at once
            want = [n for n in (sl["item"], sl["shin"]) if n]
            if sl["accepts"] != want:
                bad.append("%s/%s: accepts does not match item+shin"
                           % (s["set"], sl["slot"]))
            if sl["shin"] and not sl["shin"].startswith(SHIN):
                bad.append("%s/%s: shin variant is not marked"
                           % (s["set"], sl["slot"]))
            if tamer and not sl["shin"]:
                bad.append("%s/%s: clothing slot lost its shin variant"
                           % (s["set"], sl["slot"]))
            if sl["item"].startswith(SHIN):
                bad.append("%s/%s: base item is a shin variant"
                           % (s["set"], sl["slot"]))
            if not sl["stats_from"]:
                bad.append("%s/%s: no source supplied the stats"
                           % (s["set"], sl["slot"]))
        # the clothing sets each have a 4-piece and a 6-piece bonus
        sizes = sorted(b["pieces"] for b in s["bonuses"])
        if tamer and sizes != [4, 6]:
            bad.append("%s: bonus sizes %s, expected [4, 6]" % (s["set"], sizes))
        if not sizes:
            bad.append("%s: no bonuses joined" % s["set"])
        # a threshold can never ask for more pieces than the set has
        for n in sizes:
            if n > len(s["slots"]):
                bad.append("%s: a %d-piece bonus on a %d-slot set"
                           % (s["set"], n, len(s["slots"])))

    # Davis procs at both sizes; the others are permanent at 4. Guards the
    # join from quietly pairing a set with another set's bonuses.
    davis = next((s for s in sets if s["set"].startswith("Davis")), None)
    if davis and any(b["permanent"] for b in davis["bonuses"]):
        bad.append("Davis: a bonus is marked permanent, both are procs")
    for s in sets:
        if s["set"].startswith("Davis"):
            continue
        four = next((b for b in s["bonuses"] if b["pieces"] == 4), None)
        if four and not four["permanent"]:
            bad.append("%s: the 4-piece bonus should be permanent" % s["set"])
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


def check_set_model():
    """Cross-check the browser DP against the ILP reference model.

    The DP collapses every state that already clears its floor into one, which
    is what keeps it fast and also the likeliest place for a silent error. The
    ILP never merges states, so agreement is evidence rather than the solver
    checking its own arithmetic. Needs node and pulp; absent either, skip.
    """
    try:
        import pulp  # noqa: F401
    except ImportError:
        return ["__skip__: pulp not installed"]
    r = subprocess.run(
        [sys.executable, str(PROJ / "tools" / "diff_set_model.py")],
        cwd=PROJ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if "NODE ERR" in r.stdout:
        return ["__skip__: node unavailable"]
    if r.returncode != 0:
        tail = [ln for ln in r.stdout.strip().splitlines() if ln][-6:]
        return ["DP and ILP disagree:"] + tail
    return []


def main():
    no_build = "--no-build" in sys.argv
    checks = [
        ("JSON parses", check_json),
        ("HTML balanced", check_html),
        ("inline JS syntax", check_scripts),
        ("parser fixtures", check_parsers),
        ("chip registry", check_chip_registry),
        ("set rosters", check_set_rosters),
        ("set registry", check_set_registry),
        ("DP vs ILP model", check_set_model),
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
