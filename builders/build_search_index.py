"""Generate docs/search_index.json — the Cross-server Lookup dataset.

Aggregates every seal-table row (docs/seal_data.json) and every tracked
digimon (data/scan_result_digimon.json) into one alias-folded entry list so
docs/lookup.html can answer "เซิร์ฟไหนมีของชื่อนี้" from a single search box
in EN / KR / TH.

Matching accuracy lives HERE (Python), not in page JS:
  - names are normalized with builders/aliases.py norm() (alias-folded,
    decoration-stripped) — the same logic build_seal_tables.py trusts;
  - TH row names are mapped to EN via data/th_seal_en.json BEFORE norm()
    (Thai script has no a-z0-9, a raw norm() would collapse to "");
  - KR original spellings are re-attached from data/kr_seal_en.json
    (reverse map) so typing Korean also matches;
  - unmapped TH/KR names still get their own entry keyed on the raw name.

Deterministic: no timestamps — "coverage" dates are derived from the data
itself (latest post date per server), so tools/validate.py's idempotency
check holds.
"""

import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "builders"))
sys.path.insert(0, str(PROJ / "enrichers"))
from aliases import _strip_decoration, canonical, norm  # noqa: E402
from enrich_digimon_kr import EN_TO_KR_KEYWORDS  # noqa: E402

SEAL_DATA = PROJ / "docs" / "seal_data.json"
KR_EN = PROJ / "data" / "kr_seal_en.json"
TH_EN = PROJ / "data" / "th_seal_en.json"
ALIASES = PROJ / "data" / "digimon_aliases.json"
DIGIMON = PROJ / "data" / "scan_result_digimon.json"
OUT = PROJ / "docs" / "search_index.json"

HAS_THAI = re.compile(r"[฀-๿]")
HAS_HANGUL = re.compile(r"[가-힯]")


def iso_from_dmy(dmy):  # "17.03.2026" -> "2026-03-17"
    dd, mm, yyyy = dmy.split(".")
    return f"{yyyy}-{mm}-{dd}"


def iso_from_mdy(mdy):  # "03-05-2024" -> "2024-03-05"
    mm, dd, yyyy = mdy.split("-")
    return f"{yyyy}-{mm}-{dd}"


def entry_key(raw_name, th_to_en):
    """(group_key, en_name_or_None) for a seal-table row name."""
    base = _strip_decoration(raw_name)
    if HAS_THAI.search(base):
        en = th_to_en.get(base)
        if en:
            return norm(en), en
        return "th:" + base, None  # unmapped Thai — own entry
    if HAS_HANGUL.search(base):
        return "kr:" + base, None  # unmapped Korean — own entry
    return norm(raw_name), base


def main() -> None:
    seal_data = json.loads(SEAL_DATA.read_text(encoding="utf-8"))
    kr_to_en = json.loads(KR_EN.read_text(encoding="utf-8"))
    th_to_en = json.loads(TH_EN.read_text(encoding="utf-8"))
    digimon = json.loads(DIGIMON.read_text(encoding="utf-8"))
    alias_map = {
        k: v for k, v in json.loads(ALIASES.read_text(encoding="utf-8")).items()
        if not k.startswith("_")
    }

    # reverse maps: EN -> [KR spellings], EN -> [TH spellings]
    en_to_kr, en_to_th = {}, {}
    for kr, en in kr_to_en.items():
        en_to_kr.setdefault(norm(en), []).append(kr)
    for th, en in th_to_en.items():
        en_to_th.setdefault(norm(en), []).append(th)

    coverage = {}  # server -> latest ISO date seen

    def bump(server, iso):
        if iso and iso > coverage.get(server, ""):
            coverage[server] = iso

    # --- seal rows ------------------------------------------------------
    entries: OrderedDict[str, dict] = OrderedDict()
    for key in sorted(seal_data):
        tbl = seal_data[key]
        server = tbl["server"]
        post_id = key.split("#")[0]
        date_iso = iso_from_dmy(tbl["date"]) if tbl.get("date") else ""
        bump(server, date_iso)
        for row in tbl.get("rows", []):
            raw = row[0]
            gkey, en = entry_key(raw, th_to_en)
            e = entries.setdefault(gkey, {
                "type": "seal",
                "key": gkey,
                "display": "",
                "names": {"en": [], "kr": [], "th": []},
                "servers": {},
            })
            if en and not e["display"]:
                e["display"] = canonical(en)
            base = _strip_decoration(raw)
            lang = "th" if HAS_THAI.search(base) else ("kr" if HAS_HANGUL.search(base) else "en")
            if base not in e["names"][lang]:
                e["names"][lang].append(base)
            e["servers"].setdefault(server, []).append({
                "post": post_id,
                "date": tbl.get("date", ""),
                "qty": row[1] if len(row) > 1 else "",
                "tickets": row[2] if len(row) > 2 else "",
                "stat": row[3] if len(row) > 3 else "",
                "value": row[4] if len(row) > 4 else "",
            })

    # attach known KR/TH spellings from the mapping files (search in any language
    # finds the entry even when that server hasn't shipped the item yet)
    for e in entries.values():
        nkey = e["key"]
        for kr in en_to_kr.get(nkey, []):
            if kr not in e["names"]["kr"]:
                e["names"]["kr"].append(kr)
        for th in en_to_th.get(nkey, []):
            if th not in e["names"]["th"]:
                e["names"]["th"].append(th)
        if not e["display"]:
            e["display"] = (e["names"]["en"] or e["names"]["th"] or e["names"]["kr"] or [nkey])[0]

    # --- seal patch posts (search by caption / server / date) -----------
    patch_entries: OrderedDict[str, dict] = OrderedDict()
    for key in sorted(seal_data):
        tbl = seal_data[key]
        post_id = key.split("#")[0]
        if post_id in patch_entries:
            e = patch_entries[post_id]
            if tbl.get("caption") and tbl["caption"] not in e["names"]["en"]:
                e["names"]["en"].append(tbl["caption"])
            e["n_tables"] += 1
            e["n_rows"] += len(tbl.get("rows", []))
            continue
        server = tbl["server"]
        patch_entries[post_id] = {
            "type": "patch",
            "key": post_id,
            "display": f"{post_id} — {tbl.get('caption', 'Seal Exchange')}",
            "names": {"en": [post_id, tbl.get("caption", "")], "kr": [], "th": []},
            "anchor": f"seals.html#{post_id}",
            "n_tables": 1,
            "n_rows": len(tbl.get("rows", [])),
            "servers": {server: [{"post": post_id, "date": tbl.get("date", "")}]},
        }

    # --- digimon --------------------------------------------------------
    dig_entries = []
    for kind, posts in (("event", digimon.get("event", {})), ("patch", digimon.get("patch", {}))):
        for idx, p in sorted(posts.items(), key=lambda kv: int(kv[0])):
            date_iso = iso_from_mdy(p["date"]) if p.get("date") else ""
            bump("na", date_iso)
            if p.get("date_th"):
                bump("th", p["date_th"][:10])
            anchor = f"digimon.html#{'e' if kind == 'event' else 'p'}{idx}"
            for name in p.get("digimon", []):
                canon = canonical(name)
                alts = alias_map.get(canon, [])
                # attach Korean spellings from the EN→KR keyword dict so
                # typing Korean finds new digimon too
                squashed = re.sub(r"\s+", "", name.lower())
                kr_names = [
                    kr_kw for en_kw, kr_kw in EN_TO_KR_KEYWORDS
                    if re.sub(r"\s+", "", en_kw.lower()) in squashed
                ]
                servers = {}
                servers["na"] = [{"url": p.get("source", ""), "date": p.get("date", "")}]
                if p.get("source_kr"):
                    servers["kr"] = [{"url": p["source_kr"], "date": ""}]
                if p.get("source_th"):
                    servers["th"] = [{"url": p["source_th"], "date": p.get("date_th", "")}]
                dig_entries.append({
                    "type": "digimon",
                    "key": norm(name),
                    "display": canon,
                    "names": {"en": sorted({name, canon, *alts}), "kr": sorted(set(kr_names)), "th": []},
                    "anchor": anchor,
                    "servers": servers,
                })

    out = {
        "coverage": {s: coverage.get(s, "") for s in ("na", "kr", "th")},
        "entries": sorted(entries.values(), key=lambda e: e["display"].lower())
                   + sorted(patch_entries.values(), key=lambda e: e["display"].lower())
                   + sorted(dig_entries, key=lambda e: (e["display"].lower(), e["anchor"])),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        f"Wrote {OUT.relative_to(PROJ)} — {len(entries)} seal + {len(patch_entries)} patch"
        f" + {len(dig_entries)} digimon, coverage {out['coverage']}"
    )


if __name__ == "__main__":
    main()
