# dvri-peek — review follow-ups tracker

## DONE — feat/followups (merged 2026-06-30)
- Calendar recurrence: EXDATE (skip cancelled, still count toward COUNT), RECURRENCE-ID overrides (suppress original, override renders), DAILY/WEEKLY expand-from-window-start (COUNT still counts from DTSTART).
- Cleanup/hardening: removed dead `--stream`/`default_stream` knob; `flask>=2.2` floor; `html.escape` on rendered ids; divider floor clamped under width-aware ceiling + re-clamp restored split; `pauseHiddenStreams` after promote/picker; `"reconnecting"` worker status (held frame → yellow dot); trusted-plugin/LAN-open posture documented.
- Regressions: switch-stall (force-close MJPEG sockets via `data:,` not `''`); NVR grid cells fit the panel (`grid-auto-rows:1fr`, dropped `aspect-ratio:16/9`) — no scroll.
- Test quality: conftest `ROOT` CWD-proofing across all test files; causal node grid-geometry test; tightened test_fetch window assertions; specific calendar_view asserts.

## DONE earlier (calendar-blockers / doc-drift / stream-lifecycle / kiosk)
- RRULE INTERVAL=0 DoS; end-less all-day; DST month cells; max_events wiring; string-0 config clamp; manifest/README/rtsp.md alignment; tiered sub/main workers + progressive load + bounded previews; kiosk.sh/run.sh/setup-pi.sh +x; WiFi power-save off + infinite retries.

## Remaining — low priority / defer (not worth blocking on)
- [ ] onclick id in nested JS-string context: `html.escape(quote=True)` is HTML-attr-safe but a literal `'` in an id isn't JS-string-neutralized. Theoretical only (ids are trusted first-party `cameras.yaml`); switch to `data-*` + delegated listener if ever untrusted.
- [ ] COUNT series with ancient DTSTART iterates DTSTART→window (bounded by lookahead, capped by max_events_grid). Intentional — preserves count-from-DTSTART. Accept.
- [ ] All-day events bucket by local day (correct for the CEST kiosk; would be off-by-one for viewers west of UTC). Document if ever non-CEST.
- [ ] iframe sandbox `allow-scripts allow-same-origin` + `/plugin/calendar/data` LAN-open unauthenticated. Documented posture; add a bind-host config only if a private-calendar deployment needs 127.0.0.1.
- [ ] Week view: a TIMED event crossing midnight renders one oversized block in the start column; events starting before the visible week are dropped. Minor.
- [ ] Initial page load tears down/restarts each server-started MJPEG once (server media lacks data-mkey). One-time flicker.
- [ ] Rapid out-of-order syncStreams POSTs can briefly mismatch tiers (self-heals next poll/promote). Minor.
- [ ] Whole-device stale entries in state.local.json never pruned (only per-tile ids reconcile). Minor.
- [ ] Active-tile `.tpreview` is left-grouped (not centered) + clickcatch makes the filler preview non-interactive. Intentional/design.
- [ ] imencode-fail edge: status "online" before encode; pathological.
