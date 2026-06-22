"""Generate docs/index.html — the project hub.

Renders:
  - Hero with site-wide totals
  - Feature cards linking to decks / digimon / seal / breakthrough pages
    (seal + breakthrough counts are static — those pages aren't scan-driven)
  - Recent Activity feed (latest 8 items across both decks + digimon),
    timeline-grouped by month, so the landing page reads like a changelog.

Pulls from data/scan_result.json (decks) + data/scan_result_digimon.json
(digimon). Re-run after either scan refresh.
"""

import json
import sys
from collections import OrderedDict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
DECKS = PROJ / "data" / "scan_result.json"
DIGIMON = PROJ / "data" / "scan_result_digimon.json"
OUT = PROJ / "docs" / "index.html"

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


def date_key(mmddyyyy):
    if not mmddyyyy:
        return "00000000"
    mm, dd, yyyy = mmddyyyy.split("-")
    return f"{yyyy}{mm}{dd}"


def fmt_date(mmddyyyy):
    if not mmddyyyy:
        return ""
    mm, dd, yyyy = mmddyyyy.split("-")
    return f"{dd}.{mm}.{yyyy}"


def month_key(mmddyyyy):
    if not mmddyyyy:
        return "000000"
    mm, _dd, yyyy = mmddyyyy.split("-")
    return f"{yyyy}{mm}"


def month_label(ym):
    return f"{MONTH_NAMES[int(ym[4:6]) - 1]} {ym[:4]}"


def main() -> None:
    decks = json.loads(DECKS.read_text(encoding="utf-8"))
    digimon = json.loads(DIGIMON.read_text(encoding="utf-8"))

    # Build a unified activity list (newest first)
    activity: list[dict] = []
    for m in decks["matches"]:
        if not m.get("new_decks"):
            continue
        activity.append(
            {
                "kind_label": "Decks · " + ("EventView" if m["kind"] == "event" else "PatchNote"),
                "topic": "decks",
                "idx": m["idx"],
                "date": m["date"],
                "title": ", ".join(m["new_decks"][:2])
                + (f" + {len(m['new_decks']) - 2} more" if len(m["new_decks"]) > 2 else ""),
                "href": f"decks.html#{'e' if m['kind'] == 'event' else 'p'}{m['idx']}",
                "n_items": len(m["new_decks"]),
            }
        )
    for kind, posts in (("event", digimon.get("event", {})), ("patch", digimon.get("patch", {}))):
        for idx, p in posts.items():
            activity.append(
                {
                    "kind_label": "Digimon · " + ("EventView" if kind == "event" else "PatchNote"),
                    "topic": "digimon",
                    "idx": idx,
                    "date": p["date"],
                    "title": ", ".join(p["digimon"]),
                    "href": f"digimon.html#{'e' if kind == 'event' else 'p'}{idx}",
                    "n_items": len(p["digimon"]),
                }
            )

    activity.sort(key=lambda a: (date_key(a["date"]), int(a["idx"])), reverse=True)

    # Group most-recent 12 by month for the preview feed
    preview = activity[:12]
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for a in preview:
        grouped.setdefault(month_key(a["date"]), []).append(a)

    # --- Stats ----------------------------------------------------------
    deck_posts = decks.get("matched_posts", 0)
    deck_count = decks.get("new_deck_count", 0)
    digimon_posts = len(digimon.get("event", {})) + len(digimon.get("patch", {}))
    digimon_count = sum(
        len(p["digimon"])
        for p in list(digimon.get("event", {}).values()) + list(digimon.get("patch", {}).values())
    )
    total_activity = len(activity)

    # --- Activity feed render ------------------------------------------
    feed_blocks: list[str] = []
    for ym, items in grouped.items():
        cards = "\n".join(
            f'''        <a class="card tl-entry feed-card" href="{a["href"]}">
          <div class="card-head">
            <span class="card-date">{fmt_date(a["date"])}</span>
            <span class="card-kind-badge {"is-digimon" if a["topic"] == "digimon" else "is-decks"}">{a["kind_label"]}</span>
            <span class="card-idx">idx {a["idx"]}</span>
          </div>
          <div class="feed-title">{a["title"]}</div>
        </a>'''
            for a in items
        )
        feed_blocks.append(
            f"""      <div class="tl-month">
        <span class="tl-month-label">{month_label(ym)}</span>
        <span class="tl-month-count">{len(items)} update{"" if len(items) == 1 else "s"}</span>
      </div>
{cards}"""
        )
    feed_html = "\n".join(feed_blocks)

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>DMO Tracker — Home</title>
<script src="js/theme.js"></script>
<link rel="stylesheet" href="css/site.css">
<style>
  /* Index-only tweaks */
  .feed-card {{ display: block; padding-bottom: 14px; }}
  .feed-card .card-head {{ padding-top: 14px; }}
  .feed-card .feed-title {{
    margin: 6px 20px 8px; font-size: 16px; font-weight: 500; color: var(--ink);
    line-height: 1.4;
    font-family: var(--display-font);
    letter-spacing: -0.2px;
  }}
  .feed-card:hover {{ transform: translateY(-1px); border-color: var(--coral); }}
  .card-kind-badge.is-digimon {{ background: var(--surface-card); color: var(--ink); }}
  .card-kind-badge.is-decks {{ background: var(--coral); color: var(--on-primary); }}
</style>
</head>
<body>

<header class="site-nav">
  <div class="site-nav-inner">
    <a class="brand" href="./"><span class="dot"></span>DMO Tracker</a>
    <nav>
      <a href="./" class="is-active">Home</a>
      <a href="decks.html">Decks</a>
      <a href="digimon.html">Digimon</a>
      <a href="seals.html">Seal</a>
      <a href="breakthrough.html">Breakthrough</a>
    </nav>
    <span class="nav-meta">scrape: dmo.gameking.com</span>
  </div>
</header>

<main class="page">

  <div class="hero">
    <div>
      <h1>🎮 DMO Tracker</h1>
      <p class="lead">News tracking สำหรับ Digimon Masters Online — scrape จาก dmo.gameking.com อัตโนมัติ</p>
    </div>
    <div class="hero-stats">
      <div class="hero-stat"><div class="num">{deck_posts + digimon_posts}</div><div class="lbl">โพสต์</div></div>
      <div class="hero-stat"><div class="num">{deck_count}</div><div class="lbl">deck</div></div>
      <div class="hero-stat"><div class="num">{digimon_count}</div><div class="lbl">digimon</div></div>
    </div>
  </div>

  <div class="feature-grid">
    <a href="decks.html" class="feature">
      <div class="icon">📊</div>
      <h3>New Decks</h3>
      <p>Deck ใหม่ที่ถูกเพิ่มในเกม พร้อม Digimon List + Effect tables</p>
      <div class="feature-stats">
        <div class="stat"><b>{deck_posts}</b>โพสต์</div>
        <div class="stat"><b>{deck_count}</b>deck</div>
      </div>
    </a>

    <a href="digimon.html" class="feature">
      <div class="icon">🐉</div>
      <h3>New Digimon</h3>
      <p>Digimon ใหม่ที่ถูกเพิ่มในเกม (Mode evolution, Extreme forms)</p>
      <div class="feature-stats">
        <div class="stat"><b>{digimon_posts}</b>โพสต์</div>
        <div class="stat"><b>{digimon_count}</b>digimon</div>
      </div>
    </a>

    <a href="seals.html" class="feature">
      <div class="icon">🔁</div>
      <h3>Seal Exchange</h3>
      <p>กิจกรรม/ระบบแลกซีล (씰 교환 · แลกซีล) รวมทุกเซิร์ฟ NA · KR · TH</p>
      <div class="feature-stats">
        <div class="stat"><b>56</b>โพสต์</div>
        <div class="stat"><b>3</b>เซิร์ฟ</div>
      </div>
    </a>

    <a href="breakthrough.html" class="feature">
      <div class="icon">⚡</div>
      <h3>Breakthrough Sim</h3>
      <p>จำลองการตี Breakthrough (ตีสเตตัส) — ลองสุ่มดูค่าที่จะได้ภายใน 40 ครั้ง</p>
      <div class="feature-stats">
        <div class="stat"><b>40</b>attempts</div>
        <div class="stat"><b>75%</b>base rate</div>
      </div>
    </a>
  </div>

  <div class="section-header">
    <h2>Recent activity</h2>
    <span class="see-all">{total_activity} updates tracked</span>
  </div>

  <div class="timeline">
{feed_html}
  </div>

</main>

<footer class="site-footer">
  Built by <a href="https://github.com/kongpop1405" target="_blank">@kongpop1405</a>
  &nbsp;·&nbsp; Generated with <a href="https://claude.ai/" target="_blank">Claude AI</a>
  &nbsp;·&nbsp; <a href="https://github.com/dmo-hub/dmo" target="_blank">Source on GitHub</a>
  &nbsp;·&nbsp; <a href="styleguide.html">Style Guide</a>
</footer>

</body>
</html>
"""

    OUT.write_text(html, encoding="utf-8")
    print(
        f"Wrote {OUT.relative_to(PROJ)} — {total_activity} activity items, {len(preview)} in preview"
    )


if __name__ == "__main__":
    main()
