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

from _content_match import find_matches, lookup_keyword, name_matches, parse_iso, parse_mmddyyyy

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
DIGIMON = PROJ / "data" / "scan_result_digimon.json"
TH_DIGIMON = PROJ / "data" / "th_patch_digimon.json"

# (EN_substring, TH_substring, required_th_modifier_or_None).
# Match logic:
#   1. find first tuple where `en_kw` is a substring of the EN digimon name
#   2. find TH posts where one of `th_names` (every new digimon the post
#      announces) contains `th_kw`
#   3. if `required_th_modifier` is set, also require it in that same name
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
    # EN key is just "Satan Mode": the NA name's shape has flipped between
    # "Lucemon: Satan Mode (Extreme)" and "[Extreme] Lucemon : Satan Mode"
    # across rescans (colon spacing + bracket position), and no longer
    # contiguous-substring-matches the full form. Only Lucemon carries
    # "Satan Mode"; the เอ็กซ์ตรีม modifier keeps the TH Shin release out.
    ("Satan Mode(Shin)", "ซาตานโหมด", "ชิน"),
    ("Satan Mode", "ซาตานโหมด", "เอ็กซ์ตรีม"),
    ("Omegamon – Merciful Mode", "เมอซิฟูล", None),
    # "=" = the whole TH name: the plain forms are inside the longer ones.
    ("Shoutmon X7", "=เชาท์มอน X7", None),
    ("Xros Up Mervamon", "ครอสอัพ เมอร์วามอน", None),
    ("JetMervamon", "=เจ็ทเมอร์วามอน", None),
    ("Mervamon", "=เมอร์วามอน", None),
    ("Bond of Friendship", "กาบูมอน – สายสัมพันธ์", None),
    ("Imperialdramon Fighter", "อิมพีเรียลดรามอน ไฟเตอร์", None),
    ("Beelzebumon Blast Mode", "เบลเซบุมอน บลาสโหมด", None),
    ("Belphemon", "เบลเฟมอน", "อะเวค"),
    ("Sakuyamon", "ซาคุยามอน", "อะเวค"),
    ("(Awaken)Ordinemon", "โอดิเนมอน", "อะเวค"),
    # NA released WarGreymon with MetalGarurumon in Jan 2025: the awakened pair.
    ("WarGreymon", "วอร์เกรย์มอน", "อะเวค"),
    ("Angoramon", "อังโกรามอน", None),
    ("Jellymon", "เจลลีมอน", None),
    ("Omegamon X Extreme", "โอเมกามอน X", "เอ็กซ์ตรีม"),
    # Single-name digimon (Thai transliterations)
    ("Eosmon", "อีออสมอน", None),
    ("Bloomlordmon", "บลูมลอร์ดมอน", None),
    ("ZeedMillenniummon", "ซีดมิลเลเนียม", None),
    ("Goddramon", "ก็อดดรามอน", None),
    ("Holydramon", "โฮลีดรามอน", None),
    ("Susanoomon", "ซูซาโน", None),
    # Lilithmon X shares a TH post with other digimon; without the modifier
    # the awakened form would land on it.
    ("Awakened Lilithmon", "ลิลิธมอน", "อะเวค"),
    ("Lilithmon", "ลิลิธมอน", None),
    ("DoneDevimon", "ดันเดวีมอน", None),
    ("Negamon", "เนกามอน", None),
    ("Fanglongmon (Shin)", "ฟานลอนมอน (ชิน)", None),
    ("Rafflesimon", "ราเฟลเรซีมอน", None),
    ("Chaosmon", "คาออสมอน", None),
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
                matches = find_matches(th_kw, th_posts,
                                       lambda p: p.get("th_names") or [p["th_name"]],
                                       required_mod)
                if not matches:
                    continue
                th_post = pick_best(matches, parse_mmddyyyy(post["date"])) if len(matches) > 1 else matches[0]
                via = (name, th_kw, required_mod, len(matches))
                break

            if th_post:
                post["source_th"] = th_post["url"]
                post["date_th"] = th_post["date"]
                # the name that actually matched, not the post's first digimon
                post["_th_name"] = next(
                    (n for n in th_post.get("th_names") or [] if name_matches(via[1], n, via[2])),
                    th_post["th_name"])
                # Each digimon's own picture from the post; failing that, the
                # banner -- but only for the first digimon, since the banner
                # shows that one and a later digimon would get its picture.
                own = (th_post.get("images") or {}).get(post["_th_name"])
                if not own and post["_th_name"] == th_post["th_name"]:
                    own = th_post["image_url"]
                if own:
                    if own != post.get("_th_image_url"):
                        post.pop("image_th", None)   # re-extract the new picture
                    post["_th_image_url"] = own
                else:
                    post.pop("_th_image_url", None)
                    post.pop("image_th", None)
                # The post's other digimon have pictures of their own too
                # (Mervamon + JetMervamon); the card shows them beside the first.
                extra = {}
                for other in post["digimon"]:
                    row = lookup_keyword(other, EN_TO_TH_KEYWORDS) if other != via[0] else None
                    if not row:
                        continue
                    th_n = next((n for n in th_post.get("th_names") or []
                                 if name_matches(row[1], n, row[2])), None)
                    url = (th_post.get("images") or {}).get(th_n)
                    if url and url != own:
                        extra[other] = url
                if extra:
                    post["_th_extra_image_urls"] = extra
                else:
                    post.pop("_th_extra_image_urls", None)
                    post.pop("images_th_extra", None)
                matched += 1
                tag = f" [{via[3]} candidates]" if via[3] > 1 else ""
                print(
                    f"  {kind} {idx} ({post['date']}) → TH {th_post['date']}{tag}: {th_post['th_name']}"
                )
            else:
                for k in ("source_th", "date_th", "_th_name", "_th_image_url",
                          "_th_extra_image_urls", "images_th_extra"):
                    post.pop(k, None)
                no_match.append(f"{kind} {idx} ({post['date']}): {post['digimon']}")

    DIGIMON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nMatched: {matched}, no Thai equivalent: {len(no_match)}")
    for n in no_match:
        print(f"  no TH: {n}")


if __name__ == "__main__":
    main()
