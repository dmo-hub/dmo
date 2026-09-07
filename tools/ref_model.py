"""Independent reference model for the gear optimizer, as an ILP.

Why this exists
    docs/js/gear-solver.js is a cap-DP: it collapses every state whose targeted
    stats already clear their floor into one, which is what keeps the table
    small enough to run in a browser. That collapse is the whole reason the DP
    is fast, and also the thing most likely to be subtly wrong -- a bad cap
    silently merges two states that were not interchangeable, and the answer
    comes back plausible.

    An ILP cannot make that mistake, because it never merges anything. It is a
    different paradigm solved by a different engine (CBC), so agreeing with it
    is real evidence rather than the DP checking its own arithmetic.

    The DP's header has claimed agreement with "the PuLP reference model" since
    it was written, but no such model was ever in the repo. This is it.

Model
    x[i]        1 if item i is worn                       (binary)
    c[j]        1 if chip j is taken                      (binary)
    y[s,p]      1 if set s is credited at threshold p     (binary)

    one item per slot          sum(x[i] for i in slot) <= 1
    chip budget                sum(c) <= MAX_CHIPS
    set threshold linking      p * y[s,p] <= sum(x[i] for i in pieces of s)
    stat floor                 base + gear + chips + bonus >= target

    maximize AT (gear + chips + set bonus)

    The linking constraint only forces y DOWN -- y may sit at 0 even with the
    pieces worn. That is safe here precisely because y never hurts: it appears
    with a positive coefficient in the objective and on the left of every
    floor, so the optimizer raises it whenever it legally can. Encoding the
    other direction would need a second constraint per threshold and buy
    nothing.

Scope
    Deliberately NOT a reimplementation of the DP's fallback path. When no
    loadout can meet the floors the DP returns a best-effort "least shortfall"
    answer; this model just reports infeasible. Cross-checks therefore compare
    feasible cases only, which is where a wrong answer would actually mislead.
"""

import json
import sys
from pathlib import Path

import pulp

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent

# Mirrors of the JS constants. Kept as literals rather than parsed out of the
# JS: a reference model that reads its rules from the thing it is checking is
# not independent of it.
SLOTS = [
    "ring", "necklace", "bracelet", "earring", "glasses", "wing",
    "head", "fashion", "top", "bottom", "gloves", "shoes", "keyring",
    "digivice", "aura",
]
STATS = ["HT", "CT", "DS", "DE", "EV", "BL"]
PCT_STATS = {"CT"}
MAX_CHIPS = 8


def scale(stat, v):
    """Percent stats carry 2 decimals; integers keep CBC off floating point."""
    v = float(v or 0)
    return int(round(v * 100)) if stat in PCT_STATS else int(round(v))


def index_sets(sets):
    """(owner, bonus, pieces-per-set) from docs/set_registry.json."""
    owner = {}
    bonus = {}
    for s in sets or []:
        for sl in s.get("slots") or []:
            for name in sl.get("accepts") or []:
                owner[name] = s["set"]
        for b in s.get("bonuses") or []:
            add = {}
            for e in b.get("effects") or []:
                if e.get("scoreable"):
                    add[e["stat"]] = add.get(e["stat"], 0) + e["value"]
            bonus[(s["set"], b["pieces"])] = add
    return owner, bonus


def solve(data, base_stats, targets):
    accessories = list(data.get("accessories") or [])
    chips = list(data.get("chips") or [])
    owner, bonus = index_sets(data.get("sets"))

    base = {st: float((base_stats or {}).get(st) or 0) for st in STATS}
    base["AT"] = float((base_stats or {}).get("AT") or 0)

    prob = pulp.LpProblem("gear", pulp.LpMaximize)

    x = [pulp.LpVariable(f"x{i}", cat="Binary") for i in range(len(accessories))]
    c = [pulp.LpVariable(f"c{j}", cat="Binary") for j in range(len(chips))]
    y = {k: pulp.LpVariable(f"y{k[0]}_{k[1]}", cat="Binary") for k in bonus}

    for slot in SLOTS:
        members = [x[i] for i, it in enumerate(accessories) if it.get("slot") == slot]
        if members:
            prob += pulp.lpSum(members) <= 1, f"slot_{slot}"

    if chips:
        prob += pulp.lpSum(c) <= MAX_CHIPS, "chip_budget"

    # A set is credited at threshold p only if at least p of its pieces are worn.
    for (name, pieces) in bonus:
        worn = [x[i] for i, it in enumerate(accessories)
                if owner.get(it.get("name")) == name]
        prob += pieces * y[(name, pieces)] <= pulp.lpSum(worn), f"set_{name}_{pieces}"

    def total(stat):
        gear = pulp.lpSum(scale(stat, it.get(stat)) * x[i]
                          for i, it in enumerate(accessories))
        chip = pulp.lpSum(scale(stat, it.get(stat)) * c[j]
                          for j, it in enumerate(chips))
        sets = pulp.lpSum(scale(stat, add.get(stat, 0)) * y[k]
                          for k, add in bonus.items() if add.get(stat))
        return gear + chip + sets

    for stat, want in (targets or {}).items():
        if stat not in STATS:
            continue
        need = scale(stat, want) - scale(stat, base.get(stat, 0))
        if need > 0:
            prob += total(stat) >= need, f"floor_{stat}"

    prob += total("AT")

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        return None

    picked = [accessories[i] for i in range(len(accessories)) if x[i].value() > 0.5]
    taken = [chips[j] for j in range(len(chips)) if c[j].value() > 0.5]

    totals = {}
    for stat in STATS + ["AT"]:
        got = sum(float(it.get(stat) or 0) for it in picked)
        got += sum(float(it.get(stat) or 0) for it in taken)
        for k, add in bonus.items():
            if add.get(stat) and y[k].value() > 0.5:
                got += add[stat]
        totals[stat] = base.get(stat, 0) + got

    return {
        "at": round(totals["AT"] - base["AT"], 4),
        "totals": totals,
        "accessories": sorted(it.get("name") for it in picked),
        "chips": sorted(it.get("name") for it in taken),
        "sets": sorted(f"{k[0]}:{k[1]}" for k in bonus if y[k].value() > 0.5),
    }


def main():
    payload = json.load(sys.stdin)
    out = solve(payload["data"], payload.get("base") or {}, payload.get("targets") or {})
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
