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


def load_secrets(path="secrets.local.yaml"):
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
 .sbtn.active{background:#374151;border-color:#4b5563;color:#fff}
 .device{display:none;padding:10px;flex:1 1 auto;min-height:0}
 .device.active{display:flex;flex-direction:column;min-height:0}
 /* spotlight */
 .spot{display:flex;gap:0;align-items:stretch;flex:1 1 auto;min-height:0}
 .big{flex:0 0 66%;min-width:160px;display:flex;flex-direction:column;background:#000;border:1px solid var(--line);border-radius:10px;overflow:hidden}
 .big .cap{flex:0 0 auto;padding:6px 12px;font-size:13px;font-weight:600;background:#141417}
 .big img{flex:1 1 auto;min-height:0;width:100%;height:100%;object-fit:contain;background:#000;display:block}
 .divider{flex:0 0 16px;margin:0 5px;cursor:col-resize;border-radius:7px;background:#3a3a42;
          display:flex;align-items:center;justify-content:center;user-select:none;color:#cbd5e1;font-size:18px;line-height:1}
 .divider:hover,.divider.drag{background:var(--accent);color:#fff}
 .thumbs{flex:1 1 0;min-width:150px;display:flex;flex-direction:column;gap:8px}
 .thumb{flex:1 1 0;min-height:0;position:relative;background:#000;border:2px solid var(--line);border-radius:9px;
        overflow:hidden;cursor:pointer}
 .thumb.active{border-color:var(--accent);cursor:default}
 .thumb img{width:100%;height:100%;object-fit:contain;background:#000;display:block}
 .thumb .lbl{position:absolute;top:0;left:0;right:0;padding:4px 8px;font-size:12px;font-weight:600;
             background:linear-gradient(#000b,#0000);display:flex;justify-content:space-between;z-index:2}
 .thumb .placeholder{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
             color:#9ca3af;font-size:13px;text-align:center;padding:10px}
 .dot{width:8px;height:8px;border-radius:50%;background:#888;display:inline-block;margin-right:5px}
 .on{background:#22c55e}.off{background:#ef4444}.wait{background:#eab308}
 /* grid */
 .grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));flex:1 1 auto;min-height:0;overflow:auto;align-content:start}
 .cell{background:#000;border:1px solid var(--line);border-radius:9px;overflow:hidden;position:relative;aspect-ratio:16/9}
 .cell img{width:100%;display:block;aspect-ratio:16/9;object-fit:contain;background:#000}
 .cell .lbl{position:absolute;top:0;left:0;right:0;padding:4px 8px;font-size:12px;font-weight:600;background:linear-gradient(#000b,#0000)}
 /* collapsible header */
 header.collapsed{display:none}
 #revealbar{position:fixed;top:0;left:0;right:0;height:6px;background:#2563eb55;cursor:pointer;z-index:20;display:none}
 body.headerhidden #revealbar{display:block}
 /* settings mode */
 .thumb .picker,.cell .picker{position:absolute;inset:auto 6px 6px 6px;z-index:5;display:none}
 body.settings .thumb .picker,body.settings .cell .picker{display:block}
 .titleoverlay{position:absolute;top:0;left:0;right:0;padding:4px 8px;font-size:12px;
   font-weight:600;background:linear-gradient(#000b,#0000);z-index:3;pointer-events:none}
 .pluginframe{width:100%;height:100%;border:0;background:#000;display:block}
 .thumb.active{outline:2px solid var(--accent);outline-offset:-2px}
 /* big pane media container */
 .bigmedia{flex:1 1 auto;min-height:0;overflow:hidden;background:#000}
 .bigmedia img{width:100%;height:100%;object-fit:contain;display:block}
 .bigmedia iframe{width:100%;height:100%;border:0;display:block}
 /* tile media container */
 .tmediadiv{position:absolute;inset:0;overflow:hidden}
 .tmediadiv img{width:100%;height:100%;object-fit:contain;background:#000;display:block}
 .tmediadiv iframe{width:100%;height:100%;background:#000;border:0;display:block}
</style></head><body>
"""


def _tile_media(source_id, ctx):
    """Return inner media HTML for a source in a given context (tile/main/filler)."""
    if source_id and source_id.startswith("plugin:"):
        pid = source_id.split(":", 1)[1]
        return (f'<iframe class="pluginframe" src="/plugin/{pid}/view?ctx={ctx}"'
                f' frameborder="0"></iframe>')
    return f'<img class="cam" data-id="{source_id}" src="/stream/{source_id}">'


def render_spotlight(dev):
    lenses = dev["lenses"]
    first = lenses[0]["id"]
    thumbs = ""
    for ln in lenses:
        lid, lname = ln["id"], ln.get("name", ln["id"])
        thumbs += f"""
        <div class="thumb" id="th-{lid}" data-lens="{lid}" data-slot="{lid}" data-source="{lid}" data-dev="{dev['id']}" onclick="promote('{dev['id']}','{lid}')">
          <div class="lbl"><span class="tname">{lname}</span><span id="meta-{lid}"><span class="dot wait"></span></span></div>
          <div class="titleoverlay"></div>
          <div class="tmediadiv" id="tmedia-{lid}">{_tile_media(lid, "tile")}</div>
          <select class="picker" data-slot="{lid}" data-dev="{dev['id']}"></select>
        </div>"""
    return f"""
    <div class="spot" id="spot-{dev['id']}">
      <div class="big">
        <div class="cap" id="bigcap-{dev['id']}">{lenses[0].get('name','')}</div>
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
          <div class="lbl"><span>{lname}</span> <span id="meta-{lid}"><span class="dot wait"></span></span></div>
          <div class="tmediadiv">{_tile_media(lid, "tile")}</div>
          <select class="picker" data-slot="{lid}" data-dev="{dev['id']}"></select>
        </div>"""
    return f'<div class="grid">{cells}</div>'


@app.route("/")
def index():
    tabs = ""
    panes = ""
    for i, dev in enumerate(DEVICES):
        active = " active" if i == 0 else ""
        tabs += f'<button class="tab{active}" data-dev="{dev["id"]}" onclick="showTab(\'{dev["id"]}\')">{dev["name"]}</button>'
        body = render_spotlight(dev) if dev.get("layout") == "spotlight" else render_grid(dev)
        panes += f'<div class="device{active}" id="dev-{dev["id"]}">{body}</div>'
    mode = next(iter(WORKERS.values())).stream_mode if WORKERS else "sub"
    head = PAGE_HEAD
    controls = (f'<div class="right">'
                f'<button class="sbtn{" active" if mode=="main" else ""}" id="b-main" onclick="setStream(\'main\')">Main HD</button>'
                f'<button class="sbtn{" active" if mode=="sub" else ""}" id="b-sub" onclick="setStream(\'sub\')">Sub</button>'
                f'<button class="sbtn" id="gear" onclick="toggleSettings()">&#9881;</button>'
                f'<button class="sbtn" id="header-collapse" onclick="collapseHeader()">&#9662;</button>'
                f'</div>')
    script = """
<script>
function showTab(dev){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.dev===dev));
  document.querySelectorAll('.device').forEach(d=>d.classList.toggle('active',d.id==='dev-'+dev));
}
// ---- server-side layout state ----
let LAYOUT={ui:{header_collapsed:false},devices:{}};
let SOURCES=[];
async function loadState(){
  try{
    [SOURCES,LAYOUT]=await Promise.all([
      fetch('/api/sources').then(r=>r.json()),
      fetch('/api/layout').then(r=>r.json())
    ]);
  }catch(e){ console.error('loadState failed:',e); SOURCES=SOURCES||[]; }
  applyHeader(!!(LAYOUT.ui&&LAYOUT.ui.header_collapsed));
  applyAssignments();
  document.querySelectorAll('.device').forEach(d=>{
    const dev=d.id.replace('dev-','');
    if(d.querySelector('.spot')) initDivider(dev);
  });
}
function saveUI(ui){LAYOUT.ui=Object.assign({},LAYOUT.ui,ui);
  fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(LAYOUT)});}
function saveLayout(){fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(LAYOUT)});}
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
    return '<iframe class="pluginframe" src="/plugin/'+pid+'/view?ctx='+ctx+'" frameborder="0"></iframe>';
  }
  return '<img class="cam" data-id="'+srcId+'" src="/stream/'+srcId+'">';
}
// ---- tile assignments ----
function applyAssignments(){
  document.querySelectorAll('.device').forEach(d=>{
    const dev=d.id.replace('dev-','');
    const devState=(LAYOUT.devices&&LAYOUT.devices[dev])||{};
    const tiles=devState.tiles||{};
    const filler=devState.filler||null;
    const thumbEls=[...d.querySelectorAll('.thumb[data-dev="'+dev+'"]')];
    // determine selected source (falls back to first thumb's default)
    let selected=devState.selected||null;
    if(!selected&&thumbEls.length>0) selected=thumbEls[0].dataset.source;
    // spotlight: big pane + thumbnails
    if(thumbEls.length>0){
      const selThumb=thumbEls.find(t=>t.dataset.source===selected)||thumbEls[0];
      if(selThumb){
        const selSrc=tiles[selThumb.dataset.slot]||selThumb.dataset.source;
        const bigmedia=d.querySelector('#bigmedia-'+dev);
        if(bigmedia) bigmedia.innerHTML=_mediaHTML(selSrc,'main');
        const bigcap=d.querySelector('#bigcap-'+dev);
        if(bigcap){
          const meta=SOURCES.find(s=>s.id===selSrc);
          bigcap.textContent=meta?meta.name:((selThumb.querySelector('.tname')||{}).textContent||'');
        }
      }
      thumbEls.forEach(th=>{
        const slot=th.dataset.slot;
        const defaultSrc=th.dataset.source;
        const assignedSrc=tiles[slot]||defaultSrc;
        const isActive=th.dataset.source===selected;
        th.classList.toggle('active',isActive);
        // tile media: active shows filler (or placeholder); others show assigned source
        const mediaDiv=th.querySelector('.tmediadiv');
        if(mediaDiv){
          if(isActive&&filler) mediaDiv.innerHTML=_mediaHTML(filler,'filler');
          else if(isActive) mediaDiv.innerHTML='<div class="placeholder">&#9679; Live in main view</div>';
          else mediaDiv.innerHTML=_mediaHTML(assignedSrc,'tile');
        }
        // title overlay: shown on active tile to label the slot
        const overlay=th.querySelector('.titleoverlay');
        if(overlay) overlay.textContent=isActive?((th.querySelector('.tname')||{}).textContent||''):'';
        // populate picker: active tile picker selects filler; others select slot source
        const picker=th.querySelector('.picker');
        if(picker&&SOURCES.length>0){
          const pickerVal=isActive?(filler||''):assignedSrc;
          picker.innerHTML=SOURCES.map(s=>'<option value="'+s.id+'"'+(s.id===pickerVal?' selected':'')+'>'+s.name+'</option>').join('');
          if(isActive){
            picker.onchange=()=>{
              if(!LAYOUT.devices[dev]) LAYOUT.devices[dev]={};
              LAYOUT.devices[dev].filler=picker.value;
              applyAssignments();
            };
          } else {
            picker.onchange=()=>{
              if(!LAYOUT.devices[dev]) LAYOUT.devices[dev]={};
              if(!LAYOUT.devices[dev].tiles) LAYOUT.devices[dev].tiles={};
              LAYOUT.devices[dev].tiles[slot]=picker.value;
              applyAssignments();
            };
          }
        }
      });
    }
    // grid: update cell media + pickers (no selected/big-pane logic)
    d.querySelectorAll('.cell[data-dev="'+dev+'"]').forEach(cell=>{
      const slot=cell.dataset.slot;
      const assignedSrc=tiles[slot]||cell.dataset.source;
      const mediaDiv=cell.querySelector('.tmediadiv');
      if(mediaDiv) mediaDiv.innerHTML=_mediaHTML(assignedSrc,'tile');
      const picker=cell.querySelector('.picker');
      if(picker&&SOURCES.length>0){
        picker.innerHTML=SOURCES.map(s=>'<option value="'+s.id+'"'+(s.id===assignedSrc?' selected':'')+'>'+s.name+'</option>').join('');
        picker.onchange=()=>{
          if(!LAYOUT.devices[dev]) LAYOUT.devices[dev]={};
          if(!LAYOUT.devices[dev].tiles) LAYOUT.devices[dev].tiles={};
          LAYOUT.devices[dev].tiles[slot]=picker.value;
          applyAssignments();
        };
      }
    });
  });
}
function promote(dev,lid){
  if(!LAYOUT.devices) LAYOUT.devices={};
  if(!LAYOUT.devices[dev]) LAYOUT.devices[dev]={};
  LAYOUT.devices[dev].selected=lid;
  saveLayout();
  applyAssignments();
}
function initDivider(dev){
  const sp=document.getElementById('spot-'+dev); if(!sp) return;
  const big=sp.querySelector('.big'); const div=sp.querySelector('.divider');
  const saved=localStorage.getItem('split-'+dev); if(saved) big.style.flexBasis=saved;
  let dragging=false;
  div.addEventListener('mousedown',e=>{dragging=true;div.classList.add('drag');document.body.style.userSelect='none';e.preventDefault();});
  window.addEventListener('mousemove',e=>{
    if(!dragging)return; const r=sp.getBoundingClientRect();
    let pct=(e.clientX-r.left)/r.width*100; pct=Math.max(25,Math.min(85,pct));
    big.style.flexBasis=pct.toFixed(1)+'%';
  });
  window.addEventListener('mouseup',()=>{
    if(!dragging)return; dragging=false; div.classList.remove('drag'); document.body.style.userSelect='';
    try{ localStorage.setItem('split-'+dev, big.style.flexBasis); }catch(e){}
  });
}
function setStream(m){
  fetch('/set_stream?mode='+m).then(()=>{
    document.getElementById('b-sub').classList.toggle('active',m==='sub');
    document.getElementById('b-main').classList.toggle('active',m==='main');
    document.querySelectorAll('img.cam').forEach(i=>{ if(i.src && !i.src.endsWith('/')) i.src=i.src.split('?')[0]+'?t='+Date.now(); });
  });
}
async function poll(){
  try{const s=await (await fetch('/status')).json();
    for(const c of s){ const m=document.getElementById('meta-'+c.id); if(!m)continue;
      const on=c.status.startsWith('online');
      m.innerHTML='<span class="dot '+(on?'on':(c.status==='connecting'?'wait':'off'))+'"></span>'+
                  (on? c.resolution+' '+c.fps+'f':'');
    }
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


@app.route("/set_stream")
def set_stream():
    mode = request.args.get("mode", "sub")
    for w in WORKERS.values():
        w.set_stream(mode)
    return jsonify({"ok": True, "mode": mode})


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
