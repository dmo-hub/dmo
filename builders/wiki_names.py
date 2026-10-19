"""Display names for digimon, taken from dmowiki page titles.

The scan data keeps each NA post's own spelling, because the TH/KR enrichers
match on it; pages show the wiki's name instead (data/digimon_wiki_names.json).
"""

import json
import re
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
_MAP_FILE = _PROJ / "data" / "digimon_wiki_names.json"
# dmowiki Category:Digimon_Rank_U, saved by hand (see CLAUDE.md, dmowiki steps)
_RANK_U_FILE = _PROJ / "rank_u.html"
_MAP = {k: v for k, v in json.loads(_MAP_FILE.read_text(encoding="utf-8")).items()
        if not k.startswith("_")}


def wiki_name(name: str) -> str:
    return _MAP.get(name, name)


_RANK_U = {t for t in re.findall(r'<li><a href="[^"]+" title="([^"]+)">',
                                 _RANK_U_FILE.read_text(encoding="utf-8"))}


def is_rank_u(name: str) -> bool:
    """Whether dmowiki files this digimon under Rank U. Checked against the
    "Rank : X" lines of the NA posts: every post that states a rank agrees."""
    return wiki_name(name) in _RANK_U
