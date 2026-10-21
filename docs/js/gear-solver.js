/* Exact gear optimizer for the DMO accessory/chip loadout problem.
 *
 * Problem
 *   - 12 distinct gear slots (6 accessory + 6 clothing); one item each.
 *   - Chips are one interchangeable pool; at most MAX_CHIPS of them.
 *   - Any stat can be given a floor (hard); overshoot above it is worthless.
 *   - AT has no floor and is maximized.
 *
 * Only the stats the caller actually targets enter the state key. That is not
 * an optimisation detail -- benchmarking on the real registry put two targets
 * at ~1s and four at ~13s, so an untargeted stat riding along in the key is the
 * difference between usable and not.
 *
 * Why a DP and not an ILP
 *   The browser has no CBC. "Overshoot is worthless" lets every state whose
 *   HT/CT already clears the target collapse into one, which is what keeps the
 *   table small. The result is exact, not a heuristic — it agrees with the PuLP
 *   reference model in tools/ref_model.py on every cross-checked case, which
 *   the validate gate re-runs via tools/diff_set_model.py.
 *
 *   ⚠️ This bound only holds while the item list stays small. Benchmarking with
 *   ~400 items (the size of the full wiki registry) blows the table past 6M
 *   states and the solve never returns, at 6 slots as well as 12. Wiring a
 *   registry of that size into the page needs the algorithm replaced first —
 *   dominance filtering plus branch-and-bound solved the same instances in
 *   ~3s. The seed shipped with the page is far smaller, so this DP is still
 *   correct and fast for it.
 *
 * CT is a percentage carried to 2 decimals (7.05, 7.12), so it is quantized to
 * hundredths and kept in integers; floats would make the state keys unstable.
 */
(function (root) {
  "use strict";

  /* Accessory slots first, then the clothing slots. Order is the order the
     result list renders in, so it follows how the game lays the doll out. */
  var SLOTS = [
    "ring", "necklace", "bracelet", "earring", "glasses", "wing",
    "head", "fashion", "top", "bottom", "gloves", "shoes", "keyring",
    "digivice", "aura", "idcard", "xai"
  ];

  /* Thai label and group for each slot. The ID above stays English on purpose:
     it is what sits in localStorage and in every registry row, so renaming it
     would orphan every loadout a player has already saved. */
  var SLOT_GROUPS = ["\u0e0a\u0e38\u0e14", "\u0e1b\u0e23\u0e30\u0e14\u0e31\u0e1a",
                     "\u0e2d\u0e37\u0e48\u0e19 \u0e46"];
  var SLOT_INFO = {
    head:     { label: "\u0e2b\u0e31\u0e27",       group: "\u0e0a\u0e38\u0e14" },
    top:      { label: "\u0e40\u0e2a\u0e37\u0e49\u0e2d",     group: "\u0e0a\u0e38\u0e14" },
    bottom:   { label: "\u0e01\u0e32\u0e07\u0e40\u0e01\u0e07", group: "\u0e0a\u0e38\u0e14" },
    gloves:   { label: "\u0e16\u0e38\u0e07\u0e21\u0e37\u0e2d", group: "\u0e0a\u0e38\u0e14" },
    shoes:    { label: "\u0e23\u0e2d\u0e07\u0e40\u0e17\u0e49\u0e32", group: "\u0e0a\u0e38\u0e14" },
    fashion:  { label: "\u0e40\u0e04\u0e23\u0e37\u0e48\u0e2d\u0e07\u0e41\u0e15\u0e48\u0e07\u0e01\u0e32\u0e22", group: "\u0e0a\u0e38\u0e14" },
    ring:     { label: "\u0e41\u0e2b\u0e27\u0e19",   group: "\u0e1b\u0e23\u0e30\u0e14\u0e31\u0e1a" },
    necklace: { label: "\u0e2a\u0e23\u0e49\u0e2d\u0e22\u0e04\u0e2d", group: "\u0e1b\u0e23\u0e30\u0e14\u0e31\u0e1a" },
    bracelet: { label: "\u0e01\u0e33\u0e44\u0e25",   group: "\u0e1b\u0e23\u0e30\u0e14\u0e31\u0e1a" },
    earring:  { label: "\u0e15\u0e48\u0e32\u0e07\u0e2b\u0e39", group: "\u0e1b\u0e23\u0e30\u0e14\u0e31\u0e1a" },
    glasses:  { label: "\u0e41\u0e27\u0e48\u0e19",   group: "\u0e2d\u0e37\u0e48\u0e19 \u0e46" },
    wing:     { label: "\u0e1b\u0e35\u0e01",     group: "\u0e2d\u0e37\u0e48\u0e19 \u0e46" },
    keyring:  { label: "\u0e04\u0e35\u0e22\u0e4c\u0e23\u0e34\u0e07", group: "\u0e2d\u0e37\u0e48\u0e19 \u0e46" },
    digivice: { label: "\u0e14\u0e34\u0e08\u0e34\u0e44\u0e27\u0e0b\u0e4c", group: "\u0e2d\u0e37\u0e48\u0e19 \u0e46" },
    aura:     { label: "\u0e2d\u0e2d\u0e23\u0e48\u0e32", group: "\u0e2d\u0e37\u0e48\u0e19 \u0e46" },
    idcard:   { label: "ID Card", group: "\u0e2d\u0e37\u0e48\u0e19 \u0e46" },
    xai:      { label: "XAI",     group: "\u0e2d\u0e37\u0e48\u0e19 \u0e46" }
  };

  /* Wearing order within each group, so the dropdown reads head-to-toe rather
     than following the internal SLOTS order. */
  var SLOT_ORDER = [
    "head", "top", "bottom", "gloves", "shoes", "fashion",
    "ring", "necklace", "bracelet", "earring",
    "glasses", "wing", "keyring", "digivice", "aura", "idcard", "xai"
  ];

  function slotsInGroup(group) {
    return SLOT_ORDER.filter(function (s) {
      return SLOT_INFO[s] && SLOT_INFO[s].group === group;
    });
  }

  function slotLabel(slot) {
    var info = SLOT_INFO[slot];
    return info ? info.label : String(slot);
  }

  function slotGroup(slot) {
    var info = SLOT_INFO[slot];
    return info ? info.group : SLOT_GROUPS[SLOT_GROUPS.length - 1];
  }
  /* A character has eight chip sockets. This is a property of the character,
     not of the gear -- the per-item "Attribute Slot" numbers on the wiki count
     something else, and summing those across a loadout would reach 42. */
  var MAX_CHIPS = 8;

  /* Stats that are percentages are held as hundredths so the DP works in whole
     numbers -- 7.05% would otherwise make state keys float-unstable. The gear
     page reads this list too; tools/validate.py checks it against
     builders/stat_units.py, which the Python side uses. */
  var PCT_STATS = { CT: true, EV: true, BL: true };
  var STATS = ["HT", "CT", "DS", "DE", "EV", "BL"];

  var ct100 = function (v) { return Math.round((Number(v) || 0) * 100); };
  var num = function (v) { return Number(v) || 0; };

  function scale(stat, v) {
    return PCT_STATS[stat] ? ct100(v) : Math.round(num(v));
  }
  function unscale(stat, v) {
    return PCT_STATS[stat] ? v / 100 : v;
  }

  /* A state key packs the targeted stat totals, the chip count and the piece
     count of each set the current plan tracks. Every value is capped (stats at
     their target, counts at the set's top threshold), so all stay small. */
  function key(vals, n, counts) {
    return vals.join("|") + "|" + n + "|" + counts.join(",");
  }

  /* Partition the sets into groups that share at least one slot. Sets in one
     group compete for the same slots, so a loadout can complete at most one of
     them; sets in different groups (Last Evolution sits on its own two
     accessory slots) can pay out together. Union-find over the slot lists. */
  function groupSets(sets) {
    var parent = {};
    function find(a) {
      while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; }
      return a;
    }
    (sets || []).forEach(function (s) { parent[s.set] = s.set; });
    var owners = {};
    (sets || []).forEach(function (s) {
      (s.slots || []).forEach(function (sl) {
        if (owners[sl.slot] !== undefined) {
          var a = find(owners[sl.slot]), b = find(s.set);
          if (a !== b) parent[a] = b;
        } else {
          owners[sl.slot] = s.set;
        }
      });
    });
    var group = {};
    (sets || []).forEach(function (s) { group[s.set] = find(s.set); });
    return group;
  }

  /* Each state remembers the choice that produced it. `prev` is a direct
     reference to the parent state object, never a key lookup: keys are reused
     across phases (an empty slot maps a state onto its own key), so resolving a
     parent by key can walk into itself and loop forever. */
  /* Flatten docs/set_registry.json into the two lookups the DP needs: which
     set an item belongs to, and what a given count of that set is worth. */
  function indexSets(sets) {
    var owner = {}, bonus = {}, label = {}, proc = {}, thresholds = {};
    (sets || []).forEach(function (s) {
      label[s.set] = s.set_th || s.set;
      (s.slots || []).forEach(function (sl) {
        (sl.accepts || []).forEach(function (name) { owner[name] = s.set; });
      });
      (s.bonuses || []).forEach(function (b) {
        var add = {};
        (b.effects || []).forEach(function (e) {
          if (e.scoreable) add[e.stat] = (add[e.stat] || 0) + e.value;
        });
        bonus[s.set + ":" + b.pieces] = add;
        proc[s.set + ":" + b.pieces] = !b.permanent;
        (thresholds[s.set] = thresholds[s.set] || []).push(Number(b.pieces) || 0);
      });
    });
    return { owner: owner, bonus: bonus, label: label, proc: proc,
             thresholds: thresholds, group: groupSets(sets) };
  }

  /* "set:worn" and "set:pieces" are split on the LAST colon: dmowiki names
     some sets with a colon of their own ("Fire : Spirit"). */
  function splitPair(pair) {
    var i = pair.lastIndexOf(":");
    return [pair.slice(0, i), pair.slice(i + 1)];
  }

  /* What a state's set progress is worth right now. Bonuses stack by
     threshold: six pieces earns the 4-set bonus as well as the 6-set one,
     which is how the wiki lists them. */
  function setBonusFor(setKey, index) {
    var out = {};
    if (!setKey) return out;
    /* The key now holds one "set:worn" pair per group, comma separated, so a
       clothing set and Last Evolution can both be paying out at once. */
    setKey.split(",").filter(Boolean).forEach(function (pair) {
      var parts = splitPair(pair);
      var name = parts[0], worn = Number(parts[1]);
      Object.keys(index.bonus).forEach(function (k) {
        var kp = splitPair(k);
        if (kp[0] !== name) return;
        if (worn < Number(kp[1])) return;
        var add = index.bonus[k];
        Object.keys(add).forEach(function (st) {
          out[st] = (out[st] || 0) + add[st];
        });
      });
    });
    return out;
  }

  /* The digivice decides how many chips fit (a row's chipCap: loaders 6, true
     digivices 4, the First Digivice 6-8 by level). The chip pool and the
     digivice therefore cannot be chosen apart: each distinct cap is solved
     with only that cap's digivices on offer, and the best answer wins --
     reaching the targets first, then AT, then the smaller shortfall. A
     digivice row with no cap (typed by hand) is offered in every run; with no
     capped digivice at all the old flat MAX_CHIPS applies. */
  function solve(data, baseStats, targetHT, targetCT) {
    var all = (data && data.accessories) || [];
    var caps = [];
    all.forEach(function (it) {
      if (it.slot === "digivice" && it.chipCap > 0 && caps.indexOf(it.chipCap) < 0) caps.push(it.chipCap);
    });
    if (!caps.length) caps = [MAX_CHIPS];
    var best = null;
    caps.forEach(function (cap) {
      var sub = {};
      Object.keys(data || {}).forEach(function (k) { sub[k] = data[k]; });
      sub.accessories = all.filter(function (it) {
        return it.slot !== "digivice" || !(it.chipCap > 0) || it.chipCap === cap;
      });
      var out = solveCapped(sub, baseStats, targetHT, targetCT, cap);
      if (!out) return;
      out.maxChips = cap;
      /* The cap came from wearing one of these digivices, so the answer has
         to wear one even when its stats add nothing the search could see
         (all zero). Stats are never negative, so the totals only grow. */
      var row = out.result.accessories.filter(function (a) { return a.slot === "digivice"; })[0];
      var mine = sub.accessories.filter(function (it) { return it.slot === "digivice" && it.chipCap === cap; });
      if (row && !row.item && mine.length) {
        var pick = mine.slice().sort(function (a, b) { return num(b.AT) - num(a.AT); })[0];
        row.item = pick;
        var t = out.result.totals;
        t.AT += num(pick.AT);
        STATS.forEach(function (st) { t[st] = unscale(st, scale(st, t[st]) + scale(st, pick[st])); });
      }
      if (!best || better(out, best)) best = out;
    });
    return best;
  }

  function better(a, b) {
    if (a.feasible !== b.feasible) return a.feasible;
    var gap = function (o) {
      return Object.keys(o.shortfall || {}).reduce(function (s, k) { return s + o.shortfall[k]; }, 0);
    };
    if (!a.feasible && gap(a) !== gap(b)) return gap(a) < gap(b);
    return a.result.totals.AT > b.result.totals.AT;
  }

  function solveCapped(data, baseStats, targetHT, targetCT, maxChips) {
    var accessories = (data && data.accessories) || [];
    var chips = (data && data.chips) || [];
    var index = indexSets(data && data.sets);

    /* Two call shapes are supported: the original (base, targetHT, targetCT)
       and an object of stat -> floor. The positional form stays because the
       page and the differential tests both still use it. */
    var targets = {};
    if (targetHT && typeof targetHT === "object") {
      targets = targetHT;
    } else {
      targets.HT = num(targetHT);
      targets.CT = num(targetCT);
    }

    var base = { AT: num(baseStats && baseStats.AT) };
    STATS.forEach(function (st) { base[st] = num(baseStats && baseStats[st]); });

    // Only stats with a floor above base need tracking; the rest are free.
    var axes = [];
    var caps = [];
    STATS.forEach(function (st) {
      if (!(st in targets)) return;
      var want = scale(st, targets[st]) - scale(st, base[st]);
      if (want > 0) {
        axes.push(st);
        caps.push(want);
      }
    });

    /* Set progress used to ride in the state key for EVERY set, as a run per
       group. That key is what blew up: the five element-spirit sets share one
       template, so their pieces carry identical stats and differ only in which
       set they feed, and every one of them still forked the table. Adding them
       took a validate case from 3.6 s to past 120 s with every answer correct.

       Instead the search runs once per PLAN: for each group, either no set or
       one named set is tracked. Inside a plan only the tracked sets count
       pieces; every other piece is a plain item -- and plain items with equal or
       worse stats than another item in the same slot can be dropped outright,
       which folds the identical spirit pieces back into one. The best loadout
       over all plans is the answer: a loadout that completes set S is scored in
       full by the plan tracking S, and under-scored (never over-scored) by every
       other plan. */
    /* Chips never belong to a set, so what the pool can add does not depend on
       the plan. Running the chip knapsack inside every plan repeated the same
       work once per plan and on every gear state -- with 18 chips that phase
       was ~99% of a solve. It is built once here as a table of capped gain
       vectors and joined to each plan's finished gear states below. */
    var chipTable = runChips(chips, axes, caps, maxChips);
    var plans = setPlans(data && data.sets, index);
    var best = null;
    var bestShort = null;
    plans.forEach(function (plan) {
      var gear = runPlan(plan, accessories, axes, caps, index);
      Object.keys(gear).forEach(function (k) {
       chipTable.forEach(function (ch) {
        var g = gear[k];
        var st = {
          at: g.at + ch.at,
          v: axes.map(function (stat, i) { return Math.min(caps[i], g.v[i] + ch.v[i]); }),
          gear: g, chips: ch,
        };
        var meets = axes.every(function (stat, i) { return st.v[i] >= caps[i]; });
        if (meets && (!best || st.at > best.at)) best = st;

        // Fallback candidate: least total shortfall, then highest AT. The AT
        // tiebreak is what stops "closest to target" from also meaning "weakest
        // possible" — a pure min-shortfall pass happily leaves free slots empty.
        // Shortfalls are summed in display units so a percentage stat short by 5
        // does not outweigh a flat stat short by 500.
        var short = {};
        var pen = 0;
        axes.forEach(function (stat, i) {
          var gap = Math.max(0, caps[i] - st.v[i]);
          short[stat] = unscale(stat, gap);
          pen += short[stat];
        });
        if (!bestShort || pen < bestShort.pen || (pen === bestShort.pen && st.at > bestShort.st.at)) {
          bestShort = { pen: pen, st: st, short: short };
        }
       });
      });
    });

    var feasible = !!best;
    var joined = best || (bestShort && bestShort.st);
    if (!joined) return null;
    var winner = chainChips(joined);

    return buildResult(winner, base, feasible, bestShort, axes, index);
  }

  /* Every combination of "track nothing / track one set" across the groups. */
  function setPlans(sets, index) {
    var byGroup = {};
    (sets || []).forEach(function (s) {
      var g = index.group[s.set];
      (byGroup[g] = byGroup[g] || []).push(s.set);
    });
    var plans = [[]];
    Object.keys(byGroup).sort().forEach(function (g) {
      var next = [];
      plans.forEach(function (p) {
        next.push(p);
        byGroup[g].forEach(function (name) { next.push(p.concat([name])); });
      });
      plans = next;
    });
    return plans;
  }

  /* ladder[k] = the bonus a tracked set pays with k pieces worn. Bonuses stack
     by threshold: six pieces earns the 4-set bonus as well as the 6-set one,
     which is how the wiki lists them. */
  function bonusLadder(name, index) {
    var top = Math.max.apply(null, [0].concat(index.thresholds[name] || []));
    var ladder = [];
    for (var k = 0; k <= top; k++) {
      var add = {};
      (index.thresholds[name] || []).forEach(function (t) {
        if (k < t) return;
        var b = index.bonus[name + ":" + t] || {};
        Object.keys(b).forEach(function (st) { add[st] = (add[st] || 0) + b[st]; });
      });
      ladder.push(add);
    }
    return ladder;
  }

  /* Keep only the plain items no other plain item in the slot beats. b beats a
     when it is at least as good on every tracked axis and on AT; then any
     loadout wearing a does at least as well wearing b instead, so dropping a
     cannot lose the optimum. Exact ties keep the first, so equal pieces of
     different untracked sets collapse to one. */
  function paretoPlain(items, axes) {
    var vecs = items.map(function (it) {
      return axes.map(function (st) { return scale(st, it[st]); }).concat([num(it.AT)]);
    });
    return items.filter(function (it, i) {
      for (var j = 0; j < items.length; j++) {
        if (j === i) continue;
        var ge = true, gt = false;
        for (var d = 0; d < vecs[i].length; d++) {
          if (vecs[j][d] < vecs[i][d]) { ge = false; break; }
          if (vecs[j][d] > vecs[i][d]) gt = true;
        }
        if (ge && (gt || j < i)) return false;
      }
      return true;
    });
  }

  function runPlan(plan, accessories, axes, caps, index) {
    var ladders = plan.map(function (name) { return bonusLadder(name, index); });
    var tracked = {};
    plan.forEach(function (name, i) { tracked[name] = i; });

    var zero = axes.map(function () { return 0; });
    var zeroCounts = plan.map(function () { return 0; });
    var states = {};
    states[key(zero, 0, zeroCounts)] = { at: 0, v: zero, n: 0, c: zeroCounts,
                                         plan: plan, prev: null, pick: null };

    function step(st, it) {
      var ti = tracked[index.owner[it.name]];
      var c = st.c;
      var bonusAT = 0;
      var gain = axes.map(function (stat) { return scale(stat, it[stat]); });
      if (ti !== undefined && c[ti] < ladders[ti].length - 1) {
        c = c.slice();
        c[ti] += 1;
        var after = ladders[ti][c[ti]], before = ladders[ti][c[ti] - 1];
        axes.forEach(function (stat, i) {
          gain[i] += scale(stat, num(after[stat]) - num(before[stat]));
        });
        bonusAT = num(after.AT) - num(before.AT);
      }
      var v = axes.map(function (stat, i) { return Math.min(caps[i], st.v[i] + gain[i]); });
      return { v: v, c: c, at: st.at + num(it.AT) + bonusAT };
    }

    // --- accessories: exactly one choice per slot, "leave empty" included ---
    SLOTS.forEach(function (slot) {
      var inSlot = accessories.filter(function (it) { return it.slot === slot; });
      var setPieces = inSlot.filter(function (it) { return tracked[index.owner[it.name]] !== undefined; });
      var plain = paretoPlain(inSlot.filter(function (it) {
        return tracked[index.owner[it.name]] === undefined;
      }), axes);
      var candidates = plain.concat(setPieces);
      var next = {};
      Object.keys(states).forEach(function (k) {
        var st = states[k];
        // empty slot: totals and set counts carry over unchanged
        if (!next[k] || next[k].at < st.at) {
          next[k] = { at: st.at, v: st.v, n: st.n, c: st.c, plan: plan, prev: st, pick: null };
        }
        candidates.forEach(function (it) {
          var r = step(st, it);
          var nk = key(r.v, st.n, r.c);
          if (!next[nk] || next[nk].at < r.at) {
            next[nk] = { at: r.at, v: r.v, n: st.n, c: r.c, plan: plan, prev: st, pick: it };
          }
        });
      });
      states = next;
    });

    return states;
  }

  /* Every distinct capped gain the chip pool can add with at most maxChips
     chips, keeping the best AT per gain and dropping any row another row beats
     on every axis and AT (the join only ever wants the better one). */
  function runChips(chips, axes, caps, maxChips) {
    var zero = axes.map(function () { return 0; });
    var states = {};
    states[zero.join("|") + "|0"] = { at: 0, v: zero, n: 0, prev: null, pick: null };
    chips.forEach(function (it) {
      var next = {};
      // carry every state forward unchanged (this chip not taken)
      Object.keys(states).forEach(function (k) { next[k] = states[k]; });
      Object.keys(states).forEach(function (k) {
        var st = states[k];
        if (st.n >= maxChips) return;
        var v = axes.map(function (stat, i) {
          return Math.min(caps[i], st.v[i] + scale(stat, it[stat]));
        });
        var at = st.at + num(it.AT);
        var nk = v.join("|") + "|" + (st.n + 1);
        if (!next[nk] || next[nk].at < at) {
          next[nk] = { at: at, v: v, n: st.n + 1, prev: st, pick: it };
        }
      });
      states = next;
    });
    var byGain = {};
    Object.keys(states).forEach(function (k) {
      var st = states[k], g = st.v.join("|");
      if (!byGain[g] || byGain[g].at < st.at) byGain[g] = st;
    });
    var rows = Object.keys(byGain).map(function (g) { return byGain[g]; });
    return rows.filter(function (a) {
      return !rows.some(function (b) {
        if (b === a || b.at < a.at) return false;
        var strict = b.at > a.at;
        for (var i = 0; i < a.v.length; i++) {
          if (b.v[i] < a.v[i]) return false;
          if (b.v[i] > a.v[i]) strict = true;
        }
        return strict;
      });
    });
  }

  /* A joined answer is a gear state plus a chip row. Re-thread the chip picks
     onto the end of the gear state's parent chain so the result builder walks
     one chain, exactly as it did when chips were the last DP phase. */
  function chainChips(joined) {
    var picks = [];
    for (var node = joined.chips; node && node.prev; node = node.prev) {
      if (node.pick) picks.push(node.pick);
    }
    picks.reverse();
    var tip = joined.gear;
    picks.forEach(function (it) {
      tip = { at: tip.at, v: tip.v, c: tip.c, plan: tip.plan, prev: tip, pick: it, chip: true };
    });
    return { at: joined.at, v: joined.v, c: joined.gear.c, plan: joined.gear.plan,
             prev: tip.prev, pick: tip.pick, chip: tip.chip };
  }

  /* The "set:worn" pairs a state has earned, in the form setBonusFor and the
     result builder read. */
  function setKeyOf(st) {
    return (st.plan || []).map(function (name, i) {
      return st.c[i] > 0 ? name + ":" + st.c[i] : "";
    }).filter(Boolean).sort().join(",");
  }

  /* Walk the parent chain back to the root, collecting the picks. Following
     object references means the chain is acyclic by construction — it can only
     ever run backwards through states that were actually built. */
  function buildResult(winner, base, feasible, bestShort, axes, index) {
    var chosenChips = [];
    var accPicks = [];

    for (var node = winner; node && node.prev; node = node.prev) {
      if (node.pick) (node.chip ? chosenChips : accPicks).push(node.pick);
    }
    accPicks.reverse();
    chosenChips.reverse();

    var bySlot = {};
    accPicks.forEach(function (it) { bySlot[it.slot] = it; });
    var accessoriesOut = SLOTS.map(function (s) {
      return { slot: s, item: bySlot[s] || null };
    });

    var picked = accPicks.concat(chosenChips);

    /* Totals cover every stat, not just the targeted ones: an untargeted stat
       is still worth showing, it just did not need to constrain the search.
       Percentages are summed in hundredths and converted back once, so 7.05 +
       7.12 cannot drift. */
    /* The set bonus has to be added back here. The DP used it to steer the
       search, but these totals are rebuilt from the chosen items alone, so
       leaving it out would report numbers the solver did not actually
       optimise for -- the answer would look worse than the loadout is. */
    var winnerSet = setKeyOf(winner);
    var setBonus = index ? setBonusFor(winnerSet, index) : {};

    var totals = {
      AT: base.AT
        + picked.reduce(function (a, it) { return a + num(it.AT); }, 0)
        + num(setBonus.AT),
    };
    STATS.forEach(function (stat) {
      var acc = scale(stat, base[stat]);
      picked.forEach(function (it) { acc += scale(stat, it[stat]); });
      acc += scale(stat, num(setBonus[stat]));
      totals[stat] = unscale(stat, acc);
    });

    /* Which set the answer completed, and at which thresholds. The page needs
       this to explain a jump in the numbers, and decision 06 requires saying
       that a proc bonus is counted at full value. */
    var setsOut = [];
    if (index && winnerSet) {
      // one "set:worn" pair per group, so more than one set can be earned
      winnerSet.split(",").filter(Boolean).forEach(function (pair) {
      var parts = splitPair(pair);
      var worn = Number(parts[1]);
      Object.keys(index.bonus).forEach(function (k) {
        var kp = splitPair(k);
        if (kp[0] !== parts[0] || worn < Number(kp[1])) return;
        var b = index.bonus[k] || {};
        setsOut.push({
          set: parts[0],
          label: (index.label && index.label[parts[0]]) || parts[0],
          pieces: Number(kp[1]),
          worn: worn,
          /* A proc bonus is one the wiki gates behind a chance and a trigger.
             Decision 06 counts it at full value anyway, so the page has to
             say so -- see the note rendered next to it. */
          proc: !!index.proc[k],
          effects: Object.keys(b).map(function (st) {
            return { stat: st, value: b[st] };
          }),
        });
      });
      });
      setsOut.sort(function (a, b) { return a.pieces - b.pieces; });
    }

    var out = {
      feasible: feasible,
      result: {
        accessories: accessoriesOut,
        chips: chosenChips,
        totals: totals,
        sets: setsOut,
        setBonus: setBonus,
        targeted: (axes || []).slice(),
      },
    };
    if (!feasible && bestShort) {
      out.shortfall = bestShort.short;
    }
    return out;
  }

  /* Item ids must be unique: the UI keys rows by id, and a duplicate would let
     one item be counted twice while occupying a single chip slot. */
  function findDuplicateIds(data) {
    var seen = {}, dupes = [];
    ["accessories", "chips"].forEach(function (group) {
      ((data && data[group]) || []).forEach(function (it) {
        var id = String(it && it.id);
        if (seen[id]) { if (dupes.indexOf(id) < 0) dupes.push(id); }
        seen[id] = true;
      });
    });
    return dupes;
  }

  /* The registry keeps ONE ROW PER UPGRADE LEVEL, and a row can cover a band
     ("0-4" carries upgrade 0 with upgradeMax 4). The solver picks one item per
     slot by score, so feeding it every row would have it "choose" the highest
     level -- recommending a +15 to someone who owns a +3. The level is the
     player's, not the optimizer's, so rows are filtered down to the one band
     that contains each item's locked level before the solve. */
  function levelOf(it) {
    return num(it && (it.upgrade !== undefined ? it.upgrade : it.up));
  }

  function bandContains(it, lvl) {
    var lo = levelOf(it);
    var hi = it && it.upgradeMax !== undefined && it.upgradeMax !== null
      ? num(it.upgradeMax) : lo;
    return lvl >= lo && lvl <= hi;
  }

  /* levels: { "<item name>": <locked level> }. An item with no entry keeps its
     lowest row, which is what an untouched piece is. */
  function applyUpgradeLevels(data, levels) {
    levels = levels || {};
    var out = { accessories: [], chips: (data && data.chips) || [] };
    var groups = {};
    ((data && data.accessories) || []).forEach(function (it) {
      if (!it || it.upgrade === undefined || it.upgrade === null) {
        out.accessories.push(it);
        return;
      }
      var key = String(it.slot) + "\u0000" + String(it.name);
      (groups[key] = groups[key] || []).push(it);
    });
    Object.keys(groups).forEach(function (key) {
      var rows = groups[key].slice().sort(function (a, b) {
        return levelOf(a) - levelOf(b);
      });
      var want = levels[rows[0].name];
      var pick = null;
      if (want !== undefined && want !== null && want !== "") {
        var lvl = num(want);
        for (var i = 0; i < rows.length; i++) {
          if (bandContains(rows[i], lvl)) { pick = rows[i]; break; }
        }
        /* A level above every band means the piece is upgraded further than
           the wiki records; the top band is the closest truth we have. */
        if (!pick) pick = rows[rows.length - 1];
      }
      out.accessories.push(pick || rows[0]);
    });
    return out;
  }

  /* Every row is scored, whatever its axis: the owner counts tamer-side and
     unplaced gear toward the digimon too. The axis mark stays on the rows
     (registry, saved data) so this is one line to narrow again. */
  function scorableAxis() {
    return true;
  }

  function dropOffAxis(data) {
    var kept = [], keptChips = [], dropped = [];
    ((data && data.accessories) || []).forEach(function (it) {
      (scorableAxis(it) ? kept : dropped).push(it);
    });
    ((data && data.chips) || []).forEach(function (it) {
      (scorableAxis(it) ? keptChips : dropped).push(it);
    });
    return {
      data: { accessories: kept, chips: keptChips },
      dropped: dropped
    };
  }

  root.GearSolver = {
    SLOTS: SLOTS,
    SLOT_GROUPS: SLOT_GROUPS,
    SLOT_INFO: SLOT_INFO,
    slotsInGroup: slotsInGroup,
    slotLabel: slotLabel,
    slotGroup: slotGroup,
    MAX_CHIPS: MAX_CHIPS,
    PCT_STATS: PCT_STATS,
    solve: solve,
    findDuplicateIds: findDuplicateIds,
    applyUpgradeLevels: applyUpgradeLevels,
    dropOffAxis: dropOffAxis,
    scorableAxis: scorableAxis,
  };
})(typeof window !== "undefined" ? window : globalThis);
