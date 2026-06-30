# tests/test_calendar_geometry.py — CAUSAL coverage for the pure grid-geometry
# helpers (dnum / splitSpanByWeek / assignLanes) that live in the calendar view's
# inline <script>. We extract the ACTUAL function source from view.html (balanced-
# brace scan — no re-implementation) and execute it under node with concrete inputs,
# asserting real outputs. If the helper logic regresses in view.html, the extracted
# source changes and these assertions fail — that is the causality.
#
# NOTE: the all-day exclusive [s, s+1) clamp lives in renderMonth/renderWeek DOM code
# (not a standalone pure fn); its presence is locked by test_calendar_view.py
# (Math.max(...,s+1) / Math.max(dnum(...),s+1)). Full month/week DOM rendering remains
# covered by manual + this node repro of the geometry primitives it composes.
import os
import re
import shutil
import subprocess

import pytest

from tests.conftest import ROOT

VIEW = ROOT / "plugins" / "calendar" / "view.html"


def _extract_fn(src, name):
    """Return the full `function name(...){...}` source via balanced-brace scan."""
    start = src.index("function " + name + "(")
    depth = 0
    i = src.index("{", start)
    body_start = i
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    raise AssertionError("unbalanced braces extracting " + name)


def test_grid_geometry_helpers_causal(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available for grid-geometry repro")
    src = VIEW.read_text()
    ms_day = re.search(r"const MS_DAY=\d+;", src)
    assert ms_day, "MS_DAY const missing from view.html"

    harness = (
        ms_day.group(0) + "\n"
        + _extract_fn(src, "dnum") + "\n"
        + _extract_fn(src, "splitSpanByWeek") + "\n"
        + _extract_fn(src, "assignLanes") + "\n"
        + r"""
const J=JSON.stringify;
function eq(a,b,m){ if(J(a)!==J(b)) throw new Error(m+": got "+J(a)+" want "+J(b)); }

// --- splitSpanByWeek: clip a [start,endExcl) day-range into per-week row segments ---
eq(splitSpanByWeek(3,6,0), [{row:0,col0:3,col1:5}], "single-week span");
eq(splitSpanByWeek(5,10,0),
   [{row:0,col0:5,col1:6},{row:1,col0:0,col1:2}], "cross-week span splits at the boundary");
eq(splitSpanByWeek(10,12,7), [{row:0,col0:3,col1:4}], "weekStartIdx offset -> local cols");

// --- assignLanes: greedy lane packing of [s,e) day ranges (e exclusive) ---
eq(assignLanes([{s:0,e:2},{s:2,e:5}]), [0,0], "adjacent (e exclusive) share a lane");
eq(assignLanes([{s:0,e:3},{s:1,e:4}]), [0,1], "overlap -> separate lanes");
eq(assignLanes([{s:0,e:5},{s:1,e:2},{s:1,e:6}]), [0,1,2], "triple overlap -> 3 lanes");
eq(assignLanes([{s:0,e:2},{s:0,e:5},{s:3,e:4}]), [0,1,0], "lane reused once it frees");

// --- dnum: wall-clock day bucket. TZ=Europe/Warsaw (UTC+2 in July) makes the
//     getTimezoneOffset() subtraction load-bearing: without it, two times on the
//     same LOCAL date would straddle a UTC midnight and bucket differently. ---
const d0 = new Date(2026,6,3,0,0);    // local 2026-07-03 00:00
const dLate = new Date(2026,6,3,23,0);// local 2026-07-03 23:00 (same local date)
const dNext = new Date(2026,6,4,0,0); // local 2026-07-04 00:00
eq(dnum(d0), dnum(dLate), "same local date -> same day bucket (offset term load-bearing)");
eq(dnum(dNext), dnum(d0)+1, "next local day -> bucket + 1");

console.log("OK");
"""
    )
    js = tmp_path / "geom.js"
    js.write_text(harness)
    env = {**os.environ, "TZ": "Europe/Warsaw"}
    r = subprocess.run([node, str(js)], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, "node geometry repro failed:\n" + r.stdout + r.stderr
    assert "OK" in r.stdout
