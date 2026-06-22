# dmo

[![validate](https://github.com/dmo-hub/dmo/actions/workflows/validate.yml/badge.svg)](https://github.com/dmo-hub/dmo/actions/workflows/validate.yml)
[![refresh](https://github.com/dmo-hub/dmo/actions/workflows/refresh.yml/badge.svg)](https://github.com/dmo-hub/dmo/actions/workflows/refresh.yml)

Python scripts that scrape **dmo.gameking.com** (Digimon Masters Online news) plus
the KR (digimonmasters.com) and TH (vplay.in.th) servers to detect game updates —
**New Deck**, **New Digimon**, and **Seal Exchange** announcements. Reports are
generated as static HTML under [`docs/`](docs/) and published via GitHub Pages.

🌐 **Live site:** https://dmo-hub.github.io/dmo/

Not a package — just scripts run directly from the repo root.

## Repo layout

```
fetchers/    # network scrapers (fetch_*)
scanners/    # cache-only parsers (scan_*, reparse_cache, extract_deck_detail)
enrichers/   # add fields to scan_result_digimon.json (enrich_*)
extractors/  # download images per post (extract_*_images)
builders/    # generate HTML report / audit (build_*, diff_report, compare_*)
tools/       # validate.py (CI gate), curate.html (data editor)
data/        # all JSON outputs
docs/        # GitHub Pages output (served from main /docs)
cache/       # raw HTML cache (gitignored, regenerated)
```

All scripts resolve the repo root via `PROJ = Path(__file__).resolve().parent.parent`,
so run them from the repo root with the subfolder prefix.

## Quick start

```bash
pip install -r requirements.txt
playwright install chromium   # only for the CDP fetchers (fetch_dmowiki*, fetch_via_cdp)

# Static checks (no network) — the CI gate
python tools/validate.py            # all checks (JSON + HTML + inline JS + idempotency)
python tools/validate.py --no-build # skip the rebuild/idempotency check

# Rebuild the published pages from existing data
python builders/build_th_seal_en.py
python builders/build_seal_tables.py
python builders/build_digimon_html.py
```

See [CLAUDE.md](CLAUDE.md) for the full command catalog and pipeline architecture.

## Tooling

- **Lint/format:** [Ruff](https://docs.astral.sh/ruff/) — config in [`pyproject.toml`](pyproject.toml).
  A hard gate in CI (pinned `ruff==0.15.18`); run locally with `ruff check .` and `ruff format .`.
- **Runtime deps:** `requests`, `playwright` — pinned in [`requirements.txt`](requirements.txt).

## CI / CD

Two GitHub Actions (never auto-push to `main`):

| Workflow | Trigger | What it does |
|---|---|---|
| [`validate.yml`](.github/workflows/validate.yml) | push / PR | JSON + HTML + inline-JS checks + Ruff lint/format (gate). Writes a run summary to the Actions UI. Gates Pages. |
| [`refresh.yml`](.github/workflows/refresh.yml) | manual (`workflow_dispatch`) | Re-runs the cloud-safe half of the pipeline (seal tables + KR/TH digimon refs), validates, opens a **PR** for review. |

`refresh.yml` deliberately skips the destructive / Chrome-CDP / image-download
steps — those stay local. **Deploy** is GitHub Pages serving `main /docs` directly;
there is no separate deploy workflow.
