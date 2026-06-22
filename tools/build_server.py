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
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
PY = sys.executable
HTML = Path(__file__).resolve().parent / "build.html"

# Each step is an ordered list of argv lists, run in sequence; a non-zero exit
# stops the step and is reported. `ruff` is split out because it may not be
# installed — we try `ruff` then `python -m ruff`.
STEPS = {
    "pages": [
        [PY, "builders/build_th_seal_en.py"],
        [PY, "builders/build_seal_tables.py"],
        [PY, "builders/build_digimon_html.py"],
    ],
    "validate": [
        [PY, "tools/validate.py"],
    ],
    "ruff": [
        [PY, "-m", "ruff", "format", "."],
        [PY, "-m", "ruff", "check", ".", "--fix"],
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

    def _run(self, step):
        cmds = STEPS.get(step)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        if not cmds:
            _sse(self, "line", f"!! unknown step: {step}")
            _sse(self, "done", {"ok": False})
            return

        overall_ok = True
        for cmd in cmds:
            shown = " ".join(c if c != PY else "python" for c in cmd)
            _sse(self, "line", f"$ {shown}")
            try:
                proc = subprocess.Popen(
                    cmd, cwd=PROJ, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                    errors="replace", bufsize=1,
                )
            except FileNotFoundError as e:
                _sse(self, "line", f"!! cannot run: {e}")
                overall_ok = False
                break
            for raw in proc.stdout:
                _sse(self, "line", raw.rstrip("\n"))
            code = proc.wait()
            if code != 0:
                _sse(self, "line", f"!! exited {code}")
                overall_ok = False
                break
        _sse(self, "done", {"ok": overall_ok})


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
