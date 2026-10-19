"""Which stats are percentages, and how numbers are rounded -- the Python side.

The gear page's solver (docs/js/gear-solver.js) holds percentage stats as
hundredths and rounds with Math.round. Everything in Python that produces or
cross-checks those numbers (the registries, the ILP reference) has to agree
with it exactly, or a value that sits on .5 lands one unit apart in the two
engines. tools/validate.py checks that gear-solver.js's PCT_STATS matches the
set below.
"""

import math

# Percentage stats the solver scores. Scanners that tag units on wiki tables
# add their own extras (MS, EXP ...) on top of this set.
PCT_STATS = frozenset({"CT", "EV", "BL"})

# Percentages keep two decimals (7.05%); the solver works in hundredths.
PCT_DECIMALS = 2


def js_round(value: float, ndigits: int = 0):
    """Round the way JavaScript's Math.round does: halves go up (2.5 -> 3,
    0.125 -> 0.13). Python's round() sends halves to the even neighbour
    (2.5 -> 2), so the two languages would otherwise disagree on exactly the
    values that sit on a boundary."""
    f = 10 ** ndigits
    out = math.floor(value * f + 0.5) / f
    return int(out) if ndigits == 0 else out


def round_stat(stat: str, value: float):
    """A stat as the registries store it: percentages to two decimals, the
    rest to whole numbers."""
    return js_round(value, PCT_DECIMALS) if stat in PCT_STATS else js_round(value)
