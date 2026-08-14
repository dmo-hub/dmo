"""Generate docs/index.html — the project hub.

Renders:
  - Hero with site-wide totals
  - Feature cards linking to every topic page (decks / digimon / seal /
    breakthrough / nametag / accessories / lookup — tool & item-DB counts
    are static, those pages aren't scan-driven)
  - Recent Activity feed (latest 12 items across decks + digimon + seal),
    timeline-grouped by month, so the landing page reads like a changelog.

Pulls from data/scan_result.json (decks) + data/scan_result_digimon.json
(digimon) + docs/seal_data.json (seal posts). Re-run after any refresh.
"""

import json
import sys
from collections import OrderedDict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
DECKS = PROJ / "data" / "scan_result.json"
DIGIMON = PROJ / "data" / "scan_result_digimon.json"
SEALS = PROJ / "docs" / "seal_data.json"
OUT = PROJ / "docs" / "index.html"

def date_key(mmddyyyy):
    if not mmddyyyy:
        return "00000000"
    mm, dd, yyyy = mmddyyyy.split("-")
    return f"{yyyy}{mm}{dd}"


SERVER_LABEL = {"na": "NA", "kr": "KR", "th": "TH"}


def seal_posts(seal_data):
    """Collapse seal_data.json table keys (kr-814935#0, #1, …) to one entry
    per post: {id, server, date (MM-DD-YYYY to match scan dates), caption}."""
    posts: OrderedDict[str, dict] = OrderedDict()
    for key, tbl in seal_data.items():
        post_id = key.split("#")[0]
        if post_id in posts:
            continue
        dd, mm, yyyy = (tbl.get("date") or "01.01.2000").split(".")
        posts[post_id] = {
            "id": post_id,
            "server": tbl.get("server", ""),
            "date": f"{mm}-{dd}-{yyyy}",
            "caption": tbl.get("caption", "Seal Exchange"),
        }
    return list(posts.values())


def main() -> None:
    decks = json.loads(DECKS.read_text(encoding="utf-8"))
    digimon = json.loads(DIGIMON.read_text(encoding="utf-8"))
    seals = seal_posts(json.loads(SEALS.read_text(encoding="utf-8")))

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

    for s in seals:
        activity.append(
            {
                "kind_label": f"Seal · {SERVER_LABEL.get(s['server'], s['server'].upper())}",
                "topic": "seal",
                "idx": s["id"],
                "date": s["date"],
                "title": s["caption"],
                "href": f"seals.html#{s['id']}",
                "n_items": 1,
            }
        )

    def idx_key(v):
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        return int(digits) if digits else 0

    activity.sort(key=lambda a: (date_key(a["date"]), idx_key(a["idx"])), reverse=True)

    # --- Stats ----------------------------------------------------------
    deck_posts = decks.get("matched_posts", 0)
    deck_count = decks.get("new_deck_count", 0)
    digimon_posts = len(digimon.get("event", {})) + len(digimon.get("patch", {}))
    digimon_count = sum(
        len(p["digimon"])
        for p in list(digimon.get("event", {}).values()) + list(digimon.get("patch", {}).values())
    )
    seal_post_count = len(seals)
    seal_servers = len({s["server"] for s in seals})
    total_activity = len(activity)

    # --- Seal-patch highlight cards (auto: one per docs/seal-patch-th-*.html,
    # newest first, dated from its th-<N>#0 entry in seal_data.json) ---------
    import re as _re

    seal_data_raw = json.loads(SEALS.read_text(encoding="utf-8"))
    patch_cards = []
    page_suffixes = sorted(
        (
            int(m.group(1))
            for f in (PROJ / "docs").glob("seal-patch-th-*.html")
            if (m := _re.search(r"th-(\d+)\.html$", f.name))
        ),
        reverse=True,
    )
    for n in page_suffixes:
        entry = seal_data_raw.get(f"th-{n}#0") or seal_data_raw.get(f"th-{n}") or {}
        date = entry.get("date", "")
        n_seals = sum(
            len(v.get("rows", []))
            for k, v in seal_data_raw.items()
            if _re.fullmatch(rf"th-{n}(#\d+)?", k)
        )
        patch_cards.append(f"""    <a href="seal-patch-th-{n}.html" class="feature">
      <div class="icon">📜</div>
      <h3>ซีลแพทช์ TH #{n}</h3>
      <p>ซีลแพทช์ {date} — รายละเอียดตารางแลก + เครื่องคำนวณ</p>
      <div class="feature-stats">
        <div class="stat"><b>#{n}</b>แพทช์</div>
        <div class="stat"><b>{n_seals}</b>ซีล</div>
      </div>
    </a>""")
    seal_patch_cards = "\n\n".join(patch_cards)

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="ติดตามอัพเดต Digimon Masters Online — deck ใหม่, digimon ใหม่, seal exchange ทุกเซิร์ฟ NA · KR · TH">
<meta property="og:title" content="DMO Tracker — Home">
<meta property="og:description" content="ติดตามอัพเดต Digimon Masters Online — deck ใหม่, digimon ใหม่, seal exchange ทุกเซิร์ฟ NA · KR · TH">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎮</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<title>DMO Tracker — Home</title>
<script src="js/theme.js"></script>
<link rel="stylesheet" href="css/site.css">
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
        <div class="stat"><b>{seal_post_count}</b>โพสต์</div>
        <div class="stat"><b>{seal_servers}</b>เซิร์ฟ</div>
      </div>
    </a>

    <a href="lookup.html" class="feature">
      <div class="icon">🔎</div>
      <h3>Cross-server Lookup</h3>
      <p>ค้นชื่อซีล/ดิจิมอน EN · KR · TH ช่องเดียว — เช็คว่าเซิร์ฟไหนมี พร้อมลิงก์โพสต์ต้นทาง</p>
      <div class="feature-stats">
        <div class="stat"><b>3</b>เซิร์ฟ</div>
        <div class="stat"><b>EN·KR·TH</b>ภาษา</div>
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

    <a href="nametag.html" class="feature">
      <div class="icon">🏷️</div>
      <h3>Name Tag Items</h3>
      <p>แพท NA ที่แจก/ขาย/แลกของกลุ่ม Name Tag — แยกตามที่มา (Box · Package · Exchange · Craft)</p>
      <div class="feature-stats">
        <div class="stat"><b>14</b>แพท</div>
        <div class="stat"><b>5</b>item</div>
      </div>
    </a>

    <a href="accessories.html" class="feature">
      <div class="icon">💍</div>
      <h3>Accessories</h3>
      <p>เครื่องประดับเซิร์ฟ TH — ที่มา สเตตัส และการอัพเกรด</p>
      <div class="feature-stats">
        <div class="stat"><b>7</b>ชนิด</div>
        <div class="stat"><b>10</b>ชิ้น</div>
      </div>
    </a>

    <a href="dungeon.html" class="feature">
      <div class="icon">🏰</div>
      <h3>Dungeons</h3>
      <p>ดันเจี้ยนเซิร์ฟ TH — วัตถุดิบ ของดรอป และที่มา</p>
      <div class="feature-stats">
        <div class="stat"><b>2</b>ดัน</div>
        <div class="stat"><b>TH</b>เซิร์ฟ</div>
      </div>
    </a>
  </div>

  <div class="section-header">
    <h2>Patch highlights</h2>
    <span class="see-all">หน้าเจาะลึกรายแพทช์ เซิร์ฟ TH</span>
  </div>

  <div class="feature-grid">
    <a href="susanoomon-extreme-th-90.html" class="feature">
      <div class="icon">⚡</div>
      <h3>[Extreme] Susanoomon</h3>
      <p>TH แพทช์ #90 — ไกด์วัตถุดิบ 2 ชิ้น + เครื่องคำนวณงบแก่นทั้งอีเวนต์</p>
      <div class="feature-stats">
        <div class="stat"><b>#90</b>แพทช์</div>
        <div class="stat"><b>TH</b>เซิร์ฟ</div>
      </div>
    </a>

    <a href="seal-lookup-89.html" class="feature">
      <div class="icon">🔖</div>
      <h3>Seal Lookup #89</h3>
      <p>เทียบไอเทม TH update #89 กับชื่อ NA · KR — ที่มา + สถานะ effect</p>
      <div class="feature-stats">
        <div class="stat"><b>#89</b>แพทช์</div>
        <div class="stat"><b>3</b>เซิร์ฟ</div>
      </div>
    </a>

{seal_patch_cards}
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
    print(f"Wrote {OUT.relative_to(PROJ)} — {total_activity} activity items tracked")


if __name__ == "__main__":
    main()
