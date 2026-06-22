"""Generate docs/digimon.html from scan_result_digimon.json.

Re-run after scan_digimon.py to refresh the published Digimon report.

Output layout is a chronological activity feed: posts are grouped by
month (newest first), each rendered as a card hanging off a vertical
timeline rail. Visual language is shared across all docs/ pages via
the external stylesheet at css/site.css.
"""

import json
import re
import sys
import urllib.parse
from collections import OrderedDict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "data" / "scan_result_digimon.json"
KR_INDEX = PROJ / "data" / "kr_news_index.json"
OUT = PROJ / "docs" / "digimon.html"


MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def fmt_date(mmddyyyy: str | None) -> str:
    """MM-DD-YYYY → DD.MM.YYYY (matches deck report convention)."""
    if not mmddyyyy:
        return ""
    mm, dd, yyyy = mmddyyyy.split("-")
    return f"{dd}.{mm}.{yyyy}"


def fmt_iso_date(iso: str | None) -> str:
    """YYYY-MM-DD → DD.MM.YYYY."""
    if not iso:
        return ""
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def date_key(mmddyyyy: str | None) -> str:
    """MM-DD-YYYY → YYYYMMDD for sorting; missing dates sink to bottom."""
    if not mmddyyyy:
        return "00000000"
    mm, dd, yyyy = mmddyyyy.split("-")
    return f"{yyyy}{mm}{dd}"


def month_key(mmddyyyy: str | None) -> str:
    """MM-DD-YYYY → YYYYMM for grouping (empty → 000000)."""
    if not mmddyyyy:
        return "000000"
    mm, _dd, yyyy = mmddyyyy.split("-")
    return f"{yyyy}{mm}"


def month_label(ym: str) -> str:
    """YYYYMM → 'May 2026'. Returns 'Unknown' for 000000."""
    if ym == "000000":
        return "Unknown date"
    return f"{MONTH_NAMES[int(ym[4:6]) - 1]} {ym[:4]}"


def _link_text(url: str, kind: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    if kind == "th":
        m = re.search(r"(patch|รายละเอียดการอัพเดท)?-?(\d+)$", urllib.parse.unquote(slug))
        if m and m.group(2):
            return f"patch -{m.group(2)}"
        return urllib.parse.unquote(slug)
    return slug


def canonical_src_key(url: str) -> tuple[str, str]:
    if "digimonmasters.com" in url:
        m = re.search(r"[?&]o=(\d+)", url)
        return ("kr", m.group(1) if m else url)
    if "gameking.com" in url:
        m = re.search(r"[?&]idx=(\d+)", url)
        return ("na", m.group(1) if m else url)
    if "vplay.in.th" in url:
        return ("th", url.rstrip("/").rsplit("/", 1)[-1])
    return ("other", url)


ATTR_ABBR_MAP = {"Vaccine": "VA", "Virus": "VI", "Data": "DA", "Free": "FR", "Unknown": "UN"}

ELEM_ICON = {
    "Light": "Light",
    "Fire": "Fire",
    "Water": "Water",
    "Wind": "Wind",
    "Wood": "Wood",
    "Earth": "Earth",
    "Steel": "Steel",
    "Thunder": "Thunder",
    "Ice": "Ice",
    "Neutral": "Neutral",
    "Pitch Black": "Pitch_Black",
}
# Full Natural-Attribute set, shown in the filter even when no digimon has
# that element yet (ordered by element, not by what's present in the data).
ELEM_ORDER = [
    "Fire",
    "Water",
    "Ice",
    "Wind",
    "Wood",
    "Earth",
    "Steel",
    "Thunder",
    "Light",
    "Pitch Black",
    "Neutral",
]
FAMILY_ICON = {
    "Virus Busters": "Virus_Busters",
    "Wind Guardians": "Wind_Guardians",
    "Nightmare Soldiers": "Nightmare_Soldiers",
    "Jungle Troopers": "Jungle_Troopers",
    "Nature Spirits": "Nature_Spirits",
    "Deep Savers": "Deep_Savers",
    "Metal Empire": "Metal_Empire",
    "Dragon's Roar": "Dragons_Roar",
    "Unknown": "Unknown",
    "Dark Area": "Dark_Area",
    "TBD": "TBD",
}
# Full Families set, shown in the filter even when no digimon has that family
# yet. Real fields first (canonical order), placeholders (Unknown/TBD) last.
FAMILY_ORDER = [
    "Nature Spirits",
    "Deep Savers",
    "Nightmare Soldiers",
    "Wind Guardians",
    "Metal Empire",
    "Virus Busters",
    "Dragon's Roar",
    "Dark Area",
    "Jungle Troopers",
    "Unknown",
    "TBD",
]


def elem_slug(value: str) -> str:
    return ELEM_ICON.get(value, value.replace(" ", "_"))


def family_slug(value: str) -> str:
    return FAMILY_ICON.get(value, value.replace(" ", "_"))


def render_digimon(name: str, attrs: dict | None, show_name: bool = True) -> str:
    rows: list[str] = []
    if attrs:
        if attrs.get("attribute"):
            v = attrs["attribute"]
            rows.append(
                f'<div class="chips-row">'
                f'<span class="chips-label">Attribute</span>'
                f'<img class="chip-icon-only" src="img/icons/attr-{v}.png" '
                f'alt="{v}" title="{v}"></div>'
            )
        if attrs.get("natural_attribute"):
            v = attrs["natural_attribute"]
            rows.append(
                f'<div class="chips-row">'
                f'<span class="chips-label">Element</span>'
                f'<img class="chip-icon-only" src="img/icons/elem-{elem_slug(v)}.png" '
                f'alt="{v}" title="{v}"></div>'
            )
        if attrs.get("families"):
            fam_icons = "".join(
                f'<img class="chip-icon-only" src="img/icons/field-{family_slug(f)}.png" '
                f'alt="{f}" title="{f}">'
                for f in attrs["families"]
            )
            src_links = "".join(
                f'<a class="rebalance-src" href="{s["url"]}" target="_blank" '
                f'title="Families updated in {s["kind"]}_{s["idx"]}">'
                f"updated&nbsp;{s['kind'][0]}{s['idx']}</a>"
                for s in attrs.get("rebalance_sources", [])
            )
            rows.append(
                f'<div class="chips-row">'
                f'<span class="chips-label">Families</span>{fam_icons}{src_links}</div>'
            )

    chip_block = "".join(rows)
    name_html = f'<span class="digimon-name">{name}</span>' if show_name else ""
    return f"{name_html}{chip_block}" or "&nbsp;"


def render() -> str:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    events = data.get("event", {})
    patches = data.get("patch", {})

    kr_dates: dict[str, str] = {}
    if KR_INDEX.exists():
        for p in json.loads(KR_INDEX.read_text(encoding="utf-8"))["posts"]:
            kr_dates[p["o"]] = p["date"]

    total_posts = len(events) + len(patches)
    total_digimon = sum(len(p["digimon"]) for p in list(events.values()) + list(patches.values()))

    # Build merged list, sorted by gameking date DESCENDING (newest first
    # — activity-feed convention). Tie-break by idx desc so same-day posts
    # are also stable.
    merged: list[tuple[str, str, dict]] = sorted(
        [("event", idx, p) for idx, p in events.items()]
        + [("patch", idx, p) for idx, p in patches.items()],
        key=lambda t: (date_key(t[2].get("date")), int(t[1])),
        reverse=True,
    )

    # Group by month
    by_month: OrderedDict[str, list[tuple[str, str, dict]]] = OrderedDict()
    for kind, idx, p in merged:
        ym = month_key(p.get("date"))
        by_month.setdefault(ym, []).append((kind, idx, p))

    # --- Source links --------------------------------------------------
    def render_sources(p: dict) -> str:
        seen: set[tuple[str, str]] = set()
        parts: list[str] = []
        for u in (p.get("source"), p.get("source_kr"), p.get("source_th")):
            if not u:
                continue
            kind, oid = canonical_src_key(u)
            if (kind, oid) in seen:
                continue
            seen.add((kind, oid))
            cls = {"kr": "is-kr", "th": "is-th", "na": "is-na"}.get(kind, "is-na")
            label = {"kr": "KR", "th": "TH", "na": "NA"}.get(kind, "?")
            if kind == "kr":
                date_str = fmt_iso_date(kr_dates.get(oid))
            elif kind == "th":
                date_str = fmt_iso_date(p.get("date_th"))
            else:
                date_str = fmt_date(p["date"])
            parts.append(
                f'<span class="src-item {cls}">'
                f'<a class="src-label" href="{u}" target="_blank" '
                f'title="{_link_text(u, kind)}">{label}</a>'
                f'<span class="src-date">{date_str}</span>'
                f"</span>"
            )
        return "".join(parts)

    # --- One entry card ------------------------------------------------
    def render_entry(idx: str, p: dict, kind: str) -> str:
        prefix = "e" if kind == "event" else "p"
        names = p["digimon"]
        n = len(names)
        attrs_map = p.get("attributes", {})
        h2_text = ", ".join(names)

        items = "\n        ".join(
            f"<li>{render_digimon(name, attrs_map.get(name), show_name=(n > 1))}</li>"
            for name in names
        )
        img_path = p.get("image_th") or p.get("image") or p.get("image_kr")
        img_block = (
            f'<a href="{img_path}" target="_blank">'
            f'<img class="card-image" src="{img_path}" alt="idx {idx}" loading="lazy">'
            f"</a>"
            if img_path
            else ""
        )

        all_attrs = sorted({a.get("attribute") for a in attrs_map.values() if a.get("attribute")})
        all_elems = sorted(
            {a.get("natural_attribute") for a in attrs_map.values() if a.get("natural_attribute")}
        )
        all_fams = sorted({f for a in attrs_map.values() for f in a.get("families", [])})

        return f"""        <article class="card tl-entry" id="{prefix}{idx}"
                 data-attr="{",".join(all_attrs)}"
                 data-elem="{",".join(all_elems)}"
                 data-family="{",".join(all_fams)}">
          <h2 class="card-title">{h2_text}</h2>
          <div class="sources">{render_sources(p)}</div>
          <div class="card-body">
            {img_block}
            <ul class="digimon-list">
              {items}
            </ul>
          </div>
        </article>"""

    # --- Timeline body -------------------------------------------------
    timeline_blocks: list[str] = []
    for ym, entries in by_month.items():
        cards = "\n".join(render_entry(idx, p, kind) for kind, idx, p in entries)
        timeline_blocks.append(
            f"""      <div class="tl-month">
        <span class="tl-month-label">{month_label(ym)}</span>
        <span class="tl-month-count">{len(entries)} post{"" if len(entries) == 1 else "s"}</span>
      </div>
{cards}"""
        )
    timeline_html = "\n".join(timeline_blocks)

    # --- Filter bar ----------------------------------------------------
    all_posts = list(events.values()) + list(patches.values())
    seen_attrs: list[str] = []
    seen_elems: list[str] = []
    seen_fams: list[str] = []
    for p in all_posts:
        for a in p.get("attributes", {}).values():
            if a.get("attribute") and a["attribute"] not in seen_attrs:
                seen_attrs.append(a["attribute"])
            if a.get("natural_attribute") and a["natural_attribute"] not in seen_elems:
                seen_elems.append(a["natural_attribute"])
            for f in a.get("families", []):
                if f not in seen_fams:
                    seen_fams.append(f)
    attr_order = ["Vaccine", "Virus", "Data", "Free", "Unknown"]
    seen_attrs.sort(key=lambda x: (attr_order.index(x) if x in attr_order else 999, x))
    seen_elems.sort()
    seen_fams.sort()

    def filter_pill(category: str, value: str, slug: str, cls: str, icon_dir: str) -> str:
        return (
            f'<button class="filter-pill {cls}" '
            f'data-filter="{category}" data-value="{value}">'
            f'<img src="img/icons/{icon_dir}-{slug}.png" alt="">{value}</button>'
        )

    attr_pills = "".join(
        filter_pill("attr", v, v, f"chip-attr-{ATTR_ABBR_MAP.get(v, 'UN')}", "attr")
        for v in seen_attrs
    )
    # Show every Natural Attribute, including ones no digimon currently has,
    # plus any data element not in the canonical order (future-proofing).
    elem_values = ELEM_ORDER + [e for e in seen_elems if e not in ELEM_ORDER]
    elem_pills = "".join(
        filter_pill("elem", v, elem_slug(v), "chip-elem", "elem") for v in elem_values
    )
    fam_values = FAMILY_ORDER + [f for f in seen_fams if f not in FAMILY_ORDER]
    fam_pills = "".join(
        filter_pill("family", v, family_slug(v), "chip-families", "field") for v in fam_values
    )

    filter_bar = f"""<div class="filter-bar">
    <h4>Basic Attribute</h4>
    <div class="filter-group">{attr_pills}</div>
    <h4>Natural Attribute</h4>
    <div class="filter-group">{elem_pills}</div>
    <h4>Families <span class="hint">(เลือกได้หลายอัน — match ทุกอัน)</span></h4>
    <div class="filter-group">{fam_pills}<button class="filter-reset" id="filter-reset">reset</button><span class="filter-count" id="filter-count"></span></div>
  </div>"""

    filter_js = """<script>
(() => {
  const state = {attr: null, elem: null, family: new Set()};
  const pills = document.querySelectorAll('.filter-pill');
  const cards = document.querySelectorAll('.tl-entry');
  const months = document.querySelectorAll('.tl-month');
  const countEl = document.getElementById('filter-count');

  function apply() {
    let visible = 0;
    cards.forEach(c => {
      const a = (c.dataset.attr   || '').split(',');
      const e = (c.dataset.elem   || '').split(',');
      const f = (c.dataset.family || '').split(',');
      let show = true;
      if (state.attr && !a.includes(state.attr)) show = false;
      if (state.elem && !e.includes(state.elem)) show = false;
      if (state.family.size) {
        for (const wanted of state.family) {
          if (!f.includes(wanted)) { show = false; break; }
        }
      }
      c.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    // Hide month headers whose entries are all filtered out
    months.forEach(m => {
      let next = m.nextElementSibling;
      let any = false;
      while (next && !next.matches('.tl-month')) {
        if (next.matches('.tl-entry') && next.style.display !== 'none') { any = true; break; }
        next = next.nextElementSibling;
      }
      m.style.display = any ? '' : 'none';
    });
    const active = [state.attr, state.elem, ...state.family].filter(Boolean);
    countEl.textContent = active.length
      ? `${visible} โพสต์ ตรงตาม ${active.join(' + ')}`
      : '';
  }

  pills.forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.filter;
      const val = btn.dataset.value;
      if (key === 'family') {
        if (state.family.has(val)) { state.family.delete(val); btn.classList.remove('active'); }
        else { state.family.add(val); btn.classList.add('active'); }
      } else {
        if (state[key] === val) { state[key] = null; btn.classList.remove('active'); }
        else {
          document.querySelectorAll(`.filter-pill[data-filter="${key}"]`)
            .forEach(b => b.classList.remove('active'));
          state[key] = val; btn.classList.add('active');
        }
      }
      apply();
    });
  });

  document.getElementById('filter-reset').addEventListener('click', () => {
    state.attr = null; state.elem = null; state.family.clear();
    pills.forEach(b => b.classList.remove('active'));
    apply();
  });
})();
</script>"""

    return f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>DMO Digimon — Activity Feed</title>
<script src="js/theme.js"></script>
<link rel="stylesheet" href="css/site.css">
</head>
<body>

<header class="site-nav">
  <div class="site-nav-inner">
    <a class="brand" href="./"><span class="dot"></span>DMO Tracker</a>
    <nav>
      <a href="./">Home</a>
      <a href="decks.html">Decks</a>
      <a href="digimon.html" class="is-active">Digimon</a>
      <a href="seals.html">Seal</a>
      <a href="breakthrough.html">Breakthrough</a>
    </nav>
    <span class="nav-meta">scrape: dmo.gameking.com</span>
  </div>
</header>

<main class="page">

  <section>
    <div class="hero">
      <div>
        <h1>Digimon Activity Feed</h1>
        <p class="lead">Digimon ใหม่ที่ถูกเพิ่ม — เรียงตามเดือนของ NA release</p>
      </div>
      <div class="hero-stats">
        <div class="hero-stat"><div class="num">{total_posts}</div><div class="lbl">โพสต์</div></div>
        <div class="hero-stat"><div class="num">{total_digimon}</div><div class="lbl">digimon</div></div>
        <div class="hero-stat"><div class="num">{len(by_month)}</div><div class="lbl">เดือน</div></div>
      </div>
    </div>

    {filter_bar}

    <div class="timeline">
{timeline_html}
    </div>

  </section>
</main>

<footer class="site-footer">
  Built by <a href="https://github.com/kongpop1405" target="_blank">@kongpop1405</a>
  &nbsp;·&nbsp; Generated with <a href="https://claude.ai/" target="_blank">Claude AI</a>
  &nbsp;·&nbsp; <a href="https://github.com/dmo-hub/dmo" target="_blank">Source on GitHub</a>
  &nbsp;·&nbsp; <a href="styleguide.html">Style Guide</a>
</footer>

{filter_js}
</body>
</html>
"""


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(PROJ)}")


if __name__ == "__main__":
    main()
