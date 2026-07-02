# tests/test_dashboard_view.py — markup contract for the combined dashboard view.
from tests.conftest import ROOT

H = (ROOT / "plugins" / "dashboard" / "view.html").read_text()
C = H.replace(" ", "").replace("\n", "")   # whitespace-insensitive CSS checks

def _rule(sel):
    i = C.index(sel); return C[i:C.index("}", i)]

def test_plugin_registered_and_two_contexts():
    from plugins import PluginRegistry
    reg = PluginRegistry(str(ROOT / "plugins")); reg.discover()
    p = reg.get("dashboard")
    assert p is not None and p.backend is not None and hasattr(p.backend, "fetch")
    assert {"tile", "main", "filler"} <= set(p.contexts)
    assert 'id="preview"' in H and 'id="dash"' in H       # preview + main both present
    assert "data-ctx" in H                                 # ctx-adaptive

def test_view_fetches_dashboard_data():
    assert 'fetch("/plugin/dashboard/data")' in H

def test_view_persists_mode_in_localstorage():
    assert 'localStorage.getItem("dash.viewmode")' in H
    assert 'localStorage.setItem("dash.viewmode"' in H

def test_main_has_month_week_and_controls():
    assert "cal-month" in H and "renderMonth" in H
    assert "cal-week" in H and "renderWeek" in H and "cal-allday" in H
    assert all(x in H for x in ("cal-prev", "cal-next", "cal-today", "cal-mode"))
    assert "splitSpanByWeek" in H and "assignLanes" in H   # spanning helpers present

def test_main_has_weather_forecast_and_upnext():
    assert "renderWx" in H and 'id="wx"' in H               # current weather
    assert 'class="fc"' in H or 'id="fc"' in H              # 5-day forecast strip
    assert "renderRailNext" in H and 'id="rail-next"' in H  # "up next" rail agenda

def test_preview_agenda_fits_tile_no_scroll():
    assert "renderPvAgenda" in H
    assert "overflow:hidden" in _rule("#preview{")          # preview clips (clickcatch owns the gesture)
    assert "overflow:hidden" in _rule("#pv-agenda{")
    assert "overflow:auto" not in _rule("#preview{")
    assert "slice(0,PV_MAX)" in H and "const PV_MAX=3" in H  # fixed small count

def test_news_is_scrolling_marquee():
    assert 'id="newsband"' in H and "renderNews" in H
    assert "news-track" in H and "@keyframes news-scroll" in H          # crawl animation
    assert "translateX(-50%)" in C                                       # loop by one content width
    assert "itemsHtml+itemsHtml" in H                                    # duplicated for seamless loop
    assert "prefers-reduced-motion:reduce" in C and ".news-track{animation:none}" in C  # reduced-motion honored

def test_view_dst_safe_and_exclusive_end_clamps():
    # month cells via calendar-date overflow (DST-safe), not ms arithmetic
    assert "getDate()+idx" in H and "gridStart.getTime()+idx*MS_DAY" not in H
    # week scroll-to-07:00 gated to first-paint / nav (preserve on refresh)
    assert "lastWeekKey" in H and "prevScroll" in H
    # all-day exclusive end clamped to >= start+1 (never zero-width) in both views
    assert "Math.max(eend,s+1)" in H and "Math.max(dnum(new Date(e.end||e.start)),s+1)" in H
