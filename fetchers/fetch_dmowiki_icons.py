"""Download attribute/element/family icons from dmowiki.com (Cloudflare-blocked)
via the running CDP Chrome session. Saves to docs/img/icons/<name>.png.

Sources:
  https://dmowiki.com/Digimon_Attributes   (5 basic attribute icons)
  https://dmowiki.com/Elemental_Attributes (11 element icons)
  https://dmowiki.com/Families             (11 field/family icons)

Filenames written under docs/img/icons/:
  attr-{Vaccine,Virus,Data,Free,Unknown}.png
  elem-{Fire,Light,Wood,Wind,Steel,Thunder,Water,Earth,Pitch_Black,Neutral}.png
  field-{Virus_Busters,Wind_Guardians,Nightmare_Soldiers,Jungle_Troopers,
         Nature_Spirits,Deep_Savers,Metal_Empire,Dragons_Roar,Unknown,
         Dark_Area,TBD}.png

Run with the same Chrome-with-CDP session used by fetch_dmowiki_digimon.py
(must have a valid CF cookie — solve CAPTCHA on any dmowiki page first).
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
OUT = PROJ / "docs" / "img" / "icons"
CDP_URL = "http://localhost:9222"

# (dmowiki URL path → local filename). We write canonical filenames keyed on
# the value we store in scan_result_digimon.json so build_digimon_html.py can
# build src URLs trivially.
ICONS: dict[str, str] = {
    # Basic attributes — dmowiki uses VA/VI/DA/NO/UN suffixed names with
    # MediaWiki's hashed paths (/images/<X>/<XX>/...). The Digimon_Attributes
    # page references them at these exact paths:
    "/images/7/76/VA1.png": "attr-Vaccine.png",
    "/images/d/dc/VI1.png": "attr-Virus.png",
    "/images/d/dc/DA1.png": "attr-Data.png",
    "/images/e/e5/NO1.png": "attr-Free.png",
    "/images/f/fd/UN1.png": "attr-Unknown.png",
    # Natural attributes (elements) — flat /images/<X>/<XX>/<Name>.png paths
    "/images/3/30/Fire.png": "elem-Fire.png",
    "/images/a/a6/Light.png": "elem-Light.png",
    "/images/d/df/Wood.png": "elem-Wood.png",
    "/images/b/bf/Wind.png": "elem-Wind.png",
    "/images/c/c9/Steel.png": "elem-Steel.png",
    "/images/3/3d/Thunder.png": "elem-Thunder.png",
    "/images/9/9d/Water.png": "elem-Water.png",
    "/images/a/ae/Land.png": "elem-Earth.png",  # wiki "Land" = game "Earth"
    "/images/7/77/Ice.png": "elem-Ice.png",
    "/images/1/10/Pitch_Black.png": "elem-Pitch_Black.png",
    "/images/b/b3/Neutral.png": "elem-Neutral.png",
    # Field / family icons
    "/images/5/56/Virus_Busters.png": "field-Virus_Busters.png",
    "/images/f/fa/Wind_Guardians.png": "field-Wind_Guardians.png",
    "/images/3/30/Nightmare_Soldiers.png": "field-Nightmare_Soldiers.png",
    "/images/e/e5/Jungle_Troopers.png": "field-Jungle_Troopers.png",
    "/images/e/e1/Nature_Spirits.png": "field-Nature_Spirits.png",
    "/images/b/b1/Deep_Savers.png": "field-Deep_Savers.png",
    "/images/7/70/Metal_Empire.png": "field-Metal_Empire.png",
    "/images/9/95/Dragons_Roar.png": "field-Dragons_Roar.png",
    "/images/d/dd/Unknown.png": "field-Unknown.png",
    "/images/3/36/Dark_Area.png": "field-Dark_Area.png",
    "/images/b/bb/TBD_Icon.png": "field-TBD.png",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"ERROR: can't connect to Chrome at {CDP_URL}: {e}")
            sys.exit(1)
        if not browser.contexts:
            print("ERROR: no browser context — open dmowiki in a tab first.")
            sys.exit(2)
        ctx = browser.contexts[0]
        req = ctx.request  # inherits Cloudflare clearance cookies

        ok, skipped, failed = 0, 0, []
        for path, name in ICONS.items():
            out_file = OUT / name
            if out_file.exists():
                print(f"  · {name:36s} (cached)")
                skipped += 1
                continue
            url = f"https://dmowiki.com{path}"
            r = req.get(url, timeout=20000)
            if not r.ok or "image" not in r.headers.get("content-type", ""):
                print(f"  ✗ {name:36s} ← {url}  (status={r.status})")
                failed.append(name)
                continue
            out_file.write_bytes(r.body())
            print(f"  ✓ {name:36s} ← {url}  ({len(r.body())} bytes)")
            ok += 1

        print(f"\n--- downloaded {ok}, cached {skipped}, failed {len(failed)} ---")
        if failed:
            for f in failed:
                print(f"  ! {f}")


if __name__ == "__main__":
    main()
