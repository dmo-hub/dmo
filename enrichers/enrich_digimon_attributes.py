"""Fetch Basic Attribute / Natural Attribute / Field for each digimon from
the dmowiki.com cache (fetched via fetch_dmowiki_digimon.py over CDP), and
add them to scan_result_digimon.json.

Source:
  cache/dmowiki_<safe-slug>.html
    Manually fetched via fetch_dmowiki_digimon.py (Cloudflare-blocked, so
    needs a Playwright session attached to a running Chrome instance).

`digitalmastersworld.wiki.gg` (formerly the `dmw:` fallback in this script)
is **blocklisted** — its Awaken/Extreme pages fall back to base-form data,
which doesn't match what the game actually ships. See
.claude memory `dmw-wiki-blocklist` for the rationale.

Fields extracted:
  - attribute            "Vaccine" / "Virus" / "Data" / "Free" / "Unknown"
  - natural_attribute    "Light" / "Fire" / "Wood" / ... (element)
  - families             ["Virus Busters", "Wind Guardians", ...] (fields)

The result is attached per-digimon as a parallel `attributes` dict on each
post so existing readers that expect `digimon: list[str]` still work.

Usage:
  python enrich_digimon_attributes.py            # missing only
  python enrich_digimon_attributes.py --force    # re-parse every digimon
"""

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SCAN = PROJ / "data" / "scan_result_digimon.json"
CACHE = PROJ / "cache"
CACHE.mkdir(exist_ok=True)

ABBR = {"Vaccine": "VA", "Virus": "VI", "Data": "DA", "Free": "FR"}

BASIC_ATTRS = {"Vaccine", "Virus", "Data", "Free"}
NATURAL_ATTRS = {
    "Fire",
    "Water",
    "Earth",
    "Wind",
    "Wood",
    "Light",
    "Steel",
    "Thunder",
    "Pitch Black",
    "Neutral",
}
FAMILIES = {
    "Virus Busters",
    "Wind Guardians",
    "Nightmare Soldiers",
    "Jungle Troopers",
    "Nature Spirits",
    "Deep Savers",
    "Metal Empire",
    "Dragon's Roar",
    "Unknown",
    "Dark Area",
}


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def parse_infobox(html: str) -> dict | None:
    """Pull Basic Attribute, Natural Attribute, and Families from a MediaWiki
    digimon infobox. Both dmowiki and (formerly) dmw use the same scraper-*
    ids — this still works for the dmowiki cache we keep.
    """

    def cell_by_id(id_: str) -> str | None:
        m = re.search(rf'id="{id_}"[^>]*>(.*?)</td>', html, re.S)
        if not m:
            return None
        return strip_tags(m.group(1))

    attr = cell_by_id("scraper-digimon-attribute")
    natural = cell_by_id("scraper-digimon-naturalattribute")

    families: list[str] = []
    m = re.search(r"Families:\s*</a>\s*</b>\s*</td>\s*<td[^>]*>(.*?)</td>", html, re.S)
    if m:
        cell = m.group(1)
        for fm in re.finditer(
            r'href="/wiki/Category:([^"]+)" title="Category:[^"]+">([^<]+)</a>',
            cell,
        ):
            label = fm.group(2).strip()
            if label and label not in families:
                families.append(label)

    if not (attr or natural or families):
        return None

    result: dict = {}
    if attr:
        result["attribute"] = attr
        if attr in ABBR:
            result["attribute_abbr"] = ABBR[attr]
    if natural:
        result["natural_attribute"] = natural
    if families:
        result["families"] = families
    return result


def parse_dmowiki(html: str) -> dict | None:
    """Parse a dmowiki.com page. Try the infobox first; fall back to the
    MediaWiki `wgCategories` JSON which dmowiki tags every digimon page with
    (e.g. "Vaccine Attribute", "Light Attribute", "Virus Busters").
    """
    via_infobox = parse_infobox(html)
    if via_infobox:
        return via_infobox

    m = re.search(r'"wgCategories":\[([^\]]+)\]', html)
    if not m:
        return None
    cats = [c.strip().strip('"') for c in m.group(1).split(",")]

    result: dict = {}
    for c in cats:
        if c.endswith(" Attribute"):
            name = c[: -len(" Attribute")].strip()
            if name in BASIC_ATTRS or name == "Unknown":
                result["attribute"] = name
                if name in ABBR:
                    result["attribute_abbr"] = ABBR[name]
            else:
                # Any "<X> Attribute" not in BASIC is treated as natural.
                result.setdefault("natural_attribute", name)
        elif c in FAMILIES:
            result.setdefault("families", []).append(c)

    return result or None


def lookup(name: str) -> tuple[dict, str] | None:
    """Find dmowiki cache by name. Uses the same resolve_slug() the fetcher
    used (rank_u.html + OVERRIDES) so matching is exact — no fuzzy
    substring traps."""
    try:
        from fetch_dmowiki_digimon import (
            build_rank_u_map,
            resolve_slug,
            safe_filename,
        )
    except Exception as e:
        print(f"    ! can't import fetch_dmowiki_digimon: {e}")
        return None
    if not hasattr(lookup, "_rank_map"):
        lookup._rank_map = build_rank_u_map()  # type: ignore[attr-defined]
    slug = resolve_slug(name, lookup._rank_map)  # type: ignore[attr-defined]
    if not slug:
        print("    ✗ no slug mapping (run fetch_dmowiki_digimon.py first)")
        return None
    f = CACHE / f"dmowiki_{safe_filename(slug)}.html"
    if not f.exists():
        print(f"    ✗ dmowiki:{slug} (no cache — run fetch_dmowiki_digimon.py)")
        return None
    attrs = parse_dmowiki(f.read_text(encoding="utf-8"))
    if attrs:
        print(f"    ✓ dmowiki:{slug} → {attrs}")
        return attrs, slug
    print(f"    ✗ dmowiki:{slug} (cache present, no infobox or categories)")
    return None


def main() -> None:
    force = "--force" in sys.argv
    data = json.loads(SCAN.read_text(encoding="utf-8"))

    updated = 0
    missing: list[str] = []
    for kind in ("event", "patch"):
        for idx, post in data.get(kind, {}).items():
            existing = post.get("attributes") or {}
            new_attrs = dict(existing) if not force else {}
            for name in post["digimon"]:
                if name in new_attrs and not force:
                    continue
                print(f"\n{kind}_{idx}: {name}")
                hit = lookup(name)
                if hit:
                    new_attrs[name] = hit[0]
                    updated += 1
                else:
                    missing.append(f"{kind} {idx}: {name}")
            if new_attrs:
                post["attributes"] = new_attrs

    SCAN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n--- Updated {updated} digimon entries in {SCAN.name} ---")
    if missing:
        print(f"--- {len(missing)} entries had no dmowiki match: ---")
        for m in missing:
            print(f"  {m}")


if __name__ == "__main__":
    main()
