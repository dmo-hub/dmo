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
OCR_PATH = PROJ / "data" / "seal_ocr.json"
# Vision-OCR'd exchange tables for gameking posts that ship the list as an
# image instead of an HTML table (rows already in canonical column order).
OCR_DATA = ({k: v for k, v in json.loads(OCR_PATH.read_text(encoding="utf-8")).items()
             if not k.startswith("_")} if OCR_PATH.exists() else {})
# Korean seal-name -> official English name, so KR tables show English data.
KR_EN_PATH = PROJ / "data" / "kr_seal_en.json"
KR_EN = (json.loads(KR_EN_PATH.read_text(encoding="utf-8"))
         if KR_EN_PATH.exists() else {})

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
TH_SUFFIXES = [88, 83, 78, 76, 66, 64, 59, 56, 49, 42, 28, 24, 21, 15, 12]

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


# --- Normalisation to one canonical 5-column layout -----------------------
# Every seal-exchange table, whatever its native column order/wording, is
# remapped to the canonical layout using the Thai-server column names:
# [seal | seals given | tickets used | stat | max @ Master].
NORM_HEADER = ["รายการซีล", "จำนวนซีลที่ได้รับ",
               "จำนวนตั๋วแลกการ์ดซีลที่ใช้ผลิต", "ความสามารถ", "สเตตัสสูงสุด"]
_STAT = re.compile(r"\b(AT|HP|HT|DS|DE|BL|EV|CT|SCD|MS|DEX|EXP)\b")

KW_NAME = ("제작 씰", "제작 아이템", "craft seal", "craft item",
           "รายการซีล", "ไอเทมที่ได้รับ", "รายการไอเทม", "รายการผลิต",
           "ซีลที่ได้รับ")   # th-88 layout: the seal you RECEIVE is the name col
KW_GIVEN = ("씰 지급", "씰 획득", "seals given", "seal obtained", "seal given",
            "จำนวนซีลที่ได้รับ", "จำนวนที่ได้รับ", "จำนวน ที่ได้รับ")
KW_TICKET = ("교환권", "재료", "seal exchange ticket", "needed seal exchange",
             "required number of seal", "material", "ตั๋วแลกการ์ดซีล",
             "ตั๋วแลกซีล", "ไอเทมวัตถุดิบ", "วัตถุดิบ", "ที่ใช้ผลิต", "ในการผลิต")
KW_MAX = ("최대", "마스터 수치", "마스터 능력치", "수치", "master value", "max value",
          "stat value", "value (master)", "master attribute", "final ability",
          "สเตตัสสูงสุด", "ค่าความสามารถสูงสุด", "ค่าสเตตัสสูงสุด", "สูงสุด")
KW_STAT = ("능력치", "stat", "attribute", "ความสามารถ", "ประเภทสเตตัส",
           "ประเภท", "คุณสมบัติ", "seal stat", "ค่าความสามารถ", "ค่าสเตตัส", "สเตตัส")
KW_QTY = ("개수", "จำนวน", "amount")


def _has(h, kws):
    # match ignoring whitespace — KR/TH headers have inconsistent spacing
    # and occasional typos (e.g. "จำนว น" for "จำนวน")
    hns = h.lower().replace(" ", "")
    return any(k.replace(" ", "") in hns for k in kws)


def table_rows(tb):
    """Expand the table into a full grid, honouring colspan/rowspan so that
    rowspan-collapsed rows (common in TH material tables) keep their columns
    aligned."""
    tb = re.sub(r"<colgroup.*?</colgroup>", "", tb, flags=re.S)
    grid, carry = [], {}            # carry: col -> [text, remaining_rows]
    for tr in re.findall(r"<tr\b.*?</tr>", tb, re.S):
        cells = []
        for m in re.finditer(r"<(t[dh])\b([^>]*)>(.*?)</\1>", tr, re.S):
            a = m.group(2)
            cs = re.search(r'colspan="?(\d+)"?', a)
            rs = re.search(r'rowspan="?(\d+)"?', a)
            cells.append((strip_text(m.group(3)),
                          int(cs.group(1)) if cs else 1,
                          int(rs.group(1)) if rs else 1))
        if not cells and not any(v[1] > 0 for v in carry.values()):
            continue
        line, col, si = [], 0, 0
        while True:
            if carry.get(col, [None, 0])[1] > 0:
                line.append(carry[col][0]); carry[col][1] -= 1; col += 1; continue
            if si < len(cells):
                txt, cs, rs = cells[si]; si += 1
                for _ in range(cs):
                    line.append(txt)
                    if rs > 1:
                        carry[col] = [txt, rs - 1]
                    col += 1
                continue
            future = [k for k, v in carry.items() if v[1] > 0 and k >= col]
            if future:
                while col < min(future):
                    line.append(""); col += 1
                continue
            break
        grid.append(line)
    return grid


def _num(s):
    m = re.search(r"\d[\d,]*", s)
    return m.group(0).replace(",", "") if m else ""


def _embedded_qty(s):
    """Oldest TH packs qty into the name cell: 'กาบูมอน ซีล 10 ชิ้น'."""
    m = re.search(r"(\d+)\s*ชิ้น", s)
    return (m.group(1), re.sub(r"\s*\d+\s*ชิ้น.*$", "", s).strip()) if m else ("", s)


def _role_of(cell):
    # given BEFORE name: th-88's name col is "ซีลที่ได้รับ" but the legacy
    # given col is "จำนวนซีลที่ได้รับ" (a superstring) — checking given first
    # keeps the legacy column a count, while bare "ซีลที่ได้รับ" falls to name.
    if _has(cell, KW_GIVEN):
        return "given"
    if _has(cell, KW_NAME):
        return "name"
    if _has(cell, KW_MAX):
        return "max"
    if _has(cell, KW_TICKET):
        return "ticket"
    if _has(cell, KW_STAT):
        return "stat"
    if _has(cell, KW_QTY):
        return "qty"
    return None


def _classify(header):
    """Return column-index roles. Generic qty cols resolve by adjacency."""
    return [_role_of(h) for h in header]


def normalize_table(tb, server):
    rows = table_rows(tb)
    if len(rows) < 2:
        return None
    # header = the row among the first 3 whose cells match the most column
    # keywords (skips colspan title rows like na-789's "Seal Exchangement"
    # and avoids data rows when the real header has duplicate column names)
    hi = max(range(min(3, len(rows))),
             key=lambda i: sum(1 for c in rows[i] if _role_of(c)))
    header = rows[hi]
    role = _classify(header)
    if "name" not in role:
        return None                          # can't map confidently -> fall back
    iname = role.index("name")
    iticket = role.index("ticket") if "ticket" in role else None
    igiven = role.index("given") if "given" in role else None
    stat_idxs = [i for i, r in enumerate(role) if r == "stat"]
    istat = stat_idxs[0] if stat_idxs else None
    imax = role.index("max") if "max" in role else None
    if imax is None and len(stat_idxs) >= 2:   # 1st stat col = type, 2nd = value
        imax = stat_idxs[-1]

    def qty_after(idx):
        for j in range(idx + 1, len(role)):
            if role[j] == "qty":
                return j
            if role[j] in ("name", "ticket"):
                break
        return None

    given_q = igiven if igiven is not None else qty_after(iname)
    if iticket is None:
        ticket_q = None
    elif _has(header[iticket], ("개수", "필요", "quantity", "required number",
              "needed", "จำนวน", "ที่ต้องการ", "ตั๋วแลกซีล")):
        ticket_q = iticket                   # the ticket column is itself a count
    else:
        ticket_q = qty_after(iticket) or iticket   # count is the qty beside it

    norm_header = [h.strip() for h in header]

    out = ['<table class="seal-tbl">', "<tr>"]
    out += [f"<th>{H.escape(c)}</th>" for c in NORM_HEADER]
    out.append("</tr>")
    for row in rows[hi + 1:]:
        if len(row) <= iname or not row[iname].strip():
            continue
        # skip in-table category-title rows: a colspan banner (e.g. th-88's
        # "หมวดผลิตตั๋วแลกซีลแบบพิเศษ") expands to the same text in every cell.
        cell_vals = [c.strip() for c in row if c.strip()]
        if len(set(cell_vals)) == 1:
            continue
        # skip a REPEATED header row: th-88 packs two sub-tables into one
        # <table>, so the second section's column header ("ไอเทมวัตถุดิบ |
        # ... | ซีลที่ได้รับ | ...") reappears mid-table — identical to the
        # header we already consumed. Drop it instead of emitting a junk row.
        if [c.strip() for c in row] == norm_header:
            continue
        eq, name = _embedded_qty(row[iname])
        if server == "KR":
            name = KR_EN.get(name, name)     # show KR seal names in English
        given = (row[given_q] if given_q is not None and given_q < len(row) else "")
        given = _num(given) or eq
        ticket = _num(row[ticket_q]) if ticket_q is not None and ticket_q < len(row) else ""
        if not ticket and iticket is not None and iticket < len(row):
            ticket, _ = _embedded_qty(row[iticket])
        statcell = row[istat] if istat is not None and istat < len(row) else ""
        maxcell = row[imax] if imax is not None and imax < len(row) else ""
        sm = _STAT.search(statcell) or _STAT.search(maxcell)
        stat = sm.group(1) if sm else statcell.strip()
        mx = _num(maxcell)
        if not mx:                            # stat & max combined e.g. "AT +150"
            mx = _num(statcell)
        cells = [name, given or "—", ticket or "—", stat or "—", mx or "—"]
        out.append("<tr>" + "".join(f"<td>{H.escape(c)}</td>" for c in cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


def emit_norm_rows(rows):
    """Build a normalized table straight from canonical [name,qty,ticket,stat,max] rows."""
    out = ['<table class="seal-tbl">', "<tr>"]
    out += [f"<th>{H.escape(c)}</th>" for c in NORM_HEADER]
    out.append("</tr>")
    for r in rows:
        cells = [str(c) if str(c).strip() else "—" for c in r]
        out.append("<tr>" + "".join(f"<td>{H.escape(c)}</td>" for c in cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


# The exchange currency must be a Seal Exchange Ticket — not a material
# (Kaiser Trace, firecracker) or a special coin (Tamer / Special Exchanger).
TICKET_RE = re.compile(
    r"씰\s*교환권|교환권|seal exchange ticket|ตั๋วแลกการ์ดซีล|ตั๋วแลกซีล|ตั๋วแลก\S*ซีล",
    re.I)


def uses_exchange_ticket(tb):
    """True only if the table's exchange input is a Seal Exchange Ticket."""
    rows = table_rows(tb)
    if len(rows) < 2:
        return False
    hi = max(range(min(3, len(rows))),
             key=lambda i: sum(1 for c in rows[i] if _role_of(c)))
    header = rows[hi]
    role = _classify(header)
    if "ticket" not in role:
        return False
    it = role.index("ticket")
    if TICKET_RE.search(header[it]):          # forward tables name it in the header
        return True
    for r in rows[hi + 1:hi + 4]:             # material tables name it in the cells
        if it < len(r) and TICKET_RE.search(r[it]):
            return True
    return False


def _is_trivial_craft(html):
    """True for a 1-ticket->1-seal list with no stat/max — the redundant
    'craft each event seal from one exchange ticket' table that sits beside
    the real stat-bearing exchange table (e.g. na-4118, kr-814707)."""
    data = re.findall(r"<tr>(.*?)</tr>", html, re.S)[1:]
    if not data:
        return False
    for r in data:
        c = [re.sub(r"<[^>]+>", "", x).strip()
             for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(c) < 5 or not (c[1] == "1" and c[2] == "1"
                              and c[3] == "—" and c[4] == "—"):
            return False
    return True


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


# a full-width category banner: a <tr> with a single colspan cell, e.g. th-88's
# "หมวดผลิตซีลมาสเตอร์" / "หมวดผลิตตั๋วแลกซีลแบบพิเศษ".
_BANNER_TR = re.compile(
    r'<tr\b[^>]*>\s*<t[dh]\b[^>]*\bcolspan="?(\d+)"?[^>]*>(.*?)</t[dh]>\s*</tr>',
    re.S | re.I)


def split_category_tables(tb):
    """Split one <table> that stacks several category sections (each introduced
    by a full-width colspan banner row) into one <table> per section, returning
    [(category_title_or_None, table_html), ...]. A table with 0-1 banners is
    returned unchanged as a single (None, tb) entry, so existing single-section
    cards are untouched."""
    trs = re.findall(r"<tr\b.*?</tr>", tb, re.S)
    banners = [i for i, tr in enumerate(trs)
               if (m := _BANNER_TR.fullmatch(tr.strip())) and int(m.group(1)) >= 2]
    if len(banners) < 2:
        return [(None, tb)]
    open_tag = re.match(r"<table\b[^>]*>", tb, re.S).group(0)
    out = []
    for n, start in enumerate(banners):
        end = banners[n + 1] if n + 1 < len(banners) else len(trs)
        title = strip_text(_BANNER_TR.fullmatch(trs[start].strip()).group(2))
        # drop the banner row itself; the section's own header row follows it
        section = open_tag + "".join(trs[start + 1:end]) + "</table>"
        out.append((title, section))
    return out


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
        if not uses_exchange_ticket(tb):
            continue                  # keep only Seal-Exchange-Ticket exchanges
        # one <table> may stack several category sections (th-88) — emit each
        # as its own table; single-section tables come back unchanged.
        for cat_title, sub in split_category_tables(tb):
            normalized = normalize_table(sub, server)
            if normalized and _is_trivial_craft(normalized):
                continue              # skip redundant 1-ticket->1-seal craft lists
            cleaned = normalized or clean_table(sub)
            if cleaned in seen:       # drop exact-duplicate tables
                continue
            seen.add(cleaned)
            entry = {
                "header": (cat_title or htxt)[:160],
                "score": body_score,
                "rows": sub.count("<tr"),
                "normalized": bool(normalized),
                "html": cleaned,
            }
            if cat_title:                 # only split sections carry a title
                entry["cat_title"] = cat_title
            tables.append(entry)
    # Fall back to a vision-OCR'd table for posts whose list is image-only.
    if not tables and "rows" in OCR_DATA.get(post["key"], {}):
        tables.append({
            "header": "OCR", "score": -1, "ocr": True,
            "rows": len(OCR_DATA[post["key"]]["rows"]) + 1,
            "normalized": True,
            "html": emit_norm_rows(OCR_DATA[post["key"]]["rows"]),
        })
    cap = CAPTION[server]
    for i, t in enumerate(tables):
        if t.get("cat_title"):                      # split section -> its own name
            base = f"{cap} · {t['cat_title']}"
        elif len(tables) == 1:
            base = cap
        else:
            base = f"{cap} ({i + 1})"
        t["caption"] = base + (" · ดึงจากรูปภาพ" if t.get("ocr") else "")
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

    # Resolve OCR aliases: a post that reuses another post's standing list
    # (e.g. na-810 had no list of its own — it's the same Takato list as 4100).
    for key, meta in OCR_DATA.items():
        if "alias" not in meta or result.get(key, {}).get("tables"):
            continue
        src = result.get(meta["alias"], {}).get("tables")
        if not src:
            print(f"  !! alias source missing for {key}: {meta['alias']}", file=sys.stderr)
            continue
        srv = key.split("-")[0].upper()
        result[key] = {"tables": [{
            "header": "ALIAS", "score": -1, "ocr": True, "alias": meta["alias"],
            "rows": src[0]["rows"], "normalized": True, "html": src[0]["html"],
            "caption": CAPTION[srv] + " · " + meta.get("tag", "ลิสต์มาตรฐาน"),
        }], "note": ""}
        print(f"{key:<12} tables=1 (alias -> {meta['alias']})")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    n_tbl = sum(len(v.get("tables", [])) for v in result.values())
    n_none = sum(1 for v in result.values() if not v.get("tables"))
    print(f"\nWrote {OUT}  ({n_tbl} tables across {len(posts)} posts; "
          f"{n_none} posts with no table)")


if __name__ == "__main__":
    main()
