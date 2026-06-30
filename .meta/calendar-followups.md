# Calendar-polish — deferred follow-ups (final whole-branch review, 2026-06-29)

Merge blockers FIXED in-branch: RRULE INTERVAL=0 DoS, end-less all-day vanishing.
Cheap correctness folded in: DST month cells, max_events wiring, manifest/README align, week-scroll-reset, string-0 config clamp.

## Stream-lifecycle — deferred (final review 2026-06-30, branch merge-ready, no blockers):
- [ ] Remove the dead `--stream`/`default_stream` knob (workers are always created "sub"; CLI/print misleads). @DeprecatedRetention. player.py + cameras.example.yaml:25 + README.
- [ ] Worker shows last frame + green dot during a transient reconnect (status not refreshed once ready). Consider a "reconnecting" (yellow) state holding the frame. player.py run().
- [ ] `/api/streams` whole-reconcile not atomic (start-loop + stop-loop each locked, not together) — self-healing, single user can't trigger; optional: diff under one _MAIN_LOCK.
- [ ] Defensive: call pauseHiddenStreams() after promote()/picker onchange applyAssignments() (safe today via mkey stability).
- [ ] imencode-fail edge: status set "online" before encode; if encode fails ready stays False (pathological).
- [ ] Test cosmetic: stray `s_ready=None` + unused ctor params in FakeW (tests/test_streams.py).

## Deferred (fast-follow, NOT merge-blocking):
- [ ] DST fall-back off-by-one in the October month grid (renderMonth ms-stepping)
      FIX: Build cells with calendar-date overflow instead of ms arithmetic: `new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate()+idx)` at view.html:273, giving true local midnight across the CEST→CET transition. renderWeek does not exhibit the EU-transition defect; do not change line 308.
- [ ] Documented calendar config key max_events is dead — agenda count hardcoded to 5
      FIX: Either wire d.max_events through backend.fetch() return + renderAgenda (replace `const max=5` at view.html:219), or drop max_events from README.md:163/176 and manifest.yaml:5; align the manifest config list with the keys backend actually reads (lookback_days, lookahead_days, max_events_grid).
- [ ] Grid geometry (splitSpanByWeek/assignLanes/exclusive-end math) has zero behavioral test coverage — only string-presence checks
      FIX: Extract the pure JS helpers into a tiny module (or port the integer logic) and add causal tests: splitSpanByWeek across a week boundary returns 2 segments with correct col0/col1; assignLanes returns distinct lanes for overlap and the same lane for disjoint; dnum buckets 23:00 and 01:00 CEST same-date to the same index; all-day [s,s+1) covers exactly one day.
- [ ] EXDATE / RECURRENCE-ID overrides ignored — cancelled or moved instances render as ghosts
      FIX: Capture EXDATE during parse and skip matching occurrences in expand(); capture RECURRENCE-ID overrides and suppress the original instance for that timestamp. If deferred, document the limitation in the backend.py module header alongside the MONTHLY/YEARLY note.
- [ ] DAILY/WEEKLY expansion iterates from DTSTART across all history instead of from window_start
      FIX: When COUNT is absent, arithmetically fast-forward the cursor to the first occurrence >= window_start before the emit loop; keep counting from DTSTART only when COUNT is present (correctness).
- [ ] String "0" config values bypass defaults for lookback/lookahead/cap
      FIX: Parse-then-clamp at backend.py:127-129, e.g. `cap = int(config.get("max_events_grid") or 2000); cap = cap if cap>0 else 2000`, or a shared _pos_int(value, default) helper reused by the INTERVAL fix.
- [ ] Timed multi-day events in week view render as one oversized block in the start column; events starting before the visible week are dropped
      FIX: Clamp block height to the day's remaining hours and optionally emit per-covered-day continuation blocks; when dnum(start)<wsIdx but dnum(end)>=wsIdx, clamp di to 0 and top to 0 so the overlapping portion still appears (view.html:359-372).
- [ ] All-day events bucket to the previous day for viewers west of UTC
      FIX: Bucket all-day events by their stored UTC Y/M/D (offset-independent) rather than through local-offset dnum (view.html:162 with :239/:346), or emit all-day as floating dates from the backend; at minimum document the CEST assumption.
- [ ] Week view scroll position resets to 07:00 on every 5-minute periodic refresh
      FIX: Gate `hrs.scrollTop=7*HOUR` (view.html:376) to first paint / nav only — preserve and restore prior scrollTop on periodic re-render, or set it only when the rendered week changed.
- [ ] Calendar tests are presence-only and do not verify load-bearing pure logic
      FIX: Replace substring checks in tests/test_calendar_view.py with causal assertions on dnum, splitSpanByWeek, assignLanes, and all-day exclusive-end behavior (see grid-geometry follow-up).
- [ ] manifest.yaml config keys drift from backend (max_events vs max_events_grid; refresh_minutes unused)
      FIX: Align manifest.yaml:5 keys with what backend.fetch consumes (max_events_grid, lookback_days, lookahead_days) and drop refresh_minutes in favor of the top-level refresh_seconds.
- [ ] Initial page load tears down/restarts every MJPEG stream once (server media lacks data-mkey)
      FIX: Have _tile_media()/render_spotlight()/render_grid() emit a data-mkey equal to the exact media string the client computes (player.py:338/346/360), so the first setMedia is a no-op and server-started streams are reused.
- [ ] Active-tile center zone (.tpreview) renders left-grouped beside the name, not centered
      FIX: If true centering is intended, give `.tile.active .tpreview{margin:0 auto}` or let .tname flex:1 push it center (player.py:273-277/502-506); otherwise correct the comments to say 'left-grouped after the name'.
- [ ] Active-tile clickcatch blocks interaction with a plugin filler preview
      FIX: Add `.tile.active .clickcatch{pointer-events:none}` if plugin fillers should be interactive on the already-active tile (promote is a no-op there); otherwise document that filler previews are intentionally non-interactive.
- [ ] Divider 25% floor overrides the width-aware ceiling on narrow panels; restored split is not re-clamped
      FIX: Clamp the floor to the ceiling — `lo=Math.min(25,maxPct); pct=Math.max(lo,Math.min(Math.min(85,maxPct),pct))` — and run the same width-aware clamp on the saved value in initDivider before assigning flexBasis (player.py:563-564/576).
- [ ] .meta/rtsp.md still documents the removed /set_stream route and localStorage persistence
      FIX: Update the HTTP-surface table at .meta/rtsp.md:114/117: replace /set_stream with POST /api/streams {main:[lens_ids]}, add /api/sources + /api/layout, and change 'persisted (localStorage)' to 'persisted server-side (state.local.json via /api/layout)'.
- [ ] cameras.example.yaml comment 'main = full HD (default)' misleads under AUTO per-selection tiering
      FIX: Reword cameras.example.yaml:25 to clarify default_stream is the pre-client/headless tier only (AUTO tiering takes over once the dashboard loads); consider defaulting the example to sub for low startup load.
- [ ] Rapid out-of-order syncStreams POSTs can leave worker tiers mismatched with the UI, with no self-heal
      FIX: Make tier authoritative: tag each POST /api/streams with a monotonic client seq and have api_streams ignore stale seqs, or re-run syncStreams from current selection inside poll() so drift self-corrects within the poll cycle (player.py:586-588/651-657).
- [ ] Whole-device stale entries in state.local.json are never pruned
      FIX: On load, drop LAYOUT.devices entries whose device id has no rendered .device element (or no lens in SOURCES) before first save, or prune unknown device ids server-side in layout.save() against the config device list.
- [ ] README claims lens selection persists in localStorage; it is actually server-side state.local.json
      FIX: Change README.md:40 bullet to '(persisted server-side in state.local.json)'.
- [ ] README still advertises a manual 'Main HD / Sub stream toggle' replaced by automatic per-selection tiering
      FIX: Replace the toggle bullet (README.md:41, and 88-91/298-302) with a description of AUTO tiering (active/big-pane lens streams main, previews stream sub) and clarify --stream only seeds the initial pre-client mode.
- [ ] Pi deploy installs Flask via apt, bypassing the declared flask>=3.0 floor
      FIX: Either relax requirements.txt to flask>=2.2 to match the apt baseline (code uses no Flask-3-only APIs), or add an install-time version assertion in deploy/setup-pi.sh and document the minimum Debian release.
- [ ] Server-side markup interpolates lens/device ids raw (no html.escape) while names are escaped and the client esc()s ids
      FIX: Pass ids through html.escape(..., quote=True) at player.py render points (326/336/340/348/358/361/372) or validate ids as slug-safe at config load, mirroring the client esc() so the trusted-config assumption is enforced by construction.
- [ ] Plugin iframe sandbox uses allow-scripts + allow-same-origin (no real isolation)
      FIX: Document the trusted-first-party-plugin assumption near the sandbox attribute (player.py:325/427); if untrusted plugins are ever envisioned, serve plugin views from a distinct origin and drop allow-same-origin, or use postMessage instead of same-origin DOM access.
- [ ] New /plugin/calendar/data exposes personal calendar contents unauthenticated on 0.0.0.0
      FIX: Note the LAN-open posture in the README (calendar titles/times are unauthenticated) and/or add a bind-address/http_host config so private-calendar deployments can restrict to 127.0.0.1 (plugins.py:101-103, player.py:708).
- [ ] test_fetch_uses_broad_window_and_cap is misnamed and under-asserts (tests only the window, not the cap, and does not lock the 365d default)
      FIX: Rename to test_fetch_uses_broad_window and tighten: include an event at ~360d (asserted present) and one at ~370d (asserted absent), or assert against the configured default explicitly (tests/test_calendar.py:84-93).
- [ ] CWD-coupled module-level file reads with no conftest/rootdir pinning make collection fragile
      FIX: Add tests/conftest.py exposing ROOT = Path(__file__).resolve().parent.parent and resolve all fixture/view/backend paths against ROOT instead of process CWD (tests/test_calendar_view.py:2, test_calendar.py:7/13, test_touch_responsive.py:111).
- [ ] test_calendar_view.py smoke assertions on generic tokens (ctx, agenda) add near-zero regression value
      FIX: Drop the generic-token checks or replace with specific assertions (the cal.viewmode localStorage key, the data endpoint, and a paired negative such as the old auto-scroll agenda CSS being absent).
