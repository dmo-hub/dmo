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
 *   reference model on every cross-checked case.
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
    "head", "fashion", "top", "bottom", "gloves", "shoes", "keyring"
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
    keyring:  { label: "\u0e04\u0e35\u0e22\u0e4c\u0e23\u0e34\u0e07", group: "\u0e2d\u0e37\u0e48\u0e19 \u0e46" }
  };

  /* Wearing order within each group, so the dropdown reads head-to-toe rather
     than following the internal SLOTS order. */
  var SLOT_ORDER = [
    "head", "top", "bottom", "gloves", "shoes", "fashion",
    "ring", "necklace", "bracelet", "earring", "glasses", "wing", "keyring"
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
     numbers -- 7.05% would otherwise make state keys float-unstable. */
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

  /* A state key packs the targeted stat totals plus the chip count. Every value
     is already capped at its target, so all of them stay small integers. */
  function key(vals, n) { return vals.join("|") + "|" + n; }

  /* Each state remembers the choice that produced it. `prev` is a direct
     reference to the parent state object, never a key lookup: keys are reused
     across phases (an empty slot maps a state onto its own key), so resolving a
     parent by key can walk into itself and loop forever. */
  function solve(data, baseStats, targetHT, targetCT) {
    var accessories = (data && data.accessories) || [];
    var chips = (data && data.chips) || [];

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

    var zero = axes.map(function () { return 0; });
    var states = {};
    states[key(zero, 0)] = { at: 0, v: zero, n: 0, prev: null, pick: null };

    // Advance one state by one item, capping every axis at its target.
    function advance(st, it) {
      return axes.map(function (stat, i) {
        return Math.min(caps[i], st.v[i] + scale(stat, it[stat]));
      });
    }

    // --- accessories: exactly one choice per slot, "leave empty" included ---
    SLOTS.forEach(function (slot) {
      var candidates = accessories.filter(function (it) { return it.slot === slot; });
      var next = {};
      Object.keys(states).forEach(function (k) {
        var st = states[k];
        // empty slot
        var ek = key(st.v, st.n);
        if (!next[ek] || next[ek].at < st.at) {
          next[ek] = { at: st.at, v: st.v, n: st.n, prev: st, pick: null };
        }
        candidates.forEach(function (it) {
          var v = advance(st, it);
          var at = st.at + num(it.AT);
          var nk = key(v, st.n);
          if (!next[nk] || next[nk].at < at) {
            next[nk] = { at: at, v: v, n: st.n, prev: st, pick: it };
          }
        });
      });
      states = next;
    });

    // --- chips: 0/1 knapsack over the pool, capped at MAX_CHIPS ---
    chips.forEach(function (it) {
      var next = {};
      // carry every state forward unchanged (this chip not taken)
      Object.keys(states).forEach(function (k) { next[k] = states[k]; });
      Object.keys(states).forEach(function (k) {
        var st = states[k];
        if (st.n >= MAX_CHIPS) return;
        var v = advance(st, it);
        var at = st.at + num(it.AT);
        var nk = key(v, st.n + 1);
        if (!next[nk] || next[nk].at < at) {
          next[nk] = { at: at, v: v, n: st.n + 1, prev: st, pick: it, chip: true };
        }
      });
      states = next;
    });

    // --- pick the winner ---
    var best = null;
    var bestShort = null;
    Object.keys(states).forEach(function (k) {
      var st = states[k];
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

    var feasible = !!best;
    var winner = best || (bestShort && bestShort.st);
    if (!winner) return null;

    return buildResult(winner, base, feasible, bestShort, axes);
  }

  /* Walk the parent chain back to the root, collecting the picks. Following
     object references means the chain is acyclic by construction — it can only
     ever run backwards through states that were actually built. */
  function buildResult(winner, base, feasible, bestShort, axes) {
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
    var totals = { AT: base.AT + picked.reduce(function (a, it) { return a + num(it.AT); }, 0) };
    STATS.forEach(function (stat) {
      var acc = scale(stat, base[stat]);
      picked.forEach(function (it) { acc += scale(stat, it[stat]); });
      totals[stat] = unscale(stat, acc);
    });

    var out = {
      feasible: feasible,
      result: {
        accessories: accessoriesOut,
        chips: chosenChips,
        totals: totals,
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

  /* Decision 02 scoped the optimizer to DIGIMON stats. Tamer gear reaches
     values ~10x larger on the same axis names, so leaving it in the pool makes
     the solver pick it every time and hand back a loadout whose numbers never
     reach the digimon. Rows the wiki never placed on an axis are the same
     hazard with the added twist that nobody knows which way they fall.

     Rows carrying no axis mark at all are hand-entered and stay: the player
     typed those numbers, so they are the player's to judge. */
  function scorableAxis(it) {
    var ax = it && it.regAxis;
    if (!ax) return true;
    return ax === "digimon";
  }

  function dropOffAxis(data) {
    var kept = [], dropped = [];
    ((data && data.accessories) || []).forEach(function (it) {
      (scorableAxis(it) ? kept : dropped).push(it);
    });
    return {
      data: { accessories: kept, chips: (data && data.chips) || [] },
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
    solve: solve,
    findDuplicateIds: findDuplicateIds,
    applyUpgradeLevels: applyUpgradeLevels,
    dropOffAxis: dropOffAxis,
    scorableAxis: scorableAxis,
  };
})(typeof window !== "undefined" ? window : globalThis);
