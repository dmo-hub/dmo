"""Build docs/budget.html — the Seal Budget calculator as its own page.

The calculator used to sit inside a <details> panel on docs/seals.html. It
carries ~140 lines of CSS and ~230 of JS, which made the feed page hard to read
and buried the tool one click deep. This builder owns the standalone page; the
feed keeps only the ☆ buttons that add a table to the budget, and the two pages
talk through localStorage (same origin, same keys).

The page body is assembled here rather than hand-edited so the markup, CSS and
script stay in one place and a rebuild can't leave the two pages disagreeing.

Run: python builders/build_seal_budget.py
"""

import io
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
FEED = PROJ / "docs" / "seals.html"
OUT = PROJ / "docs" / "budget.html"

TITLE = "DMO Seal Budget — คำนวณตั๋วและราคา"
DESC = "คำนวณตั๋วแลกซีลและราคาแพ็คจากตารางที่ติดตามไว้ในหน้า Seal Exchange (NA · KR · TH)"

CSS = """
  /* ===== Seal Budget calculator ===== */
  .bg-intro { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
    margin: 0 0 18px; padding: 12px 16px; border: 1px solid var(--hairline);
    border-radius: var(--radius); background: var(--surface-soft); }
  .bg-intro p { margin: 0; font-size: 13px; color: var(--body); }
  /* --coral on --surface-soft is 3.7:1 in dark, so the label runs at --ink and
     the accent stays on the border (same call as the seal-search buttons) */
  .bg-intro .back { margin-left: auto; font-size: 12.5px; font-weight: 600;
    color: var(--ink); text-decoration: none; border: 1px solid var(--coral);
    border-radius: 9999px; padding: 5px 13px; white-space: nowrap; }
  .bg-intro .back:hover { background: var(--coral); color: var(--on-primary);
    text-decoration: none; }
  .calc-srvtabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 0 0 14px; }
  .calc-srvtab { appearance: none; cursor: pointer; font: inherit; font-size: 12.5px;
    font-weight: 600; padding: 5px 13px; border-radius: 9999px;
    border: 1px solid var(--hairline); background: var(--surface-soft);
    color: var(--muted); display: inline-flex; align-items: center; gap: 6px; }
  .calc-srvtab .n { font-size: 10.5px; padding: 1px 7px; border-radius: 9999px;
    background: var(--surface-card); color: var(--muted); }
  .calc-srvtab.on { color: var(--on-primary); border-color: transparent; }
  .calc-srvtab.on.s-na { background: var(--amber); }
  .calc-srvtab.on.s-kr { background: var(--coral); }
  .calc-srvtab.on.s-th { background: var(--teal); }
  .calc-srvtab.on .n { background: rgba(255,255,255,.25); color: var(--on-primary); }
  .ct-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px;
    padding: 10px 13px; border-top: 1px solid var(--hairline); }
  .ct-controls label { font-size: 13px; color: var(--body); font-weight: 500;
    display: inline-flex; align-items: center; gap: 7px; }
  .ct-controls input[type=number] { width: 84px; padding: 6px 9px; font: inherit;
    font-size: 13px; border: 1px solid var(--hairline); border-radius: 8px;
    background: var(--canvas); color: var(--ink); text-align: right; }
  .ct-controls .cc-unit { color: var(--muted-soft); font-size: 12.5px; margin-left: -3px; }
  input[type=number] { -moz-appearance: textfield; appearance: textfield; }
  input[type=number]::-webkit-outer-spin-button,
  input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  .ct-controls .fixed { color: var(--muted-soft); font-size: 12.5px; }
  .ct-controls .spacer { flex: 1 1 auto; }
  .ct-controls button { appearance: none; border: 1px solid var(--hairline); cursor: pointer;
    font: inherit; font-size: 12px; font-weight: 600; padding: 6px 13px;
    border-radius: 9999px; background: var(--surface-soft); color: var(--ink); }
  .ct-controls button:hover { background: var(--surface-card); }
  .calc-card { border: 1px solid var(--hairline); border-radius: var(--radius);
    overflow: hidden; margin: 0 0 14px; background: var(--canvas); }
  .calc-card-head { display: flex; align-items: center; gap: 10px; padding: 9px 13px;
    border-bottom: 1px solid var(--hairline); background: var(--surface-soft); }
  .calc-srv { font-size: 9.5px; font-weight: 600; letter-spacing: 1.2px; text-transform: uppercase;
    padding: 3px 8px; border-radius: 9999px; }
  .calc-srv.s-kr { background: var(--coral); color: var(--on-primary); }
  .calc-srv.s-th { background: var(--teal); color: var(--on-primary); }
  .calc-srv.s-na { background: var(--amber); color: var(--on-primary); }
  .calc-card-head .cap { font-size: 12.5px; color: var(--ink); font-weight: 500; }
  .calc-card-head .cap-note { color: var(--amber); font-size: 11.5px; }
  .calc-card-head .cap-note.s-kr { color: var(--coral); }
  .calc-card-head .dt { font-size: 11px; color: var(--muted-soft); font-family: "JetBrains Mono", monospace; }
  .calc-card-head .head-btns { margin-left: auto; display: inline-flex; gap: 7px; }
  .calc-card-head .rm { appearance: none; cursor: pointer;
    font: inherit; font-size: 11.5px; font-weight: 600; padding: 4px 10px;
    border-radius: 9999px; border: 1px solid var(--hairline);
    background: var(--canvas); color: var(--muted); }
  .calc-card-head .rm:hover { color: var(--on-primary); background: var(--coral); border-color: var(--coral); }
  .export-btn { appearance: none; cursor: pointer; font: inherit; font-size: 11.5px;
    font-weight: 600; padding: 4px 10px; border-radius: 9999px;
    border: 1px solid var(--hairline); background: var(--canvas); color: var(--muted); }
  .export-btn:hover { color: var(--on-primary); background: var(--primary); border-color: var(--primary); }
  .export-btn:disabled { opacity: .5; cursor: default; }
  /* off-screen capture stage: rendered for one frame, then removed */
  .export-shot { position: fixed; left: 0; top: 0; z-index: 9999;
    padding: 16px; background: var(--canvas); pointer-events: none; opacity: .01; }
  .export-shot .calc-total { position: static; margin: 0 0 14px; }
  .export-shot .calc-card { margin: 0; }
  .export-shot, .export-shot * { overflow: visible !important; max-height: none !important; }
  .export-shot table.calc-tbl { min-width: 0; width: 100%; }
  .export-only { display: none; }
  .export-shot .export-only { display: flex; }
  .calc-tbl-wrap { overflow-x: auto; }
  table.calc-tbl { border-collapse: collapse; width: 100%; font-size: 12px; min-width: 420px; }
  table.calc-tbl th, table.calc-tbl td { padding: 6px 11px; text-align: center;
    border-bottom: 1px solid var(--hairline); white-space: nowrap; }
  table.calc-tbl tr:first-child th { background: var(--surface-card); color: var(--ink); }
  table.calc-tbl td:first-child, table.calc-tbl th:first-child { text-align: left; font-weight: 500; }
  table.calc-tbl tr:nth-child(even) td { background: var(--surface-soft); }
  table.calc-tbl input.want { width: 76px; padding: 4px 7px; font: inherit; font-size: 12px;
    border: 1px solid var(--hairline); border-radius: 7px; background: var(--canvas);
    color: var(--ink); text-align: right; }
  table.calc-tbl .tk { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--ink); }
  table.calc-tbl .status { font-variant-numeric: tabular-nums; white-space: nowrap; }
  table.calc-tbl .status .got { font-weight: 600; color: var(--ink); }
  table.calc-tbl .status .mx { color: var(--muted-soft); }
  table.calc-tbl tr.sub td { background: var(--surface-card); font-weight: 600; color: var(--ink); }
  table.calc-tbl .rm-cell { width: 1%; }
  table.calc-tbl .rm-seal { appearance: none; cursor: pointer; border: 0; background: none;
    color: var(--muted-soft); font: inherit; font-size: 13px; line-height: 1; padding: 2px 4px; }
  table.calc-tbl .rm-seal:hover { color: var(--coral); }
  .calc-filter { display: flex; flex-wrap: wrap; align-items: center; gap: 5px;
    padding: 8px 13px; border-bottom: 1px solid var(--hairline); }
  .calc-filter .lbl { font-size: 11px; color: var(--muted-soft); margin-right: 3px; }
  .calc-chip { appearance: none; cursor: pointer; font: inherit; font-size: 11px;
    font-weight: 600; padding: 3px 9px; border-radius: 9999px;
    border: 1px solid var(--hairline); background: var(--canvas); color: var(--muted); }
  .calc-chip.on { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }
  .calc-total { position: sticky; top: 6px; z-index: 2; margin: 0 0 16px;
    border: 1px solid var(--hairline); border-radius: var(--radius);
    background: var(--surface-soft); overflow: hidden; }
  .calc-total .ct-row { display: flex; align-items: baseline; justify-content: space-between;
    gap: 12px; padding: 7px 13px; }
  .calc-total .ct-row + .ct-row { border-top: 1px solid var(--hairline); }
  .calc-total .t { font-size: 12px; color: var(--muted); font-weight: 500; }
  .calc-total .vw { display: inline-flex; align-items: baseline; gap: 5px; }
  .calc-total .v { font-size: 14px; font-weight: 700; color: var(--ink);
    font-variant-numeric: tabular-nums; }
  .calc-total .u { font-size: 10px; color: var(--muted-soft); }
  .calc-total .ct-price { background: var(--surface-card); }
  .calc-total .ct-price .t { color: var(--body); font-weight: 600; }
  .calc-total .ct-price .v { font-size: 15.5px; color: var(--ink); }
  .calc-total .ct-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px;
    padding: 8px 13px; border-top: 1px solid var(--hairline); }
  .calc-total .ct-stats .st { display: flex; align-items: baseline; justify-content: space-between;
    gap: 6px; padding: 3px 7px; border-radius: 7px; background: var(--canvas); }
  .calc-total .ct-stats .st .k { font-size: 11px; font-weight: 700; color: var(--muted); letter-spacing: .3px; }
  .calc-total .ct-stats .st .n { font-size: 13px; font-weight: 700; color: var(--ink);
    font-variant-numeric: tabular-nums; }
  @media (max-width: 520px) { .calc-total .ct-stats { grid-template-columns: repeat(2, 1fr); } }
  /* the empty state is the whole page when nothing is tracked, so it uses the
     stronger muted token — --muted-soft only reaches 2.7:1 on the light canvas */
  .calc-empty { padding: 26px 18px; text-align: center; color: var(--muted);
    font-size: 13px; line-height: 1.9; }
  .calc-removed { padding: 7px 13px; font-size: 11.5px; color: var(--muted-soft);
    border-top: 1px solid var(--hairline); background: var(--surface-soft); }
  .calc-removed a { color: var(--coral); cursor: pointer; text-decoration: none; }
"""

BODY = """
  <div class="hero">
    <div>
      <h1>Seal Budget</h1>
      <p class="lead">คำนวณตั๋วแลกซีลและราคาแพ็คจากตารางที่ติดตามไว้ — แยกงบต่อเซิร์ฟ NA · KR · TH</p>
    </div>
    <div class="hero-stats">
      <div class="hero-stat"><div class="num" id="hero-tables">0</div><div class="lbl">ตารางที่ติดตาม</div></div>
      <div class="hero-stat"><div class="num">3,000</div><div class="lbl">ตั๋ว/แพ็ค</div></div>
    </div>
  </div>

  <div class="bg-intro">
    <p>กดปุ่ม <b>☆ ติดตาม</b> บนตารางในหน้า Seal Exchange เพื่อเพิ่มเข้ามาคำนวณที่นี่</p>
    <a class="back" href="seals.html">← กลับไปหน้า Seal Exchange</a>
  </div>

  <div class="calc-srvtabs no-export" id="calc-srvtabs"></div>
  <div class="calc-total" id="calc-total" hidden>
    <div class="ct-row export-only"><span class="t">🏷️ ราคา/แพ็ค</span><span class="vw"><span class="v" id="tot-pricepack">0</span><span class="u">฿</span></span></div>
    <div class="ct-row"><span class="t">🎟️ รวมตั๋วที่ใช้</span><span class="vw"><span class="v" id="tot-tickets">0</span><span class="u">ใบ</span></span></div>
    <div class="ct-row"><span class="t">📦 คิดเป็น</span><span class="vw"><span class="v" id="tot-packs">0</span><span class="u">แพ็ค</span></span></div>
    <div class="ct-row ct-price"><span class="t">💵 ราคารวม</span><span class="vw"><span class="v" id="tot-price">0</span><span class="u">฿</span></span></div>
    <div class="ct-stats" id="tot-stats"></div>
    <div class="ct-controls no-export">
      <label>ราคา/แพ็ค <input type="number" id="price-pack" min="0" step="1" value="240"><span class="cc-unit">฿</span></label>
      <span class="fixed">· 1 แพ็ค = 3,000 ตั๋ว</span>
      <span class="spacer"></span>
      <button id="set-master" type="button">ตั้งทุกแถว = 3000 (ถึง Master)</button>
      <button id="clear-want" type="button">ล้างค่าที่กรอก</button>
    </div>
  </div>
  <div id="calc-root"></div>
"""

# The ☆ buttons live on the feed page; this page only reads what they wrote to
# localStorage, so there is no paintStars/feed-DOM half here.
SCRIPT = """
<script>
(() => {
  const PACK = 3000;
  const STARS_KEY = 'dmo_seal_stars', WANT_KEY = 'dmo_seal_want',
        REMOVED_KEY = 'dmo_seal_removed', PRICE_KEY = 'dmo_seal_pricepack';
  const root = document.getElementById('calc-root');
  const totalBar = document.getElementById('calc-total');
  const heroTables = document.getElementById('hero-tables');
  const priceInput = document.getElementById('price-pack');
  const fmt = n => n.toLocaleString('en-US');
  const fmt2 = n => n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});

  // Lazily load html-to-image from CDN only when the user first exports.
  let _h2iP = null;
  const loadH2I = () => _h2iP || (_h2iP = new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/html-to-image@1.11.13/dist/html-to-image.js';
    s.onload = () => res(window.htmlToImage); s.onerror = rej; document.head.appendChild(s);
  }));
  // Snapshot the total bar + one tracked table as a single PNG. Builds a
  // visible (briefly on-screen, so the browser actually paints it) wrapper
  // holding clones of both, strips .no-export chrome from the clone, captures,
  // then removes it — the live DOM is untouched.
  async function exportCard(card, filename, btn) {
    let lib;
    try { lib = await loadH2I(); }
    catch (e) { alert('โหลดตัวสร้างรูปไม่สำเร็จ (ต้องต่อเน็ต)'); return; }
    const prev = btn && btn.textContent;
    if (btn) { btn.disabled = true; btn.textContent = '⏳ กำลังสร้าง…'; }
    const w = card.offsetWidth;
    const wrap = document.createElement('div');
    wrap.className = 'export-shot';
    wrap.style.width = w + 'px';
    const cardClone = card.cloneNode(true);
    // cloneNode copies the value ATTRIBUTE, not the live input .value the user
    // typed — mirror each one onto the clone so "ต้องการ" shows the real number
    const srcInputs = card.querySelectorAll('input.want');
    cardClone.querySelectorAll('input.want').forEach((inp, i) => {
      if (srcInputs[i]) inp.setAttribute('value', srcInputs[i].value);
    });
    wrap.appendChild(totalBar.cloneNode(true));
    wrap.appendChild(cardClone);
    wrap.querySelectorAll('.no-export').forEach(n => n.remove());
    document.body.appendChild(wrap);
    try {
      const bg = getComputedStyle(document.body).backgroundColor;
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const url = await lib.toPng(wrap, {pixelRatio: 2, backgroundColor: bg,
        width: wrap.offsetWidth, height: wrap.offsetHeight, cacheBust: true});
      const a = document.createElement('a'); a.href = url; a.download = filename + '.png'; a.click();
    } catch (e) { alert('สร้างรูปไม่สำเร็จ: ' + e); }
    finally { wrap.remove(); if (btn) { btn.disabled = false; btn.textContent = prev; } }
  }

  const jget = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } };
  const stars = () => jget(STARS_KEY, []);
  const setStars = a => localStorage.setItem(STARS_KEY, JSON.stringify(a));
  let want = jget(WANT_KEY, {}), removed = jget(REMOVED_KEY, {});
  const saveWant = () => localStorage.setItem(WANT_KEY, JSON.stringify(want));
  const saveRemoved = () => localStorage.setItem(REMOVED_KEY, JSON.stringify(removed));
  const filterState = {};
  priceInput.value = jget(PRICE_KEY, 240);
  let DATA = {};
  let activeServer = null;                       // each server budgets separately
  const SRV_ORDER = ['na', 'kr', 'th'];
  function starCounts() {
    const c = {};
    stars().forEach(k => { if (DATA[k]) c[DATA[k].server] = (c[DATA[k].server] || 0) + 1; });
    return c;
  }
  function renderTabs(counts) {
    const el = document.getElementById('calc-srvtabs');
    el.innerHTML = SRV_ORDER.filter(s => counts[s]).map(s =>
      `<button class="calc-srvtab s-${s} ${s === activeServer ? 'on' : ''}" data-srv="${s}" type="button">${s.toUpperCase()} <span class="n">${counts[s]}</span></button>`).join('');
    el.querySelectorAll('.calc-srvtab').forEach(b =>
      b.addEventListener('click', () => { activeServer = b.dataset.srv; render(); }));
  }

  const ticketsFor = (w, e, f) => (w > 0 && e > 0) ? Math.ceil(w / e) * f : 0;
  // status gained from owning `w` seals: a step function of the seal count
  // (the in-game tiers), times the seal's max stat. Floors to the tier reached.
  const STAT_TIERS = [[3000, 1], [1000, 0.8], [500, 0.6], [200, 0.4], [50, 0.2], [1, 0.1]];
  const statFracFor = w => { for (const [n, f] of STAT_TIERS) if (w >= n) return f; return 0; };
  const statGained = (w, max) => max > 0 ? Math.round(max * statFracFor(w)) : 0;
  // CT/BL/EV are percentage stats: the table value is value×100, so show it as
  // (value/100) with 2 decimals + a % sign. The rest are flat point values.
  const PCT_STATS = new Set(['CT', 'BL', 'EV']);
  const fmtStat = (stat, v) => PCT_STATS.has(stat) ? (v / 100).toFixed(2) + '%' : fmt(v);
  const applyFilter = card => {
    const sel = filterState[card.dataset.tkey];
    card.querySelectorAll('tr[data-seal]').forEach(tr =>
      tr.style.display = (!sel || !sel.size || sel.has(tr.dataset.stat)) ? '' : 'none');
  };
  // grid is 4 cols: top row AT HT CT HP, bottom row DE BL EV DS
  const STAT_ORDER = ['AT', 'HT', 'CT', 'HP', 'DE', 'BL', 'EV', 'DS'];
  function recalc() {
    let grand = 0;
    const statTot = {};                       // stat type -> total status gained
    document.querySelectorAll('.calc-card').forEach(card => {
      let sub = 0, subGot = 0;
      card.querySelectorAll('tr[data-seal]').forEach(tr => {
        if (tr.style.display === 'none') return;
        const w = parseInt(tr.querySelector('input.want').value, 10) || 0;
        const each = +tr.dataset.each, tick = +tr.dataset.tickets;
        const t = ticketsFor(w, each, tick);
        tr.querySelector('.tk').textContent = t ? fmt(t) : '–';
        const stat = tr.dataset.stat, max = +tr.dataset.max || 0;
        const got = statGained(w, max);
        tr.querySelector('.status .got').textContent = max ? fmtStat(stat, got) : '–';
        if (got && stat) statTot[stat] = (statTot[stat] || 0) + got;
        sub += t; subGot += got;
      });
      card.querySelector('.sub .tk').textContent = fmt(sub);
      card.querySelector('.sub .status .got').textContent = fmt(subGot);
      grand += sub;
    });
    const packs = grand / PACK;
    const price = +priceInput.value || 0;
    document.getElementById('tot-tickets').textContent = fmt(grand);
    document.getElementById('tot-packs').textContent = fmt2(packs);
    document.getElementById('tot-price').textContent = fmt(Math.round(packs * price));
    document.getElementById('tot-pricepack').textContent = fmt(price);
    const stEl = document.getElementById('tot-stats');
    const shown = STAT_ORDER.filter(s => statTot[s]);
    stEl.innerHTML = shown.map(s =>
      `<div class="st"><span class="k">${s}</span><span class="n">${fmtStat(s, statTot[s])}</span></div>`).join('');
    stEl.hidden = !shown.length;
  }

  function render() {
    const counts = starCounts();
    const srvs = SRV_ORDER.filter(s => counts[s]);
    if (!srvs.includes(activeServer)) activeServer = srvs[0] || null;
    renderTabs(counts);
    const keys = stars().filter(k => DATA[k] && DATA[k].server === activeServer);
    heroTables.textContent = stars().filter(k => DATA[k]).length;
    root.innerHTML = '';
    totalBar.hidden = !keys.length;
    if (!keys.length) {
      root.innerHTML = '<div class="calc-empty">ยังไม่ได้ติดตามตารางไหน 🌟<br>กดปุ่ม ☆ ติดตาม บนตารางในหน้า <a href="seals.html">Seal Exchange</a> เพื่อเพิ่มเข้า Seal Budget</div>';
      recalc();
      return;
    }
    keys.forEach(k => {
      const t = DATA[k];
      const rm = new Set(removed[k] || []);
      const rows = t.rows.filter(r => !rm.has(r[0]));
      const statsList = [...new Set(rows.map(r => r[3]).filter(s => s && s !== '—'))];
      const nRm = (removed[k] || []).length;
      const chips = statsList.map(s => `<button class="calc-chip" data-stat="${s}" type="button">${s}</button>`).join('');
      const body = rows.map(r => {
        const w = (want[k] || {})[r[0]] ?? '';
        return `<tr data-seal="${r[0]}" data-each="${r[1]}" data-tickets="${r[2]}" data-stat="${r[3]}" data-max="${r[4] || 0}">
          <td>${r[0]}</td><td>${r[3] || '–'}</td><td>${r[1]}</td><td>${r[2]}</td>
          <td><input class="want" type="number" min="0" step="1" value="${w}" placeholder="0"></td>
          <td class="tk">–</td><td class="status"><span class="got">0</span>/<span class="mx">${r[4] ? fmtStat(r[3], +r[4]) : '–'}</span></td><td class="rm-cell no-export"><button class="rm-seal" type="button" title="ลบซีลนี้">✕</button></td></tr>`;
      }).join('');
      const card = document.createElement('div');
      card.className = 'calc-card'; card.dataset.tkey = k;
      card.innerHTML = `
        <div class="calc-card-head"><span class="calc-srv s-${t.server}">${t.server.toUpperCase()}</span>
          <span class="dt">${t.date}</span><span class="cap${t.note ? ` cap-note s-${t.server}` : ''} no-export">${t.note || t.caption}</span>
          <span class="head-btns no-export">
            <button class="export-btn" type="button" title="บันทึกตารางนี้เป็นรูป">🖼️ บันทึกรูป</button>
            <button class="rm" type="button" title="เลิกติดตามตารางนี้">✕ เลิกติดตาม</button></span></div>
        ${statsList.length > 1 ? `<div class="calc-filter no-export"><span class="lbl">Stat:</span>${chips}</div>` : ''}
        <div class="calc-tbl-wrap"><table class="calc-tbl">
          <tr><th>ซีล</th><th>Stat</th><th>ได้/ครั้ง</th><th>ตั๋ว/ครั้ง</th><th>ต้องการ</th><th>ใช้ตั๋ว</th><th>Status (ได้/สูงสุด)</th><th class="rm-cell no-export"></th></tr>
          ${body}
          <tr class="sub no-export"><td colspan="5">รวมตารางนี้</td><td class="tk">0</td><td class="status"><span class="got">0</span></td><td class="rm-cell"></td></tr>
        </table></div>
        ${nRm ? `<div class="calc-removed">ลบไป ${nRm} ซีล · <a class="restore">คืนค่าทั้งหมด</a></div>` : ''}`;
      card.querySelector('.export-btn').addEventListener('click', e =>
        exportCard(card, `seal-${t.server}-${k}`, e.currentTarget));
      card.querySelector('.rm').addEventListener('click', () => {
        const set = new Set(stars()); set.delete(k); setStars([...set]); render();
      });
      card.querySelectorAll('.calc-chip').forEach(chip => chip.addEventListener('click', () => {
        const set = filterState[k] = filterState[k] || new Set(); const s = chip.dataset.stat;
        if (set.has(s)) { set.delete(s); chip.classList.remove('on'); }
        else { set.add(s); chip.classList.add('on'); }
        applyFilter(card); recalc();
      }));
      card.querySelectorAll('.rm-seal').forEach(btn => btn.addEventListener('click', () => {
        const name = btn.closest('tr').dataset.seal; removed[k] = removed[k] || [];
        if (!removed[k].includes(name)) removed[k].push(name); saveRemoved(); render();
      }));
      const restore = card.querySelector('.restore');
      if (restore) restore.addEventListener('click', () => { delete removed[k]; saveRemoved(); render(); });
      card.querySelectorAll('input.want').forEach(inp => inp.addEventListener('input', () => {
        const name = inp.closest('tr').dataset.seal; want[k] = want[k] || {};
        if (inp.value === '') delete want[k][name]; else want[k][name] = inp.value;
        saveWant(); recalc();
      }));
      root.appendChild(card);
      if (filterState[k]) card.querySelectorAll('.calc-chip').forEach(c => { if (filterState[k].has(c.dataset.stat)) c.classList.add('on'); });
      applyFilter(card);
    });
    recalc();
  }
  priceInput.addEventListener('input', () => { localStorage.setItem(PRICE_KEY, priceInput.value || 0); recalc(); });
  document.getElementById('set-master').addEventListener('click', () => {
    document.querySelectorAll('.calc-card').forEach(card => {
      const k = card.dataset.tkey; want[k] = want[k] || {};
      card.querySelectorAll('tr[data-seal]').forEach(tr => {
        if (tr.style.display === 'none') return;
        tr.querySelector('input.want').value = 3000; want[k][tr.dataset.seal] = '3000';
      });
    });
    saveWant(); recalc();
  });
  document.getElementById('clear-want').addEventListener('click', () => {
    want = {}; saveWant(); document.querySelectorAll('input.want').forEach(i => i.value = ''); recalc();
  });

  // The feed page writes the same keys, so a star toggled in another tab has to
  // redraw this one rather than leave it showing a stale list.
  window.addEventListener('storage', e => {
    if ([STARS_KEY, WANT_KEY, REMOVED_KEY].includes(e.key)) {
      want = jget(WANT_KEY, {}); removed = jget(REMOVED_KEY, {}); render();
    }
  });

  fetch('seal_data.json').then(r => r.json()).then(d => { DATA = d; render(); })
    .catch(() => { root.innerHTML = '<div class="calc-empty">โหลดข้อมูลไม่ได้ — เปิดผ่านเว็บ (Pages) ไม่ใช่ไฟล์ตรง ๆ</div>'; });
})();
</script>
"""


def _shell(feed_html):
    """Head/nav/footer lifted from the feed page so both share one look. Taking
    them from the live file (rather than a copy here) keeps this page in step
    when the site chrome changes."""
    nav = re.search(r'<header class="site-nav">.*?</header>', feed_html, re.S)
    footer = re.search(r'<footer class="site-footer">.*?</footer>', feed_html, re.S)
    if not nav or not footer:
        sys.exit("could not read nav/footer from seals.html")
    nav_html = nav.group(0).replace(
        '<a href="seals.html" class="is-active">Seal</a>', '<a href="seals.html">Seal</a>'
    )
    return nav_html, footer.group(0)


def main():
    feed = FEED.read_text(encoding="utf-8")
    nav, footer = _shell(feed)
    page = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{DESC}">
<meta property="og:title" content="{TITLE}">
<meta property="og:description" content="{DESC}">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>💰</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<title>{TITLE}</title>
<script src="js/theme.js"></script>
<link rel="stylesheet" href="css/site.css">
<style>{CSS}</style>
</head>
<body>

{nav}

<main class="page">
{BODY}
</main>

{footer}
{SCRIPT}
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.name} ({page.count(chr(10)) + 1} lines)")


if __name__ == "__main__":
    main()
