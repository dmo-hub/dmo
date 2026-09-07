"""B05 differential: cap-DP (JS) vs ILP reference (PuLP), WITH set effects.

Cross-checks the two engines on random targets over the real registry plus the
real set registry, so set thresholds are actually crossed rather than assumed.
Compares feasibility and AT; the DP's least-shortfall fallback is out of scope
(the ILP just reports infeasible), so infeasible cases only check that both
agree it is infeasible.
"""
import io
import json
import os
import random
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)

import ref_model  # noqa: E402


def load(p):
    return json.load(io.open(os.path.join(PROJ, p), encoding="utf-8"))


items = load("docs/gear_items.json")
sets = load("docs/set_registry.json")
set_rows = sets if isinstance(sets, list) else sets.get("sets") or []

data = {
    "accessories": items.get("accessories") or [],
    "chips": items.get("chips") or [],
    "sets": set_rows,
}

# The shipped seed has no clothing, so no set could ever complete. Add the real
# set pieces from the registry -- these are the items the page itself offers
# once a set is worn, and their stats come from the registry, not invented.
owner, bonus = ref_model.index_sets(set_rows)
have = {it.get("name") for it in data["accessories"]}
added = 0
for s in set_rows:
    for sl in s.get("slots") or []:
        name = sl.get("item")
        if not name or name in have:
            continue
        row = {"id": "set_%d" % added, "name": name, "slot": sl.get("slot")}
        for st, v in (sl.get("stats") or {}).items():
            row[st] = v
        data["accessories"].append(row)
        have.add(name)
        added += 1

random.seed(2026)
cases = []
for _ in range(int(os.environ.get("N", "12"))):
    targets = {}
    for st in ("HT", "CT", "AT"):
        if st == "AT":
            continue
        if random.random() < 0.8:
            targets[st] = (random.randint(0, 9000) if st == "HT"
                           else round(random.uniform(0, 40), 2))
    cases.append({
        "base": {"AT": random.choice([0, 500]), "HT": random.choice([0, 1000])},
        "targets": targets,
    })

# A random corpus always affords the full six pieces, so it never lands on a
# PARTIAL set -- and a threshold off-by-one ties on AT by reaching the same
# bonus legitimately. Append a variant with one set slot emptied, which forces
# the 5-piece state where crediting one early actually diverges.
variants = [(data, cases)]
victim_set = "T.K-Light of Hope"
victim_slot = None
for s_ in set_rows:
    if s_["set"] == victim_set and (s_.get("slots") or []):
        victim_slot = s_["slots"][-1].get("slot")
if victim_slot:
    broken = dict(data)
    broken["accessories"] = [it for it in data["accessories"]
                             if not (owner.get(it.get("name")) == victim_set
                                     and it.get("slot") == victim_slot)]
    variants.append((broken, [{"base": {"AT": 0, "HT": 0}, "targets": t}
                              for t in ({"HT": 3000}, {"HT": 0}, {"CT": 10.0})]))

bad = feas = total = 0
for vi, (vdata, vcases) in enumerate(variants):
    json.dump({"data": vdata, "cases": vcases},
              io.open(SP + "/.diff_cases.json", "w", encoding="utf-8"),
              ensure_ascii=False)
    r = subprocess.run(["node", SP + "/diff_set_model.js", SP + "/.diff_cases.json"],
                       capture_output=True, text=True, encoding="utf-8", cwd=PROJ)
    if r.returncode:
        print("NODE ERR", r.stderr[:600])
        sys.exit(1)
    js = json.loads(r.stdout)

    for i, (c, j) in enumerate(zip(vcases, js)):
        total += 1
        tag = "v%d#%d" % (vi, i)
        p = ref_model.solve(vdata, c["base"], c["targets"])
        pf, jf = (p is not None), bool(j["feasible"])
        if pf:
            feas += 1
        if pf != jf:
            bad += 1
            print("FEAS MISMATCH %s %s -> pulp=%s js=%s" % (tag, c["targets"], pf, jf))
            continue
        if pf and abs(p["at"] - j["at"]) > 1e-6:
            bad += 1
            print("AT MISMATCH %s %s -> pulp=%s js=%s"
                  % (tag, c["targets"], p["at"], j["at"]))
            print("   pulp sets=%s" % p["sets"])
            print("   js   sets=%s" % j["sets"])
            continue

        # AT alone is too coarse: two loadouts can tie on AT while crediting
        # different thresholds. Also check every threshold the JS claims is
        # actually backed by that many worn pieces.
        if pf:
            worn = {}
            for name in j.get("worn") or []:
                o = owner.get(name)
                if o:
                    worn[o] = worn.get(o, 0) + 1
            for t in j["sets"]:
                nm, _, pc = t.rpartition(":")
                if worn.get(nm, 0) < int(pc):
                    bad += 1
                    print("SET CREDIT %s: js claims %s with only %d worn"
                          % (tag, t, worn.get(nm, 0)))

print("=== %d cases (%d feasible), mismatches: %d ===" % (total, feas, bad))
sys.exit(1 if bad else 0)
