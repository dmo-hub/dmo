"""Scan cached gameking posts for post-release "Family Attributes" rebalance
blocks and merge the additions into scan_result_digimon.json.

Some digimon get their family list updated after their initial release post.
Example from event_782:

    [Digimon rebalancing] Family attributes will be added to certain Digimon
    [Contents] Rebalancing info Addition of Family Attributes to existing digimon
    Family Attributes info
    [Awaken] Ordinemon – TBD, UK
    Cross-up Mervamon – TBD, UK
    Kuzuhamon Miko Mode – Nso, UK, TBD
    Eosmon – TBD, UK
    BloomLordmon – UK, TBD
    ◎ ...

The block lists the **new total** family set per digimon (not just the deltas),
so we union with whatever was already on the record. Names are matched
case-insensitively after stripping spaces / punctuation (e.g. gameking
"BloomLordmon" → JSON "Bloomlordmon", "Kuzuhamon Miko Mode" → "Kuzuhamon MikoMode").
"""

import glob
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# Re-use the field-abbreviation map from the gameking enricher so we stay
# consistent.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_digimon_gameking import FIELD_MAP, html_to_text  # type: ignore

PROJ = Path(__file__).resolve().parent.parent
SCAN = PROJ / "data" / "scan_result_digimon.json"
CACHE = PROJ / "cache"

# Match an "Addition of Family Attributes" / "Family Attributes info" block
# header. The block runs until the next ◎ separator or section header.
BLOCK_RE = re.compile(
    r"Family Attributes info\s+(.+?)(?:◎|\[Event|\[Update|$)",
    re.S,
)

# Within the block, each line looks like:  <name> – <abbr>(, <abbr>)*
# Name can have a leading `[Awaken]` / `[Extreme]` qualifier and contain
# hyphens (e.g. "Cross-up Mervamon"). The separator is an en-/em-dash or
# hyphen *surrounded by whitespace* so embedded hyphens like "Cross-up"
# don't confuse it.
FIELD_ABBR = "|".join(sorted(map(re.escape, FIELD_MAP.keys()), key=len, reverse=True))
ENTRY_RE = re.compile(
    rf"([\w\[\]()\- ]+?)\s+[–—-]\s+((?:{FIELD_ABBR})(?:\s*,\s*(?:{FIELD_ABBR}))*)",
    re.IGNORECASE,
)


def norm(name: str) -> str:
    """Lowercase + strip non-alphanumeric for fuzzy name matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_entries(text: str) -> list[tuple[str, list[str]]]:
    """Return [(parsed_name, [family_full_names]), ...] from a "Family
    Attributes info" block found anywhere in `text`."""
    m = BLOCK_RE.search(text)
    if not m:
        return []
    block = m.group(1)
    field_lookup = {k.lower(): v for k, v in FIELD_MAP.items()}
    out: list[tuple[str, list[str]]] = []
    for em in ENTRY_RE.finditer(block):
        name = em.group(1).strip()
        families: list[str] = []
        for tok in re.split(r"[,/]", em.group(2)):
            full = field_lookup.get(tok.strip().lower())
            if full and full not in families:
                families.append(full)
        if families:
            out.append((name, families))
    return out


def parse_source_idx(fname: str) -> tuple[str, str]:
    """`cache/event_782.html` → ("event", "782"); `patch_4148.html` → ("patch", "4148")."""
    stem = Path(fname).stem  # e.g. "event_782"
    kind, _, idx = stem.partition("_")
    return kind, idx


def source_url(src_kind: str, idx: str) -> str:
    if src_kind == "event":
        return f"https://dmo.gameking.com/news/EventView.aspx?idx={idx}"
    return f"https://dmo.gameking.com/news/PatchNoteView.aspx?idx={idx}"


def main() -> None:
    data = json.loads(SCAN.read_text(encoding="utf-8"))

    # Build normalized-name → (kind, idx, json_name) index.
    name_index: dict[str, tuple[str, str, str]] = {}
    for kind in ("event", "patch"):
        for idx, post in data.get(kind, {}).items():
            for json_name in post["digimon"]:
                name_index[norm(json_name)] = (kind, idx, json_name)

    updated, skipped = 0, []
    for fname in sorted(
        glob.glob(str(CACHE / "event_*.html")) + glob.glob(str(CACHE / "patch_*.html"))
    ):
        text = html_to_text(Path(fname).read_text(encoding="utf-8"))
        entries = parse_entries(text)
        if not entries:
            continue
        src_kind, src_idx = parse_source_idx(fname)
        print(f"\n{Path(fname).name}:")
        for parsed_name, new_families in entries:
            key = norm(parsed_name)
            hit = name_index.get(key)
            if not hit:
                print(f"  ? {parsed_name} – {new_families}  (no JSON match)")
                skipped.append(parsed_name)
                continue
            kind, idx, json_name = hit
            attrs = data[kind][idx].setdefault("attributes", {}).setdefault(json_name, {})
            # Skip if the rebalance post IS the digimon's own announcement
            # (no point linking back to itself).
            self_source = kind == src_kind and idx == src_idx
            current = list(attrs.get("families", []))
            before = list(current)
            for f in new_families:
                if f not in current:
                    current.append(f)
            attrs["families"] = current

            # Record source even if the families weren't strictly "new" on
            # this run — idempotent reruns shouldn't lose the audit trail.
            if not self_source:
                sources = attrs.setdefault("rebalance_sources", [])
                # Dedupe by (kind, idx) — one post can only contribute once.
                if not any(s["kind"] == src_kind and s["idx"] == src_idx for s in sources):
                    sources.append(
                        {
                            "kind": src_kind,
                            "idx": src_idx,
                            "url": source_url(src_kind, src_idx),
                            "families": new_families,
                        }
                    )

            if current != before:
                updated += 1
                print(f"  ✓ {json_name}: {before} → {current}  (from {src_kind}_{src_idx})")
            else:
                print(
                    f"  · {json_name}: already has {new_families}  "
                    f"(source recorded: {src_kind}_{src_idx})"
                )

    SCAN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n--- updated {updated} entries, {len(skipped)} unmatched ---")
    if skipped:
        for s in skipped:
            print(f"  ! {s}")


if __name__ == "__main__":
    main()
