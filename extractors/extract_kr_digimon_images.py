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


def extract_image(raw: str) -> tuple[bytes, str] | None:
    """Pick the first non-chrome image. Prefers inline base64 (the digimon graphic)."""
    # 1. Inline base64 — usually the digimon banner
    m = DATA_URL_RE.search(raw)
    if m:
        ext = m.group(2).lower()
        try:
            return base64.b64decode(m.group(3), validate=False), ext
        except Exception as e:
            print(f"  WARN: base64 decode failed: {e}")

    # 2. External URL — skip header/footer chrome
    for src in IMG_RE.findall(raw):
        if src.startswith("data:") or is_chrome(src):
            continue
        url = src if src.startswith("http") else f"https://www.digimonmasters.com{src}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            ext = url.rsplit(".", 1)[-1].lower().split("?")[0]
            if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                ext = "jpg"
            return r.content, ext
        except Exception as e:
            print(f"  WARN: fetch {url[:60]} failed: {e}")
            continue
    return None


def main() -> None:
    force = "--force" in sys.argv
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(SCAN.read_text(encoding="utf-8"))

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

            result = extract_image(cf.read_text(encoding="utf-8"))
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

    SCAN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\nExtracted: {extracted}, kept existing: {skipped_existing}, "
        f"no source_kr: {no_source}, no image: {no_image}"
    )


if __name__ == "__main__":
    main()
