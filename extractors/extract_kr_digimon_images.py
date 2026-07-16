"""Extract the digimon banner image from each KR post → docs/img/digimon/<prefix><idx>_kr.<ext>.

Dual of [extract_digimon_images.py](extract_digimon_images.py) but reads from the
KR cache (`cache/kr_view_o<N>.html`) instead of the gameking cache. Adds an
`image_kr` field to scan_result_digimon.json so the HTML builder can render both
the EN (gameking) and KR (digimonmasters.com) portraits side-by-side, letting a
human pick the better one later.

KR posts typically embed exactly one inline base64 PNG with the full digimon-info
graphic (evolution tree + portrait), which is what we save.

Source for each post = `source_kr` in scan_result_digimon.json (set by
[enrich_digimon_kr.py](enrich_digimon_kr.py)). Posts without `source_kr` are
skipped.

Run after enrich_digimon_kr.py. Pass --force to re-extract overwriting existing.
"""

import re
import sys
from pathlib import Path

from _image_common import CACHE, IMG_DIR, extract_image, load_scan, save_scan

sys.stdout.reconfigure(encoding="utf-8")

# Filter out chrome (logos, footer icons, etc.) — KR pages embed several of these.
SKIP_URL_KEYWORDS = ("logo", "icon", "/footer/", "/header/", "btn_", "violent", "renewal_main/")


def is_chrome(src: str) -> bool:
    s = src.lower()
    return any(k in s for k in SKIP_URL_KEYWORDS)


def kr_cache_file(source_kr: str) -> Path | None:
    """Find `cache/kr_view_o<N>.html` matching a `digimonmasters.com ...?o=N` URL."""
    m = re.search(r"[?&]o=(\d+)", source_kr)
    if not m:
        return None
    f = CACHE / f"kr_view_o{m.group(1)}.html"
    return f if f.exists() else None


def main() -> None:
    force = "--force" in sys.argv
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    data = load_scan()

    extracted = 0
    skipped_existing = 0
    no_source = 0
    no_image = 0

    for kind in ("event", "patch"):
        prefix = "e" if kind == "event" else "p"
        for idx, post in data.get(kind, {}).items():
            source_kr = post.get("source_kr")
            if not source_kr:
                no_source += 1
                continue

            existing = post.get("image_kr")
            if existing and not force:
                skipped_existing += 1
                continue

            cf = kr_cache_file(source_kr)
            if cf is None:
                print(f"skip {kind}_{idx}: no KR cache for {source_kr}")
                continue

            result = extract_image(
                cf.read_text(encoding="utf-8"),
                url_ok=lambda s: not is_chrome(s),
                absolutize=lambda s: s if s.startswith("http") else f"https://www.digimonmasters.com{s}",
            )
            if result is None:
                print(f"{kind}_{idx}: no image in KR cache")
                no_image += 1
                continue

            blob, ext = result
            out = IMG_DIR / f"{prefix}{idx}_kr.{ext}"
            out.write_bytes(blob)
            post["image_kr"] = f"img/digimon/{out.name}"
            extracted += 1
            print(f"{kind}_{idx}: {out.name} ({len(blob) // 1024} KB)")

    save_scan(data)
    print(
        f"\nExtracted: {extracted}, kept existing: {skipped_existing}, "
        f"no source_kr: {no_source}, no image: {no_image}"
    )


if __name__ == "__main__":
    main()
