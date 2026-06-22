"""Local build dashboard — a tiny stdlib HTTP server that runs the project's
build steps from a web UI and streams their output live.

    python tools/build_server.py          # serves http://127.0.0.1:8765
    python tools/build_server.py --port 9000

Throwaway dev tool (like tools/curate.html) — NOT part of CI or the published
site. Binds to localhost only; it shells out to the repo's own scripts, so do
not expose it to a network. No third-party dependency — stdlib http.server +
subprocess + Server-Sent Events for the live log.

Steps (see STEPS):
  pages    deterministic page rebuild from existing data (no network)
  validate python tools/validate.py (full: JSON+HTML+JS+idempotency)
  ruff     ruff format . + ruff check --fix .   (needs ruff on PATH / pipx)
  refresh  network scrape + rebuild — the cloud-safe half (NO scan_digimon,
           NO attribute/image steps; those stay manual). Slow.
"""

import argparse
import io
import json
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
PY = sys.executable
HTML = Path(__file__).resolve().parent / "build.html"
RUFF_VERSION = "0.15.18"  # pinned to match .github/workflows/validate.yml
MAIN_REF = "origin/main"  # the ref the "from main" build checks out

# The deterministic page builders, in dependency order. Reused by the normal
# `pages` step and the worktree-isolated `pages-main` build.
PAGE_BUILDERS = [
    "builders/build_th_seal_en.py",
    "builders/build_seal_tables.py",
    "builders/build_digimon_html.py",
]
# Files the page builders emit under docs/ — copied back from the worktree.
PAGE_OUTPUTS = ["seals.html", "digimon.html", "seal_data.json"]

# Each step is an ordered list of argv lists, run in sequence; a non-zero exit
# stops the step and is reported. The `ruff` step is resolved at run time (see
# _ruff_prefix) because ruff may be a module, a `pipx run`, or absent.
STEPS = {
    "pages": [[PY, b] for b in PAGE_BUILDERS],
    "validate": [
        [PY, "tools/validate.py"],
    ],
    # ruff subcommands; _resolve_steps prepends the runner prefix at run time
    "ruff": [
        ["format", "."],
        ["check", ".", "--fix"],
    ],
    "refresh": [
        [PY, "builders/extract_seal_tables.py"],
        [PY, "builders/build_th_seal_en.py"],
        [PY, "builders/build_seal_tables.py"],
        [PY, "fetchers/fetch_kr_news_index.py"],
        [PY, "fetchers/fetch_th_patch_index.py"],
        [PY, "scanners/scan_kr_digimon_releases.py"],
        [PY, "scanners/scan_th_patch_digimon.py"],
        [PY, "enrichers/enrich_digimon_kr.py"],
        [PY, "enrichers/enrich_digimon_th.py"],
        [PY, "enrichers/enrich_digimon_gameking.py"],
        [PY, "builders/build_digimon_html.py"],
    ],
}


def _ruff_prefix():
    """Resolve how to invoke ruff, preferring the local interpreter's module
    (fast, no download) over pipx (fetches the pinned version on demand).
    Returns the argv prefix, or None if neither is available."""
    if subprocess.run([PY, "-m", "ruff", "--version"], capture_output=True).returncode == 0:
        return [PY, "-m", "ruff"]
    if shutil.which("pipx"):
        return ["pipx", "run", f"ruff=={RUFF_VERSION}"]
    return None


def _resolve_steps(step):
    """Expand a step name into concrete argv lists, or raise RuntimeError with
    a user-facing message the step can't be run (e.g. ruff not installed)."""
    if step == "ruff":
        prefix = _ruff_prefix()
        if prefix is None:
            raise RuntimeError(
                f"ติดตั้ง ruff ก่อน — `pip install ruff=={RUFF_VERSION}` หรือ `pipx install ruff`"
            )
        return [prefix + args for args in STEPS["ruff"]]
    return STEPS.get(step)


def _sse(handler, event, data):
    """Write one Server-Sent Event frame."""
    payload = json.dumps(data) if not isinstance(data, str) else data
    handler.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
    handler.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence default request logging
        pass

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._serve_html()
        elif url.path == "/api/run":
            self._run(parse_qs(url.query).get("step", [""])[0])
        else:
            self.send_error(404)

    def _serve_html(self):
        body = HTML.read_text(encoding="utf-8").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _begin_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def _stream(self, cmd, cwd=PROJ):
        """Run one command, streaming its output as SSE lines. Returns the exit
        code (or None if the executable was not found)."""
        shown = " ".join(c if c != PY else "python" for c in cmd)
        _sse(self, "line", f"$ {shown}")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError as e:
            _sse(self, "line", f"!! cannot run: {e}")
            return None
        for raw in proc.stdout or ():
            _sse(self, "line", raw.rstrip("\n"))
        code = proc.wait()
        if code != 0:
            _sse(self, "line", f"!! exited {code}")
        return code

    def _run(self, step):
        self._begin_sse()
        if step == "pages-main":
            self._run_from_main()
            return
        try:
            cmds = _resolve_steps(step)
        except RuntimeError as e:
            _sse(self, "line", f"!! {e}")
            _sse(self, "done", {"ok": False})
            return
        if not cmds:
            _sse(self, "line", f"!! unknown step: {step}")
            _sse(self, "done", {"ok": False})
            return

        overall_ok = True
        for cmd in cmds:
            if self._stream(cmd):  # non-zero or None → stop
                overall_ok = False
                break
        _sse(self, "done", {"ok": overall_ok})

    def _run_from_main(self):
        """Build the pages from a clean MAIN_REF checkout in a throwaway git
        worktree, then copy the generated docs back. The live working tree is
        never touched. Builders run with cwd = the worktree, so they read main's
        own data/ and write main's docs/ in isolation."""
        wt = Path(tempfile.mkdtemp(prefix="dmo-build-main-"))
        ok = True
        try:
            _sse(self, "line", f"── preparing worktree from {MAIN_REF} ──")
            if self._stream(["git", "fetch", "origin", "main"]) not in (0, None):
                _sse(self, "line", "!! git fetch failed — building from local main ref")
            if self._stream(["git", "worktree", "add", "--detach", str(wt), MAIN_REF]):
                _sse(self, "line", "!! cannot create worktree")
                _sse(self, "done", {"ok": False})
                return

            for b in PAGE_BUILDERS:
                if self._stream([PY, b], cwd=wt):
                    ok = False
                    break

            if ok:
                _sse(self, "line", "── copying generated docs back ──")
                for name in PAGE_OUTPUTS:
                    src = wt / "docs" / name
                    if src.exists():
                        shutil.copy2(src, PROJ / "docs" / name)
                        _sse(self, "line", f"  ← docs/{name}")
                    else:
                        _sse(self, "line", f"  (skip docs/{name} — not produced)")
        finally:
            _sse(self, "line", "── removing worktree ──")
            self._stream(["git", "worktree", "remove", "--force", str(wt)])
            shutil.rmtree(wt, ignore_errors=True)
        _sse(self, "done", {"ok": ok})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"dmo build dashboard → {url}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
