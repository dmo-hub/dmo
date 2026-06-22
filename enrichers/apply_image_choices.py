"""One-shot script: apply user's image picks (EN / KR / external URL) to
scan_result_digimon.json. After running, each post will have a single `image`
field and the orphan `_kr` file (if any) is deleted. The `image_kr` field is
removed.

The CHOICES dict below is hand-built from the user's selections in the
interactive form. To re-run after a fresh extract: rebuild this dict from
fresh AskUserQuestion answers and re-run.
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

# Action: ("EN",) | ("KR",) | ("URL", "<url>") | ("REMOVE",)
CHOICES: dict[tuple[str, str], tuple] = {
    ("event", "663"): ("URL", "https://www.vplay.in.th/wp-content/uploads/2024/03/8.jpg"),
    ("event", "664"): ("EN",),
    ("event", "673"): ("KR",),
    ("event", "683"): ("KR",),
    ("event", "692"): ("EN",),
    ("event", "705"): ("EN",),
    ("event", "708"): ("KR",),
    ("event", "731"): ("KR",),
    ("event", "743"): ("KR",),
    ("event", "759"): ("EN",),
    ("event", "770"): ("EN",),
    ("event", "782"): ("KR",),
    ("event", "784"): ("EN",),
    ("event", "791"): ("URL", "https://dmowiki.com/images/5/52/Lilithmon_X.png"),
    ("event", "798"): ("KR",),
    ("event", "810"): (
        "URL",
        "https://static.wikia.nocookie.net/digimon/images/7/7c/Abbadomon_core_101.jpg/revision/latest?cb=20210928124811&path-prefix=zh",
    ),
    ("patch", "4110"): ("EN",),
    ("patch", "4121"): ("URL", "https://wikimon.net/images/d/d7/Omegamonx.jpg"),
    ("patch", "4148"): ("EN",),
}

HEADERS = {"User-Agent": "Mozilla/5.0 (dmoDeck/1.0)"}


def ext_for(url: str, content_type: str = "") -> str:
    """Best-guess extension from URL or content-type."""
    m = re.search(r"\.(png|jpe?g|gif|webp)", url.lower())
    if m:
        return "jpeg" if m.group(1) == "jpg" else m.group(1)
    if "png" in content_type:
        return "png"
    if "jpeg" in content_type or "jpg" in content_type:
        return "jpeg"
    if "webp" in content_type:
        return "webp"
    if "gif" in content_type:
        return "gif"
    return "jpg"


def delete_existing(prefix: str, idx: str, suffix: str = "") -> None:
    """Delete docs/img/digimon/<prefix><idx>[<suffix>].* (any extension)."""
    for f in IMG_DIR.glob(f"{prefix}{idx}{suffix}.*"):
        f.unlink()
        print(f"  deleted {f.name}")


def apply(kind: str, idx: str, post: dict, action: tuple) -> None:
    prefix = "e" if kind == "event" else "p"
    en_path = post.get("image")
    kr_path = post.get("image_kr")

    if action[0] == "EN":
        if not en_path:
            print(f"  WARN: no EN image to keep for {kind} {idx}")
            return
        # delete KR file + field
        if kr_path:
            kr_file = PROJ / "docs" / kr_path
            if kr_file.exists():
                kr_file.unlink()
                print(f"  deleted {kr_file.name}")
            post.pop("image_kr", None)
        print(f"  {kind} {idx}: kept EN ({en_path})")

    elif action[0] == "KR":
        if not kr_path:
            print(f"  WARN: no KR image to promote for {kind} {idx}")
            return
        # Move KR file into the non-_kr slot
        kr_file = PROJ / "docs" / kr_path
        if not kr_file.exists():
            print(f"  WARN: KR file missing on disk: {kr_file}")
            return
        # Delete old EN file (any extension)
        delete_existing(prefix, idx)
        new_name = kr_file.name.replace(f"{prefix}{idx}_kr.", f"{prefix}{idx}.")
        new_file = IMG_DIR / new_name
        kr_file.rename(new_file)
        post["image"] = f"img/digimon/{new_name}"
        post.pop("image_kr", None)
        print(f"  {kind} {idx}: promoted KR → {new_name}")

    elif action[0] == "URL":
        url = action[1]
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"  ERROR {kind} {idx}: fetch {url[:60]} failed: {e}")
            return
        ext = ext_for(url, r.headers.get("content-type", ""))
        # Delete both old EN + KR files
        delete_existing(prefix, idx)
        delete_existing(prefix, idx, suffix="_kr")
        new_file = IMG_DIR / f"{prefix}{idx}.{ext}"
        new_file.write_bytes(r.content)
        post["image"] = f"img/digimon/{new_file.name}"
        post.pop("image_kr", None)
        print(
            f"  {kind} {idx}: downloaded {new_file.name} ({len(r.content) // 1024} KB) from {url[:60]}"
        )

    elif action[0] == "REMOVE":
        delete_existing(prefix, idx)
        delete_existing(prefix, idx, suffix="_kr")
        post.pop("image", None)
        post.pop("image_kr", None)
        print(f"  {kind} {idx}: removed all images")


def main() -> None:
    data = json.loads(SCAN.read_text(encoding="utf-8"))
    for (kind, idx), action in CHOICES.items():
        post = data.get(kind, {}).get(idx)
        if not post:
            print(f"  SKIP: {kind} {idx} not in JSON")
            continue
        apply(kind, idx, post, action)

    SCAN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {SCAN.name}")


if __name__ == "__main__":
    main()
