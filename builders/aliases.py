"""Central Digimon-name canonicaliser shared by the builders.

Folds the English-dub vs Japanese-romanized spellings of the SAME digimon
onto one key so cross-server data lines up (e.g. Scorpiomon == Anomalocarimon).
The map lives in data/digimon_aliases.json — canonical name -> [alt spellings].

Two entry points:
  norm(name)      -> a comparison key: lower-cased, alphanumerics only, alias-folded.
                     Use this when comparing names across servers.
  canonical(name) -> the canonical *display* spelling for a name (or the name
                     unchanged if it has no alias). Casing/spacing preserved
                     from data/digimon_aliases.json.

Both are tolerant of the "<Name> Seal" / "[Awaken] <Name>" decorations that
appear in seal tables — they strip a trailing " Seal..." and bracketed tags.
"""

import json
import re
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
_ALIAS_PATH = PROJ / "data" / "digimon_aliases.json"


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _strip_decoration(s: str) -> str:
    """Drop a trailing ' Seal...'/' 씰...'/' ซีล...' suffix and [bracketed] tags."""
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\s*(Seal|씰|ซีล).*$", "", s)
    return s.strip()


def _load():
    raw = json.loads(_ALIAS_PATH.read_text(encoding="utf-8"))
    norm_to_canon = {}     # normalized alt key -> canonical display name
    for canon, alts in raw.items():
        if canon.startswith("_"):          # skip _README etc.
            continue
        norm_to_canon[_norm_key(canon)] = canon
        for alt in alts:
            norm_to_canon[_norm_key(alt)] = canon
    return norm_to_canon


_NORM_TO_CANON = _load()


def canonical(name: str) -> str:
    """Canonical display spelling for `name` (unchanged if it has no alias)."""
    base = _strip_decoration(name)
    return _NORM_TO_CANON.get(_norm_key(base), base)


def norm(name: str) -> str:
    """Alias-folded comparison key (lower, alphanumerics only) for `name`."""
    base = _strip_decoration(name)
    key = _norm_key(base)
    canon = _NORM_TO_CANON.get(key)
    return _norm_key(canon) if canon else key
