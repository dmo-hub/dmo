"""Shared plumbing for the per-server image extractors
(extract_digimon_images.py, extract_kr_digimon_images.py, extract_th_digimon_images.py).

Common paths + scan JSON round-trip + the base64-first-then-URL image
extraction core. Per-server URL relevance filters, cache resolution, and the
main loops stay in each extractor — their semantics genuinely differ.
"""
import base64
import json
import re
from pathlib import Path

import requests

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
SCAN = PROJ / "data" / "scan_result_digimon.json"
IMG_DIR = PROJ / "docs" / "img" / "digimon"

HEADERS = {"User-Agent": "Mozilla/5.0 (dmoDeck/1.0)"}
DATA_URL_RE = re.compile(r'src=["\'](data:image/(\w+);base64,([^"\']+))["\']', re.IGNORECASE)
IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def load_scan() -> dict:
    return json.loads(SCAN.read_text(encoding="utf-8"))


def save_scan(data: dict) -> None:
    SCAN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def norm_ext(url: str) -> str:
    ext = url.rsplit(".", 1)[-1].lower().split("?")[0]
    return ext if ext in ("jpg", "jpeg", "png", "gif", "webp") else "jpg"


def extract_image(raw: str, url_ok, absolutize=lambda s: s) -> tuple[bytes, str] | None:
    """(bytes, ext) of first relevant image in raw HTML — inline base64 wins,
    else first <img> URL passing url_ok (absolutize maps relative src → full URL)."""
    m = DATA_URL_RE.search(raw)
    if m:
        try:
            return base64.b64decode(m.group(3), validate=False), m.group(2).lower()
        except Exception as e:
            print(f"  WARN: base64 decode failed: {e}")

    for src in IMG_RE.findall(raw):
        if src.startswith("data:") or not url_ok(src):
            continue
        url = absolutize(src)
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.content, norm_ext(url)
        except Exception as e:
            print(f"  WARN: fetch {url[:60]} failed: {e}")
    return None
