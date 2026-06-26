"""Build docs/nametag.html — NA Name-Tag-set item × patch matrix.

Reads data/na_nametag_items.json (produced by scanners/scan_na_nametag.py) and
renders a matrix: each NA update splits into one sub-row per obtain-source
(Box/Drop, Package, Exchange, Craft); columns = the tracked Name-Tag items,
cells = total amount from that source (— if absent). Filtered to updates that
grant BOTH Equipment Data: Name Tag AND Name Tag Enhancement Backup Chip.
Shares docs/css/site.css + .site-nav markup.

    python builders/build_nametag_html.py
"""

import html as _html
import json
import re
from datetime import date
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DATA = PROJ / "data" / "na_nametag_items.json"
OUT = PROJ / "docs" / "nametag.html"

# column groups -> (canonical item, short header). Group header spans its cols.
GROUPS = [
    ("Enhancement", [
        ("Name Tag Enhancement Hacking Tool", "Hacking Tool"),
        ("Name Tag Enhancement Backup Chip", "Backup Chip"),
    ]),
    ("Reinforcement", [
        ("Name Tag Reinforcement Hacking Tool", "Hacking Tool"),
        ("Name Tag Reinforcement Backup Chip", "Backup Chip"),
    ]),
    ("Equipment", [
        ("Equipment Data: Name Tag", "Data: Name Tag"),
    ]),
]
COLS = [(canon, short) for _g, cols in GROUPS for canon, short in cols]


def esc(s):
    return _html.escape(str(s), quote=True)


def parse_date(post):
    # primary: listing reg_date as MM-DD-YYYY
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", post.get("date", ""))
    if m:
        mm, dd, yy = map(int, m.groups())
        try:
            return date(yy, mm, dd)
        except ValueError:
            pass
    # fallback (cache mode): subject "D.M.YYYY Update"
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", post.get("subject", ""))
    if m:
        dd, mm, yy = map(int, m.groups())
        try:
            return date(yy, mm, dd)
        except ValueError:
            pass
    return date.min


def cell_total(entries):
    tot = 0
    for e in entries:
        m = re.search(r"\d+", e.get("amount", "") or "")
        if m:
            tot += int(m.group())
    return tot


# obtain-source display order + Thai label
SOURCES = [
    ("box", "Box / Drop"),
    ("package", "Package (ขาย)"),
    ("summon", "Summon (กาชา)"),
    ("exchange", "Exchange (แลก)"),
    ("craft", "Craft"),
]


def post_sources(p):
    """Sources present in a post, in SOURCES order, with per-item totals.

    Returns [(src_key, src_label, {canon: total})] for sources that grant at
    least one tracked item.
    """
    out = []
    for key, label in SOURCES:
        per_item = {}
        for canon, _short in COLS:
            ents = [e for e in p["items"].get(canon, []) if e.get("source") == key]
            if ents:
                per_item[canon] = cell_total(ents)
        if per_item:
            out.append((key, label, per_item))
    return out


# only show updates that grant BOTH of these items
REQUIRE_BOTH = {"Equipment Data: Name Tag", "Name Tag Enhancement Backup Chip"}


def render():
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    all_posts = sorted(payload["posts"], key=parse_date, reverse=True)
    full = [p for p in all_posts if REQUIRE_BOTH <= set(p["items"])]
    partial = [p for p in all_posts if not (REQUIRE_BOTH <= set(p["items"]))]

    n_patch = sum(1 for p in all_posts if p["kind"] == "patch")
    n_event = sum(1 for p in all_posts if p["kind"] == "event")
    span = "—"
    dates = [parse_date(p) for p in all_posts if parse_date(p) != date.min]
    if dates:
        span = f"{min(dates):%b %Y} – {max(dates):%b %Y}"

    ncols_total = len(COLS) + 2  # update + source + items

    def matrix_rows(p):
        upd = esc(p["subject"].replace(" Update", "").strip() or p["date"])
        kb = f'<span class="nt-kind nt-kind-{p["kind"]}">{p["kind"].upper()}</span>'
        srcs = post_sources(p)
        upd_th = (
            f'<th scope="row" rowspan="{len(srcs)}" class="nt-upd">'
            f'{kb}<span>{upd}</span>'
            f'<a class="nt-src-link" href="{esc(p["url"])}" target="_blank" '
            f'rel="noopener">post ↗</a></th>'
        )
        out = []
        for si, (skey, slabel, per_item) in enumerate(srcs):
            cells = [f'<td class="nt-srccol nt-src-{skey}">{esc(slabel)}</td>']
            for canon, _short in COLS:
                if canon in per_item:
                    cells.append(f'<td class="nt-has">{per_item[canon]}</td>')
                else:
                    cells.append('<td class="nt-none">—</td>')
            lead = upd_th if si == 0 else ""
            border = " nt-post-top" if si == 0 else ""
            out.append(f'<tr class="nt-row{border}">{lead}{"".join(cells)}</tr>')
        return out

    def matrix_grp(text):
        return (
            f'<tr class="nt-ref-grp nt-post-top"><td colspan="{ncols_total}">'
            f"{esc(text)}</td></tr>"
        )

    rows_list = [matrix_grp(f"ครบทั้ง 2 item ({len(full)} แพท)")]
    for p in full:
        rows_list += matrix_rows(p)
    if partial:
        rows_list.append(matrix_grp(f"พูดถึงบางส่วน — ไม่ครบ 2 item ({len(partial)} แพท)"))
        for p in partial:
            rows_list += matrix_rows(p)
    rows = "\n".join(rows_list)

    # reference table — one row per post: where each key item is mentioned +
    # the source link to the gameking post. Covers ALL scanned posts, split
    # into "ครบทั้ง 2" (passes the filter) and "พูดถึงบางส่วน" (mentions a Name
    # Tag item but not both required ones).
    KEY_ITEMS = [
        ("Equipment Data: Name Tag", "Equip. Data: Name Tag"),
        ("Name Tag Enhancement Backup Chip", "Enh. Backup Chip"),
    ]
    labels = {k: lbl for k, lbl in SOURCES}

    def ref_row(p):
        upd = esc(p["subject"].replace(" Update", "").strip() or p["date"])
        kb = f'<span class="nt-kind nt-kind-{p["kind"]}">{p["kind"].upper()}</span>'
        cells = []
        for canon, _short in KEY_ITEMS:
            srcs_for = sorted({e.get("source", "box") for e in p["items"].get(canon, [])})
            if srcs_for:
                tags = " ".join(
                    f'<span class="nt-srctag nt-src-{s}">{esc(labels.get(s, s))}</span>'
                    for s in srcs_for
                )
                cells.append(f'<td class="nt-ref-yes">{tags}</td>')
            else:
                cells.append('<td class="nt-none">—</td>')
        return (
            f'<tr><td class="nt-ref-upd">{kb}<span>{upd}</span></td>'
            + "".join(cells)
            + f'<td class="nt-ref-link"><a href="{esc(p["url"])}" target="_blank" '
            f'rel="noopener">{esc(p["url"].split("//")[-1])} ↗</a></td></tr>'
        )

    ncol = len(KEY_ITEMS) + 2

    def group_header(text):
        return f'<tr class="nt-ref-grp"><td colspan="{ncol}">{esc(text)}</td></tr>'

    ref_parts = [group_header(f"ครบทั้ง 2 item ({len(full)} แพท — แสดงในตารางบน)")]
    ref_parts += [ref_row(p) for p in full]
    if partial:
        ref_parts.append(
            group_header(f"พูดถึงบางส่วน — ไม่ครบ 2 item ({len(partial)} แพท)")
        )
        ref_parts += [ref_row(p) for p in partial]
    ref_rows = "\n".join(ref_parts)
    ref_thead = (
        "<tr><th>NA Update</th>"
        + "".join(f"<th>{esc(s)}</th>" for _c, s in KEY_ITEMS)
        + "<th>แหล่งอ้างอิง (gameking post)</th></tr>"
    )

    # two-row head: group spanners + per-item labels (Update + Source pinned)
    group_cells = (
        '<th rowspan="2" class="nt-upd-h">NA Update</th>'
        '<th rowspan="2" class="nt-srccol-h">Source</th>'
        + "".join(
            f'<th colspan="{len(cols)}" class="nt-grp">{esc(g)}</th>'
            for g, cols in GROUPS
        )
    )
    item_cells = "".join(f"<th>{esc(s)}</th>" for _c, s in COLS)
    thead = f"<tr>{group_cells}</tr><tr>{item_cells}</tr>"

    return TEMPLATE.format(
        n_posts=len(all_posts),
        n_patch=n_patch,
        n_event=n_event,
        span=esc(span),
        thead=thead,
        rows=rows,
        ref_thead=ref_thead,
        ref_rows=ref_rows,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DMO Name Tag Items — NA Patch Matrix</title>
<script src="js/theme.js"></script>
<link rel="stylesheet" href="css/site.css">
<style>
  .nt-wrap {{ overflow-x: auto; border: 1px solid var(--hairline);
    border-radius: var(--radius); background: var(--canvas); margin-top: 6px; }}
  table.nt {{ border-collapse: collapse; width: 100%; font-size: 13px;
    min-width: 640px; font-variant-numeric: tabular-nums; }}
  table.nt th, table.nt td {{ padding: 8px 12px; text-align: center;
    border-bottom: 1px solid var(--hairline); white-space: nowrap; }}
  table.nt thead th {{ background: var(--surface-card); color: var(--ink);
    font-weight: 600; position: sticky; top: 0; }}
  table.nt thead .nt-grp {{ border-bottom: 1px solid var(--hairline);
    border-left: 1px solid var(--hairline); font-size: 11px;
    letter-spacing: .5px; text-transform: uppercase; color: var(--muted-soft); }}
  .nt-upd-h, .nt-upd {{ text-align: left !important; }}
  .nt-upd {{ display: flex; align-items: center; gap: 8px; font-weight: 600; }}
  .nt-kind {{ font-size: 9.5px; font-weight: 700; letter-spacing: .5px;
    padding: 2px 7px; border-radius: 9999px; }}
  .nt-kind-patch {{ background: var(--coral); color: var(--on-primary); }}
  .nt-kind-event {{ background: var(--teal); color: var(--on-primary); }}
  .nt-src-link {{ font-size: 11px; font-weight: 500; color: var(--muted-soft);
    margin-left: auto; }}
  .nt-has {{ font-weight: 700; color: var(--ink); }}
  .nt-none {{ color: var(--muted-soft); }}
  /* source sub-row label cell */
  .nt-srccol, .nt-srccol-h {{ text-align: left !important; font-size: 12px;
    font-weight: 600; white-space: nowrap; }}
  .nt-srccol {{ border-left: 3px solid var(--hairline); }}
  .nt-src-box {{ border-left-color: var(--teal); }}
  .nt-src-package {{ border-left-color: var(--coral); }}
  .nt-src-summon {{ border-left-color: #c084fc; }}
  .nt-src-exchange {{ border-left-color: var(--accent, #6b7cff); }}
  .nt-src-craft {{ border-left-color: var(--muted-soft); }}
  /* group rows of one update with a top divider */
  .nt-post-top td, .nt-post-top th {{ border-top: 2px solid var(--hairline); }}
  .nt-upd {{ vertical-align: top; padding-top: 12px !important; }}
  /* reference table */
  table.nt-ref th, table.nt-ref td {{ text-align: left; white-space: normal; }}
  table.nt-ref .nt-ref-upd {{ display: flex; align-items: center; gap: 8px;
    font-weight: 600; white-space: nowrap; }}
  .nt-ref-yes {{ line-height: 1.9; }}
  .nt-ref-link a {{ font-size: 11.5px; color: var(--coral); word-break: break-all; }}
  .nt-srctag {{ display: inline-block; font-size: 10.5px; font-weight: 600;
    padding: 1px 8px; margin: 1px 2px; border-radius: 9999px;
    background: var(--surface-soft); border-left: 3px solid var(--hairline); }}
  tr.nt-ref-grp td {{ background: var(--surface-card); font-weight: 700;
    font-size: 11.5px; letter-spacing: .3px; color: var(--muted-soft);
    text-transform: uppercase; padding: 7px 12px; }}
</style>
</head>
<body>

<header class="site-nav">
  <div class="site-nav-inner">
    <a class="brand" href="./"><span class="dot"></span>DMO Tracker</a>
    <nav>
      <a href="./">Home</a>
      <a href="decks.html">Decks</a>
      <a href="digimon.html">Digimon</a>
      <a href="seals.html">Seal</a>
      <a href="breakthrough.html">Breakthrough</a>
      <a href="nametag.html" class="is-active">Name Tag</a>
    </nav>
    <span class="nav-meta">scrape: dmo.gameking.com</span>
  </div>
</header>

<main class="page">
  <section>
    <div class="hero">
      <div>
        <h1>Name Tag Items — NA Patch Matrix</h1>
        <p class="lead">แพท NA (gameking) ที่แจกของกลุ่ม Name Tag —
          กลุ่มแรกครบทั้ง 2 item, กลุ่มสองพูดถึงบางส่วน ·
          แยกแถวตามที่มา (Box/Drop · Package ขาย · Summon กาชา · Exchange แลก · Craft) ·
          ค่า = จำนวนรวมของที่มานั้น</p>
      </div>
      <div class="hero-stats">
        <div class="hero-stat"><div class="num">{n_posts}</div><div class="lbl">โพสต์</div></div>
        <div class="hero-stat"><div class="num">{n_patch}</div><div class="lbl">patch</div></div>
        <div class="hero-stat"><div class="num">{n_event}</div><div class="lbl">event</div></div>
      </div>
    </div>

    <div class="nt-wrap">
      <table class="nt">
        <thead>{thead}</thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </div>
    <p class="lead" style="margin-top:14px;font-size:12px">
      ช่วงเวลา: {span} · ที่มา: dmo.gameking.com PatchNote + EventView ·
      แสดงทุกแพทที่ scan เจอ Name Tag item — แยกกลุ่มครบ 2 / บางส่วน
    </p>
  </section>

  <section style="margin-top:34px">
    <h2 style="font-size:18px;margin:0 0 4px">แหล่งอ้างอิง (Reference Links)</h2>
    <p class="lead" style="font-size:12.5px;margin-bottom:10px">
      แพททั้งหมดที่ scan เจอ — กลุ่มแรกครบทั้ง 2 item (ตรงกับตารางบน)
      กลุ่มสองพูดถึงบางส่วน · พร้อมลิงก์ post ต้นทาง และที่มาของแต่ละ item
    </p>
    <div class="nt-wrap">
      <table class="nt nt-ref">
        <thead>{ref_thead}</thead>
        <tbody>
{ref_rows}
        </tbody>
      </table>
    </div>
  </section>
</main>

</body>
</html>
"""


def main():
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJ)}")


if __name__ == "__main__":
    main()
