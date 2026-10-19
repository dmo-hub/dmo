"""List digimon KR has released that no NA post announces yet.

    data/kr_digimon_releases.json + data/scan_result_digimon.json
      -> data/kr_only_digimon.json   { "<o>": {date, url, digimon, kr_names, image_kr} }

A KR release post already linked to an NA entry (source_kr) only counts the
names that entry does not cover: post 782896 brings Beelzebumon Blast Mode
(Awaken), which NA has, and Gammamon, which NA announced in a separate post.
Matching by keyword alone is not enough -- 아폴로몬:위스퍼드 contains 아폴로몬, so
Apollomon Whispered would pass for the Apollomon NA already has -- hence the
check is per linked post, and an unlinked post counts every name.

A KR name with no entry in KR_TO_EN is reported and shown in Korean until one
is added. Run after enrich_digimon_kr.py.
"""

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "extractors"))
from _image_common import CACHE, IMG_DIR, extract_image  # noqa: E402
from enrich_digimon_kr import EN_TO_KR_KEYWORDS  # noqa: E402

RELEASES = PROJ / "data" / "kr_digimon_releases.json"
DIGIMON = PROJ / "data" / "scan_result_digimon.json"
OUT = PROJ / "data" / "kr_only_digimon.json"

# KR release name -> the dmowiki page title
KR_TO_EN = {
    "아폴로몬:위스퍼드": "Apollomon Whispered",
}

SKIP_URL_KEYWORDS = ("logo", "icon", "/footer/", "/header/", "btn_", "violent", "renewal_main/")


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def covered(kr_name: str, na_names: list[str], whole: bool) -> bool:
    """Whether one of na_names is this KR name, through EN_TO_KR_KEYWORDS.
    whole=True wants the KR keyword to be the entire name, for posts not linked
    to any NA entry; within a linked post a contained keyword is enough
    (오르디네몬 ( 각성 ) is the Ordinemon (Awaken) that post announces)."""
    k = squash(kr_name)
    for en_kw, kr_kw in EN_TO_KR_KEYWORDS:
        if not any(en_kw.lower() in n.lower() for n in na_names):
            continue
        if (squash(kr_kw) == k) if whole else (squash(kr_kw) in k):
            return True
    return False


def main() -> None:
    releases = json.loads(RELEASES.read_text(encoding="utf-8"))["posts"]
    scan = json.loads(DIGIMON.read_text(encoding="utf-8"))
    by_o: dict[str, list[str]] = {}
    na_all: list[str] = []
    for kind in ("event", "patch"):
        for post in scan.get(kind, {}).values():
            na_all += post["digimon"]
            m = re.search(r"[?&]o=(\d+)", post.get("source_kr") or "")
            if m:
                by_o.setdefault(m.group(1), []).extend(post["digimon"])

    out: dict[str, dict] = {}
    for r in releases:
        linked = by_o.get(r["o"]) or []
        names = [n for n in r["kr_names"]
                 if not covered(n, linked, whole=False) and not covered(n, na_all, whole=True)]
        if not names:
            continue
        entry = {"date": r["date"], "url": r["url"], "kr_names": names,
                 "digimon": [KR_TO_EN.get(n, n) for n in names]}
        cf = CACHE / f"kr_view_o{r['o']}.html"
        if cf.exists():
            got = extract_image(cf.read_text(encoding="utf-8"),
                                url_ok=lambda s: not any(k in s.lower() for k in SKIP_URL_KEYWORDS),
                                absolutize=lambda s: s if s.startswith("http") else f"https://www.digimonmasters.com{s}")
            if got:
                blob, ext = got
                img = IMG_DIR / f"k{r['o']}_kr.{ext}"
                img.write_bytes(blob)
                entry["image_kr"] = f"img/digimon/{img.name}"
        out[r["o"]] = entry
        for n in names:
            if n not in KR_TO_EN:
                print(f"  ! o={r['o']}: no English name for {n} -- add it to KR_TO_EN")

    # a post that NA has since announced drops out; so does its picture
    for f in IMG_DIR.glob("k*_kr.*"):
        if f.stem[1:-3] not in out:
            f.unlink()
            print(f"  removed {f.name} (no longer KR-only)")

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(PROJ)}: {len(out)} KR-only post(s)")
    for o, e in out.items():
        print(f"  o={o} {e['date']}: {', '.join(e['digimon'])}")


if __name__ == "__main__":
    main()
