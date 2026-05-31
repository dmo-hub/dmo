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
  .seal-detail { margin: 2px 20px 16px; }
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
"""

CSS_START, CSS_END = "/* SEAL-CSS */", "/* /SEAL-CSS */"
ST_RE = re.compile(r"\n?[ \t]*<!--ST:[^>]*?-->.*?<!--/ST-->", re.S)


def block_for(key, data):
    tables = data.get("tables", [])
    if not tables:
        return ""   # posts without a table get nothing injected
    n = len(tables)
    label = "ดูตารางแลกซีล" + (f" · {n} ตาราง" if n > 1 else "")
    inner = [f'<!--ST:{key}-->',
             f'<details class="seal-detail"><summary>📋 {label}</summary>']
    for t in tables:
        inner.append(f'<div class="seal-cap">{t["caption"]}</div>')
        inner.append(f'<div class="seal-tbl-wrap">{t["html"]}</div>')
    inner.append("</details>")
    inner.append("<!--/ST-->")
    return "\n        " + "\n        ".join(inner)


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
    injected = 0
    for key, d in data.items():
        pat = re.compile(r'(<article\b[^>]*\bid="%s"[^>]*>.*?)(</article>)'
                         % re.escape(key), re.S)
        if not pat.search(html):
            print(f"  !! card not found: {key}", file=sys.stderr)
            continue
        blk = block_for(key, d)
        if not blk:
            continue   # no-table posts get nothing
        html = pat.sub(lambda m: m.group(1) + blk + "\n      " + m.group(2),
                       html, count=1)
        injected += 1

    HTML.write_text(html, encoding="utf-8")
    n_tbl = sum(len(v.get("tables", [])) for v in data.values())
    print(f"Injected into {injected}/{len(data)} cards "
          f"({n_tbl} tables total) -> {HTML}")


if __name__ == "__main__":
    main()
