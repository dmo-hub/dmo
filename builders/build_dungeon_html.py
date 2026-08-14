"""Build docs/dungeon.html — cross-server dungeon guide (NA · KR · TH).

Reads data/dungeons.json (produced by scanners/scan_dungeons.py) and renders one
card per dungeon: boss header + an image slot (left blank for manual fill) + a
per-server panel (TH populated now; NA/KR show "เร็ว ๆ นี้" until their scanners
land). Shares docs/css/site.css + .site-nav markup, same as the other pages.

    python builders/build_dungeon_html.py
"""

import html as _html
import json
from datetime import date
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DATA = PROJ / "data" / "dungeons.json"
OUT = PROJ / "docs" / "dungeon.html"

SERVERS = [("na", "NA"), ("kr", "KR"), ("th", "TH")]


def esc(s):
    return _html.escape(str(s), quote=True)


def server_panel(code, label, srv):
    if not srv:
        return (
            f'<div class="dg-srv dg-srv-{code} dg-srv-empty">'
            f'<span class="dg-srv-tag">{label}</span>'
            f'<span class="dg-soon">เร็ว ๆ นี้</span></div>'
        )
    rows = []
    if srv.get("req"):
        rows.append(f'<div class="dg-fld"><span class="dg-k">เลเวล</span>'
                    f'<span class="dg-v">{esc(srv["req"])}</span></div>')
    if srv.get("pass_item"):
        rows.append(f'<div class="dg-fld"><span class="dg-k">บัตรผ่าน</span>'
                    f'<span class="dg-v">{esc(srv["pass_item"])}</span></div>')
    drops = srv.get("drop") or []
    if drops:
        lis = "".join(f"<li>{esc(d)}</li>" for d in drops)
        rows.append(f'<div class="dg-fld dg-drop"><span class="dg-k">ของดรอป</span>'
                    f'<ul class="dg-droplist">{lis}</ul></div>')
    src = ""
    if srv.get("url"):
        src = (f'<a class="dg-src" href="{esc(srv["url"])}" target="_blank" '
               f'rel="noopener">อ่านต่อที่ vplay ↗</a>')
    summary = f'<p class="dg-summary">{esc(srv["summary"])}</p>' if srv.get("summary") else ""
    date_html = f'<span class="dg-date">{esc(srv["date"])}</span>' if srv.get("date") else ""
    rows_html = "".join(rows)
    return (
        f'<div class="dg-srv dg-srv-{code}">'
        f'<div class="dg-srv-head"><span class="dg-srv-tag">{label}</span>'
        f'{date_html}</div>'
        f'{summary}{rows_html}{src}</div>'
    )


def dungeon_card(d):
    th = d.get("th") or {}
    title = esc(th.get("boss") or d["id"])
    subtitle = esc(th.get("name", "")).split(":")[0] if th.get("name") else ""
    img = d.get("image") or ""
    if img:
        media = f'<img class="dg-img" src="{esc(img)}" alt="{title}" loading="lazy">'
    else:
        media = ('<div class="dg-img dg-img-slot" aria-label="เว้นไว้ใส่รูปภายหลัง">'
                 '<span>🏰</span></div>')
    panels = "".join(server_panel(c, lbl, d.get(c)) for c, lbl in SERVERS)
    sub_html = f'<p class="dg-sub">{subtitle}</p>' if subtitle else ""
    return (
        f'<article class="dg-card">'
        f'<div class="dg-media">{media}</div>'
        f'<div class="dg-body">'
        f'<h2 class="dg-boss">{title}</h2>'
        f'{sub_html}'
        f'<div class="dg-servers">{panels}</div>'
        f'</div></article>'
    )


STYLE = """
  .dg-grid { display: grid; gap: 18px; margin-top: 6px; }
  .dg-card { display: flex; gap: 18px; border: 1px solid var(--hairline);
    border-radius: var(--radius-lg, 16px); background: var(--canvas);
    overflow: hidden; padding: 16px; }
  @media (max-width: 640px){ .dg-card{ flex-direction: column; } }
  .dg-media { flex: 0 0 200px; }
  .dg-img { width: 200px; height: 200px; object-fit: cover;
    border-radius: var(--radius, 12px); }
  .dg-img-slot { display: flex; align-items: center; justify-content: center;
    font-size: 60px; background: var(--surface-card);
    border: 1px dashed var(--hairline); color: var(--muted-soft); }
  @media (max-width: 640px){ .dg-media,.dg-img,.dg-img-slot{ width:100%; flex-basis:auto; } }
  .dg-body { flex: 1; min-width: 0; }
  .dg-boss { font-size: 20px; font-weight: 700; margin: 0; color: var(--ink); }
  .dg-sub { font-size: 12.5px; color: var(--muted-soft); margin: 2px 0 12px; }
  .dg-servers { display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr));
    gap: 12px; }
  .dg-srv { border: 1px solid var(--hairline); border-radius: var(--radius, 12px);
    padding: 12px; background: var(--surface-soft, var(--canvas)); font-size: 13px; }
  .dg-srv-empty { display: flex; align-items: center; justify-content: space-between;
    color: var(--muted-soft); }
  .dg-srv-head { display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 8px; }
  .dg-srv-tag { font-size: 10.5px; font-weight: 700; letter-spacing: .5px;
    padding: 2px 9px; border-radius: 9999px; background: var(--primary, #6b7cff);
    color: var(--on-primary, #fff); }
  .dg-srv-th .dg-srv-tag { background: var(--coral); }
  .dg-srv-kr .dg-srv-tag { background: var(--teal, #14b8a6); }
  .dg-srv-na .dg-srv-tag { background: var(--primary, #6b7cff); }
  .dg-date { font-size: 11px; color: var(--muted-soft); }
  .dg-soon { font-size: 12px; font-style: italic; }
  .dg-summary { margin: 0 0 8px; color: var(--muted); line-height: 1.5; }
  .dg-fld { display: flex; gap: 8px; margin: 6px 0; }
  .dg-k { flex: 0 0 62px; font-weight: 600; color: var(--muted-soft); font-size: 12px; }
  .dg-v { color: var(--ink); }
  .dg-drop { flex-direction: column; gap: 4px; }
  .dg-droplist { margin: 2px 0 0; padding-left: 18px; color: var(--ink);
    line-height: 1.6; }
  .dg-droplist li { font-size: 12.5px; }
  .dg-src { display: inline-block; margin-top: 8px; font-size: 12px; font-weight: 600;
    color: var(--coral); }
"""


def render(payload):
    cards = "\n".join(dungeon_card(d) for d in payload["dungeons"])
    n = len(payload["dungeons"])
    n_th = sum(1 for d in payload["dungeons"] if d.get("th"))
    return f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="ไกด์ดันเจี้ยน Digimon Masters Online — บอส เงื่อนไข บัตรผ่าน ของดรอป รวมเซิร์ฟ NA · KR · TH">
<title>DMO Dungeons — Cross-server Guide</title>
<script src="js/theme.js"></script>
<link rel="stylesheet" href="css/site.css">
<style>{STYLE}</style>
</head>
<body>

<header class="site-nav">
  <div class="site-nav-inner">
    <a class="brand" href="./"><span class="dot"></span>DMO Tracker</a>
    <nav>
      <a href="./">Home</a>
      <a href="decks.html">Decks</a>
      <a href="digimon.html">Digimon</a>
      <a href="dungeon.html" class="is-active">Dungeon</a>
      <a href="seals.html">Seal</a>
    </nav>
    <span class="nav-meta">scrape: vplay · gameking · digimonmasters</span>
  </div>
</header>

<main class="page">
  <section>
    <div class="hero">
      <div>
        <h1>🏰 Dungeons — ไกด์ดันเจี้ยน</h1>
        <p class="lead">ดันเจี้ยน (ดันบอส) ของ Digimon Masters Online — บอส · เงื่อนไขเลเวล · บัตรผ่าน · ของดรอป
          รวมทุกเซิร์ฟ NA · KR · TH · คอลัมน์ TH จาก vplay.in.th (NA/KR เร็ว ๆ นี้)</p>
      </div>
      <div class="hero-stats">
        <div class="hero-stat"><div class="num">{n}</div><div class="lbl">ดันเจี้ยน</div></div>
        <div class="hero-stat"><div class="num">{n_th}</div><div class="lbl">TH</div></div>
        <div class="hero-stat"><div class="num">3</div><div class="lbl">เซิร์ฟ</div></div>
      </div>
    </div>

    <div class="dg-grid">
{cards}
    </div>
    <p class="lead" style="margin-top:14px;font-size:12px">
      ที่มา: vplay.in.th (TH) · รูปบอสเว้นช่องไว้ใส่ภายหลัง · gen จาก
      <code>builders/build_dungeon_html.py</code> — data <code>data/dungeons.json</code>
    </p>
  </section>
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


def main():
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    OUT.write_text(render(payload), encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJ)}  ({len(payload['dungeons'])} dungeon)")


if __name__ == "__main__":
    main()
