/* Exact gear optimizer for the DMO accessory/chip loadout problem.
 *
 * Problem
 *   - 6 distinct accessory slots; each takes at most one accessory.
 *   - Chips are one interchangeable pool; at most MAX_CHIPS of them.
 *   - HT and CT must reach their targets (hard); overshoot is worthless.
 *   - AT has no target and is maximized.
 *
 * Why a DP and not an ILP
 *   The browser has no CBC. But "overshoot is worthless" lets every state whose
 *   HT/CT already clears the target collapse into a single state, which bounds
 *   the table: on the real dataset the worst case is ~45k states, trivial to
 *   enumerate. The result is exact, not a heuristic — it agrees with the PuLP
 *   reference model on every cross-checked case.
 *
 * CT is a percentage carried to 2 decimals (7.05, 7.12), so it is quantized to
 * hundredths and kept in integers; floats would make the state keys unstable.
 */
(function (root) {
  "use strict";

  var SLOTS = ["ring", "necklace", "bracelet", "earring", "glasses", "wing"];
  var MAX_CHIPS = 6;

  var ct100 = function (v) { return Math.round((Number(v) || 0) * 100); };
  var num = function (v) { return Number(v) || 0; };

  /* A state key packs (ht, ct, chipCount). ht/ct are already capped at the
     target, so both fit well inside the safe-integer range for any real input. */
  function key(h, c, n) { return h + "|" + c + "|" + n; }

  /* Each state remembers the choice that produced it. `prev` is a direct
     reference to the parent state object, never a key lookup: keys are reused
     across phases (an empty slot maps a state onto its own key), so resolving a
     parent by key can walk into itself and loop forever. */
  function solve(data, baseStats, targetHT, targetCT) {
    var accessories = (data && data.accessories) || [];
    var chips = (data && data.chips) || [];
    var base = {
      AT: num(baseStats && baseStats.AT),
      HT: num(baseStats && baseStats.HT),
      CT: num(baseStats && baseStats.CT),
    };

    // Targets are expressed relative to base, since base is a free constant.
    var tH = Math.max(0, Math.round(num(targetHT) - base.HT));
    var tC = Math.max(0, ct100(targetCT) - ct100(base.CT));

    var states = {};
    states[key(0, 0, 0)] = { at: 0, ht: 0, ct: 0, n: 0, prev: null, pick: null };

    // --- accessories: exactly one choice per slot, "leave empty" included ---
    SLOTS.forEach(function (slot) {
      var candidates = accessories.filter(function (it) { return it.slot === slot; });
      var next = {};
      Object.keys(states).forEach(function (k) {
        var st = states[k];
        // empty slot
        var ek = key(st.ht, st.ct, st.n);
        if (!next[ek] || next[ek].at < st.at) {
          next[ek] = { at: st.at, ht: st.ht, ct: st.ct, n: st.n, prev: st, pick: null };
        }
        candidates.forEach(function (it) {
          var h = Math.min(tH, st.ht + num(it.HT));
          var c = Math.min(tC, st.ct + ct100(it.CT));
          var at = st.at + num(it.AT);
          var nk = key(h, c, st.n);
          if (!next[nk] || next[nk].at < at) {
            next[nk] = { at: at, ht: h, ct: c, n: st.n, prev: st, pick: it };
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
        var h = Math.min(tH, st.ht + num(it.HT));
        var c = Math.min(tC, st.ct + ct100(it.CT));
        var at = st.at + num(it.AT);
        var nk = key(h, c, st.n + 1);
        if (!next[nk] || next[nk].at < at) {
          next[nk] = { at: at, ht: h, ct: c, n: st.n + 1, prev: st, pick: it, chip: true };
        }
      });
      states = next;
    });

    // --- pick the winner ---
    var best = null;
    var bestShort = null;
    Object.keys(states).forEach(function (k) {
      var st = states[k];
      if (st.ht >= tH && st.ct >= tC) {
        if (!best || st.at > best.at) best = st;
      }
      // Fallback candidate: least total shortfall, then highest AT. The AT
      // tiebreak is what stops "closest to target" from also meaning "weakest
      // possible" — a pure min-shortfall pass happily leaves free slots empty.
      // On the shipped dataset it never changes the winner (the DP already
      // keeps only the max-AT state per key), but it is load-bearing for any
      // dataset where two states tie on shortfall with different AT.
      var shortH = Math.max(0, tH - st.ht);
      var shortC = Math.max(0, tC - st.ct) / 100;
      var pen = shortH + shortC;
      if (!bestShort || pen < bestShort.pen || (pen === bestShort.pen && st.at > bestShort.st.at)) {
        bestShort = { pen: pen, st: st, shortH: shortH, shortC: shortC };
      }
    });

    var feasible = !!best;
    var winner = best || (bestShort && bestShort.st);
    if (!winner) return null;

    return buildResult(winner, base, feasible, bestShort);
  }

  /* Walk the parent chain back to the root, collecting the picks. Following
     object references means the chain is acyclic by construction — it can only
     ever run backwards through states that were actually built. */
  function buildResult(winner, base, feasible, bestShort) {
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

    var sum = function (list, stat) {
      return list.reduce(function (a, it) { return a + num(it[stat]); }, 0);
    };
    var sumCT = function (list) {
      return list.reduce(function (a, it) { return a + ct100(it.CT); }, 0);
    };
    var picked = accPicks.concat(chosenChips);

    var totals = {
      AT: base.AT + sum(picked, "AT"),
      HT: base.HT + sum(picked, "HT"),
      CT: (ct100(base.CT) + sumCT(picked)) / 100,
    };

    var out = {
      feasible: feasible,
      result: { accessories: accessoriesOut, chips: chosenChips, totals: totals },
    };
    if (!feasible && bestShort) {
      out.shortfall = { HT: bestShort.shortH, CT: bestShort.shortC };
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

  root.GearSolver = {
    SLOTS: SLOTS,
    MAX_CHIPS: MAX_CHIPS,
    solve: solve,
    findDuplicateIds: findDuplicateIds,
  };
})(typeof window !== "undefined" ? window : globalThis);
