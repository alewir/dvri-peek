import importlib.util
import threading
import time
from pathlib import Path

import yaml
from flask import Blueprint, Response, jsonify, send_from_directory

class Plugin:
    def __init__(self, pid, path, manifest, backend):
        self.id = pid
        self.path = Path(path)
        self.manifest = manifest or {}
        self.backend = backend
        self.name = self.manifest.get("name", pid)
        self.contexts = list(self.manifest.get("contexts", ["tile"]))
        try:
            self.refresh = int(self.manifest.get("refresh_seconds", 0) or 0)
        except (TypeError, ValueError):
            self.refresh = 0

class PluginRegistry:
    def __init__(self, plugins_dir, secrets=None):
        self.dir = Path(plugins_dir)
        self.secrets = secrets or {}
        self.plugins = {}
        self._cache = {}            # pid -> (ts, data)
        self._lock = threading.Lock()

    def discover(self):
        self.plugins = {}
        if not self.dir.is_dir():
            return self.plugins
        for child in sorted(self.dir.iterdir()):
            mf = child / "manifest.yaml"
            if not child.is_dir() or not mf.is_file():
                continue
            try:
                manifest = yaml.safe_load(mf.read_text()) or {}
                if not isinstance(manifest, dict):
                    raise ValueError("manifest is not a mapping")
                pid = manifest.get("id") or child.name
                backend = self._load_backend(child)
                self.plugins[pid] = Plugin(pid, child, manifest, backend)
            except Exception as e:                       # noqa: BLE001 - skip bad plugin
                print(f"[plugins] skipping {child.name}: {e}")
        return self.plugins

    def _load_backend(self, child):
        bp = child / "backend.py"
        if not bp.is_file():
            return None
        spec = importlib.util.spec_from_file_location(f"dvripeek_plugin_{child.name}", bp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod if hasattr(mod, "fetch") else None

    def list(self):
        return list(self.plugins.values())

    def get(self, pid):
        return self.plugins.get(pid)

    def data(self, pid):
        p = self.get(pid)
        if not p:
            return {"error": "unknown plugin"}
        if not p.backend:
            return {"error": "no backend"}
        cfg = (self.secrets.get("plugins", {}) or {}).get(pid, {}) or {}
        # Single lock scope over check + fetch + store: concurrent requests for
        # the same backend plugin serialize (suppressing a fetch stampede); a
        # no-backend plugin returned above and never reaches the lock.
        with self._lock:
            now = time.time()
            cached = self._cache.get(pid)
            if cached and p.refresh and (now - cached[0]) < p.refresh:
                return cached[1]
            try:
                result = p.backend.fetch(cfg)
                if not isinstance(result, dict):
                    result = {"error": "backend did not return a dict"}
            except Exception as e:                       # noqa: BLE001
                result = {"error": str(e)}
            if p.refresh:                                # only cache when a TTL applies
                self._cache[pid] = (now, result)
            return result

def create_plugins_blueprint(registry):
    bp = Blueprint("plugins", __name__)

    @bp.route("/plugin/<pid>/view")
    def view(pid):
        p = registry.get(pid)
        if not p:
            return ("no such plugin", 404)
        if not (p.path / "view.html").is_file():
            return ("plugin has no view", 404)
        return Response((p.path / "view.html").read_text(), mimetype="text/html")

    @bp.route("/plugin/<pid>/data")
    def data(pid):
        return jsonify(registry.data(pid))

    @bp.route("/plugin/<pid>/static/<path:fn>")
    def static_(pid, fn):
        p = registry.get(pid)
        if not p:
            return ("no such plugin", 404)
        return send_from_directory(str(p.path / "static"), fn)

    return bp
