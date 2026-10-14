# Sirens — Weekly KPI Scoreboard

Team: Elie Boutros, Bassam Eter (one team, no individual feature ownership)
Capacity: ~10 h/week total
Start: week of 2026-10-12 · Deadline: end of month (exact date TBC)
Deliverable: live demo + written report + code

**Rules:** each session states this week's KPI, works only on it, and ends by
ticking what is done. Cut-line: defer the lowest item rather than extend into
week 4. Only tick an item when it has been verified (pasted output or a
working check), not just "edited".

Status: [x] done (verified) · [~] in progress · [ ] not started

## W1 — Foundation
- [~] Feature branch pushed (`bassam/w1-foundation` on fork, draft PR open). Done once Elie reviews.
- [x] `.gitignore` excludes `data/sirens.db*`, `.venv`, `venv`, `__pycache__`, `data/photos/`.
  Evidence 2026-10-12: `git check-ignore -v` matches all of them; the committed
  `venv/` (7,969 files) is no longer tracked; `git ls-files venv | wc -l` = 0.
- [~] Fresh clone runs from README in <= 10 min. Evidence 2026-10-12 (cloud
  machine, not the real test): fresh clone, `bash setup.sh`, `python app.py`,
  demo data loaded in 45 s. Still needed: timed run on a second laptop.
- [x] Demo-mode button loads sample data. Evidence: `/demo` page, "Load demo
  data (fabricated)" button; `tests/test_demo.py` passes (temp DB, 40
  incidents); clicked in a headless browser: "40 in database".
- [~] htmx + Chart.js load from `static/vendor/` with network off. Evidence:
  `/vendor-check` in headless Chromium with every non-127.0.0.1 request
  blocked: htmx 2.0.11 and Chart.js 4.5.1 detected, chart drawn, htmx swap
  works, zero external requests; `tests/test_vendor.py` passes (no external
  script/stylesheet in any template). Still needed: open it with Wi-Fi off.
- [x] DB tables for link decisions and notes exist (`linker/decisions.py`).
  Evidence: `python -m linker.decisions` ends with `SELF-CHECK PASSED`;
  `tests/test_decisions.py` passes.

## W2 — Analyst workbench
- [x] Confirm / Reject / Unsure on every link, no page reload. Evidence
  2026-10-12: `/review` (review_bp.py) lists all 74 tree links on the demo
  data, each with Confirm / Reject / Unsure / Undo and a note box (htmx);
  `tests/test_review.py` passes; headless Chromium: decision + note swap in
  place, 0 navigations, 0 server/JS errors, 0 external requests.
- [x] Decisions + notes persist across restart. Evidence:
  `tests/test_persistence.py` (two separate processes, same temp DB) passes;
  live server stopped and restarted: decision and note still shown.
- [x] Scripted 10-click test: zero server errors. Evidence:
  `tests/test_ten_clicks.py` passes (10 clicks, all < 500); same flow by
  hand in headless Chromium: 10 clicks, 0 server errors, 0 JS errors.
- Still to do on a laptop: try `/review` by hand with Wi-Fi off; Elie to
  review the page design.

## W3 — Dashboard + auto-flagging
- [x] Timeline chart + 2 more charts + working filters. Evidence 2026-10-12:
  `/dashboard` (dashboard_bp.py): incidents per month, by area, by
  initiation method, 4 tiles; one filter row (date range, area, method) plus
  click-a-bar filtering; table twin per chart; `tests/test_dashboard.py`
  passes (totals add up, every method bar equals its filter result);
  headless Chromium: 3 charts drawn, filters work, 0 errors, 0 external requests.
- [x] Saving a report shows its likely network with band + reasons.
  Evidence: network_bp.py panel loads on the console result after Save;
  `tests/test_network.py` passes (network, size, band and reasons match the
  link-tree clustering); headless Chromium: panel shown after saving a
  fabricated report, 0 errors.
- Still to do on a laptop: try both pages with Wi-Fi off; Elie to review design.
- Caution found while testing (matcher not changed): a fabricated report
  near Meiss ej-Jabal got a 1.00 "strong" link partly from "same individual
  (Meiss)", i.e. the village name read as a person. This inflates scores, so
  the place-name issue below is worth fixing before the demo.

## W4 — Freeze / polish / deliver
- [x] Tooltips on all form fields. Evidence 2026-10-13: every field on the
  console, brief, review and dashboard forms has an (i) help (hover, tap,
  keyboard focus; Escape/click-away closes); `tests/test_forms.py` checks every
  field on all four forms; checked by hand in headless Chromium.
- [ ] Regression test fails if F1 < 0.73
- [ ] README with screenshots
- [ ] Written report, first draft
- [ ] Deck updated
- [ ] Full demo rehearsal with the model pre-loaded
- Stretch: CSV/JSON import · live threshold slider · completeness badge

## UI: header, forms, map (branch `bassam/ui-header-forms-map`, 2026-10-13)
- [x] Header pinned on all 8 pages. Evidence: headless Chromium at 1366x768,
  scrolled to the bottom, header at top 0 and clickable; menu 64/64; 10-click
  workflow zero errors.
- [x] All 4 forms use the shared form CSS and macros (`forms_ui.py`,
  `static/forms.css`, `static/forms.js`); field inventory in the session report.
- [x] (i) help on every form field (see W4 tooltips above).
- [x] Arabic round trip (report + note) passes; location suggestions and
  "Not a known place" note work; filter chips add/remove; "Saved"
  confirmation and Likely network box still work. Evidence: `tests/test_forms.py`
  + headless Chromium at 1366 px and 390 px (no horizontal overflow).
- [~] `/map` shows the offline street map, Lebanon only, road names on hover.
  Evidence: works end to end with a SYNTHETIC test map file (headless Chromium,
  all outside requests blocked: map draws, mask + pan limit, road hover shows
  English/Arabic name and ref, popups, HTTP Range). **Needs laptop:** build or
  download the real OSM file (`scripts/map/build_map.sh`), record its size and
  checksum, publish it as a release asset, then check it on Elie's laptop.
- [x] No request outside 127.0.0.1 with the internet blocked (browser check;
  `tests/test_map.py` + `tests/test_vendor.py` cover style, fonts, glyphs,
  sprites, scripts and stylesheets).
- [x] MGRS grid (100 km / 10 km / 1 km), live readout and click-to-copy work;
  incident popups show MGRS marked approx. (caza centre) unless a grid was filed.
- [x] MGRS tests pass against independent references (`mgrs`, `pyproj`),
  including both sides of 36 E (`tests/test_mgrs.py`).
- Tests: 89 pass (was 57). Accuracy re-measured: unchanged.

## Measured accuracy (only numbers we actually measured)
| Date | Data | Threshold | P | R | F1 |
|---|---|---|---|---|---|
| (before W1) | 100 synthetic, seed 7 | 0.25 | 0.628 | 0.888 | 0.736 |
| 2026-10-12 | 100 synthetic, seed 7 | 0.25 | 0.628 | 0.888 | 0.736 |
| 2026-10-12 (after W2, matcher untouched) | 100 synthetic, seed 7 | 0.25 | 0.628 | 0.888 | 0.736 |
| 2026-10-12 (after W3, matcher untouched) | 100 synthetic, seed 7 | 0.25 | 0.628 | 0.888 | 0.736 |
| 2026-10-13 (after header/forms/map/MGRS, matcher untouched) | 100 synthetic, seed 7 | 0.25 | 0.628 | 0.888 | 0.736 |

Target: P 0.90 / R 0.80 / F1 0.85.

## Open items to verify on Elie's laptop
- BEFORE pulling: back up the local DB (`cp data/sirens.db data/sirens.db.bak`).
- Pulling commit 828e3ec deletes the old `venv/` folder from disk (it is no
  longer tracked). That is expected: run `bash setup.sh` to get `.venv/`.
- GitHub already has `debug=False`, the width / watermark / checkbox CSS and
  the brief "Incidents on record here" list; `tests/` exists. Check whether
  any newer unpushed edits differ, then merge them (app.py changed by only 3
  lines on this branch: 2 Blueprint registrations, 1 nav link).
- Open `/vendor-check` with Wi-Fi off; both rows must say "ok".
- Check the AI panels with Ollama running (not testable in the cloud session).
- Not fixed (outside W1, decide later): root `cli.py` has a SyntaxError on
  line 1 (README "Use" section relies on it); `anthropic` is in
  requirements.txt but never imported; `data/generated/` is tracked.
- Extraction quality (seen on /review, not changed: the matcher was
  off-limits this session): the top demo link INC-008 <-> INC-040 cites "same
  individual (Meiss)", but Meiss is the place name Meiss ej-Jabal picked up
  as a person. An analyst can now Reject such links; fixing the extractor is
  a separate decision.

## Session log
- 2026-10-12 (Bassam, browser): forked repo, created branch, fixed
  `.gitignore`, untracked `sirens.db`, added this scoreboard.
    Also: vendored htmx 2.0.11 + Chart.js 4.5.1; added linker/decisions.py
  (written in browser, NOT yet run: verify with `python -m linker.decisions`).
- 2026-10-12 (Bassam + Claude Code, cloud session): ran everything for the
  first time. Install from README: 37 s. Decisions self-check passed. Pages
  `/`, `/map`, `/tree`, `/brief` return 200; no crash without Ollama.
  Accuracy re-measured: identical to baseline (table above).
  Changed: untracked committed `venv/` and fixed ignore rules; removed
  leftover `import_500.py`, `load_500.py`, `data/consolidated_incidents.json`;
  added `/vendor-check` (vendor_bp.py) and `/demo` (demo_bp.py) Blueprints;
  added tests (21 pass, temp DB only); fixed README/setup.sh install steps.
  Still unverified: Wi-Fi-off test, timed second-machine install, AI with
  Ollama. Elie: see "Open items" above.
- 2026-10-12 (Bassam + Claude Code, W2, same session): added `/review`
  link-review page (review_bp.py): Confirm / Reject / Unsure / Undo + notes
  on every link via htmx, filters, analyst initials; `all_notes()` helper in
  decisions.py. Tests: review page, restart persistence (two processes),
  10-click workflow; 32 pass. app.py: +2 lines (registration, nav link).
  Accuracy re-measured: unchanged. Unverified: Wi-Fi-off use of /review.
- 2026-10-12 (Bassam + Claude Code, W3, same session): added `/dashboard`
  (timeline + area + initiation charts, filters, tables; vendored Chart.js)
  and the likely-network panel shown after saving a report (network_bp.py,
  htmx). app.py: +4 lines (2 registrations, 1 nav link, panel placeholder)
  and the htmx script tag in the console template. 45 tests pass. Accuracy
  re-measured: unchanged. Unverified: Wi-Fi-off use of the new pages.
- 2026-10-13 (Bassam + Claude Code, UI pass): one shared drop-down menu on
  all 8 pages (Reports / Analysis / Data, current page highlighted; ui_menu.py);
  dashboard expanded with signatures (feature selector + filter), candidate
  networks, link strength + review progress, and data quality
  (linker/stats.py); link tree restyled to the light theme with a
  colour-vision-checked muted cluster palette; console empty panel points to
  dashboard / review / tree and no longer says "13 samples". Found and fixed
  the open menu being covered by page content on console and brief. 57 tests
  pass; 64/64 menu clicks and the 10-click workflow pass in headless
  Chromium; accuracy re-measured: unchanged (0.628 / 0.888 / 0.736).
- 2026-10-13 (Bassam + Claude Code, branch `bassam/ui-header-forms-map`):
  pinned header; one shared form design with (i) help on every field, Arabic
  input, place suggestions, chips, Saving/Saved, calm error pages; /map replaced
  by an offline OpenStreetMap street map (MapLibre + PMTiles, Lebanon only,
  road hover) with an MGRS grid, readout, click-to-copy and MGRS in popups.
  89 tests pass; accuracy unchanged. Needs laptop: real map file (build,
  size, checksum, release asset), Wi-Fi-off run, map speed on Elie's laptop,
  Ollama check, timed fresh install. PR for this branch not opened yet (review first).
