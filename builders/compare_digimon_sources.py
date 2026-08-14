"""Side-by-side comparison of digimon stats across all 4 sources we cache:

  * gameking   — cache/{event,patch}_<idx>.html   (EventView / PatchNote)
  * KR site    — cache/kr_view_o<N>.html          (digimonmasters.com Update)
  * DMW Wiki   — cache/dmw_<slug>.html            (digitalmastersworld.wiki.gg)
  * dmowiki    — cache/dmowiki_<safe-slug>.html   (dmowiki.com)

For each digimon, pulls (attribute, natural_attribute, families) from every
cache that has the page, then prints them aligned so divergences are obvious.
Use this to audit which source we should trust when scan_result_digimon.json
has been auto-enriched.

Run:  python compare_digimon_sources.py        # all digimon
      python compare_digimon_sources.py 663    # just one event idx
"""

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SCAN = PROJ / "data" / "scan_result_digimon.json"
CACHE = PROJ / "cache"

# Re-use parsers we already wrote (repo is split into stage subfolders).
sys.path.insert(0, str(PROJ / "enrichers"))
sys.path.insert(0, str(PROJ / "fetchers"))
from enrich_digimon_attributes import (  # type: ignore
    parse_dmowiki,
)
from enrich_digimon_gameking import (  # type: ignore
    html_to_text,
    parse_kr_stat_blocks,
    parse_stat_blocks,
)
from fetch_dmowiki_digimon import (  # type: ignore
    build_rank_u_map,
    resolve_slug,
    safe_filename,
)


def load_gk_blocks(kind: str, idx: str) -> list[dict]:
    prefix = "event" if kind == "event" else "patch"
    f = CACHE / f"{prefix}_{idx}.html"
    if not f.exists():
        return []
    return parse_stat_blocks(html_to_text(f.read_text(encoding="utf-8")))


def load_kr_blocks(post: dict) -> list[dict]:
    src = post.get("source_kr") or post.get("source") or ""
    m = re.search(r"[?&]o=(\d+)", src)
    if not m:
        return []
    f = CACHE / f"kr_view_o{m.group(1)}.html"
    if not f.exists():
        return []
    return parse_kr_stat_blocks(html_to_text(f.read_text(encoding="utf-8")))


def load_dmowiki(name: str, rank_map: dict[str, str]) -> dict | None:
    slug = resolve_slug(name, rank_map)
    if not slug:
        return None
    f = CACHE / f"dmowiki_{safe_filename(slug)}.html"
    if not f.exists():
        return None
    return parse_dmowiki(f.read_text(encoding="utf-8"))


def fmt(b: dict | None) -> tuple[str, str, str]:
    if not b:
        return ("—", "—", "—")
    return (
        b.get("attribute") or "—",
        b.get("natural_attribute") or "—",
        ", ".join(b.get("families", [])) or "—",
    )


def pick_block(blocks: list[dict], idx_in_post: int) -> dict | None:
    """Pick the block matching this digimon's position in a multi-digimon
    post, falling back to the first block if counts mismatch."""
    if not blocks:
        return None
    if idx_in_post < len(blocks):
        return blocks[idx_in_post]
    return blocks[0]


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    data = json.loads(SCAN.read_text(encoding="utf-8"))
    rank_map = build_rank_u_map()

    divergences = 0
    print(f"{'idx':>6}  {'digimon':42s}  {'source':>9}  {'attr':8s} {'element':12s} {'families'}")
    print("-" * 130)
    for kind in ("event", "patch"):
        for idx, post in data.get(kind, {}).items():
            if only and idx != only:
                continue
            gk_blocks = load_gk_blocks(kind, idx)
            kr_blocks = load_kr_blocks(post)
            for i, name in enumerate(post["digimon"]):
                gk = pick_block(gk_blocks, i)
                kr = pick_block(kr_blocks, i)
                dmowiki = load_dmowiki(name, rank_map)

                # 3 trustworthy sources only — dmw (digitalmastersworld.wiki.gg)
                # was blocklisted because its Awaken/Extreme pages serve
                # base-form data that disagrees with the game.
                rows = [
                    ("gameking", gk),
                    ("kr", kr),
                    ("dmowiki", dmowiki),
                ]
                # Decide if there's a non-trivial divergence (ignore None
                # and ignore order for families).
                attrs = {r[1].get("attribute") for r in rows if r[1]}
                elems = {r[1].get("natural_attribute") for r in rows if r[1]}
                fam_sets = {
                    frozenset(r[1]["families"]) for r in rows if r[1] and r[1].get("families")
                }
                flag = ""
                if len({a for a in attrs if a and a != "Unknown"}) > 1:
                    flag = " ⚠ attr"
                if len({e for e in elems if e}) > 1:
                    flag += " ⚠ elem"
                if len(fam_sets) > 1:
                    flag += " ⚠ field"
                if flag:
                    divergences += 1

                print(
                    f"{(kind[0] + idx):>6}  {name[:42]:42s}                                            {flag}"
                )
                for src, b in rows:
                    a, e, f = fmt(b)
                    marker = " " if b else "·"
                    print(f"        {'':42s} {marker} {src:>9s}  {a:8s} {e:12s} {f}")
                print()

    print(f"-- {divergences} digimon have a non-trivial divergence across sources --")


if __name__ == "__main__":
    main()
