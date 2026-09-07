"""Write the chip list the gear page loads.

    data/chip_double.json  ->  docs/chip_registry.json

Scope, as decided: only the Double ChipSets (R16-R18). R1-R15 from
data/chip_items.json are left out -- nobody optimising a loadout is fitting a
low-grade chip, and carrying them would triple the list for no gain.

A Double ChipSet grants BOTH its primary and its secondary stat set at once
("ค่าความสามารถหลักและค่าความสามารถรอง"), so the numbers the page
shows are the two summed. The split is kept alongside so the page can explain
where a total came from.

Percentages arrive already scaled by the scanner: vplay writes "CT 400" for
what dmowiki calls "+4%".
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "data" / "chip_double.json"
OUT = PROJ / "docs" / "chip_registry.json"

# Every stat a chip can carry. The solver targets AT/HT/CT; the rest ride along
# so the page can show what else a chip brings, and so nothing is dropped
# without anyone noticing.
CHIP_STATS = ["HP", "DS", "AT", "DE", "HT", "EV", "CT", "BL"]


def main():
    src = json.loads(SRC.read_text(encoding="utf-8"))
    out = []
    for it in src["items"]:
        primary = it.get("primary", {})
        secondary = it.get("secondary", {})
        rec = {
            "id": it["id"],
            "name": it["name"],
            "grade": it["grade"],
            "axis": it.get("axis", "digimon"),
        }
        for key in CHIP_STATS:
            total = 0.0
            for part in (primary, secondary):
                got = part.get(key)
                if got:
                    total += float(got["value"])
            if total:
                rec[key] = round(total, 2) if key in ("CT", "EV", "BL") else round(total)
        rec["parts"] = {
            "primary": {k: v["value"] for k, v in sorted(primary.items())},
            "secondary": {k: v["value"] for k, v in sorted(secondary.items())},
        }
        out.append(rec)

    out.sort(key=lambda r: r["grade"])
    OUT.write_text(json.dumps({
        "built_at": date.today().isoformat(),
        "source": "data/chip_double.json",
        "note": ("Double ChipSets only (R16-R18); each value is the primary and "
                 "secondary sets added together, both of which the item grants"),
        "items": out,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print("wrote %s" % OUT.relative_to(PROJ))
    print("  chips %d" % len(out))
    for r in out:
        print("    %-22s AT %-5s HT %-5s CT %-6s DS %-6s DE %s"
              % (r["name"], r.get("AT"), r.get("HT"), r.get("CT"),
                 r.get("DS"), r.get("DE")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
