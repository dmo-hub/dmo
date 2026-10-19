"""Download the Thai banner image for each post that has a TH match
(`_th_image_url` set by enrich_digimon_th.py) → docs/img/digimon/<prefix><idx>_th.<ext>,
and add `image_th` field to scan_result_digimon.json.

build_digimon_html.py prefers `image_th` over `image` when present, so the Thai
banner becomes the primary image for posts with a TH equivalent (per the user's
"ถ้ามีให้ใช้ภาพจากไทย" preference).

Run after enrich_digimon_th.py. Pass --force to re-download existing.
"""

import io
import re
import sys

import requests
from PIL import Image

from _image_common import IMG_DIR, load_scan, save_scan

sys.stdout.reconfigure(encoding="utf-8")

# vplay.in.th ต้องการ browser UA เต็ม — ไม่ใช้ HEADERS กลางของ _image_common
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def ext_from(url: str, content_type: str = "") -> str:
    m = re.search(r"\.(png|jpe?g|gif|webp)(?:\?|$)", url.lower())
    if m:
        return "jpeg" if m.group(1) == "jpg" else m.group(1)
    if "png" in content_type:
        return "png"
    if "jpeg" in content_type or "jpg" in content_type:
        return "jpeg"
    return "jpg"


# The card shows these at most 320px tall, but a click opens the file itself and
# the posts carry their text inside the picture -- keep enough width to read it.
# vplay serves multi-MB PNG screenshots that are fully opaque.
MAX_W = 1200


def shrink(content: bytes, ext: str) -> tuple[bytes, str]:
    try:
        im = Image.open(io.BytesIO(content))
        im.load()
    except Exception:
        return content, ext
    if ext in ("jpeg", "jpg") and im.width <= MAX_W:
        return content, ext  # re-encoding a JPEG only loses quality on every run
    if ext == "gif" or im.convert("RGBA").getextrema()[3][0] < 255:
        return content, ext  # animation or real transparency: JPEG would break it
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    out = buf.getvalue()
    return (out, "jpeg") if len(out) < len(content) else (content, ext)


def shrink_existing(data: dict) -> int:
    """Re-encode files saved before shrink() existed; already-small ones stay put."""
    done = 0
    for kind in ("event", "patch"):
        for post in data.get(kind, {}).values():
            rel = post.get("image_th")
            if not rel:
                continue
            src = IMG_DIR.parent.parent / rel
            if not src.exists():
                continue
            raw = src.read_bytes()
            body, ext = shrink(raw, src.suffix.lstrip("."))
            if body is raw:
                continue
            out = src.with_suffix("." + ext)
            if out != src:
                src.unlink()
            out.write_bytes(body)
            post["image_th"] = f"img/digimon/{out.name}"
            done += 1
            print(f"  shrank {src.name} -> {out.name} ({len(raw) // 1024} -> {len(body) // 1024} KB)")
    return done


def delete_existing(prefix: str, idx: str, suffix: str = "") -> None:
    for f in IMG_DIR.glob(f"{prefix}{idx}{suffix}.*"):
        f.unlink()
        print(f"  deleted {f.name}")


def main() -> None:
    force = "--force" in sys.argv
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    data = load_scan()

    extracted = 0
    skipped_existing = 0
    no_url = 0

    for kind in ("event", "patch"):
        prefix = "e" if kind == "event" else "p"
        for idx, post in data.get(kind, {}).items():
            url = post.get("_th_image_url")
            if not url:
                no_url += 1
                continue

            existing = post.get("image_th")
            if existing and not force:
                skipped_existing += 1
                continue

            try:
                r = requests.get(url, headers=HEADERS, timeout=30)
                r.raise_for_status()
            except Exception as e:
                print(f"  ERROR {kind}_{idx}: fetch {url[:60]} failed: {e}")
                continue

            body, ext = shrink(r.content, ext_from(url, r.headers.get("content-type", "")))
            delete_existing(prefix, idx, suffix="_th")
            out = IMG_DIR / f"{prefix}{idx}_th.{ext}"
            out.write_bytes(body)
            post["image_th"] = f"img/digimon/{out.name}"
            extracted += 1
            print(f"{kind}_{idx}: {out.name} ({len(body) // 1024} KB)")

    shrunk = shrink_existing(data)
    save_scan(data)
    print(f"\nExtracted: {extracted}, shrunk: {shrunk}, kept existing: {skipped_existing}, no TH image URL: {no_url}")


if __name__ == "__main__":
    main()
