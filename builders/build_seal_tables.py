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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
HTML = PROJ / "docs" / "seals.html"
DATA = PROJ / "data" / "seal_tables.json"

CSS = """
  /* injected by build_seal_tables.py — seal exchange tables */
  /* cards on this page carry no head/title, so the source-links row is the
     card's header: give it top padding and pull the detail toggle up close
     beneath it */
  .tl-entry > .sources:first-child { padding-top: 16px; }
  .tl-entry .sources { padding-bottom: 8px; }
  .seal-detail { margin: 0 20px 16px; }
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
  .seal-cap { font-size: 11.5px; font-weight: 600; color: var(--muted);
    margin: 14px 2px 6px; }
  .seal-cap:first-of-type { margin-top: 4px; }
  .seal-tbl-wrap { overflow-x: auto; border: 1px solid var(--hairline);
    border-radius: var(--radius); background: var(--canvas); }
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
  .seal-match { margin: 2px 20px 14px; font-size: 12px; color: var(--muted); }
  .seal-match .lbl { color: var(--muted-soft); }
  .seal-match a { color: var(--body); text-decoration: none; font-weight: 500;
    border: 1px solid var(--hairline); border-radius: 9999px; padding: 2px 9px;
    margin-right: 4px; white-space: nowrap; }
  .seal-match a:hover { background: var(--surface-soft); }
  /* twin link wears the colour of the server it points to */
  .seal-match a.tw-na { color: var(--amber); border-color: var(--amber); }
  .seal-match a.tw-kr { color: var(--coral); border-color: var(--coral); }
  .seal-match a.tw-th { color: var(--teal); border-color: var(--teal); }
  /* per-table notes live inside the details, aligned with the caption */
  .seal-detail .seal-match { margin: -2px 2px 12px; }
"""

CSS_START, CSS_END = "/* SEAL-CSS */", "/* /SEAL-CSS */"
ST_RE = re.compile(r"\n?[ \t]*<!--ST:[^>]*?-->.*?<!--/ST-->", re.S)

_SRV_ORDER = {"na": 0, "kr": 1, "th": 2}


def _row_seq(html):
    """Rate-tuple sequence (qty,ticket,stat,max) of a table's data rows."""
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S)[1:]:
        c = [re.sub(r"<[^>]+>", "", x).strip()
             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(c) >= 5:
            out.append((c[1], c[2], c[3], c[4]))
    return tuple(out)


def compute_matches(data):
    """Map each post-key to the keys on OTHER servers whose exchange list is
    identical (same seal qty/ticket/stat/max sequence)."""
    from collections import defaultdict
    seqs = defaultdict(list)              # sequence -> [(key, table_index)]
    for key, v in data.items():
        for ti, t in enumerate(v.get("tables", [])):
            s = _row_seq(t["html"])
            if s:
                seqs[s].append((key, ti))
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


def block_for(key, data, tmatch=None, dates=None):
    tables = data.get("tables", [])
    if not tables:
        return ""   # posts without a table get nothing injected
    dates, tmatch = dates or {}, tmatch or {}

    def note(tw):
        links = " ".join(_twin_link(x, dates) for x in tw)
        return (f'<div class="seal-match"><span class="lbl">🔗 ลิสต์เดียวกับ:</span> '
                f'{links}</div>')

    single = len(tables) == 1
    inner = [f"<!--ST:{key}-->"]
    if single and tmatch.get(0):          # one table -> note above the toggle
        inner.append(note(tmatch[0]))
    label = "ดูตารางแลกซีล" + (f" · {len(tables)} ตาราง" if not single else "")
    inner.append(f'<details class="seal-detail"><summary>📋 {label}</summary>')
    for ti, t in enumerate(tables):
        inner.append(f'<div class="seal-cap">{t["caption"]}</div>')
        if not single and tmatch.get(ti):  # many tables -> note per table
            inner.append(note(tmatch[ti]))
        inner.append(f'<div class="seal-tbl-wrap">{t["html"]}</div>')
    inner.append("</details>")
    inner.append("<!--/ST-->")
    return "\n        " + "\n        ".join(inner)


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
        blk = block_for(key, d, matches.get(key, {}), dates)
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
    n_tbl = sum(len(v.get("tables", [])) for v in data.values())
    print(f"Injected into {injected} cards, removed {removed} no-table cards "
          f"({n_tbl} tables total) -> {HTML}")


if __name__ == "__main__":
    main()
