"""Extract the Seal-Exchange table(s) from every seal post (NA/KR/TH) and
write cleaned, embeddable HTML to data/seal_tables.json.

Strategy (validated by probing real posts):
  * A post contains many <table> blocks (deck lists, season-pass rewards,
    box contents, etc.). The *seal-exchange* table is identifiable by
    content — it is dense with seal tokens (씰 / ซีล / Seal). Real seal
    tables score 25-40 such tokens; incidental ones score 0-3.
  * Inclusion rule per table: seal_token_count >= 4, OR the nearest
    preceding heading text contains a strong seal-exchange phrase.
  * Each kept table is stripped of inline styles/spans and re-emitted as a
    minimal <table class="seal-tbl"> with the first row as <th>.

Reads from cache/ when present; fetches + caches the ~10 missing posts.
Run: python builders/extract_seal_tables.py
"""

import html as H
import io
import json
import re
import sys
import time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
OUT = PROJ / "data" / "seal_tables.json"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

# NA idx that are PatchNote (rest are EventView)
NA_PATCH = {4100, 4110, 4114, 4118, 4121, 4129}

# TH system page (permanent Seal Master explainer) — encoded permalink
TH_SYSTEM_URL = ("https://www.vplay.in.th/%E0%B8%A3%E0%B8%B0%E0%B8%9A%E0%B8%9A"
                 "%E0%B8%8B%E0%B8%B5%E0%B8%A5%E0%B8%A1%E0%B8%B2%E0%B8%AA%E0%B9%80"
                 "%E0%B8%95%E0%B8%AD%E0%B8%A3%E0%B9%8C/")

# All 56 seal posts, keyed by their docs/seals.html card id.
KR_IDS = [816593, 814935, 814707, 814605, 814493, 814269, 814064, 813810,
          813439, 812989, 811713, 811362, 810828, 808363, 807402, 797955,
          794497, 792682, 789333, 788597, 787646, 783755, 782119, 780048, 708817]
NA_IDS = [4129, 4121, 4118, 4114, 4110, 4100, 810, 789, 784, 782, 759, 743,
          683, 673, 636, 551, 530, 352]
TH_SUFFIXES = [83, 78, 66, 64, 59, 56, 49, 42, 28, 21, 12, 15]

SEAL_PHRASES = ("씰 교환", "씰 마스터", "씰교환", "seal exchange", "seal master",
                "แลกซีล", "แลกเปลี่ยนซีล", "รายการซีล", "ซีล>", "ผลิตซีล",
                "seal exchange ticket", "씰 교환권")


def fetch(url, cache_name):
    """GET url, cache raw HTML under cache/<cache_name>, return text."""
    cf = CACHE / cache_name
    if cf.exists():
        return cf.read_text(encoding="utf-8", errors="ignore")
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200 and len(r.text) > 500:
                cf.write_text(r.text, encoding="utf-8")
                print(f"    fetched {url} -> {cache_name} ({len(r.text)}b)")
                return r.text
        except Exception as e:
            print(f"    retry {attempt} {url}: {e}", file=sys.stderr)
        time.sleep(1.5)
    print(f"    !! failed to fetch {url}", file=sys.stderr)
    return ""


def get_html(post):
    server, ident = post["server"], post["id"]
    if server == "KR":
        cf = CACHE / f"kr_view_o{ident}.html"
        if cf.exists():
            return cf.read_text(encoding="utf-8", errors="ignore")
        btype = "Event" if ident == 708817 else "Update"
        url = f"https://www.digimonmasters.com/news/newsBoard_sub.aspx?o={ident}&Btype={btype}"
        return fetch(url, f"kr_view_o{ident}.html")
    if server == "NA":
        kind = "patch" if ident in NA_PATCH else "event"
        cf = CACHE / f"{kind}_{ident}.html"
        if cf.exists():
            return cf.read_text(encoding="utf-8", errors="ignore")
        view = (f"https://dmo.gameking.com/News/PatchNoteView.aspx?idx={ident}"
                if kind == "patch"
                else f"https://dmo.gameking.com/news/EventView.aspx?idx={ident}")
        return fetch(view, f"{kind}_{ident}.html")
    # TH
    if ident == "system":
        return fetch(TH_SYSTEM_URL, "th_view_system.html")
    hits = list(CACHE.glob(f"th_view_*-{ident}.html"))
    if hits:
        return hits[0].read_text(encoding="utf-8", errors="ignore")
    return ""


def strip_text(t):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def seal_token_count(text):
    return text.count("씰") + text.count("ซีล") + len(re.findall(r"seal", text, re.I))


def clean_cell(inner):
    txt = strip_text(inner)
    return H.escape(txt)


def clean_table(tb):
    tb = re.sub(r"<colgroup.*?</colgroup>", "", tb, flags=re.S)
    rows = re.findall(r"<tr\b.*?</tr>", tb, re.S)
    out = ['<table class="seal-tbl">']
    for ri, row in enumerate(rows):
        cells = re.findall(r"<(t[dh])\b([^>]*)>(.*?)</\1>", row, re.S)
        if not cells:
            continue
        tag = "th" if ri == 0 else "td"
        out.append("<tr>")
        for _celltag, attrs, inner in cells:
            span = ""
            m = re.search(r'colspan="?(\d+)"?', attrs)
            if m and m.group(1) != "1":
                span += f' colspan="{m.group(1)}"'
            m = re.search(r'rowspan="?(\d+)"?', attrs)
            if m and m.group(1) != "1":
                span += f' rowspan="{m.group(1)}"'
            out.append(f"<{tag}{span}>{clean_cell(inner)}</{tag}>")
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


# A header row identifies a seal-EXCHANGE table when it names a seal AND an
# exchange/produce/obtain action — this cleanly separates the real exchange
# lists from season-pass reward, new-seal-info, package-sale, and random-box
# tables that merely mention seals.
SEAL_NOUN = re.compile(r"씰|ซีล|seal", re.I)
EXCHANGE_HINT_RE = re.compile(r"exchange|obtain|craft|ticket", re.I)
EXCHANGE_HINT_KR = ("교환", "획득", "제작")
EXCHANGE_HINT_TH = ("แลก", "ผลิต", "ได้รับ", "ตั๋ว")

CAPTION = {"KR": "씰 교환권 제작 리스트 (Seal Exchange Craft List)",
           "NA": "Seal Exchange Ticket — Craft List",
           "TH": "รายการแลกซีล (Seal Exchange List)"}


def header_text(tb):
    m = re.search(r"<tr\b.*?</tr>", tb, re.S)
    return strip_text(m.group(0)) if m else ""


# Headers that look seal-ish but are NOT exchange lists: shop packages / sale
# promos, and new-seal stat-reference tables ("how to obtain" / "획득처").
EXCLUDE_HINT = ("package", "sale", "패키지", "판매", "แพ็คเกจ", "ลดราคา",
                "วิธีการได้รับ", "วิธีได้รับ", "획득처")


# KR exchange tables always carry an "you obtain N seals" column. Requiring
# one rejects the ticket-CRAFTING table ("씰 교환권 제작": spend Bit -> get the
# ticket itself, no seal names) which otherwise looks seal-ish.
KR_OBTAIN_KW = ("제작 씰", "씰 획득", "씰 지급")


def is_exchange_header(htxt, head2, body_score, server):
    h = htxt.lower()
    if htxt.strip().startswith("-"):
        return False
    if any(x in h for x in ("package", "sale")) or any(x in htxt for x in EXCLUDE_HINT):
        return False
    hint = (bool(EXCHANGE_HINT_RE.search(htxt))
            or any(x in htxt for x in EXCHANGE_HINT_KR)
            or any(x in htxt for x in EXCHANGE_HINT_TH))
    if not hint:
        return False
    if server == "KR":
        return any(k in head2 for k in KR_OBTAIN_KW)
    if SEAL_NOUN.search(htxt):
        return True
    # Older TH exchange tables head their columns "material -> obtained"
    # without the word ซีล; fall back to a seal-dense body. NA exchange
    # headers always name the seal, so the fallback is TH-only (it would
    # otherwise admit e.g. NA's "Digivice Craft List").
    return server == "TH" and body_score >= 12


def extract(post):
    raw = get_html(post)
    if not raw:
        return {"tables": [], "error": "no html"}
    tables, seen = [], set()
    server = post["server"]
    for m in re.finditer(r"<table\b.*?</table>", raw, re.S):
        tb = m.group(0)
        htxt = header_text(tb)
        head2 = strip_text("".join(re.findall(r"<tr\b.*?</tr>", tb, re.S)[:2]))
        body_score = seal_token_count(strip_text(tb))
        if not is_exchange_header(htxt, head2, body_score, server):
            continue
        cleaned = clean_table(tb)
        if cleaned in seen:           # drop exact-duplicate tables
            continue
        seen.add(cleaned)
        tables.append({
            "header": htxt[:160],
            "score": body_score,
            "rows": tb.count("<tr"),
            "html": cleaned,
        })
    cap = CAPTION[server]
    for i, t in enumerate(tables):
        t["caption"] = cap if len(tables) == 1 else f"{cap} ({i + 1})"
    note = "" if tables else "โพสต์อธิบายกลไก/แสดงเป็นรูปภาพ — ไม่มีตาราง HTML (ดูในโพสต์ต้นทาง)"
    return {"tables": tables, "note": note}


def main():
    posts = (
        [{"key": f"kr-{i}", "server": "KR", "id": i} for i in KR_IDS]
        + [{"key": f"na-{i}", "server": "NA", "id": i} for i in NA_IDS]
        + [{"key": f"th-{s}", "server": "TH", "id": s} for s in TH_SUFFIXES]
        + [{"key": "th-system", "server": "TH", "id": "system"}]
    )
    result = {}
    print(f"Extracting seal tables from {len(posts)} posts...\n")
    for p in posts:
        data = extract(p)
        result[p["key"]] = data
        tbls = data.get("tables", [])
        flag = "" if tbls else "  <-- NO TABLE"
        print(f"{p['key']:<12} tables={len(tbls)}{flag}")
        for t in tbls:
            print(f"    score={t['score']:>3} rows={t['rows']:>2} hdr={t['header']!r}")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    n_tbl = sum(len(v.get("tables", [])) for v in result.values())
    n_none = sum(1 for v in result.values() if not v.get("tables"))
    print(f"\nWrote {OUT}  ({n_tbl} tables across {len(posts)} posts; "
          f"{n_none} posts with no table)")


if __name__ == "__main__":
    main()
