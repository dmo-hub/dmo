"""Build data/th_seal_en.json — a Thai seal-name -> English (the spelling the
KR/NA tables use) map, so cross-server matching can compare seals by name.

Two sources:
  1. BOOTSTRAP — for every cross-server pair whose rate sequence is identical
     (KR/NA English ↔ TH Thai), align rows and learn TH name -> the EN name
     KR/NA used at that row. Reliable for rows where the seal is the same.
  2. MANUAL — TH names not covered by any rate-matched pair (hand transliterated)
     plus OVERRIDES that fix the handful of rows where KR and TH genuinely list
     a different seal at the same rate (so the bootstrap learned the wrong name).

Run: python builders/build_th_seal_en.py
"""

import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).resolve().parent.parent
DATA = PROJ / "data" / "seal_tables.json"
OUT = PROJ / "data" / "th_seal_en.json"

# Hand-mapped TH names (uncovered by bootstrap) + overrides for genuine
# KR/TH list differences where the bootstrap learned the wrong English name.
MANUAL = {
    # --- overrides: KR & TH list a different seal at the same rate ---
    "โกมามอน": "Gomamon", "ซาคุยามอน": "Sakuyamon",
    "ชัคโคมอน": "Shakkoumon", "มิราจกาโอมอน": "MirageGaogamon",
    # --- TH names not in any rate-matched pair ---
    "กลาดิมอน": "Gladimon", "กาจิมอน": "Gazimon", "กิลมอน": "Guilmon",
    "คลื่นความร้อน": "Heat Wave", "คอร์ดรามอน(กรีน)": "Coredramon(Green)",
    "คาออสมอน": "Chaosmon", "คิวบีมอน": "Kyubimon", "คิเมรามอน": "Kimeramon",
    "คูลูมอน": "Culumon", "จินลองมอน": "Huanglongmon", "จูเรย์มอน": "Cherrymon",
    "ดราคุมอน": "Dracmon", "ดาร์คทีราโนมอน": "DarkTyrannomon",
    "ดุ๊คมอน คริมสันโหมด": "Gallantmon Crimson Mode", "ทอยอากูมอน": "ToyAgumon",
    "ปรินซ์มาเมมอน": "PrinceMamemon", "ปิเอมอน": "Piedmon", "พล็อตมอน": "Salamon",
    "พาราไซมอน": "Parasimon", "ฟานลองมอน": "Fanglongmon", "มัชชูมอน": "Mushroomon",
    "มุเกนดรามอน": "MugenDramon", "ยูคิดารุมอน": "Yukidarumon",
    "ลอร์ดไนท์มอน": "LordKnightmon", "ลูเจมอน ซาตานโหมด": "Lucemon Satan Mode",
    "วาจิรามอน": "Vajramon", "วาสพ์มอน": "Waspmon", "สกัลเกรย์มอน": "SkullGreymon",
    "อัลฟามอน": "Alphamon", "อิคคาคุมอน": "Ikkakumon", "เครามอน": "Keramon",
    "เคออส ปิเอมอน": "ChaosPiedmon", "เจสมอน": "Jesmon", "เชนทารูมอน": "Centarumon",
    "เชาท์มอนX2": "ShoutmonX2", "เซเวียร์แฮคมอน": "SaviorHackmon",
    "เดธ X โดรุเกรย์มอน": "Death-X-DoruGreymon",
    "เดธ X โดรุโกรามอน": "Death-X-Dorugoramon", "เนโอเดวีมอน": "NeoDevimon",
    "เมทัลการูรูมอน": "MetalGarurumon", "เมทัลซีดรามอน": "MetalSeadramon",
    "เมทัลทีราโมมอน": "MetalTyrannomon", "เรนามอน": "Renamon",
    "เรพิดมอน": "Rapidmon", "เอ็กซามอน": "Examon",
    "แกรนดิสคุวากามอน": "GrandisKuwagamon", "แบล็ควาร์การูรูมอน": "BlackWereGarurumon",
    "แรปเตอร์ดรามอน": "Raptordramon", "แร็ปเตอร์ดรามอน": "Raptordramon",
    "แรร์มอน": "Raremon", "แฮคมอน": "Hackmon", "โกเลมอน": "Golemon",
    "โบลท์โบทามอน": "BoltBotamon", "โบโคมอน": "Bokomon",
    "โมโนคุโรมอน": "Monochromon", "โมโนดรามอน": "Monodramon", "โรสมอน": "Rosemon",
    "โอเมกามอน สวอร์ธ": "Omegamon Zwart", "ไทแรนคาบุเทริมอน": "TyrantKabuterimon",
    "ไทแรนคาบูเทริมอน": "TyrantKabuterimon", "ไบฟูมอน": "Baihumon",
}


def th_name(s):
    return re.sub(r"\s*ซีล.*$", "", re.sub(r"\[[^\]]*\]", "", s)).strip()


def en_name(s):
    return re.sub(r"\s*Seal.*$", "", re.sub(r"\[[^\]]*\]", "", s)).strip()


def rows(html):
    return [[re.sub(r"<[^>]+>", "", c).strip()
             for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            for r in re.findall(r"<tr>(.*?)</tr>", html, re.S)][1:]


def rate_seq(r):
    return tuple((x[1], x[2], x[3], x[4]) for x in r if len(x) >= 5)


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    T = {f"{k}#{ti}": rows(t["html"])
         for k, v in d.items() for ti, t in enumerate(v["tables"])}
    votes = defaultdict(Counter)
    for ta in [x for x in T if x.startswith("th-")]:
        for tb in [x for x in T if x.split("-")[0] in ("kr", "na")]:
            A, B = T[ta], T[tb]
            if len(A) == len(B) and rate_seq(A) == rate_seq(B):
                for a, b in zip(A, B):
                    if a and b and a[0] and b[0]:
                        votes[th_name(a[0])][en_name(b[0])] += 1
    boot = {th: c.most_common(1)[0][0] for th, c in votes.items()}
    out = {**boot, **MANUAL}                      # MANUAL overrides bootstrap
    out.pop("", None)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {OUT.name}: {len(out)} names "
          f"(bootstrap {len(boot)}, manual/override {len(MANUAL)})")


if __name__ == "__main__":
    main()
