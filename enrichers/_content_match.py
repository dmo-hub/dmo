"""Shared content-matching helpers for the cross-server enrichers
(enrich_digimon_kr.py, enrich_digimon_th.py).

The matching model both enrichers share:
  1. an ordered EN→foreign keyword table (more specific compound names FIRST),
  2. substring lookup of the EN keyword inside the actual EN digimon name,
  3. substring search of the foreign keyword inside each release post's name(s),
     whitespace/case-normalized on both sides.

Date-tiebreak semantics differ per server (KR prefers closest, TH prefers
release-after-NA first), so the pickers stay in each enricher.
"""
from datetime import date


def normalize(s: str) -> str:
    return "".join(s.split()).lower()


def parse_mmddyyyy(s: str) -> date:
    mm, dd, yyyy = s.split("-")
    return date(int(yyyy), int(mm), int(dd))


def parse_iso(s: str) -> date:
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def lookup_keyword(en_name: str, table: list[tuple]) -> tuple | None:
    """First table row whose row[0] (EN keyword) is a substring of en_name."""
    en_low = en_name.lower()
    for row in table:
        if row[0].lower() in en_low:
            return row
    return None


def name_matches(kw: str, name: str, required_mod: str | None = None) -> bool:
    """kw inside name (and required_mod if set). A leading "=" asks for the
    whole name instead: "เมอร์วามอน" alone is also inside "เจ็ทเมอร์วามอน"
    and "ครอสอัพ เมอร์วามอน"."""
    nn = normalize(name)
    if kw.startswith("="):
        hit = nn == normalize(kw[1:])
    else:
        hit = normalize(kw) in nn
    return hit and (required_mod is None or normalize(required_mod) in nn)


def find_matches(kw: str, posts: list[dict], get_names, required_mod: str | None = None) -> list[dict]:
    """Posts where any of get_names(post) matches kw (see name_matches)."""
    return [p for p in posts if any(name_matches(kw, n, required_mod) for n in get_names(p))]
