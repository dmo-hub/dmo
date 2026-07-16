"""Match each entry in scan_result_digimon.json to its Thai-server release
(vplay.in.th) by content keyword and add `source_th` + `date_th` fields.

The Thai server lags NA/KR by 10–12 months, so most recent NA entries simply
have no Thai equivalent yet — that's expected and reported as "no Thai match".

Reads:  scan_result_digimon.json, th_patch_digimon.json
Writes: scan_result_digimon.json (updates `source_th`, `date_th`)

When a new digimon is added to scan_result_digimon.json, look at the Thai
transliteration in [th_patch_digimon.json](th_patch_digimon.json) and add an
entry to EN_TO_TH_KEYWORDS below.
"""

import json
import sys
from datetime import date
from pathlib import Path

from _content_match import find_matches, lookup_keyword, parse_iso, parse_mmddyyyy

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
DIGIMON = PROJ / "data" / "scan_result_digimon.json"
TH_DIGIMON = PROJ / "data" / "th_patch_digimon.json"

# (EN_substring, TH_substring, required_th_modifier_or_None).
# Match logic:
#   1. find first tuple where `en_kw` is a substring of the EN digimon name
#   2. find TH posts whose `th_name` contains `th_kw`
#   3. if `required_th_modifier` is set, also require it in `th_name`
#      (used to disambiguate e.g. Alphamon Ouryuken Extreme vs Awaken)
# Keep keywords as specific as possible — substring matching on "โอเมกามอน"
# alone would catch every Omegamon variant including Alter-B.
# Order matters: list MORE specific compound names FIRST.
EN_TO_TH_KEYWORDS: list[tuple[str, str, str | None]] = [
    # More specific compound names first
    ("Abbadomon Core", "อบาดอน คอร์", None),
    ("Shoutmon X7 Superior", "ซูพีเรียร์", None),
    ("Kuzuhamon Miko", "มิโกะ", None),
    ("Gallantmon Crimson", "คริมสัน", None),  # Dukemon Crimson Mode
    ("Imperialdramon Paladin", "พาราดิน", None),
    ("Alphamon Ouryuken [Extreme]", "อัลฟามอน โอริวเคน", "เอ็กซ์ตรีม"),
    ("Alphamon Ouryuken", "อัลฟามอน โอริวเคน", None),  # fallback for non-Extreme
    ("Last Evolution: Kizuna", "ลาสต์ อีโวลูชัน", None),
    ("Lucemon: Satan Mode (Extreme)", "ซาตานโหมด", "เอ็กซ์ตรีม"),
    ("Omegamon – Merciful Mode", "เมอซิฟูล", None),
    ("Omegamon X Extreme", "โอเมกามอน X", "เอ็กซ์ตรีม"),
    # Single-name digimon (Thai transliterations)
    ("Eosmon", "อีออสมอน", None),
    ("Bloomlordmon", "บลูมลอร์ดมอน", None),
    ("ZeedMillenniummon", "ซีดมิลเลเนียม", None),
    ("Goddramon", "ก็อดดรามอน", None),
    ("Holydramon", "โฮลีดรามอน", None),
    ("Susanoomon", "ซูซาโน", None),
    ("Lilithmon", "ลิลิธมอน", None),
    ("DoneDevimon", "ดันเดวีมอน", None),
    ("Negamon", "เนกามอน", None),
    ("Abbadomon", "อบาดอน", None),
    ("Quantumon", "ควอนตัมมอน", None),
]


def pick_best(matches: list[dict], na_date: date) -> dict:
    """Prefer TH date >= NA date (Thai usually lags NA), closest distance."""

    def sort_key(p: dict) -> tuple[int, int]:
        if not p["date"]:
            return (1, 0)
        th_date = parse_iso(p["date"])
        # TH BEFORE NA gets penalized to the back
        return (0 if th_date >= na_date else 1, abs((th_date - na_date).days))

    return min(matches, key=sort_key)


def main() -> None:
    data = json.loads(DIGIMON.read_text(encoding="utf-8"))
    th = json.loads(TH_DIGIMON.read_text(encoding="utf-8"))
    th_posts = th["posts"]

    matched = 0
    no_match: list[str] = []

    for kind in ("event", "patch"):
        for idx, post in data.get(kind, {}).items():
            th_post = None
            via = None
            for name in post["digimon"]:
                row = lookup_keyword(name, EN_TO_TH_KEYWORDS)
                if not row:
                    continue
                _, th_kw, required_mod = row
                matches = find_matches(th_kw, th_posts, lambda p: [p["th_name"]], required_mod)
                if not matches:
                    continue
                th_post = pick_best(matches, parse_mmddyyyy(post["date"])) if len(matches) > 1 else matches[0]
                via = (name, th_kw, required_mod, len(matches))
                break

            if th_post:
                post["source_th"] = th_post["url"]
                post["date_th"] = th_post["date"]
                post["_th_name"] = th_post["th_name"]
                post["_th_image_url"] = th_post["image_url"]
                matched += 1
                tag = f" [{via[3]} candidates]" if via[3] > 1 else ""
                print(
                    f"  {kind} {idx} ({post['date']}) → TH {th_post['date']}{tag}: {th_post['th_name']}"
                )
            else:
                for k in ("source_th", "date_th", "_th_name", "_th_image_url"):
                    post.pop(k, None)
                no_match.append(f"{kind} {idx} ({post['date']}): {post['digimon']}")

    DIGIMON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nMatched: {matched}, no Thai equivalent: {len(no_match)}")
    for n in no_match:
        print(f"  no TH: {n}")


if __name__ == "__main__":
    main()
