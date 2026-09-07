/* Drive the real gear-solver.js over a batch of cases and print its answers.
   The file ends with an IIFE that falls back to globalThis when there is no
   window, so a plain require() installs GearSolver for us -- no eval needed,
   and the artifact under test is the shipped file, not a copy. */
var fs = require("fs");
require(require("path").join(__dirname, "..", "docs", "js", "gear-solver.js"));

var solver = globalThis.GearSolver;
if (!solver || typeof solver.solve !== "function") {
  console.error("no solver export");
  process.exit(2);
}

var payload = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
var out = payload.cases.map(function (c) {
  var r = solver.solve(payload.data, c.base, c.targets);
  if (!r) return { feasible: false, at: null };
  var res = r.result || {};
  var base = Number((c.base && c.base.AT) || 0);
  return {
    feasible: !!r.feasible,
    /* Report the GAIN over base, which is what the ILP objective maximizes;
       the JS totals include the base AT the caller passed in. */
    at: Number((res.totals && res.totals.AT) || 0) - base,
    totals: res.totals,
    sets: (res.sets || []).map(function (s) { return s.set + ":" + s.pieces; }),
    worn: (res.accessories || []).filter(function (a) { return a.item; })
                                 .map(function (a) { return a.item.name; })
  };
});
process.stdout.write(JSON.stringify(out));
