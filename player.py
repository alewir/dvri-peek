#!/usr/bin/env python3
"""Multi-camera live preview.

Reads cameras.yaml (single source of truth), generates a go2rtc config, spawns
go2rtc to bridge the proprietary DVRIP protocol (XiongMai/ICSee, port 34567 —
the only way the 3-lens camera exposes lenses 2 & 3) into plain RTSP, then
decodes each stream with OpenCV and serves a web UI:

  * one TAB per device
  * "spotlight" layout: big pane (left 2/3) + lens thumbnails (right);
    click a thumbnail to promote it to the big pane — the active lens's
    thumbnail is disabled (not streamed twice).
  * "grid" layout for simple multi-cam devices (the NVR).

RTP is carried over TCP everywhere (WSL2 NAT drops UDP RTP return packets).

Usage:  python player.py [--config cameras.yaml] [--stream sub|main] [--port N]
Open    http://localhost:<port>
"""
import os
import sys
import time
import json
import html
import signal
import argparse
import threading
import subprocess
import urllib.request
import urllib.parse

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;8000000|max_delay;500000",
)

import cv2
import numpy as np
import yaml
from flask import Flask, Response, jsonify, request

import layout as layout_mod
import plugins as plugins_mod

# dvrip/rtsp stream index per mode
SUBTYPE = {"sub": 1, "main": 0}        # dvrip subtype / rtsp stream index

GO2RTC_PROC = None


# --------------------------------------------------------------------------- #
#  Config + go2rtc generation
# --------------------------------------------------------------------------- #
def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _dvrip_url(dev, channel, subtype):
    u = urllib.parse.quote(str(dev.get("icsee_user", "")), safe="")
    p = urllib.parse.quote(str(dev.get("icsee_pass", "")), safe="")
    return (f"dvrip://{u}:{p}@{dev['host']}:{dev.get('dvrip_port', 34567)}"
            f"?channel={channel}&subtype={subtype}")


def _rtsp_url(dev, rtsp_channel, stream_idx):
    return (f"rtsp://{dev['host']}:{dev.get('rtsp_port', 554)}"
            f"/user={dev.get('rtsp_user','admin')}&password={dev.get('rtsp_pass','')}"
            f"&channel={rtsp_channel}&stream={stream_idx}.sdp?real_stream")


def build_go2rtc_config(cfg, out_path):
    """Generate a go2rtc YAML. Each lens gets a <id> (sub) and <id>_main stream,
    each a failover list: DVRIP first, then RTSP fallback when available."""
    gw = cfg.get("gateway", {})
    streams = {}
    lens_index = {}   # lens_id -> {device, name, has_main}
    for dev in cfg["devices"]:
        for lens in dev["lenses"]:
            lid = lens["id"]
            for mode, sub in SUBTYPE.items():
                name = lid if mode == "sub" else f"{lid}_main"
                srcs = [_dvrip_url(dev, lens["channel"], sub)]
                if "rtsp_channel" in lens:
                    srcs.append(_rtsp_url(dev, lens["rtsp_channel"], sub))
                streams[name] = srcs
            lens_index[lid] = {"device": dev["id"], "name": lens.get("name", lid)}
    g2 = {
        "log": {"level": "info"},
        "api": {"listen": f"{gw.get('api_host','127.0.0.1')}:{gw.get('api_port',1984)}"},
        "rtsp": {"listen": f":{gw.get('rtsp_port',8554)}"},
        "streams": streams,
    }
    with open(out_path, "w") as f:
        yaml.safe_dump(g2, f, sort_keys=False, default_style="'")
    return lens_index


def start_go2rtc(cfg, config_path):
    global GO2RTC_PROC
    gw = cfg.get("gateway", {})
    binary = gw.get("go2rtc_bin", "./go2rtc")
    binary = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          binary) if binary.startswith("./") else binary
    logf = open("/tmp/go2rtc_player.log", "w")
    GO2RTC_PROC = subprocess.Popen([binary, "-config", config_path],
                                   stdout=logf, stderr=subprocess.STDOUT)
    api = f"http://{gw.get('api_host','127.0.0.1')}:{gw.get('api_port',1984)}/api/streams"
    for _ in range(100):
        try:
            urllib.request.urlopen(api, timeout=1)
            return
        except Exception:
            time.sleep(0.1)
    print("WARNING: go2rtc API did not come up", file=sys.stderr)


def stop_go2rtc():
    if GO2RTC_PROC and GO2RTC_PROC.poll() is None:
        GO2RTC_PROC.terminate()
        try:
            GO2RTC_PROC.wait(timeout=5)
        except Exception:
            GO2RTC_PROC.kill()


# --------------------------------------------------------------------------- #
#  Per-lens grabber (reads go2rtc's RTSP restream)
# --------------------------------------------------------------------------- #
class LensWorker(threading.Thread):
    def __init__(self, lens_id, name, gw, jpeg_quality, target_fps, stream_mode):
        super().__init__(daemon=True)
        self.id = lens_id
        self.name = name
        self._rtsp_host = gw.get("api_host", "127.0.0.1")
        self._rtsp_port = gw.get("rtsp_port", 8554)
        self.jpeg_quality = jpeg_quality
        self.min_period = 1.0 / max(target_fps, 1)
        self._mode = stream_mode
        self._lock = threading.Lock()
        self._jpeg = None
        self._stop = threading.Event()
        self._reconnect = threading.Event()
        self.status = "connecting"
        self.resolution = "-"
        self.fps = 0.0

    def url(self):
        name = self.id if self._mode == "sub" else f"{self.id}_main"
        return f"rtsp://{self._rtsp_host}:{self._rtsp_port}/{name}"

    def set_stream(self, mode):
        if mode in SUBTYPE and mode != self._mode:
            self._mode = mode
            self._reconnect.set()

    @property
    def stream_mode(self):
        return self._mode

    def stop(self):
        self._stop.set()

    def get_jpeg(self):
        with self._lock:
            return self._jpeg

    def _placeholder(self, lines, color=(60, 200, 255)):
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        for i, line in enumerate(lines):
            cv2.putText(img, line, (24, 70 + 38 * i),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", img)
        with self._lock:
            self._jpeg = buf.tobytes() if ok else None

    def run(self):
        enc = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        while not self._stop.is_set():
            self._placeholder([self.name, "connecting..."])
            self.status = "connecting"
            cap = cv2.VideoCapture(self.url(), cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                self.status = "no signal / needs credentials"
                self._placeholder([self.name, "NO SIGNAL", "(needs camera credentials?)"])
                cap.release()
                if self._stop.wait(3.0):
                    break
                continue
            self._reconnect.clear()
            fail = 0
            t_prev = time.time()
            fps_ema = 0.0
            while not self._stop.is_set() and not self._reconnect.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    fail += 1
                    if fail > 40:
                        self.status = "no signal / needs credentials"
                        self._placeholder([self.name, "NO SIGNAL", "(needs camera credentials?)"])
                        break
                    time.sleep(0.05)
                    continue
                fail = 0
                now = time.time()
                dt = now - t_prev
                t_prev = now
                if dt > 0:
                    fps_ema = 0.9 * fps_ema + 0.1 / dt if fps_ema else 1.0 / dt
                self.fps = round(fps_ema, 1)
                h, w = frame.shape[:2]
                self.resolution = f"{w}x{h}"
                self.status = f"online ({self._mode})"
                ok2, buf = cv2.imencode(".jpg", frame, enc)
                if ok2:
                    with self._lock:
                        self._jpeg = buf.tobytes()
                time.sleep(self.min_period * 0.5)
            cap.release()


# --------------------------------------------------------------------------- #
#  App
# --------------------------------------------------------------------------- #
app = Flask(__name__)
CFG = None
WORKERS = {}        # lens_id -> LensWorker
DEVICES = []        # config devices (for rendering)
REGISTRY = None
STORE = None


def load_secrets(path):
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except (FileNotFoundError, OSError):
        return {}


PAGE_HEAD = """<!doctype html><html><head><meta charset="utf-8">
<title>dvri-peek</title>
<style>
 :root{--bg:#0e0e10;--panel:#1a1a1d;--line:#2e2e33;--txt:#e4e4e7;--accent:#2563eb;}
 *{box-sizing:border-box}
 html,body{height:100%}
 body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,Segoe UI,Arial,sans-serif;
      display:flex;flex-direction:column;height:100vh;overflow:hidden}
 header{flex:0 0 auto;display:flex;align-items:center;gap:8px;padding:8px 14px;background:#161619;
        border-bottom:1px solid var(--line);z-index:10}
 .tab{background:#222;border:1px solid var(--line);color:#cfcfd4;border-radius:7px;
      padding:7px 14px;cursor:pointer;font-size:13px;font-weight:600}
 .tab.active{background:var(--accent);border-color:var(--accent);color:#fff}
 .right{margin-left:auto;display:flex;gap:6px;align-items:center}
 .sbtn{background:#222;border:1px solid var(--line);color:#cfcfd4;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:12px}
 .device{display:none;padding:10px;flex:1 1 auto;min-height:0}
 .device.active{display:flex;flex-direction:column;min-height:0}
 /* spotlight */
 .spot{display:flex;gap:0;align-items:stretch;flex:1 1 auto;min-height:0}
 .big{flex:0 0 66%;min-width:160px;display:flex;flex-direction:column;background:#000;border:1px solid var(--line);border-radius:10px;overflow:hidden}
 .big .cap{flex:0 0 auto;padding:6px 12px;font-size:13px;font-weight:600;background:#141417}
 .divider{flex:0 0 16px;margin:0 5px;cursor:col-resize;border-radius:7px;background:#3a3a42;touch-action:none;
          display:flex;align-items:center;justify-content:center;user-select:none;color:#cbd5e1;font-size:18px;line-height:1}
 .divider:hover,.divider.drag{background:var(--accent);color:#fff}
 .thumbs{flex:1 1 0;min-width:150px;display:flex;flex-direction:column;gap:8px}
 .tile{flex:1 1 0;min-height:0;position:relative;background:#000;border:2px solid var(--line);border-radius:9px;
       overflow:hidden;cursor:pointer;display:flex;flex-direction:column}
 .tile.active{outline:2px solid var(--accent);outline-offset:-2px;cursor:default}
 .tname{flex:1 1 0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .tmeta{flex:0 0 auto;white-space:nowrap;font-size:10px;color:#9ca3af;font-variant-numeric:tabular-nums}
 /* active tile = 3-zone strip: name (left) · [preview: filler] (center, muted) · status (right) */
 .tpreview{flex:0 99 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
   font-size:10px;font-weight:500;color:#8b8b93}
 .tpreview:empty{display:none}
 .tile.active .tname{flex:0 1 auto}
 .tile.active .tmeta{margin-left:auto}
 .tile .placeholder{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
            color:#9ca3af;font-size:13px;text-align:center;padding:10px}
 /* header strip — always-visible row above media; tile = flex col → [strip][media] */
 .tilehead{display:flex;align-items:center;gap:6px;padding:3px 8px;font-size:11px;font-weight:600;
   color:var(--txt);background:#141417;border-bottom:1px solid #1c1c21;flex:0 0 auto;min-height:22px}
 .tile.active .tilehead{border-left:3px solid var(--accent);padding-left:5px}
 .dot{width:8px;height:8px;border-radius:50%;background:#888;display:inline-block;margin-right:5px}
 .on{background:#22c55e}.off{background:#ef4444}.wait{background:#eab308}
 /* grid */
 .grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));flex:1 1 auto;min-height:0;overflow:auto;align-content:start}
 .cell{background:#000;border:1px solid var(--line);border-radius:9px;overflow:hidden;display:flex;flex-direction:column;aspect-ratio:16/9}
 /* collapsible header */
 header.collapsed{display:none}
 /* thin 6px visual accent (::before) inside a taller transparent ~24px touch target */
 #revealbar{position:fixed;top:0;left:0;right:0;height:24px;background:transparent;cursor:pointer;z-index:20;display:none}
 #revealbar::before{content:"";position:absolute;top:0;left:0;right:0;height:6px;background:#2563eb55}
 body.headerhidden #revealbar{display:block}
 /* settings mode */
 .picker-wrap{position:absolute;inset:auto 6px 6px 6px;z-index:5;display:none;
              background:rgba(14,14,16,.88);border-radius:5px;padding:3px 6px}
 body.settings .tile .picker-wrap,body.settings .cell .picker-wrap{display:flex;align-items:center;gap:5px}
 .picker-lbl{font-size:10px;font-weight:700;color:#9ca3af;white-space:nowrap;flex:0 0 auto;text-transform:uppercase;letter-spacing:.04em}
 .picker{flex:1 1 auto;min-width:0;background:#1e1e24;color:var(--txt);border:1px solid var(--line);
         border-radius:4px;font-size:11px;padding:2px 4px;cursor:pointer}
 .pluginframe{width:100%;height:100%;border:0;background:#000;display:block}
 /* iframes (plugins) swallow mouse events; a parent-doc overlay restores click-to-promote
    on tiles (clicks bubble to the tile's onclick). The divider uses pointer capture, so
    pointermove is routed to it even over the big-pane iframe — no drag shield needed. */
 .tile .clickcatch{position:absolute;inset:0;z-index:1;cursor:pointer}
 .tile.active .clickcatch{cursor:default}
 /* big pane media container */
 .bigmedia{flex:1 1 auto;min-height:0;overflow:hidden;background:#000}
 .bigmedia img{width:100%;height:100%;object-fit:contain;display:block}
 .bigmedia iframe{width:100%;height:100%;border:0;display:block}
 /* tile / cell media container — fills remaining height under the header strip */
 .tmediadiv{flex:1 1 auto;min-height:0;position:relative;overflow:hidden}
 .tmediadiv img{width:100%;height:100%;object-fit:contain;background:#000;display:block}
 .tmediadiv iframe{width:100%;height:100%;background:#000;border:0;display:block}
</style></head><body>
"""


def _tile_media(source_id, ctx):
    """Return inner media HTML for a source in a given context (tile/main/filler)."""
    if source_id and source_id.startswith("plugin:"):
        pid = source_id.split(":", 1)[1]
        return (f'<iframe class="pluginframe" src="/plugin/{pid}/view?ctx={ctx}"'
                f' frameborder="0" sandbox="allow-scripts allow-same-origin"></iframe>')
    return f'<img class="cam" data-id="{source_id}" src="/stream/{source_id}">'


def render_spotlight(dev):
    lenses = dev["lenses"]
    first = lenses[0]["id"]
    thumbs = ""
    for ln in lenses:
        lid, lname = ln["id"], ln.get("name", ln["id"])
        thumbs += f"""
        <div class="tile" id="th-{lid}" data-lens="{lid}" data-slot="{lid}" data-source="{lid}" data-dev="{dev['id']}" onclick="promote('{dev['id']}','{lid}')">
          <div class="tilehead" id="tilehead-{lid}"><span class="tname">{html.escape(lname)}</span><span class="tpreview"></span><span class="tmeta"></span></div>
          <div class="tmediadiv" id="tmedia-{lid}">{_tile_media(lid, "tile")}</div>
          <div class="clickcatch"></div>
          <div class="picker-wrap"><span class="picker-lbl">Show:</span><select class="picker" data-slot="{lid}" data-dev="{dev['id']}" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()"></select></div>
        </div>"""
    return f"""
    <div class="spot" id="spot-{dev['id']}">
      <div class="big">
        <div class="cap" id="bigcap-{dev['id']}">{html.escape(lenses[0].get('name',''))}</div>
        <div class="bigmedia" id="bigmedia-{dev['id']}">{_tile_media(first, "main")}</div>
      </div>
      <div class="divider" data-dev="{dev['id']}" title="Drag to resize">⋮</div>
      <div class="thumbs">{thumbs}</div>
    </div>"""


def render_grid(dev):
    cells = ""
    for ln in dev["lenses"]:
        lid, lname = ln["id"], ln.get("name", ln["id"])
        cells += f"""
        <div class="cell" data-source="{lid}" data-slot="{lid}" data-dev="{dev['id']}">
          <div class="tilehead"><span class="tname">{html.escape(lname)}</span><span class="tmeta"></span></div>
          <div class="tmediadiv">{_tile_media(lid, "tile")}</div>
          <div class="picker-wrap"><span class="picker-lbl">Show:</span><select class="picker" data-slot="{lid}" data-dev="{dev['id']}" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()"></select></div>
        </div>"""
    return f'<div class="grid">{cells}</div>'


@app.route("/")
def index():
    tabs = ""
    panes = ""
    for i, dev in enumerate(DEVICES):
        active = " active" if i == 0 else ""
        tabs += f'<button class="tab{active}" data-dev="{dev["id"]}" onclick="showTab(\'{dev["id"]}\')">{html.escape(dev["name"])}</button>'
        body = render_spotlight(dev) if dev.get("layout") == "spotlight" else render_grid(dev)
        panes += f'<div class="device{active}" id="dev-{dev["id"]}">{body}</div>'
    head = PAGE_HEAD
    controls = ('<div class="right">'
                '<button class="sbtn" id="gear" onclick="toggleSettings()">&#9881;</button>'
                '<button class="sbtn" id="header-collapse" onclick="collapseHeader()">&#9662;</button>'
                '</div>')
    script = """
<script>
function showTab(dev){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.dev===dev));
  document.querySelectorAll('.device').forEach(d=>d.classList.toggle('active',d.id==='dev-'+dev));
}
// ---- server-side layout state ----
let LAYOUT={ui:{header_collapsed:false},devices:{}};
let SOURCES=[];
// Persisting is gated on a successful /api/layout load: an unloaded module default
// must never overwrite good disk state. Stays false until /api/layout resolves.
let LAYOUT_LOADED=false;
// HTML-encode any local-config value interpolated into innerHTML strings (mirrors
// plugins/calendar/view.html's esc): a stray quote in a name can't break markup.
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
async function loadState(){
  // Fetch sources and layout INDEPENDENTLY: a failed /api/sources must not wipe
  // LAYOUT (and vice-versa). Each settles into its own global only on success.
  await Promise.allSettled([
    fetch('/api/sources').then(r=>r.json()).then(d=>{SOURCES=d;})
      .catch(e=>console.error('sources load failed:',e)),
    fetch('/api/layout').then(r=>r.json()).then(d=>{LAYOUT=d;LAYOUT_LOADED=true;})
      .catch(e=>console.error('layout load failed:',e))
  ]);
  applyHeader(!!(LAYOUT.ui&&LAYOUT.ui.header_collapsed));
  applyAssignments();
  document.querySelectorAll('.device').forEach(d=>{
    const dev=d.id.replace('dev-','');
    if(d.querySelector('.spot')) initDivider(dev);
  });
}
function saveUI(ui){if(!LAYOUT_LOADED) return; LAYOUT.ui=Object.assign({},LAYOUT.ui,ui);
  fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(LAYOUT)});}
function saveLayout(){if(!LAYOUT_LOADED) return;
  fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(LAYOUT)});}
function toggleSettings(){document.body.classList.toggle('settings');
  if(!document.body.classList.contains('settings')) saveLayout();}
// ---- collapsible header ----
function applyHeader(c){document.body.classList.toggle('headerhidden',c);
  document.querySelector('header').classList.toggle('collapsed',c);}
function collapseHeader(){applyHeader(true);saveUI({header_collapsed:true});}
function showHeader(){applyHeader(false);saveUI({header_collapsed:false});}
// ---- media helper ----
function _mediaHTML(srcId,ctx){
  if(!srcId) return '';
  if(srcId.startsWith('plugin:')){
    const pid=srcId.split(':')[1];
    return '<iframe class="pluginframe" src="/plugin/'+esc(pid)+'/view?ctx='+ctx+'" frameborder="0" sandbox="allow-scripts allow-same-origin"></iframe>';
  }
  return '<img class="cam" data-id="'+esc(srcId)+'" src="/stream/'+esc(srcId)+'">';
}
// A source is "known" when it exists in SOURCES. When /api/sources failed to load
// (SOURCES empty) staleness is unknowable, so nothing is treated as removed.
function srcKnown(id){return !SOURCES.length||SOURCES.some(s=>s.id===id);}
// Resolve an assigned/override id against SOURCES: ids removed from config (stale
// on-disk state) fall back to the slot default so a tile never points at nothing.
function resolveSrc(id,def){return (id&&srcKnown(id))?id:def;}
// Only rewrite a media container when its desired content actually changed.
// Comparing against a stored intended-key (not el.innerHTML, which the browser
// re-serializes) avoids needlessly tearing down + restarting live MJPEG <img>
// streams (flicker) on every re-render.
function setMedia(el,html){
  if(!el) return;
  if(el.dataset.mkey!==html){ el.innerHTML=html; el.dataset.mkey=html; }
}
// Build the <select> options once per SOURCES set; only update the selection.
// Rebuilding options on every render would drop a user's open dropdown.
function fillPicker(picker,selVal,withNone){
  if(!picker||!SOURCES.length) return;
  // Fold withNone into the cached signature so the option list rebuilds when a tile
  // toggles between Show: and Filler: modes (else the (none) option goes missing/stale).
  const sig=(withNone?'none|':'')+SOURCES.map(s=>s.id).join(',');
  if(picker.dataset.sig!==sig){
    const opts=SOURCES.map(s=>'<option value="'+esc(s.id)+'">'+esc(s.name)+'</option>');
    if(withNone) opts.unshift('<option value="">(none — live in main)</option>');
    picker.innerHTML=opts.join('');
    picker.dataset.sig=sig;
  }
  if(picker.value!==(selVal||'')) picker.value=selVal||'';
}
// ---- tile assignments ----
function applyAssignments(){
  const mainLenses=[];
  document.querySelectorAll('.device').forEach(d=>{
    const dev=d.id.replace('dev-','');
    const devState=(LAYOUT.devices&&LAYOUT.devices[dev])||{};
    const tiles=devState.tiles||{};
    // stale on-disk filler (source removed from config) → no filler
    const filler=resolveSrc(devState.filler||null,null);
    const thumbEls=[...d.querySelectorAll('.tile[data-dev="'+dev+'"]')];
    // determine selected tile; a stale/removed selection falls back to the first thumb
    let selected=devState.selected||null;
    if(selected&&!srcKnown(selected)) selected=null;
    if(!selected&&thumbEls.length>0) selected=thumbEls[0].dataset.source;
    // spotlight: big pane + thumbnails
    if(thumbEls.length>0){
      const selThumb=thumbEls.find(t=>t.dataset.source===selected)||thumbEls[0];
      // pin selection to a real tile so EXACTLY ONE tile is ever active
      selected=selThumb.dataset.source;
      const selSrc=resolveSrc(tiles[selThumb.dataset.slot],selThumb.dataset.source);
      // tier by prefix (not SOURCES lookup): a failed /api/sources can't drop the big lens to sub
      if(selSrc&&!selSrc.startsWith('plugin:')) mainLenses.push(selSrc);
      setMedia(d.querySelector('#bigmedia-'+dev),_mediaHTML(selSrc,'main'));
      const bigcap=d.querySelector('#bigcap-'+dev);
      if(bigcap){
        // resolve un-suffixed name from SOURCES (never the active thumb's .tname,
        // which now carries the " · in main" decoration)
        const meta=SOURCES.find(s=>s.id===selSrc);
        const name=meta?meta.name:selSrc;
        if(bigcap.textContent!==name) bigcap.textContent=name;
      }
      thumbEls.forEach(th=>{
        const slot=th.dataset.slot;
        const defaultSrc=th.dataset.source;
        const assignedSrc=resolveSrc(tiles[slot],defaultSrc);
        const isActive=th.dataset.source===selected;
        // a filler equal to the big-pane source = no filler (don't duplicate main)
        const effFiller=(isActive&&filler&&filler!==selSrc)?filler:null;
        th.classList.toggle('active',isActive);
        const _sm=SOURCES.find(s=>s.id===assignedSrc);
        const _tn=th.querySelector('.tname');
        // LEFT: big-pane source name (+ "· in main" on the active tile)
        if(_tn){const nm=(_sm?_sm.name:assignedSrc)+(isActive?' · in main':''); if(_tn.textContent!==nm)_tn.textContent=nm;}
        // CENTER: "[preview: <filler>]" — muted; empty (→display:none) for non-active or no filler
        const _tp=th.querySelector('.tpreview');
        if(_tp){let pv=''; if(effFiller){const _fm=SOURCES.find(s=>s.id===effFiller); pv='[preview: '+(_fm?_fm.name:effFiller)+']';}
          if(_tp.textContent!==pv) _tp.textContent=pv;}
        // RIGHT (status source): active tile reflects the FILLER it actually shows; others their slot source
        th.dataset.src=isActive?(effFiller||''):assignedSrc;
        // tile media: active shows filler (or a content-aware placeholder); others show assigned source
        let html;
        if(isActive&&effFiller) html=_mediaHTML(effFiller,'filler');
        else if(isActive){const plg=selSrc&&selSrc.startsWith('plugin:');
          html='<div class="placeholder">&#9679; '+(plg?'in main':'Live in main view')+'</div>';}
        else html=_mediaHTML(assignedSrc,'tile');
        setMedia(th.querySelector('.tmediadiv'),html);
        // picker: active tile picker selects filler; others select slot source
        const pickerLbl=th.querySelector('.picker-lbl');
        if(pickerLbl) pickerLbl.textContent=isActive?'Filler:':'Show:';
        const picker=th.querySelector('.picker');
        if(picker){
          fillPicker(picker,isActive?(filler||''):assignedSrc,isActive);
          picker.onchange=isActive
            ?()=>{ LAYOUT.devices[dev]=LAYOUT.devices[dev]||{};
                   LAYOUT.devices[dev].filler=picker.value||null; applyAssignments(); saveLayout(); }
            :()=>{ LAYOUT.devices[dev]=LAYOUT.devices[dev]||{};
                   LAYOUT.devices[dev].tiles=LAYOUT.devices[dev].tiles||{};
                   LAYOUT.devices[dev].tiles[slot]=picker.value; applyAssignments(); saveLayout(); };
        }
      });
    }
    // grid: update cell media + pickers (no selected/big-pane logic)
    d.querySelectorAll('.cell[data-dev="'+dev+'"]').forEach(cell=>{
      const slot=cell.dataset.slot;
      const assignedSrc=resolveSrc(tiles[slot],cell.dataset.source);
      const _csm=SOURCES.find(s=>s.id===assignedSrc), _ctn=cell.querySelector('.tname');
      if(_ctn){const nm=_csm?_csm.name:assignedSrc; if(_ctn.textContent!==nm)_ctn.textContent=nm;}
      cell.dataset.src=assignedSrc;
      setMedia(cell.querySelector('.tmediadiv'),_mediaHTML(assignedSrc,'tile'));
      const picker=cell.querySelector('.picker');
      if(picker){
        fillPicker(picker,assignedSrc);
        picker.onchange=()=>{ LAYOUT.devices[dev]=LAYOUT.devices[dev]||{};
          LAYOUT.devices[dev].tiles=LAYOUT.devices[dev].tiles||{};
          LAYOUT.devices[dev].tiles[slot]=picker.value; applyAssignments(); saveLayout(); };
      }
    });
  });
  syncStreams(mainLenses);
}
function promote(dev,lid){
  if(document.body.classList.contains('settings')) return;
  if(LAYOUT.devices&&LAYOUT.devices[dev]&&LAYOUT.devices[dev].selected===lid) return;
  if(!LAYOUT.devices) LAYOUT.devices={};
  if(!LAYOUT.devices[dev]) LAYOUT.devices[dev]={};
  LAYOUT.devices[dev].selected=lid;
  saveLayout();
  applyAssignments();
}
function initDivider(dev){
  const sp=document.getElementById('spot-'+dev); if(!sp) return;
  const big=sp.querySelector('.big'); const div=sp.querySelector('.divider');
  // restore the split from server-side layout state (per device), not browser storage
  const saved=LAYOUT.devices&&LAYOUT.devices[dev]&&LAYOUT.devices[dev].split;
  if(saved) big.style.flexBasis=saved;
  let dragging=false;
  // Pointer events (mouse AND touch). setPointerCapture routes every subsequent
  // pointermove/up to the divider — even while the cursor is over the big-pane
  // iframe — so the iframe can no longer eat the drag (no drag-shield overlay needed).
  div.addEventListener('pointerdown',e=>{dragging=true;div.classList.add('drag');
    div.setPointerCapture(e.pointerId);document.body.style.userSelect='none';e.preventDefault();});
  div.addEventListener('pointermove',e=>{
    if(!dragging)return; const r=sp.getBoundingClientRect();
    // width-aware ceiling: keep the thumbnail column (150px min) + divider box (26px:
    // 16 flex-basis + 2×5 margin) on-screen so its status dots/res/fps are never clipped
    const maxPct=(r.width-150-26)/r.width*100;
    let pct=(e.clientX-r.left)/r.width*100; pct=Math.max(25,Math.min(Math.min(85,maxPct),pct));
    big.style.flexBasis=pct.toFixed(1)+'%';
  });
  div.addEventListener('pointerup',e=>{
    if(!dragging)return; dragging=false; div.classList.remove('drag'); document.body.style.userSelect='';
    try{ div.releasePointerCapture(e.pointerId); }catch(_){}
    LAYOUT.devices[dev]=LAYOUT.devices[dev]||{};
    LAYOUT.devices[dev].split=big.style.flexBasis; saveLayout();
  });
}
function syncStreams(main){
  fetch('/api/streams',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({main})});
}
async function poll(){
  try{
    const s=await (await fetch('/status')).json();
    const statusMap={};
    for(const c of s) statusMap[c.id]=c;
    document.querySelectorAll('.tile,.cell').forEach(el=>{
      // active tile included: its .tmeta (right zone) shows the FILLER's status via dataset.src
      const src=el.dataset.src;
      const m=el.querySelector('.tmeta');
      if(!m) return;
      if(!src||src.startsWith('plugin:')){m.innerHTML='';return;}
      const c=statusMap[src];
      if(!c){m.innerHTML='<span class="dot off"></span>';return;}
      const on=c.status.startsWith('online');
      m.innerHTML='<span class="dot '+(on?'on':(c.status==='connecting'?'wait':'off'))+'"></span>'+
                  (on?c.resolution+' '+c.fps+'f':'');
    });
  }catch(e){}
}
setInterval(poll,1500); poll();
loadState();
</script></body></html>"""
    return (head
            + '<header><div style="font-weight:700;margin-right:8px">&#128247; dvri-peek</div>'
            + tabs + controls + '</header>'
            + '<div id="revealbar" onclick="showHeader()" title="Show menu"></div>'
            + panes + script)


@app.route("/stream/<lens_id>")
def stream(lens_id):
    w = WORKERS.get(lens_id)
    if not w:
        return "no such lens", 404

    def gen():
        period = 1.0 / max(CFG["player"].get("target_fps", 15), 1)
        while True:
            jpg = w.get_jpeg()
            if jpg:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            time.sleep(period)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/snapshot/<lens_id>")
def snapshot(lens_id):
    w = WORKERS.get(lens_id)
    if not w:
        return "no such lens", 404
    jpg = w.get_jpeg()
    return Response(jpg, mimetype="image/jpeg") if jpg else ("no frame", 503)


@app.route("/status")
def status():
    return jsonify([{"id": w.id, "name": w.name, "status": w.status,
                     "resolution": w.resolution, "fps": w.fps, "stream": w.stream_mode}
                    for w in WORKERS.values()])


@app.route("/api/streams", methods=["POST"])
def api_streams():
    data = request.get_json(force=True, silent=True) or {}
    main_set = set(data.get("main", []))
    for w in WORKERS.values():
        w.set_stream("main" if w.id in main_set else "sub")
    return jsonify({"ok": True})


def bootstrap(config_path=None, stream_mode=None, start_workers=True, start_gateway=True,
              plugins_dir=None, state_path=None, secrets_path=None):
    global CFG, DEVICES, REGISTRY, STORE
    here = os.path.dirname(os.path.abspath(__file__))
    config_path = config_path or os.path.join(here, "cameras.yaml")
    CFG = load_config(config_path)
    DEVICES = CFG["devices"]
    pl = CFG.get("player", {})
    mode = stream_mode or pl.get("default_stream", "sub")

    secrets = load_secrets(secrets_path or os.path.join(here, "secrets.local.yaml"))
    REGISTRY = plugins_mod.PluginRegistry(plugins_dir or os.path.join(here, "plugins"), secrets=secrets)
    REGISTRY.discover()
    STORE = layout_mod.LayoutStore(state_path or os.path.join(here, "state.local.json"))

    if "plugins" not in app.blueprints:
        app.register_blueprint(plugins_mod.create_plugins_blueprint(REGISTRY))
    if "layout" not in app.blueprints:
        app.register_blueprint(layout_mod.create_layout_blueprint(CFG, REGISTRY, STORE))

    if start_gateway:
        g2_path = os.path.join(here, "go2rtc.generated.yaml")
        lens_index = build_go2rtc_config(CFG, g2_path)
        start_go2rtc(CFG, g2_path)
    else:
        lens_index = {ln["id"]: {"name": ln.get("name", ln["id"])}
                      for dev in DEVICES for ln in dev["lenses"]}
    if start_workers:
        gw = CFG.get("gateway", {})
        for lid, meta in lens_index.items():
            w = LensWorker(lid, meta["name"], gw, pl.get("jpeg_quality", 75),
                           pl.get("target_fps", 15), mode)
            WORKERS[lid] = w
            w.start()
    return mode


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--config", default=os.path.join(here, "cameras.yaml"))
    ap.add_argument("--stream", choices=["sub", "main"], default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()
    mode = bootstrap(config_path=args.config, stream_mode=args.stream)
    port = args.port or CFG.get("player", {}).get("http_port", 8090)
    print(f"Player: http://localhost:{port}   (stream={mode})")
    try:
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
    finally:
        for w in WORKERS.values():
            w.stop()
        stop_go2rtc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_go2rtc()
