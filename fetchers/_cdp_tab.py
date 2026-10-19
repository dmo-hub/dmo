"""The dmowiki.com tab a person already let past Cloudflare, driven over raw CDP.

Playwright's connect_over_cdp attaches to every target in the browser and hangs
on one that never answers, so the dmowiki fetchers go through
fetchers/cdp_eval.js, which talks to that single tab and nothing else. Every
request runs inside the tab (fetch with the tab's own cookies); nothing here
opens, navigates or clicks -- the challenge is always passed by a person.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
CDP_PORT = "9222"
ORIGIN = "https://dmowiki.com"

JS_FETCH_TEXT = """async (url) => {
  const r = await fetch(url, {credentials: 'same-origin'});
  return {status: r.status, type: r.headers.get('content-type') || '', body: await r.text()};
}"""


class ChallengeError(RuntimeError):
    """Cloudflare clearance is gone; continuing would only collect 403s."""


class RawTab:
    def __init__(self) -> None:
        self._fn: dict[str, str] = {}
        # Give a person who is still clicking the challenge a minute.
        for n in range(30):
            info = self._run("-")
            if "Just a moment" not in info["title"]:
                self.url = info["url"]
                return
            if n == 0:
                print("Waiting for the challenge to be passed in Chrome ...")
            time.sleep(2)
        sys.exit("ERROR: challenge not yet passed -- finish it in Chrome then re-run.")

    def _run(self, fn_file: str, arg=None) -> dict:
        cmd = ["node", str(PROJ / "fetchers" / "cdp_eval.js"), CDP_PORT, fn_file]
        if arg is not None:
            cmd.append(json.dumps(arg))
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=90)
        if r.returncode:
            sys.exit(f"ERROR: {r.stderr.strip()} -- start Chrome with "
                     f"--remote-debugging-port={CDP_PORT}, open {ORIGIN} and pass its challenge.")
        return json.loads(r.stdout)

    def evaluate(self, js: str, arg):
        if js not in self._fn:
            f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
            f.write(js)
            f.close()
            self._fn[js] = f.name
        return self._run(self._fn[js], arg)["value"]

    def get_html(self, url: str) -> tuple[int, str]:
        """(status, body) of a dmowiki page; raises ChallengeError on the challenge."""
        res = self.evaluate(JS_FETCH_TEXT, url)
        if res["status"] == 403 or "Just a moment" in res["body"][:3000]:
            raise ChallengeError(f"challenge on {url} -- pass it again in Chrome")
        return res["status"], res["body"]
