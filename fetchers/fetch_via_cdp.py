"""Attach to a running Chrome (via CDP) and save the Rank U page HTML.

Setup before running this:
  1. Close all Chrome windows.
  2. Launch Chrome with:
       chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\temp\\chrome-cdp
  3. In that Chrome, open https://dmowiki.com/Category:Digimon_Rank_U
  4. Click the CAPTCHA. Wait until the actual wiki page (with the Pages-in-category list) is visible.
  5. Run this script.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).parent / "rank_u.html"
CDP_URL = "http://localhost:9222"

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CDP_URL)
    print(f"connected: {len(browser.contexts)} context(s)")

    target_page = None
    for ctx in browser.contexts:
        for pg in ctx.pages:
            url = pg.url
            print(f"  page: {url}")
            if "dmowiki.com" in url and "Rank_U" in url:
                target_page = pg

    if not target_page:
        print("ERROR: open https://dmowiki.com/Category:Digimon_Rank_U in the Chrome window first")
        sys.exit(1)

    title = target_page.title()
    print(f"target title: {title!r}")
    if "Just a moment" in title:
        print("ERROR: CAPTCHA not yet solved — click it in Chrome then re-run")
        sys.exit(2)

    html = target_page.content()
    OUT.write_text(html, encoding="utf-8")
    print(f"SAVED {len(html)} bytes -> {OUT}")
