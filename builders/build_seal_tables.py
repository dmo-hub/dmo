"""Inject the extracted seal-exchange tables into docs/seals.html.

Reads data/seal_tables.json (from extract_seal_tables.py) and inserts a
collapsible <details> block with the cleaned table(s) into each matching
card (matched by the card's id == json key). Idempotent: previously
injected blocks (wrapped in ST markers) and the CSS block are replaced on
re-run.

Run: python builders/build_seal_tables.py
"""

import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # for `import aliases`
import aliases  # noqa: E402  central dub/JP name canonicaliser

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
HTML = PROJ / "docs" / "seals.html"
DATA = PROJ / "data" / "seal_tables.json"
SEAL_DATA_OUT = PROJ / "docs" / "seal_data.json"   # per-table data for calc.html

CSS = """
  /* injected by build_seal_tables.py — seal exchange tables */
  /* cards on this page carry no head/title, so the source-links row is the
     card's header: give it top padding and pull the detail toggle up close
     beneath it */
  .tl-entry > .sources:first-child { padding-top: 16px; }
  .tl-entry .sources { padding-bottom: 8px; }
  /* meta row (♾️ badge + match links) and actions row (star + toggle) —
     two balanced flex lines instead of four stacked blocks */
  .seal-meta { display: flex; flex-wrap: wrap; align-items: center;
    gap: 6px 10px; margin: 2px 20px 10px; }
  .seal-actions { display: flex; flex-wrap: wrap; align-items: flex-start;
    gap: 8px; margin: 0 20px 16px; }
  .seal-detail { margin: 0; }
  .seal-detail[open] { flex-basis: 100%; }
  .seal-detail > summary {
    cursor: pointer; list-style: none; user-select: none;
    display: inline-flex; align-items: center; gap: 7px;
    font-size: 12px; font-weight: 600; color: var(--coral);
    padding: 6px 13px; border: 1px solid var(--hairline);
    border-radius: 9999px; background: var(--surface-soft);
  }
  .seal-detail > summary::-webkit-details-marker { display: none; }
  .seal-detail > summary::before { content: "▸"; font-size: 9px; }
  .seal-detail[open] > summary::before { content: "▾"; }
  .seal-detail[open] > summary { margin-bottom: 12px; }
  .seal-tbl-wrap { overflow-x: auto; border: 1px solid var(--hairline);
    border-radius: var(--radius); background: var(--canvas); }
  .seal-tbl-wrap + .seal-tbl-wrap, .seal-tbl-wrap + .seal-match { margin-top: 14px; }
  table.seal-tbl { border-collapse: collapse; width: 100%;
    font-size: 12px; min-width: 360px; }
  table.seal-tbl th, table.seal-tbl td {
    padding: 6px 11px; text-align: center; line-height: 1.35;
    border-bottom: 1px solid var(--hairline); white-space: nowrap; }
  table.seal-tbl tr:first-child th {
    background: var(--surface-card); color: var(--ink); font-weight: 600;
    position: sticky; top: 0; }
  table.seal-tbl tr:nth-child(even) td { background: var(--surface-soft); }
  table.seal-tbl td:first-child, table.seal-tbl th:first-child {
    text-align: left; font-weight: 500; }
  table.seal-tbl tr:last-child td { border-bottom: 0; }
  .seal-match { margin: 0; font-size: 12px; color: var(--muted); }
  .seal-match .lbl { color: var(--muted-soft); }
  .seal-match a { color: var(--body); text-decoration: none; font-weight: 500;
    border: 1px solid var(--hairline); border-radius: 9999px; padding: 2px 9px;
    margin-right: 4px; white-space: nowrap; }
  .seal-match a:hover { background: var(--surface-soft); }
  /* twin link wears the colour of the server it points to */
  .seal-match a.tw-na { color: var(--amber); border-color: var(--amber); }
  .seal-match a.tw-kr { color: var(--coral); border-color: var(--coral); }
  .seal-match a.tw-th { color: var(--teal); border-color: var(--teal); }
  /* per-table notes live inside the details, above their table */
  .seal-detail .seal-match { margin: 0 2px 10px; }
  /* NA/KR standing-list badge (full text in its tooltip) */
  .seal-note { margin: 0; font-size: 11.5px; font-weight: 500; cursor: help;
    color: var(--amber); display: inline-flex; align-items: center; gap: 5px;
    padding: 4px 11px; border: 1px solid var(--amber); border-radius: 9999px;
    background: var(--surface-soft); }
  .seal-tbl .inf { font-size: 10px; cursor: help; }
  /* visible "add to calculator" star bar (sits above the table toggle) */
  .seal-starbar { display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 20px 10px; }
  .seal-star { appearance: none; cursor: pointer; font: inherit; font-size: 12px;
    font-weight: 600; display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 13px; border-radius: 9999px;
    border: 1px solid var(--hairline); background: var(--surface-soft);
    color: var(--body); transition: background .12s, border-color .12s, color .12s; }
  .seal-star .ic { font-size: 15px; line-height: 1; }
  .seal-star:hover { border-color: var(--amber); color: var(--amber); }
  .seal-star.on { background: var(--amber); border-color: var(--amber); color: var(--on-primary); }
"""

CSS_START, CSS_END = "/* SEAL-CSS */", "/* /SEAL-CSS */"
# Strip the leading newline+indent AND the trailing newline+indent we add
# around the block on inject (step 3), so repeated rebuilds don't accumulate
# blank lines before each card's </article> (keeps the build idempotent).
ST_RE = re.compile(r"\n?[ \t]*<!--ST:[^>]*?-->.*?<!--/ST-->[ \t]*\n?[ \t]*", re.S)

_SRV_ORDER = {"na": 0, "kr": 1, "th": 2}
_TH_EN_PATH = PROJ / "data" / "th_seal_en.json"
TH_EN = (json.loads(_TH_EN_PATH.read_text(encoding="utf-8"))
         if _TH_EN_PATH.exists() else {})


def _norm_seal(s):
    # alias-fold dub/JP spellings of the same digimon (Scorpiomon==Anomalocarimon)
    # so KR and NA lists compare equal; aliases.norm also strips " Seal"/[tags].
    return aliases.norm(s)


def _name_multiset(html, server):
    """Multiset of canonical English seal names. TH names are translated via
    TH_EN; an untranslated TH name is namespaced so it never matches by chance."""
    from collections import Counter
    ms = Counter()
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S)[1:]:
        cells = [re.sub(r"<[^>]+>", "", x).strip()
                 for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if not cells or not cells[0]:
            continue
        raw = re.sub(r"\[[^\]]*\]", "", cells[0]).strip()
        if server == "th":
            base = re.sub(r"\s*ซีล.*$", "", raw).strip()
            en = TH_EN.get(base)
            key = _norm_seal(en) if en else "th:" + _norm_seal(re.sub(r"ซีล", "", base))
        else:
            key = _norm_seal(re.sub(r"\s*Seal.*$", "", raw))
        if key:
            ms[key] += 1
    return ms


def compute_matches(data):
    """Map each post-key to the keys on OTHER servers whose exchange list has
    the SAME seals (English-name multiset, order-independent; TH via TH_EN)."""
    from collections import defaultdict
    seqs = defaultdict(list)              # name-multiset -> [(key, table_index)]
    for key, v in data.items():
        srv = key.split("-")[0]
        for ti, t in enumerate(v.get("tables", [])):
            ms = _name_multiset(t["html"], srv)
            if ms:
                seqs[frozenset(ms.items())].append((key, ti))
    res = defaultdict(dict)               # key -> {table_index: [twin keys]}
    for members in seqs.values():
        for key, ti in members:
            srv = key.split("-")[0]
            # cross-server only — a list recurring in another post on the SAME
            # server is not a server comparison, so skip same-server twins.
            twins = sorted({o for o, _ in members if o.split("-")[0] != srv},
                           key=lambda x: (_SRV_ORDER.get(x.split("-")[0], 9), x))
            if twins:
                res[key][ti] = twins
    return res


def _twin_link(k, dates):
    """Link to a twin card, labelled "SRV DD.MM.YYYY" (falls back to the
    post id when the date is unknown)."""
    srv, idp = k.split("-", 1)
    label = dates.get(k) or idp
    return f'<a class="tw-{srv}" href="#{k}">{srv.upper()} {label}</a>'


def standing_note(key):
    """Short ♾️ badge for NA/KR cards. The full explanation lives in
    standing_note_full() and is shown as the badge's tooltip — every row also
    carries its own ♾️, so the badge stays compact. NA/KR seal exchange is a
    standing list (NA: "will remain unchanged"; KR: 오유민 list "유지됩니다");
    TH posts say the NPC exists "ในระยะเวลากิจกรรม" (event-only), so TH gets
    no badge. Also shipped to the Budget calc via seal_data.json."""
    return "♾️ ลิสต์ถาวร · ไม่หายไป" if key.split("-")[0] in ("na", "kr") else ""


def standing_note_full(key):
    srv = key.split("-")[0]
    if srv not in ("na", "kr"):
        return ""
    npc = "Takato" if srv == "na" else "โอยูมิน (오유민)"
    return (f'ซีลที่แลกกับ {npc} ไม่หายไป — '
            f'ลิสต์เก่ายังแลกได้ต่อ (สะสมเพิ่มทุกแพท)')


_INF_MARK = (' <span class="inf" title="ไม่หายไป — ลิสต์เก่ายังแลกได้ต่อ '
             '(สะสมเพิ่มทุกแพท)">♾️</span>')


def _seal_key(raw, srv):
    """Normalized cross-server seal key for a name cell, or None if a TH name
    has no English mapping (it then can't be matched against the NA/KR set)."""
    raw = re.sub(r"\[[^\]]*\]", "", raw).strip()
    if srv == "th":
        base = re.sub(r"\s*ซีล.*$", "", raw).strip()
        en = TH_EN.get(base)
        return _norm_seal(en) if en else None
    return _norm_seal(raw)


def _standing_set(data):
    """Normalized names of every seal in the NA/KR standing lists. Those
    lists never rotate out, so any seal in them — on ANY server's table —
    is permanently exchangeable somewhere."""
    s = set()
    for key, v in data.items():
        srv = key.split("-")[0]
        if srv not in ("na", "kr"):
            continue
        for t in v.get("tables", []):
            for r in _table_rows_only(t["html"]):
                if r and r[0]:
                    k = _seal_key(r[0], srv)
                    if k:
                        s.add(k)
    return s


def _mark_standing(html, srv, standing):
    """Append ♾️ to the seal-name cell of each data row whose seal is in the
    standing set (TH names are translated to English first). Header rows use
    <th> so the <tr><td> pattern only touches data rows. Applied at inject
    time only — data/seal_tables.json stays clean for matching/calc."""
    def mark(m):
        name = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        k = _seal_key(name, srv)
        if k and k in standing:
            return m.group(1) + m.group(2) + _INF_MARK + m.group(3)
        return m.group(0)
    return re.sub(r"(<tr><td>)(.*?)(</td>)", mark, html)


def block_for(key, data, tmatch=None, dates=None, standing=None):
    tables = data.get("tables", [])
    if not tables:
        return ""   # posts without a table get nothing injected
    dates, tmatch, standing = dates or {}, tmatch or {}, standing or set()

    def note(tw):
        links = " ".join(_twin_link(x, dates) for x in tw)
        return (f'<div class="seal-match"><span class="lbl">🔗 ลิสต์เดียวกับ:</span> '
                f'{links}</div>')

    single = len(tables) == 1
    inner = [f"<!--ST:{key}-->"]
    # meta row: compact ♾️ badge (full text in tooltip) + cross-server match
    meta = []
    if standing_note(key):
        meta.append(f'<span class="seal-note" title="{standing_note_full(key)}">'
                    f'{standing_note(key)}</span>')
    if single and tmatch.get(0):          # one table -> note in the meta row
        meta.append(note(tmatch[0]))
    if meta:
        inner.append('<div class="seal-meta">' + "".join(meta) + "</div>")
    # actions row: star button(s) + the table toggle side by side
    bar = "".join(
        f'<button class="seal-star" data-tkey="{key}#{ti}" type="button" '
        f'title="เพิ่มเข้ารายการติดตาม">'
        f'<span class="ic">☆</span>{"รายการติดตาม" if single else f"รายการติดตาม #{ti + 1}"}</button>'
        for ti in range(len(tables)))
    inner.append('<div class="seal-actions">')
    inner.append(f'<div class="seal-starbar">{bar}</div>')
    label = "ดูตารางแลกซีล" + (f" · {len(tables)} ตาราง" if not single else "")
    inner.append(f'<details class="seal-detail"><summary>📋 {label}</summary>')
    for ti, t in enumerate(tables):
        # no caption line — the table itself says what it is
        if not single and tmatch.get(ti):  # many tables -> note per table
            inner.append(note(tmatch[ti]))
        thtml = _mark_standing(t["html"], key.split("-")[0], standing)
        inner.append(f'<div class="seal-tbl-wrap">{thtml}</div>')
    inner.append("</details>")
    inner.append("</div>")
    inner.append("<!--/ST-->")
    return "\n        " + "\n        ".join(inner)


def _table_rows_only(html):
    """Data rows (no header) of a normalized seal table as lists of cells."""
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S)[1:]:
        cells = [re.sub(r"<[^>]+>", "", x).strip()
                 for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if cells:
            out.append(cells)
    return out


def emit_seal_data(data, html, standing=None):
    """Write docs/seal_data.json — one entry per table, keyed key#index, so
    calc.html can fetch the seals a user stars and run the ticket/price calc.
    `inf` carries a per-row 0/1 flag: the seal is in the NA/KR standing set
    (never rotates out), so the calc can ♾️-mark it on ANY server's table."""
    standing = standing or set()
    dates = dict(re.findall(
        r'<article\b[^>]*\bid="([^"]+)"[^>]*>.*?<span class="src-date">([^<]+)</span>',
        html, re.S))
    out = {}
    for key, v in data.items():
        if not v.get("tables"):
            continue
        srv = key.split("-")[0]
        for ti, t in enumerate(v["tables"]):
            rows = _table_rows_only(t["html"])
            out[f"{key}#{ti}"] = {
                "server": srv,
                "date": dates.get(key, ""),
                "caption": t.get("caption", ""),
                "note": standing_note(key),
                "inf": [1 if (r and r[0] and (_seal_key(r[0], srv) or "") in standing) else 0
                        for r in rows],
                "rows": rows,
            }
    SEAL_DATA_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print(f"  wrote {SEAL_DATA_OUT.name} ({len(out)} tables)")


def drop_empty_months(html):
    """Remove month headers left with no <article> after card removal."""
    op = '<div class="timeline">'
    oi = html.index(op)
    note = html.index('<p style="max-width:760px', oi)
    ci = html.rindex("</div>", oi, note)          # timeline's closing </div>
    inner = html[oi + len(op):ci]
    parts = re.split(r'(<div class="tl-month">.*?</div>)', inner, flags=re.S)
    out = parts[0]
    for i in range(1, len(parts), 2):
        content = parts[i + 1] if i + 1 < len(parts) else ""
        if "<article" in content:
            out += parts[i] + content
    return html[:oi + len(op)] + out + html[ci:]


def update_counts(html, data):
    """Set hero total / earliest-year / per-server tab counts from the cards
    that actually remain in the page."""
    from collections import Counter
    kept = [k for k, v in data.items() if v.get("tables")]
    c = Counter(k.split("-")[0] for k in kept)
    labels = {"NA": "NA · gameking", "KR": "KR · digimonmasters", "TH": "TH · vplay"}
    for srv, lab in labels.items():
        html = re.sub(
            r'(data-server="%s"[^>]*>%s <span class="tab-count">)\d+(</span>)'
            % (srv, re.escape(lab)),
            lambda m, n=c[srv.lower()]: f"{m.group(1)}{n}{m.group(2)}", html)
    html = re.sub(r'(<div class="num">)\d+(</div><div class="lbl">โพสต์)',
                  lambda m: f"{m.group(1)}{len(kept)}{m.group(2)}", html)
    years = re.findall(r'<span class="src-date">\d{2}\.\d{2}\.(\d{4})</span>', html)
    if years:
        lo = min(years)
        html = re.sub(r'(<div class="num">)\d{4}(</div><div class="lbl">ตั้งแต่)',
                      lambda m: f"{m.group(1)}{lo}{m.group(2)}", html)
    return html


def main():
    html = HTML.read_text(encoding="utf-8")
    data = json.loads(DATA.read_text(encoding="utf-8"))

    # 1) strip previously injected table blocks
    html = ST_RE.sub("", html)

    # 2) (re)inject CSS once, inside the existing <style>
    css_block = f"{CSS_START}{CSS}{CSS_END}"
    if CSS_START in html:
        html = re.sub(re.escape(CSS_START) + r".*?" + re.escape(CSS_END),
                      css_block, html, flags=re.S)
    else:
        html = html.replace("</style>", css_block + "\n</style>", 1)

    # 3) inject a block before each matching card's </article>
    matches = compute_matches(data)
    standing = _standing_set(data)        # seals that never rotate out (NA/KR)
    # key -> card date (DD.MM.YYYY), read from each card's src-date span, so
    # twin links can be labelled by date rather than the opaque post id
    dates = dict(re.findall(
        r'<article\b[^>]*\bid="([^"]+)"[^>]*>.*?<span class="src-date">([^<]+)</span>',
        html, re.S))
    injected = 0
    for key, d in data.items():
        if not d.get("tables"):
            continue   # no-table posts are removed below, not injected
        pat = re.compile(r'(<article\b[^>]*\bid="%s"[^>]*>.*?)(</article>)'
                         % re.escape(key), re.S)
        if not pat.search(html):
            print(f"  !! card not found: {key}", file=sys.stderr)
            continue
        blk = block_for(key, d, matches.get(key, {}), dates, standing)
        html = pat.sub(lambda m: m.group(1) + blk + "\n      " + m.group(2),
                       html, count=1)
        injected += 1
    print(f"  cross-server matches: {len(matches)} cards link a twin")

    # 4) remove cards with no table ("no real data"), then prune empty months
    removed = 0
    for key, d in data.items():
        if d.get("tables"):
            continue
        html, n = re.subn(r'\n?\s*<article\b[^>]*\bid="%s"[^>]*>.*?</article>'
                          % re.escape(key), "", html, flags=re.S, count=1)
        removed += n
    html = drop_empty_months(html)

    # 5) refresh hero total / year / tab counts to match remaining cards
    html = update_counts(html, data)

    HTML.write_text(html, encoding="utf-8")
    emit_seal_data(data, html, standing)  # per-table data for calc.html
    n_tbl = sum(len(v.get("tables", [])) for v in data.values())
    print(f"Injected into {injected} cards, removed {removed} no-table cards "
          f"({n_tbl} tables total) -> {HTML}")


if __name__ == "__main__":
    main()
