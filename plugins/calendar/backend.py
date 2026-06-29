# plugins/calendar/backend.py — merged multi-calendar agenda from secret ICS feeds.
# Stdlib only. Recurrence: non-recurring always; FREQ=DAILY|WEEKLY (INTERVAL,COUNT,
# UNTIL, weekly BYDAY) expanded in-window; MONTHLY/YEARLY -> original occurrence only.
import urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

def _http_get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read().decode("utf-8", "replace")

def _unfold(text):
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out

def _parse_dt(val, params):
    if params.get("VALUE") == "DATE" or (len(val) == 8 and "T" not in val):
        d = datetime.strptime(val, "%Y%m%d").replace(tzinfo=timezone.utc)
        return d, True
    if val.endswith("Z"):
        return datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), False
    naive = datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        try:
            return naive.replace(tzinfo=ZoneInfo(tzid)).astimezone(timezone.utc), False
        except Exception:  # noqa: BLE001 — unknown zone: fall through to UTC
            pass
    return naive.replace(tzinfo=timezone.utc), False

def parse_ics(text):
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"summary": "", "start": None, "end": None, "allday": False, "rrule": None}
        elif line == "END:VEVENT":
            if cur and cur["start"] is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            name, _, value = line.partition(":")
            key, *parts = name.split(";")
            params = dict(p.split("=", 1) for p in parts if "=" in p)
            key = key.upper()
            if key == "SUMMARY":
                cur["summary"] = value
            elif key == "DTSTART":
                cur["start"], cur["allday"] = _parse_dt(value, params)
            elif key == "DTEND":
                cur["end"], _ = _parse_dt(value, params)
            elif key == "RRULE":
                cur["rrule"] = dict(kv.split("=", 1) for kv in value.split(";") if "=" in kv)
    return events

def _rrule_until(rule):
    if "UNTIL" in rule:
        u = rule["UNTIL"]
        try:
            return datetime.strptime(u, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.strptime(u[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
    return None

def expand(events, window_start, window_end):
    out = []
    for e in events:
        rule = e.get("rrule")
        dur = (e["end"] - e["start"]) if e.get("end") else timedelta(0)
        if not rule:
            if e["start"] <= window_end and (e.get("end") or e["start"]) >= window_start:
                out.append({**e, "end": e["start"] + dur})
            continue
        freq = rule.get("FREQ")
        interval = int(rule.get("INTERVAL", 1) or 1)
        count = int(rule["COUNT"]) if "COUNT" in rule else None
        until = _rrule_until(rule)
        emitted = 0
        if freq == "DAILY":
            cur = e["start"]; step = timedelta(days=interval)
            while cur <= window_end and (until is None or cur <= until):
                if cur >= window_start:
                    out.append({**e, "start": cur, "end": cur + dur, "rrule": None})
                emitted += 1
                if count and emitted >= count:
                    break
                cur += step
        elif freq == "WEEKLY":
            bydays = [_WEEKDAYS[d] for d in rule.get("BYDAY", "").split(",") if d in _WEEKDAYS]
            if not bydays:
                bydays = [e["start"].weekday()]
            week0 = e["start"] - timedelta(days=e["start"].weekday())
            wk = 0
            while True:
                base = week0 + timedelta(weeks=wk * interval)
                if base > window_end or (until and base > until):
                    break
                for wd in sorted(bydays):
                    occ = base.replace(hour=e["start"].hour, minute=e["start"].minute,
                                       second=e["start"].second) + timedelta(days=wd)
                    if occ < e["start"]:
                        continue
                    if until and occ > until:
                        continue
                    if occ > window_end:
                        continue
                    if occ >= window_start:
                        out.append({**e, "start": occ, "end": occ + dur, "rrule": None})
                    emitted += 1
                    if count and emitted >= count:
                        break
                if count and emitted >= count:
                    break
                wk += 1
        else:  # MONTHLY/YEARLY/unknown -> original occurrence only
            if window_start <= e["start"] <= window_end:
                out.append({**e, "end": e["start"] + dur, "rrule": None})
    return out

def fetch(config, now=None):
    lookback = int(config.get("lookback_days", 90) or 90)
    lookahead = int(config.get("lookahead_days", 365) or 365)
    cap = int(config.get("max_events_grid", 2000) or 2000)
    sources = config.get("sources", []) or []
    now = now or datetime.now(timezone.utc)
    w0 = now - timedelta(days=lookback)
    w1 = now + timedelta(days=lookahead)
    merged, errors = [], []
    for src in sources:
        try:
            text = _http_get(src["ics_url"])
            for ev in expand(parse_ics(text), w0, w1):
                merged.append({
                    "title": ev["summary"],
                    "start": ev["start"].isoformat(),
                    "end": (ev["end"] or ev["start"]).isoformat(),
                    "allday": ev["allday"],
                    "source": src.get("name", ""),
                    "color": src.get("color", "#888"),
                    "_sortkey": ev["start"],
                })
        except Exception as e:                           # noqa: BLE001
            errors.append({"source": src.get("name", ""), "error": str(e)})
    merged.sort(key=lambda e: e["_sortkey"])
    truncated = len(merged) > cap
    events = merged[:cap]
    for e in events:
        del e["_sortkey"]
    out = {"events": events, "generated": now.isoformat()}
    if truncated:
        out["truncated"] = True
    if errors:
        out["errors"] = errors
    return out
