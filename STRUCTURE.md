# dmo/ — โครงสร้างโดยละเอียด

`dmo/` เป็น folder เดียวที่รวม **3 ระบบแยก git กัน**:

```
dmo/              git #1 — DMO Tracker (scraper + เว็บ GitHub Pages)
├── poster-studio/   git #2 — โรงงานผลิตโปสเตอร์โฆษณา
└── backoffice/      git #3 — หลังบ้านคุมโปสเตอร์ขึ้นเว็บ
```

ทั้ง 3 ระบบเชื่อมกันด้วยไฟล์ล้วน (PNG / JSON) ไม่มี dependency ข้าม repo:

```
poster-studio/dist/*.png  ──scan_posters.py──▶  backoffice/data/placements.json
                                                          │ (approve ใน backoffice.html)
                                                          ▼
                                              publish_posters.py
                                                          │
                                                          ▼
                                        dmo/docs/img/posters/*.png
                                        + <!-- POSTERS:slot --> section ในหน้าเว็บ
```

---

## ระบบ 1 — DMO Tracker (root)

สคริปต์ Python scrape ข่าวเกม **Digimon Masters Online** จาก dmo.gameking.com (+ KR/TH source)
แล้ว publish เป็น static HTML บน GitHub Pages. ไม่มี test suite / lint / venv — dep เดียวคือ `requests`.

### Pipeline หลัก (เรียงตาม data flow)

```
fetchers/  →  cache/*.html  →  scanners/  →  data/*.json  →  enrichers/ (เติม field)
                                                    │
                                                    ▼
                                          extractors/ (ดึงรูป → docs/img/)
                                                    │
                                                    ▼
                                          builders/ (gen HTML) → docs/*.html
```

### `fetchers/` — ดึง HTML จากเน็ต (เขียนลง cache/)

| ไฟล์ | หน้าที่ |
|------|--------|
| `fetch_dmowiki_digimon.py` | ดึงหน้า digimon จาก dmowiki.com ผ่าน Chrome CDP (เลี่ยง Cloudflare — ต้องเปิด Chrome debug port เอง + solve CAPTCHA มือ) |
| `fetch_dmowiki_icons.py` | ดึงไอคอน digimon จาก dmowiki |
| `fetch_kr_news_index.py` | scrape รายการโพสต์ KR Update board → `data/kr_news_index.json` |
| `fetch_th_patch_index.py` | scrape รายการ patch note เซิร์ฟ TH (vplay.in.th) → `data/th_patch_index.json` |
| `fetch_via_cdp.py` | helper กลาง เชื่อม Chrome ผ่าน CDP (ใช้ร่วมกับ `fetch_dmowiki_*`) |
| `fetch_wiki_rank_u.py` | ดึงหน้า Rank-U category จาก dmowiki → `rank_u.html` (root) — `build_rank_u_map()` ใน `fetch_dmowiki_digimon.py` ใช้ทำ name→slug mapping |

### `scanners/` — parse cache → JSON (offline, ไม่แตะเน็ต)

| ไฟล์ | หน้าที่ |
|------|--------|
| `scan_decks.py` | parse `[New Deck Add(ed)]` / `[Modify Existing Deck]` จาก cache → `data/scan_result.json` |
| `scan_digimon.py` | ⚠️ **destructive** — parse `[New Digimon ...]` marker แล้ว **rewrite ทับ** `data/scan_result_digimon.json` ทั้งไฟล์ ล้าง curation มือ (image, source_kr/th, attributes ฯลฯ) รันเฉพาะหลัง `scan_decks.py` ดึงโพสต์ใหม่มาแล้วเท่านั้น |
| `scan_kr_digimon_releases.py` | parse โพสต์ KR หา marker `[신규 디지몬 추가 - ชื่อ]` → `data/kr_digimon_releases.json` |
| `scan_na_nametag.py` | parse ข้อมูล nametag item ฝั่ง NA |
| `scan_th_patch_digimon.py` | parse โพสต์ TH หา marker `ดิจิมอนใหม่` → `data/th_patch_digimon.json` |
| `extract_deck_detail.py` | inspector เจาะดู Digimon List / Effect table ของโพสต์เดียว (table-aware parser คนละตัวกับ `scan_decks`) |
| `reparse_cache.py` | rebuild `scan_result.json` จาก cache ที่มีอยู่ ไม่ยิงเน็ตซ้ำ — ใช้ตอนแก้ parser logic |

### `enrichers/` — เติม field ลง JSON ที่มีอยู่ (ไม่ลบของเดิม)

| ไฟล์ | หน้าที่ |
|------|--------|
| `_content_match.py` | shared helper (ไม่ runnable) — normalize/keyword lookup/substring match/date parse ใช้โดย enrich kr+th |
| `apply_image_choices.py` | apply ผลเลือกรูปจาก `tools/curate.html` กลับลง JSON |
| `enrich_digimon_attributes.py` | เติม `attributes` (basic/element/families) จาก dmowiki ที่ cache ไว้ |
| `enrich_digimon_gameking.py` | เติม/override attribute จาก stat block ฝั่ง gameking (canonical กว่า dmowiki) |
| `enrich_digimon_kr.py` | จับคู่โพสต์ EN ↔ KR ด้วย **เนื้อหา** (keyword dict) ไม่ใช้วันที่ — เพราะ lag ไม่คงที่ (1 วันถึงหลายเดือน) |
| `enrich_digimon_rebalance.py` | เติมข้อมูล rebalance/buff-nerf |
| `enrich_digimon_th.py` | จับคู่โพสต์ EN ↔ TH เหมือน KR — เติม `source_th`/`date_th` |

### `extractors/` — โหลดรูป banner ต่อโพสต์

| ไฟล์ | หน้าที่ |
|------|--------|
| `_image_common.py` | shared helper (ไม่ runnable) — paths/scan JSON round-trip/base64-first extraction core ใช้โดยทั้ง 3 extractor |
| `extract_digimon_images.py` | ดึงรูป NA → `docs/img/digimon/<idx>.<ext>`, เติม field `image` |
| `extract_kr_digimon_images.py` | ดึงรูป KR (base64-inline ใน HTML) → `<idx>_kr.<ext>` |
| `extract_th_digimon_images.py` | ดึงรูป TH (wp-content/uploads) → เติม `image_th` (priority สูงสุดใน builder) |

### `builders/` — gen HTML จาก JSON

| ไฟล์ | หน้าที่ |
|------|--------|
| `aliases.py` | จัดการชื่อ digimon ที่สะกดต่างกัน (dub vs JP romanization) ผ่าน `data/digimon_aliases.json` — `norm()`/`canonical()` |
| `build_digimon_html.py` | gen `docs/digimon.html` เต็มจาก `scan_result_digimon.json` (fully auto) |
| `build_index_html.py` | gen หน้า hub `docs/index.html` |
| `build_nametag_html.py` | gen `docs/nametag.html` จาก nametag data |
| `build_seal_tables.py` | inject seal-exchange table ลง `docs/seals.html` แบบ **idempotent** (ST-marker guard) |
| `build_search_index.py` | gen `docs/search_index.json` สำหรับ cross-server lookup |
| `build_th_seal_en.py` | bootstrap `data/th_seal_en.json` (ชื่อซีล TH → EN) จาก rate-aligned pair |
| `compare_digimon_sources.py` | audit เทียบ attribute จาก gameking/KR/dmowiki เจอที่ขัดกัน |
| `diff_report.py` | เทียบ `scan_result.json` กับ `docs/decks.html` (หน้านี้แก้มือ ไม่ auto-gen) หาโพสต์ตกหล่น |
| `extract_seal_tables.py` | ดึง seal-exchange table ดิบจากทุกโพสต์ (NA/KR/TH) → `data/seal_tables.json` |

### `data/` — JSON source of truth ระหว่างขั้น pipeline

`scan_result.json` (deck), `scan_result_digimon.json` (digimon — **ไฟล์ curate มือหลัก**), `kr_*` / `th_*` (index + release ต่อเซิร์ฟ), `digimon_aliases.json`, `seal_tables.json`, `seal_ocr.json` (OCR ตารางที่มาเป็นรูป), `diff.json`, `na_nametag_items.json`

### `tools/` — เครื่องมือ throwaway

| ไฟล์ | หน้าที่ |
|------|--------|
| `curate.html` | standalone editor (file://) แก้ `scan_result_digimon.json` แบบมี image preview — pattern เดียวกับที่ใช้ทำ `backoffice.html` |
| `validate.py` | เช็คก่อน commit: JSON parse ครบ + HTML tag สมดุล + builder idempotent (รันซ้ำไม่มี diff) |

### `docs/` — เว็บ publish (GitHub Pages: dmo-hub.github.io/dmo)

| ไฟล์ | หน้าที่ |
|------|--------|
| `index.html` | หน้า hub เชื่อมไปทุกหน้า |
| `decks.html` | รายงาน deck ใหม่ — **แก้มือ** (มี table Digimon List/Effect ที่ auto-gen ไม่ไหว) |
| `digimon.html` | รายงาน digimon ใหม่ — auto-gen เต็มจาก `build_digimon_html.py` |
| `seals.html` | Seal Exchange ข้ามเซิร์ฟ NA/KR/TH + localStorage budget calculator |
| `lookup.html` | Cross-server name lookup (EN/KR/TH alias-aware) |
| `nametag.html` | ข้อมูล nametag item |
| `accessories.html`, `breakthrough.html` | หน้าเสริม — มีลิงก์เข้าจาก nav/seals ครบ ไม่ orphan |
| `seal-deal.html`, `seal-deal-calculator.html`, `seal-lookup-89.html`, `seal-patch-th-88.html`, `susanoomon-extreme-th-90.html` | หน้า one-off ผูก patch เฉพาะ |
| `styleguide.html` | reference component ทุกตัวของ site (copy-paste) |
| `css/site.css` | stylesheet กลางทุกหน้า (light/dark theme) — รวม `.poster-*` ที่เพิ่มไว้รองรับ backoffice |
| `js/theme.js` | toggle light/dark |
| `img/` | รูปทั้งหมด (~34MB) แยกโฟลเดอร์ย่อยตาม feature (`digimon/`, `posters/` ฯลฯ) |
| `search_index.json`, `seal_data.json` | data ที่หน้าเว็บ fetch ตอน runtime (client-side) |
| `plans/` | plan spec HTML (workflow "HTML is the new Markdown" ก่อน implement feature ใหญ่) |

### ไฟล์ root อื่น

`CLAUDE.md` (คู่มือฉบับเต็มของ repo — commands, architecture, conventions), `DESIGN.md` / `DESIGN-dmo.md` (design token reference), `README.md`, `requirements.txt` (แค่ `requests`), `pyproject.toml`

---

## ระบบ 2 — `poster-studio/` (git แยก)

โปสเตอร์โฆษณา FB สำหรับบริการรับเซอร์วิสดันเจี้ยนในเกม — data-driven HTML → export PNG

| ที่ | หน้าที่ |
|----|--------|
| `src/poster.html`, `src/dungeon.html`, `src/pricelist.html`, `src/items.html`, `src/trate.html` | template โปสเตอร์แต่ละแบบ (inline CSS, อ่าน data จาก json) |
| `src/data/poster.json` | single source ข้อมูล 6 ดันเจี้ยน + ราคา/brand |
| `assets/boss/` | รูป boss 6 ตัว (removebg โปร่งใส) |
| `assets/tooltips/` | รูป tooltip ไอเทมในเกม (อ้างอิงตอนออกแบบ) |
| `build/export_poster.mjs`, `export_dungeons.mjs`, `export_pricelist.mjs`, `export_items.mjs` | render HTML → PNG 2048px ผ่าน Playwright (boilerplate รวมอยู่ `build/lib/export_util.mjs`) |
| `dist/` | ผลลัพธ์ PNG พร้อมโพสต์ — **นี่คือ input ของ backoffice** (9 ไฟล์ ณ ตอนนี้) |
| `_src-images/` | รูปต้นฉบับ/reference ก่อน removebg (ไม่ใช้ build) |
| `docs/plans/PLAN_pptx-generator.html` | plan spec ของ feature pptx export |

รัน: `npm run serve` (static server 8777) → แก้ `poster.json`/`.html` → `npm run export` → PNG ใน `dist/`

---

## ระบบ 3 — `backoffice/` (git แยก, สร้างล่าสุด)

คุมว่ารูปใน `poster-studio/dist/` รูปไหน **approve ขึ้นเว็บ dmo ได้** และ **ขึ้นหน้าไหน**

| ไฟล์ | หน้าที่ |
|------|--------|
| `scan_posters.py` | glob `poster-studio/dist/*.png` → merge เข้า manifest, รูปใหม่ default `approved:false` เสมอ (ไม่ทับ curation เดิม, ไม่ลบรูปที่หายจาก dist ให้เอง) |
| `backoffice.html` | UI เปิด file:// ตรง ๆ (ไม่ต้องมี server) — drag-drop manifest, grid preview รูป, toggle approve, เลือกหน้า+slot (`top`=ใต้ hero / `bottom`=ท้ายหน้า) ต่อรูป, แก้ caption/link, filter, Download JSON กลับทับไฟล์ |
| `data/placements.json` | **source of truth** — list หน้าที่รองรับ (`pages`) + list โปสเตอร์พร้อม approve/placements/caption/link |
| `publish_posters.py` | อ่าน manifest → copy รูป approve ไป `dmo/docs/img/posters/` (ลบรูปที่เลิก approve) → แทรก/ถอด `<section class="poster-promo">` ในหน้าเว็บที่เลือก ด้วย marker `<!-- POSTERS:slot:START/END -->` (idempotent — รันซ้ำไม่มี diff) รองรับ `--docs-root` สำหรับ test แยกจากหน้าเว็บจริง |
| `README.md` | flow 4 ขั้น: scan → approve ใน UI → publish → review diff ใน dmo แล้ว commit เอง |

**flow เต็ม:** export poster ใหม่ใน studio → `scan_posters.py` → เปิด `backoffice.html` approve+เลือกหน้า → Download JSON ทับ manifest → `publish_posters.py` → `git diff docs/` ใน dmo → commit/push เอง (ไม่ auto)
