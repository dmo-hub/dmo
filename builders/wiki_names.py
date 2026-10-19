"""Display names for digimon, taken from dmowiki page titles.

The scan data keeps each NA post's own spelling, because the TH/KR enrichers
match on it; pages show the wiki's name instead (data/digimon_wiki_names.json).
"""

import json
from pathlib import Path

_MAP_FILE = Path(__file__).resolve().parent.parent / "data" / "digimon_wiki_names.json"
_MAP = {k: v for k, v in json.loads(_MAP_FILE.read_text(encoding="utf-8")).items()
        if not k.startswith("_")}


def wiki_name(name: str) -> str:
    return _MAP.get(name, name)
