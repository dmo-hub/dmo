# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A set of Python scripts that scrape **dmo.gameking.com** (Digimon Masters Online news site) to detect game updates — currently "New Deck" and "New Digimon" announcements — across `EventView` and `PatchNote` posts. Reports are published as static HTML under `docs/` and served as GitHub Pages. Not a package — just scripts run directly from the repo root.

The site is structured as a hub: `docs/index.html` is a landing page linking to topic-specific reports (`docs/decks.html`, `docs/digimon.html`, `docs/seals.html`, and future ones like `docs/system.html`). `docs/seals.html` is a cross-server Seal-Exchange feed (NA/KR/TH) with the per-patch exchange tables auto-extracted by `builders/extract_seal_tables.py` + `build_seal_tables.py` (see command #15).

## Repo layout

Scripts are grouped by pipeline stage so it's easy to locate a step:

```
fetchers/    # network scrapers (fetch_*)
scanners/    # cache-only parsers (scan_*, reparse_cache, extract_deck_detail)
enrichers/   # add fields to scan_result_digimon.json (enrich_*, apply_image_choices)
extractors/  # download images per post (extract_*_images)
builders/    # generate HTML report / audit (build_digimon_html, diff_report, compare_digimon_sources)
data/        # all JSON outputs (scan_result*, kr_*, th_*, diff)
docs/        # GitHub Pages output (index.html, decks.html, digimon.html, img/)
cache/       # raw HTML cache (regenerated; gitignored)
```

All scripts use `PROJ = Path(__file__).resolve().parent.parent` so they
resolve the repo root regardless of which subfolder they live in. JSON paths
are `PROJ / "data" / "<name>.json"`. Run scripts from the repo root using the
subfolder prefix (e.g. `python scanners/scan_digimon.py`).

## Common commands

```powershell
# 0. THE usual entry point — run the whole refresh (fetch all 3 servers,
#    enrich, rebuild every page, validate) in the right order:
python tools/refresh.py                     # everything
python tools/refresh.py --servers th        # one server's fetch leg only
python tools/refresh.py --no-fetch          # re-run enrich/build only (no network)
#    (Chrome-CDP steps — dmowiki attributes #11-12 — stay manual.)

# 1. Full scrape + parse (network) — populates cache/ and writes data/scan_result.json
#    Exits 1 without writing when the gameking list comes back empty (site
#    unreachable), so refresh.py stops instead of wiping every deck match.
python scanners/scan_decks.py

# 2. Re-parse only from cached HTML (no network) — use after tweaking parser logic
python scanners/reparse_cache.py

# 3. Inspect Digimon List / Effect tables for specific cached posts
python scanners/extract_deck_detail.py event 635 770 patch 4148

# 4. Compare data/scan_result.json against docs/decks.html (find missed/extra posts)
python builders/diff_report.py

# 5. Scan cache for "[New Digimon ...]" markers → data/scan_result_digimon.json
python scanners/scan_digimon.py

# 6. Extract banner image per post → docs/img/digimon/<idx>.<ext>; updates JSON's `image` field
python extractors/extract_digimon_images.py

# 7. Generate docs/digimon.html from data/scan_result_digimon.json (uses `image` if present)
python builders/build_digimon_html.py

# 8. Scrape KR news board list (digimonmasters.com Btype=Update) → data/kr_news_index.json
#    Every page is re-fetched (a new post shifts the whole board) and parsed one
#    <li> at a time: the last row of each page carries a broken class attribute
#    and same-day posts show "today HH:MM", which a whole-item regex ran across.
python fetchers/fetch_kr_news_index.py

# 9. Fetch each KR update post body & extract `[ 신규 디지몬 추가 - <name> ]` markers
#    → data/kr_digimon_releases.json (the authoritative KR-release list)
python scanners/scan_kr_digimon_releases.py

# 10. Match EN ↔ KR by content (EN→KR keyword dict + date tiebreaker)
#     → adds `source_kr` to data/scan_result_digimon.json
python enrichers/enrich_digimon_kr.py

# 10b. Extract KR-side digimon image from each KR post body → docs/img/digimon/<idx>_kr.<ext>
python extractors/extract_kr_digimon_images.py

# 10c. Thai-server (vplay.in.th) pipeline. Thai lags NA/KR by 10–12 months, so
#      most recent NA posts have no TH equivalent yet — that's expected.
python fetchers/fetch_th_patch_index.py        # → data/th_patch_index.json
python scanners/scan_th_patch_digimon.py       # → data/th_patch_digimon.json
python enrichers/enrich_digimon_th.py          # → adds source_th + date_th
python extractors/extract_th_digimon_images.py # → image_th (becomes primary image)

# 11. Fetch dmowiki.com digimon pages via CDP (Cloudflare-blocked, needs a
#     Chrome session past CAPTCHA). Launch Chrome first:
#       chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\temp\chrome-cdp
#     then open https://dmowiki.com, solve the CAPTCHA, then:
python fetchers/fetch_dmowiki_digimon.py
#     Saves to cache/dmowiki_<safe-slug>.html. Names the rank_u.html map
#     misses go in its OVERRIDES.
#     Every dmowiki fetcher drives that one tab over raw CDP
#     (fetchers/_cdp_tab.py -> fetchers/cdp_eval.js, needs Node 22): Playwright's
#     connect_over_cdp attaches to every target in the browser and hangs on one
#     that never answers ("Timeout ... <ws connected>"). Requests run as fetch()
#     inside the tab; nothing navigates or clicks. A 403 "Just a moment..." means
#     the challenge is back -- a person passes it, the scripts stop.

# 11b. Same Chrome session, any page list. --mode html saves the page HTML as
#      fetched inside the tab (cache/dmowiki_<slug>.html, what scan_clothing/scan_chipsets read);
#      --mode api calls api.php from inside the tab and saves raw wikitext
#      (cache/dmowiki_<slug>.json), 50 titles per request. Cached files are
#      skipped unless --force; --dry-run prints the plan without Chrome.
python fetchers/fetch_dmowiki_pages.py Clothing ChipSets
python fetchers/fetch_dmowiki_pages.py --mode api --category Digimon_Rank_U
python fetchers/fetch_dmowiki_pages.py --mode api --list titles.txt

# 11c. Gear picker pictures. scan_clothing records each row's wiki image as
#      `icon`; build_gear_registry passes it on as `iconWiki` and sets `icon`
#      only once the file is in docs/img/gear/. /images/ sits behind the same
#      challenge as the pages, so the download goes through the same tab.
python fetchers/fetch_dmowiki_images.py      # then re-run build_gear_registry.py
#      Grouped wiki rows ("*:Spirit X", "Yolei,T.K,Davis X") draw every set's
#      piece in one picture; SPLIT_SETS in build_gear_registry splits them into
#      one pick per set with a cut-out icon. Picture order is NOT the name's:
#      MDG pictures run Davis, T.K, Yolei. build_set_registry reads each set's
#      own pieces through TEMPLATE_BY_SET.
#      Thai names (nameTh): set pieces from data/set_rosters.json, everything
#      else from data/gear_th_names.json (each pair checked present in a cached
#      vplay page). docs/gear-names.html lists them with pictures and sets;
#      clothing slots there show set pieces only.

# 11d. TH wording on decks.html. scan_th_patch_decks reads every "เพิ่มเด็คใหม่"
#      out of the cached TH posts; data/deck_th_map.json is the hand-checked
#      NA deck -> TH deck pairing; apply_th_decks swaps those decks to the TH
#      text (keeps NA names for the filter). Add a pair to the map when TH
#      ships a deck the page already has, then re-run.
python scanners/scan_th_patch_decks.py         # -> data/th_patch_decks.json
python tools/apply_th_decks.py                 # -> docs/decks.html (idempotent)

# 11e. The site follows Rank U, and shows dmowiki's names.
#      - Rank U = a page in dmowiki Category:Digimon_Rank_U, saved as rank_u.html
#        (builders/wiki_names.is_rank_u). digimon.html lists Rank U digimon only;
#        refresh does NOT update rank_u.html -- re-fetch it when the wiki adds one:
#          python fetchers/fetch_dmowiki_pages.py Category:Digimon_Rank_U --force
#          cp cache/dmowiki_category~digimon_rank_u.html rank_u.html
#        fetch_dmowiki_category_images.py <Category> saves that page's pictures
#        to docs/img/wiki/ (portraits named after their page).
#      - Decks with no Rank U digimon are left off decks.html and listed in
#        data/deck_excluded.json ("e622" whole post, "e673/<deck name>" one deck);
#        diff_report, the home feed and apply_th_decks all read it.
#      - Display names: data/digimon_wiki_names.json (digimon page) and
#        data/deck_wiki_names.json + tools/apply_wiki_names_decks.py (decks page).
#        scan_result_digimon.json keeps the NA spelling -- the TH/KR enrichers
#        match on it. A map key hits EVERY post spelled that way: before adding
#        one, check each post using it ("Shoutmon X7" once relabelled the 2023
#        SSS+ post as the Rank U Superior Mode).
#      - Digimon only KR has released: enrichers/find_kr_only_digimon.py ->
#        data/kr_only_digimon.json (cards with a "KR เท่านั้น" badge). A KR name
#        it cannot place needs a KR_TO_EN row, or an EN_TO_KR row in
#        enrich_digimon_kr.py when NA already has it under another spelling.

# 12. Parse cache/dmowiki_*.html and seed `attributes` dict on each digimon.
python enrichers/enrich_digimon_attributes.py            # missing only
python enrichers/enrich_digimon_attributes.py --force    # re-parse every digimon

# 13. Pull Basic/Natural Attribute + Affiliated Field straight from the
#     gameking EventView/PatchNote stat block. In-game-canonical — overrides
#     the dmowiki seed from #12 where present.
python enrichers/enrich_digimon_gameking.py

# 14. Audit: dump attribute/element/families from gameking, KR, and dmowiki
#     side-by-side per digimon so divergences are easy to spot.
python builders/compare_digimon_sources.py              # all digimon
python builders/compare_digimon_sources.py 731          # just one idx

# 15. Seal Exchange report. Extract the seal-exchange table(s) from every
#     seal post (NA/KR/TH) into data/seal_tables.json (reads cache/, fetches
#     the ~10 missing posts and caches them), then inject the cleaned tables
#     into docs/seals.html. Card ids in seals.html (kr-<o>/na-<idx>/th-<suffix>)
#     are the JSON keys; build_seal_tables.py is idempotent (ST-marker guarded).
#     Only Seal-Exchange-Ticket tables are kept; columns are normalized to the
#     Thai-server names. gameking posts that ship the list as an image (no HTML
#     table) get their rows from data/seal_ocr.json (vision-OCR'd, canonical
#     column order; supports an "alias" to reuse another post's standing list).
#     KR table cells are shown in English via data/kr_seal_en.json (Korean
#     seal-name -> official English; unmapped names stay Korean). build_seal_tables.py
#     also removes cards with no table and refreshes hero/tab counts.
#     Cross-server "same list" notes match by ACTUAL SEAL NAMES (order-independent
#     multiset), not by rate — TH Thai names are mapped to the KR/NA English
#     spelling via data/th_seal_en.json (build_th_seal_en.py bootstraps it from
#     rate-aligned pairs + a manual tail). The Seal page also embeds a
#     localStorage "Seal Budget" calculator (per-table ⭐, per-server sub-tabs,
#     ticket = ceil(want/qty)*tickets, packs = /3000, price = *editable/pack)
#     fed by docs/seal_data.json.
#     New seal posts are AUTO-DISCOVERED from cache/ (phrase scan + the
#     extractor's own table criteria); the hardcoded id lists are only the
#     curated baseline. A kept discovery prints "!! NEW seal post(s)" — add a
#     card to docs/seals.html for it, then re-run build_seal_tables.py.
python builders/extract_seal_tables.py
python builders/build_th_seal_en.py
python builders/build_seal_tables.py

# 15b. Per-patch TH seal page (docs/seal-patch-th-<N>.html) with the
#      ticket/pack/price calculator + 🆕 badges from the patch's own
#      "เพิ่มซีลใหม่" table. Regenerates every existing page; new suffixes
#      with tables get a page automatically. Cards on index.html are
#      generated per page by build_index_html.py.
python builders/build_seal_patch_html.py --all   # or: ... 92


# 16. Post-release "Family Attributes" rebalance blocks — merge additions into
#     scan_result_digimon.json (3rd content enricher alongside #10 KR / #10c TH).
python enrichers/enrich_digimon_rebalance.py

# 17. NA Name-Tag-set exchange tracking: scan gameking posts for Name-Tag item
#     tables → data/na_nametag_items.json, then render the item × patch matrix.
python scanners/scan_na_nametag.py
python builders/build_nametag_html.py

# 18. Site-wide builders: hub page (hero totals + feature cards + recent
#     activity) and the Cross-server Lookup dataset for docs/lookup.html.
python builders/build_index_html.py
python builders/build_search_index.py

# 19. Static site checks (no network). Run before committing / in CI:
#     - every data/*.json + docs/*.json parses
#     - every docs/*.html has balanced tags
#     - inline <script> blocks pass node --check
#     - parser regression fixtures (tools/fixtures/ — frozen slices of real
#       posts; a failure means a parser EDIT broke old markup, not that the
#       live site changed)
#     - the deterministic builders are idempotent (re-running them leaves no
#       git diff — catches template drift and accumulation bugs)
python tools/validate.py              # all checks
python tools/validate.py --no-build   # skip the rebuild/idempotency check
```

**Shared helper modules** (not runnable): `enrichers/_content_match.py`
(normalize / keyword lookup / substring match + date parse — used by the KR/TH
enrichers) and `extractors/_image_common.py` (paths, scan JSON round-trip,
base64-first image extraction core — used by all three image extractors).
`builders/aliases.py` is the third one (digimon name aliasing).

**`scanners/scan_digimon.py` is merge-safe.** Existing entries in
`data/scan_result_digimon.json` are never touched (they carry curated fields —
`image`, `image_th`, `image_kr`, `source_kr`, `source_th`, `attributes`, the
Rank-U filter on `e810`); only posts not yet in the file are added. Re-run
freely after a `scan_decks.py` pull.

**Trusted-sources policy:** only `dmowiki.com`, gameking EventView/PatchNote,
and the KR site (digimonmasters.com) are trusted for digimon stats.
`digitalmastersworld.wiki.gg` (formerly cached as `cache/dmw_*.html`) is
**blocklisted** — its Awaken/Extreme pages return base-form data that
disagrees with the game. Do not re-introduce it.

**Digimon name aliases (dub vs JP).** KR and NA both label seals in English but
sometimes pick different spellings for the *same* digimon — one the English-dub
name, one the Japanese romanization (Scorpiomon = Anomalocarimon, Garbagemon =
Gerbemon, Datamon = Nanomon). `data/digimon_aliases.json` (canonical name →
[alt spellings]) folds these onto one key via `builders/aliases.py`
(`norm()` for comparison, `canonical()` for display). `build_seal_tables._norm_seal`
uses it so cross-server lists line up. ⚠️ Only add a pair after confirming on
wikimon.net that it is genuinely one digimon — do NOT merge two distinct digimon
one stage apart (MachGaogamon ≠ MirageGaogamon, both real). The cards still show
each server's own spelling; aliasing only affects *matching*.

**CI / automation.** Two GitHub Actions (manual + push-gated, never auto-push):
- `.github/workflows/validate.yml` — runs `tools/validate.py --no-build` on every
  push/PR (JSON + HTML balance). A broken page fails the check before Pages rebuilds.
- `.github/workflows/refresh.yml` — `workflow_dispatch` only. Re-runs the
  *cloud-safe* half of the pipeline (seal extract/build + KR/TH digimon refs +
  rebuild digimon.html) on a runner, validates, and opens a **PR** for review.
  Deliberately skips `scan_digimon.py` (destructive), attribute enrichment (needs
  Chrome CDP past Cloudflare), and image extraction (binaries) — those stay local.
  Because `cache/` is gitignored, the runner fetches live each run.

There is no test suite, lint config, package manifest, or virtualenv setup. Only runtime dep is `requests`.

## Architecture

The three scripts form a pipeline; understanding their data flow matters more than any single file:

```
scanners/scan_decks.py ──┐
                         ├──► cache/{event,patch}_<idx>.html  (raw HTML, persisted)
                         └──► data/scan_result.json           (parsed deck names per post)
                                  │
                                  ├──► builders/diff_report.py ──► data/diff.json  (vs. docs/decks.html)
                                  │
                                  └──► (manual hand-curation) ──► docs/decks.html  (published)

cache/*.html ──► scanners/scan_digimon.py ──► data/scan_result_digimon.json
                                                  │
                                                  ├──► extractors/extract_digimon_images.py
                                                  │       ├──► docs/img/digimon/<idx>.<ext>
                                                  │       └──► (adds `image` field to JSON)
                                                  │
                                                  ├──► enrichers/enrich_digimon_kr.py
                                                  │       (content-match EN→KR, adds `source_kr`)
                                                  │
                                                  ├──► enrichers/enrich_digimon_th.py
                                                  │       (content-match EN→TH, adds `source_th`/`date_th`)
                                                  │
                                                  ├──► enrichers/enrich_digimon_attributes.py
                                                  │   + enrichers/enrich_digimon_gameking.py
                                                  │       (adds `attributes` dict w/ basic/element/families)
                                                  │
                                                  └──► builders/build_digimon_html.py ──► docs/digimon.html

fetchers/fetch_kr_news_index.py ──► cache/kr_list_p<N>.html
                                └──► data/kr_news_index.json (108 KR Update posts)
                                          │
                                          ▼
                  scanners/scan_kr_digimon_releases.py
                      ├──► cache/kr_view_o<N>.html
                      └──► data/kr_digimon_releases.json (24 posts w/ `신규 디지몬` markers)

fetchers/fetch_th_patch_index.py ──► cache/th_list_p<N>.html
                                └──► data/th_patch_index.json (189 TH patch-note posts)
                                          │
                                          ▼
                  scanners/scan_th_patch_digimon.py
                      ├──► cache/th_view_<slug>.html
                      └──► data/th_patch_digimon.json (53 posts w/ `ดิจิมอนใหม่` markers)

fetchers/fetch_th_links.py  (by hand, not a refresh.py step)
    reads cache/th_view_*.html, fetches each vplay page they link to
    ──► cache/th_link_<sha1[:12]>.html + cache/th_link_index.json

docs/index.html  (hand-written landing page linking to decks.html + digimon.html)

scanners/reparse_cache.py: rebuilds data/scan_result.json from cache/ without network
scanners/extract_deck_detail.py: ad-hoc inspector for a single post's tables
extractors/extract_kr_digimon_images.py + extract_th_digimon_images.py: dual to
the NA image extractor, downloading per-server banners (KR base64-inline, TH from
wp-content/uploads). Image priority in builder: TH > NA > KR.
```

Key design points:

- **`cache/` is the source of truth for parser iteration.** `scan_decks.py` fetches a detail page once and writes the raw HTML there; subsequent runs short-circuit on `cache_file.exists()`. When tweaking parsing, run `reparse_cache.py` rather than re-hitting the server.
- **Enumeration vs. detail are separate phases.** `enumerate_idx()` pages an AJAX endpoint (`AjaxEventList.aspx` / `AjaxPatchNoteList.aspx`) to discover idx values; `fetch_detail()` then GETs each `EventView.aspx?idx=…` / `PatchNoteView.aspx?idx=…` in a 15-worker thread pool.
- **Deck detection logic lives in `parse_decks()` in [scan_decks.py](scan_decks.py).** It strips HTML to plain text, finds positions of `[New Deck Add(ed)]` and `[Existing Deck Effect Changed]` / `[Modify Existing Deck]` markers, then walks every `[<Name>] Digimon List` anchor and classifies each by the *nearest preceding* marker. Don't move classification logic elsewhere — `reparse_cache.py` imports `parse_decks` and `html_to_text` directly from `scan_decks`.
- **`extract_deck_detail.py` uses a different, table-aware parser** (finds the next `<table>` after each heading). It exists because `parse_decks()` only captures deck names, not the Digimon List / Effect tables.
- **KR is a secondary reference source, matched by content (not date).** Posts in `scan_result_digimon.json` carry both a `source` (typically `dmo.gameking.com`, the English translation) and an optional `source_kr` (`digimonmasters.com`, the original Korean post). `build_digimon_html.py` renders both links with `EN`/`KR` labels (auto-detected by hostname). The matching pipeline is content-based because gameking-side translations can lag KR by anywhere from 1 day to several months (e.g. e673 Kuzuhamon = 28-day lag, e663 Omegamon Merciful = 3-month lag — pure date matching is unreliable):
  1. [scan_kr_digimon_releases.py](scan_kr_digimon_releases.py) fetches every KR Update post body and extracts `[ 신규 디지몬 (계열)? (추가)? - <name> ]` markers using balanced-bracket walking (names can contain nested `[각성]` / `[극의]` prefixes). Output: `kr_digimon_releases.json`.
  2. [enrich_digimon_kr.py](enrich_digimon_kr.py) maps EN digimon names to KR keywords via the `EN_TO_KR_KEYWORDS` list (ordered: longer/more-specific keys first, so "Abbadomon Core" matches before "Abbadomon"), then looks up each keyword in the KR release list. If multiple KR posts contain the keyword, the one closest to the gameking date wins.
  3. `OVERRIDES` in `enrich_digimon_kr.py` handles digimon released only via deck/event posts that lack a `신규 디지몬` marker (e.g. Omegamon Merciful Mode came in via deck "하얀 날개 : 용기의 우령도", post o=780048).
- **The deck report is hand-curated; the digimon report is auto-generated.** No script auto-generates `docs/decks.html` from `scan_result.json` — it's edited by hand because deck content includes tables (Digimon List + Effect) that need human review. `diff_report.py` reports drift between scan and report. By contrast, `docs/digimon.html` is fully generated by `build_digimon_html.py` from `scan_result_digimon.json` since digimon entries are just names + metadata. The deck report supports two layouts (old `<h2>idx N</h2>` and new `<section id="e<idx>">`) — `parse_report_idx()` handles both.

## Publishing the report

The `docs/` folder is published as **https://dmo-hub.github.io/dmo/** via GitHub Pages, configured to serve from this repo's `main` branch / `/docs` folder. Repo is `dmo-hub/dmo` (previously `dmoDeck` / `dmo-decks` — both old URLs auto-redirect). Edit files under `docs/`, commit, push to `origin/main` (SSH key at `~/.ssh/id_ed25519_github`), and Pages rebuilds in ~30s.

```bash
# After editing/regenerating files in docs/
git add docs/ && git commit -m "update report" && git push
```

To add a new report type (e.g. `system.html` for game-system updates), add a
card to `docs/index.html` linking to it and create `docs/<topic>.html` with the
same look-and-feel as `decks.html` / `digimon.html`. All pages share the
external stylesheet `docs/css/site.css` (light/dark via `docs/js/theme.js`) and
the same `.site-nav` / `.hero` / `.timeline` / `.card` markup — don't re-inline
CSS; reuse the tokens. `docs/styleguide.html` renders every shared component for
copy-paste reference.

**Mockup-first for new pages.** Before writing a `build_<topic>_html.py`, hand-write
a *static mockup* `docs/<topic>.html` with 2-3 rows of FAKE data so the layout can
be reviewed in a real browser first (this is the "HTML is the new Markdown"
workflow — spend effort on the visual spec, not on a builder you'll rewrite). Mark
the mockup with a `<!-- MOCKUP -->` comment + a visible banner, and keep it OUT of
`index.html` and `tools/validate.py` until the builder exists. Once the layout is
approved, write the builder to regenerate the file from real scan data; the
hand-written mockup is then thrown away (overwritten by the builder's output).

**Curation micro-UI.** `tools/curate.html` is a standalone (no-server, `file://`)
editor for `data/scan_result_digimon.json`: drag-drop the JSON, fix
`image`/`image_th`/`image_kr`/`source*` and `digimon[]` names visually with image
previews, then "Download JSON" to save back over the data file. Use it instead of
hand-editing the JSON. It is a throwaway tool — not part of the build or CI.

## Conventions worth knowing

- **Sponsored ads live in `docs/js/ads.js` only.** Every page with the ad
  markup (`#ad-float` / `.ad-inline` / `#ad-box` + `data-ad-*` hooks) loads it
  via `<script src="js/ads.js">`. To add/remove a product, edit the `ADS`
  array there — never inline ad config in a page again.

- All scripts force UTF-8 stdout at startup (`sys.stdout.reconfigure`) because the project path contains Thai characters and the default Windows console encoding will crash on prints.
- `BASE` host, the two AJAX endpoints, and the two view-URL templates are centralized in the `CONFIGS` dict at the top of [scan_decks.py](scan_decks.py) — other scripts import from there rather than duplicating URLs.
- Post dates in cached HTML are `MM-DD-YYYY` (US format), extracted with `DATE_RE = r">\s*(\d{2}-\d{2}-\d{4})\s*<"`.
- Scanners read `cache/*.html` only. Never move cache files aside to force a
  refetch while a source might be down: the NA posts once sat in
  `cache/_stale-<date>/` after gameking stopped answering, and Gammamon plus
  three NA banners went missing until the files were copied back. Use the
  fetchers' `--force` instead.
- vplay's post archive is open through WordPress:
  `https://www.vplay.in.th/wp-json/wp/v2/posts?per_page=100&page=N` (685 posts
  on 2026-10-20) -- but that listing leaves out the GM-note category (id 5, 56
  posts, where the equipment posts live); fetch it with `&categories=5`. A
  post's id is in its page HTML (`?p=<id>`) when its slug will not match
  `?slug=`. The cache only covers the patch-note
  category, so a Thai name or per-level table not found in `cache/` is often in
  an event/promotion post -- that is where 7 Thai gear names and the Spirit /
  Four Holy Beasts level tables came from.
- `scanners/scan_clothing.py` is not a `refresh.py` step. After changing it
  run it by hand, then `builders/build_gear_registry.py`, then
  `tools/validate.py` twice: the first run fails "builders idempotent" because
  `docs/set_registry.json` still holds the old values, the second passes.
- An item missing from the wiki-built registry is not proof NA lacks it. grep
  the NA notices in `cache/event_*.html` / `cache/patch_*.html` first: the 2025
  Four Holy Beasts gear (Noble Head Ornament of Huanglongmon ...) is absent
  from dmowiki's Clothing page but sold in event_740 / event_784.
- Daisuke/Takeru/Miyako gear has a "(ชิน)" tier with higher numbers. It is
  its own registry item (`<name> (Shin)`, built by `add_shin_pieces` from the
  vplay per-level tables) but the SAME set: vplay lists all 12 pieces under
  one set and one bonus table, so base and shin pieces worn mixed both count.
- The solver finds a row's set by the row's name, and rows carry the
  registry's English name. `set_registry.json` "accepts" therefore lists the
  Thai pair first, then the registry names whose nameTh is one of them;
  without the English names no registry-picked row ever earned a set bonus.
  `validate.py` fails a slot whose accepts misses any of those names.
- A set bonus can sit under another name. dmowiki's "Digimon Frontier"
  4-piece row is the element-spirit 4-piece bonus (vplay lists the same
  numbers per element), joined through `BONUS_ALIASES` in
  `build_set_registry.py`. A set dmowiki never recorded gets a hand-kept
  bonus file listed in `scan_set_effects.EXTRA_SOURCES`
  (`data/last_evolution.json`) plus a `SET_NAMES` entry.
- The vplay-only Four Holy Beasts clothing ("มงกุฎศักดิ์สิทธิ์ของฟานลอนมอน
  [อัลติเมท]" ...) is kept out of the registry on the owner's call, so
  "พลังของสี่สัตว์เทพเซ็ต" prints "not joined" in build_set_registry -- expected.
- Accessories (rings, necklaces, earrings, bracelets) roll random options. The
  wiki's tables give option counts and what each option can roll, never one
  piece's stats, so the registry's numbers for them are only a cap (axis
  "unknown", the solver skips them). `build_gear_registry` also writes
  `docs/accessory_registry.json` -- list row joined to its roll table -- for
  the gear-names page. In `scan_clothing`, Minimum/Maximum/Fixed columns mean
  the table is one item named by its `<caption>` (or a one-cell title row),
  "... with N Options"/"Regular ..." columns are category caps (`category`),
  and per-level cells are spread by colspan. "Vital Breath Digivice -V-" is a
  bracelet despite the name.
  Accessories the owner left out are listed in `data/accessory_excluded.json`;
  one entry drops both the gear-names row and the optimizer's stats row
  (matched with only a level/duration tail dropped -- `excluded_key`, not
  `icon_key`, which drops any bracket and once took "Miracle Bracelet
  [Special]" out with "[Level 1]"). Remove a Thai name for a
  dropped piece from `gear_th_names.json` too, or the builder warns.
- Goggles come from vplay, not dmowiki: `scanners/scan_vplay_goggles.py`
  (posts 19820 Adventure · 25445 Kaiser · 17826 Tamer, cached as
  `cache_vplay/wp_<id>.json`) -> `data/goggles_th.json`, and
  `build_gear_registry.add_th_goggles` drops the wiki's goggles rows (named
  "Tamer's Goggles [..]" under every goggles heading, NA rolls) for them.
  Adventure Goggles are 25 fixed main/third-option pairs, axis digimon (the
  post says so); Kaiser goggles are read as digimon too -- their post never
  says, but AT 4000 / CT 40% is digimon-scale, not the tamer goggles' AT 400.
- Digivices, the Digi-Aura, key rings and magnetic ID cards also come from
  vplay: `scanners/scan_vplay_tamer_gear.py` (GM-note posts, category id 5 --
  not in `/wp-json/wp/v2/posts` without `?categories=5`) ->
  `data/tamer_gear_th.json` -> `build_gear_registry.add_th_tamer_gear`, which
  drops every wiki key ring row and adds the wiki's XAI + Final Digivice (no
  vplay post). Each line is kept at its top tier only, one item per line;
  family key rings list their 11 families instead of 11 items. A digivice's
  attribute/element options go to `rows` (gear-names) and never to stats.
  Axis: digivices/aura/Ghost digimon (posts say so), Spiral base tamer (post),
  ID cards tamer (wiki), Spiral-family / DIGI-Key Ring / XAI unknown (nothing
  says). Not a `refresh.py` step: run it by hand like scan_clothing.
