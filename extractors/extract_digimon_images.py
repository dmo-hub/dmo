"""Extract one representative image per digimon post → docs/img/digimon/<idx>.<ext>.

Reads scan_result_digimon.json + cache HTML. For each post:
  - Find first relevant <img>: base64 (data:image), gameking URL, or Steam CDN URL
  - base64 → decode + save locally
  - URL → download via requests + save locally
Writes path into scan_result_digimon.json as `image` field (relative to docs/).

Run after scan_digimon.py.
"""

import sys

from _image_common import CACHE, IMG_DIR, extract_image, load_scan, save_scan

sys.stdout.reconfigure(encoding="utf-8")


def is_relevant(src: str) -> bool:
    if src.startswith("data:image"):
        return True
    if "gameking.com/digimon" in src:
        return True
    if "akamai" in src or "steamstatic" in src:
        return True
    return False


def main() -> None:
    force = "--force" in sys.argv
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    data = load_scan()

    for kind in ("event", "patch"):
        prefix = "e" if kind == "event" else "p"
        for idx, post in data.get(kind, {}).items():
            if post.get("image") and not force:
                # Already has an image (possibly hand-curated or from another source).
                # Don't overwrite — use --force to re-extract from cache.
                continue
            cache_file = CACHE / f"{kind}_{idx}.html"
            if not cache_file.exists():
                print(f"skip {kind}_{idx}: no cache")
                continue
            raw = cache_file.read_text(encoding="utf-8")
            result = extract_image(raw, url_ok=is_relevant)
            if result is None:
                print(f"{kind}_{idx}: no image found")
                continue
            blob, ext = result
            out = IMG_DIR / f"{prefix}{idx}.{ext}"
            out.write_bytes(blob)
            # Path relative to docs/ (used as <img src=...> from docs/digimon.html)
            post["image"] = f"img/digimon/{out.name}"
            print(f"{kind}_{idx}: {out.name} ({len(blob) // 1024} KB)")

    save_scan(data)
    print("\nUpdated scan_result_digimon.json")


if __name__ == "__main__":
    main()
