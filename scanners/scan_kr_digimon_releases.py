"""Fetch each KR Update post body (from kr_news_index.json) and extract
`[ 신규 디지몬 추가 - <KR name> ]` markers — the KR-site equivalent of gameking's
`[New Digimon Added - <EN name>]`.

Caches each detail page under cache/kr_view_o<N>.html (one-time fetch, then idempotent).
Output: kr_digimon_releases.json — only KR posts that actually announce new digimon.

This is the authoritative source for KR↔EN matching, since date-only matching fails
when gameking delays a translation by weeks (e.g., gameking idx 673 dated 2024-06-11
actually corresponds to KR o=787200 dated 2024-05-14, a 28-day lag).
"""

import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
INDEX = PROJ / "data" / "kr_news_index.json"
OUT = PROJ / "data" / "kr_digimon_releases.json"

# Marker variants seen in the wild:
#   `[ 신규 디지몬 추가 - <name> ]`      (most common)
#   `[ 신규 디지몬 계열 추가 - <name> ]` (lineage release, e.g. Eosmon w/ Adult/Perfect/Ultimate)
#   `[ 신규 디지몬 - <name> ]`           (no 추가 — used for movie tie-ins, e.g. Last Evolution Kizuna)
# All three are followed by a dash and the name. Use balanced-bracket walking so
# names like `[극의] 루체몬 : 사탄모드` are captured intact.
MARKER_PHRASE = re.compile(r"신규\s*디지몬(?:\s*계열)?\s*(?:추가)?\s*[–—-]\s*")


def html_to_text(raw: str) -> str:
    t = re.sub(r"<[^>]+>", " ", raw)
    t = html.unescape(t)
    t = re.sub(r"&nbsp;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def fetch_detail(o: str, force: bool = False) -> str:
    cache_file = CACHE / f"kr_view_o{o}.html"
    if cache_file.exists() and not force:
        return cache_file.read_text(encoding="utf-8")
    url = f"https://www.digimonmasters.com/news/newsBoard_sub.aspx?o={o}&Btype=Update"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    CACHE.mkdir(exist_ok=True)
    cache_file.write_text(r.text, encoding="utf-8")
    return r.text


def extract_releases(raw_html: str) -> list[str]:
    """Find every `[ 신규 디지몬 추가 - <name> ]` marker, with balanced bracket
    walking so names with `[각성]` / `[극의]` prefixes are captured intact.
    """
    text = html_to_text(raw_html)
    out: list[str] = []
    pos = 0
    while True:
        m = MARKER_PHRASE.search(text, pos)
        if not m:
            return out
        # walk back to the enclosing `[`
        br = text.rfind("[", max(0, m.start() - 10), m.start() + 1)
        if br == -1:
            pos = m.end()
            continue
        # walk forward, balanced
        depth = 0
        end = -1
        for i in range(br, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            pos = m.end()
            continue
        # name = everything between the dash and the closing `]`
        name = text[m.end() : end - 1].strip()
        if name:
            out.append(name)
        pos = end


def process(post: dict) -> tuple[dict, list[str]]:
    raw = fetch_detail(post["o"])
    return post, extract_releases(raw)


def main() -> None:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    updates = [p for p in index["posts"] if p["type"] == "update"]
    print(f"Scanning {len(updates)} KR update posts for `신규 디지몬 추가` markers...")

    releases: list[dict] = []
    fetch_count = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(process, p): p for p in updates}
        for fut in as_completed(futures):
            post, kr_names = fut.result()
            fetch_count += 1
            if not (CACHE / f"kr_view_o{post['o']}.html").exists():
                # shouldn't happen — process() writes the cache
                continue
            if kr_names:
                releases.append(
                    {
                        "o": post["o"],
                        "date": post["date"],
                        "num": post["num"],
                        "kr_names": kr_names,
                        "url": post["url"],
                    }
                )

    releases.sort(key=lambda x: -x["num"])
    out = {
        "scanned": len(updates),
        "release_posts": len(releases),
        "posts": releases,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT.name}: {len(releases)}/{len(updates)} posts had new-digimon markers")
    for r in releases[:30]:
        print(f"  o={r['o']} ({r['date']}): {', '.join(r['kr_names'])}")
    if len(releases) > 30:
        print(f"  ... ({len(releases) - 30} more)")


if __name__ == "__main__":
    main()
