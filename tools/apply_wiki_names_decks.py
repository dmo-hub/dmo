"""Show dmowiki's name for every English digimon name on docs/decks.html.

    data/deck_wiki_names.json  ->  docs/decks.html   (patched in place)

decks.html is hand-written, so this rewrites it in place, the same way
apply_th_decks.py does, and runs after it. Two places carry names:

  * the digimon-table cells of NA decks -- the cell text becomes the wiki
    name and keeps the post's own spelling in its title (shown on hover);
  * data-na-digimon on TH decks, which feeds the Digimon filter, so the filter
    lists one spelling for a digimon whichever server the deck came from.

Thai cells stay as the TH post wrote them. A name the map does not list is left
alone, and a cell already carrying a wiki name is not a key, so re-running
changes nothing.
"""

import html
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
PAGE = PROJ / "docs" / "decks.html"
MAP = PROJ / "data" / "deck_wiki_names.json"


def main() -> None:
    names = {k: v for k, v in json.loads(MAP.read_text(encoding="utf-8")).items()
             if not k.startswith("_") and v and v != k}
    page = PAGE.read_text(encoding="utf-8")
    cells = attrs = 0

    def cell(m):
        nonlocal cells
        text = html.unescape(m.group(2))
        if text not in names:
            return m.group(0)
        cells += 1
        return '<td title="%s">%s</td>' % (html.escape(text), html.escape(names[text], quote=False))

    def table(m):
        return re.sub(r"<td( [^>]*)?>([^<]*)</td>", cell, m.group(0))

    page = re.sub(r'<table class="gk-table digimon-table">.*?</table>', table, page, flags=re.S)

    def attr(m):
        nonlocal attrs
        parts = html.unescape(m.group(1)).split("|")
        new = [names.get(p, p) for p in parts]
        if new == parts:
            return m.group(0)
        attrs += 1
        return 'data-na-digimon="%s"' % html.escape("|".join(new))

    page = re.sub(r'data-na-digimon="([^"]*)"', attr, page)
    if cells or attrs:
        PAGE.write_text(page, encoding="utf-8", newline="\n")
    print(f"{PAGE.relative_to(PROJ)}: {cells} cell(s), {attrs} deck filter list(s) renamed")


if __name__ == "__main__":
    main()
