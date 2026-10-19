"""Save the gear picker's item pictures from dmowiki.com into docs/img/gear/.

Reads the `iconWiki` paths that builders/build_gear_registry.py records, and
downloads each one not yet on disk through the same Chrome tab the page
fetcher uses: dmowiki puts its /images/ behind the same Cloudflare challenge as
its pages, so a plain request gets the challenge page, not the picture. A
person solves the CAPTCHA in that tab; this script never does.

    python fetchers/fetch_dmowiki_images.py            # fetch missing pictures
    python fetchers/fetch_dmowiki_images.py --dry-run  # list them only
    python builders/build_gear_registry.py              # then link them in

Needs Chrome on --remote-debugging-port=9222 with a dmowiki.com tab open.
"""

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "builders"))
sys.path.insert(0, str(PROJ / "fetchers"))

from build_gear_registry import ICON_DIR, OUT as REGISTRY, icon_filename  # noqa: E402
from fetch_dmowiki_pages import CDP_URL, ORIGIN, ChallengeError  # noqa: E402

# Bytes cross the CDP boundary as base64; the content type is returned too so a
# challenge page served with 200 is caught instead of saved as a .png.
JS_FETCH_BYTES = """async (url) => {
  const r = await fetch(url, {credentials: "include"});
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return {status: r.status, type: r.headers.get("content-type") || "", b64: btoa(s)};
}"""


class RawTab:
    """The dmowiki tab driven through fetchers/cdp_eval.js. Playwright's
    connect_over_cdp attaches to every target in the browser and hangs on one
    that never answers; this touches only the dmowiki tab."""

    def __init__(self) -> None:
        self.port = CDP_URL.rsplit(":", 1)[-1]
        self._fn = {}
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
        cmd = ["node", str(PROJ / "fetchers" / "cdp_eval.js"), self.port, fn_file]
        if arg is not None:
            cmd.append(json.dumps(arg))
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=60)
        if r.returncode:
            sys.exit(f"ERROR: {r.stderr.strip()} -- open https://dmowiki.com in the Chrome "
                     f"on {CDP_URL} and pass its challenge.")
        return json.loads(r.stdout)

    def evaluate(self, js: str, arg):
        if js not in self._fn:
            f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
            f.write(js)
            f.close()
            self._fn[js] = f.name
        return self._run(self._fn[js], arg)["value"]


def wanted() -> dict[str, str]:
    items = json.loads(REGISTRY.read_text(encoding="utf-8"))["items"]
    return {icon_filename(i["iconWiki"]): i["iconWiki"] for i in items if i.get("iconWiki")}


def fetch_one(page, wiki_path: str, out: Path) -> bool:
    res = page.evaluate(JS_FETCH_BYTES, ORIGIN + wiki_path)
    if res["status"] == 403 or res["type"].startswith("text/html"):
        raise ChallengeError(f"{wiki_path} answered {res['status']} {res['type']} -- challenge again?")
    if res["status"] != 200 or not res["type"].startswith("image/"):
        print(f"  skip {wiki_path}: {res['status']} {res['type']}")
        return False
    out.write_bytes(base64.b64decode(res["b64"]))
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--force", action="store_true", help="refetch even if saved")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    args = ap.parse_args()

    files = wanted()
    todo = {f: p for f, p in files.items() if args.force or not (ICON_DIR / f).exists()}
    print(f"{len(files)} pictures, {len(todo)} to fetch")
    if args.dry_run:
        for f, p in todo.items():
            print(f"  {p} -> {(ICON_DIR / f).relative_to(PROJ)}")
        return

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    ok, failed = 0, []
    page = RawTab()
    print(f"Using tab: {page.url}")
    try:
        for n, (f, path) in enumerate(todo.items()):
            if fetch_one(page, path, ICON_DIR / f):
                ok += 1
            else:
                failed.append(path)
            if n + 1 < len(todo):
                time.sleep(args.delay)
    except ChallengeError as e:
        sys.exit(f"\nSTOPPED after {ok}: {e}\nPass the challenge in Chrome and re-run; saved files are kept.")

    print(f"\n--- fetched {ok}, failed {len(failed)} ---")
    for path in failed:
        print(f"  failed: {path}")


if __name__ == "__main__":
    main()
