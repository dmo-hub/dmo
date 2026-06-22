"""Extract one representative image per digimon post → docs/img/digimon/<idx>.<ext>.

Reads scan_result_digimon.json + cache HTML. For each post:
  - Find first relevant <img>: base64 (data:image), gameking URL, or Steam CDN URL
  - base64 → decode + save locally
  - URL → download via requests + save locally
Writes path into scan_result_digimon.json as `image` field (relative to docs/).

Run after scan_digimon.py.
"""

import base64
import json
import re
import sys
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
SCAN = PROJ / "data" / "scan_result_digimon.json"
IMG_DIR = PROJ / "docs" / "img" / "digimon"

HEADERS = {"User-Agent": "Mozilla/5.0 (dmoDeck/1.0)"}
DATA_URL_RE = re.compile(r'src=["\'](data:image/(\w+);base64,([^"\']+))["\']', re.IGNORECASE)
IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def is_relevant(src: str) -> bool:
    if src.startswith("data:image"):
        return True
    if "gameking.com/digimon" in src:
        return True
    if "akamai" in src or "steamstatic" in src:
        return True
    return False


def extract_image(raw: str) -> tuple[bytes, str] | None:
    """Return (bytes, ext) for first relevant image, or None."""
    # Try base64 first (already inline)
    m = DATA_URL_RE.search(raw)
    if m:
        ext = m.group(2).lower()
        try:
            data = base64.b64decode(m.group(3), validate=False)
            return data, ext
        except Exception as e:
            print(f"  WARN: base64 decode failed: {e}")

    # Try external URL
    for src in IMG_RE.findall(raw):
        if src.startswith("data:"):
            continue
        if not is_relevant(src):
            continue
        try:
            r = requests.get(src, headers=HEADERS, timeout=15)
            r.raise_for_status()
            ext = src.rsplit(".", 1)[-1].lower()
            if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                ext = "jpg"
            return r.content, ext
        except Exception as e:
            print(f"  WARN: fetch {src[:60]} failed: {e}")
            continue
    return None


def main() -> None:
    force = "--force" in sys.argv
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(SCAN.read_text(encoding="utf-8"))

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
            result = extract_image(raw)
            if result is None:
                print(f"{kind}_{idx}: no image found")
                continue
            blob, ext = result
            out = IMG_DIR / f"{prefix}{idx}.{ext}"
            out.write_bytes(blob)
            # Path relative to docs/ (used as <img src=...> from docs/digimon.html)
            post["image"] = f"img/digimon/{out.name}"
            print(f"{kind}_{idx}: {out.name} ({len(blob) // 1024} KB)")

    SCAN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nUpdated {SCAN.name}")


if __name__ == "__main__":
    main()
