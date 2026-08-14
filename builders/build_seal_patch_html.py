"""Generate docs/seal-patch-th-<N>.html — the per-patch TH seal page with the
ticket/pack/price calculator — from data the pipeline already produces.

Data sources:
  * docs/seal_data.json ..... the patch's exchange table(s) (th-<N>#i keys)
  * data/th_patch_index.json  post URL + slug for the patch suffix
  * cache/th_view_*-<N>.html  the patch post itself, for the declared
                              "เพิ่มซีลใหม่" table -> 🆕 badges per row

Rows are copied verbatim from seal_data.json — no re-parsing, no manual
transcription. 🆕 badges come from the patch's own new-seal announcement,
not from diffing history (TH patch lineups never overlap, so "seen before"
is meaningless there). Declared names are matched to exchange-row names
with whitespace/ซีล-insensitive comparison plus a fuzzy fallback, because
posts sometimes spell the same digimon two ways (โอคุวากามอน vs โอคุวามอน).

Run:  python builders/build_seal_patch_html.py 92        # one patch
      python builders/build_seal_patch_html.py --all     # every suffix that has a page or tables
"""

import difflib
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
CACHE = PROJ / "cache"
DOCS = PROJ / "docs"
SEAL_DATA = json.loads((DOCS / "seal_data.json").read_text(encoding="utf-8"))
TH_INDEX = json.loads((PROJ / "data" / "th_patch_index.json").read_text(encoding="utf-8"))

# table whose caption marks the special-ticket craft category renders without
# the Status column (the hand-built th-88 page's noStats behaviour)
NO_STATS_MARK = "ตั๋วแลกซีลแบบพิเศษ"


def post_for_suffix(n):
    for p in TH_INDEX["posts"]:
        if re.search(rf"-{n}$", p["slug"]):
            return p
    return None


def declared_new_seals(n):
    """Names from the patch's own 'เพิ่มซีลใหม่' table ([] when absent)."""
    p = post_for_suffix(n)
    if not p:
        return []
    hits = list(CACHE.glob(f"th_view_*-{n}.html"))
    if not hits:
        return []
    h = hits[0].read_text(encoding="utf-8", errors="ignore")
    i = h.find("เพิ่มซีลชนิดใหม่")
    if i < 0:
        i = h.find("เพิ่มซีลใหม่")
    if i < 0:
        return []
    m = re.search(r"<table.*?</table>", h[i:], re.S)
    if not m:
        return []
    names = []
    for row in re.findall(r"<tr\b.*?</tr>", m.group(0), re.S):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c.replace("&nbsp;", " "))).strip()
            for _, c in re.findall(r"<(td|th)\b[^>]*>(.*?)</\1>", row, re.S)
        ]
        if len(cells) >= 2 and cells[0] and cells[0] != "ซีล":
            names.append(cells[0])
    return names


def _squash(s):
    return re.sub(r"[\sซีล]+", "", s)


def match_new_to_rows(declared, row_names):
    """Map declared new-seal names onto exchange-row spellings."""
    out, misses = set(), []
    squashed = {_squash(r): r for r in row_names}
    for d in declared:
        key = _squash(d)
        if key in squashed:
            out.add(squashed[key])
            continue
        close = difflib.get_close_matches(key, list(squashed), n=1, cutoff=0.8)
        if close:
            out.add(squashed[close[0]])
        else:
            misses.append(d)
    return out, misses


def tables_for(n):
    keys = sorted(k for k in SEAL_DATA if re.fullmatch(rf"th-{n}(#\d+)?", k))
    return [(k, SEAL_DATA[k]) for k in keys if SEAL_DATA[k].get("rows")]


def js_str(s):
    return json.dumps(s, ensure_ascii=False)


def build_tables_js(n, tables, new_rows):
    blocks = []
    for k, v in tables:
        rows = ",\n".join("        " + json.dumps(r, ensure_ascii=False) for r in v["rows"])
        no_stats = NO_STATS_MARK in v.get("caption", "")
        lines = [
            "    {",
            f"      key: {js_str(k)},",
            f"      caption: {js_str(v['caption'])},",
            f"      date: {js_str(v['date'])},",
        ]
        if no_stats:
            lines.append("      noStats: true,")
        lines.append("      rows: [\n" + rows + "\n      ]" + ("," if new_rows else ""))
        if new_rows:
            names = ",\n".join(
                "        " + js_str(r) for r in v["rows"] if r[0] in new_rows
            )
            lines.append("      newSeals: [\n" + names + "\n      ]")
        lines.append("    }")
        blocks.append("\n".join(lines))
    return "  const TABLES = [\n" + ",\n".join(blocks) + "\n  ];"


def build(n):
    tables = tables_for(n)
    if not tables:
        print(f"  th-{n}: no tables in seal_data.json — skipped")
        return False
    post = post_for_suffix(n)
    date = tables[0][1]["date"]
    post_url = post["url"] if post else ""

    declared = declared_new_seals(n)
    all_rows = [r[0] for _, v in tables for r in v["rows"]]
    new_rows, misses = match_new_to_rows(declared, all_rows)
    for m in misses:
        print(f"  th-{n}: declared new seal not in exchange table: {m}")

    n_seals = len(all_rows)
    n_stats = len({r[3] for _, v in tables for r in v["rows"] if r[3] and r[3] != "—"})
    hero_new = (
        f'\n      <div class="hero-stat"><div class="num">{len(new_rows)}</div>'
        f'<div class="lbl">🆕 ซีลใหม่</div></div>'
        if new_rows
        else ""
    )
    pack_note = (
        "· 1 แพ็ค = 3,000 ตั๋ว · แต่ละหมวดคนละแพ็ค คิดราคาแยกกัน"
        if len(tables) > 1
        else "· 1 แพ็ค = 3,000 ตั๋ว"
    )
    lead_cat = (
        f"{len(tables)} หมวด พร้อมเครื่องคำนวณตั๋ว/แพ็ค/ราคา"
        if len(tables) > 1
        else "พร้อมเครื่องคำนวณตั๋ว/แพ็ค/ราคา"
    )
    site_url = (
        f'<a href="{post_url}" target="_blank" rel="noopener noreferrer">vplay.in.th</a>'
        if post_url
        else "vplay.in.th"
    )

    html = TEMPLATE
    html = html.replace("{{DATE}}", date)
    html = html.replace("{{N}}", str(n))
    html = html.replace("{{HERO_NEW}}", hero_new)
    html = html.replace("{{N_TABLES}}", str(len(tables)))
    html = html.replace("{{N_SEALS}}", str(n_seals))
    html = html.replace("{{N_STATS}}", str(n_stats))
    html = html.replace("{{PACK_NOTE}}", pack_note)
    html = html.replace("{{LEAD_CAT}}", lead_cat)
    html = html.replace("{{SITE_URL}}", site_url)
    html = html.replace("{{TABLES_JS}}", build_tables_js(n, tables, new_rows))

    out = DOCS / f"seal-patch-th-{n}.html"
    out.write_text(html, encoding="utf-8")
    print(
        f"  Wrote {out.name} — {len(tables)} table(s), {n_seals} seals, "
        f"{len(new_rows)} new, date {date}"
    )
    return True


def all_suffixes():
    have_tables = {
        int(m.group(1))
        for k in SEAL_DATA
        if (m := re.fullmatch(r"th-(\d+)(#\d+)?", k)) and SEAL_DATA[k].get("rows")
    }
    have_pages = {
        int(m.group(1))
        for f in DOCS.glob("seal-patch-th-*.html")
        if (m := re.search(r"th-(\d+)\.html$", f.name))
    }
    # regenerate existing pages + build pages for any newer patch with tables
    newest_page = max(have_pages) if have_pages else 0
    return sorted(have_pages | {s for s in have_tables if s > newest_page})


def main():
    args = sys.argv[1:]
    if args and args[0] == "--all":
        targets = all_suffixes()
    elif args:
        targets = [int(a) for a in args]
    else:
        targets = all_suffixes()
    print(f"Building seal-patch pages for: {targets}\n")
    for n in targets:
        build(n)


# ── page template (canonical layout = the reviewed th-92 page) ──────────────
TEMPLATE = r"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="ซีลแพทช์ TH {{DATE}} — รายละเอียดตารางแลก + เครื่องคำนวณ">
<meta property="og:title" content="DMO · ซีลแพทช์ TH {{DATE}} — รายละเอียด + คำนวณ">
<meta property="og:description" content="ซีลแพทช์ TH {{DATE}} — รายละเอียดตารางแลก + เครื่องคำนวณ">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎮</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<title>DMO · ซีลแพทช์ TH {{DATE}} — รายละเอียด + คำนวณ</title>
<script src="js/theme.js"></script>
<link rel="stylesheet" href="css/site.css">
<style>
  /* ===== page-scoped: TH seal patch detail + calculator ===== */
  /* standalone header: brand left, meta + theme toggle pushed right */
  .site-nav .nav-meta { margin-left: auto; }
  .patch-meta { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center;
    margin: 0 0 22px; font-size: 13px; color: var(--muted); }
  .patch-meta .pm { display: inline-flex; align-items: center; gap: 6px; }
  .patch-meta .pm b { color: var(--ink); font-weight: 600; }
  .patch-meta .srv-th { font-size: 9.5px; font-weight: 600; letter-spacing: 1.2px;
    text-transform: uppercase; padding: 2px 9px; border-radius: 9999px;
    background: var(--teal); color: var(--on-primary); }

  /* hide the native number-input spinner */
  .page input[type=number] { -moz-appearance: textfield; appearance: textfield; }
  .page input[type=number]::-webkit-outer-spin-button,
  .page input[type=number]::-webkit-inner-spin-button {
    -webkit-appearance: none; appearance: none; margin: 0; }

  /* per-table budget summary (lives above each card's table) */
  .calc-total { background: var(--surface-soft); color: var(--ink);
    border-bottom: 1px solid var(--hairline); padding: 4px;
    display: flex; flex-direction: column; }
  .calc-total .ct-row { display: flex; align-items: baseline; justify-content: space-between;
    gap: 16px; padding: 8px 14px; border-radius: var(--radius-xs); }
  .calc-total .ct-row + .ct-row { border-top: 1px solid var(--hairline); }
  .calc-total .t { font-size: 12px; color: var(--muted); font-weight: 500; }
  .calc-total .vw { display: inline-flex; align-items: baseline; gap: 5px; }
  .calc-total .v { font-size: 14px; font-weight: 700; color: var(--ink);
    font-variant-numeric: tabular-nums; font-family: var(--display-font); letter-spacing: -.2px; }
  .calc-total .u { font-size: 10px; color: var(--muted-soft); }
  .calc-total .ct-pricein input.price-pack { width: 84px; padding: 5px 8px; font: inherit;
    font-size: 13px; border: 1px solid var(--hairline); border-radius: var(--radius-xs);
    background: var(--canvas); color: var(--ink); text-align: right; }
  .calc-total .ct-price { background: var(--surface-card); }
  .calc-total .ct-price .t { color: var(--body); font-weight: 600; }
  .calc-total .ct-price .v { font-size: 15.5px; color: var(--ink); }
  .calc-total .ct-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px;
    padding: 8px; border-top: 1px solid var(--hairline); }
  .calc-total .ct-stats .st { display: flex; align-items: baseline; justify-content: space-between;
    gap: 6px; padding: 5px 10px; background: var(--surface-soft); border-radius: var(--radius-xs); }
  .calc-total .ct-stats .st .k { font-size: 11px; font-weight: 700; color: var(--muted); letter-spacing: .3px; }
  .calc-total .ct-stats .st .n { font-size: 13px; font-weight: 700; color: var(--ink);
    font-variant-numeric: tabular-nums; font-family: var(--display-font); }
  @media (max-width: 520px) { .calc-total .ct-stats { grid-template-columns: repeat(2, 1fr); } }

  /* per-table card */
  .calc-card { border: 1px solid var(--hairline); border-radius: var(--radius);
    background: var(--canvas); margin: 0 0 16px; overflow: hidden; }
  .calc-card-head { display: flex; align-items: center; gap: 10px; padding: 9px 13px;
    border-bottom: 1px solid var(--hairline); background: var(--surface-soft); }
  .calc-srv { font-size: 9.5px; font-weight: 600; letter-spacing: 1.2px; text-transform: uppercase;
    padding: 2px 8px; border-radius: 9999px; background: var(--teal); color: var(--on-primary); }
  .calc-card-head .cap { font-size: 12.5px; color: var(--ink); font-weight: 500; }
  .calc-card-head .dt { font-size: 11px; color: var(--muted-soft); font-family: "JetBrains Mono", monospace; }
  .calc-card-head .head-btns { margin-left: auto; display: inline-flex; flex-wrap: wrap; gap: 7px; }
  .calc-card-head .head-btns button { appearance: none; border: 1px solid var(--hairline); cursor: pointer;
    background: var(--canvas); color: var(--body); font: inherit; font-size: 11.5px;
    padding: 4px 12px; border-radius: 9999px; white-space: nowrap; }
  .calc-card-head .head-btns button:hover { background: var(--surface-card); }
  @media (max-width: 560px){ .calc-card-head { flex-wrap: wrap; } .calc-card-head .head-btns { margin-left: 0; width: 100%; } }

  .calc-filter { display: flex; flex-wrap: wrap; align-items: center; gap: 5px;
    padding: 8px 13px; border-bottom: 1px solid var(--hairline); background: var(--canvas); }
  .calc-filter .lbl { font-size: 11px; color: var(--muted-soft); margin-right: 3px; }
  .calc-chip { appearance: none; border: 1px solid var(--hairline); background: var(--surface-soft);
    color: var(--body); font: inherit; font-size: 11px; font-weight: 600; padding: 3px 11px;
    border-radius: 9999px; cursor: pointer; }
  .calc-chip:hover { border-color: var(--teal); }
  .calc-chip.on { background: var(--teal); color: var(--on-primary); border-color: var(--teal); }

  .calc-tbl-wrap { overflow-x: auto; }
  table.calc-tbl { border-collapse: collapse; width: 100%; font-size: 12px; min-width: 480px; }
  table.calc-tbl th, table.calc-tbl td { padding: 6px 11px; text-align: center;
    border-bottom: 1px solid var(--hairline); white-space: nowrap; }
  table.calc-tbl tr:first-child th { background: var(--surface-card); color: var(--ink); }
  table.calc-tbl td:first-child, table.calc-tbl th:first-child { text-align: left; font-weight: 500; }
  table.calc-tbl tr:nth-child(even) td { background: var(--surface-soft); }
  table.calc-tbl input.want { width: 80px; padding: 4px 7px; font: inherit; font-size: 12px;
    border: 1px solid var(--hairline); border-radius: var(--radius-xs);
    background: var(--canvas); color: var(--ink); text-align: right; }
  table.calc-tbl .tk { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--ink); }
  table.calc-tbl .status { font-variant-numeric: tabular-nums; white-space: nowrap; }
  table.calc-tbl .status .got { font-weight: 600; color: var(--ink); }
  table.calc-tbl .status .mx { color: var(--muted); }
  table.calc-tbl tr.sub td { background: var(--surface-card); font-weight: 600; border-top: 2px solid var(--hairline); }
  table.calc-tbl .seal-new { font-size: 11px; vertical-align: middle; cursor: help; }

  /* ===== sponsored ad: floating (desktop) → inline footer (mobile) ===== */
  .ad-label { font-size: 9.5px; letter-spacing: .8px; text-transform: uppercase;
    color: var(--muted-soft); font-weight: 600; }

  /* desktop: floating thumbnail bottom-right */
  .ad-float { position: fixed; right: 18px; bottom: 18px; z-index: 40;
    width: 200px; background: var(--canvas); border: 1px solid var(--hairline);
    border-radius: var(--radius); box-shadow: 0 6px 24px rgba(0,0,0,.18);
    overflow: hidden; }
  .ad-float[hidden] { display: none; }
  .ad-float .ad-head { display: flex; align-items: center; justify-content: space-between;
    padding: 5px 6px 5px 10px; border-bottom: 1px solid var(--hairline); background: var(--surface-strong); }
  .ad-float .ad-close { appearance: none; border: 0; background: none; cursor: pointer;
    color: var(--muted-soft); font-size: 16px; line-height: 1; padding: 2px 6px; border-radius: var(--radius-xs); }
  .ad-float .ad-close:hover { color: var(--coral); background: var(--surface-card); }
  .ad-float .ad-thumb { display: block; width: 100%; cursor: zoom-in; padding: 0; border: 0;
    background: none; }
  .ad-float .ad-thumb img { display: block; width: 100%; height: auto; }

  /* lightbox (shared) */
  .ad-box { position: fixed; inset: 0; z-index: 60; display: none;
    align-items: center; justify-content: center; padding: 24px;
    background: rgba(0,0,0,.62); }
  .ad-box.open { display: flex; }
  .ad-box .ad-stage { position: relative; max-width: min(92vw, 560px); max-height: 88vh; }
  .ad-box .ad-link { display: block; cursor: pointer; border-radius: var(--radius); overflow: hidden;
    box-shadow: 0 12px 40px rgba(0,0,0,.4); }
  .ad-box .ad-link img { display: block; width: 100%; height: auto; max-height: 80vh; object-fit: contain; }
  .ad-box .ad-cta { display: block; text-align: center; margin-top: 10px; color: #fff;
    font-size: 13px; font-weight: 600; text-decoration: none; }
  .ad-box .ad-cta:hover { text-decoration: underline; }
  .ad-box .ad-x { position: absolute; top: -14px; right: -14px; width: 32px; height: 32px;
    border-radius: 50%; border: 0; cursor: pointer; background: var(--canvas); color: var(--ink);
    font-size: 17px; line-height: 32px; box-shadow: 0 2px 10px rgba(0,0,0,.3); }

  /* inline footer ad — hidden on desktop, shown on mobile */
  .ad-inline { display: none; }
  @media (max-width: 720px) {
    .ad-float { display: none !important; }
    .ad-inline { display: block; margin: 26px auto 8px; max-width: 360px; text-align: center; }
    .ad-inline .ad-label { display: block; margin-bottom: 6px; }
    .ad-inline a { display: block; border: 1px solid var(--hairline); border-radius: var(--radius);
      overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,.12); }
    .ad-inline img { display: block; width: 100%; height: auto; }
  }
</style>
</head>
<body>

<header class="site-nav">
  <div class="site-nav-inner">
    <span class="brand"><span class="dot"></span>DMO Tracker</span>
    <span class="nav-meta">scrape: gameking · KR · TH</span>
  </div>
</header>

<main class="page">

  <div class="hero">
    <div>
      <h1>ซีลแพทช์ TH · {{DATE}}</h1>
      <p class="lead">รายการแลกซีล (Seal Exchange List) เซิร์ฟไทย (vplay) ของแพทช์ {{DATE}} — {{LEAD_CAT}}</p>
    </div>
    <div class="hero-stats">
      <div class="hero-stat"><div class="num">{{N_TABLES}}</div><div class="lbl">หมวด</div></div>
      <div class="hero-stat"><div class="num">{{N_SEALS}}</div><div class="lbl">ซีล</div></div>{{HERO_NEW}}
      <div class="hero-stat"><div class="num">{{N_STATS}}</div><div class="lbl">Stat</div></div>
    </div>
  </div>

  <div class="patch-meta">
    <span class="pm"><span class="srv-th">TH</span></span>
    <span class="pm">📅 วันที่ <b>{{DATE}}</b></span>
    <span class="pm">🌐 {{SITE_URL}}</span>
    <span class="pm">{{PACK_NOTE}}</span>
  </div>

  <div id="calc-root"></div>

  <!-- mobile-only inline ad (footer) — src/href/label เซ็ตโดย js/ads.js -->
  <div class="ad-inline">
    <span class="ad-label" data-ad-label></span>
    <a data-ad-link href="#" target="_blank" rel="noopener noreferrer">
      <img data-ad-img src="" alt="โฆษณา" loading="lazy" width="1080" height="1080">
    </a>
  </div>

</main>

<!-- desktop floating ad (bottom-right) -->
<aside class="ad-float" id="ad-float">
  <div class="ad-head"><span class="ad-label" data-ad-label></span>
    <button class="ad-close" id="ad-close" type="button" title="ปิด" aria-label="ปิด">✕</button></div>
  <button class="ad-thumb" id="ad-thumb" type="button" aria-label="ขยายดูโฆษณา">
    <img data-ad-img src="" alt="โฆษณา" loading="lazy" width="1080" height="1080">
  </button>
</aside>

<!-- shared lightbox -->
<div class="ad-box" id="ad-box" role="dialog" aria-modal="true" aria-label="โฆษณา">
  <div class="ad-stage">
    <button class="ad-x" id="ad-x" type="button" title="ปิด" aria-label="ปิด">✕</button>
    <a class="ad-link" data-ad-link href="#" target="_blank" rel="noopener noreferrer">
      <img data-ad-img src="" alt="โฆษณา">
    </a>
    <a class="ad-cta" data-ad-link href="#" target="_blank" rel="noopener noreferrer">เปิดดูใน Facebook ↗</a>
  </div>
</div>

<script>
(() => {
  const PACK = 3000;
  const WANT_KEY = 'dmo_sealpatch_th{{N}}_want', PRICE_KEY = 'dmo_sealpatch_th{{N}}_price';

  // ── data: copied verbatim from seal_data.json by build_seal_patch_html.py ──
  // row = [name, e (ได้/ครั้ง), f (ตั๋ว/ครั้ง), stat, max]
{{TABLES_JS}}

  const root = document.getElementById('calc-root');
  const fmt = n => n.toLocaleString('en-US');
  const fmt2 = n => n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});

  const jget = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } };
  let want = jget(WANT_KEY, {});
  const saveWant = () => localStorage.setItem(WANT_KEY, JSON.stringify(want));
  let price = jget(PRICE_KEY, {});                  // per-table price/pack, keyed by table key
  const savePrice = () => localStorage.setItem(PRICE_KEY, JSON.stringify(price));
  const filterState = {};

  const ticketsFor = (w, e, f) => (w > 0 && e > 0) ? Math.ceil(w / e) * f : 0;
  // status gained from owning `w` seals: in-game step tiers × the seal's max stat
  const STAT_TIERS = [[3000, 1], [1000, 0.8], [500, 0.6], [200, 0.4], [50, 0.2], [1, 0.1]];
  const statFracFor = w => { for (const [n, f] of STAT_TIERS) if (w >= n) return f; return 0; };
  const statGained = (w, max) => max > 0 ? Math.round(max * statFracFor(w)) : 0;
  // CT/BL/EV are percentage stats: table value is value×100 → show (value/100) with %
  const PCT_STATS = new Set(['CT', 'BL', 'EV']);
  const fmtStat = (stat, v) => PCT_STATS.has(stat) ? (v / 100).toFixed(2) + '%' : fmt(v);
  const STAT_ORDER = ['AT', 'HT', 'CT', 'HP', 'DE', 'BL', 'EV', 'DS'];

  const applyFilter = card => {
    const sel = filterState[card.dataset.tkey];
    card.querySelectorAll('tr[data-seal]').forEach(tr =>
      tr.style.display = (!sel || !sel.size || sel.has(tr.dataset.stat)) ? '' : 'none');
  };

  function recalc() {
    document.querySelectorAll('.calc-card').forEach(card => {
      let sub = 0;
      const statTot = {};
      card.querySelectorAll('tr[data-seal]').forEach(tr => {
        if (tr.style.display === 'none') return;
        const w = parseInt(tr.querySelector('input.want').value, 10) || 0;
        const tk = ticketsFor(w, +tr.dataset.e, +tr.dataset.f);
        tr.querySelector('.tk').textContent = tk ? fmt(tk) : '–'; sub += tk;
        const got = statGained(w, +tr.dataset.max);
        const gotEl = tr.querySelector('.status .got');
        if (gotEl) gotEl.textContent = got ? fmtStat(tr.dataset.stat, got) : '0';
        if (got) statTot[tr.dataset.stat] = (statTot[tr.dataset.stat] || 0) + got;
      });
      const price = +card.querySelector('.price-pack').value || 0;
      card.querySelector('.sub .tk').textContent = fmt(sub);
      card.querySelector('.tot-tickets').textContent = fmt(sub);
      card.querySelector('.tot-packs').textContent = fmt2(sub / PACK);
      card.querySelector('.tot-price').textContent = fmt2(sub / PACK * price);
      const statsEl = card.querySelector('.tot-stats');
      if (statsEl) statsEl.innerHTML = STAT_ORDER.map(s =>
        `<span class="st"><span class="k">${s}</span><span class="n">${fmtStat(s, statTot[s] || 0)}</span></span>`).join('');
    });
  }

  function render() {
    root.innerHTML = '';
    TABLES.forEach(t => {
      const k = t.key, rows = t.rows;
      const statsList = [...new Set(rows.map(r => r[3]).filter(s => s && s !== '—'))];
      const chips = statsList.map(s => `<button class="calc-chip" data-stat="${s}" type="button">${s}</button>`).join('');
      const newSet = new Set(t.newSeals || []);
      const rowsHtml = rows.map(r => {
        const name = r[0], ne = name.replace(/"/g, '&quot;'), saved = (want[k] && want[k][name]) || '';
        const statusCell = t.noStats ? '' :
          `<td class="status"><span class="got">0</span>/<span class="mx">${r[4] ? fmtStat(r[3], +r[4]) : '–'}</span></td>`;
        const newTag = newSet.has(name)
          ? ' <span class="seal-new" title="ซีลชนิดใหม่ที่เพิ่มในแพทช์นี้">🆕</span>' : '';
        return `<tr data-seal="${ne}" data-e="${r[1]}" data-f="${r[2]}" data-stat="${r[3]}" data-max="${r[4] || 0}">
          <td>${name}${newTag}</td><td>${r[3]}</td><td>${r[1]}</td><td>${r[2]}</td>
          <td><input class="want" type="number" min="0" step="1" value="${saved}"></td>
          <td class="tk">–</td>${statusCell}</tr>`;
      }).join('');
      const card = document.createElement('div');
      card.className = 'calc-card'; card.dataset.tkey = k;
      card.innerHTML = `
        <div class="calc-card-head"><span class="calc-srv">TH</span>
          <span class="dt">${t.date}</span><span class="cap">${t.caption}</span>
          <span class="head-btns">
            <button class="set-master" type="button">ตั้งทุกแถว = 3000 (ถึง Master)</button>
            <button class="clear-want" type="button">ล้างค่าที่กรอก</button></span></div>
        ${statsList.length > 1 ? `<div class="calc-filter"><span class="lbl">Stat:</span>${chips}</div>` : ''}
        <div class="calc-total">
          <div class="ct-row"><span class="t">🎟️ รวมตั๋วที่ใช้ (หมวดนี้)</span><span class="vw"><span class="v tot-tickets">0</span><span class="u">ใบ</span></span></div>
          <div class="ct-row"><span class="t">📦 คิดเป็น</span><span class="vw"><span class="v tot-packs">0</span><span class="u">แพ็ค</span></span></div>
          <div class="ct-row ct-pricein"><span class="t">🏷️ ราคา/แพ็ค (หมวดนี้)</span><span class="vw"><input class="price-pack" type="number" min="0" step="1" value="${price[k] ?? 0}"><span class="u">฿</span></span></div>
          <div class="ct-row ct-price"><span class="t">💵 ราคารวม</span><span class="vw"><span class="v tot-price">0</span><span class="u">฿</span></span></div>
          ${t.noStats ? '' : '<div class="ct-stats tot-stats"></div>'}
        </div>
        <div class="calc-tbl-wrap"><table class="calc-tbl">
          <tr><th>ซีล</th><th>Stat</th><th>ได้/ครั้ง</th><th>ตั๋ว/ครั้ง</th><th>ต้องการ</th><th>ใช้ตั๋ว</th>${t.noStats ? '' : '<th>Status (ได้/สูงสุด)</th>'}</tr>
          ${rowsHtml}
          <tr class="sub"><td colspan="5">รวมตั๋วตารางนี้</td><td class="tk">0</td>${t.noStats ? '' : '<td>ดู Status แยกตาม Stat ด้านบน ↑</td>'}</tr>
        </table></div>`;
      card.querySelectorAll('.calc-chip').forEach(chip => chip.addEventListener('click', () => {
        const set = filterState[k] = filterState[k] || new Set(); const s = chip.dataset.stat;
        if (set.has(s)) { set.delete(s); chip.classList.remove('on'); } else { set.add(s); chip.classList.add('on'); }
        applyFilter(card); recalc();
      }));
      card.querySelectorAll('input.want').forEach(inp => inp.addEventListener('input', () => {
        const name = inp.closest('tr').dataset.seal; want[k] = want[k] || {};
        if (inp.value === '') delete want[k][name]; else want[k][name] = inp.value;
        saveWant(); recalc();
      }));
      card.querySelector('.set-master').addEventListener('click', () => {
        want[k] = want[k] || {};
        card.querySelectorAll('tr[data-seal]').forEach(tr => {
          if (tr.style.display === 'none') return;
          tr.querySelector('input.want').value = 3000; want[k][tr.dataset.seal] = '3000';
        });
        saveWant(); recalc();
      });
      card.querySelector('.clear-want').addEventListener('click', () => {
        delete want[k]; saveWant();
        card.querySelectorAll('input.want').forEach(i => i.value = ''); recalc();
      });
      root.appendChild(card);
      applyFilter(card);
    });
    recalc();
  }

  render();
})();
</script>
<script src="js/ads.js"></script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
