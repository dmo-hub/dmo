"""Fetch missing digimon images from Digital Masters World Wiki.

Looks for entries in scan_result_digimon.json that have no `image` field.
For each, derives candidate URLs from the digimon name(s) using DMW Wiki
filename convention (spaces → underscores, drop punctuation) and tries until
one returns 200. Saves to docs/img/digimon/<idx>.png and updates JSON.

Usage:
  python fetch_dmw_images.py            # missing only
  python fetch_dmw_images.py --force    # re-fetch every post from DMW Wiki
"""

import json
import re
import sys
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SCAN = PROJ / "data" / "scan_result_digimon.json"
IMG_DIR = PROJ / "docs" / "img" / "digimon"

WIKI = "https://digitalmastersworld.wiki.gg/images"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://digitalmastersworld.wiki.gg/",
    "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
}


def name_candidates(raw_name: str) -> list[str]:
    """Generate candidate DMW Wiki filename slugs from a digimon name.

    Tries the full name, then a version with any leading [Bracket] / (Paren)
    qualifier stripped (e.g. "[Extreme] Lucemon..." → "Lucemon..."), each
    with/without parens. Treats both kinds of dash and the colon as separators.

    Does NOT fall back to bare first word — that would substitute a specific
    form (e.g. "Omegamon Merciful Mode") with the generic base form
    ("Omegamon.png"), which is the wrong portrait.

    Examples:
      "Omegamon – Merciful Mode" → ["Omegamon_Merciful_Mode"]
      "[Extreme] Lucemon : Satan Mode" → ["Extreme_Lucemon_Satan_Mode", "Lucemon_Satan_Mode"]
      "Alphamon Ouryuken (Extreme)" → ["Alphamon_Ouryuken_(Extreme)", "Alphamon_Ouryuken_Extreme"]
    """
    sources = [raw_name]
    # Add a stripped version if there's a leading [...] or (...) qualifier
    stripped = re.sub(r"^\s*[\[(][^\])]+[\])]\s*", "", raw_name).strip()
    if stripped and stripped != raw_name:
        sources.append(stripped)

    candidates: list[str] = []
    for s in sources:
        # Variant: keep parens (matches wiki filenames like "Alphamon_Ouryuken_(Extreme).png")
        a = re.sub(r"[\-–—:\[\]]", " ", s)
        a = re.sub(r"\s+", " ", a).strip().replace(" ", "_")
        # Variant: drop parens too
        b = re.sub(r"[\-–—:\[\]()]", " ", s)
        b = re.sub(r"\s+", " ", b).strip().replace(" ", "_")
        candidates.extend([a, b])

    seen, out = set(), []
    for v in candidates:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def try_fetch(slug: str) -> tuple[bytes, str] | None:
    for ext in ("png", "jpg", "jpeg"):
        url = f"{WIKI}/{slug}.{ext}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200 and r.content:
                return r.content, ext
        except Exception:
            continue
    return None


def main() -> None:
    force = "--force" in sys.argv
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(SCAN.read_text(encoding="utf-8"))

    updated = 0
    for kind in ("event", "patch"):
        prefix = "e" if kind == "event" else "p"
        for idx, post in data.get(kind, {}).items():
            if post.get("image") and not force:
                continue
            print(f"\n{kind}_{idx}: trying {post['digimon']}")
            blob_ext = None
            for name in post["digimon"]:
                for slug in name_candidates(name):
                    result = try_fetch(slug)
                    if result:
                        print(f"  ✓ {slug}.{result[1]} ({len(result[0]) // 1024} KB)")
                        blob_ext = result
                        break
                    else:
                        print(f"  ✗ {slug}")
                if blob_ext:
                    break
            if blob_ext:
                blob, ext = blob_ext
                out = IMG_DIR / f"{prefix}{idx}.{ext}"
                out.write_bytes(blob)
                post["image"] = f"img/digimon/{out.name}"
                updated += 1

    SCAN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nUpdated {updated} entries in {SCAN.name}")


if __name__ == "__main__":
    main()
