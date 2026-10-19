// Run one expression inside the already-open dmowiki.com tab over raw CDP.
//
//   node fetchers/cdp_eval.js <port> <fn-source-file|-> [json-arg]
//
// Prints {url, title, value} as JSON. With "-" no function runs: only the tab's
// url and title come back, which is how the caller checks the challenge state.
//
// Why not Playwright: connect_over_cdp attaches to every target in the browser,
// and one target that never answers (seen with Chrome 155) hangs the whole
// connect. This talks to the single dmowiki tab and nothing else. It never
// opens, navigates or clicks -- a person passes the challenge in that tab.
"use strict";
const fs = require("fs");

const [port, fnFile, rawArg] = process.argv.slice(2);

async function main() {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const tab = targets.find((t) => t.type === "page" && /^https:\/\/(www\.)?dmowiki\.com\//.test(t.url));
  if (!tab) throw new Error("no dmowiki.com tab");
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = () => bad(new Error("ws error")); });
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  };
  const call = (method, params) => new Promise((ok) => {
    const id = ++seq;
    pending.set(id, ok);
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const r = await call("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.error) throw new Error(r.error.message);
    if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text);
    return r.result.result.value;
  };
  const out = { url: tab.url, title: await evaluate("document.title") };
  if (fnFile !== "-") {
    const fn = fs.readFileSync(fnFile, "utf8");
    out.value = await evaluate(`(${fn})(${rawArg || "null"})`);
  }
  ws.close();
  process.stdout.write(JSON.stringify(out));
}

main().catch((e) => { process.stderr.write(String(e.message || e)); process.exit(1); });
