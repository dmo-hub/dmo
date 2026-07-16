"""Fetch dmowiki Rank U page via Playwright with real Chrome + anti-detection."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

URL = "https://dmowiki.com/Category:Digimon_Rank_U"
# PROJ root — build_rank_u_map() in fetch_dmowiki_digimon.py reads it from there
OUT = Path(__file__).resolve().parent.parent / "rank_u.html"

STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = {runtime: {}};
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
  parameters.name === 'notifications'
    ? Promise.resolve({state: Notification.permission})
    : originalQuery(parameters)
);
"""

with sync_playwright() as p:
    browser = p.chromium.launch(
        channel="chrome",
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    print(">>> ถ้าเห็น CAPTCHA กรุณาคลิก checkbox ใน browser <<<")
    print(">>> Script รอสูงสุด 5 นาที (poll ทุก 2 วินาที) <<<")

    saved = False
    for i in range(150):
        page.wait_for_timeout(2000)
        try:
            title = page.title()
            url = page.url
            if i % 5 == 0:
                print(f"[{i * 2}s] title={title!r}")
            if "Just a moment" in title:
                continue
            has_pages = page.locator("#mw-pages").count() > 0
            has_cat = page.locator(".mw-category, .mw-category-group").count() > 0
            heading = ""
            try:
                heading = page.locator("#firstHeading").inner_text(timeout=1000)
            except Exception:
                pass
            if has_pages or has_cat or "Rank U" in heading:
                html = page.content()
                OUT.write_text(html, encoding="utf-8")
                print(f"SAVED {len(html)} bytes -> {OUT}")
                print(f"TITLE: {title}")
                print(f"URL: {url}")
                saved = True
                break
        except Exception as e:
            print(f"[{i * 2}s] err: {e}")

    if not saved:
        try:
            html = page.content()
            OUT.write_text(html, encoding="utf-8")
            print(f"FALLBACK saved partial HTML ({len(html)} bytes)")
        except Exception:
            pass
        print("TIMEOUT — Cloudflare may still be blocking")

    browser.close()
