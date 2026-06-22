"""Extract Basic / Natural Attribute and Affiliated Field directly from the
gameking-cached EventView / PatchNoteView HTML, and merge into
scan_result_digimon.json.

Why this layer exists when we already have DMW + dmowiki enrichers:
  * gameking is the *primary* announcement — it ships the stat block first
    (DMW/dmowiki sometimes lag, or never index niche digimon at all).
  * gameking uses field abbreviations (VB, WG, NSo, ...) that wikis often
    don't tag explicitly, so this is where we recover families that wiki
    pages omit.

The script *augments* — it only fills fields that are currently missing
(`attribute`, `natural_attribute`, or empty `families`). It never overwrites
data wiki parsers already populated, except `attribute` if the wiki said
"Unknown" and gameking has a definite answer.

Format variants found across posts (years 2024–2026):
  • "Basic Attribute: Vaccine (Va) Natural Attribute: Light (Light) Affiliated Field: VB"
  • "Attribute: Vaccine (Va) Element: Light Field: VB, DS, WG"
  • "Attribute: Vi Elemental: Darkness Family: DA"
  • "Basic attribute: Unknown (Un) Natural attribute: Darkness (Darkness) Affiliated field: UK, TBD"
"""

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SCAN = PROJ / "data" / "scan_result_digimon.json"
CACHE = PROJ / "cache"

# Basic-attribute abbreviation → full name (matches gameking + DMW conventions).
ATTR_MAP = {
    "Va": "Vaccine",
    "Vi": "Virus",
    "Da": "Data",
    "Fr": "Free",
    "Un": "Unknown",
}
ATTR_ABBR = {v: k.upper() for k, v in ATTR_MAP.items()}

# gameking element terms → DMW Wiki canonical names (so chips render consistently).
ELEMENT_MAP = {
    "Darkness": "Pitch Black",
    "Lightning": "Thunder",  # e784 shows "Thunder (Lightning)" — Thunder wins
    # passthrough for already-canonical names
    "Light": "Light",
    "Fire": "Fire",
    "Water": "Water",
    "Wind": "Wind",
    "Wood": "Wood",
    "Earth": "Earth",
    "Steel": "Steel",
    "Thunder": "Thunder",
    "Neutral": "Neutral",
    "Pitch Black": "Pitch Black",
}

# Affiliated-field abbreviation → full family name.
FIELD_MAP = {
    "VB": "Virus Busters",
    "WG": "Wind Guardians",
    "NSp": "Nature Spirits",
    "NS": "Nature Spirits",
    "DS": "Deep Savers",
    "JT": "Jungle Troopers",
    "ME": "Metal Empire",
    "DR": "Dragon's Roar",
    "NSo": "Nightmare Soldiers",
    "UK": "Unknown",
    "DA": "Dark Area",
    "TBD": "TBD",
}


def html_to_text(raw: str) -> str:
    t = re.sub(r"<[^>]+>", " ", raw)
    t = t.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()


# KR equivalent — same stat block, Korean labels but English values in parens:
#   "기본 속성 : 데이터 (Da) 자연 속성 : 강철 (Steel) 소속 필드 : VB"
KR_STAT_BLOCK = re.compile(
    r"기본\s*속성\s*:\s*[^()]*\(\s*(?P<basic>[A-Za-z]{2,3})\s*\)\s*"
    r"자연\s*속성\s*:\s*[^()]*\(\s*(?P<elem>[A-Za-z ]+)\s*\)\s*"
    r"소속\s*필드\s*:\s*(?P<field>[A-Za-z, /]+?)\s*(?:스탯|스킬|$)",
)


# Capture one "Basic Attribute / Natural Attribute / Affiliated Field" block.
# Across posts the labels vary in casing, spacing, and separator:
#   "Basic Attribute:" / "Attribute :" (space before colon)
#   between-field separators: whitespace, "◎", "/"
#   field label: "Affiliated field" / "Field" / "Family"
# Values:
#   basic → optional name + parenthesised abbr, or just abbreviation ("Vi", "(Va)")
#   elem  → single word, optionally followed by "(<canonical>)"
#   field → comma- or slash-separated abbreviations (case-insensitive)
SEP = r"[\s◎]*"  # any whitespace or `◎` glyph between fields
STAT_BLOCK = re.compile(
    r"(?:Basic\s+)?Attribute\s*:\s*"
    r"(?P<basic>(?:[A-Za-z]+\s*)?(?:\([A-Za-z]{2,3}\))?)"
    + SEP
    + r"(?:Natural\s+Attribute|Elemental|Element)\s*:\s*"
    r"(?P<elem>(?:\([A-Za-z]+\)|[A-Za-z]+))"
    r"(?:\s*\([A-Za-z ]+\))?" + SEP + r"(?:Affiliated\s+[Ff]ield|Field|Family)\s*:?\s*"
    r"(?P<field>[A-Za-z, /]+?)"
    r"(?=\s*(?:[-•]|Stat|Skill|How|&|$|\[))",
    re.IGNORECASE,
)


def parse_kr_stat_blocks(text: str) -> list[dict]:
    """Parse all KR-site Korean stat blocks (values in parens are canonical
    English forms — same mapping logic as the EN block)."""
    out: list[dict] = []
    for m in KR_STAT_BLOCK.finditer(text):
        abbr = m.group("basic").title()
        name = ATTR_MAP.get(abbr)
        elem_raw = m.group("elem").strip().title()
        element = ELEMENT_MAP.get(elem_raw, elem_raw)
        field_lookup = {k.lower(): v for k, v in FIELD_MAP.items()}
        families: list[str] = []
        for tok in re.split(r"[,/]", m.group("field")):
            tok = tok.strip()
            if not tok:
                continue
            full = field_lookup.get(tok.lower())
            if full and full not in families:
                families.append(full)
        block: dict = {}
        if name:
            block["attribute"] = name
            block["attribute_abbr"] = abbr.upper()
        if element:
            block["natural_attribute"] = element
        if families:
            block["families"] = families
        if block:
            out.append(block)
    return out


def parse_kr_stat_block(text: str) -> dict | None:
    blocks = parse_kr_stat_blocks(text)
    return blocks[0] if blocks else None


def parse_stat_blocks(text: str) -> list[dict]:
    """Return ALL stat blocks in document order (one per digimon in a
    multi-digimon post like e782 Goddramon + Holydramon (Awaken))."""
    out: list[dict] = []
    for m in STAT_BLOCK.finditer(text):
        block = _block_from_match(m)
        if block:
            out.append(block)
    return out


def parse_stat_block(text: str) -> dict | None:
    """Return the first stat block, or None."""
    blocks = parse_stat_blocks(text)
    return blocks[0] if blocks else None


def _block_from_match(m: re.Match) -> dict | None:

    # ---- Basic attribute -----------------------------------------------------
    raw_basic = m.group("basic").strip()
    abbr = None
    name = None
    am = re.search(r"\(([A-Za-z]{2,3})\)", raw_basic)
    if am:
        abbr = am.group(1).title()
        if abbr in ATTR_MAP:
            name = ATTR_MAP[abbr]
    if not name:
        # Sometimes the long form is present without parens ("Vaccine"); strip
        # the abbreviation parenthetical and try the leading word.
        word = re.sub(r"\(.*?\)", "", raw_basic).strip()
        if word in ATTR_MAP.values():
            name = word
            abbr = ATTR_ABBR[word][:2].title()
        elif word.title() in ATTR_MAP:
            # Bare abbreviation like "Vi" / "Va"
            abbr = word.title()
            name = ATTR_MAP[abbr]

    # ---- Natural attribute (element) ----------------------------------------
    raw_elem = m.group("elem").strip().strip("()")
    element = ELEMENT_MAP.get(raw_elem.title(), raw_elem.title())

    # ---- Affiliated field ----------------------------------------------------
    # gameking case varies wildly: "Nso", "NSo", "NSO", "Uk", "UK" — match
    # case-insensitively against FIELD_MAP keys.
    field_lookup = {k.lower(): v for k, v in FIELD_MAP.items()}
    families: list[str] = []
    for tok in re.split(r"[,/]", m.group("field")):
        tok = tok.strip()
        if not tok:
            continue
        full = field_lookup.get(tok.lower())
        if full and full not in families:
            families.append(full)

    out: dict = {}
    if name:
        out["attribute"] = name
        out["attribute_abbr"] = abbr.upper() if abbr else ATTR_ABBR.get(name, "UN")
    if element:
        out["natural_attribute"] = element
    if families:
        out["families"] = families
    return out or None


def merge(existing: dict | None, gk: dict) -> dict:
    """Prefer gameking/KR data over wiki — gameking is the in-game source of
    truth so its field list / element naming wins when present. For
    `attribute` we additionally upgrade if existing says 'Unknown'.
    Wiki values are kept only when gameking doesn't supply that field.
    """
    out = dict(existing or {})
    # attribute: gameking wins unless gameking itself says Unknown and wiki had a real answer.
    if gk.get("attribute"):
        new = gk["attribute"]
        cur = out.get("attribute")
        if not cur or cur == "Unknown" or new != "Unknown":
            out["attribute"] = new
            out["attribute_abbr"] = gk.get("attribute_abbr") or ATTR_ABBR.get(new, "UN")
    if gk.get("natural_attribute"):
        out["natural_attribute"] = gk["natural_attribute"]
    if gk.get("families"):
        out["families"] = gk["families"]
    return out


def main() -> None:
    data = json.loads(SCAN.read_text(encoding="utf-8"))
    filled, augmented, missed = 0, 0, []

    for kind in ("event", "patch"):
        prefix = "event" if kind == "event" else "patch"
        for idx, post in data.get(kind, {}).items():
            blocks: list[dict] = []
            origin: str = ""
            cache_file = CACHE / f"{prefix}_{idx}.html"
            if cache_file.exists():
                text = html_to_text(cache_file.read_text(encoding="utf-8"))
                blocks = parse_stat_blocks(text)
                if blocks:
                    origin = "gameking"

            # Fallback to KR site cache (cache/kr_view_o<N>.html) — primary
            # path for posts that gameking didn't translate (e.g. e664) and
            # backup for any English block the regex missed.
            if not blocks:
                kr_o = None
                src = post.get("source_kr") or post.get("source") or ""
                mm = re.search(r"[?&]o=(\d+)", src)
                if mm:
                    kr_o = mm.group(1)
                if kr_o:
                    kr_file = CACHE / f"kr_view_o{kr_o}.html"
                    if kr_file.exists():
                        kr_text = html_to_text(kr_file.read_text(encoding="utf-8"))
                        blocks = parse_kr_stat_blocks(kr_text)
                        if blocks:
                            origin = "kr"

            if not blocks:
                missed.append(
                    f"{kind} {idx}: stat block not found"
                    + ("" if cache_file.exists() else " (no gameking cache)")
                )
                continue

            # Multi-digimon posts (e.g. e782 Goddramon + Holydramon Awaken)
            # carry one block per digimon, in the same order as `digimon`.
            # Single-block posts apply to every name.
            names = post["digimon"]
            if len(blocks) == len(names):
                pairs = list(zip(names, blocks, strict=True))
            elif len(blocks) == 1:
                pairs = [(n, blocks[0]) for n in names]
            else:
                # Count mismatch — apply the first block to every name; warn.
                print(
                    f"  ! {kind}_{idx}: {len(blocks)} blocks vs {len(names)} digimon — using first"
                )
                pairs = [(n, blocks[0]) for n in names]

            print(f"{kind}_{idx}: {origin} → {len(blocks)} block(s)")
            attrs_map = post.setdefault("attributes", {})
            for name, gk in pairs:
                print(f"    {name}: {gk}")
                before = attrs_map.get(name)
                merged = merge(before, gk)
                if merged != before:
                    if before is None:
                        filled += 1
                    else:
                        augmented += 1
                    attrs_map[name] = merged

    SCAN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n--- filled {filled} new, augmented {augmented} existing ---")
    if missed:
        print(f"--- {len(missed)} skipped: ---")
        for m in missed:
            print(f"  {m}")


if __name__ == "__main__":
    main()
