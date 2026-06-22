"""Match each entry in scan_result_digimon.json to its original KR release post
and add a `source_kr` field.

Date-only matching is unreliable: gameking sometimes delays an English translation
by weeks or months (e.g. e673 Kuzuhamon MikoMode = 28-day lag, e663 Omegamon
Merciful Mode = 3-month lag). So we match by *content*:

1. For each EN digimon, find the longest EN keyword in EN_TO_KR that is a substring
   of the actual EN name (so "Lilithmon X (Awaken)" matches the "Lilithmon" key).
2. Look up the mapped KR keyword in kr_digimon_releases.json — the auth list of
   KR release posts containing `[ 신규 디지몬 (계열)? (추가)? - <name> ]` markers.
3. If multiple KR posts match the same keyword (e.g. "아바도몬" hits both 아바도몬
   and 아바도몬 코어), pick the one closest to the EN date.
4. Apply OVERRIDES for digimon released only through deck/event posts that lack
   a `신규 디지몬` marker.

Reads:  scan_result_digimon.json, kr_digimon_releases.json, kr_news_index.json
Writes: scan_result_digimon.json (updates `source_kr` field)

When a new digimon is added to scan_result_digimon.json:
- If the KR release post uses a standard `신규 디지몬` marker, add an entry to
  EN_TO_KR_KEYWORDS below.
- If it was released as part of a deck/event post without that marker, add an
  entry to OVERRIDES with the KR post `o` id.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
DIGIMON = PROJ / "data" / "scan_result_digimon.json"
KR_RELEASES = PROJ / "data" / "kr_digimon_releases.json"
KR_INDEX = PROJ / "data" / "kr_news_index.json"

# (EN_substring, KR_substring). For each EN digimon name, the FIRST keyword whose
# `en_kw` appears in the name (case-insensitive) is used. Order matters: list more
# specific names BEFORE generic ones so e.g. "Abbadomon Core" matches before "Abbadomon".
EN_TO_KR_KEYWORDS: list[tuple[str, str]] = [
    # More specific compound names first
    ("Abbadomon Core", "아바도몬 코어"),
    ("Negamon (Evolved Form)", "네가몬 ( 진화된 모습 )"),
    ("Shoutmon X7", "샤우트몬 X7"),
    ("Imperialdramon Paladin", "황제드라몬 팔라딘"),
    ("Imperialdramon Fighter", "황제드라몬 파이터"),
    ("Alphamon Ouryuken", "알파몬 : 왕룡검"),
    ("Last Evolution: Kizuna", "라스트 에볼루션 : 인연"),
    # Single-name digimon
    ("Kuzuhamon", "쿠즈하몬"),
    ("Gallantmon", "듀크몬"),  # Dukemon = Gallantmon
    ("Eosmon", "에오스몬"),
    ("Bloomlordmon", "블룸로드몬"),
    ("ZeedMillenniummon", "지드밀레니엄몬"),
    ("Lucemon", "루체몬"),
    ("Goddramon", "갓드라몬"),
    ("Holydramon", "홀리드라몬"),
    ("Susanoomon", "스사노오몬"),
    ("Lilithmon", "리리스몬"),
    ("DoneDevimon", "던데블몬"),
    ("Negamon", "네가몬"),
    ("Abbadomon", "아바도몬"),
    ("Omegamon", "오메가몬"),
    ("Quantumon", "퀀텀몬"),
]

# Digimon released only via deck/event posts (no `신규 디지몬` marker exists).
# Key = (kind, idx), value = KR `o` id.
OVERRIDES: dict[tuple[str, str], str] = {
    # Omegamon Merciful Mode: introduced via deck "하얀 날개 : 용기의 우령도"
    # in o=780048 (2023-12-13). No dedicated 신규 디지몬 marker.
    ("event", "663"): "780048",
}


def parse_mmddyyyy(s: str) -> date:
    mm, dd, yyyy = s.split("-")
    return date(int(yyyy), int(mm), int(dd))


def parse_iso(s: str) -> date:
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def normalize(s: str) -> str:
    return "".join(s.split())


def lookup_kr_keyword(en_name: str) -> str | None:
    en_low = en_name.lower()
    for en_kw, kr_kw in EN_TO_KR_KEYWORDS:
        if en_kw.lower() in en_low:
            return kr_kw
    return None


def find_kr_matches(kr_kw: str, releases: list[dict]) -> list[dict]:
    """All KR release posts whose `kr_names` list contains the keyword."""
    norm_kw = normalize(kr_kw)
    out = []
    for r in releases:
        for n in r["kr_names"]:
            if norm_kw in normalize(n):
                out.append(r)
                break
    return out


def pick_closest(matches: list[dict], en_date: date) -> dict:
    """Closest KR date to en_date; ties prefer KR <= EN (gameking translates from KR)."""
    return min(
        matches,
        key=lambda r: (abs((en_date - parse_iso(r["date"])).days), parse_iso(r["date"]) > en_date),
    )


def main() -> None:
    data = json.loads(DIGIMON.read_text(encoding="utf-8"))
    kr = json.loads(KR_RELEASES.read_text(encoding="utf-8"))
    releases = kr["posts"]

    o_to_url = {r["o"]: r["url"] for r in releases}
    if KR_INDEX.exists():
        for p in json.loads(KR_INDEX.read_text(encoding="utf-8"))["posts"]:
            o_to_url.setdefault(p["o"], p["url"])

    matched = 0
    overridden = 0
    unmatched: list[str] = []

    for kind in ("event", "patch"):
        for idx, post in data.get(kind, {}).items():
            key = (kind, idx)
            if key in OVERRIDES:
                o = OVERRIDES[key]
                post["source_kr"] = o_to_url.get(
                    o, f"https://www.digimonmasters.com/news/newsBoard_sub.aspx?o={o}&Btype=Update"
                )
                overridden += 1
                print(
                    f"  {kind} {idx} ({post['date']}) → KR o={o} [OVERRIDE]: "
                    f"{', '.join(post['digimon'])}"
                )
                continue

            en_date = parse_mmddyyyy(post["date"])
            kr_post = None
            via_kw = None
            for name in post["digimon"]:
                kr_kw = lookup_kr_keyword(name)
                if not kr_kw:
                    continue
                matches = find_kr_matches(kr_kw, releases)
                if not matches:
                    continue
                kr_post = pick_closest(matches, en_date) if len(matches) > 1 else matches[0]
                via_kw = (name, kr_kw, len(matches))
                break

            if kr_post:
                post["source_kr"] = kr_post["url"]
                matched += 1
                tag = f" [{via_kw[2]} candidates]" if via_kw[2] > 1 else ""
                print(
                    f"  {kind} {idx} ({post['date']}) → KR o={kr_post['o']} "
                    f"({kr_post['date']}){tag}: {', '.join(kr_post['kr_names'])}"
                )
            else:
                unmatched.append(f"{kind} {idx} ({post['date']}): {post['digimon']}")
                post.pop("source_kr", None)

    DIGIMON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nMatched: {matched}, overridden: {overridden}, unmatched: {len(unmatched)}")
    for u in unmatched:
        print(f"  unmatched: {u}")
        print("    → add an entry to EN_TO_KR_KEYWORDS or OVERRIDES in enrich_digimon_kr.py")


if __name__ == "__main__":
    main()
