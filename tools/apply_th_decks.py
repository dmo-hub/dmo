"""Show the TH version of every deck in docs/decks.html that TH also has.

    data/deck_th_map.json + data/th_patch_decks.json  ->  docs/decks.html

decks.html is hand-written, so this patches it in place rather than
rebuilding it. For each paired deck the visible name, digimon list and buff
table become the TH ones, the English name stays as a caption, and the post
gets a TH source chip. The page's filter keys off English names (the Rank U
regexes, the effect aliases), so the NA lists are kept on the deck as
data-na-digimon / data-na-effect and the filter reads those.

Safe to re-run: a deck already carrying data-th is left alone.
"""

import html
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
PAGE = PROJ / "docs" / "decks.html"
MAP = PROJ / "data" / "deck_th_map.json"
TH = PROJ / "data" / "th_patch_decks.json"

# A deck runs to the next deck or the end of the post: some carry an
# "upgraded version" note after their tables, inside the same deck div.
DECK_RE = re.compile(r'<div class="deck"[^>]*>.*?(?=<div class="deck"|</section>)', re.S)


def esc(s):
    return html.escape(s or "", quote=False)


def cells(table_html):
    return [re.findall(r"<td>(.*?)</td>", r) for r in re.findall(r"<tr>(.*?)</tr>", table_html)]


def th_block(deck_html, th, na_name):
    digi = re.search(r'<table class="gk-table digimon-table">.*?</table>', deck_html, re.S).group(0)
    eff = re.search(r'<table class="gk-table effect-table">.*?</table>', deck_html, re.S).group(0)
    na_digimon = [html.unescape(r[0]) for r in cells(digi) if r]
    na_effect = [html.unescape(r[0]) for r in cells(eff) if r]
    effects = [list(e) for e in th["effects"]]
    na_rows = [r for r in cells(eff) if len(r) >= 3]
    # TH sometimes drops a timed buff's duration that NA states ("30%
    # Increase for 10s" vs "+30%"). Same row, same number: carry it over,
    # marked as NA's, rather than show a timed buff as permanent.
    if len(na_rows) == len(effects):
        for e, r in zip(effects, na_rows):
            dur = re.search(r"for (\d+)\s*s\b", r[2])
            num = re.search(r"(\d+(?:\.\d+)?)\s*%", r[2])
            if dur and num and "วินาที" not in (e[1] or "") + e[2] and num.group(1) in e[2]:
                e[2] = "%s นาน %s วินาที (ตาม NA)" % (e[2], dur.group(1))
    rows = "".join("<tr><td>%s</td></tr>" % esc(m) for m in th["digimon"])
    new_digi = ('<table class="gk-table digimon-table"><tr><th>%s<br><span class="deck-alt">NA: %s</span>'
                '</th></tr>\n          %s</table>' % (esc(th["name"]), esc(na_name), rows))
    erows = "\n".join("          <tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                      % (esc(a), esc(b) if b else "—", esc(c)) for a, b, c in effects)
    new_eff = ('<table class="gk-table effect-table">\n          <tr><th>สเตตัส</th><th>โอกาส</th>'
               '<th>ผล</th></tr>\n%s\n          </table>' % erows)
    out = deck_html.replace(digi, new_digi, 1).replace(eff, new_eff, 1)
    out = out.replace("<p class=\"gk-label\">Effect</p>", "<p class=\"gk-label\">Effect (TH)</p>", 1)
    out = re.sub(r'<p class="gk-label">Digimon List(?: \(\d+\))?</p>',
                 '<p class="gk-label">Digimon List (TH)</p>', out, count=1)
    attrs = ' data-th="1" data-na-digimon="%s" data-na-effect="%s"' % (
        html.escape("|".join(na_digimon), quote=True), html.escape("|".join(na_effect), quote=True))
    return out.replace('<div class="deck">', '<div class="deck"%s>' % attrs, 1)


def main():
    page = PAGE.read_text(encoding="utf-8")
    pairs = json.loads(MAP.read_text(encoding="utf-8"))["pairs"]
    th_decks = {(d["date"], d["name"]): d for d in json.loads(TH.read_text(encoding="utf-8"))["decks"]}
    done = skipped = 0
    for p in pairs:
        th = th_decks.get((p["th_date"], p["th_name"]))
        if not th:
            sys.exit("TH deck not found: %s %s" % (p["th_date"], p["th_name"]))
        sec = re.search(r'<section class="post" id="%s">.*?</section>' % p["na_post"], page, re.S)
        if not sec:
            sys.exit("post not in page: %s" % p["na_post"])
        body = sec.group(0)
        target = None
        for d in DECK_RE.finditer(body):
            head = re.search(r"digimon-table\"><tr><th>(.*?)(?:<br>|</th>)", d.group(0))
            if head and html.unescape(head.group(1)) in (p["na_name"], th["name"]):
                target = d.group(0)
                break
        if target is None:
            sys.exit("deck not in %s: %s" % (p["na_post"], p["na_name"]))
        if "data-th=" in target:
            skipped += 1
            continue
        new_body = body.replace(target, th_block(target, th, p["na_name"]), 1)
        if 'src-item is-th' not in new_body:
            y, m, d_ = th["date"].split("-")
            chip = ('<span class="src-item is-th"><a class="src-label" href="%s" target="_blank" '
                    'title="vplay.in.th">TH</a><span class="src-date">%s.%s.%s</span></span>'
                    % (esc(th["url"]), d_, m, y))
            new_body = re.sub(r'(<div class="sources">.*?)(</div>)', r"\1" + chip.replace("\\", "\\\\") + r"\2",
                              new_body, count=1, flags=re.S)
        page = page.replace(body, new_body, 1)
        done += 1
    PAGE.write_text(page, encoding="utf-8", newline="\n")
    print("decks switched to TH: %d (already TH: %d)" % (done, skipped))


if __name__ == "__main__":
    main()
